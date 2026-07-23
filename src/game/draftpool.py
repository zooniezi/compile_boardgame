"""밴픽(드래프트)이 시작하는 프로토콜 풀을 구성.

매치 옵션에 따라:
  sets: 어떤 카드 세트를 허용할지 ("main1", "aux1", ... protocols.SET_ORDER
        참고). None/빈 값 = 모든 세트.
  mode: "standard" = 그 세트들의 전체 풀
        "blind"    = 그중 무작위 BLIND_SIZE개

포팅 원본: draftpool.lua
"""

import random

from . import protocols as Protocols

BLIND_SIZE = 9
# 선택된 세트는 최소 이만큼의 프로토콜을 제공해야 한다 (픽/밴 시퀀스가
# 8개를 소모하고, blind 모드는 9개가 필요). 세트 이름이 아니라 "개수"로
# 검증하므로, 나중에 세트가 늘어나도 합계가 9 이상이면 그대로 선택 가능.
MIN_POOL = 9


def count_for(sets):
    """주어진 세트 선택({세트id: True} 딕셔너리 또는 세트id 리스트)이 제공하는
    프로토콜 개수. None/빈 값이면 전체 세트."""
    allowed = {}
    if isinstance(sets, dict):
        for k, v in sets.items():
            if v is True:
                allowed[k] = True
    elif isinstance(sets, (list, tuple)):
        for s in sets:
            if isinstance(s, str):
                allowed[s] = True
    if not allowed:
        for s in Protocols.SET_ORDER:
            allowed[s] = True
    return sum(1 for proto in Protocols.PROTOCOL_LIST if allowed.get(Protocols.SET_OF[proto]))


def sanitize(opts):
    """신뢰할 수 없는 opts를 {"sets": [...]|None, "mode": "standard"|"blind"}로
    정리. 기본값(전체 세트 + standard)과 동일하면 None을 반환."""
    if not isinstance(opts, dict):
        return None
    valid = set(Protocols.SET_ORDER)
    sets, seen = [], set()
    for s in (opts.get("sets") or []):
        if isinstance(s, str) and s in valid and s not in seen:
            seen.add(s)
            sets.append(s)
    if len(sets) == len(Protocols.SET_ORDER):
        sets = []  # 전체 선택 = 기본값
    # 드래프트를 진행하기엔 너무 작은 선택은 그냥 거부(전체 세트로 대체) --
    # 클라이언트 쪽 선택 UI가 강제하는 규칙과 동일.
    if sets and count_for(sets) < MIN_POOL:
        sets = []
    mode = "blind" if opts.get("mode") == "blind" else "standard"
    if not sets and mode == "standard":
        return None
    return {"sets": sets or None, "mode": mode}


def build(opts):
    """드래프트용 풀을 만든다. blind 모드면 그중 무작위로 BLIND_SIZE개만 남긴다."""
    allowed = {}
    if isinstance(opts, dict):
        for s in (opts.get("sets") or []):
            allowed[s] = True
    if not allowed:
        for s in Protocols.SET_ORDER:
            allowed[s] = True

    pool = [proto for proto in Protocols.PROTOCOL_LIST if allowed.get(Protocols.SET_OF[proto])]

    # 픽/밴 시퀀스를 감당 못 할 만큼 작은 선택이면, 드래프트가 막히는 대신
    # 전체 카탈로그로 되돌아간다.
    if len(pool) < MIN_POOL:
        pool = list(Protocols.PROTOCOL_LIST)

    if isinstance(opts, dict) and opts.get("mode") == "blind":
        pool = random.sample(pool, min(BLIND_SIZE, len(pool)))

    return pool
