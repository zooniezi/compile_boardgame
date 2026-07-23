import random

from src.game.engine import Engine


class DummyAI:
    """실제 AI 포팅 전, 엔진 파이프라인 검증용 무작위 AI."""

    def decide(self, g, req):
        t = req.get("type")
        if t == "action":
            acts = g.legal_actions(req["chooser"])
            return random.choice(acts)
        if t == "chooseCard":
            cands = req.get("candidates") or []
            return random.choice(cands) if cands else None
        if t == "chooseHandCards":
            hand = g.players[req["chooser"]]["hand"]
            n = min(req.get("count", 0), len(hand))
            return [c.uid for c in hand[:n]]
        if t == "confirmCompile":
            cands = req.get("candidates") or []
            return cands[0] if cands else None
        if t == "chooseLine":
            cands = req.get("candidates") or []
            return cands[0] if cands else None
        if t == "choosePlayer":
            return None
        if t == "confirmRefresh":
            return True
        return None

    def planRearrange(self, g, pi, compiling_line):
        return None


def _run_full_game(seed):
    random.seed(seed)
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"],
               ai1=True, ai2=True, ai=DummyAI())
    e.start()
    steps = 0
    while e.pending is not None and steps < 20000:
        steps += 1
        if e.pending["kind"] == "anim":
            e.advance_anim()
        else:
            e.answer(None)
    return e, steps


def test_full_game_reaches_winner_without_error():
    e, steps = _run_full_game(seed=42)
    assert e.error is None
    assert e.winner in (1, 2)
    assert e.pending is None
    assert steps < 20000  # 턴 상한 안전망에 걸리지 않고 정상 종료됐는지


def test_full_game_conserves_all_36_cards():
    e, _ = _run_full_game(seed=7)
    # 재컴파일 보상(drawFromDeckOf)은 카드 소유권을 정당하게 이전시키므로
    # (룰북 규칙), 플레이어별 18장이 아니라 "합쳐서 36장"만 검증한다.
    total = 0
    for pi in (1, 2):
        p = e.players[pi]
        on_board = sum(len(p["stacks"][l]) for l in (1, 2, 3))
        total += len(p["hand"]) + len(p["deck"]) + len(p["discard"]) + on_board
    assert total == 36


def test_full_game_is_deterministic_given_same_seed():
    e1, steps1 = _run_full_game(seed=123)
    e2, steps2 = _run_full_game(seed=123)
    assert steps1 == steps2
    assert e1.winner == e2.winner
    assert e1.turn_count == e2.turn_count
