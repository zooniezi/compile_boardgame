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

`DEFAULT_LEGIBLE_EPS=0.04`는 루트 가독성 동점 처리(`ISMCTSAI`의
`legible_eps` 참고)의 허용 오차값 -- 더 크게 잡으면 탐색이 실제로 선호
하는 수(진짜 가치 차이가 있는 죽은 라인 방어 등)까지 덮어쓰기 시작할
위험이 있어 보수적으로 잡았다. 이 프리셋이 학습 eval + 학습 정책 +
mcts 탐색을 전부 갖춘 가장 상위 스택이라 여기서만 기본으로 켠다 --
중급(`ISMCTSLearnedAI`)과 손튜닝 `ISMCTSAI`는 기본값 None(꺼짐)을
그대로 둔다.

`DEFAULT_ITERATIONS=300`은 lua/ai_expert.lua의 `mcts.iters=300`과 맞춘
값(기존엔 `ISMCTSAI` 기본값 200을 그대로 물려받고 있었음). Lua는
150->300에서 60.0% ±6.8 유의미 우세(n=200, 학습된 eval이 포지션을
구별할 수 있게 된 뒤부터), 300->900은 53.3% ±5.6(사실상 노이즈)로
포화를 실측했다(같은 파일 주석 참고) -- 200->300은 그 "확실히 이득"
구간(150~300) 안에 들어간다. 실측 지연시간(중반 국면 5회 샘플): 200회
0.6~1.0초, 300회 1.0~1.2초 -- 한 수당 +0.3초 정도로, 이미 AI 턴마다
걸려있는 연출 지연(`aiTurnPace`, web/static/js/app.js)보다 작아
체감상 무시할 만한 수준이다.

`DEFAULT_REARRANGE_ITERATIONS=120`은 이 프리셋의 기본 `iterations`
(300)의 약 0.4배). 메인 탐색보다 훨씬 저렴한 예산으로도
"포기 + 단일 스왑 6가지"라는 작은 후보군은 충분히 구분 가능하다는
판단이다. Control 재배치 서브탐색(`ISMCTSAI.planRearrange`, 4단계
260804)도 legible과 같은 이유로 이 "고급" 프리셋에서만 기본으로 켠다.
"""

from pathlib import Path

from src.game.ai_ismcts import ISMCTSAI
from src.game.ai_sim import evaluate_learned_mlp, load_mlp_weights

DEFAULT_MLP_WEIGHTS_PATH = Path(__file__).resolve().parent / "data" / "eval_weights_mlp.npz"
DEFAULT_MLP_EVAL_SCALE = 3.1
DEFAULT_ITERATIONS = 300
DEFAULT_LEGIBLE_EPS = 0.04
DEFAULT_REARRANGE_ITERATIONS = 120


class ISMCTSMLPAI(ISMCTSAI):
    """`ISMCTSAI`와 완전히 같은 인터페이스지만, 기본 `eval_fn`이 학습된
    소형 MLP 평가함수고 탐색 예산(`iterations`)/루트 가독성 동점 처리
    (`legible_eps`)/Control 재배치 서브탐색(`rearrange_iterations`)이
    Lua Expert에 맞춰 기본으로 켜져 있다. 다른 인자는 그대로 오버라이드
    가능."""

    def __init__(self, weights_path=DEFAULT_MLP_WEIGHTS_PATH,
                 eval_scale=DEFAULT_MLP_EVAL_SCALE, **kwargs):
        kwargs.setdefault("eval_fn", evaluate_learned_mlp)
        kwargs.setdefault("eval_w", load_mlp_weights(str(weights_path)))
        kwargs.setdefault("eval_scale", eval_scale)
        kwargs.setdefault("iterations", DEFAULT_ITERATIONS)
        kwargs.setdefault("legible_eps", DEFAULT_LEGIBLE_EPS)
        kwargs.setdefault("rearrange_iterations", DEFAULT_REARRANGE_ITERATIONS)
        super().__init__(**kwargs)
