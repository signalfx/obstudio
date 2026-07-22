from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).parents[1]
SKILL = SKILL_DIR / "SKILL.md"
WRAPPER = SKILL_DIR / "scripts" / "observe_report.py"
FLOW = SKILL_DIR / "references" / "json-approval-handoff.md"
WRAPPER_SPEC = importlib.util.spec_from_file_location(
    "otel_verify_observe_report_wrapper", WRAPPER
)
assert WRAPPER_SPEC is not None and WRAPPER_SPEC.loader is not None
WRAPPER_MODULE = importlib.util.module_from_spec(WRAPPER_SPEC)
WRAPPER_SPEC.loader.exec_module(WRAPPER_MODULE)


class JsonApprovalFlowGuidanceTest(unittest.TestCase):
    def test_consumes_the_same_bound_selection(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        text = skill + FLOW.read_text(encoding="utf-8")
        self.assertIn("./references/json-approval-handoff.md", skill)
        required = (
            ".observe/otel-audit.json",
            ".observe/otel-selection.json",
            "$otel-verify --ids OTEL-001,OTEL-002",
            "exactly the approved findings in audit order",
            'python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" select',
            'python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" validate-flow',
            ".observe/tmp/otel-selected-findings.json",
        )
        for value in required:
            self.assertIn(value, text)

    def test_preserves_finding_and_scenario_ids_in_machine_report(self) -> None:
        text = FLOW.read_text(encoding="utf-8")
        normalized = " ".join(text.split())
        self.assertIn('"kind": "otel-verify"', text)
        self.assertIn('"audit_sha256": "audit-sha256-from-selection"', text)
        self.assertIn("selection_sha256", text)
        self.assertIn("transitively bound to the exact normalized selection", normalized)
        self.assertIn("Findings must exactly equal approved IDs in audit order", normalized)
        self.assertIn("one scenario object for every scenario referenced", normalized)
        for value in (
            '"item_results": [',
            '"direct_assertion_passed": true',
            '"proof_mode": "full_runtime"',
            '"visibility": "explorer_visible"',
            "one `item_results` row for every instrumentation",
            "not_explorer_visible",
        ):
            self.assertIn(value, text)
        self.assertIn("--verify-json .observe/otel-verify.json", text)
        self.assertIn("render-instrumentation-html", text)
        self.assertIn(".observe/otel-instrumentation.html", text)

    def test_item_assertion_status_is_not_downgraded_by_scenario_rollup(self) -> None:
        text = " ".join((SKILL.read_text(encoding="utf-8") + FLOW.read_text(encoding="utf-8")).split())
        for value in (
            "direct_assertion_passed",
            "before computing scenario or finding rollups",
            "removed telemetry item",
            "intended replacement owner",
        ):
            self.assertIn(value, text)

    def test_scenario_references_are_selection_scoped(self) -> None:
        coverage = (SKILL_DIR / "references" / "path-scenario-coverage.md").read_text(
            encoding="utf-8"
        )
        runtime = (SKILL_DIR / "references" / "project-runtime-resolution.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("only the approved findings' referenced scenarios", coverage)
        self.assertIn("selected findings' referenced verification", runtime)

    def test_wrapper_exposes_shared_flow_commands(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(WRAPPER), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("select", completed.stdout)
        self.assertIn("validate-flow", completed.stdout)
        self.assertIn("render-html", completed.stdout)
        self.assertIn("render-instrumentation-html", completed.stdout)

    def test_wrapper_missing_helper_is_a_tool_error(self) -> None:
        missing = Path("/definitely/missing/observe_report.py")
        error = io.StringIO()
        with (
            mock.patch.object(
                WRAPPER_MODULE, "shared_tool_path", return_value=missing
            ),
            redirect_stderr(error),
        ):
            self.assertEqual(WRAPPER_MODULE.main(), 1)
        self.assertIn("OpenTelemetry report helper is missing", error.getvalue())


if __name__ == "__main__":
    unittest.main()
