"""Exercise recorder boundaries independently of model or eval telemetry."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/skill_workflow.py"
SPEC = importlib.util.spec_from_file_location("skill_workflow", SCRIPT)
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)


class SkillWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.environment = patch.dict(os.environ, {"OBSTUDIO_SKILL_MCP_ENDPOINT": "none"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def start(self, skill="otel-audit"):
        return workflow.start(skill, self.root)

    def test_checkpoint_path_retries_and_completion(self):
        run = self.start()
        workflow.add_event(run, "discover", "passed", "checkpoint", branch="go")
        workflow.add_event(run, "assess", "failed", "checkpoint")
        workflow.add_event(run, "assess", "passed", "checkpoint", branch="fresh")
        artifact = self.root / "audit.json"
        artifact.write_text('{"result":"example"}')
        workflow.add_event(run, "report", "passed", "checkpoint", evidence=["audit.json"])
        state = workflow.finish(run, "passed")
        self.assertEqual(state["status"], "passed")
        self.assertEqual([e["attempt"] for e in state["events"]], [1, 1, 2, 1])
        report = workflow.inspect(state)
        self.assertEqual(report["findings"], [])
        self.assertIsNone(report["tokens"])
        self.assertNotIn("durationMs", state["events"][0])
        self.assertEqual(len(state["events"][-1]["evidence"][0]["sha256"]), 71)
        self.assertNotIn("example", run.read_text())
        with self.assertRaisesRegex(ValueError, "already finished"):
            workflow.add_event(run, "report", "passed", "checkpoint")

    def test_missing_blocked_and_out_of_order_never_become_success(self):
        run = self.start()
        workflow.add_event(run, "assess", "blocked", "checkpoint", reason="runtime_missing")
        findings = workflow.inspect(workflow.read_state(run))["findings"]
        self.assertEqual({f["kind"] for f in findings}, {"stage_order", "unobserved", "blocked"})
        self.assertEqual(workflow.finish(run, "passed")["status"], "partial")

    def test_execute_measures_real_failure_without_saving_command_or_output(self):
        run = self.start("otel-verify")
        args = argparse.Namespace(run=run, stage="build", branch="blocked", evidence=[],
                                  command=[sys.executable, "-c", "import sys;sys.exit(7)"])
        self.assertEqual(workflow.execute(args), 7)
        state = workflow.read_state(run)
        event = state["events"][0]
        self.assertEqual((event["source"], event["status"], event["exitCode"]), ("executed", "failed", 7))
        self.assertGreater(event["durationMs"], 0)
        self.assertNotIn("sys.exit", run.read_text())
        self.assertEqual(state["status"], "running")

    def test_recording_failure_does_not_prevent_original_command(self):
        target = self.root / "primary-result"
        completed = subprocess.run([sys.executable, str(SCRIPT), "execute", "--run",
                                    str(self.root / "missing.json"), "--stage", "build", "--",
                                    sys.executable, "-c", "from pathlib import Path;import sys;Path(sys.argv[1]).touch();sys.exit(3)",
                                    str(target)], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 3)
        self.assertTrue(target.exists())
        self.assertIn("recording unavailable", completed.stderr)

    def test_cancellation_is_recorded_and_not_finished_as_success(self):
        run = self.start("otel-verify")
        args = argparse.Namespace(run=run, stage="build", branch="", evidence=[], command=["go", "test"])
        with patch.object(workflow.subprocess, "call", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                workflow.execute(args)
        event = workflow.read_state(run)["events"][0]
        self.assertEqual((event["exitCode"], event["reason"]), (130, "interrupted"))
        self.assertEqual(workflow.finish(run, "cancelled")["status"], "cancelled")

    def test_concurrent_events_and_runs_are_isolated(self):
        first, second = self.start(), self.start()
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: workflow.add_event(first, "discover", "passed", "checkpoint"), range(8)))
        self.assertEqual([e["attempt"] for e in workflow.read_state(first)["events"]], list(range(1, 9)))
        self.assertEqual(workflow.read_state(second)["events"], [])

    def test_rejects_unknown_paths_symlinks_reasons_and_capacity(self):
        run = self.start()
        for stage, branch in [("invented", ""), ("discover", "invented")]:
            with self.assertRaises(ValueError):
                workflow.add_event(run, stage, "passed", "checkpoint", branch=branch)
        with self.assertRaises(ValueError):
            workflow.add_event(run, "discover", "blocked", "checkpoint", reason="secret token")
        for evidence in (["../outside"], [str(run)], ["missing"]):
            with self.assertRaises(ValueError):
                workflow.add_event(run, "discover", "passed", "checkpoint", evidence=evidence)
        link = self.root / "linked.json"
        link.symlink_to(run)
        with self.assertRaises(ValueError):
            workflow.read_state(link)
        with patch.object(workflow, "MAX_EVENTS", 0):
            with self.assertRaises(ValueError):
                workflow.add_event(run, "discover", "passed", "checkpoint")
        self.assertEqual(workflow.read_state(run)["events"], [])

    def test_export_is_offline_safe_local_only_and_does_not_follow_redirects(self):
        run = self.start()
        state = workflow.read_state(run)
        for endpoint in ("https://example.com/mcp", "http://localhost:3000/mcp?token=secret",
                         "http://user:secret@localhost/mcp", "http://localhost/wrong"):
            with patch.dict(os.environ, {"OBSTUDIO_SKILL_MCP_ENDPOINT": endpoint}), patch.object(workflow, "build_opener") as opener:
                self.assertFalse(workflow.publish(state))
                opener.assert_not_called()
        with patch.dict(os.environ, {"OBSTUDIO_SKILL_MCP_ENDPOINT": "http://localhost:3000/mcp"}):
            with patch.object(workflow, "build_opener") as opener:
                response = opener.return_value.open.return_value.__enter__.return_value
                response.read.return_value = b"[]"
                self.assertFalse(workflow.publish(state))
                response.read.return_value = b'{"result":{"isError":false}}'
                self.assertTrue(workflow.publish(state))
        self.assertIsNone(workflow.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com"))


if __name__ == "__main__":
    unittest.main()
