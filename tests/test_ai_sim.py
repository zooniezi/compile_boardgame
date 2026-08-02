"""ai_sim.py -- 결정화(determinize) / 평가(evaluate) / 1수 앞보기(pick_best)
회귀 테스트.
"""

import random

import numpy as np
import pytest

from src.game.engine import Engine
from src.game.ai_random import RandomAI
from src.game.ai_sim import (
    determinize, evaluate, pick_best, evaluate_learned, load_eval_weights, DEFAULT_WEIGHTS,
)
from src.game.ai_features import extract, expand_features, feature_count


def _card(g, proto, value, owner, face_up=True):
    c = g.new_card(proto, value, owner)
    c.face_up = face_up
    return c


def _driven_engine(seed, ai, steps=500):
    # RandomAI가 엔진 seed가 아니라 파이썬 전역 random을 쓰므로, 테스트
    # 실행 순서(다른 테스트가 먼저 전역 random을 소비했는지)와 무관하게
    # 이 판이 항상 같은 길이로 진행되도록 여기서도 고정한다.
    random.seed(seed)
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"],
               ai1=True, ai2=True, ai=ai, seed=seed)
    e.start()
    n = 0
    while e.pending is not None and n < steps:
        n += 1
        if e.pending["kind"] == "anim":
            e.advance_anim()
        else:
            e.answer(None)
    return e


def test_determinize_preserves_public_info_but_shuffles_hidden_info():
    e = _driven_engine(seed=4242, ai=RandomAI())
    sim = e.clone_at_decision()
    assert sim is not None

    opp_hand_before = [(c.uid, c.proto, c.value) for c in sim.players[2]["hand"]]
    my_deck_multiset_before = sorted((c.proto, c.value) for c in sim.players[1]["deck"])
    my_faceup_before = [(c.uid, c.proto, c.value) for l in (1, 2, 3)
                        for c in sim.players[1]["stacks"][l] if c.face_up]

    determinize(sim, 1, salt=0)

    opp_hand_after = [(c.uid, c.proto, c.value) for c in sim.players[2]["hand"]]
    my_deck_multiset_after = sorted((c.proto, c.value) for c in sim.players[1]["deck"])
    my_faceup_after = [(c.uid, c.proto, c.value) for l in (1, 2, 3)
                       for c in sim.players[1]["stacks"][l] if c.face_up]

    # 개수는 유지, 정체는 섞임 (숨은 정보)
    assert len(opp_hand_before) == len(opp_hand_after)
    assert opp_hand_before != opp_hand_after
    # 공개 정보는 그대로
    assert my_deck_multiset_before == my_deck_multiset_after
    assert my_faceup_before == my_faceup_after
    sim.dispose()


def test_determinize_same_salt_reproduces_same_world():
    e = _driven_engine(seed=4242, ai=RandomAI())
    sim1 = e.clone_at_decision()
    sim2 = e.clone_at_decision()
    determinize(sim1, 1, salt=0)
    determinize(sim2, 1, salt=0)
    a = [(c.proto, c.value) for c in sim1.players[2]["hand"]]
    b = [(c.proto, c.value) for c in sim2.players[2]["hand"]]
    sim1.dispose()
    sim2.dispose()
    assert a == b


def test_determinize_different_salt_gives_different_world():
    e = _driven_engine(seed=4242, ai=RandomAI())
    sim1 = e.clone_at_decision()
    sim2 = e.clone_at_decision()
    determinize(sim1, 1, salt=0)
    determinize(sim2, 1, salt=1)
    a = [(c.proto, c.value) for c in sim1.players[2]["hand"]]
    b = [(c.proto, c.value) for c in sim2.players[2]["hand"]]
    sim1.dispose()
    sim2.dispose()
    assert a != b


def test_evaluate_favors_winner_and_compiled_protocols():
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    baseline = evaluate(e, 1)

    e.winner = 1
    assert evaluate(e, 1) == 1e6
    assert evaluate(e, 2) == -1e6
    e.winner = None

    e.players[1]["compiled"][1] = True
    assert evaluate(e, 1) > baseline


def test_evaluate_ready_bonus_suppressed_when_lust_locked():
    """임계값을 넘겨 우세해도 Lust_0류 동적 봉쇄(상대가 Control을 쥐고
    blockOpponentCompileWithControl 카드를 드러내 놓음) 상태면, 다음 턴에
    실제로 컴파일할 수 없으니 "곧 컴파일"(ready) 대신 그냥 라인
    우세(lead)로만 평가해야 한다 -- ai_prior.compile_available_next_check와
    동일한 규칙."""
    def build(locked):
        protos2 = ["Lust", "Metal", "Death"] if locked else ["Metal", "Water", "Death"]
        e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=protos2)
        e.control = 2  # 봉쇄 없는 쪽도 control 항이 동일하게 상쇄되도록 통일
        if locked:
            e.players[2]["stacks"][1].append(_card(e, "Lust", 0, 2))
        e.players[1]["stacks"][2].append(_card(e, "Fire", 5, 1))
        e.players[1]["stacks"][2].append(_card(e, "Water", 5, 1))
        return e

    e_locked = build(True)
    e_free = build(False)
    assert e_locked.line_value(1, 2) >= 10 and e_free.line_value(1, 2) >= 10
    diff = evaluate(e_free, 1) - evaluate(e_locked, 1)
    assert diff == pytest.approx(DEFAULT_WEIGHTS["ready"] - DEFAULT_WEIGHTS["lead"])


def test_pick_best_returns_a_legal_action_from_within_ai_decide():
    """실제 사용 형태: AI의 decide() 안에서 pick_best를 호출해 후보 중
    하나를 골라야 한다. 재생 종료 이후의 하위 결정(카드 효과 안의 대상
    선택 등)도 policy가 전부 답할 수 있어야 크래시 없이 끝까지 돈다."""
    picks = []

    class LookaheadSpyAI(RandomAI):
        def decide(self, g, req):
            if req.get("type") == "action" and len(picks) < 5:
                acts = g.legal_actions(req["chooser"])
                if len(acts) > 1:
                    cands = [{"a": a, "s": 0} for a in acts]
                    best = pick_best(g, req["chooser"], cands, RandomAI(), {"samples": 1})
                    picks.append(best)
            return super().decide(g, req)

    e = _driven_engine(seed=2024, ai=LookaheadSpyAI())
    assert e.error is None
    assert len(picks) > 0
    assert all(p is not None for p in picks)


def test_pick_best_does_not_mutate_the_live_engine():
    """복제본에서 무엇을 시도하든 원본(살아있는 판)은 전혀 영향받지 않아야
    한다."""
    result = {}

    class OnceSpyAI(RandomAI):
        triggered = False

        def decide(self, g, req):
            if not OnceSpyAI.triggered and req.get("type") == "action":
                acts = g.legal_actions(req["chooser"])
                if len(acts) > 1:
                    OnceSpyAI.triggered = True
                    before = [g.line_value(1, l) for l in (1, 2, 3)]
                    cands = [{"a": a, "s": 0} for a in acts]
                    pick_best(g, req["chooser"], cands, RandomAI(), {"samples": 1})
                    after = [g.line_value(1, l) for l in (1, 2, 3)]
                    result["before"], result["after"] = before, after
            return super().decide(g, req)

    _driven_engine(seed=555, ai=OnceSpyAI())
    assert result.get("before") == result.get("after")


def _fake_weights(n, seed=0):
    rng = np.random.RandomState(seed)
    return rng.randn(n).astype(np.float64), float(rng.randn())


def test_evaluate_learned_matches_manual_dot_product():
    e = _driven_engine(seed=11, ai=RandomAI())
    coef, intercept = _fake_weights(feature_count())
    x = extract(e, 1)
    expected = float(np.dot(coef, x) + intercept)
    assert evaluate_learned(e, 1, (coef, intercept)) == pytest.approx(expected)


def test_evaluate_learned_auto_expands_when_coef_is_wider():
    """coef 길이가 원본 특징 수보다 크면 -- 즉 교차항까지 학습한
    가중치라면 -- expand_features()를 자동으로 적용해야 한다."""
    e = _driven_engine(seed=12, ai=RandomAI())
    x = extract(e, 1)
    expanded_len = len(expand_features(x))
    coef, intercept = _fake_weights(expanded_len, seed=1)
    expected = float(np.dot(coef, expand_features(x)) + intercept)
    assert evaluate_learned(e, 1, (coef, intercept)) == pytest.approx(expected)


def test_evaluate_learned_requires_weights():
    e = _driven_engine(seed=13, ai=RandomAI())
    with pytest.raises(ValueError):
        evaluate_learned(e, 1, None)


def test_evaluate_learned_short_circuits_on_decided_winner():
    e = _driven_engine(seed=14, ai=RandomAI())
    coef, intercept = _fake_weights(feature_count())
    e.winner = 1
    assert evaluate_learned(e, 1, (coef, intercept)) == 1e6
    assert evaluate_learned(e, 2, (coef, intercept)) == -1e6


def test_load_eval_weights_roundtrips_and_caches(tmp_path):
    coef = np.array([0.1, -0.2, 0.3])
    intercept = np.array([0.5])
    path = str(tmp_path / "w.npz")
    np.savez(path, coef=coef, intercept=intercept)

    w1 = load_eval_weights(path)
    w2 = load_eval_weights(path)  # 캐시 재사용 -- 같은 객체여야 함
    assert w1 is w2
    assert np.allclose(w1[0], coef)
    assert w1[1] == pytest.approx(0.5)
