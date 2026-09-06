"""Break down PPO vs Baseline C solve rate on ShopMind by structural difficulty,
to distinguish two very different explanations for a solve-rate drop vs RE1:

  (a) genuine cross-topology generalization limit on multi-hop cascading
      incidents (expected, and even predicted in the project blueprint), vs
  (b) an artifact of ShopMind's compressed latency/severity dynamic range
      (0-2s vs RE1's 0-9.9s) flattening anomaly scores and causing failures
      even on structurally trivial (single-hop) incidents.

Difficulty proxy: hop-distance (BFS over the incident's edge list, treated
as undirected) from the top-ranked node under the scorer to the true
root_cause node. hop_distance == 0 means the scorer's #1 guess IS the root
cause (trivial/single-hop); hop_distance >= 2 means the anomaly signal is
appearing far from the true source (classic cascading-failure signature).

Usage:
    PYTHONPATH=. python3 scripts/diagnose_shopmind_failures.py \
        --dataset /Users/rakshithayathiraj/Desktop/shopmind_evaluation_dataset \
        --model models/ppo_dispatch.zip \
        --graphsage-model models/graphsage.pt
"""

from __future__ import annotations

import argparse
import statistics as st
from collections import defaultdict, deque

from stable_baselines3 import PPO

from incidentmind_p1.dispatch import PPODispatcher, greedy_baseline_c
from incidentmind_p1.loader import load_dataset, summarize_dataset
from incidentmind_p1.scoring import AnomalyScorer

STEP_BUDGET = 5


def build_adjacency(incident):
    adj = defaultdict(set)
    for source, target in incident.edges:
        adj[source].add(target)
        adj[target].add(source)
    return adj


def hop_distance(adj, start, goal):
    if start == goal:
        return 0
    visited = {start}
    queue = deque([(start, 0)])
    while queue:
        node, dist = queue.popleft()
        for neighbor in adj.get(node, ()):
            if neighbor == goal:
                return dist + 1
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, dist + 1))
    return None  # disconnected -- shouldn't happen on a connected service graph


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


def bucket_label(hops):
    if hops is None:
        return "disconnected"
    if hops == 0:
        return "0 (single-hop / trivial)"
    if hops == 1:
        return "1"
    return f"{hops}+ (multi-hop cascading)"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Break down ShopMind solve rate by hop-distance difficulty bucket"
    )
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--step-budget", type=int, default=STEP_BUDGET)
    parser.add_argument("--graphsage-model", default=None)
    args = parser.parse_args()

    incidents = load_dataset(args.dataset)
    print(summarize_dataset(incidents))

    if args.graphsage_model:
        from incidentmind_p1.gnn_scorer import GraphSAGEScorer
        from incidentmind_p1.training import load_checkpoint

        encoder, stats = load_checkpoint(args.graphsage_model)
        scorer = GraphSAGEScorer(encoder, stats)
        print(f"Scoring with trained GraphSAGE checkpoint: {args.graphsage_model}")
    else:
        print("WARNING: no --graphsage-model given -- using AnomalyScorer fallback.")
        scorer = AnomalyScorer()

    policy = PPO.load(args.model)
    dispatcher = PPODispatcher(policy=policy)

    rows = []
    for inc in incidents:
        adj = build_adjacency(inc)
        ranked = sorted(scorer.score_graph(inc), key=lambda s: s.rank)
        top_node = ranked[0].service_id if ranked else None
        hops = hop_distance(adj, top_node, inc.root_cause) if top_node else None

        ppo_steps, ppo_ok = run_episode_ppo(dispatcher, scorer, inc, args.step_budget)
        greedy_steps, greedy_ok = run_episode_greedy(scorer, inc, args.step_budget)

        rows.append(
            {
                "incident_id": inc.incident_id,
                "root_cause": inc.root_cause,
                "top_ranked_node": top_node,
                "hops": hops,
                "ppo_solved": ppo_ok,
                "greedy_solved": greedy_ok,
            }
        )

    # Per-incident detail
    print("\n--- Per-incident detail ---")
    print(f"{'incident':12s} {'root_cause':20s} {'top_ranked':20s} {'hops':>5s} {'PPO':>5s} {'GreedyC':>8s}")
    for r in rows:
        print(
            f"{r['incident_id']:12s} {r['root_cause']:20s} {str(r['top_ranked_node']):20s} "
            f"{str(r['hops']):>5s} {str(r['ppo_solved']):>5s} {str(r['greedy_solved']):>8s}"
        )

    # Bucketed summary
    buckets = defaultdict(list)
    for r in rows:
        buckets[bucket_label(r["hops"])].append(r)

    print("\n--- Solve rate by hop-distance bucket (top-ranked node -> true root cause) ---")
    print(f"{'bucket':28s} {'n':>4s} {'PPO solve_rate':>16s} {'Baseline C solve_rate':>22s}")
    for label in sorted(buckets.keys(), key=lambda l: (l == "disconnected", l)):
        group = buckets[label]
        n = len(group)
        ppo_rate = sum(r["ppo_solved"] for r in group) / n
        greedy_rate = sum(r["greedy_solved"] for r in group) / n
        print(f"{label:28s} {n:4d} {ppo_rate:16.3f} {greedy_rate:22.3f}")

    print(
        "\nInterpretation: if solve rate is high on the '0 (single-hop / trivial)' "
        "bucket and drops sharply as hop-distance increases, the gap vs RE1 is a "
        "genuine cross-topology / cascading-failure generalization limit -- expected "
        "and consistent with the project's own risk analysis (RL should look upstream "
        "on multi-hop failures where greedy dispatch chases the downstream victim). "
        "If solve rate is ALSO low on the trivial bucket, the drop is not (only) about "
        "topology -- re-check whether ShopMind's compressed latency/severity range "
        "(0-2s vs RE1's 0-9.9s) is flattening anomaly scores enough to cause ties or "
        "near-ties in ranking even on easy incidents."
    )


if __name__ == "__main__":
    main()
