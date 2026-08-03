"""아레나(AI 측정 도구) 자체에 대한 회귀 테스트.

아레나가 고장나면 이후 모든 AI 개선 판단이 무의미해지므로, 도구 자체를
최소한으로 검증해둔다. 판수를 아주 작게 잡아 테스트 스위트 속도를 해치지 않는다.
"""

from scripts.arena import arena, play_one
from src.game.ai_random import RandomAI

import pytest


class LazyAI(RandomAI):
    """일부러 약한 AI: 낼 수 있어도 항상 리프레시만 해서 보드에 값을 못 쌓는다."""

    def decide(self, g, req):
        if req.get("type") == "action":
            for a in g.legal_actions(req["chooser"]):
                if a["kind"] == "refresh":
                    return a
        return super().decide(g, req)


def test_play_one_reaches_a_winner():
    w = play_one(RandomAI(), RandomAI(),
                 ["Water", "Fire", "Life"], ["Ice", "Metal", "Death"], seed=42)
    assert w in (1, 2)


def test_same_seed_and_ai_replays_identically():
    """미러 페어가 성립하려면 같은 시드+같은 AI가 같은 판을 재생해야 한다."""
    args = (["Water", "Fire", "Life"], ["Ice", "Metal", "Death"], 7)
    assert play_one(RandomAI(), RandomAI(), *args) == play_one(RandomAI(), RandomAI(), *args)


def test_arena_reports_no_difference_between_identical_ais():
    """같은 AI끼리는 미러 페어가 정확히 1승1패로 갈리므로 50% + 불확실성 0."""
    r = arena(RandomAI, RandomAI, n_pairs=3, progress=False)
    assert r["games"] == 6
    assert r["rate"] == 0.5
    assert r["ci"] == 0.0   # 판 단위로 잘못 계산하면 여기서 0이 아닌 값이 나온다


def test_arena_detects_a_known_skill_gap():
    """알려진 실력차를 실제로 잡아내는지 (도구가 무딘지 확인)."""
    r = arena(RandomAI, LazyAI, n_pairs=5, progress=False)
    assert r["rate"] > 0.8


# ---------------------------------------------------------------------------
# 병렬 실행 (260803_병렬화_plan.md) -- 게임이 결정론적이므로 n_workers를
# 바꿔도 결과가 통계적으로 "비슷"한 게 아니라 승/패/무 집계까지 정확히
# 같아야 한다(쌍 목록을 병렬 분기 전에 먼저 순차로 뽑아두는 설계 덕분).
# ---------------------------------------------------------------------------

def test_arena_parallel_matches_sequential_exactly():
    kwargs = dict(n_pairs=4, seed0=11, progress=False)
    seq = arena(RandomAI, LazyAI, **kwargs, n_workers=1)
    par = arena(RandomAI, LazyAI, **kwargs, n_workers=2)
    assert par["wins_a"] == seq["wins_a"]
    assert par["wins_b"] == seq["wins_b"]
    assert par["draws"] == seq["draws"]
    assert par["rate"] == seq["rate"]
    assert par["ci"] == seq["ci"]


def test_arena_rejects_unpicklable_factory_with_clear_error():
    """람다는 Windows multiprocessing(spawn)에서 워커로 못 넘어간다 --
    스폰 후 알 수 없는 에러 대신 여기서 미리 명확하게 걸려야 한다."""
    with pytest.raises(TypeError, match="피클"):
        arena(lambda: RandomAI(), LazyAI, n_pairs=2, progress=False, n_workers=2)
