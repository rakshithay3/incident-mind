"""
cross_instance_dispatch_demo.py -- the full multi-instance, multi-fault,
priority-weighted dispatch flow: pulls every snapshot currently held by
multi_instance_receiver.py, scores each instance's graph with GraphSAGE,
feeds every anomalous node (from ANY instance) into ONE global
CrossInstancePriorityQueue, then lets PPO pull dispatch targets
sequentially off that SAME global queue -- one decision per anomalous node,
in cross-instance priority order -- instead of dispatching within a single
instance's ranking at a time.
"""

import argparse
import json

import requests
from stable_baselines3 import PPO

from incidentmind_p1.dispatch import PPODispatcher
from incidentmind_p1.training import load_checkpoint
from incidentmind_p1.gnn_scorer import GraphSAGEScorer
from replay_demo import compile_live_snapshot
from priority.cross_instance_queue import CrossInstancePriorityQueue
from priority.global_dispatch import GlobalPPODispatcher
from priority.result_export import build_multi_instance_result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--receiver-url", default="http://localhost:5001")
    parser.add_argument("--graphsage-model", default="models/graphsage.pt")
    parser.add_argument("--ppo-model", default="models/ppo_dispatch.zip")
    parser.add_argument("--output", default=None,
                        help="Write queue + dispatches as JSON for the dashboard (copy to dashboard/public/multiInstanceResult.json)")
    args = parser.parse_args()

    resp = requests.get(f"{args.receiver_url}/snapshots")
    resp.raise_for_status()
    snapshots = resp.json()

    if not snapshots:
        print("No instances have reported telemetry yet.")
        return

    print(f"Found {len(snapshots)} instance(s): {list(snapshots.keys())}")

    encoder, stats = load_checkpoint(args.graphsage_model)
    base_scorer = GraphSAGEScorer(encoder, stats)

    queue = CrossInstancePriorityQueue()

    instances = []
    for instance_id, telemetry in snapshots.items():
        summary = {
            "instance_id": instance_id,
            "incident_id": telemetry.get("incident_id"),
            "fault_type": telemetry.get("fault_type"),
            "target_service": telemetry.get("target_service"),
            "anomalous_count": 0,
            "status": "scored",
        }
        instances.append(summary)
        print(f"\n[{instance_id}] Scoring incident {telemetry.get('incident_id')}...")
        try:
            incident = compile_live_snapshot(telemetry)
            scores = base_scorer.score_graph(incident)
        except (KeyError, ValueError) as e:
            print(f"  SKIPPED: malformed telemetry from this instance ({e})")
            summary["status"] = "skipped"
            continue
        added = queue.add_instance_scores(instance_id, scores)
        summary["anomalous_count"] = added
        print(f"  {added} anomalous node(s) added to global queue")

    print(f"\n=== Global priority queue: {len(queue)} total anomalous node(s) across all instances ===")

    policy = PPO.load(args.ppo_model)
    dispatcher = GlobalPPODispatcher(queue, policy=policy)
    global_ranked = queue.ranked_snapshot()
    decisions = []
    for decision in dispatcher.dispatch_all():
        decisions.append(decision)
        action = decision.action
        print(
            f"  #{decision.step} [{action.instance_id}] agent={action.agent_type:<8} "
            f"target={action.target_service:<22} confidence={decision.policy_confidence:.2f}"
        )

    if args.output:
        result = build_multi_instance_result(instances, global_ranked, decisions)
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()
