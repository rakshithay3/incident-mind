"""
notifications/notifier.py -- email notification hooks (extension item:
notification hooks, P2).

Two events fire an email:

  1. dispatch_threshold -- PPO dispatched a node whose
     priority_score = anomaly_score * impact_weight is >= threshold.
  2. report_complete    -- the Report Agent finished an RCA report.

Backend is stdlib smtplib (zero new dependencies). Config comes from env
vars (see NotificationConfig.from_env). If SMTP credentials or recipients
are missing, the notifier runs in DRY-RUN mode: nothing is sent, the email
is written to output/notifications/ instead. That keeps demos and tests
working on any machine without creds.

Notifications are best-effort and never raise: a failed SMTP call is
recorded as status="failed" and the pipeline keeps going. Every attempt
(sent / dry_run / failed / skipped) is appended to
output/notifications/log.jsonl and returned as a dict, so callers can put
it straight into demo_result.json for the dashboard's incident cards.

Env vars:
    IM_NOTIFY_ENABLED     "0" disables all notifications (default "1")
    IM_SMTP_HOST          default smtp.gmail.com
    IM_SMTP_PORT          default 587 (STARTTLS); 465 uses SMTP_SSL
    IM_SMTP_USER          SMTP login (Gmail address)
    IM_SMTP_PASSWORD      SMTP password (Gmail: 16-char app password)
    IM_NOTIFY_FROM        default = IM_SMTP_USER
    IM_NOTIFY_TO          comma-separated recipients
    IM_DISPATCH_THRESHOLD priority_score threshold, default 0.5
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from priority.impact_weights import SERVICE_TIERS, get_impact_weight

DEFAULT_OUTPUT_DIR = Path("output/notifications")
DEFAULT_THRESHOLD = 0.5


@dataclass
class NotificationConfig:
    enabled: bool = True
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    sender: Optional[str] = None
    recipients: List[str] = field(default_factory=list)
    dispatch_threshold: float = DEFAULT_THRESHOLD
    timeout_sec: float = 10.0

    @classmethod
    def from_env(cls, env: Optional[Dict[str, str]] = None) -> "NotificationConfig":
        env = os.environ if env is None else env
        user = env.get("IM_SMTP_USER") or None
        recipients = [r.strip() for r in env.get("IM_NOTIFY_TO", "").split(",") if r.strip()]
        try:
            threshold = float(env.get("IM_DISPATCH_THRESHOLD", DEFAULT_THRESHOLD))
        except ValueError:
            threshold = DEFAULT_THRESHOLD
        try:
            port = int(env.get("IM_SMTP_PORT", 587))
        except ValueError:
            port = 587
        return cls(
            enabled=env.get("IM_NOTIFY_ENABLED", "1") != "0",
            smtp_host=env.get("IM_SMTP_HOST", "smtp.gmail.com"),
            smtp_port=port,
            smtp_user=user,
            smtp_password=env.get("IM_SMTP_PASSWORD") or None,
            sender=env.get("IM_NOTIFY_FROM") or user,
            recipients=recipients,
            dispatch_threshold=threshold,
        )

    @property
    def can_send(self) -> bool:
        return bool(self.smtp_user and self.smtp_password and self.sender and self.recipients)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Notifier:
    def __init__(
        self,
        config: Optional[NotificationConfig] = None,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
        smtp_factory=None,
    ):
        self.config = config or NotificationConfig.from_env()
        self.output_dir = Path(output_dir)
        # Injectable for tests; defaults to smtplib.SMTP / SMTP_SSL.
        self._smtp_factory = smtp_factory
        self._sent_keys = set()
        self.history: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Event hooks
    # ------------------------------------------------------------------

    def notify_dispatch(
        self,
        incident_id: str,
        decision,
        ranked: Iterable,
        fault_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Hook 1: fire when the PPO-dispatched node crosses the priority
        threshold. `decision` is a DispatchDecision, `ranked` the NodeScore
        list it was chosen from (needed to look up the target's score)."""
        action = decision.action
        target = action.target_service
        instance_id = getattr(action, "instance_id", None)

        node = next(
            (
                s for s in ranked
                if s.service_id == target and getattr(s, "instance_id", None) == instance_id
            ),
            None,
        )
        anomaly = float(node.anomaly_score) if node is not None else 0.0
        weight = get_impact_weight(target)
        priority = anomaly * weight
        threshold = self.config.dispatch_threshold

        details = {
            "target_service": target,
            "instance_id": instance_id,
            "agent_type": action.agent_type,
            "anomaly_score": round(anomaly, 4),
            "impact_tier": SERVICE_TIERS.get(target, "default"),
            "impact_weight": weight,
            "priority_score": round(priority, 4),
            "threshold": threshold,
            "policy_confidence": round(float(decision.policy_confidence), 4),
            "fault_type": fault_type,
        }

        if priority < threshold:
            return self._record("dispatch_threshold", incident_id, "skipped", details,
                                reason=f"priority_score {priority:.3f} < threshold {threshold}")

        where = f" on {instance_id}" if instance_id else ""
        subject = f"[IncidentMind] {incident_id}: dispatching {action.agent_type} agent to {target}{where}"
        body = "\n".join([
            f"IncidentMind dispatched an investigation for incident {incident_id}.",
            "",
            f"Target service   : {target}{where}",
            f"Agent            : {action.agent_type}",
            f"Fault type       : {fault_type or 'unknown'}",
            f"Anomaly score    : {anomaly:.3f}",
            f"Impact tier      : {details['impact_tier']} (weight {weight})",
            f"Priority score   : {priority:.3f} (threshold {threshold})",
            f"PPO confidence   : {decision.policy_confidence:.2f}",
            "",
            "Investigation agents are running. A second email follows when the RCA report is ready.",
        ])
        key = ("dispatch_threshold", incident_id, instance_id, target)
        return self._deliver("dispatch_threshold", incident_id, subject, body, details, key)

    def notify_report(self, incident_id: str, report: Dict[str, Any]) -> Dict[str, Any]:
        """Hook 2: fire when the Report Agent completes."""
        report = report if isinstance(report, dict) else {}
        root = report.get("root_cause_service", "unknown")
        try:
            confidence = float(report.get("confidence_score", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        fix = report.get("suggested_fix", "") or ""
        blast = report.get("estimated_blast_radius", []) or []
        evidence = report.get("evidence_summary", []) or []
        report_en = (report.get("report_text") or {}).get("en", "")

        details = {
            "root_cause_service": root,
            "confidence_score": round(confidence, 3),
            "estimated_blast_radius": blast,
        }

        subject = f"[IncidentMind] {incident_id}: RCA report ready -- root cause {root} ({confidence:.0%})"
        lines = [
            f"The Report Agent finished the RCA for incident {incident_id}.",
            "",
            f"Root cause       : {root}",
            f"Confidence       : {confidence:.2f}",
            f"Blast radius     : {', '.join(map(str, blast)) if blast else 'none reported'}",
            f"Suggested fix    : {fix or 'none'}",
            "",
            "Evidence:",
        ]
        for item in evidence:
            if isinstance(item, dict):
                lines.append(f"  - [{item.get('agent_type', '?')}] {item.get('summary', '')}")
        if report_en:
            lines += ["", "Report:", report_en]
        key = ("report_complete", incident_id)
        return self._deliver("report_complete", incident_id, subject, "\n".join(lines), details, key)

    # ------------------------------------------------------------------
    # Delivery
    # ------------------------------------------------------------------

    def _deliver(self, event, incident_id, subject, body, details, key) -> Dict[str, Any]:
        cfg = self.config
        if not cfg.enabled:
            return self._record(event, incident_id, "skipped", details, reason="notifications disabled")
        if key in self._sent_keys:
            return self._record(event, incident_id, "skipped", details, reason="duplicate")

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = cfg.sender or "incidentmind@localhost"
        msg["To"] = ", ".join(cfg.recipients) or "undisclosed-recipients:;"
        msg.set_content(body)

        if not cfg.can_send:
            path = self._write_dry_run(event, incident_id, msg)
            self._sent_keys.add(key)
            return self._record(event, incident_id, "dry_run", details, subject=subject,
                                reason="SMTP creds or recipients not set", file=str(path))

        try:
            self._send(msg)
        except Exception as exc:  # best-effort: never break the pipeline
            return self._record(event, incident_id, "failed", details, subject=subject,
                                reason=f"{type(exc).__name__}: {exc}")

        self._sent_keys.add(key)
        return self._record(event, incident_id, "sent", details, subject=subject,
                            recipients=list(cfg.recipients))

    def _send(self, msg: EmailMessage) -> None:
        cfg = self.config
        if self._smtp_factory is not None:
            smtp = self._smtp_factory(cfg.smtp_host, cfg.smtp_port)
        elif cfg.smtp_port == 465:
            smtp = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=cfg.timeout_sec,
                                    context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=cfg.timeout_sec)
        with smtp:
            if cfg.smtp_port != 465 and self._smtp_factory is None:
                smtp.starttls(context=ssl.create_default_context())
            smtp.login(cfg.smtp_user, cfg.smtp_password)
            smtp.send_message(msg)

    def _write_dry_run(self, event, incident_id, msg: EmailMessage) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        path = self.output_dir / f"{stamp}_{incident_id}_{event}.eml"
        path.write_bytes(bytes(msg))
        return path

    def _record(self, event, incident_id, status, details, **extra) -> Dict[str, Any]:
        entry = {"event": event, "incident_id": incident_id, "status": status,
                 "timestamp": _now(), "details": details}
        entry.update({k: v for k, v in extra.items() if v is not None})
        self.history.append(entry)
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            with open(self.output_dir / "log.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass
        status_line = f"  [notify] {event}: {status}"
        if "reason" in extra:
            status_line += f" ({extra['reason']})"
        print(status_line)
        return entry
