import os
import json
import zipfile
import shutil

DATASETS_DIR = "datasets"
COMPILED_DIR = "datasets_compiled"
ZIP_OUTPUT = "shopmind_evaluation_dataset.zip"
SCHEDULE_FILE = "evaluation_schedule.json"

def get_baseline_averages(baseline_history):
    """Computes baseline average latency, cpu, and memory for all services."""
    sums = {}
    counts = {}
    for snap in baseline_history:
        for node in snap.get("nodes", []):
            srv = node["service_id"]
            if srv not in sums:
                sums[srv] = {"cpu": 0.0, "memory": 0.0, "latency": 0.0}
                counts[srv] = 0
            
            # Read original telemetry schema fields
            sums[srv]["cpu"] += node.get("cpu_pct") or 0.0
            sums[srv]["memory"] += node.get("mem_pct") or 0.0
            sums[srv]["latency"] += node.get("mean_latency_ms") or 0.0
            counts[srv] += 1
            
    averages = {}
    for srv, m_sums in sums.items():
        cnt = counts[srv] if counts[srv] > 0 else 1
        averages[srv] = {
            "cpu": m_sums["cpu"] / cnt,
            "memory": m_sums["memory"] / cnt,
            "latency": m_sums["latency"] / cnt
        }
    return averages

def select_peak_anomaly_snapshot(failure_history, baseline_averages, target_service, fault_type):
    """Dynamically identifies the snapshot with the highest anomaly score."""
    if not failure_history:
        return None
        
    best_snap = failure_history[0]
    max_score = -1.0
    
    for snap in failure_history:
        score = 0.0
        for node in snap.get("nodes", []):
            srv = node["service_id"]
            base = baseline_averages.get(srv, {"cpu": 0.02, "memory": 0.1, "latency": 5.0})
            
            curr_cpu = node.get("cpu_pct") or 0.0
            curr_mem = node.get("mem_pct") or 0.0
            curr_lat = node.get("mean_latency_ms") or 0.0
            curr_err = node.get("error_rate") or 0.0
            
            # Anomaly score based on deviations from baseline
            cpu_dev = max(0.0, curr_cpu - base["cpu"])
            mem_dev = max(0.0, curr_mem - base["memory"])
            lat_ratio = curr_lat / max(1.0, base["latency"])
            
            # High weight on errors and target symptoms
            score += (cpu_dev * 5.0) + (mem_mem := mem_dev * 5.0) + curr_err * 10.0
            if lat_ratio > 3.0:
                score += lat_ratio
                
            # If this is the target service of the crash, lack of metrics is anomalous
            if srv == target_service and fault_type == "pod_crash" and (node.get("cpu_pct") is None or node.get("cpu_pct") == 0.0):
                score += 50.0
                
        if score > max_score:
            max_score = score
            best_snap = snap
            
    # Find index of the selected snap to guide our last-known-good history search
    snap_idx = 15
    for idx, s in enumerate(failure_history):
        if s.get("timestamp") == best_snap.get("timestamp"):
            snap_idx = idx
            break
            
    return best_snap, snap_idx

def find_last_known_good(service_id, key, snap_idx, failure_history, baseline_history, fallback_val):
    """Searches backward in time for the most recent valid telemetry sample."""
    # 1. Search failure history backwards starting from snap_idx - 1
    for idx in range(snap_idx - 1, -1, -1):
        for node in failure_history[idx].get("nodes", []):
            if node["service_id"] == service_id:
                val = node.get(key)
                if val is not None:
                    return val
                    
    # 2. Search baseline history backwards starting from the end
    for idx in range(len(baseline_history) - 1, -1, -1):
        for node in baseline_history[idx].get("nodes", []):
            if node["service_id"] == service_id:
                val = node.get(key)
                if val is not None:
                    return val
                    
    return fallback_val

def compile_incident(inc_dir):
    series_path = os.path.join(inc_dir, "telemetry_series.json")
    if not os.path.exists(series_path):
        return None
        
    with open(series_path, "r") as f:
        data = json.load(f)
        
    incident_id = data.get("incident_id")
    target = data.get("target_service")
    fault = data.get("fault_type")
    
    baseline_history = data.get("baseline_history", [])
    failure_history = data.get("failure_history", [])
    if not failure_history or not baseline_history:
        return None
        
    # Calculate baseline averages and select the peak anomaly snapshot dynamically
    baseline_averages = get_baseline_averages(baseline_history)
    snap, snap_idx = select_peak_anomaly_snapshot(failure_history, baseline_averages, target, fault)
    if not snap:
        return None
    
    # 1. Compile Nodes and translate keys to GNN contract
    compiled_nodes = []
    for node in snap.get("nodes", []):
        srv_id = node.get("service_id")
        base = baseline_averages.get(srv_id, {"cpu": 0.02, "memory": 0.1, "latency": 5.0})
        
        # CPU (Coerce nulls)
        cpu = node.get("cpu_pct")
        if cpu is None:
            cpu = find_last_known_good(srv_id, "cpu_pct", snap_idx, failure_history, baseline_history, base["cpu"])
            
        # Memory (Coerce nulls)
        memory = node.get("mem_pct")
        if memory is None:
            memory = find_last_known_good(srv_id, "mem_pct", snap_idx, failure_history, baseline_history, base["memory"])
            
        # Latency (Coerce nulls)
        latency = node.get("mean_latency_ms")
        if latency is None:
            latency = find_last_known_good(srv_id, "mean_latency_ms", snap_idx, failure_history, baseline_history, base["latency"])
            
        # P99 Latency (Coerce nulls)
        p99_lat = node.get("p99_latency_ms")
        if p99_lat is None:
            p99_fallback = base["latency"] * 3.0 if base["latency"] > 0 else 20.0
            p99_lat = find_last_known_good(srv_id, "p99_latency_ms", snap_idx, failure_history, baseline_history, p99_fallback)
            
        # Error Rate (Coerce nulls)
        err_rate = node.get("error_rate")
        if err_rate is None:
            err_rate = find_last_known_good(srv_id, "error_rate", snap_idx, failure_history, baseline_history, 0.0)
        
        # Map values to the GNN schema expected by loader.py
        compiled_nodes.append({
            "service_id": srv_id,
            "cpu": round(cpu, 4),
            "memory": round(memory, 4),
            "error_rate": round(err_rate, 4),
            "latency": round(latency, 2),
            "p99_latency": round(p99_lat, 2),
            "label": 1 if srv_id == target else 0
        })
        
    # 2. Compile Edges
    compiled_edges = []
    for edge in snap.get("edges", []):
        compiled_edges.append({
            "source": edge.get("source"),
            "target": edge.get("target"),
            "call_count": edge.get("call_count", 0)
        })
        
    # 3. Assemble GNN payload
    gnn_payload = {
        "incident_id": incident_id,
        "timestamp": snap.get("timestamp", ""),
        "nodes": compiled_nodes,
        "edges": compiled_edges,
        "fault_injection": {
            "active": True,
            "fault_type": fault,
            "target_service": target,
            "injected_at": data.get("injected_at_epoch", "")
        },
        "root_cause": target,
        "metadata": {
            "fault_type": fault,
            "dataset_version": "2026.07"
        }
    }
    return gnn_payload

def main():
    print("Starting evaluation dataset packaging...")
    
    if os.path.exists(COMPILED_DIR):
        shutil.rmtree(COMPILED_DIR)
    os.makedirs(COMPILED_DIR)
    
    # 1. Determine target incident limit based on schedule file to avoid old data pollution
    target_count = None
    if os.path.exists(SCHEDULE_FILE):
        try:
            with open(SCHEDULE_FILE, "r") as sf:
                schedule = json.load(sf)
                target_count = len(schedule)
                print(f"Target schedule detected: limiting packaging to first {target_count} incidents.")
        except Exception as e:
            print(f"Warning: failed to load schedule file: {e}")
            
    incidents = [d for d in os.listdir(DATASETS_DIR) if d.startswith("incident_") and os.path.isdir(os.path.join(DATASETS_DIR, d))]
    incidents.sort()
    
    if target_count is not None:
        incidents = incidents[:target_count]
        
    compiled_count = 0
    for inc_name in incidents:
        inc_dir = os.path.join(DATASETS_DIR, inc_name)
        payload = compile_incident(inc_dir)
        if payload:
            out_file = os.path.join(COMPILED_DIR, f"{inc_name}.json")
            with open(out_file, "w") as f:
                json.dump(payload, f, indent=2)
            compiled_count += 1
            
    print(f"Successfully compiled {compiled_count} incidents into {COMPILED_DIR}/")
    
    # Compress into a single zip archive for GNN training delivery
    with zipfile.ZipFile(ZIP_OUTPUT, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(COMPILED_DIR):
            for file in files:
                zipf.write(os.path.join(root, file), file)
                
    print(f"Dataset package successfully bundled into {ZIP_OUTPUT}")

if __name__ == "__main__":
    main()
