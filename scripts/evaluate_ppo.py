"""Evaluate the trained PPO dispatch policy against Baseline C (greedy
dispatch) on the held-out RE1 test split.

Uses the SAME 60/20/20 split (seed=42) as train_and_evaluate.py and
train_ppo.py's default --split train, so this evaluates strictly on
incidents PPO never saw during training.

This measures the RL orchestrator's core novelty claim in isolation: given
identical anomaly scores from AnomalyScorer, does the learned dispatch
policy solve incidents in fewer steps than always greedily picking the
top-ranked node? Baseline C has no memory across steps, so if its first
(and only) guess is wrong it never recovers within the step budget --
PPO's observation includes visited-service history, so it can.

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

from incidentmind_p1.dispatch import PPODispatcher, greedy_baseline_c
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
    parser = argparse.ArgumentParser(description="Evaluate PPO dispatch vs Baseline C on held-out RE1 test incidents")
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
    greedy_results = [run_episode_greedy(scorer, inc, args.step_budget) for inc in test_incidents]

    print()
    ppo_summary = summarize(ppo_results, "PPO")
    greedy_summary = summarize(greedy_results, "Baseline C")

    print()
    delta_solve = ppo_summary["solve_rate"] - greedy_summary["solve_rate"]
    print(f"PPO solve rate advantage over Baseline C: {delta_solve:+.3f}")


if __name__ == "__main__":
    main()
