import json
import tempfile
import unittest
from pathlib import Path

from incidentmind_p1.contracts import DispatchAction, DispatchDecision, NodeScore
from notifications.notifier import NotificationConfig, Notifier


def _ranked():
    return [
        NodeScore("auth-service", 0.92, 128, "anomalous", 1),
        NodeScore("notification-service", 0.92, 128, "anomalous", 2),
        NodeScore("search-service", 0.40, 128, "normal", 3),
    ]


def _decision(target, instance_id=None):
    return DispatchDecision(step=1, action=DispatchAction("log", target, instance_id), policy_confidence=0.81)


REPORT = {
    "incident_id": "live_001",
    "root_cause_service": "auth-service",
    "confidence_score": 0.8,
    "evidence_summary": [{"agent_type": "metrics", "summary": "cpu_pct sustained at 98%"}],
    "suggested_fix": "Scale auth-service",
    "estimated_blast_radius": ["order-service"],
    "report_text": {"en": "auth-service CPU saturation", "hi": "..."},
}


class FakeSMTP:
    sent = []
    fail = False

    def __init__(self, host, port):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        if FakeSMTP.fail:
            raise OSError("auth failed")

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def _send_config(**overrides):
    cfg = NotificationConfig(smtp_user="bot@example.com", smtp_password="pw",
                             sender="bot@example.com", recipients=["oncall@example.com"])
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


class NotifierTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        FakeSMTP.sent = []
        FakeSMTP.fail = False

    def tearDown(self):
        self.tmp.cleanup()

    def test_config_from_env(self):
        cfg = NotificationConfig.from_env({
            "IM_SMTP_USER": "a@x.com", "IM_SMTP_PASSWORD": "p",
            "IM_NOTIFY_TO": "b@x.com, c@x.com", "IM_DISPATCH_THRESHOLD": "0.7",
        })
        self.assertEqual(cfg.recipients, ["b@x.com", "c@x.com"])
        self.assertEqual(cfg.sender, "a@x.com")
        self.assertEqual(cfg.dispatch_threshold, 0.7)
        self.assertTrue(cfg.can_send)
        self.assertFalse(NotificationConfig.from_env({}).can_send)

    def test_dispatch_above_threshold_sends(self):
        n = Notifier(_send_config(), output_dir=self.out, smtp_factory=FakeSMTP)
        entry = n.notify_dispatch("live_001", _decision("auth-service"), _ranked(), fault_type="cpu_stress")
        self.assertEqual(entry["status"], "sent")
        self.assertEqual(entry["details"]["priority_score"], 0.92)
        self.assertEqual(len(FakeSMTP.sent), 1)
        self.assertIn("auth-service", FakeSMTP.sent[0]["Subject"])

    def test_low_tier_service_below_threshold_is_skipped(self):
        # 0.92 anomaly * 0.3 (low tier) = 0.276 < 0.5
        n = Notifier(_send_config(), output_dir=self.out, smtp_factory=FakeSMTP)
        entry = n.notify_dispatch("live_001", _decision("notification-service"), _ranked())
        self.assertEqual(entry["status"], "skipped")
        self.assertEqual(FakeSMTP.sent, [])

    def test_duplicate_dispatch_not_resent(self):
        n = Notifier(_send_config(), output_dir=self.out, smtp_factory=FakeSMTP)
        n.notify_dispatch("live_001", _decision("auth-service"), _ranked())
        second = n.notify_dispatch("live_001", _decision("auth-service"), _ranked())
        self.assertEqual(second["status"], "skipped")
        self.assertEqual(len(FakeSMTP.sent), 1)

    def test_same_service_on_other_instance_is_not_duplicate(self):
        ranked = [
            NodeScore("auth-service", 0.9, 128, "anomalous", 1, instance_id="mac-a"),
            NodeScore("auth-service", 0.8, 128, "anomalous", 2, instance_id="mac-b"),
        ]
        n = Notifier(_send_config(), output_dir=self.out, smtp_factory=FakeSMTP)
        a = n.notify_dispatch("inc", _decision("auth-service", "mac-a"), ranked)
        b = n.notify_dispatch("inc", _decision("auth-service", "mac-b"), ranked)
        self.assertEqual((a["status"], b["status"]), ("sent", "sent"))
        self.assertEqual(b["details"]["anomaly_score"], 0.8)

    def test_dry_run_without_creds_writes_eml(self):
        n = Notifier(NotificationConfig(), output_dir=self.out)
        entry = n.notify_report("live_001", REPORT)
        self.assertEqual(entry["status"], "dry_run")
        eml = Path(entry["file"]).read_text()
        self.assertIn("auth-service", eml)
        self.assertIn("Scale auth-service", eml)
        log = [json.loads(l) for l in (self.out / "log.jsonl").read_text().splitlines()]
        self.assertEqual(log[-1]["event"], "report_complete")

    def test_smtp_failure_does_not_raise(self):
        FakeSMTP.fail = True
        n = Notifier(_send_config(), output_dir=self.out, smtp_factory=FakeSMTP)
        entry = n.notify_report("live_001", REPORT)
        self.assertEqual(entry["status"], "failed")
        self.assertIn("auth failed", entry["reason"])

    def test_disabled(self):
        n = Notifier(_send_config(enabled=False), output_dir=self.out, smtp_factory=FakeSMTP)
        self.assertEqual(n.notify_report("live_001", REPORT)["status"], "skipped")
        self.assertEqual(FakeSMTP.sent, [])

    def test_malformed_report_still_notifies(self):
        n = Notifier(NotificationConfig(), output_dir=self.out)
        entry = n.notify_report("live_002", None)
        self.assertEqual(entry["details"]["root_cause_service"], "unknown")


if __name__ == "__main__":
    unittest.main()
