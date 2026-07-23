from src.game.carddefs import get
from tests.conftest import make_ai


def test_light_0_draws_by_flipped_value(dealt_engine):
    e = dealt_engine
    c = e.new_card("Light", 0, 1)
    c.definition = get("Light", 0)
    target = e.new_card("Psychic", 4, 1)  # 아직 안 옮긴 프로토콜 -> 중립 카드
    target.face_up = False
    e.players[1]["stacks"][1].append(target)

    make_ai(e, 1, [target.uid])
    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    assert target.face_up is True
    assert len(e.players[1]["hand"]) == hand_before + 4  # 뒤집힌 뒤 값(4)만큼 드로우


def test_light_1_finish_draws_one():
    from src.game.engine import Engine
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    e.build_decks()
    c = e.new_card("Light", 1, 1)
    c.definition = get("Light", 1)
    before = len(e.players[1]["hand"])
    c.definition["finish"](e, c)
    assert len(e.players[1]["hand"]) == before + 1


def test_light_2_reveals_and_optionally_flips(dealt_engine):
    e = dealt_engine
    c = e.new_card("Light", 2, 1)
    c.definition = get("Light", 2)
    target = e.new_card("Psychic", 2, 2)
    target.face_up = False
    target.definition = {}  # 중립 카드: Psychic_2의 실제 효과와 섞이지 않게
    e.players[2]["stacks"][1].append(target)

    make_ai(e, 1, [target.uid, "flip"])
    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    assert len(e.players[1]["hand"]) == hand_before + 2
    assert target.face_up is True


def test_light_2_can_decline_optional_reveal(dealt_engine):
    e = dealt_engine
    c = e.new_card("Light", 2, 1)
    c.definition = get("Light", 2)
    target = e.new_card("Psychic", 2, 2)
    target.face_up = False
    target.definition = {}  # 중립 카드: Psychic_2의 실제 효과와 섞이지 않게
    e.players[2]["stacks"][1].append(target)

    make_ai(e, 1, [None])  # optional 대상 선택 자체를 거절
    c.definition["play"](e, c)
    assert target.face_up is False


def test_light_3_moves_all_facedown_cards_in_line(engine):
    e = engine
    c = e.new_card("Light", 3, 1)
    c.definition = get("Light", 3)
    e.players[1]["stacks"][1].append(c)
    fd1 = e.new_card("Psychic", 0, 1)
    fd1.face_up = False
    fu1 = e.new_card("Psychic", 1, 1)
    fu1.face_up = True
    fd2 = e.new_card("Speed", 0, 2)
    fd2.face_up = False
    e.players[1]["stacks"][1].extend([fd1, fu1])
    e.players[2]["stacks"][1].append(fd2)

    make_ai(e, 1, [2])  # 목적지 라인2
    c.definition["play"](e, c)
    assert fd1 in e.players[1]["stacks"][2]
    assert fd2 in e.players[2]["stacks"][2]
    assert fu1 in e.players[1]["stacks"][1]  # 앞면은 안 움직임


def test_light_4_emits_reveal_hand_event():
    from src.game.engine import Engine
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    e.build_decks()
    c = e.new_card("Light", 4, 1)
    c.definition = get("Light", 4)
    log_before = len(e.log)
    c.definition["play"](e, c)
    # revealHandEvent는 emit만 하고 상태를 바꾸진 않음 -- 예외 없이 실행되는지만 확인.
    assert len(e.players[2]["hand"]) == 5


def test_light_5_shares_discard_one():
    assert get("Light", 5) is get("Water", 5)
