from src.game.carddefs import get
from tests.conftest import make_ai, neutral_card


def test_corruption_0_flags_and_flips_own_faceup_card_in_stack(engine):
    e = engine
    c = neutral_card(e, "Corruption", 0, 1)
    c.face_up = True
    c.definition = get("Corruption", 0)
    assert c.definition["freePlay"] is True
    assert c.definition["playAnySide"] is True

    other = neutral_card(e, "Water", 0, 1)
    other.face_up = True
    e.players[1]["stacks"][1].extend([other, c])

    assert c.definition["can"]["startTop"](e, c) is True
    make_ai(e, 1, [other.uid])
    c.definition["startTop"](e, c)
    assert other.face_up is False


def test_corruption_0_can_false_with_no_flippable_own_card(engine):
    e = engine
    c = neutral_card(e, "Corruption", 0, 1)
    c.face_up = True
    c.definition = get("Corruption", 0)
    e.players[1]["stacks"][1].append(c)
    assert c.definition["can"]["startTop"](e, c) is False


def test_corruption_1_returns_to_deck_flag_and_play(engine):
    e = engine
    c = neutral_card(e, "Corruption", 1, 1)
    c.definition = get("Corruption", 1)
    assert c.definition["returnToDeck"] is True
    target = neutral_card(e, "Water", 0, 1)
    target.face_up = True
    e.players[1]["stacks"][1].append(target)
    make_ai(e, 1, [target.uid])
    c.definition["play"](e, c)
    assert target in e.players[1]["hand"]


def test_corruption_2_draw_discard_and_reactive(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Corruption", 2, 1)
    c.definition = get("Corruption", 2)
    hand = e.players[1]["hand"]
    make_ai(e, 1, [[hand[0].uid]])
    hand_before = len(hand)
    c.definition["play"](e, c)
    assert len(e.players[1]["hand"]) == hand_before  # +1 뽑고 -1 버림 상쇄

    fn = c.definition["reactiveTop"]["afterDiscard"]

    class FakeGame:
        def __init__(self):
            self.discarded = None

        def discard(self, pi, n):
            self.discarded = (pi, n)

    fake = FakeGame()
    fn(fake, c, 2, None, None)
    assert fake.discarded is None
    fn(fake, c, 1, None, None)
    assert fake.discarded == (2, 1)


def test_corruption_3_flips_a_covered_face_up_card(engine):
    e = engine
    c = neutral_card(e, "Corruption", 3, 1)
    c.definition = get("Corruption", 3)
    covered = neutral_card(e, "Water", 0, 2)
    covered.face_up = True
    top = neutral_card(e, "Fire", 0, 2)
    top.face_up = True
    e.players[2]["stacks"][1].extend([covered, top])

    make_ai(e, 1, [covered.uid])
    c.definition["play"](e, c)
    assert covered.face_up is False


def test_corruption_5_shares_discard_one():
    assert get("Corruption", 5) is get("Water", 5)


def test_corruption_6_forced_delete_on_empty_hand(engine):
    e = engine
    c = neutral_card(e, "Corruption", 6, 1)
    c.face_up = True
    c.definition = get("Corruption", 6)
    e.players[1]["stacks"][1].append(c)
    e.players[1]["hand"] = []
    c.definition["finishTop"](e, c)
    assert c in e.players[1]["discard"]


def test_corruption_6_offers_choice_with_hand(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Corruption", 6, 1)
    c.face_up = True
    c.definition = get("Corruption", 6)
    e.players[1]["stacks"][1].append(c)

    make_ai(e, 1, ["discard", [e.players[1]["hand"][0].uid]])
    c.definition["finishTop"](e, c)
    assert c in e.players[1]["stacks"][1]  # 삭제 안 됨
    assert len(e.players[1]["discard"]) == 1
