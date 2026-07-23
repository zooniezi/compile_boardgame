from src.game.draft import Draft, STEPS, MANUAL_STEPS
from src.game import protocols as Protocols


def test_standard_sequence_ends_with_three_picks_each():
    d = Draft(list(Protocols.PROTOCOL_LIST))
    order = []
    while not d.done():
        cur = d.current()
        order.append((cur["player"], cur["action"]))
        pid = d.available()[0]
        ok, err = d.apply(cur["player"], pid)
        assert ok, err

    p1, p2 = d.result()
    assert len(p1) == 3
    assert len(p2) == 3
    # 서로 겹치지 않음
    assert set(p1).isdisjoint(p2)
    # 순서: P1 pick1 P2 pick2 P1 ban1 P2 ban1 P1 pick2 P2 pick1
    assert order == [
        (1, "pick"),
        (2, "pick"), (2, "pick"),
        (1, "ban"),
        (2, "ban"),
        (1, "pick"), (1, "pick"),
        (2, "pick"),
    ]


def test_current_reflects_remaining_within_a_multi_count_step():
    d = Draft(list(Protocols.PROTOCOL_LIST))
    d.apply(1, d.available()[0])  # P1 pick1 완료
    cur = d.current()
    assert cur == {"player": 2, "action": "pick", "remaining": 2}
    d.apply(2, d.available()[0])
    cur = d.current()
    assert cur == {"player": 2, "action": "pick", "remaining": 1}


def test_apply_rejects_wrong_player_turn():
    d = Draft(list(Protocols.PROTOCOL_LIST))
    ok, err = d.apply(2, d.available()[0])  # 지금은 P1 차례
    assert ok is False
    assert err == "not your turn"


def test_apply_rejects_unknown_protocol():
    d = Draft(["Water", "Fire", "Life"])
    ok, err = d.apply(1, "NotAProtocol")
    assert ok is False
    assert err == "unknown protocol"


def test_apply_rejects_already_taken_protocol():
    d = Draft(list(Protocols.PROTOCOL_LIST))
    pid = d.available()[0]
    d.apply(1, pid)  # P1이 픽
    ok, err = d.apply(2, pid)  # 같은 걸 다시
    assert ok is False
    assert err == "protocol unavailable"


def test_apply_after_done_is_rejected():
    d = Draft(list(Protocols.PROTOCOL_LIST))
    while not d.done():
        cur = d.current()
        d.apply(cur["player"], d.available()[0])
    ok, err = d.apply(1, d.pool[0])
    assert ok is False
    assert err == "draft complete"


def test_result_is_none_before_done():
    d = Draft(list(Protocols.PROTOCOL_LIST))
    assert d.result() is None


def test_banned_protocol_removed_from_available_for_both():
    d = Draft(list(Protocols.PROTOCOL_LIST))
    d.apply(1, d.available()[0])
    d.apply(2, d.available()[0])
    d.apply(2, d.available()[0])
    ban_target = d.available()[0]
    d.apply(1, ban_target)  # P1 ban
    assert ban_target not in d.available()
    p1, p2 = None, None
    while not d.done():
        cur = d.current()
        d.apply(cur["player"], d.available()[0])
    p1, p2 = d.result()
    assert ban_target not in p1
    assert ban_target not in p2


def test_manual_steps_no_bans_each_player_picks_three_in_a_row():
    d = Draft(list(Protocols.PROTOCOL_LIST), steps=MANUAL_STEPS)
    order = []
    while not d.done():
        cur = d.current()
        order.append(cur["player"])
        d.apply(cur["player"], d.available()[0])
    assert order == [1, 1, 1, 2, 2, 2]
    p1, p2 = d.result()
    assert len(p1) == 3 and len(p2) == 3


def test_small_pool_matching_min_still_works():
    # STEPS가 8개를 소모하므로 딱 맞는 8장 풀로도 끝까지 진행되어야 함
    pool = list(Protocols.PROTOCOL_LIST)[:8]
    d = Draft(pool)
    while not d.done():
        cur = d.current()
        ok, err = d.apply(cur["player"], d.available()[0])
        assert ok, err
    assert d.available() == []
