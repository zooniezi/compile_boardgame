"""자기대국 데이터(생성_selfplay_data.py의 결과물)로 평가 함수를 학습.

로지스틱 회귀부터 시작 -- 특징 44개 -> "이 상황에서 이길 확률" 하나.
학습이 끝나면 가중치를 .npz로 저장해서 ai_sim.py의 evaluate_learned()가
읽어 쓸 수 있게 한다.

사용법:
    python3 scripts/train_eval.py <데이터.npz> <가중치출력.npz>
"""

import sys
sys.path.insert(0, ".")

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, accuracy_score
from sklearn.model_selection import train_test_split

from src.game.ai_features import FEATURE_NAMES, feature_count


def train(data_path, out_path):
    d = np.load(data_path)
    X, y = d["X"], d["y"]
    assert X.shape[1] == feature_count(), "특징 길이가 ai_features.py와 안 맞음 -- 데이터를 다시 만들어야 함"

    print(f"전체 샘플: {len(X)}개")

    # 검증셋을 20% 떼어둔다 -- 학습에 안 쓴 데이터로 "진짜 처음 보는 상황"에서도
    # 잘 맞히는지 확인하기 위함 (학습 데이터로만 채점하면 외운 것처럼 보일 수 있음)
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=0)
    print(f"학습용: {len(X_train)}개, 검증용: {len(X_val)}개")

    model = LogisticRegression(max_iter=2000)
    model.fit(X_train, y_train)

    p_val = model.predict_proba(X_val)[:, 1]
    ll = log_loss(y_val, p_val)
    acc = accuracy_score(y_val, p_val >= 0.5)

    print()
    print(f"검증 로그손실(logloss): {ll:.4f}  (0.693=동전 던지기 수준, 낮을수록 좋음)")
    print(f"검증 정확도(accuracy) : {acc*100:.1f}%")
    print()

    # 어떤 특징이 승패에 가장 큰 영향을 주는지 (계수 절댓값 상위 10개)
    coefs = model.coef_[0]
    order = np.argsort(-np.abs(coefs))[:10]
    print("영향력 큰 특징 상위 10개:")
    for i in order:
        print(f"  {FEATURE_NAMES[i]:20s} 계수={coefs[i]:+.3f}")

    np.savez(out_path, coef=model.coef_[0], intercept=model.intercept_,
             feature_names=np.array(FEATURE_NAMES))
    print()
    print(f"가중치 저장: {out_path}")


if __name__ == "__main__":
    data_path = sys.argv[1] if len(sys.argv) > 1 else "selfplay_5000.npz"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "eval_weights.npz"
    train(data_path, out_path)

