import pytest

from src.game.engine import Engine


class ScriptedAI:
    """카드 효과 테스트용: prompt()가 순서대로 미리 정해둔 답을 돌려주게 한다."""

    def __init__(self, answers):
        self.answers = list(answers)

    def decide(self, g, req):
        return self.answers.pop(0) if self.answers else None

    def planRearrange(self, g, pi, compiling_line):
        return None


def make_ai(engine_, pi, answers):
    """플레이어 pi를 AI로 표시하고, ScriptedAI로 다음 prompt들의 답을 예약."""
    engine_.players[pi]["isAI"] = True
    engine_.ai_modules[pi] = ScriptedAI(answers)


def neutral_card(engine_, proto, value, owner):
    """"아무 효과 없는 카드"가 필요한 테스트용. proto/value가 실제로 구현된
    카드라도 이 함수로 만들면 항상 빈 definition을 강제해서, 그 카드가
    뒤집히거나 발동할 때 진짜 카드 효과와 우연히 섞이는 걸 막는다."""
    card = engine_.new_card(proto, value, owner)
    card.definition = {}
    return card


@pytest.fixture
def engine():
    """빈 보드, 표준 프로토콜 6개짜리 엔진. build_decks는 호출하지 않은 상태
    (테스트마다 카드를 직접 배치하기 편하도록)."""
    return Engine(protocols1=["Water", "Fire", "Life"],
                  protocols2=["Ice", "Metal", "Death"])


@pytest.fixture
def dealt_engine():
    """덱까지 만들어진(각자 손 5장) 엔진."""
    e = Engine(protocols1=["Water", "Fire", "Life"],
               protocols2=["Ice", "Metal", "Death"])
    e.build_decks()
    return e
