import urllib.request
import json
import sys

SERVICES_FILE = "services.json"

def main():
    try:
        with open(SERVICES_FILE, "r") as f:
            services = json.load(f)
    except Exception as e:
        print(f"Error loading {SERVICES_FILE}: {e}")
        sys.exit(1)
        
    print("Resetting all application services...")
    for name, cfg in services.items():
        if cfg.get("role") == "app":
            url = f"http://{cfg['host']}:{cfg['port']}/api/reset"
            try:
                req = urllib.request.Request(url, method="POST")
                with urllib.request.urlopen(req, timeout=3) as res:
                    print(f"Successfully reset {name}: {res.read().decode('utf-8').strip()}")
            except Exception as e:
                print(f"Failed to reset {name}: {e}")
                
    # Wipe the global fault cache file on clean reset
    import os
    global_fault_file = "datasets/last_active_fault.json"
    if os.path.exists(global_fault_file):
        try:
            os.remove(global_fault_file)
            print("Successfully deleted global fault cache file.")
        except Exception as e:
            print(f"Failed to delete global fault cache: {e}")

if __name__ == "__main__":
    main()
