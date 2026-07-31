"""ISMCTSLearnedAI(학습된 평가함수 프리셋) 하이퍼파라미터 스윕.

`scripts/sweep_ismcts.py`와 똑같은 구조지만 AI가 다르다 -- 저건 손튜닝
`evaluate()`를 쓰는 `ISMCTSAI`를 스윕했고(그 결과가 지금 `rollout_turn_cap`
기본값 2/`iterations`=200/`c_ucb`=1.41의 근거), 이건 `ISMCTSLearnedAI`
(학습된 eval, `ai_train_pipeline.md` Phase 3에서 손튜닝 대비 86.7% ±11.6로
유의미 우세를 확인한 조합)를 스윕한다.

배경: 지금 하이퍼파라미터 기본값은 전부 손튜닝 eval 기준으로 정해진
것들이다 -- 평가함수가 바뀌면(특히 로짓 스케일/판별력이 다르면) 탐색을
얼마나 깊게/넓게 해야 최선인지도 달라질 수 있다. 이 스크립트로 학습된
eval 기준으로 재확인한다.

CONFIGS를 직접 편집해서 원하는 설정만 추리거나 새로 추가해도 된다 --
단계적으로(rollout_turn_cap -> iterations -> c_ucb) 축 하나씩 스윕하고,
앞 단계에서 가장 좋았던 값을 다음 단계의 고정값으로 삼는 방식을 권장한다
(축 3개를 한꺼번에 전수조사하기엔 판당 비용이 크다).

중요한 방법론 메모(스모크 테스트로 실제 확인함): `HeuristicAI` 상대로는
`ISMCTSLearnedAI`가 하이퍼파라미터를 뭘로 바꿔도 거의 항상 압도적으로
이겨서(n_pairs=1에서도 4개 설정 전부 100.0%), 설정 간 차이를 구분할
신호가 전혀 안 나온다. 그래서 이 스크립트는 **후보 설정을 HeuristicAI가
아니라 "지금 기본값"(cap=2, it=200, c_ucb=1.41) 직접 맞대결**시킨다 --
둘 다 비슷하게 강해서, 하이퍼파라미터 차이가 실제로 승률에 드러난다.

사용법:
    python3 scripts/sweep_ismcts_learned.py [n_pairs] [seed0]
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.arena import arena  # noqa: E402
from src.game.ai_ismcts_learned import ISMCTSLearnedAI  # noqa: E402

# 기준선 -- 지금 ISMCTSAI 기본값 그대로(rollout_turn_cap=2, iterations=200,
# c_ucb=1.41). CONFIGS의 각 후보는 이 기준선과 직접 맞대결한다.
BASELINE = {"iterations": 200, "c_ucb": 1.41, "rollout_turn_cap": 2}

# Phase A 결과(2026-07-31, n_pairs=6): cap=4 vs cap=2 -- 정확히 6승6패
# (50.0% ±0.0, 완전 동률). cap=8 vs cap=2 -- 7승5패(58.3% ±30.1, 낌새는
# 있으나 표본 부족으로 무의미). cap=12 vs cap=2 -- 2승10패(16.7% ±20.7,
# cap=2가 유의미하게 우세, 확실히 나쁨). 결론: cap=2를 그대로 Phase B의
# 고정값으로 채택(cap=8의 낌새는 나중에 표본을 늘려 별도 재확인할 후보로
# 남겨둠).

# Phase B 결과(2026-07-31, n_pairs=6): it=100 vs it=200 -- 4승8패(33.3%
# ±20.7, 무의미하나 약해지는 쪽). it=150 vs it=200 -- 7승5패(58.3% ±30.1,
# cap=8과 같은 패턴의 "낌새만 있는 개선", 무의미). it=300 vs it=200 --
# 5승7패(41.7% ±30.1, 무의미하나 오히려 약해지는 쪽 -- 손튜닝 eval
# 스윕에서 봤던 "과하게 늘리면 한계효용 없음" 패턴과 일치). 결론: it=200을
# 뒤집을 근거 없음, 그대로 Phase C의 고정값으로 채택.

# Phase C 결과(2026-07-31, n_pairs=6): c_ucb=0.7 -- 9승3패(75.0% ±33.5).
# c_ucb=1.0 -- 8승4패(66.7% ±32.7). c_ucb=2.0 -- 5승7패(41.7% ±30.1, 기준값
# 1.41이 58.3%로 우세). 0.7->1.0->1.41->2.0 순서로 승률이 정확히 단조
# 감소 -- 개별로는 전부 무의미하지만 4개 값에 걸친 이 일관된 패턴 자체가
# "낮은 c_ucb가 유리하다"는 강한 정황증거. 가장 유력한 0.7을 표본을 늘려
# 확정하는 게 Phase D.

# Phase D 결과(2026-07-31, n_pairs=15/30판, seed0=100): c_ucb=0.7 --
# 15승15패, 정확히 50.0% ±13.5. Phase C의 75% 쏠림(n=12)이 표본을 5배로
# 늘리자 완전히 사라짐 -- 초반 신호는 노이즈였던 것으로 확정. 결론:
# c_ucb를 바꿀 근거 없음, 기본값(1.41=sqrt(2)) 유지.
#
# === 4단계 스윕 전체 결론 (rollout_turn_cap=2, iterations=200, c_ucb=1.41
# 기본값 유지) ===
# 학습된 eval로 갈아탄 뒤에도 손튜닝 eval 기준으로 잡았던 하이퍼파라미터
# 기본값 3개(cap/iterations/c_ucb) 전부 뒤집을 유의미한 근거를 찾지
# 못했다. cap=8/it=150의 "낌새"(Phase A/B, n=6)와 c_ucb=0.7의 "낌새"
# (Phase C, n=6)는 전부 Phase D 패턴(표본을 늘리면 사라짐)과 같은 종류의
# 소표본 노이즈였을 가능성이 높다 -- 재확인 없이는 신뢰하지 말 것.

# Phase D: 가장 유력한 후보(c_ucb=0.7)만 표본을 키워 재확인. (완료)
CONFIGS = [
    {"label": "c_ucb=0.7 (확정 재확인)", "iterations": 200, "c_ucb": 0.7, "rollout_turn_cap": 2},
]


def _make(cfg):
    return lambda: ISMCTSLearnedAI(iterations=cfg["iterations"], c_ucb=cfg["c_ucb"],
                                    rollout_turn_cap=cfg["rollout_turn_cap"])


def main(argv):
    n_pairs = int(argv[1]) if len(argv) > 1 else 8
    seed0 = int(argv[2]) if len(argv) > 2 else 0

    print(f"기준선: {BASELINE}")
    print(f"후보 {len(CONFIGS)}개, 설정당 n_pairs={n_pairs}({n_pairs * 2}판), seed0={seed0}")
    print("(양쪽 다 ISMCTSLearnedAI라 판당 비용이 vs-HeuristicAI보다 큼)")
    print()

    results = []
    for i, cfg in enumerate(CONFIGS, 1):
        print(f"=== [{i}/{len(CONFIGS)}] {cfg['label']} vs baseline(cap=2) ===")
        t0 = time.time()
        r = arena(_make(cfg), _make(BASELINE), n_pairs=n_pairs, seed0=seed0,
                   label_a=cfg["label"], label_b="baseline(cap=2)")
        r["elapsed_measured"] = time.time() - t0
        r["label"] = cfg["label"]
        results.append(r)
        print()

    print("=" * 70)
    print("스윕 요약 (승률은 전부 후보 기준, baseline(cap=2) 상대)")
    print("=" * 70)
    print(f"{'설정':30s} {'승률':>8s} {'±CI':>8s} {'유의미':>6s} {'소요(초)':>10s} {'판당(초)':>10s}")
    for r in results:
        sig = "O" if (r["rate"] - r["ci"] > 0.5) else ("X(역전)" if (r["rate"] + r["ci"] < 0.5) else "-")
        per_game = r["elapsed_measured"] / r["games"]
        print(f"{r['label']:30s} {r['rate']*100:7.1f}% {r['ci']*100:7.1f}% "
              f"{sig:>6s} {r['elapsed_measured']:9.1f} {per_game:9.1f}")

    return results


if __name__ == "__main__":
    main(sys.argv)
