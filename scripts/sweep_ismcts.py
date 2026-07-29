"""ISMCTSAI 하이퍼파라미터 스윕 -- 여러 설정을 순서대로 돌려서 결과를 표로 비교.

`scripts/arena_ismcts_vs_heuristic.py`가 설정 하나를 돌리는 도구라면, 이
스크립트는 아래 CONFIGS에 나열된 여러 설정을 전부 순서대로 돌리고 끝에
요약 표를 출력한다. 매번 명령을 따로 치는 대신, 이거 하나 실행해두고
기다리면 된다(설정이 많으면 오래 걸린다 -- 아래 "예상 소요 시간" 참고).

배경: `ai_ismcts_expectedoutput.md` §5.5에서 iterations=200(기본값)이
HeuristicAI 상대 90.0% ±10.5(유의미)를 냈다. 남은 질문은 "더 싸면서도
여전히 이기는 설정이 있는가"(웹 서비스 응답속도용)와 "c_ucb/
rollout_turn_cap/rollout_policy가 승률에 영향을 주는가"이다.

CONFIGS를 직접 편집해서 원하는 설정만 추리거나 새로 추가해도 된다.

사용법:
    python3 scripts/sweep_ismcts.py [n_pairs] [seed0]

    n_pairs: 설정 하나당 미러 쌍 수 (기본 8 = 16판). 값을 키우면 결과가
             더 정확해지지만 시간도 그만큼 늘어난다.
    seed0:   전체 설정이 공유하는 시작 시드 (기본 0) -- 같은 시드를 쓰면
             설정 간 비교가 "같은 프로토콜 매치업 순서"로 공정해진다.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.arena import arena  # noqa: E402
from src.game.ai_heuristic import HeuristicAI  # noqa: E402
from src.game.ai_ismcts import ISMCTSAI  # noqa: E402
from src.game.ai_random import RandomAI  # noqa: E402

# 반복 1회당 대략 이 정도 걸린다는 거친 상수 (ai_ismcts_expectedoutput.md
# §5.2 실측: iterations=200에서 결정 1회 ≈3.2초 -> 3.2/200). 예상 소요
# 시간 안내용일 뿐 정밀한 값이 아니다.
_SEC_PER_ITERATION = 3.2 / 200
_ASSUMED_DECISIONS_PER_GAME = 20

ROLLOUT_POLICIES = {"heuristic": HeuristicAI, "random": RandomAI}

# 우선순위 순서로 나열: 1) iterations를 낮춰서 "얼마나 싸도 여전히
# 이기는가", 2) iterations를 올려서 "한계효용이 있는가", 3) 나머지 축.
# label, iterations, c_ucb, rollout_turn_cap, rollout_policy(문자열 키)
CONFIGS = [
    {"label": "baseline (it=200, 기존 확인값)", "iterations": 200, "c_ucb": 1.41,
     "rollout_turn_cap": 24, "rollout_policy": "heuristic"},
    {"label": "it=100 (더 저렴한가?)", "iterations": 100, "c_ucb": 1.41,
     "rollout_turn_cap": 24, "rollout_policy": "heuristic"},
    {"label": "it=150", "iterations": 150, "c_ucb": 1.41,
     "rollout_turn_cap": 24, "rollout_policy": "heuristic"},
    {"label": "it=300 (더 올리면 더 좋아지는가?)", "iterations": 300, "c_ucb": 1.41,
     "rollout_turn_cap": 24, "rollout_policy": "heuristic"},
    {"label": "c_ucb=1.0", "iterations": 200, "c_ucb": 1.0,
     "rollout_turn_cap": 24, "rollout_policy": "heuristic"},
    {"label": "c_ucb=2.0", "iterations": 200, "c_ucb": 2.0,
     "rollout_turn_cap": 24, "rollout_policy": "heuristic"},
    {"label": "rollout_turn_cap=12", "iterations": 200, "c_ucb": 1.41,
     "rollout_turn_cap": 12, "rollout_policy": "heuristic"},
    {"label": "rollout_turn_cap=40", "iterations": 200, "c_ucb": 1.41,
     "rollout_turn_cap": 40, "rollout_policy": "heuristic"},
    {"label": "rollout_policy=random", "iterations": 200, "c_ucb": 1.41,
     "rollout_turn_cap": 24, "rollout_policy": "random"},
]


def _estimate_seconds(n_pairs, iterations):
    games = n_pairs * 2
    per_game = iterations * _SEC_PER_ITERATION * _ASSUMED_DECISIONS_PER_GAME
    return games * per_game


def main(argv):
    n_pairs = int(argv[1]) if len(argv) > 1 else 8
    seed0 = int(argv[2]) if len(argv) > 2 else 0

    total_est = sum(_estimate_seconds(n_pairs, c["iterations"]) for c in CONFIGS)
    print(f"설정 {len(CONFIGS)}개, 설정당 n_pairs={n_pairs}({n_pairs * 2}판), seed0={seed0}")
    print(f"전체 예상 소요 시간: 대략 {total_est / 60:.0f}분 (거친 추정치)")
    print("CONFIGS를 편집하면 이 목록/개수를 바꿀 수 있습니다.")
    print()

    results = []
    for i, cfg in enumerate(CONFIGS, 1):
        print(f"=== [{i}/{len(CONFIGS)}] {cfg['label']} ===")
        rollout_cls = ROLLOUT_POLICIES[cfg["rollout_policy"]]

        def make_ismcts(cfg=cfg, rollout_cls=rollout_cls):
            return ISMCTSAI(iterations=cfg["iterations"], c_ucb=cfg["c_ucb"],
                             rollout_turn_cap=cfg["rollout_turn_cap"],
                             rollout_policy=rollout_cls())

        t0 = time.time()
        r = arena(make_ismcts, HeuristicAI, n_pairs=n_pairs, seed0=seed0,
                   label_a=cfg["label"], label_b="Heuristic")
        r["elapsed_measured"] = time.time() - t0
        r["label"] = cfg["label"]
        results.append(r)
        print()

    print("=" * 70)
    print("스윕 요약 (승률은 전부 ISMCTSAI 기준, HeuristicAI 상대)")
    print("=" * 70)
    print(f"{'설정':38s} {'승률':>8s} {'±CI':>8s} {'유의미':>6s} {'소요(초)':>10s}")
    for r in results:
        sig = "O" if (r["rate"] - r["ci"] > 0.5) else ("X(역전)" if (r["rate"] + r["ci"] < 0.5) else "-")
        print(f"{r['label']:38s} {r['rate']*100:7.1f}% {r['ci']*100:7.1f}% "
              f"{sig:>6s} {r['elapsed_measured']:9.1f}")

    return results


if __name__ == "__main__":
    main(sys.argv)
