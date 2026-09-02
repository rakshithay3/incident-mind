import urllib.request
import json
import sys
import os
import time
import subprocess

SERVICES_FILE = "services.json"
GLOBAL_FAULT_FILE = "datasets/last_active_fault.json"

def load_services():
    try:
        with open(SERVICES_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {SERVICES_FILE}: {e}")
        sys.exit(1)

def check_service_health(host, port, timeout=2):
    """Pings /health endpoint. Returns True if HTTP 200, False otherwise."""
    url = f"http://{host}:{port}/health"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status == 200
    except Exception:
        return False

def reset_service_endpoint(host, port, timeout=3):
    """Sends POST to /reset endpoint to clear fault injectors and counters."""
    url = f"http://{host}:{port}/reset"
    try:
        req = urllib.request.Request(url, method="POST", data=b"{}")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return True, res.read().decode('utf-8').strip()
    except Exception as e:
        return False, str(e)

def restart_container_host(service_name):
    """Host-level recovery: restarts container via docker compose if process crashed."""
    container_name = f"shopmind-{service_name}"
    print(f"  [HOST RECOVERY] Attempting docker compose restart for {container_name}...")
    try:
        cmd = ["docker", "restart", container_name]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if res.returncode == 0:
            print(f"  [HOST RECOVERY] Successfully restarted {container_name} via docker restart.")
            return True
        else:
            print(f"  [HOST RECOVERY] docker restart returned code {res.returncode}: {res.stderr.strip()}")
            return False
    except Exception as e:
        print(f"  [HOST RECOVERY] Failed to execute docker compose restart: {e}")
        return False

def emergency_rollback(services_config=None):
    """Performs an emergency reset and verification across all application microservices."""
    start_time = time.time()
    if services_config is None:
        services_config = load_services()

    app_services = {name: cfg for name, cfg in services_config.items() if cfg.get("role") == "app"}
    print(f"\n========================================================")
    print(f"  SHOPMIND EMERGENCY ROLLBACK — RESETTING CLUSTER")
    print(f"========================================================")

    # 1. First pass: send /reset to all accessible services
    unresponsive = []
    for name, cfg in app_services.items():
        ok, msg = reset_service_endpoint(cfg["host"], cfg["port"])
        if ok:
            print(f"  [RESET OK] {name:<22} -> State cleared")
        else:
            print(f"  [RESET FAIL] {name:<20} -> Unresponsive ({msg})")
            unresponsive.append((name, cfg))

    # 2. Host-level Docker restart fallback for crashed containers (e.g. pod_crash)
    if unresponsive:
        print(f"\nDetected {len(unresponsive)} unresponsive service(s). Initiating host-level container restart...")
        for name, cfg in unresponsive:
            restart_container_host(name)

    # 3. Health verification loop with 15s deadline
    print("\nVerifying cluster health across all microservices...")
    deadline = time.time() + 15
    all_healthy = False

    while time.time() < deadline:
        statuses = {}
        for name, cfg in app_services.items():
            statuses[name] = check_service_health(cfg["host"], cfg["port"], timeout=1)

        if all(statuses.values()):
            all_healthy = True
            break
        time.sleep(1)

    # 4. Wipe global fault cache file
    if os.path.exists(GLOBAL_FAULT_FILE):
        try:
            os.remove(GLOBAL_FAULT_FILE)
            print("  [CACHE] Deleted global fault cache file.")
        except Exception as e:
            print(f"  [CACHE] Failed to delete global fault cache: {e}")

    elapsed = time.time() - start_time
    print("--------------------------------------------------------")
    if all_healthy:
        print(f"  CLUSTER STATUS: ALL 7 APP SERVICES HEALTHY & VERIFIED")
        print(f"  Emergency rollback completed in {elapsed:.2f}s")
        print("========================================================\n")
        return True
    else:
        failed_services = [n for n, h in statuses.items() if not h]
        print(f"  WARNING: {len(failed_services)} service(s) still unhealthy: {failed_services}")
        print(f"  Rollback aborted after {elapsed:.2f}s")
        print("========================================================\n")
        return False

def main():
    success = emergency_rollback()
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
