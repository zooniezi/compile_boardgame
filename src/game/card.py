"""보드 위의 카드 한 장을 나타내는 객체.

Lua 원본은 카드를 단순한 테이블(dict)로 표현하고, 필요에 따라 자유롭게
필드를 추가한다 (예: `_committed`). Python에서도 같은 유연함을 유지하기
위해 일반 클래스(dataclass 아님)로 만든다 — 정의되지 않은 속성도 나중에
자유롭게 붙일 수 있다 (예: card._committed = True).

포팅 원본: engine.lua (Engine:newCard)
"""


class Card:
    def __init__(self, uid, proto, value, owner, definition):
        self.uid = uid
        self.proto = proto
        self.value = value
        self.owner = owner
        self.face_up = False
        # 카드 효과 정의 (carddefs.py에서 가져온 play/start/finish/... 딕셔너리).
        # Lua 원본 필드명은 `def`이지만 Python 예약어라 `definition`으로 이름 변경.
        self.definition = definition

    def __repr__(self):
        face = "face_up" if self.face_up else "face_down"
        return f"Card(uid={self.uid}, {self.proto}_{self.value}, owner={self.owner}, {face})"
