"""Command line entry points for P1 work."""

from __future__ import annotations

import argparse
import json

from .dispatch import greedy_baseline_c
from .evaluation import evaluate_ranking
from .loader import load_dataset, load_incident, summarize_dataset
from .pipeline import run_inference
from .scoring import AnomalyScorer


def main() -> None:
    parser = argparse.ArgumentParser(prog="incidentmind-p1")
    sub = parser.add_subparsers(dest="command", required=True)

    score = sub.add_parser("score", help="score one RCAEval incident and emit handoff JSON")
    score.add_argument("--incident", required=True)

    validate = sub.add_parser("validate", help="validate RCAEval dataset shape")
    validate.add_argument("--dataset", required=True)

    baseline = sub.add_parser("baseline-c", help="run GNN-informed greedy dispatch")
    baseline.add_argument("--incident", required=True)

    args = parser.parse_args()
    if args.command == "score":
        print(json.dumps(run_inference(args.incident).to_json(), indent=2))
    elif args.command == "validate":
        incidents = load_dataset(args.dataset)
        print(json.dumps(summarize_dataset(incidents), indent=2))
    elif args.command == "baseline-c":
        graph = load_incident(args.incident)
        scores = AnomalyScorer().score_graph(graph)
        output = {
            "incident_id": graph.incident_id,
            "baseline_c_dispatch": greedy_baseline_c(scores).to_json(),
            "metrics": evaluate_ranking(scores, graph.root_cause).to_json(),
        }
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
