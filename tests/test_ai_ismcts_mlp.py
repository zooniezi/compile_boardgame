"""ISMCTSMLPAI(src/game/ai_ismcts_mlp.py) 회귀 테스트.

test_ai_ismcts_learned.py와 완전히 같은 패턴 -- "제대로 조립됐는가"만
확인한다(가중치 로드, eval_fn/eval_scale 배선, 다른 인자 오버라이드,
실제로 한 판 굴려도 안 죽는지). 실력(승률)은 아레나로 별도 검증
(260801_mlp.md §6.3).
"""

import random
import threading

from src.game.engine import Engine
from src.game.ai_heuristic import HeuristicAI
from src.game.ai_ismcts import ISMCTSAI
from src.game.ai_ismcts_mlp import ISMCTSMLPAI, DEFAULT_MLP_WEIGHTS_PATH, DEFAULT_MLP_EVAL_SCALE
from src.game.ai_sim import evaluate, evaluate_learned_mlp, load_mlp_weights

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


def test_default_construction_wires_mlp_eval():
    ai = ISMCTSMLPAI(iterations=1)
    assert ai.eval_fn is evaluate_learned_mlp
    assert ai.eval_scale == DEFAULT_MLP_EVAL_SCALE
    expected = load_mlp_weights(str(DEFAULT_MLP_WEIGHTS_PATH))
    assert len(ai.eval_w) == len(expected)
    for (w1, b1), (w2, b2) in zip(ai.eval_w, expected):
        assert (w1 == w2).all()
        assert (b1 == b2).all()


def test_is_a_real_ismctsai_subclass_with_same_interface():
    ai = ISMCTSMLPAI(iterations=1)
    assert isinstance(ai, ISMCTSAI)


def test_other_kwargs_remain_overridable():
    ai = ISMCTSMLPAI(iterations=7, rollout_turn_cap=3, c_ucb=0.9)
    assert ai.iterations == 7
    assert ai.rollout_turn_cap == 3
    assert ai.c_ucb == 0.9
    assert ai.eval_fn is evaluate_learned_mlp


def test_explicit_eval_fn_overrides_the_preset():
    ai = ISMCTSMLPAI(iterations=1, eval_fn=evaluate, eval_w=None)
    assert ai.eval_fn is evaluate
    assert ai.eval_w is None


def test_full_game_runs_without_error():
    ai = ISMCTSMLPAI(iterations=8, rollout_turn_cap=3)
    e = _driven_engine(seed=2024, ai_modules={1: ai, 2: HeuristicAI()})
    assert e.error is None
    assert e.winner in (1, 2)


def test_decide_does_not_leak_threads():
    before = threading.active_count()
    ai = ISMCTSMLPAI(iterations=8, rollout_turn_cap=3)
    _driven_engine(seed=7, ai_modules={1: ai, 2: HeuristicAI()})
    after = threading.active_count()
    assert after == before
