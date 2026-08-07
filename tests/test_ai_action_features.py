"""ai_action_features.py -- 액션 특징 추출 회귀 테스트.

extract(g, pi, action)은 "이 상황에서 이 후보 액션" -> 숫자 목록 변환일
뿐, 학습은 전혀 없다. 검증 포인트: (1) 항상 같은 길이, (2) 값이 -1~1
범위(대부분 0~1이지만 effect_prior/heuristic_score는 부호 있는 값이라
-1~1까지 씀), (3) refresh/play(앞면/뒷면)/opp_side(Corruption_0류) 세
갈래 모두 실제 대국에서 등장할 때 에러 없이 동작.

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
                assert all(-1.0001 <= v <= 1.0001 for v in x)
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


def test_facedown_contrib_uses_real_facedown_value_not_fixed_two():
    """회귀 테스트: 뒷면으로 낼 때 contrib이 고정값 2가 아니라
    facedown_value_in_stack()의 실제 값(Darkness_2 있으면 4)을 써야
    한다 -- ai_features.py의 opp_one_move/best_swing과 같은 버그가
    액션 특징 쪽에도 있었다."""
    idx = {name: i for i, name in enumerate(FEATURE_NAMES)}

    def contrib_for(with_darkness2):
        e = Engine(protocols1=["Water", "Darkness", "Life"], protocols2=["Ice", "Metal", "Death"])
        if with_darkness2:
            d2 = e.new_card("Darkness", 2, 1)
            d2.face_up = True
            e.players[1]["stacks"][1].append(d2)
        card = e.new_card("Water", 3, 1)
        e.players[1]["hand"] = [card]
        action = {"kind": "play", "uid": card.uid, "line": 1, "faceUp": False}
        x = extract(e, 1, action)
        return x[idx["contrib"]]

    assert abs(contrib_for(with_darkness2=False) - 2 / 7.0) < 1e-9
    assert abs(contrib_for(with_darkness2=True) - 4 / 7.0) < 1e-9


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
    """같은 카드/라인이라도 앞면이면 contrib=카드 값, 뒷면이면
    contrib=facedown_value_in_stack() (이 테스트의 프로토콜 조합엔
    Darkness_2가 없어 기본값 2로 귀결)."""
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
            assert abs(xu[idx["contrib"]] - min(1.0, card.value / 7.0)) < 1e-9
            assert abs(xd[idx["contrib"]] - 2 / 7.0) < 1e-9
            assert xu[idx["face_up"]] == 1.0 and xu[idx["face_down"]] == 0.0
            assert xd[idx["face_up"]] == 0.0 and xd[idx["face_down"]] == 1.0
            return
    raise AssertionError("앞/뒷면 둘 다 가능한 액션을 찾지 못함 (시드 범위 조정 필요)")


# ---------------------------------------------------------------------------
# 이식 항목 5종 (260808_2.md): covers_card/covered_top_face_up, cap_*,
# effect_prior, hand_after/opp_hand, heuristic_score
# ---------------------------------------------------------------------------

def test_feature_count_is_39():
    assert feature_count() == 39


def test_covers_card_and_covered_top_face_up_reflect_existing_top_card():
    idx = {name: i for i, name in enumerate(FEATURE_NAMES)}

    def covers(top_face_up):
        e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
        if top_face_up is not None:
            top = e.new_card("Fire", 1, 1)
            top.face_up = top_face_up
            e.players[1]["stacks"][1].append(top)
        card = e.new_card("Water", 3, 1)
        e.players[1]["hand"] = [card]
        action = {"kind": "play", "uid": card.uid, "line": 1, "faceUp": True}
        return extract(e, 1, action)

    x_empty = covers(None)
    x_facedown_top = covers(False)
    x_faceup_top = covers(True)
    assert x_empty[idx["covers_card"]] == 0.0 and x_empty[idx["covered_top_face_up"]] == 0.0
    assert x_facedown_top[idx["covers_card"]] == 1.0 and x_facedown_top[idx["covered_top_face_up"]] == 0.0
    assert x_faceup_top[idx["covers_card"]] == 1.0 and x_faceup_top[idx["covered_top_face_up"]] == 1.0


def test_cap_lock_reflects_hand_class_of_the_card_being_played_face_up_only():
    """Metal_1 = {"draw": 2, "block_compile": True} -> hand_class().lock만
    True(다른 3개는 False). 뒷면으로 내면 정체가 안 보이므로 전부 0이어야
    한다(기존 tag_* 8개 필드와 같은 관례)."""
    idx = {name: i for i, name in enumerate(FEATURE_NAMES)}
    e = Engine(protocols1=["Metal", "Fire", "Life"], protocols2=["Ice", "Water", "Death"])
    card = e.new_card("Metal", 1, 1)
    e.players[1]["hand"] = [card]

    x_up = extract(e, 1, {"kind": "play", "uid": card.uid, "line": 1, "faceUp": True})
    assert x_up[idx["cap_lock"]] == 1.0
    assert x_up[idx["cap_tempo"]] == 0.0
    assert x_up[idx["cap_control"]] == 0.0
    assert x_up[idx["cap_risk"]] == 0.0

    x_down = extract(e, 1, {"kind": "play", "uid": card.uid, "line": 1, "faceUp": False})
    assert x_down[idx["cap_lock"]] == 0.0


def test_effect_prior_is_negative_for_rigid_7_and_zero_when_facedown_or_opp_side():
    """Rigid_7 = ongoing=-2.5(명백한 지속 부채) + self_discard=1 -> effect_prior
    총합이 음수여야 한다(부호 있는 값이라는 게 이번 이식의 핵심 포인트)."""
    idx = {name: i for i, name in enumerate(FEATURE_NAMES)}
    e = Engine(protocols1=["Rigid", "Fire", "Life"], protocols2=["Ice", "Water", "Death"])
    card = e.new_card("Rigid", 7, 1)
    e.players[1]["hand"] = [card]

    x_up = extract(e, 1, {"kind": "play", "uid": card.uid, "line": 1, "faceUp": True})
    assert x_up[idx["effect_prior"]] < 0.0
    assert x_up[idx["cap_risk"]] == 1.0  # ongoing<0 -> hand_class risk도 True

    x_down = extract(e, 1, {"kind": "play", "uid": card.uid, "line": 1, "faceUp": False})
    assert x_down[idx["effect_prior"]] == 0.0

    x_opp = extract(e, 1, {"kind": "play", "uid": card.uid, "line": 1, "faceUp": True, "side": 2})
    assert x_opp[idx["effect_prior"]] == 0.0


def test_hand_after_and_opp_hand_reflect_real_sizes_play_vs_refresh():
    idx = {name: i for i, name in enumerate(FEATURE_NAMES)}
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    card = e.new_card("Water", 3, 1)
    other_card = e.new_card("Water", 2, 1)
    e.players[1]["hand"] = [card, other_card]
    e.players[2]["hand"] = [e.new_card("Metal", 1, 2), e.new_card("Metal", 2, 2), e.new_card("Metal", 3, 2)]

    x_play = extract(e, 1, {"kind": "play", "uid": card.uid, "line": 1, "faceUp": True})
    assert abs(x_play[idx["hand_after"]] - 1 / 10.0) < 1e-9  # 손 2장 중 1장 냄 -> 1장 남음
    assert abs(x_play[idx["opp_hand"]] - 3 / 10.0) < 1e-9

    x_refresh = extract(e, 1, {"kind": "refresh"})
    assert x_refresh[idx["hand_after"]] == 0.0  # 리프레시는 손이 통째로 갈림
    assert abs(x_refresh[idx["opp_hand"]] - 3 / 10.0) < 1e-9


def test_heuristic_score_defaults_to_zero_and_feeds_through_when_given():
    idx = {name: i for i, name in enumerate(FEATURE_NAMES)}
    e = Engine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    card = e.new_card("Water", 3, 1)
    e.players[1]["hand"] = [card]
    action = {"kind": "play", "uid": card.uid, "line": 1, "faceUp": True}

    x_default = extract(e, 1, action)
    assert x_default[idx["heuristic_score"]] == 0.0

    x_given = extract(e, 1, action, 30.0)
    assert abs(x_given[idx["heuristic_score"]] - 0.5) < 1e-9  # 30/60

    x_clipped_hi = extract(e, 1, action, 999.0)
    assert x_clipped_hi[idx["heuristic_score"]] == 1.0

    x_clipped_lo = extract(e, 1, action, -999.0)
    assert x_clipped_lo[idx["heuristic_score"]] == -1.0
