from src.game.carddefs import get
from tests.conftest import make_ai


def test_gravity_0_counts_self_and_covers_itself_normally(dealt_engine):
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
    assert len(e.players[1]["deck"]) == before_deck - 1
    # 특별한 위치 지정 없이 그냥 라인에 평범하게 낸 것 -- 맨 위(uncovered)가
    # 새로 낸 뒷면 카드고, Gravity_0 자신은 그 밑에 덮인다.
    assert e.players[1]["stacks"][1][-1].face_up is False
    assert e.is_uncovered(c) is False


def test_gravity_0_multiple_facedowns_stack_normally_on_top_in_order(engine):
    """카드가 많이 쌓여있어 여러 장(2장 이상)이 나오는 경우, 특별한 위치
    지정 없이 그냥 순서대로 라인 맨 위에 쌓여야 한다 -- Gravity_0이 맨
    먼저 덮이고, 그 위로 뒷면 카드들이 낸 순서대로 쌓인다."""
    e = engine
    c = e.new_card("Gravity", 0, 1)
    c.face_up = True
    c.definition = get("Gravity", 0)
    for i in range(5):
        other = e.new_card("Water", i, 1)
        other.face_up = True
        e.players[1]["stacks"][1].append(other)
    e.players[1]["stacks"][1].append(c)  # 총 6장 -> floor(6/2) = 3장 추가
    for _ in range(4):
        e.players[1]["deck"].append(e.new_card("Fire", 3, 1))

    c.definition["play"](e, c)

    stack = e.players[1]["stacks"][1]
    idx_c = stack.index(c)
    # c 위로 3장이 낸 순서 그대로 쌓여있어야 함 (특별한 삽입 없이 그냥 append)
    assert len(stack) - 1 - idx_c == 3
    assert all(not card.face_up for card in stack[idx_c + 1:])
    assert e.is_uncovered(c) is False
    assert e.is_uncovered(stack[-1]) is True  # 맨 마지막에 낸 카드만 uncovered


def test_gravity_0_completes_all_repeats_even_after_covering_itself(engine):
    """Gravity_0은 "어느 라인에 낼지" 선택의 여지가 없는 고정 반복 카드다
    (Life_0/Smoke_0처럼 순서를 고르는 카드와 다름). 정식 play_card()
    경로로 실행했을 때, 첫 번째로 낸 카드가 자기 자신을 덮어도 나머지
    반복이 전부 끝까지 진행돼야 한다 -- command()로 안 감싸져 있으면
    "명령 사이에 덮임" 판정으로 첫 카드 이후 전부 중단되는 실제 버그가
    있었다 (직접 definition["play"]를 호출하면 _card_stack이 비어있어
    이 버그가 재현이 안 되므로, 반드시 play_card()로 검증해야 한다)."""
    e = engine
    e.players[1]["protocols"][1] = "Gravity"
    for i in range(4):
        o = e.new_card("Water", i, 1)
        o.face_up = True
        e.players[1]["stacks"][1].append(o)
    for i in range(3):
        opp = e.new_card("Ice", i, 2)
        opp.face_up = True
        e.players[2]["stacks"][1].append(opp)
    for _ in range(8):
        e.players[1]["deck"].append(e.new_card("Fire", 3, 1))

    g0 = e.new_card("Gravity", 0, 1)
    e.players[1]["hand"].append(g0)
    total_before = len(e.players[1]["stacks"][1]) + 1 + len(e.players[2]["stacks"][1])
    expected_repeats = total_before // 2
    assert expected_repeats >= 2  # 이 테스트가 실제로 여러 번 반복되는 상황인지 확인

    e.play_card(1, g0.uid, 1, True)

    stack = e.players[1]["stacks"][1]
    idx_c = stack.index(g0)
    assert len(stack) - 1 - idx_c == expected_repeats


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
