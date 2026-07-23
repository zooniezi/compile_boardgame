from src.game import rules as Rules
from tests.conftest import make_ai


def test_build_decks_gives_correct_counts(dealt_engine):
    e = dealt_engine
    for pi in (1, 2):
        p = e.players[pi]
        assert len(p["deck"]) == 18 - Rules.HAND_SIZE
        assert len(p["hand"]) == Rules.HAND_SIZE
        assert len(p["discard"]) == 0


def test_all_36_cards_are_distinct_uids(dealt_engine):
    e = dealt_engine
    uids = set()
    for pi in (1, 2):
        p = e.players[pi]
        for c in p["deck"] + p["hand"] + p["discard"]:
            assert c.uid not in uids
            uids.add(c.uid)
    assert len(uids) == 36


def test_draw_one_moves_card_from_deck_to_hand(dealt_engine):
    e = dealt_engine
    before_deck = len(e.players[1]["deck"])
    before_hand = len(e.players[1]["hand"])
    c = e.draw_one(1)
    assert c is not None
    assert len(e.players[1]["deck"]) == before_deck - 1
    assert len(e.players[1]["hand"]) == before_hand + 1
    assert c in e.players[1]["hand"]


def test_reshuffle_discard_into_deck(engine):
    e = engine
    p = e.players[1]
    c1 = e.new_card("Water", 0, 1)
    c2 = e.new_card("Water", 1, 1)
    p["discard"] = [c1, c2]
    p["deck"] = []
    ok = e.reshuffle_discard_into_deck(1)
    assert ok is True
    assert len(p["deck"]) == 2
    assert len(p["discard"]) == 0


def test_pop_deck_may_reshuffle(engine):
    e = engine
    p = e.players[1]
    c1 = e.new_card("Water", 0, 1)
    p["deck"] = []
    p["discard"] = [c1]
    c = e.pop_deck(1, may_reshuffle=True)
    assert c is c1
    assert len(p["discard"]) == 0


def test_pop_deck_without_reshuffle_flag_stays_empty(engine):
    e = engine
    p = e.players[1]
    c1 = e.new_card("Water", 0, 1)
    p["deck"] = []
    p["discard"] = [c1]
    c = e.pop_deck(1, may_reshuffle=False)
    assert c is None
    assert len(p["discard"]) == 1  # 리셔플 안 됨


def test_draw_blocked_by_no_draw_if_hand_passive(engine):
    e = engine
    p1 = e.players[1]
    p1["hand"] = [e.new_card("Water", 0, 1)]
    blocker = e.new_card("Ice", 6, 1)
    blocker.face_up = True
    blocker.definition = {"passive": {"noDrawIfHand": True}}
    p1["stacks"][1].append(blocker)
    assert e.draw_blocked(1) is True

    p1["hand"] = []  # 손이 비면 다시 드로우 가능
    assert e.draw_blocked(1) is False


def test_discard_truncates_answer_that_exceeds_count(engine):
    """안전장치: chooseHandCards 응답이 count보다 많은 uid를 담고 있어도
    서버에서 count만큼만 잘라 버린다 (클라이언트 버그로부터 방어)."""
    e = engine
    p = e.players[1]
    cards = [e.new_card("Water", v, 1) for v in range(4)]
    p["hand"] = cards
    make_ai(e, 1, [[c.uid for c in cards]])  # count=1인데 4장을 전부 응답
    n = e.discard(1, 1)
    assert n == 1
    assert len(p["discard"]) == 1
    assert len(p["hand"]) == 3
