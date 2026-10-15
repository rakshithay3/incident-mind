"""incident_watcher.py detection logic, with fakes only (no Docker/Ollama/torch)."""

import random
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from incident_watcher import (BaselineBuffer, IncidentStateMachine, WatcherConfig, build_result, gate_ranking,
                              resolve_ground_truth)

ROOT = Path(__file__).resolve().parent.parent
APPS = ["auth-service", "user-service", "order-service", "payment-service",
        "inventory-service", "notification-service", "search-service"]
INFRA = ["frontend", "api-gateway", "cache", "postgres-primary", "postgres-replica"]
POLL = 2.0


def _iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _snap(rng, overrides=None):
    nodes = []
    for sid in APPS:
        node = {"service_id": sid, "cpu_pct": round(0.02 + rng.uniform(-0.01, 0.01), 4),
                "mem_pct": round(0.10 + rng.uniform(-0.005, 0.005), 4),
                "mean_latency_ms": round(5 + rng.uniform(-2, 2), 2),
                "p99_latency_ms": round(20 + rng.uniform(-5, 5), 2), "error_rate": 0.0}
        node.update((overrides or {}).get(sid, {}))
        nodes.append(node)
    for sid in INFRA:
        nodes.append({"service_id": sid, "cpu_pct": 0.0, "mem_pct": 0.0, "mean_latency_ms": 0.0,
                      "p99_latency_ms": 0.0, "error_rate": 0.0})
    return {"timestamp": "t", "nodes": nodes, "edges": []}


HOT = {"auth-service": {"cpu_pct": 0.95}}
DOWN = {"auth-service": {"cpu_pct": None, "mem_pct": None}}
MEM = {"search-service": {"mem_pct": 0.57}}
CRASH = {"inventory-service": {"cpu_pct": None, "mem_pct": None}}


def fake_anomaly(telemetry):
    """Stand-in for GraphSAGE: high if any app service in the window is hot
    or missing. Asserts it is never handed a label."""
    assert "target_service" not in telemetry and "fault_type" not in telemetry
    for snap in telemetry["failure_history"]:
        for n in snap["nodes"]:
            if n["service_id"] in APPS and (n["cpu_pct"] is None or n["cpu_pct"] > 0.5):
                return 0.9
    return 0.1


def blind_anomaly(telemetry):
    """GraphSAGE as observed live on memory_pressure / pod_crash: 0.000."""
    assert "target_service" not in telemetry and "fault_type" not in telemetry
    return 0.0


class Harness:
    def __init__(self, running=lambda: False, anomaly_fn=fake_anomaly, **cfg):
        self.now = 0.0
        self.rng = random.Random(7)
        self.machine = IncidentStateMachine(
            WatcherConfig(**cfg), APPS, anomaly_fn, running,
            clock=lambda: self.now, wall_clock=lambda: 1_700_000_000 + self.now,
        )
        self.events = []

    def feed(self, n, overrides=None, snap=None):
        for _ in range(n):
            s = snap if snap is not None else _snap(self.rng, overrides)
            self.events += self.machine.step(s)
            self.now += POLL
        return self

    def kinds(self, kind):
        return [e for e in self.events if e.kind == kind]

    def arm(self):
        return self.feed(8)


class DetectionTest(unittest.TestCase):
    def test_healthy_stream_never_triggers(self):
        h = Harness().feed(300)
        self.assertTrue(h.machine.armed)
        self.assertEqual(h.kinds("confirmed"), [])
        self.assertEqual(h.kinds("incident"), [])

    def test_single_spike_does_not_trigger(self):
        h = Harness().arm().feed(1, HOT).feed(20)
        self.assertEqual(h.kinds("confirmed"), [])

    def test_sustained_cpu_fault_triggers_exactly_once(self):
        h = Harness().arm().feed(30, HOT)
        self.assertEqual(len(h.kinds("confirmed")), 1)
        incidents = h.kinds("incident")
        self.assertEqual(len(incidents), 1)
        tel = incidents[0].telemetry
        self.assertTrue(re.fullmatch(r"auto_\d+", tel["incident_id"]))
        self.assertEqual(tel["target_service"], "unknown")
        self.assertEqual(tel["fault_type"], "unknown")
        # confirm window + ~capture_sec/POLL more snapshots
        self.assertGreaterEqual(len(tel["failure_history"]), 2 + int(20 / POLL))
        self.assertGreaterEqual(len(tel["baseline_history"]), 5)

    def test_down_service_triggers(self):
        h = Harness().arm().feed(20, DOWN)
        self.assertEqual(len(h.kinds("incident")), 1)

    def test_single_missed_scrape_does_not_trigger(self):
        h = Harness().arm().feed(1, DOWN).feed(20)
        self.assertEqual(h.kinds("confirmed"), [])

    def test_fault_never_enters_baseline(self):
        h = Harness().arm().feed(1, HOT).feed(3).feed(1, DOWN).feed(3)
        for snap in h.machine.baseline.snapshots():
            auth = next(n for n in snap["nodes"] if n["service_id"] == "auth-service")
            self.assertIsNotNone(auth["cpu_pct"])
            self.assertLess(auth["cpu_pct"], 0.5)
        h.feed(30, HOT)
        for snap in h.kinds("incident")[0].telemetry["baseline_history"]:
            auth = next(n for n in snap["nodes"] if n["service_id"] == "auth-service")
            self.assertLess(auth["cpu_pct"], 0.5)

    def test_not_armed_before_min_baseline(self):
        h = Harness().feed(3).feed(20, HOT)
        self.assertFalse(h.machine.armed)
        self.assertEqual(h.kinds("armed"), [])
        self.assertEqual(h.kinds("confirmed"), [])

    def test_all_none_stack_does_not_trigger(self):
        dead = _snap(random.Random(1), {sid: {"cpu_pct": None, "mem_pct": None} for sid in APPS})
        h = Harness().arm().feed(30, snap=dead)
        self.assertEqual(h.kinds("confirmed"), [])
        self.assertTrue(h.kinds("stack_down"))
        h = Harness().arm()
        h.events += h.machine.step(None)
        self.assertEqual(h.kinds("stack_down")[0].message, "telemetry collector failed")


class CooldownTest(unittest.TestCase):
    def test_cooldown_needs_healthy_streak_and_min_gap_then_rearms(self):
        h = Harness().arm().feed(14, HOT)            # confirm at poll 2, capture 20s
        self.assertEqual(len(h.kinds("incident")), 1)
        self.assertEqual(h.machine.state, "cooldown")
        h.feed(5)                                     # healthy streak met, gap (60s) not yet
        self.assertEqual(h.machine.state, "cooldown")
        h.feed(4, HOT).feed(4)                        # fault again resets the streak
        self.assertEqual(h.machine.state, "cooldown")
        self.assertEqual(len(h.kinds("confirmed")), 1)
        h.feed(10)
        self.assertEqual(len(h.kinds("rearming")), 1)
        h.feed(5)
        self.assertTrue(h.machine.armed)

    def test_later_separate_fault_is_a_second_incident(self):
        h = Harness().arm().feed(14, HOT).feed(40).feed(30, DOWN)
        incidents = h.kinds("incident")
        self.assertEqual(len(incidents), 2)
        self.assertNotEqual(incidents[0].incident_id, incidents[1].incident_id)

    def test_running_investigation_suppresses_new_incidents(self):
        busy = {"on": False}
        h = Harness(running=lambda: busy["on"]).arm().feed(14, HOT)
        busy["on"] = True
        h.feed(60)                                    # healthy for ages, but still investigating
        self.assertEqual(h.machine.state, "cooldown")
        busy["on"] = False
        h.feed(1).feed(5)
        self.assertTrue(h.machine.armed)
        busy["on"] = True                             # armed, but a worker is still busy
        h.feed(20, HOT)
        self.assertEqual(len(h.kinds("confirmed")), 1)
        self.assertTrue(h.kinds("suppressed"))


class FallbackTest(unittest.TestCase):
    def test_off_by_default_gate_alone_never_confirms(self):
        self.assertFalse(WatcherConfig().fallback)
        h = Harness(anomaly_fn=blind_anomaly).arm().feed(30, MEM).feed(30, CRASH)
        self.assertEqual(h.kinds("confirmed"), [])

    def test_memory_fault_confirms_via_gate_fallback(self):
        h = Harness(anomaly_fn=blind_anomaly, fallback=True).arm().feed(30, MEM)
        confirmed = h.kinds("confirmed")
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(confirmed[0].detection, "gate-fallback")
        incident = h.kinds("incident")[0]
        self.assertEqual(incident.detection, "gate-fallback")
        self.assertEqual(incident.telemetry["detection"], "gate-fallback")

    def test_sustained_down_confirms_via_gate_fallback(self):
        h = Harness(anomaly_fn=blind_anomaly, fallback=True).arm().feed(30, CRASH)
        self.assertEqual([e.detection for e in h.kinds("confirmed")], ["gate-fallback"])

    def test_graphsage_still_wins_when_it_agrees(self):
        h = Harness(fallback=True).arm().feed(30, HOT)
        self.assertEqual([e.detection for e in h.kinds("confirmed")], ["graphsage"])

    def test_fallback_still_needs_consecutive_polls(self):
        h = Harness(anomaly_fn=blind_anomaly, fallback=True).arm()
        h.feed(2, MEM).feed(1).feed(2, MEM).feed(20)
        self.assertEqual(h.kinds("confirmed"), [])
        self.assertEqual(Harness(anomaly_fn=blind_anomaly, fallback=True).arm().feed(30).kinds("confirmed"), [])

    def test_gate_ranking_puts_down_first_then_largest_deviation(self):
        rng = random.Random(3)
        baseline = [_snap(rng) for _ in range(8)]
        both = {**MEM, **CRASH}
        ranked = gate_ranking({"baseline_history": baseline, "failure_history": [_snap(rng, both) for _ in range(3)]})
        self.assertEqual([s.service_id for s in ranked[:2]], ["inventory-service", "search-service"])
        self.assertEqual([s.rank for s in ranked], list(range(1, len(ranked) + 1)))
        self.assertEqual(ranked[0].anomaly_score, 1.0)
        self.assertEqual(ranked[1].anomaly_score, 1.0)   # (0.57 - 0.10) / 0.05 = 9.4 >= 2 x gate
        self.assertEqual([s.status for s in ranked[:3]], ["anomalous", "anomalous", "normal"])
        self.assertTrue(all(0.0 <= s.anomaly_score <= 1.0 for s in ranked))

        ranked = gate_ranking({"baseline_history": baseline, "failure_history": [_snap(rng, MEM) for _ in range(3)]})
        self.assertEqual(ranked[0].service_id, "search-service")
        self.assertTrue(all(s.status == "normal" for s in ranked[1:]))


class ResultTest(unittest.TestCase):
    def _scores(self):
        ids = ["auth-service", "order-service", "user-service", "cache", "frontend", "search-service"]
        return [SimpleNamespace(service_id=s, anomaly_score=0.9 - 0.1 * i,
                                status="anomalous" if i < 2 else "normal", rank=i + 1) for i, s in enumerate(ids)]

    def test_build_result_has_every_key_transform_demo_result_reads(self):
        js = (ROOT / "dashboard/src/data/transformDemoResult.js").read_text()
        body = js.split("export function transformDemoResult", 1)[1].split("\n}\n", 1)[0]
        read_keys = set(re.findall(r"raw\.(\w+)", body))
        self.assertIn("ppo_dispatch", read_keys)

        scores = self._scores()
        dispatch = {"agent_type": "log", "target_service": "auth-service", "policy_confidence": 0.8}
        investigation = {"evidence_bundle": {"x": 1}, "report": {"root_cause_service": "auth-service"}}
        result = build_result("auto_1", "t", scores, scores, scores[:2], dispatch,
                              {"target_service": "auth-service", "fault_type": "cpu_stress"}, investigation)
        optional = {"edges", "fault_reports"}  # fault_reports: multi-fault runs only
        self.assertTrue(read_keys - optional <= set(result), read_keys - set(result))
        self.assertEqual(set(result["ppo_dispatch"]), {"agent_type", "target_service", "policy_confidence"})
        self.assertEqual(set(result["nodes"][0]), {"service_id", "anomaly_score", "status", "rank"})
        self.assertEqual(result["metrics"]["pr_at_1"], 1.0)
        self.assertEqual(result["fault_type"], "cpu_stress")
        self.assertEqual(result["ground_truth"], "fault-status")
        self.assertEqual(result["detection"], "graphsage")
        self.assertEqual(result["metrics"]["ranking"], "graphsage_raw")

    def test_build_result_marks_gate_fallback(self):
        scores = self._scores()
        result = build_result("auto_1", "t", scores, scores, [], {"agent_type": "log", "target_service": "x",
                              "policy_confidence": 0.1}, None, detection="gate-fallback",
                              detection_info={"detected_at": "t", "fallback_enabled": True})
        self.assertEqual(result["detection"], "gate-fallback")
        self.assertEqual(result["metrics"]["ranking"], "gate_fallback")
        self.assertTrue(result["detection_info"]["fallback_enabled"])

    def test_interim_and_unknown_ground_truth(self):
        scores = self._scores()
        result = build_result("auto_1", "t", scores, scores, [], {"agent_type": "log", "target_service": "x",
                              "policy_confidence": 0.1}, None, fault_injection_state="active")
        self.assertIsNone(result["report"])
        self.assertEqual(result["fault_injection_state"], "active")
        self.assertEqual(result["ground_truth"], "unavailable")
        self.assertEqual(result["injected_target"], "unknown")
        self.assertEqual({result["metrics"][k] for k in ("pr_at_1", "pr_at_3", "pr_at_5")}, {0.0})

    def test_ground_truth_needs_exactly_one_active_target(self):
        a = {"target_service": "auth-service", "fault_type": "cpu_stress"}
        b = {"target_service": "order-service", "fault_type": "pod_crash"}
        self.assertEqual(resolve_ground_truth([a], [a]), a)
        self.assertEqual(resolve_ground_truth([a], []), a)
        self.assertIsNone(resolve_ground_truth([], []))
        self.assertIsNone(resolve_ground_truth([a], [b]))

    def test_baseline_buffer_rolls(self):
        buf = BaselineBuffer(3)
        for i in range(5):
            buf.add({"i": i}, at=100.0 + i)
        self.assertEqual([s["i"] for s in buf.snapshots()], [2, 3, 4])
        self.assertEqual(buf.started_at(), 102.0)
        buf.clear()
        self.assertIsNone(buf.started_at())

    def test_baseline_started_at_bounds_each_incident_log_window(self):
        # Logs are pulled with `docker logs --since telemetry["baseline_started_at"]`;
        # the second incident's window must start after the first incident ended.
        h = Harness(min_gap_sec=0).arm().feed(30, HOT)
        first = h.kinds("incident")[0].telemetry
        self.assertEqual(first["baseline_started_at"], "2023-11-14T22:13:20Z")  # epoch 1_700_000_000
        first_end = h.now
        h.feed(12).feed(30, HOT)
        incidents = h.kinds("incident")
        self.assertEqual(len(incidents), 2)
        second = incidents[1].telemetry["baseline_started_at"]
        self.assertRegex(second, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertGreater(second, _iso(1_700_000_000 + first_end))


if __name__ == "__main__":
    unittest.main()
