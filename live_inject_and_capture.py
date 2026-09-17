"""
live_inject_and_capture.py -- the missing link between a REAL live fault
injection on ShopMind and replay_demo.py's full inference pipeline.

Uses pieces that already exist, unchanged:
  - export_metrics.py::collect_all_telemetry()   (Archie, Prometheus+Jaeger scrape)
  - <service>/inject-fault HTTP endpoint          (Archie, per-service server.js)
  - docker logs <container>                       (standard docker CLI)

Produces exactly what replay_demo.py already expects:
  <out_dir>/telemetry_series.json   (baseline_history + failure_history)
  <out_dir>/<service>.log

Also POSTs that same telemetry (tagged with --instance-id) to
multi_instance_receiver.py, same schema capture_and_post.py sends, so a live
capture reaches the cross-instance queue without a separate manual step.
Pass --skip-post to opt out.

Then (optionally) hands off straight to replay_demo.py so the whole thing
runs as one command: inject -> capture -> GraphSAGE -> PPO -> agents -> report.

RUN:
    PYTHONPATH=. python3 live_inject_and_capture.py \
        --target-service auth-service \
        --fault-type cpu_stress \
        --duration-sec 30 \
        --out-dir live_incident_001 \
        --run-pipeline

Requires services.json and export_metrics.py to be importable (repo root),
and the ShopMind docker-compose stack + Prometheus/Jaeger already running.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

from export_metrics import collect_all_telemetry, load_services

CONTAINER_PREFIX = "shopmind-"
BASELINE_SNAPSHOTS = 5      # ~5 snapshots before injecting
BASELINE_INTERVAL_SEC = 2
FAILURE_INTERVAL_SEC = 2
LOG_TAIL_LINES = 500


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def capture_window(config: dict, n_snapshots: int, interval_sec: float, lookback_sec: int = 10) -> list[dict]:
    """Repeatedly call collect_all_telemetry() and wrap each call as one
    'snapshot' in the shape telemetry_series.json's history arrays use."""
    history = []
    for _ in range(n_snapshots):
        nodes, edges = collect_all_telemetry(config, lookback_sec)
        history.append({
            "timestamp": nodes[0]["timestamp"] if nodes else "",
            "nodes": nodes,
            "edges": edges,
        })
        time.sleep(interval_sec)
    return history


def inject_fault(config: dict, target_service: str, fault_type: str, duration_sec: int, fault_config: dict | None = None) -> None:
    host = config[target_service]["host"]
    port = config[target_service]["port"]
    url = f"http://{host}:{port}/inject-fault"
    print(f"[inject] POST {url}  type={fault_type} duration={duration_sec}s")
    post_json(url, {
        "type": fault_type,
        "duration_sec": duration_sec,
        "config": fault_config or {},
    })


def post_to_receiver(telemetry: dict, instance_id: str, receiver_url: str) -> None:
    """POST the captured telemetry to multi_instance_receiver.py, tagged with
    instance_id -- same schema capture_and_post.py sends (telemetry_series.json
    plus instance_id), which is what mac-instance-A/B already have stored."""
    payload = dict(telemetry)
    payload["instance_id"] = instance_id
    try:
        resp = post_json(receiver_url, payload)
        print(f"  posted to {receiver_url} as instance_id={instance_id}: {resp}")
    except Exception as e:
        print(f"  WARNING: could not post telemetry to {receiver_url}: {e}")


def capture_logs(out_dir: Path, services: list[str], tail: int = LOG_TAIL_LINES) -> None:
    """Pull docker logs for each service into <service>.log, matching the
    naming convention replay_demo.py already looks for."""
    for service in services:
        container = f"{CONTAINER_PREFIX}{service}"
        log_path = out_dir / f"{service}.log"
        try:
            result = subprocess.run(
                ["docker", "logs", "--tail", str(tail), container],
                capture_output=True, text=True, timeout=10,
            )
            log_path.write_text(result.stdout + result.stderr)
        except Exception as e:
            print(f"  WARNING: could not capture logs for {container}: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inject a live fault into ShopMind and capture it as a telemetry_series.json incident")
    parser.add_argument("--target-service", required=True, help="e.g. auth-service")
    parser.add_argument("--fault-type", required=True, choices=["cpu_stress", "memory_pressure", "network_delay", "pod_crash"])
    parser.add_argument("--duration-sec", type=int, default=30)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--incident-id", default=None)
    parser.add_argument("--instance-id", default=socket.gethostname(), help="Tag posted to multi_instance_receiver.py (default: this machine's hostname)")
    parser.add_argument("--receiver-url", default="http://localhost:5001/telemetry")
    parser.add_argument("--skip-post", action="store_true", help="Don't POST the captured telemetry to multi_instance_receiver.py")
    parser.add_argument("--run-pipeline", action="store_true", help="Call replay_demo.py's pipeline on the captured result immediately after")
    parser.add_argument("--graphsage-model", default="models/graphsage.pt")
    parser.add_argument("--ppo-model", default="models/ppo_dispatch.zip")
    parser.add_argument("--code-repo-path", default=None)
    args = parser.parse_args()

    config = load_services()
    if args.target_service not in config:
        raise ValueError(f"{args.target_service} not found in services.json")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    incident_id = args.incident_id or f"live_{args.target_service}_{args.fault_type}_{int(time.time())}"

    print(f"[1/5] Capturing baseline ({BASELINE_SNAPSHOTS} snapshots)...")
    baseline_history = capture_window(config, BASELINE_SNAPSHOTS, BASELINE_INTERVAL_SEC)

    print(f"[2/5] Injecting fault and capturing failure window ({args.duration_sec}s)...")
    inject_fault(config, args.target_service, args.fault_type, args.duration_sec)
    n_failure_snapshots = max(1, args.duration_sec // FAILURE_INTERVAL_SEC)
    failure_history = capture_window(config, n_failure_snapshots, FAILURE_INTERVAL_SEC)

    telemetry = {
        "incident_id": incident_id,
        "target_service": args.target_service,
        "fault_type": args.fault_type,
        "baseline_history": baseline_history,
        "failure_history": failure_history,
    }
    telemetry_path = out_dir / "telemetry_series.json"
    with open(telemetry_path, "w") as f:
        json.dump(telemetry, f, indent=2)
    print(f"  wrote {telemetry_path}")

    if args.skip_post:
        print("[3/5] Skipping post to multi_instance_receiver.py (--skip-post)")
    else:
        print(f"[3/5] Posting telemetry to multi_instance_receiver.py as instance_id={args.instance_id}...")
        post_to_receiver(telemetry, args.instance_id, args.receiver_url)

    print("[4/5] Capturing service logs...")
    capture_logs(out_dir, list(config.keys()))

    print("[5/5] Done.")
    if args.run_pipeline:
        print("Handing off to replay_demo.py...")
        cmd = [
            "python3", "replay_demo.py",
            "--incident-dir", str(out_dir),
            "--graphsage-model", args.graphsage_model,
            "--ppo-model", args.ppo_model,
            "--output", str(out_dir / "result.json"),
        ]
        if args.code_repo_path:
            cmd += ["--code-repo-path", args.code_repo_path]
        subprocess.run(cmd, check=True)
    else:
        print(f"Run manually with:\n  python3 replay_demo.py --incident-dir {out_dir} ...")


if __name__ == "__main__":
    main()
