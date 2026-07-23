"""순수(headless) 프로토콜 밴픽 상태 머신.

번갈아 진행되는 픽/밴 시퀀스. UI나 서버나 규칙이 같아야 하므로 여기 하나만
둔다.

순서(플레이어 인덱스 1, 2): P1 pick1 · P2 pick2 · P1 ban1 · P2 ban1 ·
P1 pick2 · P2 pick1  -> 각 플레이어가 최종적으로 3장씩 픽; ban은 풀에서
그 프로토콜을 양쪽 모두에게서 제거.

사용법:
    d = Draft(pool_id_list)          # 예: protocols.PROTOCOL_LIST의 사본
    cur = d.current()                # {"player":.., "action": "pick"|"ban", "remaining":..}
    ok, err = d.apply(player, proto_id)
    if d.done():
        p1, p2 = d.result()

포팅 원본: draft.lua
"""

# 표준 밴픽 순서. 단일 진실 공급원(화면/서버가 공유).
STEPS = (
    {"who": 1, "action": "pick", "count": 1},
    {"who": 2, "action": "pick", "count": 2},
    {"who": 1, "action": "ban", "count": 1},
    {"who": 2, "action": "ban", "count": 1},
    {"who": 1, "action": "pick", "count": 2},
    {"who": 2, "action": "pick", "count": 1},
)

# 수동 구성(vs-AI 새 게임 옵션): ban도 번갈아 진행도 없음 -- 사람이 자기
# 프로토콜 3개를 직접 고르고, 그다음 AI의 3개. 같은 상태 머신, 다른 순서.
MANUAL_STEPS = (
    {"who": 1, "action": "pick", "count": 3},
    {"who": 2, "action": "pick", "count": 3},
)


class Draft:
    def __init__(self, pool, steps=None):
        """pool: 선택 가능한 프로토콜 id의 순서 있는 리스트.
        steps: 시퀀스 재정의(기본 STEPS -- 온라인 드래프트/서버는 항상 기본값)."""
        self.pool = list(pool or [])
        self.owner = {}          # id -> 1 | 2 | "ban"
        self.picks = {1: [], 2: []}  # 플레이어별, 픽한 순서대로
        self.steps = steps if steps is not None else STEPS
        self.step_idx = 0  # 0-based (Lua는 1-based)
        self.remaining = self.steps[0]["count"] if self.steps else 0

    def available(self):
        """아직 선택 가능한(픽도 밴도 안 된) id들, 풀 순서 그대로."""
        return [pid for pid in self.pool if pid not in self.owner]

    def done(self):
        return self.step_idx >= len(self.steps)

    def current(self):
        """지금 진행 중인 단계, 드래프트가 끝났으면 None."""
        if self.step_idx >= len(self.steps):
            return None
        s = self.steps[self.step_idx]
        return {"player": s["who"], "action": s["action"], "remaining": self.remaining}

    def _in_pool(self, pid):
        return pid in self.pool

    def apply(self, player, pid):
        """`player`가 현재 단계에서 `pid`를 선택. 성공하면 (True, None),
        실패하면 (False, 사유). 서버가 이 결과로 거부 여부를 판단(권위 있는 판정)."""
        cur = self.current()
        if not cur:
            return False, "draft complete"
        if player != cur["player"]:
            return False, "not your turn"
        if not self._in_pool(pid):
            return False, "unknown protocol"
        if pid in self.owner:
            return False, "protocol unavailable"

        if cur["action"] == "pick":
            self.owner[pid] = player
            self.picks[player].append(pid)
        else:
            self.owner[pid] = "ban"

        self.remaining -= 1
        if self.remaining <= 0:
            self.step_idx += 1
            if self.step_idx < len(self.steps):
                self.remaining = self.steps[self.step_idx]["count"]
        return True, None

    def result(self):
        """끝났으면 picks[1], picks[2](각각 3개 id 리스트) 반환, 아니면 None."""
        if not self.done():
            return None
        return self.picks[1], self.picks[2]
