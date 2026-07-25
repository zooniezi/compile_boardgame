"""컴파일(Compile)의 순수 규칙 엔진.

상호작용 모델: 게임 진행 전체가 별도 스레드(백그라운드 스레드) 하나에서 돈다.
결정이 필요할 때마다 prompt(req)를 호출한다. 결정 주체가 AI면 그 자리에서
바로 답한다 (블로킹 없음). 사람이면 큐에 {kind: "input"} 메시지를 넣고 답이
올 때까지 스레드를 블로킹한다. 페이싱을 위한 emit(evt)도 마찬가지로
{kind: "anim"} 메시지를 큐에 넣고 확인(advance_anim)이 올 때까지 블로킹한다.
메인 스레드(=pygame 루프)는 절대 블로킹되지 않고, 사람 턴과 AI 턴이 완전히
동일한 코드 경로를 탄다.

포팅 원본: engine.lua
"""

import random
import threading
from queue import Queue

from src.game import protocols as Protocols
from src.game import rules as Rules
from src.game import carddefs as Cards
from src.game.card import Card

# discard()가 블로킹 중인 게임 스레드를 깨워서 즉시 정리시킬 때 쓰는 신호.
# AI 시뮬레이션(clone_at_decision)이 만든 클론은 평가 후 버려지는데, 그냥
# 방치하면 스레드가 _in_queue.get()에 영원히 블로킹된 채로 남는다 --
# 이 poison pill을 받으면 대기 중이던 코드가 즉시 _EngineDiscarded를 던져서
# 스레드가 자연스럽게(기존 예외 처리 경로로) 종료되게 한다.
_DISCARD = object()


class _EngineDiscarded(Exception):
    """discard()가 블로킹 중인 스레드를 정리하려고 내부적으로 쓰는 신호."""

# 여러 장을 한꺼번에 옮길 때(덱->손, 손->버림, 컴파일 라인 정리) 한 장씩
# 순서대로 애니메이션되도록 카드 사이에 주는 간격(초).
MOVE_STAGGER = 0.16


def _other(player):
    return 2 if player == 1 else 1


def _shuffle(seq, rng):
    """Fisher-Yates 셔플. rng(n)은 1..n 사이의 정수를 반환해야 한다
    (Lua 원본과 동일한 난수 계약을 유지해 결정론적 진행을 보장)."""
    for i in range(len(seq), 1, -1):
        j = rng(i)
        seq[i - 1], seq[j - 1] = seq[j - 1], seq[i - 1]


def _line_passive(g, pi, line, flag, uncovered_only=False):
    """`flag`를 가진 앞면 패시브를 (pi, line)에서 찾는다.
    TOP-band 패시브는 덮여도 활성이라 uncovered_only=False(기본)로 전체 스캔;
    BOTTOM-band 패시브는 카드가 uncovered일 때만 활성이라 uncovered_only=True."""
    st = g.players[pi]["stacks"][line]
    for idx, c in enumerate(st):
        passive = c.definition.get("passive")
        if c.face_up and passive and passive.get(flag):
            if not uncovered_only or idx == len(st) - 1:
                return passive
    return None


def _proto_allowed_here(g, line, proto):
    """Unity_1: 프로토콜이 안 맞아도 이 라인에 앞면으로 낼 수 있게 허용됐는가."""
    for top in g.cards_with_def_field("allowFaceUpHere", {"line": line, "top_only": True}):
        if top.definition.get("allowFaceUpHere") == proto:
            return True
    return False


def _same_field_line(a, b):
    return (a.get("zone") == "field" and b.get("zone") == "field"
            and a.get("pi") == b.get("pi") and a.get("line") == b.get("line"))


def _return_redirected(g, card):
    """Corruption_1: 손으로 돌아갈 카드가 소유자의 상대 것이면 덱 위로 대신 간다."""
    for top in g.cards_with_def_field("returnToDeck", {"top_only": True}):
        if card.owner == _other(top.owner):
            return True
    return False


class Engine:
    # -------------------------------------------------------------------
    # 생성
    # -------------------------------------------------------------------
    def __init__(self, *, protocols1, protocols2, ai1=False, ai2=False,
                 rng=None, aux_rng=None, first_player=1,
                 auto_compile=False, auto_refresh=False, on_dealt=None,
                 decks=None, ai=None, ai_modules=None, seed=None,
                 ai_lookahead=True):
        # self.rng는 메커니즘(덱 셔플, 랜덤 카드 효과)을 결정한다 -- 이 값이
        # 매치 진행을 결정론적으로 만들어서 리플레이가 똑같이 재현된다.
        # self.aux_rng는 메커니즘과 무관한 잡음(AI 숙고 시간 등)에 쓰이며
        # 메커니즘 스트림을 절대 건드리면 안 된다.
        #
        # seed가 주어지면 실제로 시드된 random.Random을 만들어 쓴다 (예전엔
        # self.seed에 저장만 되고 rng 생성엔 전혀 반영이 안 되던 죽은
        # 파라미터였음 -- clone_at_decision의 재생 기반 복제가 여기 의존함).
        # rng를 직접 넘기면(테스트 등) 그게 우선이고, aux_rng는 메커니즘
        # 스트림과 겹치지 않도록 다른 시드에서 파생한 별도 스트림을 쓴다.
        if rng is not None:
            self.rng = rng
        elif seed is not None:
            _rng_state = random.Random(seed)
            self.rng = lambda n: _rng_state.randint(1, n)
        else:
            self.rng = lambda n: random.randint(1, n)
        if aux_rng is not None:
            self.aux_rng = aux_rng
        elif seed is not None:
            _aux_state = random.Random(seed ^ 0x5BD1E995)
            self.aux_rng = lambda n: _aux_state.randint(1, n)
        else:
            self.aux_rng = self.rng

        self.uid = 0
        self.cards_by_uid = {}
        self.log = []
        self.winner = None
        self.control = None
        self.cant_compile = {1: False, 2: False}
        self.pending = None
        self.error = None

        # 스레드 기반 "코루틴" 제어용 상태
        self._thread = None
        self._out_queue = Queue()   # 게임 스레드 -> 메인 스레드
        self._in_queue = Queue()    # 메인 스레드 -> 게임 스레드
        self._awaiting_answer = False

        # 현재 효과가 resolve 중인 카드 스택 (가장 안쪽이 맨 위) -- prompt가
        # 어떤 카드가 동작 중인지 UI에 알려줄 수 있도록.
        self._card_stack = []
        self.acting = None

        self.phase = "setup"
        self.turn_count = 0
        self.auto_compile = auto_compile
        self.auto_refresh = auto_refresh
        self.on_dealt = on_dealt

        self.players = {}
        for i in (1, 2):
            protos = protocols1 if i == 1 else protocols2
            is_ai = ai1 if i == 1 else ai2
            self.players[i] = {
                "index": i,
                "isAI": bool(is_ai),
                # 라인 번호(1,2,3)로 인덱싱 -- stacks/compiled와 동일한 규칙.
                "protocols": {1: protos[0], 2: protos[1], 3: protos[2]},
                "compiled": {1: False, 2: False, 3: False},
                "deck": [], "discard": [], "hand": [],
                "stacks": {1: [], 2: [], 3: []},
            }

        self.turn = first_player or 1
        # cloneAtDecision(나중에 포팅 예정)을 위한 생성 시점 스냅샷: self.turn은
        # 진행되면서 바뀌고 protocols도 Control 재배치로 바뀌므로, 매치 도중
        # 다시 만들 클론은 "원래" 값을 알아야 한다.
        self._first_player = self.turn
        self._protocols = {
            1: dict(self.players[1]["protocols"]),
            2: dict(self.players[2]["protocols"]),
        }

        # 고정 덱 (튜토리얼 / 퍼즐 모드용): decks[pi]가 (proto, value) 튜플을
        # "뽑는 순서"대로 나열하면, 셔플 없이 그대로 스택으로 쌓인다.
        self.fixed_decks = decks

        # AI는 "결정 제공자"이며 주입 가능하다. TODO: ai.py 포팅 후 연결.
        self.ai = ai
        self.ai_modules = ai_modules or {}

        # 매 프롬프트마다 실제로 확정된 답 (AI 결정 포함), 순서대로.
        self.answer_log = []
        self.seed = seed
        self.ai_lookahead = ai_lookahead

        # clone_at_decision()이 쓰는 재생 큐. None이면 평소대로 동작.
        # 값이 있으면(리스트) prompt/emit이 멈추지 않고 그 값들을 그대로
        # 소비하며 빠르게 재생하다가, 다 쓰면 그 지점부터 진짜로 멈춘다
        # (isAI 여부와 무관하게) -- 캐치업한 그 지점이 caller가 실제로
        # 답해야 하는 결정 지점이 되도록.
        self._replay = None
        # 재생이 끝나는 순간 켜지고 그 뒤로는 절대 안 꺼진다: 시뮬레이션
        # 클론은 (원본 살아있는 판이 실제로 AI끼리 두는 판이라 ai1=ai2=True로
        # 만들어졌어도) 캐치업한 결정부터는 그 턴 안의 모든 후속 하위 결정을
        # 전부 playout()의 policy가 답해야 한다 -- 원본 AI 모듈로 자동
        # resolve해버리면(sim엔 실제 AI 모듈을 안 넣어뒀으므로) 크래시난다.
        self._sim_paused_mode = False

        # 진행 중인 zone 이동("commit된 카드") 큐.
        self._commits = []
        # fireReactiveSnapshot의 재귀 깊이 가드 (reactive가 reactive를 유발하는
        # 연쇄가 무한루프로 번지는 것을 막음).
        self._react_depth = 0
        self._flip_depth = 0
        # 컴파일로 지금 비워지는 중인 라인 (Speed_2가 자기 자신을 그 라인 밖으로
        # 이동시킬 때, 목적지가 지워지는 라인이면 uncover를 resolve하면 안 됨).
        self._compiling_line = None

    # -------------------------------------------------------------------
    # 스레드 기반 코루틴 제어
    # -------------------------------------------------------------------
    def start(self):
        """게임을 시작한다: 게임 스레드를 만들고 첫 정지 지점까지 실행."""
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._awaiting_answer = False
        self._thread.start()
        self.step(None)

    def _run_loop(self):
        try:
            self._game_loop()
        except Exception as exc:  # noqa: BLE001 - 엔진 스레드 예외를 메인으로 전달
            self._out_queue.put({"kind": "__error__", "error": exc})
            return
        self._out_queue.put({"kind": "__dead__"})

    def step(self, answer):
        """게임 스레드에 답을 넘기고 재개한다. 다음 정지 지점까지 진행."""
        if self._thread is None:
            return
        if self._awaiting_answer:
            self._in_queue.put(answer)
        payload = self._out_queue.get()  # 다음 정지 지점까지 블로킹
        kind = payload["kind"]
        if kind == "__error__":
            self.error = payload["error"]
            self.pending = None
            self._thread = None
            self._awaiting_answer = False
            return
        if kind == "__dead__":
            self.pending = None
            self._thread = None
            self._awaiting_answer = False
            return
        self.pending = payload  # {kind: "input"|"anim", ...}
        self._awaiting_answer = True

    def answer(self, value):
        """편의 메서드: 입력 요청에 답한다."""
        if self.pending and self.pending.get("kind") == "input":
            self.answer_log.append({"value": value})
            self.step(value)

    def advance_anim(self):
        """편의 메서드: 애니메이션 이벤트를 확인/종료한다."""
        if self.pending and self.pending.get("kind") == "anim":
            self.step(None)

    def clone_at_decision(self):
        """AI 시뮬레이션(1수 앞보기/ISMCTS) 전용 복제.

        살아있는 엔진(스레드/큐가 실제로 붙어 도는 그 인스턴스)을 그대로
        복제하는 게 아니다 (스레드/락은 애초에 pickle/deepcopy가 안 됨).
        대신 같은 시드로 새 Engine을 만들어 self.answer_log를 그대로
        재생해서, 지금과 완전히 같은 결정 지점까지 따라잡는다.

        재생 중엔 prompt()/emit()이 멈추지 않고 기록된 값을 즉시 소비하며
        빠르게 지나가다가(_replay), 재생이 끝나는 순간 -- 정확히 지금 이
        판이 답하려는 그 프롬프트에서 -- isAI 여부와 무관하게 진짜로
        멈춘다. 그 지점부터 caller가 answer()로 원하는 후보 액션을 직접
        시도해볼 수 있다 (원본은 전혀 건드리지 않는 완전히 독립된 사본).

        정상적인 호출 위치는 AI 자신의 decide(g, req) 안, 즉 이 req의
        답이 아직 self.answer_log에 안 남은 바로 그 시점이다 -- 이때는
        prompt()가 AI 분기라 self.pending이 이 req를 반영하지 않지만
        (양쪽 다 AI면 pending은 절대 "input"이 안 됨), 재생 메커니즘
        자체가 answer_log 길이만으로 정확히 같은 지점을 재구성하므로
        문제없다. (사람 차례가 진짜로 멈춰있을 때 바깥에서 힌트용으로
        불러도 마찬가지로 동작한다.)

        seed가 없거나(재현 불가능한 판), 재생이 어긋나면(예: 도중에 카드
        로직이 바뀌어 프롬프트 수가 달라짐) None을 반환한다 -- 호출자는
        이 경우 시뮬레이션 없이 휴리스틱으로 안전하게 폴백해야 한다.
        """
        if self.seed is None:
            return None
        protos1 = [self._protocols[1][line] for line in (1, 2, 3)]
        protos2 = [self._protocols[2][line] for line in (1, 2, 3)]
        sim = Engine(protocols1=protos1, protocols2=protos2,
                     ai1=True, ai2=True,
                     seed=self.seed, first_player=self._first_player,
                     auto_compile=self.auto_compile, auto_refresh=self.auto_refresh,
                     decks=self.fixed_decks)
        sim._replay = [a["value"] for a in self.answer_log]
        sim.start()
        if sim.error or not (sim.pending and sim.pending.get("kind") == "input"):
            sim.dispose()  # 실패 경로에서도 블로킹 중인 스레드가 있으면 정리
            return None
        return sim

    # -------------------------------------------------------------------
    # 카드 스택 / 효과 실행
    # -------------------------------------------------------------------
    def ai_module(self, pi):
        """플레이어 pi의 결정 제공자 (플레이어별 override, 없으면 공용)."""
        return self.ai_modules.get(pi, self.ai)

    def active_chain(self):
        """현재 resolve 중인 카드 스택을 {uid, band} 리스트로 스냅샷."""
        return [{"uid": e["card"].uid, "band": e["band"]} for e in self._card_stack]

    def refresh_acting(self):
        """"누가 무엇을 하고 있는가" 공개 마커를 카드 스택에서 갱신."""
        if not self._card_stack:
            self.acting = None
            return
        top = self._card_stack[-1]
        self.acting = {
            "player": self.turn,
            "band": top["band"],
            "chain": self.active_chain(),
        }

    def run_card(self, card, fn, band, via):
        """카드의 효과 콜백을 "현재 활성 카드"로 표시하며 실행한다."""
        if self.winner:
            return
        alive0 = card.face_up and (
            self.locate(card) is not None or getattr(card, "_committed", False)
        )
        self._card_stack.append({"card": card, "band": band, "alive0": alive0, "via": via})
        self.refresh_acting()
        fn()
        self._card_stack.pop()
        self.refresh_acting()

    def actor(self):
        """지금 행동 중인 플레이어 (로그 귀속용)."""
        if self._card_stack:
            return self._card_stack[-1]["card"].owner
        return self.turn

    def effect_interrupted(self):
        """지금 resolve 중인 카드 효과가 (뒤집히거나 덮여서) 중단됐는가."""
        if not self._card_stack:
            return False
        top = self._card_stack[-1]
        if not top["alive0"]:
            return False
        c = top["card"]
        if not c.face_up:
            return True  # 뒷면으로 뒤집힘 (어느 band든)
        if getattr(c, "_committed", False):
            return False  # 이동 중: 여전히 같은 카드
        pi, line, idx = self.locate(c)
        if pi is None:
            return True  # 필드에서 제거됨
        stack_len = len(self.players[pi]["stacks"][line])
        if (not top.get("inCommand") and top["band"] != "top"
                and top["via"] != "covered" and idx != stack_len - 1):
            return True  # 명령과 명령 사이에 덮임: 나머지는 무효
        return False

    def command(self, fn):
        """fn을 활성 카드 텍스트의 명령 하나로 resolve한다."""
        if self.effect_interrupted():
            return
        top = self._card_stack[-1] if self._card_stack else None
        if top is None:
            fn()
            return
        prev = top.get("inCommand")
        top["inCommand"] = True
        fn()
        top["inCommand"] = prev

    def _wait_for_answer(self):
        """_in_queue에서 답을 기다린다. discard()의 poison pill을 받으면
        즉시 _EngineDiscarded를 던져 스레드가 정리되게 한다. 모든 블로킹
        지점(prompt/spend_control)이 이 메서드 하나를 거치게 통일한다."""
        value = self._in_queue.get()
        if value is _DISCARD:
            raise _EngineDiscarded()
        return value

    def dispose(self):
        """더 이상 쓸 일 없는 엔진(특히 AI 시뮬레이션 클론)의 스레드를
        정리한다. 블로킹 중인 스레드가 있으면 깨워서 즉시 종료시키고,
        실제로 끝났음을 확인한 뒤에 반환한다. 이미 끝난 엔진에 불러도
        안전(아무 일도 안 함)."""
        if self._thread is None:
            return
        if self._awaiting_answer:
            self._in_queue.put(_DISCARD)
            self._out_queue.get()  # __error__(정리됨) 또는 __dead__ 대기
        self._thread = None
        self._awaiting_answer = False

    def prompt(self, req):
        """플레이어에게 결정을 요청한다. 사람이면 입력 대기, AI면 즉시 결정."""
        if self.effect_interrupted():
            return None
        top = self._card_stack[-1] if self._card_stack else None
        if top:
            if req.get("sourceUid") is None:
                req["sourceUid"] = top["card"].uid
            if req.get("sourceBand") is None:
                req["sourceBand"] = top["band"]
            if req.get("sourceChain") is None:
                req["sourceChain"] = self.active_chain()
        if self._replay is not None:
            if self._replay:
                value = self._replay.pop(0)
                self.answer_log.append({"value": value})
                return value
            # 재생 끝: 지금부터가 원본이 실제로 답해야 했던 결정 지점이다.
            # isAI 여부와 무관하게 진짜로 멈춰서 caller(시뮬레이션 드라이버)가
            # 후보 액션을 직접 답하게 한다. 이후 이 판이 끝날 때까지 계속
            # 이렇게 동작해야 하므로(그 턴 안의 하위 결정들도 playout()의
            # policy가 답함) _sim_paused_mode를 영구히 켠다.
            self._replay = None
            self._sim_paused_mode = True
        if self._sim_paused_mode:
            if threading.current_thread() is self._thread:
                self._out_queue.put({"kind": "input", "req": req})
                return self._wait_for_answer()
            return None
        chooser = self.players.get(req.get("chooser"))
        if chooser and chooser["isAI"]:
            value = self.ai_module(req["chooser"]).decide(self, req)
            self.answer_log.append({"value": value})
            return value
        if threading.current_thread() is self._thread:
            self._out_queue.put({"kind": "input", "req": req})
            return self._wait_for_answer()
        # 폴백 (원칙적으로 일어나면 안 됨): 그럴듯한 기본값을 고른다.
        value = self.ai_module(req.get("chooser")).decide(self, req)
        self.answer_log.append({"value": value})
        return value

    def emit(self, kind, data=None):
        """씬에 애니메이션/페이싱 이벤트를 yield한다. 짧은 지연 뒤 재개."""
        data = dict(data) if data else {}
        data["kind"] = kind
        if data.get("i18n") and not data.get("noLog"):
            self.logmsg(data["i18n"])
        if self._replay is not None:
            return  # 재생 중엔 애니메이션 정지 없이 그대로 통과 (빠른 재생)
        if threading.current_thread() is self._thread:
            self._out_queue.put({"kind": "anim", "event": data, "dur": data.get("dur", 0.45)})
            self._wait_for_answer()

    # -------------------------------------------------------------------
    # 위치 헬퍼
    # -------------------------------------------------------------------
    def locate(self, card):
        """보드 스택 위 카드의 (플레이어, 라인, 인덱스)를 반환. 없으면 (None, None, None)."""
        for pi in (1, 2):
            for line in (1, 2, 3):
                stack = self.players[pi]["stacks"][line]
                for idx, x in enumerate(stack):
                    if x is card:
                        return pi, line, idx
        return None, None, None

    # -------------------------------------------------------------------
    # 선택 요청 (prompt 래퍼)
    # -------------------------------------------------------------------
    def cards_in_play(self, filter_fn=None):
        out = []
        for pi in (1, 2):
            for line in (1, 2, 3):
                for c in self.players[pi]["stacks"][line]:
                    if filter_fn is None or filter_fn(c, pi, line):
                        out.append(c)
        return out

    def choose_card_from(self, chooser, candidates, opts=None):
        """chooser에게 후보 목록에서 카드 한 장을 고르게 한다. 카드 또는 None."""
        opts = opts or {}
        # 이동 중("committed")인 카드는 어떤 효과의 대상도 될 수 없다.
        candidates = [c for c in candidates if not getattr(c, "_committed", False)]
        if not candidates:
            return None
        uids = [c.uid for c in candidates]
        req = {
            "type": "chooseCard", "chooser": chooser, "candidates": uids,
            "optional": opts.get("optional", False),
            "fromHand": opts.get("fromHand"),
            "pickCards": opts.get("pickCards"),
            "dests": opts.get("dests"),
            "prompt": opts.get("prompt", "카드를 선택하세요"),
            "intent": opts.get("intent"),
        }
        if opts.get("showcase"):
            req["showcase"] = True
            req["cards"] = [{"uid": c.uid, "proto": c.proto, "value": c.value} for c in candidates]
        pick = self.prompt(req)
        if not pick:
            return None
        return self.cards_by_uid.get(pick)

    def choose_line_from(self, chooser, lines, opts=None):
        opts = opts or {}
        if not lines:
            return None
        return self.prompt({
            "type": "chooseLine", "chooser": chooser, "candidates": lines,
            "target": opts.get("target"),
            "prompt": opts.get("prompt", "라인을 선택하세요"), "promptParams": opts.get("promptParams"),
            "intent": opts.get("intent"),
        })

    def choose_option_from(self, chooser, options, opts=None):
        """options의 값(숫자/프로토콜 등) 중 하나를 고르게 한다. opts.kind는 UI 라벨용."""
        opts = opts or {}
        if not options:
            return None
        return self.prompt({
            "type": "chooseOption", "chooser": chooser, "candidates": options,
            "optionKind": opts.get("kind"), "optional": opts.get("optional", False),
            "labels": opts.get("labels"),
            "prompt": opts.get("prompt", "옵션을 선택하세요"), "intent": opts.get("intent"),
        })

    def choose_rearrange(self, chooser, target, opts=None):
        """target의 프로토콜 3개를 chooser가 자유롭게 재배열. {위치: 원래라인} 딕셔너리 반환.
        opts.must_change (기본 True): 카드 효과로 인한 재배열은 룰북상 반드시
        위치가 바뀌어야 한다. Control로 인한 재배열은 "may rearrange"(선택)라
        그대로 둘 수 있으므로, spend_control은 must_change=False로 부른다."""
        opts = opts or {}
        must_change = opts.get("must_change", True)
        protos = self.players[target]["protocols"]
        order = self.prompt({
            "type": "rearrange", "chooser": chooser, "target": target,
            "protocols": {1: protos[1], 2: protos[2], 3: protos[3]},
            "prompt": opts.get("prompt", "프로토콜을 재배열하세요"), "intent": "rearrange",
            "mustChange": must_change,
        })
        identity = {1: 1, 2: 2, 3: 3}
        forced_default = {1: 2, 2: 1, 3: 3}
        fallback = forced_default if must_change else identity
        # 웹 API를 거치면 JSON 직렬화 때문에 딕셔너리 키가 전부 문자열이 된다
        # ("1","2","3") -- 정수 키로 정규화해서 비교/조회가 제대로 되게 한다.
        if isinstance(order, dict):
            normalized = {}
            for k, v in order.items():
                try:
                    normalized[int(k)] = v
                except (TypeError, ValueError):
                    return fallback
            order = normalized
        if not isinstance(order, dict):
            return fallback
        seen = set()
        for pos in (1, 2, 3):
            l = order.get(pos)
            if not isinstance(l, int) or l < 1 or l > 3 or l in seen:
                return fallback
            seen.add(l)
        if must_change and order == identity:
            return forced_default
        return order

    # -------------------------------------------------------------------
    # 카드 생성 / 로그
    # -------------------------------------------------------------------
    def new_card(self, proto, value, owner):
        self.uid += 1
        definition = Cards.get(proto, value)
        c = Card(uid=self.uid, proto=proto, value=value, owner=owner, definition=definition)
        self.cards_by_uid[c.uid] = c
        return c

    def logmsg(self, entry):
        """로그 한 줄을 남긴다. 카드 효과 resolve 중이면 원인(entry["src"])을 태깅."""
        top = self._card_stack[-1] if self._card_stack else None
        if top and isinstance(entry, dict) and not entry.get("src"):
            c = top["card"]
            entry["src"] = {
                "uid": c.uid, "depth": len(self._card_stack), "via": top["via"],
                "band": top["band"],
                "proto": c.proto if c.face_up else None,
                "value": c.value if c.face_up else None,
            }
        if isinstance(entry, dict):
            self._log_seq = getattr(self, "_log_seq", 0) + 1
            entry["n"] = self._log_seq
        self.log.append(entry)
        if len(self.log) > 200:
            self.log.pop(0)

    # -------------------------------------------------------------------
    # 보드 조회
    # -------------------------------------------------------------------
    def top_card(self, pi, line):
        st = self.players[pi]["stacks"][line]
        return st[-1] if st else None

    def is_uncovered(self, card):
        """카드에 "활성 명령"이 있으려면 스택의 맨 위(uncovered) 카드여야 한다."""
        pi, line, idx = self.locate(card)
        if pi is None:
            return False
        return idx == len(self.players[pi]["stacks"][line]) - 1

    def passives_suppressed(self, line):
        """이 라인이 Middle 명령을 전부 무시하는가? (Apathy_2)"""
        for pi in (1, 2):
            for c in self.players[pi]["stacks"][line]:
                if c.face_up and c.definition.get("passive", {}).get("ignoreMiddle"):
                    return True
        return False

    # -------------------------------------------------------------------
    # 값 계산
    # -------------------------------------------------------------------
    def facedown_value_in_stack(self, stack):
        for c in stack:
            if c.face_up:
                val = c.definition.get("passive", {}).get("facedownValueThisStack")
                if val:
                    return val
        return 2

    def facedown_in_line(self, line):
        n = 0
        for pi in (1, 2):
            for c in self.players[pi]["stacks"][line]:
                if not c.face_up:
                    n += 1
        return n

    def line_value(self, pi, line):
        st = self.players[pi]["stacks"][line]
        fd_val = self.facedown_value_in_stack(st)
        total = 0
        for c in st:
            total += c.value if c.face_up else fd_val
        # 자기 자신 값 보정 패시브 (Apathy_0)
        for c in st:
            if c.face_up:
                fn = c.definition.get("passive", {}).get("lineValueSelf")
                if fn:
                    total += fn(self, c, line)
        # 이 라인의 상대편 값 감소 패시브 (Metal_0)
        for c in self.players[_other(pi)]["stacks"][line]:
            if c.face_up:
                delta = c.definition.get("passive", {}).get("lineValueOppDelta")
                if delta:
                    total += delta
        return total

    def winning_line(self, pi, line):
        return self.line_value(pi, line) > self.line_value(_other(pi), line)

    def lines_winning_count(self, pi):
        return sum(1 for line in (1, 2, 3) if self.winning_line(pi, line))

    def compilable_lines(self, pi):
        """지금 pi가 컴파일할 수 있는 라인들."""
        out = []
        if self.cant_compile[pi]:
            return out
        for line in (1, 2, 3):
            if (self.line_value(pi, line) >= Rules.COMPILE_THRESHOLD
                    and self.winning_line(pi, line)):
                out.append(line)
        return out

    # -------------------------------------------------------------------
    # 패시브 규칙 조회 (플레이 적법성)
    # -------------------------------------------------------------------
    def cards_with_def_field(self, field, opts=None):
        """`field`를 가진 모든 앞면 카드를 보드 전체에서 스캔.
        opts: player(한쪽만), line(한 라인만), top_only(각 스택의 맨 위만),
        passive(def 대신 def.passive에서 field를 찾음)."""
        opts = opts or {}
        out = []
        for pi in (1, 2):
            if opts.get("player") and opts["player"] != pi:
                continue
            for line in (1, 2, 3):
                if opts.get("line") and opts["line"] != line:
                    continue
                st = self.players[pi]["stacks"][line]
                indices = ([len(st) - 1] if st else []) if opts.get("top_only") else range(len(st))
                for idx in indices:
                    c = st[idx]
                    d = c.definition.get("passive") if opts.get("passive") else c.definition
                    if c.face_up and d and d.get(field):
                        out.append(c)
        return out

    def can_play_face_up(self, pi, card, line, any_proto=False):
        """플레이어 pi가 `card`를 `line`에 앞면으로 낼 수 있는가?"""
        me = self.players[pi]
        bypass = (
            any_proto
            or bool(card.definition.get("freePlay"))
            or any(_line_passive(self, pi, l, "playAnywhere") for l in (1, 2, 3))
            or _proto_allowed_here(self, line, card.proto)
        )
        if not bypass:
            mine_proto = me["protocols"][line]
            opp_proto = self.players[_other(pi)]["protocols"][line]
            if card.proto != mine_proto and card.proto != opp_proto:
                return False, "이 라인과 프로토콜이 일치하지 않습니다"
        if _line_passive(self, _other(pi), line, "oppNoPlayHere", uncovered_only=True):
            return False, "이 라인에 낼 수 없습니다"
        return True, None

    def can_play_face_down(self, pi, card, line):
        """플레이어 pi가 `card`를 `line`에 뒷면으로 낼 수 있는가? card는 None 가능."""
        if _line_passive(self, _other(pi), line, "oppNoPlayHere", uncovered_only=True):
            return False, "이 라인에 낼 수 없습니다"
        if _line_passive(self, _other(pi), line, "oppNoFacedownHere"):
            return False, "이 라인에 뒷면으로 낼 수 없습니다"
        return True, None

    def can_play_on_opp_side(self, pi, card, line, face_up):
        """플레이어 pi가 `card`를 상대편 쪽에 낼 수 있는가? (Corruption_0)"""
        if not card.definition.get("playAnySide"):
            return False, None
        if _line_passive(self, _other(pi), line, "oppNoPlayHere", uncovered_only=True):
            return False, "이 라인에 낼 수 없습니다"
        if not face_up and _line_passive(self, _other(pi), line, "oppNoFacedownHere"):
            return False, "이 라인에 뒷면으로 낼 수 없습니다"
        return True, None

    def forced_face_down_only(self, pi):
        """pi가 이번 턴 뒷면으로만 낼 수 있게 강제됐는가? (상대의 Psychic_1)"""
        return any(_line_passive(self, _other(pi), line, "oppOnlyFacedown") for line in (1, 2, 3))

    # -------------------------------------------------------------------
    # 덱 / 손 조작
    # -------------------------------------------------------------------
    def reshuffle_discard_into_deck(self, pi):
        if self.effect_interrupted():
            return False
        p = self.players[pi]
        if not p["discard"]:
            return False
        n = len(p["discard"])
        p["deck"].extend(p["discard"])
        p["discard"] = []
        p["revealedTop"] = None
        _shuffle(p["deck"], self.rng)
        self.emit("reshuffle", {"player": pi, "n": n, "dur": 0.6,
                                 "i18n": {"key": "ev.reshuffle", "params": {"p": pi, "n": n}}})
        self.fire_reactive(pi, "afterShuffle")
        return True

    def shuffle_deck(self, pi):
        """pi의 덱을 제자리 셔플 (Unity_4)."""
        if self.effect_interrupted():
            return
        p = self.players[pi]
        p["revealedTop"] = None
        _shuffle(p["deck"], self.rng)
        self.emit("shuffleDeck", {"player": pi, "dur": 0.5,
                                   "i18n": {"key": "ev.shuffleDeck", "params": {"p": pi}}})
        self.fire_reactive(pi, "afterShuffle")

    def set_revealed_top(self, pi, card):
        if self.effect_interrupted():
            return
        p = self.players[pi]
        if not card or not p["deck"] or p["deck"][-1] is not card:
            return
        p["revealedTop"] = card.uid
        self.emit("revealTopStay", {"player": pi, "uid": card.uid,
                                     "i18n": {"key": "ev.revealTopStay", "params": {
                                         "p": pi, "card": {"uid": card.uid, "proto": card.proto,
                                                            "value": card.value}}}})

    def revealed_top_card(self, pi):
        p = self.players[pi]
        revealed = p.get("revealedTop")
        if not revealed:
            return None
        top = p["deck"][-1] if p["deck"] else None
        return top if (top and top.uid == revealed) else None

    def pop_deck(self, pi, may_reshuffle=False):
        """pi의 덱 맨 위 카드를 꺼내 반환. (드로우만 리셔플 가능; 플레이/밀은 불가.)"""
        p = self.players[pi]
        if not p["deck"]:
            if not may_reshuffle:
                return None
            if not self.reshuffle_discard_into_deck(pi):
                return None
        c = p["deck"].pop() if p["deck"] else None
        if c:
            p["revealedTop"] = None
        return c

    def draw_blocked(self, pi):
        """Ice_6: 손에 카드가 있으면 드로우 불가 (지속 효과)."""
        if not self.players[pi]["hand"]:
            return False
        return len(self.cards_with_def_field("noDrawIfHand", {"player": pi, "passive": True})) > 0

    def draw_card_unchecked(self, pi):
        p = self.players[pi]
        c = self.pop_deck(pi, may_reshuffle=True)
        if c:
            p["hand"].append(c)
        return c

    def draw_one(self, pi):
        if self.draw_blocked(pi):
            return None
        return self.draw_card_unchecked(pi)

    def take_from_deck_to_hand(self, pi, card, opts=None):
        """덱 안 특정 카드를 손으로 (Clarity_2/3, Unity_4). 덱 순서는 유지, 셔플 없음."""
        if self.effect_interrupted():
            return False
        p = self.players[pi]
        found = None
        for i in range(len(p["deck"]) - 1, -1, -1):
            if p["deck"][i] is card:
                found = i
                break
        if found is None:
            return False
        p["deck"].pop(found)
        if p.get("revealedTop") == card.uid:
            p["revealedTop"] = None
        p["hand"].append(card)
        if not (opts and opts.get("silent")):
            self.emit("draw", {"player": pi, "n": 1, "uid": card.uid, "dur": MOVE_STAGGER,
                                "i18n": {"key": "ev.draw", "params": {"p": pi, "n": 1}}})
            self.fire_reactive(pi, "afterDraw")
        return True

    def draw_from_deck_of(self, from_pi, to_pi):
        """from_pi의 덱 맨 위 카드를 to_pi의 손으로 (Love_1, Chaos_0, Assimilation)."""
        if self.effect_interrupted():
            return None
        if self.draw_blocked(to_pi):
            return None
        card = self.pop_deck(from_pi, may_reshuffle=True)
        if not card:
            return None
        card.owner = to_pi
        self.players[to_pi]["hand"].append(card)
        self.emit("take", {"i18n": {"key": "ev.drawFromDeck", "params": {"p": to_pi, "opp": from_pi}}})
        self.fire_reactive(to_pi, "afterDraw")
        return card

    def mill_top(self, pi):
        """pi의 덱 맨 위 카드를 버림더미로 ("mill")."""
        if self.effect_interrupted():
            return None
        p = self.players[pi]
        c = self.pop_deck(pi)
        if not c:
            return None
        c.face_up = True
        p["discard"].append(c)
        self.emit("millTop", {"player": pi, "uid": c.uid,
                               "i18n": {"key": "ev.millTop", "params": {
                                   "p": pi, "card": {"uid": c.uid, "proto": c.proto, "value": c.value}}}})
        self.fire_reactive(pi, "afterDiscard")
        return c

    def discard_deck(self, pi):
        """Time_1: pi의 덱 전체를 버림더미로."""
        if self.effect_interrupted():
            return 0
        p = self.players[pi]
        n = len(p["deck"])
        if n == 0:
            return 0
        for c in reversed(p["deck"]):
            c.face_up = True
            p["discard"].append(c)
        p["deck"] = []
        p["revealedTop"] = None
        self.emit("discardDeck", {"player": pi, "n": n, "dur": 0.6,
                                   "i18n": {"key": "ev.discardDeck", "params": {"p": pi, "n": n}}})
        self.fire_reactive(pi, "afterDiscard")
        return n

    def draw(self, pi, n):
        if self.effect_interrupted():
            return 0
        if self.draw_blocked(pi):
            return 0
        got = 0
        for _ in range(n):
            c = self.draw_card_unchecked(pi)
            if not c:
                break
            got += 1
            self.emit("draw", {"player": pi, "n": 1, "dur": MOVE_STAGGER,
                                "i18n": ({"key": "ev.draw", "params": {"p": pi, "n": n}}
                                         if got == 1 else None)})
        if got > 0:
            self.fire_reactive(pi, "afterDraw")
        return got

    def discard_hand_by_uids(self, pi, uids, opts=None):
        if self.effect_interrupted():
            return 0
        p = self.players[pi]
        wanted = set(uids)
        to_remove = [c for c in p["hand"] if c.uid in wanted]
        removed = 0
        for c in to_remove:
            p["hand"] = [x for x in p["hand"] if x is not c]
            c.face_up = True
            p["discard"].append(c)
            removed += 1
            self.emit("discard", {"player": pi, "n": 1, "uid": c.uid, "dur": MOVE_STAGGER,
                                   "i18n": {"key": "ev.discardCard", "params": {
                                       "p": pi, "card": {"uid": c.uid, "proto": c.proto, "value": c.value}}}})
        if removed > 0 and not (opts and opts.get("silent")):
            self.fire_reactive(pi, "afterDiscard")
        return removed

    def discard(self, pi, count, opts=None):
        opts = opts or {}
        p = self.players[pi]
        if not p["hand"]:
            return 0
        count = min(count, len(p["hand"]))
        if count <= 0:
            return 0
        pick = self.prompt({
            "type": "chooseHandCards", "chooser": pi, "player": pi,
            "count": count, "min": opts.get("min", count),
            "prompt": opts.get("prompt", "카드를 버리세요"),
            "intent": opts.get("intent"),
        })
        pick = pick or []
        if len(pick) > count:  # 안전장치: 클라이언트가 count를 넘겨 보내도 서버에서 자름
            pick = pick[:count]
        return self.discard_hand_by_uids(pi, pick)

    def refresh(self, pi):
        """손이 HAND_SIZE가 될 때까지 한 장씩 드로우 (버리기는 안 함)."""
        if self.effect_interrupted():
            return
        # Control을 쥔 채로 리프레시하면 (재배치 포함) 리프레시가 resolve되기
        # 전에 소비된다 (룰북 순서).
        self.spend_control(pi)
        p = self.players[pi]
        logged = False

        def refresh_log():
            nonlocal logged
            if logged:
                return None
            logged = True
            return {"key": "ev.refresh", "params": {"p": pi}}

        got = 0
        if not self.draw_blocked(pi):
            while len(p["hand"]) < Rules.HAND_SIZE:
                c = self.draw_card_unchecked(pi)
                if not c:
                    break
                got += 1
                self.emit("draw", {"player": pi, "n": 1, "uid": c.uid, "dur": MOVE_STAGGER,
                                    "i18n": refresh_log()})
        if got > 0:
            self.fire_reactive(pi, "afterDraw")
        self.fire_reactive(pi, "afterRefresh")

    def build_decks(self):
        """각 플레이어의 프로토콜 3개(6장씩)로 덱을 만들고 셔플한 뒤 5장을 뽑는다."""
        for pi in (1, 2):
            p = self.players[pi]
            deck = []
            fixed = self.fixed_decks.get(pi) if self.fixed_decks else None
            if fixed:
                # 뽑는 순서 -> 스택 순서: drawOne은 END에서 꺼낸다.
                for proto, value in reversed(fixed):
                    deck.append(self.new_card(proto, value, pi))
            else:
                for proto in p["protocols"].values():
                    for v in Protocols.VALUES[proto]:
                        deck.append(self.new_card(proto, v, pi))
                _shuffle(deck, self.rng)
            p["deck"] = deck
            p["hand"] = []
            p["discard"] = []
            for _ in range(Rules.HAND_SIZE):
                self.draw_one(pi)

    # -------------------------------------------------------------------
    # 리액티브 트리거 ("~한 후", 앞면으로 uncovered인 카드에서)
    # -------------------------------------------------------------------
    def snapshot_reactive(self, event):
        snap = {"event": event, "entries": []}
        # bot-band 리액티브: uncovered 앞면 top 카드만 활성
        for pi in (1, 2):
            for line in (1, 2, 3):
                top = self.top_card(pi, line)
                if top and top.face_up and top.definition.get("reactive", {}).get(event):
                    snap["entries"].append({"card": top, "band": "bot", "line": line})
        # top-band 리액티브는 Persistent: 덮여도 앞면이면 활성.
        for c in self.cards_with_def_field("reactiveTop"):
            if c.definition["reactiveTop"].get(event):
                _, line, _ = self.locate(c)
                snap["entries"].append({"card": c, "band": "top", "line": line})
        return snap

    def fire_reactive_snapshot(self, snap, actor, ctx=None):
        event = snap["event"]
        self._react_depth += 1
        if self._react_depth > 6:
            self._react_depth -= 1
            return
        for s in snap["entries"]:
            c = s["card"]
            if s["band"] == "bot":
                if c.face_up and self.is_uncovered(c):
                    fn = c.definition["reactive"][event]
                    self.run_card(c, lambda: fn(self, c, actor, ctx, s), "bot", "reactive")
            elif c.face_up and self.locate(c)[0] is not None:
                fn = c.definition["reactiveTop"][event]
                self.run_card(c, lambda: fn(self, c, actor, ctx, s), "top", "reactive")
        self._react_depth -= 1

    def fire_reactive(self, actor, event, ctx=None):
        self.fire_reactive_snapshot(self.snapshot_reactive(event), actor, ctx)

    # -------------------------------------------------------------------
    # 카드 배치 (커버 트리거 포함)
    # -------------------------------------------------------------------
    def resolve_cover_trigger(self, pi, line, incoming, incoming_face_up):
        """스택에 새 카드가 놓이기 직전, 현재 top 카드의 "덮이기 전" 트리거를 resolve."""
        top = self.top_card(pi, line)
        if top and top.face_up and top.definition.get("onCovered"):
            fn = top.definition["onCovered"]
            self.run_card(top, lambda: fn(self, top, incoming, incoming_face_up), "bot", "covered")

    def place_on_stack(self, card, pi, line, face_up):
        """(pi,line) 스택 맨 위에 카드를 놓는다. 덮이는 카드가 있으면 커버 트리거 처리."""
        st = self.players[pi]["stacks"][line]
        covered = len(st) > 0
        if covered:
            self.resolve_cover_trigger(pi, line, card, face_up)
        st = self.players[pi]["stacks"][line]  # 커버 트리거가 스택을 바꿨을 수 있어 다시 조회
        covered = len(st) > 0
        card.owner = card.owner or pi
        card.face_up = face_up
        st.append(card)
        return covered

    # ---- Committed cards (룰북 "Committed Cards") ----
    # 트리거가 걸릴 수 있는 zone 간 이동은 전부 COMMIT을 거친다: 카드가 원래
    # zone을 떠나 목적지가 "확정"된 채로 여기 큐에 걸리고, "떠남"의 결과(uncover
    # cascade 등)가 다 처리된 다음에야 실제로 "착지(land)"한다. commit된 동안
    # 카드는 어느 zone에도 속하지 않는다 -- 아무 조회/선택도 이 카드를 못 찾는다.

    def commit(self, card, dest, after_land=None):
        card._committed = True
        e = {"card": card, "dest": dest, "afterLand": after_land}
        self._commits.append(e)
        return e

    def commit_blocked_by(self, e):
        """같은 필드 라인에 먼저 걸려 아직 안 착지한 commit (FIFO). 없으면 None."""
        for o in self._commits:
            if o is e:
                return None
            if _same_field_line(o["dest"], e["dest"]):
                return o
        return None

    def land_commit(self, e):
        e["ready"] = True
        if not self.commit_blocked_by(e):
            self.perform_landing(e)

    def perform_landing(self, e):
        e["landing"] = True
        card, d = e["card"], e["dest"]
        if d["zone"] == "field":
            idx = None
            if d.get("underCard"):
                st = self.players[d["pi"]]["stacks"][d["line"]]
                for i, x in enumerate(st):
                    if x is d["underCard"]:
                        idx = i
                        break
            if idx is not None:
                # 밑으로 슬라이드해 들어가는 경우는 새로 덮는 게 아니라 커버 트리거 없음.
                card.owner = card.owner or d["pi"]
                card.face_up = d["faceUp"]
                self.players[d["pi"]]["stacks"][d["line"]].insert(idx, card)
            else:
                self.place_on_stack(card, d["pi"], d["line"], d["faceUp"])
        elif d["zone"] == "trash":
            card.face_up = True
            self.players[card.owner]["discard"].append(card)
        elif d["zone"] == "hand":
            if d.get("owner"):
                card.owner = d["owner"]  # 소유권 이전 (룰북)
            card.face_up = False
            self.players[card.owner]["hand"].append(card)
        elif d["zone"] == "deck":
            card.face_up = False
            self.players[card.owner]["deck"].append(card)  # 덱의 top = 리스트의 끝
            self.players[card.owner]["revealedTop"] = None

        for i, o in enumerate(self._commits):
            if o is e:
                del self._commits[i]
                break
        card._committed = False
        if e.get("afterLand"):
            e["afterLand"](e)
        # 이 착지로 같은 라인의 다음 commit들이 풀렸을 수 있다: 준비된 것들을
        # commit된 순서대로 전부 착지시킨다.
        i = 0
        while i < len(self._commits):
            o = self._commits[i]
            if o.get("ready") and not o.get("landing") and not self.commit_blocked_by(o):
                self.perform_landing(o)
                i = 0  # 큐가 바뀌었으니 처음부터 다시 스캔
            else:
                i += 1

    def play_top_face_down(self, pi, line, under_card=None):
        """pi의 덱 맨 위 카드를 뒷면으로 line에 낸다."""
        if self.effect_interrupted():
            return False
        c = self.pop_deck(pi)
        if not c:
            return False
        entry = {"key": "ev.playFaceDown", "params": {"p": pi, "line": line}}
        self.logmsg(entry)

        def after_land(_e):
            self.emit("playFaceDown", {"player": pi, "line": line, "uid": c.uid, "fromDeck": True,
                                        "noLog": True, "i18n": entry})
            self.fire_reactive(pi, "afterPlay", {"line": line, "card": c, "side": pi})

        e = self.commit(c, {"zone": "field", "pi": pi, "line": line, "faceUp": False,
                             "underCard": under_card}, after_land)
        self.land_commit(e)
        return c

    def play_external(self, actor, card, side_pi, line, face_up):
        """손에 있지 않은 카드(트래시/덱 top)를 (side_pi, line)에 낸다."""
        if self.effect_interrupted():
            return False
        card.owner = side_pi
        if face_up:
            entry = {"key": "ev.playFaceUp", "params": {"p": actor, "line": line,
                     "card": {"uid": card.uid, "proto": card.proto, "value": card.value}}}
        else:
            entry = {"key": "ev.playFaceDown", "params": {"p": actor, "line": line}}
        self.logmsg(entry)

        def after_land(_e):
            ctx = {"line": line, "card": card, "side": side_pi}
            if face_up:
                self.emit("playFaceUp", {"player": actor, "line": line, "side": side_pi,
                                          "uid": card.uid, "noLog": True, "i18n": entry})
                # "상대가 이 라인에 카드를 냈을 때" 반응은 PLAY 시점에 자격이 고정된다
                # (Ice_1 소급 적용 버그 방지) -- 지금 낸 카드의 middle이 resolve되기 전에.
                snap = self.snapshot_reactive("afterPlay")
                self.resolve_middle(card, "play")
                self.fire_reactive_snapshot(snap, actor, ctx)
            else:
                self.emit("playFaceDown", {"player": actor, "line": line, "side": side_pi,
                                            "uid": card.uid, "noLog": True, "i18n": entry})
                self.fire_reactive(actor, "afterPlay", ctx)

        e = self.commit(card, {"zone": "field", "pi": side_pi, "line": line, "faceUp": face_up},
                         after_land)
        self.land_commit(e)
        return True

    # -------------------------------------------------------------------
    # Middle("Immediate") 명령
    # -------------------------------------------------------------------
    def middle_suppressed_for(self, card):
        """Fear_0: 소유자 턴 동안 상대 카드는 Middle 명령이 없다."""
        enemy = _other(card.owner)
        if self.turn != enemy:
            return False
        return len(self.cards_with_def_field("oppNoMiddle", {"player": enemy, "passive": True})) > 0

    def resolve_middle(self, card, via):
        """카드의 Middle 명령을 resolve. via: "play"|"flip"|"uncover" (로그 귀속용)."""
        if not (card and card.face_up and card.definition.get("play")):
            return
        _, line, _ = self.locate(card)
        if line and self.passives_suppressed(line):
            self.emit("middleIgnored", {"player": card.owner, "line": line, "uid": card.uid,
                                         "i18n": {"key": "ev.middleIgnored", "params": {
                                             "p": card.owner, "line": line,
                                             "card": {"uid": card.uid, "proto": card.proto,
                                                      "value": card.value}}}})
            return
        if self.middle_suppressed_for(card):
            self.emit("middleIgnored", {"player": card.owner, "line": line, "uid": card.uid,
                                         "i18n": {"key": "ev.middleFear", "params": {
                                             "p": card.owner,
                                             "card": {"uid": card.uid, "proto": card.proto,
                                                      "value": card.value}}}})
            return
        self._flip_depth = getattr(self, "_flip_depth", 0) + 1
        if self._flip_depth <= 8:
            fn = card.definition["play"]
            self.run_card(card, lambda: fn(self, card), "mid", via)
        self._flip_depth -= 1

    def fire_uncover(self, pi, line):
        """(pi,line)의 top에서 카드 한 장이 방금 제거됨: 새 top이 uncover됨."""
        st = self.players[pi]["stacks"][line]
        if st:
            self.resolve_middle(st[-1], "uncover")

    # -------------------------------------------------------------------
    # 턴 액션
    # -------------------------------------------------------------------
    def take_from_hand(self, pi, uid):
        p = self.players[pi]
        for i, c in enumerate(p["hand"]):
            if c.uid == uid:
                return p["hand"].pop(i)
        return None

    def play_card(self, pi, uid, line, face_up, side_pi=None):
        """손 카드(uid)를 line에 낸다."""
        card = self.take_from_hand(pi, uid)
        if not card:
            return False
        return self.play_external(pi, card, side_pi or pi, line, face_up)

    def legal_actions(self, pi):
        """pi의 모든 합법적 행동을 나열 (AI + "낼 게 없음" 판정용)."""
        acts = []
        p = self.players[pi]
        forced_down = self.forced_face_down_only(pi)
        for c in p["hand"]:
            for line in (1, 2, 3):
                if not forced_down:
                    ok, _ = self.can_play_face_up(pi, c, line)
                    if ok:
                        acts.append({"kind": "play", "uid": c.uid, "line": line, "faceUp": True})
                ok, _ = self.can_play_face_down(pi, c, line)
                if ok:
                    acts.append({"kind": "play", "uid": c.uid, "line": line, "faceUp": False})
                # Corruption_0: 상대편 쪽에도 낼 수 있음.
                if c.definition.get("playAnySide"):
                    if not forced_down:
                        ok, _ = self.can_play_on_opp_side(pi, c, line, True)
                        if ok:
                            acts.append({"kind": "play", "uid": c.uid, "line": line,
                                         "faceUp": True, "side": _other(pi)})
                    ok, _ = self.can_play_on_opp_side(pi, c, line, False)
                    if ok:
                        acts.append({"kind": "play", "uid": c.uid, "line": line,
                                     "faceUp": False, "side": _other(pi)})
        if (len(p["hand"]) < Rules.HAND_SIZE and not self.draw_blocked(pi)) or not acts:
            acts.append({"kind": "refresh"})
        return acts

    def perform_action(self, pi, action):
        if action["kind"] == "refresh":
            self.refresh(pi)
        elif action["kind"] == "play":
            self.play_card(pi, action["uid"], action["line"], action["faceUp"], action.get("side"))

    # -------------------------------------------------------------------
    # 삭제 / 반환 / 뒤집기 / 이동 프리미티브 (필드 위 카드에 대해 동작)
    # -------------------------------------------------------------------
    def delete_card(self, card, via_compile=False, silent=False):
        if self.effect_interrupted():
            return False
        ok = self.delete_card_raw(card, via_compile, silent)
        # 단일 삭제도 "카드를 삭제하는 것"이라 Hate_3 등이 자기 자신의 삭제도
        # 보게 하려면 리액티브를 쏴야 한다 (단, 컴파일 클리어는 doCompile에서
        # 배치로 한 번만 쏘므로 여기서 중복 발화하면 안 됨).
        if ok and not via_compile:
            self.fire_reactive(self.actor(), "afterDelete")
        return ok

    def delete_card_raw(self, card, via_compile=False, silent=False):
        """interruption 가드 없는 deleteCard. deleteCards가 배치 처리에 사용."""
        pi, line, idx = self.locate(card)
        if pi is None:
            return False
        st = self.players[pi]["stacks"][line]
        was_top = st[-1] is card
        for i in range(len(st) - 1, -1, -1):
            if st[i] is card:
                del st[i]
                break
        if via_compile:
            # 컴파일은 라인 전체를 한 번에 지운다: uncover도, 중간 effect도 없이
            # 곧바로 트래시로.
            card.face_up = True
            self.players[card.owner]["discard"].append(card)
            if not silent:
                self.emit("delete", {"uid": card.uid, "player": pi, "line": line,
                                      "i18n": {"key": "ev.delete", "params": {
                                          "p": self.actor(), "line": line,
                                          "card": {"uid": card.uid, "proto": card.proto,
                                                   "value": card.value}}}})
            return True
        entry = {"key": "ev.delete", "params": {"p": self.actor(), "line": line,
                 "card": {"uid": card.uid, "proto": card.proto, "value": card.value}}}
        if not silent:
            self.logmsg(entry)

        def after_land(_e):
            if not silent:
                self.emit("delete", {"uid": card.uid, "player": pi, "line": line,
                                      "noLog": True, "i18n": entry})

        e = self.commit(card, {"zone": "trash"}, after_land)
        if was_top:
            self.fire_uncover(pi, line)
        self.land_commit(e)
        return True

    def delete_cards(self, cards, via_compile=False, silent=False, as_actor=None):
        if self.effect_interrupted():
            return False
        any_deleted = False
        for c in cards:
            if self.delete_card_raw(c, via_compile, silent):
                any_deleted = True
        # 지금 resolve 중인 카드의 소유자(actor)에게 귀속 -- 턴 플레이어가 아님.
        if any_deleted:
            self.fire_reactive(as_actor or self.actor(), "afterDelete")
        return any_deleted

    def return_card(self, card):
        """필드의 카드를 소유자 손으로 되돌린다."""
        if self.effect_interrupted():
            return False
        pi, line, idx = self.locate(card)
        if pi is None:
            return False
        to_deck = _return_redirected(self, card)
        st = self.players[pi]["stacks"][line]
        was_top = st[-1] is card
        for i in range(len(st) - 1, -1, -1):
            if st[i] is card:
                del st[i]
                break
        pub_card = ({"uid": card.uid, "proto": card.proto, "value": card.value}
                    if card.face_up else None)
        if to_deck:
            entry = ({"key": "ev.returnToDeckCard", "params": {"p": card.owner, "card": pub_card}}
                     if pub_card else {"key": "ev.returnToDeck", "params": {"p": card.owner}})
        else:
            entry = ({"key": "ev.returnCard", "params": {"p": self.actor(), "card": pub_card}}
                     if pub_card else {"key": "ev.return", "params": {"p": self.actor()}})
        self.logmsg(entry)

        def after_land(_e):
            self.emit("returnToDeck" if to_deck else "return",
                       {"uid": card.uid, "noLog": True, "i18n": entry})

        e = self.commit(card, {"zone": "deck" if to_deck else "hand"}, after_land)
        if was_top:
            self.fire_uncover(pi, line)
        self.land_commit(e)
        return True

    def put_into_hand(self, card, to_pi):
        """필드의 카드를 to_pi의 손으로 옮긴다 (소유권도 함께 이전, Assimilation_0)."""
        if self.effect_interrupted():
            return False
        pi, line, idx = self.locate(card)
        if pi is None:
            return False
        st = self.players[pi]["stacks"][line]
        was_top = st[-1] is card
        for i in range(len(st) - 1, -1, -1):
            if st[i] is card:
                del st[i]
                break
        pub_card = ({"uid": card.uid, "proto": card.proto, "value": card.value}
                    if card.face_up else None)
        entry = ({"key": "ev.takeBoardCard", "params": {"p": to_pi, "card": pub_card}}
                 if pub_card else {"key": "ev.takeBoard", "params": {"p": to_pi}})
        self.logmsg(entry)

        def after_land(_e):
            self.emit("takeBoard", {"uid": card.uid, "noLog": True, "i18n": entry})

        e = self.commit(card, {"zone": "hand", "owner": to_pi}, after_land)
        if was_top:
            self.fire_uncover(pi, line)
        self.land_commit(e)
        return True

    def can_flip(self, card):
        """Ice_4 "뒤집을 수 없음": 앞면+uncovered일 때만 보호가 활성."""
        if card.face_up and card.definition.get("cantFlip") and self.is_uncovered(card):
            return False
        return True

    def flip_card(self, card, opts=None):
        """필드의 카드를 뒤집는다. 앞면으로 뒤집히면 Middle 명령이 다시 발동."""
        if self.effect_interrupted():
            return
        if getattr(card, "_committed", False):
            return
        if not self.can_flip(card):
            return
        if card.face_up and card.definition.get("onFlipSelfDestruct"):
            self.delete_card(card)
            return
        was_face_up = card.face_up
        card.face_up = not card.face_up
        self.emit("flip", {"uid": card.uid, "faceUp": card.face_up,
                            "i18n": {"key": "ev.flipUp" if card.face_up else "ev.flipDownCard",
                                     "params": {"p": self.actor(),
                                                "card": {"uid": card.uid, "proto": card.proto,
                                                         "value": card.value}}}})
        if ((not was_face_up) and card.face_up and self.is_uncovered(card)
                and not (opts and opts.get("noMiddle"))):
            self.resolve_middle(card, "flip")

    def move_card(self, card, to_player, to_line):
        """카드를 toPlayer의 toLine 스택 맨 위로 옮긴다 (shift)."""
        if self.effect_interrupted():
            return False
        pi, line, idx = self.locate(card)
        if pi is None:
            return False
        st = self.players[pi]["stacks"][line]
        was_top = st[-1] is card
        for i in range(len(st) - 1, -1, -1):
            if st[i] is card:
                del st[i]
                break
        if card.face_up:
            entry = {"key": "ev.moveCard", "params": {"p": self.actor(), "fromLine": line,
                     "line": to_line, "card": {"uid": card.uid, "proto": card.proto,
                                                "value": card.value}}}
        else:
            entry = {"key": "ev.move", "params": {"p": self.actor(), "fromLine": line, "line": to_line}}
        self.logmsg(entry)

        def after_land(_e):
            self.emit("move", {"uid": card.uid, "toLine": to_line, "noLog": True, "i18n": entry})
            if not was_top:
                # 옮겨진 카드가 COVERED 상태였다면, 목적지에서는 맨 위가 되어
                # uncover된다 -- 자기 자신의 middle 명령이 다시 발동.
                self.resolve_middle(card, "uncover")

        e = self.commit(card, {"zone": "field", "pi": to_player, "line": to_line,
                                "faceUp": card.face_up}, after_land)
        # 먼저 착지(목적지 스택에 실제로 삽입)부터 끝낸다. 그래야 이 카드가
        # "원래 자리에서도 빠졌고 목적지에도 아직 없는" 허공 상태에서 원래
        # 자리의 uncover 연쇄(아래 fire_uncover)가 다른 카드 효과를 재발동시켜도
        # (예: 영혼2가 드러나 재발동하며 "카드 1장을 뒤집으세요") 그 프롬프트의
        # 후보 목록에 방금 옮겨진 이 카드가 정상적으로 포함된다.
        self.land_commit(e)
        if was_top and not (to_player == pi and to_line == line):
            # 컴파일로 지워지는 중인 라인이면 uncover된 카드의 middle을 resolve하면
            # 안 됨 (어차피 삭제될 카드).
            if line != self._compiling_line:
                self.fire_uncover(pi, line)
        return True

    # -------------------------------------------------------------------
    # 컴파일 + Control
    # -------------------------------------------------------------------
    def check_control(self):
        pi = self.turn
        if self.lines_winning_count(pi) >= 2:
            if self.control != pi:
                self.control = pi
                self.emit("control", {"player": pi,
                                       "i18n": {"key": "ev.controlTake", "params": {"p": pi}}})

    def swap_protocols(self, pi, a, b):
        """두 라인의 프로토콜 카드를 맞바꾼다. 밑에 깔린 카드 스택은 움직이지 않음."""
        if self.effect_interrupted():
            return
        if a == b:
            return
        p = self.players[pi]
        p["protocols"][a], p["protocols"][b] = p["protocols"][b], p["protocols"][a]
        p["compiled"][a], p["compiled"][b] = p["compiled"][b], p["compiled"][a]
        self.emit("rearrange", {"player": pi,
                                 "moves": [
                                     {"from": b, "to": a, "proto": p["protocols"][a],
                                      "compiled": p["compiled"][a]},
                                     {"from": a, "to": b, "proto": p["protocols"][b],
                                      "compiled": p["compiled"][b]},
                                 ],
                                 "i18n": {"key": "ev.rearrange", "params": {"p": pi, "a": a, "b": b}}})

    def rearrange_protocols(self, pi, order):
        """order[슬롯] = 그 슬롯으로 갈 프로토콜이 원래 있던 라인. 전체 재배열."""
        if self.effect_interrupted():
            return
        p = self.players[pi]
        new_proto, new_comp = {}, {}
        for slot in (1, 2, 3):
            new_proto[slot] = p["protocols"][order[slot]]
            new_comp[slot] = p["compiled"][order[slot]]
        p["protocols"], p["compiled"] = new_proto, new_comp
        moves = []
        for slot in (1, 2, 3):
            if order[slot] != slot:
                moves.append({"from": order[slot], "to": slot,
                              "proto": new_proto[slot], "compiled": new_comp[slot]})
        self.emit("rearrange", {"player": pi, "moves": moves or None,
                                 "i18n": {"key": "ev.rearrangeFull", "params": {"p": pi}}})

    def swap_stacks(self, pi, a, b):
        """Mirror_2: 두 스택 전체를 통째로 맞바꾼다 (커버/uncover 트리거 없음)."""
        if self.effect_interrupted():
            return
        if a == b:
            return
        p = self.players[pi]
        p["stacks"][a], p["stacks"][b] = p["stacks"][b], p["stacks"][a]
        self.emit("swapStacks", {"player": pi, "a": a, "b": b,
                                  "i18n": {"key": "ev.swapStacks", "params": {"p": pi, "a": a, "b": b}}})

    def mark_compiled(self, pi, line):
        """(pi,line)을 컴파일 완료로 표시하고, 3개 다 완료면 승리 처리."""
        p = self.players[pi]
        p["compiled"][line] = True
        for l in (1, 2, 3):
            if not p["compiled"][l]:
                return False
        self.winner = pi
        self.emit_win(pi)
        return True

    def emit_win(self, pi):
        self.emit("win", {"player": pi, "i18n": {"key": "ev.win", "params": {"p": pi}}})

    def compile_protocol_effect(self, pi, proto_name):
        """Diversity_0/Unity_1: 카드 효과로 지정된 프로토콜을 컴파일 완료 처리."""
        if self.effect_interrupted():
            return None
        for who in (pi, _other(pi)):
            p = self.players[who]
            for line in (1, 2, 3):
                if p["protocols"][line] == proto_name and not p["compiled"][line]:
                    p["compiled"][line] = True
                    self.emit("compileFlip", {"player": who, "line": line,
                                               "i18n": {"key": "ev.compileFlip", "params": {
                                                   "p": who, "proto": proto_name, "line": line}}})
                    self.mark_compiled(who, line)
                    return line
        return None

    def spend_control(self, pi, compiling_line=None):
        """컴파일/리프레시 시 Control 토큰을 소비: 중앙으로 반납하고 재배치권을 준다."""
        if self.control != pi:
            return
        self.control = None
        self.emit("control", {"player": None, "i18n": {"key": "ev.controlSpend", "params": {"p": pi}}})
        if self.players[pi]["isAI"]:
            if self._replay is not None:
                if self._replay:
                    # prompt()를 거치지 않는 별도 경로라 재생 모드를 직접
                    # 확인해야 한다. answer_log엔 이 결정도 기록돼 있으므로
                    # 그대로 재생.
                    plan = self._replay.pop(0)
                    self.answer_log.append({"value": plan})
                else:
                    # 재생이 정확히 이 결정에서 끝남: prompt()와 동일하게
                    # 진짜로 멈춰서 caller의 답을 기다린다. answer_log는
                    # 여기서 append하지 않는다 -- caller가 answer()로 답을
                    # 넘길 때 그쪽에서 이미 기록하므로, 여기서 또 하면
                    # 중복된다. 이후 계속 이 모드를 유지한다(_sim_paused_mode).
                    self._replay = None
                    self._sim_paused_mode = True
                    req = {"type": "planRearrange", "chooser": pi,
                           "compilingLine": compiling_line}
                    if threading.current_thread() is self._thread:
                        self._out_queue.put({"kind": "input", "req": req})
                        plan = self._wait_for_answer()
                    else:
                        plan = None
            elif self._sim_paused_mode:
                # 재생은 이미 예전에 끝났고(이번 턴 이전) 지금은 그 이후의
                # 하위 결정 -- prompt()와 동일하게 계속 진짜로 멈춘다.
                req = {"type": "planRearrange", "chooser": pi,
                       "compilingLine": compiling_line}
                if threading.current_thread() is self._thread:
                    self._out_queue.put({"kind": "input", "req": req})
                    plan = self._wait_for_answer()
                else:
                    plan = None
            else:
                plan = self.ai_module(pi).planRearrange(self, pi, compiling_line)
                self.answer_log.append({"value": plan})
            if plan:
                self.rearrange_protocols(plan["who"], plan["order"])
            return
        who = self.prompt({"type": "choosePlayer", "chooser": pi,
                            "prompt": "제어: 한 플레이어의 프로토콜을 재배열하세요"})
        if not who:
            return
        order = self.choose_rearrange(pi, who, {
            "prompt": ("자신의 프로토콜을 재배열하세요" if who == pi
                       else "상대의 프로토콜을 재배열하세요"),
            "must_change": False,
        })
        self.rearrange_protocols(who, order)

    def do_compile(self, pi, line):
        """Compile 행동: 라인을 클리어하고 프로토콜을 컴파일 완료로 뒤집는다."""
        # Control을 쥐고 있었다면 -- 재배치 포함 -- 컴파일이 resolve되기 전에 소비.
        self.spend_control(pi, line)
        cp = self.players[pi]
        recompile = cp["compiled"][line]
        self.emit("compileStart", {"player": pi, "line": line, "recompile": recompile or None,
                                    "i18n": {"key": "ev.recompile" if recompile else "ev.compile",
                                             "params": {"p": pi, "proto": cp["protocols"][line],
                                                        "line": line}}})
        # 세 번째 프로토콜을 완료하는 순간 즉시 승리하므로, 이 컴파일이 유발할 수
        # 있는 다른 어떤 효과도 발동하면 안 된다 (Speed_2, afterDelete/afterCompile,
        # End 페이즈 등). winner를 먼저 정해서 runCard의 가드가 전부 막아준다.
        cp["compiled"][line] = True
        won = all(cp["compiled"][l] for l in (1, 2, 3))
        if won:
            self.winner = pi
        to_delete = []
        for who in (1, 2):
            to_delete.extend(self.players[who]["stacks"][line])
        # Speed_2는 컴파일되면 스스로 라인 밖으로 빠져나간다 (top-band 명령이라
        # 덮여있어도 발동).
        self._compiling_line = line
        for c in to_delete:
            if c.face_up and c.definition.get("onCompileDelete"):
                fn = c.definition["onCompileDelete"]
                self.run_card(c, lambda c=c, fn=fn: fn(self, c), "top", "compile")
        self._compiling_line = None
        # 다시 수집 (카드가 라인 밖으로 이동했을 수 있음).
        to_delete = []
        for who in (1, 2):
            to_delete.extend(self.players[who]["stacks"][line])
        clears = []
        for c in to_delete:
            cpi, cline, _ = self.locate(c)
            if cpi is not None:
                clears.append({
                    "uid": c.uid, "player": cpi, "line": cline, "owner": c.owner,
                    "proto": c.proto if c.face_up else None,
                    "value": c.value if c.face_up else None,
                    "faceUp": c.face_up,
                })
        for c in to_delete:
            self.delete_card(c, True, True)  # silent + viaCompile: per-card 이벤트/uncover 없음
        if clears:
            self.emit("compileClear", {"line": line, "clears": clears, "dur": 0.4})
        if to_delete:
            self.fire_reactive(self.actor(), "afterDelete")
        # 라인 클리어와 애니메이션이 큐에 걸렸다. 이 컴파일로 게임이 끝났다면
        # 승리 배너를 띄우고 끝 -- afterCompile 없음.
        if won:
            self.emit_win(pi)
            return
        # 재컴파일 보상: 프로토콜이 다시 뒤집히지 않으니 대신 상대 덱 맨 위를 뽑는다.
        if recompile:
            self.draw_from_deck_of(_other(pi), pi)
        self.fire_reactive(pi, "afterCompile")

    # -------------------------------------------------------------------
    # 페이즈 트리거 (Start/End)
    # -------------------------------------------------------------------
    def collect_phase_triggers(self, pi, field, top_field):
        lst = []
        seen = set()
        for line in (1, 2, 3):
            top = self.top_card(pi, line)
            if top and top.face_up and top.definition.get(field) and top not in seen:
                seen.add(top)
                lst.append({"card": top, "band": "bot", "field": field})
        for c in self.cards_with_def_field(top_field, {"player": pi}):
            if c.face_up and c not in seen:
                seen.add(c)
                lst.append({"card": c, "band": "top", "field": top_field})
        return lst

    def choose_phase_trigger(self, pi, pending, field):
        """사람에게 남은 Start/End 효과 중 무엇을 먼저 resolve할지 묻는다. pending 안의 인덱스 반환."""
        cards = [e["card"] for e in pending]
        is_start = field == "start"
        pick = self.choose_card_from(pi, cards, {
            "pickCards": True,
            "intent": "startEffect" if is_start else "endEffect",
            "prompt": ("어떤 시작 효과를 처리할지 선택하세요" if is_start
                       else "어떤 종료 효과를 처리할지 선택하세요"),
        })
        for i, e in enumerate(pending):
            if e["card"] is pick:
                return i
        return 0

    def phase_trigger_resolvable(self, e):
        """이 페이즈 트리거가 지금 실제로 뭔가를 할 수 있는가? (무의미한 선택지 배제용)"""
        c = e["card"]
        pi, _, _ = self.locate(c)
        visible = c.face_up and pi is not None and (e["band"] == "top" or self.is_uncovered(c))
        if not visible or not c.definition.get(e["field"]):
            return False
        can_map = c.definition.get("can")
        can = can_map.get(e["field"]) if can_map else None
        if can and not can(self, c):
            return False
        return True

    def resolve_phase_triggers(self, pi, field, top_field):
        """스냅샷된 페이즈 효과들을 플레이어가 고르는 순서대로 resolve한다."""
        pending = self.collect_phase_triggers(pi, field, top_field)
        human = not self.players[pi]["isAI"]
        while not self.winner:
            ready = [e for e in pending if self.phase_trigger_resolvable(e)]
            if not ready:
                break
            idx = 0
            if len(ready) > 1 and human:
                idx = self.choose_phase_trigger(pi, ready, field)
            e = ready[idx]
            for i, x in enumerate(pending):
                if x is e:
                    del pending[i]
                    break
            via = "start" if field == "start" else "finish"
            self.run_card(e["card"], lambda e=e: e["card"].definition[e["field"]](self, e["card"]),
                          e["band"], via)

    def resolve_start_triggers(self, pi):
        self.resolve_phase_triggers(pi, "start", "startTop")

    def resolve_end_triggers(self, pi):
        self.resolve_phase_triggers(pi, "finish", "finishTop")

    def skip_cache(self, pi):
        """Spirit_0: 캐시 정리 페이즈를 건너뛰는가."""
        return any(_line_passive(self, pi, line, "skipCache", uncovered_only=True)
                   for line in (1, 2, 3))

    def set_phase(self, name):
        self.phase = name
        self.emit("phase", {"dur": 0.16})

    # -------------------------------------------------------------------
    # 게임 루프
    # -------------------------------------------------------------------
    def resolve_stalemate(self):
        def rank(pi):
            compiled_count = sum(1 for l in (1, 2, 3) if self.players[pi]["compiled"][l])
            total_value = sum(self.line_value(pi, l) for l in (1, 2, 3))
            return compiled_count, total_value

        c1, v1 = rank(1)
        c2, v2 = rank(2)
        if c1 != c2:
            w = 1 if c1 > c2 else 2
        elif v1 != v2:
            w = 1 if v1 > v2 else 2
        elif self.control:
            w = self.control
        else:
            w = 1
        self.winner = w
        self.emit("win", {"player": w, "i18n": {"key": "ev.stalemate", "params": {"p": w}}})

    def run_turn(self, pi):
        self.turn_count += 1
        self.turn = pi
        self.phase = "start"
        self.emit("turnStart", {"player": pi,
                                 "i18n": {"key": "ev.turnStart",
                                          "params": {"p": pi, "n": self.turn_count}}})

        self.resolve_start_triggers(pi)
        if self.winner:
            return

        self.set_phase("control")
        self.check_control()

        self.set_phase("compile")
        compilable = self.compilable_lines(pi)
        if compilable:
            me = self.players[pi]
            line = None
            # 컴파일은 의무. auto-compile이 꺼져 있는 사람은 버튼을 눌러 직접
            # 트리거해야 한다 (여러 후보가 있으면 라인도 선택). AI/auto-compile은
            # 즉시 resolve.
            if not me["isAI"] and not self.auto_compile:
                ans = self.prompt({"type": "confirmCompile", "chooser": pi, "player": pi,
                                    "candidates": compilable, "intent": "compile"})
                for l in compilable:
                    if ans == l:
                        line = ans
                        break
            if not line:
                line = compilable[0]
                if len(compilable) > 1:
                    line = self.choose_line_from(
                        pi, compilable,
                        {"prompt": "컴파일할 프로토콜을 선택하세요", "intent": "compile"}
                    ) or compilable[0]
            self.do_compile(pi, line)
            # 컴파일하면 그게 턴 전체다: 1회성 cant_compile을 지우고 종료.
            self.cant_compile[pi] = False
            if self.winner:
                return
        else:
            self.cant_compile[pi] = False
            self.set_phase("action")
            has_play = any(a["kind"] == "play" for a in self.legal_actions(pi))
            if not has_play:
                # 리프레시가 강제된다. auto-refresh가 꺼진 사람은 버튼을 눌러야 함.
                me = self.players[pi]
                if not me["isAI"] and not self.auto_refresh:
                    self.prompt({"type": "confirmRefresh", "chooser": pi, "player": pi})
                action = {"kind": "refresh"}
            else:
                can_refresh = (len(self.players[pi]["hand"]) < Rules.HAND_SIZE
                               and not self.draw_blocked(pi))
                action = self.prompt({
                    "type": "action", "chooser": pi, "player": pi,
                    "canRefresh": can_refresh,
                    "prompt": "카드를 플레이하거나 리프레시하세요" if can_refresh else "카드를 플레이하세요",
                })
            if not action:
                action = {"kind": "refresh"}
            self.perform_action(pi, action)
            if self.winner:
                return

        # 캐시 정리 확인
        self.set_phase("cache")
        cleared = 0
        if not self.skip_cache(pi):
            p = self.players[pi]
            if len(p["hand"]) > 5:
                cleared = self.discard(pi, len(p["hand"]) - 5,
                                        {"prompt": "정리: 5장까지 버리세요",
                                         "intent": "cache"})
        # "캐시를 정리한 후" (Speed_1)는 실제로 뭔가 버렸을 때만 발동.
        if cleared > 0:
            self.fire_reactive(pi, "afterCache")

        # 종료
        self.set_phase("end")
        self.resolve_end_triggers(pi)

    def _game_loop(self):
        self.build_decks()
        if self.on_dealt:
            self.on_dealt(self)
        self.emit("gameStart", {"i18n": {"key": "ev.gameStart"}})
        while not self.winner:
            self.run_turn(self.turn)
            if self.winner:
                break
            if self.turn_count >= Rules.TURN_CAP:
                self.resolve_stalemate()
                break
            self.turn = _other(self.turn)
        self.phase = "over"
