"""`ISMCTSAI`에 학습된 비선형(소형 MLP) 평가함수를 기본으로 꽂은 프리셋.

`ai_ismcts_learned.py`(선형, 로지스틱 회귀)와 완전히 병렬 구조 --
`eval_fn`/`eval_w`/`eval_scale`만 MLP 버전으로 바뀐다. 두 프리셋은
서로를 대체하지 않고 나란히 존재한다(260801_mlp.md §9 "건드리지 않는
것" 참고 -- 손튜닝 `ISMCTSAI`도, 기존 gen1 선형 프리셋도 이 작업으로
안 바뀜).

가중치(`src/game/data/eval_weights_mlp.npz`)는 `selfplay_gen3.npz`
(HeuristicAI 자기대국 1만 판, 다양성 주입, Main3/Aux3 포함 45개
프로토콜 전부, 2026-08-02 생성)로 학습한 소형 MLP다 --
260801_mlp.md §3.2 파일럿에서 같은 데이터의 로지스틱 회귀 대비 검증
로그손실 -0.0172(0.5852 -> 0.5681, 은닉층 (64,), alpha=0.0001)를
확인했다.

`DEFAULT_EVAL_SCALE=3.1`은 5.3절 방식(실제 로짓 분포 실측, 무작위
5만 표본)으로 역산: 평균≈-0.01, 표준편차≈1.41, |로짓| p95≈3.08,
p99≈4.53(gen1 선형 모델의 표준편차≈1.16/p95≈1.9보다 폭이 넓다 --
비선형이라 극값이 더 극단적으로 나온다는 계획서 §5.3의 예상과
일치). gen1의 `eval_scale=2.0`을 그대로 썼다면 이 분포에서 tanh가
너무 일찍 포화돼 탐색 신호가 뭉개졌을 것.
"""

from pathlib import Path

from src.game.ai_ismcts import ISMCTSAI
from src.game.ai_sim import evaluate_learned_mlp, load_mlp_weights

DEFAULT_MLP_WEIGHTS_PATH = Path(__file__).resolve().parent / "data" / "eval_weights_mlp.npz"
DEFAULT_MLP_EVAL_SCALE = 3.1


class ISMCTSMLPAI(ISMCTSAI):
    """`ISMCTSAI`와 완전히 같은 인터페이스지만, 기본 `eval_fn`이 학습된
    소형 MLP 평가함수다. `iterations`/`c_ucb`/`rollout_turn_cap` 등 다른
    인자는 그대로 오버라이드 가능."""

    def __init__(self, weights_path=DEFAULT_MLP_WEIGHTS_PATH,
                 eval_scale=DEFAULT_MLP_EVAL_SCALE, **kwargs):
        kwargs.setdefault("eval_fn", evaluate_learned_mlp)
        kwargs.setdefault("eval_w", load_mlp_weights(str(weights_path)))
        kwargs.setdefault("eval_scale", eval_scale)
        super().__init__(**kwargs)
