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

import numpy as np
import pytest

from src.game.engine import Engine
from src.game.ai_ismcts import (
    ISMCTSAI, _Node, _select_ucb1, _select_puct, _answer_key, _node_key, _reward,
    _candidates_for, _run_iteration, _compile_lock_reward_correction,
    _MY_LOCK_CORRECTION, _OPP_LOCK_CORRECTION,
)
from src.game.ai_features import feature_count as state_feature_count
from src.game.ai_action_features import feature_count as action_feature_count
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


def test_c_ucb_and_c_puct_have_independent_defaults():
    """트리 내부 노드용 c_ucb와 루트 전용 c_puct는 하나로 합쳐진 상수가
    아니라 각자 다른 기본값을 갖는 별개 파라미터여야 한다."""
    ai = ISMCTSAI()
    assert ai.c_ucb == 0.7
    assert ai.c_puct == 1.5


def test_mlp_and_learned_presets_inherit_c_ucb_c_puct_defaults():
    from src.game.ai_ismcts_mlp import ISMCTSMLPAI
    from src.game.ai_ismcts_learned import ISMCTSLearnedAI
    assert ISMCTSMLPAI().c_ucb == 0.7
    assert ISMCTSMLPAI().c_puct == 1.5
    assert ISMCTSLearnedAI().c_ucb == 0.7
    assert ISMCTSLearnedAI().c_puct == 1.5


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
# 6.1 학습된 평가함수용 컴파일 락 보정 (260805, 0단계에서 손튜닝 evaluate()
#     에만 반영하고 미뤄뒀던 부분) -- _compile_lock_reward_correction 자체와,
#     _reward()가 evaluate_learned류에만 이 보정을 적용하는지 확인.
# ---------------------------------------------------------------------------

def test_compile_lock_reward_correction_penalizes_my_false_lead():
    """내가 임계값 이상 우세해도 상대 Lust_0류 봉쇄로 실제 컴파일이 안
    되면, 그만큼 보상을 깎아야 한다."""
    e = Engine(protocols1=["Fire", "Water", "Life"], protocols2=["Lust", "Metal", "Death"])
    e.control = 2
    lust0 = e.new_card("Lust", 0, 2)
    lust0.face_up = True
    e.players[2]["stacks"][1].append(lust0)
    for _ in range(2):
        c = e.new_card("Fire", 5, 1)
        c.face_up = True
        e.players[1]["stacks"][1].append(c)  # 라인1 값=10 (임계값 이상, 상대는 0)
    assert _compile_lock_reward_correction(e, 1) == pytest.approx(_MY_LOCK_CORRECTION)


def test_compile_lock_reward_correction_rewards_opponent_false_lead():
    """반대 방향: 상대가 봉쇄돼 실제로는 위협이 아닌데 임계값 이상
    우세하면, 그만큼 내 보상을 올려줘야 한다."""
    e = Engine(protocols1=["Lust", "Water", "Fire"], protocols2=["Fire", "Metal", "Death"])
    e.control = 1
    lust0 = e.new_card("Lust", 0, 1)
    lust0.face_up = True
    e.players[1]["stacks"][1].append(lust0)
    for _ in range(2):
        c = e.new_card("Fire", 5, 2)
        c.face_up = True
        e.players[2]["stacks"][1].append(c)
    assert _compile_lock_reward_correction(e, 1) == pytest.approx(_OPP_LOCK_CORRECTION)


def test_compile_lock_reward_correction_zero_when_nobody_locked():
    e = Engine(protocols1=PROTOS1, protocols2=PROTOS2)
    assert _compile_lock_reward_correction(e, 1) == 0.0


def test_reward_applies_lock_correction_only_to_registered_learned_eval_fns():
    """evaluate()(손튜닝, 이미 자체 게이트 있음)는 이 보정 대상이 아니고,
    _LOCK_CORRECTED_EVAL_FNS에 등록된 함수만 보정이 적용돼야 한다 --
    이중 적용(evaluate() 자체 게이트 + 이 보정 둘 다)을 막는 핵심 불변식."""
    e = Engine(protocols1=["Fire", "Water", "Life"], protocols2=["Lust", "Metal", "Death"])
    e.control = 2
    lust0 = e.new_card("Lust", 0, 2)
    lust0.face_up = True
    e.players[2]["stacks"][1].append(lust0)
    for _ in range(2):
        c = e.new_card("Fire", 5, 1)
        c.face_up = True
        e.players[1]["stacks"][1].append(c)

    def fake_learned_eval(sim, pi, w=None):
        return 0.0  # 원시 점수 0 -- tanh(0/scale)=0이라 보정만 순수하게 드러남

    orig = ai_ismcts_module._LOCK_CORRECTED_EVAL_FNS
    ai_ismcts_module._LOCK_CORRECTED_EVAL_FNS = (fake_learned_eval,)
    try:
        corrected = _reward(e, 1, fake_learned_eval, None, 200.0)
    finally:
        ai_ismcts_module._LOCK_CORRECTED_EVAL_FNS = orig
    uncorrected = _reward(e, 1, evaluate, None, 200.0)  # evaluate는 등록 목록 밖

    assert corrected == pytest.approx(_MY_LOCK_CORRECTION)
    assert uncorrected != pytest.approx(_MY_LOCK_CORRECTION)


def test_reward_clamps_to_valid_range_after_correction():
    """tanh(score/scale)가 이미 ±1에 가까운 상태에서 보정까지 더해지면
    범위를 벗어날 수 있으니 [-1, 1]로 다시 잘라야 한다."""
    e = Engine(protocols1=["Lust", "Water", "Fire"], protocols2=["Fire", "Metal", "Death"])
    e.control = 1
    lust0 = e.new_card("Lust", 0, 1)
    lust0.face_up = True
    e.players[1]["stacks"][1].append(lust0)
    for _ in range(2):
        c = e.new_card("Fire", 5, 2)
        c.face_up = True
        e.players[2]["stacks"][1].append(c)

    def fake_learned_eval(sim, pi, w=None):
        return 1e9  # tanh(.../scale)가 이미 사실상 1.0

    orig = ai_ismcts_module._LOCK_CORRECTED_EVAL_FNS
    ai_ismcts_module._LOCK_CORRECTED_EVAL_FNS = (fake_learned_eval,)
    try:
        result = _reward(e, 1, fake_learned_eval, None, 200.0)
    finally:
        ai_ismcts_module._LOCK_CORRECTED_EVAL_FNS = orig
    assert result == 1.0  # 1.0 + _OPP_LOCK_CORRECTION(0.30)이 아니라 1.0으로 clamp


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
# 9. _candidates_for -- 하위 결정 분기 후보 생성 (2026-08-03 개편으로 신설)
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
# 10. _answer_key -- 분기 답변 종류별 키
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


# ---------------------------------------------------------------------------
# 12. _select_puct -- 3단계 학습된 루트 정책(PUCT). action_scores(ai_ismcts_
#     policy.py)를 몽키패치해서 신경망 없이 PUCT 수식 자체(사전확률 반영,
#     FPU=0.5, uniform_mix)만 검증한다.
# ---------------------------------------------------------------------------

import src.game.ai_ismcts as ai_ismcts_module


def _three_actions():
    return [
        {"kind": "play", "uid": 1, "line": 1, "faceUp": True},
        {"kind": "play", "uid": 2, "line": 1, "faceUp": True},
        {"kind": "play", "uid": 3, "line": 1, "faceUp": True},
    ]


def test_select_puct_prefers_highest_prior_action_when_all_unvisited(monkeypatch):
    """전부 미방문(N=0)이면 Q는 셋 다 FPU=0.5로 동률이라, 사전확률(softmax
    logit)이 가장 큰 후보가 이겨야 한다."""
    actions = _three_actions()
    keys = [_answer_key(a) for a in actions]
    node = _Node(chooser=1)
    node.answer_of = dict(zip(keys, actions))

    monkeypatch.setattr(ai_ismcts_module, "action_scores",
                         lambda sim, pi, acts, w: [0.0, 5.0, -5.0])
    picked = _select_puct(node, _StubSim(), keys, actions, pi0=1, c_puct=1.41,
                           policy_w=object())
    assert picked == keys[1]


def test_select_puct_uses_fpu_half_not_zero_for_unvisited():
    """핵심 버그 픽스 회귀: 미방문 후보의 Q를 0으로 두면
    첫 평가된 자식(음의 보상)이 형제를 다 굶긴다. 여기서는 이미 방문됐고
    평균 보상이 뚜렷하게 음수인(-0.9) 후보 하나와, 아직 미방문인 후보
    둘을 두고, 두 정책 모두(사전확률이 완전히 균등이라 uniform_mix로 켜서
    prior 차이가 없게 만듦) U항이 같다면 미방문 쪽이 FPU=0.5로 시작해
    방문한 나쁜 후보(-0.9)보다 항상 우선돼야 한다."""
    actions = _three_actions()
    keys = [_answer_key(a) for a in actions]
    node = _Node(chooser=1)
    node.answer_of = dict(zip(keys, actions))
    node.visits = 20
    node.N = {keys[0]: 20}
    node.W = {keys[0]: -18.0}  # 평균 -0.9

    def _flat_scores(sim, pi, acts, w):
        return [0.0, 0.0, 0.0]  # 사전확률이 완전히 균등하도록

    orig = ai_ismcts_module.action_scores
    ai_ismcts_module.action_scores = _flat_scores
    try:
        picked = _select_puct(node, _StubSim(), keys, actions, pi0=1, c_puct=1.41,
                               policy_w=object())
    finally:
        ai_ismcts_module.action_scores = orig
    # keys[1]/keys[2]는 미방문(Q=FPU=0.5), keys[0]은 방문했지만 Q=-0.9 --
    # 어느 미방문 쪽이 뽑히든(균등 prior라 동률) keys[0]만 아니면 통과.
    assert picked in (keys[1], keys[2])


def test_select_puct_only_used_at_root_key_not_deeper_nodes():
    """_run_iteration은 policy_w가 있어도 root_key와 일치하는 노드에서만
    _select_puct를 쓰고, 그 외 노드는 여전히 _select_ucb1이어야 한다
    ("루트 정책"이라는 이름 그대로) -- 실제 대국을 굴리며 두 함수 호출
    횟수를 계측해 확인한다(하위 결정 분기가 있으니 루트가 아닌 노드도
    반드시 여러 번 방문됨)."""
    ucb1_calls, puct_calls = [], []
    orig_ucb1 = ai_ismcts_module._select_ucb1
    orig_puct = ai_ismcts_module._select_puct

    def spy_ucb1(*a, **kw):
        ucb1_calls.append(1)
        return orig_ucb1(*a, **kw)

    def spy_puct(*a, **kw):
        puct_calls.append(1)
        return orig_puct(*a, **kw)

    fake_w = [(
        np.zeros((state_feature_count() + action_feature_count(), 1)),
        np.zeros(1),
    )]

    ai_ismcts_module._select_ucb1 = spy_ucb1
    ai_ismcts_module._select_puct = spy_puct
    try:
        ai = ISMCTSAI(iterations=15, rollout_turn_cap=6, policy_w=fake_w)
        e = _driven_engine(seed=2, ai_modules={1: ai, 2: HeuristicAI()})
        assert e.error is None
    finally:
        ai_ismcts_module._select_ucb1 = orig_ucb1
        ai_ismcts_module._select_puct = orig_puct

    assert puct_calls, "policy_w가 있는데 _select_puct가 한 번도 안 불림"
    assert ucb1_calls, "하위 결정 분기(루트가 아닌 노드)는 여전히 UCB1을 써야 하는데 한 번도 안 불림"


def test_ismcts_with_policy_w_none_is_unaffected_baseline():
    """policy_w=None(기본값)이면 이전과 동일하게 전부 _select_ucb1만 써야
    한다 -- 하위 호환 회귀."""
    puct_calls = []
    orig_puct = ai_ismcts_module._select_puct
    ai_ismcts_module._select_puct = lambda *a, **kw: puct_calls.append(1) or orig_puct(*a, **kw)
    try:
        ai = ISMCTSAI(iterations=15, rollout_turn_cap=6)  # policy_w 생략
        e = _driven_engine(seed=3, ai_modules={1: ai, 2: HeuristicAI()})
        assert e.error is None
    finally:
        ai_ismcts_module._select_puct = orig_puct
    assert puct_calls == []


# ---------------------------------------------------------------------------
# 13. decide_with_stats() / 디리클레 탐험 노이즈 -- 진짜 RL(260803_RL_plan.md)
#     의 자기대국 데이터 생성이 쓸 방문분포 노출 경로. decide()(경쟁 플레이,
#     아레나, 웹 서비스)는 이 배치로 전혀 건드리지 않는다는 게 핵심 불변식.
# ---------------------------------------------------------------------------

from src.game.ai_ismcts import _dirichlet_noise, _search  # noqa: E402


def test_decide_with_stats_visit_counts_sum_to_iterations_and_cover_legal_actions():
    """루트에서 벗어난 반복이 없다면(클론 실패 없음) 루트 자식들의 방문
    횟수 합은 정확히 iterations와 같아야 한다 -- 반복마다 정확히 한 번씩
    루트를 거치기 때문.

    ai1=True/ai2=True로 돌리면 엔진이 결정을 내부에서 즉시
    ai_module.decide()로 처리해버려서 바깥 pending 루프에는 "action"
    요청이 노출되지 않는다(§11 test_sub_decision_branching_...와 동일한
    함정) -- 그래서 감시용 래퍼(ai=)를 꽂아 엔진이 실제로 넘겨주는 살아있는
    g/req로 decide_with_stats()를 호출해야 한다."""
    result = {}

    class _StatsSpyAI(ISMCTSAI):
        def decide(self, g, req):
            if "chosen" not in result and req.get("type") == "action" \
                    and len(g.legal_actions(req["chooser"])) > 1:
                chosen, visits = self.decide_with_stats(g, req)
                result["chosen"] = chosen
                result["visits"] = visits
                result["legal"] = g.legal_actions(req["chooser"])
            return super().decide(g, req)

    for seed in range(5):
        ai = _StatsSpyAI(iterations=30, rollout_turn_cap=4)
        e = Engine(protocols1=PROTOS1, protocols2=PROTOS2, ai1=True, ai2=True,
                   seed=seed, ai_modules={1: ai, 2: RandomAI()})
        e.start()
        n = 0
        while e.pending is not None and n < 200 and "chosen" not in result:
            n += 1
            if e.pending["kind"] == "anim":
                e.advance_anim()
            else:
                e.answer(None)
        if "chosen" in result:
            break

    assert "chosen" in result, "5개 시드 동안 여러 후보가 있는 action 프롬프트를 못 만남"
    assert result["chosen"] in result["legal"]
    assert result["visits"]
    assert all(v[0] in result["legal"] for v in result["visits"])
    assert all(v[1] > 0 for v in result["visits"])
    assert sum(v[1] for v in result["visits"]) == 30


def test_decide_with_stats_falls_back_to_trivial_distribution_when_no_choice():
    """후보가 하나(또는 0개)뿐이면 실제 탐색을 안 하므로 그 액션 하나짜리
    자명한 분포를 반환해야 한다."""
    class _OneActionGame:
        def legal_actions(self, pi):
            return [{"kind": "refresh"}]

    ai = ISMCTSAI(iterations=10)
    chosen, visits = ai.decide_with_stats(_OneActionGame(), {"chooser": 1, "type": "action"})
    assert chosen == {"kind": "refresh"}
    assert visits == [({"kind": "refresh"}, 1)]


def test_dirichlet_noise_is_a_valid_probability_distribution():
    noise = _dirichlet_noise(5, 0.3, lambda n: 1)  # 결정론적 시드로도 유효성만 확인
    assert len(noise) == 5
    assert all(x > 0 for x in noise)
    assert abs(sum(noise) - 1.0) < 1e-9


def test_root_dirichlet_noise_can_override_dominant_policy_preference():
    """eps=1.0(사전확률을 노이즈로 완전히 대체)이면, 정책이 압도적으로
    선호하는 후보라도 노이즈가 미는 쪽으로 뒤집힐 수 있어야 한다 --
    노이즈 혼합 수식이 실제로 선택에 영향을 준다는 걸 확인(정책 점수는
    몽키패치로 고정해서 신경망 없이 수식만 검증, §12와 동일 요령)."""
    actions = _three_actions()[:2]
    keys = [_answer_key(a) for a in actions]
    node = _Node(chooser=1)
    node.answer_of = dict(zip(keys, actions))

    orig_scores = ai_ismcts_module.action_scores
    orig_noise = ai_ismcts_module._dirichlet_noise
    ai_ismcts_module.action_scores = lambda sim, pi, acts, w: [100.0, -100.0]  # A를 압도적으로 선호
    ai_ismcts_module._dirichlet_noise = lambda n, alpha, rng: [0.01, 0.99]     # 노이즈는 B를 압도적으로 선호
    try:
        no_noise = ai_ismcts_module._select_puct(
            node, _StubSim(), keys, actions, pi0=1, c_puct=1.41, policy_w=object(),
            root_dirichlet_alpha=None)
        full_noise = ai_ismcts_module._select_puct(
            node, _StubSim(), keys, actions, pi0=1, c_puct=1.41, policy_w=object(),
            root_dirichlet_alpha=0.3, root_dirichlet_eps=1.0)
    finally:
        ai_ismcts_module.action_scores = orig_scores
        ai_ismcts_module._dirichlet_noise = orig_noise

    assert no_noise == keys[0]
    assert full_noise == keys[1]


def test_search_return_root_is_opt_in_and_backward_compatible():
    """return_root=False(기본값)면 예전처럼 답 하나만 반환 -- 시그니처
    확장이 기존 호출부(ISMCTSAI.decide())에 영향 없음을 직접 확인.
    (ai1=True/ai2=True 함정은 위 테스트와 동일 -- 감시 래퍼로 살아있는
    g/req를 얻는다.)"""
    result = {}

    class _SearchSpyAI(RandomAI):
        def decide(self, g, req):
            if "done" not in result and req.get("type") == "action" \
                    and len(g.legal_actions(req["chooser"])) > 1:
                result["done"] = True
                plain = _search(g, req["chooser"], req, 10, 1.41, 1.5, HeuristicAI(), 4,
                                 evaluate, None, 200.0)
                with_root = _search(g, req["chooser"], req, 10, 1.41, 1.5, HeuristicAI(), 4,
                                     evaluate, None, 200.0, return_root=True)
                result["plain_is_tuple"] = isinstance(plain, tuple)
                result["with_root_ok"] = isinstance(with_root, tuple) and len(with_root) == 2
            return super().decide(g, req)

    for seed in range(5):
        e = Engine(protocols1=PROTOS1, protocols2=PROTOS2, seed=seed,
                   ai1=True, ai2=True, ai_modules={1: _SearchSpyAI(), 2: RandomAI()})
        e.start()
        n = 0
        while e.pending is not None and n < 200 and "done" not in result:
            n += 1
            if e.pending["kind"] == "anim":
                e.advance_anim()
            else:
                e.answer(None)
        if "done" in result:
            break

    assert "done" in result, "5개 시드 동안 여러 후보가 있는 action 프롬프트를 못 만남"
    assert result["plain_is_tuple"] is False
    assert result["with_root_ok"] is True


# ---------------------------------------------------------------------------
# 14. 루트 가독성(legibility) 동점 처리 -- "탐색이 통계적으로 동률로
#     판단한 후보들 중에서는 라이브 라인 + 앞면을 우선한다"는 계획
#     그대로: 방문수 차이가 진짜 가치 차이가 아니라 잡음일 때만 개입하고,
#     진짜 격차(eps 밖)는 절대 건드리지 않는다.
# ---------------------------------------------------------------------------

from src.game.ai_ismcts import _legibility, _apply_legibility_tiebreak  # noqa: E402


class _StubG:
    """`_legibility()`가 필요로 하는 최소 인터페이스(players[pi]["compiled"])
    만 흉내내는 가짜 게임 상태."""

    def __init__(self, compiled_p1=None, compiled_p2=None):
        self.players = {
            1: {"compiled": compiled_p1 or {1: False, 2: False, 3: False}},
            2: {"compiled": compiled_p2 or {1: False, 2: False, 3: False}},
        }


def test_legibility_scores_face_up_live_line_highest():
    g = _StubG(compiled_p1={1: False, 2: True, 3: False})
    face_up_live = {"kind": "play", "line": 1, "faceUp": True}
    face_down_live = {"kind": "play", "line": 1, "faceUp": False}
    face_up_dead = {"kind": "play", "line": 2, "faceUp": True}
    face_down_dead = {"kind": "play", "line": 2, "faceUp": False}
    assert _legibility(g, 1, face_up_live) == 3
    assert _legibility(g, 1, face_down_live) == 1
    assert _legibility(g, 1, face_up_dead) == 2
    assert _legibility(g, 1, face_down_dead) == 0


def test_legibility_ignores_compiled_status_when_playing_onto_opponent_side():
    """상대 라인에 얹는 수(side가 설정됨)는 그 라인이 내 라인 기준으로
    컴파일됐는지와 무관하게 dead 취급하지 않는다 -- side는 항상 상대를
    가리키므로 "상대 라인에 얹는 수는 dead가 아니다"라는 조건이 항상
    성립한다."""
    g = _StubG(compiled_p1={1: True, 2: False, 3: False})
    on_opp_side = {"kind": "play", "line": 1, "faceUp": True, "side": 2}
    assert _legibility(g, 1, on_opp_side) == 3


def _root_from(entries, chooser=1):
    """entries: [(key, visits, mean_q, action_dict), ...] -> N/W/answer_of가
    채워진 _Node."""
    node = _Node(chooser=chooser)
    for key, n, q, action in entries:
        node.N[key] = n
        node.W[key] = q * n
        node.answer_of[key] = action
    return node


def test_tiebreak_is_noop_when_legible_eps_is_none():
    g = _StubG()
    root = _root_from([
        ("A", 100, 0.5, {"kind": "play", "line": 1, "faceUp": False}),
        ("B", 70, 0.5, {"kind": "play", "line": 1, "faceUp": True}),
    ])
    assert _apply_legibility_tiebreak(g, 1, root, "A", None) == "A"


def test_tiebreak_is_noop_when_best_answer_is_not_a_play_action():
    g = _StubG()
    root = _root_from([
        ("A", 100, 0.5, {"kind": "refresh"}),
        ("B", 70, 0.5, {"kind": "play", "line": 1, "faceUp": True}),
    ])
    assert _apply_legibility_tiebreak(g, 1, root, "A", 0.05) == "A"


def test_tiebreak_switches_to_more_legible_candidate_within_eps_and_visit_floor():
    """A(최다방문, 뒷면/죽은 라인)와 Q가 거의 같고(eps 이내) 방문수도
    충분한(>=60%) B(앞면/살아있는 라인)가 있으면 B로 바뀌어야 한다."""
    g = _StubG(compiled_p1={1: False, 2: True, 3: False})
    root = _root_from([
        ("A", 100, 0.50, {"kind": "play", "line": 2, "faceUp": False}),  # legibility 0
        ("B", 70, 0.49, {"kind": "play", "line": 1, "faceUp": True}),    # legibility 3
    ])
    assert _apply_legibility_tiebreak(g, 1, root, "A", 0.05) == "B"


def test_tiebreak_respects_real_value_gap_outside_eps():
    """B가 더 가독성 높아도 Q 격차가 eps보다 크면(진짜 가치 차이) A를
    유지해야 한다."""
    g = _StubG(compiled_p1={1: False, 2: True, 3: False})
    root = _root_from([
        ("A", 100, 0.50, {"kind": "play", "line": 2, "faceUp": False}),
        ("B", 70, 0.40, {"kind": "play", "line": 1, "faceUp": True}),
    ])
    assert _apply_legibility_tiebreak(g, 1, root, "A", 0.05) == "A"


def test_tiebreak_ignores_candidate_below_visit_floor():
    """B가 eps 이내 + 더 가독성 높아도 방문수가 bestN*0.6 미만이면
    (탐색이 충분히 검증하지 않은 후보) 무시해야 한다."""
    g = _StubG(compiled_p1={1: False, 2: True, 3: False})
    root = _root_from([
        ("A", 100, 0.50, {"kind": "play", "line": 2, "faceUp": False}),
        ("B", 59, 0.52, {"kind": "play", "line": 1, "faceUp": True}),
    ])
    assert _apply_legibility_tiebreak(g, 1, root, "A", 0.05) == "A"


def test_tiebreak_prefers_higher_q_among_equal_legibility():
    g = _StubG()
    root = _root_from([
        ("A", 100, 0.50, {"kind": "play", "line": 1, "faceUp": True}),
        ("B", 90, 0.51, {"kind": "play", "line": 1, "faceUp": True}),
    ])
    assert _apply_legibility_tiebreak(g, 1, root, "A", 0.05) == "B"


def test_legible_eps_default_none_leaves_decide_unaffected():
    """ISMCTSAI 기본값(legible_eps=None)은 이 배치 이전과 동일하게
    동작해야 한다 -- end-to-end로 한 판 굴려서 안 죽는지만 확인
    (수치 검증은 위 단위 테스트들이 담당)."""
    ai = ISMCTSAI(iterations=8, rollout_turn_cap=3)
    assert ai.legible_eps is None
    e = Engine(protocols1=PROTOS1, protocols2=PROTOS2, ai1=True, ai2=True,
               seed=11, ai_modules={1: ai, 2: RandomAI()})
    e.start()
    n = 0
    while e.pending is not None and n < 20000:
        n += 1
        if e.pending["kind"] == "anim":
            e.advance_anim()
        else:
            e.answer(None)
    assert e.error is None


def test_legible_eps_enabled_runs_full_game_without_error():
    ai = ISMCTSAI(iterations=8, rollout_turn_cap=3, legible_eps=0.04)
    e = Engine(protocols1=PROTOS1, protocols2=PROTOS2, ai1=True, ai2=True,
               seed=13, ai_modules={1: ai, 2: RandomAI()})
    e.start()
    n = 0
    while e.pending is not None and n < 20000:
        n += 1
        if e.pending["kind"] == "anim":
            e.advance_anim()
        else:
            e.answer(None)
    assert e.error is None


# ---------------------------------------------------------------------------
# 15. Control 재배치(planRearrange) 서브탐색 (4단계, 260804).
#     spend_control()이 prompt()를 거치지 않고 AI를 동기 직접호출하는
#     별도 경로라서, 이 경로 자체가 살아있는 게임에서 실제로 발동하는지
#     까지 확인한다(§8의 test_control_rearrange_path_does_not_crash와
#     같은 우려).
# ---------------------------------------------------------------------------

def test_rearrange_iterations_none_delegates_to_heuristic_unchanged():
    """기본값(None)은 이 배치 이전과 동일하게 HeuristicAI.planRearrange를
    그대로 위임해야 한다 -- 새로 계산하는 게 아니라 진짜로 위임하는지
    스텁으로 확인."""
    orig = HeuristicAI.planRearrange
    sentinel = {"who": 1, "order": {1: 2, 2: 1, 3: 3}}
    HeuristicAI.planRearrange = lambda self, g, pi, compiling_line: sentinel
    try:
        ai = ISMCTSAI(iterations=8)
        assert ai.rearrange_iterations is None
        e = Engine(protocols1=PROTOS1, protocols2=PROTOS2)
        assert ai.planRearrange(e, 1, None) is sentinel
    finally:
        HeuristicAI.planRearrange = orig


def test_rearrange_search_calls_search_with_synthetic_root_req_and_no_policy_w():
    """`_search()`에 planRearrange 합성 프롬프트를 루트로 넘기고,
    policy_w(학습된 루트 정책) 없이 순수 UCB1로 호출하는지 인자 자체를
    캡처해서 확인한다."""
    captured = {}

    def fake_search(g, pi0, root_req, iterations, c_ucb, c_puct, rollout_policy,
                     rollout_turn_cap, eval_fn, eval_w, eval_scale, *args, **kwargs):
        captured["pi0"] = pi0
        captured["root_req"] = root_req
        captured["iterations"] = iterations
        captured["extra_args"] = args
        captured["extra_kwargs"] = kwargs
        return DECLINE

    orig = ai_ismcts_module._search
    ai_ismcts_module._search = fake_search
    try:
        ai = ISMCTSAI(iterations=1, rearrange_iterations=7)
        e = Engine(protocols1=PROTOS1, protocols2=PROTOS2)
        result = ai.planRearrange(e, 2, 3)
    finally:
        ai_ismcts_module._search = orig

    assert captured["pi0"] == 2
    assert captured["root_req"] == {"type": "planRearrange", "chooser": 2, "compilingLine": 3}
    assert captured["iterations"] == 7
    assert not captured["extra_args"] and not captured["extra_kwargs"]
    assert result is None  # DECLINE -> None


def test_rearrange_search_passes_through_a_chosen_plan():
    plan = {"who": 2, "order": {1: 1, 2: 3, 3: 2}}
    orig = ai_ismcts_module._search
    ai_ismcts_module._search = lambda *a, **k: plan
    try:
        ai = ISMCTSAI(iterations=1, rearrange_iterations=5)
        e = Engine(protocols1=PROTOS1, protocols2=PROTOS2)
        assert ai.planRearrange(e, 1, None) is plan
    finally:
        ai_ismcts_module._search = orig


def test_rearrange_search_falls_back_to_heuristic_when_clone_impossible():
    """`_search()`가 None(클론 불가 등)을 반환하면 안전하게
    HeuristicAI.planRearrange로 폴백해야 한다."""
    calls = {"n": 0}
    orig_h = HeuristicAI.planRearrange

    def counting(self, g, pi, compiling_line):
        calls["n"] += 1
        return orig_h(self, g, pi, compiling_line)

    HeuristicAI.planRearrange = counting
    orig_s = ai_ismcts_module._search
    ai_ismcts_module._search = lambda *a, **k: None
    try:
        ai = ISMCTSAI(iterations=1, rearrange_iterations=5)
        e = Engine(protocols1=PROTOS1, protocols2=PROTOS2)
        ai.planRearrange(e, 1, None)
    finally:
        ai_ismcts_module._search = orig_s
        HeuristicAI.planRearrange = orig_h

    assert calls["n"] == 1


def test_rearrange_search_path_runs_full_games_and_is_actually_exercised():
    """§8과 같은 우려(스텁이 실제로 그 경로를 타는지)를 서치 버전에도
    똑같이 적용한다 -- `_search`가 "planRearrange" 타입 root_req로 최소
    한 번은 불렸는지까지 확인."""
    calls = {"types": []}
    orig = ai_ismcts_module._search

    def counting_search(g, pi0, root_req, *args, **kwargs):
        calls["types"].append(root_req["type"])
        return orig(g, pi0, root_req, *args, **kwargs)

    ai_ismcts_module._search = counting_search
    try:
        for seed in range(4):
            e = _driven_engine(
                seed,
                ai_modules={1: ISMCTSAI(iterations=8, rollout_turn_cap=4, rearrange_iterations=6),
                            2: ISMCTSAI(iterations=8, rollout_turn_cap=4)},
            )
            assert e.error is None
    finally:
        ai_ismcts_module._search = orig

    assert "planRearrange" in calls["types"], "Control 재배치 서브탐색이 한 번도 발동하지 않음"
