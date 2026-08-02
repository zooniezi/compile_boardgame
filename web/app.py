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

import colorsys
import random
import sys
import threading
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.game.ai_random import RandomAI
from src.game.ai_heuristic import HeuristicAI
from src.game.ai_ismcts_learned import ISMCTSLearnedAI
from src.game.ai_ismcts_mlp import ISMCTSMLPAI
from src.game.engine import Engine
from src.game import protocols as Protocols
from src.game.card_text import CARD_TEXT, PROTOCOL_NAME_KO, PROTOCOL_TAGLINE, PROTOCOL_VERBS
from src.game import draft as DraftMod
from src.game import draftpool as DraftPool
from src.game import tutorial_script as TutorialScript

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


def _card_dict(c, hidden=False):
    """hidden=True면 이 카드의 진짜 정체(proto/value)를 감추고 uid/owner/
    faceUp만 보낸다 -- 뒷면 카드가 다른 플레이어(또는 AI) 소유일 때 씀.
    화면은 faceUp만으로도 카드 뒷면을 그릴 수 있으니 렌더링엔 지장 없다."""
    if hidden:
        return {"uid": c.uid, "proto": None, "value": None, "owner": c.owner, "faceUp": c.face_up}
    return {"uid": c.uid, "proto": c.proto, "value": c.value, "owner": c.owner, "faceUp": c.face_up}


def _serialize(e):
    """엔진 상태를 JSON으로 보낼 수 있는 딕셔너리로 변환.

    프라이버시: 이 화면은 두 플레이어가 한 브라우저를 같이 보는 hotseat과,
    사람+AI가 같이 보는 vs_ai 양쪽 다 지원한다. 서버는 "지금 화면을 보는
    게 정확히 누구인지" 알 방법이 없으므로(세션 구분이 없음), 대신 아래
    규칙으로 노출 범위를 정한다:
    - 소유자가 AI면: 항상 감춘다 (누구 턴이든 사람이 절대 못 보게).
    - 소유자가 사람이고, 상대도 사람(hotseat)이면: 지금 그 소유자의
      턴일 때만 보여준다 (상대가 자기 턴에 내 패를 못 보게). 단, 지금
      대기 중인 입력 프롬프트의 실제 응답자(chooser)가 이 소유자라면
      턴 주인이 상대여도 보여준다 -- Lust_6/Inert_3처럼 카드 효과가
      "상대는 자기 손패에서 골라라"를 강제하는 경우, 응답자는 소유자
      자신인데 e.turn은 여전히 카드를 낸 쪽이라 원래 규칙만으로는 자기
      손패가 안 보여서 고를 카드 정보가 null로 나오는 문제가 있었다.
    - 소유자가 사람이고, 상대는 AI(vs_ai)면: 항상 보여준다 -- 화면을
      보는 사람은 한 명뿐이라 자기 자신에게 숨길 이유가 없다 (AI 턴이라고
      내 손패까지 같이 숨겨지면 안 됨).
    앞면(공개) 카드와 버림더미는 원래 공개 정보라 그대로 보낸다.
    """
    pending_chooser = None
    if e.pending and e.pending.get("kind") == "input":
        pending_chooser = e.pending.get("req", {}).get("chooser")

    players = {}
    for pi in (1, 2):
        p = e.players[pi]
        opp = e.players[2 if pi == 1 else 1]
        if p["isAI"]:
            visible = False
        elif opp["isAI"]:
            visible = True  # vs_ai: 사람은 한 명뿐이니 항상 자기 걸 봄
        else:
            visible = (e.turn == pi) or (pending_chooser == pi)  # hotseat

        def hand_card(c, _visible=visible):
            return _card_dict(c, hidden=not _visible)

        def stack_card(c, _visible=visible):
            # 앞면 카드는 원래 공개 정보라 소유자와 무관하게 항상 그대로.
            return _card_dict(c, hidden=(not c.face_up and not _visible))

        players[str(pi)] = {
            "isAI": p["isAI"],
            "protocols": {str(l): p["protocols"][l] for l in (1, 2, 3)},
            "compiled": {str(l): p["compiled"][l] for l in (1, 2, 3)},
            "hand": [hand_card(c) for c in p["hand"]],
            "deckCount": len(p["deck"]),
            "discard": [_card_dict(c) for c in p["discard"]],  # 버림더미는 항상 공개 정보
            "stacks": {str(l): [stack_card(c) for c in p["stacks"][l]] for l in (1, 2, 3)},
            # 패시브 보정(거울0, 금속0 등)까지 반영된 진짜 라인 값 -- 프론트는
            # 이 값을 그대로 써야 한다. 카드 값을 화면에서 단순 합산하면
            # lineValueSelf/lineValueOppDelta 같은 패시브가 누락된다.
            "lineValues": {str(l): e.line_value(pi, l) for l in (1, 2, 3)},
            # 명료1처럼 "다음에 바뀌기 전까지 공개 유지"되는 덱 맨 위 카드.
            # 없으면 None. 규칙상 원래 공개(양쪽 다 볼 수 있음)라 마스킹 대상 아님.
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


def _pastel_variant(rgb):
    """protocols.py의 원색(검은 배경용 네온)을 밝은/파스텔 테마에서도 쓸 수
    있게 변환한다. 색상(H)은 그대로 둬서 "이 프로토콜은 이 색"이라는 정체성은
    유지한다.

    채도(S)는 원래 값에 비례시키지 않고 좁은 목표 띠(0.45~0.80)로 다시
    맞춘다 -- 원래 채도를 그대로 비례 축소하면 역효과가 난다: Clarity/Peace
    처럼 "아주 밝아서 눈에는 옅어 보이지만 HSL 채도 자체는 이미 높은" 색을
    그대로 어둡게(밝은 배경에서 테두리/글자로 쓸 수 있게)만 만들면, 밝기만
    빠지고 채도는 유지돼 오히려 쨍한 색이 튀어나온다. 채도를 아예 좁은
    띠로 다시 맞춰야 "같은 계열의 파스텔"처럼 고르게 느껴진다 (예전엔
    0.30~0.50으로 너무 눌러서 칙칙해 보였다 -- 화사하게 보이도록 상향).

    명도(L)도 밝은 배경 위 테두리/글자로 쓸 수 있는 중간 밝기 띠
    (0.40~0.60, 중심 0.50)로 누르되, (l - 0.5) 항으로 원래 밝기 순서를
    약하게나마 보존한다(예: 원래 더 밝았던 프로토콜이 파스텔 버전에서도
    상대적으로 더 밝게 남는다)."""
    r, g, b = rgb
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    s2 = 0.45 + 0.35 * min(s, 1.0)
    l2 = max(0.40, min(0.60, 0.50 + 0.09 * (l - 0.5)))
    return colorsys.hls_to_rgb(h, l2, s2)


def _rgb_css(rgb):
    r, g, b = rgb
    return f"rgb({int(r*255)},{int(g*255)},{int(b*255)})"


@app.route("/")
def index():
    proto_colors_dark = {p: _rgb_css(rgb) for p, rgb in Protocols.COLOR.items()}
    proto_colors_light = {p: _rgb_css(_pastel_variant(rgb)) for p, rgb in Protocols.COLOR.items()}
    proto_values = {p: list(v) for p, v in Protocols.VALUES.items()}
    return render_template("index.html", proto_colors_dark=proto_colors_dark,
                            proto_colors_light=proto_colors_light, proto_values=proto_values,
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
    return jsonify(_serialize_draft(entry))


@app.route("/api/draft/randomize/<draft_id>", methods=["POST"])
def draft_randomize(draft_id):
    """vs_ai 밴픽에서 'AI가 쓸 프로토콜을 무작위로 정하기' 버튼용.
    지금 남은 AI(플레이어2) 몫의 픽을 전부 무작위(티어 가중치)로 채운다.
    플레이어1의 몫에는 영향 없음 -- 지금 차례가 플레이어2일 때만 채워짐."""
    entry = DRAFTS.get(draft_id)
    if not entry:
        return jsonify({"error": "밴픽 세션을 찾을 수 없어요"}), 404
    with entry["lock"]:
        _auto_resolve_ai_draft(entry)
    return jsonify(_serialize_draft(entry))


@app.route("/api/new_game", methods=["POST"])
def new_game():
    data = request.get_json(force=True) or {}
    mode = data.get("mode", "hotseat")  # "hotseat" | "vs_ai"
    ai_side = data.get("aiSide", 2)
    # "random"(왕초보) | "heuristic"(초보) | "ismcts"(중급) |
    # "ismcts_mlp"(고급). 모르는 값이 오면 안전하게 랜덤.
    ai_difficulty = data.get("aiDifficulty", "random")
    first_player = data.get("firstPlayer", random.choice([1, 2]))

    protocols1 = data.get("draftedProtocols", {}).get("1")
    protocols2 = data.get("draftedProtocols", {}).get("2")
    if not protocols1 or not protocols2:
        protocols1, protocols2 = _pick_protocols()

    ai1 = mode == "vs_ai" and ai_side == 1
    ai2 = mode == "vs_ai" and ai_side == 2

    def make_ai_module():
        if ai_difficulty == "ismcts_mlp":
            return ISMCTSMLPAI()
        if ai_difficulty == "ismcts":
            return ISMCTSLearnedAI()
        if ai_difficulty == "heuristic":
            return HeuristicAI()
        return RandomAI()

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


@app.route("/api/tutorial/new", methods=["POST"])
def new_tutorial():
    """가이드 튜토리얼 챕터 하나를 스크립트된 보드 상태로 시작한다.
    chapter는 1-indexed (Script.chapters와 동일한 규칙)."""
    data = request.get_json(force=True) or {}
    idx = int(data.get("chapter", 1)) - 1
    if not (0 <= idx < len(TutorialScript.TUTORIAL_CHAPTERS)):
        return jsonify({"error": "존재하지 않는 챕터예요"}), 404
    ch = TutorialScript.TUTORIAL_CHAPTERS[idx]
    e = Engine(protocols1=ch["protocols1"], protocols2=ch["protocols2"],
               ai1=False, ai2=True, ai_modules={2: ch["ai_class"]()},
               first_player=1, decks=ch["decks"], on_dealt=ch["on_dealt"],
               auto_compile=False, auto_refresh=False, seed=1)
    game_id = uuid.uuid4().hex[:8]
    GAMES[game_id] = {"engine": e, "lock": threading.Lock()}
    e.start()
    return jsonify({"gameId": game_id, "state": _serialize(e), "chapter": idx + 1})


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
    # threaded=True: "ismcts" 난이도는 결정 1번에 1초 안팎 걸릴 수 있어서
    # (ai_train_pipeline.md Phase 3 실측), 단일 스레드로 두면 그동안 다른
    # 접속자의 요청까지 전부 막힌다. 게임별로 이미 lock을 쓰고 있어
    # 동시 접근 자체는 안전하다.
    app.run(debug=True, port=5000, threaded=True)
