import urllib.request
import json
import time
import random
import os
import argparse
import subprocess
import sys
import export_metrics
import adjacency_export

SERVICES_FILE = "services.json"
DATASET_DIR = "datasets"

fault_types = ["cpu_stress", "memory_pressure", "network_delay", "pod_crash"]

def load_services():
    try:
        with open(SERVICES_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {SERVICES_FILE}: {e}")
        return {}

def send_post(url, data):
    try:
        req = urllib.request.Request(url, method="POST")
        req.add_header("Content-Type", "application/json")
        body = json.dumps(data).encode("utf-8")
        with urllib.request.urlopen(req, data=body, timeout=5) as res:
            return res.status, res.read().decode("utf-8")
    except Exception as e:
        return 500, str(e)

def run_incident(incident_id, services_config, service_name, fault_type):
    print(f"\n--- Starting Incident {incident_id} ---")
    print(f"Target: {service_name} | Fault: {fault_type}")
    
    # 0. Clean reset microservices to wipe any prior faults or metric counters
    print("Wiping any leftover fault states before collecting baseline...")
    for name, cfg_s in services_config.items():
        if cfg_s.get("role") == "app":
            send_post(f"http://{cfg_s['host']}:{cfg_s['port']}/reset", {})
            
    # 1. Start Load Generator Process
    load_proc = subprocess.Popen(["python", "load_generator.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # 2. Collect baseline telemetry for 10 seconds
    print("Collecting 10s baseline metrics...")
    baseline_snapshots = []
    for _ in range(10):
        nodes, edges = export_metrics.collect_all_telemetry(services_config, 10)
        baseline_snapshots.append({"timestamp": time.time(), "nodes": nodes, "edges": edges})
        time.sleep(1)
        
    # 3. Inject fault
    cfg = services_config[service_name]
    inject_url = f"http://{cfg['host']}:{cfg['port']}/inject-fault"
    inject_data = {
        "type": fault_type,
        "duration_sec": 30,
        "config": {"delayMs": 2000}
    }
    
    print(f"Injecting fault via {inject_url}...")
    status, resp = send_post(inject_url, inject_data)
    if status != 200:
        print(f"Warning: Fault injection returned status {status}: {resp}")
        
    # 4. Collect telemetry per second during 30s failure window
    print("Collecting high-resolution 1s metrics during failure window...")
    failure_snapshots = []
    injected_time = time.time()
    for _ in range(30):
        nodes, edges = export_metrics.collect_all_telemetry(services_config, 2)
        failure_snapshots.append({"timestamp": time.time(), "nodes": nodes, "edges": edges})
        time.sleep(1)
        
    # 5. Rollback state / reset services
    print("Resetting microservices back to clean baseline...")
    for name, cfg_s in services_config.items():
        if cfg_s.get("role") == "app":
            send_post(f"http://{cfg_s['host']}:{cfg_s['port']}/reset", {})
            
    # 5.5 Dynamically verify all services are clean and settled (metrics-aware under active load)
    wait_for_services_to_settle(services_config, timeout_sec=20)
            
    # 6. Terminate Load Generator
    load_proc.terminate()
    load_proc.wait()
    
    # 7. Write telemetry time-series dataset to folder
    inc_dir = os.path.join(DATASET_DIR, f"incident_{incident_id:03d}")
    if not os.path.exists(inc_dir):
        os.makedirs(inc_dir)
        
    dataset_payload = {
        "incident_id": f"incident_{incident_id:03d}",
        "dataset_version": "2026.07",
        "target_service": service_name,
        "fault_type": fault_type,
        "injected_at_epoch": injected_time,
        "baseline_history": baseline_snapshots,
        "failure_history": failure_snapshots
    }
    
    out_file = os.path.join(inc_dir, "telemetry_series.json")
    try:
        with open(out_file, "w") as f:
            json.dump(dataset_payload, f, indent=2)
        print(f"Successfully saved incident telemetry series to {out_file}")
    except Exception as e:
        print(f"Error saving incident data: {e}")

def get_service_metrics(host, port):
    url = f"http://{host}:{port}/metrics"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=1) as res:
            text = res.read().decode("utf-8")
        cpu = None
        mem = None
        for line in text.split("\n"):
            if line.startswith("process_cpu_usage_ratio"):
                cpu = float(line.split()[1])
            elif line.startswith("process_memory_usage_ratio"):
                mem = float(line.split()[1])
        return cpu, mem
    except Exception:
        return None, None

def wait_for_services_to_settle(services_config, timeout_sec=20):
    print("Verifying that all services have fully settled and are healthy (latency & metrics-aware)...")
    start_time = time.time()
    
    while time.time() - start_time < timeout_sec:
        all_settled = True
        for name, cfg in services_config.items():
            if cfg.get("role") != "app":
                continue
                
            # 1. Check health endpoint (HTTP 200)
            health_url = f"http://{cfg['host']}:{cfg['port']}/health"
            try:
                req = urllib.request.Request(health_url)
                with urllib.request.urlopen(req, timeout=1) as res:
                    if res.status != 200:
                        all_settled = False
                        break
            except Exception:
                all_settled = False
                break
                
            # 2. Check active fault status (should be false)
            fault_url = f"http://{cfg['host']}:{cfg['port']}/api/fault-status"
            try:
                req = urllib.request.Request(fault_url)
                with urllib.request.urlopen(req, timeout=1) as res:
                    fault_status = json.loads(res.read().decode("utf-8"))
                    if fault_status.get("active"):
                        all_settled = False
                        break
            except Exception:
                all_settled = False
                break

            # 3. Check actual CPU metrics to ensure they are back to baseline
            cpu, mem = get_service_metrics(cfg["host"], cfg["port"])
            # If CPU is successfully scraped, verify it is below the threshold. Ignore transient timeouts.
            if cpu is not None and cpu > 0.15:
                all_settled = False
                break



        # 4. Check Jaeger transaction metrics (latency and error rate) under active load
        if all_settled:
            try:
                nodes, _ = export_metrics.collect_all_telemetry(services_config, 5)
                for node in nodes:
                    srv = node["service_id"]
                    if srv in ["order-service", "payment-service", "inventory-service", "user-service", "auth-service", "notification-service", "search-service"]:
                        lat = node.get("mean_latency_ms")
                        err = node.get("error_rate")
                        if (lat is not None and lat > 100.0) or (err is not None and err > 0.10):
                            all_settled = False
                            print(f"  Service '{srv}' still recovering from backlog: Latency={lat:.2f}ms, ErrorRate={err:.2f}")
                            break
            except Exception:
                all_settled = False

        if all_settled:
            elapsed = time.time() - start_time
            print(f"All services settled cleanly and verified healthy after {elapsed:.2f}s.")
            return True
            
        time.sleep(1)
        
    print(f"Warning: Settle check timed out after {timeout_sec}s. Some services might not be fully healthy.")
    return False

def main():
    parser = argparse.ArgumentParser(description="ShopMind Incident Dataset Generator")
    parser.add_argument("--count", type=int, default=5, help="Number of synthetic incidents to run")
    parser.add_argument("--seed", type=int, default=None, help="Deterministic seed for service and fault selection")
    parser.add_argument("--schedule", type=str, default=None, help="Path to JSON schedule file containing explicit incidents list")
    args = parser.parse_args()
    
    if args.seed is not None:
        random.seed(args.seed)
        print(f"Deterministic seed set: {args.seed}")
        
    schedule = None
    if args.schedule:
        try:
            with open(args.schedule, "r") as sf:
                schedule = json.load(sf)
            print(f"Loaded explicit schedule containing {len(schedule)} incidents from {args.schedule}")
            args.count = len(schedule)
        except Exception as e:
            print(f"Error loading schedule file {args.schedule}: {e}")
            sys.exit(1)
            
    services_config = load_services()
    if not services_config:
        sys.exit(1)
        
    app_services = [name for name, cfg in services_config.items() if cfg.get("role") == "app"]
    
    print(f"Preparing to execute {args.count} synthetic incidents...")
    if not os.path.exists(DATASET_DIR):
        os.makedirs(DATASET_DIR)
        
    for i in range(1, args.count + 1):
        inc_dir = os.path.join(DATASET_DIR, f"incident_{i:03d}")
        if os.path.exists(os.path.join(inc_dir, "telemetry_series.json")):
            print(f"Incident {i:03d} already exists on disk. Skipping to support resuming...")
            continue
            
        if schedule is not None:
            # Expects list of {"target": "...", "fault": "..."}
            item = schedule[i - 1]
            target = item["target"]
            fault = item["fault"]
        else:
            target = random.choice(app_services)
            fault = random.choice(fault_types)
            
        run_incident(i, services_config, target, fault)
            
    print("\nBatch incident generation completed successfully!")

if __name__ == "__main__":
    main()


