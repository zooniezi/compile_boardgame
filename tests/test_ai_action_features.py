"""ai_action_features.py -- 액션 특징 추출 회귀 테스트.

extract(g, pi, action)은 "이 상황에서 이 후보 액션" -> 숫자 목록 변환일
뿐, 학습은 전혀 없다. 검증 포인트: (1) 항상 같은 길이, (2) 값이 0~1
범위(부호 있는 필드가 없는 설계), (3) refresh/play(앞면/뒷면)/opp_side
(Corruption_0류) 세 갈래 모두 실제 대국에서 등장할 때 에러 없이 동작.

engine.ai1=True/ai2=True로 돌리면 모든 결정이 엔진 내부에서 ai_module로
바로 처리돼 바깥 pending 루프에는 "action" 요청이 노출되지 않는다(항상
kind="anim"만 관측됨) -- scripts/generate_selfplay_data.py의 RecordingAI와
같은 요령으로, ai= 파라미터에 감시용 래퍼를 꽂아 decide() 호출 시점에서
가로채는 방식으로 확인한다.
"""

import random

from src.game.engine import Engine
from src.game.ai_random import RandomAI

from src.game.ai_action_features import extract, FEATURE_NAMES, feature_count


class _SpyAI(RandomAI):
    def __init__(self):
        self.seen = {"refresh": 0, "up": 0, "down": 0}

    def decide(self, g, req):
        if req.get("type") == "action":
            pi = req["chooser"]
            for a in g.legal_actions(pi):
                x = extract(g, pi, a)
                assert len(x) == feature_count()
                assert all(-0.0001 <= v <= 1.0001 for v in x)
                if a.get("kind") == "refresh":
                    self.seen["refresh"] += 1
                elif a.get("faceUp"):
                    self.seen["up"] += 1
                else:
                    self.seen["down"] += 1
        return super().decide(g, req)


def _play_game(seed):
    random.seed(seed)
    spy = _SpyAI()
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"],
               ai1=True, ai2=True, ai=spy, seed=seed)
    e.start()
    n = 0
    while e.pending is not None and n < 20000:
        n += 1
        if e.pending["kind"] == "anim":
            e.advance_anim()
        else:
            e.answer(None)
    return spy


def test_feature_count_matches_names():
    assert feature_count() == len(FEATURE_NAMES)


def test_extract_always_returns_fixed_length_and_bounded_values_over_real_play():
    """무작위 대국 여러 판을 굴리면서 매 action 결정 시점의 모든 후보에
    extract()를 호출 -- refresh/앞면/뒷면 세 갈래를 자연스럽게 다 커버."""
    totals = {"refresh": 0, "up": 0, "down": 0}
    for seed in range(10):
        spy = _play_game(seed)
        for k in totals:
            totals[k] += spy.seen[k]
    assert totals["refresh"] > 0
    assert totals["up"] > 0
    assert totals["down"] > 0


def test_refresh_action_has_refresh_flag_set_and_play_fields_zeroed():
    idx = {name: i for i, name in enumerate(FEATURE_NAMES)}
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"],
               ai1=True, ai2=True, ai=RandomAI(), seed=1)
    e.start()
    x = extract(e, 1, {"kind": "refresh"})
    assert x[idx["is_refresh"]] == 1.0
    assert x[idx["is_play"]] == 0.0
    assert x[idx["face_up"]] == 0.0
    assert x[idx["face_down"]] == 0.0
    assert x[idx["card_value"]] == 0.0


class _FaceVariantSpyAI(RandomAI):
    """같은 (uid, line)에 앞면/뒷면 둘 다 낼 수 있는 첫 액션 쌍을 찾으면
    두 벡터를 저장해두고, 이후 결정은 전부 무작위(RandomAI)로 넘긴다."""

    def __init__(self):
        self.found = None

    def decide(self, g, req):
        if self.found is None and req.get("type") == "action":
            pi = req["chooser"]
            by_key = {}
            for a in g.legal_actions(pi):
                if a.get("kind") != "play" or a.get("side"):
                    continue
                by_key.setdefault((a["uid"], a["line"]), {})[a["faceUp"]] = a
            for (uid, line), variants in by_key.items():
                if True in variants and False in variants:
                    self.found = (
                        g.cards_by_uid[uid],
                        extract(g, pi, variants[True]),
                        extract(g, pi, variants[False]),
                    )
                    break
        return super().decide(g, req)


def test_play_action_face_up_vs_face_down_differ_only_where_expected():
    """같은 카드/라인이라도 앞면이면 contrib=카드 값, 뒷면이면 contrib=2
    (규칙서: 뒷면 카드는 항상 값 2 취급)."""
    idx = {name: i for i, name in enumerate(FEATURE_NAMES)}
    for seed in range(15):
        random.seed(seed)
        spy = _FaceVariantSpyAI()
        e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"],
                   ai1=True, ai2=True, ai=spy, seed=seed)
        e.start()
        n = 0
        while e.pending is not None and n < 20000 and spy.found is None:
            n += 1
            if e.pending["kind"] == "anim":
                e.advance_anim()
            else:
                e.answer(None)
        if spy.found is not None:
            card, xu, xd = spy.found
            assert abs(xu[idx["contrib"]] - min(1.0, card.value / 6.0)) < 1e-9
            assert abs(xd[idx["contrib"]] - 2 / 6.0) < 1e-9
            assert xu[idx["face_up"]] == 1.0 and xu[idx["face_down"]] == 0.0
            assert xd[idx["face_up"]] == 0.0 and xd[idx["face_down"]] == 1.0
            return
    raise AssertionError("앞/뒷면 둘 다 가능한 액션을 찾지 못함 (시드 범위 조정 필요)")
