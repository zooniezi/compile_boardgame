"""학습된 "루트 정책"의 순수 numpy 추론.

학습(scripts/train_policy.py)은 sklearn.neural_network.MLPClassifier로 하되,
런타임(ai_ismcts.py)에는 sklearn을 아예 끌어들이지 않는다 -- 학습이 끝난
가중치 행렬만 뽑아 여기서 손으로 순방향 계산을 재현한다(src/game/ai_sim.py의
evaluate_learned_mlp과 완전히 동일한 원칙). activation은 반드시 "relu"로
고정(학습 설정과 다르면 조용히 틀린 값을 계산한다).

입력은 상태 특징(ai_features.extract)과 후보 액션 특징(ai_action_features.
extract)을 이어붙인 벡터이고, 출력은 "이 후보가 실제로 선택될 로짓"
(시그모이드 적용 전, 압축 안 된 스칼라) 하나다. 후보 여러 개의 로짓을
모아 softmax를 취하면 이 상태에서의 사전확률 분포 P(a|s)가 된다 --
ai_ismcts.py의 PUCT 선택(_select_puct)이 이 분포를 c_ucb와 함께 쓴다."""

import numpy as np

from src.game.ai_features import extract as extract_state
from src.game.ai_action_features import extract as extract_action
from src.game.ai_prior import score_action

_policy_weights_cache = {}


def load_policy_weights(path):
    """scripts/train_policy.py가 저장한 .npz를 읽어 [(w, b), ...] 층별
    가중치 리스트로 반환한다. 같은 경로는 캐시해서 반복 로드를 피한다."""
    if path not in _policy_weights_cache:
        d = np.load(path)
        n_layers = int(d["n_layers"])
        _policy_weights_cache[path] = [
            (d[f"layer{i}_w"], d[f"layer{i}_b"]) for i in range(n_layers)
        ]
    return _policy_weights_cache[path]


def _relu(x):
    return np.maximum(x, 0.0)


def _forward(x, layers):
    n = len(layers)
    for i, (w, b) in enumerate(layers):
        x = x @ w + b
        if i < n - 1:  # 마지막 층 전까지만 ReLU (sklearn 기본 activation)
            x = _relu(x)
    return float(x[0])


def action_scores(g, pi, actions, w):
    """actions(g.legal_actions(pi) 형태의 후보 리스트)와 같은 순서의 raw
    로짓 리스트를 반환한다(softmax/sigmoid 적용 전). w는 반드시
    load_policy_weights()가 반환한 값이어야 한다."""
    sf = np.asarray(extract_state(g, pi), dtype=np.float64)
    out = []
    for a in actions:
        hs = score_action(g, pi, a)
        af = np.asarray(extract_action(g, pi, a, hs), dtype=np.float64)
        x = np.concatenate([sf, af])
        out.append(_forward(x, w))
    return out
