from src.game import draftpool as DraftPool
from src.game import protocols as Protocols


def test_count_for_default_is_all_45():
    assert DraftPool.count_for(None) == 45
    assert DraftPool.count_for({}) == 45
    assert DraftPool.count_for([]) == 45


def test_count_for_specific_sets():
    assert DraftPool.count_for(["main1"]) == 12
    assert DraftPool.count_for(["aux1"]) == 3
    assert DraftPool.count_for(["main1", "aux1"]) == 15
    assert DraftPool.count_for({"main2": True, "aux2": True}) == 15


def test_sanitize_all_sets_collapses_to_none():
    opts = {"sets": list(Protocols.SET_ORDER), "mode": "standard"}
    assert DraftPool.sanitize(opts) is None


def test_sanitize_too_small_selection_falls_back_to_default():
    opts = {"sets": ["aux1", "aux2"], "mode": "standard"}
    assert DraftPool.sanitize(opts) is None


def test_sanitize_valid_subset_kept():
    opts = {"sets": ["main1", "aux1"], "mode": "standard"}
    result = DraftPool.sanitize(opts)
    assert result == {"sets": ["main1", "aux1"], "mode": "standard"}


def test_sanitize_blind_mode_kept_even_with_default_sets():
    opts = {"sets": [], "mode": "blind"}
    assert DraftPool.sanitize(opts) == {"sets": None, "mode": "blind"}


def test_sanitize_rejects_non_dict():
    assert DraftPool.sanitize(None) is None
    assert DraftPool.sanitize("garbage") is None


def test_sanitize_dedupes_and_ignores_invalid_set_names():
    opts = {"sets": ["main1", "main1", "not_a_set", "aux1"], "mode": "standard"}
    result = DraftPool.sanitize(opts)
    assert result["sets"] == ["main1", "aux1"]


def test_build_default_returns_full_catalog():
    pool = DraftPool.build(None)
    assert len(pool) == 45
    assert set(pool) == set(Protocols.PROTOCOL_LIST)


def test_build_restricted_to_one_set():
    pool = DraftPool.build({"sets": ["main1"]})
    assert len(pool) == 12
    assert all(Protocols.SET_OF[p] == "main1" for p in pool)


def test_build_falls_back_to_full_catalog_when_too_small():
    pool = DraftPool.build({"sets": ["aux1"]})
    assert len(pool) == 45


def test_build_blind_mode_shuffles_and_truncates():
    pool = DraftPool.build({"mode": "blind"})
    assert len(pool) == DraftPool.BLIND_SIZE
    assert len(set(pool)) == DraftPool.BLIND_SIZE  # 중복 없이 서로 다른 프로토콜
    assert all(p in Protocols.PROTOCOL_LIST for p in pool)


def test_build_blind_mode_respects_set_restriction():
    pool = DraftPool.build({"sets": ["main1", "aux1"], "mode": "blind"})
    assert len(pool) == DraftPool.BLIND_SIZE
    assert all(Protocols.SET_OF[p] in ("main1", "aux1") for p in pool)
