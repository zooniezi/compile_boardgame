from src.game.carddefs import get
from tests.conftest import make_ai, neutral_card


def test_chaos_0_flips_one_covered_per_line_and_draws_from_both_decks(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Chaos", 0, 1)
    c.face_up = True
    c.definition = get("Chaos", 0)
    e.players[1]["stacks"][1].append(c)
    covered1 = neutral_card(e, "Water", 0, 1)
    covered1.face_up = False
    e.players[1]["stacks"][1].append(covered1)  # c 위에 놓여 c를 덮음
    covered2 = neutral_card(e, "Ice", 0, 2)
    covered2.face_up = False
    top2 = neutral_card(e, "Metal", 0, 2)
    top2.face_up = True
    e.players[2]["stacks"][2].extend([covered2, top2])

    make_ai(e, 1, [covered1.uid, covered2.uid, None])
    c.definition["play"](e, c)
    assert covered1.face_up is True
    assert covered2.face_up is True

    p1_deck_before = len(e.players[1]["deck"])
    p2_deck_before = len(e.players[2]["deck"])
    hand1_before = len(e.players[1]["hand"])
    hand2_before = len(e.players[2]["hand"])
    c.definition["start"](e, c)
    assert len(e.players[1]["hand"]) == hand1_before + 1
    assert len(e.players[2]["hand"]) == hand2_before + 1
    assert len(e.players[1]["deck"]) == p1_deck_before - 1
    assert len(e.players[2]["deck"]) == p2_deck_before - 1


def test_chaos_1_rearranges_both_sides(engine):
    e = engine
    c = neutral_card(e, "Chaos", 1, 1)
    c.definition = get("Chaos", 1)
    e.players[1]["protocols"] = {1: "Water", 2: "Fire", 3: "Chaos"}
    e.players[2]["protocols"] = {1: "Ice", 2: "Metal", 3: "Death"}

    make_ai(e, 1, [{1: 3, 2: 1, 3: 2}, {1: 2, 2: 3, 3: 1}])
    c.definition["play"](e, c)
    assert e.players[1]["protocols"] == {1: "Chaos", 2: "Water", 3: "Fire"}
    assert e.players[2]["protocols"] == {1: "Metal", 2: "Death", 3: "Ice"}


def test_chaos_2_moves_own_covered_card(engine):
    e = engine
    c = neutral_card(e, "Chaos", 2, 1)
    c.definition = get("Chaos", 2)
    e.players[1]["stacks"][1].append(c)
    covered = neutral_card(e, "Water", 0, 1)
    covered.face_up = True
    top = neutral_card(e, "Fire", 0, 1)
    top.face_up = True
    e.players[1]["stacks"][2].extend([covered, top])

    make_ai(e, 1, [covered.uid, 3])
    c.definition["play"](e, c)
    assert covered in e.players[1]["stacks"][3]


def test_chaos_3_free_play_flag():
    assert get("Chaos", 3)["freePlay"] is True


def test_chaos_4_discards_hand_then_redraws(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Chaos", 4, 1)
    c.definition = get("Chaos", 4)
    assert c.definition["can"]["finish"](e, c) is True

    hand_size = len(e.players[1]["hand"])
    c.definition["finish"](e, c)
    assert len(e.players[1]["discard"]) == hand_size
    assert len(e.players[1]["hand"]) == hand_size


def test_chaos_4_can_predicate_false_on_empty_hand(engine):
    e = engine
    c = neutral_card(e, "Chaos", 4, 1)
    c.definition = get("Chaos", 4)
    e.players[1]["hand"] = []
    assert c.definition["can"]["finish"](e, c) is False


def test_chaos_5_shares_discard_one():
    assert get("Chaos", 5) is get("Water", 5)
