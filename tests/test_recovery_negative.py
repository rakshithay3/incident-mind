import tempfile
import unittest
from pathlib import Path

from notifications.notifier import NotificationConfig, Notifier
from notifications.recovery import wait_for_recovery
from notifications.recovery_sim import SCENARIOS, make_collector, simulate_recovery

BASE = {
    "auth-service": dict(cpu_pct=0.05, mem_pct=0.20, error_rate=0.0, p99_latency_ms=40.0),
    "order-service": dict(cpu_pct=0.04, mem_pct=0.25, error_rate=0.0, p99_latency_ms=60.0),
    "cache": dict(cpu_pct=0.0, mem_pct=0.0, error_rate=0.0, p99_latency_ms=0.0),
}
TELEMETRY = {
    "target_service": "auth-service",
    "baseline_history": [{"nodes": [{"service_id": s, **v} for s, v in BASE.items()]} for _ in range(3)],
}
TIMEOUT, INTERVAL, CONSECUTIVE = 60.0, 5.0, 3
TIMEOUT_POLLS = int(TIMEOUT // INTERVAL) + 1  # polls at t=0, 5, ..., 60

# scenario -> (recovered, outcome, polls, still_unhealthy)
EXPECTED = {
    "persistent": (False, "not_recovered", TIMEOUT_POLLS, ["auth-service", "order-service"]),
    "partial": (False, "partial", TIMEOUT_POLLS, ["auth-service"]),
    "relapse": (False, "relapsed", TIMEOUT_POLLS, ["auth-service"]),
    "crash_loop": (False, "not_recovered", TIMEOUT_POLLS, ["auth-service"]),
    "telemetry": (False, "not_recovered", TIMEOUT_POLLS, ["telemetry error: ConnectionError"]),
    "late": (False, "not_recovered", TIMEOUT_POLLS, ["auth-service", "order-service"]),
    "recovers": (True, "recovered", 1 + CONSECUTIVE, []),
    "recovers_round2": (False, "relapsed", TIMEOUT_POLLS, ["auth-service"]),  # round 1 plays "relapse"
}
NEGATIVE = [s for s in SCENARIOS if s != "recovers"]


def _sim(scenario, **kw):
    return simulate_recovery(scenario, TELEMETRY, timeout_sec=TIMEOUT, interval_sec=INTERVAL,
                             consecutive=CONSECUTIVE, log=lambda m: None, **kw)


def _wait(collect):
    t = [0.0]
    return wait_for_recovery(TELEMETRY["baseline_history"], collect, timeout_sec=TIMEOUT, interval_sec=INTERVAL,
                             consecutive=CONSECUTIVE, sleep=lambda s: t.__setitem__(0, t[0] + s),
                             clock=lambda: t[0], log=lambda m: None)


def _nodes(**overrides):
    return [{"service_id": s, **{**v, **overrides.get(s, {})}} for s, v in BASE.items()]


class ScenarioTest(unittest.TestCase):
    def assertScenario(self, scenario):
        recovered, outcome, polls, still = EXPECTED[scenario]
        res = _sim(scenario)
        self.assertEqual(res["recovered"], recovered)
        self.assertEqual(res["outcome"], outcome)
        self.assertEqual(res["polls"], polls)
        self.assertEqual(res["still_unhealthy"], still)
        self.assertEqual(res["simulated"], scenario)
        # existing keys are kept
        for key in ("recovered", "restored_at", "polls", "still_unhealthy"):
            self.assertIn(key, res)
        self.assertEqual(res["restored_at"] is not None, recovered)
        return res

    def test_persistent(self):
        res = self.assertScenario("persistent")
        self.assertEqual((res["relapses"], res["best_streak"]), (0, 0))

    def test_partial(self):
        res = self.assertScenario("partial")
        self.assertEqual((res["relapses"], res["best_streak"]), (0, 0))

    def test_relapse(self):
        res = self.assertScenario("relapse")
        self.assertEqual(res["relapses"], 1)
        self.assertEqual(res["best_streak"], CONSECUTIVE - 1)

    def test_crash_loop(self):
        self.assertScenario("crash_loop")

    def test_telemetry(self):
        self.assertScenario("telemetry")

    def test_late(self):
        res = self.assertScenario("late")
        self.assertEqual(res["best_streak"], 0)

    def test_recovers(self):
        res = self.assertScenario("recovers")
        self.assertEqual((res["relapses"], res["best_streak"]), (0, CONSECUTIVE))

    def test_every_scenario_has_expectation(self):
        self.assertEqual(set(EXPECTED), set(SCENARIOS))

    def test_unknown_scenario_rejected(self):
        with self.assertRaises(ValueError):
            make_collector("nope", TELEMETRY["baseline_history"])

    def test_unknown_target_falls_back_to_an_app_service(self):
        res = _sim("crash_loop", target="unknown")
        self.assertEqual(len(res["still_unhealthy"]), 1)
        self.assertNotEqual(res["still_unhealthy"], ["cache"])


class OutcomeRulesTest(unittest.TestCase):
    def test_wrong_service_fixed_real_fault_remains(self):
        # The RCA blamed order-service and it got fixed, but the real fault
        # (auth-service errors) never went away: users must not be told it's fixed.
        polls = [0]

        def collect():
            polls[0] += 1
            broken = {"auth-service": {"error_rate": 0.4}}
            if polls[0] == 1:
                broken["order-service"] = {"p99_latency_ms": 900.0}
            return _nodes(**broken)

        res = _wait(collect)
        self.assertFalse(res["recovered"])
        self.assertEqual(res["outcome"], "partial")
        self.assertEqual(res["still_unhealthy"], ["auth-service"])
        self.assertEqual(res["polls"], TIMEOUT_POLLS)

    def test_telemetry_error_does_not_count_as_partial(self):
        # two real failures, then telemetry dies: one "telemetry error" entry
        # is fewer than two services, but it's no improvement
        polls = [0]

        def collect():
            polls[0] += 1
            if polls[0] > 1:
                raise ConnectionError("down")
            return _nodes(**{"auth-service": {"cpu_pct": None}, "order-service": {"error_rate": 0.4}})

        res = _wait(collect)
        self.assertEqual(res["outcome"], "not_recovered")
        self.assertEqual(res["still_unhealthy"], ["telemetry error: ConnectionError"])

    def test_telemetry_error_first_poll_is_not_the_reference(self):
        polls = [0]

        def collect():
            polls[0] += 1
            if polls[0] == 1:
                raise ConnectionError("down")
            return _nodes(**{"auth-service": {"cpu_pct": None}})

        res = _wait(collect)
        self.assertEqual(res["outcome"], "not_recovered")
        self.assertEqual(res["still_unhealthy"], ["auth-service"])


class NotifierNegativeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_email_for_any_negative(self):
        for scenario in NEGATIVE:
            with self.subTest(scenario=scenario):
                # enabled, no SMTP creds: notify_restored would write .eml drafts here
                n = Notifier(NotificationConfig(), output_dir=self.out)
                res = _sim(scenario)
                self.assertFalse(res["recovered"])
                entry = n.notify_not_recovered(f"inc-{scenario}", res["still_unhealthy"], TIMEOUT)
                self.assertEqual(entry["status"], "skipped")
                self.assertEqual(entry["sent_count"], 0)
                self.assertEqual(list(self.out.glob("*.eml")), [])


class ReplayRoutingTest(unittest.TestCase):
    def test_simulate_routes_to_simulator(self):
        import replay_demo

        res = replay_demo._wait_for_shopmind(TELEMETRY, TIMEOUT, INTERVAL, simulate="partial")
        self.assertEqual(res["simulated"], "partial")
        self.assertEqual(res["outcome"], "partial")


if __name__ == "__main__":
    unittest.main()
