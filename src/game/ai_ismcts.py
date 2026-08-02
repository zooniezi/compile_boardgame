"""ISMCTS(정보집합 몬테카를로 트리 탐색, Information Set Monte Carlo Tree
Search) 기반 AI.

Engine.ai_modules[pi] = ISMCTSAI()로 꽂으면 동작한다. RandomAI/HeuristicAI와
동일한 decide(g, req) / planRearrange(g, pi, compiling_line) 인터페이스를
그대로 따른다.

핵심 아이디어(2026-08-03 개편): "action"(카드 플레이/리프레시) 결정뿐 아니라,
그 액션이 여는 "내"(pi0) 하위 결정(chooseCard/chooseLine/chooseOption/
chooseHandCards/planRearrange/yesno) 전부를 같은 트리에서 UCB1으로 분기한다
-- 참고용 Lua 구현(ai_mcts.lua)의 candidatesFor()/keyOf()/select-expand-
rollout 한 방 루프를 그대로 옮긴 구조다. 이 파일 안에서 "Lua:"로 시작하는
주석은 그 대응 관계를 표시한다. 상대(opponent)의 프롬프트와, 분기하기엔
후보가 너무 많거나(>_NODE_CAND_CAP) 모양이 안 맞는 프롬프트는 여전히
롤아웃 정책(기본 HeuristicAI)이 즉답한다.

매 반복(iteration)마다 Engine.clone_at_decision()으로 새 클론을 만들고
ai_sim.determinize()로 숨은 정보(상대 손패, 상대 덱 순서, 상대 소유 뒷면
카드)를 무작위로 재구성한 뒤, 그 안에서 select(트리를 따라 UCB로 내려가다가
처음 보는 정보집합에서 expand) -> rollout(그 뒤는 정책이 흘려보냄) ->
backpropagate를 한 번 수행한다.

트리 노드는 "정보집합" 단위로 관리된다 -- 즉 뿌리 플레이어(pi0, 탐색을
수행하는 자기 자신)가 실제로 구별할 수 없는 상황들은 전부 같은 노드로
합쳐져 통계가 공유된다. 노드 키는 항상 pi0 시점에서 관찰 가능한 정보로만
구성한다 -- 상대 차례 노드라고 해서 상대의 (결정화로 가정한 가상의)
손패를 키에 넣으면, 반복마다 다른 가상 손패가 서로 다른 노드로 쪼개져
트리 재사용이 무너진다.

포팅 원본: ai_mcts.lua(설계와 select-expand-rollout 구조), ai_ismcts_plan.md
(원래 액션 전용 골격).
"""

import math

from src.game.ai_heuristic import HeuristicAI
from src.game.ai_sim import determinize, evaluate, DECLINE

# 한 반복(select+expand+rollout 전체)의 무한 진행을 막는 안전장치. Lua
# ai_mcts.lua의 `while guard < 8000`과 동일한 상수 -- 예전엔 선택 단계
# (_MAX_SELECTION_DEPTH=500)와 롤아웃 단계(_ROLLOUT_GUARD=8000)가 따로
# 있었지만, 이번 개편으로 한 루프가 됐으니 가드도 하나로 합친다.
_ROLLOUT_GUARD = 8000
# 하위 결정 노드 하나가 가질 수 있는 최대 분기 수 (Lua의 NODE_CAND_CAP과
# 동일). 이보다 후보가 많으면(예: 전체 보드 카드 중 아무거나) 트리에 안
# 넣고 롤아웃 정책이 즉답 -- 클론 재생 비용이 지배적이라 무제한 분기는
# 감당이 안 된다.
_NODE_CAND_CAP = 12


def _other(pi):
    return 2 if pi == 1 else 1


def _answer_key(v):
    """분기 후보 답변 하나를 해시 가능한 키로 압축한다 (Lua ai_mcts.lua의
    keyOf() 대응). 답변은 네 가지 모양뿐이다: action 딕셔너리(kind 필드로
    식별), 재배치 plan 딕셔너리(who+order), chooseHandCards의 uid
    리스트, 그 외 원시 스칼라(bool/int/str) -- DECLINE 센티널도 별도
    분기."""
    if v is DECLINE:
        return ("decline",)
    if isinstance(v, dict):
        if "kind" in v:  # 턴 액션 (legal_actions()의 원소)
            return ("action", v["kind"], v.get("uid"), v.get("line"),
                    v.get("faceUp"), v.get("side"))
        if "who" in v and "order" in v:  # Control 재배치 plan
            order = v["order"]
            return ("plan", v["who"], order[1], order[2], order[3])
        raise ValueError(f"ai_ismcts: unrecognized answer shape: {v!r}")
    if isinstance(v, list):  # chooseHandCards -- uid 1개짜리 리스트
        return ("uids",) + tuple(v)
    return ("scalar", type(v).__name__, v)


def _candidates_for(sim, req):
    """지금 멈춰있는 프롬프트에 대해 분기할 후보 답변 목록을 만든다 (Lua
    ai_mcts.lua의 candidatesFor() 대응). 분기 불가능한 모양이면 None --
    호출부가 롤아웃 정책으로 즉답 처리한다.

    "action"은 legal_actions() 전부를 후보로 쓴다(이 프로젝트 전반의
    관례대로 상위-K 컷 없음, Lua의 policy.actionCandidates 캡과는 다른
    지점). 나머지 타입은 _NODE_CAND_CAP으로 후보 수를 제한한다 -- 클론
    재생 비용이 지배적이라 "판 전체 카드 중 아무거나" 같은 프롬프트를
    무제한 분기할 수는 없다."""
    t = req["type"]
    if t == "action":
        acts = sim.legal_actions(req["chooser"])
        return acts if acts else None
    if t == "yesno":
        out = [True, False]
    elif t in ("chooseCard", "chooseLine", "chooseOption"):
        out = list(req.get("candidates") or [])
        if req.get("optional"):
            out.append(DECLINE)
    elif t == "chooseHandCards":
        # 다중 선택(count != 1)은 조합이 폭발하니 분기 대상에서 제외 --
        # ai_prior.simDecide 계열 sub-decision sim들도 동일하게 제외.
        # 주의: `req.get("count") or 1`처럼 Lua의 `req.count or 1` 관용구를
        # 그대로 옮기면 안 된다 -- Lua는 0이 참(truthy)이라 그 관용구가
        # 통하지만, 파이썬은 0이 falsy라 명시적 min=0/count=0을 조용히
        # 기본값으로 덮어써버린다. 반드시 .get(key, default)로 판별한다.
        if req.get("count", 1) != 1:
            return None
        out = [[c.uid] for c in sim.players[req["player"]]["hand"]]
        if req.get("min", 1) == 0:
            out.append(DECLINE)
    elif t == "planRearrange":
        # cloneAtDecision의 스탠드인이 raise하는 합성 프롬프트(Control
        # 소비 시 재배치 계획이 아직 저널화 안 된 경우). 후보: 포기 +
        # 양쪽 플레이어의 모든 단일 라인 스왑 -- ai_prior.plan_rearrange가
        # 실제로 만드는 것과 같은 모양(전체 순열 중 단일 스왑만).
        out = [DECLINE]
        chooser = req["chooser"]
        for who in (chooser, _other(chooser)):
            for a in (1, 2):
                for b in range(a + 1, 4):
                    order = {1: 1, 2: 2, 3: 3}
                    order[a], order[b] = b, a
                    out.append({"who": who, "order": order})
    else:
        return None
    return out if 2 <= len(out) <= _NODE_CAND_CAP else None


def _apply_answer(sim, v):
    sim.answer(None if v is DECLINE else v)


def _rollout_answer(sim, req, rollout_policy):
    """분기하지 않는 프롬프트 하나에 rollout_policy로 답한다. planRearrange는
    prompt()를 거치지 않는 별도 경로라 decide()가 아니라 전용 시그니처로
    호출해야 한다 (spend_control의 AI 직접호출)."""
    if req["type"] == "planRearrange":
        return rollout_policy.planRearrange(sim, req["chooser"], req.get("compilingLine"))
    return rollout_policy.decide(sim, req)


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
    쪼개져서 트리 재사용이 무력화된다).

    req["type"]/req.get("intent")를 키 앞에 넣는다 -- 액션 전용이던 시절엔
    "지금 이 보드 상태에서 다음 액션"만 구분하면 됐지만, 하위 결정까지
    분기하는 지금은 같은 보드 상태에서 서로 다른 질문(예: chooseCard로
    "지울 카드"를 묻는 것과 "뒤집을 카드"를 묻는 것)이 우연히 겹치면 안
    되므로 프롬프트 종류 자체를 키의 일부로 명시한다."""
    o = _other(pi0)
    p1, p2 = sim.players[1], sim.players[2]
    return (
        req["type"], req.get("intent"),
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
    """정보집합 하나에 대응하는 트리 노드. N/W/answer_of는 '이 노드에서
    특정 답변을 선택했을 때'의 통계이므로 답변 키(_answer_key)로 인덱싱된
    딕셔너리로 이 노드가 직접 들고 있는다 (부모->자식 포인터가 아니라,
    _search()의 전역 nodes 딕셔너리가 키로 어디서든 같은 노드를 찾는다)."""

    def __init__(self, chooser):
        self.chooser = chooser      # 이 결정을 내리는 플레이어 (1|2)
        self.visits = 0             # 이 노드를 지나간 총 횟수 (모든 답변의 N 합)
        self.N = {}                 # answer_key -> 방문 횟수
        self.W = {}                 # answer_key -> 누적 보상 (항상 pi0 시점)
        self.answer_of = {}         # answer_key -> 실제 답변 값(action dict/uid list/plan/scalar)


def _select_ucb1(node, sim, keys, pi0, c_ucb):
    """node.chooser 시점에서 keys(이 노드에 지금 실제로 유효한 답변 후보
    키 목록) 중 하나를 고른다. 아직 한 번도 안 가본 후보가 있으면
    그것부터(표준 UCT 관례), 다 가봤으면 UCB1 점수가 가장 높은 것을
    고른다.

    node.chooser == pi0면 점수가 큰 쪽(나에게 유리한 쪽)을, 아니면 점수가
    작은 쪽(상대에게 유리한 쪽)을 우선한다 -- minimax 부호 규약."""
    if not keys:
        return None
    untried = [k for k in keys if node.N.get(k, 0) == 0]
    if untried:
        # 항상 목록의 첫 항목만 고르면 후보 나열 순서(손패 순서 등)에
        # 따라 탐색이 편향되므로, sim.aux_rng로 무작위로 고른다 (게임
        # 메커니즘 스트림과 무관한, "AI 숙고용" 잡음이라는 계약에 맞는
        # 용도 -- determinize()가 매 반복 salt로 새로 시드해준다).
        idx = sim.aux_rng(len(untried)) - 1  # aux_rng는 1..n 관례
        return untried[idx]

    sign = 1.0 if node.chooser == pi0 else -1.0
    log_total = math.log(node.visits) if node.visits > 0 else 0.0
    best_key, best_score = None, None
    for k in keys:
        n = node.N[k]
        q = sign * node.W[k] / n
        bonus = c_ucb * math.sqrt(log_total / n)
        score = q + bonus
        if best_score is None or score > best_score:
            best_score, best_key = score, k
    return best_key


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


def _run_iteration(g, pi0, nodes, rollout_policy, c_ucb, horizon_turn,
                    eval_fn, eval_w, eval_scale, salt):
    """ISMCTS 반복 한 번: select(트리를 따라 UCB로 내려가다가 처음 보는
    정보집합에서 expand) -> rollout(그 뒤로는 rollout_policy가 흘려보냄)을
    한 방 루프로 수행한다 (Lua ai_mcts.lua M.pick()의 반복 본문과 동일한
    구조 -- Lua는 `inTree` 플래그로 "아직 트리 안"과 "확장 후 롤아웃"을
    가르는데, 여기서도 `in_tree` 변수가 똑같은 역할을 한다).

    분기 대상: "action" 타입은 항상, 그 외 타입은 req["chooser"] == pi0일
    때만(내 하위 결정만 -- 상대의 카드 선택/라인 선택 등은 상대의 정보라
    분기하지 않고 롤아웃 정책이 대신 답한다, Lua의 기본 동작과 동일).

    반환: (path, value) -- path는 역전파용 [(node, key), ...],
    value는 이 반복의 보상(pi0 시점, _reward()가 승부 확정/미확정 양쪽을
    다 처리). 클론 자체가 불가능하면 (None, None)."""
    sim = g.clone_at_decision()
    if sim is None:
        return None, None
    try:
        determinize(sim, pi0, salt=salt)
        path = []
        in_tree = True
        guard = 0
        while guard < _ROLLOUT_GUARD:
            guard += 1
            if sim.error or sim.winner is not None or sim.pending is None:
                break
            if sim.pending["kind"] == "anim":
                sim.advance_anim()
                continue
            req = sim.pending["req"]
            if sim.turn_count >= horizon_turn:
                break

            cands = None
            if in_tree and (req["type"] == "action" or req["chooser"] == pi0):
                cands = _candidates_for(sim, req)

            if cands is not None:
                key = _node_key(sim, req, pi0)
                is_new = key not in nodes
                if is_new:
                    nodes[key] = _Node(chooser=req["chooser"])
                node = nodes[key]
                node.visits += 1
                keys = []
                for v in cands:
                    k = _answer_key(v)
                    node.answer_of.setdefault(k, v)
                    keys.append(k)
                chosen_key = _select_ucb1(node, sim, keys, pi0, c_ucb)
                chosen_val = node.answer_of[chosen_key]
                path.append((node, chosen_key))
                _apply_answer(sim, chosen_val)
                if is_new:
                    in_tree = False  # 확장 완료 -- 이후로는 전부 롤아웃
            else:
                sim.answer(_rollout_answer(sim, req, rollout_policy))

        return path, _reward(sim, pi0, eval_fn, eval_w, eval_scale)
    finally:
        sim.dispose()  # 반드시 호출 -- 안 그러면 블로킹된 스레드가 쌓인다


def _search(g, pi0, root_req, iterations, c_ucb, rollout_policy,
            rollout_turn_cap, eval_fn, eval_w, eval_scale):
    """ISMCTS 본체. 성공하면 legal_actions(pi0)의 원소 하나를 반환하고,
    시뮬레이션이 불가능하면(시드 없음 등) None을 반환한다 -- 호출자는
    이 경우 휴리스틱 채점으로 폴백해야 한다."""
    if iterations <= 0:
        return None
    root_key = _node_key(g, root_req, pi0)
    nodes = {root_key: _Node(chooser=pi0)}
    horizon_turn = g.turn_count + rollout_turn_cap

    for i in range(iterations):
        path, value = _run_iteration(g, pi0, nodes, rollout_policy, c_ucb,
                                      horizon_turn, eval_fn, eval_w, eval_scale, salt=i)
        if path is None:
            return None  # 클론 불가(시드 없음 등) -- 호출자가 휴리스틱으로 폴백
        for n, k in reversed(path):
            n.N[k] = n.N.get(k, 0) + 1
            n.W[k] = n.W.get(k, 0.0) + value

    root = nodes[root_key]
    if not root.N:
        return None
    best_key = max(root.N, key=lambda k: root.N[k])
    return root.answer_of[best_key]


class ISMCTSAI(HeuristicAI):
    """ISMCTS로 'action'(카드 플레이/리프레시) 결정과, 그 액션이 여는 내
    하위 결정(chooseCard/chooseLine/chooseOption/chooseHandCards/
    planRearrange/yesno)까지 같은 트리에서 고르는 AI. 상대의 하위 결정과,
    분기하기엔 후보가 너무 많거나 모양이 안 맞는 프롬프트는 여전히
    HeuristicAI(ai_prior의 태그 채점)가 즉답한다.

    시뮬레이션이 불가능하면(Engine에 seed가 없는 등, clone_at_decision()이
    None을 반환하는 모든 경우) 자동으로 HeuristicAI의 채점으로 폴백한다.

    rollout_turn_cap 기본값 2 (2026-07-30, 24->12->4->2로 단계적 재조정):
    ai_ismcts_expectedoutput.md §5.8 스윕은 12가 24와 승률 동급(둘 다
    87.5%)이면서 판당 약 4배 저렴함을 실측으로 확인했다(24->12 변경
    근거). 이어서 4로 낮춘 뒤 HeuristicAI 상대 8쌍(16판)으로 검증했더니
    13승/3패(81.2% ±17.9, 유의미하게 우세)로 승률 손실이 없었다(4는
    그 자체로도 §5.8 실측 범위 밖이었지만 사후 검증됨).
    아레나로도 검증했다(HeuristicAI 상대 8쌍, 16판):
    12승/4패(75.0% ±26.2, 표본이 작아 통계적으로는 아직 무의미하나
    승 쪽 숫자는 유지) -- 속도는 판당 19.8초로 지금까지 측정한 값 중
    가장 빠르다(4는 38.4초, 12는 28.8초). 승률이 표본을 늘려도 유지
    되는지는 아직 확정 전이니 신뢰도는 중간 정도로 볼 것.

    2026-08-03: 하위 결정 분기를 추가한 뒤 이 튜닝(rollout_turn_cap 등)이
    여전히 최선인지는 재검증하지 않았다 -- 트리가 커진 만큼 반복 예산
    (iterations) 대비 노드당 통계가 희석될 수 있어(Lua의 oppInTree가
    같은 이유로 꺼져 있는 것과 동일한 리스크), 병합 전 arena 재측정
    필요."""

    def __init__(self, iterations=200, c_ucb=1.41, rollout_policy=None,
                 rollout_turn_cap=2, eval_fn=evaluate, eval_w=None,
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
    # 구현을 그대로 상속한다 -- spend_control이 프롬프트를 거치지 않고
    # 직접 호출하는 별도 경로라, 하위 결정 트리 편입(2026-08-03)의 범위
    # 밖이다. cloneAtDecision의 planRearrange 스탠드인(합성 프롬프트)만
    # 트리에서 다뤄지고, 실제 라이브 매치의 이 호출 경로 자체는 여전히
    # 휴리스틱이다.
