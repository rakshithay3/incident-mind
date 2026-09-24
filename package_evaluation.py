import os
import json
import zipfile
import shutil

DATASETS_DIR = "datasets"
COMPILED_DIR = "datasets_compiled"
# Written to a NEW name so the original (target-aware) frozen set in
# shopmind_evaluation_dataset.zip stays available for before/after numbers.
ZIP_OUTPUT = "shopmind_evaluation_dataset_labelfree.zip"
SCHEDULE_FILE = "evaluation_schedule.json"

# UNIT FIX (see diagnose_feature_scale.py results, Sept 2026):
# ShopMind's exported units did not match RCAEval RE1's units, which silently
# collapsed GNN scoring on ShopMind (PR@1 dropped from 0.92 on RE1 to 0.16 on
# ShopMind). RE1's raw ranges (observed empirically from RCAEval RE1-OB):
#   cpu:     0.24 - 97.0   -> percent (0-100 scale)
#   latency: 0    - 9.9    -> seconds
#   memory:  raw bytes     -> container_memory_usage_bytes
# ShopMind was exporting:
#   cpu_pct:         0 - 1        -> fraction (0-1 scale), needs x100
#   mean_latency_ms: 0 - 2001     -> milliseconds, needs /1000
#   mem_pct:         0 - 1        -> ratio, reconstructed as mem_pct * mem_limit_bytes
# Unit conversion, peak-snapshot selection and crash encoding all live in
# shopmind_snapshot.py so the benchmark, replay_demo.py and live_demo.py
# share one label-free implementation (see that module's docstring for why
# the previous target-aware version here was replaced).
from shopmind_snapshot import (  # noqa: E402
    CPU_RATIO_TO_PERCENT,
    DEFAULT_MEM_LIMIT_BYTES,
    MS_TO_SECONDS,
    SERVICE_MEM_LIMIT_BYTES,
    baseline_averages as get_baseline_averages,
    compile_telemetry,
)


def compile_incident(inc_dir):
    series_path = os.path.join(inc_dir, "telemetry_series.json")
    if not os.path.exists(series_path):
        return None
    with open(series_path, "r") as f:
        data = json.load(f)
    return compile_telemetry(data)

def main():
    import argparse
    global DATASETS_DIR, ZIP_OUTPUT
    parser = argparse.ArgumentParser(description="Compile raw ShopMind incidents into the GNN evaluation set")
    parser.add_argument("--datasets-dir", default=DATASETS_DIR, help="folder of incident_*/telemetry_series.json")
    parser.add_argument("--zip-output", default=ZIP_OUTPUT)
    args = parser.parse_args()
    DATASETS_DIR, ZIP_OUTPUT = args.datasets_dir, args.zip_output

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
