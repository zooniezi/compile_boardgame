from tests.conftest import make_ai


def test_check_control_taken_when_winning_two_lines(engine):
    e = engine
    e.turn = 1
    for line in (1, 2):
        c = e.new_card("Water", 3, 1)
        c.face_up = True
        e.players[1]["stacks"][line].append(c)
    assert e.control is None
    e.check_control()
    assert e.control == 1


def test_swap_protocols_swaps_proto_and_compiled_flag(engine):
    e = engine
    p = e.players[1]
    p["protocols"] = {1: "Water", 2: "Fire", 3: "Life"}
    p["compiled"] = {1: True, 2: False, 3: False}
    e.swap_protocols(1, 1, 2)
    assert p["protocols"] == {1: "Fire", 2: "Water", 3: "Life"}
    assert p["compiled"] == {1: False, 2: True, 3: False}


def test_rearrange_protocols_full_permutation(engine):
    e = engine
    p = e.players[1]
    p["protocols"] = {1: "Water", 2: "Fire", 3: "Life"}
    p["compiled"] = {1: False, 2: False, 3: True}
    # order[슬롯] = 그 슬롯에 들어갈 프로토콜의 "원래" 라인 번호
    e.rearrange_protocols(1, {1: 3, 2: 1, 3: 2})
    assert p["protocols"] == {1: "Life", 2: "Water", 3: "Fire"}
    assert p["compiled"] == {1: True, 2: False, 3: False}


def test_choose_rearrange_rejects_no_change(engine):
    """룰북: 재배열은 반드시 위치가 바뀌어야 한다 -- 그대로 두는 답은 강제로
    최소 한 곳이 바뀌는 기본값으로 대체된다."""
    e = engine
    make_ai(e, 1, [{1: 1, 2: 2, 3: 3}])  # 변화 없는 답을 일부러 제출
    order = e.choose_rearrange(1, 1)
    assert order != {1: 1, 2: 2, 3: 3}
    assert sorted(order.values()) == [1, 2, 3]  # 여전히 유효한 순열이어야 함


def test_choose_rearrange_rejects_invalid_input(engine):
    e = engine
    make_ai(e, 1, ["garbage"])  # dict가 아닌 잘못된 답
    order = e.choose_rearrange(1, 1)
    assert order != {1: 1, 2: 2, 3: 3}
    assert sorted(order.values()) == [1, 2, 3]


def test_choose_rearrange_accepts_valid_change(engine):
    e = engine
    make_ai(e, 1, [{1: 2, 2: 3, 3: 1}])
    order = e.choose_rearrange(1, 1)
    assert order == {1: 2, 2: 3, 3: 1}


def test_choose_rearrange_handles_json_stringified_keys(engine):
    """웹 API를 거치면 JSON 직렬화 때문에 딕셔너리 키가 문자열이 된다
    ("1","2","3") -- 실제 브라우저에서 재배치 확정이 반영 안 되던 버그의
    회귀 테스트."""
    e = engine
    make_ai(e, 1, [{"1": 2, "2": 3, "3": 1}])  # JSON 왕복을 흉내낸 문자열 키
    order = e.choose_rearrange(1, 1)
    assert order == {1: 2, 2: 3, 3: 1}


def test_choose_rearrange_must_change_false_allows_no_change(engine):
    """Control로 인한 재배치("may rearrange")는 카드 효과와 달리 그대로 둬도 된다."""
    e = engine
    make_ai(e, 1, [{1: 1, 2: 2, 3: 3}])
    order = e.choose_rearrange(1, 1, {"must_change": False})
    assert order == {1: 1, 2: 2, 3: 3}


def test_mark_compiled_sets_winner_only_when_all_three(engine):
    e = engine
    p = e.players[1]
    p["compiled"] = {1: True, 2: True, 3: False}
    won = e.mark_compiled(1, 3)
    assert won is True
    assert e.winner == 1


def test_mark_compiled_not_won_yet(engine):
    e = engine
    p = e.players[1]
    p["compiled"] = {1: True, 2: False, 3: False}
    won = e.mark_compiled(1, 2)
    assert won is False
    assert e.winner is None


def test_do_compile_clears_line_and_flips_protocol(dealt_engine):
    e = dealt_engine
    p = e.players[1]
    c1 = e.new_card("Water", 5, 1)
    c1.face_up = True
    c2 = e.new_card("Water", 5, 2)  # 상대 카드도 같이 지워짐
    c2.face_up = True
    p["stacks"][1].append(c1)
    e.players[2]["stacks"][1].append(c2)

    before_discard = len(p["discard"])
    e.do_compile(1, 1)

    assert p["compiled"][1] is True
    assert p["stacks"][1] == []
    assert e.players[2]["stacks"][1] == []
    assert c1 in p["discard"]
    assert c2 in e.players[2]["discard"]
    assert len(p["discard"]) == before_discard + 1


def test_do_compile_wins_game_on_third_protocol(dealt_engine):
    e = dealt_engine
    p = e.players[1]
    p["compiled"] = {1: True, 2: True, 3: False}
    e.do_compile(1, 3)
    assert e.winner == 1


def test_recompile_draws_from_opponent_deck(dealt_engine):
    e = dealt_engine
    p = e.players[1]
    p["compiled"][1] = True  # 이미 컴파일된 라인 -> 재컴파일
    opp_deck_before = len(e.players[2]["deck"])
    hand_before = len(p["hand"])
    e.do_compile(1, 1)
    assert len(e.players[2]["deck"]) == opp_deck_before - 1
    assert len(p["hand"]) == hand_before + 1
