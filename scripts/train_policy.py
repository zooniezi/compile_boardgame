"""자기대국 데이터로 "루트 정책"(학습된 정책) MLP를 학습한다.

train_eval_mlp.py(평가함수, 상태만 입력)와 데이터 포맷/모델 저장 방식은
같지만, 입력이 다르다: 여기선 한 행이 "상태 특징 + 후보 액션 특징"을
이어붙인 벡터이고, 라벨은 "그 후보가 실제로 선택됐는가"(이진)다. 같은
결정(scripts/generate_policy_data.py의 group id)에 속한 후보들이 학습/
검증 셋에 갈라져 섞이면 안 되므로(같은 결정의 후보 몇 개는 train, 몇 개는
val로 새면 정보가 샌 채로 평가하는 셈), 행이 아니라 **그룹(결정) 단위로
분할**한다.

추론(src/game/ai_ismcts_policy.py)에서는 sklearn 없이 순수 numpy 순방향
계산으로 재현한다(train_eval_mlp.py/ai_sim.evaluate_learned_mlp과 동일
원칙). activation은 반드시 "relu"로 고정.

평가지표: row-level logloss/accuracy(이진 분류로서의 성능)뿐 아니라,
top1/top3 정확도(결정 단위로 후보들을 이 모델 점수로 순위 매겼을 때,
실제 선택된 후보가 1등/3등 안에 드는 비율)를 그룹별로 계산한다.

사용법:
    python3 scripts/train_policy.py <데이터.npz> <가중치출력.npz> \
        [--hidden 64] [--alpha 0.0001] [--max-samples-groups N]
"""

import sys
sys.path.insert(0, ".")

import numpy as np
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import log_loss, accuracy_score

from src.game.ai_features import feature_count as state_feature_count
from src.game.ai_action_features import feature_count as action_feature_count


def _group_split(group, test_size=0.2, seed=0):
    """그룹(결정) 단위로 train/val 인덱스를 나눈다 -- 같은 결정의 후보
    행들이 항상 같은 쪽에 붙어 있도록."""
    groups = np.unique(group)
    rng = np.random.RandomState(seed)
    rng.shuffle(groups)
    n_val = max(1, int(len(groups) * test_size))
    val_groups = set(groups[:n_val].tolist())
    val_mask = np.array([g in val_groups for g in group])
    return ~val_mask, val_mask


def _topk_accuracy(scores, y, group, k):
    """그룹별로 scores 내림차순 상위 k개 안에 실제 선택(y==1)이 들어있는
    비율. 한 그룹의 y==1 행은 정확히 하나(라벨 생성 시점에 그렇게 만듦)."""
    order = np.argsort(group, kind="stable")
    scores, y, group = scores[order], y[order], group[order]
    hits, total = 0, 0
    start = 0
    n = len(group)
    while start < n:
        end = start
        while end < n and group[end] == group[start]:
            end += 1
        gs, gy = scores[start:end], y[start:end]
        chosen_idx = int(np.argmax(gy))
        rank_order = np.argsort(-gs)
        topk = set(rank_order[:k].tolist())
        if chosen_idx in topk:
            hits += 1
        total += 1
        start = end
    return hits / max(total, 1)


def train_policy(data_path, out_path, hidden_layer_sizes=(64,), alpha=0.0001,
                  max_iter=500, early_stopping=True, max_samples_groups=None, verbose=True):
    d = np.load(data_path)
    Xs, Xa, y, group = d["Xs"], d["Xa"], d["y"], d["group"]
    assert Xs.shape[1] == state_feature_count(), "상태 특징 길이가 ai_features.py와 안 맞음"
    assert Xa.shape[1] == action_feature_count(), "액션 특징 길이가 ai_action_features.py와 안 맞음"
    X = np.hstack([Xs, Xa])

    if verbose:
        print(f"전체 후보 행: {len(X)}개, 결정(그룹): {len(np.unique(group))}개")

    if max_samples_groups is not None:
        groups_all = np.unique(group)
        if len(groups_all) > max_samples_groups:
            rng = np.random.RandomState(0)
            keep = set(rng.choice(groups_all, size=max_samples_groups, replace=False).tolist())
            mask = np.array([g in keep for g in group])
            X, y, group = X[mask], y[mask], group[mask]
            if verbose:
                print(f"결정을 {max_samples_groups}개로 무작위 축소 (행 {len(X)}개로 축소)")

    train_mask, val_mask = _group_split(group, test_size=0.2, seed=0)
    X_train, y_train = X[train_mask], y[train_mask]
    X_val, y_val, group_val = X[val_mask], y[val_mask], group[val_mask]
    if verbose:
        print(f"학습용: {len(X_train)}행/{len(np.unique(group[train_mask]))}결정, "
              f"검증용: {len(X_val)}행/{len(np.unique(group_val))}결정")
        print(f"설정: hidden={hidden_layer_sizes}, alpha={alpha}, early_stopping={early_stopping}")

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
    top1 = _topk_accuracy(p_val, y_val, group_val, k=1)
    top3 = _topk_accuracy(p_val, y_val, group_val, k=3)

    p_train = model.predict_proba(X_train)[:, 1]
    ll_train = log_loss(y_train, p_train)
    acc_train = accuracy_score(y_train, p_train >= 0.5)

    if verbose:
        print()
        print(f"학습 로그손실/정확도: {ll_train:.4f} / {acc_train*100:.1f}%")
        print(f"검증 로그손실(logloss): {ll:.4f}")
        print(f"검증 행단위 정확도(accuracy): {acc*100:.1f}%")
        print(f"검증 결정단위 top1: {top1*100:.2f}%  top3: {top3*100:.2f}%")
        print(f"실제 반복 횟수: {model.n_iter_} (max_iter={max_iter})")

    save_kwargs = {
        "n_layers": len(model.coefs_), "activation": "relu",
        "state_feature_count": state_feature_count(),
        "action_feature_count": action_feature_count(),
    }
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
        "val_logloss": ll, "val_accuracy": acc, "val_top1": top1, "val_top3": top3,
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
    hidden = tuple(hidden) if hidden else (64,)

    alpha = 0.0001
    if "--alpha" in sys.argv:
        alpha = float(sys.argv[sys.argv.index("--alpha") + 1])

    max_samples_groups = None
    if "--max-samples-groups" in sys.argv:
        max_samples_groups = int(sys.argv[sys.argv.index("--max-samples-groups") + 1])

    train_policy(data_path, out_path, hidden_layer_sizes=hidden, alpha=alpha,
                 max_samples_groups=max_samples_groups)
