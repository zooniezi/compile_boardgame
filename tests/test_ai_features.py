"""ai_features.py -- 특징 추출 회귀 테스트.

extract()는 "판 상황 -> 숫자 목록" 변환일 뿐, 여기엔 학습이 전혀 없다.
검증 포인트: (1) 항상 같은 길이, (2) 값이 대략 -1~1 범위, (3) 같은 상황을
두 플레이어 시점에서 보면 my/opp가 정확히 뒤바뀌는 대칭성.
"""

from src.game.engine import Engine
from src.game.ai_random import RandomAI
from src.game.ai_features import extract, FEATURE_NAMES, feature_count


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


def test_hand_potential_reflects_tagged_cards():
    """손패에 제거 태그가 붙은 카드가 있으면 hand_del 특징이 0보다 커야 한다."""
    e = Engine(protocols1=["Hate", "Water", "Fire"], protocols2=["Ice", "Metal", "Death"])
    e.players[1]["hand"] = [e.new_card("Hate", 0, 1)]  # TAGS["Hate_0"] = {"del": {...}}
    x = extract(e, 1)
    idx = FEATURE_NAMES.index("hand_del")
    assert x[idx] > 0


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
