"""액션 특징 추출 -- "지금 이 결정에서 후보 액션 하나"를 학습 가능한 숫자
목록으로 바꾼다. "상태특징 + 액션특징을 이어붙여 학습된 소형 MLP로 정책을
근사한다"는 설계를, 파이썬 쪽 카드 지식(ai_prior.TAGS,
compile_available_next_check 등)으로 구현한 것이다.

ai_features.extract(g, pi)가 "판 전체 상태"를 보는 것과 달리, 이 파일의
extract(g, pi, action)은 g.legal_actions(pi)가 내놓는 후보 하나하나를
본다 -- 같은 상태에서 후보 액션마다 다른 벡터가 나와야 정책이 "이 상황에서
이 카드를 이 라인에 이렇게 내는 게 얼마나 그럴듯한가"를 배울 수 있다.

state_features(=ai_features.extract)와 이 벡터를 이어붙인 게 정책 신경망의
입력이 된다(scripts/generate_policy_data.py, scripts/train_policy.py).
"""

from src.game.rules import COMPILE_THRESHOLD
from src.game.ai_prior import TAGS, compile_available_next_check, defusable_threat


def _other(pi):
    return 2 if pi == 1 else 1


def _clip01(x):
    return max(0.0, min(1.0, x))


LINE_VALUE_SCALE = 15.0


def extract(g, pi, action):
    """pi 시점에서 후보 action(g.legal_actions(pi)의 원소 하나) 하나의
    특징 벡터. 항상 FEATURE_NAMES와 같은 길이의 실수 목록을 반환한다."""
    if action.get("kind") == "refresh":
        hand = g.players[pi]["hand"]
        avg = (sum(c.value for c in hand) / len(hand)) if hand else 0.0
        return [
            1.0, 0.0,               # is_refresh, is_play
            0.0, 0.0, 0.0,          # face_up, face_down, opp_side
            0.0, 0.0,               # card_value, contrib
            0.0,                    # line_rank
            0.0, 0.0, 0.5,          # my_line_before, opp_line_before, diff_before
            0.0, 0.5,               # new_mine, new_diff
            0.0, 0.0,               # my_line_compiled, opp_line_compiled
            0.0, 0.0, 0.0,          # reach_threshold, compile_open, winning_move
            0.0,                    # defuses_line_threat
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,  # tag_* (전부 face_up 전용)
            _clip01(avg / 6.0),
            1.0 if defusable_threat(g, pi) is not None else 0.0,
        ]

    o = _other(pi)
    card = g.cards_by_uid[action["uid"]]
    line = action["line"]
    face_up = bool(action["faceUp"])
    side = action.get("side")
    opp_side = 1.0 if (side and side != pi) else 0.0

    if opp_side:
        # Corruption_0류 "상대편 스택에 내기" -- 내 라인 형세와 무관하게
        # 상대 스택 맨 위를 덮는 행위라, 아래 my_line/opp_line 기반 필드는
        # 전부 의미가 없어 0으로 비워둔다(대신 face_up/opp_side/card_value/
        # tag_*는 그대로 채운다 -- 카드 정체와 앞뒷면은 여전히 유효한 신호).
        tag = TAGS.get(f"{card.proto}_{card.value}", {}) if face_up else {}
        return [
            0.0, 1.0,
            1.0 if face_up else 0.0, 0.0 if face_up else 1.0, 1.0,
            _clip01(card.value / 6.0), 0.0,
            0.0,
            0.0, 0.0, 0.5,
            0.0, 0.5,
            0.0, 0.0,
            0.0, 0.0, 0.0,
            0.0,
            1.0 if tag.get("del") else 0.0,
            1.0 if tag.get("ret") else 0.0,
            1.0 if tag.get("flip") else 0.0,
            1.0 if (tag.get("draw") or tag.get("deck_plays")) else 0.0,
            1.0 if tag.get("ongoing") else 0.0,
            1.0 if tag.get("move") else 0.0,
            1.0 if tag.get("opp_discard") else 0.0,
            1.0 if tag.get("self_discard") else 0.0,
            0.0,
            0.0,
        ]

    my_line = g.line_value(pi, line)
    opp_line = g.line_value(o, line)
    contrib = card.value if face_up else 2
    new_mine = my_line + contrib

    # 이 액션이 놓일 라인이 "내가 유리한 순서"로 몇 등인지 -- ai_features.py의
    # 라인 정렬 원칙과 동일(라인 번호 자체는 무의미, 상대적 순위만 의미 있음).
    ranked = sorted((1, 2, 3), key=lambda l: g.line_value(pi, l) - g.line_value(o, l),
                    reverse=True)
    line_rank = ranked.index(line) / 2.0  # 0(1등) / 0.5(2등) / 1.0(3등)

    my_compiled = g.players[pi]["compiled"][line]
    opp_compiled = g.players[o]["compiled"][line]

    projected_wins = 0
    for l in (1, 2, 3):
        mine = new_mine if l == line else g.line_value(pi, l)
        if mine > g.line_value(o, l):
            projected_wins += 1
    compile_open = compile_available_next_check(g, pi, projected_wins)
    reach_threshold = new_mine >= COMPILE_THRESHOLD and new_mine > opp_line
    winning_move = 1.0 if (compile_open and reach_threshold and not my_compiled) else 0.0

    # 지금 상대가 이 라인에서 임박한 위협(임계값-2 이상 + 우세)을 쥐고
    # 있었는데, 이 플레이로 내가 역전하는가 -- score_action의 위협 로직과
    # 같은 원리를 "이 액션이 그 위협을 지우는가"로 단순화한 신호.
    opp_had_edge = opp_line >= COMPILE_THRESHOLD - 2 and opp_line > my_line
    defuses = 1.0 if (opp_had_edge and new_mine > opp_line) else 0.0

    tag = TAGS.get(f"{card.proto}_{card.value}", {}) if face_up else {}

    return [
        0.0, 1.0,
        1.0 if face_up else 0.0, 0.0 if face_up else 1.0, 0.0,
        _clip01(card.value / 6.0), _clip01(contrib / 6.0),
        line_rank,
        _clip01(my_line / LINE_VALUE_SCALE), _clip01(opp_line / LINE_VALUE_SCALE),
        _clip01((my_line - opp_line + LINE_VALUE_SCALE) / (2 * LINE_VALUE_SCALE)),
        _clip01(new_mine / LINE_VALUE_SCALE),
        _clip01((new_mine - opp_line + LINE_VALUE_SCALE) / (2 * LINE_VALUE_SCALE)),
        1.0 if my_compiled else 0.0, 1.0 if opp_compiled else 0.0,
        1.0 if reach_threshold else 0.0, 1.0 if compile_open else 0.0, winning_move,
        defuses,
        1.0 if tag.get("del") else 0.0,
        1.0 if tag.get("ret") else 0.0,
        1.0 if tag.get("flip") else 0.0,
        1.0 if (tag.get("draw") or tag.get("deck_plays")) else 0.0,
        1.0 if tag.get("ongoing") else 0.0,
        1.0 if tag.get("move") else 0.0,
        1.0 if tag.get("opp_discard") else 0.0,
        1.0 if tag.get("self_discard") else 0.0,
        0.0,
        0.0,
    ]


FEATURE_NAMES = (
    "is_refresh", "is_play",
    "face_up", "face_down", "opp_side",
    "card_value", "contrib",
    "line_rank",
    "my_line_before", "opp_line_before", "diff_before",
    "new_mine", "new_diff",
    "my_line_compiled", "opp_line_compiled",
    "reach_threshold", "compile_open", "winning_move",
    "defuses_line_threat",
    "tag_del", "tag_ret", "tag_flip", "tag_draw", "tag_ongoing",
    "tag_move", "tag_opp_discard", "tag_self_discard",
    "refresh_hand_avg_value",
    "refresh_defusable_threat",
)


def feature_count():
    return len(FEATURE_NAMES)
