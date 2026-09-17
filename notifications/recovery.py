"""
notifications/recovery.py -- decides when ShopMind is actually fixed.

After the RCA, poll live telemetry (export_metrics.collect_all_telemetry)
until every app service is back near its pre-fault baseline for several
polls in a row. Only then does the "ShopMind is back" email go out, so users
are never told it's fixed while it's still broken.

"Back near baseline" per service (baseline = mean over the incident's
baseline_history):
    - reachable (cpu_pct is not None -- None means crashed/unreachable)
    - error_rate     <= baseline + 0.05
    - cpu_pct        <= max(1.5 x baseline, baseline + 0.10)
    - mem_pct        <= max(1.3 x baseline, baseline + 0.10)
    - p99_latency_ms <= max(1.5 x baseline, baseline + 100 ms)

All app services are checked, not just the root cause: network_delay shows
up on the caller, and users care whether the site works, not one service.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional, Tuple

FIELDS = ("cpu_pct", "mem_pct", "error_rate", "p99_latency_ms")


def baseline_means(baseline_history: Iterable[Dict]) -> Dict[str, Dict[str, float]]:
    sums: Dict[Tuple[str, str], float] = {}
    counts: Dict[Tuple[str, str], int] = {}
    for snap in baseline_history or []:
        for node in snap.get("nodes", []):
            sid = node.get("service_id")
            for f in FIELDS:
                v = node.get(f)
                if v is not None:
                    sums[(sid, f)] = sums.get((sid, f), 0.0) + float(v)
                    counts[(sid, f)] = counts.get((sid, f), 0) + 1
    out: Dict[str, Dict[str, float]] = {}
    for (sid, f), total in sums.items():
        out.setdefault(sid, {})[f] = total / counts[(sid, f)]
    return out


def unhealthy_services(nodes: Iterable[Dict], baseline: Dict[str, Dict[str, float]],
                       services: Optional[Iterable[str]] = None) -> List[str]:
    by_id = {n.get("service_id"): n for n in nodes}
    check = list(services) if services is not None else list(baseline.keys())
    bad = []
    for sid in check:
        n = by_id.get(sid)
        b = baseline.get(sid, {})
        if n is None or n.get("cpu_pct") is None:
            bad.append(sid)
            continue
        limits = {
            "error_rate": b.get("error_rate", 0.0) + 0.05,
            "cpu_pct": max(1.5 * b.get("cpu_pct", 0.0), b.get("cpu_pct", 0.0) + 0.10),
            "mem_pct": max(1.3 * b.get("mem_pct", 0.0), b.get("mem_pct", 0.0) + 0.10),
            "p99_latency_ms": max(1.5 * b.get("p99_latency_ms", 0.0), b.get("p99_latency_ms", 0.0) + 100.0),
        }
        for f, limit in limits.items():
            v = n.get(f)
            if v is not None and float(v) > limit:
                bad.append(sid)
                break
    return bad


def wait_for_recovery(
    baseline_history: Iterable[Dict],
    collect: Callable[[], List[Dict]],
    timeout_sec: float = 180.0,
    interval_sec: float = 5.0,
    consecutive: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    log: Callable[[str], None] = print,
) -> Dict:
    """collect() returns the current list of telemetry nodes.
    Returns {"recovered": bool, "restored_at": iso|None, "polls": int,
             "still_unhealthy": [...]}"""
    baseline = baseline_means(baseline_history)
    app_services = [sid for sid, b in baseline.items() if b.get("cpu_pct", 0.0) > 0 or b.get("p99_latency_ms", 0.0) > 0]
    if not app_services:
        app_services = list(baseline.keys())

    start = clock()
    streak, polls, bad = 0, 0, app_services
    while True:
        polls += 1
        try:
            nodes = collect()
            bad = unhealthy_services(nodes, baseline, app_services)
        except Exception as exc:  # telemetry down counts as not healthy
            bad = [f"telemetry error: {type(exc).__name__}"]
        if bad:
            streak = 0
            log(f"  [recovery] poll {polls}: waiting on {', '.join(bad)}")
        else:
            streak += 1
            log(f"  [recovery] poll {polls}: all services healthy ({streak}/{consecutive})")
            if streak >= consecutive:
                return {
                    "recovered": True,
                    "restored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "polls": polls,
                    "still_unhealthy": [],
                }
        if clock() - start >= timeout_sec:
            return {"recovered": False, "restored_at": None, "polls": polls, "still_unhealthy": bad}
        sleep(interval_sec)
