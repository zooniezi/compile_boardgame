"""ai_prior.py -- 카드 효과 태그 + 상황별 채점(effect_prior) 회귀 테스트.

180장 전부 채워짐 (Aux1 18 + Main1 72 + Main2 72 + Aux2 18).
"""

from src.game.carddefs import DEFS
from src.game.engine import Engine
from src.game.ai_prior import TAGS, effect_prior, defusable_threat, plan_rearrange


def test_all_180_cards_have_a_tag():
    missing = [k for k in DEFS if k not in TAGS]
    assert not missing, f"태그 없는 카드({len(missing)}장): {missing}"


def test_no_tag_points_to_a_nonexistent_card():
    orphan = [k for k in TAGS if k not in DEFS]
    assert not orphan, f"존재하지 않는 카드를 가리키는 태그: {orphan}"


def test_tags_cover_exactly_180_cards():
    assert len(TAGS) == 180
    assert len(DEFS) == 180


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
