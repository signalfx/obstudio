from __future__ import annotations

import importlib.util
import io
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock
from pathlib import Path


VALIDATOR = Path(__file__).parents[1] / "scripts" / "validate_audit_report.py"
REPORT_WRAPPER = Path(__file__).parents[1] / "scripts" / "observe_report.py"
WRAPPER_SPEC = importlib.util.spec_from_file_location(
    "otel_audit_observe_report_wrapper", REPORT_WRAPPER
)
assert WRAPPER_SPEC is not None and WRAPPER_SPEC.loader is not None
WRAPPER = importlib.util.module_from_spec(WRAPPER_SPEC)
WRAPPER_SPEC.loader.exec_module(WRAPPER)

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
    empty_gaps = """| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|

No gaps found."""
    genai_gap = """| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|
| required | Provider/model calls | Provider model calls have no GenAI span | Model failures cannot be localized | Emit a bounded `chat` span | default | http.search.success |"""
    return (
        VALID_REPORT.replace("**Status:** Pass", "**Status:** Partial")
        .replace(
            "**GenAI ownership detected:** No",
            "**GenAI ownership detected:** Yes",
        )
        .replace(
            "| GenAI ownership | No | repository dependency and source scan |",
            "| GenAI ownership | Yes | app/harness.py; pyproject.toml |",
        )
        .replace(current, f"{current}\n\n{GENAI_READINESS}")
        .replace(empty_gaps, genai_gap)
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
    return (
        VALID_REPORT.replace("**Status:** Pass", "**Status:** Partial")
        .replace(current, readiness)
        .replace(gap_table, gap_row)
    )


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

    def test_accepts_source_proven_java_agent_duplicate_owner(self) -> None:
        report = (
            VALID_REPORT.replace("**Status:** Pass", "**Status:** Partial")
            .replace(
                "[SOURCE-COVERED] Client -> API",
                "[SOURCE-COVERED] Client -> API [GAP: HTTP server request telemetry]",
            )
            .replace(
                """| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|

No gaps found.""",
                """| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|
| required | HTTP server request telemetry | Duplicate HTTP server spans can overlap | Operators need one canonical request trace | Make the OpenTelemetry Java agent the canonical HTTP server telemetry owner | default | http.search.success |""",
            )
        )

        result = self.validate(report)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepts_combined_unit_runtime_proof_level_alias(self) -> None:
        report = VALID_REPORT.replace("focused call-site", "unit plus runtime")

        result = self.validate(report)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepts_escaped_pipe_in_rendered_table_cell(self) -> None:
        report = VALID_REPORT.replace(
            "repository dependency and source scan",
            r"repository dependency \| source scan",
        )

        result = self.validate(report)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_report_wrapper_missing_helper_is_a_tool_error(self) -> None:
        missing = Path("/definitely/missing/observe_report.py")
        error = io.StringIO()
        with (
            mock.patch.object(WRAPPER, "shared_tool_path", return_value=missing),
            redirect_stderr(error),
        ):
            self.assertEqual(WRAPPER.main(), 1)
        self.assertIn("OpenTelemetry report helper is missing", error.getvalue())

    def test_accepts_external_follow_up_instrument_mode(self) -> None:
        gap_table = """| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|

No gaps found."""
        external_gap = """| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|
| deferred | External edge telemetry | External edge latency and error signals have no known service feed | Edge failures cannot be separated from application failures | Have the named platform telemetry owner supply bounded edge metrics and synthetic proof | external follow-up | http.search.success |"""
        report = VALID_REPORT.replace("**Status:** Pass", "**Status:** Partial")
        result = self.validate(report.replace(gap_table, external_gap))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepts_service_owned_canonical_duplicate_remediation(self) -> None:
        gap_table = """| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|

No gaps found."""
        owned_gap = """| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|
| required | Metric export | Duplicate metric export is possible | Metrics can be counted twice | Keep MetricReporter as the service-owned canonical custom-metric exporter | default | http.search.success |"""
        report = VALID_REPORT.replace("**Status:** Pass", "**Status:** Partial")

        result = self.validate(report.replace(gap_table, owned_gap))

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_status_matches_source_visible_gap_state(self) -> None:
        gap_table = """| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|

No gaps found."""
        gap = """| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|
| required | HTTP telemetry | HTTP spans are missing | Requests cannot be traced | Add route-aware server spans | default | http.search.success |"""

        pass_with_gap = VALID_REPORT.replace(gap_table, gap)
        result = self.validate(pass_with_gap)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Status Pass requires zero source-visible gaps", result.stderr)

        partial_without_gap = VALID_REPORT.replace(
            "**Status:** Pass", "**Status:** Partial"
        )
        result = self.validate(partial_without_gap)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "Status Partial requires at least one source-visible gap", result.stderr
        )

    def test_rejects_unknown_instrument_mode(self) -> None:
        gap_table = """| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|

No gaps found."""
        invalid_gap = """| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|
| deferred | Edge ownership | Edge owner is outside this service | Incidents can be routed incorrectly | Track the platform owner | external | http.search.success |"""
        report = VALID_REPORT.replace("**Status:** Pass", "**Status:** Partial")
        result = self.validate(report.replace(gap_table, invalid_gap))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid instrument mode: external", result.stderr)

    def test_rejects_undefined_environment(self) -> None:
        report = VALID_REPORT.replace(
            "| focused-test |\n\n## Anti-Patterns",
            "| missing-profile |\n\n## Anti-Patterns",
        )
        result = self.validate(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("undefined environment IDs", result.stderr)

    def test_blocked_status_requires_scan_blocker_details(self) -> None:
        missing = self.validate(VALID_REPORT.replace("**Status:** Pass", "**Status:** Blocked"))
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("scan-blocker details", missing.stderr)

        present = VALID_REPORT.replace("**Status:** Pass", "**Status:** Blocked").replace(
            "- Source-derived plan is ready.",
            "- Scan blocked: BLOCK-001 — generated sources are unavailable.",
        )
        result = self.validate(present)
        self.assertEqual(result.returncode, 0, result.stderr)

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

    def test_accepts_canonical_scan_blockers_section(self) -> None:
        report = VALID_REPORT.replace("**Status:** Pass", "**Status:** Blocked")
        report = report.replace(
            "- Source-derived plan is ready.",
            "- Scan blocked: generated sources were unavailable.",
        )
        report = report.replace(
            "## Signal Flow",
            """## Scan Blockers
| ID | Check | Blocked scope | Prerequisite | Evidence | Required action |
|---|---|---|---|---|---|
| BLOCK-001 | source-scan | generated/ | Generated sources are unavailable | `.observe/evidence/source-scan.txt` | Provide generated sources |

## Signal Flow""",
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

    def test_external_owner_mapped_genai_is_complete_without_a_gap(self) -> None:
        empty_gaps = """## Gaps
| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|

No gaps found.

"""
        genai = with_genai_readiness().replace(
            "| Provider/model calls | missing |",
            "| Provider/model calls | owner-mapped |",
        ).replace(
            "| App-owned: app/harness.py |",
            "| Provider/platform-owned: billing API |",
        ).replace("**Status:** Partial", "**Status:** Pass")
        genai = re.sub(
            r"(?ms)^## Gaps\n.*?(?=^## Verification Plan)",
            empty_gaps,
            genai,
        )
        genai_result = self.validate(genai)

        self.assertEqual(genai_result.returncode, 0, genai_result.stderr)

    def test_owner_mapped_readiness_rejects_app_owner_or_missing_incident_owner(self) -> None:
        genai = with_genai_readiness().replace(
            "| Provider/model calls | missing |",
            "| Provider/model calls | owner-mapped |",
        )
        incident = with_incident_readiness().replace(
            "| Queue pressure | partial |",
            "| Queue pressure | owner-mapped |",
        ).replace("**Status:** Partial", "**Status:** Pass")
        incident = re.sub(
            r"(?ms)^## Gaps\n.*?(?=^## Verification Plan)",
            """## Gaps
| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|

No gaps found.

""",
            incident,
        )

        genai_result = self.validate(genai)
        incident_result = self.validate(incident)
        generic_external_owner_result = self.validate(
            genai.replace("| App-owned: app/harness.py |", "| external team |")
        )

        self.assertNotEqual(genai_result.returncode, 0)
        self.assertIn("must name an exact external", genai_result.stderr)
        self.assertNotEqual(generic_external_owner_result.returncode, 0)
        self.assertIn(
            "must name an exact external", generic_external_owner_result.stderr
        )
        self.assertNotEqual(incident_result.returncode, 0)
        self.assertIn(
            "partial, missing, or owner-mapped Incident Readiness area",
            incident_result.stderr,
        )

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

    def test_rejects_covered_incident_readiness_with_prioritized_gap(self) -> None:
        report = with_incident_readiness().replace(
            "| Queue pressure | partial |",
            "| Queue pressure | covered |",
        )
        result = self.validate(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "covered Incident Readiness areas must not have "
            "prioritized gaps",
            result.stderr,
        )

    def test_rejects_incident_readiness_with_undefined_scenario(self) -> None:
        result = self.validate(
            with_incident_readiness(verification_scenarios="queue.pressure")
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("undefined verification scenario IDs", result.stderr)


if __name__ == "__main__":
    unittest.main()
