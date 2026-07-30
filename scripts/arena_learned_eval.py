"""학습된 평가함수(evaluate_learned) 비교 벤치마크.

`scripts/train_eval.py`로 만든 가중치 두 개를 `LookaheadAI`(1수 앞보기,
`ai_sim.pick_best` 기반)에 각각 꽂아서 실전 승률로 비교한다. 주 용도:
plain(97차원) 모델 vs 교차항 확장(4850차원) 모델 -- 오프라인 검증
logloss/accuracy만으로는 "실제 대국에서 더 잘 두는가"를 보장 못 하므로,
계획한 것처럼 실제 아레나로 재확인한다.

세 번째 비교 상대로 손튜닝 `evaluate()`도 옵션으로 붙을 수 있게 해서,
"학습된 모델이 손튜닝보다 나은가"도 같이 잴 수 있다.

사용법:
    python scripts/arena_learned_eval.py <가중치A.npz> <가중치B.npz> [n_pairs]
    python scripts/arena_learned_eval.py <가중치A.npz> handtuned [n_pairs]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.arena import arena  # noqa: E402
from src.game.ai_heuristic import HeuristicAI  # noqa: E402
from src.game.ai_lookahead import LookaheadAI  # noqa: E402
from src.game.ai_sim import evaluate, evaluate_learned, load_eval_weights  # noqa: E402


def _make_ai(spec):
    """spec이 'handtuned'면 손튜닝 evaluate(), 그 외엔 .npz 경로로 취급해
    evaluate_learned()를 꽂은 LookaheadAI 팩토리를 만든다."""
    if spec == "handtuned":
        label = "Lookahead(handtuned)"
        return (lambda: LookaheadAI(eval_fn=evaluate)), label
    w = load_eval_weights(spec)
    dim = len(w[0])
    label = f"Lookahead({Path(spec).stem}, {dim}d)"
    return (lambda: LookaheadAI(eval_fn=evaluate_learned, eval_w=w)), label


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    spec_a, spec_b = argv[1], argv[2]
    n_pairs = int(argv[3]) if len(argv) > 3 else 10

    ai_a, label_a = _make_ai(spec_a)
    ai_b, label_b = _make_ai(spec_b)

    print(f"{label_a}  vs  {label_b}  ({n_pairs}쌍 = {n_pairs*2}판)")
    print()
    arena(ai_a, ai_b, n_pairs=n_pairs, label_a=label_a, label_b=label_b)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
