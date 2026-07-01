from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


VALIDATOR = Path(__file__).parents[1] / "scripts" / "validate_gap_closure.py"

AUDIT_NO_GENAI = """# OTel Audit: sample

**Status:** Partial
**GenAI ownership detected:** No

## Gaps
| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|
| required | runtime bootstrap | No exporter | No telemetry | Add exporter | default | runtime.export |
"""

GENAI_READINESS = """## GenAI Readiness
| Surface | Status | Evidence | Required Signals | Owner / Source Files | Acceptance Criteria | Detection/Localization Impact |
|---|---|---|---|---|---|---|
| Workflow/agent trace | missing | Workflow has no GenAI span | `invoke_workflow` | App-owned: app.py | Trace proves workflow parentage | Workflow failures cannot be localized |
| Provider/model call | missing | Provider call has no GenAI span | `chat`; provider and model attributes | App-owned: app.py | Trace proves model-call attributes and parentage | Model failures cannot be localized |
| Privacy/cardinality | partial | Metadata-only spans, stdout IDs remain | metadata-only capture; bounded dimensions | App-owned: logging.py | Sentinel export is clean | Telemetry may expose identifiers |
"""

AUDIT_GENAI = AUDIT_NO_GENAI.replace(
    "**GenAI ownership detected:** No",
    "**GenAI ownership detected:** Yes",
).replace("## Gaps", f"{GENAI_READINESS}\n## Gaps")

INSTRUMENT_NO_GENAI = """# OTel Instrumentation Report: sample

**Result:** Pass

## Audit Gap Closure
| Priority | Gap | What changed | Tested | Result | Evidence / reason |
|---|---|---|---|---|---|
| required | runtime bootstrap | Added exporter | runtime.export | Working | Export test passed |

## Validation Gates
| Gate | Result |
|---|---|
| Unit tests | Pass |
"""

GENAI_CLOSURE = """## GenAI Readiness Closure
| Surface | Required signals | Implemented / proven | Tests | Remaining signals | Result |
|---|---|---|---|---|---|
| Workflow/agent trace | `invoke_workflow` | Workflow span emitted with parentage | trace.success | None | Working |
| Provider/model call | `chat`; provider and model attributes | Chat span emitted with bounded attributes and parentage | chat.success | None | Working |
| Privacy/cardinality | metadata-only capture; bounded dimensions | Span dimensions are bounded | telemetry.redaction | OTLP log policy | Partial |
"""

INSTRUMENT_GENAI = INSTRUMENT_NO_GENAI.replace(
    "**Result:** Pass",
    "**Result:** Partial",
).replace("## Validation Gates", f"{GENAI_CLOSURE}\n## Validation Gates")


class ValidateGapClosureTest(unittest.TestCase):
    def validate(
        self, audit: str, instrumentation: str
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit_path = root / "otel.md"
            instrumentation_path = root / "otel-instrumentation.md"
            audit_path.write_text(audit, encoding="utf-8")
            instrumentation_path.write_text(instrumentation, encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    str(audit_path),
                    str(instrumentation_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

    def test_accepts_one_to_one_genai_surface_closure(self) -> None:
        result = self.validate(AUDIT_GENAI, INSTRUMENT_GENAI)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("3 GenAI readiness surfaces", result.stdout)

    def test_pass_rejects_partial_genai_surface(self) -> None:
        result = self.validate(
            AUDIT_GENAI,
            INSTRUMENT_GENAI.replace("**Result:** Partial", "**Result:** Pass"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Result Pass conflicts", result.stderr)

    def test_pass_rejects_unproven_audit_gap(self) -> None:
        report = INSTRUMENT_NO_GENAI.replace(
            "| Working | Export test passed |",
            "| Not proven | No runtime proof |",
        )
        result = self.validate(AUDIT_NO_GENAI, report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Result Pass conflicts", result.stderr)

    def test_rejects_duplicate_report_result(self) -> None:
        report = INSTRUMENT_GENAI.replace(
            "**Result:** Partial",
            "**Result:** Partial\n**Result:** Pass",
        )
        result = self.validate(AUDIT_GENAI, report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly one valid Result declaration", result.stderr)

    def test_genai_audit_requires_closure_section(self) -> None:
        result = self.validate(AUDIT_GENAI, INSTRUMENT_NO_GENAI)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires ## GenAI Readiness Closure", result.stderr)

    def test_rejects_missing_genai_surface(self) -> None:
        missing_row = (
            "| Privacy/cardinality | metadata-only capture; bounded dimensions "
            "| Span dimensions are bounded | telemetry.redaction | OTLP log policy "
            "| Partial |\n"
        )
        result = self.validate(
            AUDIT_GENAI,
            INSTRUMENT_GENAI.replace(missing_row, ""),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing=['Privacy/cardinality']", result.stderr)

    def test_rejects_changed_required_signals(self) -> None:
        result = self.validate(
            AUDIT_GENAI,
            INSTRUMENT_GENAI.replace(
                "`chat`; provider and model attributes",
                "`chat`",
            ),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("required signals changed", result.stderr)

    def test_working_surface_requires_no_remaining_signals(self) -> None:
        result = self.validate(
            AUDIT_GENAI,
            INSTRUMENT_GENAI.replace(
                "| None | Working |",
                "| chat error proof | Working |",
            ),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Remaining signals None", result.stderr)

    def test_non_working_surface_names_remaining_signals(self) -> None:
        result = self.validate(
            AUDIT_GENAI,
            INSTRUMENT_GENAI.replace(
                "| OTLP log policy | Partial |",
                "| None | Partial |",
            ),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must name remaining signals", result.stderr)

    def test_working_surface_rejects_not_run_tests(self) -> None:
        result = self.validate(
            AUDIT_GENAI,
            INSTRUMENT_GENAI.replace(
                "| trace.success | None | Working |",
                "| Not run | None | Working |",
            ),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must name executed proof", result.stderr)

    def test_working_surface_rejects_diluted_not_run_tests(self) -> None:
        result = self.validate(
            AUDIT_GENAI,
            INSTRUMENT_GENAI.replace(
                "| trace.success | None | Working |",
                "| Tests blocked on CI and not run yet | None | Working |",
            ),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must name executed proof", result.stderr)

    def test_working_surface_allows_positive_proof_with_state_words(self) -> None:
        report = INSTRUMENT_GENAI.replace(
            "Both spans emitted with parentage",
            "All spans emitted with parentage; none missing",
        ).replace(
            "trace.success",
            "All pending-state and skipped-state label cases passed",
        )
        result = self.validate(AUDIT_GENAI, report)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_empty_genai_readiness_table(self) -> None:
        empty = AUDIT_GENAI.replace(
            "| Workflow/agent trace | missing | Workflow has no GenAI span | `invoke_workflow` | App-owned: app.py | Trace proves workflow parentage | Workflow failures cannot be localized |\n",
            "",
        ).replace(
            "| Provider/model call | missing | Provider call has no GenAI span | `chat`; provider and model attributes | App-owned: app.py | Trace proves model-call attributes and parentage | Model failures cannot be localized |\n",
            "",
        ).replace(
            "| Privacy/cardinality | partial | Metadata-only spans, stdout IDs remain | metadata-only capture; bounded dimensions | App-owned: logging.py | Sentinel export is clean | Telemetry may expose identifiers |\n",
            "",
        )
        result = self.validate(empty, INSTRUMENT_GENAI)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("at least one surface row", result.stderr)

    def test_rejects_genai_closure_after_validation_gates(self) -> None:
        misplaced = INSTRUMENT_NO_GENAI + "\n" + GENAI_CLOSURE
        result = self.validate(AUDIT_GENAI, misplaced)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("before Validation Gates", result.stderr)

    def test_rejects_duplicate_genai_closure_section(self) -> None:
        duplicated = INSTRUMENT_GENAI.replace(
            "\n## Validation Gates",
            f"\n{GENAI_CLOSURE}\n## Validation Gates",
        )
        result = self.validate(AUDIT_GENAI, duplicated)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("at most one ## GenAI Readiness Closure", result.stderr)

    def test_non_genai_audit_forbids_genai_closure(self) -> None:
        result = self.validate(AUDIT_NO_GENAI, INSTRUMENT_GENAI)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not contain ## GenAI Readiness Closure", result.stderr)

    def test_requires_source_audit_genai_ownership_declaration(self) -> None:
        incomplete = AUDIT_GENAI.replace(
            "**GenAI ownership detected:** Yes\n",
            "",
        )
        result = self.validate(incomplete, INSTRUMENT_GENAI)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly one GenAI ownership declaration", result.stderr)

    def test_rejects_duplicate_genai_closure_surface(self) -> None:
        row = (
            "| Privacy/cardinality | metadata-only capture; bounded dimensions "
            "| Span dimensions are bounded | telemetry.redaction | OTLP log policy "
            "| Partial |\n"
        )
        result = self.validate(
            AUDIT_GENAI,
            INSTRUMENT_GENAI.replace(row, row + row),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate GenAI closure surface", result.stderr)

    def test_rejects_duplicate_audit_genai_surface(self) -> None:
        row = (
            "| Privacy/cardinality | partial | Metadata-only spans, stdout IDs remain "
            "| metadata-only capture; bounded dimensions | App-owned: logging.py "
            "| Sentinel export is clean | Telemetry may expose identifiers |\n"
        )
        result = self.validate(
            AUDIT_GENAI.replace(row, row + row),
            INSTRUMENT_GENAI,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate audit GenAI readiness surface", result.stderr)

    def test_rejects_extra_genai_closure_surface(self) -> None:
        extra = (
            "| Evaluation quality | evaluation event | None | ownership review "
            "| evaluator owner | Owner-mapped |\n"
        )
        report = INSTRUMENT_GENAI.replace(
            "\n## Validation Gates",
            f"{extra}\n## Validation Gates",
        )
        result = self.validate(AUDIT_GENAI, report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("extra=['Evaluation quality']", result.stderr)


if __name__ == "__main__":
    unittest.main()
