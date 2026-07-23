from src.game.carddefs import get
from tests.conftest import make_ai


def test_apathy_0_passive_line_value_self_counts_facedown(engine):
    e = engine
    c = e.new_card("Apathy", 0, 1)
    c.face_up = True
    c.definition = get("Apathy", 0)
    fd1 = e.new_card("Water", 5, 1)
    fd1.face_up = False
    fd2 = e.new_card("Water", 0, 2)
    fd2.face_up = False
    e.players[1]["stacks"][1].extend([c, fd1])
    e.players[2]["stacks"][1].append(fd2)

    # line_value(1,1) = c(뒷면취급아님,앞면값0) + fd1(뒷면기본값2) + lineValueSelf(뒷면장수=2)
    assert e.line_value(1, 1) == 0 + 2 + 2


def test_apathy_1_flips_all_other_face_up_cards_in_line(engine):
    e = engine
    c = e.new_card("Apathy", 1, 1)
    c.face_up = True
    c.definition = get("Apathy", 1)
    covered_target = e.new_card("Fire", 0, 1)  # covered인데도 대상 (all-in-line)
    covered_target.face_up = True
    facedown_untouched = e.new_card("Water", 0, 2)
    facedown_untouched.face_up = False
    opp_target = e.new_card("Ice", 1, 2)
    opp_target.face_up = True

    e.players[1]["stacks"][1].extend([covered_target, c])
    e.players[2]["stacks"][1].extend([facedown_untouched, opp_target])

    c.definition["play"](e, c)

    assert covered_target.face_up is False
    assert opp_target.face_up is False
    assert facedown_untouched.face_up is False  # 원래도 뒷면, 안 건드려짐(토글 안 됨)
    assert c.face_up is True  # 자기 자신은 대상에서 제외


def test_apathy_2_passive_and_on_covered():
    from src.game.engine import Engine
    e = Engine(protocols1=["Water", "Fire", "Apathy"], protocols2=["Ice", "Metal", "Death"])
    c = e.new_card("Apathy", 2, 1)
    c.face_up = True
    c.definition = get("Apathy", 2)
    assert c.definition["passive"]["ignoreMiddle"] is True
    e.players[1]["stacks"][1].append(c)

    covering = e.new_card("Water", 0, 1)
    e.place_on_stack(covering, 1, 1, True)
    assert c.face_up is False  # onCovered가 스스로를 뒤집음


def test_apathy_3_flips_a_face_up_opponent_card(engine):
    e = engine
    c = e.new_card("Apathy", 3, 1)
    c.definition = get("Apathy", 3)
    target = e.new_card("Ice", 2, 2)
    target.face_up = True
    facedown_opp = e.new_card("Metal", 3, 2)
    facedown_opp.face_up = False
    e.players[2]["stacks"][1].append(target)
    e.players[2]["stacks"][2].append(facedown_opp)

    make_ai(e, 1, [target.uid])
    c.definition["play"](e, c)
    assert target.face_up is False


def test_apathy_4_flips_own_covered_face_up_card(engine):
    e = engine
    c = e.new_card("Apathy", 4, 1)
    c.definition = get("Apathy", 4)
    covered = e.new_card("Water", 1, 1)
    covered.face_up = True
    top = e.new_card("Fire", 2, 1)
    top.face_up = True
    e.players[1]["stacks"][1].extend([covered, top])

    make_ai(e, 1, [covered.uid])
    c.definition["play"](e, c)
    assert covered.face_up is False
    assert top.face_up is True  # uncovered라 대상 아님


def test_apathy_5_shares_discard_one():
    assert get("Apathy", 5) is get("Water", 5)
