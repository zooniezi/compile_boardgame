from src.game.carddefs import get
from tests.conftest import make_ai, neutral_card


def test_time_0_plays_from_trash_then_reshuffles(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Time", 0, 1)
    c.definition = get("Time", 0)
    trash_card = neutral_card(e, "Water", 0, 1)
    e.players[1]["discard"] = [trash_card]

    make_ai(e, 1, [trash_card.uid, 2, "down"])
    c.definition["play"](e, c)
    assert trash_card in e.players[1]["stacks"][2]
    assert e.players[1]["discard"] == []


def test_time_0_reshuffles_even_without_trash_pick(engine):
    e = engine
    c = neutral_card(e, "Time", 0, 1)
    c.definition = get("Time", 0)
    leftover = neutral_card(e, "Water", 0, 1)
    e.players[1]["discard"] = [leftover]
    e.players[1]["deck"] = []

    make_ai(e, 1, [None])  # 트래시에서 낼 카드 선택을 거절
    c.definition["play"](e, c)
    assert leftover in e.players[1]["deck"]


def test_time_1_flips_covered_card_then_discards_deck(engine):
    e = engine
    c = neutral_card(e, "Time", 1, 1)
    c.definition = get("Time", 1)
    bottom = neutral_card(e, "Water", 0, 1)
    bottom.face_up = False
    top = neutral_card(e, "Fire", 0, 1)
    top.face_up = True
    e.players[1]["stacks"][1].extend([bottom, top])
    e.players[1]["deck"] = [neutral_card(e, "Water", 0, 1) for _ in range(3)]

    make_ai(e, 1, [bottom.uid])
    c.definition["play"](e, c)
    assert bottom.face_up is True
    assert e.players[1]["deck"] == []
    assert len(e.players[1]["discard"]) == 3


def test_time_2_reactive_top_after_shuffle(engine):
    e = engine
    c = neutral_card(e, "Time", 2, 1)
    c.face_up = True
    c.definition = get("Time", 2)
    e.players[1]["stacks"][1].append(c)
    e.players[1]["deck"] = [neutral_card(e, "Water", 0, 1)]

    make_ai(e, 1, [True, 2])
    fn = c.definition["reactiveTop"]["afterShuffle"]
    hand_before = len(e.players[1]["hand"])
    fn(e, c, 1)
    assert len(e.players[1]["hand"]) == hand_before + 1
    assert c in e.players[1]["stacks"][2]


def test_time_2_play_may_shuffle_trash(engine):
    e = engine
    c = neutral_card(e, "Time", 2, 1)
    c.definition = get("Time", 2)
    discarded = neutral_card(e, "Water", 0, 1)
    e.players[1]["discard"] = [discarded]
    e.players[1]["deck"] = []
    make_ai(e, 1, [True])
    c.definition["play"](e, c)
    assert discarded in e.players[1]["deck"]


def test_time_3_reveals_and_plays_facedown_elsewhere(engine):
    e = engine
    c = neutral_card(e, "Time", 3, 1)
    c.definition = get("Time", 3)
    e.players[1]["stacks"][1].append(c)
    trash_card = neutral_card(e, "Water", 0, 1)
    e.players[1]["discard"] = [trash_card]

    make_ai(e, 1, [trash_card.uid, 2])
    c.definition["play"](e, c)
    assert trash_card in e.players[1]["stacks"][2]
    assert trash_card.face_up is False
    assert e.players[1]["discard"] == []


class _Peek2AI:
    def decide(self, g, req):
        if req.get("type") == "chooseHandCards":
            h = g.players[1]["hand"]
            return [h[0].uid, h[1].uid]
        return None

    def planRearrange(self, g, pi, compiling_line):
        return None


def test_time_4_draws_then_discards_two(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Time", 4, 1)
    c.definition = get("Time", 4)
    e.players[1]["isAI"] = True
    e.ai_modules[1] = _Peek2AI()

    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    assert len(e.players[1]["hand"]) == hand_before


def test_time_5_shares_discard_one():
    assert get("Time", 5) is get("Water", 5)
