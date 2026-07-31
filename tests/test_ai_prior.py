"""ai_prior.py -- 카드 효과 태그 + 상황별 채점(effect_prior) 회귀 테스트.

270장 전부 채워짐 (Aux1 18 + Main1 72 + Main2 72 + Aux2 18 + Main3 72 + Aux3 18).
"""

import pytest

from src.game.carddefs import DEFS
from src.game.engine import Engine
from src.game.ai_prior import TAGS, effect_prior, defusable_threat, plan_rearrange, score_action, choose_line


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
