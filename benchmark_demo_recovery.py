#!/usr/bin/env python3
"""
Benchmark Demo Recovery Timings
Runs each fault type through demo_workflow programmatically and records empirical settle durations.
"""

import sys
import time
from demo_workflow import run_demo, FAULT_PRESETS

def main():
    print("\n" + "=" * 75)
    print("       SHOPMIND EMPIRICAL DEMO RECOVERY BENCHMARK (ALL FAULT TYPES)")
    print("=" * 75)

    results = []

    for key in sorted(FAULT_PRESETS.keys()):
        preset = FAULT_PRESETS[key]
        print(f"\n>>> Running Benchmark for Scenario {key}: {preset['name']}...")
        t0 = time.time()
        ok, settle_sec = run_demo(fault_key=key, non_interactive=True)
        total_test_time = time.time() - t0

        results.append({
            "key": key,
            "name": preset["name"],
            "target": preset["target"],
            "category": preset["category"],
            "settle_sec": settle_sec,
            "total_sec": total_test_time,
            "success": ok
        })
        time.sleep(2) # Brief cooldown between benchmark runs

    print("\n" + "=" * 75)
    print("               EMPIRICAL RECOVERY BENCHMARK RESULTS TABLE")
    print("=" * 75)
    print(f"{'Preset':<7} | {'Fault Scenario':<30} | {'Target':<18} | {'Settle (s)':<10} | {'Status'}")
    print("-" * 75)
    for r in results:
        status = "PASSED" if r["success"] else "FAILED"
        print(f"{r['key']:<7} | {r['name']:<30} | {r['target']:<18} | {r['settle_sec']:<10.2f} | {status}")
    print("=" * 75 + "\n")

    all_passed = all(r["success"] for r in results)
    if all_passed:
        print("✓ All 4 demo scenarios benchmarked and verified successfully!")
        sys.exit(0)
    else:
        print("! One or more demo scenarios failed settling verification.")
        sys.exit(1)

if __name__ == "__main__":
    main()
