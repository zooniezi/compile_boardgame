def test_play_card_lands_face_up_and_triggers_middle(dealt_engine):
    e = dealt_engine
    trace = []
    card = e.players[1]["hand"][0]
    card.definition = {"play": lambda g, c: trace.append("played")}
    uid = card.uid

    ok = e.play_card(1, uid, line=2, face_up=True)
    assert ok is True
    assert trace == ["played"]
    assert e.players[1]["stacks"][2] == [card]
    assert card.face_up is True
    assert card not in e.players[1]["hand"]


def test_play_card_face_down_does_not_trigger_middle(dealt_engine):
    e = dealt_engine
    trace = []
    card = e.players[1]["hand"][0]
    card.definition = {"play": lambda g, c: trace.append("played")}
    uid = card.uid

    e.play_card(1, uid, line=1, face_up=False)
    assert trace == []  # 뒷면 카드는 Middle 명령이 발동하지 않음
    assert e.players[1]["stacks"][1][0].face_up is False


def test_playing_on_top_covers_and_fires_cover_trigger(dealt_engine):
    e = dealt_engine
    trace = []
    bottom = e.players[1]["hand"][0]
    bottom.definition = {"onCovered": lambda g, c, incoming, up: trace.append("covered")}
    e.play_card(1, bottom.uid, line=1, face_up=True)

    top_card = e.players[1]["hand"][0]
    top_card.definition = {}
    e.play_card(1, top_card.uid, line=1, face_up=True)

    assert trace == ["covered"]
    assert e.players[1]["stacks"][1] == [bottom, top_card]


def test_take_from_hand_removes_and_returns_card():
    from src.game.engine import Engine
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    e.build_decks()
    hand_before = list(e.players[1]["hand"])
    target = hand_before[2]
    got = e.take_from_hand(1, target.uid)
    assert got is target
    assert target not in e.players[1]["hand"]
    assert len(e.players[1]["hand"]) == len(hand_before) - 1
