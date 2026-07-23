from src.game.engine import Engine
from src.game.carddefs import get
from tests.conftest import make_ai


def _engine(rng=None):
    return Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"],
                  rng=rng)


def test_love_1_can_predicate_and_play_and_finish():
    e = _engine()
    e.build_decks()
    c = e.new_card("Love", 1, 1)
    c.face_up = True
    c.definition = get("Love", 1)
    e.players[1]["stacks"][1].append(c)

    # can.finish: 손이 비면 False
    e.players[1]["hand"] = []
    assert c.definition["can"]["finish"](e, c) is False
    e.players[1]["hand"] = [e.new_card("Water", 0, 1)]
    assert c.definition["can"]["finish"](e, c) is True

    # play: 상대(2) 덱 top을 owner(1)의 손으로
    opp_deck_before = len(e.players[2]["deck"])
    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    assert len(e.players[2]["deck"]) == opp_deck_before - 1
    assert len(e.players[1]["hand"]) == hand_before + 1

    # finish: yesno에 True, giveCard의 chooseCard에 손 카드 하나 선택
    give_target = e.players[1]["hand"][0]
    make_ai(e, 1, [True, give_target.uid])
    opp_hand_before = len(e.players[2]["hand"])
    my_hand_before = len(e.players[1]["hand"])
    c.definition["finish"](e, c)
    assert give_target in e.players[2]["hand"]
    assert give_target.owner == 2
    assert len(e.players[1]["hand"]) == my_hand_before - 1 + 2  # 1장 주고 2장 뽑음
    assert len(e.players[2]["hand"]) == opp_hand_before + 1


def test_love_1_finish_declines():
    e = _engine()
    e.build_decks()
    c = e.new_card("Love", 1, 1)
    c.definition = get("Love", 1)
    make_ai(e, 1, [False])  # yesno: 거절
    hand_before = len(e.players[1]["hand"])
    c.definition["finish"](e, c)
    assert len(e.players[1]["hand"]) == hand_before  # 아무 일도 안 일어남


def test_love_2_opp_draws_and_owner_refreshes():
    e = _engine()
    e.build_decks()
    c = e.new_card("Love", 2, 1)
    c.definition = get("Love", 2)
    e.players[1]["hand"] = e.players[1]["hand"][:2]  # 손을 줄여서 refresh가 실제로 뽑게
    opp_hand_before = len(e.players[2]["hand"])
    my_hand_before = len(e.players[1]["hand"])

    c.definition["play"](e, c)
    assert len(e.players[2]["hand"]) == opp_hand_before + 1
    assert len(e.players[1]["hand"]) == 5  # HAND_SIZE까지 리프레시
    assert len(e.players[1]["hand"]) > my_hand_before


def test_love_3_takes_random_then_gives_back():
    e = _engine(rng=lambda n: 1)  # takeRandom이 항상 상대 손의 첫 카드를 가져오게
    e.build_decks()
    c = e.new_card("Love", 3, 1)
    c.definition = get("Love", 3)
    taken_card = e.players[2]["hand"][0]

    give_back_uid = None

    class _AI:
        def decide(self, g, req):
            nonlocal give_back_uid
            # giveCard의 chooseCard: 지금 손에 있는 아무 카드나 하나 선택
            give_back_uid = req["candidates"][0]
            return give_back_uid
        def planRearrange(self, g, pi, compiling_line):
            return None

    e.players[1]["isAI"] = True
    e.ai_modules[1] = _AI()

    opp_hand_before = len(e.players[2]["hand"])
    my_hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)

    assert taken_card in e.players[1]["hand"]
    assert taken_card.owner == 1
    assert len(e.players[2]["hand"]) == opp_hand_before  # 하나 뺏기고 하나 받음 (상쇄)
    assert len(e.players[1]["hand"]) == my_hand_before  # 하나 받고 하나 줌 (상쇄)


def test_love_4_reveals_and_flips():
    e = _engine()
    e.build_decks()
    c = e.new_card("Love", 4, 1)
    c.face_up = True
    c.definition = get("Love", 4)
    e.players[1]["stacks"][1].append(c)

    flip_target = e.new_card("Fire", 0, 2)
    flip_target.face_up = True
    e.players[2]["stacks"][2].append(flip_target)

    reveal_uid = e.players[1]["hand"][0].uid
    make_ai(e, 1, [reveal_uid, flip_target.uid])
    c.definition["play"](e, c)

    assert flip_target.face_up is False


def test_love_5_and_6_share_and_use_discard_draw():
    assert get("Love", 5) is get("Water", 5)  # 같은 공유 정의 재사용

    e = _engine()
    e.build_decks()
    c = e.new_card("Love", 6, 1)
    c.definition = get("Love", 6)
    opp_hand_before = len(e.players[2]["hand"])
    c.definition["play"](e, c)
    assert len(e.players[2]["hand"]) == opp_hand_before + 2
