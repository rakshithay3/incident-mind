"""
notifications/recipients.py -- who gets the "ShopMind is back" email.

Recipients are registered ShopMind users, read from auth-service's
GET /api/auth/users. auth-service keeps accounts in memory, so a pod_crash
on it wipes every account registered since startup. To survive that, every
successful fetch is merged into a small on-disk cache
(output/notifications/recipients_cache.json) and the cache is used when the
live fetch fails or comes back smaller. Call get_recipients() BEFORE the
fault / investigation, and again at send time.

Skipped: guest sessions, invalid addresses, and placeholder domains
(seeded demo accounts use @shopmind.io / @example.com, which don't receive
mail). For a demo, register on ShopMind with a real email address.

Env vars:
    IM_SHOPMIND_AUTH_URL  default http://localhost:3001 (auth-service direct,
                          so a broken api-gateway doesn't block the lookup)
    IM_SKIP_DOMAINS       default example.com,example.org,example.net,shopmind.io
    IM_NOTIFY_TO          optional extra addresses, always included
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

DEFAULT_AUTH_URL = "http://localhost:3001"
DEFAULT_SKIP_DOMAINS = "example.com,example.org,example.net,shopmind.io"
DEFAULT_CACHE = Path("output/notifications/recipients_cache.json")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _skip_domains(env) -> set:
    raw = env.get("IM_SKIP_DOMAINS", DEFAULT_SKIP_DOMAINS)
    return {d.strip().lower() for d in raw.split(",") if d.strip()}


def filter_users(users: List[Dict], skip_domains: set) -> List[Dict[str, str]]:
    out, seen = [], set()
    for u in users or []:
        if not isinstance(u, dict):
            continue
        if str(u.get("role", "")).lower() == "guest":
            continue
        email = str(u.get("email") or "").strip()
        if not _EMAIL_RE.match(email):
            continue
        if email.split("@", 1)[1].lower() in skip_domains:
            continue
        key = email.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"email": email, "name": str(u.get("name") or u.get("username") or "").strip()})
    return out


def fetch_shopmind_users(auth_url: str, timeout: float = 3.0) -> Optional[List[Dict]]:
    try:
        with urllib.request.urlopen(f"{auth_url.rstrip('/')}/api/auth/users", timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data if isinstance(data, list) else None
    except Exception:
        return None


def _load_cache(path: Path) -> List[Dict[str, str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [r for r in data if isinstance(r, dict) and r.get("email")]
    except Exception:
        return []


def _save_cache(path: Path, recipients: List[Dict[str, str]]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(recipients, indent=2), encoding="utf-8")
    except OSError:
        pass


def get_recipients(env=None, cache_path: Path = DEFAULT_CACHE, fetch=fetch_shopmind_users) -> Dict:
    """Returns {"recipients": [{email, name}], "source": "live"|"cache"|"live+cache"|"none"}."""
    env = os.environ if env is None else env
    skip = _skip_domains(env)
    cache_path = Path(cache_path)

    cached = _load_cache(cache_path)
    live_raw = fetch(env.get("IM_SHOPMIND_AUTH_URL", DEFAULT_AUTH_URL))
    live = filter_users(live_raw, skip) if live_raw is not None else []

    merged, seen = [], set()
    for r in live + cached:
        k = r["email"].lower()
        if k not in seen:
            seen.add(k)
            merged.append(r)

    extra = [e.strip() for e in env.get("IM_NOTIFY_TO", "").split(",") if e.strip()]
    for e in extra:
        if _EMAIL_RE.match(e) and e.lower() not in seen:
            seen.add(e.lower())
            merged.append({"email": e, "name": ""})

    stored = [r for r in merged if r["email"].lower() not in {e.lower() for e in extra}]
    if live_raw is not None:
        _save_cache(cache_path, stored)

    if live_raw is not None and cached and len(stored) > len(live):
        source = "live+cache"
    elif live_raw is not None:
        source = "live"
    elif cached:
        source = "cache"
    else:
        source = "extra" if extra else "none"
    return {"recipients": merged, "source": source}
