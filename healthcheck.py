import urllib.request
import json
import time
import os
import sys

SERVICES_FILE = "services.json"
UPTIME_LOG = "uptime_log.jsonl"

RESTARTS_FILE = "datasets/restart_counts.json"

def load_services():
    try:
        with open(SERVICES_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {SERVICES_FILE}: {e}")
        return {}

def load_restart_counts():
    if os.path.exists(RESTARTS_FILE):
        try:
            with open(RESTARTS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_restart_counts(counts):
    try:
        os.makedirs(os.path.dirname(RESTARTS_FILE), exist_ok=True)
        with open(RESTARTS_FILE, "w") as f:
            json.dump(counts, f)
    except Exception as e:
        print(f"Failed to save restart counts: {e}")

def log_event(service_name, status, error_msg="", downtime_sec=0, restart_count=0):
    timestamp = json.dumps(time.strftime("%Y-%m-%dT%H:%M:%SZ"))[1:-1]
    entry = {
        "timestamp": timestamp,
        "service": service_name,
        "status": status
    }
    if error_msg:
        entry["error"] = error_msg
    if status == "up" and downtime_sec > 0:
        entry["downtime_duration_sec"] = downtime_sec
    if status == "up":
        entry["restart_count"] = restart_count
        
    try:
        with open(UPTIME_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
        print(f"Logged uptime event: {service_name} is {status}. (Downtime: {downtime_sec}s, Restarts: {restart_count})")
    except Exception as e:
        print(f"Failed to write to uptime log: {e}")

def monitor():
    services = load_services()
    if not services:
        return
        
    # Track state: True for UP, False for DOWN
    state = {}
    down_since = {}
    restart_counts = load_restart_counts()
    
    for name, cfg in services.items():
        if cfg.get("role") == "app":
            state[name] = True # Assume up initially
            if name not in restart_counts:
                restart_counts[name] = 0
            
    print("Starting uptime monitor poll loop (every 30s)...")
    while True:
        try:
            for name, cfg in services.items():
                if cfg.get("role") != "app":
                    continue
                    
                url = f"http://{cfg['host']}:{cfg['port']}/health"
                is_up = False
                error_msg = ""
                
                try:
                    req = urllib.request.Request(url)
                    with urllib.request.urlopen(req, timeout=3) as res:
                        if res.status == 200:
                            is_up = True
                        else:
                            error_msg = f"HTTP {res.status}"
                except Exception as e:
                    error_msg = str(e)
                    
                prev_state = state.get(name, True)
                if is_up != prev_state:
                    # State changed!
                    downtime = 0
                    if is_up:
                        # Recovered!
                        t_down = down_since.pop(name, None)
                        if t_down:
                            downtime = int(time.time() - t_down)
                        restart_counts[name] = restart_counts.get(name, 0) + 1
                        save_restart_counts(restart_counts)
                        log_event(name, "up", "Recovered", downtime, restart_counts[name])
                    else:
                        # Went down!
                        down_since[name] = time.time()
                        log_event(name, "down", error_msg)
                        
                    state[name] = is_up
                    
        except Exception as e:
            print(f"Monitor error: {e}")
            
        time.sleep(30)

if __name__ == "__main__":
    try:
        monitor()
    except KeyboardInterrupt:
        print("\nUptime monitor stopped.")
