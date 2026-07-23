"""무작위로 결정하는 플레이스홀더 AI.

실제 ai.lua(수천 줄짜리 진짜 AI)를 아직 옮기지 않아서, 그 자리를 채우는
자리표시자. engine.ai_modules[pi] = RandomAI()로 붙이면 그 플레이어는
prompt()가 올 때마다 이 클래스의 decide()로 즉시(블로킹 없이) 답한다.

포팅 원본 없음 -- GUI를 먼저 완성하기 위한 임시 구현.
"""

import random


class RandomAI:
    def decide(self, g, req):
        t = req.get("type")

        if t == "action":
            acts = g.legal_actions(req["chooser"])
            return random.choice(acts)

        if t in ("chooseCard", "yesno"):
            if t == "yesno":
                return random.choice([True, False])
            cands = req.get("candidates") or []
            if not cands:
                return None
            if req.get("optional") and random.random() < 0.3:
                return None
            return random.choice(cands)

        if t == "chooseHandCards":
            chooser = req["chooser"]
            hand = g.players[chooser]["hand"]
            lo = req.get("min", 0)
            hi = req.get("count", 0)
            n = random.randint(min(lo, len(hand)), min(hi, len(hand)))
            return [c.uid for c in random.sample(hand, n)] if n > 0 else []

        if t in ("confirmCompile", "chooseLine"):
            cands = req.get("candidates") or []
            return random.choice(cands) if cands else None

        if t == "chooseOption":
            cands = req.get("candidates") or []
            if not cands:
                return None
            if req.get("optional") and random.random() < 0.3:
                return None
            return random.choice(cands)

        if t == "choosePlayer":
            return None  # Control 재배치를 생략 (단순화)

        if t == "confirmRefresh":
            return True

        if t == "rearrange":
            return None  # 기본 순서 유지

        return None

    def planRearrange(self, g, pi, compiling_line):
        return None
