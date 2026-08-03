"""ai_prior.py -- 카드 효과 태그 + 상황별 채점(effect_prior) 회귀 테스트.

270장 전부 채워짐 (Aux1 18 + Main1 72 + Main2 72 + Aux2 18 + Main3 72 + Aux3 18).
"""

import pytest

from src.game.carddefs import DEFS
from src.game.engine import Engine
from src.game.ai_prior import (
    TAGS, effect_prior, defusable_threat, plan_rearrange, score_action, choose_line,
    _line_threat, compile_available_next_check, _lust_0, _greed_1, _pride_6,
    _shift_card_value, _best_shift_where, _pride_0, _nova_3, _greed_3,
    _flexible_0, _flexible_3, _flip_swing, _best_flip_where, _sum_flip_where,
    _ambush_1, _ambush_2, _ambush_4, _envy_1, _envy_2, _envy_4,
    _fulcrum_0, _fulcrum_1, _fulcrum_2, _fulcrum_4, _gluttony_2, _nova_4,
    _wrath_1, _wrath_2, _sloth_2, _flexible_1, _inert_0, _inert_2,
    _nova_1, _overwhelm_1, _pride_4, _rigid_7,
    _nova_2, _lust_4, _wrath_4, _greed_0, _greed_4, _lust_2, _lust_6,
    _inert_4, _pride_2, _sloth_0, _sloth_1,
)
from src.game.rules import COMPILE_THRESHOLD


def test_all_270_cards_have_a_tag():
    missing = [k for k in DEFS if k not in TAGS]
    assert not missing, f"태그 없는 카드({len(missing)}장): {missing}"


def test_no_tag_points_to_a_nonexistent_card():
    orphan = [k for k in TAGS if k not in DEFS]
    assert not orphan, f"존재하지 않는 카드를 가리키는 태그: {orphan}"


def test_tags_cover_exactly_270_cards():
    assert len(TAGS) == 270
    assert len(DEFS) == 270


def _card(g, proto, value, owner, face_up=True):
    c = g.new_card(proto, value, owner)
    c.face_up = face_up
    return c


def test_hate_0_values_removal_higher_when_enemy_line_is_threatening():
    """카드 1장 제거(대상 제한 없음)는, 상대의 위협적인 라인에 값 높은
    카드가 드러나 있을 때 훨씬 높게 평가돼야 한다."""
    e = Engine(protocols1=["Hate", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    hate0 = _card(e, "Hate", 0, 1)

    # 상황 A: 상대 필드가 비어있음 -> 제거해봐야 내 카드를 쳐야 함(마이너스)
    s_empty = effect_prior(e, 1, hate0)

    # 상황 B: 상대 라인2가 위협적(임계값 이상, 앞서고 있음)이고 값5 카드가 드러남
    e.players[2]["stacks"][2].append(_card(e, "Fire", 5, 2))
    for _ in range(9):
        e.players[2]["stacks"][2].append(_card(e, "Fire", 5, 2, face_up=False))
    s_threat = effect_prior(e, 1, hate0)

    assert s_threat > s_empty


def test_hate_2_sequential_removal_targets_own_then_enemy():
    e = Engine(protocols1=["Hate", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    hate2 = _card(e, "Hate", 2, 1)
    # 내 쪽엔 낮은 카드, 상대 쪽엔 높은 카드 -> 상대 쪽 제거 이득이 더 커야 함
    e.players[1]["stacks"][1].append(_card(e, "Water", 1, 1))
    e.players[2]["stacks"][1].append(_card(e, "Ice", 6, 2))
    s = effect_prior(e, 1, hate2)
    assert s > 0  # 내 손실(1)보다 상대 이득(6)이 훨씬 커서 순이익


def test_apathy_5_and_hate_5_are_pure_cost_cards():
    e = Engine(protocols1=["Apathy", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    apathy5 = _card(e, "Apathy", 5, 1)
    assert effect_prior(e, 1, apathy5) < 0


def test_love_6_and_love_2_are_penalized_for_opponent_draw():
    e = Engine(protocols1=["Love", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    love6 = _card(e, "Love", 6, 1)
    love2 = _card(e, "Love", 2, 1)
    assert effect_prior(e, 1, love6) < 0
    # love2는 opp_draw(마이너스)와 refresh_self(플러스)가 섞여있음 -- 손패가
    # 거의 없을 때는 refresh 이득이 커서 순이익이 될 수 있음
    e.players[1]["hand"].clear()
    assert effect_prior(e, 1, love2) > effect_prior(e, 1, love6)


def test_unknown_key_scores_zero():
    """180장이 다 채워진 지금, "태그 없는 카드"는 실제로는 존재하지 않는
    proto_value 키뿐이다 -- 그런 경우 크래시 대신 0점으로 안전하게 처리."""
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    fake = _card(e, "Water", 0, 1)
    fake.proto, fake.value = "NoSuchProto", 99
    assert effect_prior(e, 1, fake) == 0.0


# ---------------------------------------------------------------------------
# effect_prior의 "prior"(flat rider) / "fn"(bespoke 콜백) 필드 배관.
# 예전엔 TAGS에 이 두 필드가 있어도 effect_prior가 아예 읽지 않아 34장의
# prior 값이 조용히 무시되고, fn 콜백 자체가 지원되지 않았다.
# ---------------------------------------------------------------------------

def test_prior_flat_rider_was_previously_a_dead_value_now_applied():
    """Spirit_4는 TAGS에 {"prior": 1.0} 하나만 있다 -- 다른 verb가 전혀
    없으므로, prior가 배관되면 effect_prior 결과가 정확히 1.0이어야 한다."""
    e = Engine(protocols1=["Spirit", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    spirit4 = _card(e, "Spirit", 4, 1)
    assert TAGS["Spirit_4"] == {"prior": 1.0}
    assert effect_prior(e, 1, spirit4) == pytest.approx(1.0)


def test_effect_prior_supports_a_callable_prior_rider(monkeypatch):
    """prior가 숫자가 아니라 콜백이면 (g, pi, card, line, handAfter)로
    호출되고, 반환값이 그대로 합산돼야 한다."""
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    seen = {}

    def cb(g, pi, card, line, hand_after):
        seen["args"] = (pi, line, hand_after)
        return 3.5

    monkeypatch.setitem(TAGS, "Water_5", {"prior": cb})
    e.players[1]["hand"].clear()
    card = _card(e, "Water", 5, 1)
    e.players[1]["hand"].append(card)
    assert effect_prior(e, 1, card, line=2) == pytest.approx(3.5)
    assert seen["args"] == (1, 2, 0)  # 손패가 이 카드 1장뿐이라 handAfter=0


def test_effect_prior_supports_an_fn_callback(monkeypatch):
    """fn 콜백도 prior와 동일한 계약으로 호출되고 합산돼야 한다 -- del/ret/
    flip 같은 일반 verb 위에 얹히는 값이라 다른 verb와 함께 있어도 된다."""
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])

    def cb(g, pi, card, line, hand_after):
        return 2.0

    monkeypatch.setitem(TAGS, "Water_5", {"draw": 1, "fn": cb})
    card = _card(e, "Water", 5, 1)
    assert effect_prior(e, 1, card) == pytest.approx(0.7 * 1 + 2.0)


def test_effect_prior_ongoing_numeric_override_replaces_the_flat_default(monkeypatch):
    """ongoing이 숫자면(예: -2.5) 그 값을 그대로 쓰고, True면 여전히
    flat +0.8 -- bool은 int의 서브클래스라 True가 숫자 분기로 새지
    않아야 한다."""
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    monkeypatch.setitem(TAGS, "Water_5", {"ongoing": -2.5})
    card = _card(e, "Water", 5, 1)
    assert effect_prior(e, 1, card) == pytest.approx(-2.5)
    monkeypatch.setitem(TAGS, "Water_5", {"ongoing": True})
    assert effect_prior(e, 1, card) == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# Rigid_7 -- 인쇄값(7) 뒤에 숨은 심각한 지속 부채. 예전엔 ongoing:True로
# +0.8 보너스를 주고 있었는데, 실제로는 cantFlip+cantMove(숨길 방법이
# 없음) + 매 턴 상대에게 공짜 뽑기/플레이를 주는 명백한 순손실 카드다.
# ---------------------------------------------------------------------------

def test_rigid_7_is_a_net_negative_not_a_bonus():
    e = Engine(protocols1=["Rigid", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    e.players[1]["hand"].clear()
    rigid7 = _card(e, "Rigid", 7, 1)
    e.players[1]["hand"].append(rigid7)
    e.players[2]["hand"] = [_card(e, "Ice", 3, 2)]  # 상대가 낼 카드도 있음
    assert effect_prior(e, 1, rigid7) < 0


def test_rigid_7_immediate_gift_scales_with_opponent_capability():
    e = Engine(protocols1=["Rigid", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Rigid", 7, 1)
    e.players[2]["hand"] = []
    e.players[2]["deck"] = []
    e.players[2]["discard"] = []
    assert _rigid_7(e, 1, card, None, 0) == 0.0  # 상대가 뽑을 수도 낼 수도 없음

    e.players[2]["deck"] = [_card(e, "Ice", 1, 2)]
    assert _rigid_7(e, 1, card, None, 0) == pytest.approx(-0.7)  # 뽑기만 가능

    e.players[2]["hand"] = [_card(e, "Metal", 4, 2)]
    assert _rigid_7(e, 1, card, None, 0) == pytest.approx(-2.5)  # 낼 수도 있음(더 큰 선물)


# ---------------------------------------------------------------------------
# bespoke fn (4차 배치) -- 이미 있는 인프라로 바로 이식 가능했는데 놓쳤던
# 카드들 (Nova_2, Lust_2/4/6, Wrath_4, Greed_0/4, Inert_4, Pride_2, Sloth_0/1)
# ---------------------------------------------------------------------------

def test_gluttony_0_now_uses_generic_ret_and_draw_verbs():
    """새 fn 없이 기존 ret/draw generic verb만으로 풀리는 카드."""
    assert TAGS["Gluttony_0"]["ret"] == {}
    assert TAGS["Gluttony_0"]["draw"] == 1
    e = Engine(protocols1=["Gluttony", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    gluttony0 = _card(e, "Gluttony", 0, 1)
    e.players[2]["stacks"][1].append(_card(e, "Ice", 6, 2))
    assert effect_prior(e, 1, gluttony0) > 0.0  # 뽑기 + 상대 카드 반환 이득


def test_nova_2_grants_a_small_bonus_when_covering_its_own_protocol():
    e = Engine(protocols1=["Nova", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Nova", 2, 1)
    e.players[1]["stacks"][2].append(_card(e, "Nova", 4, 1))  # 앞면 Nova -- 덮으면 소액 재배열
    assert _nova_2(e, 1, card, 2, 0) == pytest.approx(0.7)


def test_nova_2_prices_control_gain_when_not_covering_a_nova():
    e = Engine(protocols1=["Nova", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Nova", 2, 1)
    e.control = 2
    assert _nova_2(e, 1, card, 2, 0) == pytest.approx(2.5)  # 상대에게서 뺏어옴


def test_lust_4_only_valuable_while_opponent_holds_control():
    e = Engine(protocols1=["Lust", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Lust", 4, 1)
    e.control = 1
    assert _lust_4(e, 1, card, None, 0) == pytest.approx(-0.2)
    e.control = 2
    assert _lust_4(e, 1, card, None, 0) == pytest.approx(1.8)


def test_wrath_4_requires_holding_control_and_scales_with_opponent_hand():
    e = Engine(protocols1=["Wrath", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Wrath", 4, 1)
    e.players[2]["hand"] = [_card(e, "Ice", v, 2) for v in (1, 2, 3)]
    e.control = 2
    assert _wrath_4(e, 1, card, None, 0) == 0.0
    e.control = 1
    assert _wrath_4(e, 1, card, None, 0) == pytest.approx(0.9 * 2 - 1.2)


def test_greed_0_combines_discard_cost_deletion_and_draw_bonus():
    e = Engine(protocols1=["Greed", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Greed", 0, 1)
    e.players[2]["stacks"][1].append(_card(e, "Ice", 6, 2))
    deletion = 6 * 0.9
    assert _greed_0(e, 1, card, None, 2) == pytest.approx(-0.9 * 2 + deletion + 0.7)


def test_greed_4_requires_discarding_the_whole_hand():
    e = Engine(protocols1=["Greed", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Greed", 4, 1)
    e.players[1]["stacks"][1].append(_card(e, "Water", 0, 1))
    assert _greed_4(e, 1, card, None, 0) == 0.0
    assert _greed_4(e, 1, card, None, 2) == pytest.approx(max(0.0, 2.0 - 0.9 * 2))


def test_lust_2_pulls_an_opponents_covered_card_from_another_line():
    e = Engine(protocols1=["Lust", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Lust", 2, 1)
    e.players[2]["stacks"][2].append(_card(e, "Ice", 6, 2))    # covered
    e.players[2]["stacks"][2].append(_card(e, "Metal", 3, 2))  # top
    assert _lust_2(e, 1, card, 1, 0) > 0.4  # shift value + 0.4 reach
    assert _lust_2(e, 1, card, None, 0) == 0.0


def test_lust_6_forces_a_free_facedown_play_when_legal():
    e = Engine(protocols1=["Lust", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Lust", 6, 1)
    assert _lust_6(e, 1, card, 1, 0) == 0.0  # 상대 손패 없음
    e.players[2]["hand"] = [_card(e, "Ice", 3, 2)]
    assert _lust_6(e, 1, card, 1, 0) == pytest.approx(-1.4)


def test_inert_4_only_favors_the_side_with_the_smaller_deck():
    e = Engine(protocols1=["Inert", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Inert", 4, 1)
    e.players[1]["deck"] = [_card(e, "Water", v, 1) for v in (1, 2)]
    e.players[2]["deck"] = [_card(e, "Ice", v, 2) for v in (1, 2, 3, 4, 5)]
    assert _inert_4(e, 1, card, None, 0) == pytest.approx(0.08 * 3)


def test_pride_2_counts_lines_i_am_ahead_in_after_this_play():
    e = Engine(protocols1=["Pride", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Pride", 2, 1)
    e.players[1]["stacks"][2].append(_card(e, "Water", 3, 1))
    e.players[2]["stacks"][2].append(_card(e, "Ice", 2, 2))
    assert _pride_2(e, 1, card, 2, 0) == pytest.approx(0.7)


def test_sloth_0_counts_lines_i_am_behind_in_after_this_play():
    e = Engine(protocols1=["Sloth", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Sloth", 0, 1)
    e.players[2]["stacks"][2].append(_card(e, "Ice", 5, 2))
    assert _sloth_0(e, 1, card, 2, 0) == pytest.approx(0.7)


def test_sloth_1_returns_the_opponents_strongest_uncovered_card():
    e = Engine(protocols1=["Sloth", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Sloth", 1, 1)
    e.players[2]["stacks"][1].append(_card(e, "Ice", 6, 2))
    assert _sloth_1(e, 1, card, None, 0) == pytest.approx(6 * 0.9 * 0.6)


# ---------------------------------------------------------------------------
# bespoke fn -- Lust_0 / Greed_1 / Pride_6 (Control/컴파일 직결 카드부터,
# 260803_ai_lua_vs_python_analysis.md §7 1단계 우선순위)
# ---------------------------------------------------------------------------

def test_lust_0_prices_control_gain_higher_when_taken_from_the_opponent():
    """Lust_0의 play는 곧바로 gain_control을 호출한다 -- 아무도 안 쥔
    상태에서 얻는 것보다, 상대가 쥐고 있던 걸 뺏어오는 쪽이 더 가치있고,
    내가 이미 쥔 상태에서 내면 그 항목은 0이어야 한다."""
    e = Engine(protocols1=["Lust", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    lust0 = _card(e, "Lust", 0, 1)

    e.control = None
    s_neutral = _lust_0(e, 1, lust0, 1, 0)
    e.control = 2
    s_from_opp = _lust_0(e, 1, lust0, 1, 0)
    e.control = 1
    s_already_mine = _lust_0(e, 1, lust0, 1, 0)

    assert s_from_opp > s_neutral > 0
    assert s_already_mine == 0.0


def test_lust_0_adds_a_denial_bonus_per_imminent_opponent_line():
    """상대가 이미 임계값 이상으로 우세한 라인이 있으면, Lust_0로 Control을
    쥐어 그 컴파일을 막는 값(+8/라인)이 추가로 붙어야 한다."""
    e = Engine(protocols1=["Lust", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    lust0 = _card(e, "Lust", 0, 1)
    e.control = None
    base = _lust_0(e, 1, lust0, 1, 0)

    e.players[2]["stacks"][2].append(_card(e, "Ice", 5, 2))
    e.players[2]["stacks"][2].append(_card(e, "Metal", 5, 2))
    with_threat = _lust_0(e, 1, lust0, 1, 0)

    assert with_threat == pytest.approx(base + 8.0)


def test_greed_1_counts_lines_that_reach_the_threshold_after_the_play():
    """Greed_1의 finish는 지금 즉시 컴파일 가능한 라인이 있으면 그 자리에서
    컴파일한다 -- 이 카드를 낸 후 라인 값이 임계값에 도달 + 우세해지는
    라인마다 +8이어야 한다."""
    e = Engine(protocols1=["Greed", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Greed", 1, 1)
    e.players[1]["stacks"][2].append(_card(e, "Water", 5, 1))
    assert _greed_1(e, 1, card, 2, 0) == 0.0  # 5+1=6, 아직 임계값 미달

    e.players[1]["stacks"][2].append(_card(e, "Water", 4, 1))  # 5+4+1=10
    assert _greed_1(e, 1, card, 2, 0) == pytest.approx(8.0)


def test_greed_1_is_zero_when_immediately_blocked_by_opponent_control():
    """Greed_1의 finish는 즉시 발동하는 트리거라, cant_compile/Lust_0류
    봉쇄로 지금 당장 컴파일이 막혀 있으면(2라인 우세의 turn-start 유예는
    여기 해당 없음) 값이 0이어야 한다."""
    e = Engine(protocols1=["Greed", "Water", "Fire"], protocols2=["Lust", "Metal", "Death"])
    e.control = 2
    e.players[2]["stacks"][1].append(_card(e, "Lust", 0, 2))
    card = _card(e, "Greed", 1, 1)
    e.players[1]["stacks"][2].append(_card(e, "Water", 5, 1))
    e.players[1]["stacks"][2].append(_card(e, "Water", 4, 1))
    assert _greed_1(e, 1, card, 2, 0) == 0.0


def test_pride_6_prices_the_immediate_self_flip_when_opponent_holds_control():
    """Pride_6은 이미 상대가 Control을 쥔 상태에서 내면 그 자리에서
    스스로 뒷면(6->2)으로 뒤집힌다 -- 그 낙폭(-4)만 반영하고, 그 외의
    경우(Control 없음/내가 쥠)는 이 항목이 0이어야 한다."""
    e = Engine(protocols1=["Pride", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Pride", 6, 1)

    e.control = None
    assert _pride_6(e, 1, card, 1, 0) == 0.0
    e.control = 1
    assert _pride_6(e, 1, card, 1, 0) == 0.0
    e.control = 2
    assert _pride_6(e, 1, card, 1, 0) == pytest.approx(-4.0)


# ---------------------------------------------------------------------------
# _shift_card_value / _best_shift_where -- 일반화된 "이동(shift)" verb 인프라
# (del/ret/flip에 이미 있던 프라이서와 나란히, 이동 계열 카드를 위해 신설)
# ---------------------------------------------------------------------------

def test_shift_card_value_scales_with_line_threat_for_enemy_cards():
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    quiet = _card(e, "Ice", 2, 2)
    e.players[2]["stacks"][1].append(quiet)
    assert _shift_card_value(e, 1, quiet) == pytest.approx(0.8)

    brewing = _card(e, "Metal", 5, 2)
    e.players[2]["stacks"][2].append(brewing)
    e.players[2]["stacks"][2].append(_card(e, "Metal", 3, 2))  # 라인2 값=8 (임계값-2 이상, 미만)
    assert _shift_card_value(e, 1, brewing) == pytest.approx(2.0)

    imminent = _card(e, "Death", 5, 2)
    e.players[2]["stacks"][3].append(imminent)
    e.players[2]["stacks"][3].append(_card(e, "Death", 5, 2))  # 라인3 값=10, 임계값 이상
    assert _shift_card_value(e, 1, imminent) == pytest.approx(4.0)


def test_shift_card_value_own_card_bonus_for_uncovering_live_machinery():
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    live_below = _card(e, "Fire", 0, 1)
    assert live_below.definition  # 전제: 실제 효과가 있는(빈 정의가 아닌) 카드
    e.players[1]["stacks"][1].append(live_below)
    on_top = _card(e, "Water", 3, 1)
    e.players[1]["stacks"][1].append(on_top)
    assert _shift_card_value(e, 1, on_top) == pytest.approx(0.8 + 0.75)

    vanilla_below = _card(e, "Water", 2, 1)
    vanilla_below.definition = {}
    e.players[1]["stacks"][2].append(vanilla_below)
    on_top2 = _card(e, "Fire", 3, 1)
    e.players[1]["stacks"][2].append(on_top2)
    assert _shift_card_value(e, 1, on_top2) == pytest.approx(0.8)


def test_best_shift_where_zero_when_no_candidate_matches():
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    e.players[2]["stacks"][1].append(_card(e, "Ice", 2, 2))
    assert _best_shift_where(e, 1, lambda c: False) == 0.0


def test_best_shift_where_picks_the_highest_value_candidate():
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    e.players[2]["stacks"][1].append(_card(e, "Ice", 2, 2))  # 0.8
    e.players[2]["stacks"][2].append(_card(e, "Metal", 5, 2))
    e.players[2]["stacks"][2].append(_card(e, "Metal", 5, 2))  # 임계값 이상 -- 4.0
    best = _best_shift_where(e, 1, lambda c: c.owner == 2 and e.is_uncovered(c))
    assert best == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# bespoke fn (2차 배치) -- Pride_0 / Nova_3 / Greed_3 / Flexible_0 / Flexible_3
# (shift 인프라로 새로 정밀화된 카드들, 260803_ai_lua_vs_python_analysis.md §7)
# ---------------------------------------------------------------------------

def test_pride_0_with_control_can_target_the_opponents_side_too():
    """Control을 쥔 상태로 내면 상대 카드도 이동 후보다 -- 임박한 위협
    라인에서 소재를 빼내는 게 최선의 선택이 돼야 한다."""
    e = Engine(protocols1=["Pride", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Pride", 0, 1)
    e.control = 1
    e.players[2]["stacks"][2].append(_card(e, "Metal", 5, 2))
    e.players[2]["stacks"][2].append(_card(e, "Metal", 5, 2))  # 임계값 이상
    assert _pride_0(e, 1, card, 1, 0) == pytest.approx(4.0)


def test_pride_0_without_control_only_considers_own_cards():
    """Control이 없으면(상대가 쥠) 내 카드만 후보다 -- 상대의 임박한
    위협 라인이 있어도 그건 무시하고, 내 카드 중 최선만 본다."""
    e = Engine(protocols1=["Pride", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Pride", 0, 1)
    e.control = 2
    e.players[2]["stacks"][2].append(_card(e, "Metal", 5, 2))
    e.players[2]["stacks"][2].append(_card(e, "Metal", 5, 2))  # 후보 아님(상대 카드)
    live_below = _card(e, "Fire", 0, 1)
    e.players[1]["stacks"][1].append(live_below)
    e.players[1]["stacks"][1].append(_card(e, "Water", 3, 1))  # 내 카드, 밑에 live -- 1.55
    assert _pride_0(e, 1, card, 1, 0) == pytest.approx(0.8 + 0.75)


def test_nova_3_targets_a_card_valued_below_the_post_play_stack_size():
    """놓인 뒤 스택 카드 수(자기 자신 포함)보다 값이 낮은 카드만 후보다."""
    e = Engine(protocols1=["Nova", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Nova", 3, 1)
    e.players[1]["stacks"][2].append(_card(e, "Water", 0, 1))
    # 지금 스택 카드 수=1, Nova_3이 놓이면 2 -> limit=2. 값0 카드만 <2라 후보.
    assert _nova_3(e, 1, card, 2, 0) == pytest.approx(0.8)


def test_nova_3_returns_zero_without_a_line():
    e = Engine(protocols1=["Nova", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Nova", 3, 1)
    assert _nova_3(e, 1, card, None, 0) == 0.0


def test_greed_3_only_considers_cards_that_will_be_covered_by_it():
    """Greed_3이 이 라인에 놓이면 지금 스택 전체가 가려진다 -- 지금
    스택에 있는 내 카드는(놓이기 전엔 맨 위였어도) 전부 후보여야 한다."""
    e = Engine(protocols1=["Greed", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Greed", 3, 1)
    only_card = _card(e, "Water", 4, 1)
    e.players[1]["stacks"][2].append(only_card)
    assert _greed_3(e, 1, card, 2, 0) == pytest.approx(0.8)


def test_greed_3_ignores_opponent_owned_cards_in_the_same_line():
    e = Engine(protocols1=["Greed", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Greed", 3, 1)
    e.players[1]["stacks"][2].append(_card(e, "Ice", 4, 2))  # 소유자가 상대 -- 후보 아님
    assert _greed_3(e, 1, card, 2, 0) == 0.0


def test_flexible_0_takes_the_better_of_bounce_or_shift():
    e = Engine(protocols1=["Flexible", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Flexible", 0, 1)
    # 상대의 값6 카드를 반환할 수 있으면(bounce) 그게 이동(shift, 최대 0.8)보다 큼
    e.players[2]["stacks"][1].append(_card(e, "Ice", 6, 2))
    assert _flexible_0(e, 1, card, 1, 0) > 0.8


def test_flexible_3_falls_back_to_the_protocol_swap_floor():
    """이동할 수 있는 상대 카드가 없으면 항상 가능한 대안(프로토콜
    교환, 0.5)으로 근사돼야 한다."""
    e = Engine(protocols1=["Flexible", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Flexible", 3, 1)
    assert _flexible_3(e, 1, card, 1, 0) == pytest.approx(0.5)


def test_flexible_3_prefers_shifting_an_opponent_card_out_of_a_threatening_line():
    e = Engine(protocols1=["Flexible", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Flexible", 3, 1)
    e.players[2]["stacks"][2].append(_card(e, "Metal", 5, 2))
    e.players[2]["stacks"][2].append(_card(e, "Metal", 5, 2))  # 임계값 이상
    assert _flexible_3(e, 1, card, 1, 0) == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# 버그 수정 회귀 -- _flip_prior의 부호 오류(2026-08-03)와 from_face 미배관.
# 예전엔 "상대의 강한 앞면 카드를 뒤집어 깎는" 명백히 좋은 수가 마이너스로,
# "내 강한 앞면 카드를 뒤집어 내리는" 명백히 나쁜 수가 플러스로 채점됐다.
# ---------------------------------------------------------------------------

def test_flip_prior_values_deflating_a_strong_enemy_face_up_card_as_positive():
    e = Engine(protocols1=["Apathy", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    apathy3 = _card(e, "Apathy", 3, 1)
    e.players[2]["stacks"][1].append(_card(e, "Metal", 5, 2))
    assert effect_prior(e, 1, apathy3) == pytest.approx(3.0)


def test_flip_prior_values_flipping_my_own_strong_face_up_card_down_as_negative(monkeypatch):
    """내 카드만 대상인 flip 태그(예: Apathy_4류 owner=own)로 확인 --
    Apathy_4는 may=True라 자체적으로 마이너스면 0으로 declines하므로,
    부호 검증용으로 may 없는 합성 태그를 하나 꽂아 직접 확인한다."""
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    monkeypatch.setitem(TAGS, "Water_5", {"flip": {"n": 1, "owner": "own"}})
    card = _card(e, "Water", 5, 1)
    e.players[1]["stacks"][1].append(_card(e, "Fire", 5, 1))  # 내 강한 앞면 카드
    assert effect_prior(e, 1, card) == pytest.approx(-3.0)


def test_flip_prior_all_branch_sign_matches_single_branch(monkeypatch):
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    monkeypatch.setitem(TAGS, "Water_5", {"flip": {"n": "all"}})
    card = _card(e, "Water", 5, 1)
    e.players[2]["stacks"][1].append(_card(e, "Metal", 5, 2))  # 적의 강한 카드 하나뿐인 라인
    assert effect_prior(e, 1, card) == pytest.approx(3.0 * 0.9)


def test_flip_prior_from_face_filter_is_actually_applied():
    """from_face="up"인데 유일한 후보가 뒷면이면 후보가 아예 없어야
    한다(0점) -- 예전엔 이 필드가 안 읽혀서 뒷면 카드도 후보에 들었다."""
    e = Engine(protocols1=["Apathy", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    apathy3 = _card(e, "Apathy", 3, 1)
    e.players[2]["stacks"][1].append(_card(e, "Metal", 5, 2, face_up=False))
    assert effect_prior(e, 1, apathy3) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _flip_swing / _best_flip_where / _sum_flip_where -- 판 전체 스캔형 뒤집기
# 인프라 (_shift_card_value/_best_shift_where와 대칭)
# ---------------------------------------------------------------------------

def test_flip_swing_signs_for_all_four_cases():
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    enemy_up = _card(e, "Metal", 5, 2)
    own_up = _card(e, "Fire", 5, 1)
    own_down = _card(e, "Water", 5, 1, face_up=False)
    enemy_down = _card(e, "Ice", 5, 2, face_up=False)
    assert _flip_swing(e, 1, enemy_up) == pytest.approx(3.0)     # 적 강한 카드 깎기 = 이득
    assert _flip_swing(e, 1, own_up) == pytest.approx(-3.0)      # 내 강한 카드 깎기 = 손해
    assert _flip_swing(e, 1, own_down) == pytest.approx(3.0)     # 내 뒷면(안 값)을 5로 공개 = 이득
    assert _flip_swing(e, 1, enemy_down) == pytest.approx(-1.5)  # 적의 정체 불명 공개 = 약한 손해


def test_best_flip_where_and_sum_flip_where():
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    e.players[2]["stacks"][1].append(_card(e, "Ice", 3, 2))
    e.players[2]["stacks"][2].append(_card(e, "Metal", 6, 2))
    assert _best_flip_where(e, 1, lambda c: c.owner == 2) == pytest.approx(4.0)
    assert _sum_flip_where(e, 1, lambda c: c.owner == 2) == pytest.approx(1.0 + 4.0)


# ---------------------------------------------------------------------------
# bespoke fn (3차 배치) -- Ambush_1/2/4, Envy_1/2/4, Fulcrum_0/1/2/4,
# Gluttony_2, Nova_4, Wrath_1/2, Sloth_2, Flexible_1, Inert_0/2
# ---------------------------------------------------------------------------

def test_ambush_1_sums_flips_of_own_value_0_or_1_cards_and_draws_that_many():
    e = Engine(protocols1=["Ambush", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Ambush", 1, 1)
    e.players[1]["stacks"][2].append(_card(e, "Water", 1, 1))
    e.players[1]["stacks"][3].append(_card(e, "Fire", 5, 1))  # 값5는 대상 아님
    swing = _flip_swing(e, 1, e.players[1]["stacks"][2][0])
    assert _ambush_1(e, 1, card, None, 0) == pytest.approx(swing + 0.7)


def test_ambush_2_moves_my_lowest_covered_card():
    e = Engine(protocols1=["Ambush", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Ambush", 2, 1)
    e.players[1]["stacks"][1].append(_card(e, "Water", 1, 1))  # covered, 값1(최저)
    e.players[1]["stacks"][1].append(_card(e, "Fire", 5, 1))   # top
    assert _ambush_2(e, 1, card, None, 0) == pytest.approx(0.8)


def test_ambush_4_requires_a_face_down_top_of_my_own():
    e = Engine(protocols1=["Ambush", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Ambush", 4, 1)
    assert _ambush_4(e, 1, card, None, 0) == 0.0
    e.players[1]["stacks"][1].append(_card(e, "Water", 3, 1, face_up=False))
    assert _ambush_4(e, 1, card, None, 0) == pytest.approx(0.7)


def test_envy_1_only_prices_the_optional_flip_when_opponent_holds_control():
    e = Engine(protocols1=["Envy", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Envy", 1, 1)
    e.players[2]["stacks"][1].append(_card(e, "Ice", 6, 2))
    e.control = 1
    assert _envy_1(e, 1, card, None, 0) == 0.0
    e.control = 2
    assert _envy_1(e, 1, card, None, 0) > 0.0


def test_envy_2_scales_with_actual_opponent_hand_size():
    e = Engine(protocols1=["Envy", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Envy", 2, 1)
    e.players[2]["hand"] = [_card(e, "Ice", v, 2) for v in (1, 2, 3)]
    assert _envy_2(e, 1, card, None, 0) == pytest.approx(0.7 * 3)


def test_envy_4_gated_on_opponent_compiling_more_than_me():
    e = Engine(protocols1=["Envy", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Envy", 4, 1)
    e.players[2]["stacks"][1].append(_card(e, "Ice", 6, 2))
    assert _envy_4(e, 1, card, None, 0) == 0.0
    e.players[2]["compiled"][1] = True
    assert _envy_4(e, 1, card, None, 0) > 0.0


def test_fulcrum_0_only_when_hand_will_be_empty():
    e = Engine(protocols1=["Fulcrum", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Fulcrum", 0, 1)
    assert _fulcrum_0(e, 1, card, None, 1) == 0.0
    assert _fulcrum_0(e, 1, card, None, 0) == pytest.approx(0.9)


def test_fulcrum_1_sums_all_other_face_up_cards_board_wide():
    e = Engine(protocols1=["Fulcrum", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Fulcrum", 1, 1)
    e.players[1]["stacks"][2].append(_card(e, "Fire", 5, 1))
    e.players[2]["stacks"][3].append(_card(e, "Metal", 5, 2))
    # 내 5(뒤집으면 -3) + 적 5(뒤집으면 +3) = 0, + 0.3 reach 보너스
    assert _fulcrum_1(e, 1, card, None, 0) == pytest.approx(0.3)


def test_fulcrum_2_gated_on_hand_of_two_at_play_time():
    e = Engine(protocols1=["Fulcrum", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Fulcrum", 2, 1)
    e.players[2]["stacks"][1].append(_card(e, "Ice", 6, 2))
    assert _fulcrum_2(e, 1, card, None, 0) == 0.0
    assert _fulcrum_2(e, 1, card, None, 1) > 0.0


def test_fulcrum_4_gated_on_hand_of_four_at_play_time():
    e = Engine(protocols1=["Fulcrum", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Fulcrum", 4, 1)
    assert _fulcrum_4(e, 1, card, None, 2) == 0.0
    assert _fulcrum_4(e, 1, card, None, 3) == pytest.approx(0.7)


def test_gluttony_2_scales_with_hand_after():
    e = Engine(protocols1=["Gluttony", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Gluttony", 2, 1)
    assert _gluttony_2(e, 1, card, None, 4) == pytest.approx(0.7 * 4)


def test_momentum_0_deck_plays_scales_with_compiled_lines():
    e = Engine(protocols1=["Momentum", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    momentum0 = _card(e, "Momentum", 0, 1)
    assert effect_prior(e, 1, momentum0) == pytest.approx(0.0)
    e.players[1]["compiled"][2] = True
    e.players[2]["compiled"][3] = True
    assert effect_prior(e, 1, momentum0) == pytest.approx(2.0)


def test_nova_4_only_targets_cards_below_the_post_play_stack_size():
    e = Engine(protocols1=["Nova", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Nova", 4, 1)
    e.players[1]["stacks"][2].append(_card(e, "Water", 0, 1))
    # 스택 카드 수=1, Nova_4가 놓이면 2 -> limit=2. 값0(<2)만 후보 -- 뒤집으면
    # 뒷면 기본값 2로 올라가므로(내 카드) 스윙은 +2.
    assert _nova_4(e, 1, card, 2, 0) == pytest.approx(2.0)


def test_wrath_1_deletes_a_face_up_card_only_while_i_hold_control():
    e = Engine(protocols1=["Wrath", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Wrath", 1, 1)
    e.players[2]["stacks"][1].append(_card(e, "Ice", 6, 2))
    e.control = 2
    assert _wrath_1(e, 1, card, None, 0) == 0.0
    e.control = 1
    assert _wrath_1(e, 1, card, None, 0) > 0.0


def test_wrath_2_prefers_the_line_with_more_of_my_own_strong_cards():
    e = Engine(protocols1=["Wrath", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Wrath", 2, 1)
    # 라인1: 카드 2장(내 강한 카드), 라인2: 카드 2장(적 강한 카드) -- 동률, 내 쪽이 유리한 라인이 선택돼야 함
    e.players[1]["stacks"][1].append(_card(e, "Water", 5, 1))
    e.players[1]["stacks"][1].append(_card(e, "Water", 5, 1))
    e.players[2]["stacks"][2].append(_card(e, "Ice", 5, 2))
    e.players[2]["stacks"][2].append(_card(e, "Ice", 5, 2))
    assert _wrath_2(e, 1, card, None, 0) == pytest.approx(6.0)


def test_sloth_2_only_targets_my_covered_cards():
    e = Engine(protocols1=["Sloth", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Sloth", 2, 1)
    e.players[1]["stacks"][1].append(_card(e, "Water", 5, 1))  # covered
    e.players[1]["stacks"][1].append(_card(e, "Fire", 3, 1))   # top -- 후보 아님
    assert _sloth_2(e, 1, card, None, 0) == pytest.approx(-3.0)


def test_flexible_1_picks_the_better_of_flip_or_shift_on_my_own_cards():
    e = Engine(protocols1=["Flexible", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Flexible", 1, 1)
    e.players[1]["stacks"][1].append(_card(e, "Water", 0, 1))  # 뒤집으면 0->2, +2
    assert _flexible_1(e, 1, card, None, 0) == pytest.approx(2.0)


def test_inert_0_only_targets_other_lines():
    e = Engine(protocols1=["Inert", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Inert", 0, 1)
    e.players[2]["stacks"][1].append(_card(e, "Ice", 6, 2))  # 같은 라인 -- 후보 아님
    assert _inert_0(e, 1, card, 1, 0) == 0.0
    e.players[2]["stacks"][2].append(_card(e, "Metal", 6, 2))  # 다른 라인 -- 후보
    assert _inert_0(e, 1, card, 1, 0) == pytest.approx(4.0)


def test_inert_2_flips_every_card_tied_for_highest_in_the_best_line():
    e = Engine(protocols1=["Inert", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Inert", 2, 1)
    e.players[1]["stacks"][1].append(_card(e, "Water", 5, 1))
    e.players[2]["stacks"][1].append(_card(e, "Ice", 5, 2))  # 동률 최고값 -- 둘 다 뒤집힘, 합산 0
    e.players[2]["stacks"][2].append(_card(e, "Metal", 6, 2))  # 이 라인이 더 유리
    assert _inert_2(e, 1, card, None, 0) == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# bespoke fn (보너스 배치) -- 기존 인프라를 그대로 재사용하는 저위험 카드
# ---------------------------------------------------------------------------

def test_nova_1_scales_with_the_post_play_stack_size():
    e = Engine(protocols1=["Nova", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Nova", 1, 1)
    e.players[1]["stacks"][2].append(_card(e, "Water", 3, 1))
    e.players[1]["stacks"][2].append(_card(e, "Fire", 2, 1))
    # 스택 카드 수=2, Nova_1이 놓이면 3.
    assert _nova_1(e, 1, card, 2, 0) == pytest.approx(0.9 * 3)


def test_nova_1_returns_zero_without_a_line():
    e = Engine(protocols1=["Nova", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Nova", 1, 1)
    assert _nova_1(e, 1, card, None, 0) == 0.0


def test_overwhelm_1_counts_lines_winning_after_this_play():
    e = Engine(protocols1=["Overwhelm", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Overwhelm", 1, 1)
    e.players[1]["stacks"][1].append(_card(e, "Water", 3, 1))
    e.players[2]["stacks"][1].append(_card(e, "Ice", 2, 2))
    # 라인1: 내 3+카드값1=4 > 상대2 -- 우세. 라인2/3: 둘 다 0-0 동률, 우세 아님.
    assert _overwhelm_1(e, 1, card, 1, 0) == pytest.approx(1.0)


def test_pride_4_requires_control_and_a_different_line_target():
    e = Engine(protocols1=["Pride", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Pride", 4, 1)
    e.players[2]["stacks"][2].append(_card(e, "Metal", 5, 2))
    e.control = 2
    assert _pride_4(e, 1, card, 1, 0) == 0.0  # Control 없음
    e.control = 1
    assert _pride_4(e, 1, card, 2, 0) == 0.0  # 유일한 상대 카드가 목적지(line=2)와 같은 라인
    assert _pride_4(e, 1, card, 1, 0) == pytest.approx(0.8)  # 다른 라인으로 끌어올 수 있음


# ---------------------------------------------------------------------------
# compile_available_next_check / _line_threat -- Lust_0류 동적 컴파일 봉쇄
# (엔진의 check_control -> compilable_lines 순서, _blocked_by_opponent_control)
# ---------------------------------------------------------------------------

def test_compile_available_next_check_false_when_locked_by_opponent_control():
    """상대(Control 보유자)가 Lust_0를 드러내 놓으면, 임계값을 넘겨도
    2라인 우세가 아닌 한 다음 턴에 컴파일할 수 없다."""
    e = Engine(protocols1=["Fire", "Water", "Life"], protocols2=["Lust", "Metal", "Death"])
    e.control = 2
    e.players[2]["stacks"][1].append(_card(e, "Lust", 0, 2))
    assert compile_available_next_check(e, 1) is False


def test_compile_available_next_check_released_by_two_line_win():
    """check_control()이 컴파일 판정보다 먼저 돌아, 2라인 이상 우세면
    Control이 넘어와 Lust_0의 조건("상대가 Control을 쥠")이 깨진다 --
    winning 인자로 그 미리 계산된 우세 라인 수를 넘기면 봉쇄가 풀린다."""
    e = Engine(protocols1=["Fire", "Water", "Life"], protocols2=["Lust", "Metal", "Death"])
    e.control = 2
    e.players[2]["stacks"][1].append(_card(e, "Lust", 0, 2))
    assert compile_available_next_check(e, 1, winning=1) is False
    assert compile_available_next_check(e, 1, winning=2) is True


def test_compile_available_next_check_true_for_the_control_holder_itself():
    """봉쇄는 "상대가 Control을 쥔" 경우에만 적용된다 -- Control을 쥔
    당사자 자신은 자기 Lust_0에 영향받지 않는다."""
    e = Engine(protocols1=["Fire", "Water", "Life"], protocols2=["Lust", "Metal", "Death"])
    e.control = 2
    e.players[2]["stacks"][1].append(_card(e, "Lust", 0, 2))
    assert compile_available_next_check(e, 2) is True


def test_compile_available_next_check_ignores_cant_compile_of_the_other_player():
    """cant_compile은 그 플레이어 자신의 1회성 봉쇄일 뿐, 상대에게는
    영향이 없다."""
    e = Engine(protocols1=["Fire", "Water", "Life"], protocols2=["Metal", "Water", "Death"])
    e.cant_compile[2] = True
    assert compile_available_next_check(e, 1) is True
    assert compile_available_next_check(e, 2) is False


def test_line_threat_zero_when_threatening_side_is_lust_locked():
    """상대 라인 값이 임계값을 넘겨도, 그 상대가 Lust_0류로 봉쇄돼 실제로
    컴파일을 못 하는 상태면 위협도는 0이어야 한다(그냥 우세일 뿐)."""
    e = Engine(protocols1=["Fire", "Water", "Life"], protocols2=["Lust", "Metal", "Death"])
    e.control = 2
    e.players[2]["stacks"][1].append(_card(e, "Lust", 0, 2))
    e.players[1]["stacks"][2].append(_card(e, "Fire", 5, 1))
    e.players[1]["stacks"][2].append(_card(e, "Water", 5, 1))
    assert e.line_value(1, 2) >= COMPILE_THRESHOLD  # 값 자체는 임계값 이상
    assert _line_threat(e, 2, 2) == 0  # 하지만 봉쇄돼 있어 실제 위협은 아님


def test_line_threat_nonzero_once_lust_lock_is_released_by_two_line_win():
    """같은 봉쇄 상황이라도, 상대가 이미 다른 라인에서 2라인째 우세를
    만든 뒤라면(Control 체크가 먼저 락을 풀어줌) 위협이 다시 성립한다."""
    e = Engine(protocols1=["Fire", "Water", "Life"], protocols2=["Lust", "Metal", "Death"])
    e.control = 2
    e.players[2]["stacks"][1].append(_card(e, "Lust", 0, 2))
    e.players[1]["stacks"][2].append(_card(e, "Fire", 5, 1))
    e.players[1]["stacks"][2].append(_card(e, "Water", 5, 1))
    # 라인3에서도 player1이 우세하게 만들어 2라인 우세를 달성
    e.players[1]["stacks"][3].append(_card(e, "Life", 3, 1))
    assert e.lines_winning_count(1) >= 2
    assert _line_threat(e, 2, 2) == 2


def test_score_action_threshold_bonus_suppressed_when_playing_side_is_locked():
    """score_action의 "임계값 도달" +60 보너스는 이 플레이 이후에도 여전히
    Lust_0류로 봉쇄된 상태라면 붙으면 안 된다(실제로 컴파일이 안 열리므로)."""
    def build(locked):
        protos2 = ["Lust", "Metal", "Death"] if locked else ["Metal", "Water", "Death"]
        e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=protos2)
        if locked:
            e.control = 2
            e.players[2]["stacks"][1].append(_card(e, "Lust", 0, 2))
        e.players[1]["stacks"][2].append(_card(e, "Water", 5, 1))
        e.players[1]["hand"].clear()
        card = _card(e, "Water", 5, 1)
        e.players[1]["hand"].append(card)
        action = {"kind": "play", "uid": card.uid, "line": 2, "faceUp": True}
        return e, action

    e_locked, action_locked = build(True)
    e_free, action_free = build(False)
    s_locked = score_action(e_locked, 1, action_locked)
    s_free = score_action(e_free, 1, action_free)
    assert s_free - s_locked == pytest.approx(60)


# ---------------------------------------------------------------------------
# defusable_threat / plan_rearrange (1-d)
# ---------------------------------------------------------------------------

def test_defusable_threat_requires_control():
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    for v in (5, 5):
        c = _card(e, "Fire", v, 2)
        e.players[2]["stacks"][2].append(c)
    e.players[2]["compiled"][3] = True
    assert defusable_threat(e, 1) is None  # 제어권이 없음


def test_defusable_threat_requires_an_already_compiled_enemy_line():
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    e.control = 1
    for v in (5, 5):
        c = _card(e, "Fire", v, 2)
        e.players[2]["stacks"][2].append(c)
    assert defusable_threat(e, 1) is None  # 상대의 다른 라인이 컴파일 안 돼있음


def test_defusable_threat_detects_the_rescue_line():
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    e.control = 1
    for v in (5, 5):
        c = _card(e, "Fire", v, 2)
        e.players[2]["stacks"][2].append(c)
    e.players[2]["compiled"][3] = True
    assert defusable_threat(e, 1) == 2


def test_plan_rearrange_rescues_own_wasted_recompile():
    """지금 컴파일하려는 라인이 내가 이미 컴파일한 프로토콜이면, 아직
    컴파일 안 한 라인 중 값이 제일 낮은 곳과 맞바꿔 진짜 진전으로 바꾼다."""
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    e.players[1]["compiled"][1] = True
    c1 = _card(e, "Water", 3, 1)
    e.players[1]["stacks"][2].append(c1)  # 라인2(값3) vs 라인3(값0, 더 낮음)
    plan = plan_rearrange(e, 1, compiling_line=1)
    assert plan == {"who": 1, "order": {1: 3, 2: 2, 3: 1}}


def test_plan_rearrange_disrupts_opponents_most_threatening_line():
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    for v in (5, 5, 5):
        c = _card(e, "Ice", v, 2)
        e.players[2]["stacks"][2].append(c)  # 라인2: 위협적(값15)
    c = _card(e, "Metal", 3, 2)
    e.players[2]["stacks"][3].append(c)  # 라인3: 값3 (라인1의 값0보다 큼)
    plan = plan_rearrange(e, 1, compiling_line=None)
    assert plan["who"] == 2
    assert plan["order"][2] == 1 and plan["order"][1] == 2  # 위협 라인 <-> 제일 낮은 라인


def test_plan_rearrange_never_returns_a_no_op_swap():
    """반환하는 경우 항상 서로 다른 두 라인을 실제로 맞바꿔야 한다(같은
    라인끼리의 무의미한 스왑은 규칙 위반)."""
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    plan = plan_rearrange(e, 1, compiling_line=None)
    if plan is not None:
        swapped = [l for l in (1, 2, 3) if plan["order"][l] != l]
        assert len(swapped) == 2


def test_plan_rearrange_wired_into_spend_control_via_ai_module():
    """실제 엔진 연동: Control을 쥔 AI가 컴파일/리프레시로 그걸 소비할 때,
    engine.spend_control()이 ai_module(pi).planRearrange(g, pi, compiling_line)를
    그대로 호출해 우리 plan_rearrange가 실제로 실행되는지 확인."""
    class TinyAI:
        def decide(self, g, req):
            return None

        def planRearrange(self, g, pi, compiling_line):
            return plan_rearrange(g, pi, compiling_line)

    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"],
               ai1=True, ai_modules={1: TinyAI()})
    e.control = 1
    for v in (5, 5, 5):
        c = _card(e, "Ice", v, 2)
        e.players[2]["stacks"][2].append(c)
    before = dict(e.players[2]["protocols"])
    e.spend_control(1)
    assert e.control is None  # 제어권은 항상 중립으로 반납됨
    assert e.players[2]["protocols"] != before  # 실제로 재배치가 적용됨


# ---------------------------------------------------------------------------
# score_action의 자기대국 다양성 훅 (ai_style_bias/ai_dump_bias) --
# ai_howtodiversity.md Phase A. 프로덕션 안전성(미설정 시 완전히 기존과
# 동일)이 가장 중요한 불변식이라 이걸 직접 회귀 테스트로 박아둔다.
# ---------------------------------------------------------------------------

def test_score_action_dump_bias_absent_by_default_and_purely_additive():
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    e.players[1]["compiled"][1] = True  # dump 지점(이미 컴파일한 라인)이 걸리게
    card = _card(e, "Water", 2, 1, face_up=False)
    e.players[1]["hand"] = [card]
    action = {"kind": "play", "uid": card.uid, "line": 1, "faceUp": False}

    assert not hasattr(e, "ai_dump_bias")
    baseline = score_action(e, 1, action)

    e.ai_dump_bias = {1: 7.0, 2: -3.0}
    assert score_action(e, 1, action) == pytest.approx(baseline + 7.0)


def test_score_action_style_bias_absent_by_default_and_purely_additive():
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Water", 2, 1, face_up=True)
    e.players[1]["hand"] = [card]
    action = {"kind": "play", "uid": card.uid, "line": 1, "faceUp": True}

    assert not hasattr(e, "ai_style_bias")
    baseline = score_action(e, 1, action)

    e.ai_style_bias = {1: -2.5, 2: 2.5}
    assert score_action(e, 1, action) == pytest.approx(baseline - 2.5)


def test_score_action_bias_only_affects_the_targeted_seat():
    """좌석 2에만 편향을 설정했으면 좌석 1의 채점은 그대로여야 한다."""
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Water", 2, 1, face_up=True)
    e.players[1]["hand"] = [card]
    action = {"kind": "play", "uid": card.uid, "line": 1, "faceUp": True}

    baseline = score_action(e, 1, action)
    e.ai_style_bias = {2: 5.0}  # 좌석 1엔 값 없음
    assert score_action(e, 1, action) == pytest.approx(baseline)


def test_score_action_style_bias_does_not_affect_facedown_plays():
    """style 편향은 face_up 분기 안에서만 더해져야 한다 -- 뒷면 플레이 채점엔
    영향을 주면 안 된다."""
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    card = _card(e, "Water", 2, 1, face_up=False)
    e.players[1]["hand"] = [card]
    action = {"kind": "play", "uid": card.uid, "line": 1, "faceUp": False}

    baseline = score_action(e, 1, action)
    e.ai_style_bias = {1: 999.0}
    assert score_action(e, 1, action) == pytest.approx(baseline)


# ---------------------------------------------------------------------------
# Smoke_0/Life_0의 조건부 deck_plays -- 실제 자격 라인 수만큼만 값을 매겨야
# 한다(고정값 버그: 자격 라인이 0개인데도 항상 +2.0을 주던 것을 수정).
# ---------------------------------------------------------------------------

def test_smoke_0_effect_prior_scales_with_eligible_facedown_lines():
    e = Engine(protocols1=["Smoke", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    c = _card(e, "Smoke", 0, 1)

    # 뒷면 카드가 보드에 하나도 없으면 -- 실제로도 아무 일도 안 일어남 -> 0점
    assert effect_prior(e, 1, c) == 0.0

    # 라인1에 뒷면 카드 1장(소유자 무관) -> 자격 라인 1개
    fd1 = _card(e, "Water", 3, 2, face_up=False)
    e.players[2]["stacks"][1].append(fd1)
    assert effect_prior(e, 1, c) == pytest.approx(1.0)

    # 라인2에도 뒷면 카드 추가 -> 자격 라인 2개
    fd2 = _card(e, "Ice", 1, 1, face_up=False)
    e.players[1]["stacks"][2].append(fd2)
    assert effect_prior(e, 1, c) == pytest.approx(2.0)


def test_life_0_effect_prior_scales_with_own_nonempty_lines():
    """Life_0은 ongoing 태그도 있어 deck_plays가 0이어도 기본 0.8점은
    남는다 -- deck_plays 쪽만 실제 라인 수만큼 늘어나는지 그 증분으로 확인."""
    e = Engine(protocols1=["Life", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    c = _card(e, "Life", 0, 1)

    base = effect_prior(e, 1, c)  # 자격 라인 0개 -> ongoing(0.8)만
    assert base == pytest.approx(0.8)

    mine = _card(e, "Water", 3, 1, face_up=True)
    e.players[1]["stacks"][1].append(mine)
    assert effect_prior(e, 1, c) == pytest.approx(base + 1.0)


def test_water_1_unconditional_deck_plays_still_flat_two():
    """무조건부 deck_plays(정수 그대로)는 기존처럼 보드 상태와 무관하게
    고정값이어야 한다 -- 이번 수정이 조건부 카드 케이스만 건드렸는지 확인."""
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    c = _card(e, "Water", 1, 1)
    assert effect_prior(e, 1, c) == pytest.approx(2.0)


def test_diversity_6_effect_prior_penalizes_playing_when_diversity_would_stay_low():
    """Diversity_6은 End에 판 전체의 서로 다른 프로토콜 종류가 4개 미만이면
    자기 자신을 제거한다. 지금 낸다고 해도(자신의 'Diversity' 프로토콜을
    보태도) 여전히 4개 미만이면, 같은 턴 End 페이즈에 즉시 제거될 게
    뻔하므로 ongoing 보너스(0.8)를 상쇄하고도 남을 만큼 감점돼야 한다."""
    e = Engine(protocols1=["Diversity", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    c = _card(e, "Diversity", 6, 1)

    # 판에 이미 앞면으로 드러난 프로토콜은 Fire, Ice 2종뿐 -> 이 카드를
    # 내도(+Diversity) 3종에 그쳐 여전히 4 미만.
    e.players[1]["stacks"][2].append(_card(e, "Fire", 1, 1))
    e.players[2]["stacks"][1].append(_card(e, "Ice", 1, 2))

    assert effect_prior(e, 1, c) == pytest.approx(0.8 - 8.0)


def test_diversity_6_effect_prior_has_no_penalty_once_diversity_is_safe():
    """판에 이미 서로 다른 프로토콜이 4종(이 카드가 보탤 'Diversity'
    포함해서) 갖춰져 있으면, End 체크를 통과하니 ongoing 기본 보너스만
    남아야 한다."""
    e = Engine(protocols1=["Diversity", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    c = _card(e, "Diversity", 6, 1)

    e.players[1]["stacks"][2].append(_card(e, "Fire", 1, 1))
    e.players[1]["stacks"][3].append(_card(e, "Water", 1, 1))
    e.players[2]["stacks"][1].append(_card(e, "Ice", 1, 2))

    assert effect_prior(e, 1, c) == pytest.approx(0.8)


def test_diversity_6_effect_prior_still_penalized_when_another_diversity_card_already_counted():
    """판에 이미 다른 Diversity 앞면 카드가 있으면, 이 카드는 새로운
    프로토콜 종류를 보태지 못한다(같은 프로토콜) -- 그래서 현재 3종뿐이면
    이 카드를 내도 여전히 3종에 머물러 위험이 그대로 유지돼야 한다."""
    e = Engine(protocols1=["Diversity", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    c = _card(e, "Diversity", 6, 1)

    e.players[1]["stacks"][1].append(_card(e, "Diversity", 1, 1))
    e.players[1]["stacks"][2].append(_card(e, "Fire", 1, 1))
    e.players[2]["stacks"][1].append(_card(e, "Ice", 1, 2))

    assert effect_prior(e, 1, c) == pytest.approx(0.8 - 8.0)


def test_choose_line_defers_the_currently_resolving_cards_own_line():
    """Overwhelm_2 실전 버그(사용자 리포트): "각 라인마다 카드를 낸다" 류
    효과(Life_0/Smoke_0/Momentum_0/Overwhelm_1/Overwhelm_2)가 라인을 하나씩
    순서대로 물을 때, AI가 지금 발동 중인 카드 자신이 있는 라인을 먼저
    골라버리면 그 즉시 자기 자신을 덮어 명령이 조기 중단된다(공식 FAQ).
    다른 후보가 남아있는 한 그 라인은 맨 뒤로 미뤄야 한다."""
    e = Engine(protocols1=["Overwhelm", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    source = _card(e, "Overwhelm", 2, 1)  # 소스 카드 자신 -- 라인 1에 홀로 있어
    e.players[1]["stacks"][1].append(source)  # 값 2로 자연스럽게 가장 유리한 라인이 됨

    req = {"type": "chooseLine", "chooser": 1, "candidates": [1, 2, 3], "intent": "play",
           "sourceUid": source.uid}
    assert choose_line(e, req) != 1  # 자기 라인이 제일 유리해도 다른 후보부터

    # 다른 후보가 하나도 없으면(그 라인만 남았으면) 당연히 그 라인을 골라야 함.
    req_only = {"type": "chooseLine", "chooser": 1, "candidates": [1], "intent": "play",
                "sourceUid": source.uid}
    assert choose_line(e, req_only) == 1

    # sourceUid가 없으면(다른 카드가 발동한 chooseLine) 기존처럼 그냥
    # 값 기준으로 고른다 -- 이번 수정이 무관한 상황까지 바꾸면 안 됨.
    req_no_source = {"type": "chooseLine", "chooser": 1, "candidates": [1, 2, 3], "intent": "play"}
    assert choose_line(e, req_no_source) == 1


# ---------------------------------------------------------------------------
# choose_line() move intent -- 이미 컴파일 조건을 만족한(누가 컴파일하든 곧
# 그 라인의 양쪽 카드가 전부 사라지는) 라인은 이동 목적지로서 약하게
# 감점된다 (260803_logic_fix.md 버그 #3, 실전 리포트: 멀쩡한 카드를 곧
# 사라질 라인으로 옮기는 낭비). 원천 배제(-1000)가 아니라 약한 페널티
# (-6)인 이유: 상대의 값비싼 카드를 그 라인으로 옮겨 상대 자신의
# 컴파일에 같이 날려버리거나, 내 카드로 상대 우세를 뒤집어 컴파일 자체를
# 막는 것처럼 더 강한 이유가 있으면 여전히 그쪽을 고를 수 있어야 하기
# 때문 -- 그래서 "격차가 작을 때는 피하고, 격차가 크면 그래도 고른다"
# 두 경우를 각각 테스트한다.
# ---------------------------------------------------------------------------

def test_choose_line_move_intent_avoids_a_line_i_am_about_to_compile_when_close():
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    # 라인1: 내가 이미 컴파일 조건 충족(값10, 상대 0) -- 곧 통째로 사라질 라인.
    for v in (4, 3, 2, 1):
        e.players[1]["stacks"][1].append(_card(e, "Water", v, 1))
    # 라인2: 정상 진행 중(값5) -- 페널티 없이는 라인1(10)에 밀리지만, -6
    # 페널티가 붙으면(10-6=4) 라인2(5)가 더 매력적이어야 한다.
    e.players[1]["stacks"][2].append(_card(e, "Fire", 5, 1))

    assert e.line_value(1, 1) >= COMPILE_THRESHOLD and e.winning_line(1, 1)

    req = {"chooser": 1, "candidates": [1, 2], "intent": "move"}
    assert choose_line(e, req) == 2


def test_choose_line_move_intent_avoids_a_line_the_opponent_is_about_to_compile_when_close():
    """do_compile()은 컴파일하는 쪽뿐 아니라 그 라인의 양쪽 카드를 전부
    지운다 -- 그러니 '상대가' 이기고 있어 곧 컴파일할 라인도 내 카드가
    같이 사라지므로, 격차가 작을 땐 피해야 한다."""
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    # 라인1: 상대가 이미 컴파일 조건 충족(값10), 나는 9(상대가 근소 우세).
    for v in (4, 3, 2):
        e.players[1]["stacks"][1].append(_card(e, "Water", v, 1))  # 나: 9
    for v in (4, 3, 2, 1):
        e.players[2]["stacks"][1].append(_card(e, "Ice", v, 2))    # 상대: 10
    # 라인2: 정상 진행 중(값4).
    e.players[1]["stacks"][2].append(_card(e, "Fire", 4, 1))

    assert e.line_value(2, 1) >= COMPILE_THRESHOLD and e.winning_line(2, 1)
    # 페널티 없이 계산하면 라인1이 여전히 더 매력적임을 먼저 확인
    # (9 - 10*0.3 = 6 > 라인2의 4) -- 이 격차를 -6 페널티가 뒤집어야 의미있는 테스트.
    assert (9 - 10 * 0.3) > 4

    req = {"chooser": 1, "candidates": [1, 2], "intent": "move"}
    assert choose_line(e, req) == 2


def test_choose_line_move_intent_can_still_pick_an_imminent_line_when_the_gap_is_large():
    """대조군: 약한 페널티(-6)라, 대안이 훨씬 약하면 컴파일 임박 라인도
    여전히 고를 수 있어야 한다 -- 예를 들어 상대의 값비싼 카드를 상대
    자신의 컴파일에 같이 날려버리는 것처럼, 더 강한 전략적 이유가 있는
    경우를 원천 봉쇄하면 안 되기 때문(260803_logic_fix.md 논의 참고)."""
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    for v in (4, 3, 2, 1):
        e.players[1]["stacks"][1].append(_card(e, "Water", v, 1))  # 라인1: 값10, 컴파일 임박
    e.players[1]["stacks"][2].append(_card(e, "Fire", 1, 1))       # 라인2: 값1, 훨씬 약함

    assert e.line_value(1, 1) >= COMPILE_THRESHOLD and e.winning_line(1, 1)

    req = {"chooser": 1, "candidates": [1, 2], "intent": "move"}
    assert choose_line(e, req) == 1  # 10-6=4 > 1, 페널티가 있어도 여전히 라인1


def test_choose_line_move_intent_unaffected_when_no_line_is_compile_imminent():
    """대조군: 컴파일 임박 라인이 전혀 없는 평범한 상황에선 기존처럼 그냥
    값이 큰 라인을 그대로 고른다 -- 이번 수정이 무관한 상황까지 바꾸면 안 됨."""
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    e.players[1]["stacks"][1].append(_card(e, "Water", 5, 1))  # 라인1: 값5 (아직 미달)
    e.players[1]["stacks"][2].append(_card(e, "Fire", 2, 1))   # 라인2: 값2

    req = {"chooser": 1, "candidates": [1, 2], "intent": "move"}
    assert choose_line(e, req) == 1  # 컴파일 임박이 아니므로 그냥 값 큰 라인


def test_choose_line_play_intent_is_not_affected_by_this_fix():
    """이번 수정은 move intent만 범위(260803_logic_fix.md §3.3) -- play
    intent는 컴파일 임박 라인이어도 여전히 값 기준으로 그대로 고른다."""
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    for v in (4, 5, 3):
        e.players[1]["stacks"][1].append(_card(e, "Water", v, 1))
    e.players[1]["stacks"][2].append(_card(e, "Fire", 4, 1))

    req = {"chooser": 1, "candidates": [1, 2], "intent": "play"}
    assert choose_line(e, req) == 1  # play는 이번 수정 대상이 아니므로 그대로 값 큰 라인1
