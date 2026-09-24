"""
replay_demo.py -- the missing link for tomorrow's demo: takes a REAL,
already-captured ShopMind incident (raw telemetry_series.json + captured
service logs, from Archie) and runs it through the FULL live pipeline:

    raw telemetry --> GraphSAGE scoring --> PPO dispatch
        --> live Ollama agents (using the SAME real incident as evidence)
        --> live Report Agent

Nothing before this script connected GNN+PPO scoring to the replay-based
agent investigation -- shopmind_adapter.py / run_investigation() only
handle the agent side. This closes that gap.

SETUP (run once):

    You need Archie's package_evaluation.py (for the RE1-scale unit
    conversion + SERVICE_MEM_LIMIT_BYTES table) in your repo root:

        cp /tmp/archie-branch/package_evaluation.py .

    And the incident directory Archie sends you should look like:

        <incident_dir>/telemetry_series.json
        <incident_dir>/auth-service.log        (or whichever service)
        <incident_dir>/frontend.log             (optional, for context)
        ...

RUN:

    PYTHONPATH=. python3 replay_demo.py \
        --incident-dir /path/to/incident_from_archie \
        --graphsage-model models/graphsage.pt \
        --ppo-model models/ppo_dispatch.zip \
        --code-repo-path /tmp/archie-branch \
        --output demo_result.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from incidentmind_p1.contracts import IncidentGraph
from incidentmind_p1.dispatch import PPODispatcher
from incidentmind_p1.gnn_scorer import GraphSAGEScorer
from incidentmind_p1.training import load_checkpoint
from priority.impact_weights import PriorityWeightedScorer
from multi_fault import detect_multi_fault
from notifications.notifier import Notifier
from notifications.recipients import get_recipients
from notifications.recovery import wait_for_recovery

# Snapshot selection, crash encoding, unit conversion and edges come from
# shopmind_snapshot.py -- the SAME label-free code that builds the
# 100-incident benchmark (package_evaluation.py), so replay/live runs and
# the paper's numbers see identical inputs. Previously this file had its own
# copy that (a) only encoded a crash when srv_id == target_service, and
# (b) passed edges=[], which turns GraphSAGE into a per-node MLP.
from shopmind_snapshot import compile_telemetry, payload_to_graph, select_peak_snapshot  # noqa: E402


def find_peak_snapshot(telemetry):
    """(peak_snapshot, index) -- label-free, see shopmind_snapshot."""
    snap, idx, _down = select_peak_snapshot(
        telemetry["failure_history"], telemetry.get("baseline_history", [])
    )
    return snap, idx


def compile_live_snapshot(telemetry: dict) -> IncidentGraph:
    """Raw telemetry_series.json -> IncidentGraph (with call-graph edges)."""
    payload = compile_telemetry(telemetry)
    if payload is None:
        raise ValueError("telemetry_series.json needs non-empty baseline_history and failure_history")
    return payload_to_graph(payload, source="replay")


def _fault_started_at(telemetry):
    failure = telemetry.get("failure_history") or []
    if not failure:
        return None
    first = failure[0]
    return first.get("timestamp") or next(
        (n.get("timestamp") for n in first.get("nodes", []) if n.get("timestamp")), None
    )


def _wait_for_shopmind(telemetry, timeout_sec, interval_sec):
    """Poll live ShopMind telemetry until it's back near this incident's
    baseline. If ShopMind/export_metrics isn't available at all, report
    not-recovered rather than guessing -- users are only told it's fixed
    when telemetry actually shows it."""
    try:
        from export_metrics import collect_all_telemetry, load_services
        config = load_services()
    except (ImportError, SystemExit, Exception) as exc:
        print(f"  [recovery] live telemetry unavailable ({type(exc).__name__}), users not emailed")
        return {"recovered": False, "restored_at": None, "polls": 0,
                "still_unhealthy": ["telemetry unavailable"]}

    def collect():
        nodes, _edges = collect_all_telemetry(config, 10)
        return nodes

    return wait_for_recovery(
        telemetry.get("baseline_history", []), collect,
        timeout_sec=timeout_sec, interval_sec=interval_sec,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a real ShopMind incident through the full live pipeline")
    parser.add_argument("--incident-dir", required=True, help="Directory with telemetry_series.json + service logs")
    parser.add_argument("--graphsage-model", default="models/graphsage.pt")
    parser.add_argument("--ppo-model", default="models/ppo_dispatch.zip")
    parser.add_argument("--code-repo-path", default=None, help="Git repo path for the Code Agent (e.g. Archie's ShopMind checkout)")
    parser.add_argument("--output", default="demo_result.json")
    parser.add_argument("--no-notify", action="store_true",
                        help="Don't wait for recovery or email ShopMind users")
    parser.add_argument("--recovery-timeout", type=float, default=180.0,
                        help="Seconds to wait for ShopMind to return to baseline before giving up on the user email")
    parser.add_argument("--recovery-interval", type=float, default=5.0)
    args = parser.parse_args()

    notifier = None if args.no_notify else Notifier()

    incident_dir = Path(args.incident_dir)
    telemetry_path = incident_dir / "telemetry_series.json"
    if not telemetry_path.exists():
        raise FileNotFoundError(f"Expected {telemetry_path} -- check --incident-dir")

    with open(telemetry_path) as f:
        telemetry = json.load(f)

    print(f"[1/5] Loaded incident {telemetry['incident_id']}: {telemetry['fault_type']} on {telemetry['target_service']}")

    # Snapshot ShopMind's registered users now, before anything else: auth-
    # service keeps accounts in memory, so a pod_crash on it would wipe them.
    recipients_info = get_recipients() if notifier is not None else None
    if recipients_info is not None:
        print(f"  ShopMind users to notify on recovery: {len(recipients_info['recipients'])} ({recipients_info['source']})")

    print("[2/6] Compiling live snapshot for GraphSAGE scoring...")
    incident = compile_live_snapshot(telemetry)
    n_snapshots = len(telemetry["failure_history"])
    print(f"  scored snapshot: peak-anomaly ({n_snapshots} snapshots in failure_history)")
    for n in incident.nodes:
        if n.service_id == telemetry["target_service"]:
            print(f"  target ({n.service_id}) features: {dict(n.features)}")

    print("[3/6] Scoring with GraphSAGE + dispatching with PPO...")
    encoder, stats = load_checkpoint(args.graphsage_model)
    base_scorer = GraphSAGEScorer(encoder, stats)
    # Accuracy metrics come from the raw GraphSAGE ranking (what the paper
    # reports); priority re-ranking is for the dispatch order only.
    raw_ranked = sorted(base_scorer.score_graph(incident), key=lambda s: s.rank)
    scorer = PriorityWeightedScorer(base_scorer)
    ranked = sorted(scorer.score_graph(incident), key=lambda s: s.rank)
    print("  Ranking:")
    for s in ranked[:5]:
        marker = " <-- true root cause" if s.service_id == telemetry["target_service"] else ""
        print(f"    #{s.rank} {s.service_id:<22} score={s.anomaly_score:.3f} status={s.status}{marker}")

    multi_fault_nodes = detect_multi_fault(ranked)
    print(f"  Multi-fault detection: {len(multi_fault_nodes)} node(s) above anomaly threshold")
    for s in multi_fault_nodes:
        print(f"    -> {s.service_id} (score={s.anomaly_score:.3f})")

    from stable_baselines3 import PPO

    policy = PPO.load(args.ppo_model)
    dispatcher = PPODispatcher(policy=policy)
    decision = dispatcher.choose(ranked, visited=set(), step=1)
    top_service = decision.action.target_service
    print(f"  PPO dispatch: agent={decision.action.agent_type} target={top_service} confidence={decision.policy_confidence:.2f}")
    if top_service == telemetry["target_service"]:
        print("  PPO correctly identified the true root cause on the first dispatch.")
    else:
        print(f"  Note: PPO dispatched to {top_service}, true root cause is {telemetry['target_service']}.")

    print("[4/6] Running live investigation (Ollama agents + report) using REAL captured evidence...")
    from schemas.contracts import DispatchAction
    from pipeline import run_investigation

    log_path = incident_dir / f"{top_service}.log"
    actions = [
        DispatchAction(agent_type="log", target_service=top_service),
        DispatchAction(agent_type="metrics", target_service=top_service),
        DispatchAction(agent_type="code", target_service=top_service),
    ]

    # run_investigation -> pipeline.investigate_incident -> pipeline.dispatch
    # passes telemetry_path/log_path/code_path through to each agent's
    # investigate(). Code Agent uses code_path (repo_path), not
    # telemetry_path/log_path -- all three are separate pipeline.py params.
    if not log_path.exists():
        print(f"  WARNING: no log file found at {log_path} -- Log Agent will fall back to static sample_data/logs.txt")

    investigation = run_investigation(
        actions,
        incident_id=incident.incident_id,
        telemetry_path=str(telemetry_path),
        log_path=str(log_path) if log_path.exists() else None,
        code_path=args.code_repo_path,
    )

    print(f"  Root cause identified: {investigation['report']['root_cause_service']}")
    print(f"  Confidence: {investigation['report']['confidence_score']}")

    notifications, recovery = [], None
    if notifier is not None:
        print("[5/6] Waiting for ShopMind to return to normal before emailing users...")
        recovery = _wait_for_shopmind(telemetry, args.recovery_timeout, args.recovery_interval)
        if recovery["recovered"]:
            reported = investigation["report"].get("root_cause_service")
            affected = reported if reported and reported != "unknown" else top_service
            fresh = get_recipients()  # pick up anyone who registered meanwhile
            notifications.append(notifier.notify_restored(
                incident.incident_id,
                fresh["recipients"],
                root_cause_service=affected,
                started_at=_fault_started_at(telemetry),
                restored_at=recovery["restored_at"],
                recipients_source=fresh["source"],
            ))
        else:
            notifications.append(notifier.notify_not_recovered(
                incident.incident_id, recovery["still_unhealthy"], args.recovery_timeout
            ))

    print("[6/6] Saving result...")
    result = {
        "incident_id": incident.incident_id,
        "timestamp": incident.timestamp,
        "fault_type": telemetry["fault_type"],
        "injected_target": telemetry["target_service"],
        "true_root_cause": telemetry["target_service"],
        # Replays a finished capture, so the injected fault itself is over;
        # only report "active" if the post-run recovery check says the site
        # never returned to baseline.
        "fault_injection_state": "active" if (recovery is not None and not recovery.get("recovered")) else "resolved",
        "nodes": [
            {"service_id": s.service_id, "anomaly_score": s.anomaly_score, "status": s.status, "rank": s.rank}
            for s in ranked
        ],
        "multi_fault_detected": [
            {"service_id": s.service_id, "anomaly_score": s.anomaly_score, "rank": s.rank}
            for s in multi_fault_nodes
        ],
        "ppo_dispatch": {
            "agent_type": decision.action.agent_type,
            "target_service": decision.action.target_service,
            "policy_confidence": decision.policy_confidence,
        },
        "evidence_bundle": investigation["evidence_bundle"],
        "report": investigation["report"],
        "recovery": recovery,
        "notifications": notifications,
        "metrics": {
            "pr_at_1": 1.0 if raw_ranked[0].service_id == telemetry["target_service"] else 0.0,
            "pr_at_3": 1.0 if telemetry["target_service"] in {s.service_id for s in raw_ranked[:3]} else 0.0,
            "pr_at_5": 1.0 if telemetry["target_service"] in {s.service_id for s in raw_ranked[:5]} else 0.0,
            "ranking": "graphsage_raw",
        },
    }
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
