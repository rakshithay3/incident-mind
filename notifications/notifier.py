"""
notifications/notifier.py -- tells ShopMind users the site is working again.

One event: service_restored. After IncidentMind finishes its investigation
and live telemetry confirms ShopMind is back to normal
(notifications/recovery.py), every registered ShopMind user
(notifications/recipients.py) gets a short, plain-language email. No RCA
details, scores or internal service names -- it's written for shoppers.

Backend is stdlib smtplib. If SMTP credentials are missing, it runs in
DRY-RUN mode and writes the emails to output/notifications/ instead.
Best-effort: never raises. Each call returns a status dict (also appended to
output/notifications/log.jsonl) that replay_demo.py puts in demo_result.json
for the dashboard. The status dict holds counts only, never addresses.

Env vars:
    IM_NOTIFY_ENABLED   "0" disables notifications (default "1")
    IM_SMTP_HOST        default smtp.gmail.com
    IM_SMTP_PORT        default 587 (STARTTLS); 465 uses SMTP_SSL
    IM_SMTP_USER        SMTP login (Gmail address)
    IM_SMTP_PASSWORD    Gmail app password
    IM_NOTIFY_FROM      default = IM_SMTP_USER
    IM_SHOPMIND_URL     link in the email, default http://localhost:3000
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_OUTPUT_DIR = Path("output/notifications")

# Internal service -> what a shopper would have noticed.
AFFECTED_AREA = {
    "auth-service": "signing in",
    "user-service": "your account pages",
    "order-service": "placing orders",
    "payment-service": "checkout and payments",
    "inventory-service": "stock availability",
    "notification-service": "order confirmation emails",
    "search-service": "search",
    "api-gateway": "the website",
    "frontend": "the website",
    "cache": "page loading",
    "postgres-primary": "the website",
    "postgres-replica": "search and browsing",
}


def affected_area(service_id: Optional[str]) -> str:
    return AFFECTED_AREA.get(service_id or "", "parts of the website")


@dataclass
class NotificationConfig:
    enabled: bool = True
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    sender: Optional[str] = None
    shop_url: str = "http://localhost:3000"
    timeout_sec: float = 10.0

    @classmethod
    def from_env(cls, env: Optional[Dict[str, str]] = None) -> "NotificationConfig":
        env = os.environ if env is None else env
        user = env.get("IM_SMTP_USER") or None
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
            shop_url=env.get("IM_SHOPMIND_URL", "http://localhost:3000"),
        )

    @property
    def can_send(self) -> bool:
        return bool(self.smtp_user and self.smtp_password and self.sender)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fmt_time(iso: Optional[str]) -> Optional[str]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%I:%M %p").lstrip("0")
    except (ValueError, TypeError):
        return None


def build_restored_email(name: str, area: str, started_at: Optional[str], restored_at: Optional[str],
                         shop_url: str) -> Dict[str, str]:
    greeting = f"Hi {name}," if name else "Hi there,"
    start, end = _fmt_time(started_at), _fmt_time(restored_at)
    window = f" between {start} and {end}" if start and end else ""
    subject = "ShopMind is back to normal"
    text = "\n".join([
        greeting,
        "",
        f"Earlier today, ShopMind had a problem with {area}{window}.",
        "It's fixed now, and everything is running normally again.",
        "",
        "If something you tried during that time didn't go through, please give it another go.",
        "",
        f"Visit ShopMind: {shop_url}",
        "",
        "Sorry for the trouble,",
        "The ShopMind team",
    ])
    html = f"""<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:480px;margin:0 auto;color:#1f2933;line-height:1.55">
<p style="font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#0f766e;margin:0 0 18px">ShopMind</p>
<h1 style="font-size:20px;margin:0 0 14px">We're back to normal</h1>
<p>{escape(greeting)}</p>
<p>Earlier today, ShopMind had a problem with {escape(area)}{escape(window)}. It's fixed now, and everything is running normally again.</p>
<p>If something you tried during that time didn't go through, please give it another go.</p>
<p style="margin:22px 0"><a href="{escape(shop_url)}" style="background:#0f766e;color:#fff;text-decoration:none;padding:10px 18px;border-radius:6px;display:inline-block">Go to ShopMind</a></p>
<p style="color:#52606d">Sorry for the trouble,<br>The ShopMind team</p>
</div>"""
    return {"subject": subject, "text": text, "html": html}


class Notifier:
    def __init__(self, config: Optional[NotificationConfig] = None, output_dir: Path = DEFAULT_OUTPUT_DIR,
                 smtp_factory=None):
        self.config = config or NotificationConfig.from_env()
        self.output_dir = Path(output_dir)
        self._smtp_factory = smtp_factory  # injectable for tests
        self._sent_incidents = set()
        self.history: List[Dict[str, Any]] = []

    def notify_restored(
        self,
        incident_id: str,
        recipients: List[Dict[str, str]],
        root_cause_service: Optional[str] = None,
        started_at: Optional[str] = None,
        restored_at: Optional[str] = None,
        recipients_source: Optional[str] = None,
    ) -> Dict[str, Any]:
        cfg = self.config
        area = affected_area(root_cause_service)
        details = {
            "affected_area": area,
            "root_cause_service": root_cause_service,
            "started_at": started_at,
            "restored_at": restored_at,
            "recipients_source": recipients_source,
        }
        if started_at and restored_at:
            try:
                a = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                b = datetime.fromisoformat(restored_at.replace("Z", "+00:00"))
                details["downtime_sec"] = max(0, int((b - a).total_seconds()))
            except (ValueError, TypeError):
                pass

        if not cfg.enabled:
            return self._record(incident_id, "skipped", details, 0, 0, reason="notifications disabled")
        if incident_id in self._sent_incidents:
            return self._record(incident_id, "skipped", details, 0, 0, reason="already notified")
        if not recipients:
            return self._record(incident_id, "skipped", details, 0, 0,
                                reason="no registered ShopMind users with a deliverable email")

        # A replay of an old capture would otherwise tell users about a window
        # from days ago -- only mention the time window for a same-session fix.
        window_start = started_at if details.get("downtime_sec", 10**9) <= 6 * 3600 else None

        messages = []
        for r in recipients:
            content = build_restored_email(r.get("name", ""), area, window_start, restored_at, cfg.shop_url)
            msg = EmailMessage()
            msg["Subject"] = content["subject"]
            msg["From"] = formataddr(("ShopMind", cfg.sender or "shopmind@localhost"))
            msg["To"] = r["email"]
            msg.set_content(content["text"])
            msg.add_alternative(content["html"], subtype="html")
            messages.append(msg)

        if not cfg.can_send:
            self._write_dry_run(incident_id, messages)
            self._sent_incidents.add(incident_id)
            return self._record(incident_id, "dry_run", details, len(messages), 0,
                                reason="SMTP credentials not set", file=str(self.output_dir))

        sent, errors = 0, []
        try:
            with self._open_smtp() as smtp:
                for msg in messages:
                    try:
                        smtp.send_message(msg)
                        sent += 1
                    except Exception as exc:
                        errors.append(type(exc).__name__)
        except Exception as exc:
            return self._record(incident_id, "failed", details, len(messages), sent,
                                reason=f"{type(exc).__name__}: {exc}")

        if sent:
            self._sent_incidents.add(incident_id)
        status = "sent" if sent == len(messages) else ("partial" if sent else "failed")
        reason = f"{len(errors)} message(s) failed" if errors else None
        return self._record(incident_id, status, details, len(messages), sent, reason=reason)

    def notify_not_recovered(self, incident_id: str, still_unhealthy: List[str], waited_sec: float) -> Dict[str, Any]:
        return self._record(incident_id, "skipped", {"still_unhealthy": still_unhealthy}, 0, 0,
                            reason=f"ShopMind not back to normal after {int(waited_sec)}s, users not emailed")

    # ------------------------------------------------------------------

    def _open_smtp(self):
        cfg = self.config
        if self._smtp_factory is not None:
            smtp = self._smtp_factory(cfg.smtp_host, cfg.smtp_port)
            smtp.login(cfg.smtp_user, cfg.smtp_password)
            return smtp
        if cfg.smtp_port == 465:
            smtp = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=cfg.timeout_sec,
                                    context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=cfg.timeout_sec)
            smtp.starttls(context=ssl.create_default_context())
        smtp.login(cfg.smtp_user, cfg.smtp_password)
        return smtp

    def _write_dry_run(self, incident_id: str, messages: List[EmailMessage]) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        for i, msg in enumerate(messages, start=1):
            (self.output_dir / f"{stamp}_{incident_id}_restored_{i}.eml").write_bytes(bytes(msg))

    def _record(self, incident_id, status, details, recipients_count, sent_count, **extra) -> Dict[str, Any]:
        entry = {
            "event": "service_restored",
            "incident_id": incident_id,
            "status": status,
            "timestamp": _now(),
            "recipients_count": recipients_count,
            "sent_count": sent_count,
            "details": details,
        }
        entry.update({k: v for k, v in extra.items() if v is not None})
        self.history.append(entry)
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            with open(self.output_dir / "log.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass
        if status == "dry_run":
            line = f"  [notify] service_restored: dry_run ({recipients_count} email(s) saved to {self.output_dir})"
        else:
            line = f"  [notify] service_restored: {status} ({sent_count}/{recipients_count} emails)"
        if extra.get("reason"):
            line += f" -- {extra['reason']}"
        print(line)
        return entry
