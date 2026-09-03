"""Diagnose whether ShopMind's raw feature scales match RE1's, and whether
the z-normalization fit on RE1 training data is pushing ShopMind features
into a range the trained GraphSAGE encoder never saw.

Usage:
    PYTHONPATH=. python3 diagnose_feature_scale.py \
        --re1-dataset data/rcaeval_re1 \
        --shopmind-dataset /Users/rakshithayathiraj/Desktop/shopmind_evaluation_dataset \
        --graphsage-model models/graphsage.pt
"""

from __future__ import annotations

import argparse
import statistics as st

from incidentmind_p1.contracts import FEATURES
from incidentmind_p1.loader import load_dataset
from incidentmind_p1.training import load_checkpoint


def collect_raw_columns(incidents):
    columns = {name: [] for name in FEATURES}
    for incident in incidents:
        for node in incident.nodes:
            for name, value in zip(FEATURES, node.feature_vector(FEATURES)):
                columns[name].append(value)
    return columns


def describe(columns, label):
    print(f"\n--- {label} (raw, pre-normalization) ---")
    print(f"{'feature':14s} {'min':>10s} {'max':>10s} {'mean':>10s} {'std':>10s}")
    for name, values in columns.items():
        if not values:
            print(f"{name:14s}  (no data)")
            continue
        vmin, vmax = min(values), max(values)
        vmean = st.fmean(values)
        vstd = st.pstdev(values) if len(values) > 1 else 0.0
        print(f"{name:14s} {vmin:10.3f} {vmax:10.3f} {vmean:10.3f} {vstd:10.3f}")


def describe_normalized(columns, means, stds, label):
    print(f"\n--- {label} (AFTER applying RE1-fitted z-normalization) ---")
    print(f"{'feature':14s} {'min':>10s} {'max':>10s} {'mean':>10s} {'std':>10s}")
    for name, m, s in zip(FEATURES, means, stds):
        values = columns[name]
        if not values:
            continue
        normed = [(v - m) / s for v in values]
        vmin, vmax = min(normed), max(normed)
        vmean = st.fmean(normed)
        vstd = st.pstdev(normed) if len(normed) > 1 else 0.0
        flag = "  <-- FAR FROM N(0,1), outside training distribution" if abs(vmean) > 2 or vstd > 3 else ""
        print(f"{name:14s} {vmin:10.3f} {vmax:10.3f} {vmean:10.3f} {vstd:10.3f}{flag}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare RE1 vs ShopMind raw feature scales")
    parser.add_argument("--re1-dataset", required=True)
    parser.add_argument("--shopmind-dataset", required=True)
    parser.add_argument("--graphsage-model", required=True, help="checkpoint holding the RE1-fitted FeatureStats")
    args = parser.parse_args()

    re1_incidents = load_dataset(args.re1_dataset)
    shopmind_incidents = load_dataset(args.shopmind_dataset)

    _, stats = load_checkpoint(args.graphsage_model)
    print(f"Loaded FeatureStats from checkpoint (fit on RE1 training split):")
    print(f"{'feature':14s} {'mean':>10s} {'std':>10s}")
    for name, m, s in zip(stats.feature_names, stats.means, stats.stds):
        print(f"{name:14s} {m:10.3f} {s:10.3f}")

    re1_cols = collect_raw_columns(re1_incidents)
    shopmind_cols = collect_raw_columns(shopmind_incidents)

    describe(re1_cols, "RE1 (all incidents, raw)")
    describe(shopmind_cols, "ShopMind (all incidents, raw)")

    describe_normalized(shopmind_cols, stats.means, stats.stds, "ShopMind")

    print(
        "\nInterpretation: GraphSAGE was trained on RE1 features normalized to "
        "roughly N(0,1). If ShopMind's normalized mean/std above is wildly off "
        "from 0/1 (flagged rows), the model is seeing inputs far outside anything "
        "it learned from -- this alone can explain a PR@1 collapse from RE1 to "
        "ShopMind, independent of any real topology-generalization gap."
    )


if __name__ == "__main__":
    main()
