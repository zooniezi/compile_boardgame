"""특징 추출 -- "지금 이 순간 판 상황"을 학습 가능한 숫자 목록(벡터)으로
바꾼다.

이 파일이 하는 일은 딱 하나: extract(g, pi) -> 고정된 길이의 실수 목록.
아직 기계학습은 전혀 등장하지 않는다 -- 그냥 "판 상태를 읽어서 정해진 공식대로
숫자로 옮겨 적는" 결정론적 함수일 뿐이다. 이 숫자 목록에 나중에(자기대국이 끝난
뒤) "결국 이겼는지" 라벨을 붙여서 학습 데이터로 쓴다.

핵심 설계 원칙:
1. pi 시점 벡터다 -- 같은 판 상태라도 g.players[1] 기준으로 뽑은 벡터와
   g.players[2] 기준으로 뽑은 벡터는 다르다("내"/"상대"가 뒤바뀌므로).
2. 라인은 "내가 유리한 순서"로 정렬해서 넣는다 -- 라인 번호(1/2/3) 자체는
   그냥 자리 배치일 뿐 의미가 없어서, 번호 그대로 넣으면 모델이 무의미한
   패턴("라인 1일 때")을 배우게 된다. "가장 유리한 라인 -> 가장 불리한
   라인" 순으로 항상 정렬해서 넣으면 "1등 라인이 이럴 때" 같은 의미 있는
   패턴을 배울 수 있다.
3. 모든 값을 대략 0~1 범위로 정규화한다 -- 손패 수(0~5)와 턴 수(0~240)처럼
   스케일이 다른 값들을 그대로 섞으면 학습이 불안정해진다.
4. 손패는 "카드가 몇 장인지"보다 "무엇을 할 수 있는지"로 특징화한다 --
   ai_prior.py의 TAGS를 그대로 재활용해서 "제거 카드가 몇 장 있는지" 같은
   잠재력을 센다.

이 함수 하나를 자기대국 데이터 생성과 학습된 평가 양쪽에서 반드시 똑같이
써야 한다 -- 서로 다른 특징 추출 로직을 쓰면 학습이 완전히 어긋난다.
특징 개수(FEATURE_NAMES의 길이)가 바뀌면 이전에 학습된 가중치는 전부
재학습해야 한다.
"""

from src.game.rules import COMPILE_THRESHOLD, HAND_SIZE
from src.game.ai_prior import TAGS

DECK_TOTAL = 18  # 프로토콜 3개 x 카드 6장 (손패 포함, 초기 덱+손패 합계)
LINE_VALUE_SCALE = 15.0  # 라인 값이 실전에서 대략 이 범위 안에 들어옴
TURN_SCALE = 60.0  # 턴 수 정규화 기준 (그 이상은 그냥 1.0으로 잘라둠)


def _other(pi):
    return 2 if pi == 1 else 1


def _clip01(x):
    return max(0.0, min(1.0, x))


def _hand_potential(g, pi):
    """손패를 '몇 장인지'가 아니라 '무엇을 할 수 있는지'로 요약.
    ai_prior.TAGS를 그대로 재사용 -- 새로 만들 게 아니라 이미 있는 지식을
    다시 씀."""
    hand = g.players[pi]["hand"]
    n = len(hand) or 1  # 0으로 나누기 방지
    del_n = ret_n = flip_n = draw_n = ongoing_n = 0
    total_value = 0
    for c in hand:
        tag = TAGS.get(f"{c.proto}_{c.value}", {})
        if tag.get("del"):
            del_n += 1
        if tag.get("ret"):
            ret_n += 1
        if tag.get("flip"):
            flip_n += 1
        if tag.get("draw") or tag.get("deck_plays"):
            draw_n += 1
        if tag.get("ongoing"):
            ongoing_n += 1
        total_value += c.value
    return [
        del_n / n, ret_n / n, flip_n / n, draw_n / n, ongoing_n / n,
        (total_value / n) / 6.0,  # 카드 값은 보통 0~6
    ]


def _line_block(g, pi, o, line):
    """라인 하나를 특징 몇 개로 요약 (pi 시점)."""
    mv, ov = g.line_value(pi, line), g.line_value(o, line)
    my_compiled = g.players[pi]["compiled"][line]
    opp_compiled = g.players[o]["compiled"][line]
    my_fd = sum(1 for c in g.players[pi]["stacks"][line] if not c.face_up)
    opp_fd = sum(1 for c in g.players[o]["stacks"][line] if not c.face_up)
    return [
        _clip01(mv / LINE_VALUE_SCALE),
        _clip01(ov / LINE_VALUE_SCALE),
        _clip01((mv - ov + LINE_VALUE_SCALE) / (2 * LINE_VALUE_SCALE)),  # -15~15 -> 0~1
        1.0 if my_compiled else 0.0,
        1.0 if opp_compiled else 0.0,
        1.0 if (not my_compiled and mv >= COMPILE_THRESHOLD and mv > ov) else 0.0,
        1.0 if (not opp_compiled and ov >= COMPILE_THRESHOLD and ov > mv) else 0.0,
        min(my_fd, 6) / 6.0,
        min(opp_fd, 6) / 6.0,
    ]


def extract(g, pi):
    """pi 시점의 특징 벡터. 항상 같은 길이의 실수 목록을 반환한다."""
    o = _other(pi)
    me, op = g.players[pi], g.players[o]

    x = [
        len(me["hand"]) / HAND_SIZE,
        len(op["hand"]) / HAND_SIZE,
        len(me["deck"]) / DECK_TOTAL,
        len(op["deck"]) / DECK_TOTAL,
        len(me["discard"]) / DECK_TOTAL,
        len(op["discard"]) / DECK_TOTAL,
        sum(me["compiled"].values()) / 3.0,
        sum(op["compiled"].values()) / 3.0,
        1.0 if g.control == pi else (-1.0 if g.control == o else 0.0),
        1.0 if g.turn == pi else 0.0,
        _clip01(min(g.turn_count, TURN_SCALE) / TURN_SCALE),
    ]
    x += _hand_potential(g, pi)

    # 라인은 "내가 유리한 순서"로 정렬 -- 번호 자체는 의미가 없으므로.
    lines_sorted = sorted((1, 2, 3),
                          key=lambda l: g.line_value(pi, l) - g.line_value(o, l),
                          reverse=True)
    for line in lines_sorted:
        x += _line_block(g, pi, o, line)

    return x


# 각 인덱스가 뭘 뜻하는지 -- 디버깅/해석용. extract()와 반드시 같은 순서로
# 유지해야 한다.
FEATURE_NAMES = (
    ["my_hand", "opp_hand", "my_deck", "opp_deck", "my_discard", "opp_discard",
     "my_compiled_n", "opp_compiled_n", "control", "my_turn", "turn_count"]
    + ["hand_del", "hand_ret", "hand_flip", "hand_draw", "hand_ongoing", "hand_avg_value"]
    + [f"line{rank}_{name}" for rank in (1, 2, 3) for name in
       ("my_val", "opp_val", "diff", "my_compiled", "opp_compiled",
        "my_ready", "opp_ready", "my_facedown", "opp_facedown")]
)


def feature_count():
    return len(FEATURE_NAMES)
