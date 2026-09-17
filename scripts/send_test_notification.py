"""
scripts/send_test_notification.py -- preview the "ShopMind is back to normal"
email without running the pipeline or breaking anything.

By default it emails ONLY the addresses in IM_NOTIFY_TO, so registered
ShopMind users don't get a fake outage email. Pass --list-users to see who
would get the real one (read from auth-service), without sending to them.

    export IM_SMTP_USER=you@gmail.com
    export IM_SMTP_PASSWORD=your16charapppassword
    export IM_NOTIFY_TO=you@gmail.com
    PYTHONPATH=. python3 scripts/send_test_notification.py
    PYTHONPATH=. python3 scripts/send_test_notification.py --list-users

With no SMTP creds it runs in dry-run mode and writes .eml files to
output/notifications/.
"""

import argparse
import os
from datetime import datetime, timedelta, timezone

from notifications.notifier import Notifier
from notifications.recipients import get_recipients


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-users", action="store_true",
                        help="Show which registered ShopMind users would be emailed, then exit")
    parser.add_argument("--service", default="payment-service",
                        help="Pretend this service was the one that broke (changes the wording)")
    args = parser.parse_args()

    if args.list_users:
        info = get_recipients(env={k: v for k, v in os.environ.items() if k != "IM_NOTIFY_TO"})
        print(f"{len(info['recipients'])} registered ShopMind user(s) would be emailed (source: {info['source']}):")
        for r in info["recipients"]:
            print(f"  {r['name'] or '(no name)'} <{r['email']}>")
        if not info["recipients"]:
            print("  none -- register on ShopMind with a real email address (seeded demo accounts are skipped)")
        return

    to = [e.strip() for e in os.environ.get("IM_NOTIFY_TO", "").split(",") if e.strip()]
    if not to:
        print("Set IM_NOTIFY_TO to your own address first -- this script never emails ShopMind users.")
        return

    notifier = Notifier()
    mode = "SEND" if notifier.config.can_send else "DRY-RUN (SMTP creds missing)"
    print(f"Mode: {mode} | to={to}")

    now = datetime.now(timezone.utc)
    notifier.notify_restored(
        "test_notification",
        [{"email": e, "name": ""} for e in to],
        root_cause_service=args.service,
        started_at=(now - timedelta(minutes=4)).isoformat(timespec="seconds"),
        restored_at=now.isoformat(timespec="seconds"),
        recipients_source="IM_NOTIFY_TO",
    )


if __name__ == "__main__":
    main()
