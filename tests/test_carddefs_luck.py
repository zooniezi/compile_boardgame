from src.game.carddefs import get
from tests.conftest import make_ai, neutral_card


def test_luck_0_states_number_and_may_play_match(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Luck", 0, 1)
    c.definition = get("Luck", 0)
    e.players[1]["deck"].append(neutral_card(e, "Water", 3, 1))  # 덱 top이 값3

    make_ai(e, 1, [3, None, True, 2])
    # 1) 숫자=3, 2) 매칭 후보 중 선택 안 함(폴백=matches[0]), 3) 낼지 여부=True,
    # 4) 낼 라인=2 (Fire 라인이라 뒷면만 가능해서 위/아래 선택 프롬프트는 안 뜸)
    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    # 3장 뽑고, 그중 하나(값3)를 다시 냈으니 순변화 +2
    assert len(e.players[1]["hand"]) == hand_before + 2


def test_luck_1_plays_facedown_then_flips_without_middle(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Luck", 1, 1)
    c.definition = get("Luck", 1)
    triggered = []
    fd_card = neutral_card(e, "Water", 0, 1)
    fd_card.definition = {"play": lambda g, cc: triggered.append("middle")}
    e.players[1]["deck"].append(fd_card)

    make_ai(e, 1, [1])
    c.definition["play"](e, c)
    assert e.players[1]["stacks"][1][0].face_up is True
    assert triggered == []  # noMiddle=True라 middle 발동 안 함


def test_luck_2_mills_and_draws_by_value(engine):
    e = engine
    c = neutral_card(e, "Luck", 2, 1)
    c.definition = get("Luck", 2)
    milled = neutral_card(e, "Water", 4, 1)
    filler = [neutral_card(e, "Fire", 0, 1) for _ in range(6)]
    e.players[1]["deck"] = filler + [milled]  # milled가 top, 리셔플 걱정 없을 만큼 덱이 충분함

    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    assert milled in e.players[1]["discard"]
    assert len(e.players[1]["hand"]) == hand_before + 4


def test_luck_3_states_protocol_and_deletes_on_match(engine):
    e = engine
    c = neutral_card(e, "Luck", 3, 1)
    c.definition = get("Luck", 3)
    e.players[2]["protocols"] = {1: "Ice", 2: "Metal", 3: "Death"}
    e.players[2]["deck"] = [neutral_card(e, "Ice", 0, 2)]  # top이 Ice

    target = neutral_card(e, "Water", 0, 1)
    target.face_up = True
    e.players[1]["stacks"][1].append(target)

    make_ai(e, 1, ["Ice", target.uid])
    c.definition["play"](e, c)
    assert target in e.players[1]["discard"]


def test_luck_4_mills_and_deletes_matching_value(engine):
    e = engine
    c = neutral_card(e, "Luck", 4, 1)
    c.definition = get("Luck", 4)
    e.players[1]["deck"] = [neutral_card(e, "Water", 3, 1)]

    target = neutral_card(e, "Ice", 3, 2)
    target.face_up = True
    e.players[2]["stacks"][1].append(target)

    make_ai(e, 1, [target.uid])
    c.definition["play"](e, c)
    assert target in e.players[2]["discard"]


def test_luck_5_shares_discard_one():
    assert get("Luck", 5) is get("Water", 5)
