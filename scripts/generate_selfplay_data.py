"""자기대국으로 학습 데이터 생성.

기본은 HeuristicAI끼리 여러 판을 두게 하면서, 매 'action' 결정 직전마다 두
플레이어 시점의 특징 벡터(ai_features.extract)를 기록해둔다. 판이 끝나
승자가 정해지면 그동안 기록해둔 벡터들에 "그 시점 주인이 결국 이겼나(1/0)"
라벨을 붙인다. 무승부/미완료(스텝 한도 초과) 판은 라벨을 못 붙이므로 통째로
버린다.

기본적으로 좌석마다 매 판 무작위 "스타일 편향"(ai_style_bias, 앞/뒷면 결정을
흔듦)과 "덤프 편향"(ai_dump_bias, 이미 컴파일한 라인에 또 낼지를 흔듦)을
줘서 자기대국에 대조되는 스타일이 섞이게 한다(ai_howtodiversity.md) -- 모두
같은 정책으로만 두면 "이 선택이 실제로 승패에 영향을 줬는지" 판단할 대조군이
데이터에 없어서 학습이 배울 신호가 부족해진다. `--no-diversity`로 끄면
순수 자기대국(둘 다 편향 없음)으로 돌아간다.

`--policy lookahead --weights <gen{N}.npz경로>`를 주면 HeuristicAI 대신
LookaheadAI(eval_fn=evaluate_learned, eval_w=그 가중치)로 자기대국을
둔다 -- "학습된 eval 자기개선 루프"(260731.md §9 이후 작업)의 세대별
데이터 생성용. HeuristicAI보다 판단력이 높은 정책으로 자기대국을 두면
그 데이터로 학습한 다음 세대 eval이 더 정확해질 거라는 가설을 검증한다.

사용법:
    python3 scripts/generate_selfplay_data.py <판수> <출력파일.npz> \
        [--seed-base N] [--no-diversity] \
        [--policy heuristic|lookahead] [--weights <가중치.npz경로>]
"""

import sys
import random
import time

sys.path.insert(0, ".")

import numpy as np

from src.game.engine import Engine
from src.game.ai_heuristic import HeuristicAI
from src.game.ai_lookahead import LookaheadAI
from src.game.ai_features import extract, feature_count
from src.game.ai_sim import evaluate_learned, load_eval_weights
from src.game import protocols as P

MAX_STEPS = 20000  # 무한 대치(스테일메이트) 방지 -- 이 이상 걸리면 미완료로 버림

# ai_howtodiversity.md §3.2: score_action()의 실제 점수 스케일(컴파일 임계값
# 관련 항은 60/40/20/12, effect_prior()는 대략 0~±2)에 견줘 "종종 애매한
# 결정을 뒤집을 만큼 크되 큰 전술 판단은 못 건드리는" 크기로 역산한 값.
STYLE_TIERS = [-2.5, -1.25, 0.0, 1.25, 2.5]
DUMP_TIERS = [-8.0, -4.0, 0.0, 4.0, 8.0]


def sample_bias(seed):
    """좌석별 (style_bias, dump_bias) 딕셔너리를 샘플링한다. 전역 random
    스트림과 완전히 분리된 별도 RNG를 써서, 이 샘플링을 추가해도 게임 자체의
    재현성(같은 seed -> 같은 판)이 깨지지 않게 한다."""
    r = random.Random(f"bias:{seed}")  # 문자열 시드 -- 튜플은 해시 기반 시딩이라 폐지 예정(Python 3.9+)
    style = {1: r.choice(STYLE_TIERS), 2: r.choice(STYLE_TIERS)}
    dump = {1: r.choice(DUMP_TIERS), 2: r.choice(DUMP_TIERS)}
    return style, dump


class RecordingAI:
    """내부 정책 AI(HeuristicAI든 LookaheadAI든 무엇이든)를 감싸서, 매
    'action' 프롬프트 직전에 두 플레이어 시점 특징 벡터를 같이 적어둔다.
    실제 결정은 전부 내부 AI(`inner`)에 위임한다 -- 상속이 아니라 위임으로
    짠 이유는, 어떤 정책이든(HeuristicAI/LookaheadAI/...) 똑같이 감쌀 수
    있어야 하기 때문(각 정책마다 RecordingAI 서브클래스를 따로 만들지
    않아도 됨)."""

    def __init__(self, inner):
        self.inner = inner
        self.snapshots = []  # [(pi, feature_vector), ...]

    def decide(self, g, req):
        if req.get("type") == "action":
            self.snapshots.append((1, extract(g, 1)))
            self.snapshots.append((2, extract(g, 2)))
        return self.inner.decide(g, req)

    def __getattr__(self, name):
        # planRearrange 등 decide() 외의 AI 프로토콜 메서드를 inner로 위임.
        return getattr(self.inner, name)


def play_one_game(seed, protos1, protos2, diversity=True, policy_factory=HeuristicAI):
    random.seed(seed)  # HeuristicAI 내부는 결정적이지만, RandomAI로 폴백되는
                        # 하위 결정들이 전역 random을 쓰므로 재현성을 위해 고정
    ai = RecordingAI(policy_factory())
    e = Engine(protocols1=protos1, protocols2=protos2, ai1=True, ai2=True,
               ai=ai, seed=seed)
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
    return ai.snapshots, e.winner


def generate(n_games, out_path, seed_base=0, diversity=True, policy_factory=HeuristicAI):
    rnd = random.Random(seed_base)
    X, y = [], []
    completed = 0
    t0 = time.time()

    for i in range(n_games):
        pool = list(P.PROTOCOL_LIST)
        rnd.shuffle(pool)
        p1, p2 = pool[:3], pool[3:6]

        snapshots, winner = play_one_game(seed_base + i, p1, p2, diversity=diversity,
                                           policy_factory=policy_factory)
        if winner is None:
            continue  # 무승부/미완료 -- 라벨을 못 붙이니 버림
        completed += 1
        for pi, feat in snapshots:
            X.append(feat)
            y.append(1.0 if winner == pi else 0.0)

        if (i + 1) % max(1, n_games // 10) == 0:
            el = time.time() - t0
            print(f"  {i+1}/{n_games}판 진행 ({el:.1f}초, 완료율 {completed}/{i+1})")

    X = np.asarray(X, dtype=np.float32)
    y = np.asarray(y, dtype=np.float32)
    assert X.shape[1] == feature_count(), "특징 길이가 ai_features.py와 안 맞음"

    np.savez(out_path, X=X, y=y)
    el = time.time() - t0
    print()
    print(f"완료: {completed}/{n_games}판 정상 종료 ({el:.1f}초)")
    print(f"샘플 {len(X)}개 (판당 평균 {len(X)/max(completed,1):.1f}개)")
    print(f"승/패 비율: {y.mean()*100:.1f}% / {(1-y.mean())*100:.1f}%")
    print(f"저장: {out_path}")


if __name__ == "__main__":
    n_games = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    out_path = sys.argv[2] if len(sys.argv) > 2 else "selfplay_data.npz"
    seed_base = 0
    if "--seed-base" in sys.argv:
        seed_base = int(sys.argv[sys.argv.index("--seed-base") + 1])
    diversity = "--no-diversity" not in sys.argv

    policy = "heuristic"
    if "--policy" in sys.argv:
        policy = sys.argv[sys.argv.index("--policy") + 1]

    if policy == "lookahead":
        if "--weights" not in sys.argv:
            raise SystemExit("--policy lookahead는 --weights <가중치.npz경로>가 필요함")
        weights_path = sys.argv[sys.argv.index("--weights") + 1]
        eval_w = load_eval_weights(weights_path)
        policy_factory = lambda: LookaheadAI(eval_fn=evaluate_learned, eval_w=eval_w)
    elif policy == "heuristic":
        policy_factory = HeuristicAI
    else:
        raise SystemExit(f"알 수 없는 --policy: {policy} (heuristic|lookahead)")

    generate(n_games, out_path, seed_base, diversity=diversity, policy_factory=policy_factory)
