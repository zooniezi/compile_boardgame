"""카드 효과 태그 -- AI가 카드 효과를 데이터로 읽을 수 있게 함.

DEFS는 카드 효과를 클로저({"play": <function>})로 담고 있어서, AI 입장에서는
"뒤집기"와 "삭제"가 똑같이 그냥 "함수 하나"로만 보인다. 여기서는 그 효과가
구조적으로 뭘 하는지를 데이터로 다시 기술해서, AI가 판 상황에 비추어 값을
계산할 수 있게 한다.

TAGS는 카드 텍스트가 아니라 carddefs.py의 실제 구현과 대조해서 채운다 --
텍스트만 보고 짐작하면 "누가 대상인지"(양쪽/상대만), "강제/선택" 같은 미묘한
차이를 놓치기 쉽다.

포팅 원본: ai_prior.lua (필드명은 파이썬 스타일로: selfDiscard -> self_discard 등)
"""

from src.game.rules import COMPILE_THRESHOLD

TAGS = {}

# =============================================================================
# AUX 1 -- LOVE / APATHY / HATE
# carddefs.py의 실제 구현(_love_*, _apathy_*, _hate_* 등)과 대조해서 채움.
# =============================================================================

# --- LOVE ---
# Love_1: play로 상대 덱 맨 위를 뽑아옴(사실상 draw) + End에 "1장 주고 2장
# 뽑기" 선택 트리거를 계속 갖고 있음(ongoing).
TAGS["Love_1"] = {"draw": 1, "ongoing": True}
# Love_2: 상대가 1장 뽑고(opp_draw) 나는 리프레시.
TAGS["Love_2"] = {"opp_draw": 1, "refresh_self": True}
# Love_3: 상대 손패에서 무작위로 1장 훔치고, 내 손패가 있으면 1장 돌려줌
# (내가 고르는 거라 제일 약한 카드를 줌 -- 순가치는 약한 카드 <-> 무작위
# 카드 교환에 가까움).
TAGS["Love_3"] = {"draw": 1, "self_discard": 1}
# Love_4: 손패 공개(정보만, 손실 없음) 후 카드 1장 뒤집기(대상 제한 없음).
TAGS["Love_4"] = {"flip": {"n": 1}}
TAGS["Love_5"] = {"self_discard": 1}
TAGS["Love_6"] = {"opp_draw": 2}

# --- APATHY ---
# Apathy_0: 패시브로 이 라인 값이 뒷면 카드 수만큼 오름 -- 지속 효과.
TAGS["Apathy_0"] = {"ongoing": True}
# Apathy_1: 이 라인의 다른 앞면 카드 전부(양쪽)를 뒤집음 -- 내가 유리한
# 라인/구성일 때만 좋은 양날의 카드.
TAGS["Apathy_1"] = {"flip": {"n": "all"}}
# Apathy_2: 이 라인 중앙 명령 무효화(패시브) + 가려질 때 자기 자신을 먼저
# 뒤집음 -- 둘 다 판 상황과 무관하게 늘 유지되는 지속 효과로 취급.
TAGS["Apathy_2"] = {"ongoing": True}
# Apathy_3: 상대의 드러난 앞면 카드 1장을 뒤집음(값을 2로 깎음).
TAGS["Apathy_3"] = {"flip": {"n": 1, "owner": "enemy", "from_face": "up"}}
# Apathy_4: 자신의 가려진 "앞면" 카드 1장을 뒤집을 수 있음(선택) -- 위험한
# 값을 숨기는 방어용.
TAGS["Apathy_4"] = {"flip": {"n": 1, "owner": "own", "from_face": "up", "may": True}}
TAGS["Apathy_5"] = {"self_discard": 1}

# --- HATE ---
# Hate_0: 카드 1장 제거, 대상 제한 없음(양쪽 다 후보 -- _delete_one의
# filter_fn=None으로 확인).
TAGS["Hate_0"] = {"del": {"n": 1}}
# Hate_1: 3장 버리고, 대상 제한 없는 제거를 2번(각각 독립적으로 아무 카드나).
TAGS["Hate_1"] = {"self_discard": 3, "del": {"n": 2}}
# Hate_2: 먼저 "자신의" 최고값 카드 제거, 그다음 "상대의" 최고값 카드 제거
# (순차 2단계라 del을 리스트로).
TAGS["Hate_2"] = {"del": [{"n": 1, "owner": "own"}, {"n": 1, "owner": "enemy"}]}
# Hate_3: 리액티브(자신이 카드를 제거한 후 1장 뽑음) -- 즉시효과가 아니라
# 지속적으로 붙는 보너스라 ongoing으로 취급.
TAGS["Hate_3"] = {"ongoing": True}
# Hate_4: onCovered 트리거(즉시 play 효과가 아님) -- 이후 방어적 가치가
# 있는 지속 성격이라 ongoing으로 취급.
TAGS["Hate_4"] = {"ongoing": True}
TAGS["Hate_5"] = {"self_discard": 1}

# =============================================================================
# MAIN 1
# =============================================================================

# --- WATER ---
TAGS["Water_0"] = {"flip": {"n": 1}}  # 다른 카드 1장 뒤집기(+자기 자신도 뒤집힘, 값은 안 매김)
TAGS["Water_1"] = {"deck_plays": 2}   # 다른 두 라인에 덱에서 뒷면 공짜 플레이
TAGS["Water_2"] = {"draw": 2}
TAGS["Water_3"] = {"ret": {"n": "all", "vmax": 2}}  # 값2(뒷면 포함) 전부 반환, 양쪽
TAGS["Water_4"] = {"ret": {"n": 1, "owner": "own"}}
TAGS["Water_5"] = {"self_discard": 1}

# --- SPIRIT ---
TAGS["Spirit_0"] = {"refresh_self": True, "draw": 1}
TAGS["Spirit_1"] = {"draw": 2, "ongoing": True}
TAGS["Spirit_2"] = {"flip": {"n": 1, "may": True}}
TAGS["Spirit_3"] = {"ongoing": True}
TAGS["Spirit_4"] = {"prior": 1.0}   # 자기 프로토콜 2개 위치 교환 -- 정체된 라인 구제용
TAGS["Spirit_5"] = {"self_discard": 1}

# --- FIRE ---
TAGS["Fire_0"] = {"flip": {"n": 1}, "draw": 2, "ongoing": True}  # onCovered 보너스 포함
TAGS["Fire_1"] = {"self_discard": 1, "del": {"n": 1}, "gated_on_discard": True}
TAGS["Fire_2"] = {"self_discard": 1, "ret": {"n": 1}, "gated_on_discard": True}
TAGS["Fire_3"] = {"ongoing": True}  # End: 선택적 버리기->뒤집기
TAGS["Fire_4"] = {"self_discard": 1, "draw": 2}  # 최소 1장 버림 기준 근사(버릴수록 더 뽑음)
TAGS["Fire_5"] = {"self_discard": 1}

# --- GRAVITY ---
TAGS["Gravity_0"] = {"deck_plays": 1}  # 이 라인 카드 2장마다 -- 변동적이라 보수적으로 1
TAGS["Gravity_1"] = {"draw": 2}
TAGS["Gravity_2"] = {"flip": {"n": 1}}
TAGS["Gravity_4"] = {"prior": 1.0}  # 뒷면 카드를 이 라인으로 이동 -- 소유자 무관 재배치 도구
# Gravity_6: 상대가 자기 덱 맨 위를 이 라인에 뒷면으로 냄 -- 상대 라인에 값을
# 얹어주는 셈이라(+2) 순가치가 애매함(다른 효과와 조합 목적일 수 있음).
# 확신이 없어 보수적으로 약한 마이너스만 반영.
TAGS["Gravity_6"] = {"prior": -0.5}
TAGS["Gravity_5"] = {"self_discard": 1}

# --- LIGHT ---
TAGS["Light_0"] = {"flip": {"n": 1}, "draw": 2}  # 뽑는 양은 뒤집은 카드 값에 따라 다름(근사)
TAGS["Light_1"] = {"ongoing": True}
TAGS["Light_2"] = {"draw": 2}
TAGS["Light_3"] = {"prior": 1.0}  # 이 라인의 뒷면 카드 전부를 다른 라인으로 이동
TAGS["Light_4"] = {"prior": 0.5}  # 상대 손패 공개(정보만)
TAGS["Light_5"] = {"self_discard": 1}

# --- METAL ---
TAGS["Metal_0"] = {"ongoing": True, "flip": {"n": 1}}  # 패시브(상대 값 -2) + 뒤집기
TAGS["Metal_1"] = {"draw": 2, "block_compile": True}
TAGS["Metal_2"] = {"ongoing": True}  # 패시브: 상대 이 라인 뒷면 플레이 금지
TAGS["Metal_3"] = {"draw": 1, "prior": 1.0}  # 8장 이상 라인 제거는 상황부 보너스
TAGS["Metal_5"] = {"self_discard": 1}
TAGS["Metal_6"] = {"ongoing": True}  # onCovered/onFlip 자폭 방어

# --- DEATH ---
TAGS["Death_0"] = {"del": [{"n": 1}, {"n": 1}]}  # 다른 두 라인에서 각각 1장(대상 제한 없음)
TAGS["Death_1"] = {"ongoing": True}  # startTop: 선택적 뽑기->제거->자기 삭제
TAGS["Death_2"] = {"del": {"n": "all", "vmax": 2}}  # 값1·2 전부, 한 라인, 양쪽
TAGS["Death_3"] = {"del": {"n": 1}}  # 뒷면 카드 1장 (효과값은 항상 2로 근사됨)
TAGS["Death_4"] = {"del": {"n": "all", "vmax": 1}}  # 값0·1 (뒷면은 효과값2라 자동 제외)
TAGS["Death_5"] = {"self_discard": 1}

# --- DARKNESS ---
TAGS["Darkness_0"] = {"draw": 3}
TAGS["Darkness_1"] = {"flip": {"n": 1, "owner": "enemy"}}
TAGS["Darkness_2"] = {"ongoing": True}  # 패시브(이 스택 뒷면=값4) + 뒤집기 옵션
TAGS["Darkness_3"] = {"extra_play": True}  # 손패 카드를 다른 라인에 즉시 뒷면으로 추가 플레이
TAGS["Darkness_4"] = {"prior": 0.5}  # 뒷면 카드 1장 이동(대상 제한 없음)
TAGS["Darkness_5"] = {"self_discard": 1}

# --- PLAGUE ---
TAGS["Plague_0"] = {"opp_discard": 1, "ongoing": True}  # 패시브(이 라인 상대 플레이 금지)
TAGS["Plague_1"] = {"opp_discard": 1, "ongoing": True}  # 리액티브(상대가 버릴 때마다 나도 뽑음)
TAGS["Plague_2"] = {"self_discard": 1, "opp_discard": 2}  # 최소 1장 기준(나1:상대2)
TAGS["Plague_3"] = {"flip": {"n": "all"}}  # 드러난 다른 앞면 카드 전부(양쪽)
TAGS["Plague_4"] = {"ongoing": True}  # End: 상대 뒷면 카드 강제 제거 + 자기 선택적 뒤집기
TAGS["Plague_5"] = {"self_discard": 1}

# --- PSYCHIC ---
TAGS["Psychic_0"] = {"draw": 2, "opp_discard": 2}
TAGS["Psychic_1"] = {"ongoing": True}  # 패시브(상대 뒷면만) + 시작(자기 뒤집기)
TAGS["Psychic_2"] = {"opp_discard": 2}  # + 상대 프로토콜 재배열(부가 교란)
TAGS["Psychic_3"] = {"opp_discard": 1}  # + 상대 카드 1장 이동(부가)
TAGS["Psychic_4"] = {"ongoing": True}  # End: 선택적 상대 카드 반환->자기 뒤집기
TAGS["Psychic_5"] = {"self_discard": 1}

# --- SPEED ---
TAGS["Speed_0"] = {"extra_play": True}
TAGS["Speed_1"] = {"draw": 2, "ongoing": True}  # + 캐시 정리 후 리액티브 추가 뽑기
TAGS["Speed_2"] = {"ongoing": True}  # onCompileDelete: 제거 대신 이동(생존)
TAGS["Speed_3"] = {"prior": 0.5, "ongoing": True}  # 강제 자기 카드 이동 + End 선택 이동/뒤집기
TAGS["Speed_4"] = {"prior": 0.5}  # 상대 뒷면 카드 1장 이동(교란/유틸)
TAGS["Speed_5"] = {"self_discard": 1}

# --- LIFE ---
TAGS["Life_0"] = {"deck_plays": 2, "ongoing": True}  # 자기 라인마다 뒷면 공짜 플레이 + End 자기삭제 방어
TAGS["Life_1"] = {"flip": [{"n": 1}, {"n": 1}]}
TAGS["Life_2"] = {"draw": 1, "flip": {"n": 1, "may": True}}
TAGS["Life_3"] = {"ongoing": True}  # onCovered: 덮이기 전 다른 라인에 뒷면 플레이
TAGS["Life_4"] = {"ongoing": True}  # 덮고 있으면 뽑기(상황 의존 지속형)
TAGS["Life_5"] = {"self_discard": 1}

# =============================================================================
# MAIN 2
# =============================================================================

# --- CHAOS ---
TAGS["Chaos_0"] = {"flip": [{"n": 1}, {"n": 1}, {"n": 1}], "ongoing": True}  # 라인마다 1장 + start 트레이드
TAGS["Chaos_1"] = {"prior": 1.0}   # 양쪽 프로토콜 강제 재배열(디스럽션+자기부담 혼합)
TAGS["Chaos_2"] = {"prior": 0.5}   # 자신의 커버된 카드 이동
TAGS["Chaos_3"] = {"ongoing": True}  # freePlay 패시브(프로토콜 불일치해도 냄)
TAGS["Chaos_4"] = {"ongoing": True}  # End: 손패 전부 버리고 그만큼 다시 뽑기
TAGS["Chaos_5"] = {"self_discard": 1}

# --- CLARITY ---
TAGS["Clarity_0"] = {"ongoing": True}  # 패시브: 이 라인 값 += 손패 수
TAGS["Clarity_1"] = {"ongoing": True}  # start 공개+선택버리기, onCovered 뽑기3, play 상대손패공개
TAGS["Clarity_2"] = {"draw": 1}   # 덱에서 값1 카드 낚기 + 손패의 값1 카드 플레이
TAGS["Clarity_3"] = {"draw": 1}   # 덱에서 값5 카드 낚기(원하는 카드를 정확히 얻음)
TAGS["Clarity_4"] = {"prior": 0.3}  # 선택적 버림더미 셔플(자원 재활용 유틸)
TAGS["Clarity_5"] = {"self_discard": 1}

# --- CORRUPTION ---
TAGS["Corruption_0"] = {"ongoing": True}  # freePlay+어느 편에나+startTop 자기 카드 뒤집기
TAGS["Corruption_1"] = {"ret": {"n": 1}}  # 대상 제한 없이 반환(상대 손패로 가면 덱 위로 대체)
TAGS["Corruption_2"] = {"draw": 1, "self_discard": 1, "ongoing": True}  # + 자기 버림 후 상대도 버림(리액티브)
TAGS["Corruption_3"] = {"flip": {"n": 1, "may": True}}  # 커버된 앞면 카드 뒤집기(소유자 무관)
TAGS["Corruption_5"] = {"self_discard": 1}
TAGS["Corruption_6"] = {"ongoing": True}  # End: 버리기 또는 자기 제거(자기부담 트리거)

# --- COURAGE ---
TAGS["Courage_0"] = {"draw": 1, "ongoing": True}
TAGS["Courage_1"] = {"del": {"n": 1, "owner": "enemy"}}  # 상대가 이기는 라인에서만 가능(자연히 고가치)
TAGS["Courage_2"] = {"draw": 1, "ongoing": True}
TAGS["Courage_3"] = {"ongoing": True}  # End: 상대 최고값 라인으로 자기 이동(전략적 조건부)
TAGS["Courage_5"] = {"self_discard": 1}
TAGS["Courage_6"] = {"ongoing": True}  # End: 이 라인에서 지고 있으면 자기 뒤집기(방어적 정보)

# --- FEAR ---
TAGS["Fear_0"] = {"ongoing": True}  # 패시브(내 턴엔 상대 중앙명령 무효) + 이동/뒤집기 택1
TAGS["Fear_1"] = {"draw": 2, "opp_discard": 1}  # 상대 손패 리셋(순 -1장 근사)
TAGS["Fear_2"] = {"ret": {"n": 1, "owner": "enemy"}}
TAGS["Fear_3"] = {"prior": 1.5}  # 이 라인의 상대 카드를 다른 라인으로 추방(약한 디나이얼)
TAGS["Fear_4"] = {"opp_discard": 1}  # 상대가 무작위 카드 강제로 버림
TAGS["Fear_5"] = {"self_discard": 1}

# --- ICE ---
TAGS["Ice_1"] = {"ongoing": True}  # 선택적 자기 이동 + 리액티브(상대가 이 라인에 내면 버리게 함)
TAGS["Ice_2"] = {"prior": 0.5}  # 다른 카드 1장 이동(대상 제한 없음)
TAGS["Ice_3"] = {"ongoing": True}  # End: 가려져 있으면 선택적 자기 이동
TAGS["Ice_4"] = {"ongoing": True}  # 패시브: 자기 자신 뒤집기 불가(방어)
TAGS["Ice_5"] = {"self_discard": 1}
# Ice_6: 패시브가 "손패가 있으면 자신이 뽑기 불가" -- 소유자에게 불리한 자기
# 제약형 카드. 확신은 낮지만 명백한 자기 손해라 마이너스로 반영.
TAGS["Ice_6"] = {"prior": -1.0}

# --- LUCK ---
TAGS["Luck_0"] = {"draw": 3}
TAGS["Luck_1"] = {"deck_plays": 1}  # 덱 맨 위를 뒷면으로 내고 중앙명령 무시하고 뒤집음
TAGS["Luck_2"] = {"draw": 2}  # 버린 카드 값만큼 뽑기(평균적으로 근사)
TAGS["Luck_3"] = {"del": {"n": 1, "may": True}}  # 프로토콜 선언 적중해야 발동(조건부)
TAGS["Luck_4"] = {"del": {"n": 1}}
TAGS["Luck_5"] = {"self_discard": 1}

# --- MIRROR ---
TAGS["Mirror_0"] = {"ongoing": True}  # 패시브: 이 라인 값 += 이 라인의 상대 카드 수
TAGS["Mirror_1"] = {"ongoing": True}  # End: 상대 카드의 중앙명령을 대신 발동(강력하지만 상황 의존)
TAGS["Mirror_2"] = {"prior": 1.0}  # 자기 스택 2개 전체 위치 교환
TAGS["Mirror_3"] = {"flip": [{"n": 1, "owner": "own"}, {"n": 1, "owner": "enemy"}]}
TAGS["Mirror_4"] = {"ongoing": True}  # 리액티브: 상대가 뽑으면 나도 뽑음
TAGS["Mirror_5"] = {"self_discard": 1}

# --- PEACE ---
TAGS["Peace_1"] = {"ongoing": True}  # 양쪽 손패 전부 버리기 + End 조건부 뽑기(상황 의존)
TAGS["Peace_2"] = {"draw": 1, "extra_play": True}  # 카드 1장을 뒷면으로 추가 플레이
TAGS["Peace_3"] = {"flip": {"n": 1}}  # 선택적 버리기 + 손패수보다 값 큰 카드 뒤집기
TAGS["Peace_4"] = {"ongoing": True}  # 리액티브: 상대 턴에 내가 버리면 뽑기
TAGS["Peace_5"] = {"self_discard": 1}
TAGS["Peace_6"] = {"ongoing": True}  # 손패 2장 이상이면 자기 뒤집기(조건부)

# --- SMOKE ---
TAGS["Smoke_0"] = {"deck_plays": 2}
TAGS["Smoke_1"] = {"flip": {"n": 1, "owner": "own"}}  # + 선택적 이동
TAGS["Smoke_2"] = {"ongoing": True}  # 패시브: 이 라인 값 += 이 라인 뒷면 카드 수
TAGS["Smoke_3"] = {"extra_play": True}  # 뒷면 카드 있는 라인에 손패 카드 추가로 뒷면 플레이
TAGS["Smoke_4"] = {"prior": 0.5}  # 커버된 뒷면 카드 이동
TAGS["Smoke_5"] = {"self_discard": 1}

# --- TIME ---
TAGS["Time_0"] = {"extra_play": True}  # 버림더미에서 카드 1장 플레이(자원 재활용)
# Time_1: 뒤집기 자체는 이득이지만 "내 덱 전체를 버림"은 상당한 리스크/코스트라
# 순가치가 애매함 -- 확신 없이 낙관적으로 잡지 않고 보수적으로 상쇄.
TAGS["Time_1"] = {"flip": {"n": 1}, "prior": -1.0}
TAGS["Time_2"] = {"ongoing": True}  # 셔플 후 리액티브 뽑기+이동, play 선택적 셔플
TAGS["Time_3"] = {"extra_play": True}  # 버림더미 카드를 공개 후 뒷면으로 플레이(선택)
TAGS["Time_4"] = {"prior": 0.5}  # 뽑고 버려서 손패 필터링(순 카드수 변화 없음)
TAGS["Time_5"] = {"self_discard": 1}

# --- WAR ---
TAGS["War_0"] = {"ongoing": True}  # 리액티브 2종(자기 리프레시 후 뒤집기, 상대 뽑기 후 제거)
TAGS["War_1"] = {"ongoing": True}  # 리액티브: 상대 리프레시 후 나는 버리고 리프레시
TAGS["War_2"] = {"flip": {"n": 1}, "ongoing": True}  # + 리액티브(상대 컴파일 후 손패 전부 버리게)
TAGS["War_3"] = {"draw": 1, "ongoing": True}  # + 리액티브(상대 버림 후 선택적 뒷면 플레이)
TAGS["War_4"] = {"opp_discard": 1}
TAGS["War_5"] = {"self_discard": 1}

# =============================================================================
# AUX 2
# =============================================================================

# --- ASSIMILATION ---
# 상대의 뒷면 카드를 내 손패로 훔침 -- 제거(상대 입장 손실)와 획득(내 손패
# 증가)이 겹치므로 둘 다 반영.
TAGS["Assimilation_0"] = {"draw": 1, "del": {"n": 1, "owner": "enemy", "vmax": 2}}
TAGS["Assimilation_1"] = {"self_discard": 1, "refresh_self": True, "ongoing": True}
TAGS["Assimilation_2"] = {"ongoing": True}  # End: 상대 덱 맨 위를 이 스택에 뒷면으로(상대 자원 소모)
TAGS["Assimilation_4"] = {"draw": 1, "opp_draw": 1}  # 상호 교환(대략 상쇄)
TAGS["Assimilation_5"] = {"self_discard": 1}
# Assimilation_6: 내 덱 맨 위를 "상대 쪽"에 뒷면으로 놓음 -- Corruption_0 방식대로
# 착지한 편이 그 카드를 갖게 될 가능성이 높아 순가치가 불확실함. 확신 없이
# 단정하지 않고 중립적 지속효과로만 표시.
TAGS["Assimilation_6"] = {"ongoing": True}

# --- DIVERSITY ---
TAGS["Diversity_0"] = {"ongoing": True}  # 조건부 컴파일 + End 조건부 추가 플레이
TAGS["Diversity_1"] = {"draw": 2}  # 이동 + 이 라인 프로토콜 종류 수만큼 뽑기(근사)
TAGS["Diversity_3"] = {"ongoing": True}  # 패시브: 조건부 +2
TAGS["Diversity_4"] = {"flip": {"n": 1}}
TAGS["Diversity_5"] = {"self_discard": 1}
TAGS["Diversity_6"] = {"ongoing": True}  # End: 조건부 자기 제거(리스크)

# --- UNITY ---
TAGS["Unity_0"] = {"ongoing": True}  # 조건부 뒤집기or뽑기(+onCovered 동일 트리거)
TAGS["Unity_1"] = {"ongoing": True}  # 패시브(여기 앞면 허용) + 조건부 컴파일+라인삭제
TAGS["Unity_2"] = {"draw": 2}  # 필드의 단결 카드 수만큼 뽑기(근사)
TAGS["Unity_3"] = {"flip": {"n": 1, "may": True}}
TAGS["Unity_4"] = {"ongoing": True}  # End: 손패 비었으면 단결 카드 전부 뽑기
TAGS["Unity_5"] = {"self_discard": 1}


def _other(pi):
    return 2 if pi == 1 else 1


def _eff_val(card):
    """가려진 카드는 늘 값 2 취급 (규칙서: 뒷면 카드의 값은 2)."""
    return card.value if card.face_up else 2


def _line_threat(g, me, line):
    """0/1/2 -- 상대가 이 라인에서 컴파일에 얼마나 가까운가.
    (엔진의 line_value가 패시브 보정까지 반영된 값이라 이걸 그대로 씀.)"""
    o = _other(me)
    if g.players[o]["compiled"][line]:
        return 0
    ov, mv = g.line_value(o, line), g.line_value(me, line)
    if ov <= mv:
        return 0
    if ov >= COMPILE_THRESHOLD:
        return 2
    if ov >= COMPILE_THRESHOLD - 2:
        return 1
    return 0


def _as_list(spec):
    """del/ret/flip은 단일 dict 또는 dict 리스트(Hate_2처럼 순차 2단계인
    경우) 둘 다 허용한다."""
    if spec is None:
        return []
    return spec if isinstance(spec, list) else [spec]


# ---------------------------------------------------------------------------
# 제거/반환/뒤집기 -- 지금 필드 상황에 비추어 값을 계산
# ---------------------------------------------------------------------------

def _del_prior(g, pi, spec):
    """제거 효과 1건의 기대 가치. spec: {n, owner(선택), vmax(선택)}."""
    o = _other(pi)
    owner_filter = spec.get("owner")  # "enemy"/"own"/None(양쪽 다 후보)
    vmax = spec.get("vmax")

    def matches(card, owner_pi):
        if owner_filter == "enemy" and owner_pi != o:
            return False
        if owner_filter == "own" and owner_pi != pi:
            return False
        if vmax is not None and _eff_val(card) > vmax:
            return False
        return True

    gains, losses = [], []
    for target_pi in (1, 2):
        for line in (1, 2, 3):
            top = g.top_card(target_pi, line)
            if top and matches(top, target_pi):
                th = _line_threat(g, pi, line) if target_pi == o else 0
                score = _eff_val(top) * 0.9 + (4 if th == 2 else 1.5 if th == 1 else 0)
                if target_pi == o:
                    gains.append(score)
                else:
                    losses.append(-_eff_val(top))
    gains.sort(reverse=True)
    losses.sort(reverse=True)  # 손실은 절댓값이 작은(=값이 큰, 마이너스가 덜한) 순
    n = spec.get("n", 1)
    if n == "all":
        return sum(gains) + sum(losses)
    n = int(n)
    s = sum(gains[:min(n, len(gains))])
    remain = n - min(n, len(gains))
    if not spec.get("may") and remain > 0:
        s += sum(losses[:remain])
    return s


def _ret_prior(g, pi, spec):
    """반환은 제거보다 약함 (파괴가 아니라 손으로 돌아가 다시 나올 수 있음)."""
    return _del_prior(g, pi, spec) * 0.6


def _flip_prior(g, pi, spec):
    """뒤집기 효과 1건의 기대 가치. spec: {n, owner(선택), from_face(선택),
    may(선택)}. "all_line" n이면 그 라인 전체(양쪽)를 한꺼번에 뒤집는 것으로
    본다 (Apathy_1)."""
    o = _other(pi)
    owner_filter = spec.get("owner")  # "enemy"/"own"/None
    n = spec.get("n", 1)

    if n == "all":
        # 지금 판에서 라인마다 "뒤집으면 얼마나 바뀌나"를 계산해 최댓값을 씀
        # (실제로 낼 라인은 나중에 chooseLine에서 결정되므로, 여기선 최선의
        # 라인을 하나 골랐을 때의 기대값으로 어림).
        best = 0
        for line in (1, 2, 3):
            delta = 0
            for target_pi in (1, 2):
                for card in g.players[target_pi]["stacks"][line]:
                    if card.face_up:
                        change = 2 - _eff_val(card)  # 앞->뒤: 값이 2로 떨어짐
                        delta += change if target_pi == o else -change
            best = max(best, delta)
        return best * 0.9

    def score_one(card, owner_pi):
        was_up = card.face_up
        change = (2 - _eff_val(card)) if was_up else (card.value - 2)
        # 상대 카드를 뒤집는 건: 앞->뒤(값 깎기)는 이득, 뒤->앞(정체 불명 공개)은
        # 리스크라 약한 손해로 침. 내 카드는 그 반대.
        if owner_pi == o:
            return change if was_up else -1.5
        return -change if was_up else (card.value - 2) * 0.5

    cands = []
    for target_pi in (1, 2):
        if owner_filter == "enemy" and target_pi != o:
            continue
        if owner_filter == "own" and target_pi != pi:
            continue
        for line in (1, 2, 3):
            top = g.top_card(target_pi, line)
            if top:
                cands.append(score_one(top, target_pi))
    if not cands:
        return 0
    cands.sort(reverse=True)
    n = int(n)
    if spec.get("may") and (not cands or cands[0] <= 0):
        return 0
    return sum(cands[:n])


# ---------------------------------------------------------------------------
# 진입점 -- 카드 하나의 효과 전체를 지금 상황에 비추어 채점
# ---------------------------------------------------------------------------

def effect_prior(g, pi, card, line=None):
    """card.proto_value 태그를 읽어 지금 상황에서의 기대 가치를 계산.
    태그가 없으면 0 (아직 안 채워진 카드 -- 시뮬레이션이 실제 값을 알아냄)."""
    tag = TAGS.get(f"{card.proto}_{card.value}")
    if not tag:
        return 0.0

    hand_after = max(len(g.players[pi]["hand"]) - 1, 0)
    if tag.get("gated_on_discard") and hand_after == 0:
        return 0.0  # 버릴 카드가 없어 효과 자체가 불발

    s = 0.0
    for spec in _as_list(tag.get("del")):
        s += _del_prior(g, pi, spec)
    for spec in _as_list(tag.get("ret")):
        s += _ret_prior(g, pi, spec)
    for spec in _as_list(tag.get("flip")):
        s += _flip_prior(g, pi, spec)
    if tag.get("draw"):
        s += 0.7 * tag["draw"]
    if tag.get("opp_draw"):
        s -= 0.7 * tag["opp_draw"]
    if tag.get("self_discard"):
        s -= 0.9 * tag["self_discard"]
    if tag.get("opp_discard"):
        s += 0.9 * tag["opp_discard"]
    if tag.get("refresh_self"):
        s += 0.6 * (5 - hand_after)
    if tag.get("deck_plays"):
        # 손패를 안 쓰고 덱에서 뒷면으로 내는 공짜 판 진전 (Water_1/Life_0 등).
        # 뒷면 카드는 항상 값 2로 취급되니 그 정도 기여로 어림.
        s += 1.0 * tag["deck_plays"]
    if tag.get("extra_play"):
        # 손패에서 카드를 하나 더 낼 기회 -- 손이 있어야 의미 있음.
        if g.players[pi]["hand"]:
            s += 2.2
    if tag.get("ongoing"):
        s += 0.8
    if tag.get("block_compile"):
        s += 7.0
    return s


# ---------------------------------------------------------------------------
# 제어권(Control) 활용 -- 소비 시 프로토콜 재배치 계획
# ---------------------------------------------------------------------------

def defusable_threat(g, me):
    """지금 제어권을 쥐고 있고, 상대의 임박한 컴파일(위협도 2)을 재배치로
    무력화할 수 있는 상황인가 -- 그 위협 라인 번호를 반환(없으면 None).

    조건: 내가 Control을 쥠 + 상대가 컴파일 자체가 막힌 상태가 아님 + 위협도
    2인 라인이 있음 + 상대가 "다른" 라인에 이미 컴파일한 프로토콜을 갖고
    있음(그 프로토콜을 위협 라인으로 옮기면 상대의 강제 컴파일이 수확 없는
    재컴파일로 전락한다).

    score_action()의 리프레시 채점에서 참조 -- "지금 리프레시하면 이
    무력화를 실제로 실행할 기회(제어권 소비)가 생긴다"는 보너스로 쓰임.
    """
    if g.control != me:
        return None
    o = _other(me)
    if g.cant_compile.get(o):
        return None
    for line in (1, 2, 3):
        if _line_threat(g, me, line) == 2:
            for j in (1, 2, 3):
                if j != line and g.players[o]["compiled"][j]:
                    return line
    return None


def plan_rearrange(g, pi, compiling_line=None):
    """제어권 소비 시 실제로 어떻게 재배치할지 계획.

    갈래 1: 지금 컴파일하려는 라인이 내가 "이미 컴파일한" 프로토콜이면
    (재컴파일 = 새로 얻는 게 없음), 아직 컴파일 안 한 라인 중 값이 제일
    낮은 곳과 맞바꿔서 그 컴파일을 진짜 진전으로 바꾼다.

    갈래 2: 그게 아니면 상대를 방해한다 -- 상대의 미완료 라인 중 위협도가
    최우선(값은 동점 처리용)인 라인의 프로토콜을, 상대의 값이 제일 낮은
    다른 라인과 맞바꾼다.

    반환: {"who": 대상 플레이어, "order": {1:.., 2:.., 3:..}} 또는 None.
    """
    o = _other(pi)

    if compiling_line and g.players[pi]["compiled"].get(compiling_line):
        best, best_val = None, None
        for line in (1, 2, 3):
            if line != compiling_line and not g.players[pi]["compiled"][line]:
                v = g.line_value(pi, line)
                if best_val is None or v < best_val:
                    best_val, best = v, line
        if best:
            order = {1: 1, 2: 2, 3: 3}
            order[compiling_line], order[best] = best, compiling_line
            return {"who": pi, "order": order}

    best, best_key = None, None
    for line in (1, 2, 3):
        if not g.players[o]["compiled"][line] and line != compiling_line:
            v = g.line_value(o, line)
            key = _line_threat(g, pi, line) * 100 + v
            if best_key is None or key > best_key:
                best_key, best = key, line
    if best is None:
        return None
    low, low_val = None, None
    for line in (1, 2, 3):
        if line != best:
            v = g.line_value(o, line)
            if low_val is None or v < low_val:
                low_val, low = v, line
    if low is None or low == best:
        return None
    order = {1: 1, 2: 2, 3: 3}
    order[best], order[low] = low, best
    return {"who": o, "order": order}


# ---------------------------------------------------------------------------
# 후보 액션 채점 -- pick_best에 넘길 s 값
# ---------------------------------------------------------------------------

def score_action(g, pi, action):
    """legal_actions()가 내놓는 액션 하나를 채점 (pick_best의 후보 점수 s로
    씀). 아직 카드 지식(effect_prior)이 없는 카드는 기본항만으로 채점되고,
    태그가 있으면 그 값이 더해진다 -- 태그를 채울수록 이 점수가 정확해짐.

    아직 Lua ai.lua의 scoreAction 전체(1-a 로드맵)를 포팅한 건 아니고, 태그
    파이프라인이 실제로 pick_best에 연결되는지 확인할 만큼의 기본항만 담음.
    """
    if action.get("kind") == "refresh":
        hand = g.players[pi]["hand"]
        avg = (sum(c.value for c in hand) / len(hand)) if hand else 0
        s = 4 - avg - len(hand) * 0.5
        if defusable_threat(g, pi):
            # 제어권 재배치로 상대의 강제 컴파일을 재컴파일(수확 없음)로
            # 무력화할 기회 -- 리프레시가 그 소비 창구가 되니 강하게 우대.
            s += 60
        return s

    card = g.cards_by_uid[action["uid"]]
    line = action["line"]
    face_up = action["faceUp"]
    o = _other(pi)
    contrib = card.value if face_up else 2
    my_line = g.line_value(pi, line)
    opp_line = g.line_value(o, line)
    new_mine = my_line + contrib
    score = contrib

    if new_mine >= COMPILE_THRESHOLD and new_mine > opp_line:
        score += -20 if g.players[pi]["compiled"][line] else 60
    threat = _line_threat(g, pi, line)
    if threat > 0 and new_mine >= opp_line:
        score += 40 if threat == 2 else 8
    if my_line <= opp_line < new_mine:
        score += 12
    if g.players[pi]["compiled"][line]:
        score -= 5
    if face_up:
        score += 0.3 + effect_prior(g, pi, card, line)
    else:
        score += 0.5
    if opp_line - new_mine >= 6:
        score -= 4
    return score
