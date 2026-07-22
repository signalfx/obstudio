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
    "otel_instrument_observe_report_wrapper", WRAPPER
)
assert WRAPPER_SPEC is not None and WRAPPER_SPEC.loader is not None
WRAPPER_MODULE = importlib.util.module_from_spec(WRAPPER_SPEC)
WRAPPER_SPEC.loader.exec_module(WRAPPER_MODULE)


class JsonApprovalFlowGuidanceTest(unittest.TestCase):
    def test_requires_bound_approval_before_application_edits(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        text = skill + FLOW.read_text(encoding="utf-8")
        self.assertIn("./references/json-approval-handoff.md", skill)
        required = (
            ".observe/otel-audit.json",
            ".observe/otel-selection.json",
            "$otel-instrument --ids OTEL-001,OTEL-002",
            "Before any application-code, dependency, runtime-config, or test edit",
            'python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" select',
            'python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" validate-flow',
            ".observe/tmp/otel-selected-findings.json",
        )
        for value in required:
            self.assertIn(value, text)

    def test_preserves_approved_ids_in_machine_handoff(self) -> None:
        text = FLOW.read_text(encoding="utf-8")
        normalized = " ".join(text.split())
        self.assertIn('"kind": "otel-instrumentation"', text)
        self.assertIn('"audit_sha256": "audit-sha256-from-selection"', text)
        self.assertIn(
            "Findings must exactly equal the dependency-closed selected IDs (`approved_ids`) in audit order",
            normalized,
        )
        for value in (
            '"id": "OTEL-001.http-server-span"',
            '"change_kind": "added"',
            '"added_attributes": ["http.route"]',
            '"verification_scenarios": ["http.health.success"]',
            "chart/dashboard or detector",
            "filter, slice, group-by",
        ):
            self.assertIn(value, text)
        self.assertIn("--instrumentation-json .observe/otel-instrumentation.json", text)
        self.assertIn("--verify-json .observe/otel-verify.json", text)
        self.assertIn("render-instrumentation-html", text)
        self.assertIn(".observe/otel-instrumentation.html", text)

    def test_genai_reference_does_not_bypass_selection(self) -> None:
        text = (SKILL_DIR / "references" / "genai-instrumentation.md").read_text(
            encoding="utf-8"
        )
        normalized = " ".join(text.split())
        self.assertIn(
            "only the findings selected in `.observe/otel-selection.json`",
            normalized,
        )
        self.assertIn("only the bound selection defines code-change scope", normalized)

    def test_child_verification_records_item_local_assertion_before_rollup(self) -> None:
        text = " ".join(
            (SKILL.read_text(encoding="utf-8") + FLOW.read_text(encoding="utf-8")).split()
        )
        for value in (
            "direct_assertion_passed",
            "before any finding/scenario rollup",
            "removed item",
            "replacement owner",
        ):
            self.assertIn(value, text)

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
