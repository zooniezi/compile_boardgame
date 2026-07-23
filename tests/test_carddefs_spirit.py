from src.game.carddefs import get
from tests.conftest import make_ai


def test_spirit_0_passive_and_play(dealt_engine):
    e = dealt_engine
    c = e.new_card("Spirit", 0, 1)
    c.definition = get("Spirit", 0)
    assert c.definition["passive"]["skipCache"] is True

    e.players[1]["hand"] = e.players[1]["hand"][:2]
    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    assert len(e.players[1]["hand"]) == 5 + 1  # refresh(5까지) 후 추가로 1장 더


def test_spirit_1_passive_and_play(dealt_engine):
    e = dealt_engine
    c = e.new_card("Spirit", 1, 1)
    c.definition = get("Spirit", 1)
    assert c.definition["passive"]["playAnywhere"] is True
    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    assert len(e.players[1]["hand"]) == hand_before + 2


def test_spirit_1_start_forces_flip_when_hand_empty(engine):
    e = engine
    c = e.new_card("Spirit", 1, 1)
    c.face_up = False
    c.definition = get("Spirit", 1)
    e.players[1]["hand"] = []
    e.players[1]["stacks"][1].append(c)

    c.definition["start"](e, c)
    assert c.face_up is True  # 선택지 없이 강제로 뒤집힘


def test_spirit_1_start_offers_choice_when_hand_has_cards(dealt_engine):
    e = dealt_engine
    c = e.new_card("Spirit", 1, 1)
    c.face_up = False
    c.definition = get("Spirit", 1)
    e.players[1]["stacks"][1].append(c)

    make_ai(e, 1, ["discard", [e.players[1]["hand"][0].uid]])
    hand_before = len(e.players[1]["hand"])
    c.definition["start"](e, c)
    assert c.face_up is False  # discard를 골랐으니 안 뒤집힘
    assert len(e.players[1]["hand"]) == hand_before - 1


def test_spirit_2_optional_flip_can_decline(engine):
    e = engine
    c = e.new_card("Spirit", 2, 1)
    c.definition = get("Spirit", 2)
    target = e.new_card("Water", 0, 2)
    target.face_up = True
    e.players[2]["stacks"][1].append(target)

    make_ai(e, 1, [None])  # optional: 선택 안 함
    c.definition["play"](e, c)
    assert target.face_up is True  # 안 건드려짐


def test_spirit_3_reacts_only_to_own_draw_and_moves(engine):
    e = engine
    c = e.new_card("Spirit", 3, 1)
    c.face_up = True
    c.definition = get("Spirit", 3)
    e.players[1]["stacks"][1].append(c)

    # 상대(2)가 드로우했을 때는 반응하면 안 됨
    fn = c.definition["reactiveTop"]["afterDraw"]
    fn(e, c, 2, None, None)
    assert e.players[1]["stacks"][1] == [c]  # 안 움직임

    # 자신(1)이 드로우했을 때: yes 응답 + 라인3 선택
    make_ai(e, 1, [True, 3])
    fn(e, c, 1, None, None)
    assert e.players[1]["stacks"][1] == []
    assert e.players[1]["stacks"][3] == [c]


def test_spirit_4_swaps_two_protocols(engine):
    e = engine
    c = e.new_card("Spirit", 4, 1)
    c.definition = get("Spirit", 4)
    e.players[1]["protocols"] = {1: "Water", 2: "Fire", 3: "Spirit"}

    make_ai(e, 1, [1, 3])  # 라인1과 라인3 교환
    c.definition["play"](e, c)
    assert e.players[1]["protocols"] == {1: "Spirit", 2: "Fire", 3: "Water"}


def test_spirit_5_shares_discard_one():
    assert get("Spirit", 5) is get("Water", 5)
