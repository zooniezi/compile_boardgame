"""'초보' 난이도 AI -- 카드 지식(ai_prior.py의 태그+채점)을 실제로 쓴다.

RandomAI를 상속해서 "action"(카드 플레이/리프레시) 결정과 제어권 재배치만
score_action()/plan_rearrange()로 오버라이드한다. 그 외 하위 결정(카드 선택,
라인 선택 등)은 아직 RandomAI 그대로 -- 로드맵 1-b(하위 결정 휴리스틱)가
남은 부분이라 정직하게 상속만 해둔다.

시뮬레이션(1수 앞보기/ISMCTS)은 안 쓴다 -- 순수하게 태그 채점만으로 결정하며,
판당 25ms 수준으로 빠르다 (아레나 측정: RandomAI 상대 98~100% 승률).

포팅 원본: ai.lua의 easy 난이도 개념("앞보기 없이 우선순위가 곧 결정")에 대응.
"""

from src.game.ai_random import RandomAI
from src.game.ai_prior import score_action, plan_rearrange


class HeuristicAI(RandomAI):
    def decide(self, g, req):
        if req.get("type") == "action":
            acts = g.legal_actions(req["chooser"])
            if not acts:
                return None
            best, best_s = None, None
            for a in acts:
                s = score_action(g, req["chooser"], a)
                if best_s is None or s > best_s:
                    best_s, best = s, a
            return best
        return super().decide(g, req)

    def planRearrange(self, g, pi, compiling_line):
        return plan_rearrange(g, pi, compiling_line)
