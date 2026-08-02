"""프로토콜별 승률 측정 — 어떤 AI가 각 프로토콜을 얼마나 잘 다루는지 순위를 낸다.

Lua판 luajit scripts/proto_winrates.lua 6000 과 동일한 아이디어: 같은 AI를
자기 자신과 맞붙이되(자기 실력 차는 상쇄) 매판 서로 겹치지 않는 프로토콜
3+3을 무작위로 뽑아서, 그 프로토콜을 손에 쥔 쪽이 이겼는지만 집계한다.
즉 "이 AI가 이 프로토콜을 얼마나 잘 플레이하는가" = 드래프트가 최적화해야
할 바로 그 지표.

AI를 바꿀 때마다 다시 돌려서 랭킹을 갱신할 것.

사용법:
    python3 scripts/proto_winrates.py [게임수] [ai모듈경로:클래스명]

    # 기본값: 6000판, src.game.ai_heuristic:HeuristicAI
    python3 scripts/proto_winrates.py 6000
    python3 scripts/proto_winrates.py 6000 src.game.ai_ismcts:ISMCTSAI
"""

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.arena import _mk, load_ai, play_one  # noqa: E402
from src.game import protocols as Protocols  # noqa: E402

DEFAULT_AI = "src.game.ai_heuristic:HeuristicAI"


def run(ai_factory, n_games=6000, seed0=0, progress=True):
    """n_games판을 두고 프로토콜별 {wins, games}를 반환."""
    rnd = random.Random(seed0)
    pool = list(Protocols.PROTOCOL_LIST)
    wins = {p: 0 for p in pool}
    games = {p: 0 for p in pool}
    t0 = time.time()

    for i in range(n_games):
        rnd.shuffle(pool)
        protos1, protos2 = pool[:3], pool[3:6]
        seed = seed0 + i
        winner = play_one(_mk(ai_factory), _mk(ai_factory), protos1, protos2, seed)

        for p in protos1:
            games[p] += 1
            if winner == 1:
                wins[p] += 1
        for p in protos2:
            games[p] += 1
            if winner == 2:
                wins[p] += 1

        if progress and (i + 1) % max(1, n_games // 20) == 0:
            print(f"  ... {i + 1}/{n_games}판", flush=True)

    elapsed = time.time() - t0
    if progress:
        print(f"  완료: {elapsed:.1f}초 ({elapsed / n_games * 1000:.0f}ms/판)")

    return wins, games


def report(wins, games):
    """승률 내림차순 표를 출력하고 (proto, rate, n) 리스트를 반환."""
    rows = []
    for p in wins:
        n = games[p]
        rate = wins[p] / n if n else 0.0
        rows.append((p, rate, n))
    rows.sort(key=lambda r: -r[1])

    print()
    print(f"{'rank':>4}  {'protocol':<14} {'winrate':>8}  games")
    for rank, (p, rate, n) in enumerate(rows, start=1):
        print(f"{rank:>4}  {p:<14} {rate * 100:6.1f}%  {n}")

    # 드래프트 티어 테이블로 바로 붙여넣을 수 있는 형태 (순위 1 = 최강).
    print()
    print("DRAFT_TIER = {")
    for rank, (p, rate, n) in enumerate(rows, start=1):
        print(f'    "{p}": {rank:>3},   # {rate * 100:.1f}% over {n} games')
    print("}")

    return rows


def main(argv):
    n_games = int(argv[1]) if len(argv) > 1 else 6000
    ai_spec = argv[2] if len(argv) > 2 else DEFAULT_AI
    ai_cls = load_ai(ai_spec)
    print(f"{ai_spec} 로 자기 자신과 {n_games}판 (프로토콜 무작위 3+3)")
    wins, games = run(ai_cls, n_games=n_games)
    report(wins, games)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
