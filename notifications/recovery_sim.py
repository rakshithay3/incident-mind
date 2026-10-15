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
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional

from notifications.recovery import app_services_of, baseline_means, limits_for, wait_for_recovery

SCENARIOS = ("persistent", "partial", "relapse", "crash_loop", "telemetry", "late", "recovers")


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
) -> Callable[[], List[Dict]]:
    """Return a collect() that plays `scenario`. `clock` (virtual seconds since
    the first poll) is only needed for "late"."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown recovery scenario {scenario!r} (choose from {', '.join(SCENARIOS)})")
    baseline = baseline_means(baseline_history)
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
) -> Dict:
    """Run wait_for_recovery against `scenario` on a virtual clock. The result
    has the usual keys plus "simulated": scenario."""
    history = telemetry.get("baseline_history", [])
    t = [0.0]
    collect = make_collector(
        scenario, history,
        target=target or telemetry.get("target_service"), dependent=dependent,
        consecutive=consecutive, timeout_sec=timeout_sec, clock=lambda: t[0],
    )
    log(f"  [recovery] SIMULATED scenario '{scenario}' (virtual clock, no live telemetry)")
    result = wait_for_recovery(
        history, collect, timeout_sec=timeout_sec, interval_sec=interval_sec, consecutive=consecutive,
        sleep=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0], log=log,
    )
    result["simulated"] = scenario
    return result
