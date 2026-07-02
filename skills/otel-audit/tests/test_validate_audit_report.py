from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


VALIDATOR = Path(__file__).parents[1] / "scripts" / "validate_audit_report.py"

VALID_REPORT = """# OTel Audit: sample

**Status:** Pass
**GenAI ownership detected:** No

## Executive Summary
- Source-derived plan is ready.

## Flow
audit -> instrument -> verify

## Audit Evidence
| Check | Finding | Source |
|---|---|---|
| Manifest | Python | pyproject.toml |
| Entry point | API | app.py |
| Route source | One route | routes.py |
| Runtime/startup | uv | uv.lock |
| GenAI ownership | No | repository dependency and source scan |

## Signal Flow
### Component Flow Map
[SOURCE-COVERED] Client -> API

## Current Instrumentation
No spans detected.

## Gaps
| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|

No gaps found.

## Verification Plan
### Test Environments
| Environment ID | Surface | Config Evidence | Runner / Toolchain | Scope | Shared Prerequisites |
|---|---|---|---|---|---|
| focused-test | API module | pyproject.toml | uv run pytest | import and focused test | fake repository |

### Acceptance Scenarios
| Scenario ID | Trigger / Path | Source Entrypoint | Expected Signals | Proof Level | Acceptance Criteria | Environment |
|---|---|---|---|---|---|---|
| http.search.success | GET /search | routes.py:search | search span | focused call-site | span has OK status | focused-test |

## Anti-Patterns
- None detected.

## Recommendation
- Run $otel-verify.
"""

GENAI_READINESS = """## GenAI Readiness
| Surface | Status | Evidence | Required Signals | Owner / Source Files | Acceptance Criteria | Detection/Localization Impact |
|---|---|---|---|---|---|---|
| Provider/model calls | missing | DeepAgents model call detected without a GenAI span | `chat` span with provider and model attributes | App-owned: app/harness.py | In-memory trace proves stable name, attributes, and parentage | Model failures cannot be localized |"""


def with_genai_readiness() -> str:
    current = "## Current Instrumentation\nNo spans detected."
    return (
        VALID_REPORT.replace(
            "**GenAI ownership detected:** No",
            "**GenAI ownership detected:** Yes",
        )
        .replace(
            "| GenAI ownership | No | repository dependency and source scan |",
            "| GenAI ownership | Yes | app/harness.py; pyproject.toml |",
        )
        .replace(current, f"{current}\n\n{GENAI_READINESS}")
    )


def with_incident_readiness(
    *,
    readiness_area: str = "Queue pressure",
    gap_area: str = "Queue pressure",
    verification_scenarios: str = "http.search.success",
) -> str:
    current = "## Current Instrumentation\nNo spans detected."
    readiness = f"""{current}

### Incident Readiness
| Area | Status | Evidence | Required Signals / Gap | Detection / Localization Impact |
|---|---|---|---|---|
| {readiness_area} | partial | Queue depth is present | Oldest message age | MTTD-improving |"""
    gap_table = """| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|

No gaps found."""
    gap_row = f"""| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|
| required | {gap_area} | Oldest message age is missing | Backlog can age silently | Add oldest message age | default | {verification_scenarios} |"""
    return VALID_REPORT.replace(current, readiness).replace(gap_table, gap_row)


class ValidateAuditReportTest(unittest.TestCase):
    def validate(self, report: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "otel.md"
            path.write_text(report, encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(VALIDATOR), str(path)],
                check=False,
                capture_output=True,
                text=True,
            )

    def test_accepts_environment_references(self) -> None:
        result = self.validate(VALID_REPORT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1 test environments, 1 acceptance scenarios", result.stdout)

    def test_rejects_undefined_environment(self) -> None:
        report = VALID_REPORT.replace(
            "| focused-test |\n\n## Anti-Patterns",
            "| missing-profile |\n\n## Anti-Patterns",
        )
        result = self.validate(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("undefined environment IDs", result.stderr)

    def test_rejects_unexpected_top_level_heading(self) -> None:
        report = VALID_REPORT.replace(
            "## Anti-Patterns",
            "## Internal Notes\n- Not part of the contract.\n\n## Anti-Patterns",
        )
        result = self.validate(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected top-level sections", result.stderr)

    def test_rejects_gaps_before_current_instrumentation(self) -> None:
        current = "## Current Instrumentation\nNo spans detected."
        gaps = """## Gaps
| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|

No gaps found."""
        report = VALID_REPORT.replace(
            f"{current}\n\n{gaps}",
            f"{gaps}\n\n{current}",
        )
        result = self.validate(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reader-first section order is incorrect", result.stderr)

    def test_rejects_routes_outside_reader_order(self) -> None:
        report = VALID_REPORT.replace(
            "## Recommendation",
            "## Routes\n- `GET /health`\n\n## Recommendation",
        )
        result = self.validate(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "## Routes must appear after Audit Evidence and before Signal Flow",
            result.stderr,
        )

    def test_accepts_routes_in_reader_order(self) -> None:
        report = VALID_REPORT.replace(
            "## Signal Flow",
            "## Routes\n- `GET /health`\n\n## Signal Flow",
        )
        result = self.validate(report)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_genai_readiness_is_current_state_before_gaps(self) -> None:
        current = "## Current Instrumentation\nNo spans detected."
        genai = GENAI_READINESS
        report = with_genai_readiness()
        result = self.validate(report)
        self.assertEqual(result.returncode, 0, result.stderr)

        misplaced = report.replace(
            f"{current}\n\n{genai}",
            current,
        ).replace("## Verification Plan", f"{genai}\n\n## Verification Plan")
        result = self.validate(misplaced)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("before Gaps", result.stderr)

        misplaced = report.replace(
            f"{current}\n\n{genai}",
            f"{genai}\n\n{current}",
        )
        result = self.validate(misplaced)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("after Current Instrumentation", result.stderr)

    def test_genai_yes_requires_readiness_table(self) -> None:
        report = with_genai_readiness().replace(f"\n\n{GENAI_READINESS}", "")
        result = self.validate(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GenAI ownership is Yes", result.stderr)

    def test_genai_no_forbids_readiness_table(self) -> None:
        current = "## Current Instrumentation\nNo spans detected."
        report = VALID_REPORT.replace(current, f"{current}\n\n{GENAI_READINESS}")
        result = self.validate(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GenAI ownership is No", result.stderr)

    def test_genai_declaration_must_match_evidence(self) -> None:
        report = with_genai_readiness().replace(
            "| GenAI ownership | Yes | app/harness.py; pyproject.toml |",
            "| GenAI ownership | No | repository dependency and source scan |",
        )
        result = self.validate(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("declaration and Audit Evidence row disagree", result.stderr)

    def test_rejects_duplicate_genai_declaration(self) -> None:
        report = VALID_REPORT.replace(
            "**GenAI ownership detected:** No",
            "**GenAI ownership detected:** No\n**GenAI ownership detected:** Yes",
        )
        result = self.validate(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly one GenAI ownership declaration", result.stderr)

    def test_section_name_mentions_are_not_treated_as_headings(self) -> None:
        report = VALID_REPORT.replace(
            "- Source-derived plan is ready.",
            "- Source-derived plan is ready; see `## GenAI Readiness` and `## Gaps`.",
        )
        result = self.validate(report)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepts_incident_readiness_with_matching_gap_and_scenario(self) -> None:
        result = self.validate(with_incident_readiness())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_incident_readiness_without_identical_gap_area(self) -> None:
        result = self.validate(with_incident_readiness(gap_area="Different area"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no identical prioritized Gaps Area", result.stderr)

    def test_rejects_incident_readiness_with_undefined_scenario(self) -> None:
        result = self.validate(
            with_incident_readiness(verification_scenarios="queue.pressure")
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("undefined verification scenario IDs", result.stderr)


if __name__ == "__main__":
    unittest.main()
