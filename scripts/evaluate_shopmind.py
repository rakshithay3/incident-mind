"""Evaluate the trained PPO dispatch policy against Baseline C on the FULL
ShopMind dataset -- no train/test split, since ShopMind is already entirely
held out for cross-topology generalization validation.

Usage:
    PYTHONPATH=. python3 evaluate_shopmind.py \
        --dataset /Users/rakshithayathiraj/Desktop/shopmind_evaluation_dataset \
        --model models/ppo_dispatch.zip \
        --graphsage-model models/graphsage.pt
"""

from __future__ import annotations

import argparse
import statistics as st

from stable_baselines3 import PPO

from incidentmind_p1.dispatch import PPODispatcher, greedy_baseline_c
from incidentmind_p1.loader import load_dataset, summarize_dataset
from incidentmind_p1.scoring import AnomalyScorer

STEP_BUDGET = 5


def run_episode_ppo(dispatcher: PPODispatcher, scorer, incident, step_budget: int = STEP_BUDGET):
    ranked = sorted(scorer.score_graph(incident), key=lambda s: s.rank)
    visited: set = set()
    for step in range(1, step_budget + 1):
        decision = dispatcher.choose(ranked, visited=visited, step=step)
        target = decision.action.target_service
        visited.add(target)
        if target == incident.root_cause:
            return step, True
    return step_budget, False


def run_episode_greedy(scorer, incident, step_budget: int = STEP_BUDGET):
    ranked = sorted(scorer.score_graph(incident), key=lambda s: s.rank)
    decision = greedy_baseline_c(ranked)
    target = decision.action.target_service
    if target == incident.root_cause:
        return 1, True
    return step_budget, False


def summarize(results, label: str):
    solved = [steps for steps, ok in results if ok]
    solve_rate = len(solved) / len(results)
    mean_steps_when_solved = st.fmean(solved) if solved else float("nan")
    mean_steps_all = st.fmean(steps for steps, _ in results)
    print(
        f"{label:12s}  solve_rate={solve_rate:.3f}  "
        f"mean_steps_when_solved={mean_steps_when_solved:.2f}  "
        f"mean_steps_all(unsolved=budget)={mean_steps_all:.2f}"
    )
    return {
        "solve_rate": solve_rate,
        "mean_steps_when_solved": mean_steps_when_solved,
        "mean_steps_all": mean_steps_all,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate PPO dispatch vs Baseline C on the FULL ShopMind held-out set"
    )
    parser.add_argument("--dataset", required=True, help="Path to unzipped ShopMind incidents")
    parser.add_argument("--model", required=True, help="Path to trained PPO .zip from scripts/train_ppo.py")
    parser.add_argument("--step-budget", type=int, default=STEP_BUDGET)
    parser.add_argument(
        "--graphsage-model",
        default=None,
        help="Path to trained GraphSAGE checkpoint (models/graphsage.pt). Should match "
             "whatever was used to train --model, or the comparison isn't apples-to-apples. "
             "Falls back to AnomalyScorer (peer z-score) if omitted.",
    )
    args = parser.parse_args()

    incidents = load_dataset(args.dataset)
    print(summarize_dataset(incidents))
    print(f"Evaluating on ALL {len(incidents)} ShopMind incidents (no split -- fully held-out set)")

    if args.graphsage_model:
        from incidentmind_p1.gnn_scorer import GraphSAGEScorer
        from incidentmind_p1.training import load_checkpoint

        encoder, stats = load_checkpoint(args.graphsage_model)
        scorer = GraphSAGEScorer(encoder, stats)
        print(f"Scoring with trained GraphSAGE checkpoint: {args.graphsage_model}")
    else:
        print(
            "WARNING: no --graphsage-model given -- evaluating against AnomalyScorer (peer "
            "z-score), not the real GNN. Numbers here will NOT match the paper's GNN+PPO "
            "architecture."
        )
        scorer = AnomalyScorer()

    policy = PPO.load(args.model)
    dispatcher = PPODispatcher(policy=policy)

    ppo_results = [run_episode_ppo(dispatcher, scorer, inc, args.step_budget) for inc in incidents]
    greedy_results = [run_episode_greedy(scorer, inc, args.step_budget) for inc in incidents]

    print()
    ppo_summary = summarize(ppo_results, "PPO")
    greedy_summary = summarize(greedy_results, "Baseline C")

    print()
    delta_solve = ppo_summary["solve_rate"] - greedy_summary["solve_rate"]
    print(f"PPO solve rate advantage over Baseline C on ShopMind: {delta_solve:+.3f}")


if __name__ == "__main__":
    main()
