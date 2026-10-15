"""
incident_watcher.py -- long-running, label-free trigger for the IncidentMind
pipeline. Until now the pipeline only ran from hand-started scripts
(live_demo.py, live_inject_and_capture.py --run-pipeline, replay_demo.py);
pressing the storefront chaos button only POSTed /inject-fault and nothing
noticed. This watcher polls ShopMind telemetry, notices the fault on its own
and runs the same scoring -> PPO dispatch -> agents -> report flow as
replay_demo.py, writing the result where the dashboard polls for it.

Nothing tells the watcher a fault was injected. Detection and scoring only
ever see telemetry (export_metrics.collect_all_telemetry) compiled by the
label-free shopmind_snapshot.py code.

    IDLE/warming  -- fill a rolling baseline with HEALTHY snapshots only
    armed         -- per poll: cheap gate (newest snapshot vs baseline,
                     scaled deviation >= --gate, or a service down for >= 2
                     polls); if it trips, GraphSAGE must also score some node
                     >= --threshold. --confirm consecutive polls -> incident.
    capturing     -- --capture-sec more failure_history, then write
                     <out-dir>/auto_<epoch>/telemetry_series.json + logs
                     (only lines since the baseline started) and run the
                     pipeline in a worker thread.
    cooldown      -- no new incident until --cooldown-healthy healthy polls
                     AND --min-gap-sec since the last one AND no investigation
                     running; then the baseline is refilled from scratch.

RUN (ShopMind docker-compose stack + Ollama up, models in models/):

    PYTHONPATH=. python3 incident_watcher.py
    PYTHONPATH=. python3 incident_watcher.py --dry-run --verbose   # detect only

See docs/watcher.md for flags, thresholds and limitations.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import threading
import time
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set

from notifications.recovery_sim import SCENARIOS
from shopmind_snapshot import baseline_stats, compile_telemetry, down_services, snapshot_score

DEFAULT_OUTPUT = "dashboard/public/demoResult.json"
DEFAULT_OUT_DIR = "output/watcher"
DOWN_WINDOW = 3          # snapshots used for down-detection (needs >= 2 None in a row)
LOOKBACK_SEC = 10        # Jaeger lookback per collect, same as the other capture scripts
FAULT_STATUS_TIMEOUT_SEC = 3.0


# ---------------------------------------------------------------------------
# Pure detection logic (no I/O; collector, scorer and clock are injected)
# ---------------------------------------------------------------------------
def _utc_iso(epoch: float) -> str:
    """RFC 3339 UTC ("...Z"), the form `docker logs --since` accepts."""
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class BaselineBuffer:
    """Rolling window of healthy snapshots. Callers only add() snapshots the
    gate judged healthy, so a fault never ends up in the baseline."""

    def __init__(self, size: int = 30) -> None:
        self._snaps: deque = deque(maxlen=size)
        self._times: deque = deque(maxlen=size)  # wall-clock epoch per snapshot

    def add(self, snap: dict, at: Optional[float] = None) -> None:
        self._snaps.append(snap)
        self._times.append(at)

    def snapshots(self) -> List[dict]:
        return list(self._snaps)

    def started_at(self) -> Optional[float]:
        """Wall-clock epoch of the oldest snapshot still in the buffer."""
        return self._times[0] if self._times else None

    def clear(self) -> None:
        self._snaps.clear()
        self._times.clear()

    def __len__(self) -> int:
        return len(self._snaps)


@dataclass
class GateResult:
    score: float
    down: Set[str]
    tripped: bool
    has_null: bool  # some app service missed a scrape (not yet "down")

    @property
    def healthy(self) -> bool:
        return not self.tripped and not self.has_null


class GateDetector:
    """Cheap per-poll check. Scores only the NEWEST snapshot against the
    baseline (so one spike can't satisfy --confirm twice); the last
    DOWN_WINDOW snapshots are used only to tell a crash from one missed
    scrape (shopmind_snapshot.down_services needs a run of >= 2)."""

    def __init__(self, gate: float = 3.0, app_services: Optional[Iterable[str]] = None) -> None:
        self.gate = gate
        self.app_services = set(app_services) if app_services is not None else None

    def evaluate(self, baseline: Sequence[dict], window: Sequence[dict]) -> GateResult:
        newest = window[-1]
        recent = list(window)[-DOWN_WINDOW:]
        down = down_services(recent)[-1]
        if self.app_services is not None:
            down = down & self.app_services
        score = snapshot_score(newest, baseline_stats(baseline), down)
        has_null = any(
            n.get("cpu_pct") is None
            for n in newest.get("nodes", [])
            if self.app_services is None or n["service_id"] in self.app_services
        )
        return GateResult(score=score, down=down, tripped=bool(down) or score >= self.gate, has_null=has_null)


def gate_ranking(telemetry: dict, gate: float = 3.0) -> list:
    """--fallback ranking: a fixed RULE, not the learned model. On the
    label-free peak snapshot, services that are down come first, then the
    rest by their largest scaled deviation above baseline (snapshot_score's
    units). anomaly_score maps that into [0, 1] for PPO's observation:
    down -> 1.0, deviation of 2x --gate or more -> 1.0, and the score is
    >= 0.5 ("anomalous") exactly when the deviation reaches --gate."""
    from incidentmind_p1.contracts import DEFAULT_EMBEDDING_DIM, NodeScore
    from shopmind_snapshot import select_peak_snapshot

    baseline = telemetry.get("baseline_history", [])
    snap, _idx, down = select_peak_snapshot(telemetry.get("failure_history", []), baseline)
    if snap is None:
        return []
    stats = baseline_stats(baseline)
    devs = {n["service_id"]: snapshot_score({"nodes": [n]}, stats, set()) for n in snap.get("nodes", [])}
    order = sorted(devs, key=lambda sid: (sid not in down, -devs[sid], sid))
    scores = []
    for rank, sid in enumerate(order, start=1):
        is_down = sid in down
        score = 1.0 if is_down else min(1.0, max(0.0, devs[sid]) / (2 * gate))
        scores.append(NodeScore(service_id=sid, anomaly_score=round(score, 6), embedding_dim=DEFAULT_EMBEDDING_DIM,
                                status="anomalous" if is_down or devs[sid] >= gate else "normal", rank=rank))
    return scores


@dataclass
class Event:
    kind: str  # armed | stack_down | suspect | suppressed | confirmed | incident | rearming
    message: str = ""
    incident_id: Optional[str] = None
    telemetry: Optional[dict] = None
    gate: Optional[GateResult] = None
    anomaly: Optional[float] = None
    detection: Optional[str] = None  # "graphsage" | "gate-fallback" on confirmed/incident


@dataclass
class WatcherConfig:
    gate: float = 3.0
    threshold: float = 0.5
    confirm: int = 3
    baseline_size: int = 30
    min_baseline: int = 5
    capture_sec: float = 20.0
    cooldown_healthy: int = 5
    min_gap_sec: float = 60.0
    min_app_up: int = 4
    fallback: bool = False  # rule-based: confirm on the gate alone when GraphSAGE stays below threshold


class IncidentStateMachine:
    """warming -> armed -> capturing -> cooldown -> warming ...

    step(snapshot) is called once per poll with a collect_all_telemetry()
    snapshot ({timestamp, nodes, edges}) or None when the collector failed.
    anomaly_fn(telemetry_dict) -> max GraphSAGE node anomaly_score; it is
    given only baseline_history + failure_history, never a label.
    investigation_running() -> True while a pipeline worker is busy.
    """

    def __init__(
        self,
        config: WatcherConfig,
        app_services: Iterable[str],
        anomaly_fn: Callable[[dict], float],
        investigation_running: Callable[[], bool] = lambda: False,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.cfg = config
        self.app_services = set(app_services)
        self.anomaly_fn = anomaly_fn
        self.investigation_running = investigation_running
        self.clock = clock
        self.wall_clock = wall_clock

        self.baseline = BaselineBuffer(config.baseline_size)
        self.gate = GateDetector(config.gate, self.app_services)
        self.window: deque = deque(maxlen=DOWN_WINDOW)
        self.state = "warming"
        self.streak = self.gnn_streak = 0
        self.healthy_streak = 0
        self.last_incident_start: Optional[float] = None
        self.incident_id: Optional[str] = None
        self.detection_mode = "graphsage"
        self._capture: List[dict] = []
        self._capture_start = 0.0
        self._frozen_baseline: List[dict] = []
        self._baseline_started_at: Optional[float] = None
        self.incidents = 0

    @property
    def armed(self) -> bool:
        return self.state == "armed"

    def _stack_up(self, snap: dict) -> bool:
        up = sum(1 for n in snap.get("nodes", [])
                 if n["service_id"] in self.app_services and n.get("cpu_pct") is not None)
        return up >= min(self.cfg.min_app_up, len(self.app_services))

    def step(self, snap: Optional[dict]) -> List[Event]:
        if snap is None:
            self.streak = self.gnn_streak = self.healthy_streak = 0
            return [Event("stack_down", "telemetry collector failed")]

        if self.state == "capturing":
            return self._step_capturing(snap)

        if not self._stack_up(snap):
            # Too few app services answering = stack down / restarting, not
            # an incident. Drop the window so a None run can't carry over.
            self.streak = self.gnn_streak = self.healthy_streak = 0
            self.window.clear()
            return [Event("stack_down", "stack not up (too few app services responding)")]

        self.window.append(snap)
        if self.state == "cooldown":
            return self._step_cooldown(snap)

        gate = self.gate.evaluate(self.baseline.snapshots(), list(self.window))
        if self.state == "warming":
            if gate.healthy:
                self.baseline.add(snap, self.wall_clock())
                if len(self.baseline) >= self.cfg.min_baseline:
                    self.state = "armed"
                    return [Event("armed", f"armed ({len(self.baseline)} healthy baseline snapshots)", gate=gate)]
            return []

        # armed
        if not gate.tripped:
            self.streak = self.gnn_streak = 0
            if gate.healthy:
                self.baseline.add(snap, self.wall_clock())
            return []

        if self.investigation_running():
            self.streak = self.gnn_streak = 0
            return [Event("suppressed", "gate tripped but an investigation is still running", gate=gate)]

        # Label-free: only baseline/failure history, no target_service/fault_type.
        anomaly = self.anomaly_fn({
            "incident_id": "watcher_probe",
            "baseline_history": self.baseline.snapshots(),
            "failure_history": list(self.window),
        })
        # streak counts gate-tripped polls (only used with --fallback);
        # gnn_streak counts polls where GraphSAGE agreed as well.
        self.streak += 1
        self.gnn_streak = self.gnn_streak + 1 if anomaly >= self.cfg.threshold else 0
        if self.gnn_streak >= self.cfg.confirm:
            mode = "graphsage"
        elif self.cfg.fallback and self.streak >= self.cfg.confirm:
            mode = "gate-fallback"
        elif anomaly < self.cfg.threshold:
            if not self.cfg.fallback:
                self.streak = 0
            tail = f" (fallback {self.streak}/{self.cfg.confirm})" if self.cfg.fallback else ""
            return [Event("suspect", f"gate tripped but GraphSAGE max={anomaly:.3f} < threshold{tail}",
                          gate=gate, anomaly=anomaly)]
        else:
            return [Event("suspect", f"suspect {self.gnn_streak}/{self.cfg.confirm}", gate=gate, anomaly=anomaly)]

        self.streak = self.gnn_streak = 0
        self.detection_mode = mode
        self.state = "capturing"
        self.incident_id = f"auto_{int(self.wall_clock())}"
        self.last_incident_start = self.clock()
        self._capture_start = self.clock()
        self._capture = list(self.window)  # include the confirm window
        self._frozen_baseline = copy.deepcopy(self.baseline.snapshots())
        self._baseline_started_at = self.baseline.started_at()
        return [Event("confirmed", f"incident {self.incident_id} confirmed ({mode})", incident_id=self.incident_id,
                      gate=gate, anomaly=anomaly, detection=mode)]

    def _step_capturing(self, snap: dict) -> List[Event]:
        self._capture.append(snap)
        if self.clock() - self._capture_start < self.cfg.capture_sec:
            return []
        telemetry = {
            "incident_id": self.incident_id,
            # The watcher doesn't know (and must not know) what was injected.
            "target_service": "unknown",
            "fault_type": "unknown",
            "detected_at": datetime.fromtimestamp(self.wall_clock(), timezone.utc).isoformat(timespec="seconds"),
            "detection": self.detection_mode,
            # UTC start of this incident's window; run_pipeline passes it to
            # `docker logs --since` so older incidents' log lines are dropped.
            "baseline_started_at": _utc_iso(self._baseline_started_at),
            "baseline_history": self._frozen_baseline,
            "failure_history": self._capture,
        }
        self.state = "cooldown"
        self.healthy_streak = 0
        self.window.clear()
        self.incidents += 1
        self._capture = []
        return [Event("incident", f"captured {len(telemetry['failure_history'])} snapshots",
                      incident_id=self.incident_id, telemetry=telemetry, detection=self.detection_mode)]

    def _step_cooldown(self, snap: dict) -> List[Event]:
        # Health is judged against the frozen pre-incident baseline.
        gate = self.gate.evaluate(self._frozen_baseline, list(self.window))
        self.healthy_streak = self.healthy_streak + 1 if gate.healthy else 0
        gap_ok = self.last_incident_start is None or self.clock() - self.last_incident_start >= self.cfg.min_gap_sec
        if self.healthy_streak >= self.cfg.cooldown_healthy and gap_ok and not self.investigation_running():
            self.state = "warming"
            self.baseline.clear()
            self.window.clear()
            self.streak = self.gnn_streak = self.healthy_streak = 0
            return [Event("rearming", "recovered; refilling baseline")]
        return []


# ---------------------------------------------------------------------------
# Ground truth -- EVALUATION ONLY. Never passed to the gate, GraphSAGE, PPO
# or the agents; it only fills the result's true_root_cause / metrics so the
# dashboard can show whether the label-free detection got it right.
# ---------------------------------------------------------------------------
def probe_fault_status(config: Dict[str, dict], timeout: float = FAULT_STATUS_TIMEOUT_SEC) -> List[dict]:
    """Best-effort GET /fault-status on every app service, in parallel; active
    faults only. The timeout must outlast the faults themselves: network_delay
    holds every request (including /fault-status) for 2 s by default."""
    from concurrent.futures import ThreadPoolExecutor

    def fetch(item):
        name, cfg = item
        try:
            with urllib.request.urlopen(f"http://{cfg['host']}:{cfg['port']}/fault-status", timeout=timeout) as resp:
                status = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None
        return {**status, "target_service": status.get("target_service") or name} if status.get("active") else None

    apps = [(n, c) for n, c in config.items() if c.get("role") == "app"]
    if not apps:
        return []
    with ThreadPoolExecutor(max_workers=len(apps)) as pool:
        return [s for s in pool.map(fetch, apps) if s]


def resolve_ground_truth(*probes: Sequence[dict]) -> Optional[dict]:
    """Exactly one distinct active target across all probes -> that fault;
    none or several -> None (ground truth unavailable)."""
    by_target: Dict[str, dict] = {}
    for probe in probes:
        for status in probe:
            by_target.setdefault(status["target_service"], status)
    return next(iter(by_target.values())) if len(by_target) == 1 else None


# ---------------------------------------------------------------------------
# Result JSON (same schema as replay_demo.py so transformDemoResult.js works)
# ---------------------------------------------------------------------------
def build_result(
    incident_id: str,
    timestamp: str,
    ranked: Sequence,
    raw_ranked: Sequence,
    multi_fault_nodes: Sequence,
    dispatch: dict,
    ground_truth: Optional[dict],
    investigation: Optional[dict] = None,
    recovery: Optional[dict] = None,
    notifications: Optional[list] = None,
    fault_injection_state: str = "resolved",
    detection: str = "graphsage",
    detection_info: Optional[dict] = None,
) -> dict:
    """ranked / raw_ranked / multi_fault_nodes are NodeScore-like objects
    (service_id, anomaly_score, status, rank); dispatch is
    {agent_type, target_service, policy_confidence}. detection is
    "graphsage" (learned model confirmed and ranked) or "gate-fallback"
    (--fallback rule confirmed and ranked; see gate_ranking)."""
    ranking = "gate_fallback" if detection == "gate-fallback" else "graphsage_raw"
    truth = ground_truth["target_service"] if ground_truth else None
    if truth:
        raw_ids = [s.service_id for s in raw_ranked]
        metrics = {
            "pr_at_1": 1.0 if raw_ids[:1] == [truth] else 0.0,
            "pr_at_3": 1.0 if truth in raw_ids[:3] else 0.0,
            "pr_at_5": 1.0 if truth in raw_ids[:5] else 0.0,
            "ranking": ranking,
        }
    else:
        metrics = {"pr_at_1": 0.0, "pr_at_3": 0.0, "pr_at_5": 0.0, "ranking": ranking}

    result = {
        "incident_id": incident_id,
        "timestamp": timestamp,
        "fault_type": (ground_truth or {}).get("fault_type") or "unknown",
        "injected_target": truth or "unknown",
        "true_root_cause": truth or "unknown",
        "fault_injection_state": fault_injection_state,
        "nodes": [
            {"service_id": s.service_id, "anomaly_score": s.anomaly_score, "status": s.status, "rank": s.rank}
            for s in ranked
        ],
        "multi_fault_detected": [
            {"service_id": s.service_id, "anomaly_score": s.anomaly_score, "rank": s.rank}
            for s in multi_fault_nodes
        ],
        "ppo_dispatch": dict(dispatch),
        "evidence_bundle": (investigation or {}).get("evidence_bundle"),
        "report": (investigation or {}).get("report"),
        "recovery": recovery,
        "notifications": list(notifications or []),
        "metrics": metrics,
        "ground_truth": "fault-status" if truth else "unavailable",
        "detection": detection,
    }
    if detection_info:
        result["detection_info"] = detection_info
    return result


def write_json_atomic(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _detection_latency(ground_truth: Optional[dict], confirmed_wall: float) -> Optional[float]:
    try:
        injected = datetime.fromisoformat(ground_truth["injected_at"].replace("Z", "+00:00")).timestamp()
        return round(confirmed_wall - injected, 1)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Real collector / scorer / pipeline (torch + stable_baselines3 imported lazily)
# ---------------------------------------------------------------------------
def make_collector(services_config: dict, lookback_sec: int = LOOKBACK_SEC) -> Callable[[], Optional[dict]]:
    from export_metrics import collect_all_telemetry

    def collect() -> Optional[dict]:
        try:
            nodes, edges = collect_all_telemetry(services_config, lookback_sec)
        except Exception:
            return None
        return {"timestamp": nodes[0]["timestamp"] if nodes else "", "nodes": nodes, "edges": edges}

    return collect


class GraphSAGEProbe:
    """anomaly_fn for the state machine: compile_telemetry (label-free) ->
    GraphSAGE -> max node anomaly_score. Loads the checkpoint on first use."""

    def __init__(self, model_path: str) -> None:
        self.model_path = model_path
        self._scorer = None

    def __call__(self, telemetry: dict) -> float:
        from shopmind_snapshot import payload_to_graph

        if self._scorer is None:
            from incidentmind_p1.gnn_scorer import GraphSAGEScorer
            from incidentmind_p1.training import load_checkpoint

            encoder, stats = load_checkpoint(self.model_path)
            self._scorer = GraphSAGEScorer(encoder, stats)
        payload = compile_telemetry(telemetry)
        if payload is None:
            return 0.0
        scores = self._scorer.score_graph(payload_to_graph(payload, source="watcher"))
        return max((s.anomaly_score for s in scores), default=0.0)


def run_pipeline(incident_dir: Path, telemetry: dict, ground_truth: Optional[dict], args, services: List[str],
                 detection_info: dict) -> None:
    """Same flow as replay_demo.main(), in-process, for a label-free capture."""
    import replay_demo
    from incidentmind_p1.dispatch import PPODispatcher
    from incidentmind_p1.gnn_scorer import GraphSAGEScorer
    from incidentmind_p1.training import load_checkpoint
    from live_inject_and_capture import capture_logs
    from multi_fault import detect_multi_fault
    from priority.impact_weights import PriorityWeightedScorer
    from stable_baselines3 import PPO

    telemetry_path = incident_dir / "telemetry_series.json"
    capture_logs(incident_dir, services, since=telemetry["baseline_started_at"])

    notifier = recipients_info = None
    if args.notify:
        from notifications.notifier import Notifier
        from notifications.recipients import get_recipients

        notifier = Notifier()
        recipients_info = get_recipients()
        print(f"  [{telemetry['incident_id']}] users to notify on recovery: {len(recipients_info['recipients'])}")

    incident = replay_demo.compile_live_snapshot(telemetry)
    detection = telemetry.get("detection", "graphsage")
    if detection == "gate-fallback":
        # Rule-based ranking (not the learned model): GraphSAGE didn't flag
        # this incident, so PPO dispatches on gate deviation instead.
        raw_ranked = ranked = gate_ranking(telemetry, args.gate)
    else:
        encoder, stats = load_checkpoint(args.graphsage_model)
        base_scorer = GraphSAGEScorer(encoder, stats)
        raw_ranked = sorted(base_scorer.score_graph(incident), key=lambda s: s.rank)
        ranked = sorted(PriorityWeightedScorer(base_scorer).score_graph(incident), key=lambda s: s.rank)
    multi_fault_nodes = detect_multi_fault(ranked)

    decision = PPODispatcher(policy=PPO.load(args.ppo_model)).choose(ranked, visited=set(), step=1)
    top_service = decision.action.target_service
    dispatch = {
        "agent_type": decision.action.agent_type,
        "target_service": top_service,
        "policy_confidence": decision.policy_confidence,
    }
    tag = f"[{incident.incident_id}]"
    print(f"  {tag} {'gate-fallback' if detection == 'gate-fallback' else 'GraphSAGE'} top-5: " + ", ".join(f"{s.service_id}={s.anomaly_score:.3f}" for s in raw_ranked[:5]))
    print(f"  {tag} PPO dispatch: {dispatch['agent_type']} -> {top_service} (conf {decision.policy_confidence:.2f})")

    def publish(result: dict) -> None:
        write_json_atomic(incident_dir / "result.json", result)
        write_json_atomic(Path(args.output), result)

    common = dict(incident_id=incident.incident_id, timestamp=incident.timestamp, ranked=ranked,
                  raw_ranked=raw_ranked, multi_fault_nodes=multi_fault_nodes, dispatch=dispatch,
                  ground_truth=ground_truth, detection=detection, detection_info=detection_info)
    publish(build_result(**common, fault_injection_state="active"))
    print(f"  {tag} interim result written to {args.output}; running agents...")

    from pipeline import run_investigation
    from schemas.contracts import DispatchAction

    log_path = incident_dir / f"{top_service}.log"
    investigation = run_investigation(
        [DispatchAction(agent_type=a, target_service=top_service) for a in ("log", "metrics", "code")],
        incident_id=incident.incident_id,
        telemetry_path=str(telemetry_path),
        log_path=str(log_path) if log_path.exists() else None,
        code_path=args.code_repo_path,
    )
    print(f"  {tag} report root cause: {investigation['report'].get('root_cause_service')} "
          f"(confidence {investigation['report'].get('confidence_score')})")

    notifications, recovery = [], None
    if notifier is not None:
        recovery = replay_demo._wait_for_shopmind(telemetry, args.recovery_timeout, args.recovery_interval,
                                                  simulate=getattr(args, "simulate_recovery", None))
        if recovery["recovered"]:
            reported = investigation["report"].get("root_cause_service")
            fresh = get_recipients()
            notifications.append(notifier.notify_restored(
                incident.incident_id, fresh["recipients"],
                root_cause_service=reported if reported and reported != "unknown" else top_service,
                started_at=replay_demo._fault_started_at(telemetry),
                restored_at=recovery["restored_at"],
                recipients_source=fresh["source"],
            ))
        else:
            notifications.append(notifier.notify_not_recovered(
                incident.incident_id, recovery["still_unhealthy"], args.recovery_timeout))

    state = "active" if (recovery is not None and not recovery.get("recovered")) else "resolved"
    publish(build_result(**common, investigation=investigation, recovery=recovery,
                         notifications=notifications, fault_injection_state=state))
    print(f"  {tag} final result written to {args.output} and {incident_dir / 'result.json'}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _ts() -> str:
    return time.strftime("%H:%M:%S")


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch ShopMind telemetry and run the IncidentMind pipeline on anomalies")
    parser.add_argument("--poll-sec", type=float, default=2.0)
    parser.add_argument("--baseline-size", type=int, default=30)
    parser.add_argument("--min-baseline", type=int, default=5)
    parser.add_argument("--gate", type=float, default=3.0, help="Max scaled deviation of the newest snapshot that trips the gate")
    parser.add_argument("--threshold", type=float, default=0.5, help="Min GraphSAGE node anomaly_score to count a poll")
    parser.add_argument("--confirm", type=int, default=3, help="Consecutive gate+GraphSAGE polls needed")
    parser.add_argument("--capture-sec", type=float, default=20.0)
    parser.add_argument("--cooldown-healthy", type=int, default=5)
    parser.add_argument("--min-gap-sec", type=float, default=60.0)
    parser.add_argument("--min-app-up", type=int, default=4, help="Fewer responding app services = 'stack not up'")
    parser.add_argument("--fallback", action="store_true",
                        help="Rule-based: confirm on the gate alone when GraphSAGE stays below --threshold, "
                             "and rank by gate deviation (off by default)")
    parser.add_argument("--graphsage-model", default="models/graphsage.pt")
    parser.add_argument("--ppo-model", default="models/ppo_dispatch.zip")
    parser.add_argument("--code-repo-path", default=None)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--notify", action="store_true", help="Wait for recovery and email users (off by default)")
    parser.add_argument("--recovery-timeout", type=float, default=180.0)
    parser.add_argument("--recovery-interval", type=float, default=5.0)
    parser.add_argument("--simulate-recovery", choices=SCENARIOS, default=None,
                        help="Replace live recovery polling with a scripted trajectory (only with --notify)")
    parser.add_argument("--once", action="store_true", help="Exit after the first incident finishes")
    parser.add_argument("--dry-run", action="store_true", help="Detect and log only: no files, no agents")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    from export_metrics import load_services

    services_config = load_services()
    app_services = [n for n, c in services_config.items() if c.get("role") == "app"]
    cfg = WatcherConfig(
        gate=args.gate, threshold=args.threshold, confirm=args.confirm,
        baseline_size=args.baseline_size, min_baseline=args.min_baseline,
        capture_sec=args.capture_sec, cooldown_healthy=args.cooldown_healthy,
        min_gap_sec=args.min_gap_sec, min_app_up=args.min_app_up, fallback=args.fallback,
    )
    worker: Dict[str, Optional[threading.Thread]] = {"thread": None}

    def running() -> bool:
        t = worker["thread"]
        return t is not None and t.is_alive()

    machine = IncidentStateMachine(cfg, app_services, GraphSAGEProbe(args.graphsage_model), running)
    collect = make_collector(services_config)
    pending_truth: Dict[str, list] = {}
    confirmed_wall: Dict[str, float] = {}

    print(f"[{_ts()}] watching {len(app_services)} app services every {args.poll_sec}s "
          f"(gate={cfg.gate}, threshold={cfg.threshold}, confirm={cfg.confirm}"
          f"{', fallback on' if cfg.fallback else ''})"
          f"{' [dry-run]' if args.dry_run else ''}")
    last_down_msg = 0.0
    try:
        while True:
            started = time.monotonic()
            for ev in machine.step(collect()):
                if ev.kind == "stack_down":
                    if time.monotonic() - last_down_msg > 30 or args.verbose:
                        print(f"[{_ts()}] stack not up: {ev.message}")
                        last_down_msg = time.monotonic()
                elif ev.kind == "confirmed":
                    confirmed_wall[ev.incident_id] = time.time()
                    print(f"[{_ts()}] DETECTED {ev.incident_id} [{ev.detection}]: gate={ev.gate.score:.2f} "
                          f"down={sorted(ev.gate.down)} graphsage_max={ev.anomaly:.3f}; capturing {cfg.capture_sec:.0f}s")
                    # Evaluation only (see resolve_ground_truth); not used for detection.
                    pending_truth[ev.incident_id] = [] if args.dry_run else probe_fault_status(services_config)
                elif ev.kind == "incident":
                    print(f"[{_ts()}] incident {ev.incident_id}: {ev.message}")
                    if args.dry_run:
                        if args.once:
                            return
                        continue
                    truth = resolve_ground_truth(pending_truth.pop(ev.incident_id, []),
                                                 probe_fault_status(services_config))
                    detection_info = {
                        "detected_at": ev.telemetry["detected_at"],
                        "detection_latency_sec": _detection_latency(truth, confirmed_wall.pop(ev.incident_id, time.time())),
                        "gate": cfg.gate, "threshold": cfg.threshold, "confirm": cfg.confirm,
                        "fallback_enabled": cfg.fallback,
                    }
                    incident_dir = Path(args.out_dir) / ev.incident_id
                    write_json_atomic(incident_dir / "telemetry_series.json", ev.telemetry)
                    print(f"[{_ts()}] wrote {incident_dir / 'telemetry_series.json'}; ground truth: "
                          f"{(truth['target_service'] + '/' + truth['fault_type']) if truth else 'unavailable'}")

                    def work(d=incident_dir, tel=ev.telemetry, gt=truth, det=detection_info):
                        try:
                            run_pipeline(d, tel, gt, args, list(services_config.keys()), det)
                        except Exception as exc:
                            print(f"[{_ts()}] pipeline for {tel['incident_id']} failed: {type(exc).__name__}: {exc}")

                    worker["thread"] = threading.Thread(target=work, name=ev.incident_id, daemon=True)
                    worker["thread"].start()
                else:
                    if ev.kind in ("armed", "rearming") or args.verbose:
                        print(f"[{_ts()}] {ev.message}")
            if args.verbose and machine.state in ("warming", "armed") and machine.window:
                g = machine.gate.evaluate(machine.baseline.snapshots(), list(machine.window))
                print(f"[{_ts()}] {machine.state} gate={g.score:.2f} down={sorted(g.down)} baseline={len(machine.baseline)}")
            if args.once and machine.incidents and not running() and not args.dry_run:
                print(f"[{_ts()}] --once: done")
                return
            time.sleep(max(0.0, args.poll_sec - (time.monotonic() - started)))
    except KeyboardInterrupt:
        if running():
            print(f"\n[{_ts()}] stopping; investigation {worker['thread'].name} abandoned (interim result kept)")
        else:
            print(f"\n[{_ts()}] stopped")


if __name__ == "__main__":
    main()
