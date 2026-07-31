"""가이드 튜토리얼(src/game/tutorial_script.py) 회귀 테스트.

카드 총량 보존(apply_scenario가 새로 만들지 않고 재배치만 하는지),
스크립트 AI가 매 챕터마다 새로 인스턴스화되는지(상태가 판 사이로 새지
않는지), 그리고 두 챕터가 튜토리얼이 가정하는 정확한 타이밍에 정확한
상태(상대의 뒷면 카드, Control 전환, 재배치로 인한 무해한 재컴파일)에
도달하는지를 헤드리스로 재생해서 확인한다.
"""

from src.game.engine import Engine
from src.game import tutorial_script as T


def _card_count(e):
    total = 0
    for pi in (1, 2):
        p = e.players[pi]
        total += len(p["hand"]) + len(p["deck"]) + len(p["discard"])
        for line in (1, 2, 3):
            total += len(p["stacks"][line])
    return total


def _run_until_input(e):
    """anim 이벤트는 계속 넘기고, input 프롬프트에서 멈춰 req를 반환.
    엔진이 끝났으면(에러/무승부 등) None."""
    while e.pending is not None and e.pending.get("kind") == "anim":
        e.advance_anim()
    if e.pending is None:
        if e.error:
            raise e.error
        return None
    return e.pending["req"]


def _find_hand_card(e, pi, proto, value):
    for c in e.players[pi]["hand"]:
        if c.proto == proto and c.value == value:
            return c
    raise AssertionError(f"P{pi} 손패에 {proto}_{value} 없음: "
                          f"{[(c.proto, c.value) for c in e.players[pi]['hand']]}")


def _make_chapter_engine(idx):
    ch = T.TUTORIAL_CHAPTERS[idx]
    e = Engine(protocols1=ch["protocols1"], protocols2=ch["protocols2"],
               ai1=False, ai2=True, ai_modules={2: ch["ai_class"]()},
               first_player=1, decks=ch["decks"], on_dealt=ch["on_dealt"],
               auto_compile=False, auto_refresh=False, seed=1)
    e.start()
    return e


def test_apply_scenario_preserves_card_totals():
    """ch2_on_dealt가 카드를 재배치만 하고 새로 만들거나 잃어버리지 않는지."""
    ch = T.TUTORIAL_CHAPTERS[1]
    e = Engine(protocols1=ch["protocols1"], protocols2=ch["protocols2"], decks=ch["decks"])
    e.build_decks()
    assert _card_count(e) == 36
    ch["on_dealt"](e)
    assert _card_count(e) == 36
    # 각 플레이어별로도 18장씩 그대로.
    for pi in (1, 2):
        p = e.players[pi]
        total = (len(p["hand"]) + len(p["deck"]) + len(p["discard"])
                 + sum(len(p["stacks"][line]) for line in (1, 2, 3)))
        assert total == 18, f"P{pi} 카드 총량이 18이 아님: {total}"


def test_tutorial_ai_instances_are_fresh_per_engine():
    """TUTORIAL_CHAPTERS는 인스턴스가 아니라 클래스를 담아둬야 한다 --
    그래야 매 /api/tutorial/new 호출마다 새 AI 객체가 생겨서, Ch1ScriptedAI
    의 self.turn 같은 상태가 이전 플레이스루에서 새 플레이스루로 새지
    않는다."""
    ch = T.TUTORIAL_CHAPTERS[0]
    ai_a = ch["ai_class"]()
    ai_a.turn = 5  # 마치 예전 판을 5수까지 진행했던 것처럼
    ai_b = ch["ai_class"]()
    assert ai_b.turn == 0
    assert ai_a is not ai_b


def test_chapter1_scripted_playthrough_reaches_compile_and_refresh():
    e = _make_chapter_engine(0)
    assert _card_count(e) == 36

    req = _run_until_input(e)
    assert req["type"] == "action" and req["chooser"] == 1

    # play1: Life_4 앞면 라인1
    c = _find_hand_card(e, 1, "Life", 4)
    e.answer({"kind": "play", "uid": c.uid, "line": 1, "faceUp": True})
    req = _run_until_input(e)

    # AI가 첫 수로 라인2에 뒷면 카드를 냈어야 함 (oppFd 조건).
    opp_has_fd = any(not card.face_up for line in (1, 2, 3) for card in e.players[2]["stacks"][line])
    assert opp_has_fd

    assert req["type"] == "action" and req["chooser"] == 1
    # play2: Metal_6 뒷면 라인1
    c = _find_hand_card(e, 1, "Metal", 6)
    e.answer({"kind": "play", "uid": c.uid, "line": 1, "faceUp": False})
    req = _run_until_input(e)

    assert req["type"] == "action" and req["chooser"] == 1
    # play3: Life_2 앞면 라인1 (효과: 뽑기 + 뒷면 카드 1장 선택적으로 뒤집기)
    c = _find_hand_card(e, 1, "Life", 2)
    e.answer({"kind": "play", "uid": c.uid, "line": 1, "faceUp": True})
    req = _run_until_input(e)

    # passOpt: 선택적 chooseCard여야 하고, 패스(None)해도 진행돼야 함.
    assert req["type"] == "chooseCard" and req.get("optional") is True
    e.answer(None)
    req = _run_until_input(e)

    assert req["type"] == "action" and req["chooser"] == 1
    # AI가 라인2/3을 계속 채워 값으로 앞서면서 Control을 가져갔어야 함.
    assert e.control == 2

    # play4: Life_3 앞면 라인1 -> 라인1 합계 10, 컴파일 가능.
    c = _find_hand_card(e, 1, "Life", 3)
    e.answer({"kind": "play", "uid": c.uid, "line": 1, "faceUp": True})
    req = _run_until_input(e)

    assert req["type"] == "confirmCompile"
    assert 1 in req["candidates"]
    e.answer(1)
    req = _run_until_input(e)

    # 손패가 HAND_SIZE 미만으로 남아 리프레시 버튼이 뜸.
    assert req["type"] == "action" and req["chooser"] == 1
    assert req.get("canRefresh") is True
    e.answer({"kind": "refresh"})
    _run_until_input(e)

    assert _card_count(e) == 36


def test_chapter2_scripted_playthrough_defuses_opponent_win():
    e = _make_chapter_engine(1)
    assert _card_count(e) == 36

    req = _run_until_input(e)
    # 라인2/3을 4대0으로 이기고 있어 턴1 control 체크에서 자동으로 Control 획득.
    assert e.control == 1
    assert req["type"] == "action" and req["chooser"] == 1
    assert req.get("canRefresh") is True  # 손패 2장

    e.answer({"kind": "refresh"})
    req = _run_until_input(e)
    assert req["type"] == "choosePlayer"
    e.answer(2)  # 상대 프로토콜을 재배치
    req = _run_until_input(e)

    assert req["type"] == "rearrange"
    assert req["target"] == 2
    # 이미 컴파일된 라인(2 또는 3)의 프로토콜을 라인1로 스왑.
    already_compiled_line = 2 if req["compiled"][2] else 3
    order = {1: 1, 2: 2, 3: 3}
    order[1], order[already_compiled_line] = order[already_compiled_line], order[1]
    e.answer(order)
    _run_until_input(e)

    # 라인1이 이제 이미 컴파일된 프로토콜을 가리켜야(다음 컴파일이 무해한
    # 재컴파일이 되도록) 한다.
    assert e.players[2]["compiled"][1] is True
    assert _card_count(e) == 36
