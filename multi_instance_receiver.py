"""
multi_instance_receiver.py -- HTTP receiver for multi-instance telemetry
(extension item 3). Accepts POSTed telemetry snapshots tagged with
instance_id from other machines over shared wifi, so a second instance's
captures can be collected alongside this machine's own.
"""

import json
import os
import re
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RECEIVED_DIR = Path("output/multi_instance")
MAX_BODY_BYTES = 5 * 1024 * 1024
# instance_id becomes a directory name, so only allow a safe charset
# (no "/", "..", etc.) -- otherwise a POST could write outside RECEIVED_DIR.
INSTANCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
# Optional shared secret: if IM_RECEIVER_TOKEN is set, POSTs must send it in
# the X-IM-Token header. Leave unset for loopback-only testing.
RECEIVER_TOKEN = os.environ.get("IM_RECEIVER_TOKEN") or None

_lock = threading.Lock()
_latest_by_instance = {}


class TelemetryReceiverHandler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/telemetry":
            self._send_json(404, {"error": "not found"})
            return
        if RECEIVER_TOKEN is not None and self.headers.get("X-IM-Token") != RECEIVER_TOKEN:
            self._send_json(401, {"error": "missing or wrong X-IM-Token"})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send_json(400, {"error": "bad Content-Length"})
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_json(413, {"error": f"body must be 1..{MAX_BODY_BYTES} bytes"})
            return
        raw_body = self.rfile.read(length)

        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON"})
            return

        instance_id = payload.get("instance_id") if isinstance(payload, dict) else None
        if not isinstance(instance_id, str) or not INSTANCE_ID_RE.match(instance_id):
            self._send_json(400, {"error": "missing or invalid instance_id (letters, digits, _ . - ; max 64)"})
            return

        received_at = datetime.now(timezone.utc).isoformat()
        payload["received_at"] = received_at

        with _lock:
            _latest_by_instance[instance_id] = payload
            instance_dir = RECEIVED_DIR / instance_id
            instance_dir.mkdir(parents=True, exist_ok=True)
            out_path = instance_dir / f"{received_at.replace(':', '-')}.json"
            with open(out_path, "w") as f:
                json.dump(payload, f, indent=2)

        print(f"[received] instance_id={instance_id} saved to {out_path}")
        self._send_json(200, {"status": "ok", "instance_id": instance_id, "received_at": received_at})

    def do_GET(self):
        if self.path == "/snapshots":
            with _lock:
                snapshot = dict(_latest_by_instance)
            self._send_json(200, snapshot)
        else:
            self._send_json(404, {"error": "not found"})

    def log_message(self, format, *args):
        pass


def run(port=5001):
    if RECEIVER_TOKEN is None:
        print("NOTE: IM_RECEIVER_TOKEN not set -- any machine on the network can POST telemetry.")
    server = ThreadingHTTPServer(("0.0.0.0", port), TelemetryReceiverHandler)
    print(f"Multi-instance telemetry receiver listening on 0.0.0.0:{port}")
    print("  POST /telemetry  (JSON body must include instance_id)")
    print("  GET  /snapshots  (latest snapshot per instance_id)")
    server.serve_forever()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5001
    run(port)
