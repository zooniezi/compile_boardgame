"""'초보' 난이도 AI -- 카드 지식(ai_prior.py의 태그+채점)을 실제로 쓴다.

RandomAI를 상속해서 "action"(카드 플레이/리프레시) 결정, 제어권 재배치
(planRearrange), 그리고 하위 결정(카드/라인 선택, 손패 정리, 강제 재배열,
예/아니오, 옵션 선택)까지 전부 ai_prior.py의 채점/휴리스틱 함수로
오버라이드한다 -- 앞보기 없이 우선순위(채점)만으로 결정하는 난이도다.

시뮬레이션(1수 앞보기/ISMCTS)은 안 쓴다 -- 순수하게 태그 채점/휴리스틱만으로
결정한다.
"""

from src.game.ai_random import RandomAI
from src.game.ai_prior import (
    score_action, plan_rearrange, choose_card, choose_line,
    choose_hand_cards, answer_rearrange, yesno, choose_option,
)

# req["type"] -> ai_prior.py의 하위 결정 함수. "action"(위 score_action 루프)과
# planRearrange(별도 메서드, prompt()를 안 거치는 특수 경로)는 이 표에
# 넣지 않는다 -- 각자 자기만의 호출 경로가 있다.
_SUB_DECISION_HANDLERS = {
    "chooseCard": choose_card,
    "chooseLine": choose_line,
    "chooseHandCards": choose_hand_cards,
    "rearrange": answer_rearrange,
    "yesno": yesno,
    "chooseOption": choose_option,
}


class HeuristicAI(RandomAI):
    def decide(self, g, req):
        t = req.get("type")
        if t == "action":
            acts = g.legal_actions(req["chooser"])
            if not acts:
                return None
            best, best_s = None, None
            for a in acts:
                s = score_action(g, req["chooser"], a)
                if best_s is None or s > best_s:
                    best_s, best = s, a
            return best
        handler = _SUB_DECISION_HANDLERS.get(t)
        if handler:
            return handler(g, req)
        # confirmCompile/confirmRefresh/choosePlayer 등은 AI에게 안 오거나
        # (엔진이 자동 처리) 안전한 기본값이면 충분한 경우라 RandomAI로 폴백.
        return super().decide(g, req)

    def planRearrange(self, g, pi, compiling_line):
        return plan_rearrange(g, pi, compiling_line)
