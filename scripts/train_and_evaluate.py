"""Train GraphSAGE on RE1 Online Boutique incidents and evaluate PR@k / MTTD.

Local / VS Code equivalent of notebook cells 41, 43, 44, 46.

Run scripts/prepare_re1_data.py first to populate data/rcaeval_re1/incidents/.

Usage:
    python scripts/train_and_evaluate.py [--epochs 50] [--seed 42]
"""

from __future__ import annotations
import argparse
import random
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from incidentmind_p1.contracts import NodeScore
from incidentmind_p1.evaluation import evaluate_ranking
from incidentmind_p1.loader import load_dataset, summarize_dataset
from incidentmind_p1.training import FeatureStats, score_incident, train_graphsage

ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = ROOT / "data" / "rcaeval_re1"


def to_node_scores(ranked):
    return [
        NodeScore(service_id=sid, anomaly_score=prob, embedding_dim=128, status="scored", rank=i + 1)
        for i, (sid, prob) in enumerate(ranked)
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--print-per-incident",
        action="store_true",
        help="Print the full per-incident root-cause report (like notebook cell 46).",
    )
    args = parser.parse_args()

    # --- Load + split -----------------------------------------------------
    incidents = load_dataset(str(DATASET_DIR))
    print(summarize_dataset(incidents))

    random.seed(args.seed)
    shuffled = incidents[:]
    random.shuffle(shuffled)
    n = len(shuffled)
    n_train, n_val = int(n * 0.6), int(n * 0.2)
    train_incidents = shuffled[:n_train]
    val_incidents = shuffled[n_train:n_train + n_val]
    test_incidents = shuffled[n_train + n_val:]
    print(f"train={len(train_incidents)} val={len(val_incidents)} test={len(test_incidents)}")

    # --- Train --------------------------------------------------------------
    # FeatureStats must be fit ONLY on train and reused at inference -- never
    # refit on the incident being scored or on ShopMind (see project notes).
    stats = FeatureStats.fit(train_incidents)
    encoder, history, stats = train_graphsage(train_incidents, epochs=args.epochs, stats=stats)

    for h in history[::10]:
        print(h.epoch, round(h.loss, 4))
    print("final loss:", round(history[-1].loss, 4))

    # --- Evaluate: aggregate PR@k / MTTD -------------------------------------
    results = []
    for incident in test_incidents:
        ranked = score_incident(encoder, incident, stats=stats)
        metrics = evaluate_ranking(to_node_scores(ranked), incident.root_cause)
        results.append(metrics)

    pr1 = st.fmean(r.pr_at_1 for r in results)
    pr3 = st.fmean(r.pr_at_3 for r in results)
    pr5 = st.fmean(r.pr_at_5 for r in results)
    mttd = st.fmean(r.mttd_steps for r in results)
    print(f"GraphSAGE:      PR@1={pr1:.3f} PR@3={pr3:.3f} PR@5={pr5:.3f} MTTD={mttd:.2f}")

    N = len(test_incidents[0].nodes)
    print(f"random baseline: PR@1={1/N:.3f} PR@3={min(3,N)/N:.3f} PR@5={min(5,N)/N:.3f}")

    # --- Optional: full per-incident report (notebook cell 46) --------------
    if args.print_per_incident:
        print("=" * 90)
        print("                 ROOT CAUSE PREDICTION RESULTS")
        print("=" * 90)

        rows = []
        for idx, incident in enumerate(test_incidents, start=1):
            ranked = score_incident(encoder, incident, stats=stats)
            predicted_service = ranked[0][0]
            confidence = ranked[0][1]
            actual_service = incident.root_cause
            status = "correct" if predicted_service == actual_service else "incorrect"

            print(f"\nIncident {idx}")
            print("-" * 60)
            print(f"Actual Root Cause    : {actual_service}")
            print(f"Predicted Root Cause : {predicted_service}")
            print(f"Confidence           : {confidence:.3f}")
            print(f"Status               : {status}")
            print("\nTop-5 Ranked Services")
            for rank, (service, score) in enumerate(ranked[:5], start=1):
                marker = " <-- Actual Root Cause" if service == actual_service else ""
                print(f"{rank}. {service:25} {score:.3f}{marker}")

            rows.append({
                "incident": idx,
                "actual_root_cause": actual_service,
                "predicted_root_cause": predicted_service,
                "confidence": round(confidence, 3),
                "correct": predicted_service == actual_service,
            })

        try:
            import pandas as pd
            print("\n")
            print(pd.DataFrame(rows).to_string(index=False))
        except ImportError:
            print("\n(install pandas for a formatted results table)")
            for row in rows:
                print(row)


if __name__ == "__main__":
    main()
