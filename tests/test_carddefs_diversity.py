from src.game.carddefs import get
from tests.conftest import make_ai, neutral_card


def test_diversity_0_compiles_when_six_distinct_protocols(engine):
    e = engine
    c = neutral_card(e, "Diversity", 0, 1)
    c.definition = get("Diversity", 0)
    e.players[1]["protocols"] = {1: "Water", 2: "Fire", 3: "Diversity"}
    protos = ["Water", "Fire", "Ice", "Metal", "Death", "Life"]
    for i, p in enumerate(protos):
        card = neutral_card(e, p, 0, 1)
        card.face_up = True
        e.players[1]["stacks"][(i % 3) + 1].append(card)

    c.definition["play"](e, c)
    assert e.players[1]["compiled"][3] is True


def test_diversity_0_can_predicate_needs_non_diversity_hand_card(engine):
    e = engine
    c = neutral_card(e, "Diversity", 0, 1)
    c.definition = get("Diversity", 0)
    e.players[1]["hand"] = [neutral_card(e, "Diversity", 1, 1)]
    assert c.definition["can"]["finish"](e, c) is False
    e.players[1]["hand"].append(neutral_card(e, "Water", 0, 1))
    assert c.definition["can"]["finish"](e, c) is True


def test_diversity_1_moves_and_draws_by_distinct_protos(dealt_engine):
    e = dealt_engine
    c = neutral_card(e, "Diversity", 1, 1)
    c.face_up = True
    c.definition = get("Diversity", 1)
    e.players[1]["stacks"][2].append(c)  # lineOf(c)가 라인2를 가리키게, c 자신도 자리 잡음
    mover = neutral_card(e, "Water", 0, 1)
    mover.face_up = True
    e.players[1]["stacks"][1].append(mover)
    other1 = neutral_card(e, "Fire", 0, 1)
    other1.face_up = True
    other2 = neutral_card(e, "Ice", 0, 2)
    other2.face_up = True
    e.players[1]["stacks"][2].append(other1)
    e.players[2]["stacks"][2].append(other2)

    make_ai(e, 1, [mover.uid, 2])  # mover를 골라 라인2로 이동
    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    assert mover in e.players[1]["stacks"][2]
    # 라인2 = Diversity(c) + Fire(other1) + Water(mover) + Ice(other2) = 4종
    assert len(e.players[1]["hand"]) == hand_before + 4


def test_diversity_3_passive_line_value_self(engine):
    e = engine
    c = neutral_card(e, "Diversity", 3, 1)
    c.face_up = True
    c.definition = get("Diversity", 3)
    e.players[1]["stacks"][1].append(c)
    assert e.line_value(1, 1) == c.value + 0  # 다른 프로토콜 없음 -> 0

    other = neutral_card(e, "Water", 0, 1)
    other.face_up = True
    e.players[1]["stacks"][1].append(other)
    assert e.line_value(1, 1) == c.value + 0 + 2  # Diversity 아닌 카드 있음 -> +2


def test_diversity_4_flips_low_value_card(engine):
    e = engine
    c = neutral_card(e, "Diversity", 4, 1)
    c.definition = get("Diversity", 4)
    p1 = neutral_card(e, "Water", 0, 1)
    p1.face_up = True
    p2 = neutral_card(e, "Fire", 0, 1)
    p2.face_up = True
    p3 = neutral_card(e, "Ice", 0, 2)
    p3.face_up = True
    e.players[1]["stacks"][1].append(p1)
    e.players[1]["stacks"][2].append(p2)
    e.players[2]["stacks"][1].append(p3)  # 3종 프로토콜 -> n=3

    target = neutral_card(e, "Metal", 1, 2)  # eff_val 1 < 3
    target.face_up = True
    e.players[2]["stacks"][2].append(target)

    make_ai(e, 1, [target.uid])
    c.definition["play"](e, c)
    assert target.face_up is False


def test_diversity_5_shares_discard_one():
    assert get("Diversity", 5) is get("Water", 5)


def test_diversity_6_self_deletes_when_few_protocols(engine):
    e = engine
    c = neutral_card(e, "Diversity", 6, 1)
    c.face_up = True
    c.definition = get("Diversity", 6)
    e.players[1]["stacks"][1].append(c)
    assert c.definition["can"]["finishTop"](e, c) is True  # 프로토콜 1종뿐(Diversity 자기 자신)
    c.definition["finishTop"](e, c)
    assert c in e.players[1]["discard"]
