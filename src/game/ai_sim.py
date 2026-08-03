"""AI를 위한 1수 앞보기: 결정 지점에서 엔진을 복제(Engine.clone_at_decision)
하고, AI가 몰라야 할 정보를 결정화(determinize)한 뒤, 각 후보 액션을 실제로
플레이해서(sub-prompt는 policy가 답함) 결과 위치를 평가한다. 카드 효과가
그려내는 결과(뽑기, 뒤집기, 삭제, 드러남 연쇄)를 짐작이 아니라 정확히
계산하게 된다.

순수 함수, 엔진 상태 조작은 Engine 메서드를 통해서만.
"""

import random

import numpy as np

from src.game.rules import COMPILE_THRESHOLD
from src.game.ai_features import extract, expand_features
from src.game.ai_prior import compile_available_next_check


def _other(pi):
    return 2 if pi == 1 else 1


# "선택적 프롬프트를 거절"을 나타내는 sentinel (답으로 None을 줌). pickBest의
# 호출자(나중에 포팅할 ai.py의 하위 결정들)가 이 후보를 후보 목록에 넣을 수
# 있도록 여기 둔다.
class _Decline:
    def __repr__(self):
        return "DECLINE"


DECLINE = _Decline()


# ---------------------------------------------------------------------------
# 결정화 -- 시뮬레이션이 몰라야 할 정보를 흘리면 안 된다
# ---------------------------------------------------------------------------

# 복제본은 진짜 매치를 재생한 것이라, 상대의 진짜 손패/덱과 앞으로의 실제
# 셔플 결과를 그대로 들고 있다. 시뮬레이션 전에: AI가 알 권리가 없는 모든
# 카드의 정체(프로토콜/값/정의)를 -- 상대 손패, 상대 덱, 양쪽의 뒷면 카드
# (뒷면도 안 섞으면 시뮬레이션이 "뒤집기 결과"를 미리 알아버림) -- 그 uid
# 자리들 사이에서 뒤섞고, 자기 자신의 덱 순서를 섞고(내용은 알지만 순서는
# 모르니까), 기계적 난수 스트림을 다시 시드한다(시뮬레이션 안의 무작위가
# 진짜 매치의 미래를 절대 미리 알면 안 되므로).
#
# 기준 시드는 복제본이 재생한 aux 스트림에서 가져온다: 같은 결정을 복제한
# 모든 후보에서 동일해서, 후보들이 같은 상상 세계에서 비교된다(그리고 숙고
# 전체가 결정론적으로 유지된다). `salt`(샘플 인덱스)는 다중 샘플 숙고에서
# 샘플 사이에만 세계를 다르게 한다(같은 샘플 안에서의 동일성은 유지).
def determinize(sim, pi, salt=0):
    o = _other(pi)
    base = sim.aux_rng(2 ** 30) + (salt or 0) * 7919
    rnd = random.Random(base)

    def rand_index(n):
        # 엔진 rng 계약과 동일하게 1..n을 반환 (1-based)
        return rnd.randint(1, n)

    opp_p = sim.players[o]
    revealed_top = opp_p.get("revealedTop")
    slots = []
    slots.extend(opp_p["hand"])
    for c in opp_p["deck"]:
        if c.uid != revealed_top:
            slots.append(c)
    for side in (1, 2):
        for line in (1, 2, 3):
            for c in sim.players[side]["stacks"][line]:
                if not c.face_up and c.owner == o:
                    slots.append(c)

    ids = [{"proto": c.proto, "value": c.value, "definition": c.definition} for c in slots]
    # Fisher-Yates (1-based 관례를 그대로 흉내: i는 len(ids)부터 2까지)
    for i in range(len(ids), 1, -1):
        j = rand_index(i)  # 1..i
        ids[i - 1], ids[j - 1] = ids[j - 1], ids[i - 1]
    for c, d in zip(slots, ids):
        c.proto, c.value, c.definition = d["proto"], d["value"], d["definition"]

    # 자기 덱: 순서만 섞는다 -- 단, 공개적으로 드러난 맨 위 카드는 그대로 둔다.
    deck = sim.players[pi]["deck"]
    top = len(deck)
    my_revealed_top = sim.players[pi].get("revealedTop")
    if my_revealed_top and deck and deck[top - 1].uid == my_revealed_top:
        top -= 1
    for i in range(top, 1, -1):
        j = rand_index(i)
        deck[i - 1], deck[j - 1] = deck[j - 1], deck[i - 1]

    # 새 기계적 스트림 (미래 셔플/공개가 예지력을 가지면 안 됨)
    r1 = random.Random(rand_index(2 ** 30))
    r2 = random.Random(rand_index(2 ** 30))
    sim.rng = lambda n: r1.randint(1, n)
    sim.aux_rng = lambda n: r2.randint(1, n)


# ---------------------------------------------------------------------------
# 평가 -- pi 입장에서 위치를 채점한다 (클수록 좋음)
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS = {
    "compiled": 100,   # 컴파일 완료한 프로토콜 (승리 조건 그 자체)
    "line_diff": 1,    # 내 값 - 상대 값, 라인당
    "ready": 50,       # 내가 다음 내 턴 시작에 이 라인을 컴파일
    "lead": 3,         # 그냥 라인 지배
    "opp_ready": 45,   # 상대가 다음 자기 턴 시작에 컴파일 (페널티)
    "opp_brew": 8,     # 상대가 임계값 2 아래 (위협 조짐, 페널티)
    "hand_adv": 1.5,   # 카드 우위
    "control": 4,      # 제어 컴포넌트 보유
}


def evaluate(g, pi, w=None):
    w = w or DEFAULT_WEIGHTS
    if g.winner == pi:
        return 1e6
    if g.winner:
        return -1e6
    o = _other(pi)
    s = 0.0
    # Lust_0류 동적 봉쇄(compile_available_next_check)를 먼저 확인 --
    # 임계값을 넘겨 우세해도 다음 자기 턴 시작에 실제로 컴파일을 못 하는
    # 상태라면 "곧 완성"(w["ready"]/w["opp_ready"])이 아니라 그냥 평범한
    # 라인 우세(w["lead"])로만 평가해야 한다 (ai_prior._line_threat와
    # 동일한 원칙).
    my_compile_available = compile_available_next_check(g, pi)
    opp_compile_available = compile_available_next_check(g, o)
    for line in (1, 2, 3):
        if g.players[pi]["compiled"][line]:
            s += w["compiled"]
        if g.players[o]["compiled"][line]:
            s -= w["compiled"]
    for line in (1, 2, 3):
        mv, ov = g.line_value(pi, line), g.line_value(o, line)
        s += (mv - ov) * w["line_diff"]
        if not g.players[pi]["compiled"][line]:
            if my_compile_available and mv >= COMPILE_THRESHOLD and mv > ov:
                s += w["ready"]
            elif mv > ov:
                s += w["lead"]
        if not g.players[o]["compiled"][line]:
            if opp_compile_available and ov >= COMPILE_THRESHOLD and ov > mv:
                s -= w["opp_ready"]
            elif ov >= COMPILE_THRESHOLD - 2 and ov > mv:
                s -= w["opp_brew"]
    s += (len(g.players[pi]["hand"]) - len(g.players[o]["hand"])) * w["hand_adv"]
    if g.control == pi:
        s += w["control"]
    elif g.control == o:
        s -= w["control"]
    return s


_eval_weights_cache = {}


def load_eval_weights(path):
    """train_eval.py가 저장한 .npz(coef, intercept)를 읽어 evaluate_learned()의
    eval_w로 바로 넘길 수 있는 (coef, intercept) 튜플로 반환한다. 같은 경로는
    캐시해서 반복 로드를 피한다."""
    if path not in _eval_weights_cache:
        d = np.load(path)
        _eval_weights_cache[path] = (d["coef"], float(d["intercept"][0]))
    return _eval_weights_cache[path]


def evaluate_learned(g, pi, w=None):
    """학습된 로지스틱 회귀의 로짓(결정함수 값, sigmoid 적용 전)을 반환한다.
    evaluate()와 마찬가지로 "클수록 좋음"이고 압축되지 않은 스칼라라서
    ai_ismcts.py의 tanh(score/eval_scale) 정규화에 그대로 끼워 넣을 수 있다
    (확률을 반환하면 이미 0~1로 압축돼 있어 신호가 거의 사라짐).

    w는 반드시 load_eval_weights()가 반환한 (coef, intercept)여야 한다.
    coef 길이가 원본 특징 수(feature_count())와 다르면 -- 즉 교차항까지
    확장해서 학습한 가중치라면 -- expand_features()를 자동으로 적용한다
    ("학습된 가중치 개수로 plain vs 확장 모델을 고른다"는 방식,
    ai_train_pipeline.md §1.3 참고)."""
    if w is None:
        raise ValueError(
            "evaluate_learned은 eval_w=load_eval_weights(path)와 함께 써야 함")
    if g.winner == pi:
        return 1e6
    if g.winner:
        return -1e6
    coef, intercept = w
    x = extract(g, pi)
    if len(coef) != len(x):
        x = expand_features(x)
    return float(np.dot(coef, x) + intercept)


_mlp_weights_cache = {}


def load_mlp_weights(path):
    """scripts/train_eval_mlp.py가 저장한 .npz(layer{i}_w/layer{i}_b,
    n_layers)를 읽어 evaluate_learned_mlp()의 eval_w로 바로 넘길 수 있는
    [(w, b), ...] 리스트로 반환한다(층 순서대로). 같은 경로는 캐시해서
    반복 로드를 피한다(load_eval_weights()와 동일한 패턴)."""
    if path not in _mlp_weights_cache:
        d = np.load(path)
        n = int(d["n_layers"])
        layers = [(d[f"layer{i}_w"], d[f"layer{i}_b"]) for i in range(n)]
        _mlp_weights_cache[path] = layers
    return _mlp_weights_cache[path]


def _relu(x):
    return np.maximum(x, 0.0)


def evaluate_learned_mlp(g, pi, w=None):
    """소형 MLP의 순방향 계산 -- sklearn 없이 순수 numpy로 재현한다(런타임
    쪽에 새 의존성을 추가하지 않기 위해, 학습은 sklearn MLPClassifier로
    하되 학습이 끝난 가중치 행렬만 뽑아 여기서 손으로 재구현).

    evaluate_learned()와 계약 동일: 승부가 이미 결정났으면 ±1e6, 아니면
    압축 안 된 스칼라(마지막 층의 선형결합, 시그모이드 적용 전) --
    ai_ismcts.py의 tanh(score/eval_scale) 정규화가 이미 자체 압축을
    하므로 여기서 확률(0~1)로 눌러서 넘기면 신호가 뭉개진다.

    w는 반드시 load_mlp_weights()가 반환한 [(w, b), ...] 리스트여야 한다.
    activation은 "relu"로 고정(train_eval_mlp.py의 학습 설정과 반드시
    일치해야 함 -- 다르면 조용히 틀린 값을 계산한다)."""
    if w is None:
        raise ValueError(
            "evaluate_learned_mlp은 eval_w=load_mlp_weights(path)와 함께 써야 함")
    if g.winner == pi:
        return 1e6
    if g.winner:
        return -1e6
    x = np.asarray(extract(g, pi), dtype=np.float64)
    n_layers = len(w)
    for i, (weight, bias) in enumerate(w):
        x = x @ weight + bias
        if i < n_layers - 1:   # 마지막 층 전까지만 ReLU (sklearn 기본 activation)
            x = _relu(x)
    return float(x[0])


# ---------------------------------------------------------------------------
# 플레이아웃 -- 후보 액션 하나를 적용하고 pi의 턴 끝까지 resolve
# ---------------------------------------------------------------------------

# policy는 모든 하위 프롬프트에 답한다(양쪽 다 -- 우리 카드 효과 안에서
# 상대가 버리기/선택을 해야 할 수도 있음). 상대 턴에 속한 첫 입력 프롬프트를
# 만나면 멈춘다 -- 그 시점이면 (우리가 막지 못했을 경우) 상대의 강제 시작
# 컴파일은 이미 resolve된 뒤라, 평가가 위협을 무시한 진짜 대가를 보게 된다.
#
# reply=True면 상대의 턴 전체가 resolve된다(policy가 상대 프롬프트에도
# 답함), 대신 내 다음 턴의 첫 프롬프트에서 멈춘다: 그러면 평가가 우리가
# 넘겨준 판에 대한 상대의 최선의 응수까지 가격에 반영하게 된다 -- 그리고
# 내 다음 턴 시작 컴파일(자동 resolve)도.
def playout(sim, pi, action, policy, reply=False):
    if action is DECLINE:
        action = None
    stop_at = sim.turn_count + (2 if reply else 1)
    sim.answer(action)
    guard = 0
    while sim.pending is not None and not sim.error and not sim.winner and guard < 8000:
        guard += 1
        if sim.pending["kind"] == "anim":
            sim.advance_anim()
        elif sim.turn_count >= stop_at:
            break
        else:
            sim.answer(policy.decide(sim, sim.pending["req"]))
    return sim


# ---------------------------------------------------------------------------
# 진입점 -- 시뮬레이션으로 후보 중 최선을 고른다
# ---------------------------------------------------------------------------

def pick_best(g, pi, cands, policy, opts=None):
    """cands = [{"a": action, "s": heuristic_score}, ...]. 각 후보마다
    새로 결정화한 복제본을 만든다; 휴리스틱 점수는 작은 우선순위(동점
    시뮬레이션 잡음 타이브레이크)로 남는다. 엔진이 복제 못 하면(시드 없음)
    None을 반환 -- 호출자는 순수 휴리스틱 답을 그대로 쓰면 된다.

    opts (전부 선택):
      samples  후보당 결정화할 세계 수, 평가를 평균 (기본 1)
      reply    플레이아웃이 상대의 응수 턴까지 resolve
      eval_fn  evaluate 대신 쓸 함수
      eval_w   evaluate에 넘길 가중치
    """
    opts = opts or {}
    samples = opts.get("samples", 1)
    eval_fn = opts.get("eval_fn", evaluate)
    eval_w = opts.get("eval_w")
    reply = opts.get("reply", False)

    sums = [0.0] * len(cands)
    counts = [0] * len(cands)
    for k in range(samples):
        for i, c in enumerate(cands):
            sim = g.clone_at_decision()
            if sim is None:
                return None
            determinize(sim, pi, k)
            playout(sim, pi, c["a"], policy, reply)
            if not sim.error:
                sums[i] += eval_fn(sim, pi, eval_w) if eval_w is not None else eval_fn(sim, pi)
                counts[i] += 1
            # 다 쓴 클론은 반드시 정리한다 -- 안 그러면 스레드가
            # _in_queue.get()에 영원히 블로킹된 채 계속 쌓인다.
            sim.dispose()

    best, best_s = None, None
    for i, c in enumerate(cands):
        if counts[i]:
            s = sums[i] / counts[i] + (c.get("s") or 0) * 0.01
            if best_s is None or s > best_s:
                best_s, best = s, c["a"]
    return best
