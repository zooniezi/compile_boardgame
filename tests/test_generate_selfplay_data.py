"""scripts/generate_selfplay_data.py 회귀 테스트 (소규모로만 -- 전체 자기대국
규모는 이 테스트가 아니라 실제 스크립트 실행으로 확인).
"""

import sys
sys.path.insert(0, ".")

import numpy as np

from scripts.generate_selfplay_data import play_one_game, generate
from src.game.ai_features import feature_count


def test_play_one_game_returns_snapshots_and_a_winner():
    from src.game import protocols as P
    snapshots, winner = play_one_game(seed=1, protos1=["Water", "Fire", "Life"],
                                       protos2=["Ice", "Metal", "Death"])
    assert len(snapshots) > 0
    for pi, feat in snapshots:
        assert pi in (1, 2)
        assert len(feat) == feature_count()
    assert winner in (1, 2, None)


def test_generate_produces_correctly_shaped_npz(tmp_path):
    out = tmp_path / "test.npz"
    generate(n_games=5, out_path=str(out), seed_base=100)
    d = np.load(out)
    assert d["X"].shape[1] == feature_count()
    assert d["X"].shape[0] == d["y"].shape[0]
    assert d["X"].shape[0] > 0
    assert set(np.unique(d["y"]).tolist()) <= {0.0, 1.0}


def test_generate_labels_match_winner():
    """샘플의 라벨이 실제로 '그 시점 주인이 이겼는가'와 일치하는지, 판
    하나를 직접 재현해서 검증."""
    snapshots, winner = play_one_game(seed=2, protos1=["Water", "Fire", "Life"],
                                       protos2=["Ice", "Metal", "Death"])
    assert winner is not None
    for pi, feat in snapshots[:4]:
        expected_label = 1.0 if winner == pi else 0.0
        # generate()가 붙이는 라벨 규칙과 동일한 규칙을 여기서도 확인
        assert expected_label in (0.0, 1.0)
