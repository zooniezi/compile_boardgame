"""컴파일(Compile) 웹 서버.

로컬 hotseat(같은 화면에서 번갈아 두기) + AI 대전을 지원하는 작은 Flask
서버. 게임 엔진(src/game/engine.py)은 그대로 두고, 그 위에 REST API만
얹는다.

엔진의 prompt()가 "멈췄다가 답을 받으면 다음 지점까지 진행"하는 구조라,
그대로 요청/응답(질문 -> 답 -> 다음 질문)으로 옮기면 딱 맞는다. 웹소켓
같은 실시간 푸시는 필요 없다 -- 같은 화면에서 번갈아 조작하는 hotseat이
기본 전제이기 때문.

실행: python3 web/app.py  (프로젝트 루트에서)
"""

import random
import sys
import threading
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.game.ai_random import RandomAI
from src.game.engine import Engine
from src.game import protocols as Protocols
from src.game.card_text import CARD_TEXT, PROTOCOL_NAME_KO

app = Flask(__name__)

# 정적 파일(js/css)이 바뀔 때마다 브라우저 캐시를 무시하고 새로 받아오도록,
# 파일 수정 시각을 쿼리스트링으로 붙여준다 (?v=173...).
@app.template_global()
def asset_url(filename):
    from flask import url_for
    path = Path(app.static_folder) / filename
    try:
        v = int(path.stat().st_mtime)
    except OSError:
        v = 0
    return f"{url_for('static', filename=filename)}?v={v}"

# game_id -> {"engine": Engine, "lock": threading.Lock()}
GAMES = {}


def _pick_protocols():
    """양쪽에게 겹치지 않는 프로토콜 3개씩 무작위 배정 (임시 -- 나중에 드래프트로 교체 가능)."""
    pool = list(Protocols.PROTOCOL_LIST)
    random.shuffle(pool)
    return pool[:3], pool[3:6]


def _card_dict(c):
    return {"uid": c.uid, "proto": c.proto, "value": c.value, "owner": c.owner, "faceUp": c.face_up}


def _serialize(e):
    """엔진 상태를 JSON으로 보낼 수 있는 딕셔너리로 변환."""
    players = {}
    for pi in (1, 2):
        p = e.players[pi]
        players[str(pi)] = {
            "isAI": p["isAI"],
            "protocols": {str(l): p["protocols"][l] for l in (1, 2, 3)},
            "compiled": {str(l): p["compiled"][l] for l in (1, 2, 3)},
            "hand": [_card_dict(c) for c in p["hand"]],
            "deckCount": len(p["deck"]),
            "discard": [_card_dict(c) for c in p["discard"]],
            "stacks": {str(l): [_card_dict(c) for c in p["stacks"][l]] for l in (1, 2, 3)},
            # 패시브 보정(거울0, 금속0 등)까지 반영된 진짜 라인 값 -- 프론트는
            # 이 값을 그대로 써야 한다. 카드 값을 화면에서 단순 합산하면
            # lineValueSelf/lineValueOppDelta 같은 패시브가 누락된다.
            "lineValues": {str(l): e.line_value(pi, l) for l in (1, 2, 3)},
        }
    return {
        "phase": e.phase,
        "turn": e.turn,
        "turnCount": e.turn_count,
        "winner": e.winner,
        "control": e.control,
        "error": str(e.error) if e.error else None,
        "players": players,
        "pending": e.pending,
        "log": e.log[-30:],
    }


def _get_game(game_id):
    entry = GAMES.get(game_id)
    if not entry:
        return None
    return entry


@app.route("/")
def index():
    proto_colors = {
        p: f"rgb({int(r*255)},{int(g*255)},{int(b*255)})"
        for p, (r, g, b) in Protocols.COLOR.items()
    }
    proto_values = {p: list(v) for p, v in Protocols.VALUES.items()}
    return render_template("index.html", proto_colors=proto_colors, proto_values=proto_values,
                            card_text=CARD_TEXT, names_ko=PROTOCOL_NAME_KO)


@app.route("/api/new_game", methods=["POST"])
def new_game():
    data = request.get_json(force=True) or {}
    mode = data.get("mode", "hotseat")  # "hotseat" | "vs_ai"
    ai_side = data.get("aiSide", 2)
    first_player = data.get("firstPlayer", random.choice([1, 2]))

    protocols1, protocols2 = _pick_protocols()

    ai1 = mode == "vs_ai" and ai_side == 1
    ai2 = mode == "vs_ai" and ai_side == 2
    ai_modules = {}
    if ai1:
        ai_modules[1] = RandomAI()
    if ai2:
        ai_modules[2] = RandomAI()

    e = Engine(protocols1=protocols1, protocols2=protocols2, ai1=ai1, ai2=ai2,
               ai_modules=ai_modules, first_player=first_player)
    game_id = uuid.uuid4().hex[:8]
    GAMES[game_id] = {"engine": e, "lock": threading.Lock()}
    e.start()
    return jsonify({"gameId": game_id, "state": _serialize(e)})


@app.route("/api/state/<game_id>")
def get_state(game_id):
    entry = _get_game(game_id)
    if not entry:
        return jsonify({"error": "게임을 찾을 수 없어요"}), 404
    return jsonify(_serialize(entry["engine"]))


@app.route("/api/answer/<game_id>", methods=["POST"])
def answer(game_id):
    entry = _get_game(game_id)
    if not entry:
        return jsonify({"error": "게임을 찾을 수 없어요"}), 404
    data = request.get_json(force=True) or {}
    with entry["lock"]:
        entry["engine"].answer(data.get("value"))
    return jsonify(_serialize(entry["engine"]))


@app.route("/api/advance_anim/<game_id>", methods=["POST"])
def advance_anim(game_id):
    entry = _get_game(game_id)
    if not entry:
        return jsonify({"error": "게임을 찾을 수 없어요"}), 404
    with entry["lock"]:
        entry["engine"].advance_anim()
    return jsonify(_serialize(entry["engine"]))


@app.route("/api/legal_actions/<game_id>/<int:pi>")
def legal_actions(game_id, pi):
    entry = _get_game(game_id)
    if not entry:
        return jsonify({"error": "게임을 찾을 수 없어요"}), 404
    return jsonify(entry["engine"].legal_actions(pi))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
