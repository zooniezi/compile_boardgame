"""컴파일(Compile)의 프로토콜(덱 테마) 정의.
Main 1 + Aux 1 (스페인어판 아트) / Main 2 + Aux 2 / Main 3 + Aux 3 (영어판).
각 프로토콜은 6장짜리 덱이다. 카드 값(VALUES)은 프로토콜마다 다르다
(일부는 중간 숫자를 건너뜀). 테마 색상은 UI 강조용일 뿐 -- 카드 아트
자체는 별도의 비주얼을 가진다.

프로토콜 id는 영어(언어 중립적인 정규 표기)를 사용한다.
"""

# 프로토콜 id의 순서 있는 목록 (에셋 파일명 접두사와 정확히 일치해야 함).
PROTOCOL_LIST = (
    # Main 1 + Aux 1
    "Water", "Love", "Apathy", "Spirit", "Fire",
    "Gravity", "Light", "Metal", "Death", "Hate",
    "Darkness", "Plague", "Psychic", "Speed", "Life",
    # Main 2
    "Chaos", "Clarity", "Corruption", "Courage", "Fear", "Ice",
    "Luck", "Mirror", "Peace", "Smoke", "Time", "War",
    # Aux 2
    "Assimilation", "Diversity", "Unity",
    # Main 3
    "Ambush", "Envy", "Fulcrum", "Gluttony", "Greed", "Lust",
    "Momentum", "Nova", "Overwhelm", "Pride", "Sloth", "Wrath",
    # Aux 3
    "Flexible", "Inert", "Rigid",
)


# 각 프로토콜 덱에 존재하는 카드 값들 (카드 세트 기준).
VALUES = {
    "Water":     (0, 1, 2, 3, 4, 5),
    "Love":      (1, 2, 3, 4, 5, 6),
    "Apathy":    (0, 1, 2, 3, 4, 5),
    "Spirit":    (0, 1, 2, 3, 4, 5),
    "Fire":      (0, 1, 2, 3, 4, 5),
    "Gravity":   (0, 1, 2, 4, 5, 6),
    "Light":     (0, 1, 2, 3, 4, 5),
    "Metal":     (0, 1, 2, 3, 5, 6),
    "Death":     (0, 1, 2, 3, 4, 5),
    "Hate":      (0, 1, 2, 3, 4, 5),
    "Darkness":  (0, 1, 2, 3, 4, 5),
    "Plague":    (0, 1, 2, 3, 4, 5),
    "Psychic":   (0, 1, 2, 3, 4, 5),
    "Speed":     (0, 1, 2, 3, 4, 5),
    "Life":      (0, 1, 2, 3, 4, 5),
    # Main 2
    "Chaos":       (0, 1, 2, 3, 4, 5),
    "Clarity":     (0, 1, 2, 3, 4, 5),
    "Corruption":  (0, 1, 2, 3, 5, 6),
    "Courage":     (0, 1, 2, 3, 5, 6),
    "Fear":        (0, 1, 2, 3, 4, 5),
    "Ice":         (1, 2, 3, 4, 5, 6),
    "Luck":        (0, 1, 2, 3, 4, 5),
    "Mirror":      (0, 1, 2, 3, 4, 5),
    "Peace":       (1, 2, 3, 4, 5, 6),
    "Smoke":       (0, 1, 2, 3, 4, 5),
    "Time":        (0, 1, 2, 3, 4, 5),
    "War":         (0, 1, 2, 3, 4, 5),
    # Aux 2
    "Assimilation": (0, 1, 2, 4, 5, 6),
    "Diversity":    (0, 1, 3, 4, 5, 6),
    "Unity":        (0, 1, 2, 3, 4, 5),
    # Main 3
    "Ambush":    (0, 1, 2, 3, 4, 5),
    "Envy":      (0, 1, 2, 3, 4, 5),
    "Fulcrum":   (0, 1, 2, 3, 4, 5),
    "Gluttony":  (0, 1, 2, 3, 4, 5),
    "Greed":     (0, 1, 2, 3, 4, 5),
    "Lust":      (0, 2, 3, 4, 5, 6),
    "Momentum":  (0, 1, 3, 4, 5, 6),
    "Nova":      (0, 1, 2, 3, 4, 5),
    "Overwhelm": (1, 2, 3, 4, 5, 6),
    "Pride":     (0, 2, 3, 4, 5, 6),
    "Sloth":     (0, 1, 2, 3, 4, 5),
    "Wrath":     (0, 1, 2, 3, 4, 5),
    # Aux 3
    "Flexible": (0, 1, 2, 3, 4, 5),
    "Inert":    (0, 1, 2, 3, 4, 5),
    "Rigid":    (1, 2, 3, 4, 5, 7),
}

# 프로토콜별 네온 강조색 (r, g, b). 각 색은 해당 프로토콜 배경 아트의
# 주요 색조를 기반으로 하되, (더 어두운) 아트 위에서 테두리가 묻히지
# 않고 도드라지도록 밝기/색조를 조정했다. 색조가 겹치는 계열(난색, 청록,
# 보라 등)은 명도/채도로 구분되도록 분산시켰다. 주석은 원본 아트의 색조.
COLOR = {
    "Water":     (0.15, 0.65, 1.00),   # 아트: 짙은 파랑
    "Love":      (1.00, 0.26, 0.48),   # 아트: 진홍-분홍 -> 핫핑크
    "Apathy":    (0.62, 0.64, 0.70),   # 아트: 무채색 -> 차가운 회색
    "Spirit":    (0.21, 0.48, 0.95),   # 아트: 파랑 -> 로열블루
    "Fire":      (1.00, 0.52, 0.08),   # 아트: 주황/빨강 -> 주황
    "Gravity":   (0.63, 0.23, 0.95),   # 아트: 보라
    "Light":     (1.00, 0.92, 0.05),   # 아트: 노랑
    "Metal":     (0.82, 0.77, 0.69),   # 아트: 따뜻한 강철/탄색
    "Death":     (0.80, 0.12, 0.45),   # 아트: 진홍 -> 짙은 진홍-마젠타
    "Hate":      (0.90, 0.13, 0.15),   # 아트: 빨강
    "Darkness":  (0.51, 0.16, 0.62),   # 어두운 아트 -> 짙은 보라
    "Plague":    (0.72, 0.90, 0.14),   # 아트: 황록색 -> 연두
    "Psychic":   (0.79, 0.16, 0.90),   # 아트: 마젠타-보라
    "Speed":     (0.10, 0.84, 0.96),   # 아트: 청록 -> 밝은 시안
    "Life":      (0.18, 1.00, 0.84),   # 아트: 시안 -> 밝은 아쿠아
    # Main 2
    "Chaos":       (0.96, 0.21, 0.77), # 아트: 보라-마젠타 -> 마젠타
    "Clarity":     (1.00, 0.80, 0.91), # 아트: 분홍+파랑 -> 옅은 밝은 분홍
    "Corruption":  (0.16, 0.72, 0.33), # 아트: 초록/빨강 -> 독성 에메랄드
    "Courage":     (1.00, 0.41, 0.32), # 아트: 진홍+주황 -> 코랄
    "Fear":        (0.70, 0.39, 0.18), # 아트: 주황 -> 어두운 번트오렌지
    "Ice":         (0.48, 0.58, 1.00), # 아트: 짙은 파랑 -> 옅은 페리윙클
    "Luck":        (1.00, 0.65, 0.08), # 아트: 주황 -> 호박색
    "Mirror":      (0.69, 0.69, 0.96), # 아트: 파랑 -> 옅은 은청색
    "Peace":       (1.00, 0.95, 0.66), # 아트: 옅은 노랑 -> 크림색
    "Smoke":       (0.38, 0.61, 0.66), # 아트: 청록 -> 탁한 스모키 틸
    "Time":        (0.82, 0.52, 0.39), # 아트: 붉은 코랄 -> 탁한 테라코타
    "War":         (0.93, 0.29, 0.11), # 아트: 주황-빨강 -> 버밀리언
    # Aux 2
    "Assimilation": (0.16, 0.70, 0.74), # 아트: 청록 -> 짙은 틸
    "Diversity":    (0.78, 0.64, 0.04), # 아트: 금색+청록 -> 올리브 골드
    "Unity":        (0.63, 0.43, 0.96), # 아트: 보라 -> 라벤더
    # Main 3
    "Ambush":    (0.76, 0.82, 0.34),  # 아트: 강청색/산성 노랑 -> 옅은 라임
    "Envy":      (0.37, 0.68, 0.82),  # 아트: 파랑/초록 -> 맑은 스틸블루
    "Fulcrum":   (0.55, 0.75, 0.86),  # 아트: 파랑/흰색 -> 옅은 시안블루
    "Gluttony":  (0.92, 0.69, 0.25),  # 아트: 검정/금색 -> 따뜻한 골드
    "Greed":     (0.48, 0.73, 0.78),  # 아트: 보라/청록 -> 아이시틸
    "Lust":      (0.95, 0.35, 0.15),  # 아트: 빨강/초록 -> 뜨거운 주황빨강
    "Momentum":  (0.72, 0.66, 0.86),  # 아트: 호박/라벤더 -> 옅은 라벤더
    "Nova":      (1.00, 0.67, 0.14),  # 아트: 노랑/주황 -> 태양빛 호박색
    "Overwhelm": (0.86, 0.70, 0.55),  # 아트: 검정/크림 -> 따뜻한 모래색
    "Pride":     (0.93, 0.64, 0.16),  # 아트: 금색/갈색 -> 짙은 호박색
    "Sloth":     (0.39, 0.58, 0.60),  # 아트: 파랑/초록/회색 -> 스모키 틸
    "Wrath":     (1.00, 0.31, 0.08),  # 아트: 빨강/주황 -> 강렬한 버밀리언
    # Aux 3
    "Flexible": (0.94, 0.42, 0.70),  # 아트: 분홍/보라 -> 선명한 핑크
    "Inert":    (0.82, 0.57, 0.65),  # 아트: 남색/장미색 -> 더스티로즈
    "Rigid":    (0.84, 0.85, 0.05),  # 아트: 보라/노랑 -> 산성 노랑
}

# 카드 세트(확장판) 분류. 향후 세트를 추가하려면 `SET_ORDER`에 이름을
# 넣고, `SET_LABEL`에 표시용 라벨을 지정한 뒤, `SET`에서 소속 프로토콜을
# 태그하면 된다 -- 태그되지 않은 나머지는 전부 "main1".
SET_ORDER = ("main1", "aux1", "main2", "aux2", "main3", "aux3")  # 도감 표시 순서 (확장 가능)
SET_LABEL = {"main1": "MAIN 1", "aux1": "AUX 1", "main2": "MAIN 2", "aux2": "AUX 2",
             "main3": "MAIN 3", "aux3": "AUX 3"}
SET = {
    "Love": "aux1", "Apathy": "aux1", "Hate": "aux1",
    "Chaos": "main2", "Clarity": "main2", "Corruption": "main2", "Courage": "main2",
    "Fear": "main2", "Ice": "main2", "Luck": "main2", "Mirror": "main2",
    "Peace": "main2", "Smoke": "main2", "Time": "main2", "War": "main2",
    "Assimilation": "aux2", "Diversity": "aux2", "Unity": "aux2",
    "Ambush": "main3", "Envy": "main3", "Fulcrum": "main3", "Gluttony": "main3",
    "Greed": "main3", "Lust": "main3", "Momentum": "main3", "Nova": "main3",
    "Overwhelm": "main3", "Pride": "main3", "Sloth": "main3", "Wrath": "main3",
    "Flexible": "aux3", "Inert": "aux3", "Rigid": "aux3",
}  # 나머지는 기본값 main1

# draftpool.py 등에서 "모든 프로토콜 -> 세트"를 딕셔너리로 직접 조회하기도
# 해서(SET은 main1을 생략하는 축약형이라), 30개 전부 채운 버전도 같이 둔다.
SET_OF = {p: SET.get(p, "main1") for p in PROTOCOL_LIST}


def set_of(protocol_id):
    """프로토콜이 속한 세트를 반환한다 (없으면 기본값 "main1")."""
    return SET.get(protocol_id, "main1")


def color_of(protocol_id):
    """프로토콜의 강조색을 반환한다 (없으면 기본 회색)."""
    return COLOR.get(protocol_id, (0.7, 0.7, 0.7))


def ordinal(protocol_id, value):
    """덱 안에서 카드 값(value)의 0-based 위치를 반환한다 (최솟값 = 0).

    카드 배경 아트는 값 자체가 아니라 이 순번으로 번호가 매겨진다.
    (일부 덱은 0부터 시작하지 않거나 중간 값을 건너뛰기 때문.)
    """
    vals = VALUES.get(protocol_id)
    if vals:
        try:
            return vals.index(value)
        except ValueError:
            pass
    return value  # 폴백: 0부터 시작하는 연속된 덱이라고 가정
