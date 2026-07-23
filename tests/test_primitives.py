def test_delete_card_moves_to_owners_discard(engine):
    e = engine
    c = e.new_card("Water", 3, 1)
    c.face_up = True
    e.players[1]["stacks"][1].append(c)

    ok = e.delete_card(c)
    assert ok is True
    assert c in e.players[1]["discard"]
    assert e.players[1]["stacks"][1] == []
    assert c.face_up is False


def test_delete_card_fires_uncover_on_card_beneath(engine):
    e = engine
    trace = []
    bottom = e.new_card("Water", 1, 1)
    bottom.face_up = True
    bottom.definition = {"play": lambda g, c: trace.append("bottom uncovered")}
    top = e.new_card("Water", 2, 1)
    top.face_up = True
    e.players[1]["stacks"][1].extend([bottom, top])

    e.delete_card(top)
    assert trace == ["bottom uncovered"]


def test_delete_cards_batch_fires_reactive_once(engine):
    e = engine
    reacted = []
    watcher = e.new_card("Water", 0, 1)
    watcher.face_up = True
    watcher.definition = {"reactive": {"afterDelete": lambda g, c, actor, ctx, s: reacted.append(actor)}}
    e.players[1]["stacks"][2].append(watcher)

    c1 = e.new_card("Fire", 0, 1)
    c1.face_up = True
    c2 = e.new_card("Fire", 1, 1)
    c2.face_up = True
    e.players[1]["stacks"][1].extend([c1, c2])

    e.delete_cards([c1, c2])
    assert reacted == [1]  # 배치 삭제인데 리액티브는 한 번만 발동


def test_return_card_goes_to_owner_hand(engine):
    e = engine
    c = e.new_card("Water", 4, 1)
    c.face_up = True
    e.players[1]["stacks"][1].append(c)

    ok = e.return_card(c)
    assert ok is True
    assert c in e.players[1]["hand"]
    assert e.players[1]["stacks"][1] == []
    assert c.face_up is False  # 손으로 가면 뒷면(비공개) 처리


def test_return_card_redirected_to_deck_by_corruption(engine):
    e = engine
    # Corruption_1: 상대 카드가 손으로 갈 상황이면 대신 덱 위로.
    redirector = e.new_card("Corruption", 1, 2)
    redirector.face_up = True
    redirector.definition = {"returnToDeck": True}
    e.players[2]["stacks"][3].append(redirector)

    victim = e.new_card("Water", 4, 1)  # owner=1, redirector.owner=2 -> other(2)==1 매치
    victim.face_up = True
    e.players[1]["stacks"][1].append(victim)

    e.return_card(victim)
    assert victim not in e.players[1]["hand"]
    assert victim in e.players[1]["deck"]
    assert victim.face_up is False


def test_put_into_hand_transfers_ownership(engine):
    e = engine
    c = e.new_card("Water", 2, 1)
    c.face_up = True
    e.players[1]["stacks"][1].append(c)

    e.put_into_hand(c, 2)
    assert c in e.players[2]["hand"]
    assert c.owner == 2
    assert c not in e.players[1]["hand"]


def test_flip_card_toggles_face_and_triggers_middle_when_uncovered(engine):
    e = engine
    trace = []
    c = e.new_card("Water", 3, 1)
    c.face_up = False
    c.definition = {"play": lambda g, card: trace.append("middle")}
    e.players[1]["stacks"][1].append(c)

    e.flip_card(c)
    assert c.face_up is True
    assert trace == ["middle"]  # 앞면으로 뒤집히고 uncovered라 Middle 발동

    trace.clear()
    e.flip_card(c)  # 다시 뒷면으로: Middle 발동 안 함
    assert c.face_up is False
    assert trace == []


def test_flip_card_blocked_by_cant_flip(engine):
    e = engine
    c = e.new_card("Water", 3, 1)
    c.face_up = True
    c.definition = {"cantFlip": True}
    e.players[1]["stacks"][1].append(c)

    e.flip_card(c)
    assert c.face_up is True  # 뒤집히지 않음


def test_flip_card_self_destructs_when_flagged(engine):
    e = engine
    c = e.new_card("Metal", 6, 1)
    c.face_up = True
    c.definition = {"onFlipSelfDestruct": True}
    e.players[1]["stacks"][1].append(c)

    e.flip_card(c)
    assert c in e.players[1]["discard"]  # 뒤집는 대신 삭제됨
    assert e.players[1]["stacks"][1] == []


def test_move_card_shifts_to_new_line_and_uncovers_source():
    from src.game.engine import Engine
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    trace = []
    bottom = e.new_card("Water", 1, 1)
    bottom.face_up = True
    bottom.definition = {"play": lambda g, c: trace.append("source uncovered")}
    moving = e.new_card("Water", 2, 1)
    moving.face_up = True
    e.players[1]["stacks"][1].extend([bottom, moving])

    ok = e.move_card(moving, 1, 3)
    assert ok is True
    assert e.players[1]["stacks"][1] == [bottom]
    assert e.players[1]["stacks"][3] == [moving]
    assert trace == ["source uncovered"]


def test_move_card_onto_existing_stack_uncovers_itself(engine):
    e = engine
    trace = []
    moving = e.new_card("Water", 2, 1)
    moving.face_up = True
    moving.definition = {"play": lambda g, c: trace.append("self uncovered on landing")}
    blocker = e.new_card("Water", 0, 1)  # moving을 덮어서 소스에서 covered 상태로 만듦
    blocker.face_up = True
    e.players[1]["stacks"][1].extend([moving, blocker])

    existing = e.new_card("Water", 0, 1)
    existing.face_up = True
    e.players[1]["stacks"][2].append(existing)

    e.move_card(moving, 1, 2)
    # moving은 소스에서 covered(=wasTop False) 상태였으므로, 목적지 top에 착지하며
    # covered -> uncovered로 전환된 것 -- 자기 자신의 Middle 명령이 발동해야 함.
    assert trace == ["self uncovered on landing"]
    assert e.players[1]["stacks"][2] == [existing, moving]
