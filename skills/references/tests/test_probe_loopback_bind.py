from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "probe_loopback_bind.py"
SPEC = importlib.util.spec_from_file_location("probe_loopback_bind", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeSocket:
    def __init__(self, *, bind_error: OSError | None = None) -> None:
        self.bind_error = bind_error
        self.closed = False
        self.bound = None
        self.listen_backlog = None

    def setsockopt(self, *args: object) -> None:
        return None

    def bind(self, address: tuple[str, int]) -> None:
        self.bound = address
        if self.bind_error is not None:
            raise self.bind_error

    def listen(self, backlog: int) -> None:
        self.listen_backlog = backlog

    def close(self) -> None:
        self.closed = True


class ProbeLoopbackBindTest(unittest.TestCase):
    def test_available_probe_is_bounded_and_closes_listener(self) -> None:
        listener = FakeSocket()
        result = MODULE.probe_loopback_bind(lambda *_: listener)

        self.assertEqual(result["status"], "available")
        self.assertTrue(result["complete"])
        self.assertTrue(result["candidate_only"])
        self.assertEqual(listener.bound, ("127.0.0.1", 0))
        self.assertEqual(listener.listen_backlog, 1)
        self.assertTrue(listener.closed)
        self.assertNotIn("assigned_port", result)

    def test_blocked_probe_records_exact_os_error_and_closes_listener(self) -> None:
        listener = FakeSocket(bind_error=PermissionError(1, "not permitted"))
        result = MODULE.probe_loopback_bind(lambda *_: listener)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["error"]["type"], "PermissionError")
        self.assertEqual(result["error"]["errno"], 1)
        self.assertIn("not permitted", result["error"]["message"])
        self.assertTrue(listener.closed)

    def test_cli_emits_one_complete_json_result(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        result = json.loads(completed.stdout)
        self.assertEqual(result["schema_version"], 1)
        self.assertIn(result["status"], {"available", "blocked"})


if __name__ == "__main__":
    unittest.main()
