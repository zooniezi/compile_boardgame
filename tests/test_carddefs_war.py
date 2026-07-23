from src.game.carddefs import get
from tests.conftest import make_ai, neutral_card


def test_war_0_reactive_top_and_reactive(engine):
    e = engine
    c = neutral_card(e, "War", 0, 1)
    c.face_up = True
    c.definition = get("War", 0)
    e.players[1]["stacks"][1].append(c)

    make_ai(e, 1, [True])
    fn_top = c.definition["reactiveTop"]["afterRefresh"]
    fn_top(e, c, 1)
    assert c.face_up is False

    c.face_up = True
    target = neutral_card(e, "Water", 0, 1)
    target.face_up = True
    e.players[1]["stacks"][2].append(target)
    make_ai(e, 1, [target.uid])
    fn_react = c.definition["reactive"]["afterDraw"]
    fn_react(e, c, 2, None, None)
    assert target in e.players[1]["discard"]


def test_war_1_reactive_after_refresh_discards_then_refreshes(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "War", 1, 1)
    c.definition = get("War", 1)
    hand = e.players[1]["hand"]
    make_ai(e, 1, [[hand[0].uid]])

    fn = c.definition["reactive"]["afterRefresh"]
    hand_before = len(hand)
    fn(e, c, 2, None, None)
    assert len(e.players[1]["discard"]) == 1
    assert len(e.players[1]["hand"]) == 5  # 리프레시로 다시 5장


def test_war_1_no_react_on_own_refresh(engine):
    e = engine
    c = neutral_card(e, "War", 1, 1)
    c.definition = get("War", 1)
    fn = c.definition["reactive"]["afterRefresh"]
    fn(e, c, 1, None, None)  # actor == owner -> 무반응
    assert e.players[1]["hand"] == []


def test_war_2_play_and_reactive_after_compile(engine):
    e = engine
    c = neutral_card(e, "War", 2, 1)
    c.definition = get("War", 2)
    target = neutral_card(e, "Water", 0, 1)
    target.face_up = False
    e.players[1]["stacks"][1].append(target)
    make_ai(e, 1, [target.uid])
    c.definition["play"](e, c)
    assert target.face_up is True

    fn = c.definition["reactive"]["afterCompile"]
    opp_hand_card = neutral_card(e, "Water", 0, 2)
    e.players[2]["hand"] = [opp_hand_card]
    fn(e, c, 2, None, None)
    assert e.players[2]["hand"] == []
    assert opp_hand_card in e.players[2]["discard"]


def test_war_3_play_and_reactive_after_discard(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "War", 3, 1)
    c.definition = get("War", 3)
    e.players[1]["stacks"][1].append(c)

    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    assert len(e.players[1]["hand"]) == hand_before + 1

    playable = e.players[1]["hand"][0]
    fn = c.definition["reactive"]["afterDiscard"]
    make_ai(e, 1, [True, playable.uid, 2])
    fn(e, c, 2, None, None)
    assert playable in e.players[1]["stacks"][2]
    assert playable.face_up is False


def test_war_4_forces_opponent_discard(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "War", 4, 1)
    c.definition = get("War", 4)
    make_ai(e, 2, [[e.players[2]["hand"][0].uid]])
    c.definition["play"](e, c)
    assert len(e.players[2]["discard"]) == 1


def test_war_5_shares_discard_one():
    assert get("War", 5) is get("Water", 5)
