"""자기대국 데이터(generate_selfplay_data.py의 결과물)로 평가 함수를 학습.

로지스틱 회귀부터 시작 -- 특징 벡터 -> "이 상황에서 이길 확률" 하나.
학습이 끝나면 가중치를 .npz로 저장해서 ai_sim.py의 evaluate_learned()가
읽어 쓸 수 있게 한다.

--expand를 주면 학습 직전에 ai_features.expand_features()로 2차 교차항
(제곱항 포함 상삼각 전체)까지 확장한 벡터로 학습한다 -- 저장되는 데이터
(.npz)는 항상 원본 특징 그대로 두고(재사용 가능하게), 확장은 학습
시점에만 메모리에서 수행한다. plain/expand 두 모델을 같은 자기대국
데이터로 비교할 수 있게 하려는 설계다(ai_train_pipeline.md 참고).

--C/--penalty/--l1-ratio/--solver로 정규화 강도/방식을 조절할 수 있다
(ai_regularization.md 참고) -- 기본값(C=1.0, L2, lbfgs)은 sklearn
기본값 그대로라 지금까지의 결과와 호환된다.

사용법:
    python3 scripts/train_eval.py <데이터.npz> <가중치출력.npz> [--expand] \
        [--max-samples N] [--C 값] [--penalty l2|l1|elasticnet] \
        [--l1-ratio 값] [--solver lbfgs|saga|liblinear]
"""

import sys
sys.path.insert(0, ".")

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, accuracy_score
from sklearn.model_selection import train_test_split

from src.game.ai_features import FEATURE_NAMES, feature_count, expand_features_batch


def train(data_path, out_path, expand=False, max_samples=None,
          C=1.0, penalty="l2", l1_ratio=None, solver="lbfgs", verbose=True):
    """학습하고 가중치를 저장한다. 호출자가 결과를 프로그램적으로 쓸 수
    있게(예: 정규화 스윕 스크립트) 지표를 dict로 반환한다.

    penalty가 'l1' 또는 'elasticnet'이면 solver를 'saga'로 줘야 한다
    (lbfgs는 L2/none만 지원) -- 호출자 책임, 여기서 자동 전환은 안 함
    (어떤 solver를 실제로 썼는지 항상 명시적이어야 재현/비교가 정확하다).
    """
    d = np.load(data_path)
    X, y = d["X"], d["y"]
    assert X.shape[1] == feature_count(), "특징 길이가 ai_features.py와 안 맞음 -- 데이터를 다시 만들어야 함"

    if verbose:
        print(f"전체 샘플: {len(X)}개")

    if max_samples is not None and len(X) > max_samples:
        # 교차항 확장(N -> N*(N+1)/2+N 차원)은 행렬이 훨씬 커져서, 표본을
        # 줄이지 않으면 메모리를 감당 못 할 수 있다. plain 학습에는 보통
        # 필요 없지만(97차원은 30만 행도 가벼움), 옵션으로 항상 지원한다.
        rng = np.random.RandomState(0)
        idx = rng.choice(len(X), size=max_samples, replace=False)
        X, y = X[idx], y[idx]
        if verbose:
            print(f"표본을 {max_samples}개로 무작위 축소")

    feature_names = FEATURE_NAMES
    if expand:
        X = expand_features_batch(X).astype(np.float32)
        feature_names = None  # 교차항 이름은 안 남김(너무 많음) -- coef 길이로 구분
        if verbose:
            print(f"교차항 확장: {feature_count()} -> {X.shape[1]}차원")

    # 검증셋을 20% 떼어둔다 -- 학습에 안 쓴 데이터로 "진짜 처음 보는 상황"에서도
    # 잘 맞히는지 확인하기 위함 (학습 데이터로만 채점하면 외운 것처럼 보일 수 있음)
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=0)
    if verbose:
        print(f"학습용: {len(X_train)}개, 검증용: {len(X_val)}개")
        print(f"설정: C={C}, penalty={penalty}, solver={solver}"
              + (f", l1_ratio={l1_ratio}" if penalty == "elasticnet" else ""))

    kwargs = {"C": C, "penalty": penalty, "solver": solver, "max_iter": 2000}
    if penalty == "elasticnet":
        kwargs["l1_ratio"] = l1_ratio
    model = LogisticRegression(**kwargs)
    model.fit(X_train, y_train)

    p_val = model.predict_proba(X_val)[:, 1]
    ll = log_loss(y_val, p_val)
    acc = accuracy_score(y_val, p_val >= 0.5)
    # 학습셋 지표도 같이 재서 과적합 정도(학습-검증 격차)를 직접 볼 수 있게 한다.
    p_train = model.predict_proba(X_train)[:, 1]
    ll_train = log_loss(y_train, p_train)
    acc_train = accuracy_score(y_train, p_train >= 0.5)
    # 0이 아닌 계수 비율 -- L1/엘라스틱넷의 희소성 효과를 직접 확인용.
    coefs = model.coef_[0]
    nonzero_frac = float(np.mean(np.abs(coefs) > 1e-8))

    if verbose:
        print()
        print(f"학습 로그손실/정확도: {ll_train:.4f} / {acc_train*100:.1f}%")
        print(f"검증 로그손실(logloss): {ll:.4f}  (0.693=동전 던지기 수준, 낮을수록 좋음)")
        print(f"검증 정확도(accuracy) : {acc*100:.1f}%")
        print(f"0이 아닌 계수 비율: {nonzero_frac*100:.1f}%")
        print()
        order = np.argsort(-np.abs(coefs))[:10]
        print("영향력 큰 특징 상위 10개:")
        for i in order:
            label = feature_names[i] if feature_names is not None else f"expanded[{i}]"
            print(f"  {label:20s} 계수={coefs[i]:+.3f}")

    save_kwargs = {"coef": coefs, "intercept": model.intercept_}
    if feature_names is not None:
        save_kwargs["feature_names"] = np.array(feature_names)
    np.savez(out_path, **save_kwargs)
    if verbose:
        print()
        print(f"가중치 저장: {out_path} ({'교차항 확장' if expand else 'plain'}, {len(coefs)}차원)")

    return {
        "val_logloss": ll, "val_accuracy": acc,
        "train_logloss": ll_train, "train_accuracy": acc_train,
        "nonzero_frac": nonzero_frac, "dim": len(coefs),
        "n_train": len(X_train), "n_val": len(X_val),
    }


if __name__ == "__main__":
    data_path = sys.argv[1] if len(sys.argv) > 1 else "selfplay_1000.npz"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "eval_weights.npz"
    expand = "--expand" in sys.argv
    max_samples = None
    if "--max-samples" in sys.argv:
        max_samples = int(sys.argv[sys.argv.index("--max-samples") + 1])
    C = 1.0
    if "--C" in sys.argv:
        C = float(sys.argv[sys.argv.index("--C") + 1])
    penalty = "l2"
    if "--penalty" in sys.argv:
        penalty = sys.argv[sys.argv.index("--penalty") + 1]
    l1_ratio = None
    if "--l1-ratio" in sys.argv:
        l1_ratio = float(sys.argv[sys.argv.index("--l1-ratio") + 1])
    solver = "lbfgs"
    if "--solver" in sys.argv:
        solver = sys.argv[sys.argv.index("--solver") + 1]
    train(data_path, out_path, expand=expand, max_samples=max_samples,
          C=C, penalty=penalty, l1_ratio=l1_ratio, solver=solver)
