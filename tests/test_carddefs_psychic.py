from src.game.carddefs import get
from tests.conftest import make_ai


def test_psychic_0_draws_and_forces_opp_discard(dealt_engine):
    e = dealt_engine
    c = e.new_card("Psychic", 0, 1)
    c.definition = get("Psychic", 0)
    opp_hand = e.players[2]["hand"]
    to_discard = [x.uid for x in opp_hand[:2]]
    make_ai(e, 2, [to_discard])

    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    assert len(e.players[1]["hand"]) == hand_before + 2
    assert len(e.players[2]["discard"]) == 2


def test_psychic_1_passive_and_flips_self_on_start(engine):
    e = engine
    c = e.new_card("Psychic", 1, 1)
    c.face_up = False
    c.definition = get("Psychic", 1)
    assert c.definition["passive"]["oppOnlyFacedown"] is True
    e.players[1]["stacks"][1].append(c)
    c.definition["start"](e, c)
    assert c.face_up is True


def test_psychic_2_discards_and_rearranges_opponent(dealt_engine):
    e = dealt_engine
    c = e.new_card("Psychic", 2, 1)
    c.definition = get("Psychic", 2)
    e.players[2]["protocols"] = {1: "Ice", 2: "Metal", 3: "Psychic"}
    opp_hand = e.players[2]["hand"]
    to_discard = [x.uid for x in opp_hand[:2]]

    make_ai(e, 2, [to_discard])
    make_ai(e, 1, [{1: 3, 2: 1, 3: 2}])
    c.definition["play"](e, c)
    assert len(e.players[2]["discard"]) == 2
    assert e.players[2]["protocols"] == {1: "Psychic", 2: "Ice", 3: "Metal"}


def test_psychic_3_discards_then_optionally_moves(dealt_engine):
    e = dealt_engine
    c = e.new_card("Psychic", 3, 1)
    c.definition = get("Psychic", 3)
    opp_target = e.new_card("Speed", 0, 2)
    opp_target.face_up = True
    e.players[2]["stacks"][1].append(opp_target)
    opp_hand = e.players[2]["hand"]
    to_discard = [opp_hand[0].uid]

    make_ai(e, 2, [to_discard])
    make_ai(e, 1, [opp_target.uid, 3])
    c.definition["play"](e, c)
    assert len(e.players[2]["discard"]) == 1
    assert opp_target in e.players[2]["stacks"][3]


def test_psychic_4_can_predicate_and_finish(engine):
    e = engine
    c = e.new_card("Psychic", 4, 1)
    c.face_up = True
    c.definition = get("Psychic", 4)
    e.players[1]["stacks"][1].append(c)

    assert c.definition["can"]["finish"](e, c) is False  # 대상 없음

    opp_card = e.new_card("Speed", 0, 2)
    opp_card.face_up = True
    e.players[2]["stacks"][2].append(opp_card)
    assert c.definition["can"]["finish"](e, c) is True

    make_ai(e, 1, [opp_card.uid])
    c.definition["finish"](e, c)
    assert opp_card in e.players[2]["hand"]
    assert c.face_up is False  # 앞면이었다가 flip_card로 뒷면이 됨


def test_psychic_5_shares_discard_one():
    assert get("Psychic", 5) is get("Water", 5)
