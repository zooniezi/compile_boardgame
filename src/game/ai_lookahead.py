"""1수 앞보기(1-ply lookahead) 전용 AI.

후보 액션마다 실제로 클론에서 플레이해보고(ai_sim.pick_best) 결과 위치를
평가해서 고른다 -- 트리 탐색(UCB1 반복)은 없다. `ISMCTSAI`가 이 "얕지만
정확한" 기준선보다 실제로 더 강한지 재기 위한 벤치마크 상대로 만들었다.

배경: 손튜닝 평가함수를 쓰는 트리 탐색은 "탐색을 아예 안 하는 것" 대비로는
쉽게 이겨도, "후보마다 한 번씩 시뮬레이션해서 결과 보고 고르는" 더 얕고
저렴한 방식 대비로는 이득이 없거나 오히려 무효과일 수 있다는 사례가
알려져 있다. 우리는 지금까지 `ISMCTSAI` vs `HeuristicAI`(앞보기 전혀
없음)만 쟀으므로 "탐색 vs 탐색 없음"만 증명했지 "트리 탐색 vs 1수
앞보기"라는 더 어려운 질문엔 답한 적이 없다 -- 이 클래스가 그 답을 잴
수 있게 해준다.

시뮬레이션 로직은 이미 ai_sim.py의 pick_best()가 전부 갖고 있다 --
이 클래스는 그걸 RandomAI/HeuristicAI/ISMCTSAI처럼 바로 꽂을 수 있게
감싸는 얇은 어댑터일 뿐이다.
"""

from src.game.ai_heuristic import HeuristicAI
from src.game.ai_prior import score_action
from src.game.ai_sim import pick_best, evaluate


class LookaheadAI(HeuristicAI):
    """ISMCTSAI와 동일한 계층 구조(HeuristicAI 상속, "action"만
    오버라이드, 그 외 하위 결정/planRearrange는 그대로 물려받음)지만
    탐색 방식이 다르다 -- UCB1 트리 대신 pick_best()의 "후보 전수 평가"."""

    def __init__(self, samples=1, reply=False, rollout_policy=None,
                 eval_fn=evaluate, eval_w=None):
        self.samples = samples
        self.reply = reply
        # ISMCTSAI와 동일한 이유로 절대 self를 넘기면 안 된다 -- 롤아웃
        # 도중 만나는 'action'형 서브 프롬프트에서 재귀적으로 새 탐색이
        # 또 시작돼 반복이 지수적으로 중첩된다.
        self.rollout_policy = rollout_policy or HeuristicAI()
        self.eval_fn = eval_fn
        self.eval_w = eval_w

    def decide(self, g, req):
        if req.get("type") == "action":
            pi = req["chooser"]
            acts = g.legal_actions(pi)
            if len(acts) <= 1:
                return acts[0] if acts else None
            cands = [{"a": a, "s": score_action(g, pi, a)} for a in acts]
            best = pick_best(g, pi, cands, self.rollout_policy, {
                "samples": self.samples, "reply": self.reply,
                "eval_fn": self.eval_fn, "eval_w": self.eval_w,
            })
            if best is not None:
                return best
            # 클론 불가(시드 없음) 등 -- 안전하게 휴리스틱 채점으로 폴백
        return super().decide(g, req)

    # planRearrange(g, pi, compiling_line)는 HeuristicAI(ai_prior.plan_rearrange)
    # 구현을 그대로 상속한다.
