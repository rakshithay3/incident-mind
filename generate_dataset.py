import urllib.request
import json
import time
import random
import os
import argparse
import subprocess
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

def main():
    parser = argparse.ArgumentParser(description="ShopMind Incident Dataset Generator")
    parser.add_argument("--count", type=int, default=5, help="Number of synthetic incidents to run")
    args = parser.parse_args()
    
    services_config = load_services()
    if not services_config:
        sys.exit(1)
        
    app_services = [name for name, cfg in services_config.items() if cfg.get("role") == "app"]
    
    print(f"Preparing to execute {args.count} synthetic incidents...")
    if not os.path.exists(DATASET_DIR):
        os.makedirs(DATASET_DIR)
        
    for i in range(1, args.count + 1):
        target = random.choice(app_services)
        fault = random.choice(fault_types)
        
        # If fault is pod_crash, we wait an extra 5 seconds after reset to let containers boot up
        run_incident(i, services_config, target, fault)
        if fault == "pod_crash":
            print("Waiting 5s for crashed container to complete Docker restart...")
            time.sleep(5)
            
    print("\nBatch incident generation completed successfully!")

if __name__ == "__main__":
    main()
