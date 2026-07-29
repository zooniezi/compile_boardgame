"""무작위로 결정하는 플레이스홀더 AI.

카드 지식이나 앞보기 없이 즉석에서 무작위로 답하는 가장 단순한 티어다.
engine.ai_modules[pi] = RandomAI()로 붙이면 그 플레이어는 prompt()가 올
때마다 이 클래스의 decide()로 즉시(블로킹 없이) 답한다. `HeuristicAI`
등 더 정교한 AI들이 이 클래스를 상속해서 자기가 다루지 않는 하위 결정을
여기로 안전하게 폴백시킨다.
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
