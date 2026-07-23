"""컴파일 카드 180장의 효과 정의. 키는 "Proto_value" (예: "Water_0").

플레이어가 읽는 룰 텍스트는 i18n에 있음 -- 여기 있는 건 동작(behavior)만.
정의 딕셔너리(각 카드의 D["Proto_value"])는 다음 키를 가질 수 있다
(Lua 원본 키 이름 그대로 유지 -- carddefs.lua와 대조하기 쉽도록):
  play(g,c)        내는 순간의 명령 (앞면으로 뒤집힐 때도 재발동)
  start(g,c)       "Inicio:" 트리거 (소유자 턴 시작, uncovered일 때)
  finish(g,c)      "Fin:" 트리거 (소유자 턴 끝, uncovered일 때)
  onCovered(g,c)   "덮이기 직전" 트리거
  onCompileDelete(g,c)  컴파일로 제거될 때 (Speed_2)
  onFlipSelfDestruct    True => 뒤집히는 대신 스스로 삭제 (Metal_6)
  passive = {...}  uncovered 앞면인 동안 상시 적용되는 규칙
  reactive = {afterDraw/afterDelete/afterDiscard/afterCache = fn}
  can = {start/finish/startTop/finishTop = fn(g,c)->bool}  트리거 예측 함수

콜백 인자 개수 계약 (Lua는 초과 인자를 조용히 무시하지만 Python은 엄격하게
검사하므로, 실제로 안 쓰는 인자도 시그니처에 받아야 함 -- 안 쓰면 `*_`로):
  play / start / finish / onCompileDelete / can.*   : (g, c)            2개
  onCovered                                          : (g, c, incoming, incoming_face_up)  4개
  reactive.* / reactiveTop.*                         : (g, c, actor, ctx, s)               5개
  passive.lineValueSelf                              : (g, c, line)     3개

포팅 원본: carddefs.lua
"""

# ---------------------------------------------------------------------------
# 공용 헬퍼 (카드 180장 전체에서 재사용)
# ---------------------------------------------------------------------------

def _opp(c):
    """카드 c 소유자의 상대 플레이어 번호."""
    return 2 if c.owner == 1 else 1


def _line_of(g, c):
    """카드 c가 지금 있는 라인 번호."""
    _, line, _ = g.locate(c)
    return line


def _eff_val(c):
    """"최고/최저값" 비교에 쓰는 실효값 (뒷면이면 2로 취급)."""
    return c.value if c.face_up else 2


def _uncovered_only(g, filter_fn=None):
    """Compile의 기본 타겟팅 규칙: 명시적으로 "covered"/"all"이라 하지 않는 한
    UNCOVERED(top) 카드만 대상이 될 수 있다."""
    def check(x, pi, line):
        if not g.is_uncovered(x):
            return False
        if filter_fn and not filter_fn(x, pi, line):
            return False
        return True
    return check


def _delete_one(g, chooser, filter_fn=None, opts=None):
    """chooser가 filter에 맞는 uncovered 카드 하나를 골라 삭제."""
    cands = g.cards_in_play(_uncovered_only(g, filter_fn))
    card = g.choose_card_from(chooser, cands, opts)
    if card:
        g.delete_cards([card], None, None, chooser)
    return card


def _has_target(g, filter_fn=None):
    """filter에 맞는 uncovered 카드가 하나라도 있는가? (Start/End 트리거의
    can 예측 함수가 공유 -- 대상이 없으면 그 효과는 무의미하므로 트리거
    선택지에 노출되면 안 됨)."""
    return len(g.cards_in_play(_uncovered_only(g, filter_fn))) > 0


def _flip_one(g, chooser, filter_fn=None, opts=None):
    def combined(x, pi, line):
        if not g.can_flip(x):  # Ice_4는 뒤집을 수 없음
            return False
        if filter_fn and not filter_fn(x, pi, line):
            return False
        return True
    cands = g.cards_in_play(_uncovered_only(g, combined))
    card = g.choose_card_from(chooser, cands, opts)
    if card:
        g.flip_card(card)
    return card


def _return_one(g, chooser, filter_fn=None, opts=None):
    cands = g.cards_in_play(_uncovered_only(g, filter_fn))
    card = g.choose_card_from(chooser, cands, opts)
    if card:
        g.return_card(card)
    return card


def _move_one(g, chooser, filter_fn=None, opts=None):
    """카드를 소유자의 다른 라인으로 옮긴다 (chooser가 카드+목적지 라인을 고름)."""
    opts = opts or {}
    cands = g.cards_in_play(_uncovered_only(g, filter_fn))
    card = g.choose_card_from(chooser, cands, opts)
    if not card:
        return None
    _, line, _ = g.locate(card)
    dests = [l for l in (1, 2, 3) if l != line]
    dest = g.choose_line_from(chooser, dests,
                               {"prompt": "어느 라인으로 이동할까요", "intent": "move",
                                "target": card.owner})
    if dest:
        g.move_card(card, card.owner, dest)
    return card


def _highest(cards):
    best = None
    for c in cards:
        if best is None or _eff_val(c) > _eff_val(best):
            best = c
    return best


def _delete_highest_uncovered(g, chooser, target_owner, prompt):
    """"<owner>의 최고값 uncovered 카드 삭제" (Hate_2). 동점이면 효과의
    소유자(chooser)가 고른다 (반복 순서가 임의로 정하면 안 됨)."""
    pool = g.cards_in_play(lambda x, pi, line: x.owner == target_owner and g.is_uncovered(x))
    best = _highest(pool)
    if not best:
        return None
    tied = [x for x in pool if _eff_val(x) == _eff_val(best)]
    if len(tied) == 1:
        pick = tied[0]
    else:
        pick = g.choose_card_from(chooser, tied, {"prompt": prompt, "intent": "delete"})
    if pick:
        g.delete_cards([pick])
    return pick


def _give_card(g, from_pi, to_pi):
    """from_pi의 손 카드 하나를 to_pi에게 준다 (from_pi가 무엇을 줄지 고름)."""
    frm = g.players[from_pi]
    if not frm["hand"]:
        return False
    uids = [c.uid for c in frm["hand"]]
    pick = g.prompt({"type": "chooseCard", "chooser": from_pi, "candidates": uids,
                      "optional": False, "prompt": "상대에게 카드 1장을 주세요",
                      "fromHand": True, "intent": "give"})
    if not pick:
        return False
    for i, c in enumerate(frm["hand"]):
        if c.uid == pick:
            card = frm["hand"].pop(i)
            card.owner = to_pi  # 소유권도 카드와 함께 이전 (룰북)
            g.players[to_pi]["hand"].append(card)
            g.emit("give", {"i18n": {"key": "ev.give", "params": {"from": from_pi, "to": to_pi}}})
            return True
    return False


def _take_random(g, from_pi, to_pi):
    """from_pi의 손에서 무작위 카드 한 장을 to_pi의 손으로."""
    frm = g.players[from_pi]
    if not frm["hand"]:
        return False
    i = g.rng(len(frm["hand"]))  # 1..n
    card = frm["hand"].pop(i - 1)
    card.owner = to_pi
    g.players[to_pi]["hand"].append(card)
    g.emit("take", {"i18n": {"key": "ev.take", "params": {"to": to_pi, "from": from_pi}}})
    return True


def _ask(g, chooser, prompt, intent):
    """chooser에게 예/아니오를 묻는다. intent는 AI가 패턴매칭 없이 참조하는
    언어 독립적인 태그."""
    return bool(g.prompt({"type": "yesno", "chooser": chooser, "prompt": prompt, "intent": intent}))


def _extra_play(g, pi):
    """추가로 카드 1장을 낼 기회 (리프레시는 없음), pi에게."""
    acts = [a for a in g.legal_actions(pi) if a["kind"] == "play"]
    if not acts:
        return
    action = g.prompt({"type": "action", "chooser": pi, "player": pi,
                        "prompt": "카드 1장을 추가로 플레이하세요", "playOnly": True})
    if action and action.get("kind") == "play":
        g.play_card(pi, action["uid"], action["line"], action["faceUp"])


def _play_top_face_down_each(g, owner, eligible):
    """eligible 라인마다 덱 맨 위 카드를 뒷면으로 낸다 (Life_0, Smoke_0).
    ONE 명령: owner가 순서를 고른다. 덱이 부족하면 그 자체가 "어느 라인에
    줄지" 선택이 된다."""
    def body():
        # 라인 잠금은 effect에서 그 라인을 통째로 제외시킨다 (자격 판정 시점에
        # 스냅샷).
        remaining = _facedown_legal_lines(g, owner, eligible)
        if len(g.players[owner]["deck"]) < len(remaining):
            g.logmsg({"key": "ev.deckShortPlay", "params": {
                "p": owner, "n": len(g.players[owner]["deck"]), "lines": len(remaining)}})
        while g.players[owner]["deck"] and remaining:
            line = remaining[0]
            if len(remaining) > 1:
                if len(g.players[owner]["deck"]) < len(remaining):
                    opts = {
                        "prompt": "뒷면으로 플레이할 곳을 선택하세요 (라인 %{lines}개에 덱은 %{n}장뿐)",
                        "promptParams": {"n": len(g.players[owner]["deck"]), "lines": len(remaining)},
                        "intent": "play",
                    }
                else:
                    opts = {"prompt": "다음 카드를 뒷면으로 플레이할 곳을 선택하세요", "intent": "play"}
                line = g.choose_line_from(owner, remaining, opts)
                if not line:
                    break
            if not g.play_top_face_down(owner, line):
                break
            remaining.remove(line)
    g.command(body)


def _facedown_legal_lines(g, pi, lines):
    """`lines` 중 pi가 실제로 뒷면 카드를 낼 수 있는 곳만 (Metal_2/Plague_0 잠금 제외)."""
    return [l for l in lines if g.can_play_face_down(pi, None, l)[0]]


def _move_to_other_line(g, chooser, card, prompt=None):
    """card를 (같은 소유자의) 다른 라인으로 옮긴다; chooser가 목적지를 고름."""
    _, line, _ = g.locate(card)
    if not line:
        return None
    dests = [l for l in (1, 2, 3) if l != line]
    dest = g.choose_line_from(chooser, dests,
                               {"prompt": prompt or "어느 라인으로 이동할까요", "intent": "move",
                                "target": card.owner})
    if dest:
        g.move_card(card, card.owner, dest)
    return dest


def _discard_whole_hand(g, pi, opts=None):
    """pi의 손 전체를 버린다 (선택 없이 전부). 버린 장수를 반환."""
    p = g.players[pi]
    n = len(p["hand"])
    if n == 0:
        return 0
    uids = [hc.uid for hc in p["hand"]]
    g.discard_hand_by_uids(pi, uids, opts)
    return n


def _play_dests(g, pi, card, opts=None):
    """pi가 card를 낼 수 있는 라인별 합법적인 면(들). [{line, fu, fd}, ...] 반환.
    "카드 1장 내기" 계열 효과의 유일한 적법성 원천."""
    opts = opts or {}
    forced = g.forced_face_down_only(pi)
    out = []
    for l in (1, 2, 3):
        if not opts.get("lines") or opts["lines"].get(l):
            fu = False
            if (not opts.get("faceDownOnly") and not forced
                    and g.can_play_face_up(pi, card, l, opts.get("anyFaceUp"))[0]):
                fu = True
            fd = bool(g.can_play_face_down(pi, card, l)[0])
            if fu or fd:
                out.append({"line": l, "fu": fu, "fd": fd})
    return out


def _choose_line_and_face(g, pi, card, opts=None):
    """card를 낼 합법적인 라인+면을 고른다. (line, face_up) 또는 (None, None)."""
    opts = opts or {}
    dests = _play_dests(g, pi, card, opts)
    if not dests:
        return None, None
    lines = [d["line"] for d in dests]
    by_line = {d["line"]: d for d in dests}
    line = g.choose_line_from(pi, lines,
                               {"prompt": opts.get("linePrompt", "플레이할 라인을 선택하세요"),
                                "intent": "play"})
    if not line:
        return None, None
    d = by_line[line]
    if d["fu"] and d["fd"]:
        pick = g.choose_option_from(pi, ["up", "down"], {
            "prompt": "앞면으로 플레이할까요, 뒷면으로 플레이할까요?", "intent": "faceChoice",
            "labels": {"up": "앞면", "down": "뒷면"}})
        face_up = (pick == "up")
    else:
        face_up = bool(d["fu"])
    return line, face_up


def _play_specific_from_hand(g, pi, card, opts=None):
    line, face_up = _choose_line_and_face(g, pi, card, opts)
    if not line:
        return False
    return g.play_card(pi, card.uid, line, face_up)


def _play_from_hand(g, pi, filter_fn=None, opts=None):
    """"카드 1장 내기" 효과: filter에 맞는 손 카드를 고르고, playSpecificFromHand로
    라인+면까지 고른다."""
    opts = opts or {}
    cands = [hc for hc in g.players[pi]["hand"] if (not filter_fn or filter_fn(hc))]
    if not cands:
        return None
    dests = []
    for hc in cands:
        for d in _play_dests(g, pi, hc, opts):
            dests.append({"uid": hc.uid, "line": d["line"], "fu": d["fu"], "fd": d["fd"]})
    card = g.choose_card_from(pi, cands,
                               {"fromHand": True, "optional": opts.get("optional"),
                                "dests": dests or None,
                                "prompt": opts.get("prompt", "플레이할 카드를 선택하세요"),
                                "intent": "play"})
    if not card:
        return None
    _play_specific_from_hand(g, pi, card, opts)
    return card


def _distinct_protos_in_play(g):
    """보드 전체에서 앞면 카드들의 서로 다른 프로토콜 수 (Diversity의 집계 규칙)."""
    seen, n = set(), 0
    for pi in (1, 2):
        for line in (1, 2, 3):
            for x in g.players[pi]["stacks"][line]:
                if x.face_up and x.proto not in seen:
                    seen.add(x.proto)
                    n += 1
    return n


def _distinct_protos_in_line(g, line):
    seen, n = set(), 0
    for pi in (1, 2):
        for x in g.players[pi]["stacks"][line]:
            if x.face_up and x.proto not in seen:
                seen.add(x.proto)
                n += 1
    return n


def _proto_count_in_play(g, proto):
    """보드 위 특정 프로토콜의 앞면 카드 수 (Unity의 집계 규칙)."""
    n = 0
    for pi in (1, 2):
        for line in (1, 2, 3):
            for x in g.players[pi]["stacks"][line]:
                if x.face_up and x.proto == proto:
                    n += 1
    return n


def _reveal_hand_event(g, c):
    """"상대가 손을 공개한다": 공개된 카드 정체까지 담아 이벤트를 emit
    (공개 정보라 양쪽 로그에 다 보임)."""
    target = _opp(c)
    cards = [{"uid": hc.uid, "proto": hc.proto, "value": hc.value} for hc in g.players[target]["hand"]]
    g.emit("revealHand", {"player": target,
                           "i18n": {"key": "ev.revealHand", "params": {"p": target, "cards": cards}}})


def _swap_two(g, chooser, target_player):
    """target_player의 프로토콜 정확히 2개의 위치를 맞바꾼다 (Spirit_4)."""
    a = g.choose_line_from(chooser, [1, 2, 3],
                            {"prompt": "교환: 첫 번째 프로토콜", "intent": "rearrange",
                             "target": target_player})
    if not a:
        return
    rest = [l for l in (1, 2, 3) if l != a]
    b = g.choose_line_from(chooser, rest,
                            {"prompt": "교환할 대상", "intent": "rearrange",
                             "target": target_player})
    if b:
        g.swap_protocols(target_player, a, b)


def _rearrange(g, chooser, target_player):
    """target_player의 프로토콜을 chooser가 원하는 순서로 전체 재배열
    (Chaos_1/Water_2/Psychic_2 "상대/자신의 프로토콜을 재배열")."""
    order = g.choose_rearrange(chooser, target_player, {
        "prompt": ("자신의 프로토콜을 재배열하세요" if target_player == chooser
                   else "상대의 프로토콜을 재배열하세요")})
    g.rearrange_protocols(target_player, order)


# 모든 프로토콜의 값-5 카드는 "카드 1장을 버려라"라고 적혀 있다 -- 정의가
# 상태 없이 재사용 가능해서 전부 이 하나를 공유한다.
DISCARD_ONE_DEF = {"play": lambda g, c: g.discard(c.owner, 1)}


# proto_value ("Water_0" 등) -> 효과 정의 딕셔너리. 아래에서 프로토콜별로 채운다.
DEFS = {}


# =============================================================================
# WATER
# =============================================================================
def _water_0_play(g, c):
    _flip_one(g, c.owner, lambda x, pi, line: x.uid != c.uid, {"prompt": "다른 카드를 뒤집으세요"})
    g.flip_card(c)


def _water_1_play(g, c):
    self_line = _line_of(g, c)
    for line in (1, 2, 3):
        # 잠긴 라인(Metal_2/Plague_0)은 카드를 못 받지만 나머지는 정상 진행.
        if line != self_line and g.can_play_face_down(c.owner, None, line)[0]:
            g.play_top_face_down(c.owner, line)


def _water_2_play(g, c):
    g.draw(c.owner, 2)
    _rearrange(g, c.owner, c.owner)


def _water_3_play(g, c):
    line = g.choose_line_from(c.owner, [1, 2, 3], {"prompt": "라인을 선택하세요", "intent": "return"})
    if not line:
        return
    targets = []
    for pi in (1, 2):
        for x in g.players[pi]["stacks"][line]:
            if _eff_val(x) == 2:
                targets.append(x)
    for x in targets:
        g.return_card(x)


def _water_4_play(g, c):
    _return_one(g, c.owner, lambda x, pi, line: x.owner == c.owner,
                {"prompt": "자신의 카드 1장을 반환하세요"})


DEFS["Water_0"] = {"play": _water_0_play}
DEFS["Water_1"] = {"play": _water_1_play}
DEFS["Water_2"] = {"play": _water_2_play}
DEFS["Water_3"] = {"play": _water_3_play}
DEFS["Water_4"] = {"play": _water_4_play}
DEFS["Water_5"] = DISCARD_ONE_DEF


# =============================================================================
# LOVE
# =============================================================================
def _love_1_finish(g, c):
    if not g.players[c.owner]["hand"]:
        return
    if _ask(g, c.owner, "카드 1장을 상대에게 주고 2장을 뽑을까요?", "give"):
        if _give_card(g, c.owner, _opp(c)):
            g.draw(c.owner, 2)


def _love_2_play(g, c):
    g.draw(_opp(c), 1)
    g.refresh(c.owner)


def _love_3_play(g, c):
    _take_random(g, _opp(c), c.owner)
    if g.players[c.owner]["hand"]:
        _give_card(g, c.owner, _opp(c))


def _love_4_play(g, c):
    hand = g.players[c.owner]["hand"]
    if hand:
        cands = list(hand)
        card = g.choose_card_from(c.owner, cands,
                                   {"fromHand": True, "prompt": "손패에서 카드 1장을 공개하세요"}) or cands[0]
        g.emit("reveal", {"player": c.owner, "i18n": {"key": "ev.reveal", "params": {
            "p": c.owner, "card": {"uid": card.uid, "proto": card.proto, "value": card.value}}}})
    _flip_one(g, c.owner, None, {"prompt": "카드 1장을 뒤집으세요"})


DEFS["Love_1"] = {
    # 실제로 줄 카드가 있을 때만 End 트리거를 제시한다.
    "can": {"finish": lambda g, c: len(g.players[c.owner]["hand"]) > 0},
    "play": lambda g, c: g.draw_from_deck_of(_opp(c), c.owner),
    "finish": _love_1_finish,
}
DEFS["Love_2"] = {"play": _love_2_play}
DEFS["Love_3"] = {"play": _love_3_play}
DEFS["Love_4"] = {"play": _love_4_play}
DEFS["Love_5"] = DISCARD_ONE_DEF
DEFS["Love_6"] = {"play": lambda g, c: g.draw(_opp(c), 2)}


# =============================================================================
# APATHY
# =============================================================================
def _apathy_1_play(g, c):
    line = _line_of(g, c)
    # "이 라인의 다른 앞면 카드를 모두 뒤집는다": "이 라인의 전부" 효과라
    # COVERED 카드도 대상이 된다 -- top만이 아니라 스택 전체를 순회.
    targets = []
    for pi in (1, 2):
        for x in g.players[pi]["stacks"][line]:
            if x.face_up and x.uid != c.uid:
                targets.append(x)
    for x in targets:
        g.flip_card(x)


def _apathy_4_play(g, c):
    # 예외적으로 COVERED 카드를 명시적으로 대상으로 하되, 앞면인 것만.
    cands = g.cards_in_play(lambda x, pi, line: x.owner == c.owner and not g.is_uncovered(x) and x.face_up)
    card = g.choose_card_from(c.owner, cands,
                               {"optional": True, "prompt": "자신의 커버된 카드 1장을 앞면으로 뒤집으세요"})
    if card:
        g.flip_card(card)


DEFS["Apathy_0"] = {"passive": {"lineValueSelf": lambda g, c, line: g.facedown_in_line(line)}}
DEFS["Apathy_1"] = {"play": _apathy_1_play}
DEFS["Apathy_2"] = {"passive": {"ignoreMiddle": True}, "onCovered": lambda g, c, *_: g.flip_card(c)}
DEFS["Apathy_3"] = {"play": lambda g, c: _flip_one(
    g, c.owner, lambda x, pi, line: x.owner == _opp(c) and x.face_up,
    {"prompt": "상대의 앞면 카드 1장을 뒤집으세요"})}
DEFS["Apathy_4"] = {"play": _apathy_4_play}
DEFS["Apathy_5"] = DISCARD_ONE_DEF


# =============================================================================
# SPIRIT
# =============================================================================
def _spirit_0_play(g, c):
    g.refresh(c.owner)
    g.draw(c.owner, 1)


def _spirit_1_start(g, c):
    # "카드 1장을 버리거나 이 카드를 뒤집어라." 손이 비었으면 선택지가 없이
    # 무조건 뒤집는다. 아니면 둘 다 명시적으로 제시.
    pick = "flip"
    if g.players[c.owner]["hand"]:
        pick = g.choose_option_from(c.owner, ["discard", "flip"], {
            "prompt": "카드 1장을 버릴까요, 이 카드를 뒤집을까요?", "intent": "discardOrFlip",
            "labels": {"discard": "버리기", "flip": "뒤집기"}})
    if pick == "discard":
        g.discard(c.owner, 1)
    else:
        g.flip_card(c)


def _spirit_3_after_draw(g, c, actor, *_):
    if actor != c.owner:
        return
    if _ask(g, c.owner, "정신_3을 이동할까요?", "move"):
        _, line, _ = g.locate(c)
        dests = [l for l in (1, 2, 3) if l != line]
        dest = g.choose_line_from(c.owner, dests,
                                   {"prompt": "이동할 곳", "intent": "move", "target": c.owner})
        if dest:
            g.move_card(c, c.owner, dest)


DEFS["Spirit_0"] = {"passive": {"skipCache": True}, "play": _spirit_0_play}
DEFS["Spirit_1"] = {"passive": {"playAnywhere": True},
                     "play": lambda g, c: g.draw(c.owner, 2),
                     "start": _spirit_1_start}
DEFS["Spirit_2"] = {"play": lambda g, c: _flip_one(
    g, c.owner, None, {"optional": True, "prompt": "카드 1장을 뒤집을 수 있습니다"})}
DEFS["Spirit_3"] = {
    # TOP-band 지속 리액티브: "덮여 있어도 이 카드를 이동" 하려면 덮여 있을 때도
    # 발동해야 하므로 reactive(uncovered top만 스캔)가 아니라 reactiveTop.
    "reactiveTop": {"afterDraw": _spirit_3_after_draw},
}
DEFS["Spirit_4"] = {"play": lambda g, c: _swap_two(g, c.owner, c.owner)}
DEFS["Spirit_5"] = DISCARD_ONE_DEF


# =============================================================================
# FIRE
# =============================================================================
def _fire_0_play(g, c):
    _flip_one(g, c.owner, lambda x, pi, line: x.uid != c.uid, {"prompt": "다른 카드를 뒤집으세요"})
    g.draw(c.owner, 2)


def _fire_0_on_covered(g, c, *_):
    g.draw(c.owner, 1)
    _flip_one(g, c.owner, lambda x, pi, line: x.uid != c.uid, {"prompt": "다른 카드를 뒤집으세요"})


def _fire_1_play(g, c):
    if g.discard(c.owner, 1) > 0:
        _delete_one(g, c.owner, None, {"prompt": "카드 1장을 제거하세요"})


def _fire_2_play(g, c):
    if g.discard(c.owner, 1) > 0:
        _return_one(g, c.owner, None, {"prompt": "카드 1장을 반환하세요"})


def _fire_3_finish(g, c):
    if (g.players[c.owner]["hand"]
            and _ask(g, c.owner, "카드 1장을 버려서 카드 1장을 뒤집을까요?", "discardToFlip")):
        if g.discard(c.owner, 1) > 0:
            _flip_one(g, c.owner, None, {"prompt": "카드 1장을 뒤집으세요"})


def _fire_4_play(g, c):
    p = g.players[c.owner]
    # Plague_2와 마찬가지로: 손이 비어 있으면 0장 버리지만 그래도 n+1장을
    # 뽑는다 -- 즉 마지막 카드로 Fire_4를 내면 1장을 뽑는다.
    n = g.discard(c.owner, len(p["hand"]), {"min": 1, "prompt": "카드 1장 이상을 버리세요"})
    g.draw(c.owner, n + 1)


DEFS["Fire_0"] = {"play": _fire_0_play, "onCovered": _fire_0_on_covered}
DEFS["Fire_1"] = {"play": _fire_1_play}
DEFS["Fire_2"] = {"play": _fire_2_play}
DEFS["Fire_3"] = {"can": {"finish": lambda g, c: len(g.players[c.owner]["hand"]) > 0},
                   "finish": _fire_3_finish}
DEFS["Fire_4"] = {"play": _fire_4_play}
DEFS["Fire_5"] = DISCARD_ONE_DEF


# =============================================================================
# GRAVITY
# =============================================================================
def _gravity_0_play(g, c):
    line = _line_of(g, c)
    # 라인이 고정("이 라인")이라, 상대의 Metal_2/Plague_0로 잠겨 있으면 전체
    # 효과가 무산된다 -- 아무 카드도 낼 수 없음.
    if not g.can_play_face_down(c.owner, None, line)[0]:
        return
    # "이 라인의 카드 2장마다": Gravity_0 자기 자신도 이 라인의 카드로 셈에
    # 포함된다 (룰링). 카운트는 루프 시작 전에 한 번만 계산 -- 새로 낸
    # 카드는 세지 않음.
    count = len(g.players[1]["stacks"][line]) + len(g.players[2]["stacks"][line])
    # "이 카드 밑에": 뽑은 카드들은 방금 낸 Gravity_0(맨 위) 바로 밑으로
    # 슬라이드해 들어간다.
    for _ in range(count // 2):
        g.play_top_face_down(c.owner, line, c)


def _gravity_1_play(g, c):
    g.draw(c.owner, 2)
    line = _line_of(g, c)
    if not line:
        return
    # 이동은 반드시 이 라인과 관련 있어야 한다: 이 라인 밖으로 옮기거나,
    # 다른 곳에서 이 라인으로 옮기거나.
    cands = g.cards_in_play(lambda x, pi, l: g.is_uncovered(x))
    card = g.choose_card_from(c.owner, cands, {"prompt": "이 라인으로 또는 이 라인에서 카드 1장을 이동하세요"})
    if not card:
        return
    _, cl, _ = g.locate(card)
    if cl == line:
        dests = [l for l in (1, 2, 3) if l != line]
        dest = g.choose_line_from(c.owner, dests,
                                   {"prompt": "어느 라인으로 이동할까요", "intent": "move",
                                    "target": card.owner})
        if dest:
            g.move_card(card, card.owner, dest)
    else:
        g.move_card(card, card.owner, line)


def _gravity_2_play(g, c):
    line = _line_of(g, c)
    card = _flip_one(g, c.owner, lambda x, pi, l: x.uid != c.uid, {"prompt": "카드 1장을 뒤집으세요"})
    if card and line:
        g.move_card(card, card.owner, line)


def _gravity_4_play(g, c):
    line = _line_of(g, c)
    # "이 라인으로 이동": 이미 이 라인에 있는 카드는 이 라인으로 옮길 수 없다.
    cands = g.cards_in_play(
        lambda x, pi, xl: not x.face_up and x.uid != c.uid and xl != line and g.is_uncovered(x))
    card = g.choose_card_from(c.owner, cands, {"prompt": "뒷면 카드 1장을 이동하세요"})
    if card and line:
        g.move_card(card, card.owner, line)


def _gravity_6_play(g, c):
    line = _line_of(g, c)
    # 뒷면으로 내는 쪽은 상대이므로, 적용되는 잠금도 "상대를 겨냥한" 것
    # (c.owner 본인의 Metal_2/Plague_0가 이 라인을 막으면 효과 무산).
    if line and g.can_play_face_down(_opp(c), None, line)[0]:
        g.play_top_face_down(_opp(c), line)


DEFS["Gravity_0"] = {"play": _gravity_0_play}
DEFS["Gravity_1"] = {"play": _gravity_1_play}
DEFS["Gravity_2"] = {"play": _gravity_2_play}
DEFS["Gravity_4"] = {"play": _gravity_4_play}
DEFS["Gravity_5"] = DISCARD_ONE_DEF
DEFS["Gravity_6"] = {"play": _gravity_6_play}


# =============================================================================
# LIGHT
# =============================================================================
def _light_0_play(g, c):
    card = _flip_one(g, c.owner, None, {"prompt": "카드 1장을 뒤집으세요"})
    if card:
        g.draw(c.owner, card.value if card.face_up else 2)


def _light_2_play(g, c):
    g.draw(c.owner, 2)
    cands = g.cards_in_play(lambda x, pi, line: not x.face_up and g.is_uncovered(x))
    card = g.choose_card_from(c.owner, cands, {"optional": True, "prompt": "뒷면 카드 1장을 공개하세요"})
    if card:
        g.emit("reveal", {"uid": card.uid, "i18n": {"key": "ev.revealFacedown", "params": {
            "card": {"uid": card.uid, "proto": card.proto, "value": card.value}}}})
        # "그 카드를 옮기거나 뒤집을 수 있다" -- 거절(optional)도 정당한 선택.
        pick = g.choose_option_from(c.owner, ["flip", "move"], {
            "prompt": "그 카드를 뒤집을까요, 이동할까요?", "intent": "flipOrMove", "optional": True,
            "labels": {"flip": "뒤집기", "move": "이동"}})
        if pick == "flip":
            g.flip_card(card)
        elif pick == "move":
            _, line, _ = g.locate(card)
            dests = [l for l in (1, 2, 3) if l != line]
            dest = g.choose_line_from(c.owner, dests,
                                       {"prompt": "이동할 곳", "intent": "move", "target": card.owner})
            if dest:
                g.move_card(card, card.owner, dest)


def _light_3_play(g, c):
    line = _line_of(g, c)
    if not line:
        return
    dests = [l for l in (1, 2, 3) if l != line]
    dest = g.choose_line_from(c.owner, dests,
                               {"prompt": "어느 라인으로 이동할까요", "intent": "move", "target": c.owner})
    if not dest:
        return
    movers = []
    for pi in (1, 2):
        for x in g.players[pi]["stacks"][line]:
            if not x.face_up:
                movers.append(x)
    for x in movers:
        g.move_card(x, x.owner, dest)


DEFS["Light_0"] = {"play": _light_0_play}
DEFS["Light_1"] = {"finish": lambda g, c: g.draw(c.owner, 1)}
DEFS["Light_2"] = {"play": _light_2_play}
DEFS["Light_3"] = {"play": _light_3_play}
DEFS["Light_4"] = {"play": lambda g, c: _reveal_hand_event(g, c)}
DEFS["Light_5"] = DISCARD_ONE_DEF


# =============================================================================
# METAL
# =============================================================================
def _metal_1_play(g, c):
    g.draw(c.owner, 2)
    g.cant_compile[_opp(c)] = True
    g.emit("status", {"i18n": {"key": "ev.noCompile", "params": {"opp": _opp(c)}}})


def _metal_3_play(g, c):
    g.draw(c.owner, 1)
    line = _line_of(g, c)
    cands = []
    for l in (1, 2, 3):
        if l != line:
            n = len(g.players[1]["stacks"][l]) + len(g.players[2]["stacks"][l])
            if n >= 8:
                cands.append(l)
    if cands:
        pick = g.choose_line_from(c.owner, cands,
                                   {"prompt": "라인을 제거하세요 (8장 이상)", "intent": "delete"})
        if pick:
            to_del = []
            for pi in (1, 2):
                to_del.extend(g.players[pi]["stacks"][pick])
            g.delete_cards(to_del)


DEFS["Metal_0"] = {"passive": {"lineValueOppDelta": -2},
                    "play": lambda g, c: _flip_one(g, c.owner, None, {"prompt": "카드 1장을 뒤집으세요"})}
DEFS["Metal_1"] = {"play": _metal_1_play}
DEFS["Metal_2"] = {"passive": {"oppNoFacedownHere": True}}
DEFS["Metal_3"] = {"play": _metal_3_play}
DEFS["Metal_5"] = DISCARD_ONE_DEF
DEFS["Metal_6"] = {"onCovered": lambda g, c, *_: g.delete_card(c), "onFlipSelfDestruct": True}


# =============================================================================
# DEATH
# =============================================================================
def _death_0_play(g, c):
    self_line = _line_of(g, c)
    # "다른 각 라인에서 카드 1장씩 삭제" -- 순서와 어떤 카드일지는 소유자가
    # 고른다 (고정된 좌->우 순서가 아님). 아직 안 풀린 다른 라인들의 uncovered
    # top들을 모아서 고르게 하고, 고를 때마다 그 라인의 몫이 소진된다.
    pending = {line: True for line in (1, 2, 3) if line != self_line}

    def candidates():
        out = []
        for line in (1, 2, 3):
            if pending.get(line):
                for pi in (1, 2):
                    top = g.top_card(pi, line)
                    if top:
                        out.append(top)
        return out

    for _ in range(2):  # 정확히 "다른" 두 라인
        cands = candidates()
        if not cands:
            break  # 대상이 없는 라인은 그냥 기여가 없음
        card = g.choose_card_from(c.owner, cands,
                                   {"prompt": "다른 각 라인에서 카드 1장씩 제거하세요", "intent": "delete"})
        if not card:
            break
        _, cl, _ = g.locate(card)
        pending[cl] = False
        g.delete_cards([card])


def _death_1_start_top(g, c):
    if _ask(g, c.owner, "카드 1장을 뽑을까요? (그 후 다른 카드와 이 카드를 제거합니다)", "drawThenDelete"):
        g.draw(c.owner, 1)
        _delete_one(g, c.owner, lambda x, pi, line: x.uid != c.uid, {"prompt": "다른 카드를 제거하세요"})
        g.delete_card(c)


def _death_2_play(g, c):
    def targets(line):
        out = []
        for pi in (1, 2):
            for x in g.players[pi]["stacks"][line]:
                if _eff_val(x) in (1, 2):
                    out.append(x)
        return out
    # 대상이 하나라도 있는 라인만 고를 수 있다 (대상이 진짜 있는 곳을 두고
    # 아무것도 안 지우는 라인을 고를 순 없음); 어디에도 대상이 없으면 프롬프트
    # 없이 그냥 무산.
    lines = [l for l in (1, 2, 3) if targets(l)]
    line = g.choose_line_from(c.owner, lines, {"prompt": "라인을 선택하세요", "intent": "delete"})
    if not line:
        return
    g.delete_cards(targets(line))


DEFS["Death_0"] = {"play": _death_0_play}
DEFS["Death_1"] = {
    # ERRATA(2024/10): 이 Start는 TOP 명령이라, 이 카드가 덮여 있어도 발동한다
    # (startTop -- uncovered일 때만이 아님).
    "startTop": _death_1_start_top,
}
DEFS["Death_2"] = {"play": _death_2_play}
DEFS["Death_3"] = {"play": lambda g, c: _delete_one(
    g, c.owner, lambda x, pi, line: not x.face_up, {"prompt": "뒷면 카드 1장을 제거하세요"})}
DEFS["Death_4"] = {"play": lambda g, c: _delete_one(
    g, c.owner, lambda x, pi, line: x.face_up and (x.value == 0 or x.value == 1),
    {"prompt": "값이 0 또는 1인 카드를 제거하세요"})}
DEFS["Death_5"] = DISCARD_ONE_DEF


# =============================================================================
# HATE
# =============================================================================
def _hate_1_play(g, c):
    g.discard(c.owner, 3)
    _delete_one(g, c.owner, None, {"prompt": "카드 1장을 제거하세요"})
    _delete_one(g, c.owner, None, {"prompt": "카드 1장을 제거하세요"})


def _hate_2_play(g, c):
    mine = _delete_highest_uncovered(g, c.owner, c.owner,
                                      "동점: 제거할 자신의 최고값 카드를 선택하세요")
    # RULING: Hate_2가 자기 자신의 최고값 카드였다면 첫 절에서 스스로 삭제됨 --
    # 이제 자기 자신이 없으니 두 번째 절은 존재하지 않고 발동하지 않는다.
    if mine is c:
        return
    _delete_highest_uncovered(g, c.owner, _opp(c),
                               "동점: 제거할 상대의 최고값 카드를 선택하세요")


def _hate_4_on_covered(g, c, *_):
    # "이 라인의 covered 카드 중 최저값 삭제"는 양쪽 다 대상. 동점이면 효과의
    # 소유자가 고른다 (반복 순서가 임의로 정하면 안 됨).
    _, line, _ = g.locate(c)
    if not line:
        return
    pool = []
    for pi in (1, 2):
        st = g.players[pi]["stacks"][line]
        pool.extend(st[:-1])  # covered만 (맨 위 제외)
    lowest = None
    for x in pool:
        if lowest is None or _eff_val(x) < _eff_val(lowest):
            lowest = x
    if lowest is None:
        return
    tied = [x for x in pool if _eff_val(x) == _eff_val(lowest)]
    if len(tied) == 1:
        pick = tied[0]
    else:
        pick = g.choose_card_from(
            c.owner, tied,
            {"prompt": "동점: 제거할 최저값 커버된 카드를 선택하세요", "intent": "delete"})
    if pick:
        g.delete_cards([pick])


DEFS["Hate_0"] = {"play": lambda g, c: _delete_one(g, c.owner, None, {"prompt": "카드 1장을 제거하세요"})}
DEFS["Hate_1"] = {"play": _hate_1_play}
DEFS["Hate_2"] = {"play": _hate_2_play}
DEFS["Hate_3"] = {"reactiveTop": {"afterDelete": lambda g, c, actor, *_: (
    g.draw(c.owner, 1) if actor == c.owner else None)}}
DEFS["Hate_4"] = {"onCovered": _hate_4_on_covered}
DEFS["Hate_5"] = DISCARD_ONE_DEF


# =============================================================================
# DARKNESS
# =============================================================================
def _darkness_0_play(g, c):
    g.draw(c.owner, 3)
    cands = g.cards_in_play(lambda x, pi, line: x.owner == _opp(c) and not g.is_uncovered(x))
    card = g.choose_card_from(c.owner, cands,
                               {"optional": True, "prompt": "상대의 커버된 카드 1장을 이동하세요"})
    if card:
        _, line, _ = g.locate(card)
        dests = [l for l in (1, 2, 3) if l != line]
        dest = g.choose_line_from(c.owner, dests,
                                   {"prompt": "이동할 곳", "intent": "move", "target": card.owner})
        if dest:
            g.move_card(card, card.owner, dest)


def _darkness_1_play(g, c):
    card = _flip_one(g, c.owner, lambda x, pi, line: x.owner == _opp(c),
                      {"prompt": "상대의 카드 1장을 뒤집으세요"})
    if card and _ask(g, c.owner, "그 카드를 이동할까요?", "move"):
        _, line, _ = g.locate(card)
        dests = [l for l in (1, 2, 3) if l != line]
        dest = g.choose_line_from(c.owner, dests,
                                   {"prompt": "이동할 곳", "intent": "move", "target": card.owner})
        if dest:
            g.move_card(card, card.owner, dest)


def _darkness_2_play(g, c):
    line = _line_of(g, c)
    cands = g.cards_in_play(lambda x, pi, l: l == line and not g.is_uncovered(x))
    card = g.choose_card_from(c.owner, cands,
                               {"optional": True, "prompt": "이 라인의 커버된 카드 1장을 뒤집으세요"})
    if card:
        g.flip_card(card)


def _darkness_3_play(g, c):
    if not g.players[c.owner]["hand"]:
        return
    line = _line_of(g, c)
    dests = [l for l in (1, 2, 3) if l != line]
    dests = _facedown_legal_lines(g, c.owner, dests)
    if not dests:
        return  # 다른 두 라인 다 잠겨 있으면 제시할 게 없음
    dest = g.choose_line_from(c.owner, dests, {"prompt": "뒷면으로 플레이할 곳", "intent": "play"})
    if not dest:
        return
    uids, card_dests = [], []
    for x in g.players[c.owner]["hand"]:
        uids.append(x.uid)
        # 목적지는 이미 고정(뒷면으로 dest에)됐지만, UI가 여전히 드래그 플레이로
        # 보여줄 수 있도록 req.dests에 담아준다.
        card_dests.append({"uid": x.uid, "line": dest, "fu": False, "fd": True})
    pick = g.prompt({"type": "chooseCard", "chooser": c.owner, "candidates": uids,
                      "fromHand": True, "dests": card_dests,
                      "prompt": "뒷면으로 플레이할 카드를 선택하세요"})
    if pick:
        g.play_card(c.owner, pick, dest, False)


DEFS["Darkness_0"] = {"play": _darkness_0_play}
DEFS["Darkness_1"] = {"play": _darkness_1_play}
DEFS["Darkness_2"] = {"passive": {"facedownValueThisStack": 4}, "play": _darkness_2_play}
DEFS["Darkness_3"] = {"play": _darkness_3_play}
DEFS["Darkness_4"] = {"play": lambda g, c: _move_one(
    g, c.owner, lambda x, pi, line: not x.face_up, {"prompt": "뒷면 카드 1장을 이동하세요"})}
DEFS["Darkness_5"] = DISCARD_ONE_DEF


# =============================================================================
# PLAGUE
# =============================================================================
def _plague_2_play(g, c):
    p = g.players[c.owner]
    # 손이 비어 있으면 0장 버리지만, 상대는 그래도 n+1장을 버린다 -- 즉 마지막
    # 카드로 Plague_2를 내면 상대가 1장 버림.
    n = g.discard(c.owner, len(p["hand"]), {"min": 1, "prompt": "카드 1장 이상을 버리세요"})
    g.discard(_opp(c), n + 1)


def _plague_3_play(g, c):
    # "다른 각 앞면 카드"는 uncovered 앞면 카드만 대상.
    targets = g.cards_in_play(lambda x, pi, line: x.face_up and x.uid != c.uid and g.is_uncovered(x))
    for x in targets:
        g.flip_card(x)


def _plague_4_finish(g, c):
    # Middle 명령 없음: 효과 전체가 End 트리거다, 순서대로 -- 상대가 자기
    # 뒷면 카드 하나를 삭제하고, 그다음 소유자가 이 카드를 뒤집을 수 있다.
    _delete_one(g, _opp(c), lambda x, pi, line: x.owner == _opp(c) and not x.face_up,
                {"prompt": "자신의 뒷면 카드 1장을 제거하세요"})
    if _ask(g, c.owner, "이 카드를 뒤집을까요 (역병_4)?", "flip"):
        g.flip_card(c)


DEFS["Plague_0"] = {"passive": {"oppNoPlayHere": True}, "play": lambda g, c: g.discard(_opp(c), 1)}
DEFS["Plague_1"] = {
    # TOP-band 지속 리액티브 (카드 아트도 top band) -- 덮여 있어도 계속 감시.
    "reactiveTop": {"afterDiscard": lambda g, c, actor, *_: (
        g.draw(c.owner, 1) if actor != c.owner else None)},
    "play": lambda g, c: g.discard(_opp(c), 1),
}
DEFS["Plague_2"] = {"play": _plague_2_play}
DEFS["Plague_3"] = {"play": _plague_3_play}
DEFS["Plague_4"] = {"finish": _plague_4_finish}
DEFS["Plague_5"] = DISCARD_ONE_DEF


# =============================================================================
# PSYCHIC
# =============================================================================
def _psychic_0_play(g, c):
    g.draw(c.owner, 2)
    g.discard(_opp(c), 2)
    _reveal_hand_event(g, c)


def _psychic_2_play(g, c):
    g.discard(_opp(c), 2)
    _rearrange(g, c.owner, _opp(c))


def _psychic_3_play(g, c):
    g.discard(_opp(c), 1)
    _move_one(g, c.owner, lambda x, pi, line: x.owner == _opp(c),
              {"optional": True, "prompt": "상대의 카드 1장을 이동하세요"})


def _psychic_4_finish(g, c):
    card = _return_one(g, c.owner, lambda x, pi, line: x.owner == _opp(c),
                        {"optional": True, "prompt": "상대의 카드 1장을 반환하세요"})
    if card:
        g.flip_card(c)


DEFS["Psychic_0"] = {"play": _psychic_0_play}
DEFS["Psychic_1"] = {"passive": {"oppOnlyFacedown": True}, "start": lambda g, c: g.flip_card(c)}
DEFS["Psychic_2"] = {"play": _psychic_2_play}
DEFS["Psychic_3"] = {"play": _psychic_3_play}
DEFS["Psychic_4"] = {
    # 상대 카드를 실제로 돌려줬을 때만 자기 자신을 뒤집는다. 돌려줄 uncovered
    # 상대 카드가 없으면 완전한 무산.
    "can": {"finish": lambda g, c: _has_target(g, lambda x, pi, line: x.owner == _opp(c))},
    "finish": _psychic_4_finish,
}
DEFS["Psychic_5"] = DISCARD_ONE_DEF


# =============================================================================
# SPEED
# =============================================================================
def _speed_2_on_compile_delete(g, c, *_):
    _, line, _ = g.locate(c)
    dests = [l for l in (1, 2, 3) if l != line]
    dest = g.choose_line_from(c.owner, dests,
                               {"prompt": "이 카드를 다른 라인으로 이동하세요", "intent": "move",
                                "target": c.owner})
    if dest:
        g.move_card(c, c.owner, dest)


def _speed_3_play(g, c):
    # "다른 네 카드 중 1장을 움직여라"는 "Puedes"가 없다 -> 대상이 있으면 필수.
    _move_one(g, c.owner, lambda x, pi, line: x.owner == c.owner and x.uid != c.uid,
              {"prompt": "자신의 다른 카드 1장을 이동하세요"})


def _speed_3_finish(g, c):
    # End 트리거는 선택이고, "다른"이 없다: Speed_3 자기 자신도 합법적 대상
    # (자기 자신을 다른 라인으로 옮긴 뒤 거기서 뒤집기).
    moved = _move_one(g, c.owner, lambda x, pi, line: x.owner == c.owner,
                       {"optional": True, "prompt": "자신의 카드 1장을 이동하세요"})
    # "그렇게 했다면, 이 카드를 뒤집어라." 만약 그 이동이 Speed_3 자신을 덮었다면
    # (자기 스택 위로 옮겨서) 일반 중단 규칙이 뒤집기를 무효화한다: flipCard가
    # Speed_3가 더 이상 uncovered top이 아니므로 아무 일도 안 함.
    if moved:
        g.flip_card(c)


DEFS["Speed_0"] = {"play": lambda g, c: _extra_play(g, c.owner)}
DEFS["Speed_1"] = {
    "reactiveTop": {"afterCache": lambda g, c, actor, *_: (
        g.draw(c.owner, 1) if actor == c.owner else None)},
    "play": lambda g, c: g.draw(c.owner, 2),
}
DEFS["Speed_2"] = {"onCompileDelete": _speed_2_on_compile_delete}
DEFS["Speed_3"] = {
    "play": _speed_3_play,
    "can": {"finish": lambda g, c: _has_target(g, lambda x, pi, line: x.owner == c.owner)},
    "finish": _speed_3_finish,
}
DEFS["Speed_4"] = {"play": lambda g, c: _move_one(
    g, c.owner, lambda x, pi, line: x.owner == _opp(c) and not x.face_up,
    {"prompt": "상대의 뒷면 카드 1장을 이동하세요"})}
DEFS["Speed_5"] = DISCARD_ONE_DEF


# =============================================================================
# LIFE
# =============================================================================
def _life_0_play(g, c):
    # "네가 카드를 가진 각 라인에서" -- Life_0 자신의 라인도 포함(자기 자신을
    # 덮는 것도 루프를 끊으면 안 됨; playTopFaceDownEach 참고).
    eligible = [line for line in (1, 2, 3) if g.players[c.owner]["stacks"][line]]
    _play_top_face_down_each(g, c.owner, eligible)


def _life_0_finish_top(g, c):
    if not g.is_uncovered(c):
        g.delete_card(c)


def _life_1_play(g, c):
    _flip_one(g, c.owner, None, {"prompt": "카드 1장을 뒤집으세요"})
    _flip_one(g, c.owner, None, {"prompt": "카드 1장을 뒤집으세요"})


def _life_2_play(g, c):
    g.draw(c.owner, 1)
    _flip_one(g, c.owner, lambda x, pi, line: not x.face_up,
              {"optional": True, "prompt": "뒷면 카드 1장을 뒤집으세요"})


def _life_3_on_covered(g, c, *_):
    _, line, _ = g.locate(c)
    dests = [l for l in (1, 2, 3) if l != line]
    dests = _facedown_legal_lines(g, c.owner, dests)
    if not dests:
        return  # 다른 두 라인 다 잠겨 있으면 트리거 자체가 무산
    # 필수: 선택을 취소해도 결국 낸다 -- 그래서 폴백도 반드시 합법이어야 함.
    dest = g.choose_line_from(c.owner, dests, {"prompt": "뒷면으로 플레이할 곳", "intent": "play"}) or dests[0]
    if dest:
        g.play_top_face_down(c.owner, dest)


def _life_4_play(g, c):
    # "이 카드가 다른 카드를 덮고 있다면"은 명령이 resolve되는 시점에 판정한다
    # -- Middle은 play/flip-up/uncover 시 resolve되므로, play 시점에 값을
    # 고정해버리면 안 됨(나중에 옮겨져 카드 위에 놓인 뒤 뒤집히는 경우를 놓침).
    pi, _, idx = g.locate(c)
    if pi is not None and idx > 0:
        g.draw(c.owner, 1)


DEFS["Life_0"] = {
    "play": _life_0_play,
    # ERRATA(2024/10): 이제 End(top) 명령이다 ("덮이면"이 아니라) -- 턴 끝에
    # 이 카드가 covered 상태면 삭제. top 명령이라 finishTop은 covered에서도 발동.
    "can": {"finishTop": lambda g, c: not g.is_uncovered(c)},
    "finishTop": _life_0_finish_top,
}
DEFS["Life_1"] = {"play": _life_1_play}
DEFS["Life_2"] = {"play": _life_2_play}
DEFS["Life_3"] = {"onCovered": _life_3_on_covered}
DEFS["Life_4"] = {"play": _life_4_play}
DEFS["Life_5"] = DISCARD_ONE_DEF


# =============================================================================
# CHAOS (Main 2)
# =============================================================================
def _chaos_0_play(g, c):
    # CLARIFICATION: 각 라인에서 뒤집을 covered 카드를 먼저 다 고른 다음, 골라둔
    # 카드들을 한 장씩 뒤집는다. (그 사이 다른 효과로 이미 뒤집힌 카드라도 여기서
    # 다시 뒤집힌다; covered 카드는 뒤집혀도 Middle 명령이 안 뜨는 건 엔진의
    # flipCard가 이미 처리.)
    chosen = []
    for line in (1, 2, 3):
        cands = g.cards_in_play(lambda x, pi, l, line=line: l == line and not g.is_uncovered(x))
        card = g.choose_card_from(c.owner, cands,
                                   {"prompt": "이 라인의 커버된 카드 1장을 뒤집으세요", "intent": "flip"})
        if card:
            chosen.append(card)
    for card in chosen:
        if g.locate(card)[0] is not None:
            g.flip_card(card)


def _chaos_0_start(g, c):
    g.draw_from_deck_of(_opp(c), c.owner)
    g.draw_from_deck_of(c.owner, _opp(c))


def _chaos_1_play(g, c):
    _rearrange(g, c.owner, c.owner)
    _rearrange(g, c.owner, _opp(c))


def _chaos_2_play(g, c):
    cands = g.cards_in_play(lambda x, pi, line: x.owner == c.owner and not g.is_uncovered(x))
    card = g.choose_card_from(c.owner, cands,
                               {"prompt": "자신의 커버된 카드 1장을 이동하세요", "intent": "move"})
    if card:
        _move_to_other_line(g, c.owner, card)


def _chaos_4_finish(g, c):
    n = _discard_whole_hand(g, c.owner)
    if n > 0:
        g.draw(c.owner, n)


DEFS["Chaos_0"] = {"play": _chaos_0_play, "start": _chaos_0_start}
DEFS["Chaos_1"] = {"play": _chaos_1_play}
DEFS["Chaos_2"] = {"play": _chaos_2_play}
DEFS["Chaos_3"] = {"freePlay": True}
DEFS["Chaos_4"] = {"can": {"finish": lambda g, c: len(g.players[c.owner]["hand"]) > 0},
                    "finish": _chaos_4_finish}
DEFS["Chaos_5"] = DISCARD_ONE_DEF


# =============================================================================
# CLARITY (Main 2)
# =============================================================================
def _clarity_1_start_top(g, c):
    p = g.players[c.owner]
    top = p["deck"][-1] if p["deck"] else None
    if not top:
        return
    # 지금, 버릴지 결정하는 프롬프트보다 먼저 공개한다 -- 소유자가 결정하는 동안
    # 실제로 덱 위의 카드를 앞면으로 볼 수 있도록. 드로우/밀/플레이/커버/셔플로
    # top이 바뀌기 전까진 계속 공개 상태.
    g.set_revealed_top(c.owner, top)
    if _ask(g, c.owner, "공개된 카드를 버릴까요?", "discardTopDeck"):
        g.mill_top(c.owner)


DEFS["Clarity_0"] = {"passive": {"lineValueSelf": lambda g, c, line: len(g.players[c.owner]["hand"])}}
DEFS["Clarity_1"] = {
    # 빈 덱은 아무것도 안 보여준다: 공개는 드로우가 아니므로 절대 버림더미를
    # 리셔플하면 안 됨 (룰북: 드로우만 리셔플함 -- pop_deck 참고).
    "can": {"startTop": lambda g, c: len(g.players[c.owner]["deck"]) > 0},
    "startTop": _clarity_1_start_top,
    "play": lambda g, c: _reveal_hand_event(g, c),
    "onCovered": lambda g, c, *_: g.draw(c.owner, 3),
}


def _clarity_fish(g, c, value):
    """Clarity_2/3: 소유자가 자기 덱에서 특정 값의 카드를 낚아온다. 공개도
    셔플도 없음 -- 소유자에게만 사적으로 후보를 보여준다."""
    if g.draw_blocked(c.owner):
        return
    cands = [x for x in g.players[c.owner]["deck"] if x.value == value]
    # 정규 순서(생성 uid), 덱 순서 아님 -- 소유자가 보는 목록이 덱 안 위치를
    # 흘리면 안 됨.
    cands.sort(key=lambda x: x.uid)
    card = g.choose_card_from(
        c.owner, cands,
        {"showcase": True,
         "prompt": ("덱에서 값이 1인 카드 1장을 뽑으세요" if value == 1
                    else "덱에서 값이 5인 카드 1장을 뽑으세요")})
    if card:
        g.take_from_deck_to_hand(c.owner, card)


def _clarity_2_play(g, c):
    _clarity_fish(g, c, 1)
    _play_from_hand(g, c.owner, lambda x: x.value == 1, {"prompt": "값이 1인 카드 1장을 플레이하세요"})


def _clarity_4_play(g, c):
    if not g.players[c.owner]["discard"]:
        return
    if _ask(g, c.owner, "버림더미를 덱에 섞을까요?", "shuffleTrash"):
        g.reshuffle_discard_into_deck(c.owner)


DEFS["Clarity_2"] = {"play": _clarity_2_play}
DEFS["Clarity_3"] = {"play": lambda g, c: _clarity_fish(g, c, 5)}
DEFS["Clarity_4"] = {"play": _clarity_4_play}
DEFS["Clarity_5"] = DISCARD_ONE_DEF


# =============================================================================
# CORRUPTION (Main 2)
# =============================================================================
def _corruption_0_can_start_top(g, c):
    pi, line, _ = g.locate(c)
    if pi is None:
        return False
    for x in g.players[pi]["stacks"][line]:
        if x is not c and x.face_up and x.owner == c.owner and g.can_flip(x):
            return True
    return False


def _corruption_0_start_top(g, c):
    pi, line, _ = g.locate(c)
    if pi is None:
        return
    cands = [x for x in g.players[pi]["stacks"][line]
             if x is not c and x.face_up and x.owner == c.owner and g.can_flip(x)]
    card = g.choose_card_from(
        c.owner, cands,
        {"prompt": "이 더미의 다른 앞면 카드 1장을 뒤집으세요", "intent": "flip"})
    if card:
        g.flip_card(card)


def _corruption_2_play(g, c):
    g.draw(c.owner, 1)
    g.discard(c.owner, 1)


def _corruption_3_play(g, c):
    cands = g.cards_in_play(lambda x, pi, line: x.face_up and not g.is_uncovered(x))
    card = g.choose_card_from(c.owner, cands,
                               {"optional": True, "prompt": "커버된 앞면 카드 1장을 뒤집으세요",
                                "intent": "flip"})
    if card:
        g.flip_card(card)


def _corruption_6_finish_top(g, c):
    # "카드 1장을 버리거나 이 카드를 삭제하라." 손이 비었으면 강제로 삭제.
    pick = "delete"
    if g.players[c.owner]["hand"]:
        pick = g.choose_option_from(c.owner, ["discard", "delete"], {
            "prompt": "카드 1장을 버릴까요, 이 카드를 제거할까요?", "intent": "discardOrDelete",
            "labels": {"discard": "버리기", "delete": "제거"}})
    if pick == "discard":
        g.discard(c.owner, 1)
    else:
        g.delete_card(c)


DEFS["Corruption_0"] = {
    # 프로토콜 상관없이 어느 라인에나, 어느 편에나 낼 수 있다; 카드는 착지한
    # 편이 통제한다 -- 적 편에 놓으면 Start가 그들의 스택을 오염시킨다.
    "freePlay": True, "playAnySide": True,
    "can": {"startTop": _corruption_0_can_start_top},
    "startTop": _corruption_0_start_top,
}
DEFS["Corruption_1"] = {"returnToDeck": True,
                         "play": lambda g, c: _return_one(g, c.owner, None, {"prompt": "카드 1장을 반환하세요"})}
DEFS["Corruption_2"] = {
    "reactiveTop": {"afterDiscard": lambda g, c, actor, *_: (
        g.discard(_opp(c), 1) if actor == c.owner else None)},
    "play": _corruption_2_play,
}
DEFS["Corruption_3"] = {"play": _corruption_3_play}
DEFS["Corruption_5"] = DISCARD_ONE_DEF
DEFS["Corruption_6"] = {"finishTop": _corruption_6_finish_top}


# =============================================================================
# COURAGE (Main 2)
# =============================================================================
def _courage_0_start_top(g, c):
    if not g.players[c.owner]["hand"]:
        g.draw(c.owner, 1)


def _courage_0_finish(g, c):
    if (g.players[c.owner]["hand"]
            and _ask(g, c.owner, "카드 1장을 버려 상대도 1장을 버리게 할까요?",
                      "discardToOppDiscard")):
        if g.discard(c.owner, 1) > 0:
            g.discard(_opp(c), 1)


def _courage_1_play(g, c):
    o = _opp(c)
    cands = g.cards_in_play(_uncovered_only(
        g, lambda x, pi, line: x.owner == o and g.line_value(o, line) > g.line_value(c.owner, line)))
    card = g.choose_card_from(
        c.owner, cands,
        {"prompt": "상대가 이기고 있는 라인에서 상대 카드 1장을 제거하세요", "intent": "delete"})
    if card:
        g.delete_cards([card])


def _courage_2_can_finish(g, c):
    _, line, _ = g.locate(c)
    return line is not None and g.line_value(_opp(c), line) > g.line_value(c.owner, line)


def _courage_2_finish(g, c):
    _, line, _ = g.locate(c)
    if line and g.line_value(_opp(c), line) > g.line_value(c.owner, line):
        g.draw(c.owner, 1)


def _courage_3_best_opp_line(g, c):
    o = _opp(c)
    best, best_v = None, None
    for l in (1, 2, 3):
        v = g.line_value(o, l)
        if best_v is None or v > best_v:
            best_v, best = v, l
    return best


def _courage_3_can_finish(g, c):
    best = _courage_3_best_opp_line(g, c)
    _, line, _ = g.locate(c)
    return best is not None and line is not None and best != line


def _courage_3_finish(g, c):
    best = _courage_3_best_opp_line(g, c)
    _, line, _ = g.locate(c)
    if not best or best == line:
        return
    if _ask(g, c.owner, "이 카드를 상대의 최고값 라인으로 이동할까요?", "move"):
        g.move_card(c, c.owner, best)


def _courage_6_can_finish_top(g, c):
    _, line, _ = g.locate(c)
    return line is not None and g.line_value(_opp(c), line) > g.line_value(c.owner, line)


def _courage_6_finish_top(g, c):
    _, line, _ = g.locate(c)
    if line and g.line_value(_opp(c), line) > g.line_value(c.owner, line):
        g.flip_card(c)


DEFS["Courage_0"] = {
    # Start는 손이 비었을 때만 드로우; End는 버릴 카드가 있어야 함.
    "can": {"startTop": lambda g, c: len(g.players[c.owner]["hand"]) == 0,
            "finish": lambda g, c: len(g.players[c.owner]["hand"]) > 0},
    "startTop": _courage_0_start_top,
    "play": lambda g, c: g.draw(c.owner, 1),
    "finish": _courage_0_finish,
}
DEFS["Courage_1"] = {"play": _courage_1_play}
DEFS["Courage_2"] = {"can": {"finish": _courage_2_can_finish},
                      "play": lambda g, c: g.draw(c.owner, 1),
                      "finish": _courage_2_finish}
DEFS["Courage_3"] = {"can": {"finish": _courage_3_can_finish}, "finish": _courage_3_finish}
DEFS["Courage_5"] = DISCARD_ONE_DEF
DEFS["Courage_6"] = {"can": {"finishTop": _courage_6_can_finish_top}, "finishTop": _courage_6_finish_top}


# =============================================================================
# FEAR (Main 2)
# =============================================================================
def _fear_0_play(g, c):
    pick = g.choose_option_from(c.owner, ["shift", "flip"], {
        "prompt": "카드 1장을 이동할까요, 뒤집을까요?", "intent": "shiftOrFlip",
        "labels": {"shift": "이동", "flip": "뒤집기"}})
    if pick == "shift":
        _move_one(g, c.owner, None, {"prompt": "카드 1장을 이동하세요"})
    elif pick == "flip":
        _flip_one(g, c.owner, None, {"prompt": "카드 1장을 뒤집으세요"})


def _fear_1_play(g, c):
    g.draw(c.owner, 2)
    n = _discard_whole_hand(g, _opp(c))
    if n > 1:
        g.draw(_opp(c), n - 1)


def _fear_3_play(g, c):
    line = _line_of(g, c)
    cands = g.cards_in_play(lambda x, pi, l: x.owner == _opp(c) and l == line)
    card = g.choose_card_from(c.owner, cands,
                               {"prompt": "이 라인에 있는 상대 카드 1장을 이동하세요", "intent": "move"})
    if card:
        _move_to_other_line(g, c.owner, card)


def _fear_4_play(g, c):
    o = g.players[_opp(c)]
    if not o["hand"]:
        return
    i = g.rng(len(o["hand"]))  # 1..n
    g.discard_hand_by_uids(_opp(c), [o["hand"][i - 1].uid])


DEFS["Fear_0"] = {"passive": {"oppNoMiddle": True}, "play": _fear_0_play}
DEFS["Fear_1"] = {"play": _fear_1_play}
DEFS["Fear_2"] = {"play": lambda g, c: _return_one(
    g, c.owner, lambda x, pi, line: x.owner == _opp(c), {"prompt": "상대의 카드 1장을 반환하세요"})}
DEFS["Fear_3"] = {"play": _fear_3_play}
DEFS["Fear_4"] = {"play": _fear_4_play}
DEFS["Fear_5"] = DISCARD_ONE_DEF


# =============================================================================
# ICE (Main 2)
# =============================================================================
def _ice_1_play(g, c):
    if _ask(g, c.owner, "이 카드를 이동할까요?", "move"):
        _move_to_other_line(g, c.owner, c)


def _ice_1_reactive_after_play(g, c, actor, ctx, snap):
    # "이 라인"은 Ice_1이 낼 당시 있었던 라인(엔진의 afterPlay 스냅샷으로
    # 고정) -- 낸 카드의 middle이 resolve되는 동안 uncovered되거나 이 라인으로
    # 옮겨져도 소급 적용해서 버리게 하면 안 됨.
    if actor != c.owner and ctx and snap and ctx.get("line") == snap.get("line"):
        g.discard(actor, 1)


def _ice_3_finish_top(g, c):
    if g.is_uncovered(c):
        return
    if _ask(g, c.owner, "이 카드를 이동할까요?", "move"):
        _move_to_other_line(g, c.owner, c)


DEFS["Ice_1"] = {"play": _ice_1_play, "reactive": {"afterPlay": _ice_1_reactive_after_play}}
DEFS["Ice_2"] = {"play": lambda g, c: _move_one(
    g, c.owner, lambda x, pi, line: x.uid != c.uid, {"prompt": "다른 카드 1장을 이동하세요"})}
DEFS["Ice_3"] = {
    # covered 카드만 이동 가능; uncovered면 아무 일도 안 함.
    "can": {"finishTop": lambda g, c: not g.is_uncovered(c)},
    "finishTop": _ice_3_finish_top,
}
DEFS["Ice_4"] = {"cantFlip": True}
DEFS["Ice_5"] = DISCARD_ONE_DEF
DEFS["Ice_6"] = {"passive": {"noDrawIfHand": True}}


# =============================================================================
# LUCK (Main 2)
# =============================================================================
def _luck_0_play(g, c):
    stated = g.choose_option_from(c.owner, [0, 1, 2, 3, 4, 5, 6],
                                   {"kind": "number", "prompt": "숫자를 말하세요", "intent": "stateNumber"})
    if stated is None:
        stated = 2
    g.emit("state", {"i18n": {"key": "ev.stateNumber", "params": {"p": c.owner, "n": stated}}})
    p = g.players[c.owner]
    before = len(p["hand"])
    g.draw(c.owner, 3)
    matches = [h for h in p["hand"][before:] if h.value == stated]
    if not matches:
        return
    card = g.choose_card_from(c.owner, matches,
                               {"fromHand": True, "prompt": "그 값을 가진 뽑은 카드 1장을 공개하세요"}) or matches[0]
    g.emit("reveal", {"player": c.owner, "i18n": {"key": "ev.reveal", "params": {
        "p": c.owner, "card": {"uid": card.uid, "proto": card.proto, "value": card.value}}}})
    if _ask(g, c.owner, "공개된 카드를 플레이할까요?", "playRevealed"):
        _play_specific_from_hand(g, c.owner, card)


def _luck_1_play(g, c):
    # "덱 맨 위 카드를 뒷면으로 낸다" -- 어느 라인이든, 잠금 제외: 낼 때는
    # 뒷면(Metal_2 적용)이고 곧바로 뒤집힐 뿐.
    dests = _facedown_legal_lines(g, c.owner, [1, 2, 3])
    if not dests:
        return
    dest = g.choose_line_from(c.owner, dests, {"prompt": "뒷면으로 플레이할 곳", "intent": "play"})
    if not dest:
        return
    card = g.play_top_face_down(c.owner, dest)
    if card:
        g.flip_card(card, {"noMiddle": True})


def _luck_2_play(g, c):
    m = g.mill_top(c.owner)
    if m and m.value > 0:
        g.draw(c.owner, m.value)


def _luck_3_play(g, c):
    o = _opp(c)
    protos = [g.players[o]["protocols"][l] for l in (1, 2, 3)]
    stated = g.choose_option_from(c.owner, protos,
                                   {"kind": "protocol", "prompt": "프로토콜을 말하세요",
                                    "intent": "stateProtocol"}) or protos[0]
    g.emit("state", {"i18n": {"key": "ev.stateProtocol", "params": {"p": c.owner, "proto": stated}}})
    m = g.mill_top(o)
    if m and m.proto == stated:
        _delete_one(g, c.owner, None, {"prompt": "카드 1장을 제거하세요"})


def _luck_4_play(g, c):
    m = g.mill_top(c.owner)
    if not m:
        return

    def _matches_milled_value(x, pi, line):
        v = x.value if x.face_up else g.facedown_value_in_stack(g.players[pi]["stacks"][line])
        return v == m.value

    cands = g.cards_in_play(_matches_milled_value)
    card = g.choose_card_from(c.owner, cands, {"prompt": "그 값을 가진 카드를 제거하세요", "intent": "delete"})
    if card:
        g.delete_cards([card])


DEFS["Luck_0"] = {"play": _luck_0_play}
DEFS["Luck_1"] = {"play": _luck_1_play}
DEFS["Luck_2"] = {"play": _luck_2_play}
DEFS["Luck_3"] = {"play": _luck_3_play}
DEFS["Luck_4"] = {"play": _luck_4_play}
DEFS["Luck_5"] = DISCARD_ONE_DEF


# =============================================================================
# MIRROR (Main 2)
# =============================================================================
def _mirror_1_can_finish(g, c):
    return _has_target(g, lambda x, pi, line: (
        x.owner == _opp(c) and x.face_up and x.definition.get("play") is not None))


def _mirror_1_finish(g, c):
    cands = g.cards_in_play(_uncovered_only(g, lambda x, pi, line: (
        x.owner == _opp(c) and x.face_up and x.definition.get("play") is not None)))
    card = g.choose_card_from(
        c.owner, cands,
        {"optional": True, "prompt": "상대 카드 1장의 중간 명령을 처리하세요"})
    if card:
        # "이 카드 위에 있는 것처럼": 상대 카드의 middle을 Mirror_1이 행동
        # 주체인 것처럼 실행 (owner/line 컨텍스트는 Mirror의 것).
        fn = card.definition["play"]
        g.run_card(c, lambda: fn(g, c), "bot", None)


def _mirror_2_play(g, c):
    # RULING (Main 3 코덱스): "스택은 0장일 수도 있다" -- 빈 라인도 합법적인
    # 교환 대상.
    a = g.choose_line_from(c.owner, [1, 2, 3], {"prompt": "교환: 첫 번째 더미", "intent": "rearrange"})
    if not a:
        return
    rest = [l for l in (1, 2, 3) if l != a]
    b = g.choose_line_from(c.owner, rest, {"prompt": "교환할 대상", "intent": "rearrange"})
    if b:
        g.swap_stacks(c.owner, a, b)


def _mirror_3_play(g, c):
    # "네 카드 1장을 뒤집어라"는 Mirror_3 자기 자신도 대상이 될 수 있다;
    # 룰링에 따라 먼저 자기 자신을 뒤집어 뒷면이 되면 두 번째 뒤집기는
    # 더 이상 일어나지 않는다.
    card = _flip_one(g, c.owner, lambda x, pi, line: x.owner == c.owner, {"prompt": "자신의 카드 1장을 뒤집으세요"})
    if not card or card is c:
        return
    _, line, _ = g.locate(card)
    _flip_one(g, c.owner, lambda x, pi, l: x.owner == _opp(c) and l == line,
              {"prompt": "같은 라인에 있는 상대 카드 1장을 뒤집으세요"})


DEFS["Mirror_0"] = {"passive": {"lineValueSelf": lambda g, c, line: len(g.players[_opp(c)]["stacks"][line])}}
DEFS["Mirror_1"] = {"can": {"finish": _mirror_1_can_finish}, "finish": _mirror_1_finish}
DEFS["Mirror_2"] = {"play": _mirror_2_play}
DEFS["Mirror_3"] = {"play": _mirror_3_play}
DEFS["Mirror_4"] = {
    # BOT-band 트리거 (카드 아트도 bottom band) -- uncovered일 때만 활성.
    "reactive": {"afterDraw": lambda g, c, actor, *_: (g.draw(c.owner, 1) if actor != c.owner else None)},
}
DEFS["Mirror_5"] = DISCARD_ONE_DEF


# =============================================================================
# PEACE (Main 2)
# =============================================================================
def _peace_1_play(g, c):
    # CLARIFICATION: 두 플레이어가 동시에 손을 버린다. 먼저 둘 다 조용히
    # 비우고(silent), 그다음 discard 트리거를 발동 -- "누가 버린 후" 리액티브가
    # 절반만 버려진 상태를 보지 않고 양쪽 다 이미 비워진 걸 보게.
    me, other = c.owner, _opp(c)
    n1 = _discard_whole_hand(g, me, {"silent": True})
    n2 = _discard_whole_hand(g, other, {"silent": True})
    if n1 > 0:
        g.fire_reactive(me, "afterDiscard")
    if n2 > 0:
        g.fire_reactive(other, "afterDiscard")


def _peace_2_play(g, c):
    g.draw(c.owner, 1)
    _play_from_hand(g, c.owner, None, {"faceDownOnly": True, "prompt": "카드 1장을 뒷면으로 플레이하세요"})


def _peace_3_play(g, c):
    # "카드 1장을 버릴 수 있다. 카드 1장을 뒤집어라..." -- 서로 다른 두 명령:
    # 버리기는 선택이고, 뒤집기는 어느 쪽이든 resolve된다 (손이 비어 있으면
    # 기준값이 0).
    g.discard(c.owner, 1, {"min": 0, "prompt": "카드 1장을 버릴 수 있습니다"})
    n = len(g.players[c.owner]["hand"])
    _flip_one(g, c.owner, lambda x, pi, line: _eff_val(x) > n,
              {"prompt": "손패 수보다 값이 큰 카드 1장을 뒤집으세요"})


DEFS["Peace_1"] = {
    "play": _peace_1_play,
    # 손이 비었을 때만 드로우.
    "can": {"finish": lambda g, c: len(g.players[c.owner]["hand"]) == 0},
    "finish": lambda g, c: (g.draw(c.owner, 1) if not g.players[c.owner]["hand"] else None),
}
DEFS["Peace_2"] = {"play": _peace_2_play}
DEFS["Peace_3"] = {"play": _peace_3_play}
DEFS["Peace_4"] = {
    # BOT-band 트리거 (카드 아트도 bottom band) -- uncovered일 때만 활성이라
    # reactive (reactiveTop 아님).
    "reactive": {"afterDiscard": lambda g, c, actor, *_: (
        g.draw(c.owner, 1) if (actor == c.owner and g.turn != c.owner) else None)},
}
DEFS["Peace_5"] = DISCARD_ONE_DEF
DEFS["Peace_6"] = {"play": lambda g, c: (g.flip_card(c) if len(g.players[c.owner]["hand"]) > 1 else None)}


# =============================================================================
# SMOKE (Main 2)
# =============================================================================
def _smoke_0_play(g, c):
    # "뒷면 카드가 있는 각 라인에서" -- Smoke_0 자신의 라인도 뒷면 카드를
    # 가지면 자격이 있다 (자기 자신을 덮는 첫 플레이도 포함).
    eligible = [line for line in (1, 2, 3) if g.facedown_in_line(line) > 0]
    _play_top_face_down_each(g, c.owner, eligible)


def _smoke_1_play(g, c):
    card = _flip_one(g, c.owner, lambda x, pi, line: x.owner == c.owner, {"prompt": "자신의 카드 1장을 뒤집으세요"})
    if card and _ask(g, c.owner, "그 카드를 이동할까요?", "move"):
        _move_to_other_line(g, c.owner, card)


def _smoke_3_play(g, c):
    allowed, any_line = {}, False
    for l in (1, 2, 3):
        if g.facedown_in_line(l) > 0:
            allowed[l] = True
            any_line = True
    if not any_line:
        return
    _play_from_hand(g, c.owner, None,
                     {"faceDownOnly": True, "lines": allowed,
                      "prompt": "뒷면 카드가 있는 라인에 카드 1장을 뒷면으로 플레이하세요"})


def _smoke_4_play(g, c):
    cands = g.cards_in_play(lambda x, pi, line: not x.face_up and not g.is_uncovered(x))
    card = g.choose_card_from(c.owner, cands, {"prompt": "커버된 뒷면 카드 1장을 이동하세요", "intent": "move"})
    if card:
        _move_to_other_line(g, c.owner, card)


DEFS["Smoke_0"] = {"play": _smoke_0_play}
DEFS["Smoke_1"] = {"play": _smoke_1_play}
DEFS["Smoke_2"] = {"passive": {"lineValueSelf": lambda g, c, line: g.facedown_in_line(line)}}
DEFS["Smoke_3"] = {"play": _smoke_3_play}
DEFS["Smoke_4"] = {"play": _smoke_4_play}
DEFS["Smoke_5"] = DISCARD_ONE_DEF


# =============================================================================
# TIME (Main 2)
# =============================================================================
def _time_0_play(g, c):
    p = g.players[c.owner]
    if p["discard"]:
        cands = list(p["discard"])
        card = g.choose_card_from(c.owner, cands,
                                   {"showcase": True, "prompt": "버림더미의 카드 1장을 플레이하세요",
                                    "intent": "playTrash"})
        if card:
            # 트래시를 떠나기 전에 목적지+면을 먼저 고른다 (선택을 취소하면
            # 카드는 원래 있던 곳에 그대로 남아야 함).
            line, face_up = _choose_line_and_face(g, c.owner, card)
            if line:
                for i in range(len(p["discard"]) - 1, -1, -1):
                    if p["discard"][i] is card:
                        del p["discard"][i]
                        break
                g.play_external(c.owner, card, c.owner, line, face_up)
    g.reshuffle_discard_into_deck(c.owner)


def _time_1_play(g, c):
    cands = g.cards_in_play(lambda x, pi, line: not g.is_uncovered(x))
    card = g.choose_card_from(c.owner, cands, {"prompt": "커버된 카드 1장을 뒤집으세요", "intent": "flip"})
    if card:
        g.flip_card(card)
    g.discard_deck(c.owner)


def _time_2_reactive_top_after_shuffle(g, c, actor, *_):
    if actor != c.owner:
        return
    g.draw(c.owner, 1)
    if _ask(g, c.owner, "이 카드를 이동할까요?", "move"):
        _move_to_other_line(g, c.owner, c)


def _time_2_play(g, c):
    if (g.players[c.owner]["discard"]
            and _ask(g, c.owner, "버림더미를 덱에 섞을까요?", "shuffleTrash")):
        g.reshuffle_discard_into_deck(c.owner)


def _time_3_play(g, c):
    p = g.players[c.owner]
    if not p["discard"]:
        return
    cands = list(p["discard"])
    card = g.choose_card_from(c.owner, cands,
                               {"showcase": True, "optional": True,
                                "prompt": "버림더미의 카드 1장을 공개하세요", "intent": "playTrash"})
    if not card:
        return
    g.emit("reveal", {"player": c.owner, "i18n": {"key": "ev.reveal", "params": {
        "p": c.owner, "card": {"uid": card.uid, "proto": card.proto, "value": card.value}}}})
    # 뒷면으로 다른 라인에 -- 라인 잠금(Plague_0 등) 존중.
    line = _line_of(g, c)
    allowed = {l: True for l in (1, 2, 3) if l != line}
    # Lua 원본은 반환값 중 line만 취하고 faceUp은 버린다 (faceDownOnly라
    # 어차피 항상 False이므로 아래에서 명시적으로 False를 넘김).
    dest, _face_up = _choose_line_and_face(g, c.owner, card,
                                            {"faceDownOnly": True, "lines": allowed,
                                             "linePrompt": "뒷면으로 플레이할 곳"})
    if not dest:
        return  # 합법적인 곳이 없음: 공개된 카드는 트래시에 그대로 남음
    for i in range(len(p["discard"]) - 1, -1, -1):
        if p["discard"][i] is card:
            del p["discard"][i]
            break
    g.play_external(c.owner, card, c.owner, dest, False)


def _time_4_play(g, c):
    g.draw(c.owner, 2)
    g.discard(c.owner, 2)


DEFS["Time_0"] = {"play": _time_0_play}
DEFS["Time_1"] = {"play": _time_1_play}
DEFS["Time_2"] = {"reactiveTop": {"afterShuffle": _time_2_reactive_top_after_shuffle}, "play": _time_2_play}
DEFS["Time_3"] = {"play": _time_3_play}
DEFS["Time_4"] = {"play": _time_4_play}
DEFS["Time_5"] = DISCARD_ONE_DEF


# =============================================================================
# WAR (Main 2)
# =============================================================================
def _war_0_reactive_top_after_refresh(g, c, actor, *_):
    if actor == c.owner and _ask(g, c.owner, "이 카드를 뒤집을까요 (전쟁_0)?", "flipSelf"):
        g.flip_card(c)


def _war_0_reactive_after_draw(g, c, actor, *_):
    if actor != c.owner:
        _delete_one(g, c.owner, None, {"optional": True, "prompt": "카드 1장을 제거하세요"})


def _war_1_reactive_after_refresh(g, c, actor, *_):
    # "카드 1장 이상을 버린 다음 리프레시" -- "다음"은 순서이지 조건이 아니다
    # ("그렇게 했다면"이 조건 표시). 손이 비어도(버릴 게 없어도) 리프레시는 함.
    if actor == c.owner:
        return
    p = g.players[c.owner]
    if p["hand"]:
        g.discard(c.owner, len(p["hand"]), {"min": 1, "prompt": "카드 1장 이상을 버리세요"})
    g.refresh(c.owner)


def _war_2_reactive_after_compile(g, c, actor, *_):
    if actor != c.owner:
        _discard_whole_hand(g, actor)


def _war_3_reactive_after_discard(g, c, actor, *_):
    if actor == c.owner:
        return
    if not g.players[c.owner]["hand"]:
        return
    if not _ask(g, c.owner, "다른 라인에 카드 1장을 뒷면으로 플레이할까요?", "playFaceDown"):
        return
    line = _line_of(g, c)
    allowed = {l: True for l in (1, 2, 3) if l != line}
    _play_from_hand(g, c.owner, None,
                     {"faceDownOnly": True, "lines": allowed, "optional": True,
                      "prompt": "카드 1장을 뒷면으로 플레이하세요"})


DEFS["War_0"] = {
    "reactiveTop": {"afterRefresh": _war_0_reactive_top_after_refresh},
    "reactive": {"afterDraw": _war_0_reactive_after_draw},
}
DEFS["War_1"] = {"reactive": {"afterRefresh": _war_1_reactive_after_refresh}}
DEFS["War_2"] = {
    "play": lambda g, c: _flip_one(g, c.owner, None, {"prompt": "카드 1장을 뒤집으세요"}),
    "reactive": {"afterCompile": _war_2_reactive_after_compile},
}
DEFS["War_3"] = {"play": lambda g, c: g.draw(c.owner, 1),
                  "reactive": {"afterDiscard": _war_3_reactive_after_discard}}
DEFS["War_4"] = {"play": lambda g, c: g.discard(_opp(c), 1)}
DEFS["War_5"] = DISCARD_ONE_DEF


# =============================================================================
# ASSIMILATION (Aux 2)
# =============================================================================
def _assimilation_0_play(g, c):
    cands = g.cards_in_play(lambda x, pi, line: x.owner == _opp(c) and not x.face_up)
    card = g.choose_card_from(c.owner, cands,
                               {"prompt": "상대의 뒷면 카드 1장을 자신의 손패에 넣으세요", "intent": "take"})
    if card:
        g.put_into_hand(card, c.owner)


def _assimilation_1_play(g, c):
    g.discard(c.owner, 1)
    g.refresh(c.owner)


def _assimilation_1_reactive_after_refresh(g, c, actor, *_):
    g.draw_from_deck_of(_opp(c), c.owner)
    p = g.players[c.owner]
    if not p["hand"]:
        return
    pick = g.choose_card_from(
        c.owner, p["hand"],
        {"fromHand": True, "prompt": "카드 1장을 상대의 버림더미에 버리세요",
         "intent": "give"}) or p["hand"][0]  # 필수: 선택을 취소해도 결국 버려짐
    for i in range(len(p["hand"]) - 1, -1, -1):
        if p["hand"][i] is pick:
            del p["hand"][i]
            break
    pick.face_up = False
    pick.owner = _opp(c)  # 상대의 트래시로 (그리고 나중에 상대 덱으로 재활용됨)
    g.players[_opp(c)]["discard"].append(pick)
    g.emit("discardToOpp", {"uid": pick.uid,
                             "i18n": {"key": "ev.discardToOpp", "params": {"p": c.owner, "opp": _opp(c)}}})


def _assimilation_2_can_finish(g, c):
    if not g.players[_opp(c)]["deck"]:
        return False
    pi, line, _ = g.locate(c)
    return pi is not None and g.can_play_face_down(c.owner, None, line)[0]


def _assimilation_2_finish(g, c):
    pi, line, _ = g.locate(c)
    if pi is None:
        return
    # resolve 시점에 재확인 (deck을 건드리기 전) -- can 물어본 뒤로 다른 End
    # 명령이 이 라인을 잠갔을 수 있음.
    if not g.can_play_face_down(c.owner, None, line)[0]:
        return
    card = g.pop_deck(_opp(c))
    if not card:
        return
    g.play_external(c.owner, card, pi, line, False)


def _assimilation_4_play(g, c):
    g.draw_from_deck_of(_opp(c), c.owner)
    g.draw_from_deck_of(c.owner, _opp(c))


def _assimilation_6_can_finish(g, c):
    return (len(g.players[c.owner]["deck"]) > 0
            and len(_facedown_legal_lines(g, c.owner, [1, 2, 3])) > 0)


def _assimilation_6_finish(g, c):
    p = g.players[c.owner]
    if not p["deck"]:
        return  # 낼 카드가 없음; 덱은 리셔플되지 않음
    dests = _facedown_legal_lines(g, c.owner, [1, 2, 3])
    if not dests:
        return
    line = g.choose_line_from(
        c.owner, dests,
        # 상대편 쪽에 착지 -- target을 상대로 지정해서 UI가 라인 전체가 아니라
        # 상대 쪽 절반만 강조하게.
        {"prompt": "상대 쪽에 뒷면으로 플레이하세요", "intent": "play",
         "target": _opp(c)}) or dests[0]
    card = g.pop_deck(c.owner)
    if not card:
        return
    g.play_external(c.owner, card, _opp(c), line, False)


DEFS["Assimilation_0"] = {"play": _assimilation_0_play}
DEFS["Assimilation_1"] = {"play": _assimilation_1_play,
                           "reactive": {"afterRefresh": _assimilation_1_reactive_after_refresh}}
DEFS["Assimilation_2"] = {"can": {"finish": _assimilation_2_can_finish}, "finish": _assimilation_2_finish}
DEFS["Assimilation_4"] = {"play": _assimilation_4_play}
DEFS["Assimilation_5"] = DISCARD_ONE_DEF
DEFS["Assimilation_6"] = {"can": {"finish": _assimilation_6_can_finish}, "finish": _assimilation_6_finish}


# =============================================================================
# DIVERSITY (Aux 2)
# =============================================================================
def _diversity_0_play(g, c):
    if _distinct_protos_in_play(g) >= 6:
        g.compile_protocol_effect(c.owner, "Diversity")


def _diversity_0_can_finish(g, c):
    for h in g.players[c.owner]["hand"]:
        if h.proto != "Diversity":
            return True
    return False


def _diversity_0_finish(g, c):
    line = _line_of(g, c)
    if not line:
        return
    # "이 라인에서"가 프로토콜 매치를 대신한다: 어떤 프로토콜이든 앞면으로
    # 낼 수 있음(anyFaceUp) -- 앞면 프로토콜 종류 수를 세는 Diversity의 핵심 엔진.
    _play_from_hand(g, c.owner, lambda x: x.proto != "Diversity",
                     {"lines": {line: True}, "optional": True, "anyFaceUp": True,
                      "prompt": "이 라인에 다양성이 아닌 카드 1장을 플레이할 수 있습니다"})


def _diversity_1_play(g, c):
    _move_one(g, c.owner, None, {"prompt": "카드 1장을 이동하세요"})
    line = _line_of(g, c)
    if line:
        n = _distinct_protos_in_line(g, line)
        if n > 0:
            g.draw(c.owner, n)


def _diversity_3_line_value_self(g, c, line):
    for x in g.players[c.owner]["stacks"][line]:
        if x.face_up and x.proto != "Diversity":
            return 2
    return 0


def _diversity_4_play(g, c):
    n = _distinct_protos_in_play(g)
    _flip_one(g, c.owner, lambda x, pi, line: _eff_val(x) < n, {"prompt": "더 낮은 값의 카드 1장을 뒤집으세요"})


def _diversity_6_can_finish_top(g, c):
    return _distinct_protos_in_play(g) < 4


def _diversity_6_finish_top(g, c):
    if _distinct_protos_in_play(g) < 4:
        g.delete_card(c)


DEFS["Diversity_0"] = {"play": _diversity_0_play, "can": {"finish": _diversity_0_can_finish},
                        "finish": _diversity_0_finish}
DEFS["Diversity_1"] = {"play": _diversity_1_play}
DEFS["Diversity_3"] = {"passive": {"lineValueSelf": _diversity_3_line_value_self}}
DEFS["Diversity_4"] = {"play": _diversity_4_play}
DEFS["Diversity_5"] = DISCARD_ONE_DEF
DEFS["Diversity_6"] = {"can": {"finishTop": _diversity_6_can_finish_top}, "finishTop": _diversity_6_finish_top}


# =============================================================================
# UNITY (Aux 2)
# =============================================================================
def _unity_flip_or_draw(g, c):
    """Unity_0의 이것 또는 저것, Middle 명령과 커버 트리거가 공유."""
    pick = g.choose_option_from(c.owner, ["flip", "draw"], {
        "prompt": "카드 1장을 뒤집을까요, 뽑을까요?", "intent": "flipOrDraw",
        "labels": {"flip": "뒤집기", "draw": "뽑기"}})
    if pick == "flip":
        _flip_one(g, c.owner, None, {"prompt": "카드 1장을 뒤집으세요"})
    else:
        g.draw(c.owner, 1)


def _unity_0_play(g, c):
    if _proto_count_in_play(g, "Unity") >= 2:
        _unity_flip_or_draw(g, c)


def _unity_0_on_covered(g, c, incoming, incoming_face_up):
    if incoming and incoming_face_up and incoming.proto == "Unity":
        _unity_flip_or_draw(g, c)


def _unity_1_start_top(g, c):
    if g.is_uncovered(c):
        return
    if _ask(g, c.owner, "이 카드를 이동할까요?", "move"):
        _move_to_other_line(g, c.owner, c)


def _unity_1_play(g, c):
    if _proto_count_in_play(g, "Unity") >= 5:
        line = g.compile_protocol_effect(c.owner, "Unity")
        if line:
            to_delete = []
            for pi in (1, 2):
                to_delete.extend(g.players[pi]["stacks"][line])
            g.delete_cards(to_delete)


def _unity_2_play(g, c):
    n = _proto_count_in_play(g, "Unity")
    if n > 0:
        g.draw(c.owner, n)


def _unity_3_play(g, c):
    if _proto_count_in_play(g, "Unity") >= 2:
        _flip_one(g, c.owner, lambda x, pi, line: x.face_up,
                  {"optional": True, "prompt": "앞면 카드 1장을 뒤집으세요"})


def _unity_4_finish_top(g, c):
    # 손이 비어 있을 때만 덱을 공개하고 Unity 카드를 뽑는다.
    p = g.players[c.owner]
    if p["hand"]:
        return
    g.emit("revealDeck", {"player": c.owner, "i18n": {"key": "ev.revealDeck", "params": {"p": c.owner}}})
    if not g.draw_blocked(c.owner):
        to_take = [x for x in p["deck"] if x.proto == "Unity"]
        # 하나의 드로우 배치: g.draw처럼 이벤트 1개 + afterDraw 1번.
        for x in to_take:
            g.take_from_deck_to_hand(c.owner, x, {"silent": True})
        if to_take:
            g.emit("draw", {"player": c.owner, "n": len(to_take),
                             "i18n": {"key": "ev.draw", "params": {"p": c.owner, "n": len(to_take)}}})
            g.fire_reactive(c.owner, "afterDraw")
    g.shuffle_deck(c.owner)


DEFS["Unity_0"] = {"play": _unity_0_play, "onCovered": _unity_0_on_covered}
DEFS["Unity_1"] = {
    "allowFaceUpHere": "Unity",
    # covered 카드만 이동 가능; uncovered면 아무 일도 안 함.
    "can": {"startTop": lambda g, c: not g.is_uncovered(c)},
    "startTop": _unity_1_start_top,
    "play": _unity_1_play,
}
DEFS["Unity_2"] = {"play": _unity_2_play}
DEFS["Unity_3"] = {"play": _unity_3_play}
DEFS["Unity_4"] = {"can": {"finishTop": lambda g, c: len(g.players[c.owner]["hand"]) == 0},
                    "finishTop": _unity_4_finish_top}
DEFS["Unity_5"] = DISCARD_ONE_DEF


# ---------------------------------------------------------------------------
# 공개 accessor
# ---------------------------------------------------------------------------
_EMPTY = {}


def get(proto, value):
    """카드 한 장의 효과 정의를 반환한다. 정의가 없으면 빈 딕셔너리."""
    return DEFS.get(f"{proto}_{value}", _EMPTY)
