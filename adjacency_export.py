import urllib.request
import json
import time
import argparse
import os
import sys
import export_metrics

try:
    import scipy.stats
except ImportError:
    # Print warning but allow validator structure to exist; users will run pip install scipy
    print("WARNING: scipy is not installed. To run validation, please execute: pip install scipy")

SERVICES_FILE = "services.json"
HISTORY_FILE = "metrics_history.jsonl"
OUTPUT_FILE = "adjacency.json"
REPORT_FILE = "validation_report.json"

def load_services():
    try:
        with open(SERVICES_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {SERVICES_FILE}: {e}")
        return {}

def http_get_json(url):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None

def query_active_fault(services_config, previous_file=None):
    active_fault_info = {
        "active": False,
        "fault_type": "",
        "target_service": "",
        "injected_at": "",
        "scheduled_duration_sec": 0,
        "auto_rollback": True
    }
    ground_truth = ""
    
    # Global state file for fault memory tracking
    global_fault_file = "datasets/last_active_fault.json"
    
    # 1. First check live status from services
    for name, cfg in services_config.items():
        if cfg.get("role") == "app":
            url = f"http://{cfg['host']}:{cfg['port']}/api/fault-status"
            status = http_get_json(url)
            if status and status.get("active"):
                active_fault_info = {
                    "active": True,
                    "fault_type": status.get("fault_type", ""),
                    "target_service": status.get("target_service", ""),
                    "injected_at": status.get("injected_at", ""),
                    "scheduled_duration_sec": status.get("scheduled_duration_sec", 0),
                    "auto_rollback": status.get("auto_rollback", True)
                }
                ground_truth = name
                
                # Write to global cache file to persist across different experiment runs/processes
                try:
                    os.makedirs("datasets", exist_ok=True)
                    with open(global_fault_file, "w") as gf:
                        json.dump({"fault_injection": active_fault_info, "ground_truth_root_cause": ground_truth}, gf)
                except Exception as e:
                    print(f"Error caching active fault globally: {e}")
                    
                return active_fault_info, ground_truth
                
    # 2. If no live fault, check global fault cache first, falling back to previous experiment file
    cache_sources = [global_fault_file]
    if previous_file:
        cache_sources.append(previous_file)
        
    for cache_path in cache_sources:
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r") as f:
                    cache_data = json.load(f)
                prev_fault = cache_data.get("fault_injection", {})
                if prev_fault and prev_fault.get("active") and prev_fault.get("injected_at"):
                    import datetime
                    iso_str = prev_fault.get("injected_at")
                    dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
                    injected_epoch = dt.timestamp()
                    duration = prev_fault.get("scheduled_duration_sec", 0)
                    
                    # If we are within 60s grace period after scheduled expiration
                    if time.time() < injected_epoch + duration + 60.0:
                        active_fault_info = {
                            "active": True, # Retain as active for labeled dataset
                            "fault_type": prev_fault.get("fault_type", ""),
                            "target_service": prev_fault.get("target_service", ""),
                            "injected_at": prev_fault.get("injected_at", ""),
                            "scheduled_duration_sec": duration,
                            "auto_rollback": prev_fault.get("auto_rollback", True),
                            "grace_period": True
                        }
                        ground_truth = cache_data.get("ground_truth_root_cause", "")
                        print(f"Retained previous fault label {prev_fault.get('fault_type')} on {prev_fault.get('target_service')} due to cooldown grace period (cached from {os.path.basename(cache_path)}).")
                        break
            except Exception as e:
                print(f"Error checking cache {cache_path} for grace period: {e}")
                
    return active_fault_info, ground_truth

def read_history(limit=20):
    entries = []
    if not os.path.exists(HISTORY_FILE):
        return entries
    try:
        with open(HISTORY_FILE, "r") as f:
            lines = f.readlines()
            for line in lines[-limit:]:
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
    except Exception as e:
        print(f"Error reading history: {e}")
    return entries

def run_validation(nodes, edges, fault_info, history_entries):
    report = {
        "timestamp": json.dumps(time.strftime("%Y-%m-%dT%H:%M:%SZ"))[1:-1],
        "validation_passed": True,
        "metrics_validation": {},
        "graph_validation": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "disconnected_nodes": [],
            "duplicate_nodes": False
        },
        "fault_impact_validation": {
            "fault_active": fault_info.get("active", False),
            "deviation_detected": True,
            "details": ""
        }
    }
    
    # 1. Structural Graph Validation
    node_ids = [n["service_id"] for n in nodes]
    if len(node_ids) != len(set(node_ids)):
        report["graph_validation"]["duplicate_nodes"] = True
        report["validation_passed"] = False
        
    connected_nodes = set()
    for edge in edges:
        connected_nodes.add(edge["source"])
        connected_nodes.add(edge["target"])
        
    disconnected = [n for n in node_ids if n not in connected_nodes]
    report["graph_validation"]["disconnected_nodes"] = disconnected
    if len(disconnected) > 0:
        report["validation_passed"] = False

    # 2. History-based Metrics Validation (Spearman Rank Check)
    if len(history_entries) >= 5:
        for node in nodes:
            service = node["service_id"]
            # Extract historical timeseries for this service
            cpu_history = []
            lat_history = []
            err_history = []
            p99_history = []
            
            for entry in history_entries:
                srv_metrics = entry.get("metrics", {}).get(service, {})
                if srv_metrics:
                    cpu_history.append(srv_metrics.get("cpu_pct", 0.0))
                    lat_history.append(srv_metrics.get("mean_latency_ms", 0.0))
                    err_history.append(srv_metrics.get("error_rate", 0.0))
                    p99_history.append(srv_metrics.get("p99_latency_ms", 0.0))
            
            # Filter out any history samples that contain None
            valid_cpu_lat = [(c, l) for c, l in zip(cpu_history, lat_history) if c is not None and l is not None]
            valid_err_p99 = [(e, p) for e, p in zip(err_history, p99_history) if e is not None and p is not None]
            
            cpu_flatlined = len(set(c for c, _ in valid_cpu_lat)) <= 1 if len(valid_cpu_lat) > 0 else True
            lat_flatlined = len(set(l for _, l in valid_cpu_lat)) <= 1 if len(valid_cpu_lat) > 0 else True
            
            metrics_flatlined = cpu_flatlined and lat_flatlined
            
            # Spearman Rank calculation
            cpu_vs_lat_corr = 0.0
            err_vs_p99_corr = 0.0
            
            if 'scipy' in sys.modules and len(valid_cpu_lat) >= 5 and not cpu_flatlined and not lat_flatlined:
                try:
                    cpu_vs_lat_corr, _ = scipy.stats.spearmanr(
                        [c for c, _ in valid_cpu_lat],
                        [l for _, l in valid_cpu_lat]
                    )
                    
                    err_flat = len(set(e for e, _ in valid_err_p99)) <= 1 if len(valid_err_p99) > 0 else True
                    p99_flat = len(set(p for _, p in valid_err_p99)) <= 1 if len(valid_err_p99) > 0 else True
                    
                    if len(valid_err_p99) >= 5 and not err_flat and not p99_flat:
                        err_vs_p99_corr, _ = scipy.stats.spearmanr(
                            [e for e, _ in valid_err_p99],
                            [p for _, p in valid_err_p99]
                        )
                except Exception:
                    pass
                    
            report["metrics_validation"][service] = {
                "cpu_vs_latency_spearman": round(float(cpu_vs_lat_corr) if not cpu_flatlined else 0.0, 3),
                "cpu_vs_latency_insufficient_samples": len(valid_cpu_lat) < 5,
                "errors_vs_p99_spearman": round(float(err_vs_p99_corr) if len(valid_err_p99) >= 5 and not (len(set(e for e, _ in valid_err_p99)) <= 1 or len(set(p for _, p in valid_err_p99)) <= 1) else 0.0, 3),
                "errors_vs_p99_insufficient_samples": len(valid_err_p99) < 5,
                "metrics_flatlined": metrics_flatlined
            }
            
            # Fail if metrics are flatlined for an app service
            if metrics_flatlined and service in [n["service_id"] for n in nodes if n["cpu_pct"] > 0]:
                report["validation_passed"] = False
    else:
        report["validation_passed"] = False
        print("Skipping Spearman correlation check: history window is too short (< 5 entries).")

    # 3. Targeted Fault Impact & Unlabeled Anomaly Validation
    active_fault = fault_info.get("active", False)
    target_service = fault_info.get("target_service", "")
    fault_type = fault_info.get("fault_type", "")
    
    anomalous_services = []
    
    # Analyze all services for deviations relative to their history baselines
    for node in nodes:
        service = node["service_id"]
        # Skip infra / edge services that don't collect real telemetry
        if service in ["frontend", "api-gateway", "cache", "postgres-primary", "postgres-replica"]:
            continue
            
        current_lat = node.get("mean_latency_ms")
        current_cpu = node.get("cpu_pct")
        current_err = node.get("error_rate")
        
        # Calculate baseline from history
        lats = []
        cpus = []
        for entry in history_entries:
            m = entry.get("metrics", {}).get(service, {})
            if m:
                # Filter out None values in baseline calculation
                h_lat = m.get("mean_latency_ms")
                h_cpu = m.get("cpu_pct")
                if h_lat is not None:
                    lats.append(h_lat)
                if h_cpu is not None:
                    cpus.append(h_cpu)
                
        base_lat = sum(lats) / len(lats) if len(lats) > 0 else 5.0
        base_cpu = sum(cpus) / len(cpus) if len(cpus) > 0 else 0.02
        
        is_anomalous = False
        reasons = []
        
        if current_lat is None or current_cpu is None:
            is_anomalous = True
            reasons.append("telemetry scraping timeout (unresponsive container)")
        else:
            # Latency anomaly: spike > 5x and current latency > 50ms
            if current_lat > base_lat * 5.0 and current_lat > 50.0:
                is_anomalous = True
                reasons.append(f"latency spike ({current_lat}ms vs baseline {round(base_lat, 1)}ms)")
                
            # CPU anomaly: spike > 0.4 above baseline
            if current_cpu > base_cpu + 0.4:
                is_anomalous = True
                reasons.append(f"CPU stress ({round(current_cpu, 2)} vs baseline {round(base_cpu, 2)})")
                
            # Error anomaly: error rate > 10%
            if current_err is not None and current_err > 0.1:
                is_anomalous = True
                reasons.append(f"high error rate ({round(current_err, 2)})")
            
        if is_anomalous:
            anomalous_services.append((service, ", ".join(reasons)))
            
    # Now reconcile anomalies with label status
    report["fault_impact_validation"]["fault_active"] = active_fault
    
    if active_fault:
        report["fault_impact_validation"]["target_service"] = target_service
        # Verify the target service is indeed showing an anomaly
        is_target_anomalous = any(s[0] == target_service for s in anomalous_services)
        
        if not is_target_anomalous:
            # Special check for pod_crash: node might have 0 metrics
            target_node = next((n for n in nodes if n["service_id"] == target_service), None)
            if fault_type == "pod_crash" and target_node and target_node.get("cpu_pct", 0.0) == 0.0 and target_node.get("mean_latency_ms", 0.0) == 0.0:
                report["fault_impact_validation"]["deviation_detected"] = True
                report["fault_impact_validation"]["details"] = f"Pod crash successfully detected: target {target_service} shows flatlined metrics."
            else:
                report["fault_impact_validation"]["deviation_detected"] = False
                report["fault_impact_validation"]["details"] = f"Fault active on {target_service} ({fault_type}) but no significant telemetry deviation detected on target."
                report["validation_passed"] = False
        else:
            report["fault_impact_validation"]["deviation_detected"] = True
            anomaly_details = next(s[1] for s in anomalous_services if s[0] == target_service)
            report["fault_impact_validation"]["details"] = f"Fault active on {target_service} and deviation confirmed: {anomaly_details}."
    else:
        # No fault active
        if len(anomalous_services) > 0:
            report["fault_impact_validation"]["deviation_detected"] = True
            details_list = [f"{s[0]} showed {s[1]}" for s in anomalous_services]
            report["fault_impact_validation"]["details"] = "; ".join(details_list) + " with no matching active or recently-expired fault."
            # Fail validation due to unlabeled anomaly!
            report["validation_passed"] = False
        else:
            report["fault_impact_validation"]["deviation_detected"] = False
            report["fault_impact_validation"]["details"] = "No anomalies detected and no fault is active."
            
    return report

def export_data(experiment_id, dataset_version, validate_flag):
    config = load_services()
    if not config:
        return
        
    out_dir = f"datasets/experiment_{experiment_id}" if experiment_id else "."
    out_file = os.path.join(out_dir, OUTPUT_FILE)
    rep_file = os.path.join(out_dir, REPORT_FILE)
    
    # Query fault status first
    fault_info, ground_truth = query_active_fault(config, out_file)
    
    # Assert ground-truth root cause is set before writing if fault is active
    if fault_info["active"] and not ground_truth:
        print("ERROR: Active fault detected, but ground_truth_root_cause is empty! Refusing to export.")
        return
        
    # Determine lookback based on fault state
    lookback = 2 if fault_info["active"] else 10
    
    # Collect telemetry
    nodes, edges = export_metrics.collect_all_telemetry(config, lookback)
    
    # Decoupled Grace-Period verification:
    # Retain the fault label only if the target service still exhibits deviation from baseline
    if fault_info.get("grace_period") and fault_info.get("active"):
        target_service = fault_info.get("target_service")
        target_node = next((n for n in nodes if n["service_id"] == target_service), None)
        
        target_exhibits_symptoms = False
        if target_node:
            current_lat = target_node.get("mean_latency_ms")
            current_cpu = target_node.get("cpu_pct")
            current_err = target_node.get("error_rate")
            
            history_entries = read_history()
            lats = []
            cpus = []
            for entry in history_entries:
                m = entry.get("metrics", {}).get(target_service, {})
                if m:
                    h_lat = m.get("mean_latency_ms")
                    h_cpu = m.get("cpu_pct")
                    if h_lat is not None:
                        lats.append(h_lat)
                    if h_cpu is not None:
                        cpus.append(h_cpu)
            base_lat = sum(lats) / len(lats) if len(lats) > 0 else 5.0
            base_cpu = sum(cpus) / len(cpus) if len(cpus) > 0 else 0.02
            
            # Anomaly criteria matching run_validation (including failed scrapes)
            if current_lat is None or current_cpu is None:
                target_exhibits_symptoms = True
            elif (current_lat > base_lat * 5.0 and current_lat > 50.0) or \
                 (current_cpu > base_cpu + 0.4) or \
                 (current_err is not None and current_err > 0.1):
                target_exhibits_symptoms = True
                
        if not target_exhibits_symptoms:
            print(f"Grace-period label for {target_service} cleared because target service has recovered to baseline.")
            fault_info = {
                "active": False,
                "fault_type": "",
                "target_service": "",
                "injected_at": "",
                "scheduled_duration_sec": 0,
                "auto_rollback": True
            }
            ground_truth = ""
    
    payload = {
        "schema_version": "1.0",
        "dataset_version": dataset_version,
        "experiment_id": experiment_id,
        "timestamp": json.dumps(time.strftime("%Y-%m-%dT%H:%M:%SZ"))[1:-1],
        "nodes": nodes,
        "edges": edges,
        "fault_injection": fault_info,
        "ground_truth_root_cause": ground_truth
    }
    
    # Output directory setup
    if out_dir != "." and not os.path.exists(out_dir):
        os.makedirs(out_dir)
    
    # Write Payload
    try:
        with open(out_file, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"GNN payload successfully exported to {out_file}")
    except Exception as e:
        print(f"Error writing GNN payload: {e}")
        
    # Write Validation Report
    if validate_flag:
        history_entries = read_history(20)
        report = run_validation(nodes, edges, fault_info, history_entries)
        try:
            with open(rep_file, "w") as f:
                json.dump(report, f, indent=2)
            print(f"Validation report successfully written to {rep_file}")
            if not report["validation_passed"]:
                print("WARNING: Telemetry validation checks failed! Check validation_report.json for details.")
        except Exception as e:
            print(f"Error writing validation report: {e}")
            
    return fault_info["active"]

def main():
    parser = argparse.ArgumentParser(description="ShopMind Telemetry Exporter")
    parser.add_argument("--watch", action="store_true", help="Run continuously in a loop")
    parser.add_argument("--experiment-id", type=str, default="", help="Experiment iteration ID")
    parser.add_argument("--dataset-version", type=str, default="2026.07", help="Dataset version label")
    parser.add_argument("--validate", action="store_true", help="Perform metrics and structural validation checks")
    args = parser.parse_args()
    
    if args.watch:
        print("Running in watch mode. Press Ctrl+C to stop.")
        while True:
            try:
                is_active_fault = export_data(args.experiment_id, args.dataset_version, args.validate)
                # Adaptive polling interval: 1s during fault, 10s during idle baseline
                sleep_sec = 1 if is_active_fault else 10
                time.sleep(sleep_sec)
            except KeyboardInterrupt:
                print("\nWatch loop stopped.")
                break
            except Exception as e:
                print(f"Exporter error: {e}")
                time.sleep(10)
    else:
        export_data(args.experiment_id, args.dataset_version, args.validate)

if __name__ == "__main__":
    main()
