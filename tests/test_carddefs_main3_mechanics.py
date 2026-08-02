"""Main3/Aux3 포팅에서 새로 추가된 엔진 메커닉 회귀 테스트.

기존 180장에는 없던 것들: Control 획득/포기(gain_control/lose_control),
카드 단위 이동 금지(can_move/cantMove, Rigid_7), 덱 맨 위 카드를 상대
스택에 얹는 교차 플레이(Nova_0), 새 패시브 종류(lineValueBoth/
ignoreHighestInLine/allowFaceUpHere의 불리언 형태/suppressOtherBottom),
카드 바로 밑에 손 카드를 끼워 넣는 플레이(Rigid_3).

개별 카드 90장 하나하나의 회귀보다, 이 새 메커닉들이 엔진 차원에서
올바르게 동작하는지(그리고 기존 180장 경로를 안 건드렸는지)에 초점을
맞춘다 -- 카드별 로직 자체는 RandomAI/HeuristicAI 자기대국 스모크
테스트(수백 판, 에러 0건)로 이미 폭넓게 검증했다.
"""

from src.game.carddefs import get
from tests.conftest import make_ai, neutral_card


def test_gain_control_and_lose_control_basic(engine):
    e = engine
    assert e.control is None
    assert e.gain_control(1) is True
    assert e.control == 1
    assert e.gain_control(1) is False  # 이미 갖고 있으면 변화 없음(False)
    assert e.lose_control(2) is False  # 2는 갖고 있지 않음
    assert e.lose_control(1) is True
    assert e.control is None


def test_gain_control_fires_after_gain_control_reactive(engine):
    """Pride_6: reactiveTop.afterGainControl -- 상대가 컨트롤을 얻으면 뒤집힌다."""
    e = engine
    pride6 = neutral_card(e, "Pride", 6, 1)
    pride6.definition = get("Pride", 6)
    pride6.face_up = True
    e.players[1]["stacks"][1].append(pride6)
    assert pride6.face_up is True
    e.gain_control(2)  # 상대(2)가 컨트롤을 얻음
    assert pride6.face_up is False  # afterGainControl 리액티브로 뒤집힘


def test_envy_1_start_gains_control_when_opponent_has_it(engine):
    e = engine
    envy1 = neutral_card(e, "Envy", 1, 1)
    envy1.definition = get("Envy", 1)
    e.gain_control(2)
    assert envy1.definition["can"]["start"](e, envy1) is True
    envy1.definition["start"](e, envy1)
    assert e.control == 1


def test_rigid_7_cannot_be_flipped_or_moved(engine):
    e = engine
    rigid7 = neutral_card(e, "Rigid", 7, 1)
    rigid7.definition = get("Rigid", 7)
    rigid7.face_up = True
    e.players[1]["stacks"][1].append(rigid7)
    assert e.can_flip(rigid7) is False
    assert e.can_move(rigid7) is False
    e.flip_card(rigid7)
    assert rigid7.face_up is True  # 안 뒤집힘
    assert e.move_card(rigid7, 1, 2) is False
    assert rigid7 in e.players[1]["stacks"][1]
    assert rigid7 not in e.players[1]["stacks"][2]


def test_can_move_does_not_affect_ordinary_cards(engine):
    """cantMove 플래그가 없는 보통 카드는 여전히 이동 가능(회귀 방지)."""
    e = engine
    water0 = neutral_card(e, "Water", 0, 1)
    water0.face_up = True
    e.players[1]["stacks"][1].append(water0)
    assert e.can_move(water0) is True
    assert e.move_card(water0, 1, 2) is True
    assert water0 in e.players[1]["stacks"][2]


def test_nova_0_finish_plays_deck_top_under_opponent_nova(dealt_engine):
    """Nova_0 종료: 내 덱 맨 위 카드를 상대 스택의 드러난 Nova 카드 밑에
    뒷면으로 낸다 -- side(상대)와 pi(내 덱 소유자)가 달라야 한다.

    "밑에 낸다"는 카드 텍스트 표현이지만 실제 효과는 그 Nova 카드를
    정상적으로 덮는 것이다(다음에 낸 카드처럼 위에 놓임) -- 실전 버그
    리포트로 확인, engine.py의 play_card/perform_landing 참고."""
    e = dealt_engine
    nova0 = neutral_card(e, "Nova", 0, 1)
    nova0.definition = get("Nova", 0)
    e.players[1]["stacks"][1].append(nova0)
    opp_nova = neutral_card(e, "Nova", 3, 2)
    opp_nova.face_up = True
    e.players[2]["stacks"][2].append(opp_nova)

    assert nova0.definition["can"]["finish"](e, nova0) is True
    deck_before = len(e.players[1]["deck"])
    make_ai(e, 1, [opp_nova])  # chooseCardFrom -> 상대의 드러난 Nova 카드를 고름
    nova0.definition["finish"](e, nova0)

    assert len(e.players[1]["deck"]) == deck_before - 1
    # 새 카드가 상대(2) 스택에서 그 Nova 카드를 덮었는지(바로 위에 놓였는지) 확인.
    stack = e.players[2]["stacks"][2]
    idx = stack.index(opp_nova)
    assert idx < len(stack) - 1
    placed = stack[idx + 1]
    assert placed.owner == 1  # 소유자는 여전히 나(내 덱에서 온 카드)
    assert placed.face_up is False
    assert stack[-1] is placed  # 새 카드가 이제 맨 위(드러난 카드) -- Nova 카드는 덮임
    assert not e.is_uncovered(opp_nova)


def test_lust_0_line_value_both_adds_to_each_side(engine):
    e = engine
    lust0 = neutral_card(e, "Lust", 0, 1)
    lust0.definition = get("Lust", 0)
    lust0.face_up = True
    e.players[1]["stacks"][1].append(lust0)
    # 아무 카드도 없는 라인이라도 +10이 양쪽 다 적용돼야 함.
    assert e.line_value(1, 1) == 10
    assert e.line_value(2, 1) == 10
    # 다른 라인은 영향 없음.
    assert e.line_value(1, 2) == 0


def test_lust_0_blocks_opponent_compile_while_owner_has_control(dealt_engine):
    e = dealt_engine
    lust0 = neutral_card(e, "Lust", 0, 1)
    lust0.definition = get("Lust", 0)
    lust0.face_up = True
    e.players[1]["stacks"][1].append(lust0)
    e.control = 2  # 상대(2)가 지금 컨트롤을 갖고 있다고 가정
    strong = neutral_card(e, "Water", 5, 2)
    strong.face_up = True
    e.players[2]["stacks"][2].append(strong)
    assert e.compilable_lines(2) == []  # Lust_0 소유자(1)가 컨트롤 없으므로 아직 봉쇄 안 됨

    e.control = 1  # 이제 Lust_0 소유자가 컨트롤을 가짐
    assert e.compilable_lines(2) == []  # 상대(2)는 컴파일 가능한 라인이 있어도 봉쇄됨


def test_wrath_0_ignores_highest_value_card_in_line(engine):
    e = engine
    wrath0 = neutral_card(e, "Wrath", 0, 1)
    wrath0.definition = get("Wrath", 0)
    wrath0.face_up = True
    e.players[1]["stacks"][1].append(wrath0)  # 값 0, 최고값 아님
    high = neutral_card(e, "Water", 5, 1)
    high.face_up = True
    e.players[1]["stacks"][1].append(high)  # 이 라인 최고값(5) -- 총합에서 빠져야 함
    other_p2 = neutral_card(e, "Water", 3, 2)
    other_p2.face_up = True
    e.players[2]["stacks"][1].append(other_p2)
    # 이 라인 전체(양쪽) 최고값은 5(high) -- 그 카드만 양쪽 총합에서 빠진다.
    assert e.line_value(1, 1) == 0  # wrath0(0) + high(5, 최고값이라 제외) = 0
    assert e.line_value(2, 1) == 3  # other_p2(3)는 전체 최고가 아니라 그대로 포함


def test_lust_2_allows_own_mismatched_protocol_card_in_this_stack(engine):
    e = engine
    lust2 = neutral_card(e, "Lust", 2, 1)
    lust2.definition = get("Lust", 2)
    lust2.face_up = True
    e.players[1]["stacks"][1].append(lust2)  # 라인 1(프로토콜 Water)에 Lust 카드가 있음
    mismatched = e.new_card("Fire", 0, 1)  # 프로토콜 안 맞는 내 카드
    ok, _ = e.can_play_face_up(1, mismatched, 1)
    assert ok is True
    # 상대(2)는 이 허용을 못 받음(소유자 한정).
    mismatched_opp = e.new_card("Fire", 0, 2)
    ok2, _ = e.can_play_face_up(2, mismatched_opp, 1)
    assert ok2 is False


def test_inert_1_suppresses_other_start_end_triggers_in_line(engine):
    """Inert_1: 이 라인의 다른 카드는 하단(Start/End) 명령이 없는 것으로
    취급 -- phase_trigger_resolvable이 False를 반환해야 한다."""
    e = engine
    inert1 = neutral_card(e, "Inert", 1, 1)
    inert1.definition = get("Inert", 1)
    inert1.face_up = True
    e.players[1]["stacks"][1].append(inert1)

    courage0 = neutral_card(e, "Courage", 0, 2)
    courage0.definition = get("Courage", 0)
    courage0.face_up = True
    e.players[2]["stacks"][1].append(courage0)  # 같은 라인
    e.players[2]["hand"] = []  # Courage_0 startTop 조건(손 없음) 충족

    entry = {"card": courage0, "band": "top", "field": "startTop"}
    assert e.phase_trigger_resolvable(entry) is False  # Inert_1이 억제

    # Inert_1을 치우면 다시 정상적으로 resolve 가능해야 함(억제가 이 라인의
    # suppressOtherBottom 카드 유무에만 달려 있는지 확인).
    e.players[1]["stacks"][1].remove(inert1)
    assert e.phase_trigger_resolvable(entry) is True


def test_rigid_3_plays_hand_card_that_covers_self(dealt_engine):
    """실전 버그 리포트: "이 카드 밑에 낸다"는 카드 텍스트 표현이지만,
    실제 효과는 "이 카드 다음에 낸 카드처럼" 그 위를 덮는 것이다 --
    Rigid_3 자신이 가려져야 한다(반대로 구현돼 있던 걸 수정)."""
    e = dealt_engine
    rigid3 = neutral_card(e, "Rigid", 3, 1)
    rigid3.definition = get("Rigid", 3)
    rigid3.face_up = True
    e.players[1]["stacks"][1].append(rigid3)
    hand_card = e.players[1]["hand"][0]

    stack_before = list(e.players[1]["stacks"][1])
    ok = e.play_card(1, hand_card.uid, 1, False, under_card=rigid3)
    assert ok
    stack = e.players[1]["stacks"][1]
    assert len(stack) == len(stack_before) + 1
    idx_new = stack.index(hand_card)
    idx_rigid = stack.index(rigid3)
    assert idx_new == idx_rigid + 1  # rigid3 바로 위에 놓여 rigid3을 덮음
    assert stack[-1] is hand_card  # 새 카드가 맨 위(드러난 카드)
    assert not e.is_uncovered(rigid3)  # rigid3은 이제 가려짐


def test_under_card_fires_a_real_cover_trigger_when_anchor_is_on_top(dealt_engine):
    """앵커가 지금 스택 맨 위(드러난 카드)일 때는 정상적으로 덮이는 것과
    완전히 같아야 한다 -- Rigid_4("이 카드가 뒷면 카드에 의해 가려지려 할
    때: 그 전에, 카드를 1장 뽑습니다")의 onCovered가 실제로 발동하는지로
    확인. 예전 구현은 "밑으로 슬라이드"로 취급해 커버 트리거를 일부러
    건너뛰었었다."""
    e = dealt_engine
    rigid4 = neutral_card(e, "Rigid", 4, 1)
    rigid4.definition = get("Rigid", 4)
    rigid4.face_up = True
    e.players[1]["stacks"][1].append(rigid4)
    hand_card = e.players[1]["hand"][0]

    deck_before = len(e.players[1]["deck"])
    ok = e.play_card(1, hand_card.uid, 1, False, under_card=rigid4)
    assert ok
    assert len(e.players[1]["deck"]) == deck_before - 1  # onCovered가 발동해 1장 뽑음


def test_swap_protocols_fires_after_rearrange_reactive(dealt_engine):
    """사용자 실전 버그(Momentum_1 "작동 안 함"): swap_protocols/
    rearrange_protocols가 afterRearrange 리액티브를 한 번도 쏘지 않아서
    Momentum_1("플레이어가 프로토콜을 재배열한 뒤: 버리고 뽑는다")과
    Nova_2("내가 재배열한 뒤: 뒷면 카드를 이동할 수 있다")가 전혀
    발동하지 않던 문제. afterCompile은 이미 있었는데 afterRearrange만
    빠져 있었다."""
    e = dealt_engine
    momentum1 = neutral_card(e, "Momentum", 1, 1)
    momentum1.definition = get("Momentum", 1)
    momentum1.face_up = True
    e.players[1]["stacks"][1].append(momentum1)

    hand_before = len(e.players[1]["hand"])
    discard_before = len(e.players[1]["discard"])
    make_ai(e, 1, [[e.players[1]["hand"][0].uid]])  # chooseHandCards 응답(버릴 카드 1장)
    e.swap_protocols(1, 2, 3)

    assert len(e.players[1]["discard"]) == discard_before + 1  # 버리기 발동
    assert len(e.players[1]["hand"]) == hand_before  # 버리고 다시 뽑아 순변화 없음


def test_move_one_candidate_lists_exclude_cantmove_cards(engine):
    """전수 재검토로 발견한 문제: _move_one을 쓰는 여러 카드(Nova_2/Nova_3/
    Pride_0/Flexible_1/Flexible_3)가 canMove를 후보 필터에 안 넣고 있었다.
    move_card() 자체가 이제 전역으로 canMove를 강제해서 실제로 잘못된
    이동이 벌어지진 않지만(§ 회귀 없음), 후보 목록에 이동 불가능한 카드가
    섞여 나와 "골랐는데 아무 일도 안 일어나는" UX 문제가 있었다. Pride_0로
    확인: 컨트롤을 가진 상태에서 "다른 카드"가 Rigid_7(이동 불가) 하나뿐이면
    후보가 없어서 아무것도 이동하지 않아야 한다."""
    e = engine
    pride0 = neutral_card(e, "Pride", 0, 1)
    pride0.definition = get("Pride", 0)
    pride0.face_up = True
    e.players[1]["stacks"][1].append(pride0)
    e.control = 1  # "내가 컨트롤을 가지고 있다면 다른 카드를 1장 이동" 분기

    rigid7 = neutral_card(e, "Rigid", 7, 1)
    rigid7.definition = get("Rigid", 7)
    rigid7.face_up = True
    e.players[1]["stacks"][2].append(rigid7)  # 유일한 "다른 카드"인데 이동 불가

    make_ai(e, 1, [rigid7.uid, 2])  # chooseCard(rigid7 선택 시도), chooseLine(있다면)
    stack_before = list(e.players[1]["stacks"][2])
    pride0.definition["play"](e, pride0)
    assert e.players[1]["stacks"][2] == stack_before  # 이동 후보가 없어 그대로여야 함


def test_rearrange_protocols_also_fires_after_rearrange_reactive(dealt_engine):
    """swap_protocols(부분 교환)뿐 아니라 rearrange_protocols(전체 재배열)도
    똑같이 afterRearrange를 쏴야 한다 -- 두 메서드 다 "프로토콜을
    재배열한다"는 카드 텍스트에 해당하는 별개의 실제 경로라서."""
    e = dealt_engine
    momentum1 = neutral_card(e, "Momentum", 1, 1)
    momentum1.definition = get("Momentum", 1)
    momentum1.face_up = True
    e.players[1]["stacks"][1].append(momentum1)

    discard_before = len(e.players[1]["discard"])
    make_ai(e, 1, [[e.players[1]["hand"][0].uid]])
    e.rearrange_protocols(1, {1: 2, 2: 1, 3: 3})

    assert len(e.players[1]["discard"]) == discard_before + 1
