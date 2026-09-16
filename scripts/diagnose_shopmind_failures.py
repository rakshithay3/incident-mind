"""Per-incident error analysis for GraphSAGE on ShopMind: breaks PR@1 hits/
misses down by fault_type and by root-cause service, to see whether misses
are concentrated (e.g. on services/fault types RE1 never saw) or spread
evenly (suggesting a general precision ceiling rather than a specific gap).

Usage:
    PYTHONPATH=. python3 scripts/diagnose_shopmind_failures.py \
        --dataset ~/Desktop/shopmind_evaluation_dataset \
        --graphsage-model models/graphsage.pt
"""

from __future__ import annotations

import argparse
from collections import defaultdict

from incidentmind_p1.loader import load_dataset
from incidentmind_p1.training import load_checkpoint, score_incident


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--graphsage-model", required=True)
    args = parser.parse_args()

    incidents = load_dataset(args.dataset)
    encoder, stats = load_checkpoint(args.graphsage_model)

    rows = []
    for incident in incidents:
        ranked = score_incident(encoder, incident, stats=stats)
        predicted = ranked[0][0]
        actual = incident.root_cause
        fault_type = incident.metadata.get("fault_type", "unknown")
        rank_of_truth = next(
            (i + 1 for i, (sid, _) in enumerate(ranked) if sid == actual), None
        )
        rows.append({
            "incident_id": incident.incident_id,
            "fault_type": fault_type,
            "actual": actual,
            "predicted": predicted,
            "hit": predicted == actual,
            "rank_of_truth": rank_of_truth,
        })

    total = len(rows)
    hits = sum(r["hit"] for r in rows)
    print(f"Overall PR@1: {hits}/{total} = {hits/total:.3f}\n")

    # --- Breakdown by fault_type -------------------------------------------
    by_fault = defaultdict(list)
    for r in rows:
        by_fault[r["fault_type"]].append(r)

    print("--- PR@1 by fault_type ---")
    print(f"{'fault_type':30s} {'n':>4s} {'hits':>5s} {'PR@1':>6s}")
    for fault_type, group in sorted(by_fault.items(), key=lambda kv: -len(kv[1])):
        n = len(group)
        h = sum(g["hit"] for g in group)
        print(f"{fault_type:30s} {n:4d} {h:5d} {h/n:6.3f}")

    # --- Breakdown by root-cause service -------------------------------------
    by_service = defaultdict(list)
    for r in rows:
        by_service[r["actual"]].append(r)

    print("\n--- PR@1 by root-cause service ---")
    print(f"{'service':22s} {'n':>4s} {'hits':>5s} {'PR@1':>6s}  mean_rank_of_truth")
    for service, group in sorted(by_service.items(), key=lambda kv: -len(kv[1])):
        n = len(group)
        h = sum(g["hit"] for g in group)
        mean_rank = sum(g["rank_of_truth"] for g in group) / n
        print(f"{service:22s} {n:4d} {h:5d} {h/n:6.3f}  {mean_rank:.2f}")

    # --- What gets predicted instead, on misses ------------------------------
    misses = [r for r in rows if not r["hit"]]
    print(f"\n--- On the {len(misses)} misses, what did the model predict instead? ---")
    wrong_pred_counts = defaultdict(int)
    for r in misses:
        wrong_pred_counts[r["predicted"]] += 1
    for service, count in sorted(wrong_pred_counts.items(), key=lambda kv: -kv[1]):
        print(f"  predicted '{service}' instead: {count} times")

    print(f"\nmean rank of true root cause on misses: "
          f"{sum(r['rank_of_truth'] for r in misses) / len(misses):.2f}"
          if misses else "\n(no misses)")


if __name__ == "__main__":
    main()
