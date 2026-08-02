"""자기대국 데이터로 비선형(소형 MLP) 평가 함수를 학습.

train_eval.py(로지스틱 회귀)와 데이터 포맷/검증 분할 방식(train_test_split
(test_size=0.2, random_state=0))을 완전히 동일하게 맞춘다 -- 같은 데이터로
두 모델을 공정하게 비교하기 위함(260801_mlp.md §3 파일럿이 이 분할로 이미
gen3 데이터에서 -0.0172 개선을 확인함).

학습에만 sklearn.neural_network.MLPClassifier를 쓰고, 추론(src/game/ai_sim.py)
에서는 sklearn을 아예 import하지 않는다 -- coefs_/intercepts_만 뽑아 .npz로
저장해서 순수 numpy 순방향 계산으로 재현한다(ai_sim.py의 evaluate_learned_mlp
참고). activation은 반드시 "relu"로 고정(sklearn 기본값이자 evaluate_learned_mlp
의 하드코딩된 가정) -- 다르게 학습하면 추론이 조용히 틀려진다.

sklearn MLPClassifier는 이진분류 마지막 층에 시그모이드를 내장하지만, 저장은
전체 층의 원본 가중치 그대로 하고, 추론 쪽에서 마지막 시그모이드를 적용하지
않은 raw 로짓을 반환하도록 손으로 구현한다(evaluate_learned()과 계약 일치 --
ai_ismcts.py의 tanh(score/eval_scale) 정규화가 이미 자체 압축을 하므로 이중
압축을 피함).

사용법:
    python3 scripts/train_eval_mlp.py <데이터.npz> <가중치출력.npz> \
        [--hidden 32] [--hidden 64 16] [--alpha 0.0001] [--max-samples N]
"""

import sys
sys.path.insert(0, ".")

import numpy as np
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import log_loss, accuracy_score
from sklearn.model_selection import train_test_split

from src.game.ai_features import feature_count


def train_mlp(data_path, out_path, hidden_layer_sizes=(32,), alpha=0.0001,
              max_iter=500, early_stopping=True, max_samples=None, verbose=True):
    """학습하고 가중치를 저장한다. 호출자가 결과를 프로그램적으로 쓸 수
    있게(예: 은닉층/alpha 스윕 스크립트) 지표를 dict로 반환한다."""
    d = np.load(data_path)
    X, y = d["X"], d["y"]
    assert X.shape[1] == feature_count(), "특징 길이가 ai_features.py와 안 맞음 -- 데이터를 다시 만들어야 함"

    if verbose:
        print(f"전체 샘플: {len(X)}개")

    if max_samples is not None and len(X) > max_samples:
        rng = np.random.RandomState(0)
        idx = rng.choice(len(X), size=max_samples, replace=False)
        X, y = X[idx], y[idx]
        if verbose:
            print(f"표본을 {max_samples}개로 무작위 축소")

    # train_eval.py와 동일한 시드/분할 -- 같은 데이터의 같은 20% 검증셋으로
    # 로지스틱 회귀와 공정 비교하기 위함.
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=0)
    if verbose:
        print(f"학습용: {len(X_train)}개, 검증용: {len(X_val)}개")
        print(f"설정: hidden={hidden_layer_sizes}, alpha={alpha}, "
              f"early_stopping={early_stopping}")

    model = MLPClassifier(
        hidden_layer_sizes=hidden_layer_sizes,
        activation="relu",
        alpha=alpha,
        max_iter=max_iter,
        early_stopping=early_stopping,
        random_state=0,
    )
    model.fit(X_train, y_train)

    p_val = model.predict_proba(X_val)[:, 1]
    ll = log_loss(y_val, p_val)
    acc = accuracy_score(y_val, p_val >= 0.5)
    p_train = model.predict_proba(X_train)[:, 1]
    ll_train = log_loss(y_train, p_train)
    acc_train = accuracy_score(y_train, p_train >= 0.5)

    if verbose:
        print()
        print(f"학습 로그손실/정확도: {ll_train:.4f} / {acc_train*100:.1f}%")
        print(f"검증 로그손실(logloss): {ll:.4f}")
        print(f"검증 정확도(accuracy) : {acc*100:.1f}%")
        print(f"실제 반복 횟수: {model.n_iter_} (max_iter={max_iter})")

    # coefs_[i]: (n_in, n_out) 행렬, intercepts_[i]: (n_out,) 벡터, 층 순서대로.
    # sklearn 없이도 순방향 계산이 가능하도록 전부 numpy 배열로 저장.
    save_kwargs = {"n_layers": len(model.coefs_), "activation": "relu"}
    for i, (w, b) in enumerate(zip(model.coefs_, model.intercepts_)):
        save_kwargs[f"layer{i}_w"] = w
        save_kwargs[f"layer{i}_b"] = b
    np.savez(out_path, **save_kwargs)
    if verbose:
        n_params = sum(w.size + b.size for w, b in zip(model.coefs_, model.intercepts_))
        print()
        print(f"가중치 저장: {out_path} (은닉층 {hidden_layer_sizes}, "
              f"파라미터 {n_params}개, {len(model.coefs_)}개 층)")

    return {
        "val_logloss": ll, "val_accuracy": acc,
        "train_logloss": ll_train, "train_accuracy": acc_train,
        "n_train": len(X_train), "n_val": len(X_val),
        "hidden_layer_sizes": hidden_layer_sizes, "alpha": alpha,
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    data_path, out_path = sys.argv[1], sys.argv[2]

    hidden = []
    if "--hidden" in sys.argv:
        i = sys.argv.index("--hidden") + 1
        while i < len(sys.argv) and not sys.argv[i].startswith("--"):
            hidden.append(int(sys.argv[i]))
            i += 1
    hidden = tuple(hidden) if hidden else (32,)

    alpha = 0.0001
    if "--alpha" in sys.argv:
        alpha = float(sys.argv[sys.argv.index("--alpha") + 1])

    max_samples = None
    if "--max-samples" in sys.argv:
        max_samples = int(sys.argv[sys.argv.index("--max-samples") + 1])

    train_mlp(data_path, out_path, hidden_layer_sizes=hidden, alpha=alpha,
              max_samples=max_samples)
