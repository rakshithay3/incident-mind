"""shopmind_snapshot.py -- ONE label-free way to turn a ShopMind
telemetry_series.json into a scored GNN input.

Used by package_evaluation.py (the 100-incident benchmark), replay_demo.py
(live/replay runs) and live_demo.py, so the benchmark and the demo see
exactly the same snapshot and the same feature encoding.

Why this exists (Sep 2026 review): the previous versions used the ground
truth to build the test input:
  * the peak-snapshot chooser weighted `target_service` 3x and added +100
    when the target was down, so every snapshot was picked with the answer;
  * the crash encoding (error_rate = 1.0) only fired when
    `srv_id == target_service and fault_type == "pod_crash"`, so only the
    true root cause could ever look crashed.
Nothing below reads `target_service` or `fault_type`. The label is only
copied through to the output's `root_cause` / `label` fields for scoring.

Peak rule: the snapshot whose single most-deviant (service, field) sits
furthest above its baseline median, measured in fixed per-field units. The old
fixed coefficients (cpu fraction x5 vs latency ms x0.1) only worked because
the target was up-weighted; without it they picked post-fault latency noise.

Crash rule: export_metrics.py only emits cpu_pct = None for an *app*
service whose /metrics scrape failed (edge/infra nodes are always 0.0).
A single failed scrape can be a timeout under load, so a service counts as
DOWN at snapshot i only if its cpu_pct is None for a run of at least
`min_down_run` consecutive snapshots containing i (default 2, i.e. >= ~4 s
at the 2 s poll interval). A down service is encoded as crashed
(zeroed resources/latency, error_rate 1.0); an isolated None is backfilled
with the last known good value, as before.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Set, Tuple

CPU_RATIO_TO_PERCENT = 100.0
MS_TO_SECONDS = 1.0 / 1000.0
DEFAULT_MIN_DOWN_RUN = 2

SERVICE_MEM_LIMIT_BYTES = {
    "frontend": 128 * 1024 * 1024,
    "api-gateway": 128 * 1024 * 1024,
    "auth-service": 384 * 1024 * 1024,
    "user-service": 384 * 1024 * 1024,
    "order-service": 384 * 1024 * 1024,
    "payment-service": 384 * 1024 * 1024,
    "inventory-service": 384 * 1024 * 1024,
    "notification-service": 384 * 1024 * 1024,
    "search-service": 384 * 1024 * 1024,
    "cache": 192 * 1024 * 1024,
    "postgres-primary": 512 * 1024 * 1024,
    "postgres-replica": 512 * 1024 * 1024,
    "prometheus": 384 * 1024 * 1024,
    "jaeger": 384 * 1024 * 1024,
    "docker-socket-proxy": 64 * 1024 * 1024,
}
DEFAULT_MEM_LIMIT_BYTES = 384 * 1024 * 1024

# Fallbacks used only when a service has no reading anywhere in history.
_DEFAULT_BASE = {"cpu": 0.02, "memory": 0.1, "latency": 5.0}

# Peak-snapshot scoring: each (service, field) deviation above that
# service's baseline MEDIAN, divided by a fixed per-field scale in ShopMind's
# raw units ("how many meaningful units above normal"). Fixed scales, not
# per-service stds: a quiet service's tiny baseline std turns a harmless
# blip into a huge z-score, and one noisy baseline sample inflates another's.
_Z_FIELDS = {
    "cpu_pct": 0.10,          # 10 CPU percentage points
    "mem_pct": 0.05,          # 5% of the memory limit
    "mean_latency_ms": 50.0,
    "p99_latency_ms": 200.0,
    "error_rate": 0.05,
}
_DOWN_SCORE = 1e3             # a sustained-down service outranks any deviation


# ---------------------------------------------------------------------------
# Baseline + down detection
# ---------------------------------------------------------------------------
def baseline_averages(baseline_history: Sequence[dict]) -> Dict[str, Dict[str, float]]:
    """Per-service mean cpu_pct / mem_pct / mean_latency_ms over the baseline
    window (None counted as 0.0, unchanged from package_evaluation.py)."""
    sums: Dict[str, Dict[str, float]] = {}
    counts: Dict[str, int] = {}
    for snap in baseline_history:
        for node in snap.get("nodes", []):
            srv = node["service_id"]
            s = sums.setdefault(srv, {"cpu": 0.0, "memory": 0.0, "latency": 0.0})
            s["cpu"] += node.get("cpu_pct") or 0.0
            s["memory"] += node.get("mem_pct") or 0.0
            s["latency"] += node.get("mean_latency_ms") or 0.0
            counts[srv] = counts.get(srv, 0) + 1
    return {srv: {k: v / (counts[srv] or 1) for k, v in s.items()} for srv, s in sums.items()}


def _null_cpu(snap: dict) -> Set[str]:
    return {n["service_id"] for n in snap.get("nodes", []) if n.get("cpu_pct") is None}


def down_services(failure_history: Sequence[dict], min_down_run: int = DEFAULT_MIN_DOWN_RUN) -> List[Set[str]]:
    """For each snapshot index, the services that are DOWN there: cpu_pct is
    None in a run of >= min_down_run consecutive snapshots containing it."""
    nulls = [_null_cpu(s) for s in failure_history]
    down: List[Set[str]] = [set() for _ in failure_history]
    services = set().union(*nulls) if nulls else set()
    for srv in services:
        i = 0
        while i < len(nulls):
            if srv not in nulls[i]:
                i += 1
                continue
            j = i
            while j < len(nulls) and srv in nulls[j]:
                j += 1
            if j - i >= min_down_run:
                for k in range(i, j):
                    down[k].add(srv)
            i = j
    return down


# ---------------------------------------------------------------------------
# Peak snapshot (label-free)
# ---------------------------------------------------------------------------
def baseline_stats(baseline_history: Sequence[dict]) -> Dict[Tuple[str, str], Tuple[float, float]]:
    """(service_id, field) -> (baseline median, field scale)."""
    import statistics

    values: Dict[Tuple[str, str], List[float]] = {}
    for snap in baseline_history:
        for node in snap.get("nodes", []):
            for field in _Z_FIELDS:
                v = node.get(field)
                if v is not None:
                    values.setdefault((node["service_id"], field), []).append(float(v))
    return {key: (statistics.median(vals), _Z_FIELDS[key[1]]) for key, vals in values.items()}


def snapshot_score(snap: dict, stats: Dict[Tuple[str, str], Tuple[float, float]], down: Set[str]) -> float:
    """Largest upward scaled deviation from baseline of any (service, field)
    in the snapshot; any sustained-down service scores _DOWN_SCORE. Using the max
    (not a sum over services) picks the moment the single most-deviant
    service peaks, instead of a moment of widespread low-level noise."""
    if down:
        return _DOWN_SCORE + len(down)
    best = 0.0
    for node in snap.get("nodes", []):
        srv = node["service_id"]
        for field, scale in _Z_FIELDS.items():
            v = node.get(field)
            if v is None:
                continue
            median, scale = stats.get((srv, field), (0.0, scale))
            best = max(best, (float(v) - median) / scale)
    return best


def select_peak_snapshot(
    failure_history: Sequence[dict],
    baseline_history: Sequence[dict],
    min_down_run: int = DEFAULT_MIN_DOWN_RUN,
) -> Tuple[Optional[dict], int, Set[str]]:
    """(peak_snapshot, index, down_services_at_peak). Earliest index wins ties."""
    if not failure_history:
        return None, -1, set()
    stats = baseline_stats(baseline_history)
    down = down_services(failure_history, min_down_run)
    best_idx, best = 0, float("-inf")
    for idx, snap in enumerate(failure_history):
        s = snapshot_score(snap, stats, down[idx])
        if s > best:
            best_idx, best = idx, s
    return failure_history[best_idx], best_idx, down[best_idx]


# ---------------------------------------------------------------------------
# Feature encoding
# ---------------------------------------------------------------------------
def last_known_good(service_id, key, snap_idx, failure_history, baseline_history, fallback):
    """Most recent non-null reading strictly before snap_idx (failure window
    first, then baseline). Never looks past the peak."""
    for idx in range(snap_idx - 1, -1, -1):
        for node in failure_history[idx].get("nodes", []):
            if node["service_id"] == service_id and node.get(key) is not None:
                return node[key]
    for idx in range(len(baseline_history) - 1, -1, -1):
        for node in baseline_history[idx].get("nodes", []):
            if node["service_id"] == service_id and node.get(key) is not None:
                return node[key]
    return fallback


def encode_node(node, down: Set[str], snap_idx=0, failure_history=(), baseline_history=(), base_avgs=None) -> dict:
    """ShopMind node -> RE1-unit feature dict (cpu %, memory bytes, s)."""
    srv = node["service_id"]
    if srv in down:
        return {"service_id": srv, "cpu": 0.0, "memory": 0.0, "error_rate": 1.0, "latency": 0.0, "p99_latency": 0.0}

    base = (base_avgs or {}).get(srv, _DEFAULT_BASE)

    def get(key, fallback):
        val = node.get(key)
        if val is None:
            val = last_known_good(srv, key, snap_idx, failure_history, baseline_history, fallback)
        return val

    cpu = get("cpu_pct", base["cpu"]) * CPU_RATIO_TO_PERCENT
    memory = get("mem_pct", base["memory"]) * SERVICE_MEM_LIMIT_BYTES.get(srv, DEFAULT_MEM_LIMIT_BYTES)
    latency = get("mean_latency_ms", base["latency"]) * MS_TO_SECONDS
    p99_fallback = base["latency"] * 3.0 if base["latency"] > 0 else 20.0
    p99 = get("p99_latency_ms", p99_fallback) * MS_TO_SECONDS
    err = get("error_rate", 0.0)
    return {
        "service_id": srv,
        "cpu": round(cpu, 4),
        "memory": round(memory, 2),
        "error_rate": round(err, 4),
        "latency": round(latency, 4),
        "p99_latency": round(p99, 4),
    }


def compile_edges(snap: dict, service_ids: Set[str]) -> List[dict]:
    edges = []
    for e in snap.get("edges", []) or []:
        s, t = e.get("source"), e.get("target")
        if s in service_ids and t in service_ids:
            edges.append({"source": s, "target": t, "call_count": e.get("call_count", 0)})
    return edges


def compile_telemetry(data: dict, min_down_run: int = DEFAULT_MIN_DOWN_RUN) -> Optional[dict]:
    """telemetry_series.json dict -> GNN payload (package_evaluation format).

    Label-free: target_service/fault_type are only copied into root_cause,
    label and metadata, never used to choose or encode the snapshot."""
    baseline_history = data.get("baseline_history", [])
    failure_history = data.get("failure_history", [])
    if not failure_history or not baseline_history:
        return None

    snap, idx, down = select_peak_snapshot(failure_history, baseline_history, min_down_run)
    base_avgs = baseline_averages(baseline_history)
    target = data.get("target_service")
    fault = data.get("fault_type")

    nodes = []
    for node in snap.get("nodes", []):
        enc = encode_node(node, down, idx, failure_history, baseline_history, base_avgs)
        enc["label"] = 1 if enc["service_id"] == target else 0
        nodes.append(enc)

    return {
        "incident_id": data.get("incident_id"),
        "timestamp": snap.get("timestamp", ""),
        "nodes": nodes,
        "edges": compile_edges(snap, {n["service_id"] for n in nodes}),
        "fault_injection": {
            "active": True,
            "fault_type": fault,
            "target_service": target,
            "injected_at": data.get("injected_at_epoch", ""),
        },
        "root_cause": target,
        "metadata": {
            "fault_type": fault,
            "dataset_version": "2026.09-labelfree",
            "peak_index": idx,
            "down_at_peak": sorted(down),
        },
    }


def payload_to_graph(payload: dict, source: str = "replay"):
    """GNN payload -> IncidentGraph (imports lazily so this module stays
    importable without the package on sys.path)."""
    from incidentmind_p1.contracts import IncidentGraph, ServiceNode

    feats = ("cpu", "memory", "latency", "error_rate", "p99_latency")
    return IncidentGraph(
        incident_id=payload["incident_id"],
        timestamp=str(payload.get("timestamp", "")),
        nodes=[ServiceNode(service_id=n["service_id"], features={k: float(n[k]) for k in feats}) for n in payload["nodes"]],
        edges=[(e["source"], e["target"]) for e in payload["edges"]],
        root_cause=payload.get("root_cause"),
        metadata={**payload.get("metadata", {}), "target_service": payload.get("root_cause"), "source": source},
    )
