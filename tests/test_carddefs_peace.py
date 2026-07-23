from src.game.carddefs import get
from tests.conftest import make_ai, neutral_card


def test_peace_1_both_discard_hands_and_react(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Peace", 1, 1)
    c.definition = get("Peace", 1)
    reacted = []
    watcher = neutral_card(e, "Water", 0, 1)
    watcher.face_up = True
    watcher.definition = {"reactive": {"afterDiscard": lambda g, cc, actor, ctx, s: reacted.append(actor)}}
    e.players[1]["stacks"][2].append(watcher)

    c.definition["play"](e, c)
    assert e.players[1]["hand"] == []
    assert e.players[2]["hand"] == []
    assert set(reacted) == {1, 2}

    assert c.definition["can"]["finish"](e, c) is True
    hand_before = len(e.players[1]["hand"])
    c.definition["finish"](e, c)
    assert len(e.players[1]["hand"]) == hand_before + 1


def test_peace_2_draws_and_plays_facedown_only(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Peace", 2, 1)
    c.definition = get("Peace", 2)
    playable = e.players[1]["hand"][0]

    make_ai(e, 1, [playable.uid, 1])  # 카드 선택 -> 라인1 (강제 뒷면이라 위/아래 선택 없음)
    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    assert len(e.players[1]["hand"]) == hand_before  # +1 뽑고 -1 내서 상쇄
    assert playable in e.players[1]["stacks"][1]
    assert playable.face_up is False


def test_peace_3_optional_discard_then_flip_above_hand_size(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Peace", 3, 1)
    c.definition = get("Peace", 3)
    e.players[1]["hand"] = e.players[1]["hand"][:2]  # 손 2장
    # eff_val은 뒷면 카드를 항상 기본값(2)로 취급하므로, 실제 값(5)이 비교에
    # 쓰이려면 앞면이어야 함.
    target = neutral_card(e, "Water", 5, 2)  # 값5 > 손2
    target.face_up = True
    e.players[2]["stacks"][1].append(target)

    make_ai(e, 1, [[], target.uid])  # 버리기 0장 -> 뒤집기 대상 선택
    c.definition["play"](e, c)
    assert target.face_up is False  # 앞면이었다가 뒤집혀 뒷면이 됨


def test_peace_4_reactive_only_on_own_turn_discard():
    from src.game.card import Card
    c_def = get("Peace", 4)
    fn = c_def["reactive"]["afterDiscard"]
    dummy = Card(uid=1, proto="Peace", value=4, owner=1, definition=c_def)

    class FakeGame:
        def __init__(self, turn):
            self.turn = turn
            self.drew = None

        def draw(self, pi, n):
            self.drew = (pi, n)

    fake = FakeGame(turn=1)
    fn(fake, dummy, 1, None, None)  # 자기 턴에 자기가 버림 -> 조건(turn != owner) 불충족
    assert fake.drew is None

    fake2 = FakeGame(turn=2)
    fn(fake2, dummy, 1, None, None)  # 상대 턴에 자신이 버림 -> 발동
    assert fake2.drew == (1, 1)

    fake3 = FakeGame(turn=2)
    fn(fake3, dummy, 2, None, None)  # 상대가 버림 -> actor != owner라 발동 안 함
    assert fake3.drew is None


def test_peace_5_shares_discard_one():
    assert get("Peace", 5) is get("Water", 5)


def test_peace_6_flips_self_if_hand_bigger_than_one(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Peace", 6, 1)
    c.face_up = True
    c.definition = get("Peace", 6)
    c.definition["play"](e, c)
    assert c.face_up is False


def test_peace_6_stays_if_hand_at_most_one(engine):
    e = engine
    c = neutral_card(e, "Peace", 6, 1)
    c.face_up = True
    c.definition = get("Peace", 6)
    e.players[1]["hand"] = []
    c.definition["play"](e, c)
    assert c.face_up is True
