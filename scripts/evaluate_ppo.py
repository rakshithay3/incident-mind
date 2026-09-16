"""Evaluate the trained PPO dispatch policy against Baselines A, B, and C on
the held-out RE1 test split.

Uses the SAME 60/20/20 split (seed=42) as train_and_evaluate.py and
train_ppo.py's default --split train, so this evaluates strictly on
incidents PPO never saw during training.

This measures the RL orchestrator's core novelty claim in isolation: given
identical anomaly scores from AnomalyScorer, does the learned dispatch
policy solve incidents in fewer steps than three baselines with
progressively less signal?

  Baseline A -- uniformly random among anomalous nodes (the floor: no
                ranking, no threshold-arrival ordering, no learning).
  Baseline B -- threshold-only, arrival order (any signal beats none, but
                still no ranking by anomaly_score).
  Baseline C -- always greedily pick the top-ranked node, deterministically.
                Has no memory across steps, so if its first (and only)
                guess is wrong it never recovers within the step budget.

PPO's observation includes visited-service history, so unlike Baseline C it
can actually use a wrong first guess to inform its next one -- Baselines A
and B are given the same multi-step, visited-aware chance within the step
budget so the comparison isn't stacked against them by a single-shot check.

Usage:
    PYTHONPATH=. python scripts/evaluate_ppo.py \
        --dataset data/rcaeval_re1 \
        --model models/ppo_dispatch.zip
"""

from __future__ import annotations

import argparse
import random
import statistics as st
from pathlib import Path

from stable_baselines3 import PPO

from incidentmind_p1.dispatch import PPODispatcher, baseline_a, baseline_b, greedy_baseline_c
from incidentmind_p1.loader import load_dataset
from incidentmind_p1.scoring import AnomalyScorer

STEP_BUDGET = 5


def split_incidents(incidents, seed: int):
    """Same 60/20/20 split convention as train_and_evaluate.py / train_ppo.py."""
    shuffled = incidents[:]
    random.Random(seed).shuffle(shuffled)
    n = len(shuffled)
    n_train, n_val = int(n * 0.6), int(n * 0.2)
    return shuffled[:n_train], shuffled[n_train:n_train + n_val], shuffled[n_train + n_val:]


def run_episode_ppo(dispatcher: PPODispatcher, scorer: AnomalyScorer, incident, step_budget: int = STEP_BUDGET):
    ranked = sorted(scorer.score_graph(incident), key=lambda s: s.rank)
    visited: set = set()
    for step in range(1, step_budget + 1):
        decision = dispatcher.choose(ranked, visited=visited, step=step)
        target = decision.action.target_service
        visited.add(target)
        if target == incident.root_cause:
            return step, True
    return step_budget, False


def run_episode_greedy(scorer: AnomalyScorer, incident, step_budget: int = STEP_BUDGET):
    ranked = sorted(scorer.score_graph(incident), key=lambda s: s.rank)
    decision = greedy_baseline_c(ranked)
    target = decision.action.target_service
    if target == incident.root_cause:
        return 1, True
    # Baseline C is stateless/deterministic -- if its single top pick is
    # wrong it has no mechanism to try anything else, so it never solves
    # within the budget.
    return step_budget, False


def run_episode_baseline_stepped(dispatch_fn, scorer: AnomalyScorer, incident, step_budget: int = STEP_BUDGET):
    """Shared step loop for Baseline A and Baseline B -- unlike Baseline C,
    both actually use the visited set to try a different node on each
    retry (random re-roll for A, next-in-arrival-order for B), so they get
    the same multi-step chance within the budget that PPO gets."""
    ranked = sorted(scorer.score_graph(incident), key=lambda s: s.rank)
    visited: set = set()
    for step in range(1, step_budget + 1):
        decision = dispatch_fn(ranked, visited=visited)
        target = decision.action.target_service
        visited.add(target)
        if target == incident.root_cause:
            return step, True
    return step_budget, False


def run_episode_baseline_a(scorer: AnomalyScorer, incident, step_budget: int = STEP_BUDGET, seed: int = 0):
    return run_episode_baseline_stepped(
        lambda ranked, visited: baseline_a(ranked, visited=visited, seed=seed), scorer, incident, step_budget
    )


def run_episode_baseline_b(scorer: AnomalyScorer, incident, step_budget: int = STEP_BUDGET):
    return run_episode_baseline_stepped(baseline_b, scorer, incident, step_budget)


def summarize(results, label: str):
    solved = [steps for steps, ok in results if ok]
    solve_rate = len(solved) / len(results)
    mean_steps_when_solved = st.fmean(solved) if solved else float("nan")
    mean_steps_all = st.fmean(steps for steps, _ in results)
    print(f"{label:12s}  solve_rate={solve_rate:.3f}  "
          f"mean_steps_when_solved={mean_steps_when_solved:.2f}  "
          f"mean_steps_all(unsolved=budget)={mean_steps_all:.2f}")
    return {
        "solve_rate": solve_rate,
        "mean_steps_when_solved": mean_steps_when_solved,
        "mean_steps_all": mean_steps_all,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate PPO dispatch vs Baselines A/B/C on held-out RE1 test incidents")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--model", required=True, help="path to trained PPO .zip from scripts/train_ppo.py")
    parser.add_argument("--seed", type=int, default=42, help="must match the seed used to train the policy")
    parser.add_argument("--step-budget", type=int, default=STEP_BUDGET)
    parser.add_argument(
        "--graphsage-model",
        default=None,
        help="Path to a GraphSAGE checkpoint (models/graphsage.pt). Should match whatever "
             "--graphsage-model (or its absence) was used to train --model, or the comparison "
             "isn't apples-to-apples. Falls back to AnomalyScorer (peer z-score) if omitted.",
    )
    args = parser.parse_args()

    incidents = load_dataset(args.dataset)
    _, _, test_incidents = split_incidents(incidents, args.seed)
    print(f"Loaded {len(incidents)} incidents, evaluating on {len(test_incidents)} held-out test incidents "
          f"(seed={args.seed}, same split as train_ppo.py --split train)")

    if args.graphsage_model:
        from incidentmind_p1.gnn_scorer import GraphSAGEScorer
        from incidentmind_p1.training import load_checkpoint

        encoder, stats = load_checkpoint(args.graphsage_model)
        scorer = GraphSAGEScorer(encoder, stats)
        print(f"Scoring with trained GraphSAGE checkpoint: {args.graphsage_model}")
    else:
        print("WARNING: no --graphsage-model given -- evaluating against AnomalyScorer (peer z-score), "
              "not the real GNN. Numbers here will NOT match the paper's GNN+PPO architecture.")
        scorer = AnomalyScorer()
    policy = PPO.load(args.model)
    dispatcher = PPODispatcher(policy=policy)

    ppo_results = [run_episode_ppo(dispatcher, scorer, inc, args.step_budget) for inc in test_incidents]
    baseline_a_results = [run_episode_baseline_a(scorer, inc, args.step_budget, seed=args.seed) for inc in test_incidents]
    baseline_b_results = [run_episode_baseline_b(scorer, inc, args.step_budget) for inc in test_incidents]
    greedy_results = [run_episode_greedy(scorer, inc, args.step_budget) for inc in test_incidents]

    print()
    ppo_summary = summarize(ppo_results, "PPO")
    baseline_a_summary = summarize(baseline_a_results, "Baseline A")
    baseline_b_summary = summarize(baseline_b_results, "Baseline B")
    greedy_summary = summarize(greedy_results, "Baseline C")

    print()
    print(f"PPO solve rate advantage over Baseline A (random):    {ppo_summary['solve_rate'] - baseline_a_summary['solve_rate']:+.3f}")
    print(f"PPO solve rate advantage over Baseline B (threshold): {ppo_summary['solve_rate'] - baseline_b_summary['solve_rate']:+.3f}")
    print(f"PPO solve rate advantage over Baseline C (greedy):    {ppo_summary['solve_rate'] - greedy_summary['solve_rate']:+.3f}")


if __name__ == "__main__":
    main()
