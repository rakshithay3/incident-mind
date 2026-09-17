import email
import json
import tempfile
import unittest
from pathlib import Path

from notifications.notifier import NotificationConfig, Notifier, affected_area, build_restored_email
from notifications.recipients import filter_users, get_recipients
from notifications.recovery import baseline_means, unhealthy_services, wait_for_recovery

USERS = [
    {"id": "1", "username": "admin", "role": "admin", "name": "Admin", "email": "admin@shopmind.io"},
    {"id": "2", "username": "archie", "role": "member", "name": "Archie", "email": "archie@example.com"},
    {"id": "10", "username": "priya", "role": "member", "name": "Priya", "email": "priya@gmail.com"},
    {"id": "11", "username": "ravi", "role": "member", "name": "Ravi", "email": "RAVI@outlook.com"},
    {"id": "g", "username": "Guest_1", "role": "guest", "name": "Guest", "email": "guest1234@gmail.com"},
    {"id": "12", "username": "bad", "role": "member", "name": "Bad", "email": "not-an-email"},
]

RECIPIENTS = [{"email": "priya@gmail.com", "name": "Priya"}, {"email": "ravi@outlook.com", "name": "Ravi"}]


class FakeSMTP:
    sent = []
    fail_login = False

    def __init__(self, host, port):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        if FakeSMTP.fail_login:
            raise OSError("auth failed")

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def _send_cfg(**kw):
    cfg = NotificationConfig(smtp_user="bot@gmail.com", smtp_password="pw", sender="bot@gmail.com")
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


class RecipientsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name) / "cache.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_filters_guests_placeholders_invalid(self):
        out = filter_users(USERS, {"shopmind.io", "example.com"})
        self.assertEqual([r["email"] for r in out], ["priya@gmail.com", "RAVI@outlook.com"])

    def test_cache_survives_auth_service_restart(self):
        env = {}
        first = get_recipients(env, self.cache, fetch=lambda url: USERS)
        self.assertEqual(first["source"], "live")
        self.assertEqual(len(first["recipients"]), 2)

        # pod_crash restarts auth-service: only seeded accounts come back
        seeded_only = USERS[:2]
        after = get_recipients(env, self.cache, fetch=lambda url: seeded_only)
        self.assertEqual(len(after["recipients"]), 2)
        self.assertEqual(after["source"], "live+cache")

        down = get_recipients(env, self.cache, fetch=lambda url: None)
        self.assertEqual(down["source"], "cache")
        self.assertEqual(len(down["recipients"]), 2)

    def test_extra_addresses_included_not_cached(self):
        env = {"IM_NOTIFY_TO": "me@gmail.com"}
        out = get_recipients(env, self.cache, fetch=lambda url: USERS)
        self.assertIn("me@gmail.com", [r["email"] for r in out["recipients"]])
        self.assertNotIn("me@gmail.com", self.cache.read_text())


def _snap(**overrides):
    base = {
        "auth-service": dict(cpu_pct=0.05, mem_pct=0.20, error_rate=0.0, p99_latency_ms=40.0),
        "order-service": dict(cpu_pct=0.04, mem_pct=0.25, error_rate=0.0, p99_latency_ms=60.0),
        "cache": dict(cpu_pct=0.0, mem_pct=0.0, error_rate=0.0, p99_latency_ms=0.0),
    }
    nodes = []
    for sid, vals in base.items():
        vals = {**vals, **overrides.get(sid, {})}
        nodes.append({"service_id": sid, **vals})
    return nodes


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.history = [{"nodes": _snap()} for _ in range(3)]
        self.baseline = baseline_means(self.history)

    def test_healthy_snapshot(self):
        self.assertEqual(unhealthy_services(_snap(), self.baseline), [])

    def test_detects_cpu_crash_and_errors(self):
        self.assertEqual(unhealthy_services(_snap(**{"auth-service": {"cpu_pct": 0.9}}), self.baseline), ["auth-service"])
        self.assertEqual(unhealthy_services(_snap(**{"auth-service": {"cpu_pct": None}}), self.baseline), ["auth-service"])
        self.assertEqual(unhealthy_services(_snap(**{"order-service": {"error_rate": 0.3}}), self.baseline), ["order-service"])

    def test_waits_for_consecutive_healthy_polls(self):
        seq = [_snap(**{"auth-service": {"cpu_pct": 0.95}})] * 2 + [_snap()] * 3
        it = iter(seq)
        t = [0.0]
        res = wait_for_recovery(self.history, lambda: next(it), timeout_sec=100, interval_sec=5,
                                consecutive=3, sleep=lambda s: t.__setitem__(0, t[0] + s),
                                clock=lambda: t[0], log=lambda m: None)
        self.assertTrue(res["recovered"])
        self.assertEqual(res["polls"], 5)

    def test_times_out_while_still_broken(self):
        t = [0.0]
        res = wait_for_recovery(self.history, lambda: _snap(**{"auth-service": {"cpu_pct": None}}),
                                timeout_sec=20, interval_sec=5, sleep=lambda s: t.__setitem__(0, t[0] + s),
                                clock=lambda: t[0], log=lambda m: None)
        self.assertFalse(res["recovered"])
        self.assertEqual(res["still_unhealthy"], ["auth-service"])


class NotifierTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        FakeSMTP.sent = []
        FakeSMTP.fail_login = False

    def tearDown(self):
        self.tmp.cleanup()

    def test_email_is_customer_friendly(self):
        e = build_restored_email("Priya", affected_area("payment-service"), "2026-09-17T09:00:00Z",
                                 "2026-09-17T09:04:00Z", "http://localhost:3000")
        self.assertEqual(e["subject"], "ShopMind is back to normal")
        self.assertIn("Hi Priya,", e["text"])
        self.assertIn("checkout and payments", e["text"])
        for internal in ("payment-service", "root cause", "anomaly", "IncidentMind", "confidence"):
            self.assertNotIn(internal, e["text"])

    def test_sends_one_personal_email_per_user(self):
        n = Notifier(_send_cfg(), output_dir=self.out, smtp_factory=FakeSMTP)
        entry = n.notify_restored("live_001", RECIPIENTS, "auth-service",
                                  "2026-09-17T09:00:00Z", "2026-09-17T09:03:00Z", "live")
        self.assertEqual(entry["status"], "sent")
        self.assertEqual((entry["recipients_count"], entry["sent_count"]), (2, 2))
        self.assertEqual(entry["details"]["downtime_sec"], 180)
        self.assertEqual([m["To"] for m in FakeSMTP.sent], ["priya@gmail.com", "ravi@outlook.com"])
        self.assertIn("Hi Ravi,", FakeSMTP.sent[1].get_body(("plain",)).get_content())
        self.assertNotIn("priya@gmail.com", json.dumps(entry))  # status dict holds counts only

    def test_old_replay_omits_time_window(self):
        n = Notifier(_send_cfg(), output_dir=self.out, smtp_factory=FakeSMTP)
        n.notify_restored("old", RECIPIENTS[:1], "auth-service", "2026-09-10T09:00:00Z", "2026-09-17T09:03:00Z")
        self.assertNotIn("between", FakeSMTP.sent[0].get_body(("plain",)).get_content())

    def test_not_sent_twice(self):
        n = Notifier(_send_cfg(), output_dir=self.out, smtp_factory=FakeSMTP)
        n.notify_restored("live_001", RECIPIENTS)
        self.assertEqual(n.notify_restored("live_001", RECIPIENTS)["status"], "skipped")
        self.assertEqual(len(FakeSMTP.sent), 2)

    def test_no_recipients_skips(self):
        n = Notifier(_send_cfg(), output_dir=self.out, smtp_factory=FakeSMTP)
        self.assertEqual(n.notify_restored("live_001", [])["status"], "skipped")

    def test_dry_run_writes_eml_per_user(self):
        n = Notifier(NotificationConfig(), output_dir=self.out)
        entry = n.notify_restored("live_001", RECIPIENTS, "search-service")
        self.assertEqual(entry["status"], "dry_run")
        emls = sorted(self.out.glob("*.eml"))
        self.assertEqual(len(emls), 2)
        msg = email.message_from_bytes(emls[0].read_bytes())
        self.assertEqual(msg["Subject"], "ShopMind is back to normal")

    def test_smtp_failure_does_not_raise(self):
        FakeSMTP.fail_login = True
        n = Notifier(_send_cfg(), output_dir=self.out, smtp_factory=FakeSMTP)
        entry = n.notify_restored("live_001", RECIPIENTS)
        self.assertEqual(entry["status"], "failed")

    def test_not_recovered_records_skip(self):
        n = Notifier(_send_cfg(), output_dir=self.out, smtp_factory=FakeSMTP)
        entry = n.notify_not_recovered("live_001", ["auth-service"], 180)
        self.assertEqual(entry["status"], "skipped")
        self.assertIn("not back to normal", entry["reason"])
        self.assertEqual(FakeSMTP.sent, [])


if __name__ == "__main__":
    unittest.main()
