import tempfile
import unittest
from pathlib import Path

from incidentmind_p1.contracts import DispatchAction, DispatchDecision, NodeScore
from notifications.notifier import NotificationConfig, Notifier
from notifications.recovery_sim import SCENARIOS, SNAPSHOT_FIELDS, simulated_snapshot
from notifications.rounds import notify_rounds_outcome, run_recovery_rounds

SERVICES = ["auth-service", "payment-service", "order-service", "cart-service"]
BASE = {
    "auth-service": dict(cpu_pct=0.05, mem_pct=0.20, error_rate=0.0, mean_latency_ms=12.0, p99_latency_ms=40.0),
    "payment-service": dict(cpu_pct=0.03, mem_pct=0.15, error_rate=0.0, mean_latency_ms=20.0, p99_latency_ms=70.0),
    "order-service": dict(cpu_pct=0.04, mem_pct=0.25, error_rate=0.0, mean_latency_ms=18.0, p99_latency_ms=60.0),
}
EDGES = [{"source": "order-service", "target": "payment-service", "call_count": 5},
         {"source": "order-service", "target": "auth-service", "call_count": 3}]
TELEMETRY = {
    "incident_id": "inc_rounds",
    "target_service": "auth-service",
    "baseline_history": [{"timestamp": f"t{i}", "nodes": [{"service_id": s, **v} for s, v in BASE.items()],
                          "edges": EDGES} for i in range(3)],
}
RECIPIENTS = {"recipients": [{"email": "priya@gmail.com", "name": "Priya"}], "source": "test"}
TIMEOUT = 60.0


def _ranked(order=SERVICES):
    return [NodeScore(service_id=s, anomaly_score=1.0 - 0.1 * i, embedding_dim=8, status="anomalous", rank=i + 1)
            for i, s in enumerate(order)]


def _decision(target, step):
    return DispatchDecision(step=step, action=DispatchAction(agent_type="log", target_service=target),
                            policy_confidence=0.5)


def _recovery(ok):
    if ok:
        return {"recovered": True, "restored_at": "2026-10-15T10:00:00+00:00", "polls": 4,
                "still_unhealthy": [], "outcome": "recovered"}
    return {"recovered": False, "restored_at": None, "polls": 13,
            "still_unhealthy": ["auth-service"], "outcome": "relapsed"}


class Harness:
    """Fakes for the expensive parts; records every call."""

    def __init__(self, recover_on=None, pick=None):
        self.recover_on = recover_on  # round number that recovers (None = never)
        self.pick = pick or (lambda ranked, visited: next(s.service_id for s in ranked if s.service_id not in visited))
        self.waits, self.investigated, self.choose_calls = [], [], []

    def wait(self, r):
        self.waits.append(r)
        return _recovery(r == self.recover_on)

    def rescore(self, r):
        return _ranked()

    def choose(self, ranked, visited, step):
        self.choose_calls.append((set(visited), step))
        return _decision(self.pick(ranked, visited), step)

    def investigate(self, target, r):
        self.investigated.append((target, r))
        return {"report": {"root_cause_service": target}, "evidence_bundle": {"round": r}}

    def run(self, max_rounds=3):
        return run_recovery_rounds(
            "auth-service", {"report": {"root_cause_service": "auth-service"}}, _ranked(),
            wait=self.wait, rescore=self.rescore, choose=self.choose, investigate=self.investigate,
            max_rounds=max_rounds, log=lambda m: None,
        )


class RoundsLoopTest(unittest.TestCase):
    def test_first_round_recovery_needs_no_reinvestigation(self):
        h = Harness(recover_on=1)
        out = h.run()
        self.assertTrue(out["recovered"])
        self.assertEqual(h.waits, [1])
        self.assertEqual(h.investigated, [])
        self.assertIsNone(out["decision"])
        self.assertEqual(len(out["rounds"]), 1)

    def test_stops_on_first_recovery(self):
        h = Harness(recover_on=2)
        out = h.run(max_rounds=5)
        self.assertTrue(out["recovered"])
        self.assertEqual(h.waits, [1, 2])
        self.assertEqual(h.investigated, [("payment-service", 2)])
        self.assertEqual([(r["round"], r["target_service"], r["recovery"]["outcome"]) for r in out["rounds"]],
                         [(1, "auth-service", "relapsed"), (2, "payment-service", "recovered")])
        self.assertEqual(out["rounds"][1]["report_root_cause"], "payment-service")
        self.assertEqual(out["target"], "payment-service")
        self.assertEqual(out["investigation"]["evidence_bundle"], {"round": 2})

    def test_respects_max_rounds(self):
        for max_rounds in (1, 2, 3):
            with self.subTest(max_rounds=max_rounds):
                h = Harness(recover_on=None)
                out = h.run(max_rounds=max_rounds)
                self.assertFalse(out["recovered"])
                self.assertEqual(h.waits, list(range(1, max_rounds + 1)))
                self.assertEqual(len(out["rounds"]), max_rounds)
                self.assertEqual(len(h.investigated), max_rounds - 1)

    def test_choose_gets_visited_and_round_step(self):
        h = Harness(recover_on=None)
        h.run(max_rounds=3)
        self.assertEqual(h.choose_calls, [({"auth-service"}, 2), ({"auth-service", "payment-service"}, 3)])

    def test_never_repicks_a_visited_service(self):
        # A policy that always lands on the top-ranked (already visited) node.
        h = Harness(recover_on=None, pick=lambda ranked, visited: ranked[0].service_id)
        out = h.run(max_rounds=4)
        tried = [r["target_service"] for r in out["rounds"]]
        self.assertEqual(len(tried), len(set(tried)))
        self.assertEqual(tried, ["auth-service", "payment-service", "order-service", "cart-service"])
        self.assertEqual(out["services_tried"], tried)

    def test_stops_when_every_service_investigated(self):
        h = Harness(recover_on=None)
        h.rescore = lambda r: _ranked(["auth-service", "payment-service"])
        out = h.run(max_rounds=5)
        self.assertEqual(out["services_tried"], ["auth-service", "payment-service"])
        self.assertEqual(len(out["rounds"]), 2)

    def test_rounds_entry_records_top5_ranking_and_logs_pick(self):
        logs = []
        h = Harness(recover_on=2)
        h.rescore = lambda r: _ranked(["order-service", "auth-service", "payment-service", "cart-service",
                                       "user-service", "ship-service"])
        out = run_recovery_rounds(
            "auth-service", {"report": {"root_cause_service": "auth-service"}}, _ranked(),
            wait=h.wait, rescore=h.rescore, choose=h.choose, investigate=h.investigate, log=logs.append,
        )
        self.assertIsNone(out["rounds"][0]["ranking"])
        self.assertEqual(out["rounds"][1]["ranking"], [
            {"service": "order-service", "score": 1.0},
            {"service": "auth-service", "score": 0.9},
            {"service": "payment-service", "score": 0.8},
            {"service": "cart-service", "score": 0.7},
            {"service": "user-service", "score": 0.6},
        ])
        self.assertIn("  [round 2] ranking: order-service 1.000, auth-service 0.900, payment-service 0.800, "
                      "cart-service 0.700, user-service 0.600 | visited: auth-service | PPO picked order-service",
                      logs)

    def test_failed_rescore_keeps_previous_ranking(self):
        h = Harness(recover_on=2)

        def boom(r):
            raise ConnectionError("telemetry down")
        h.rescore = boom
        out = h.run()
        self.assertTrue(out["recovered"])
        self.assertEqual(out["target"], "payment-service")


class NotifyOnceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.notifier = Notifier(NotificationConfig(), output_dir=self.out)  # dry run: one .eml per user

    def tearDown(self):
        self.tmp.cleanup()

    def _notify(self, outcome):
        return notify_rounds_outcome(self.notifier, "inc_rounds", outcome, lambda: RECIPIENTS,
                                     "2026-10-15T09:55:00Z", TIMEOUT)

    def test_email_sent_once_when_a_later_round_recovers(self):
        entries = self._notify(Harness(recover_on=2).run())
        self.assertEqual([e["status"] for e in entries], ["dry_run"])
        self.assertEqual(len(list(self.out.glob("*.eml"))), 1)
        self.assertEqual(len(self.notifier.history), 1)

    def test_no_email_when_every_round_fails(self):
        entries = self._notify(Harness(recover_on=None).run(max_rounds=3))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["status"], "skipped")
        self.assertEqual(entries[0]["details"]["services_tried"],
                         ["auth-service", "payment-service", "order-service"])
        self.assertIn("auth-service, payment-service, order-service", entries[0]["reason"])
        self.assertEqual(list(self.out.glob("*.eml")), [])
        self.assertEqual(len(self.notifier.history), 1)


class SimulatorRoundsTest(unittest.TestCase):
    def test_scenario_registered(self):
        self.assertIn("recovers_round2", SCENARIOS)

    def test_snapshot_has_all_graphsage_inputs(self):
        snap = simulated_snapshot("persistent", TELEMETRY)
        self.assertEqual(snap["edges"], EDGES)
        for node in snap["nodes"]:
            for f in SNAPSHOT_FIELDS:
                self.assertIn(f, node)
        self.assertIn("mean_latency_ms", SNAPSHOT_FIELDS)

    def test_snapshot_none_when_telemetry_down(self):
        self.assertIsNone(simulated_snapshot("telemetry", TELEMETRY))

    def test_recovers_round2_end_to_end(self):
        """Simulated polling + real compile/re-score path (fake GraphSAGE) +
        the rounds loop + dry-run notifier."""
        import replay_demo

        class FakeScorer:  # anomaly = error_rate deviation, enough to rank the broken node first
            def score_graph(self, graph):
                ordered = sorted(graph.nodes, key=lambda n: -n.features["error_rate"])
                return [NodeScore(n.service_id, n.features["error_rate"], 8,
                                  "anomalous" if n.features["error_rate"] > 0.05 else "normal", i + 1)
                        for i, n in enumerate(ordered)]

        rescored = []

        def rescore(r):
            ranked = replay_demo.rescore_snapshot(replay_demo.fresh_snapshot(TELEMETRY, "recovers_round2", r),
                                                  TELEMETRY, FakeScorer())
            rescored.append(ranked)
            return ranked

        h = Harness()
        out = run_recovery_rounds(
            "auth-service", {"report": {"root_cause_service": "auth-service"}}, _ranked(),
            wait=lambda r: replay_demo._wait_for_shopmind(TELEMETRY, TIMEOUT, 5.0, simulate="recovers_round2",
                                                          round_no=r),
            rescore=rescore, choose=h.choose, investigate=h.investigate, log=lambda m: None,
        )
        self.assertEqual(rescored[0][0].service_id, "auth-service")  # relapsed node scores highest
        self.assertEqual([(r["round"], r["recovery"]["outcome"]) for r in out["rounds"]],
                         [(1, "relapsed"), (2, "recovered")])
        self.assertNotEqual(out["rounds"][1]["target_service"], "auth-service")
        with tempfile.TemporaryDirectory() as tmp:
            notifier = Notifier(NotificationConfig(), output_dir=Path(tmp))
            entries = notify_rounds_outcome(notifier, "inc_rounds", out, lambda: RECIPIENTS, None, TIMEOUT)
            self.assertEqual([e["status"] for e in entries], ["dry_run"])


class FaultStartedAtTest(unittest.TestCase):
    def test_epoch_snapshot_timestamp_becomes_iso(self):
        import replay_demo

        self.assertEqual(replay_demo._fault_started_at({"failure_history": [{"timestamp": 1788787195.33}]}),
                         "2026-09-07T13:19:55+00:00")
        self.assertEqual(replay_demo._fault_started_at({"failure_history": [{"timestamp": "2026-09-07T18:49:54Z"}]}),
                         "2026-09-07T18:49:54Z")


class ResultSchemaTest(unittest.TestCase):
    def test_build_result_has_rounds(self):
        from incident_watcher import build_result

        rounds = Harness(recover_on=2).run()["rounds"]
        res = build_result("inc", "t", _ranked(), _ranked(), [], {"agent_type": "log",
                           "target_service": "payment-service", "policy_confidence": 0.5}, None,
                           recovery=rounds[-1]["recovery"], rounds=rounds)
        self.assertEqual([r["target_service"] for r in res["rounds"]], ["auth-service", "payment-service"])
        self.assertEqual(set(res["rounds"][0]), {"round", "target_service", "report_root_cause", "recovery", "ranking"})
        self.assertEqual(build_result("inc", "t", [], [], [], {}, None)["rounds"], [])


if __name__ == "__main__":
    unittest.main()
