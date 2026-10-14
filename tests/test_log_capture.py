"""capture_logs only pulls container log lines from the current incident window."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import live_inject_and_capture
from live_inject_and_capture import capture_logs


class CaptureLogsTest(unittest.TestCase):
    def test_since_timestamp_is_passed_to_docker_logs(self):
        since = "2026-10-14T09:30:00Z"
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(live_inject_and_capture.subprocess, "run",
                                  return_value=SimpleNamespace(stdout="line\n", stderr="")) as run:
            capture_logs(Path(tmp), ["auth-service", "user-service"], since=since)
            self.assertEqual((Path(tmp) / "auth-service.log").read_text(), "line\n")

        self.assertEqual(run.call_count, 2)
        for call, service in zip(run.call_args_list, ["auth-service", "user-service"]):
            cmd = call.args[0]
            self.assertEqual(cmd[:2], ["docker", "logs"])
            self.assertEqual(cmd[cmd.index("--since") + 1], since)
            self.assertIn("--timestamps", cmd)
            self.assertEqual(cmd[-1], f"shopmind-{service}")

    def test_since_is_required(self):
        with self.assertRaises(TypeError):
            capture_logs(Path("."), ["auth-service"])  # type: ignore[call-arg]

    def test_utc_now_iso_is_rfc3339_utc(self):
        self.assertRegex(live_inject_and_capture.utc_now_iso(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


if __name__ == "__main__":
    unittest.main()
