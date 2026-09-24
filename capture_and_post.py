"""
capture_and_post.py -- adapts a captured incident directory
(telemetry_series.json, from live_inject_and_capture.py) into a POST to
multi_instance_receiver.py, tagged with instance_id. Without this, a
given instance's live capture stays local and never reaches the global
cross-instance queue.
"""

import argparse
import json
import os
from pathlib import Path

import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--incident-dir", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--receiver-url", default="http://localhost:5001/telemetry")
    args = parser.parse_args()

    telemetry_path = Path(args.incident_dir) / "telemetry_series.json"
    if not telemetry_path.exists():
        raise FileNotFoundError(f"Expected {telemetry_path}")

    with open(telemetry_path) as f:
        telemetry = json.load(f)

    telemetry["instance_id"] = args.instance_id

    token = os.environ.get("IM_RECEIVER_TOKEN")
    headers = {"X-IM-Token": token} if token else {}
    resp = requests.post(args.receiver_url, json=telemetry, headers=headers)
    resp.raise_for_status()
    print(f"Posted {args.incident_dir} as instance_id={args.instance_id}")
    print(resp.json())


if __name__ == "__main__":
    main()
