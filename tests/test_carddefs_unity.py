from src.game.carddefs import get
from tests.conftest import make_ai, neutral_card


def test_unity_0_play_only_when_two_or_more_unity(engine):
    e = engine
    c = neutral_card(e, "Unity", 0, 1)
    c.definition = get("Unity", 0)
    c.face_up = True
    e.players[1]["stacks"][1].append(c)
    hand_before = len(e.players[1]["hand"])
    e.players[1]["deck"] = [neutral_card(e, "Water", 0, 1)]
    c.definition["play"](e, c)  # Unity 카드 1장뿐(자기 자신) -> 발동 안 함
    assert len(e.players[1]["hand"]) == hand_before

    other_unity = neutral_card(e, "Unity", 1, 1)
    other_unity.face_up = True
    e.players[1]["stacks"][2].append(other_unity)
    make_ai(e, 1, ["draw"])
    c.definition["play"](e, c)
    assert len(e.players[1]["hand"]) == hand_before + 1


def test_unity_0_on_covered_triggers_on_incoming_unity(engine):
    e = engine
    c = neutral_card(e, "Unity", 0, 1)
    c.face_up = True
    c.definition = get("Unity", 0)
    e.players[1]["stacks"][1].append(c)
    e.players[1]["deck"] = [neutral_card(e, "Water", 0, 1)]

    make_ai(e, 1, ["draw"])
    incoming = neutral_card(e, "Unity", 2, 1)
    hand_before = len(e.players[1]["hand"])
    e.place_on_stack(incoming, 1, 1, True)
    assert len(e.players[1]["hand"]) == hand_before + 1


def test_unity_1_flag_and_start_top_move_when_covered(engine):
    e = engine
    c = neutral_card(e, "Unity", 1, 1)
    c.face_up = True
    c.definition = get("Unity", 1)
    assert c.definition["allowFaceUpHere"] == "Unity"
    e.players[1]["stacks"][1].append(c)
    assert c.definition["can"]["startTop"](e, c) is False

    covering = neutral_card(e, "Water", 0, 1)
    e.place_on_stack(covering, 1, 1, True)
    assert c.definition["can"]["startTop"](e, c) is True
    make_ai(e, 1, [True, 2])
    c.definition["startTop"](e, c)
    assert c in e.players[1]["stacks"][2]


def test_unity_1_play_compiles_and_clears_at_five(engine):
    e = engine
    c = neutral_card(e, "Unity", 1, 1)
    c.definition = get("Unity", 1)
    e.players[1]["protocols"] = {1: "Water", 2: "Unity", 3: "Life"}
    e.players[2]["stacks"][2].append(neutral_card(e, "Water", 0, 2))
    for i in range(4):
        u = neutral_card(e, "Unity", i, 1)
        u.face_up = True
        e.players[1]["stacks"][2].append(u)
    # 지금까지 라인2에 Unity 카드 4장 + 이 카드(c)를 내면 5장째

    c.face_up = True
    e.players[1]["stacks"][2].append(c)
    c.definition["play"](e, c)
    assert e.players[1]["compiled"][2] is True
    assert e.players[1]["stacks"][2] == []
    assert e.players[2]["stacks"][2] == []


def test_unity_2_draws_by_unity_count(engine):
    e = engine
    c = neutral_card(e, "Unity", 2, 1)
    c.face_up = True
    c.definition = get("Unity", 2)
    e.players[1]["stacks"][1].append(c)
    e.players[1]["deck"] = [neutral_card(e, "Water", 0, 1) for _ in range(3)]
    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    assert len(e.players[1]["hand"]) == hand_before + 1  # c 자신 포함 1장


def test_unity_3_optional_flip_when_two_or_more(engine):
    e = engine
    c = neutral_card(e, "Unity", 3, 1)
    c.face_up = True
    c.definition = get("Unity", 3)
    e.players[1]["stacks"][1].append(c)
    other = neutral_card(e, "Unity", 0, 1)
    other.face_up = True
    e.players[1]["stacks"][2].append(other)

    make_ai(e, 1, [other.uid])
    c.definition["play"](e, c)
    assert other.face_up is False


def test_unity_4_finish_top_only_on_empty_hand(engine):
    e = engine
    c = neutral_card(e, "Unity", 4, 1)
    c.definition = get("Unity", 4)
    e.players[1]["hand"] = [neutral_card(e, "Water", 0, 1)]
    assert c.definition["can"]["finishTop"](e, c) is False

    e.players[1]["hand"] = []
    assert c.definition["can"]["finishTop"](e, c) is True
    u1 = neutral_card(e, "Unity", 0, 1)
    other = neutral_card(e, "Water", 0, 1)
    e.players[1]["deck"] = [other, u1]
    c.definition["finishTop"](e, c)
    assert u1 in e.players[1]["hand"]
    assert other in e.players[1]["deck"]


def test_unity_5_shares_discard_one():
    assert get("Unity", 5) is get("Water", 5)
