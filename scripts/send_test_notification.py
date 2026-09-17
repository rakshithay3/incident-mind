"""
scripts/send_test_notification.py -- check SMTP creds without running the
full GNN/PPO/Ollama pipeline. Sends one dispatch_threshold email and one
report_complete email using a fake cpu_stress incident on auth-service.

    export IM_SMTP_USER=you@gmail.com
    export IM_SMTP_PASSWORD=your16charapppassword
    export IM_NOTIFY_TO=you@gmail.com
    PYTHONPATH=. python3 scripts/send_test_notification.py

With no env vars set it runs in dry-run mode and writes .eml files to
output/notifications/.
"""

from incidentmind_p1.contracts import DispatchAction, DispatchDecision, NodeScore
from notifications.notifier import Notifier


def main():
    notifier = Notifier()
    cfg = notifier.config
    mode = "SEND" if cfg.can_send else "DRY-RUN (creds or IM_NOTIFY_TO missing)"
    print(f"Mode: {mode} | host={cfg.smtp_host}:{cfg.smtp_port} | to={cfg.recipients}")

    ranked = [NodeScore("auth-service", 1.0, 128, "anomalous", 1)]
    decision = DispatchDecision(step=1, action=DispatchAction("log", "auth-service"), policy_confidence=0.9)
    notifier.notify_dispatch("test_notification_001", decision, ranked, fault_type="cpu_stress")

    notifier.notify_report("test_notification_001", {
        "root_cause_service": "auth-service",
        "confidence_score": 0.8,
        "evidence_summary": [{"agent_type": "metrics", "summary": "Test email from IncidentMind notifier."}],
        "suggested_fix": "None -- this is a test.",
        "estimated_blast_radius": [],
        "report_text": {"en": "Test report body."},
    })


if __name__ == "__main__":
    main()
