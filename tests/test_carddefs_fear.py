from src.game.carddefs import get
from tests.conftest import make_ai, neutral_card


def test_fear_0_passive_and_shift_choice(engine):
    e = engine
    c = neutral_card(e, "Fear", 0, 1)
    c.definition = get("Fear", 0)
    assert c.definition["passive"]["oppNoMiddle"] is True
    mover = neutral_card(e, "Water", 0, 1)
    mover.face_up = True
    e.players[1]["stacks"][1].append(mover)

    make_ai(e, 1, ["shift", mover.uid, 2])
    c.definition["play"](e, c)
    assert mover in e.players[1]["stacks"][2]


def test_fear_0_flip_choice(engine):
    e = engine
    c = neutral_card(e, "Fear", 0, 1)
    c.definition = get("Fear", 0)
    target = neutral_card(e, "Water", 0, 1)
    target.face_up = False
    e.players[1]["stacks"][1].append(target)

    make_ai(e, 1, ["flip", target.uid])
    c.definition["play"](e, c)
    assert target.face_up is True


def test_fear_1_draws_and_forces_opponent_redraw(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Fear", 1, 1)
    c.definition = get("Fear", 1)
    opp_hand_size = len(e.players[2]["hand"])

    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    assert len(e.players[1]["hand"]) == hand_before + 2
    assert len(e.players[2]["discard"]) == opp_hand_size
    assert len(e.players[2]["hand"]) == opp_hand_size - 1  # n-1 = 4


def test_fear_2_returns_opponent_card(engine):
    e = engine
    c = neutral_card(e, "Fear", 2, 1)
    c.definition = get("Fear", 2)
    target = neutral_card(e, "Water", 0, 2)
    target.face_up = True
    e.players[2]["stacks"][1].append(target)
    make_ai(e, 1, [target.uid])
    c.definition["play"](e, c)
    assert target in e.players[2]["hand"]


def test_fear_3_moves_opponent_card_in_same_line(engine):
    e = engine
    c = neutral_card(e, "Fear", 3, 1)
    c.definition = get("Fear", 3)
    e.players[1]["stacks"][1].append(c)
    target = neutral_card(e, "Water", 0, 2)
    target.face_up = True
    e.players[2]["stacks"][1].append(target)

    make_ai(e, 1, [target.uid, 3])
    c.definition["play"](e, c)
    assert target in e.players[2]["stacks"][3]


def test_fear_4_discards_random_opponent_card(engine):
    e = engine
    c = neutral_card(e, "Fear", 4, 1)
    c.definition = get("Fear", 4)
    only_card = neutral_card(e, "Water", 0, 2)
    e.players[2]["hand"] = [only_card]

    c.definition["play"](e, c)  # rng(1)=1 항상, 대상이 하나뿐이라 결정론적
    assert only_card in e.players[2]["discard"]


def test_fear_5_shares_discard_one():
    assert get("Fear", 5) is get("Water", 5)
