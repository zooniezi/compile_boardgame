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
5. "지금 이 순간"뿐 아니라 "한 수 진행되면 어떻게 되는지"(위협권/한 수 컴파일)
   와 "보드 위 카드의 정체"(라인 맨 위 카드 값, 효과 유무)까지 특징화한다 --
   순수 정적 스냅샷 집계 수치만으로는 놓치는 신호들이다.

이 함수 하나를 자기대국 데이터 생성과 학습된 평가 양쪽에서 반드시 똑같이
써야 한다 -- 서로 다른 특징 추출 로직을 쓰면 학습이 완전히 어긋난다.
특징 개수(FEATURE_NAMES의 길이)가 바뀌면 이전에 학습된 가중치는 전부
재학습해야 한다.
"""

from src.game.rules import COMPILE_THRESHOLD, HAND_SIZE
from src.game.ai_prior import TAGS, hand_class, ongoing_value, persists_when_covered

DECK_TOTAL = 18  # 프로토콜 3개 x 카드 6장 (손패 포함, 초기 덱+손패 합계)
LINE_VALUE_SCALE = 15.0  # 라인 값이 실전에서 대략 이 범위 안에 들어옴
TURN_SCALE = 60.0  # 턴 수 정규화 기준 (그 이상은 그냥 1.0으로 잘라둠)
BOARD_VALUE_SCALE = 45.0  # 보드 전체 앞면 값 합계 기준 (LINE_VALUE_SCALE x 3라인)
EXPOSURE_SCALE = 18.0  # 라인 맨 위 카드 앞면 값 합계 기준 (3라인 x 카드 최댓값 6)


def _other(pi):
    return 2 if pi == 1 else 1


def _clip01(x):
    return max(0.0, min(1.0, x))


def _clip_signed(x):
    """부호 있는 특징(지속효과 부호값처럼 플러스=이득/마이너스=손해)용 --
    _clip01처럼 0~1로 자르면 부호 정보 자체가 사라지므로 [-1, 1]로 자른다."""
    return max(-1.0, min(1.0, x))


def _hand_potential(g, pi):
    """손패를 '몇 장인지'가 아니라 '무엇을 할 수 있는지'로 요약.
    ai_prior.TAGS를 그대로 재사용 -- 새로 만들 게 아니라 이미 있는 지식을
    다시 씀."""
    hand = g.players[pi]["hand"]
    n = len(hand) or 1  # 0으로 나누기 방지
    del_n = ret_n = flip_n = draw_n = ongoing_n = 0
    shift_n = opp_disc_n = disc_cost_n = 0
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
        if tag.get("move"):
            shift_n += 1
        if tag.get("opp_discard"):
            opp_disc_n += 1
        if tag.get("self_discard"):
            disc_cost_n += 1
        total_value += c.value
    return [
        del_n / n, ret_n / n, flip_n / n, draw_n / n, ongoing_n / n,
        (total_value / n) / 6.0,  # 카드 값은 보통 0~6
        shift_n / n, opp_disc_n / n, disc_cost_n / n,
    ]


def _hand_class_totals(g, pi):
    """손패의 "무형 잠재력" 4분류 집계. 일반적인 값/동사 카운트로는 안
    잡히는 신호: 공짜 템포, 제어권 조작, 컴파일 봉쇄력, 손해를 감수하는
    카드."""
    tempo_n = control_n = lock_n = risk_n = 0
    for c in g.players[pi]["hand"]:
        hc = hand_class(c)
        if hc["tempo"]:
            tempo_n += 1
        if hc["control"]:
            control_n += 1
        if hc["lock"]:
            lock_n += 1
        if hc["risk"]:
            risk_n += 1
    return tempo_n, control_n, lock_n, risk_n


def _hand_shape(g, pi):
    """손패의 최댓값/최솟값/효과카드(값<=1) 수 -- 평균값만으로는 안 보이는
    손패의 '모양'(예: 극단값 카드를 쥐고 있는지)을 잡는다."""
    hand = g.players[pi]["hand"]
    if not hand:
        return 0, 0, 0
    max_v = max(c.value for c in hand)
    min_v = min(c.value for c in hand)
    fx_n = sum(1 for c in hand if c.value <= 1)
    return max_v, min_v, fx_n


def _playable_face_up_count(g, pi):
    """손패 중 지금 앞면으로 낼 수 있는 곳이 하나라도 있는 카드 수."""
    n = 0
    for c in g.players[pi]["hand"]:
        for line in (1, 2, 3):
            if g.can_play_face_up(pi, c, line):
                n += 1
                break
    return n


def _face_up_spread(g, pi):
    """손패 카드를 앞면으로 받아줄 수 있는, 서로 다른 라인의 수."""
    n = 0
    for line in (1, 2, 3):
        for c in g.players[pi]["hand"]:
            if g.can_play_face_up(pi, c, line):
                n += 1
                break
    return n


def _live_tops(g, pi):
    """라인 맨 위가 앞면이면서 실제로 효과가 달린(빈 정의가 아닌) 카드 수."""
    n = 0
    for line in (1, 2, 3):
        top = g.top_card(pi, line)
        if top and top.face_up and top.definition:
            n += 1
    return n


def _board_value(g, pi):
    """보드 위(3라인 전체) 앞면 카드 값 합계."""
    total = 0
    for line in (1, 2, 3):
        for c in g.players[pi]["stacks"][line]:
            if c.face_up:
                total += c.value
    return total


def _board_facedown_count(g, pi):
    """보드 위(3라인 전체) 뒷면 카드 장수. 라인별 뒷면 수는 이미 라인
    블록에 있지만, "판 전체적으로 뒷면이 얼마나 깔려있나"는 그 3개를
    모델이 스스로 더해야만 알 수 있던 신호라 전역 특징으로 따로 낸다."""
    n = 0
    for line in (1, 2, 3):
        for c in g.players[pi]["stacks"][line]:
            if not c.face_up:
                n += 1
    return n


def _exposure(g, pi):
    """pi의 라인 맨 위 카드들의 텍스처: 앞면 값 합계, 지속효과(ongoing) 카드
    수, 뒷면 맨 위 카드 수, 그리고 지속효과의 부호값(플러스=이득/마이너스=
    손해)을 "지금 활성"과 "덮여도 지속"으로 나눈 것. 전부 공개 정보
    (맨 위 카드는 항상 관측 가능, 덮인 카드도 앞면이면 정체는 공개 정보)."""
    val, ongoing, fd_tops = 0, 0, 0
    active_value = covered_value = 0.0
    for line in (1, 2, 3):
        top = g.top_card(pi, line)
        if top:
            if top.face_up:
                val += top.value
                tag = TAGS.get(f"{top.proto}_{top.value}", {})
                if tag.get("ongoing"):
                    ongoing += 1
                    active_value += ongoing_value(g, top)
            else:
                fd_tops += 1
        # 맨 위(uncovered)를 뺀 나머지 -- 덮여도 지속되는 top 밴드 부채/자산만.
        for c in g.players[pi]["stacks"][line][:-1]:
            if c.face_up and persists_when_covered(c):
                covered_value += ongoing_value(g, c)
    return val, ongoing, fd_tops, active_value, covered_value


def _best_swing(g, pi, o):
    """지금 당장 내 제거 카드로 칠 수 있는 상대의 가장 두꺼운 라인 맨 위
    카드 값 (뒷면이면 정체 불명이므로 2로 보수적으로 가정). 손패에 제거
    카드가 아예 없으면 0 -- 손패 잠재력과 보드 위 실제 표적을 연결하는
    교차 특징."""
    has_removal = any(
        TAGS.get(f"{c.proto}_{c.value}", {}).get("del") for c in g.players[pi]["hand"])
    if not has_removal:
        return 0
    best = 0
    for line in (1, 2, 3):
        top = g.top_card(o, line)
        if top:
            v = top.value if top.face_up else 2
            if v > best:
                best = v
    return best


def _line_block(g, pi, o, line, hand_max):
    """라인 하나를 특징 몇 개로 요약 (pi 시점)."""
    T = COMPILE_THRESHOLD
    mv, ov = g.line_value(pi, line), g.line_value(o, line)
    my_compiled = g.players[pi]["compiled"][line]
    opp_compiled = g.players[o]["compiled"][line]
    my_fd = sum(1 for c in g.players[pi]["stacks"][line] if not c.face_up)
    opp_fd = sum(1 for c in g.players[o]["stacks"][line] if not c.face_up)
    opp_top = g.top_card(o, line)
    my_top = g.top_card(pi, line)
    return [
        _clip01(mv / LINE_VALUE_SCALE),
        _clip01(ov / LINE_VALUE_SCALE),
        _clip01((mv - ov + LINE_VALUE_SCALE) / (2 * LINE_VALUE_SCALE)),  # -15~15 -> 0~1
        1.0 if my_compiled else 0.0,
        1.0 if opp_compiled else 0.0,
        1.0 if (not my_compiled and mv >= T and mv > ov) else 0.0,
        1.0 if (not opp_compiled and ov >= T and ov > mv) else 0.0,
        min(my_fd, 6) / 6.0,
        min(opp_fd, 6) / 6.0,
        # 내 뒷면 카드의 실제 값 합계 -- 뒷면은 화면 표시일 뿐, 소유자 본인은
        # 항상 진짜 값을 안다(card.py: face_up과 무관하게 value는 항상 진짜
        # 값). determinize()도 내 카드 정체는 안 섞으므로 탐색 중에도 안전한
        # 정보다. 상대 뒷면은 진짜로 모르는 정보라 값을 특징화하지 않는다
        # (opp_facedown은 개수만).
        _clip01(sum(c.value for c in g.players[pi]["stacks"][line] if not c.face_up)
                / LINE_VALUE_SCALE),
        # 위협권(brew): 아직 컴파일 확정은 아니지만 임계값에 근접(-2) + 우세
        1.0 if (not my_compiled and mv >= T - 2 and mv > ov) else 0.0,
        1.0 if (not opp_compiled and ov >= T - 2 and ov > mv) else 0.0,
        # 이 라인에 쌓인 카드 장수 (양쪽) -- 값이 아니라 "규모" 자체의 신호
        min(len(g.players[pi]["stacks"][line]), 5) / 5.0,
        min(len(g.players[o]["stacks"][line]), 5) / 5.0,
        # 한 수 컴파일: 내 손패 최댓값 한 장 / 상대는 뒷면 카드 한 장이면 컴파일권
        # (뒷면 값은 보통 2지만 Darkness_2가 이 스택에 있으면 4 -- 고정값
        # 대신 반드시 g.facedown_value_in_stack()으로 실제 값을 구해야 함).
        1.0 if (not my_compiled and mv + hand_max >= T and mv + hand_max > ov) else 0.0,
        1.0 if (not opp_compiled
                and ov + g.facedown_value_in_stack(g.players[o]["stacks"][line]) >= T
                and ov + g.facedown_value_in_stack(g.players[o]["stacks"][line]) > mv) else 0.0,
        # 라인 맨 위 카드의 정체 (앞면이면 값, 상대는 뒷면 여부도)
        (opp_top.value / 6.0) if (opp_top and opp_top.face_up) else 0.0,
        1.0 if (opp_top and not opp_top.face_up) else 0.0,
        (my_top.value / 6.0) if (my_top and my_top.face_up) else 0.0,
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

    x += [
        1.0 if g.cant_compile[pi] else 0.0,
        1.0 if g.cant_compile[o] else 0.0,
        g.lines_winning_count(pi) / 3.0,
        g.lines_winning_count(o) / 3.0,
        1.0 if len(op["hand"]) <= 1 else 0.0,  # 상대의 다음 행동이 사실상 리프레시로 강제됨
    ]

    hand_max, hand_min, hand_fx = _hand_shape(g, pi)
    x += [hand_max / 6.0, hand_min / 6.0, _clip01(hand_fx / HAND_SIZE)]
    x += [
        _clip01(_playable_face_up_count(g, pi) / HAND_SIZE),
        _clip01(_face_up_spread(g, pi) / 3.0),
    ]
    x += [_clip01(_live_tops(g, pi) / 3.0), _clip01(_live_tops(g, o) / 3.0)]

    my_exp, my_ongoing, _my_fd_tops, my_active_value, my_covered_value = _exposure(g, pi)
    opp_exp, opp_ongoing, opp_fd_tops, opp_active_value, opp_covered_value = _exposure(g, o)
    x += [_clip01(my_exp / EXPOSURE_SCALE), _clip01(opp_exp / EXPOSURE_SCALE),
          _clip01(opp_fd_tops / 3.0)]
    x += [_clip01(my_ongoing / 3.0), _clip01(opp_ongoing / 3.0)]

    x += [_clip01(_board_value(g, pi) / BOARD_VALUE_SCALE),
          _clip01(_board_value(g, o) / BOARD_VALUE_SCALE)]

    x.append(_clip01(_best_swing(g, pi, o) / 6.0))

    tempo_n, control_n, lock_n, risk_n = _hand_class_totals(g, pi)
    x += [_clip01(tempo_n / HAND_SIZE), _clip01(control_n / HAND_SIZE),
          _clip01(lock_n / HAND_SIZE), _clip01(risk_n / HAND_SIZE)]

    # 지속효과 부호값(플러스=이득/마이너스=손해). 불리언 존재 카운트
    # (my_board_ongoing 등)만으론 Rigid_7(손해)과 Metal_0(이득)이 구별이
    # 안 됐던 문제의 해결. 부호 있는 값이라 클립 없이 스케일만 맞춘다
    # (다른 신호처럼 0~1로 자르면 부호 정보가 죽음, _clip_signed로 [-1,1]만 보장).
    x += [_clip_signed((my_active_value + my_covered_value) / 6.0),
          _clip_signed((opp_active_value + opp_covered_value) / 6.0),
          _clip_signed(my_active_value / 6.0), _clip_signed(opp_active_value / 6.0),
          _clip_signed(my_covered_value / 6.0), _clip_signed(opp_covered_value / 6.0)]

    # 보드 전체 뒷면 카드 수(라인 합산).
    x += [_clip01(_board_facedown_count(g, pi) / 6.0), _clip01(_board_facedown_count(g, o) / 6.0)]

    # 라인은 "내가 유리한 순서"로 정렬 -- 번호 자체는 의미가 없으므로.
    lines_sorted = sorted((1, 2, 3),
                          key=lambda l: g.line_value(pi, l) - g.line_value(o, l),
                          reverse=True)
    for line in lines_sorted:
        x += _line_block(g, pi, o, line, hand_max)

    return x


# 각 인덱스가 뭘 뜻하는지 -- 디버깅/해석용. extract()와 반드시 같은 순서로
# 유지해야 한다.
FEATURE_NAMES = (
    ["my_hand", "opp_hand", "my_deck", "opp_deck", "my_discard", "opp_discard",
     "my_compiled_n", "opp_compiled_n", "control", "my_turn", "turn_count"]
    + ["hand_del", "hand_ret", "hand_flip", "hand_draw", "hand_ongoing", "hand_avg_value",
       "hand_shift", "hand_opp_discard", "hand_disc_cost"]
    + ["my_cant_compile", "opp_cant_compile", "my_lines_winning", "opp_lines_winning",
       "opp_refresh_imminent"]
    + ["hand_max", "hand_min", "hand_fx"]
    + ["playable_face_up", "face_up_spread"]
    + ["my_live_tops", "opp_live_tops"]
    + ["my_exposure", "opp_exposure", "opp_facedown_tops"]
    + ["my_board_ongoing", "opp_board_ongoing"]
    + ["my_board_value", "opp_board_value"]
    + ["best_swing"]
    + ["hand_tempo", "hand_control", "hand_lock", "hand_risk"]
    + ["my_ongoing_signed", "opp_ongoing_signed",
       "my_active_ongoing_signed", "opp_active_ongoing_signed",
       "my_covered_persistent_signed", "opp_covered_persistent_signed"]
    + ["my_facedown_count", "opp_facedown_count"]
    + [f"line{rank}_{name}" for rank in (1, 2, 3) for name in
       ("my_val", "opp_val", "diff", "my_compiled", "opp_compiled",
        "my_ready", "opp_ready", "my_facedown", "opp_facedown",
        "my_facedown_value",
        "my_brew", "opp_brew", "my_stack_size", "opp_stack_size",
        "my_one_move", "opp_one_move",
        "opp_top_val", "opp_top_facedown", "my_top_val")]
)


def feature_count():
    return len(FEATURE_NAMES)


def expand_features(x):
    """2차 교차항 확장: 원본 벡터 뒤에 모든 특징쌍의 곱(제곱항 포함, 상삼각
    전체)을 이어붙인다. 로지스틱 회귀는 원래 특징 간 상호작용을 스스로
    못 찾는데, 이렇게 미리 곱해서 넣어주면 "카드 우위가 크면서 동시에
    제어권도 쥐고 있을 때" 같은 조합 효과까지 학습할 수 있다.

    출력 길이: N + N*(N+1)/2 (지금 N=97이면 97 + 97*98/2 = 4850)."""
    n = len(x)
    out = list(x)
    for i in range(n):
        xi = x[i]
        for j in range(i, n):
            out.append(xi * x[j])
    return out


def expanded_feature_count():
    n = feature_count()
    return n + n * (n + 1) // 2


def expand_features_batch(X):
    """expand_features()와 정확히 같은 변환을 행렬 전체(numpy 2D 배열,
    shape (n_samples, n_features))에 벡터화해서 적용한다 -- 자기대국
    데이터셋처럼 수만~수십만 행을 확장할 때, 파이썬 반복문으로 행마다
    expand_features()를 부르면 감당 안 될 만큼 느리다(특징 97개 기준
    행당 곱셈 4753번, 30만 행이면 10억 번 이상). numpy 브로드캐스팅으로
    같은 계산을 훨씬 빠르게 한다.

    `np.triu_indices(n)`가 만드는 (i,j) 순서가 expand_features()의
    `for i: for j in range(i,n)` 순서와 정확히 같다는 게 이 함수의
    정확성 근거다(둘 다 i<=j 상삼각을 행 우선으로 순회) -- 이 동치성은
    test_ai_features.py에서 직접 검증한다."""
    import numpy as np
    X = np.asarray(X)  # 호출자가 준 dtype 유지(대개 float32) -- 대량 학습 시 메모리 절약
    n = X.shape[1]
    i_idx, j_idx = np.triu_indices(n)
    cross = X[:, i_idx] * X[:, j_idx]
    return np.hstack([X, cross])
