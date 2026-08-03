"""자기대국으로 "루트 정책"(학습된 정책) 학습 데이터를 생성한다.

scripts/generate_selfplay_data.py(평가함수용, 승패 라벨)와 달리 이 스크립트는
액션 선택 라벨을 만든다: 매 'action' 결정마다 (1) 상태 특징(ai_features),
(2) 그 순간 legal_actions()의 각 후보에 대한 액션 특징(ai_action_features),
(3) 그중 실제로 내부 정책(HeuristicAI, 0~1단계로 카드 프라이싱이 다듬어진
상태)이 고른 후보가 어느 것인지를 기록한다. 후보가 하나뿐인 결정(선택의
여지가 없음)은 학습 신호가 없으므로 버린다.

승부 결과를 기다릴 필요가 없다(라벨이 "누가 이겼나"가 아니라 "그 순간
무엇을 선택했나"이므로) -- 그래서 무승부/미완료 판도 안 버리고 전부 쓴다.

저장 포맷(.npz): Xs(상태 특징, N행), Xa(액션 특징, N행), y(선택 여부
0/1, N개), group(결정 단위 id, N개 -- 같은 결정의 후보들은 같은 id를
공유. top1/top3 그룹별 평가와 학습 시 그룹 단위 분할에 씀).

사용법:
    python3 scripts/generate_policy_data.py <판수> <출력파일.npz> \
        [--seed-base N] [--no-diversity]
"""

import sys
import random
import time

sys.path.insert(0, ".")

import numpy as np

from src.game.engine import Engine
from src.game.ai_heuristic import HeuristicAI
from src.game.ai_features import extract as extract_state, feature_count as state_feature_count
from src.game.ai_action_features import extract as extract_action, feature_count as action_feature_count
from src.game import protocols as P

MAX_STEPS = 20000

# generate_selfplay_data.py와 동일한 스타일/덤프 편향 -- 같은 정책만으로
# 자기대국하면 "이 상황에서 그 정책이 유일하게 고르는 것"만 라벨로 쌓여
# 정책 자체의 편향을 그대로 답습하기 쉽다. 편향을 흔들어 대조군을 섞는다.
STYLE_TIERS = [-2.5, -1.25, 0.0, 1.25, 2.5]
DUMP_TIERS = [-8.0, -4.0, 0.0, 4.0, 8.0]


def sample_bias(seed):
    r = random.Random(f"bias:{seed}")
    style = {1: r.choice(STYLE_TIERS), 2: r.choice(STYLE_TIERS)}
    dump = {1: r.choice(DUMP_TIERS), 2: r.choice(DUMP_TIERS)}
    return style, dump


class RecordingAI:
    """내부 정책(HeuristicAI)에 결정을 위임하되, 매 action 결정 직전에
    상태+후보별 액션 특징을 적어두고, 위임 결과가 그중 어느 후보였는지
    라벨로 남긴다."""

    def __init__(self, inner, group_start=0):
        self.inner = inner
        self.rows = []  # [(state_feat, action_feat, is_chosen, group_id), ...]
        self._gid = group_start

    def decide(self, g, req):
        if req.get("type") == "action":
            pi = req["chooser"]
            acts = g.legal_actions(pi)
            chosen = self.inner.decide(g, req)
            if len(acts) > 1:
                sf = extract_state(g, pi)
                gid = self._gid
                self._gid += 1
                for a in acts:
                    af = extract_action(g, pi, a)
                    self.rows.append((sf, af, 1.0 if a == chosen else 0.0, gid))
            return chosen
        return self.inner.decide(g, req)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def play_one_game(seed, protos1, protos2, group_start, diversity=True):
    random.seed(seed)
    ai = RecordingAI(HeuristicAI(), group_start=group_start)
    e = Engine(protocols1=protos1, protocols2=protos2, ai1=True, ai2=True, ai=ai, seed=seed)
    if diversity:
        e.ai_style_bias, e.ai_dump_bias = sample_bias(seed)
    e.start()
    steps = 0
    while e.pending is not None and steps < MAX_STEPS:
        steps += 1
        if e.pending["kind"] == "anim":
            e.advance_anim()
        else:
            e.answer(None)
    return ai.rows


def generate(n_games, out_path, seed_base=0, diversity=True):
    rnd = random.Random(seed_base)
    Xs, Xa, y, group = [], [], [], []
    next_gid = 0
    t0 = time.time()

    for i in range(n_games):
        pool = list(P.PROTOCOL_LIST)
        rnd.shuffle(pool)
        p1, p2 = pool[:3], pool[3:6]

        rows = play_one_game(seed_base + i, p1, p2, next_gid, diversity=diversity)
        for sf, af, chosen, gid in rows:
            Xs.append(sf)
            Xa.append(af)
            y.append(chosen)
            group.append(gid)
            next_gid = max(next_gid, gid + 1)

        if (i + 1) % max(1, n_games // 10) == 0:
            el = time.time() - t0
            n_decisions = len(set(group))
            print(f"  {i+1}/{n_games}판 진행 ({el:.1f}초, 결정 {n_decisions}개 누적)")

    Xs = np.asarray(Xs, dtype=np.float32)
    Xa = np.asarray(Xa, dtype=np.float32)
    y = np.asarray(y, dtype=np.float32)
    group = np.asarray(group, dtype=np.int64)
    assert Xs.shape[1] == state_feature_count(), "상태 특징 길이가 ai_features.py와 안 맞음"
    assert Xa.shape[1] == action_feature_count(), "액션 특징 길이가 ai_action_features.py와 안 맞음"

    np.savez(out_path, Xs=Xs, Xa=Xa, y=y, group=group)
    el = time.time() - t0
    n_decisions = len(set(group.tolist()))
    print()
    print(f"완료: {n_games}판 ({el:.1f}초)")
    print(f"결정 {n_decisions}개, 후보 행 {len(Xs)}개 (결정당 평균 후보 {len(Xs)/max(n_decisions,1):.1f}개)")
    print(f"저장: {out_path}")


if __name__ == "__main__":
    n_games = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    out_path = sys.argv[2] if len(sys.argv) > 2 else "policy_data.npz"
    seed_base = 0
    if "--seed-base" in sys.argv:
        seed_base = int(sys.argv[sys.argv.index("--seed-base") + 1])
    diversity = "--no-diversity" not in sys.argv

    generate(n_games, out_path, seed_base, diversity=diversity)
