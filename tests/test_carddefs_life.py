from src.game.carddefs import get
from tests.conftest import make_ai


def test_life_0_processing_own_line_first_self_covers_and_stops(dealt_engine):
    """공식 FAQ: "이 과정에서 생명 0이 다른 카드에 의해 가려지면, 가운데
    명령은 즉시 중단됩니다." 자기 자신의 라인을 먼저 처리하면 그 뒷면 카드가
    Life_0 자신을 덮으므로, 그 시점에서 나머지 라인은 처리하지 않는다."""
    e = dealt_engine
    c = e.new_card("Life", 0, 1)
    c.face_up = True
    c.definition = get("Life", 0)
    e.players[1]["stacks"][1].append(c)  # 자기 라인(1)도 카드가 있으니 대상
    other = e.new_card("Metal", 0, 1)
    other.face_up = True
    e.players[1]["stacks"][2].append(other)
    # 라인3에는 카드 없음 -> 대상 아님

    # 대상 라인이 2개(1,2)라 어느 라인부터 낼지 프롬프트가 필요함.
    # 자기 라인(1)을 먼저 선택 -> 스스로 덮여서 라인2는 처리되지 않아야 함.
    make_ai(e, 1, [1])
    before_deck = len(e.players[1]["deck"])
    c.definition["play"](e, c)
    assert len(e.players[1]["stacks"][1]) == 2  # c 위에 뒷면 카드 하나 더 (덮임)
    assert len(e.players[1]["stacks"][2]) == 1  # 스스로 덮여 중단 -- 처리 안 됨
    assert e.players[1]["stacks"][3] == []
    assert len(e.players[1]["deck"]) == before_deck - 1


def test_life_0_processing_own_line_last_completes_both_lines(dealt_engine):
    """반대로 자기 라인을 마지막에 처리하도록 선택하면, 그때는 더 처리할
    라인이 안 남아있어서 중단될 일이 없다 -- 처리 순서가 실제 전략적 선택."""
    e = dealt_engine
    c = e.new_card("Life", 0, 1)
    c.face_up = True
    c.definition = get("Life", 0)
    e.players[1]["stacks"][1].append(c)
    other = e.new_card("Metal", 0, 1)
    other.face_up = True
    e.players[1]["stacks"][2].append(other)

    make_ai(e, 1, [2])  # 라인2를 먼저, 자기 라인(1)은 마지막
    before_deck = len(e.players[1]["deck"])
    c.definition["play"](e, c)
    assert len(e.players[1]["stacks"][1]) == 2
    assert len(e.players[1]["stacks"][2]) == 2  # 이번엔 정상 처리됨
    assert e.players[1]["stacks"][3] == []
    assert len(e.players[1]["deck"]) == before_deck - 2


def test_life_0_finish_top_deletes_self_only_if_covered(engine):
    e = engine
    c = e.new_card("Life", 0, 1)
    c.face_up = True
    c.definition = get("Life", 0)
    e.players[1]["stacks"][1].append(c)

    assert c.definition["can"]["finishTop"](e, c) is False  # uncovered
    c.definition["finishTop"](e, c)
    assert c in e.players[1]["stacks"][1]  # 안 지워짐

    covering = e.new_card("Metal", 0, 1)
    e.place_on_stack(covering, 1, 1, True)
    assert c.definition["can"]["finishTop"](e, c) is True
    c.definition["finishTop"](e, c)
    assert c in e.players[1]["discard"]


def test_life_1_flips_two_cards(engine):
    e = engine
    c = e.new_card("Life", 1, 1)
    c.definition = get("Life", 1)
    t1 = e.new_card("Metal", 0, 1)
    t1.face_up = True
    t2 = e.new_card("Speed", 0, 2)
    t2.face_up = False
    e.players[1]["stacks"][1].append(t1)
    e.players[2]["stacks"][1].append(t2)

    make_ai(e, 1, [t1.uid, t2.uid])
    c.definition["play"](e, c)
    assert t1.face_up is False
    assert t2.face_up is True


def test_life_2_draws_and_optionally_flips_facedown(dealt_engine):
    e = dealt_engine
    c = e.new_card("Life", 2, 1)
    c.definition = get("Life", 2)
    fd = e.new_card("Metal", 0, 1)
    fd.face_up = False
    e.players[1]["stacks"][1].append(fd)

    make_ai(e, 1, [fd.uid])
    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    assert len(e.players[1]["hand"]) == hand_before + 1
    assert fd.face_up is True


def test_life_3_on_covered_plays_facedown_elsewhere(engine):
    e = engine
    c = e.new_card("Life", 3, 1)
    c.face_up = True
    c.definition = get("Life", 3)
    e.players[1]["stacks"][1].append(c)
    e.players[1]["deck"] = [e.new_card("Metal", 0, 1)]

    make_ai(e, 1, [2])
    covering = e.new_card("Speed", 0, 1)
    e.place_on_stack(covering, 1, 1, True)  # onCovered 트리거
    assert len(e.players[1]["stacks"][2]) == 1
    assert e.players[1]["stacks"][2][0].face_up is False


def test_life_4_draws_only_when_covering_another_card(engine):
    e = engine
    c = e.new_card("Life", 4, 1)
    c.definition = get("Life", 4)
    bottom = e.new_card("Metal", 0, 1)
    bottom.face_up = True
    e.players[1]["stacks"][1].append(bottom)
    e.players[1]["stacks"][1].append(c)  # c가 bottom을 덮음 (idx=1)

    hand_before = len(e.players[1]["hand"])
    e.players[1]["deck"] = [e.new_card("Speed", 0, 1)]
    c.definition["play"](e, c)
    assert len(e.players[1]["hand"]) == hand_before + 1


def test_life_4_no_draw_when_alone_in_line(engine):
    e = engine
    c = e.new_card("Life", 4, 1)
    c.definition = get("Life", 4)
    e.players[1]["stacks"][1].append(c)  # idx=0, 아무것도 안 덮음
    e.players[1]["deck"] = [e.new_card("Speed", 0, 1)]

    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    assert len(e.players[1]["hand"]) == hand_before


def test_life_5_shares_discard_one():
    assert get("Life", 5) is get("Water", 5)
