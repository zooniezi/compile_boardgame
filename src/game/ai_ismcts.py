"""ISMCTS(정보집합 몬테카를로 트리 탐색, Information Set Monte Carlo Tree
Search) 기반 AI.

Engine.ai_modules[pi] = ISMCTSAI()로 꽂으면 동작한다. RandomAI/HeuristicAI와
동일한 decide(g, req) / planRearrange(g, pi, compiling_line) 인터페이스를
그대로 따른다.

핵심 아이디어(2026-08-03 개편): "action"(카드 플레이/리프레시) 결정뿐 아니라,
그 액션이 여는 "내"(pi0) 하위 결정(chooseCard/chooseLine/chooseOption/
chooseHandCards/planRearrange/yesno) 전부를 같은 트리에서 UCB1으로 분기한다
-- candidatesFor()로 후보를 만들고, select(트리를 따라 UCB로 내려가다가
처음 보는 정보집합에서 expand) -> rollout을 한 방 루프로 도는 구조다.
상대(opponent)의 프롬프트와, 분기하기엔 후보가 너무 많거나
(>_NODE_CAND_CAP) 모양이 안 맞는 프롬프트는 여전히 롤아웃 정책(기본
HeuristicAI)이 즉답한다.

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
"""

import math
import random

from src.game.ai_heuristic import HeuristicAI
from src.game.ai_sim import determinize, evaluate, evaluate_learned, evaluate_learned_mlp, DECLINE
from src.game.ai_ismcts_policy import action_scores
from src.game.ai_prior import compile_available_next_check
from src.game.rules import COMPILE_THRESHOLD

# 정책이 낮게 평가한 후보도 PUCT 탐색에서 완전히 죽지 않고(사전확률이
# 0에 가까워도 최소 이 비율은 남아) 계속 탐색 가능하게 균등분포를 5%
# 섞는다.
_POLICY_UNIFORM_MIX = 0.05

# 한 반복(select+expand+rollout 전체)의 무한 진행을 막는 안전장치 --
# 예전엔 선택 단계(_MAX_SELECTION_DEPTH=500)와 롤아웃 단계
# (_ROLLOUT_GUARD=8000)가 따로 있었지만, 이번 개편으로 한 루프가 됐으니
# 가드도 하나로 합친다.
_ROLLOUT_GUARD = 8000
# 하위 결정 노드 하나가 가질 수 있는 최대 분기 수. 이보다 후보가 많으면
# (예: 전체 보드 카드 중 아무거나) 트리에 안 넣고 롤아웃 정책이 즉답 --
# 클론 재생 비용이 지배적이라 무제한 분기는 감당이 안 된다.
_NODE_CAND_CAP = 12


def _other(pi):
    return 2 if pi == 1 else 1


def _answer_key(v):
    """분기 후보 답변 하나를 해시 가능한 키로 압축한다. 답변은 네 가지
    모양뿐이다: action 딕셔너리(kind 필드로
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
    """지금 멈춰있는 프롬프트에 대해 분기할 후보 답변 목록을 만든다.
    분기 불가능한 모양이면 None -- 호출부가 롤아웃 정책으로 즉답 처리한다.

    "action"은 legal_actions() 전부를 후보로 쓴다(이 프로젝트 전반의
    관례대로 상위-K 컷 없음). 나머지 타입은 _NODE_CAND_CAP으로 후보 수를
    제한한다 -- 클론
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
        # 주의: `req.get("count") or 1`처럼 "or 1"로 기본값을 잡으면 안
        # 된다 -- 파이썬은 0이 falsy라 명시적 min=0/count=0을 조용히
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


def _dirichlet_noise(n, alpha, rng_draw):
    """rng_draw(m) -- 1..m 정수를 뽑는 콜러블(sim.aux_rng 계약)을 시드로
    삼아 Dirichlet(alpha) 표본 n개를 만든다. 감마(alpha, 1) 표본 n개를
    뽑아 합으로 나누면 Dirichlet(alpha,...,alpha) 표본이 된다는 표준
    관계를 쓴다(numpy.random.dirichlet 없이, 게임 메커니즘 스트림과
    무관한 aux_rng 계약을 그대로 재사용하기 위함)."""
    r = random.Random(rng_draw(2 ** 30))
    gammas = [r.gammavariate(alpha, 1.0) for _ in range(n)]
    total = sum(gammas)
    if total <= 0:
        return [1.0 / n] * n
    return [g / total for g in gammas]


def _select_puct(node, sim, keys, cands, pi0, c_puct, policy_w,
                  uniform_mix=_POLICY_UNIFORM_MIX,
                  root_dirichlet_alpha=None, root_dirichlet_eps=0.25):
    """루트 노드 전용 선택 규칙 -- "학습된 루트 정책"이라는 이름 그대로,
    트리 안 깊은 노드는 여전히 `_select_ucb1`을 쓰고 이 함수는 루트에서만
    호출된다.

    U = Q + c_puct * P(a) * sqrt(ΣN) / (1+n) (AlphaZero식 PUCT). 학습된
    정책의 softmax(+uniform_mix)를 사전확률 P(a)로 쓴다. `c_puct`는
    `_select_ucb1`의 `c_ucb`와 별개 상수다 -- 두 식의 보너스 항 모양이
    달라서(UCB1은 `sqrt(log(N)/n)`, PUCT는 `P(a)*sqrt(N)/(1+n)`), 같은
    "탐험 압력"을 내려면 서로 다른 계수가 필요하다. 특히 PUCT는 후보가
    여럿이면 이미 1보다 훨씬 작은 사전확률 `P(a)`가 곱해져 보너스가 한 번
    깎이고 들어가므로, 그 몫까지 보상하려면 계수 자체가 더 커야 한다.
    미방문 후보의
    Q는 0이 아니라 0.5(First-Play-Urgency)로 잡는다 -- 핵심 버그 픽스:
    Q=0으로 두면 첫 평가된 자식이 형제 후보를 전부 굶겨서 탐색이
    붕괴한다(4.8%까지 승률 추락 실측 기록).

    `_select_ucb1`과 달리 "미방문 우선" 규칙이 없다 -- PUCT의 U항 자체가
    n=0일 때 분모가 1이라 자연히 큰 보너스를 줘서 미방문 후보를 우대하므로
    별도 처리가 필요 없다.

    root_dirichlet_alpha(기본 None=끔): 자기대국 데이터 생성 전용 탐험
    노이즈(260803_RL_plan.md). 값을 주면 사전확률을
    `(1-eps)*P(a) + eps*Dirichlet(alpha)`로 섞는다 -- 매 자기대국이
    학습된 정책이 가장 선호하는 수순으로만 수렴해서 다양성을 잃는 걸
    막는다. 경쟁 플레이(`decide()`)에서는 절대 켜지 않는 옵트인
    파라미터라 기본 동작(None)은 이전과 완전히 동일하다."""
    if not keys:
        return None
    scores = action_scores(sim, node.chooser, cands, policy_w)
    m = max(scores)
    exp = [math.exp(s - m) for s in scores]
    total_exp = sum(exp)
    n_cand = len(cands)
    prior = {
        k: (1 - uniform_mix) * (e / total_exp) + uniform_mix / n_cand
        for k, e in zip(keys, exp)
    }
    if root_dirichlet_alpha is not None:
        noise = _dirichlet_noise(len(keys), root_dirichlet_alpha, sim.aux_rng)
        prior = {
            k: (1 - root_dirichlet_eps) * prior[k] + root_dirichlet_eps * eps_k
            for k, eps_k in zip(keys, noise)
        }

    sign = 1.0 if node.chooser == pi0 else -1.0
    # max(1, ...): 첫 방문(전체 N=0)일 때 분자를 0으로 두면 모든 후보의
    # U항이 0이 돼 사전확률과 무관하게 keys 나열 순서로 결정론적 편향이
    # 생긴다 -- AlphaZero류 구현의 통상 관례대로 총 방문수를 최소 1로
    # 잡아, 첫 방문은 사전확률이 가장 큰 후보를 고르도록 한다.
    sqrt_total = math.sqrt(max(1, sum(node.N.get(k, 0) for k in keys)))
    best_key, best_score = None, None
    for k in keys:
        n = node.N.get(k, 0)
        q = sign * node.W[k] / n if n > 0 else 0.5
        u = c_puct * prior[k] * sqrt_total / (1 + n)
        score = q + u
        if best_score is None or score > best_score:
            best_score, best_key = score, k
    return best_key


def _legibility(g, pi0, action):
    """루트 답변 하나의 "가독성" 점수(높을수록 더 읽기 쉬운 수) -- 얼굴이
    보이는가(2점) + 이미 컴파일된 내 라인(죽은 라인)이 아닌가(1점)를 더한
    0~3 스케일. `_search()`의 legibility 동점 처리(아래) 전용.

    'dead'는 "내가 이미 컴파일해서 더는 컴파일할 수 없는 내 라인에
    (뒷면으로) 얹는 수"만 가리킨다 -- 상대 라인에 얹는 수(action["side"]가
    설정됨)는 그 라인이 몇 번 컴파일됐든 dead로 치지 않는다(상대 라인은
    거부/봉쇄 목적이 있을 수 있어 무조건 나쁜 수가 아니기 때문)."""
    line = action.get("line")
    dead = bool(line) and g.players[pi0]["compiled"][line] and not action.get("side")
    return (2 if action.get("faceUp") else 0) + (0 if dead else 1)


def _apply_legibility_tiebreak(g, pi0, root, best_key, legible_eps):
    """`_search()`의 마지막 단계 -- 최다방문 답변(best_key)이 legible_eps
    조건을 만족하는 다른 play 후보로 바뀔 수 있는지 검사해 최종 답변
    키를 반환한다. best_key가 play 액션이 아니거나 legible_eps가 None
    이면 그대로 best_key를 반환(무동작)한다.

    루트 가독성 동점 처리 -- 방문수가
    `best_n*0.6` 이상이고 평균값(Q)이 best_q-eps 이내인 play 후보들
    중에서만, `_legibility()` 점수가 더 높은(동점이면 Q가 더 높은) 쪽을
    고른다. 진짜 가치 차이(Q gap > eps)가 있는 후보는 후보군에도 안
    들어가므로 절대 안 바뀐다."""
    best = root.answer_of[best_key]
    if (legible_eps is None or not isinstance(best, dict)
            or best.get("kind") != "play"):
        return best_key
    best_n = root.N[best_key]
    best_q = root.W[best_key] / best_n
    pick_key, pick_l, pick_q = best_key, _legibility(g, pi0, best), best_q
    for k, n in root.N.items():
        val = root.answer_of[k]
        if (n >= best_n * 0.6 and isinstance(val, dict)
                and val.get("kind") == "play"):
            q = root.W[k] / n
            if q >= best_q - legible_eps:
                l = _legibility(g, pi0, val)
                if l > pick_l or (l == pick_l and q > pick_q):
                    pick_key, pick_l, pick_q = k, l, q
    return pick_key


# 학습된 평가함수(evaluate_learned/evaluate_learned_mlp)는 Lust_0류 동적
# 컴파일 봉쇄(compile_available_next_check)를 모르는 채로 학습됐다 -- 손튜닝
# evaluate()는 0단계에서 이미 이 봉쇄를 gate했지만(w["ready"] 대신
# w["lead"]로 폴백하는 조건부 스위칭), 학습 모델은 원시 로짓 스케일이
# evaluate()의 Sim.W 스케일(compiled=100 등)과 대응되지 않아 그 수정을
# 그대로 옮길 수 없어 미뤄뒀었다(260803_ai_lua_vs_python_analysis.md 0단계
# "의도적으로 보류한 부분" 참고).
#
# 이 보정은 Lua Sim.evaluateLearnedWithWeights의 compileRulesCorrection을
# 이식한 것 -- 다만 Lua는 원시 로짓을 *100 해서 Sim.W와 같은 단위로 맞춘 뒤
# 그 스케일(ready-lead=47, oppReady-oppBrew=37)로 보정을 더하는데, Python
# 학습 모델의 원시 로짓은 그 100-스케일과 직접 대응되지 않는다. 그래서
# 원시 점수가 아니라 tanh 압축 이후의 최종 보상([-1,1]) 공간에서 직접
# 보정한다 -- Lua도 결국 이 압축(ai_mcts.lua의 squash(s)=0.5+0.5*tanh(s/120))
# 을 거쳐 [0,1] MCTS 보상으로 쓰이므로, Lua의 보정이 그 압축의 원점 근방
# 기울기(0.5/120)를 통과했을 때 만드는 효과(-47/240=-0.196, +37/240=+0.154,
# [0,1] 스케일)를 Python의 [-1,1] 스케일(폭이 2배)로 환산한 값을 반올림해서
# 쓴다. 정확한 재학습/재보정이 아니라 근사이므로, 실제 도움이 되는지는
# 아레나로 검증한다(260805_lockcorrection.md 참고).
_LOCK_CORRECTED_EVAL_FNS = (evaluate_learned, evaluate_learned_mlp)
_MY_LOCK_CORRECTION = -0.35
_OPP_LOCK_CORRECTION = 0.30


def _compile_lock_reward_correction(g, pi0):
    """이번 반복이 멈춘 국면(g) 기준으로, pi0 또는 상대가 Lust_0류 동적
    봉쇄에 걸려 임계값 이상 우세해도 다음 자기 턴에 실제로 컴파일을 못 하는
    라인이 있으면 그만큼 보상을 깎거나(내 false lead) 올린다(상대 false
    lead). `ai_prior.compile_available_next_check`/`_line_threat`와 동일한
    조건을 그대로 재사용."""
    o = _other(pi0)
    my_locked = (not g.cant_compile[pi0] and g._blocked_by_opponent_control(pi0)
                 and not compile_available_next_check(g, pi0))
    opp_locked = (not g.cant_compile[o] and g._blocked_by_opponent_control(o)
                  and not compile_available_next_check(g, o))
    if not my_locked and not opp_locked:
        return 0.0
    correction = 0.0
    for line in (1, 2, 3):
        mv, ov = g.line_value(pi0, line), g.line_value(o, line)
        if (my_locked and not g.players[pi0]["compiled"][line]
                and mv >= COMPILE_THRESHOLD and mv > ov):
            correction += _MY_LOCK_CORRECTION
        if (opp_locked and not g.players[o]["compiled"][line]
                and ov >= COMPILE_THRESHOLD and ov > mv):
            correction += _OPP_LOCK_CORRECTION
    return correction


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
    reward = math.tanh(score / eval_scale)
    if eval_fn in _LOCK_CORRECTED_EVAL_FNS:
        reward += _compile_lock_reward_correction(sim, pi0)
        reward = max(-1.0, min(1.0, reward))
    return reward


def _run_iteration(g, pi0, my_turn, root_key, policy_w, policy_uniform_mix,
                    nodes, rollout_policy, c_ucb, c_puct, horizon_turn,
                    eval_fn, eval_w, eval_scale, salt,
                    root_dirichlet_alpha=None, root_dirichlet_eps=0.25):
    """ISMCTS 반복 한 번: select(트리를 따라 UCB로 내려가다가 처음 보는
    정보집합에서 expand) -> rollout(그 뒤로는 rollout_policy가 흘려보냄)을
    한 방 루프로 수행한다. `in_tree` 플래그로 "아직 트리 안"과 "확장 후
    롤아웃"을 가른다.

    분기 대상: `sim.turn_count == my_turn`(지금 이 턴)이고 `req["chooser"]
    == pi0`(내 결정)일 때만 -- 상대 턴이나 내 다음 턴 이후까지 분기하지
    않는다는 뜻이다. 액션이든 하위 결정이든 이 조건 하나로 통일해서
    gate한다.

    2026-08-03 첫 구현은 이 turn_count 제약이 없어서 "지금 이 턴"을 넘어
    여러 턴·양쪽 플레이어의 액션까지 계속 트리에 편입시켰는데(2단계 이전
    트리가 원래 그렇게 설계돼 있었음), 그 위에 하위결정 분기까지 얹으니
    트리가 심하게 희석돼(arena 실측 73~80% 퇴보) 반복 수를 늘려도 회복이
    안 됐다. 이번 수정으로 범위를 좁힌다 -- 상대 턴과 내 다음 턴은 전부
    롤아웃 정책이 답한다.

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
            if in_tree and sim.turn_count == my_turn and req["chooser"] == pi0:
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
                if policy_w is not None and key == root_key:
                    chosen_key = _select_puct(node, sim, keys, cands, pi0, c_puct,
                                               policy_w, policy_uniform_mix,
                                               root_dirichlet_alpha, root_dirichlet_eps)
                else:
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


def _search(g, pi0, root_req, iterations, c_ucb, c_puct, rollout_policy,
            rollout_turn_cap, eval_fn, eval_w, eval_scale,
            policy_w=None, policy_uniform_mix=_POLICY_UNIFORM_MIX,
            root_dirichlet_alpha=None, root_dirichlet_eps=0.25,
            return_root=False, legible_eps=None):
    """ISMCTS 본체. 성공하면 legal_actions(pi0)의 원소 하나를 반환하고,
    시뮬레이션이 불가능하면(시드 없음 등) None을 반환한다 -- 호출자는
    이 경우 휴리스틱 채점으로 폴백해야 한다.

    c_ucb는 트리 내부 노드의 `_select_ucb1` 탐험 상수, c_puct는 루트
    노드(policy_w가 주어졌을 때)의 `_select_puct` 탐험 상수다 -- 두 값이
    독립적으로 조정 가능해야 하는 이유는 `_select_puct`의 문서를 참고.

    policy_w(ai_ismcts_policy.load_policy_weights()의 반환값)가 주어지면
    루트 노드(root_key)의 선택에만 `_select_puct`(학습된 정책 사전확률 +
    PUCT)를 쓰고, 트리의 나머지 노드는 여전히 `_select_ucb1`이다 --
    "루트 정책"이라는 이름 그대로 루트에만 적용된다.

    root_dirichlet_alpha/eps: `_select_puct`로 그대로 전달되는 자기대국
    전용 탐험 노이즈(기본 None=끔, 260803_RL_plan.md).

    return_root=True면 `(best_answer, root_node)` 튜플을 반환한다 --
    `root_node.N`(answer_key -> 방문횟수)이 자기대국 데이터 생성 시
    정책 학습 라벨(방문분포)의 원천이 된다(`ISMCTSAI.decide_with_stats()`
    참고). 기본값 False면 예전처럼 `best_answer` 하나만 반환(하위 호환).

    legible_eps(기본 None=끔): 루트 답변이 "play" 액션일 때만 적용되는
    가독성 동점 처리. 방문수
    최다 후보(best)와 평균값(Q)이 `eps` 이내로 붙어 있고 방문수도
    `best_n*0.6` 이상인 다른 play 후보들 중, `_legibility()` 점수(얼굴
    보임 > 얼굴 안 보임, 살아있는 라인 > 이미 컴파일한 내 라인)가 더 높은
    쪽으로 최종 답을 바꾼다 -- 방문수 차이가 진짜 가치 차이가 아니라
    탐색 잡음일 때, 사람이 보기에 더 "말이 되는" 수를 고르게 한다. 진짜
    가치 차이(eps보다 큰 격차)가 있는 후보는 건드리지 않는다."""
    if iterations <= 0:
        return None
    root_key = _node_key(g, root_req, pi0)
    nodes = {root_key: _Node(chooser=pi0)}
    my_turn = g.turn_count
    horizon_turn = g.turn_count + rollout_turn_cap

    for i in range(iterations):
        path, value = _run_iteration(g, pi0, my_turn, root_key, policy_w, policy_uniform_mix,
                                      nodes, rollout_policy, c_ucb, c_puct,
                                      horizon_turn, eval_fn, eval_w, eval_scale, salt=i,
                                      root_dirichlet_alpha=root_dirichlet_alpha,
                                      root_dirichlet_eps=root_dirichlet_eps)
        if path is None:
            return None  # 클론 불가(시드 없음 등) -- 호출자가 휴리스틱으로 폴백
        for n, k in reversed(path):
            n.N[k] = n.N.get(k, 0) + 1
            n.W[k] = n.W.get(k, 0.0) + value

    root = nodes[root_key]
    if not root.N:
        return None
    best_key = max(root.N, key=lambda k: root.N[k])
    best = root.answer_of[best_key]

    best_key = _apply_legibility_tiebreak(g, pi0, root, best_key, legible_eps)
    best = root.answer_of[best_key]
    return (best, root) if return_root else best


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

    2026-08-03: 하위 결정 분기를 처음 추가했을 때는 범위 제한이 없어서
    "이번 턴"을 넘어 여러 턴·양쪽 플레이어의 액션까지 계속 트리에
    편입됐다 -- arena 실측 결과 OldISMCTS(하위 결정 분기 없음) 상대
    73~80% 퇴보(iterations=100/200 둘 다 유의미)였다. 원인은 하위 결정
    분기를 얹기 전부터 트리가 여러 턴·양쪽 플레이어를 분기하도록 애초에
    넓게 설계돼 있었던 것 -- `_run_iteration()`에 `my_turn` 게이트를
    추가해 "지금 이 턴, 내 결정만"으로 좁혔다. 이 재설계 이후
    rollout_turn_cap 등 기존 튜닝이 여전히 최선인지는 재검증 필요
    (iterations=200 기준 arena 재측정으로 격차 80.0%->73.3%->66.7%까지는
    줄었으나 완전히 해소되진 않음).

    policy_w(3단계, 2026-08-03): scripts/train_policy.py로 학습한 "루트
    정책"(ai_ismcts_policy.load_policy_weights()의 반환값)을 주면 루트
    노드의 후보 선택에 `_select_puct`(PUCT + 학습된 사전확률)를 쓴다.
    None이면(기본값) 예전처럼 루트도 순수 UCB1 -- 하위 호환.

    root_dirichlet_alpha/eps(RL, 260803_RL_plan.md): `decide_with_stats()`
    가 자기대국 데이터를 생성할 때만 켜는 탐험 노이즈. `decide()`(경쟁
    플레이, 아레나, 웹 서비스)는 이 값을 안 쓴다 -- 기본값 그대로 둬도
    무해하지만, 실수로 켜둔 채 경쟁 플레이에 쓰지 않도록 `decide()`
    자체는 항상 노이즈 없이 호출한다.

    legible_eps(기본 None=끔): `decide()`와 `decide_with_stats()` 둘 다에
    적용되는 루트 가독성 동점 처리(`_search()` 참고) -- Dirichlet
    노이즈와 달리 경쟁 플레이용 기능이라 `decide()`에서도 그대로 켜진다.
    이 클래스 자체의 기본값은 None(하위 호환)이고, "고급" 프리셋
    (`ISMCTSMLPAI`)에서 0.04를 기본으로 켠다.

    rearrange_iterations(기본 None=끔): `planRearrange()`를 휴리스틱
    즉답(`HeuristicAI.plan_rearrange`) 대신 전용 서브 탐색으로 대체한다
    -- Control 소비(컴파일/리프레시) 시 "포기 + 양쪽 플레이어의 모든
    단일 라인 스왑"(7개 후보, `_candidates_for`의 `planRearrange` 분기와
    동일)을 실제로 몇 수 앞까지 시뮬레이션해보고 고른다. `_search()`를
    그대로 재사용하되 `policy_w=None`으로 호출한다 -- 이 서브탐색엔
    학습된 루트 정책을 안 쓰고 순수 UCB1만 쓴다. None이면(기본값)
    예전처럼 `HeuristicAI.planRearrange`(단일 휴리스틱 규칙)를 그대로
    상속 -- 하위 호환. 값을 주면 그 값을 서브탐색 iterations로 쓴다.

    c_ucb/c_puct: 트리 선택 단계의 탐험 상수 두 개를 독립적으로 둔다.
    `c_ucb`(기본 0.7)는 `_select_ucb1`이 쓰는 트리 내부 노드용 상수이고,
    `c_puct`(기본 1.5)는 `_select_puct`가 루트 노드에서만 쓰는 상수다 --
    둘을 하나로 합치지 않는 이유는 `_select_puct`의 문서에 적어 뒀다:
    두 선택 공식의 보너스 항 모양이 다르고, PUCT 쪽은 사전확률 `P(a)`가
    보너스를 한 번 더 깎기 때문에 같은 탐험 압력을 내려면 계수가 더
    커야 한다."""

    def __init__(self, iterations=200, c_ucb=0.7, c_puct=1.5,
                 rollout_policy=None,
                 rollout_turn_cap=2, eval_fn=evaluate, eval_w=None,
                 eval_scale=200.0, policy_w=None,
                 policy_uniform_mix=_POLICY_UNIFORM_MIX,
                 root_dirichlet_alpha=None, root_dirichlet_eps=0.25,
                 legible_eps=None, rearrange_iterations=None):
        self.iterations = iterations
        self.c_ucb = c_ucb
        self.c_puct = c_puct
        # 롤아웃/선택 단계의 하위 결정을 대신 답하는 정책. 절대 self(또는
        # 다른 ISMCTSAI)를 넘기면 안 된다 -- 롤아웃 도중 만나는 'action'형
        # 서브 프롬프트(_extra_play 등)에서 재귀적으로 새 탐색이 또
        # 시작돼 반복이 지수적으로 중첩된다.
        self.rollout_policy = rollout_policy or HeuristicAI()
        self.rollout_turn_cap = rollout_turn_cap
        self.eval_fn = eval_fn
        self.eval_w = eval_w
        self.eval_scale = eval_scale
        self.policy_w = policy_w
        self.policy_uniform_mix = policy_uniform_mix
        self.root_dirichlet_alpha = root_dirichlet_alpha
        self.root_dirichlet_eps = root_dirichlet_eps
        self.legible_eps = legible_eps
        self.rearrange_iterations = rearrange_iterations

    def decide(self, g, req):
        if req.get("type") == "action":
            pi0 = req["chooser"]
            acts = g.legal_actions(pi0)
            if len(acts) <= 1:
                return acts[0] if acts else None
            best = _search(g, pi0, req, self.iterations, self.c_ucb, self.c_puct,
                            self.rollout_policy, self.rollout_turn_cap,
                            self.eval_fn, self.eval_w, self.eval_scale,
                            self.policy_w, self.policy_uniform_mix,
                            legible_eps=self.legible_eps)
            if best is not None:
                return best
            # 클론 불가(시드 없음) 등 -- 안전하게 휴리스틱 채점으로 폴백
        return super().decide(g, req)

    def decide_with_stats(self, g, req):
        """`decide()`와 계약은 같지만(action 프롬프트만), 루트 노드의
        방문분포까지 같이 반환한다 -- 자기대국 데이터 생성 전용
        (260803_RL_plan.md). `decide()`는 무수정으로 그대로 둔다.

        반환: (chosen_action, [(action, visit_count), ...]). action이
        dict라 딕셔너리 키로 못 쓰므로 튜플 리스트로 준다. 후보가
        하나뿐이거나(선택의 여지 없음) 클론이 불가능하면 그 액션
        하나짜리 자명한 분포로 폴백한다 -- 실제 탐색이 없었으므로 방문
        분포도 의미가 없기 때문."""
        pi0 = req["chooser"]
        acts = g.legal_actions(pi0)
        if len(acts) <= 1:
            only = acts[0] if acts else None
            return only, ([(only, 1)] if only is not None else [])
        result = _search(g, pi0, req, self.iterations, self.c_ucb, self.c_puct,
                          self.rollout_policy, self.rollout_turn_cap,
                          self.eval_fn, self.eval_w, self.eval_scale,
                          self.policy_w, self.policy_uniform_mix,
                          root_dirichlet_alpha=self.root_dirichlet_alpha,
                          root_dirichlet_eps=self.root_dirichlet_eps,
                          return_root=True, legible_eps=self.legible_eps)
        if result is None:
            # 클론 불가(시드 없음) 등 -- 휴리스틱 채점으로 폴백, 방문
            # 분포는 그 하나짜리 자명한 분포로.
            chosen = super().decide(g, req)
            return chosen, [(chosen, 1)]
        best, root = result
        visits = [(root.answer_of[k], n) for k, n in root.N.items()]
        return best, visits

    def planRearrange(self, g, pi, compiling_line):
        """Control 소비(컴파일/리프레시) 시 재배치 계획 -- 재배치 서브탐색
        (4단계, 260804). `rearrange_iterations`가 None이면(기본)
        `HeuristicAI.planRearrange`(단일 규칙)를 그대로 상속한 것과
        동일하게 동작한다.

        spend_control()은 prompt()를 거치지 않고 이 메서드를 동기적으로
        직접 호출한다(`engine.py:spend_control`) -- 그 시점에 이 결정은
        아직 `g.answer_log`에 없으므로, 여기서 `g.clone_at_decision()`을
        부르면 클론이 정확히 이 결정 지점(합성 `planRearrange` 프롬프트,
        `_candidates_for`가 이미 이해하는 모양)에서 멈춘다 -- `_search()`를
        그대로 재사용할 수 있는 이유. `policy_w`는 일부러 안 넘긴다 --
        이 서브탐색엔 학습된 루트 정책 없이 순수 UCB1만 쓴다."""
        if self.rearrange_iterations is None:
            return super().planRearrange(g, pi, compiling_line)
        root_req = {"type": "planRearrange", "chooser": pi,
                     "compilingLine": compiling_line}
        best = _search(g, pi, root_req, self.rearrange_iterations,
                        self.c_ucb, self.c_puct,
                        self.rollout_policy, self.rollout_turn_cap,
                        self.eval_fn, self.eval_w, self.eval_scale)
        if best is None:
            # 클론 불가(시드 없음) 등 -- 안전하게 휴리스틱으로 폴백
            return super().planRearrange(g, pi, compiling_line)
        return None if best is DECLINE else best
