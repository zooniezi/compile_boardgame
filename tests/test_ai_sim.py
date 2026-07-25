"""ai_sim.py -- 결정화(determinize) / 평가(evaluate) / 1수 앞보기(pick_best)
회귀 테스트.
"""

import random

from src.game.engine import Engine
from src.game.ai_random import RandomAI
from src.game.ai_sim import determinize, evaluate, pick_best


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
