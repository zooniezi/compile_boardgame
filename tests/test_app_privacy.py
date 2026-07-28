"""web/app.py -- 뒷면 카드/손패 프라이버시 마스킹 회귀 테스트.

서버는 "지금 화면을 보는 게 누구인지" 알 방법이 없으므로(hotseat은 세션
구분이 없고, vs_ai는 AI 턴에도 사람이 화면을 보고 있음), "지금 턴인 사람
플레이어" 기준으로 노출 범위를 정한다:
- 어떤 플레이어의 손패/뒷면 카드든, 소유자가 AI이거나 지금이 그 소유자의
  턴이 아니면 진짜 정체(proto/value)를 감추고 None으로 보낸다.
- 앞면(공개) 카드와 버림더미는 원래 공개 정보라 항상 그대로 보낸다.
"""

import sys
sys.path.insert(0, ".")
sys.path.insert(0, "web")

from app import app, GAMES


def _client():
    return app.test_client()


def test_hotseat_hides_the_non_turn_players_facedown_card():
    client = _client()
    r = client.post("/api/new_game", json={"mode": "hotseat"})
    gid = r.get_json()["gameId"]
    e = GAMES[gid]["engine"]
    e.turn = 1

    c1 = e.new_card("Water", 3, 1)
    c1.face_up = False
    e.players[1]["stacks"][1].append(c1)
    c2 = e.new_card("Ice", 4, 2)
    c2.face_up = False
    e.players[2]["stacks"][1].append(c2)

    data = client.get(f"/api/state/{gid}").get_json()
    s1 = next(c for c in data["players"]["1"]["stacks"]["1"] if c["uid"] == c1.uid)
    s2 = next(c for c in data["players"]["2"]["stacks"]["1"] if c["uid"] == c2.uid)
    assert s1["proto"] == "Water"  # 지금 턴인 플레이어1 자신의 카드는 보임
    assert s2["proto"] is None     # 상대(플레이어2) 카드는 감춰짐
    assert s2["value"] is None
    assert s2["faceUp"] is False   # faceUp 자체는 렌더링에 필요하니 그대로 옴


def test_hotseat_flips_visibility_when_turn_changes():
    client = _client()
    r = client.post("/api/new_game", json={"mode": "hotseat"})
    gid = r.get_json()["gameId"]
    e = GAMES[gid]["engine"]

    c1 = e.new_card("Water", 3, 1)
    c1.face_up = False
    e.players[1]["stacks"][1].append(c1)
    c2 = e.new_card("Ice", 4, 2)
    c2.face_up = False
    e.players[2]["stacks"][1].append(c2)

    e.turn = 2
    data = client.get(f"/api/state/{gid}").get_json()
    s1 = next(c for c in data["players"]["1"]["stacks"]["1"] if c["uid"] == c1.uid)
    s2 = next(c for c in data["players"]["2"]["stacks"]["1"] if c["uid"] == c2.uid)
    assert s1["proto"] is None
    assert s2["proto"] == "Ice"


def test_ai_facedown_cards_are_always_hidden_even_on_ai_turn():
    """AI 턴이 진행 중일 때도(사람이 화면을 보고 있으므로) AI의 뒷면
    카드는 절대 정체가 드러나면 안 된다."""
    client = _client()
    r = client.post("/api/new_game", json={"mode": "vs_ai", "aiSide": 2})
    gid = r.get_json()["gameId"]
    e = GAMES[gid]["engine"]
    e.turn = 2  # AI 턴

    c = e.new_card("Ice", 5, 2)
    c.face_up = False
    e.players[2]["stacks"][1].append(c)

    data = client.get(f"/api/state/{gid}").get_json()
    s = next(x for x in data["players"]["2"]["stacks"]["1"] if x["uid"] == c.uid)
    assert s["proto"] is None
    assert s["value"] is None


def test_face_up_cards_are_never_masked():
    client = _client()
    r = client.post("/api/new_game", json={"mode": "hotseat"})
    gid = r.get_json()["gameId"]
    e = GAMES[gid]["engine"]
    e.turn = 2  # 카드 소유자(1)와 다른 턴이어도

    c = e.new_card("Water", 2, 1)
    c.face_up = True
    e.players[1]["stacks"][2].append(c)

    data = client.get(f"/api/state/{gid}").get_json()
    s = next(x for x in data["players"]["1"]["stacks"]["2"] if x["uid"] == c.uid)
    assert s["proto"] == "Water"  # 공개 정보라 항상 그대로


def test_discard_is_never_masked_regardless_of_turn_or_owner():
    client = _client()
    r = client.post("/api/new_game", json={"mode": "vs_ai", "aiSide": 2})
    gid = r.get_json()["gameId"]
    e = GAMES[gid]["engine"]
    e.turn = 1  # AI(플레이어2)의 턴이 아니어도

    c = e.new_card("Metal", 3, 2)
    c.face_up = True
    e.players[2]["discard"].append(c)

    data = client.get(f"/api/state/{gid}").get_json()
    s = data["players"]["2"]["discard"][-1]
    assert s["proto"] == "Metal"  # 버림더미는 항상 공개 정보


def test_hand_is_masked_for_ai_and_for_the_non_turn_player():
    client = _client()
    r = client.post("/api/new_game", json={"mode": "vs_ai", "aiSide": 2})
    gid = r.get_json()["gameId"]
    e = GAMES[gid]["engine"]

    e.turn = 1
    e.players[1]["hand"].append(e.new_card("Fire", 1, 1))
    e.players[2]["hand"].append(e.new_card("Metal", 3, 2))

    data = client.get(f"/api/state/{gid}").get_json()
    my_hand = data["players"]["1"]["hand"][-1]
    ai_hand = data["players"]["2"]["hand"][-1]
    assert my_hand["proto"] == "Fire"   # 지금 턴인 사람 자신의 손패는 보임
    assert ai_hand["proto"] is None     # AI 손패는 항상 감춰짐


def test_vs_ai_always_shows_the_human_players_own_hand_even_during_ai_turn():
    """vs_ai는 화면을 보는 사람이 한 명뿐이라, AI 턴이 진행 중이어도 내
    손패는 계속 보여야 한다 (숨길 상대 사람이 없으므로). hotseat과 달리
    "지금 누구 턴인지"가 사람 손패 노출 여부에 영향을 주면 안 된다."""
    client = _client()
    r = client.post("/api/new_game", json={"mode": "vs_ai", "aiSide": 2})
    gid = r.get_json()["gameId"]
    e = GAMES[gid]["engine"]
    e.players[1]["hand"].append(e.new_card("Fire", 1, 1))
    e.players[2]["hand"].append(e.new_card("Metal", 3, 2))

    e.turn = 2  # AI 턴
    data = client.get(f"/api/state/{gid}").get_json()
    assert data["players"]["1"]["hand"][-1]["proto"] == "Fire"  # 여전히 보임
    assert data["players"]["2"]["hand"][-1]["proto"] is None    # AI는 여전히 감춰짐


def test_vs_ai_always_shows_the_human_players_own_facedown_board_cards():
    """손패뿐 아니라 필드의 뒷면 카드도 마찬가지 -- vs_ai에서 AI 턴이어도
    사람 자신이 낸 뒷면 카드는 계속 보여야 한다."""
    client = _client()
    r = client.post("/api/new_game", json={"mode": "vs_ai", "aiSide": 2})
    gid = r.get_json()["gameId"]
    e = GAMES[gid]["engine"]
    c = e.new_card("Water", 3, 1)
    c.face_up = False
    e.players[1]["stacks"][1].append(c)

    e.turn = 2  # AI 턴
    data = client.get(f"/api/state/{gid}").get_json()
    s = next(x for x in data["players"]["1"]["stacks"]["1"] if x["uid"] == c.uid)
    assert s["proto"] == "Water"
