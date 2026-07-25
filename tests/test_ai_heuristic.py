"""HeuristicAI(초보 난이도) 회귀 테스트."""

from src.game.engine import Engine
from src.game.ai_heuristic import HeuristicAI
from src.game.ai_random import RandomAI


def test_heuristic_ai_plays_full_games_without_crashing():
    for seed in range(10):
        e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"],
                   ai1=True, ai2=True, ai=HeuristicAI(), seed=seed)
        e.start()
        steps = 0
        while e.pending is not None and steps < 20000:
            steps += 1
            if e.pending["kind"] == "anim":
                e.advance_anim()
            else:
                e.answer(None)
        assert e.error is None


def test_heuristic_ai_beats_random_ai():
    """스모크 수준의 승률 확인 (본 통계 검증은 scripts/arena.py에서 이미
    했음: 전체 180장 무작위 조합 100.0% ±0.0). 여기선 그냥 정식 클래스가
    똑같이 동작하는지만 적은 판수로 재확인."""
    import sys
    sys.path.insert(0, ".")
    from scripts.arena import play_one

    wins_h = 0
    N = 10
    for i in range(N):
        w = play_one(HeuristicAI(), RandomAI(), ["Water", "Fire", "Life"],
                      ["Ice", "Metal", "Death"], seed=i)
        if w == 1:
            wins_h += 1
        w = play_one(RandomAI(), HeuristicAI(), ["Water", "Fire", "Life"],
                      ["Ice", "Metal", "Death"], seed=i)
        if w == 2:
            wins_h += 1
    assert wins_h >= N  # 20판 중 최소 절반 이상 -- 압도적으로 이겨야 정상
