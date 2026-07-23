from tests.conftest import make_ai


def test_water_0_flips_chosen_card_and_self(engine):
    e = engine
    from src.game.carddefs import get
    c = e.new_card("Water", 0, 1)
    c.face_up = True
    c.definition = get("Water", 0)
    other = e.new_card("Water", 3, 1)
    other.face_up = True
    e.players[1]["stacks"][1].append(c)
    e.players[1]["stacks"][2].append(other)
    make_ai(e, 1, [other.uid])  # flipOne의 chooseCard 프롬프트에 other를 선택

    c.definition["play"](e, c)

    assert other.face_up is False  # 골라서 뒤집힘
    assert c.face_up is False      # 자기 자신도 무조건 뒤집힘


def test_water_1_plays_facedown_into_every_other_line(dealt_engine):
    e = dealt_engine
    from src.game.carddefs import get
    c = e.new_card("Water", 1, 1)
    c.face_up = True
    c.definition = get("Water", 1)
    e.players[1]["stacks"][2].append(c)  # 자기 자신은 라인2

    before_deck = len(e.players[1]["deck"])
    c.definition["play"](e, c)

    assert len(e.players[1]["stacks"][1]) == 1  # 라인1에 뒷면 카드 하나
    assert len(e.players[1]["stacks"][3]) == 1  # 라인3에도
    assert len(e.players[1]["stacks"][2]) == 1  # 자기 라인(2)엔 안 놓임 (자기 자신 뿐)
    assert e.players[1]["stacks"][1][0].face_up is False
    assert len(e.players[1]["deck"]) == before_deck - 2


def test_water_2_draws_two_and_rearranges(dealt_engine):
    e = dealt_engine
    from src.game.carddefs import get
    c = e.new_card("Water", 2, 1)
    c.face_up = True
    c.definition = get("Water", 2)
    e.players[1]["protocols"] = {1: "Water", 2: "Fire", 3: "Life"}
    e.players[1]["compiled"] = {1: False, 2: True, 3: False}
    before_hand = len(e.players[1]["hand"])

    # chooseRearrange의 prompt("rearrange")에 순서를 응답: 슬롯1<-원래3, 슬롯2<-원래1, 슬롯3<-원래2
    make_ai(e, 1, [{1: 3, 2: 1, 3: 2}])
    c.definition["play"](e, c)

    assert len(e.players[1]["hand"]) == before_hand + 2
    assert e.players[1]["protocols"] == {1: "Life", 2: "Water", 3: "Fire"}
    assert e.players[1]["compiled"] == {1: False, 2: False, 3: True}


def test_water_3_returns_all_value_2_cards_in_chosen_line(engine):
    e = engine
    from src.game.carddefs import get
    c = e.new_card("Water", 3, 1)
    c.face_up = True
    c.definition = get("Water", 3)
    e.players[1]["stacks"][1].append(c)

    target1 = e.new_card("Fire", 2, 1)
    target1.face_up = True
    target2 = e.new_card("Ice", 2, 2)
    target2.face_up = True
    not_target = e.new_card("Metal", 4, 2)
    not_target.face_up = True
    e.players[1]["stacks"][2].extend([target1])
    e.players[2]["stacks"][2].extend([not_target, target2])

    make_ai(e, 1, [2])  # chooseLine 프롬프트에 라인2 선택
    c.definition["play"](e, c)

    assert target1 in e.players[1]["hand"]
    assert target2 in e.players[2]["hand"]
    assert not_target in e.players[2]["stacks"][2]  # 값 4는 대상이 아님


def test_water_4_returns_one_own_card(engine):
    e = engine
    from src.game.carddefs import get
    c = e.new_card("Water", 4, 1)
    c.face_up = True
    c.definition = get("Water", 4)
    e.players[1]["stacks"][1].append(c)

    mine = e.new_card("Fire", 1, 1)
    mine.face_up = True
    theirs = e.new_card("Ice", 1, 2)
    theirs.face_up = True
    e.players[1]["stacks"][2].append(mine)
    e.players[2]["stacks"][2].append(theirs)

    make_ai(e, 1, [mine.uid])  # chooseCard: 후보에 theirs는 없어야 함 (필터: owner==c.owner)
    c.definition["play"](e, c)

    assert mine in e.players[1]["hand"]
    assert theirs in e.players[2]["stacks"][2]  # 안 건드려짐


def test_water_5_discards_one_card(dealt_engine):
    e = dealt_engine
    from src.game.carddefs import get
    c = e.players[1]["hand"][0]
    c.definition = get("Water", 5)
    c.face_up = True
    target = e.players[1]["hand"][1]
    before = len(e.players[1]["hand"])

    make_ai(e, 1, [[target.uid]])  # discard()의 chooseHandCards 프롬프트
    c.definition["play"](e, c)

    assert target in e.players[1]["discard"]
    assert len(e.players[1]["hand"]) == before - 1
