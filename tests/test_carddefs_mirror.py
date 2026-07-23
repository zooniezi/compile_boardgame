from src.game.carddefs import get
from tests.conftest import make_ai, neutral_card


def test_mirror_0_passive_counts_opponent_stack(engine):
    e = engine
    c = neutral_card(e, "Mirror", 0, 1)
    c.face_up = True
    c.definition = get("Mirror", 0)
    e.players[1]["stacks"][1].append(c)
    e.players[2]["stacks"][1].extend([
        neutral_card(e, "Water", 0, 2), neutral_card(e, "Water", 0, 2)])
    assert e.line_value(1, 1) == 0 + 2  # c 값(0) + 상대 스택 카드 수(2)


def test_mirror_1_can_predicate_and_finish_mimics_opponent_middle(engine):
    e = engine
    c = neutral_card(e, "Mirror", 1, 1)
    c.definition = get("Mirror", 1)
    assert c.definition["can"]["finish"](e, c) is False

    trace = []
    opp_card = neutral_card(e, "Water", 0, 2)
    opp_card.face_up = True
    opp_card.definition = {"play": lambda g, cc: trace.append(cc.uid)}
    e.players[2]["stacks"][1].append(opp_card)
    assert c.definition["can"]["finish"](e, c) is True

    make_ai(e, 1, [opp_card.uid])
    c.definition["finish"](e, c)
    assert trace == [c.uid]  # Mirror_1을 행동 주체로 실행됨


def test_mirror_2_swaps_two_stacks(engine):
    e = engine
    c = neutral_card(e, "Mirror", 2, 1)
    c.definition = get("Mirror", 2)
    a_card = neutral_card(e, "Water", 0, 1)
    e.players[1]["stacks"][1].append(a_card)
    b_card = neutral_card(e, "Fire", 0, 1)
    e.players[1]["stacks"][2].append(b_card)

    make_ai(e, 1, [1, 2])
    c.definition["play"](e, c)
    assert e.players[1]["stacks"][1] == [b_card]
    assert e.players[1]["stacks"][2] == [a_card]


def test_mirror_3_flips_own_then_opponent_same_line(engine):
    e = engine
    c = neutral_card(e, "Mirror", 3, 1)
    c.definition = get("Mirror", 3)
    mine = neutral_card(e, "Water", 0, 1)
    mine.face_up = False
    e.players[1]["stacks"][1].append(mine)
    opp_card = neutral_card(e, "Ice", 0, 2)
    opp_card.face_up = False
    e.players[2]["stacks"][1].append(opp_card)

    make_ai(e, 1, [mine.uid, opp_card.uid])
    c.definition["play"](e, c)
    assert mine.face_up is True
    assert opp_card.face_up is True


def test_mirror_3_stops_if_self_flipped(engine):
    e = engine
    c = neutral_card(e, "Mirror", 3, 1)
    c.face_up = True
    c.definition = get("Mirror", 3)
    e.players[1]["stacks"][1].append(c)

    make_ai(e, 1, [c.uid])
    c.definition["play"](e, c)  # 자기 자신을 뒤집으면 두 번째 절 발동 안 함
    assert c.face_up is False


def test_mirror_4_reactive_draws_on_opponent_draw():
    from src.game.card import Card
    c_def = get("Mirror", 4)
    fn = c_def["reactive"]["afterDraw"]
    dummy = Card(uid=1, proto="Mirror", value=4, owner=1, definition=c_def)

    class FakeGame:
        def __init__(self):
            self.drew = None

        def draw(self, pi, n):
            self.drew = (pi, n)

    fake = FakeGame()
    fn(fake, dummy, 1, None, None)
    assert fake.drew is None
    fn(fake, dummy, 2, None, None)
    assert fake.drew == (1, 1)


def test_mirror_5_shares_discard_one():
    assert get("Mirror", 5) is get("Water", 5)
