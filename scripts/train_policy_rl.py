"""자기대국이 만든 방문분포(N(a)/ΣN)를 정답으로 "루트 정책"을 학습한다
(260803_RL_plan.md, PyTorch).

`scripts/train_policy.py`(모방학습, sklearn MLPClassifier, "선택됐다/
안됐다" 이진분류)와는 학습 목표 자체가 다르다 -- 여기선 한 결정(그룹)
안의 후보들에 소프트맥스를 취한 값이 방문 비율 분포에 최대한 가까워지게
만드는 **그룹별 소프트맥스 교차엔트로피**를 최소화한다. sklearn의 분류기
API는 이런 "그룹마다 후보 수가 다른 listwise 목표"에 안 맞아서(고정
원-핫 타깃 전제) PyTorch로 직접 학습 루프를 짠다(사용자 승인, RL 계획
문서 참고).

**추론은 그대로 numpy**: 학습이 끝나면 `state_dict()`를 지금 npz 포맷
(`layer{i}_w`/`layer{i}_b`/`n_layers`/`activation="relu"`)으로 저장하므로
`src/game/ai_ismcts_policy.py`는 한 줄도 안 고친다 -- `scripts/
train_policy.py`가 만드는 가중치와 완전히 같은 방식으로 로드된다.
저장한 가중치가 PyTorch 원본과 numpy 순방향에서 정확히 같은 값을 내는지는
`tests/test_train_policy_rl.py`가 회귀로 지킨다(어긋나면 탐색이 조용히
엉뚱한 정책을 쓰게 되는 가장 위험한 지점).

사용법:
    python3 scripts/train_policy_rl.py <데이터_policy.npz> <가중치출력.npz> \
        [--hidden 64] [--epochs 30] [--lr 0.001] [--group-batch 64]
"""

import sys
sys.path.insert(0, ".")

import numpy as np
import torch
import torch.nn as nn

from src.game.ai_features import feature_count as state_feature_count
from src.game.ai_action_features import feature_count as action_feature_count


def _group_split(group, test_size=0.2, seed=0):
    """train_policy.py의 _group_split과 동일 원리 -- 같은 결정(그룹)의
    후보 행이 train/val에 걸쳐 새면 안 되므로 그룹 단위로 나눈다."""
    groups = np.unique(group)
    rng = np.random.RandomState(seed)
    rng.shuffle(groups)
    n_val = max(1, int(len(groups) * test_size))
    val_groups = set(groups[:n_val].tolist())
    val_mask = np.isin(group, list(val_groups))
    return ~val_mask, val_mask


def _group_row_indices(group):
    """group 배열 -> {group_id: 그 그룹에 속한 행의 원본 인덱스 배열}."""
    order = np.argsort(group, kind="stable")
    sorted_g = group[order]
    idx = {}
    n = len(sorted_g)
    start = 0
    while start < n:
        end = start
        while end < n and sorted_g[end] == sorted_g[start]:
            end += 1
        idx[int(sorted_g[start])] = order[start:end]
        start = end
    return idx


class PolicyNet(nn.Module):
    """추론 쪽(ai_ismcts_policy._forward)과 정확히 같은 구조 -- Linear ->
    ReLU -> Linear(출력 1개, 시그모이드 없음). 은닉층을 늘리려면
    `_forward`도 같이 확장해야 하지만, 층 개수는 npz의 n_layers로 이미
    가변 처리되므로 은닉층 크기(hidden)만 바꾸는 건 자유롭다."""

    def __init__(self, in_dim, hidden=64):
        super().__init__()
        self.fc1 = nn.Linear(in_dim, hidden)
        self.fc2 = nn.Linear(hidden, 1)

    def forward(self, x):
        return self.fc2(torch.relu(self.fc1(x))).squeeze(-1)


def _group_softmax_xent(model, X, targets, group_ids, group_idx):
    """group_ids(그룹 id 리스트) 각각에 대해: 그 그룹 후보들의 모델 점수에
    softmax를 취해 방문 비율 타깃(targets)과의 교차엔트로피를 구하고,
    그룹들의 평균 손실을 반환한다(그룹마다 후보 수가 달라 고정 배치
    텐서로 못 묶으므로 파이썬 루프로 순회 -- 신경망 자체가 아주 작아서
    이 비용은 무시할 만함)."""
    losses = []
    for gid in group_ids:
        rows = group_idx[gid]
        logits = model(X[rows])
        target = targets[rows]
        target = target / target.sum()
        log_probs = torch.log_softmax(logits, dim=0)
        losses.append(-(target * log_probs).sum())
    return torch.stack(losses).mean()


def _topk_accuracy(scores, y, group_ids, group_idx, k):
    """그룹별로 scores 내림차순 상위 k개 안에 "정답"(y가 가장 큰 행 --
    가장 많이 방문된 후보)이 들어있는 비율."""
    hits = 0
    for gid in group_ids:
        rows = group_idx[gid]
        gy = y[rows]
        gs = scores[rows]
        chosen_idx = int(np.argmax(gy))
        rank_order = np.argsort(-gs)
        if chosen_idx in set(rank_order[:k].tolist()):
            hits += 1
    return hits / max(len(group_ids), 1)


def train_policy_rl(data_path, out_path, hidden=64, epochs=30, lr=1e-3,
                     group_batch=64, alpha=1e-4, seed=0, verbose=True):
    d = np.load(data_path)
    Xs, Xa, y, group = d["Xs"], d["Xa"], d["y"], d["group"]
    assert Xs.shape[1] == state_feature_count(), "상태 특징 길이가 ai_features.py와 안 맞음"
    assert Xa.shape[1] == action_feature_count(), "액션 특징 길이가 ai_action_features.py와 안 맞음"
    X_np = np.hstack([Xs, Xa]).astype(np.float32)

    if verbose:
        print(f"전체 후보 행: {len(X_np)}개, 결정(그룹): {len(np.unique(group))}개")

    train_mask, val_mask = _group_split(group, test_size=0.2, seed=seed)
    group_idx = _group_row_indices(group)
    train_groups = sorted(set(group[train_mask].tolist()))
    val_groups = sorted(set(group[val_mask].tolist()))
    if verbose:
        print(f"학습용: {len(train_groups)}결정, 검증용: {len(val_groups)}결정")

    torch.manual_seed(seed)
    X = torch.from_numpy(X_np)
    targets = torch.from_numpy(y.astype(np.float32))
    model = PolicyNet(X_np.shape[1], hidden=hidden)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=alpha)

    rng = np.random.RandomState(seed)
    best_val_loss = None
    best_state = None
    for epoch in range(epochs):
        model.train()
        order = train_groups.copy()
        rng.shuffle(order)
        epoch_losses = []
        for i in range(0, len(order), group_batch):
            batch_groups = order[i:i + group_batch]
            optimizer.zero_grad()
            loss = _group_softmax_xent(model, X, targets, batch_groups, group_idx)
            loss.backward()
            optimizer.step()
            epoch_losses.append(loss.item())

        model.eval()
        with torch.no_grad():
            val_loss = _group_softmax_xent(model, X, targets, val_groups, group_idx).item()
        if best_val_loss is None or val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        if verbose and (epoch + 1) % max(1, epochs // 10) == 0:
            print(f"  epoch {epoch+1}/{epochs}: 학습손실 {np.mean(epoch_losses):.4f}, "
                  f"검증손실 {val_loss:.4f}")

    model.load_state_dict(best_state)  # 검증손실 최저 시점으로 복원(과적합 방지)

    model.eval()
    with torch.no_grad():
        scores = model(X).numpy()
    top1 = _topk_accuracy(scores, y, val_groups, group_idx, k=1)
    top3 = _topk_accuracy(scores, y, val_groups, group_idx, k=3)
    if verbose:
        print()
        print(f"최종 검증손실: {best_val_loss:.4f}")
        print(f"검증 결정단위 top1: {top1*100:.2f}%  top3: {top3*100:.2f}%")

    # state_dict -> 기존 numpy 추론(ai_ismcts_policy.py)이 읽는 npz 포맷.
    # fc1/fc2 순서 그대로 layer0/layer1 -- PyTorch Linear의 weight는
    # (out, in) 모양이라 numpy 순방향(x @ w + b, w가 (in, out))에 맞게
    # 전치해서 저장해야 한다.
    w1 = model.fc1.weight.detach().numpy().T.astype(np.float64)
    b1 = model.fc1.bias.detach().numpy().astype(np.float64)
    w2 = model.fc2.weight.detach().numpy().T.astype(np.float64)
    b2 = model.fc2.bias.detach().numpy().astype(np.float64)
    np.savez(out_path, n_layers=2, activation="relu",
             layer0_w=w1, layer0_b=b1, layer1_w=w2, layer1_b=b2)
    if verbose:
        n_params = w1.size + b1.size + w2.size + b2.size
        print(f"가중치 저장: {out_path} (은닉 {hidden}, 파라미터 {n_params}개)")

    return {"val_loss": best_val_loss, "val_top1": top1, "val_top3": top3,
            "n_train_groups": len(train_groups), "n_val_groups": len(val_groups)}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    data_path, out_path = sys.argv[1], sys.argv[2]

    def _arg(flag, default, cast=str):
        return cast(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default

    hidden = _arg("--hidden", 64, int)
    epochs = _arg("--epochs", 30, int)
    lr = _arg("--lr", 1e-3, float)
    group_batch = _arg("--group-batch", 64, int)

    train_policy_rl(data_path, out_path, hidden=hidden, epochs=epochs, lr=lr,
                     group_batch=group_batch)
