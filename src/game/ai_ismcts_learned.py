"""`ISMCTSAI`에 학습된 평가함수를 기본으로 꽂은 완제품 프리셋.

`ai_train_pipeline.md` Phase 3 실측 결과: `ISMCTSAI`(학습된 eval) vs
`ISMCTSAI`(손튜닝 `evaluate()`) 30판(15쌍) — **26승/4패, 86.7% ±11.6,
유의미하게 학습된 eval 우세**. 이 결과를 매번 `eval_fn`/`eval_w`/
`eval_scale`을 손으로 조립하지 않고 바로 재사용할 수 있게 만든
프리셋이다.

가중치(`src/game/data/eval_weights_plain.npz`)는 다양성 주입(자기대국
4000판, `ai_howtodiversity.md`)이 적용된 데이터로 학습한 97차원 plain
모델이다 — 교차항 확장 모델은 `ai_regularization.md`에서 확인했듯
plain과 통계적으로 대등할 뿐 더 낫지 않고 판당 비용도 커서(추론 시
`expand_features()` 호출 필요) 기본 프리셋으로는 plain을 쓴다.

`eval_scale=2.0`은 이 가중치의 실제 로짓 분포(평균≈0, 표준편차≈1.16,
p95≈1.9)를 실측해서 역산한 값이다(`ai_train_pipeline.md` Phase 3
진행 상황 참고) — 다른 가중치 파일로 바꿔 쓰려면 이 값도 다시
실측해야 한다.
"""

from pathlib import Path

from src.game.ai_ismcts import ISMCTSAI
from src.game.ai_sim import evaluate_learned, load_eval_weights

DEFAULT_WEIGHTS_PATH = Path(__file__).resolve().parent / "data" / "eval_weights_plain.npz"
DEFAULT_EVAL_SCALE = 2.0


class ISMCTSLearnedAI(ISMCTSAI):
    """`ISMCTSAI`와 완전히 같은 인터페이스지만, 기본 `eval_fn`이 학습된
    평가함수다. `iterations`/`c_ucb`/`rollout_turn_cap` 등 다른 인자는
    그대로 오버라이드 가능 -- `eval_fn`/`eval_w`/`eval_scale`만 다른
    기본값을 가진 `ISMCTSAI`라고 보면 된다."""

    def __init__(self, weights_path=DEFAULT_WEIGHTS_PATH,
                 eval_scale=DEFAULT_EVAL_SCALE, **kwargs):
        kwargs.setdefault("eval_fn", evaluate_learned)
        kwargs.setdefault("eval_w", load_eval_weights(str(weights_path)))
        kwargs.setdefault("eval_scale", eval_scale)
        super().__init__(**kwargs)
