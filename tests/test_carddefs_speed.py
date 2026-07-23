from src.game.carddefs import get
from tests.conftest import make_ai


def test_speed_0_extra_play(dealt_engine):
    e = dealt_engine
    c = e.new_card("Speed", 0, 1)
    c.definition = get("Speed", 0)
    playable = e.players[1]["hand"][0]
    playable.definition = {}

    class ExtraPlayAI:
        def decide(self, g, req):
            if req["type"] == "action":
                return {"kind": "play", "uid": playable.uid, "line": 1, "faceUp": True}
            return None

        def planRearrange(self, g, pi, compiling_line):
            return None

    e.players[1]["isAI"] = True
    e.ai_modules[1] = ExtraPlayAI()
    c.definition["play"](e, c)
    assert playable in e.players[1]["stacks"][1]


def test_speed_1_reactive_top_and_play(dealt_engine):
    e = dealt_engine
    c = e.new_card("Speed", 1, 1)
    c.definition = get("Speed", 1)
    hand_before = len(e.players[1]["hand"])
    c.definition["play"](e, c)
    assert len(e.players[1]["hand"]) == hand_before + 2

    fn = c.definition["reactiveTop"]["afterCache"]

    class FakeGame:
        def __init__(self):
            self.drew = None

        def draw(self, pi, n):
            self.drew = (pi, n)

    fake = FakeGame()
    fn(fake, c, 2, None, None)
    assert fake.drew is None
    fn(fake, c, 1, None, None)
    assert fake.drew == (1, 1)


def test_speed_2_on_compile_delete_moves_self(engine):
    e = engine
    c = e.new_card("Speed", 2, 1)
    c.face_up = True
    c.definition = get("Speed", 2)
    e.players[1]["stacks"][1].append(c)

    make_ai(e, 1, [2])
    c.definition["onCompileDelete"](e, c)
    assert c in e.players[1]["stacks"][2]


def test_speed_3_play_mandatory_move_and_finish_flip(engine):
    e = engine
    c = e.new_card("Speed", 3, 1)
    c.face_up = True
    c.definition = get("Speed", 3)
    e.players[1]["stacks"][1].append(c)
    other = e.new_card("Metal", 0, 1)
    other.face_up = True
    e.players[1]["stacks"][2].append(other)

    make_ai(e, 1, [other.uid, 3])
    c.definition["play"](e, c)
    assert other in e.players[1]["stacks"][3]

    assert c.definition["can"]["finish"](e, c) is True
    make_ai(e, 1, [c.uid, 2])
    c.definition["finish"](e, c)
    # c 자신을 라인2로 옮긴 뒤, 목적지에서 covered 아니면 뒤집힘
    assert c in e.players[1]["stacks"][2]
    assert c.face_up is False


def test_speed_4_moves_opponent_facedown_card(engine):
    e = engine
    c = e.new_card("Speed", 4, 1)
    c.definition = get("Speed", 4)
    target = e.new_card("Metal", 0, 2)
    target.face_up = False
    e.players[2]["stacks"][1].append(target)

    make_ai(e, 1, [target.uid, 2])
    c.definition["play"](e, c)
    assert target in e.players[2]["stacks"][2]


def test_speed_5_shares_discard_one():
    assert get("Speed", 5) is get("Water", 5)
