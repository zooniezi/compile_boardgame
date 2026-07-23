from src.game.carddefs import get
from tests.conftest import make_ai


def test_plague_0_passive_and_play(dealt_engine):
    e = dealt_engine
    c = e.new_card("Plague", 0, 1)
    c.definition = get("Plague", 0)
    assert c.definition["passive"]["oppNoPlayHere"] is True

    to_discard_uid = e.players[2]["hand"][0].uid
    make_ai(e, 2, [[to_discard_uid]])
    c.definition["play"](e, c)
    assert len(e.players[2]["discard"]) == 1


def test_plague_1_reactive_top_draws_on_opponent_discard():
    from src.game.card import Card
    c_def = get("Plague", 1)
    fn = c_def["reactiveTop"]["afterDiscard"]
    dummy = Card(uid=1, proto="Plague", value=1, owner=1, definition=c_def)

    class FakeGame:
        def __init__(self):
            self.drew = None

        def draw(self, pi, n):
            self.drew = (pi, n)

    fake = FakeGame()
    fn(fake, dummy, 1, None, None)  # 자신이 버림 -> 반응 안 함
    assert fake.drew is None
    fn(fake, dummy, 2, None, None)  # 상대가 버림 -> 반응
    assert fake.drew == (1, 1)


def test_plague_2_opponent_discards_one_more_than_owner(dealt_engine):
    e = dealt_engine
    c = e.new_card("Plague", 2, 1)
    c.definition = get("Plague", 2)
    hand = e.players[1]["hand"]
    to_discard = [x.uid for x in hand[:2]]

    make_ai(e, 1, [to_discard])
    opp_hand = e.players[2]["hand"]
    to_discard_opp = [x.uid for x in opp_hand[:3]]  # n+1 = 3
    make_ai(e, 2, [to_discard_opp])

    opp_before = len(e.players[2]["hand"])
    c.definition["play"](e, c)
    assert len(e.players[1]["discard"]) == 2
    assert len(e.players[2]["discard"]) == 3


def test_plague_2_empty_hand_still_forces_opponent_discard_one(engine):
    e = engine
    c = e.new_card("Plague", 2, 1)
    c.definition = get("Plague", 2)
    e.players[1]["hand"] = []
    opp_card = e.new_card("Psychic", 0, 2)
    e.players[2]["hand"] = [opp_card]
    make_ai(e, 2, [[opp_card.uid]])

    c.definition["play"](e, c)
    assert opp_card in e.players[2]["discard"]


def test_plague_3_flips_all_other_face_up_uncovered_cards(engine):
    e = engine
    c = e.new_card("Plague", 3, 1)
    c.face_up = True
    c.definition = get("Plague", 3)
    e.players[1]["stacks"][1].append(c)
    target1 = e.new_card("Psychic", 0, 1)
    target1.face_up = True
    covered = e.new_card("Speed", 0, 1)
    covered.face_up = True
    top_of_that_stack = e.new_card("Ice", 0, 1)
    top_of_that_stack.face_up = True
    e.players[1]["stacks"][2].append(target1)
    e.players[1]["stacks"][3].extend([covered, top_of_that_stack])

    c.definition["play"](e, c)
    assert target1.face_up is False
    assert top_of_that_stack.face_up is False
    assert covered.face_up is True  # covered라 대상 아님
    assert c.face_up is True  # 자기 자신 제외


def test_plague_4_finish_deletes_then_may_flip(engine):
    e = engine
    c = e.new_card("Plague", 4, 1)
    c.definition = get("Plague", 4)
    fd = e.new_card("Psychic", 0, 2)
    fd.face_up = False
    e.players[2]["stacks"][1].append(fd)

    make_ai(e, 2, [fd.uid])
    make_ai(e, 1, [True])
    c.definition["finish"](e, c)
    assert fd in e.players[2]["discard"]
    assert c.face_up is True


def test_plague_5_shares_discard_one():
    assert get("Plague", 5) is get("Water", 5)
