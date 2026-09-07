"""Per-fault-type PR@1/3/5 and PPO-vs-Baseline-C solve_rate breakdown on
the full ShopMind held-out set.

Fallback / companion to pr_at_k_shopmind.py -- gives you the fault_type x
metric table (cpu_stress / memory_pressure / network_delay / pod_crash) in
one pass, using the same GraphSAGE + PPO checkpoints as evaluate_shopmind.py.

Usage:
    PYTHONPATH=. python3 scripts/pr_at_k_by_fault_type.py \
        --dataset ~/Desktop/shopmind_evaluation_dataset \
        --model models/ppo_dispatch.zip \
        --graphsage-model models/graphsage.pt
"""

from __future__ import annotations

import argparse
import statistics as st
from collections import defaultdict

from stable_baselines3 import PPO

from incidentmind_p1.contracts import precision_at_k
from incidentmind_p1.dispatch import PPODispatcher, greedy_baseline_c
from incidentmind_p1.loader import load_dataset
from incidentmind_p1.scoring import AnomalyScorer

STEP_BUDGET = 5


def run_episode_ppo(dispatcher, scorer, incident, step_budget=STEP_BUDGET):
    ranked = sorted(scorer.score_graph(incident), key=lambda s: s.rank)
    visited: set = set()
    for step in range(1, step_budget + 1):
        decision = dispatcher.choose(ranked, visited=visited, step=step)
        target = decision.action.target_service
        visited.add(target)
        if target == incident.root_cause:
            return step, True
    return step_budget, False


def run_episode_greedy(scorer, incident, step_budget=STEP_BUDGET):
    ranked = sorted(scorer.score_graph(incident), key=lambda s: s.rank)
    decision = greedy_baseline_c(ranked)
    target = decision.action.target_service
    if target == incident.root_cause:
        return 1, True
    return step_budget, False


def main() -> None:
    parser = argparse.ArgumentParser(description="Per-fault-type PR@k and solve_rate breakdown on ShopMind")
    parser.add_argument("--dataset", required=True, help="Path to unzipped ShopMind incidents")
    parser.add_argument("--model", required=True, help="Path to trained PPO .zip from scripts/train_ppo.py")
    parser.add_argument("--step-budget", type=int, default=STEP_BUDGET)
    parser.add_argument(
        "--graphsage-model",
        default=None,
        help="Path to trained GraphSAGE checkpoint (models/graphsage.pt). Falls back to "
        "AnomalyScorer if omitted -- numbers won't match the paper's GNN+PPO architecture.",
    )
    args = parser.parse_args()

    incidents = load_dataset(args.dataset)
    print(f"Loaded {len(incidents)} ShopMind incidents")

    if args.graphsage_model:
        from incidentmind_p1.gnn_scorer import GraphSAGEScorer
        from incidentmind_p1.training import load_checkpoint

        encoder, stats = load_checkpoint(args.graphsage_model)
        scorer = GraphSAGEScorer(encoder, stats)
        print(f"Scoring with trained GraphSAGE checkpoint: {args.graphsage_model}")
    else:
        print("WARNING: no --graphsage-model given -- evaluating against AnomalyScorer, not the real GNN.")
        scorer = AnomalyScorer()

    policy = PPO.load(args.model)
    dispatcher = PPODispatcher(policy=policy)

    # Bucket incidents by fault_type (falls back to "unknown" if metadata is missing it)
    by_fault_type = defaultdict(list)
    for inc in incidents:
        fault_type = inc.metadata.get("fault_type", "unknown")
        by_fault_type[fault_type].append(inc)

    print(f"\n{'fault_type':18s}  {'n':>4s}  {'PR@1':>6s}  {'PR@3':>6s}  {'PR@5':>6s}  "
          f"{'PPO solve':>10s}  {'BaselineC solve':>16s}")

    overall_pr1, overall_pr3, overall_pr5 = [], [], []
    overall_ppo_solved, overall_greedy_solved = [], []

    for fault_type in sorted(by_fault_type):
        group = by_fault_type[fault_type]
        pr1s, pr3s, pr5s = [], [], []
        ppo_solved, greedy_solved = [], []

        for inc in group:
            ranked = sorted(scorer.score_graph(inc), key=lambda s: s.rank)
            ranked_ids = [s.service_id for s in ranked]
            pr1s.append(precision_at_k(ranked_ids, inc.root_cause, 1))
            pr3s.append(precision_at_k(ranked_ids, inc.root_cause, 3))
            pr5s.append(precision_at_k(ranked_ids, inc.root_cause, 5))

            _, ppo_ok = run_episode_ppo(dispatcher, scorer, inc, args.step_budget)
            _, greedy_ok = run_episode_greedy(scorer, inc, args.step_budget)
            ppo_solved.append(ppo_ok)
            greedy_solved.append(greedy_ok)

        overall_pr1.extend(pr1s)
        overall_pr3.extend(pr3s)
        overall_pr5.extend(pr5s)
        overall_ppo_solved.extend(ppo_solved)
        overall_greedy_solved.extend(greedy_solved)

        print(
            f"{fault_type:18s}  {len(group):4d}  {st.fmean(pr1s):6.3f}  {st.fmean(pr3s):6.3f}  "
            f"{st.fmean(pr5s):6.3f}  {sum(ppo_solved) / len(ppo_solved):10.3f}  "
            f"{sum(greedy_solved) / len(greedy_solved):16.3f}"
        )

    print(
        f"{'OVERALL':18s}  {len(incidents):4d}  {st.fmean(overall_pr1):6.3f}  {st.fmean(overall_pr3):6.3f}  "
        f"{st.fmean(overall_pr5):6.3f}  {sum(overall_ppo_solved) / len(overall_ppo_solved):10.3f}  "
        f"{sum(overall_greedy_solved) / len(overall_greedy_solved):16.3f}"
    )


if __name__ == "__main__":
    main()
