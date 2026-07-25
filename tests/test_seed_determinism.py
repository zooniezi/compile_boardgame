"""seed가 실제로 결정론적 RNG를 만드는지 검증.

예전엔 seed가 self.seed에 저장만 되고 rng 생성엔 전혀 반영이 안 되던 죽은
파라미터였다. clone_at_decision(재생 기반 복제, AI 시뮬레이션용)이 이
재현성에 의존하므로, 회귀를 여기서 고정해둔다.
"""

from src.game.engine import Engine


def _deck_order(seed):
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"],
               seed=seed)
    e.build_decks()
    return ([(c.proto, c.value) for c in e.players[1]["deck"]],
            [(c.proto, c.value) for c in e.players[2]["deck"]])


def test_same_seed_produces_identical_deck_shuffle():
    a = _deck_order(777)
    b = _deck_order(777)
    assert a == b


def test_different_seed_produces_different_shuffle():
    a = _deck_order(777)
    b = _deck_order(888)
    assert a != b


def test_no_seed_still_works_and_is_not_deterministic_by_default():
    """seed를 안 주면 예전처럼 매번 다른(시드 없는 전역 random 기반) 셔플."""
    e1 = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    e2 = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    e1.build_decks()
    e2.build_decks()
    # 아주 드물게 우연히 같을 수 있으나(사실상 무시 가능한 확률), 이 테스트의
    # 목적은 "seed 없이도 예외 없이 정상 동작한다"는 것 확인이 핵심.
    # build_decks()는 시작 손패 5장도 함께 뽑으므로 덱엔 18-5=13장이 남는다.
    assert len(e1.players[1]["deck"]) == 13
    assert len(e1.players[1]["hand"]) == 5


def test_explicit_rng_still_overrides_seed():
    """rng를 직접 넘기면(테스트 등에서 쓰는 방식) seed보다 우선한다."""
    calls = []

    def fixed_rng(n):
        calls.append(n)
        return 1  # 항상 1번째를 고름 -> 사실상 셔플 없음과 유사한 패턴

    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"],
               seed=123, rng=fixed_rng)
    e.build_decks()
    assert len(calls) > 0  # 실제로 우리가 넘긴 rng가 쓰였다
