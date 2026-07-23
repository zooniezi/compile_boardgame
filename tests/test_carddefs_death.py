from src.game.carddefs import get
from tests.conftest import make_ai


def test_death_0_deletes_one_from_each_other_line(engine):
    e = engine
    c = e.new_card("Death", 0, 1)
    c.definition = get("Death", 0)
    e.players[1]["stacks"][1].append(c)  # 자기 자신 라인은 1

    l2 = e.new_card("Psychic", 0, 1)
    l2.face_up = True
    e.players[1]["stacks"][2].append(l2)
    l3 = e.new_card("Speed", 0, 2)
    l3.face_up = True
    e.players[2]["stacks"][3].append(l3)

    make_ai(e, 1, [l2.uid, l3.uid])
    c.definition["play"](e, c)
    assert l2 in e.players[1]["discard"]
    assert l3 in e.players[2]["discard"]


def test_death_0_line_with_no_target_contributes_nothing(engine):
    e = engine
    c = e.new_card("Death", 0, 1)
    c.definition = get("Death", 0)
    e.players[1]["stacks"][1].append(c)
    # 라인2, 라인3 둘 다 비어있음 -> 아무것도 삭제 안 됨, 에러도 없어야 함
    c.definition["play"](e, c)
    assert e.players[1]["discard"] == []


def test_death_1_start_top_draw_then_delete_self_and_other():
    from src.game.engine import Engine
    e = Engine(protocols1=["Water", "Fire", "Death"], protocols2=["Ice", "Metal", "Life"])
    e.build_decks()
    c = e.new_card("Death", 1, 1)
    c.face_up = True
    c.definition = get("Death", 1)
    e.players[1]["stacks"][1].append(c)
    other = e.new_card("Psychic", 0, 1)
    other.face_up = True
    e.players[1]["stacks"][2].append(other)

    make_ai(e, 1, [True, other.uid])
    hand_before = len(e.players[1]["hand"])
    c.definition["startTop"](e, c)
    assert len(e.players[1]["hand"]) == hand_before + 1
    assert other in e.players[1]["discard"]
    assert c in e.players[1]["discard"]  # 자기 자신도 삭제


def test_death_1_start_top_declines(engine):
    e = engine
    c = e.new_card("Death", 1, 1)
    c.face_up = True
    c.definition = get("Death", 1)
    e.players[1]["stacks"][1].append(c)
    make_ai(e, 1, [False])
    c.definition["startTop"](e, c)
    assert c in e.players[1]["stacks"][1]  # 거절하면 아무 일도 안 일어남


def test_death_2_deletes_all_value_1_or_2_in_chosen_line(engine):
    e = engine
    c = e.new_card("Death", 2, 1)
    c.definition = get("Death", 2)
    e.players[1]["stacks"][1].append(c)

    keep = e.new_card("Psychic", 5, 1)
    keep.face_up = True
    del1 = e.new_card("Psychic", 1, 1)
    del1.face_up = True
    del2 = e.new_card("Speed", 2, 2)
    del2.face_up = True
    e.players[1]["stacks"][2].extend([keep, del1])
    e.players[2]["stacks"][2].append(del2)

    make_ai(e, 1, [2])
    c.definition["play"](e, c)
    assert del1 in e.players[1]["discard"]
    assert del2 in e.players[2]["discard"]
    assert keep in e.players[1]["stacks"][2]


def test_death_2_fizzles_with_no_valid_line(engine):
    e = engine
    c = e.new_card("Death", 2, 1)
    c.definition = get("Death", 2)
    only = e.new_card("Psychic", 5, 1)
    only.face_up = True
    e.players[1]["stacks"][1].append(only)
    c.definition["play"](e, c)  # 값1/2 대상이 아무데도 없음 -> 프롬프트 없이 무산
    assert only in e.players[1]["stacks"][1]


def test_death_3_deletes_a_facedown_card(engine):
    e = engine
    c = e.new_card("Death", 3, 1)
    c.definition = get("Death", 3)
    fd = e.new_card("Psychic", 0, 2)
    fd.face_up = False
    fu = e.new_card("Speed", 0, 2)
    fu.face_up = True
    e.players[2]["stacks"][1].append(fd)
    e.players[2]["stacks"][2].append(fu)

    make_ai(e, 1, [fd.uid])
    c.definition["play"](e, c)
    assert fd in e.players[2]["discard"]
    assert fu in e.players[2]["stacks"][2]


def test_death_4_deletes_value_0_or_1_face_up(engine):
    e = engine
    c = e.new_card("Death", 4, 1)
    c.definition = get("Death", 4)
    target = e.new_card("Psychic", 1, 2)
    target.face_up = True
    not_target = e.new_card("Speed", 3, 2)
    not_target.face_up = True
    e.players[2]["stacks"][1].append(target)
    e.players[2]["stacks"][2].append(not_target)

    make_ai(e, 1, [target.uid])
    c.definition["play"](e, c)
    assert target in e.players[2]["discard"]
    assert not_target in e.players[2]["stacks"][2]


def test_death_5_shares_discard_one():
    assert get("Death", 5) is get("Water", 5)
