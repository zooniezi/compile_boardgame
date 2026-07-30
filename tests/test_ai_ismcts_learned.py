"""ISMCTSLearnedAI(src/game/ai_ismcts_learned.py) 회귀 테스트.

`ISMCTSAI`에 학습된 평가함수(97차원 plain, ai_train_pipeline.md Phase 3
검증 완료)를 기본으로 꽂은 프리셋. 여기서는 "제대로 조립됐는가"(가중치가
실제로 로드되는지, eval_fn/eval_scale이 학습판으로 바뀌는지, 다른
인자는 여전히 오버라이드되는지, 실제로 한 판 굴려도 안 죽는지)만
확인한다 -- 승률 자체는 이미 ai_train_pipeline.md에서 별도 아레나로
실측했다(86.7% ±11.6).
"""

import random
import threading

from src.game.engine import Engine
from src.game.ai_heuristic import HeuristicAI
from src.game.ai_ismcts import ISMCTSAI
from src.game.ai_ismcts_learned import ISMCTSLearnedAI, DEFAULT_WEIGHTS_PATH, DEFAULT_EVAL_SCALE
from src.game.ai_sim import evaluate, evaluate_learned, load_eval_weights

PROTOS1 = ["Water", "Fire", "Life"]
PROTOS2 = ["Ice", "Metal", "Death"]


def _driven_engine(seed, ai_modules, steps=20000):
    random.seed(seed)
    e = Engine(protocols1=PROTOS1, protocols2=PROTOS2,
               ai1=True, ai2=True, seed=seed, ai_modules=ai_modules)
    e.start()
    n = 0
    while e.pending is not None and n < steps:
        n += 1
        if e.pending["kind"] == "anim":
            e.advance_anim()
        else:
            e.answer(None)
    return e


def test_default_construction_wires_learned_eval():
    ai = ISMCTSLearnedAI(iterations=1)
    assert ai.eval_fn is evaluate_learned
    assert ai.eval_scale == DEFAULT_EVAL_SCALE
    coef, intercept = ai.eval_w
    expected_coef, expected_intercept = load_eval_weights(str(DEFAULT_WEIGHTS_PATH))
    assert list(coef) == list(expected_coef)
    assert intercept == expected_intercept


def test_is_a_real_ismctsai_subclass_with_same_interface():
    ai = ISMCTSLearnedAI(iterations=1)
    assert isinstance(ai, ISMCTSAI)


def test_other_kwargs_remain_overridable():
    ai = ISMCTSLearnedAI(iterations=7, rollout_turn_cap=3, c_ucb=0.9)
    assert ai.iterations == 7
    assert ai.rollout_turn_cap == 3
    assert ai.c_ucb == 0.9
    # eval 쪽은 여전히 학습판 기본값
    assert ai.eval_fn is evaluate_learned


def test_explicit_eval_fn_overrides_the_preset():
    """프리셋이지만 강제로 손튜닝 eval을 넣으면 그게 이겨야 한다 --
    kwargs.setdefault()라 명시적 인자가 항상 우선해야 함."""
    ai = ISMCTSLearnedAI(iterations=1, eval_fn=evaluate, eval_w=None)
    assert ai.eval_fn is evaluate
    assert ai.eval_w is None


def test_full_game_runs_without_error():
    ai = ISMCTSLearnedAI(iterations=8, rollout_turn_cap=3)
    e = _driven_engine(seed=2024, ai_modules={1: ai, 2: HeuristicAI()})
    assert e.error is None
    assert e.winner in (1, 2)


def test_decide_does_not_leak_threads():
    before = threading.active_count()
    ai = ISMCTSLearnedAI(iterations=8, rollout_turn_cap=3)
    _driven_engine(seed=7, ai_modules={1: ai, 2: HeuristicAI()})
    after = threading.active_count()
    assert after == before
