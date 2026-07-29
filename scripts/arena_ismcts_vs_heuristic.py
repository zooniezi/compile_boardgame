"""ISMCTSAI vs HeuristicAI 승률 벤치마크 (표본을 크게 잡아 결론 내기용).

`scripts/arena.py`는 범용 CLI라 AI 생성자에 인자를 못 넘긴다(항상 기본값
인스턴스). 이 스크립트는 `ISMCTSAI`의 하이퍼파라미터(iterations, c_ucb,
rollout_turn_cap)를 커맨드라인에서 직접 조절하면서 `HeuristicAI` 상대
승률을 재기 위한 전용 스크립트다.

배경: `ai_ismcts_expectedoutput.md` §5.3의 소규모 실측(iterations=50,
12판)은 5승 7패(41.7% ±16.3)로 "통계적으로 무의미"했다 -- 표본이 작고
반복 수도 기본값(200)의 1/4이라 결론을 못 냈다. 이 스크립트로 표본과
반복 수를 늘려 재확인한다.

주의(시간 예산): `ai_ismcts_expectedoutput.md` §5.2 실측 기준
iterations=200에서 결정 1회가 약 3.2초 걸렸다. 한 판에 ISMCTSAI 쪽
"action" 결정이 대략 15~30회 있다고 보면 판당 대략 50~100초 -- n_pairs가
크면(예: 30쌍=60판) 수십 분 이상 걸릴 수 있다. 아래 실행 전 출력되는
"예상 소요 시간"은 거친 추정이니, 처음에는 n_pairs/iterations를 작게
잡고 실제 속도를 본 뒤 늘리는 것을 권장한다.

사용법:
    python3 scripts/arena_ismcts_vs_heuristic.py [n_pairs] [iterations] \
        [rollout_turn_cap] [c_ucb] [seed0]

    전부 위치 인자, 전부 생략 가능(기본값 사용). 예:
        python3 scripts/arena_ismcts_vs_heuristic.py            # 기본값 전부
        python3 scripts/arena_ismcts_vs_heuristic.py 5           # n_pairs=5만 바꿈
        python3 scripts/arena_ismcts_vs_heuristic.py 30 200 24 1.41 0
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.arena import arena  # noqa: E402
from src.game.ai_heuristic import HeuristicAI  # noqa: E402
from src.game.ai_ismcts import ISMCTSAI  # noqa: E402

# ai_ismcts_expectedoutput.md §5.2 실측(iterations=200 기준 결정 1회 ≈3.2초)에서
# 역산한 "반복 1회당 대략 이 정도 걸린다"는 거친 상수. 실제로는 게임/카드
# 구성에 따라 달라지므로 사전 예상 시간 안내용일 뿐, 정밀한 값이 아니다.
_SEC_PER_ITERATION = 3.2 / 200
# 한 판에 ISMCTSAI 쪽 "action" 결정이 몇 번쯤 발생하는지의 거친 추정
# (스모크 테스트에서 관찰한 턴 수 범위 기준 중간값).
_ASSUMED_DECISIONS_PER_GAME = 20


def _estimate_seconds(n_pairs, iterations):
    games = n_pairs * 2
    per_game = iterations * _SEC_PER_ITERATION * _ASSUMED_DECISIONS_PER_GAME
    return games * per_game


def main(argv):
    n_pairs = int(argv[1]) if len(argv) > 1 else 10
    iterations = int(argv[2]) if len(argv) > 2 else 200
    rollout_turn_cap = int(argv[3]) if len(argv) > 3 else 24
    c_ucb = float(argv[4]) if len(argv) > 4 else 1.41
    seed0 = int(argv[5]) if len(argv) > 5 else 0

    est = _estimate_seconds(n_pairs, iterations)
    print(f"설정: n_pairs={n_pairs} ({n_pairs * 2}판), iterations={iterations}, "
          f"rollout_turn_cap={rollout_turn_cap}, c_ucb={c_ucb}, seed0={seed0}")
    print(f"예상 소요 시간: 대략 {est:.0f}초 (~{est / 60:.1f}분) "
          f"-- 거친 추정치이니 실제와 다를 수 있음")
    print()

    def make_ismcts():
        return ISMCTSAI(iterations=iterations, c_ucb=c_ucb,
                         rollout_turn_cap=rollout_turn_cap)

    result = arena(make_ismcts, HeuristicAI, n_pairs=n_pairs, seed0=seed0,
                    label_a=f"ISMCTS(it={iterations})", label_b="Heuristic")
    return result


if __name__ == "__main__":
    main(sys.argv)
