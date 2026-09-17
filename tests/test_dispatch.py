"""Tests for the P2 dispatch pipeline (root pipeline.py).

These cover the DispatchAction -> agent routing path, including the
attribute-access contract (action.target_service, not action["target_service"])
that agents/*.py rely on. All Ollama and git calls are mocked so this suite
runs without a live Ollama instance or a git history to diff against.
"""

import unittest
from unittest.mock import patch

from pipeline import dispatch, run_investigation
from schemas.contracts import DispatchAction


LOG_OK = '{"finding": "auth errors spiking", "severity": "high", "confidence": 0.8, "evidence": ["err1"]}'
METRICS_OK = '{"finding": "latency elevated", "severity": "medium", "confidence": 0.6, "evidence": ["p99=900ms"]}'
CODE_OK = '{"finding": "risky config change", "severity": "high", "confidence": 0.7, "evidence": ["diff line"]}'
REPORT_OK = """{
    "incident_id": "inc_001",
    "root_cause_service": "auth-service",
    "confidence_score": 0.85,
    "evidence_summary": [
        {"agent_type": "log", "summary": "auth errors"},
        {"agent_type": "metrics", "summary": "latency up"},
        {"agent_type": "code", "summary": "risky change"}
    ],
    "suggested_fix": "revert config change",
    "estimated_blast_radius": ["auth-service", "order-service"],
    "report_text": {"en": "Root cause is auth-service.", "hi": "\\u092e\\u0942\\u0932 \\u0915\\u093e\\u0930\\u0923 auth-service \\u0939\\u0948\\u0964"}
}"""


class DispatchValidationTest(unittest.TestCase):
    def test_rejects_unsupported_agent_type(self):
        action = DispatchAction(agent_type="unknown", target_service="auth-service")
        with self.assertRaises(ValueError):
            dispatch(action)

    def test_rejects_missing_target_service(self):
        with self.assertRaises(TypeError):
            DispatchAction(agent_type="log")

    def test_rejects_empty_target_service(self):
        action = DispatchAction(agent_type="log", target_service="")
        with self.assertRaises(ValueError):
            dispatch(action)


class DispatchRoutingTest(unittest.TestCase):
    """Confirms dispatch() passes the DispatchAction object itself (not a
    dict, not a raw string) and that every agent unpacks it via attribute
    access -- this is the contract that previously broke."""

    @patch("agents.log_agent.ollama.chat")
    def test_log_agent_receives_dispatch_action_and_reads_target_service(self, mock_chat):
        mock_chat.return_value = {"message": {"content": LOG_OK}}
        action = DispatchAction(agent_type="log", target_service="auth-service")

        result = dispatch(action)

        self.assertEqual(result["agent_type"], "log")
        self.assertEqual(result["target_service"], "auth-service")
        self.assertEqual(result["severity"], "high")

    @patch("agents.metrics_agent.ollama.chat")
    def test_metrics_agent_receives_dispatch_action_and_reads_target_service(self, mock_chat):
        mock_chat.return_value = {"message": {"content": METRICS_OK}}
        # target_service must exist in sample_data/metrics.json for the
        # non-"no metrics found" branch; auth-service is used elsewhere in
        # the sample fixtures so it should be present.
        action = DispatchAction(agent_type="metrics", target_service="auth-service")

        result = dispatch(action)

        self.assertEqual(result["agent_type"], "metrics")
        self.assertEqual(result["target_service"], "auth-service")

    @patch("agents.code_agent.subprocess.run")
    @patch("agents.code_agent.requests.post")
    def test_code_agent_receives_dispatch_action_and_reads_target_service(self, mock_post, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "diff --git a/auth.py b/auth.py\n+ removed timeout guard"
        mock_post.return_value.raise_for_status = lambda: None
        mock_post.return_value.json.return_value = {"response": CODE_OK}

        action = DispatchAction(agent_type="code", target_service="auth-service")
        result = dispatch(action)

        self.assertEqual(result["agent_type"], "code")
        self.assertEqual(result["target_service"], "auth-service")


class RunInvestigationTest(unittest.TestCase):
    """End-to-end: DispatchAction list -> evidence bundle -> RCAReport,
    matching the AgentFinding / EvidenceBundle / RCAReport shapes in
    incidentmind_p1/contracts.py."""

    @patch("agents.report_agent.ollama.chat")
    @patch("agents.code_agent.subprocess.run")
    @patch("agents.code_agent.requests.post")
    @patch("agents.metrics_agent.ollama.chat")
    @patch("agents.log_agent.ollama.chat")
    def test_full_investigation_produces_contract_shaped_report(
        self, mock_log_chat, mock_metrics_chat, mock_code_post, mock_code_run, mock_report_chat
    ):
        mock_log_chat.return_value = {"message": {"content": LOG_OK}}
        mock_metrics_chat.return_value = {"message": {"content": METRICS_OK}}
        mock_code_run.return_value.returncode = 0
        mock_code_run.return_value.stdout = "diff --git a/auth.py b/auth.py\n+ removed timeout guard"
        mock_code_post.return_value.raise_for_status = lambda: None
        mock_code_post.return_value.json.return_value = {"response": CODE_OK}
        mock_report_chat.return_value = {"message": {"content": REPORT_OK}}

        actions = [
            DispatchAction(agent_type="log", target_service="auth-service"),
            DispatchAction(agent_type="metrics", target_service="auth-service"),
            DispatchAction(agent_type="code", target_service="auth-service"),
        ]

        result = run_investigation(actions, incident_id="inc_001")

        findings = result["evidence_bundle"]["findings"]
        self.assertEqual(len(findings), 3)
        self.assertEqual({f["agent_type"] for f in findings}, {"log", "metrics", "code"})
        for f in findings:
            self.assertEqual(f["target_service"], "auth-service")

        report = result["report"]
        self.assertEqual(report["incident_id"], "inc_001")
        self.assertEqual(report["root_cause_service"], "auth-service")
        self.assertIn("report_text", report)
        self.assertIn("en", report["report_text"])
        self.assertIn("hi", report["report_text"])


if __name__ == "__main__":
    unittest.main()
