import os
import json
import zipfile
import shutil

DATASETS_DIR = "datasets"
COMPILED_DIR = "datasets_compiled"
ZIP_OUTPUT = "shopmind_evaluation_dataset.zip"

def compile_incident(inc_dir):
    series_path = os.path.join(inc_dir, "telemetry_series.json")
    if not os.path.exists(series_path):
        return None
        
    with open(series_path, "r") as f:
        data = json.load(f)
        
    incident_id = data.get("incident_id")
    target = data.get("target_service")
    fault = data.get("fault_type")
    
    failure_history = data.get("failure_history", [])
    if not failure_history:
        return None
        
    # Select the middle snapshot (index 15 of 30) where the fault is fully active and stable.
    # Selecting a single snapshot preserves the physical consistency of node metrics and edge weights.
    snap_idx = min(15, len(failure_history) - 1)
    snap = failure_history[snap_idx]
    
    # 1. Compile Nodes and map keys to GNN contract
    compiled_nodes = []
    for node in snap.get("nodes", []):
        srv_id = node.get("service_id")
        
        # Support both old key formats and new key formats for compatibility
        cpu = node.get("cpu", node.get("cpu_pct", 0.0))
        memory = node.get("memory", node.get("mem_pct", 0.0))
        latency = node.get("latency", node.get("mean_latency_ms", 0.0))
        p99_lat = node.get("p99_latency", node.get("p99_latency_ms", 0.0))
        err_rate = node.get("error_rate", 0.0)
        
        compiled_nodes.append({
            "service_id": srv_id,
            "cpu": cpu,
            "memory": memory,
            "latency": latency,
            "error_rate": err_rate,
            "p99_latency": p99_lat,
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
    
    incidents = [d for d in os.listdir(DATASETS_DIR) if d.startswith("incident_") and os.path.isdir(os.path.join(DATASETS_DIR, d))]
    incidents.sort()
    
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
