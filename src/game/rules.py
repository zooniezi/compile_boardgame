"""게임 전역 공통 상수 (single source of truth)."""

HAND_SIZE = 5
COMPILE_THRESHOLD = 10
LINES = 3
TURN_CAP = 240  # 무한 대치(스테일메이트) 방지용 안전장치 (engine.resolve_stalemate 참고)
