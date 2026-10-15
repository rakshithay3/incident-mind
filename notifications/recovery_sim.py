"""
notifications/recovery_sim.py -- scripted NEGATIVE (and one positive)
recovery trajectories for wait_for_recovery.

ShopMind faults always end on their own, so live polling only ever sees
"recovered". These scenarios build telemetry from the incident's own
baseline_history and push it through the real wait_for_recovery on a virtual
clock (no real sleeping), so the not-recovered paths of the notifier and the
dashboard can be exercised end to end.

    persistent  target and a dependent service stay broken the whole time
    partial     dependent heals; target stays just over its p99 limit
    relapse     healthy for consecutive-1 polls, then the target breaks for good
    crash_loop  target reports cpu_pct None (crashed/unreachable) every poll
    telemetry   the collector raises every poll (telemetry down)
    late        everything heals, but only after the timeout
    recovers    positive control: broken on the first poll, healthy after
    recovers_round2
                round 1 plays "relapse", round 2+ plays "recovers" -- for the
                re-investigation loop (notifications/rounds.py)

Nodes carry all five GraphSAGE inputs (cpu_pct, mem_pct, mean_latency_ms,
error_rate, p99_latency_ms) and the baseline call-graph edges, so
simulated_snapshot() can be re-scored like a live snapshot.
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional

from notifications.recovery import FIELDS, app_services_of, baseline_means, limits_for, wait_for_recovery

SCENARIOS = ("persistent", "partial", "relapse", "crash_loop", "telemetry", "late", "recovers", "recovers_round2")
SNAPSHOT_FIELDS = FIELDS + ("mean_latency_ms",)


def _round_scenario(scenario: str, round_no: int) -> str:
    if scenario == "recovers_round2":
        return "relapse" if round_no <= 1 else "recovers"
    return scenario


def _pick_services(baseline: Dict[str, Dict[str, float]], target: Optional[str],
                   dependent: Optional[str]) -> tuple:
    app = app_services_of(baseline)
    if target not in app:
        target = app[0]
    if dependent is None or dependent == target or dependent not in app:
        dependent = next((s for s in app if s != target), None)
    return target, dependent


def make_collector(
    scenario: str,
    baseline_history: Iterable[Dict],
    target: Optional[str] = None,
    dependent: Optional[str] = None,
    consecutive: int = 3,
    timeout_sec: float = 180.0,
    clock: Optional[Callable[[], float]] = None,
    round_no: int = 1,
) -> Callable[[], List[Dict]]:
    """Return a collect() that plays `scenario` for re-investigation round
    `round_no`. `clock` (virtual seconds since the first poll) is only needed
    for "late"."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown recovery scenario {scenario!r} (choose from {', '.join(SCENARIOS)})")
    scenario = _round_scenario(scenario, round_no)
    baseline = baseline_means(baseline_history, SNAPSHOT_FIELDS)
    target, dependent = _pick_services(baseline, target, dependent)
    limits = {sid: limits_for(b) for sid, b in baseline.items()}
    polls = [0]

    def healthy() -> Dict[str, Dict]:
        return {sid: {"service_id": sid, **b} for sid, b in baseline.items()}

    def break_errors(nodes, sid):
        if sid is not None:
            nodes[sid]["error_rate"] = limits[sid]["error_rate"] + 0.25

    def break_latency(nodes, sid, margin):
        if sid is not None:
            nodes[sid]["p99_latency_ms"] = limits[sid]["p99_latency_ms"] + margin
            nodes[sid]["mean_latency_ms"] = baseline[sid].get("mean_latency_ms", 0.0) + margin / 2

    def collect() -> List[Dict]:
        polls[0] += 1
        n = polls[0]
        nodes = healthy()
        if scenario == "telemetry":
            raise ConnectionError("simulated telemetry outage")
        if scenario == "persistent":
            break_errors(nodes, target)
            break_latency(nodes, dependent, 500.0)
        elif scenario == "partial":
            if n == 1:
                break_latency(nodes, dependent, 500.0)
            break_latency(nodes, target, 1.0)  # just over the p99 limit
        elif scenario == "relapse":
            if n >= consecutive:
                break_errors(nodes, target)
        elif scenario == "crash_loop":
            nodes[target]["cpu_pct"] = None
        elif scenario == "late":
            if clock is None or clock() <= timeout_sec:
                break_errors(nodes, target)
                break_latency(nodes, dependent, 500.0)
        elif scenario == "recovers":
            if n == 1:
                break_errors(nodes, target)
        return list(nodes.values())

    return collect


def simulate_recovery(
    scenario: str,
    telemetry: Dict,
    timeout_sec: float = 180.0,
    interval_sec: float = 5.0,
    consecutive: int = 3,
    target: Optional[str] = None,
    dependent: Optional[str] = None,
    log: Callable[[str], None] = print,
    round_no: int = 1,
) -> Dict:
    """Run wait_for_recovery against `scenario` (as played in round
    `round_no`) on a virtual clock. The result has the usual keys plus
    "simulated": scenario."""
    history = telemetry.get("baseline_history", [])
    t = [0.0]
    collect = make_collector(
        scenario, history,
        target=target or telemetry.get("target_service"), dependent=dependent,
        consecutive=consecutive, timeout_sec=timeout_sec, clock=lambda: t[0], round_no=round_no,
    )
    log(f"  [recovery] SIMULATED scenario '{scenario}' round {round_no} (virtual clock, no live telemetry)")
    result = wait_for_recovery(
        history, collect, timeout_sec=timeout_sec, interval_sec=interval_sec, consecutive=consecutive,
        sleep=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0], log=log,
    )
    result["simulated"] = scenario
    return result


def simulated_snapshot(
    scenario: str,
    telemetry: Dict,
    round_no: int = 1,
    consecutive: int = 3,
    target: Optional[str] = None,
    dependent: Optional[str] = None,
) -> Optional[Dict]:
    """The telemetry snapshot a collector would return right after round
    `round_no` of `scenario` timed out: {"timestamp", "nodes", "edges"}, or
    None when the scenario's telemetry is down. Used to re-score with
    GraphSAGE before the next re-investigation round."""
    history = telemetry.get("baseline_history", [])
    collect = make_collector(
        scenario, history, target=target or telemetry.get("target_service"), dependent=dependent,
        consecutive=consecutive, round_no=round_no,
    )
    try:
        for _ in range(consecutive):
            nodes = collect()
    except Exception:
        return None
    last = history[-1] if history else {}
    return {"timestamp": f"simulated-round-{round_no}", "nodes": nodes, "edges": list(last.get("edges") or [])}
