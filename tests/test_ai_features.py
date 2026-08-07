"""ai_features.py -- 특징 추출 회귀 테스트.

extract()는 "판 상황 -> 숫자 목록" 변환일 뿐, 여기엔 학습이 전혀 없다.
검증 포인트: (1) 항상 같은 길이, (2) 값이 대략 -1~1 범위, (3) 같은 상황을
두 플레이어 시점에서 보면 my/opp가 정확히 뒤바뀌는 대칭성.
"""

from src.game.engine import Engine
from src.game.ai_random import RandomAI
import numpy as np

from src.game.ai_features import (
    extract, FEATURE_NAMES, feature_count, LINE_VALUE_SCALE,
    expand_features, expanded_feature_count, expand_features_batch,
)


def _driven_engine(seed, steps=200):
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"],
               ai1=True, ai2=True, ai=RandomAI(), seed=seed)
    e.start()
    n = 0
    while e.pending is not None and n < steps:
        n += 1
        if e.pending["kind"] == "anim":
            e.advance_anim()
        else:
            e.answer(None)
    return e


def test_feature_count_matches_names():
    assert feature_count() == len(FEATURE_NAMES)


def test_feature_count_is_109():
    """특징 확장(위협권/한 수 컴파일/라인 맨 위 정체/cantCompile/liveTops/
    라인당 스택 장수/내 뒷면 카드 실제 값/손패 잠재력 4분류/지속효과 부호값/
    전역 뒷면 카드 수 등) 이후 기대 차원 수. 실수로 특징이 빠지거나 중복
    추가되면 여기서 걸린다."""
    assert feature_count() == 109


def test_extract_always_returns_fixed_length_and_bounded_values():
    for seed in range(15):
        e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"],
                   ai1=True, ai2=True, ai=RandomAI(), seed=seed)
        e.start()
        n = 0
        while e.pending is not None and n < 150:
            n += 1
            if e.pending["kind"] == "anim":
                e.advance_anim()
            else:
                x1 = extract(e, 1)
                x2 = extract(e, 2)
                assert len(x1) == len(FEATURE_NAMES)
                assert len(x2) == len(FEATURE_NAMES)
                assert all(-1.0001 <= v <= 1.0001 for v in x1)
                assert all(-1.0001 <= v <= 1.0001 for v in x2)
                e.answer(None)


def test_extract_is_symmetric_between_perspectives():
    """같은 순간을 p1 시점/p2 시점에서 보면 my/opp가 정확히 뒤바뀌어야 한다."""
    e = _driven_engine(seed=7, steps=50)
    x1 = extract(e, 1)
    x2 = extract(e, 2)
    idx = {name: i for i, name in enumerate(FEATURE_NAMES)}

    assert x1[idx["my_hand"]] == x2[idx["opp_hand"]]
    assert x1[idx["opp_hand"]] == x2[idx["my_hand"]]
    assert x1[idx["my_deck"]] == x2[idx["opp_deck"]]
    assert x1[idx["my_compiled_n"]] == x2[idx["opp_compiled_n"]]
    # 제어권: 한쪽이 1이면 다른 쪽은 -1, 둘 다 0(무승부/미지정)일 수도 있음
    assert x1[idx["control"]] == -x2[idx["control"]]
    # 신규 특징들도 시점이 뒤바뀌면 my/opp가 정확히 뒤바뀌어야 한다
    assert x1[idx["my_cant_compile"]] == x2[idx["opp_cant_compile"]]
    assert x1[idx["my_lines_winning"]] == x2[idx["opp_lines_winning"]]
    assert x1[idx["my_live_tops"]] == x2[idx["opp_live_tops"]]
    assert x1[idx["my_board_value"]] == x2[idx["opp_board_value"]]
    assert x1[idx["my_exposure"]] == x2[idx["opp_exposure"]]
    # 라인 정렬 순서가 시점마다 달라질 수 있어 라인별로 직접 비교할 수 없다 --
    # 정렬에 무관한 "3라인 합계"로 대칭성을 확인한다.
    my_stack_sum = sum(x1[idx[f"line{r}_my_stack_size"]] for r in (1, 2, 3))
    opp_stack_sum_from_p2 = sum(x2[idx[f"line{r}_opp_stack_size"]] for r in (1, 2, 3))
    assert abs(my_stack_sum - opp_stack_sum_from_p2) < 1e-9


def test_hand_potential_reflects_tagged_cards():
    """손패에 제거 태그가 붙은 카드가 있으면 hand_del 특징이 0보다 커야 한다."""
    e = Engine(protocols1=["Hate", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    e.players[1]["hand"] = [e.new_card("Hate", 0, 1)]  # TAGS["Hate_0"] = {"del": {...}}
    x = extract(e, 1)
    idx = FEATURE_NAMES.index("hand_del")
    assert x[idx] > 0


def test_hand_class_features_reflect_tagged_cards():
    """손패 잠재력 4분류(tempo/control/lock/risk) 태그가 붙은 카드가
    손패에 있으면 해당 특징이 0보다 커야 한다."""
    e = Engine(protocols1=["Water", "Speed", "Rigid"], protocols2=["Ice", "Metal", "Death"])
    e.players[1]["hand"] = [
        e.new_card("Speed", 0, 1),   # tempo(extra_play 자동 추론)
        e.new_card("Water", 2, 1),   # control(수동 오버라이드)
        e.new_card("Rigid", 7, 1),   # risk(ongoing<0 자동 추론)
    ]
    x = extract(e, 1)
    idx = {name: i for i, name in enumerate(FEATURE_NAMES)}
    assert x[idx["hand_tempo"]] > 0
    assert x[idx["hand_control"]] > 0
    assert x[idx["hand_risk"]] > 0
    assert x[idx["hand_lock"]] == 0  # 이 손패엔 lock 카드가 없음


def test_signed_ongoing_features_distinguish_liability_from_asset():
    """불리언 존재 카운트(my_board_ongoing)만으론 손해(Rigid_7)와
    이득(Metal_0)이 구별 안 됐던 문제의 해결. 같은 my_board_ongoing=1
    이어도 부호값 특징은 서로 반대 부호여야 한다."""
    e_bad = Engine(protocols1=["Rigid", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    rigid7 = e_bad.new_card("Rigid", 7, 1)
    rigid7.face_up = True
    e_bad.players[1]["stacks"][1].append(rigid7)
    x_bad = extract(e_bad, 1)

    e_good = Engine(protocols1=["Metal", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    metal0 = e_good.new_card("Metal", 0, 1)
    metal0.face_up = True
    e_good.players[1]["stacks"][1].append(metal0)
    x_good = extract(e_good, 1)

    idx = {name: i for i, name in enumerate(FEATURE_NAMES)}
    # 기존 불리언 카운트로는 둘 다 "지속효과 하나 있음"으로 동일하게 잡힘.
    assert x_bad[idx["my_board_ongoing"]] == x_good[idx["my_board_ongoing"]]
    # 부호값 특징은 서로 반대 부호여야 함.
    assert x_bad[idx["my_ongoing_signed"]] < 0
    assert x_good[idx["my_ongoing_signed"]] > 0
    assert x_bad[idx["my_active_ongoing_signed"]] < 0
    assert x_good[idx["my_active_ongoing_signed"]] > 0


def test_board_facedown_count_sums_across_all_lines():
    """라인별로 흩어진 뒷면 카드 수를 전역 특징 하나로 합산."""
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    for line in (1, 2, 3):
        e.players[1]["stacks"][line].append(e.new_card("Water", 0, 1))  # 기본 뒷면
    x = extract(e, 1)
    idx = FEATURE_NAMES.index("my_facedown_count")
    assert x[idx] == 3 / 6.0


def test_opp_one_move_uses_real_facedown_value_not_fixed_two():
    """회귀 테스트: 상대 라인에 Darkness_2(facedownValueThisStack=4)가
    있으면 '뒷면 한 장으로 컴파일' 판정이 고정값 2가 아니라 실제 값
    4를 써야 한다."""
    from src.game.rules import COMPILE_THRESHOLD
    from src.game.ai_features import _line_block

    def opp_one_move(with_darkness2):
        e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Darkness", "Metal", "Death"])
        if with_darkness2:
            d2 = e.new_card("Darkness", 2, 2)
            d2.face_up = True
            e.players[2]["stacks"][1].append(d2)
        # 라인 값이 딱 (COMPILE_THRESHOLD - 4): 뒷면 보정 없이(2)는 컴파일권
        # 미달, Darkness_2 보정(4)이 있으면 성립하는 경계.
        filler = e.new_card("Metal", COMPILE_THRESHOLD - 4, 2)
        filler.face_up = True
        e.players[2]["stacks"][1].append(filler)
        block = _line_block(e, 1, 2, 1, hand_max=0)
        return block[FEATURE_NAMES.index("line1_opp_one_move") - FEATURE_NAMES.index("line1_my_val")]

    assert opp_one_move(with_darkness2=False) == 0.0
    assert opp_one_move(with_darkness2=True) == 1.0


def test_lines_are_sorted_by_my_advantage_not_by_line_number():
    """1등 라인 블록이 실제로 가장 유리한 라인의 값을 담고 있어야 한다."""
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    # 라인3을 가장 유리하게 만듦 (라인 번호와 등수가 다르게)
    c = e.new_card("Life", 6, 1)
    c.face_up = True
    e.players[1]["stacks"][3].append(c)
    x = extract(e, 1)
    rank1_my_val = x[FEATURE_NAMES.index("line1_my_val")]
    rank3_my_val = x[FEATURE_NAMES.index("line3_my_val")]
    assert rank1_my_val > rank3_my_val


def test_my_facedown_value_reflects_true_value_not_just_count():
    """뒷면 카드라도 소유자 시점에서는 진짜 값을 아는 정보라, 값이 큰
    뒷면 카드를 쌓으면 my_facedown_value가 그만큼 커져야 한다. 앞면
    카드는(이미 my_val에 반영되니) 이 특징에 이중으로 안 잡혀야 한다."""
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    fd = e.new_card("Water", 6, 1)  # 뒷면 유지, 값 6
    e.players[1]["stacks"][1].append(fd)
    fu = e.new_card("Fire", 6, 1)
    fu.face_up = True  # 앞면 -- my_facedown_value에는 안 잡혀야 함
    e.players[1]["stacks"][2].append(fu)
    x = extract(e, 1)
    idx = {name: i for i, name in enumerate(FEATURE_NAMES)}
    fd_line_val = sum(x[idx[f"line{r}_my_facedown_value"]] for r in (1, 2, 3))
    assert abs(fd_line_val - 6.0 / LINE_VALUE_SCALE) < 1e-9


def test_expand_features_length_matches_formula():
    x = [0.0] * feature_count()
    expanded = expand_features(x)
    n = feature_count()
    assert len(expanded) == n + n * (n + 1) // 2
    assert len(expanded) == expanded_feature_count()


def test_expand_features_prefix_is_original_and_includes_cross_terms():
    x = [2.0, 3.0, 5.0]
    expanded = expand_features(x)
    # 앞부분은 원본 그대로
    assert expanded[:3] == [2.0, 3.0, 5.0]
    # 그 뒤로 i<=j 상삼각 전체(제곱항 포함): 2*2, 2*3, 2*5, 3*3, 3*5, 5*5
    assert expanded[3:] == [4.0, 6.0, 10.0, 9.0, 15.0, 25.0]


def test_expand_features_batch_matches_row_by_row_expand_features():
    """train_eval.py는 대량 데이터를 벡터화된 expand_features_batch()로
    확장하고, evaluate_learned()는 추론 시 단일 벡터를 expand_features()로
    확장한다 -- 둘의 열 순서가 어긋나면 학습된 가중치가 추론에서 엉뚱한
    특징에 곱해진다. 이 동치성이 그 정확성의 근거다."""
    rng = np.random.RandomState(0)
    X = rng.rand(5, feature_count())
    batch_result = expand_features_batch(X)
    for i in range(5):
        row_result = np.array(expand_features(X[i].tolist()))
        assert np.allclose(batch_result[i], row_result)


def test_best_swing_is_zero_without_removal_cards():
    """손패에 제거 태그 카드가 없으면 best_swing은 항상 0이어야 한다."""
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    e.players[1]["hand"] = [e.new_card("Water", 2, 1)]  # 제거 태그 없음
    c = e.new_card("Metal", 6, 2)
    c.face_up = True
    e.players[2]["stacks"][1].append(c)
    x = extract(e, 1)
    assert x[FEATURE_NAMES.index("best_swing")] == 0.0


def test_best_swing_picks_the_fattest_face_up_target():
    """제거 카드가 있으면, 상대 라인 맨 위 앞면 카드 중 가장 값이 큰 걸 골라야 한다."""
    e = Engine(protocols1=["Hate", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    e.players[1]["hand"] = [e.new_card("Hate", 0, 1)]  # TAGS["Hate_0"] = {"del": ...}
    small = e.new_card("Ice", 2, 2)
    small.face_up = True
    e.players[2]["stacks"][1].append(small)
    big = e.new_card("Metal", 6, 2)
    big.face_up = True
    e.players[2]["stacks"][2].append(big)
    x = extract(e, 1)
    assert x[FEATURE_NAMES.index("best_swing")] == 6.0 / 6.0


def test_line_brew_and_one_move_signals():
    """위협권(brew)과 '한 수면 컴파일' 신호가 조건대로 켜지는지 확인."""
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    # 라인1에 상대가 값 9(= COMPILE_THRESHOLD-1)를 앞면으로 쌓아 위협권(brew)만
    # 켜지고("ready"는 아직 아님) "한 수 컴파일"(ov+2>=10)도 같이 켜지게 만든다.
    c = e.new_card("Ice", 6, 2)
    c.face_up = True
    e.players[2]["stacks"][1].append(c)
    c2 = e.new_card("Metal", 3, 2)
    c2.face_up = True
    e.players[2]["stacks"][1].append(c2)
    x = extract(e, 1)  # pi=1 시점이므로 이건 "상대(opp)" 쪽 신호
    idx = {name: i for i, name in enumerate(FEATURE_NAMES)}
    # 라인 정렬 순서를 몰라도, 세 라인 중 하나는 opp_brew/opp_one_move가 켜져야 한다
    assert any(x[idx[f"line{r}_opp_brew"]] == 1.0 for r in (1, 2, 3))
    assert any(x[idx[f"line{r}_opp_one_move"]] == 1.0 for r in (1, 2, 3))
    assert not any(x[idx[f"line{r}_opp_ready"]] == 1.0 for r in (1, 2, 3))
