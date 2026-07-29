"""ISMCTS(정보집합 몬테카를로 트리 탐색, Information Set Monte Carlo Tree
Search) 기반 AI.

Engine.ai_modules[pi] = ISMCTSAI()로 꽂으면 동작한다. RandomAI/HeuristicAI와
동일한 decide(g, req) / planRearrange(g, pi, compiling_line) 인터페이스를
그대로 따른다.

핵심 아이디어: "action"(카드 플레이/리프레시) 타입 결정 지점만 트리 노드로
삼고, 그 사이의 모든 하위 결정(chooseCard, chooseLine, planRearrange 등)은
롤아웃 정책(기본 HeuristicAI)이 대신 답한다. 매 반복(iteration)마다
Engine.clone_at_decision()으로 새 클론을 만들고 ai_sim.determinize()로
숨은 정보(상대 손패, 상대 덱 순서, 상대 소유 뒷면 카드)를 무작위로
재구성한 뒤, 그 안에서 UCB1 기반 선택 -> 확장 -> 롤아웃 -> 역전파를 한 번
수행한다.

트리 노드는 "정보집합" 단위로 관리된다 -- 즉 뿌리 플레이어(pi0, 탐색을
수행하는 자기 자신)가 실제로 구별할 수 없는 상황들은 전부 같은 노드로
합쳐져 통계가 공유된다. 노드 키는 항상 pi0 시점에서 관찰 가능한 정보로만
구성한다 -- 상대 차례 노드라고 해서 상대의 (결정화로 가정한 가상의)
손패를 키에 넣으면, 반복마다 다른 가상 손패가 서로 다른 노드로 쪼개져
트리 재사용이 무너진다.

포팅 원본 없음 -- ai_ismcts_plan.md의 설계를 구현한 것.
"""

import math

from src.game.ai_heuristic import HeuristicAI
from src.game.ai_sim import determinize, evaluate

# 롤아웃/선택 루프의 무한 진행을 막는 안전장치. ai_sim.playout()의
# guard < 8000 관례와 동일한 크기를 쓴다.
_ROLLOUT_GUARD = 8000
# 선택 단계가 병적으로 같은 정보집합을 계속 맴도는 경우를 막는 깊이 상한.
_MAX_SELECTION_DEPTH = 500


def _other(pi):
    return 2 if pi == 1 else 1


def _action_key(action):
    """legal_actions()가 내놓는 액션 딕셔너리를 해시 가능한 키로 압축.
    필드가 전부 원시 타입이라 그대로 튜플화할 수 있다."""
    return (action["kind"], action.get("uid"), action.get("line"),
            action.get("faceUp"), action.get("side"))


def _revealed_identity(sim, pi):
    """pi의 공개된 덱 맨 위 카드 정체 (없으면 None). 룰북의 Reveal 규칙상
    이 정보는 양쪽 모두에게 공개이므로 정보집합 키에 그대로 써도 된다."""
    uid = sim.players[pi].get("revealedTop")
    if not uid:
        return None
    deck = sim.players[pi]["deck"]
    top = deck[-1] if deck else None
    return (top.proto, top.value) if (top and top.uid == uid) else None


def _stack_snapshot(sim, pi0):
    """필드 전체를 pi0 시점으로 요약한다. 앞면 카드는 정체 그대로, pi0
    소유 뒷면 카드도 정체 그대로(자신의 뒷면 카드는 언제나 알 수 있다는
    룰북 규정, 소유권 기준 -- 놓인 side 기준이 아님), 상대 소유 뒷면
    카드는 정체를 감춘다."""
    rows = []
    for side in (1, 2):
        for line in (1, 2, 3):
            cells = []
            for c in sim.players[side]["stacks"][line]:
                if c.face_up:
                    cells.append((c.proto, c.value, "up"))
                elif c.owner == pi0:
                    cells.append((c.proto, c.value, "fd_mine"))
                else:
                    cells.append("fd_hidden")
            rows.append(tuple(cells))
    return tuple(rows)


def _node_key(sim, req, pi0):
    """지금 멈춰있는 결정 지점을 pi0 시점의 정보집합 키로 압축한다.

    req["chooser"]가 pi0든 상대든 상관없이, 상세 정보(손패 내용, 뒷면 카드
    정체)는 항상 pi0의 것만 넣는다 -- 상대 쪽은 장수만. 이래야 서로 다른
    결정화(가상의 상대 손패)에서 도달한 같은 정보집합이 하나의 노드로
    올바르게 합쳐진다 (이걸 어기면 상대 차례 노드의 통계가 반복마다
    쪼개져서 트리 재사용이 무력화된다)."""
    o = _other(pi0)
    p1, p2 = sim.players[1], sim.players[2]
    return (
        req["chooser"],
        sim.turn_count, sim.turn, sim.control, sim.phase,
        tuple(p1["protocols"][l] for l in (1, 2, 3)),
        tuple(p2["protocols"][l] for l in (1, 2, 3)),
        tuple(p1["compiled"][l] for l in (1, 2, 3)),
        tuple(p2["compiled"][l] for l in (1, 2, 3)),
        _stack_snapshot(sim, pi0),
        tuple(sorted((c.proto, c.value) for c in sim.players[pi0]["hand"])),
        len(sim.players[o]["hand"]),
        len(p1["deck"]), len(p2["deck"]),
        len(p1["discard"]), len(p2["discard"]),
        _revealed_identity(sim, 1), _revealed_identity(sim, 2),
    )


class _Node:
    """정보집합 하나에 대응하는 트리 노드. N/W/action_of는 '이 노드에서
    특정 행동을 선택했을 때'의 통계이므로 행동 키(action_key)로 인덱싱된
    딕셔너리로 이 노드가 직접 들고 있는다 (부모->자식 포인터가 아니라,
    _search()의 전역 nodes 딕셔너리가 키로 어디서든 같은 노드를 찾는다)."""

    def __init__(self, chooser):
        self.chooser = chooser      # 이 결정을 내리는 플레이어 (1|2)
        self.visits = 0             # 이 노드를 지나간 총 횟수 (모든 행동의 N 합)
        self.N = {}                 # action_key -> 방문 횟수
        self.W = {}                 # action_key -> 누적 보상 (항상 pi0 시점)
        self.action_of = {}         # action_key -> 실제 legal_actions() 원소


def _select_ucb1(node, sim, pi0, c_ucb):
    """node.chooser 시점에서 지금 이 결정화(sim)에 실제로 합법인 행동들
    중 하나를 고른다. 아직 한 번도 안 가본 행동이 있으면 그것부터(표준
    UCT 관례), 다 가봤으면 UCB1 점수가 가장 높은 것을 고른다.

    node.chooser == pi0면 점수가 큰 쪽(나에게 유리한 쪽)을, 아니면 점수가
    작은 쪽(상대에게 유리한 쪽)을 우선한다 -- minimax 부호 규약."""
    legal_now = sim.legal_actions(node.chooser)
    if not legal_now:
        return None
    keys_now = [_action_key(a) for a in legal_now]

    untried = [(k, a) for k, a in zip(keys_now, legal_now) if node.N.get(k, 0) == 0]
    if untried:
        # 항상 목록의 첫 항목만 고르면 legal_actions()의 나열 순서(손패
        # 순서 등)에 따라 탐색이 편향되므로, sim.aux_rng로 무작위로 고른다
        # (게임 메커니즘 스트림과 무관한, "AI 숙고용" 잡음이라는 계약에
        # 맞는 용도 -- determinize()가 매 반복 salt로 새로 시드해준다).
        idx = sim.aux_rng(len(untried)) - 1  # aux_rng는 1..n 관례
        k, a = untried[idx]
        node.action_of[k] = a
        return k

    sign = 1.0 if node.chooser == pi0 else -1.0
    log_total = math.log(node.visits) if node.visits > 0 else 0.0
    best_key, best_score = None, None
    for k in keys_now:
        n = node.N[k]
        q = sign * node.W[k] / n
        bonus = c_ucb * math.sqrt(log_total / n)
        score = q + bonus
        if best_score is None or score > best_score:
            best_score, best_key = score, k
    return best_key


def _answer_non_action(sim, rollout_policy):
    """지금 멈춰있는 (action이 아닌) 하위 결정 하나에 rollout_policy로
    답한다. planRearrange는 prompt()를 거치지 않는 별도 경로라 decide()가
    아니라 전용 시그니처로 호출해야 한다 (spend_control의 AI 직접호출)."""
    req = sim.pending["req"]
    if req["type"] == "planRearrange":
        plan = rollout_policy.planRearrange(sim, req["chooser"], req.get("compilingLine"))
        sim.answer(plan)
    else:
        sim.answer(rollout_policy.decide(sim, req))


def _advance_to_next_action_node(sim, action, rollout_policy):
    """action을 적용한 뒤, 다음 'action'형 결정에서 멈추거나 승부가 날
    때까지 남은 하위 결정을 전부 rollout_policy로 답하며 전진한다.
    반환: 다음 결정의 req, 또는 None(승부가 났거나 에러)."""
    sim.answer(action)
    while sim.pending is not None and not sim.error and not sim.winner:
        if sim.pending["kind"] == "anim":
            sim.advance_anim()
        elif sim.pending["req"]["type"] == "action":
            return sim.pending["req"]
        else:
            _answer_non_action(sim, rollout_policy)
    return None


def _rollout_to_horizon(sim, rollout_policy, horizon_turn):
    """트리 밖 -- 남은 결정을 전부 rollout_policy로 답하며, horizon_turn에
    도달하거나 승부가 날 때까지 진행한다. 'action'형 결정도 다른 결정과
    똑같이 rollout_policy.decide()로 답한다 (더 이상 트리를 짓지 않으므로
    action/비-action을 구분할 필요가 없다)."""
    guard = 0
    while (sim.pending is not None and not sim.error and not sim.winner
           and guard < _ROLLOUT_GUARD and sim.turn_count < horizon_turn):
        guard += 1
        if sim.pending["kind"] == "anim":
            sim.advance_anim()
        else:
            _answer_non_action(sim, rollout_policy)


def _reward(sim, pi0, eval_fn, eval_w, eval_scale):
    """항상 pi0 시점 스칼라. 이 엔진에 무승부는 없다(resolve_stalemate가
    끝까지 동률이면 승자를 강제 배정) -- sim.winner가 None이면 그건
    '아직 안 끝났다'(우리 탐색 예산 소진)는 뜻이지 무승부가 아니므로,
    evaluate()로 대체한다."""
    if sim.winner == pi0:
        return 1.0
    if sim.winner is not None:
        return -1.0
    score = eval_fn(sim, pi0, eval_w) if eval_w is not None else eval_fn(sim, pi0)
    return math.tanh(score / eval_scale)


def _search(g, pi0, root_req, iterations, c_ucb, rollout_policy,
            rollout_turn_cap, eval_fn, eval_w, eval_scale):
    """ISMCTS 본체. 성공하면 legal_actions(pi0)의 원소 하나를 반환하고,
    시뮬레이션이 불가능하면(시드 없음 등) None을 반환한다 -- 호출자는
    이 경우 휴리스틱 채점으로 폴백해야 한다."""
    if iterations <= 0:
        return None
    root_key = _node_key(g, root_req, pi0)
    nodes = {root_key: _Node(chooser=pi0)}

    for i in range(iterations):
        sim = g.clone_at_decision()
        if sim is None:
            return None
        try:
            determinize(sim, pi0, salt=i)
            horizon_turn = sim.turn_count + rollout_turn_cap
            path = []
            node = nodes[root_key]
            depth = 0

            # --- Selection (+ Expansion) ---
            while depth < _MAX_SELECTION_DEPTH and sim.turn_count < horizon_turn:
                depth += 1
                node.visits += 1
                k = _select_ucb1(node, sim, pi0, c_ucb)
                if k is None:
                    break
                path.append((node, k))
                action = node.action_of[k]
                req = _advance_to_next_action_node(sim, action, rollout_policy)
                if req is None:
                    break
                key = _node_key(sim, req, pi0)
                is_new = key not in nodes
                if is_new:
                    nodes[key] = _Node(chooser=req["chooser"])
                node = nodes[key]
                if is_new:
                    break  # 새 노드까지 확장 완료 -- 이후로는 롤아웃

            # --- Simulation (rollout) ---
            _rollout_to_horizon(sim, rollout_policy, horizon_turn)

            # --- Reward & Backpropagation ---
            z = _reward(sim, pi0, eval_fn, eval_w, eval_scale)
            for n, k in reversed(path):
                n.N[k] = n.N.get(k, 0) + 1
                n.W[k] = n.W.get(k, 0.0) + z
        finally:
            sim.dispose()  # 반드시 호출 -- 안 그러면 블로킹된 스레드가 쌓인다

    root = nodes[root_key]
    if not root.N:
        return None
    best_key = max(root.N, key=lambda k: root.N[k])
    return root.action_of[best_key]


class ISMCTSAI(HeuristicAI):
    """ISMCTS로 'action'(카드 플레이/리프레시) 결정을 고르는 AI. 그 외
    하위 결정과 Control 재배치(planRearrange)는 HeuristicAI(ai_prior의
    태그 채점)를 그대로 상속해서 답한다 -- HeuristicAI가 RandomAI를
    상속해 하위 결정을 무작위로 답하는 것과 동일한 계층 구조다.

    시뮬레이션이 불가능하면(Engine에 seed가 없는 등, clone_at_decision()이
    None을 반환하는 모든 경우) 자동으로 HeuristicAI의 채점으로 폴백한다.
    """

    def __init__(self, iterations=200, c_ucb=1.41, rollout_policy=None,
                 rollout_turn_cap=24, eval_fn=evaluate, eval_w=None,
                 eval_scale=200.0):
        self.iterations = iterations
        self.c_ucb = c_ucb
        # 롤아웃/선택 단계의 하위 결정을 대신 답하는 정책. 절대 self(또는
        # 다른 ISMCTSAI)를 넘기면 안 된다 -- 롤아웃 도중 만나는 'action'형
        # 서브 프롬프트(_extra_play 등)에서 재귀적으로 새 탐색이 또
        # 시작돼 반복이 지수적으로 중첩된다.
        self.rollout_policy = rollout_policy or HeuristicAI()
        self.rollout_turn_cap = rollout_turn_cap
        self.eval_fn = eval_fn
        self.eval_w = eval_w
        self.eval_scale = eval_scale

    def decide(self, g, req):
        if req.get("type") == "action":
            pi0 = req["chooser"]
            acts = g.legal_actions(pi0)
            if len(acts) <= 1:
                return acts[0] if acts else None
            best = _search(g, pi0, req, self.iterations, self.c_ucb,
                            self.rollout_policy, self.rollout_turn_cap,
                            self.eval_fn, self.eval_w, self.eval_scale)
            if best is not None:
                return best
            # 클론 불가(시드 없음) 등 -- 안전하게 휴리스틱 채점으로 폴백
        return super().decide(g, req)

    # planRearrange(g, pi, compiling_line)는 HeuristicAI(ai_prior.plan_rearrange)
    # 구현을 그대로 상속한다 -- ai_ismcts_plan.md 1.2절: Control 재배치의
    # 탐색 기반 최적화는 v1 범위 밖.
