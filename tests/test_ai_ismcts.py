"""ISMCTSAI(src/game/ai_ismcts.py) 회귀 테스트.

`ai_ismcts_plan.md` §10의 테스트 항목 1~8을 구현한다. 항목 9("scripts/arena.py
기반 승률 벤치마크")는 계획서도 "일반 pytest 스위트와는 분리 권장"이라 여기
넣지 않았다 -- 그건 `scripts/arena_ismcts_vs_heuristic.py`가 대신하며, 이미
실측(iterations=200, 30판, 90.0% ±10.5 유의미 우세)까지 끝났다
(`ai_ismcts_expectedoutput.md` §5.5).

여기 실린 "풀 게임" 테스트는 iterations를 일부러 아주 작게 잡는다 -- 정합성
(크래시/자원누수/합법성) 확인용이지 대전 실력 검증용이 아니다.

UCB1 부호 규약(항목 4)/정보집합 키의 pi0 시점(항목 5)/"무승부 없음"(항목 6)은
`ai_ismcts.py`의 비공개(밑줄) 헬퍼를 직접 테스트한다 -- 이 세 가지는 이
프로젝트에서 가장 조용히 틀리기 쉬운 지점들이라(각각 ai_ismcts_plan.md
§0-1/§3.5, §0-1/§4.2.2, §0-4/§7.7에서 실제로 발견/정정된 결함) 자연 대국의
승패만으로는 검증하기 어렵다 -- 그래서 그 지점을 직접 겨냥한 단위 테스트로
확인한다.
"""

import math
import random
import threading

from src.game.engine import Engine
from src.game.ai_ismcts import (
    ISMCTSAI, _Node, _select_ucb1, _answer_key, _node_key, _reward,
    _candidates_for, _run_iteration,
)
from src.game.ai_heuristic import HeuristicAI
from src.game.ai_random import RandomAI
from src.game.ai_sim import evaluate, DECLINE

PROTOS1 = ["Water", "Fire", "Life"]
PROTOS2 = ["Ice", "Metal", "Death"]


def _driven_engine(seed, ai_modules, steps=20000):
    """RandomAI/HeuristicAI 계열이 엔진 seed가 아니라 파이썬 전역 random도
    쓰므로(하위 결정), 재현성을 위해 여기서도 고정한다 -- 기존
    tests/test_ai_sim.py의 _driven_engine과 동일한 이유."""
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


# ---------------------------------------------------------------------------
# 1. decide()는 항상 합법 액션을 반환한다
# ---------------------------------------------------------------------------

class _LegalityCheckingISMCTS(ISMCTSAI):
    """action 결정마다 legal_actions()에 실제로 포함되는지 확인하고,
    위반이 있으면 기록해둔다(테스트에서 나중에 검사)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.violations = []

    def decide(self, g, req):
        if req.get("type") == "action":
            legal = g.legal_actions(req["chooser"])
            result = super().decide(g, req)
            if result not in legal:
                self.violations.append({"chooser": req["chooser"], "result": result})
            return result
        return super().decide(g, req)


def test_decide_always_returns_a_legal_action():
    for seed in range(3):
        ai = _LegalityCheckingISMCTS(iterations=10, rollout_turn_cap=6)
        e = _driven_engine(seed, {1: ai, 2: HeuristicAI()})
        assert e.error is None
        assert ai.violations == []


# ---------------------------------------------------------------------------
# 2. 원본(살아있는) 엔진을 절대 변형하지 않는다
# ---------------------------------------------------------------------------

def test_decide_does_not_mutate_the_live_engine():
    result = {}

    class OnceSpyAI(RandomAI):
        triggered = False

        def decide(self, g, req):
            if not OnceSpyAI.triggered and req.get("type") == "action":
                acts = g.legal_actions(req["chooser"])
                if len(acts) > 1:
                    OnceSpyAI.triggered = True
                    before_lines = [g.line_value(1, l) for l in (1, 2, 3)]
                    before_hand = sorted((c.proto, c.value) for c in g.players[1]["hand"])
                    ISMCTSAI(iterations=10, rollout_turn_cap=6).decide(g, req)
                    after_lines = [g.line_value(1, l) for l in (1, 2, 3)]
                    after_hand = sorted((c.proto, c.value) for c in g.players[1]["hand"])
                    result["before"] = (before_lines, before_hand)
                    result["after"] = (after_lines, after_hand)
            return super().decide(g, req)

    _driven_engine(seed=555, ai_modules={1: OnceSpyAI(), 2: RandomAI()}, steps=500)
    assert result.get("before") is not None
    assert result["before"] == result["after"]


# ---------------------------------------------------------------------------
# 3. 시드 없는 엔진에서 안전하게 폴백 (HeuristicAI와 동일하게 동작)
# ---------------------------------------------------------------------------

def test_decide_falls_back_to_heuristic_when_no_seed():
    e = Engine(protocols1=PROTOS1, protocols2=PROTOS2, seed=None)
    e.build_decks()  # prompt/emit을 안 거치는 순수 동기 호출이라 .start() 없이도 안전
    assert e.clone_at_decision() is None

    req = {"type": "action", "chooser": 1}
    ismcts_answer = ISMCTSAI(iterations=20).decide(e, req)
    heuristic_answer = HeuristicAI().decide(e, req)
    assert ismcts_answer == heuristic_answer


# ---------------------------------------------------------------------------
# 4. UCB1 부호 규약: 내 차례 노드는 나에게 좋은 쪽, 상대 차례 노드는
#    상대에게 좋은(=나에게 나쁜) 쪽을 우선해야 한다 (minimax)
# ---------------------------------------------------------------------------

class _StubSim:
    """_select_ucb1이 필요로 하는 최소 인터페이스(aux_rng)만 흉내내는 가짜
    sim -- 실제 Engine/스레드 없이 UCB1 수식 자체만 검증. 2026-08-03
    개편으로 _select_ucb1이 후보 키 목록을 외부에서 받게 되면서
    legal_actions()는 더 이상 필요 없어졌다."""

    def aux_rng(self, n):
        return 1  # 이 테스트의 후보는 전부 이미 방문된 상태라 실제로는 안 쓰임


def _two_actions_with_stats(chooser, pi0):
    actions = [{"kind": "play", "uid": 1, "line": 1, "faceUp": True},
               {"kind": "play", "uid": 2, "line": 1, "faceUp": True}]
    good_key, bad_key = _answer_key(actions[0]), _answer_key(actions[1])
    node = _Node(chooser=chooser)
    node.visits = 20
    node.N = {good_key: 10, bad_key: 10}
    node.W = {good_key: 8.0, bad_key: -8.0}  # 항상 pi0 시점 값 (설계상 불변)
    node.answer_of = {good_key: actions[0], bad_key: actions[1]}
    return node, actions, good_key, bad_key


def test_select_ucb1_prefers_pi0_favorable_action_at_own_node():
    node, actions, good_key, bad_key = _two_actions_with_stats(chooser=1, pi0=1)
    picked = _select_ucb1(node, _StubSim(), [good_key, bad_key], pi0=1, c_ucb=1.41)
    assert picked == good_key


def test_select_ucb1_prefers_pi0_unfavorable_action_at_opponent_node():
    node, actions, good_key, bad_key = _two_actions_with_stats(chooser=2, pi0=1)
    picked = _select_ucb1(node, _StubSim(), [good_key, bad_key], pi0=1, c_ucb=1.41)
    assert picked == bad_key


def test_select_ucb1_expands_untried_actions_before_using_ucb_score():
    """N이 0인(미방문) 액션이 하나라도 있으면, W/UCB 점수와 무관하게 그것부터
    골라야 한다(표준 UCT 관례)."""
    actions = [{"kind": "play", "uid": 1, "line": 1, "faceUp": True},
               {"kind": "play", "uid": 2, "line": 1, "faceUp": True}]
    tried_key, untried_key = _answer_key(actions[0]), _answer_key(actions[1])
    node = _Node(chooser=1)
    node.visits = 5
    node.N = {tried_key: 5}  # untried_key는 아직 등록 안 됨(N.get 기본값 0)
    node.W = {tried_key: 100.0}  # 압도적으로 좋아 보여도
    node.answer_of = {tried_key: actions[0]}

    picked = _select_ucb1(node, _StubSim(), [tried_key, untried_key], pi0=1, c_ucb=1.41)
    assert picked == untried_key
    # untried_key는 answer_of에 아직 없다 -- _run_iteration이 매핑을
    # 채워주는 계약이라, _select_ucb1 단독 호출로는 값이 안 생긴다.
    assert untried_key not in node.answer_of


# ---------------------------------------------------------------------------
# 5. 정보집합 키는 pi0 시점 -- 상대 손패 "내용"이 달라도(장수만 같으면)
#    같은 노드로 합쳐져야 한다 (ai_ismcts_plan.md §0-1의 핵심 정정 사항)
# ---------------------------------------------------------------------------

def test_node_key_ignores_opponent_hand_identity():
    e1 = Engine(protocols1=PROTOS1, protocols2=PROTOS2)
    e2 = Engine(protocols1=PROTOS1, protocols2=PROTOS2)
    e1.players[1]["hand"] = [e1.new_card("Water", v, 1) for v in (0, 1, 2)]
    e2.players[1]["hand"] = [e2.new_card("Water", v, 1) for v in (0, 1, 2)]
    e1.players[2]["hand"] = [e1.new_card("Ice", v, 2) for v in (1, 2, 3)]
    e2.players[2]["hand"] = [e2.new_card("Metal", v, 2) for v in (0, 1, 2)]  # 다른 정체, 같은 장수

    req = {"type": "action", "chooser": 2}  # 상대 차례 노드인 상황을 흉내
    assert _node_key(e1, req, pi0=1) == _node_key(e2, req, pi0=1)


def test_node_key_distinguishes_pi0_own_hand():
    """반대로 pi0 자신의 손패가 다르면 (당연히) 달라야 한다 -- 함수가
    그냥 모든 걸 무시해서 우연히 통과하는 게 아님을 확인."""
    e1 = Engine(protocols1=PROTOS1, protocols2=PROTOS2)
    e2 = Engine(protocols1=PROTOS1, protocols2=PROTOS2)
    e1.players[1]["hand"] = [e1.new_card("Water", 0, 1)]
    e2.players[1]["hand"] = [e2.new_card("Water", 1, 1)]
    e1.players[2]["hand"] = []
    e2.players[2]["hand"] = []

    req = {"type": "action", "chooser": 1}
    assert _node_key(e1, req, pi0=1) != _node_key(e2, req, pi0=1)


def test_node_key_distinguishes_prompt_type_at_the_same_board_state():
    """같은 보드 상태라도 프롬프트 종류(예: chooseCard vs chooseLine)가
    다르면 다른 노드여야 한다 -- 하위 결정 분기(2026-08-03)를 추가하며
    새로 생긴 충돌 위험. req["type"]을 키에 넣어 방지한다."""
    e = Engine(protocols1=PROTOS1, protocols2=PROTOS2)
    req_a = {"type": "chooseCard", "chooser": 1, "intent": "delete"}
    req_b = {"type": "chooseLine", "chooser": 1, "intent": "delete"}
    assert _node_key(e, req_a, pi0=1) != _node_key(e, req_b, pi0=1)


def test_node_key_distinguishes_intent_for_the_same_prompt_type():
    """같은 chooseCard라도 intent(지울지/뒤집을지)가 다르면 다른 질문이라
    다른 노드여야 한다."""
    e = Engine(protocols1=PROTOS1, protocols2=PROTOS2)
    req_a = {"type": "chooseCard", "chooser": 1, "intent": "delete"}
    req_b = {"type": "chooseCard", "chooser": 1, "intent": "flip"}
    assert _node_key(e, req_a, pi0=1) != _node_key(e, req_b, pi0=1)


# ---------------------------------------------------------------------------
# 6. "무승부 없음": 승부 미결 상태는 절대 0.0이 아니라 evaluate() 기반
#    연속값을 써야 한다 (ai_ismcts_plan.md §0-4/§7.7의 핵심 정정 사항)
# ---------------------------------------------------------------------------

def test_reward_is_plus_one_for_win_and_minus_one_for_loss():
    e = Engine(protocols1=PROTOS1, protocols2=PROTOS2)
    e.winner = 1
    assert _reward(e, 1, evaluate, None, 200.0) == 1.0
    assert _reward(e, 2, evaluate, None, 200.0) == -1.0


def test_reward_uses_evaluate_and_never_zero_when_undecided():
    e = Engine(protocols1=PROTOS1, protocols2=PROTOS2)
    e.build_decks()
    # 완전 대칭이면 evaluate()가 우연히 0.0이 나올 수 있으니, 한쪽 손패를
    # 한 장 늘려 확실히 비대칭으로 만든다.
    e.players[1]["hand"].append(e.new_card("Water", 3, 1))

    z = _reward(e, 1, evaluate, None, 200.0)
    assert z == math.tanh(evaluate(e, 1) / 200.0)
    assert z != 0.0


# ---------------------------------------------------------------------------
# 7. 자원 누수 없음: decide()가 끝나면 임시 클론 스레드가 전부 정리돼야 함
# ---------------------------------------------------------------------------

def test_decide_does_not_leak_threads():
    before = threading.active_count()
    ai = ISMCTSAI(iterations=10, rollout_turn_cap=6)
    _driven_engine(seed=2024, ai_modules={1: ai, 2: HeuristicAI()})
    after = threading.active_count()
    assert after == before


# ---------------------------------------------------------------------------
# 8. planRearrange 시그니처 확인: Control을 소비하는 상황(스레드 밖에서
#    prompt()를 거치지 않는 spend_control의 AI 직접호출 경로)이
#    ISMCTSAI가 낀 판에서도 예외 없이 진행돼야 함
# ---------------------------------------------------------------------------

def test_control_rearrange_path_does_not_crash():
    """HeuristicAI.planRearrange를 계측해서, 이 테스트가 실제로 그 경로를
    거치는지(발동 횟수 > 0)까지 같이 확인한다 -- 안 거치면 "통과"가
    아무것도 검증 못 한 셈이므로."""
    calls = {"n": 0}
    orig = HeuristicAI.planRearrange

    def counting_plan_rearrange(self, g, pi, compiling_line):
        calls["n"] += 1
        return orig(self, g, pi, compiling_line)

    HeuristicAI.planRearrange = counting_plan_rearrange
    try:
        for seed in range(4):
            e = _driven_engine(
                seed,
                ai_modules={1: ISMCTSAI(iterations=8, rollout_turn_cap=6),
                            2: ISMCTSAI(iterations=8, rollout_turn_cap=6)},
            )
            assert e.error is None
    finally:
        HeuristicAI.planRearrange = orig

    assert calls["n"] > 0, "Control 재배치 경로가 한 번도 발동하지 않아 이 테스트가 그 경로를 검증하지 못함"


# ---------------------------------------------------------------------------
# 9. _candidates_for -- 하위 결정 분기 후보 생성 (Lua ai_mcts.lua의
#    candidatesFor() 대응, 2026-08-03 개편으로 신설)
# ---------------------------------------------------------------------------

def test_candidates_for_yesno_is_always_true_false():
    e = Engine(protocols1=PROTOS1, protocols2=PROTOS2)
    assert _candidates_for(e, {"type": "yesno", "chooser": 1}) == [True, False]


def test_candidates_for_choose_card_includes_decline_when_optional():
    e = Engine(protocols1=PROTOS1, protocols2=PROTOS2)
    req = {"type": "chooseCard", "chooser": 1, "candidates": ["u1", "u2"], "optional": True}
    assert _candidates_for(e, req) == ["u1", "u2", DECLINE]


def test_candidates_for_choose_card_returns_none_when_too_few_or_too_many():
    e = Engine(protocols1=PROTOS1, protocols2=PROTOS2)
    assert _candidates_for(e, {"type": "chooseCard", "chooser": 1, "candidates": ["u1"]}) is None
    many = {"type": "chooseCard", "chooser": 1, "candidates": [f"u{i}" for i in range(20)]}
    assert _candidates_for(e, many) is None


def test_candidates_for_choose_hand_cards_only_when_single_pick():
    e = Engine(protocols1=PROTOS1, protocols2=PROTOS2)
    e.players[1]["hand"] = [e.new_card("Water", v, 1) for v in (0, 1, 2)]
    req = {"type": "chooseHandCards", "chooser": 1, "player": 1, "count": 1, "min": 1}
    out = _candidates_for(e, req)
    assert len(out) == 3
    assert all(isinstance(v, list) and len(v) == 1 for v in out)

    multi = {"type": "chooseHandCards", "chooser": 1, "player": 1, "count": 2, "min": 2}
    assert _candidates_for(e, multi) is None


def test_candidates_for_choose_hand_cards_adds_decline_when_optional():
    e = Engine(protocols1=PROTOS1, protocols2=PROTOS2)
    e.players[1]["hand"] = [e.new_card("Water", 0, 1)]
    req = {"type": "chooseHandCards", "chooser": 1, "player": 1, "count": 1, "min": 0}
    assert DECLINE in _candidates_for(e, req)


def test_candidates_for_plan_rearrange_enumerates_every_single_swap_both_sides():
    e = Engine(protocols1=PROTOS1, protocols2=PROTOS2)
    req = {"type": "planRearrange", "chooser": 1}
    out = _candidates_for(e, req)
    assert DECLINE in out
    plans = [v for v in out if v is not DECLINE]
    # 라인 3개 중 2개를 고르는 스왑 = 3가지, 양쪽 플레이어 = 6개
    assert len(plans) == 6
    assert {p["who"] for p in plans} == {1, 2}
    for p in plans:
        assert sorted(p["order"].values()) == [1, 2, 3]
        assert p["order"] != {1: 1, 2: 2, 3: 3}  # 항상 실제 스왑(항등이 아님)


def test_candidates_for_unbranchable_types_return_none():
    e = Engine(protocols1=PROTOS1, protocols2=PROTOS2)
    assert _candidates_for(e, {"type": "confirmRefresh", "chooser": 1}) is None
    assert _candidates_for(e, {"type": "rearrange", "chooser": 1}) is None


# ---------------------------------------------------------------------------
# 10. _answer_key -- 분기 답변 종류별 키 (Lua ai_mcts.lua의 keyOf() 대응)
# ---------------------------------------------------------------------------

def test_answer_key_distinguishes_every_shape():
    action = {"kind": "play", "uid": 1, "line": 2, "faceUp": True}
    plan = {"who": 1, "order": {1: 2, 2: 1, 3: 3}}
    uids = ["u1"]
    keys = [
        _answer_key(DECLINE),
        _answer_key(action),
        _answer_key(plan),
        _answer_key(uids),
        _answer_key(True),
        _answer_key(False),
        _answer_key(2),
        _answer_key("draw"),
    ]
    assert len(set(keys)) == len(keys)  # 전부 서로 달라야 함


def test_answer_key_is_stable_for_equal_values():
    a1 = {"kind": "play", "uid": 5, "line": 1, "faceUp": False}
    a2 = {"kind": "play", "uid": 5, "line": 1, "faceUp": False}
    assert _answer_key(a1) == _answer_key(a2)


# ---------------------------------------------------------------------------
# 11. 하위 결정 분기가 실제로 트리에 반영되는지 -- 2026-08-03 개편의 핵심
#     회귀. 배관만 있고 실제 대국에서 한 번도 안 타면 의미가 없으므로,
#     실제 게임을 굴리면서 action 이외 타입에서 _candidates_for가
#     non-None을 반환한 적이 있는지 계측한다.
# ---------------------------------------------------------------------------

def test_sub_decision_branching_is_actually_exercised_during_real_play():
    import src.game.ai_ismcts as ai_ismcts_module
    branched_types = set()
    orig = ai_ismcts_module._candidates_for

    def spying(sim, req):
        out = orig(sim, req)
        if out is not None and req["type"] != "action":
            branched_types.add(req["type"])
        return out

    ai_ismcts_module._candidates_for = spying
    try:
        for seed in range(6):
            ai = ISMCTSAI(iterations=15, rollout_turn_cap=6)
            e = _driven_engine(seed, {1: ai, 2: HeuristicAI()})
            assert e.error is None
    finally:
        ai_ismcts_module._candidates_for = orig

    assert branched_types, "6판 동안 action 이외의 하위 결정이 한 번도 분기되지 않음"
