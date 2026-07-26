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


def test_draw_log_attributes_the_triggering_card_when_played_via_play_card():
    """카드 효과로 인한 뽑기는 로그에 원인 카드가 남아야 한다 (Water_2:
    카드 2장 뽑기). play_card()의 정식 경로를 거쳐야 _card_stack이 쌓여서
    current_source_card()가 올바르게 그 카드를 가리킨다."""
    import sys
    sys.path.insert(0, "tests")
    from conftest import make_ai
    from src.game.engine import Engine

    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    e.players[1]["protocols"][1] = "Water"
    for _ in range(5):
        e.players[1]["deck"].append(e.new_card("Water", 1, 1))
    w2 = e.new_card("Water", 2, 1)
    e.players[1]["hand"].append(w2)
    make_ai(e, 1, [{1: 2, 2: 1, 3: 3}])

    before = len(e.log)
    e.play_card(1, w2.uid, 1, True)
    draw_entries = [x for x in e.log[before:] if x["key"] == "ev.draw"]
    assert len(draw_entries) == 1
    assert draw_entries[0]["params"]["source"] == {"uid": w2.uid, "proto": "Water", "value": 2}


def test_refresh_draw_has_no_source_since_it_is_not_a_card_effect():
    """턴의 리프레시 행동 자체는 카드 효과가 아니므로 원인 카드가 없다."""
    from src.game.engine import Engine

    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    for _ in range(5):
        e.players[1]["deck"].append(e.new_card("Water", 1, 1))
    before = len(e.log)
    e.refresh(1)
    entries = e.log[before:]
    assert entries[0]["key"] == "ev.refresh"
    assert "source" not in entries[0]["params"]
