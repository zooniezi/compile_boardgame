"""자기대국으로 학습 데이터 생성.

HeuristicAI끼리 여러 판을 두게 하면서, 매 'action' 결정 직전마다 두 플레이어
시점의 특징 벡터(ai_features.extract)를 기록해둔다. 판이 끝나 승자가 정해지면
그동안 기록해둔 벡터들에 "그 시점 주인이 결국 이겼나(1/0)" 라벨을 붙인다.
무승부/미완료(스텝 한도 초과) 판은 라벨을 못 붙이므로 통째로 버린다.

사용법:
    python3 scripts/generate_selfplay_data.py <판수> <출력파일.npz> [--seed-base N]
"""

import sys
import random
import time

sys.path.insert(0, ".")

import numpy as np

from src.game.engine import Engine
from src.game.ai_heuristic import HeuristicAI
from src.game.ai_features import extract, feature_count
from src.game import protocols as P

MAX_STEPS = 20000  # 무한 대치(스테일메이트) 방지 -- 이 이상 걸리면 미완료로 버림


class RecordingAI(HeuristicAI):
    """HeuristicAI 그대로 두 결정만 하되, 매 action 프롬프트 직전에
    두 플레이어 시점 특징 벡터를 같이 적어둔다."""

    def __init__(self):
        super().__init__()
        self.snapshots = []  # [(pi, feature_vector), ...]

    def decide(self, g, req):
        if req.get("type") == "action":
            self.snapshots.append((1, extract(g, 1)))
            self.snapshots.append((2, extract(g, 2)))
        return super().decide(g, req)


def play_one_game(seed, protos1, protos2):
    random.seed(seed)  # HeuristicAI 내부는 결정적이지만, RandomAI로 폴백되는
                        # 하위 결정들이 전역 random을 쓰므로 재현성을 위해 고정
    ai = RecordingAI()
    e = Engine(protocols1=protos1, protocols2=protos2, ai1=True, ai2=True,
               ai=ai, seed=seed)
    e.start()
    steps = 0
    while e.pending is not None and steps < MAX_STEPS:
        steps += 1
        if e.pending["kind"] == "anim":
            e.advance_anim()
        else:
            e.answer(None)
    return ai.snapshots, e.winner


def generate(n_games, out_path, seed_base=0):
    rnd = random.Random(seed_base)
    X, y = [], []
    completed = 0
    t0 = time.time()

    for i in range(n_games):
        pool = list(P.PROTOCOL_LIST)
        rnd.shuffle(pool)
        p1, p2 = pool[:3], pool[3:6]

        snapshots, winner = play_one_game(seed_base + i, p1, p2)
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
    generate(n_games, out_path, seed_base)
