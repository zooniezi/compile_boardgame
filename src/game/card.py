"""보드 위의 카드 한 장을 나타내는 객체.

카드마다 필요에 따라 자유롭게 속성을 붙일 수 있도록(예: `_committed`)
일반 클래스(dataclass 아님)로 만든다 — 정의되지 않은 속성도 나중에
자유롭게 붙일 수 있다 (예: card._committed = True).
"""


class Card:
    def __init__(self, uid, proto, value, owner, definition):
        self.uid = uid
        self.proto = proto
        self.value = value
        self.owner = owner
        self.face_up = False
        # 카드 효과 정의 (carddefs.py에서 가져온 play/start/finish/... 딕셔너리).
        # `def`는 파이썬 예약어라 쓸 수 없어 `definition`으로 이름 지었다.
        self.definition = definition

    def __repr__(self):
        face = "face_up" if self.face_up else "face_down"
        return f"Card(uid={self.uid}, {self.proto}_{self.value}, owner={self.owner}, {face})"
