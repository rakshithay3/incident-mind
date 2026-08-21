"""Download RCAEval RE1 (Online Boutique) and convert it into incidentmind_p1
incident JSON files.

Local / VS Code equivalent of notebook cells 39-40. Run once before
scripts/train_and_evaluate.py.

Usage:
    python scripts/prepare_re1_data.py

Requires: git available on PATH, and the RCAEval repo cloned locally (this
script clones it into ./RCAEval_src if not already present) because
`pip install RCAEval` is broken upstream (see docs/data_contract.md / project
notes: packages=["RCAEval"] in their setup.py silently drops subpackages).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RCAEVAL_SRC = ROOT / "RCAEval_src"
OB_ROOT = ROOT / "data" / "RE1" / "RE1-OB"
OUTPUT_DIR = ROOT / "data" / "rcaeval_re1" / "incidents"

ONLINE_BOUTIQUE_EDGES = [
    ("frontend", "adservice"), ("frontend", "cartservice"),
    ("frontend", "checkoutservice"), ("frontend", "currencyservice"),
    ("frontend", "productcatalogservice"), ("frontend", "recommendationservice"),
    ("frontend", "shippingservice"),
    ("checkoutservice", "cartservice"), ("checkoutservice", "currencyservice"),
    ("checkoutservice", "emailservice"), ("checkoutservice", "paymentservice"),
    ("checkoutservice", "productcatalogservice"), ("checkoutservice", "shippingservice"),
    ("recommendationservice", "productcatalogservice"),
    ("cartservice", "redis"),
]
KNOWN_SERVICES = {s for edge in ONLINE_BOUTIQUE_EDGES for s in edge}
FAULT_TYPES = ("cpu", "mem", "disk", "delay", "loss")


def ensure_rcaeval_src() -> None:
    """Clone RCAEval source if not already present, and put it on sys.path.

    pip install of RCAEval silently fails to install subpackages, so we work
    from a shallow git clone instead (see project memory / docs).
    """
    if not RCAEVAL_SRC.exists():
        print(f"Cloning RCAEval into {RCAEVAL_SRC} ...")
        subprocess.run(
            ["git", "clone", "--depth", "1", "https://github.com/phamquiluan/RCAEval.git", str(RCAEVAL_SRC)],
            check=True,
        )
    else:
        print(f"RCAEval source already present at {RCAEVAL_SRC}, skipping clone.")

    sys.path.insert(0, str(RCAEVAL_SRC))

    # Defensive: clear any stale partially-imported RCAEval modules before
    # importing fresh from the cloned source (see project memory notes).
    for mod in list(sys.modules):
        if mod == "RCAEval" or mod.startswith("RCAEval."):
            del sys.modules[mod]


def download_dataset() -> None:
    from RCAEval.utility import download_re1_dataset  # noqa: E402

    print("Downloading RE1 dataset (RE1-OB, RE1-SS, RE1-TT) ...")
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    prev_cwd = Path.cwd()
    try:
        import os
        os.chdir(ROOT)
        download_re1_dataset()
    finally:
        import os
        os.chdir(prev_cwd)


def find_ob_cases(root: Path = OB_ROOT):
    """{service}_{fault}/{instance}/data.csv"""
    cases = []
    for combo_dir in sorted(root.iterdir()):
        if not combo_dir.is_dir():
            continue
        if not any(svc in combo_dir.name for svc in KNOWN_SERVICES):
            continue
        if not any(f"_{ft}" in combo_dir.name for ft in FAULT_TYPES):
            continue
        for instance_dir in sorted(combo_dir.iterdir()):
            if instance_dir.is_dir() and (instance_dir / "data.csv").exists():
                cases.append(instance_dir)
    return cases


def peek_schema(n: int = 1) -> None:
    from RCAEval.utility import read_data  # noqa: E402

    cases = find_ob_cases()
    print(f"found {len(cases)} real OB case dirs (expect ~125)")
    for case_dir in cases[:n]:
        print(f"--- {case_dir} ---")
        df = read_data(str(case_dir / "data.csv"))
        cols = list(df.columns)
        print(" columns:", cols[:20], "..." if len(cols) > 20 else "")
        print(" rows:", len(df))
        inject_path = case_dir / "inject_time.txt"
        if inject_path.exists():
            print(" inject_time:", inject_path.read_text().strip())


def parse_root_cause(case_dir: Path) -> tuple[str | None, str | None]:
    combo_name = case_dir.parent.name  # e.g. "currencyservice_mem"
    service = next((s for s in KNOWN_SERVICES if s in combo_name), None)
    fault = next((f for f in FAULT_TYPES if f"_{f}" in combo_name or combo_name.endswith(f)), None)
    return service, fault


def extract_service_snapshot(df, service: str) -> dict:
    features = {"cpu": 0.0, "memory": 0.0, "latency": 0.0, "error_rate": 0.0, "p99_latency": 0.0}
    for feat, suffix in [("cpu", "cpu"), ("memory", "mem")]:
        col = f"{service}_{suffix}"
        if col in df.columns:
            features[feat] = float(df[col].mean())
    lat_col = f"{service}_latency"  # read_data() already renamed _latency-90 -> _latency
    if lat_col in df.columns:
        features["latency"] = float(df[lat_col].mean())
        features["p99_latency"] = float(df[lat_col].quantile(0.99))
    return features


def convert_case(case_dir: Path) -> dict | None:
    from RCAEval.utility import read_data  # noqa: E402

    df = read_data(str(case_dir / "data.csv"))

    root_cause, fault_type = parse_root_cause(case_dir)
    if root_cause is None or root_cause not in KNOWN_SERVICES:
        print(f"  WARNING: couldn't resolve root_cause for {case_dir}, skipping")
        return None

    # Use the post-injection window -- that's when fault symptoms actually
    # show up. inject_time.txt sits next to data.csv.
    inject_path = case_dir / "inject_time.txt"
    if inject_path.exists() and "time" in df.columns:
        inject_time = int(inject_path.read_text().strip().split()[0])
        post = df[df["time"] >= inject_time]
        if len(post) > 0:
            df = post

    nodes = [
        {"service_id": svc, "features": extract_service_snapshot(df, svc),
         "label": "root_cause" if svc == root_cause else None}
        for svc in KNOWN_SERVICES
    ]
    edges = [{"source": s, "target": t} for s, t in ONLINE_BOUTIQUE_EDGES]
    incident_id = f"{case_dir.parent.name}_{case_dir.name}"

    return {
        "incident_id": incident_id,
        "timestamp": "",
        "root_cause": root_cause,
        "nodes": nodes,
        "edges": edges,
        "metadata": {"source": "RCAEval_RE1_OB", "fault_type": fault_type, "case_dir": str(case_dir)},
    }


def convert_all() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cases = find_ob_cases()
    print(f"found {len(cases)} OB cases")
    written = 0
    for case_dir in cases:
        incident = convert_case(case_dir)
        if incident is None:
            continue
        (OUTPUT_DIR / f"{incident['incident_id']}.json").write_text(json.dumps(incident, indent=2))
        written += 1
    print(f"wrote {written} incident JSON files to {OUTPUT_DIR}")


def main() -> None:
    ensure_rcaeval_src()
    if not OB_ROOT.exists():
        download_dataset()
    else:
        print(f"{OB_ROOT} already exists, skipping download.")
    peek_schema(n=1)
    convert_all()


if __name__ == "__main__":
    main()
