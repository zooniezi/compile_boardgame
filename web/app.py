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
from src.game.ai_heuristic import HeuristicAI
from src.game.engine import Engine
from src.game import protocols as Protocols
from src.game.card_text import CARD_TEXT, PROTOCOL_NAME_KO, PROTOCOL_TAGLINE, PROTOCOL_VERBS
from src.game import draft as DraftMod
from src.game import draftpool as DraftPool

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

# draft_id -> {"draft": Draft, "mode": "hotseat"|"vs_ai", "lock": threading.Lock()}
DRAFTS = {}
DRAFT_AI_PLAYER = 2  # vs_ai 밴픽에서는 항상 플레이어2가 AI (MANUAL_STEPS 정의 그대로)


def _serialize_draft(entry):
    d = entry["draft"]
    cur = d.current()
    owner = {pid: v for pid, v in d.owner.items()}  # id -> 1 | 2 | "ban"
    payload = {
        "mode": entry["mode"],
        "pool": list(d.pool),
        "owner": owner,
        "available": d.available(),
        "current": cur,
        "picks": {"1": list(d.picks[1]), "2": list(d.picks[2])},
        "done": d.done(),
    }
    if d.done():
        p1, p2 = d.result()
        payload["result"] = {"1": p1, "2": p2}
    return payload


def _draft_ai_choose(avail):
    """밴픽 AI의 선택 -- 진짜 카드 상성/전략 평가는 없음(로드맵의 '진짜 AI'
    몫). 지금은 순수 무작위보다 살짝 낫게, 평균 카드 값이 높은 프로토콜을
    더 선호하는 가중 무작위로만 개선."""
    weights = []
    for pid in avail:
        vals = Protocols.VALUES.get(pid, (0, 1, 2, 3, 4, 5))
        avg = sum(vals) / len(vals)
        weights.append(max(0.2, avg))  # 0에 너무 가까워 뽑힐 확률이 0이 되지 않게
    return random.choices(avail, weights=weights, k=1)[0]


def _auto_resolve_ai_draft(entry):
    """vs_ai 밴픽에서 AI 차례(항상 플레이어2)를 자동 진행."""
    if entry["mode"] != "vs_ai":
        return
    d = entry["draft"]
    while not d.done() and d.current()["player"] == DRAFT_AI_PLAYER:
        avail = d.available()
        if not avail:
            break
        pid = _draft_ai_choose(avail)
        ok, _err = d.apply(DRAFT_AI_PLAYER, pid)
        if not ok:
            break


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
            # 명료1처럼 "다음에 바뀌기 전까지 공개 유지"되는 덱 맨 위 카드.
            # 없으면 None.
            "revealedTop": _card_dict(e.cards_by_uid[p["revealedTop"]])
                if p.get("revealedTop") and p["revealedTop"] in e.cards_by_uid else None,
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
                            card_text=CARD_TEXT, names_ko=PROTOCOL_NAME_KO,
                            proto_tagline=PROTOCOL_TAGLINE, proto_verbs=PROTOCOL_VERBS,
                            proto_list=list(Protocols.PROTOCOL_LIST),
                            proto_set={p: Protocols.set_of(p) for p in Protocols.PROTOCOL_LIST})


@app.route("/api/draft/new", methods=["POST"])
def draft_new():
    data = request.get_json(force=True) or {}
    mode = data.get("mode", "hotseat")  # "hotseat" | "vs_ai"
    sets = data.get("sets")  # None(전체) | ["main1","aux1"] | ["main2","aux2"] 등
    pool = DraftPool.build({"sets": sets} if sets else {})
    steps = DraftMod.STEPS if mode == "hotseat" else DraftMod.MANUAL_STEPS
    d = DraftMod.Draft(pool, steps)

    draft_id = uuid.uuid4().hex[:8]
    entry = {"draft": d, "mode": mode, "lock": threading.Lock()}
    DRAFTS[draft_id] = entry
    _auto_resolve_ai_draft(entry)
    return jsonify({"draftId": draft_id, "state": _serialize_draft(entry)})


@app.route("/api/draft/state/<draft_id>")
def draft_state(draft_id):
    entry = DRAFTS.get(draft_id)
    if not entry:
        return jsonify({"error": "밴픽 세션을 찾을 수 없어요"}), 404
    return jsonify(_serialize_draft(entry))


@app.route("/api/draft/pick/<draft_id>", methods=["POST"])
def draft_pick(draft_id):
    entry = DRAFTS.get(draft_id)
    if not entry:
        return jsonify({"error": "밴픽 세션을 찾을 수 없어요"}), 404
    data = request.get_json(force=True) or {}
    player = data.get("player")
    proto_id = data.get("protoId")
    with entry["lock"]:
        d = entry["draft"]
        ok, err = d.apply(player, proto_id)
        if not ok:
            return jsonify({"error": err, **_serialize_draft(entry)}), 400
        _auto_resolve_ai_draft(entry)
    return jsonify(_serialize_draft(entry))


@app.route("/api/new_game", methods=["POST"])
def new_game():
    data = request.get_json(force=True) or {}
    mode = data.get("mode", "hotseat")  # "hotseat" | "vs_ai"
    ai_side = data.get("aiSide", 2)
    # "random"(왕초보) | "heuristic"(초보). 모르는 값이 오면 안전하게 랜덤.
    ai_difficulty = data.get("aiDifficulty", "random")
    first_player = data.get("firstPlayer", random.choice([1, 2]))

    protocols1 = data.get("draftedProtocols", {}).get("1")
    protocols2 = data.get("draftedProtocols", {}).get("2")
    if not protocols1 or not protocols2:
        protocols1, protocols2 = _pick_protocols()

    ai1 = mode == "vs_ai" and ai_side == 1
    ai2 = mode == "vs_ai" and ai_side == 2

    def make_ai_module():
        return HeuristicAI() if ai_difficulty == "heuristic" else RandomAI()

    ai_modules = {}
    if ai1:
        ai_modules[1] = make_ai_module()
    if ai2:
        ai_modules[2] = make_ai_module()

    # AI 시뮬레이션(clone_at_decision 등)이 이 판을 재생하려면 시드가 필요함.
    # 매 판마다 독립적으로 생성 -- 32비트 범위면 random.Random(seed)에 충분.
    seed = random.randint(1, 2**31 - 1)
    e = Engine(protocols1=protocols1, protocols2=protocols2, ai1=ai1, ai2=ai2,
               ai_modules=ai_modules, first_player=first_player, seed=seed)
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
