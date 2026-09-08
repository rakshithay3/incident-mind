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

from incidentmind_p1.contracts import IncidentGraph, ServiceNode
from incidentmind_p1.dispatch import PPODispatcher
from incidentmind_p1.gnn_scorer import GraphSAGEScorer
from incidentmind_p1.training import load_checkpoint

CPU_RATIO_TO_PERCENT = 100.0
MS_TO_SECONDS = 1.0 / 1000.0

# Mirrors package_evaluation.py's SERVICE_MEM_LIMIT_BYTES exactly, so
# scoring here matches what the model was evaluated on. If Archie's table
# changes, update this too (or better: import it directly -- see note in
# telemetry_to_incident_graph()).
SERVICE_MEM_LIMIT_BYTES = {
    "frontend": 128 * 1024 * 1024,
    "api-gateway": 128 * 1024 * 1024,
    "auth-service": 384 * 1024 * 1024,
    "user-service": 384 * 1024 * 1024,
    "order-service": 384 * 1024 * 1024,
    "payment-service": 384 * 1024 * 1024,
    "inventory-service": 384 * 1024 * 1024,
    "notification-service": 384 * 1024 * 1024,
    "search-service": 384 * 1024 * 1024,
    "cache": 192 * 1024 * 1024,
    "postgres-primary": 512 * 1024 * 1024,
    "postgres-replica": 512 * 1024 * 1024,
}
DEFAULT_MEM_LIMIT_BYTES = 384 * 1024 * 1024


def find_last_known_good(service_id, field, history):
    """Walk history backward for the most recent non-null reading."""
    for snapshot in reversed(history):
        for node in snapshot.get("nodes", []):
            if node.get("service_id") == service_id and node.get(field) is not None:
                return node[field]
    return 0.0


_ANOMALY_FIELD_WEIGHTS = {
    # error_rate is ~0 at baseline for almost every service, so a small
    # absolute move is highly significant -- weight it heavily. Latency is
    # in ms, so it needs a small weight to stay comparable to cpu/mem pct.
    "cpu_pct": 1.0,
    "mem_pct": 1.0,
    "error_rate": 10.0,
    "mean_latency_ms": 0.01,
    "p99_latency_ms": 0.01,
}
_CRASHED_NODE_SCORE = 10.0  # pod_crash (cpu_pct is None) is maximal anomaly


def _compute_baseline_means(baseline_history):
    """Per (service_id, field) mean over the baseline window, used as the
    reference point for 'how anomalous is this snapshot'."""
    sums, counts = {}, {}
    for snapshot in baseline_history:
        for node in snapshot.get("nodes", []):
            sid = node.get("service_id")
            for field in _ANOMALY_FIELD_WEIGHTS:
                val = node.get(field)
                if val is not None:
                    key = (sid, field)
                    sums[key] = sums.get(key, 0.0) + val
                    counts[key] = counts.get(key, 0) + 1
    return {key: sums[key] / counts[key] for key in sums}


def _snapshot_anomaly_score(snapshot, baseline_means):
    """Total weighted deviation from baseline, summed across ALL nodes --
    not just the target service. network_delay's signal shows up on the
    caller node rather than the target, so scoring only the target service
    would miss the peak entirely for that fault type."""
    score = 0.0
    for node in snapshot.get("nodes", []):
        sid = node.get("service_id")
        if node.get("cpu_pct") is None:
            score += _CRASHED_NODE_SCORE
            continue
        for field, weight in _ANOMALY_FIELD_WEIGHTS.items():
            val = node.get(field)
            if val is None:
                continue
            baseline = baseline_means.get((sid, field), 0.0)
            score += weight * abs(val - baseline)
    return score


def find_peak_snapshot(telemetry):
    """Return (peak_snapshot, index_in_failure_history) -- the snapshot in
    failure_history with the largest total deviation from the baseline
    window, i.e. the actual moment of peak anomaly, not just whatever was
    captured last. By the time capture stops, a fault may have already
    self-resolved, which is exactly what caused auth-service to fall out
    of the top-5 ranking despite being the true root cause."""
    failure_history = telemetry["failure_history"]
    if len(failure_history) == 1:
        return failure_history[0], 0

    baseline_means = _compute_baseline_means(telemetry.get("baseline_history", []))
    best_idx, best_score = 0, -1.0
    for idx, snapshot in enumerate(failure_history):
        score = _snapshot_anomaly_score(snapshot, baseline_means)
        if score > best_score:
            best_idx, best_score = idx, score
    return failure_history[best_idx], best_idx


def compile_live_snapshot(telemetry: dict) -> IncidentGraph:
    """Convert a raw telemetry_series.json (baseline_history + failure_history)
    into an IncidentGraph, using the SAME unit conversion and pod_crash
    encoding as Archie's package_evaluation.py compile_incident(), so
    scoring matches what the model was evaluated on."""
    fault_type = telemetry["fault_type"]
    target_service = telemetry["target_service"]
    failure_history = telemetry["failure_history"]
    baseline_history = telemetry.get("baseline_history", [])

    # Use the snapshot with peak anomaly deviation, NOT the last captured
    # snapshot -- faults can self-resolve before capture stops, and scoring
    # a recovered snapshot makes the true root cause look healthy.
    last_snapshot, peak_idx = find_peak_snapshot(telemetry)
    # Only backfill nulls from history up to and including the peak, so we
    # never leak a "known good" value from AFTER the peak (which would
    # itself be lookahead bias reintroducing the same class of bug).
    all_history = baseline_history + failure_history[: peak_idx + 1]

    service_nodes = []
    for node in last_snapshot.get("nodes", []):
        srv_id = node["service_id"]
        cpu_pct = node.get("cpu_pct")
        is_crashed = fault_type == "pod_crash" and srv_id == target_service and cpu_pct is None

        if is_crashed:
            cpu, memory, latency, p99, err = 0.0, 0.0, 0.0, 0.0, 1.0
        else:
            cpu_val = cpu_pct if cpu_pct is not None else find_last_known_good(srv_id, "cpu_pct", all_history)
            mem_val = node.get("mem_pct")
            mem_val = mem_val if mem_val is not None else find_last_known_good(srv_id, "mem_pct", all_history)
            lat_val = node.get("mean_latency_ms")
            lat_val = lat_val if lat_val is not None else find_last_known_good(srv_id, "mean_latency_ms", all_history)
            p99_val = node.get("p99_latency_ms")
            p99_val = p99_val if p99_val is not None else find_last_known_good(srv_id, "p99_latency_ms", all_history)
            err_val = node.get("error_rate")
            err_val = err_val if err_val is not None else find_last_known_good(srv_id, "error_rate", all_history)

            cpu = cpu_val * CPU_RATIO_TO_PERCENT
            limit_bytes = SERVICE_MEM_LIMIT_BYTES.get(srv_id, DEFAULT_MEM_LIMIT_BYTES)
            memory = mem_val * limit_bytes
            latency = lat_val * MS_TO_SECONDS
            p99 = p99_val * MS_TO_SECONDS
            err = err_val

        service_nodes.append(
            ServiceNode(
                service_id=srv_id,
                features={"cpu": cpu, "memory": memory, "latency": latency, "error_rate": err, "p99_latency": p99},
            )
        )

    return IncidentGraph(
        incident_id=telemetry["incident_id"],
        timestamp=last_snapshot.get("timestamp", ""),
        nodes=service_nodes,
        edges=[],  # not needed for scoring; GraphSAGEScorer uses node features
        root_cause=target_service,
        metadata={"fault_type": fault_type, "target_service": target_service, "source": "replay"},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a real ShopMind incident through the full live pipeline")
    parser.add_argument("--incident-dir", required=True, help="Directory with telemetry_series.json + service logs")
    parser.add_argument("--graphsage-model", default="models/graphsage.pt")
    parser.add_argument("--ppo-model", default="models/ppo_dispatch.zip")
    parser.add_argument("--code-repo-path", default=None, help="Git repo path for the Code Agent (e.g. Archie's ShopMind checkout)")
    parser.add_argument("--output", default="demo_result.json")
    args = parser.parse_args()

    incident_dir = Path(args.incident_dir)
    telemetry_path = incident_dir / "telemetry_series.json"
    if not telemetry_path.exists():
        raise FileNotFoundError(f"Expected {telemetry_path} -- check --incident-dir")

    with open(telemetry_path) as f:
        telemetry = json.load(f)

    print(f"[1/5] Loaded incident {telemetry['incident_id']}: {telemetry['fault_type']} on {telemetry['target_service']}")

    print("[2/5] Compiling live snapshot for GraphSAGE scoring...")
    incident = compile_live_snapshot(telemetry)
    n_snapshots = len(telemetry["failure_history"])
    print(f"  scored snapshot: peak-anomaly ({n_snapshots} snapshots in failure_history)")
    for n in incident.nodes:
        if n.service_id == telemetry["target_service"]:
            print(f"  target ({n.service_id}) features: {dict(n.features)}")

    print("[3/5] Scoring with GraphSAGE + dispatching with PPO...")
    encoder, stats = load_checkpoint(args.graphsage_model)
    scorer = GraphSAGEScorer(encoder, stats)
    ranked = sorted(scorer.score_graph(incident), key=lambda s: s.rank)
    print("  Ranking:")
    for s in ranked[:5]:
        marker = " <-- true root cause" if s.service_id == telemetry["target_service"] else ""
        print(f"    #{s.rank} {s.service_id:<22} score={s.anomaly_score:.3f} status={s.status}{marker}")

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

    print("[4/5] Running live investigation (Ollama agents + report) using REAL captured evidence...")
    from schemas.contracts import DispatchAction
    from p2_pipeline import run_investigation

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

    print("[5/5] Saving result...")
    result = {
        "incident_id": incident.incident_id,
        "timestamp": incident.timestamp,
        "fault_type": telemetry["fault_type"],
        "injected_target": telemetry["target_service"],
        "true_root_cause": telemetry["target_service"],
        "fault_injection_state": "resolved",
        "nodes": [
            {"service_id": s.service_id, "anomaly_score": s.anomaly_score, "status": s.status, "rank": s.rank}
            for s in ranked
        ],
        "ppo_dispatch": {
            "agent_type": decision.action.agent_type,
            "target_service": decision.action.target_service,
            "policy_confidence": decision.policy_confidence,
        },
        "evidence_bundle": investigation["evidence_bundle"],
        "report": investigation["report"],
        "metrics": {
            "pr_at_1": 1.0 if ranked[0].service_id == telemetry["target_service"] else 0.0,
            "pr_at_3": 1.0 if telemetry["target_service"] in {s.service_id for s in ranked[:3]} else 0.0,
            "pr_at_5": 1.0 if telemetry["target_service"] in {s.service_id for s in ranked[:5]} else 0.0,
        },
    }
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
