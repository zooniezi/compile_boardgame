from src.game.carddefs import get
from tests.conftest import make_ai, neutral_card


def test_assimilation_0_takes_opponent_facedown_card(engine):
    e = engine
    c = neutral_card(e, "Assimilation", 0, 1)
    c.definition = get("Assimilation", 0)
    target = neutral_card(e, "Water", 0, 2)
    target.face_up = False
    e.players[2]["stacks"][1].append(target)

    make_ai(e, 1, [target.uid])
    c.definition["play"](e, c)
    assert target in e.players[1]["hand"]
    assert target.owner == 1


def test_assimilation_1_discard_refresh_then_reactive_gives_to_opp(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Assimilation", 1, 1)
    c.definition = get("Assimilation", 1)
    make_ai(e, 1, [[e.players[1]["hand"][0].uid]])
    c.definition["play"](e, c)  # discard 1, refresh
    assert len(e.players[1]["hand"]) == 5

    fn = c.definition["reactive"]["afterRefresh"]
    give_uid = e.players[1]["hand"][0].uid
    make_ai(e, 1, [give_uid])
    opp_deck_before = len(e.players[2]["deck"])
    fn(e, c, 1, None, None)
    assert len(e.players[1]["hand"]) == 5 + 1 - 1  # 상대덱에서 1장, 1장은 넘김
    assert len(e.players[2]["deck"]) == opp_deck_before - 1


def test_assimilation_2_can_and_finish_play_opp_deck_top(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Assimilation", 2, 1)
    c.face_up = True
    c.definition = get("Assimilation", 2)
    e.players[1]["stacks"][1].append(c)

    assert c.definition["can"]["finish"](e, c) is True
    opp_deck_before = len(e.players[2]["deck"])
    c.definition["finish"](e, c)
    assert len(e.players[1]["stacks"][1]) == 2
    assert len(e.players[2]["deck"]) == opp_deck_before - 1


def test_assimilation_2_can_false_on_empty_opp_deck(engine):
    e = engine
    c = neutral_card(e, "Assimilation", 2, 1)
    c.face_up = True
    c.definition = get("Assimilation", 2)
    e.players[1]["stacks"][1].append(c)
    e.players[2]["deck"] = []
    assert c.definition["can"]["finish"](e, c) is False


def test_assimilation_4_swaps_deck_tops(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Assimilation", 4, 1)
    c.definition = get("Assimilation", 4)
    hand1_before = len(e.players[1]["hand"])
    hand2_before = len(e.players[2]["hand"])
    c.definition["play"](e, c)
    assert len(e.players[1]["hand"]) == hand1_before + 1
    assert len(e.players[2]["hand"]) == hand2_before + 1


def test_assimilation_5_shares_discard_one():
    assert get("Assimilation", 5) is get("Water", 5)


def test_assimilation_6_plays_own_deck_top_on_opponent_side(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Assimilation", 6, 1)
    c.definition = get("Assimilation", 6)
    assert c.definition["can"]["finish"](e, c) is True

    make_ai(e, 1, [2])
    deck_before = len(e.players[1]["deck"])
    c.definition["finish"](e, c)
    assert len(e.players[1]["deck"]) == deck_before - 1
    assert len(e.players[2]["stacks"][2]) == 1
    assert e.players[2]["stacks"][2][0].owner == 2
