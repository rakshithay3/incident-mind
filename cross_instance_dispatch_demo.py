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

import requests
from stable_baselines3 import PPO

from incidentmind_p1.dispatch import PPODispatcher
from incidentmind_p1.training import load_checkpoint
from incidentmind_p1.gnn_scorer import GraphSAGEScorer
from replay_demo import compile_live_snapshot
from priority.cross_instance_queue import CrossInstancePriorityQueue
from priority.global_dispatch import GlobalPPODispatcher
from notifications.notifier import Notifier


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--receiver-url", default="http://localhost:5001")
    parser.add_argument("--graphsage-model", default="models/graphsage.pt")
    parser.add_argument("--ppo-model", default="models/ppo_dispatch.zip")
    parser.add_argument("--no-notify", action="store_true", help="Disable email notification hooks")
    args = parser.parse_args()
    notifier = None if args.no_notify else Notifier()

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

    incident_ids = {}
    for instance_id, telemetry in snapshots.items():
        incident_ids[instance_id] = telemetry.get("incident_id", instance_id)
        print(f"\n[{instance_id}] Scoring incident {telemetry.get('incident_id')}...")
        try:
            incident = compile_live_snapshot(telemetry)
            scores = base_scorer.score_graph(incident)
        except (KeyError, ValueError) as e:
            print(f"  SKIPPED: malformed telemetry from this instance ({e})")
            continue
        added = queue.add_instance_scores(instance_id, scores)
        print(f"  {added} anomalous node(s) added to global queue")

    print(f"\n=== Global priority queue: {len(queue)} total anomalous node(s) across all instances ===")

    policy = PPO.load(args.ppo_model)
    dispatcher = GlobalPPODispatcher(queue, policy=policy)
    global_ranked = queue.ranked_snapshot()
    for decision in dispatcher.dispatch_all():
        action = decision.action
        print(
            f"  #{decision.step} [{action.instance_id}] agent={action.agent_type:<8} "
            f"target={action.target_service:<22} confidence={decision.policy_confidence:.2f}"
        )
        if notifier is not None:
            notifier.notify_dispatch(
                incident_ids.get(action.instance_id, action.instance_id or "unknown"),
                decision,
                global_ranked,
            )


if __name__ == "__main__":
    main()
