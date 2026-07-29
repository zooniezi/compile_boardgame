"""AI 대전 측정 아레나 — 두 AI를 붙여서 승률과 95% 신뢰구간을 낸다.

AI를 고치고 "좀 나아진 것 같다"는 감각은 믿을 수 없다. 10판 두고 7승 3패가
나와도 우연일 확률이 매우 높다. 이 도구는 그 판단을 숫자로 대체한다.

미러 페어(mirrored pair) 방식:
    같은 시드 + 같은 프로토콜 조합으로 두 판을 두되, 두 AI의 자리만 맞바꾼다.
    이러면 선공 이점과 프로토콜 유불리가 상쇄돼서, 남는 차이가 순수하게
    "AI 실력 차이"가 된다.

사용법:
    # 파이썬에서
    from scripts.arena import arena
    from src.game.ai_random import RandomAI
    arena(RandomAI, RandomAI, n_pairs=500)

    # 커맨드라인에서 (모듈경로:클래스명)
    python3 scripts/arena.py src.game.ai_random:RandomAI src.game.ai_random:RandomAI 500
"""

import importlib
import math
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.game import protocols as Protocols  # noqa: E402
from src.game.engine import Engine  # noqa: E402

# 한 판이 비정상적으로 길어질 때의 안전장치 (엔진 TURN_CAP과 별개로 스텝 상한).
MAX_STEPS = 20000


def play_one(ai_seat1, ai_seat2, protos1, protos2, seed):
    """한 판을 끝까지 두고 승자(1|2|None)를 반환."""
    random.seed(seed)
    e = Engine(protocols1=protos1, protocols2=protos2,
               ai1=True, ai2=True, seed=seed,
               ai_modules={1: ai_seat1, 2: ai_seat2})
    e.start()
    steps = 0
    while e.pending is not None and steps < MAX_STEPS:
        steps += 1
        if e.pending["kind"] == "anim":
            e.advance_anim()
        else:
            e.answer(None)   # AI가 답하므로 값은 무시된다
    return e.winner


def _mk(factory):
    """AI 팩토리(클래스 또는 호출가능)에서 새 인스턴스를 만든다.

    상태를 갖는 AI가 판을 넘나들며 오염되지 않도록 매 판 새로 만든다.
    """
    return factory() if callable(factory) else factory


def _random_protocol_pair(rnd):
    """서로 겹치지 않는 프로토콜 3+3을 뽑는다."""
    pool = list(Protocols.PROTOCOL_LIST)
    rnd.shuffle(pool)
    return pool[:3], pool[3:6]


def arena(ai_a, ai_b, n_pairs=500, seed0=0, label_a="A", label_b="B",
          progress=True):
    """ai_a와 ai_b를 n_pairs쌍(= 2*n_pairs판) 붙여서 결과를 출력/반환.

    반환: {"wins_a", "wins_b", "draws", "games", "rate", "ci"}
    """
    rnd = random.Random(seed0)
    wins_a = wins_b = draws = 0
    pair_scores = []   # 쌍마다 A의 승리 지분 (0 / 0.5 / 1)
    t0 = time.time()

    for i in range(n_pairs):
        protos1, protos2 = _random_protocol_pair(rnd)
        seed = seed0 + i
        a_in_pair = 0

        # 1판: A가 1번 자리
        w = play_one(_mk(ai_a), _mk(ai_b), protos1, protos2, seed)
        if w == 1:
            wins_a += 1
            a_in_pair += 1
        elif w == 2:
            wins_b += 1
        else:
            draws += 1

        # 2판: 자리만 맞바꿈 (시드/프로토콜 동일) -- 선공·프로토콜 이점 상쇄
        w = play_one(_mk(ai_b), _mk(ai_a), protos1, protos2, seed)
        if w == 2:
            wins_a += 1
            a_in_pair += 1
        elif w == 1:
            wins_b += 1
        else:
            draws += 1

        pair_scores.append(a_in_pair / 2.0)

        if progress and (i + 1) % max(1, n_pairs // 10) == 0:
            done = (i + 1) * 2
            print(f"  ... {done}판 ({wins_a}승 {wins_b}패)", flush=True)

    elapsed = time.time() - t0

    # 신뢰구간은 "판"이 아니라 "쌍" 단위로 계산해야 한다. 미러 페어는 일부러
    # 두 판을 상쇄시킨 데이터라, 판을 독립 표본으로 세면 실제보다 넓은(=틀린)
    # 구간이 나온다. 예: 완전히 같은 AI끼리는 모든 쌍이 1승1패로 갈려서
    # 실제 불확실성이 0인데, 판 단위로 계산하면 엉뚱하게 +-6.9가 찍힌다.
    n = len(pair_scores)
    rate = sum(pair_scores) / n if n else 0.0
    if n > 1:
        var = sum((s - rate) ** 2 for s in pair_scores) / (n - 1)
        ci = 1.96 * math.sqrt(var / n)
    else:
        ci = 0.0

    games = n_pairs * 2
    print()
    print(f"{label_a}  vs  {label_b}")
    print(f"  {games}판 ({n_pairs}쌍 미러) · {elapsed:.1f}초 · 판당 {elapsed/games*1000:.0f}ms")
    print(f"  {label_a} {wins_a}승 / {label_b} {wins_b}승" + (f" / 무승부 {draws}" if draws else ""))
    print(f"  → {label_a} 승률 {rate*100:.1f}% ±{ci*100:.1f}")
    if rate - ci > 0.5:
        print(f"  → {label_a}가 유의미하게 우세")
    elif rate + ci < 0.5:
        print(f"  → {label_b}가 유의미하게 우세")
    else:
        print("  → 통계적으로 무의미 (차이 판정 불가, 표본을 늘리세요)")

    return {"wins_a": wins_a, "wins_b": wins_b, "draws": draws,
            "games": games, "rate": rate, "ci": ci, "elapsed": elapsed}


def load_ai(spec):
    """'모듈경로:클래스명' 문자열에서 AI 클래스를 임포트."""
    mod_path, _, cls_name = spec.partition(":")
    if not cls_name:
        raise ValueError(f"'모듈경로:클래스명' 형식이어야 해요: {spec}")
    return getattr(importlib.import_module(mod_path), cls_name)


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        print("예: python3 scripts/arena.py "
              "src.game.ai_random:RandomAI src.game.ai_random:RandomAI 200")
        return 1
    spec_a, spec_b = argv[1], argv[2]
    n_pairs = int(argv[3]) if len(argv) > 3 else 500
    arena(load_ai(spec_a), load_ai(spec_b), n_pairs=n_pairs,
          label_a=spec_a.split(":")[-1], label_b=spec_b.split(":")[-1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
