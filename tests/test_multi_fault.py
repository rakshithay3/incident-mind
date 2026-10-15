import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from incidentmind_p1.contracts import DispatchAction, DispatchDecision, NodeScore
from multi_fault import detect_multi_fault, investigate_faults
from notifications.rounds import run_recovery_rounds


def _scores(n_anomalous, ids=("auth-service", "payment-service", "order-service", "user-service")):
    return [NodeScore(service_id=s, anomaly_score=round(0.9 - 0.1 * i, 2), embedding_dim=8,
                      status="anomalous" if i < n_anomalous else "normal", rank=i + 1)
            for i, s in enumerate(ids)]


def _inv(target):
    return {"report": {"root_cause_service": target, "confidence_score": 0.7}, "evidence_bundle": {"svc": target}}


class InvestigateFaultsTest(unittest.TestCase):
    def test_dual_fault_reports_each_flagged_service_reusing_the_ppo_target(self):
        flagged = detect_multi_fault(_scores(2))
        investigations = {"auth-service": _inv("auth-service")}
        calls = []
        reports = investigate_faults(flagged, investigations, lambda s: calls.append(s) or _inv(s))

        self.assertEqual(calls, ["payment-service"])  # PPO target's agents are not re-run
        self.assertEqual([r["service"] for r in reports], ["auth-service", "payment-service"])
        self.assertEqual([r["score"] for r in reports], [0.9, 0.8])
        self.assertEqual([r["report"]["root_cause_service"] for r in reports], ["auth-service", "payment-service"])
        self.assertEqual(set(reports[0]), {"service", "score", "report"})
        self.assertIn("payment-service", investigations)

    def test_ppo_target_not_flagged_is_left_out(self):
        flagged = detect_multi_fault(_scores(2, ids=("payment-service", "order-service", "auth-service")))
        reports = investigate_faults(flagged, {"auth-service": _inv("auth-service")}, _inv)
        self.assertEqual([r["service"] for r in reports], ["payment-service", "order-service"])

    def test_reuses_reinvestigation_rounds(self):
        ranked = _scores(2)
        investigations = {"auth-service": _inv("auth-service")}

        def investigate(target):
            investigations[target] = _inv(target)
            return investigations[target]

        outcome = run_recovery_rounds(
            "auth-service", investigations["auth-service"], ranked,
            wait=lambda r: {"recovered": r == 2, "restored_at": "t" if r == 2 else None, "still_unhealthy": []},
            rescore=lambda r: ranked,
            choose=lambda rk, visited, step: DispatchDecision(
                step=step, action=DispatchAction(agent_type="log", target_service="payment-service"),
                policy_confidence=0.5),
            investigate=lambda target, r: investigate(target), log=lambda m: None,
        )
        self.assertEqual(outcome["services_tried"], ["auth-service", "payment-service"])
        reports = investigate_faults(detect_multi_fault(outcome["ranked"]), investigations,
                                     lambda s: self.fail(f"{s} was already investigated"))
        self.assertEqual([r["service"] for r in reports], ["auth-service", "payment-service"])

    def test_single_fault_runs_no_extra_agents(self):
        for n in (0, 1):
            flagged = detect_multi_fault(_scores(n))
            self.assertIsNone(investigate_faults(flagged, {}, lambda s: self.fail("no extra agents")))


class BuildResultFaultReportsTest(unittest.TestCase):
    DISPATCH = {"agent_type": "log", "target_service": "auth-service", "policy_confidence": 0.8}

    def test_dual_fault_result_keeps_ppo_report_on_top(self):
        from incident_watcher import build_result

        scores = _scores(2)
        flagged = detect_multi_fault(scores)
        reports = investigate_faults(flagged, {"auth-service": _inv("auth-service")}, _inv)
        res = build_result("inc", "t", scores, scores, flagged, self.DISPATCH, None,
                           investigation=_inv("auth-service"), fault_reports=reports)
        self.assertEqual(res["report"]["root_cause_service"], "auth-service")
        self.assertEqual([r["service"] for r in res["fault_reports"]],
                         [s["service_id"] for s in res["multi_fault_detected"]])

    def test_single_fault_result_unchanged(self):
        from incident_watcher import build_result

        scores = _scores(1)
        flagged = detect_multi_fault(scores)
        args = ("inc", "t", scores, scores, flagged, self.DISPATCH, None)
        before = build_result(*args, investigation=_inv("auth-service"))
        after = build_result(*args, investigation=_inv("auth-service"),
                             fault_reports=investigate_faults(flagged, {}, _inv))
        self.assertNotIn("fault_reports", after)
        self.assertEqual(before, after)


class ReplayDemoMultiFaultTest(unittest.TestCase):
    """replay_demo.main() end to end with the models and agents faked out."""

    def _run(self, n_anomalous):
        import replay_demo

        scores = _scores(n_anomalous)
        calls = []

        def investigate_service(target, *a):
            calls.append(target)
            return _inv(target)

        decision = DispatchDecision(step=1, action=DispatchAction(agent_type="log", target_service="auth-service"),
                                    policy_confidence=0.6)
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "telemetry_series.json").write_text(json.dumps(
                {"incident_id": "inc_mf", "fault_type": "cpu_stress", "target_service": "auth-service",
                 "failure_history": [{}]}))
            out = Path(d) / "result.json"
            argv = ["replay_demo.py", "--incident-dir", d, "--output", str(out), "--no-notify"]
            scorer = SimpleNamespace(score_graph=lambda g: list(scores))
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(replay_demo, "compile_live_snapshot",
                                      return_value=SimpleNamespace(incident_id="inc_mf", timestamp="t", nodes=[])), \
                    mock.patch.object(replay_demo, "load_checkpoint", return_value=(None, None)), \
                    mock.patch.object(replay_demo, "GraphSAGEScorer", return_value=scorer), \
                    mock.patch.object(replay_demo, "PriorityWeightedScorer", return_value=scorer), \
                    mock.patch.object(replay_demo, "PPODispatcher",
                                      return_value=SimpleNamespace(choose=lambda *a, **k: decision)), \
                    mock.patch("stable_baselines3.PPO.load", return_value=None), \
                    mock.patch.object(replay_demo, "investigate_service", side_effect=investigate_service), \
                    mock.patch("builtins.print"):
                replay_demo.main()
            return json.loads(out.read_text()), calls

    def test_dual_fault_writes_one_report_per_flagged_service(self):
        result, calls = self._run(2)
        self.assertEqual(calls, ["auth-service", "payment-service"])
        self.assertEqual(result["report"]["root_cause_service"], "auth-service")
        self.assertEqual([(r["service"], r["report"]["root_cause_service"]) for r in result["fault_reports"]],
                         [("auth-service", "auth-service"), ("payment-service", "payment-service")])

    def test_single_fault_has_no_fault_reports(self):
        result, calls = self._run(1)
        self.assertEqual(calls, ["auth-service"])
        self.assertNotIn("fault_reports", result)


if __name__ == "__main__":
    unittest.main()
