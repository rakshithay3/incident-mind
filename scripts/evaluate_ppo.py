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
                still no ranking by anomaly_score). "Arrival order" here is
                a per-incident seeded shuffle, NOT score_graph()'s raw
                output (already score-sorted) or the incident's raw node
                order (RCAEval's node listing is a fixed per-root-cause-
                service slot, e.g. currencyservice is always index 10 of
                11) -- either of those would leak the answer through
                position instead of testing threshold-only dispatch.
  Baseline C -- always greedily pick the top-ranked node, deterministically.
                Has no memory across steps, so if its first (and only)
                guess is wrong it never recovers within the step budget.
  Baseline D -- sequential greedy: top-ranked NOT-yet-visited node, so it
                walks ranks 1..budget. Solve rate == the scorer's PR@budget.
                This is the fair "no learning" reference for PPO; C alone
                is handicapped by design.
  PPO+mask   -- same trained policy, with visited nodes masked out at
                inference (no retraining).

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
import hashlib
import random
import statistics as st
from pathlib import Path

from stable_baselines3 import PPO

from incidentmind_p1.dispatch import PPODispatcher, baseline_a, baseline_b, baseline_d_sequential, greedy_baseline_c
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


def run_episode_baseline_stepped(dispatch_fn, ranked, incident, step_budget: int = STEP_BUDGET):
    """Shared step loop for Baseline A and Baseline B -- unlike Baseline C,
    both actually use the visited set to try a different node on each
    retry (random re-roll for A, next-in-arrival-order for B), so they get
    the same multi-step chance within the budget that PPO gets."""
    visited: set = set()
    for step in range(1, step_budget + 1):
        decision = dispatch_fn(ranked, visited=visited)
        target = decision.action.target_service
        visited.add(target)
        if target == incident.root_cause:
            return step, True
    return step_budget, False


def run_episode_baseline_d(scorer: AnomalyScorer, incident, step_budget: int = STEP_BUDGET):
    ranked = sorted(scorer.score_graph(incident), key=lambda s: s.rank)
    return run_episode_baseline_stepped(baseline_d_sequential, ranked, incident, step_budget)


def mcnemar(results_x, results_y):
    """Exact McNemar on paired solved/unsolved outcomes:
    (x_only, y_only, two-sided p or None when there are no discordant pairs)."""
    x_only = sum(1 for (_, a), (_, b) in zip(results_x, results_y) if a and not b)
    y_only = sum(1 for (_, a), (_, b) in zip(results_x, results_y) if b and not a)
    n = x_only + y_only
    if n == 0:
        return x_only, y_only, None
    from math import comb

    k = min(x_only, y_only)
    p = min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)
    return x_only, y_only, p


def run_episode_baseline_a(scorer: AnomalyScorer, incident, step_budget: int = STEP_BUDGET, seed: int = 0):
    ranked = sorted(scorer.score_graph(incident), key=lambda s: s.rank)
    return run_episode_baseline_stepped(
        lambda ranked, visited: baseline_a(ranked, visited=visited, seed=seed), ranked, incident, step_budget
    )


def _stable_seed(seed: int, key: str) -> int:
    """A random.seed() input that is portable across processes and Python
    versions -- unlike the builtin hash(), which is randomized per-process
    by PYTHONHASHSEED and would break reproducibility run to run."""
    digest = hashlib.sha256(f"{seed}:{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def run_episode_baseline_b(scorer: AnomalyScorer, incident, step_budget: int = STEP_BUDGET, seed: int = 0):
    """Baseline B needs a genuine 'arrival order' -- independent of BOTH
    anomaly_score (score_graph() always returns nodes pre-sorted by score,
    so the rank-sorted list every other baseline uses would make Baseline B
    silently identical to Baseline C on its first pick) and the incident's
    raw topology order (RCAEval's node listing is a FIXED per-service-
    identity slot -- e.g. every currencyservice-root-cause incident has
    currencyservice at index 10 of 11 across all 125 incidents -- so using
    graph.nodes' raw order directly would just swap one leakage source for
    another). Shuffling once per incident with a seed keyed to incident_id
    keeps it reproducible across runs while decorrelating the order from
    both confounds."""
    scores = list(scorer.score_graph(incident))
    random.Random(_stable_seed(seed, incident.incident_id)).shuffle(scores)
    return run_episode_baseline_stepped(baseline_b, scores, incident, step_budget)


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
    masked_dispatcher = PPODispatcher(policy=policy, mask_visited=True)

    ppo_results = [run_episode_ppo(dispatcher, scorer, inc, args.step_budget) for inc in test_incidents]
    ppo_masked_results = [run_episode_ppo(masked_dispatcher, scorer, inc, args.step_budget) for inc in test_incidents]
    baseline_d_results = [run_episode_baseline_d(scorer, inc, args.step_budget) for inc in test_incidents]
    baseline_a_results = [run_episode_baseline_a(scorer, inc, args.step_budget, seed=args.seed) for inc in test_incidents]
    baseline_b_results = [run_episode_baseline_b(scorer, inc, args.step_budget, seed=args.seed) for inc in test_incidents]
    greedy_results = [run_episode_greedy(scorer, inc, args.step_budget) for inc in test_incidents]

    print()
    ppo_summary = summarize(ppo_results, "PPO")
    baseline_a_summary = summarize(baseline_a_results, "Baseline A")
    baseline_b_summary = summarize(baseline_b_results, "Baseline B")
    greedy_summary = summarize(greedy_results, "Baseline C")
    baseline_d_summary = summarize(baseline_d_results, "Baseline D")
    summarize(ppo_masked_results, "PPO+mask")

    print()
    print(f"PPO solve rate advantage over Baseline A (random):    {ppo_summary['solve_rate'] - baseline_a_summary['solve_rate']:+.3f}")
    print(f"PPO solve rate advantage over Baseline B (threshold): {ppo_summary['solve_rate'] - baseline_b_summary['solve_rate']:+.3f}")
    print(f"PPO solve rate advantage over Baseline C (greedy):    {ppo_summary['solve_rate'] - greedy_summary['solve_rate']:+.3f}")
    print(f"PPO solve rate advantage over Baseline D (sequential): {ppo_summary['solve_rate'] - baseline_d_summary['solve_rate']:+.3f}")
    print()
    for label, other in (("Baseline C", greedy_results), ("Baseline D", baseline_d_results)):
        for name, res in (("PPO", ppo_results), ("PPO+mask", ppo_masked_results)):
            x_only, y_only, p = mcnemar(res, other)
            p_txt = "n/a" if p is None else f"{p:.4f}"
            print(f"McNemar {name} vs {label}: {name}-only={x_only} {label}-only={y_only} p={p_txt}")


if __name__ == "__main__":
    main()
