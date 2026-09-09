from __future__ import annotations

import importlib.util
import io
import re
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
DIRECT = SKILL_DIR / "references" / "direct-verification.md"
REPORT = SKILL_DIR / "references" / "verification-report.md"
WRAPPER_SPEC = importlib.util.spec_from_file_location(
    "otel_verify_observe_report_wrapper", WRAPPER
)
assert WRAPPER_SPEC is not None and WRAPPER_SPEC.loader is not None
WRAPPER_MODULE = importlib.util.module_from_spec(WRAPPER_SPEC)
WRAPPER_SPEC.loader.exec_module(WRAPPER_MODULE)


class JsonApprovalFlowGuidanceTest(unittest.TestCase):
    def test_entrypoint_routes_heavy_modes_without_loading_them_by_default(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")

        self.assertLessEqual(len(skill.encode()), 12_000)
        self.assertIn("## Progressive Disclosure", skill)
        self.assertIn("## Existing Durable Proof Packet", skill)
        self.assertIn("Do not read `direct-verification.md`", skill)
        self.assertIn("stop before\n`## Splunk Configure Contract`", skill)
        self.assertIn("Inside a loaded\nreference", skill)
        self.assertIn("from that reference's directory", skill)
        self.assertTrue(DIRECT.is_file())
        self.assertTrue(REPORT.is_file())

    def test_nested_reference_routes_resolve_from_their_owner(self) -> None:
        references = sorted((SKILL_DIR / "references").glob("*.md"))

        for owner in references:
            for relative in re.findall(r"`([^`]+\.md)`", owner.read_text()):
                if relative.startswith(".observe/"):
                    continue
                target = (owner.parent / relative).resolve()
                self.assertTrue(target.is_file(), f"{owner} routes to missing {relative}")
                self.assertTrue(target.is_relative_to(SKILL_DIR.parent.resolve()))

    def test_progressive_references_retain_execution_and_report_contracts(self) -> None:
        direct = DIRECT.read_text(encoding="utf-8")
        report = REPORT.read_text(encoding="utf-8")

        for required in (
            "instrumentation-introduced",
            "Generated SDK spans, metrics, or logs",
            "../../references/full-runtime-acceptance.md",
            "Verified: unit+OTLP",
            "Not configured",
            "$otel-instrument",
        ):
            self.assertIn(required, direct)
        for required in (
            "## What Changed",
            "## Tested And Working",
            "## Not Working Or Not Proven",
            "## Proof",
            "validate_reader_report.py",
            "raw trace IDs or span IDs",
        ):
            self.assertIn(required, report)

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
        )
        for value in required:
            self.assertIn(value, text)

    def test_preserves_finding_and_scenario_ids_in_machine_report(self) -> None:
        text = FLOW.read_text(encoding="utf-8")
        normalized = " ".join(text.split())
        self.assertIn('"kind": "otel-verify"', text)
        self.assertIn('"audit_sha256": "audit-sha256-from-selection"', text)
        self.assertIn("selection_sha256", text)
        self.assertIn("binds the exact normalized selection", normalized)
        self.assertIn("Findings must exactly equal approved IDs in audit order", normalized)
        self.assertIn("one scenario object for every scenario referenced", normalized)
        for value in (
            '"item_results": [',
            '"proof_mode": "full_runtime"',
            '"visibility": "explorer_visible"',
            "one `item_results` row for every instrumentation",
            "not_explorer_visible",
        ):
            self.assertIn(value, text)
        self.assertIn("--verify-json .observe/otel-verify.json", text)
        self.assertIn("render-instrumentation-html", text)
        self.assertIn(".observe/otel-instrumentation.html", text)

    def test_scenario_references_are_selection_scoped(self) -> None:
        normalized = " ".join(
            (SKILL.read_text(encoding="utf-8") + FLOW.read_text(encoding="utf-8")).split()
        )
        self.assertIn(
            "verify exactly the approved findings in audit order and their referenced scenarios",
            normalized,
        )
        self.assertIn(
            "Unselected findings are outside this result and must not make it partial",
            normalized,
        )

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

    def test_final_response_uses_loopback_links_for_html_only(self) -> None:
        text = " ".join(
            (SKILL.read_text(encoding="utf-8") + FLOW.read_text(encoding="utf-8")).split()
        )

        self.assertIn(
            "[otel-instrumentation.html](http://127.0.0.1:<port>/<token>/otel-instrumentation.html)",
            text,
        )
        self.assertIn(
            "[otel.html](http://127.0.0.1:<port>/<token>/otel.html)",
            text,
        )
        self.assertIn(
            "Keep the Markdown and JSON report links as absolute local-file paths",
            text,
        )
        self.assertIn("do not open either report automatically", text.lower())

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
