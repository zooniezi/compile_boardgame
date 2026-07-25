"""clone_at_decision() -- AI 시뮬레이션(1수 앞보기/ISMCTS)용 재생 기반 복제.

살아있는 Engine(스레드/큐 포함)은 pickle/deepcopy가 안 되므로, 같은 시드로
새 Engine을 만들어 answer_log를 재생해서 같은 결정 지점까지 따라잡는 방식.
"""

import random

from src.game.engine import Engine
from src.game.ai_random import RandomAI


def _run_ai_vs_ai(seed, steps=200, ai=None):
    # RandomAI는 엔진의 seed가 아니라 파이썬 전역 random을 직접 쓰므로,
    # 이것도 같이 고정해야 "seed가 같으면 같은 판이 재생된다"가 테스트
    # 실행 순서와 무관하게 안정적으로 성립한다 (안 그러면 다른 테스트가
    # 먼저 전역 random을 소비했는지에 따라 이 판의 실제 진행이 달라져서,
    # 예를 들어 게임이 의도한 것보다 훨씬 일찍 끝나버릴 수 있다).
    random.seed(seed)
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"],
               ai1=True, ai2=True, ai=ai or RandomAI(), seed=seed)
    e.start()
    for _ in range(steps):
        if e.pending is None:
            break
        if e.pending["kind"] == "anim":
            e.advance_anim()
        else:
            e.answer(None)
    return e


def test_clone_at_decision_returns_none_without_seed():
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"],
               ai1=True, ai2=True, ai=RandomAI())  # seed 없음
    e.start()
    for _ in range(20):
        if e.pending is None:
            break
        if e.pending["kind"] == "anim":
            e.advance_anim()
        else:
            e.answer(None)
    assert e.clone_at_decision() is None


def test_clone_matches_live_state_from_within_ai_decide():
    """실제 사용법: AI 자신의 decide(g, req) 안에서(아직 answer_log에 이
    결정이 안 남은 시점에) 호출하면, 복제본이 지금과 완전히 같은 상태/
    결정 지점을 재현해야 한다."""
    captured = []

    class SpyAI(RandomAI):
        def decide(self, g, req):
            if len(captured) < 8:  # 충분한 표본만 있으면 됨 -- 과도한 스레드 churn 방지
                sim = g.clone_at_decision()
                if sim is not None:
                    captured.append({
                        "live_req_type": req["type"],
                        "live_log_len": len(g.answer_log),
                        "sim_req_type": sim.pending["req"]["type"],
                        "sim_log_len": len(sim.answer_log),
                        "live_hand": sorted((c.proto, c.value) for c in g.players[1]["hand"]),
                        "sim_hand": sorted((c.proto, c.value) for c in sim.players[1]["hand"]),
                        "live_lines": [g.line_value(1, l) for l in (1, 2, 3)],
                        "sim_lines": [sim.line_value(1, l) for l in (1, 2, 3)],
                    })
                    sim.dispose()  # 검사만 하고 버리는 클론이라 스레드 정리 필요
            return super().decide(g, req)

    _run_ai_vs_ai(seed=13131313, steps=200, ai=SpyAI())

    assert len(captured) > 0
    for c in captured:
        assert c["live_req_type"] == c["sim_req_type"]
        assert c["live_log_len"] == c["sim_log_len"]
        assert c["live_hand"] == c["sim_hand"]
        assert c["live_lines"] == c["sim_lines"]


def test_clone_is_fully_independent_from_the_live_engine():
    """복제본에 다른 액션을 시도해도 원본(살아있는 판)은 전혀 영향받지
    않아야 한다."""
    class OnceSpyAI(RandomAI):
        triggered = False
        result = {}

        def decide(self, g, req):
            if not OnceSpyAI.triggered and req["type"] == "action":
                OnceSpyAI.triggered = True
                sim = g.clone_at_decision()
                acts = g.legal_actions(req["chooser"])
                if sim is not None and len(acts) > 1:
                    before = [g.line_value(1, l) for l in (1, 2, 3)]
                    sim.answer(acts[1])  # 실제로 낼 답과 다른 후보를 복제본에만 적용
                    for _ in range(10):
                        if sim.pending and sim.pending["kind"] == "anim":
                            sim.advance_anim()
                        else:
                            break
                    after = [g.line_value(1, l) for l in (1, 2, 3)]
                    OnceSpyAI.result["before"] = before
                    OnceSpyAI.result["after"] = after
                    sim.dispose()
                elif sim is not None:
                    sim.dispose()
            return super().decide(g, req)

    _run_ai_vs_ai(seed=555, steps=200, ai=OnceSpyAI())

    assert OnceSpyAI.result.get("before") == OnceSpyAI.result.get("after")


def test_clone_succeeds_repeatedly_deep_into_a_game():
    """진행이 꽤 깊어진 판(Control 재배치 등 prompt() 밖의 경로까지 여러 번
    거친 상태)에서도 반복 호출이 계속 성공해야 한다. spend_control()의
    AI 직접호출 경로(prompt()를 안 거침)가 재생 모드를 놓치던 버그의
    회귀 테스트."""
    e = _run_ai_vs_ai(seed=999, steps=500)
    assert len(e.answer_log) > 20  # 충분히 깊게 진행됐는지 확인

    successes = 0
    for _ in range(30):
        sim = e.clone_at_decision()
        if sim is not None:
            successes += 1
            sim.dispose()
    assert successes == 30
