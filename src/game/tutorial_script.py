"""가이드 튜토리얼 데이터 (챕터별 보드 세팅).

원본은 별도 Lua/LÖVE 프로젝트의 `tutorial_script.lua` -- 그 파일은 "라이브
씬 객체를 프레임마다 들여다보며 스텝 진행을 판단"하는 단일 프로세스 구조라
스텝/텍스트/앵커/정답판정 로직까지 전부 갖고 있었지만, 그 부분은 이
웹앱에서는 브라우저 쪽(web/static/js/tutorial.js)이 맡는다. 여기(서버)는
"이 챕터를 이런 보드 상태로 시작해줘"만 담당한다 -- 고정 덱, 스크립트형
AI, 미리 배치된 스택/손패. 실제 챕터 흐름(어떤 순서로 뭘 가르치는지)은
tutorial.js의 TUTORIAL_STEPS를 봐야 전체 그림이 보인다.

챕터 1(BASICS): 빈 보드에서 시작하는 조직적인 한 판. 고정 덱만 쓰고
보드 프리셋은 없음.
챕터 2(DEFENSIVE REFRESH + RECOMPILE): 상대가 한 수만 더 두면 이기는
상황을 미리 깔아두고, 플레이어는 이미 Control을 쥔 채로 시작해서
리프레시로 상대 프로토콜을 재배치해 방어하는 법을 가르친다.

원본 Lua 헤더 주석은 "Chapter 3 RECOMPILE"도 언급하지만 실제
`Script.chapters` 테이블엔 없었다 -- 이 포팅도 2챕터까지만 다룬다.
"""

from src.game.ai_random import RandomAI


# =============================================================================
# 챕터 1 -- 고정 덱 (뽑는 순서 그대로, 첫 5장이 오프닝 핸드)
# =============================================================================
CH1_DECKS = {
    1: [
        ("Life", 4), ("Metal", 6), ("Life", 2), ("Life", 3), ("Metal", 1),
        ("Fire", 1), ("Fire", 2), ("Life", 1), ("Metal", 0),
        ("Life", 0), ("Life", 5), ("Fire", 0), ("Fire", 3), ("Fire", 4),
        ("Fire", 5), ("Metal", 2), ("Metal", 3), ("Metal", 5),
    ],
    2: [
        ("Water", 3), ("Death", 2), ("Psychic", 4), ("Water", 1), ("Death", 5),
        ("Water", 0), ("Water", 2), ("Water", 4), ("Water", 5),
        ("Death", 0), ("Death", 1), ("Death", 3), ("Death", 4),
        ("Psychic", 0), ("Psychic", 1), ("Psychic", 2), ("Psychic", 3), ("Psychic", 5),
    ],
}


# =============================================================================
# 챕터 2 -- 프리페어드 챕터용 풀 18장 덱 (onDealt가 보드를 통째로 다시
# 깔아버리므로 뽑는 순서는 무의미).
# =============================================================================
def _full_deck_list(protos, values):
    return [(p, v) for p in protos for v in values]


FULL_DECKS = {
    1: _full_deck_list(["Life", "Fire"], [0, 1, 2, 3, 4, 5])
       + _full_deck_list(["Metal"], [0, 1, 2, 3, 5, 6]),
    2: _full_deck_list(["Water", "Death", "Psychic"], [0, 1, 2, 3, 4, 5]),
}


# =============================================================================
# 스크립트형 AI -- action 프롬프트만 스크립트대로 답하고, 나머지 전부(카드
# 선택/예아니오/재배치 등)는 RandomAI에 위임한다 (Lua의 "그 외엔 실제 AI로
# 폴백" 주석과 동일한 방어적 설계).
# =============================================================================
class Ch1ScriptedAI:
    """챕터 1: 라인 2/3에 번갈아 뒷면으로 냄 (효과 없는 카드라 프롬프트도
    안 뜸), 손패가 떨어지면 리프레시."""

    LANES = [2, 3, 2, 3, 2]

    def __init__(self):
        self.base = RandomAI()
        self.turn = 0

    def decide(self, g, req):
        if req.get("type") == "action" and req.get("chooser") == 2:
            self.turn += 1
            lane = self.LANES[self.turn - 1] if self.turn <= len(self.LANES) else None
            hand = g.players[2]["hand"]
            if lane and hand:
                return {"kind": "play", "uid": hand[0].uid, "line": lane, "faceUp": False}
            return {"kind": "refresh"}
        return self.base.decide(g, req)

    def planRearrange(self, g, pi, compiling_line):
        return self.base.planRearrange(g, pi, compiling_line)


class Ch2PassiveAI:
    """챕터 2: 항상 라인 3에 뒷면으로 냄 (플레이어 라인을 절대 건드리지
    않아 미리 짜둔 판이 그대로 유지됨), 손패가 떨어지면 리프레시."""

    def __init__(self):
        self.base = RandomAI()

    def decide(self, g, req):
        if req.get("type") == "action" and req.get("chooser") == 2:
            hand = g.players[2]["hand"]
            if hand:
                return {"kind": "play", "uid": hand[0].uid, "line": 3, "faceUp": False}
            return {"kind": "refresh"}
        return self.base.decide(g, req)

    def planRearrange(self, g, pi, compiling_line):
        return self.base.planRearrange(g, pi, compiling_line)


# =============================================================================
# 프리페어드 보드 세팅 (Lua Scenario.apply의 파이썬 이식)
# =============================================================================
def _find_and_remove(pools, proto, value):
    """pools(리스트들의 리스트)에서 (proto, value)와 일치하는 카드 객체를
    찾아 그 자리에서 제거하고 반환한다. 새로 만들지 않는다 -- 이미
    build_decks()가 만들어 손패/덱에 넣어둔 실제 객체를 재배치하는
    것이라야 18장 총량이 항상 그대로 보존된다."""
    for pool in pools:
        for card in pool:
            if card.proto == proto and card.value == value:
                pool.remove(card)
                return card
    return None


def apply_scenario(g, stacks=None, hand1=None):
    """지정한 스택/손패로 보드를 통째로 다시 깐다 (프리페어드 챕터의
    on_dealt 훅에서 호출).

    stacks: [{"pi": 1|2, "line": 1|2|3, "cards": [(proto, value, faceUp), ...]}]
    hand1: [(proto, value), ...] | None -- 주어지면 플레이어1의 손패를
        정확히 이 카드들로 교체한다 (기존 손패 중 안 쓰인 카드는 덱으로
        돌아감, 사라지지 않음).
    """
    for spec in (stacks or []):
        pi = spec["pi"]
        line = spec["line"]
        p = g.players[pi]
        for proto, value, face_up in spec["cards"]:
            card = _find_and_remove([p["hand"], p["deck"]], proto, value)
            if card is None:
                raise ValueError(f"시나리오 카드를 찾을 수 없음: {proto}_{value} (P{pi})")
            card.face_up = face_up
            p["stacks"][line].append(card)

    if hand1 is not None:
        p1 = g.players[1]
        leftover = list(p1["hand"])
        pools = [leftover, p1["deck"]]
        new_hand = []
        for proto, value in hand1:
            card = _find_and_remove(pools, proto, value)
            if card is None:
                raise ValueError(f"시나리오 손패 카드를 찾을 수 없음: {proto}_{value}")
            new_hand.append(card)
        # leftover에 남은 건(hand1이 요구하지 않은 원래 손패 카드) 덱으로 돌려보낸다.
        p1["deck"].extend(leftover)
        p1["hand"] = new_hand


def ch2_on_dealt(g):
    """상대가 Water(라인2)/Death(라인3)를 이미 컴파일했고 Psychic(라인1,
    미컴파일)이 10에 도달해 다음 턴 컴파일하면 이기는 상황. 플레이어는
    라인2/3을 이기고 있어(4 vs 0) 턴1 Control 체크에서 Control을 얻는다.
    손패 2장이라 리프레시가 가능 -- 리프레시로 상대 프로토콜을 재배치해
    이미 컴파일된 프로토콜을 라인1로 밀어넣으면 다음 컴파일이 무해한
    재컴파일이 된다."""
    apply_scenario(g, stacks=[
        {"pi": 1, "line": 2, "cards": [("Fire", 0, False), ("Fire", 1, False)]},
        {"pi": 1, "line": 3, "cards": [("Metal", 0, False), ("Metal", 1, False)]},
        {"pi": 2, "line": 1, "cards": [
            ("Psychic", 0, False), ("Psychic", 1, False), ("Psychic", 2, False),
            ("Psychic", 3, False), ("Psychic", 4, False)]},
    ], hand1=[("Life", 4), ("Life", 2)])
    g.players[2]["compiled"] = {1: False, 2: True, 3: True}


# =============================================================================
# 챕터 목록
#
# "ai_class"는 인스턴스가 아니라 클래스 자체를 담아둔다 -- 이 모듈은
# Flask 프로세스 시작 시 한 번만 import되므로, 여기에 인스턴스를 미리
# 만들어 두면(예: Ch1ScriptedAI()) 서로 다른 플레이스루가 같은 AI
# 객체를 공유하게 되어 self.turn 같은 상태가 이전 판에서 새 판으로
# 새어 들어간다. 호출부(web/app.py)가 매 /api/tutorial/new 요청마다
# ai_class()로 새로 인스턴스를 만들어야 한다.
# =============================================================================
TUTORIAL_CHAPTERS = [
    {
        "protocols1": ["Life", "Fire", "Metal"],
        "protocols2": ["Water", "Death", "Psychic"],
        "decks": CH1_DECKS,
        "ai_class": Ch1ScriptedAI,
        "on_dealt": None,
    },
    {
        "protocols1": ["Life", "Fire", "Metal"],
        "protocols2": ["Psychic", "Water", "Death"],
        "decks": FULL_DECKS,
        "ai_class": Ch2PassiveAI,
        "on_dealt": ch2_on_dealt,
    },
]
