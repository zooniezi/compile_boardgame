"""RL 세대 순환 오케스트레이션 (260803_RL_plan.md).

한 세대 = 자기대국(scripts/generate_rl_selfplay_data.py) -> 학습(값망은
scripts/train_eval_mlp.py, 정책망은 scripts/train_policy_rl.py) -> 게이트
(scripts/arena.py로 신구 세대 비교, 통계적으로 유의미하게 이겨야만 승격).
승격되면 다음 세대의 자기대국은 새 가중치로 두고, 아니면 그 세대는
버리고 멈춘다(--continue-on-fail로 계속 시도하게 바꿀 수 있음).

0세대 시드: 무작위 초기화 대신 지금 이미 배포된 가중치(`src/game/data/
eval_weights_mlp.npz`/`policy_weights.npz`, 오늘 모방학습 결과)를 기본
시작점으로 쓴다 -- 빈 정책으로 자기대국을 시작하면 탐색이 방향을 못 잡아
초반 세대가 거의 무의미해지기 때문.

병렬화(260803_병렬화_plan.md): 자기대국은 generate_rl_selfplay_data.py의
`--n-workers`로, 게이트 아레나는 이 스크립트가 `functools.partial`로
싼 팩토리를 `scripts.arena.arena(..., n_workers=...)`에 그대로 넘긴다.

사용법:
    python3 scripts/run_rl_generation.py <작업디렉터리> \
        [--eval-weights src/game/data/eval_weights_mlp.npz] \
        [--policy-weights src/game/data/policy_weights.npz] \
        [--n-generations 1] [--n-games 150] [--iterations 40] \
        [--gate-pairs 15] [--gate-iterations 200] [--n-workers auto] \
        [--continue-on-fail]
"""

import sys
import time
from functools import partial
from pathlib import Path

sys.path.insert(0, ".")

from src.game.ai_ismcts import ISMCTSAI
from src.game.ai_ismcts_policy import load_policy_weights
from src.game.ai_sim import evaluate_learned_mlp, load_mlp_weights
from scripts.arena import arena
from scripts.generate_rl_selfplay_data import generate as generate_selfplay
from scripts.train_eval_mlp import train_mlp
from scripts.train_policy_rl import train_policy_rl

DEFAULT_EVAL_WEIGHTS = "src/game/data/eval_weights_mlp.npz"
DEFAULT_POLICY_WEIGHTS = "src/game/data/policy_weights.npz"
GATE_EVAL_SCALE = 3.1  # eval_weights_mlp.npz와 짝을 이루는 실측값 (ai_ismcts_mlp.py 참고)


def _make_ai_factory(eval_weights_path, policy_weights_path, iterations, rollout_turn_cap=2):
    """arena()로 넘길 피클 가능한 팩토리(functools.partial) -- 람다 금지
    (260803_병렬화_plan.md와 동일 제약)."""
    eval_w = load_mlp_weights(eval_weights_path)
    policy_w = load_policy_weights(policy_weights_path)
    return partial(ISMCTSAI, eval_fn=evaluate_learned_mlp, eval_w=eval_w,
                    eval_scale=GATE_EVAL_SCALE, policy_w=policy_w,
                    iterations=iterations, rollout_turn_cap=rollout_turn_cap)


def run_one_generation(gen_idx, work_dir, eval_weights_path, policy_weights_path,
                        n_games, iterations, dirichlet_alpha, dirichlet_eps,
                        temp_moves, n_workers, gate_pairs, gate_iterations, seed_base):
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    prefix = str(work_dir / f"gen{gen_idx}")

    print(f"===== 세대 {gen_idx}: 자기대국 {n_games}판(iterations={iterations}) =====")
    t0 = time.time()
    generate_selfplay(n_games, prefix, eval_weights_path, policy_weights_path,
                       iterations=iterations, dirichlet_alpha=dirichlet_alpha,
                       dirichlet_eps=dirichlet_eps, temp_moves=temp_moves,
                       seed_base=seed_base, n_workers=n_workers)
    print(f"자기대국 소요: {time.time() - t0:.1f}초")

    print(f"===== 세대 {gen_idx}: 값망 학습 =====")
    new_eval_path = str(work_dir / f"gen{gen_idx}_eval_weights.npz")
    train_mlp(f"{prefix}_value.npz", new_eval_path, hidden_layer_sizes=(64,), verbose=True)

    print(f"===== 세대 {gen_idx}: 정책망 학습 =====")
    new_policy_path = str(work_dir / f"gen{gen_idx}_policy_weights.npz")
    train_policy_rl(f"{prefix}_policy.npz", new_policy_path, hidden=64, verbose=True)

    print(f"===== 세대 {gen_idx}: 게이트 아레나(신규 vs 현재, {gate_pairs}쌍) =====")
    new_factory = _make_ai_factory(new_eval_path, new_policy_path, gate_iterations)
    cur_factory = _make_ai_factory(eval_weights_path, policy_weights_path, gate_iterations)
    result = arena(new_factory, cur_factory, n_pairs=gate_pairs,
                    label_a=f"gen{gen_idx}_new", label_b="current", n_workers=n_workers)

    promoted = result["rate"] - result["ci"] > 0.5
    print(f"===== 세대 {gen_idx}: {'승격' if promoted else '승격 안 됨'} =====")
    return {
        "promoted": promoted,
        "new_eval_path": new_eval_path,
        "new_policy_path": new_policy_path,
        "arena_result": result,
    }


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    work_dir = argv[1]

    def _arg(flag, default, cast=str):
        return cast(argv[argv.index(flag) + 1]) if flag in argv else default

    eval_weights_path = _arg("--eval-weights", DEFAULT_EVAL_WEIGHTS)
    policy_weights_path = _arg("--policy-weights", DEFAULT_POLICY_WEIGHTS)
    n_generations = _arg("--n-generations", 1, int)
    n_games = _arg("--n-games", 150, int)
    iterations = _arg("--iterations", 40, int)
    dirichlet_alpha = _arg("--dirichlet-alpha", 0.3, float)
    dirichlet_eps = _arg("--dirichlet-eps", 0.25, float)
    temp_moves = _arg("--temp-moves", 10, int)
    gate_pairs = _arg("--gate-pairs", 15, int)
    gate_iterations = _arg("--gate-iterations", 200, int)
    seed_base = _arg("--seed-base", 0, int)
    n_workers_raw = _arg("--n-workers", "1")
    n_workers = n_workers_raw if n_workers_raw == "auto" else int(n_workers_raw)
    continue_on_fail = "--continue-on-fail" in argv

    for gen_idx in range(1, n_generations + 1):
        outcome = run_one_generation(
            gen_idx, work_dir, eval_weights_path, policy_weights_path,
            n_games=n_games, iterations=iterations,
            dirichlet_alpha=dirichlet_alpha, dirichlet_eps=dirichlet_eps,
            temp_moves=temp_moves, n_workers=n_workers,
            gate_pairs=gate_pairs, gate_iterations=gate_iterations,
            seed_base=seed_base + gen_idx * 100000)

        if outcome["promoted"]:
            eval_weights_path = outcome["new_eval_path"]
            policy_weights_path = outcome["new_policy_path"]
        elif not continue_on_fail:
            print(f"세대 {gen_idx}가 게이트를 통과 못 해서 여기서 멈춥니다 "
                  f"(--continue-on-fail을 주면 실패해도 다음 세대로 진행).")
            break

    print()
    print("최종 채택된 가중치:")
    print(f"  값: {eval_weights_path}")
    print(f"  정책: {policy_weights_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
