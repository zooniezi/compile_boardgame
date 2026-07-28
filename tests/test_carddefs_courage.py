from src.game.carddefs import get
from tests.conftest import make_ai, neutral_card


def test_courage_0_start_draws_only_on_empty_hand(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Courage", 0, 1)
    c.definition = get("Courage", 0)
    assert c.definition["can"]["startTop"](e, c) is False  # 손 있음
    hand_before = len(e.players[1]["hand"])
    c.definition["startTop"](e, c)
    assert len(e.players[1]["hand"]) == hand_before

    e.players[1]["hand"] = []
    assert c.definition["can"]["startTop"](e, c) is True
    c.definition["startTop"](e, c)
    assert len(e.players[1]["hand"]) == 1


def test_courage_0_finish_discard_chain(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Courage", 0, 1)
    c.definition = get("Courage", 0)
    assert c.definition["can"]["finish"](e, c) is True
    make_ai(e, 1, [True, [e.players[1]["hand"][0].uid]])
    make_ai(e, 2, [[e.players[2]["hand"][0].uid]])
    c.definition["finish"](e, c)
    assert len(e.players[1]["discard"]) == 1
    assert len(e.players[2]["discard"]) == 1


def test_courage_1_deletes_opp_card_where_losing(engine):
    e = engine
    c = neutral_card(e, "Courage", 1, 1)
    c.definition = get("Courage", 1)
    strong_opp = neutral_card(e, "Water", 5, 2)
    strong_opp.face_up = True
    weak_mine = neutral_card(e, "Water", 0, 1)
    weak_mine.face_up = True
    e.players[2]["stacks"][1].append(strong_opp)
    e.players[1]["stacks"][1].append(weak_mine)

    make_ai(e, 1, [strong_opp.uid])
    c.definition["play"](e, c)
    assert strong_opp in e.players[2]["discard"]


def test_courage_2_can_and_finish_draw_when_losing(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Courage", 2, 1)
    c.face_up = True
    c.definition = get("Courage", 2)
    e.players[1]["stacks"][1].append(c)
    strong_opp = neutral_card(e, "Water", 5, 2)
    strong_opp.face_up = True
    e.players[2]["stacks"][1].append(strong_opp)

    assert c.definition["can"]["finish"](e, c) is True
    hand_before = len(e.players[1]["hand"])
    c.definition["finish"](e, c)
    assert len(e.players[1]["hand"]) == hand_before + 1


def test_courage_3_moves_to_opponent_strongest_line(engine):
    e = engine
    c = neutral_card(e, "Courage", 3, 1)
    c.face_up = True
    c.definition = get("Courage", 3)
    e.players[1]["stacks"][1].append(c)
    strong = neutral_card(e, "Water", 6, 2)
    strong.face_up = True
    e.players[2]["stacks"][3].append(strong)

    assert c.definition["can"]["finish"](e, c) is True
    make_ai(e, 1, [True])
    c.definition["finish"](e, c)
    assert c in e.players[1]["stacks"][3]


def test_courage_3_offers_a_choice_when_multiple_lines_tie_for_highest(engine):
    """상대의 최고값 라인이 여러 개(동점)면, 조용히 아무 데나 고르지 말고
    플레이어가 직접 선택할 수 있어야 한다."""
    e = engine
    c = neutral_card(e, "Courage", 3, 1)
    c.face_up = True
    c.definition = get("Courage", 3)
    e.players[1]["stacks"][1].append(c)
    o2 = neutral_card(e, "Ice", 5, 2)
    o2.face_up = True
    e.players[2]["stacks"][2].append(o2)
    o3 = neutral_card(e, "Death", 5, 2)  # 라인2와 정확히 동점(값5)
    o3.face_up = True
    e.players[2]["stacks"][3].append(o3)

    captured = []

    class SpyAI:
        def decide(self, g, req):
            if req.get("type") == "chooseLine":
                captured.append(req["candidates"])
                return 3
            return True

    e.ai_modules[1] = SpyAI()
    e.players[1]["isAI"] = True
    c.definition["finish"](e, c)

    assert captured == [[2, 3]]  # 동점인 두 라인이 그대로 후보로 제시됨
    assert c in e.players[1]["stacks"][3]  # 선택한 라인3으로 실제 이동


def test_courage_3_excludes_own_current_line_from_tied_candidates(engine):
    """최고값 동점 라인 중 하나가 하필 카드 자신이 지금 있는 라인이면,
    그 라인은 후보에서 빠져야 한다(거기로 '이동'하는 건 의미가 없음).
    남는 후보가 하나뿐이면 선택 프롬프트 없이 바로 이동한다."""
    e = engine
    c = neutral_card(e, "Courage", 3, 1)
    c.face_up = True
    c.definition = get("Courage", 3)
    e.players[1]["stacks"][1].append(c)
    o1 = neutral_card(e, "Ice", 5, 2)  # c가 있는 라인1도 동점
    o1.face_up = True
    e.players[2]["stacks"][1].append(o1)
    o2 = neutral_card(e, "Metal", 5, 2)
    o2.face_up = True
    e.players[2]["stacks"][2].append(o2)

    captured = []

    class SpyAI:
        def decide(self, g, req):
            if req.get("type") == "chooseLine":
                captured.append(req["candidates"])
                return req["candidates"][0]
            return True

    e.ai_modules[1] = SpyAI()
    e.players[1]["isAI"] = True
    c.definition["finish"](e, c)

    assert captured == []  # 후보가 1개뿐이라 선택 프롬프트 자체가 안 뜸
    assert c in e.players[1]["stacks"][2]


def test_courage_5_shares_discard_one():
    assert get("Courage", 5) is get("Water", 5)


def test_courage_6_flips_self_when_losing(engine):
    e = engine
    c = neutral_card(e, "Courage", 6, 1)  # 자기 자신 값 6이 내 라인값에 포함됨
    c.face_up = True
    c.definition = get("Courage", 6)
    e.players[1]["stacks"][1].append(c)
    strong1 = neutral_card(e, "Water", 5, 2)
    strong1.face_up = True
    strong2 = neutral_card(e, "Water", 2, 2)
    strong2.face_up = True
    e.players[2]["stacks"][1].extend([strong1, strong2])  # 합계 7 > 6

    assert c.definition["can"]["finishTop"](e, c) is True
    c.definition["finishTop"](e, c)
    assert c.face_up is False
