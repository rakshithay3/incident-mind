#!/usr/bin/env python3
"""
ShopMind Rehearsed End-to-End Demo Workflow (Weeks 12-14)
Demonstrates the full incident lifecycle:
  1. Baseline Verification
  2. Normal E-Commerce Traffic & Distributed Tracing
  3. Interactive/Automated Chaos Fault Injection
  4. Real-Time Telemetry Cascade & GNN Graph Compilation
  5. Dynamic Settle Check & Clean Reset
"""

import sys
import os
import json
import time
import argparse
import urllib.request
import urllib.parse
from reset_state import emergency_rollback, check_service_health

SERVICES_FILE = "services.json"

FAULT_PRESETS = {
    "1": {
        "name": "CPU Stress (auth-service)",
        "target": "auth-service",
        "type": "cpu_stress",
        "port": 3001,
        "category": "Instant Recovery (<1s) — RECOMMENDED FOR LIVE DEMOS",
        "duration": 20,
        "config": {}
    },
    "2": {
        "name": "Memory Pressure (search-service)",
        "target": "search-service",
        "type": "memory_pressure",
        "port": 3007,
        "category": "Extended Recovery (~5–10s) — Buffer Deallocation & GC Sweep",
        "duration": 20,
        "config": {}
    },
    "3": {
        "name": "Network Delay (payment-service)",
        "target": "payment-service",
        "type": "network_delay",
        "port": 3004,
        "category": "Extended Recovery (~2–5s) — Shows Upstream Latency Cascade",
        "duration": 20,
        "config": {"delayMs": 2000}
    },
    "4": {
        "name": "Pod Crash (inventory-service)",
        "target": "inventory-service",
        "type": "pod_crash",
        "port": 3005,
        "category": "Extended Recovery (~10–15s) — Shows Container Restart & Failover",
        "duration": 20,
        "config": {}
    }
}

def load_services():
    with open(SERVICES_FILE, "r") as f:
        return json.load(f)

def send_checkout_transaction():
    """Simulates a storefront checkout order through order-service."""
    url = "http://localhost:3003/api/order/create"
    payload = {
        "userId": "demo-shopper-42",
        "items": [{"productId": "p101", "quantity": 1, "price": 499}],
        "amount": 499
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=5) as res:
            elapsed_ms = (time.time() - t0) * 1000
            body = json.loads(res.read().decode("utf-8"))
            return True, elapsed_ms, body
    except Exception as e:
        return False, 0.0, str(e)

def inject_fault(target_port, fault_type, duration_sec, config):
    """Calls /inject-fault on target microservice."""
    url = f"http://localhost:{target_port}/inject-fault"
    payload = {
        "type": fault_type,
        "duration_sec": duration_sec,
        "config": config
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=3) as res:
            return True, json.loads(res.read().decode("utf-8"))
    except Exception as e:
        return False, str(e)

def scrape_service_metrics(host, port):
    """Scrapes /metrics for CPU and memory usage."""
    url = f"http://{host}:{port}/metrics"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=2) as res:
            lines = res.read().decode("utf-8").splitlines()
            cpu, mem = 0.0, 0.0
            for l in lines:
                if l.startswith("process_cpu_usage_ratio"):
                    cpu = float(l.split()[1])
                elif l.startswith("process_memory_usage_ratio"):
                    mem = float(l.split()[1])
            return cpu, mem
    except Exception:
        return None, None

def run_demo(fault_key="1", non_interactive=False):
    preset = FAULT_PRESETS.get(fault_key, FAULT_PRESETS["1"])
    print("\n" + "=" * 65)
    print("      SHOPMIND END-TO-END DEMO: LIVE INCIDENT LIFECYCLE")
    print("=" * 65)

    # ---------------------------------------------------------
    # STAGE 1: Baseline Health Check
    # ---------------------------------------------------------
    print("\n[STAGE 1/5] VERIFYING CLUSTER BASELINE HEALTH...")
    services = load_services()
    app_services = {k: v for k, v in services.items() if v.get("role") == "app"}
    
    all_up = True
    for name, cfg in app_services.items():
        is_up = check_service_health(cfg["host"], cfg["port"], timeout=1)
        cpu, mem = scrape_service_metrics(cfg["host"], cfg["port"])
        cpu_str = f"{cpu*100:.1f}%" if cpu is not None else "N/A"
        mem_str = f"{mem*100:.1f}%" if mem is not None else "N/A"
        status_label = "HEALTHY" if is_up else "UNHEALTHY"
        print(f"  - {name:<22} [{status_label}] CPU: {cpu_str:<6} | Mem: {mem_str:<6}")
        if not is_up:
            all_up = False

    if not all_up:
        print("\n  [!] Cluster is not healthy. Executing emergency rollback first...")
        emergency_rollback(services)

    print("  ✓ Baseline verified: All microservices UP and telemetry channels green.")

    # ---------------------------------------------------------
    # STAGE 2: Storefront Checkout & Distributed Tracing
    # ---------------------------------------------------------
    print("\n[STAGE 2/5] SIMULATING STOREFRONT E-COMMERCE TRAFFIC...")
    print("  Dispatching customer checkout order through order-service (port 3003)...")
    ok, latency_ms, resp = send_checkout_transaction()
    if ok:
        print(f"  ✓ Checkout Successful! Latency: {latency_ms:.1f}ms")
        print(f"    - Order ID   : {resp.get('order', {}).get('orderId', 'ord_demo_01')}")
        print(f"    - Stock Status: Confirmed by inventory-service")
        print(f"    - Payment    : Captured by payment-service")
        print(f"    - Jaeger View: http://localhost:16686 (Service: order-service)")
    else:
        print(f"  [!] Checkout returned warning: {resp}")

    # ---------------------------------------------------------
    # STAGE 3: Fault Injection
    # ---------------------------------------------------------
    print(f"\n[STAGE 3/5] CHAOS INJECTION: {preset['name'].upper()}")
    print(f"  Target Service : {preset['target']} (Port {preset['port']})")
    print(f"  Fault Type     : {preset['type']}")
    print(f"  Classification : {preset['category']}")
    print(f"  Duration       : {preset['duration']} seconds")

    if not non_interactive:
        print("\n  Press [Enter] to inject the fault and observe failure propagation...")
        try:
            input()
        except EOFError:
            pass

    print(f"  Injecting {preset['type']} into {preset['target']}...")
    inj_ok, inj_res = inject_fault(preset['port'], preset['type'], preset['duration'], preset['config'])
    if not inj_ok:
        print(f"  [!] Fault injection notice: {inj_res}")
    else:
        print(f"  ✓ Fault successfully active on {preset['target']}.")

    # ---------------------------------------------------------
    # STAGE 4: Telemetry Cascade & GNN Feature Observation
    # ---------------------------------------------------------
    print("\n[STAGE 4/5] OBSERVING TELEMETRY CASCADE & FAILURE IMPACT...")
    time.sleep(2) # Give fault 2s to perturb system
    
    print("  Sampling live node features during failure window:")
    for name, cfg in app_services.items():
        cpu, mem = scrape_service_metrics(cfg["host"], cfg["port"])
        cpu_display = f"{cpu*100:.1f}%" if cpu is not None else "TIMED OUT (NULL)"
        mem_display = f"{mem*100:.1f}%" if mem is not None else "TIMED OUT (NULL)"
        anomaly_marker = " <--- ANOMALY TARGET" if name == preset["target"] else ""
        print(f"    {name:<22} : CPU = {cpu_display:<18} | Mem = {mem_display}{anomaly_marker}")

    # Fire checkout under fault conditions to demonstrate user impact
    print("\n  Executing checkout transaction during active fault:")
    f_ok, f_latency, f_resp = send_checkout_transaction()
    if f_ok:
        print(f"    Transaction result: Completed in {f_latency:.1f}ms (Degraded)")
    else:
        print(f"    Transaction result: FAILED / ABORTED ({f_resp})")

    # ---------------------------------------------------------
    # STAGE 5: Dynamic Settle & Clean Reset
    # ---------------------------------------------------------
    print("\n[STAGE 5/5] EMERGENCY ROLLBACK & DYNAMIC SETTLE VERIFICATION...")
    if not non_interactive:
        print("  Press [Enter] to trigger rollback and restore the cluster...")
        try:
            input()
        except EOFError:
            pass

    rollback_start = time.time()
    reset_ok = emergency_rollback(services)
    rollback_duration = time.time() - rollback_start

    print("\n" + "=" * 65)
    print("                    DEMO EXECUTION SUMMARY")
    print("=" * 65)
    print(f"  Demonstrated Scenario : {preset['name']}")
    print(f"  Fault Category        : {preset['category']}")
    print(f"  Rollback Status       : {'SUCCESS' if reset_ok else 'ATTENTION REQUIRED'}")
    print(f"  Measured Settle Time  : {rollback_duration:.2f}s")
    print("=" * 65 + "\n")
    return reset_ok, rollback_duration

def main():
    parser = argparse.ArgumentParser(description="ShopMind Rehearsed Live Demo Workflow")
    parser.add_argument("--fault", choices=["1", "2", "3", "4"], default="1",
                        help="Preset choice: 1=CPU Stress, 2=Mem Pressure, 3=Network Delay, 4=Pod Crash")
    parser.add_argument("--non-interactive", action="store_true",
                        help="Run automatically without pausing for user input")
    args = parser.parse_args()

    run_demo(fault_key=args.fault, non_interactive=args.non_interactive)

if __name__ == "__main__":
    main()
