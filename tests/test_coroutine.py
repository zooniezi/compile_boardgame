from src.game.engine import Engine


class _FakeAI:
    def decide(self, g, req):
        return "ai-picked"


class _RecordingEngine(Engine):
    """_game_loop을 오버라이드해 emit/prompt 정지-재개 순서를 기록."""
    def _game_loop(self):
        self.trace = []
        self.trace.append("start")
        self.emit("draw", {"player": 1, "n": 1})
        self.trace.append("after emit")
        value = self.prompt({"chooser": 1, "type": "chooseCard"})
        self.trace.append(f"human answered {value}")
        value2 = self.prompt({"chooser": 2, "type": "chooseCard"})
        self.trace.append(f"ai answered {value2}")
        self.winner = 1


def test_emit_pauses_and_advance_anim_resumes():
    e = _RecordingEngine(protocols1=["Water", "Fire", "Life"],
                          protocols2=["Ice", "Metal", "Death"],
                          ai2=True, ai_modules={2: _FakeAI()})
    e.start()
    assert e.pending["kind"] == "anim"

    e.advance_anim()
    assert e.pending["kind"] == "input"
    assert e.pending["req"]["chooser"] == 1


def test_answer_resumes_and_ai_prompt_does_not_block():
    e = _RecordingEngine(protocols1=["Water", "Fire", "Life"],
                          protocols2=["Ice", "Metal", "Death"],
                          ai2=True, ai_modules={2: _FakeAI()})
    e.start()
    e.advance_anim()
    e.answer("human-picked")

    assert e.pending is None  # 게임 루프가 끝까지 진행되어 죽음
    assert e.winner == 1
    assert e.trace == [
        "start", "after emit",
        "human answered human-picked",
        "ai answered ai-picked",
    ]
    assert e.answer_log == [{"value": "human-picked"}, {"value": "ai-picked"}]


def test_exception_in_game_loop_is_captured_as_error():
    class BrokenEngine(Engine):
        def _game_loop(self):
            raise ValueError("boom")

    e = BrokenEngine(protocols1=["Water", "Fire", "Life"], protocols2=["Ice", "Metal", "Death"])
    e.start()
    assert e.pending is None
    assert isinstance(e.error, ValueError)
