from src.game.carddefs import get
from tests.conftest import make_ai


def test_hate_0_deletes_one_card(engine):
    e = engine
    c = e.new_card("Hate", 0, 1)
    c.definition = get("Hate", 0)
    target = e.new_card("Psychic", 0, 2)
    target.face_up = True
    e.players[2]["stacks"][1].append(target)
    make_ai(e, 1, [target.uid])
    c.definition["play"](e, c)
    assert target in e.players[2]["discard"]


def test_hate_1_discards_three_deletes_two(dealt_engine):
    e = dealt_engine
    c = e.new_card("Hate", 1, 1)
    c.definition = get("Hate", 1)
    t1 = e.new_card("Psychic", 0, 2)
    t1.face_up = True
    t2 = e.new_card("Speed", 0, 2)
    t2.face_up = True
    e.players[2]["stacks"][1].append(t1)
    e.players[2]["stacks"][2].append(t2)
    hand = e.players[1]["hand"]
    to_discard = [c_.uid for c_ in hand[:3]]

    make_ai(e, 1, [to_discard, t1.uid, t2.uid])
    c.definition["play"](e, c)
    assert len(e.players[1]["discard"]) == 3
    assert t1 in e.players[2]["discard"]
    assert t2 in e.players[2]["discard"]


def test_hate_2_deletes_own_then_opp_highest(engine):
    e = engine
    c = e.new_card("Hate", 2, 1)
    c.definition = get("Hate", 2)
    mine = e.new_card("Psychic", 5, 1)
    mine.face_up = True
    theirs = e.new_card("Speed", 3, 2)
    theirs.face_up = True
    e.players[1]["stacks"][1].append(mine)
    e.players[2]["stacks"][1].append(theirs)

    c.definition["play"](e, c)  # 각자 유일한 최고값이라 프롬프트 없이 자동 결정
    assert mine in e.players[1]["discard"]
    assert theirs in e.players[2]["discard"]


def test_hate_2_self_delete_stops_second_clause(engine):
    e = engine
    c = e.new_card("Hate", 2, 1)  # 값 2
    c.face_up = True
    c.definition = get("Hate", 2)
    e.players[1]["stacks"][1].append(c)  # 유일한 카드라 c 자신이 최고값
    theirs = e.new_card("Speed", 3, 2)
    theirs.face_up = True
    e.players[2]["stacks"][1].append(theirs)

    c.definition["play"](e, c)
    assert c in e.players[1]["discard"]
    assert theirs in e.players[2]["stacks"][1]  # 두 번째 절 발동 안 함


def test_hate_3_reacts_only_to_own_delete():
    from src.game.card import Card
    c_def = get("Hate", 3)
    fn = c_def["reactiveTop"]["afterDelete"]
    dummy = Card(uid=1, proto="Hate", value=3, owner=1, definition=c_def)

    class FakeGame:
        def __init__(self):
            self.drew = None

        def draw(self, pi, n):
            self.drew = (pi, n)

    fake = FakeGame()
    fn(fake, dummy, 2, None, None)
    assert fake.drew is None
    fn(fake, dummy, 1, None, None)
    assert fake.drew == (1, 1)


def test_hate_4_on_covered_deletes_lowest_covered(engine):
    e = engine
    c = e.new_card("Hate", 4, 1)
    c.face_up = True
    lowest = e.new_card("Psychic", 0, 1)
    lowest.face_up = True
    e.players[1]["stacks"][1].extend([lowest, c])
    c.definition = get("Hate", 4)

    covering = e.new_card("Speed", 0, 1)
    e.place_on_stack(covering, 1, 1, True)
    assert lowest in e.players[1]["discard"]


def test_hate_5_shares_discard_one():
    assert get("Hate", 5) is get("Water", 5)
