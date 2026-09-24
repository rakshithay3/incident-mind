"""Re-score captured live runs (output/*/telemetry_series.json) with the
trained GraphSAGE: label-free compiler with edges vs the same input without
edges. The pre-fix replay path used edges=[] (and target-aware crash
encoding), so the "no edges" column is what the draft's live table measured.

Usage: PYTHONPATH=. python3 paper/live_rescore.py [glob] > paper/live_rescore.json
"""
import dataclasses
import glob
import json
import sys

from incidentmind_p1.gnn_scorer import GraphSAGEScorer
from incidentmind_p1.training import load_checkpoint
from priority.impact_weights import PriorityWeightedScorer
from replay_demo import compile_live_snapshot


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else "output/*/telemetry_series.json"
    enc, stats = load_checkpoint("models/graphsage.pt")
    scorer = PriorityWeightedScorer(GraphSAGEScorer(enc, stats))
    rows = []
    for path in sorted(glob.glob(pattern)):
        t = json.load(open(path))
        g = compile_live_snapshot(t)
        row = {"run": path.split("/")[-2], "fault_type": t["fault_type"], "target": t["target_service"],
               "down_at_peak": g.metadata.get("down_at_peak")}
        for name, graph in (("edges", g), ("no_edges", dataclasses.replace(g, edges=[]))):
            ranked = sorted(scorer.score_graph(graph), key=lambda s: s.rank)
            ids = [s.service_id for s in ranked]
            row[name] = {"rank_of_target": ids.index(t["target_service"]) + 1,
                         "top3": [(s.service_id, round(s.anomaly_score, 3)) for s in ranked[:3]]}
        rows.append(row)
    print(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
