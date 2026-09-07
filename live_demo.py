"""
live_demo.py -- the missing piece: chains fault injection (Archie) -> live
telemetry -> GraphSAGE scoring + PPO dispatch (Rakshitha) -> live Ollama
agents + report (Dharunya) into ONE run, for tomorrow's live demo.

Nothing before this script connected these three pieces. This is not a
permanent architecture -- it's the fastest path to a real, live, working
demo tonight. Proper branch integration still needs to happen after.

SETUP (run once, from your Rakshitha-branch checkout):

    # Pull in Dharunya's agent/dispatch code
    git clone -b dharunya-work https://github.com/rakshithay3/incident-mind.git /tmp/dharunya-work
    cp -r /tmp/dharunya-work/agents .
    cp -r /tmp/dharunya-work/schemas .
    cp /tmp/dharunya-work/pipeline.py p2_pipeline.py   # renamed to avoid clashing
                                                         # with incidentmind_p1/pipeline.py

    # Pull in Archie's ShopMind glue (Docker services themselves you already
    # have running via his docker-compose.yml, or clone his branch and
    # `docker compose up -d` from there)
    git clone -b archie/rakshithay3/incident-mind https://github.com/rakshithay3/incident-mind.git /tmp/archie-branch
    cp /tmp/archie-branch/services.json .
    cp /tmp/archie-branch/export_metrics.py .
    cp /tmp/archie-branch/demo_workflow.py .
    cp /tmp/archie-branch/reset_state.py .

    pip install ollama --break-system-packages   # if not already installed

RUN:

    # Make sure Docker (Archie's stack) and Ollama are both running first:
    #   cd /tmp/archie-branch && docker compose up -d
    #   ollama serve  (or however you normally start it)

    PYTHONPATH=. python3 live_demo.py --fault cpu_stress --output demo_result.json

Use --fault cpu_stress for the actual demo tomorrow -- it's the strongest
result (PR@1=0.913, PPO solve=0.957) and Archie's own presets already flag
it "RECOMMENDED FOR LIVE DEMOS" (<1s recovery). pod_crash currently scores
worse post-fix (PR@1=0.080) -- do not use it live until that's understood.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from incidentmind_p1.contracts import IncidentGraph, ServiceNode
from incidentmind_p1.dispatch import PPODispatcher
from incidentmind_p1.gnn_scorer import GraphSAGEScorer
from incidentmind_p1.training import load_checkpoint

CPU_RATIO_TO_PERCENT = 100.0
MS_TO_SECONDS = 1.0 / 1000.0

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

STATIC_EDGES = [
    ("frontend", "api-gateway"),
    ("api-gateway", "auth-service"),
    ("api-gateway", "user-service"),
    ("api-gateway", "order-service"),
    ("api-gateway", "search-service"),
    ("order-service", "payment-service"),
    ("order-service", "inventory-service"),
    ("order-service", "notification-service"),
    ("auth-service", "postgres-primary"),
    ("user-service", "postgres-primary"),
    ("order-service", "postgres-primary"),
    ("payment-service", "postgres-primary"),
    ("inventory-service", "postgres-primary"),
    ("search-service", "postgres-replica"),
    ("auth-service", "cache"),
    ("postgres-primary", "postgres-replica"),
]


def telemetry_to_incident_graph(nodes_raw: list, fault_type: str, target_service: str) -> IncidentGraph:
    """Convert Archie's collect_all_telemetry() output into an IncidentGraph,
    applying the same unit conversion as package_evaluation.py's
    compile_incident() so live scoring matches what the model was
    evaluated on."""
    service_nodes = []
    for n in nodes_raw:
        srv_id = n["service_id"]
        cpu_pct = n.get("cpu_pct")
        mem_pct = n.get("mem_pct")
        is_crashed = fault_type == "pod_crash" and srv_id == target_service and cpu_pct is None

        if is_crashed:
            cpu, memory, latency, p99, err = 0.0, 0.0, 0.0, 0.0, 1.0
        else:
            cpu = (cpu_pct or 0.0) * CPU_RATIO_TO_PERCENT
            limit_bytes = SERVICE_MEM_LIMIT_BYTES.get(srv_id, DEFAULT_MEM_LIMIT_BYTES)
            memory = (mem_pct or 0.0) * limit_bytes
            latency = n.get("mean_latency_ms", 0.0) * MS_TO_SECONDS
            p99 = n.get("p99_latency_ms", 0.0) * MS_TO_SECONDS
            err = n.get("error_rate", 0.0)

        service_nodes.append(
            ServiceNode(
                service_id=srv_id,
                features={"cpu": cpu, "memory": memory, "latency": latency, "error_rate": err, "p99_latency": p99},
            )
        )

    edges = [(s, t) for s, t in STATIC_EDGES if s in {n["service_id"] for n in nodes_raw} and t in {n["service_id"] for n in nodes_raw}]

    return IncidentGraph(
        incident_id=f"live_{int(time.time())}",
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        nodes=service_nodes,
        edges=edges,
        root_cause=target_service,  # known because we injected it -- for display/scoring only
        metadata={"fault_type": fault_type, "target_service": target_service, "source": "live_demo"},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Live end-to-end IncidentMind demo run")
    parser.add_argument("--fault", default="cpu_stress", choices=["cpu_stress", "memory_pressure", "network_delay", "pod_crash"])
    parser.add_argument("--graphsage-model", default="models/graphsage.pt")
    parser.add_argument("--ppo-model", default="models/ppo_dispatch.zip")
    parser.add_argument("--output", default="demo_result.json")
    parser.add_argument("--settle-sec", type=float, default=3.0, help="Wait time after injection before scoring")
    parser.add_argument("--skip-rollback", action="store_true")
    args = parser.parse_args()

    # These come from Archie's files, copied in per the setup instructions above
    from demo_workflow import FAULT_PRESETS, inject_fault, send_checkout_transaction
    from export_metrics import collect_all_telemetry, load_services
    from reset_state import check_service_health, emergency_rollback

    preset = next(p for p in FAULT_PRESETS.values() if p["type"] == args.fault)
    services = load_services()

    print(f"[1/6] Baseline health check...")
    app_services = {k: v for k, v in services.items() if v.get("role") == "app"}
    all_up = all(check_service_health(cfg["host"], cfg["port"], timeout=1) for cfg in app_services.values())
    if not all_up:
        print("  Cluster unhealthy -- rolling back first")
        emergency_rollback(services)
    print("  OK")

    print("[1b/6] Capturing pre-fault baseline telemetry (for Metrics Agent comparison)...")
    collect_all_telemetry(services, lookback_sec=10)
    print("  baseline snapshot logged to metrics_history.jsonl")

    print(f"[2/6] Injecting {preset['type']} into {preset['target']}...")
    ok, res = inject_fault(preset["port"], preset["type"], preset["duration"], preset["config"])
    if not ok:
        print(f"  WARNING: injection call failed: {res}", file=sys.stderr)
    print(f"  waiting {args.settle_sec}s for propagation...")
    time.sleep(args.settle_sec)

    print("[3/6] Scraping live telemetry...")
    nodes_raw, _edges_raw = collect_all_telemetry(services, lookback_sec=10)
    incident = telemetry_to_incident_graph(nodes_raw, preset["type"], preset["target"])
    print(f"  {len(incident.nodes)} nodes captured")

    print("[4/6] Scoring with GraphSAGE + dispatching with PPO...")
    encoder, stats = load_checkpoint(args.graphsage_model)
    scorer = GraphSAGEScorer(encoder, stats)
    ranked = sorted(scorer.score_graph(incident), key=lambda s: s.rank)
    print("  Ranking:")
    for s in ranked[:5]:
        marker = " <-- injected fault" if s.service_id == preset["target"] else ""
        print(f"    #{s.rank} {s.service_id:<22} score={s.anomaly_score:.3f} status={s.status}{marker}")

    from stable_baselines3 import PPO

    policy = PPO.load(args.ppo_model)
    dispatcher = PPODispatcher(policy=policy)
    decision = dispatcher.choose(ranked, visited=set(), step=1)
    print(f"  PPO dispatch: agent={decision.action.agent_type} target={decision.action.target_service} confidence={decision.policy_confidence:.2f}")

    print("[5/6] Running live investigation (Ollama agents + report)...")
    from schemas.contracts import DispatchAction
    from p2_pipeline import run_investigation

    top_service = decision.action.target_service
    actions = [
        DispatchAction(agent_type="log", target_service=top_service),
        DispatchAction(agent_type="metrics", target_service=top_service),
        DispatchAction(agent_type="code", target_service=top_service),
    ]
    investigation = run_investigation(actions, incident_id=incident.incident_id)
    print(f"  Root cause identified: {investigation['report']['root_cause_service']}")
    print(f"  Confidence: {investigation['report']['confidence_score']}")

    if not args.skip_rollback:
        print("[6/6] Rolling back fault...")
        emergency_rollback(services)
        print("  OK")
    else:
        print("[6/6] Skipping rollback (--skip-rollback)")

    result = {
        "incident_id": incident.incident_id,
        "timestamp": incident.timestamp,
        "fault_type": preset["type"],
        "injected_target": preset["target"],
        "nodes": [
            {
                "service_id": s.service_id,
                "anomaly_score": s.anomaly_score,
                "embedding_dim": s.embedding_dim,
                "status": s.status,
                "rank": s.rank,
            }
            for s in ranked
        ],
        "ppo_dispatch": {
            "step": decision.step,
            "action": {"agent_type": decision.action.agent_type, "target_service": decision.action.target_service},
            "policy_confidence": decision.policy_confidence,
        },
        "evidence_bundle": investigation["evidence_bundle"],
        "report": investigation["report"],
    }

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nSaved full result to {args.output}")


if __name__ == "__main__":
    main()
