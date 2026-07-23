from src.game.carddefs import get
from tests.conftest import make_ai


def test_fire_0_play_flips_and_draws(dealt_engine):
    e = dealt_engine
    c = e.new_card("Fire", 0, 1)
    c.face_up = True
    c.definition = get("Fire", 0)
    e.players[1]["stacks"][1].append(c)
    target = e.new_card("Water", 0, 1)
    target.face_up = True
    e.players[1]["stacks"][2].append(target)

    make_ai(e, 1, [target.uid])
    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    assert target.face_up is False
    assert len(e.players[1]["hand"]) == hand_before + 2


def test_fire_0_on_covered_draws_and_flips(dealt_engine):
    e = dealt_engine
    c = e.new_card("Fire", 0, 1)
    c.face_up = True
    c.definition = get("Fire", 0)
    e.players[1]["stacks"][1].append(c)
    target = e.new_card("Water", 0, 1)
    target.face_up = True
    e.players[1]["stacks"][2].append(target)

    make_ai(e, 1, [target.uid])
    hand_before = len(e.players[1]["hand"])
    covering = e.new_card("Metal", 0, 1)
    e.place_on_stack(covering, 1, 1, True)  # onCovered 트리거

    assert target.face_up is False
    assert len(e.players[1]["hand"]) == hand_before + 1


def test_fire_1_discards_then_deletes(dealt_engine):
    e = dealt_engine
    c = e.new_card("Fire", 1, 1)
    c.definition = get("Fire", 1)
    to_discard = e.players[1]["hand"][0]
    target = e.new_card("Ice", 0, 2)
    target.face_up = True
    e.players[2]["stacks"][1].append(target)

    make_ai(e, 1, [[to_discard.uid], target.uid])
    c.definition["play"](e, c)
    assert to_discard in e.players[1]["discard"]
    assert target in e.players[2]["discard"]


def test_fire_1_no_delete_if_hand_empty(engine):
    e = engine
    c = e.new_card("Fire", 1, 1)
    c.definition = get("Fire", 1)
    e.players[1]["hand"] = []
    target = e.new_card("Ice", 0, 2)
    target.face_up = True
    e.players[2]["stacks"][1].append(target)

    c.definition["play"](e, c)  # 프롬프트가 아예 안 불려야 함 (discard가 0 반환)
    assert target in e.players[2]["stacks"][1]  # 안 지워짐


def test_fire_2_discards_then_returns(dealt_engine):
    e = dealt_engine
    c = e.new_card("Fire", 2, 1)
    c.definition = get("Fire", 2)
    to_discard = e.players[1]["hand"][0]
    target = e.new_card("Ice", 0, 2)
    target.face_up = True
    e.players[2]["stacks"][1].append(target)

    make_ai(e, 1, [[to_discard.uid], target.uid])
    c.definition["play"](e, c)
    assert to_discard in e.players[1]["discard"]
    assert target in e.players[2]["hand"]


def test_fire_3_can_predicate_and_finish(dealt_engine):
    e = dealt_engine
    c = e.new_card("Fire", 3, 1)
    c.definition = get("Fire", 3)

    e.players[1]["hand"] = []
    assert c.definition["can"]["finish"](e, c) is False

    e.players[1]["hand"] = e.players[1]["hand"] or [e.new_card("Water", 0, 1)]
    assert c.definition["can"]["finish"](e, c) is True

    to_discard = e.players[1]["hand"][0]
    target = e.new_card("Metal", 0, 1)
    target.face_up = True
    e.players[1]["stacks"][2].append(target)
    make_ai(e, 1, [True, [to_discard.uid], target.uid])
    c.definition["finish"](e, c)
    assert to_discard in e.players[1]["discard"]
    assert target.face_up is False


def test_fire_4_draws_discarded_plus_one(dealt_engine):
    e = dealt_engine
    c = e.new_card("Fire", 4, 1)
    c.definition = get("Fire", 4)
    hand = e.players[1]["hand"]
    to_discard = [hand[0].uid, hand[1].uid]

    make_ai(e, 1, [to_discard])
    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    # 2장 버리고 3장(2+1) 뽑음 -> 순변화 +1
    assert len(e.players[1]["hand"]) == hand_before - 2 + 3


def test_fire_4_empty_hand_still_draws_one(engine):
    e = engine
    c = e.new_card("Fire", 4, 1)
    c.definition = get("Fire", 4)
    e.players[1]["hand"] = []
    e.players[1]["deck"] = [e.new_card("Water", 0, 1)]

    c.definition["play"](e, c)
    assert len(e.players[1]["hand"]) == 1  # 0장 버렸어도 0+1=1장 뽑음


def test_fire_5_shares_discard_one():
    assert get("Fire", 5) is get("Water", 5)
