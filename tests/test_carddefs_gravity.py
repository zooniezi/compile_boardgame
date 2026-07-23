from src.game.carddefs import get
from tests.conftest import make_ai


def test_gravity_0_counts_self_and_slides_underneath(dealt_engine):
    e = dealt_engine
    c = e.new_card("Gravity", 0, 1)
    c.face_up = True
    c.definition = get("Gravity", 0)
    other1 = e.new_card("Water", 0, 1)
    other1.face_up = True
    other2 = e.new_card("Ice", 0, 2)
    other2.face_up = True
    e.players[1]["stacks"][1].extend([other1, c])  # c를 포함해 총 2장 -> floor(2/2)=1
    e.players[2]["stacks"][1].append(other2)  # 총 3장 (c 포함) -> floor(3/2)=1

    before_deck = len(e.players[1]["deck"])
    c.definition["play"](e, c)
    # count = other1+c(2) + other2(1) = 3 -> floor(3/2) = 1장 추가
    assert len(e.players[1]["stacks"][1]) == 3
    assert e.players[1]["deck"] == e.players[1]["deck"]  # 그냥 참조 확인
    assert len(e.players[1]["deck"]) == before_deck - 1
    # 새 카드가 c 바로 밑에 슬라이드
    idx_c = e.players[1]["stacks"][1].index(c)
    assert e.players[1]["stacks"][1][idx_c - 1].face_up is False


def test_gravity_0_fizzles_when_line_locked(engine):
    e = engine
    c = e.new_card("Gravity", 0, 1)
    c.face_up = True
    c.definition = get("Gravity", 0)
    e.players[1]["stacks"][1].append(c)

    locker = e.new_card("Metal", 2, 2)
    locker.face_up = True
    locker.definition = {"passive": {"oppNoFacedownHere": True}}
    e.players[2]["stacks"][1].append(locker)

    c.definition["play"](e, c)
    assert e.players[1]["stacks"][1] == [c]  # 아무 것도 추가 안 됨


def test_gravity_1_moves_card_out_of_own_line(engine):
    e = engine
    c = e.new_card("Gravity", 1, 1)
    c.definition = get("Gravity", 1)
    c.face_up = True
    e.players[1]["stacks"][1].append(c)
    mover = e.new_card("Water", 0, 1)
    mover.face_up = True
    e.players[1]["stacks"][1].append(mover)

    make_ai(e, 1, [mover.uid, 2])  # 카드 선택 -> mover, 목적지 라인2
    c.definition["play"](e, c)
    assert mover in e.players[1]["stacks"][2]


def test_gravity_2_flips_then_moves_into_own_line(engine):
    e = engine
    c = e.new_card("Gravity", 2, 1)
    c.definition = get("Gravity", 2)
    c.face_up = True
    e.players[1]["stacks"][2].append(c)
    target = e.new_card("Water", 0, 1)
    target.face_up = False
    target.definition = {}  # 중립 카드로: Water_0의 실제 "뒤집고 자기도 뒤집는" 효과와 섞이지 않게
    e.players[1]["stacks"][1].append(target)

    make_ai(e, 1, [target.uid])
    c.definition["play"](e, c)
    assert target.face_up is True
    assert target in e.players[1]["stacks"][2]


def test_gravity_4_moves_facedown_card_from_other_line(engine):
    e = engine
    c = e.new_card("Gravity", 4, 1)
    c.definition = get("Gravity", 4)
    c.face_up = True
    e.players[1]["stacks"][1].append(c)

    same_line_fd = e.new_card("Water", 0, 1)
    same_line_fd.face_up = False
    e.players[1]["stacks"][1].append(same_line_fd)

    other_line_fd = e.new_card("Ice", 0, 2)
    other_line_fd.face_up = False
    e.players[2]["stacks"][2].append(other_line_fd)

    make_ai(e, 1, [other_line_fd.uid])
    c.definition["play"](e, c)
    assert other_line_fd in e.players[2]["stacks"][1]
    assert same_line_fd in e.players[1]["stacks"][1]  # 안 움직임 (같은 라인은 대상 아님)


def test_gravity_5_shares_discard_one():
    assert get("Gravity", 5) is get("Water", 5)


def test_gravity_6_forces_opponent_facedown_play(dealt_engine):
    e = dealt_engine
    c = e.new_card("Gravity", 6, 1)
    c.definition = get("Gravity", 6)
    c.face_up = True
    e.players[1]["stacks"][2].append(c)

    before_deck = len(e.players[2]["deck"])
    c.definition["play"](e, c)
    assert len(e.players[2]["stacks"][2]) == 1
    assert e.players[2]["stacks"][2][0].face_up is False
    assert len(e.players[2]["deck"]) == before_deck - 1
