"""진짜 자기대국(RL) 데이터 생성 — ISMCTS 탐색 자신이 자신과 대국한다
(260803_RL_plan.md).

`scripts/generate_policy_data.py`/`generate_selfplay_data.py`(모방학습,
HeuristicAI가 자기대국을 둠)와 다른 점은 딱 하나: 자기대국을 두는 주체가
`HeuristicAI`가 아니라 **지금 세대의 정책+값망을 장착한 `ISMCTSAI`
자신**이다. 매 action 결정마다:

1. `ISMCTSAI.decide_with_stats()`로 탐색이 만든 방문분포(N(a)/ΣN)를 얻어
   정책 학습 라벨로 기록(하드 라벨 "무엇을 골랐나"가 아니라 소프트 분포
   "탐색이 각 후보를 얼마나 신뢰했나").
2. 실제로 둘 액션은 그 분포에서 **온도 샘플링**한다(게임 초반
   `--temp-moves`수만큼은 온도 1.0로 다양성을 살리고, 그 뒤는 사실상
   argmax) -- AlphaZero 관례.
3. 탐색 자체에는 **루트 디리클레 노이즈**(`--dirichlet-alpha/-eps`)를
   섞어서, 매번 정책이 가장 선호하는 수순으로만 수렴해 다양성을 잃는
   걸 막는다(경쟁 플레이의 `decide()`는 이 노이즈를 절대 안 씀).
4. 판이 끝나면 승패로 상태별 값 라벨도 기록(`generate_selfplay_data.py`
   와 동일한 라벨링 원리).

출력은 두 개 `.npz`: `<out_prefix>_value.npz`(`X`/`y` -- `scripts/
train_eval_mlp.py`가 그대로 읽을 수 있는 기존 스키마)와
`<out_prefix>_policy.npz`(`Xs`/`Xa`/`y`/`group` -- `scripts/
generate_policy_data.py`와 같은 스키마, 다만 `y`는 0/1 하드 라벨이 아니라
방문 비율 소프트 라벨).

병렬화(260803_병렬화_plan.md): `scripts/parallel_utils.run_parallel()`을
그대로 재사용한다 -- `scripts/arena.py`와 동일한 설계(작업 목록을 먼저
순차로 뽑아두고, 워커 프로세스마다 무거운 가중치를 initializer로 한 번만
전달).

사용법:
    python3 scripts/generate_rl_selfplay_data.py <판수> <출력파일_접두사> \
        --eval-weights <값망.npz> --policy-weights <정책망.npz> \
        [--iterations 50] [--rearrange-iterations N] [--dirichlet-alpha 0.3] \
        [--dirichlet-eps 0.25] [--temp-moves 10] [--seed-base 0] [--n-workers auto]
"""

import random
import sys
import time

sys.path.insert(0, ".")

import numpy as np

from src.game.engine import Engine
from src.game.ai_ismcts import ISMCTSAI
from src.game.ai_ismcts_policy import load_policy_weights
from src.game.ai_sim import evaluate_learned_mlp, load_mlp_weights
from src.game.ai_features import extract as extract_state, feature_count as state_feature_count
from src.game.ai_action_features import extract as extract_action, feature_count as action_feature_count
from src.game.ai_prior import score_action
from src.game import protocols as P
from scripts.parallel_utils import limit_blas_threads, run_parallel

MAX_STEPS = 20000
GROUP_OFFSET_PER_GAME = 100000  # 게임 하나가 이 수만큼의 결정을 넘길 일은 없음 -- 워커 간 group id 충돌 방지


def _sample_from_visits(visits, temperature):
    """visits: [(action, count), ...]. temperature<=0이면 최다방문(argmax),
    아니면 N(a)^(1/T)에 비례해서 샘플링한다(AlphaZero 관례)."""
    if temperature <= 0:
        return max(visits, key=lambda v: v[1])[0]
    weights = [count ** (1.0 / temperature) for _, count in visits]
    total = sum(weights)
    r = random.random() * total
    upto = 0.0
    for (action, _), w in zip(visits, weights):
        upto += w
        if upto >= r:
            return action
    return visits[-1][0]  # 부동소수점 오차 안전망


class RLRecordingAI:
    """ISMCTSAI(inner)를 감싸서, 매 action 결정마다 decide_with_stats()로
    방문분포를 얻어 정책 데이터로 기록하고, 실제 게임 진행에 쓸 액션은
    그 분포에서 온도 샘플링한다(반환값이 실제 수가 됨). 값 데이터(상태
    특징 + 최종 승패)도 같은 김에 기록한다."""

    def __init__(self, inner, temp_moves=10, group_start=0):
        self.inner = inner
        self.temp_moves = temp_moves
        self.policy_rows = []  # [(state_feat, action_feat, visit_share, group_id), ...]
        self.value_snapshots = []  # [(pi, state_feat), ...] -- 판이 끝난 뒤 승패로 라벨링
        self._gid = group_start
        self._move_count = 0

    def decide(self, g, req):
        if req.get("type") == "action":
            pi = req["chooser"]
            best, visits = self.inner.decide_with_stats(g, req)
            sf = extract_state(g, pi)
            self.value_snapshots.append((pi, sf))
            if len(visits) > 1:
                gid = self._gid
                self._gid += 1
                total = sum(v for _, v in visits)
                for action, v in visits:
                    hs = score_action(g, pi, action)
                    af = extract_action(g, pi, action, hs)
                    self.policy_rows.append((sf, af, v / total, gid))
                temperature = 1.0 if self._move_count < self.temp_moves else 0.0
                self._move_count += 1
                return _sample_from_visits(visits, temperature)
            self._move_count += 1
            return best
        return self.inner.decide(g, req)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def play_one_game(seed, protos1, protos2, group_start, ai_kwargs, temp_moves,
                   eval_w, policy_w):
    random.seed(seed)

    def make_inner():
        return ISMCTSAI(eval_fn=evaluate_learned_mlp, eval_w=eval_w,
                         policy_w=policy_w, **ai_kwargs)

    ai1 = RLRecordingAI(make_inner(), temp_moves=temp_moves, group_start=group_start)
    ai2 = RLRecordingAI(make_inner(), temp_moves=temp_moves, group_start=group_start + GROUP_OFFSET_PER_GAME)

    e = Engine(protocols1=protos1, protocols2=protos2, ai1=True, ai2=True,
               ai_modules={1: ai1, 2: ai2}, seed=seed)
    e.start()
    steps = 0
    while e.pending is not None and steps < MAX_STEPS:
        steps += 1
        if e.pending["kind"] == "anim":
            e.advance_anim()
        else:
            e.answer(None)

    winner = e.winner
    policy_rows = list(ai1.policy_rows) + list(ai2.policy_rows)
    value_rows = []
    if winner is not None:
        for ai in (ai1, ai2):
            for pi, sf in ai.value_snapshots:
                value_rows.append((sf, 1.0 if winner == pi else 0.0))
    return policy_rows, value_rows


# --- 병렬 실행용 워커 (scripts/arena.py와 동일한 패턴, parallel_utils 재사용) ---

_worker_eval_w = None
_worker_policy_w = None
_worker_ai_kwargs = None
_worker_temp_moves = None


def _pool_init(eval_w, policy_w, ai_kwargs, temp_moves):
    limit_blas_threads()
    global _worker_eval_w, _worker_policy_w, _worker_ai_kwargs, _worker_temp_moves
    _worker_eval_w, _worker_policy_w = eval_w, policy_w
    _worker_ai_kwargs, _worker_temp_moves = ai_kwargs, temp_moves


def _play_game_worker(item):
    protos1, protos2, seed, group_start = item
    return play_one_game(seed, protos1, protos2, group_start,
                          _worker_ai_kwargs, _worker_temp_moves,
                          _worker_eval_w, _worker_policy_w)


def generate(n_games, out_prefix, eval_weights_path, policy_weights_path,
             iterations=50, rearrange_iterations=None, dirichlet_alpha=0.3, dirichlet_eps=0.25,
             temp_moves=10, seed_base=0, n_workers=1,
             c_ucb=1.41, rollout_turn_cap=2, eval_scale=3.1):
    eval_w = load_mlp_weights(eval_weights_path)
    policy_w = load_policy_weights(policy_weights_path)
    ai_kwargs = dict(iterations=iterations, rearrange_iterations=rearrange_iterations,
                      c_ucb=c_ucb, rollout_turn_cap=rollout_turn_cap,
                      eval_scale=eval_scale,
                      root_dirichlet_alpha=dirichlet_alpha, root_dirichlet_eps=dirichlet_eps)

    rnd = random.Random(seed_base)
    work_items = []
    for i in range(n_games):
        pool = list(P.PROTOCOL_LIST)
        rnd.shuffle(pool)
        p1, p2 = pool[:3], pool[3:6]
        work_items.append((p1, p2, seed_base + i, i * GROUP_OFFSET_PER_GAME * 2))

    Xs_p, Xa_p, y_p, group_p = [], [], [], []
    Xs_v, y_v = [], []
    completed = 0
    t0 = time.time()

    def _on_result(r):
        nonlocal completed
        policy_rows, value_rows = r
        for sf, af, share, gid in policy_rows:
            Xs_p.append(sf)
            Xa_p.append(af)
            y_p.append(share)
            group_p.append(gid)
        for sf, y in value_rows:
            Xs_v.append(sf)
            y_v.append(y)
        completed += 1
        if completed % max(1, n_games // 10) == 0:
            print(f"  {completed}/{n_games}판 진행 ({time.time() - t0:.1f}초)")

    run_parallel(work_items, _play_game_worker, init_fn=_pool_init,
                 init_args=(eval_w, policy_w, ai_kwargs, temp_moves),
                 n_workers=n_workers, on_result=_on_result)

    Xs_p = np.asarray(Xs_p, dtype=np.float32)
    Xa_p = np.asarray(Xa_p, dtype=np.float32)
    y_p = np.asarray(y_p, dtype=np.float32)
    group_p = np.asarray(group_p, dtype=np.int64)
    Xs_v = np.asarray(Xs_v, dtype=np.float32)
    y_v = np.asarray(y_v, dtype=np.float32)
    assert Xs_p.shape[1] == state_feature_count()
    assert Xa_p.shape[1] == action_feature_count()

    np.savez(f"{out_prefix}_policy.npz", Xs=Xs_p, Xa=Xa_p, y=y_p, group=group_p)
    np.savez(f"{out_prefix}_value.npz", X=Xs_v, y=y_v)

    el = time.time() - t0
    n_decisions = len(set(group_p.tolist()))
    print()
    print(f"완료: {n_games}판 ({el:.1f}초)")
    print(f"정책: 결정 {n_decisions}개, 후보 행 {len(Xs_p)}개")
    print(f"값: 상태 스냅샷 {len(Xs_v)}개 (무승부/미완료 판은 제외)")
    print(f"저장: {out_prefix}_policy.npz / {out_prefix}_value.npz")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    n_games = int(sys.argv[1])
    out_prefix = sys.argv[2]

    def _arg(flag, default, cast=str):
        return cast(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default

    eval_weights_path = _arg("--eval-weights", "src/game/data/eval_weights_mlp.npz")
    policy_weights_path = _arg("--policy-weights", "src/game/data/policy_weights.npz")
    iterations = _arg("--iterations", 50, int)
    rearrange_iterations = _arg("--rearrange-iterations", None, int)
    dirichlet_alpha = _arg("--dirichlet-alpha", 0.3, float)
    dirichlet_eps = _arg("--dirichlet-eps", 0.25, float)
    temp_moves = _arg("--temp-moves", 10, int)
    seed_base = _arg("--seed-base", 0, int)
    n_workers_raw = _arg("--n-workers", "1")
    n_workers = n_workers_raw if n_workers_raw == "auto" else int(n_workers_raw)

    generate(n_games, out_prefix, eval_weights_path, policy_weights_path,
             iterations=iterations, rearrange_iterations=rearrange_iterations,
             dirichlet_alpha=dirichlet_alpha,
             dirichlet_eps=dirichlet_eps, temp_moves=temp_moves,
             seed_base=seed_base, n_workers=n_workers)
