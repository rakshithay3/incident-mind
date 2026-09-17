"""Compute raw GraphSAGE PR@1 / PR@3 / PR@5 / MTTD on ShopMind using a saved
checkpoint -- no retraining, no PPO dispatch simulation. This is the direct
apples-to-apples comparison against the RE1 test-split PR@1=0.920 number.

Usage:
    PYTHONPATH=. python3 pr_at_k_shopmind.py \
        --dataset ~/Desktop/shopmind_evaluation_dataset \
        --graphsage-model models/graphsage.pt
"""

from __future__ import annotations

import argparse
import statistics as st

from incidentmind_p1.contracts import NodeScore
from incidentmind_p1.evaluation import evaluate_ranking
from incidentmind_p1.loader import load_dataset, summarize_dataset
from incidentmind_p1.training import load_checkpoint, score_incident


def to_node_scores(ranked):
    return [
        NodeScore(service_id=sid, anomaly_score=prob, embedding_dim=128, status="scored", rank=i + 1)
        for i, (sid, prob) in enumerate(ranked)
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--graphsage-model", required=True)
    args = parser.parse_args()

    incidents = load_dataset(args.dataset)
    print(summarize_dataset(incidents))

    encoder, stats = load_checkpoint(args.graphsage_model)
    print(f"Loaded checkpoint: {args.graphsage_model} (FeatureStats fit on RE1 train split -- not refit here)")

    results = []
    for incident in incidents:
        ranked = score_incident(encoder, incident, stats=stats)
        metrics = evaluate_ranking(to_node_scores(ranked), incident.root_cause)
        results.append(metrics)

    pr1 = st.fmean(r.pr_at_1 for r in results)
    pr3 = st.fmean(r.pr_at_3 for r in results)
    pr5 = st.fmean(r.pr_at_5 for r in results)
    mttd = st.fmean(r.mttd_steps for r in results)
    print(f"\nGraphSAGE on ShopMind ({len(incidents)} incidents): "
          f"PR@1={pr1:.3f} PR@3={pr3:.3f} PR@5={pr5:.3f} MTTD={mttd:.2f}")

    N = len(incidents[0].nodes)
    print(f"random baseline:  PR@1={1/N:.3f} PR@3={min(3,N)/N:.3f} PR@5={min(5,N)/N:.3f}")


if __name__ == "__main__":
    main()
