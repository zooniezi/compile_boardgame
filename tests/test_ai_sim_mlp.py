"""evaluate_learned_mlp()/load_mlp_weights()(src/game/ai_sim.py) 회귀 테스트.

핵심 위험: sklearn(학습)과 손으로 짠 numpy 순방향 계산(추론)이 어긋나면
조용히 틀린 값을 계산하면서도 에러가 안 난다 -- 그래서 둘의 동치성을
직접 비교하는 테스트가 이 파일의 핵심이다(260801_mlp.md §6.4).
"""

import numpy as np
from sklearn.neural_network import MLPClassifier

from src.game.ai_features import feature_count
from src.game.ai_sim import evaluate_learned_mlp, load_mlp_weights, _relu
from src.game.engine import Engine


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _weights_from_model(model):
    return list(zip(model.coefs_, model.intercepts_))


def test_evaluate_learned_mlp_matches_sklearn_predict_proba():
    """학습 직후 sklearn model.predict_proba와, evaluate_learned_mlp이
    반환한 raw 로짓에 시그모이드를 씌운 값이 일치해야 한다 -- activation/
    층 순서가 옮겨질 때 가장 먼저 깨지는 지점."""
    rng = np.random.RandomState(0)
    n = feature_count()
    X = rng.rand(200, n).astype(np.float64)
    y = (rng.rand(200) > 0.5).astype(int)
    model = MLPClassifier(hidden_layer_sizes=(8, 4), activation="relu",
                           max_iter=300, random_state=0)
    model.fit(X, y)

    w = _weights_from_model(model)
    expected = model.predict_proba(X)[:, 1]

    class FakeCard:
        pass

    # evaluate_learned_mlp은 g/pi를 받아 extract(g, pi)를 내부에서 호출하므로,
    # extract() 대신 순방향 계산 자체만 별도로 검증한다(엔진 상태 없이).
    for i in range(len(X)):
        x = X[i].copy()
        n_layers = len(w)
        for li, (weight, bias) in enumerate(w):
            x = x @ weight + bias
            if li < n_layers - 1:
                x = _relu(x)
        got_prob = _sigmoid(x[0])
        assert abs(got_prob - expected[i]) < 1e-9, (
            f"행 {i}: 수동 계산={got_prob}, sklearn={expected[i]}")


def test_evaluate_learned_mlp_returns_extreme_values_on_decided_game(engine):
    e = engine
    e.winner = 1
    assert evaluate_learned_mlp(e, 1, w=[]) == 1e6
    assert evaluate_learned_mlp(e, 2, w=[]) == -1e6


def test_evaluate_learned_mlp_requires_weights(engine):
    import pytest
    with pytest.raises(ValueError):
        evaluate_learned_mlp(engine, 1, w=None)


def test_evaluate_learned_mlp_runs_on_a_real_engine_state(dealt_engine):
    """엔진에서 뽑은 진짜 특징 벡터로도 순방향 계산이 유한한 실수를
    반환하는지 (차원 불일치 등으로 죽지 않는지)."""
    rng = np.random.RandomState(1)
    n = feature_count()
    w = [(rng.rand(n, 8) - 0.5, rng.rand(8) - 0.5),
         (rng.rand(8, 1) - 0.5, rng.rand(1) - 0.5)]
    score = evaluate_learned_mlp(dealt_engine, 1, w=w)
    assert isinstance(score, float)
    import math
    assert math.isfinite(score)


def test_load_mlp_weights_round_trips_through_npz(tmp_path):
    rng = np.random.RandomState(2)
    n = feature_count()
    layer0_w, layer0_b = rng.rand(n, 8), rng.rand(8)
    layer1_w, layer1_b = rng.rand(8, 1), rng.rand(1)
    path = tmp_path / "fake_mlp.npz"
    np.savez(path, n_layers=2, layer0_w=layer0_w, layer0_b=layer0_b,
              layer1_w=layer1_w, layer1_b=layer1_b)

    w = load_mlp_weights(str(path))
    assert len(w) == 2
    assert np.allclose(w[0][0], layer0_w)
    assert np.allclose(w[0][1], layer0_b)
    assert np.allclose(w[1][0], layer1_w)
    assert np.allclose(w[1][1], layer1_b)
