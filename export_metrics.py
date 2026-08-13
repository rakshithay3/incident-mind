import urllib.request
import json
import re
import time
import sys

SERVICES_FILE = "services.json"
HISTORY_FILE = "metrics_history.jsonl"
JAEGER_URL = "http://localhost:16686"

def load_services():
    try:
        with open(SERVICES_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {SERVICES_FILE}: {e}")
        sys.exit(1)

def http_get_json(url):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None

def http_get_raw(url):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.read().decode("utf-8")
    except Exception:
        return None

def get_direct_metrics(host, port):
    url = f"http://{host}:{port}/metrics"
    metrics_text = http_get_raw(url)
    if metrics_text is None:
        return None, None
        
    cpu_pct = 0.0
    mem_pct = 0.0
    
    cpu_match = re.search(r'process_cpu_usage_ratio\s+([\d\.]+)', metrics_text)
    if cpu_match:
        cpu_pct = float(cpu_match.group(1))
    mem_match = re.search(r'process_memory_usage_ratio\s+([\d\.]+)', metrics_text)
    if mem_match:
        mem_pct = float(mem_match.group(1))
            
    return cpu_pct, mem_pct

def get_jaeger_metrics(service_id, lookback_sec=10):
    end_time_us = int(time.time() * 1000000)
    start_time_us = end_time_us - (lookback_sec * 1000000)
    url = f"{JAEGER_URL}/api/traces?service={service_id}&start={start_time_us}&end={end_time_us}"
    traces_data = http_get_json(url)
    
    total_spans = 0
    error_spans = 0
    sum_duration = 0.0
    durations = []
    entrypoint_calls = 0
    
    if traces_data and "data" in traces_data:
        for trace in traces_data["data"]:
            spans = trace.get("spans", [])
            processes = trace.get("processes", {})
            
            for span in spans:
                process_id = span.get("processID")
                proc = processes.get(process_id, {})
                
                if proc.get("serviceName") == service_id:
                    total_spans += 1
                    duration_ms = span.get("duration", 0) / 1000.0
                    sum_duration += duration_ms;
                    durations.append(duration_ms)
                    
                    # Check for errors in status code or tags
                    span_status = span.get("status", {})
                    is_error = False
                    if span_status.get("code") in [2, "2", "ERROR", "STATUS_CODE_ERROR"]:
                        is_error = True
                    else:
                        tags = span.get("tags", [])
                        for tag in tags:
                            key = tag.get("key")
                            val = tag.get("value")
                            if key == "error" and (val is True or val == "true"):
                                is_error = True
                                break
                            if key == "otel.status_code" and val == "ERROR":
                                is_error = True
                                break
                            
                    if is_error:
                        error_spans += 1
                        
                    # Check if top-level entrypoint span
                    op_name = span.get("operationName", "")
                    is_metrics_or_health = "metrics" in op_name or "health" in op_name or "fault-status" in op_name
                    references = span.get("references", [])
                    has_parent = len(references) > 0
                    
                    if not has_parent and not is_metrics_or_health:
                        entrypoint_calls += 1
                        
    mean_latency = 0.0
    p99_latency = 0.0
    error_rate = 0.0
    
    if total_spans > 0:
        mean_latency = sum_duration / total_spans
        error_rate = error_spans / total_spans
        durations.sort()
        p99_idx = int(len(durations) * 0.99)
        p99_latency = durations[min(p99_idx, len(durations) - 1)]
        
    return mean_latency, p99_latency, error_rate, entrypoint_calls

def collect_all_telemetry(services_config, lookback_sec=10):
    timestamp = json.dumps(time.strftime("%Y-%m-%dT%H:%M:%SZ"))[1:-1]
    nodes = []
    node_telemetry_cache = {}
    
    # 1. Scrape App Node Metrics
    for name, cfg in services_config.items():
        if cfg.get("role") == "app":
            cpu, mem = get_direct_metrics(cfg["host"], cfg["port"])
            mean_lat, p99_lat, err_rate, entry_calls = get_jaeger_metrics(name, lookback_sec)
            
            nodes.append({
                "service_id": name,
                "cpu_pct": round(cpu, 4) if cpu is not None else None,
                "mem_pct": round(mem, 4) if mem is not None else None,
                "error_rate": round(err_rate, 4),
                "mean_latency_ms": round(mean_lat, 2),
                "p99_latency_ms": round(p99_lat, 2),
                "timestamp": timestamp
            })
            node_telemetry_cache[name] = entry_calls
        else:
            # Non-app nodes (edge/infra) have default zero metrics but are still represented
            nodes.append({
                "service_id": name,
                "cpu_pct": 0.0,
                "mem_pct": 0.0,
                "error_rate": 0.0,
                "mean_latency_ms": 0.0,
                "p99_latency_ms": 0.0,
                "timestamp": timestamp
            })
            node_telemetry_cache[name] = 0

    # 2. Query Jaeger Dependencies & overlay static edges
    # Standard GNN edge list mapping out all 12 services
    static_edges = [
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
        ("postgres-primary", "postgres-replica")
    ]
    
    # Scrape Jaeger dynamic call dependencies
    dep_calls = {}
    dep_url = f"{JAEGER_URL}/api/dependencies?endTs={int(time.time()*1000)}&lookback={lookback_sec * 1000}"
    dependencies = http_get_json(dep_url)
    if dependencies and "data" in dependencies:
        for link in dependencies["data"]:
            parent = link.get("parent")
            child = link.get("child")
            call_count = link.get("callCount", 0)
            if parent and child:
                dep_calls[(parent, child)] = call_count
                
    edges = []
    for src, tgt in static_edges:
        count = 0
        if src == "api-gateway":
            # Gateway calls correspond to entrypoint calls of target app service
            count = node_telemetry_cache.get(tgt, 0)
        elif src == "frontend" and tgt == "api-gateway":
            # Frontend calls sum up all gateway entries
            count = sum(node_telemetry_cache.get(name, 0) for name, cfg in services_config.items() if cfg.get("role") == "app")
        else:
            count = dep_calls.get((src, tgt), 0)
            
        edges.append({
            "source": src,
            "target": tgt,
            "call_count": count,
            "timestamp": timestamp
        })
        
    # 3. Log to history file
    history_entry = {
        "timestamp": timestamp,
        "metrics": {n["service_id"]: n for n in nodes if n["service_id"] in node_telemetry_cache}
    }
    try:
        import os
        lines = []
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r") as r_hf:
                lines = r_hf.readlines()
        if len(lines) > 2000:
            temp_file = HISTORY_FILE + ".tmp"
            with open(temp_file, "w") as w_hf:
                w_hf.writelines(lines[-1000:])
            os.replace(temp_file, HISTORY_FILE)
            
        with open(HISTORY_FILE, "a") as hf:
            hf.write(json.dumps(history_entry) + "\n")
    except Exception as e:
        print(f"Error logging to history: {e}")

    return nodes, edges

if __name__ == "__main__":
    # Test execution
    config = load_services()
    nodes, edges = collect_all_telemetry(config, 10)
    print(f"Collected {len(nodes)} nodes and {len(edges)} edges.")
