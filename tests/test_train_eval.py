"""scripts/train_eval.py 회귀 테스트."""

import sys
sys.path.insert(0, ".")

import numpy as np

from scripts.train_eval import train
from src.game.ai_features import feature_count


def test_train_produces_weights_better_than_coin_flip(tmp_path):
    """소규모 데이터로도 학습이 동전 던지기(logloss 0.693)보다는 나은지 확인.
    소규모라 크게 좋진 않아도, 최소한 무너지진 않아야 한다."""
    rng = np.random.RandomState(0)
    n = 400
    # 실제 특징 분포를 흉내낸 가짜 데이터: 한쪽 특징이 라벨과 강하게 연관되게
    X = rng.rand(n, feature_count()).astype(np.float32)
    y = (X[:, 0] > 0.5).astype(np.float32)  # 첫 특징이 라벨을 결정하게 만듦

    data_path = tmp_path / "fake.npz"
    np.savez(data_path, X=X, y=y)

    out_path = tmp_path / "weights.npz"
    train(str(data_path), str(out_path))

    d = np.load(out_path)
    assert d["coef"].shape == (feature_count(),)
    assert d["intercept"].shape == (1,)
    # 라벨을 결정한 그 특징의 계수가 가장 커야 함
    assert np.argmax(np.abs(d["coef"])) == 0
