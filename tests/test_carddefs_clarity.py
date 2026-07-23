from src.game.carddefs import get
from tests.conftest import make_ai, neutral_card


def test_clarity_0_passive_line_value_equals_hand_size(engine):
    e = engine
    c = neutral_card(e, "Clarity", 0, 1)
    c.face_up = True
    c.definition = get("Clarity", 0)
    e.players[1]["stacks"][1].append(c)
    e.players[1]["hand"] = [neutral_card(e, "Water", 0, 1) for _ in range(3)]
    assert e.line_value(1, 1) == 0 + 3  # c 자신 값(0) + 손패 수(3)


def test_clarity_1_can_predicate_reveals_and_may_discard(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Clarity", 1, 1)
    c.definition = get("Clarity", 1)
    assert c.definition["can"]["startTop"](e, c) is True

    top_before = e.players[1]["deck"][-1]
    make_ai(e, 1, [True])
    deck_before = len(e.players[1]["deck"])
    c.definition["startTop"](e, c)
    assert len(e.players[1]["deck"]) == deck_before - 1
    assert top_before in e.players[1]["discard"]


def test_clarity_1_declines_discard(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Clarity", 1, 1)
    c.definition = get("Clarity", 1)
    make_ai(e, 1, [False])
    deck_before = len(e.players[1]["deck"])
    c.definition["startTop"](e, c)
    assert len(e.players[1]["deck"]) == deck_before


def test_clarity_1_can_false_on_empty_deck(engine):
    e = engine
    c = neutral_card(e, "Clarity", 1, 1)
    c.definition = get("Clarity", 1)
    e.players[1]["deck"] = []
    assert c.definition["can"]["startTop"](e, c) is False


def test_clarity_1_on_covered_draws_three(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Clarity", 1, 1)
    c.face_up = True
    c.definition = get("Clarity", 1)
    e.players[1]["stacks"][1].append(c)
    hand_before = len(e.players[1]["hand"])
    covering = neutral_card(e, "Water", 0, 1)
    e.place_on_stack(covering, 1, 1, True)
    assert len(e.players[1]["hand"]) == hand_before + 3


def test_clarity_2_fishes_value_1_and_plays_it(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Clarity", 2, 1)
    c.definition = get("Clarity", 2)
    fish_target = neutral_card(e, "Water", 1, 1)
    e.players[1]["deck"].append(fish_target)

    make_ai(e, 1, [fish_target.uid, fish_target.uid, 1, "down"])
    # 1) 낚기(chooseCard, showcase) -> fish_target
    # 2) playFromHand의 "낼 카드 선택"(chooseCard) -> fish_target
    # 3) chooseLineFrom -> 라인1
    # 4) fu+fd 둘 다 가능한 라인이라 "위/아래" 선택 -> down
    c.definition["play"](e, c)
    assert fish_target in e.players[1]["stacks"][1]


def test_clarity_3_fishes_value_5(engine):
    e = engine
    c = neutral_card(e, "Clarity", 3, 1)
    c.definition = get("Clarity", 3)
    fish_target = neutral_card(e, "Water", 5, 1)
    e.players[1]["deck"] = [fish_target]

    make_ai(e, 1, [fish_target.uid])
    c.definition["play"](e, c)
    assert fish_target in e.players[1]["hand"]


def test_clarity_4_may_reshuffle_discard(engine):
    e = engine
    c = neutral_card(e, "Clarity", 4, 1)
    c.definition = get("Clarity", 4)
    discarded = neutral_card(e, "Water", 0, 1)
    e.players[1]["discard"] = [discarded]
    e.players[1]["deck"] = []

    make_ai(e, 1, [True])
    c.definition["play"](e, c)
    assert discarded in e.players[1]["deck"]
    assert e.players[1]["discard"] == []


def test_clarity_5_shares_discard_one():
    assert get("Clarity", 5) is get("Water", 5)
