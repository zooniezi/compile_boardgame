from src.game.carddefs import get
from tests.conftest import make_ai


def test_metal_0_passive_and_flip(engine):
    e = engine
    c = e.new_card("Metal", 0, 1)
    c.definition = get("Metal", 0)
    assert c.definition["passive"]["lineValueOppDelta"] == -2

    opp_card = e.new_card("Water", 4, 2)
    opp_card.face_up = True
    c.face_up = True
    e.players[1]["stacks"][1].append(c)
    e.players[2]["stacks"][1].append(opp_card)
    assert e.line_value(2, 1) == 4 - 2  # Metal_0의 라인값 감소 패시브

    target = e.new_card("Psychic", 0, 1)
    target.face_up = False
    e.players[1]["stacks"][2].append(target)
    make_ai(e, 1, [target.uid])
    c.definition["play"](e, c)
    assert target.face_up is True


def test_metal_1_locks_opponent_compile(dealt_engine):
    e = dealt_engine
    c = e.new_card("Metal", 1, 1)
    c.definition = get("Metal", 1)
    assert e.cant_compile[2] is False
    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    assert e.cant_compile[2] is True
    assert len(e.players[1]["hand"]) == hand_before + 2


def test_metal_2_passive_blocks_facedown_plays():
    c = get("Metal", 2)
    assert c["passive"]["oppNoFacedownHere"] is True


def test_metal_3_deletes_crowded_other_line(dealt_engine):
    e = dealt_engine
    c = e.new_card("Metal", 3, 1)
    c.definition = get("Metal", 3)
    e.players[1]["stacks"][1].append(c)

    for i in range(4):
        x = e.new_card("Psychic", 0, 1)
        x.face_up = True
        e.players[1]["stacks"][2].append(x)
        y = e.new_card("Speed", 0, 2)
        y.face_up = True
        e.players[2]["stacks"][2].append(y)
    assert len(e.players[1]["stacks"][2]) + len(e.players[2]["stacks"][2]) == 8

    make_ai(e, 1, [2])  # 라인2 선택
    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    assert e.players[1]["stacks"][2] == []
    assert e.players[2]["stacks"][2] == []
    assert len(e.players[1]["hand"]) == hand_before + 1  # 드로우 1장


def test_metal_3_no_candidates_below_threshold(engine):
    e = engine
    c = e.new_card("Metal", 3, 1)
    c.definition = get("Metal", 3)
    e.players[1]["stacks"][1].append(c)
    small = e.new_card("Psychic", 0, 1)
    small.face_up = True
    e.players[1]["stacks"][2].append(small)

    c.definition["play"](e, c)  # 8장 미만이라 삭제 프롬프트 자체가 안 나와야 함
    assert small in e.players[1]["stacks"][2]


def test_metal_5_shares_discard_one():
    assert get("Metal", 5) is get("Water", 5)


def test_metal_6_self_destructs_instead_of_flip(engine):
    e = engine
    c = e.new_card("Metal", 6, 1)
    c.face_up = True
    c.definition = get("Metal", 6)
    e.players[1]["stacks"][1].append(c)

    e.flip_card(c)
    assert c in e.players[1]["discard"]
    assert e.players[1]["stacks"][1] == []


def test_metal_6_deletes_when_covered():
    from src.game.engine import Engine
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    c = e.new_card("Metal", 6, 1)
    c.face_up = True
    c.definition = get("Metal", 6)
    e.players[1]["stacks"][1].append(c)
    covering = e.new_card("Water", 0, 1)
    e.place_on_stack(covering, 1, 1, True)
    assert c in e.players[1]["discard"]
