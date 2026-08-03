"""scripts/generate_rl_selfplay_data.py 회귀 테스트.

`_sample_from_visits`의 인덱싱 버그(v[1]을 다시 인덱싱하려 한 실수 --
언패킹 후 v가 이미 count 그 자체)를 실제 자기대국 파일럿 도중 발견해서
고쳤다 -- 이 파일은 그 회귀를 막는다. 나머지는 `generate()` 전체가
작은 규모로 에러 없이 돌고 npz 스키마가 맞는지 확인하는 통합 스모크
테스트."""

import random

import numpy as np

from scripts.generate_rl_selfplay_data import _sample_from_visits, generate
from src.game.ai_features import feature_count as state_feature_count
from src.game.ai_action_features import feature_count as action_feature_count


def test_sample_from_visits_temperature_zero_returns_argmax():
    visits = [("a", 3), ("b", 10), ("c", 1)]
    assert _sample_from_visits(visits, temperature=0.0) == "b"


def test_sample_from_visits_temperature_one_respects_distribution_shape():
    """온도 1.0이면 대략 방문 비율대로 샘플링돼야 한다(통계적 검증,
    시드 고정)."""
    random.seed(0)
    visits = [("a", 90), ("b", 10)]
    counts = {"a": 0, "b": 0}
    for _ in range(500):
        counts[_sample_from_visits(visits, temperature=1.0)] += 1
    assert counts["a"] > counts["b"]  # 90:10이니 a가 훨씬 자주 나와야 함
    assert counts["b"] > 0  # 그래도 b가 아예 안 나오면 이상함(탐험 없음)


def test_sample_from_visits_single_candidate_always_returns_it():
    assert _sample_from_visits([("only", 5)], temperature=1.0) == "only"
    assert _sample_from_visits([("only", 5)], temperature=0.0) == "only"


def test_generate_end_to_end_smoke(tmp_path):
    """작은 규모(2판, iterations=5)로 자기대국 파이프라인 전체가 에러
    없이 돌고, 저장된 두 npz의 스키마가 맞는지 확인. 오늘 실제로 이
    테스트가 없어서 인덱싱 버그를 파일럿 실행 중에야 발견했다."""
    out_prefix = str(tmp_path / "smoke")
    generate(2, out_prefix,
             eval_weights_path="src/game/data/eval_weights_mlp.npz",
             policy_weights_path="src/game/data/policy_weights.npz",
             iterations=5, temp_moves=5, seed_base=0, n_workers=1)

    policy = np.load(out_prefix + "_policy.npz")
    assert policy["Xs"].shape[1] == state_feature_count()
    assert policy["Xa"].shape[1] == action_feature_count()
    assert len(policy["Xs"]) == len(policy["Xa"]) == len(policy["y"]) == len(policy["group"])
    assert len(policy["Xs"]) > 0

    value = np.load(out_prefix + "_value.npz")
    assert value["X"].shape[1] == state_feature_count()
    assert len(value["X"]) == len(value["y"])
    assert set(np.unique(value["y"]).tolist()) <= {0.0, 1.0}
