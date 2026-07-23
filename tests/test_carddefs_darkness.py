from src.game.carddefs import get
from tests.conftest import make_ai


def test_darkness_0_draws_and_moves_opp_covered_card(dealt_engine):
    e = dealt_engine
    c = e.new_card("Darkness", 0, 1)
    c.definition = get("Darkness", 0)
    bottom = e.new_card("Psychic", 0, 2)
    bottom.face_up = True
    top = e.new_card("Speed", 0, 2)
    top.face_up = True
    e.players[2]["stacks"][1].extend([bottom, top])

    make_ai(e, 1, [bottom.uid, 2])
    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    assert len(e.players[1]["hand"]) == hand_before + 3
    assert bottom in e.players[2]["stacks"][2]


def test_darkness_1_flips_opp_card_and_moves(engine):
    e = engine
    c = e.new_card("Darkness", 1, 1)
    c.definition = get("Darkness", 1)
    target = e.new_card("Psychic", 0, 2)
    target.face_up = False
    e.players[2]["stacks"][1].append(target)

    make_ai(e, 1, [target.uid, True, 2])
    c.definition["play"](e, c)
    assert target.face_up is True
    assert target in e.players[2]["stacks"][2]


def test_darkness_2_passive_and_flips_covered_in_own_line(engine):
    e = engine
    c = e.new_card("Darkness", 2, 1)
    c.face_up = True
    c.definition = get("Darkness", 2)
    assert c.definition["passive"]["facedownValueThisStack"] == 4
    covered = e.new_card("Psychic", 0, 1)
    covered.face_up = False
    e.players[1]["stacks"][1].extend([covered, c])

    make_ai(e, 1, [covered.uid])
    c.definition["play"](e, c)
    assert covered.face_up is True


def test_darkness_3_plays_hand_card_facedown_in_other_line(dealt_engine):
    e = dealt_engine
    c = e.new_card("Darkness", 3, 1)
    c.definition = get("Darkness", 3)
    e.players[1]["stacks"][1].append(c)
    picked = e.players[1]["hand"][0]

    make_ai(e, 1, [2, picked.uid])  # 목적지 라인2 -> 손 카드 선택
    c.definition["play"](e, c)
    assert picked in e.players[1]["stacks"][2]
    assert picked.face_up is False


def test_darkness_4_moves_a_facedown_card(engine):
    e = engine
    c = e.new_card("Darkness", 4, 1)
    c.definition = get("Darkness", 4)
    target = e.new_card("Psychic", 0, 1)
    target.face_up = False
    e.players[1]["stacks"][1].append(target)

    make_ai(e, 1, [target.uid, 2])
    c.definition["play"](e, c)
    assert target in e.players[1]["stacks"][2]


def test_darkness_5_shares_discard_one():
    assert get("Darkness", 5) is get("Water", 5)
