from src.game.carddefs import get
from tests.conftest import make_ai, neutral_card


def test_smoke_0_plays_facedown_where_facedown_exists(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Smoke", 0, 1)
    c.face_up = True
    c.definition = get("Smoke", 0)
    fd_own_line = neutral_card(e, "Water", 0, 1)  # 자기 라인에도 뒷면 카드가 있어야 자격됨
    fd_own_line.face_up = False
    e.players[1]["stacks"][1].extend([fd_own_line, c])
    fd = neutral_card(e, "Water", 0, 1)
    fd.face_up = False
    e.players[1]["stacks"][2].append(fd)
    # 라인3에는 뒷면 카드 없음 -> 대상 아님

    make_ai(e, 1, [1])  # 라인1(자기 라인), 라인2 중 순서 선택
    before_deck = len(e.players[1]["deck"])
    c.definition["play"](e, c)
    assert len(e.players[1]["stacks"][1]) == 3
    assert len(e.players[1]["stacks"][2]) == 2
    assert e.players[1]["stacks"][3] == []
    assert len(e.players[1]["deck"]) == before_deck - 2


def test_smoke_1_flips_own_card_and_may_move(engine):
    e = engine
    c = neutral_card(e, "Smoke", 1, 1)
    c.definition = get("Smoke", 1)
    mine = neutral_card(e, "Water", 0, 1)
    mine.face_up = False
    e.players[1]["stacks"][1].append(mine)

    make_ai(e, 1, [mine.uid, True, 2])
    c.definition["play"](e, c)
    assert mine.face_up is True
    assert mine in e.players[1]["stacks"][2]


def test_smoke_2_passive_line_value_self(engine):
    e = engine
    c = neutral_card(e, "Smoke", 2, 1)
    c.face_up = True
    c.definition = get("Smoke", 2)
    e.players[1]["stacks"][1].append(c)
    fd = neutral_card(e, "Water", 0, 2)
    fd.face_up = False
    e.players[2]["stacks"][1].append(fd)
    assert e.line_value(1, 1) == 2 + 1  # c 자신의 값(2) + 라인의 뒷면 카드 수(1)


def test_smoke_3_plays_facedown_only_in_facedown_lines(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Smoke", 3, 1)
    c.definition = get("Smoke", 3)
    fd = neutral_card(e, "Water", 0, 1)
    fd.face_up = False
    e.players[1]["stacks"][1].append(fd)
    playable = e.players[1]["hand"][0]

    make_ai(e, 1, [playable.uid, 1])
    c.definition["play"](e, c)
    assert playable in e.players[1]["stacks"][1]
    assert playable.face_up is False


def test_smoke_4_moves_a_covered_facedown_card(engine):
    e = engine
    c = neutral_card(e, "Smoke", 4, 1)
    c.definition = get("Smoke", 4)
    covered = neutral_card(e, "Water", 0, 2)
    covered.face_up = False
    top = neutral_card(e, "Fire", 0, 2)
    top.face_up = True
    e.players[2]["stacks"][1].extend([covered, top])

    make_ai(e, 1, [covered.uid, 2])
    c.definition["play"](e, c)
    assert covered in e.players[2]["stacks"][2]


def test_smoke_5_shares_discard_one():
    assert get("Smoke", 5) is get("Water", 5)
