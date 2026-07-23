from src.game.carddefs import get
from tests.conftest import make_ai, neutral_card


def test_ice_1_play_may_move(engine):
    e = engine
    c = neutral_card(e, "Ice", 1, 1)
    c.face_up = True
    c.definition = get("Ice", 1)
    e.players[1]["stacks"][1].append(c)
    make_ai(e, 1, [True, 2])
    c.definition["play"](e, c)
    assert c in e.players[1]["stacks"][2]


def test_ice_1_reactive_after_play_discards_when_same_line(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Ice", 1, 1)
    fn = get("Ice", 1)["reactive"]["afterPlay"]
    make_ai(e, 2, [[e.players[2]["hand"][0].uid]])

    fn(e, c, 2, {"line": 1}, {"line": 1})  # actor(2) != owner(1), 같은 라인
    assert len(e.players[2]["discard"]) == 1

    fn(e, c, 2, {"line": 2}, {"line": 1})  # 라인이 다름 -> 발동 안 함
    assert len(e.players[2]["discard"]) == 1

    fn(e, c, 1, {"line": 1}, {"line": 1})  # actor == owner -> 발동 안 함
    assert len(e.players[1]["discard"]) == 0


def test_ice_2_moves_another_card(engine):
    e = engine
    c = neutral_card(e, "Ice", 2, 1)
    c.face_up = True
    c.definition = get("Ice", 2)
    e.players[1]["stacks"][1].append(c)
    other = neutral_card(e, "Water", 0, 1)
    other.face_up = True
    e.players[1]["stacks"][1].append(other)

    make_ai(e, 1, [other.uid, 2])
    c.definition["play"](e, c)
    assert other in e.players[1]["stacks"][2]


def test_ice_3_only_moves_when_covered(engine):
    e = engine
    c = neutral_card(e, "Ice", 3, 1)
    c.face_up = True
    c.definition = get("Ice", 3)
    e.players[1]["stacks"][1].append(c)
    assert c.definition["can"]["finishTop"](e, c) is False  # uncovered

    covering = neutral_card(e, "Water", 0, 1)
    e.place_on_stack(covering, 1, 1, True)
    assert c.definition["can"]["finishTop"](e, c) is True
    make_ai(e, 1, [True, 2])
    c.definition["finishTop"](e, c)
    assert c in e.players[1]["stacks"][2]


def test_ice_4_cant_flip_flag(engine):
    e = engine
    c = neutral_card(e, "Ice", 4, 1)
    c.face_up = True
    c.definition = get("Ice", 4)
    e.players[1]["stacks"][1].append(c)
    assert e.can_flip(c) is False
    e.flip_card(c)
    assert c.face_up is True  # 안 뒤집힘


def test_ice_5_shares_discard_one():
    assert get("Ice", 5) is get("Water", 5)


def test_ice_6_passive_blocks_draw_with_hand(engine):
    e = engine
    c = neutral_card(e, "Ice", 6, 1)
    c.face_up = True
    c.definition = get("Ice", 6)
    e.players[1]["stacks"][1].append(c)
    e.players[1]["hand"] = [neutral_card(e, "Water", 0, 1)]
    assert e.draw_blocked(1) is True
    e.players[1]["hand"] = []
    assert e.draw_blocked(1) is False
