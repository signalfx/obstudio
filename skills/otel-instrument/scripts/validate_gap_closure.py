#!/usr/bin/env python3
"""Validate one-to-one audit gap closure in an instrumentation report."""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType


GAP_HEADER = [
    "Priority",
    "Area",
    "Gap",
    "Why it matters",
    "Required fix",
    "Instrument mode",
    "Verification scenarios",
]
LEGACY_CLOSURE_HEADER = [
    "Priority",
    "Gap",
    "What changed",
    "Tested",
    "Result",
    "Evidence / reason",
]
CANONICAL_CLOSURE_HEADER = [
    "Finding",
    "What changed",
    "Tested",
    "Result",
    "Evidence / reason",
]
RESULTS = {"Working", "Not working", "Not proven", "Not configured", "Deferred"}
GENAI_CLOSURE_HEADER = [
    "Surface",
    "Required signals",
    "Implemented / proven",
    "Tests",
    "Remaining signals",
    "Result",
]
GENAI_RESULTS = {
    "Working",
    "Partial",
    "Not working",
    "Not proven",
    "Not configured",
    "Deferred",
    "Owner-mapped",
}
INCIDENT_SIGNAL_ROLE_HEADER = [
    "Surface",
    "Exact signal",
    "Role",
    "Detector use / reason",
    "Proof",
    "Remaining owner / prerequisite",
]
INCIDENT_SIGNAL_ROLES = {
    "MTTD-improving",
    "localization-only",
    "provider/platform-owned",
    "uncovered",
}
UNPROVEN_PROOF = re.compile(
    r"(?:^\s*(?:none|unproven|blocked|pending|skipped|n/?a)\b|"
    r"\b(?:not proven|not configured|not run|not tested)\b|"
    r"\btests?\s+(?:are\s+)?blocked\b)",
    re.IGNORECASE,
)
NEGATIVE_OR_UNCERTAIN_PROOF = re.compile(
    r"(?:^\s*(?:none|unproven|blocked|pending|skipped|unknown|n/?a)\b|"
    r"\b(?:not proven|not configured|not run|not tested|unsuccessful|"
    r"failed|failure|errored?|rejected|denied|unavailable|uncertain)\b|"
    r"\b(?:could|did)\s+not\b|\bno\s+(?:evidence|result|output|proof)\b|"
    r"\btests?\s+(?:are\s+)?blocked\b)",
    re.IGNORECASE,
)
AFFIRMATIVE_EXECUTED_PROOF = re.compile(
    r"\b(?:pass(?:ed)?|success(?:ful(?:ly)?)?|succeed(?:ed)?|completed|executed|"
    r"accepted|captured|observed|emitted|exported|recorded|assert(?:ed|ion)?|"
    r"go\s+test|pytest|cargo\s+test|(?:npm|pnpm|yarn|bun)(?:\s+run)?\s+test|"
    r"(?:gradle|gradlew|mvn|mvnw)\b[^\r\n;|]*\b(?:test|check|verify)|"
    r"dotnet\s+test|bundle\s+exec\s+(?:rspec|rake\s+test)|"
    r"(?:composer\s+(?:exec\s+)?)?(?:vendor/bin/)?phpunit)\b",
    re.IGNORECASE,
)
NON_EXECUTING_TEST_PROOF = re.compile(
    r"(?:\b(?:gradle|gradlew)\b[^\r\n;|]*"
    r"(?:--dry-run|(?<!\S)-m(?=\s|$)|"
    r"(?:--exclude-task|-x)(?:=|\s+)(?:test|check|verify)\b)|"
    r"\b(?:mvn|mvnw)\b[^\r\n;|]*"
    r"-D(?:skipTests|maven\.test\.skip)"
    r"(?:=(?:true|1|yes))?(?=\s|$))",
    re.IGNORECASE,
)
POSITIVE_PROOF_EVIDENCE = re.compile(
    r"(?:^|/)\.observe/evidence/|"
    r"(?:^|[\s/])[A-Za-z0-9_.-]+\.(?:jsonl?|txt|log|xml|html?|md|out|"
    r"tap|junit|otlp|pb)(?=$|[\s,;:])|"
    r"\b(?:pass(?:ed)?|succeed(?:ed)?|accepted|captured|observed|emitted|"
    r"exported|recorded|assertion)\b",
    re.IGNORECASE,
)
DURABLE_ARTIFACT_REFERENCE = re.compile(
    r"(?:^|[\s;`])(?:\.?[A-Za-z0-9_.-]+[/\\])*[A-Za-z0-9_.-]+\."
    r"(?:jsonl?|txt|log|xml|html?|md|out|tap|junit|otlp|pb)(?=$|[\s,;:`])",
    re.IGNORECASE,
)
NON_PROOF_ARTIFACT_LABEL = re.compile(
    r"\b(?:none|unproven|not\s+(?:proven|configured|run|tested)|blocked|"
    r"pending|skipped|unknown)\b",
    re.IGNORECASE,
)
JSON_STATUS_LABELS = {
    "working": "Working",
    "not_working": "Not working",
    "not_proven": "Not proven",
    "not_configured": "Not configured",
    "deferred": "Deferred",
}


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def has_meaningful_instrumentation_proof(instrumentation_json: dict) -> bool:
    """Return whether implementation-owned scope records any completed proof."""

    def affirmative_entries(value: object, pattern: re.Pattern[str]) -> bool:
        return (
            isinstance(value, list)
            and bool(value)
            and all(
                isinstance(item, str)
                and bool(item.strip())
                and not NON_EXECUTING_TEST_PROOF.search(item)
                and not NEGATIVE_OR_UNCERTAIN_PROOF.search(
                    re.sub(r"[._/-]+", " ", item)
                )
                and pattern.search(re.sub(r"[._/-]+", " ", item))
                for item in value
            )
        )

    def positive_evidence(value: object) -> bool:
        def positive_item(item: object) -> bool:
            if not isinstance(item, str) or not item.strip():
                return False
            artifact_refs = list(DURABLE_ARTIFACT_REFERENCE.finditer(item))
            if any(
                NON_PROOF_ARTIFACT_LABEL.search(
                    re.sub(r"[._/\\-]+", " ", match.group(0))
                )
                for match in artifact_refs
            ):
                return False
            outcome_prose = DURABLE_ARTIFACT_REFERENCE.sub(" ", item)
            return bool(
                not NEGATIVE_OR_UNCERTAIN_PROOF.search(
                    re.sub(r"[._/\\-]+", " ", outcome_prose)
                )
                and POSITIVE_PROOF_EVIDENCE.search(item)
            )

        return (
            isinstance(value, list)
            and bool(value)
            and all(positive_item(item) for item in value)
        )

    for finding in instrumentation_json.get("findings", []):
        if not isinstance(finding, dict):
            continue
        if (
            finding.get("status") == "working"
            and affirmative_entries(
                finding.get("tests"), AFFIRMATIVE_EXECUTED_PROOF
            )
            and positive_evidence(finding.get("evidence"))
        ):
            return True

    return False


def expected_report_result(
    instrumentation_json: dict,
    overlay_json: dict,
    *,
    verification_overlay: bool,
) -> str:
    """Aggregate the authoritative finding verification result."""
    if not verification_overlay:
        return str(instrumentation_json.get("meta", {}).get("result"))

    verification_result = overlay_json.get("meta", {}).get("result")
    if verification_result not in {"Pass", "Partial", "Fail", "Blocked", "Not run"}:
        fail(f"unsupported verification result: {verification_result}")
    if verification_result == "Fail":
        return "Fail"
    if verification_result == "Blocked":
        return (
            "Partial"
            if has_meaningful_instrumentation_proof(instrumentation_json)
            else "Blocked"
        )
    return "Partial" if verification_result == "Not run" else verification_result


def heading_match(text: str, heading: str) -> re.Match[str]:
    match = re.search(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE)
    if not match:
        fail(f"missing section {heading}")
    return match


def section(text: str, heading: str) -> str:
    start = heading_match(text, heading).end()
    match = re.search(r"^## ", text[start:], re.MULTILINE)
    return text[start : start + match.start()] if match else text[start:]


def subsection(text: str, heading: str) -> str:
    marker = f"### {heading}"
    match = re.search(rf"^{re.escape(marker)}\s*$", text, re.MULTILINE)
    if not match:
        fail(f"missing subsection {marker}")
    start = match.end()
    next_heading = re.search(r"^### ", text[start:], re.MULTILINE)
    return text[start : start + next_heading.start()] if next_heading else text[start:]


def split_row(line: str) -> list[str]:
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|") and not value.endswith(r"\|"):
        value = value[:-1]
    return [
        cell.replace(r"\|", "|").strip()
        for cell in re.split(r"(?<!\\)\|", value)
    ]


def table(body: str, label: str) -> tuple[list[str], list[list[str]]]:
    lines: list[str] = []
    in_table = False
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line.startswith("|"):
            in_table = True
            lines.append(line)
        elif in_table:
            break
    if len(lines) < 2:
        fail(f"{label} table is missing")
    header = split_row(lines[0])
    rows = [split_row(line) for line in lines[2:]]
    return header, rows


def load_shared_report_module() -> ModuleType:
    shared = (
        Path(__file__).resolve().parents[2]
        / "references"
        / "scripts"
        / "observe_report.py"
    )
    if not shared.is_file():
        fail(f"shared canonical flow validator is missing: {shared}")
    spec = importlib.util.spec_from_file_location(
        "otel_gap_closure_observe_report", shared
    )
    if spec is None or spec.loader is None:
        fail(f"cannot load shared canonical flow validator: {shared}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_bound_flow(
    audit_json_path: Path,
    selection_json_path: Path | None,
    instrumentation_json_path: Path,
    verify_json_path: Path | None,
) -> tuple[dict, dict, dict, dict]:
    if not audit_json_path.is_file():
        fail("a canonical audit JSON report is required and must exist")
    if not instrumentation_json_path.is_file():
        fail("an authoritative instrumentation JSON overlay is required and must exist")
    selection = selection_json_path or audit_json_path.parent / "otel-selection.json"
    if not selection.is_file():
        fail(
            "canonical JSON projection requires --selection-json or sibling "
            "otel-selection.json"
        )
    module = load_shared_report_module()
    try:
        audit_json = module.normalize_audit_report(module.load_json(audit_json_path))
        selection_json, instrumentation_json, verify_json = module.load_flow(
            audit_json,
            selection,
            instrumentation_json_path,
            verify_json_path,
        )
    except (OSError, ValueError) as error:
        fail(f"canonical audit/selection/overlay flow is invalid: {error}")
    if instrumentation_json is None:
        fail("canonical flow did not contain an instrumentation overlay")
    overlay_json = verify_json or instrumentation_json
    return audit_json, selection_json, instrumentation_json, overlay_json


def json_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{path} must be a non-empty string")
    return value


def json_string_list(value: object, path: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        fail(f"{path} must be an array of non-empty strings")
    return value


def validate_json_projection(
    closure_rows: list[list[str]],
    report_result: str,
    audit_json: dict,
    selection_json: dict,
    instrumentation_json: dict,
    overlay_json: dict,
    *,
    verification_overlay: bool,
) -> None:
    expected_result = expected_report_result(
        instrumentation_json,
        overlay_json,
        verification_overlay=verification_overlay,
    )
    if report_result != expected_result:
        fail(
            "instrumentation Markdown Result disagrees with the aggregate current "
            "state from finding verification and instrumentation GenAI closure: "
            f"markdown={report_result}, expected={expected_result}"
        )
    audit_findings_by_id = {
        finding.get("id"): finding
        for finding in audit_json.get("findings", [])
        if isinstance(finding, dict)
    }
    selected_findings = [
        audit_findings_by_id[finding_id]
        for finding_id in selection_json.get("approved_ids", [])
    ]
    canonical_labels = [
        f"{finding['id']} — {finding['title']}" for finding in selected_findings
    ]
    markdown_labels = [row[0] for row in closure_rows]
    if markdown_labels != canonical_labels:
        fail(
            "instrumentation Markdown closure rows must exactly follow canonical "
            "selected finding order: "
            f"markdown={markdown_labels}, selected={canonical_labels}"
        )
    closure_by_id = {
        finding["id"]: row for finding, row in zip(selected_findings, closure_rows)
    }
    instrumentation_by_id = {
        row.get("id"): row
        for row in instrumentation_json.get("findings", [])
        if isinstance(row, dict)
    }
    overlay_status_by_id = {
        row.get("id"): row.get("status")
        for row in overlay_json.get("findings", [])
        if isinstance(row, dict)
    }
    for finding in selected_findings:
        finding_id = finding["id"]
        row = closure_by_id[finding_id]
        raw_status = overlay_status_by_id.get(finding_id, "deferred")
        expected = JSON_STATUS_LABELS.get(raw_status)
        if expected is None:
            fail(f"unsupported JSON closure status for {finding_id}: {raw_status}")
        if row[3] != expected:
            fail(
                "instrumentation Markdown closure disagrees with the current JSON "
                f"overlay for {finding_id}: markdown={row[3]}, overlay={expected}"
            )

        implementation = instrumentation_by_id.get(finding_id)
        if implementation is None:
            continue
        expected_content = [
            "; ".join(
                json_string_list(
                    implementation.get("changes"),
                    f"instrumentation.findings[{finding_id}].changes",
                )
            ),
            "; ".join(
                json_string_list(
                    implementation.get("tests"),
                    f"instrumentation.findings[{finding_id}].tests",
                )
            ),
            "; ".join(
                json_string_list(
                    implementation.get("evidence"),
                    f"instrumentation.findings[{finding_id}].evidence",
                )
            ),
        ]
        markdown_content = [row[1], row[2], row[4]]
        if markdown_content != expected_content:
            fail(
                "instrumentation Markdown closure content disagrees with the "
                f"current instrumentation JSON for {finding_id}: "
                f"markdown={markdown_content}, overlay={expected_content}"
            )

def validate(
    instrumentation_path: Path,
    audit_json_path: Path,
    instrumentation_json_path: Path,
    selection_json_path: Path | None = None,
    verify_json_path: Path | None = None,
) -> None:
    instrumentation = instrumentation_path.read_text(encoding="utf-8")
    audit_json, selection_json, instrumentation_json, overlay_json = load_bound_flow(
        audit_json_path,
        selection_json_path,
        instrumentation_json_path,
        verify_json_path,
    )

    result_matches = list(
        re.finditer(
            r"^\*\*Result:\*\* (Pass|Partial|Fail|Blocked)\s*$",
            instrumentation,
            re.MULTILINE,
        )
    )
    if len(result_matches) != 1:
        fail("instrumentation report must contain exactly one valid Result declaration")
    result_match = result_matches[0]
    report_result = result_match.group(1)

    closure_header, closure_rows = table(
        section(instrumentation, "## Audit Gap Closure"), "Audit Gap Closure"
    )
    overlay_present = (
        instrumentation_json_path is not None or verify_json_path is not None
    )
    audit_json_present = audit_json_path is not None
    if audit_json_present != overlay_present:
        fail("--audit-json and a current --instrumentation-json/--verify-json must be used together")
    canonical_flow = audit_json_path is not None and overlay_present
    expected_header = (
        CANONICAL_CLOSURE_HEADER if canonical_flow else LEGACY_CLOSURE_HEADER
    )
    if closure_header != expected_header:
        fail(f"Audit Gap Closure header must be {expected_header}")

    closure_keys: list[tuple[str, str]] = []
    closure_statuses: list[str] = []
    for row in closure_rows:
        if len(row) != len(expected_header):
            fail(f"malformed closure row: {row}")
        status_index = 3 if canonical_flow else 4
        if row[status_index] not in RESULTS:
            fail(f"invalid closure result: {row[status_index]}")
        content_indexes = (1, 2, 4) if canonical_flow else (2, 3, 5)
        if any(not row[index] for index in content_indexes):
            fail(f"closure row lacks action, test, or evidence: {row[0]}")
        closure_statuses.append(row[status_index])
        if not canonical_flow:
            closure_keys.append((row[0], row[1]))

    if not canonical_flow:
        audit_keys = [(row[0], row[1]) for row in gap_rows]
        if sorted(audit_keys) != sorted(closure_keys):
            fail(
                "audit and closure rows differ: "
                f"missing={sorted(set(audit_keys) - set(closure_keys))}, "
                f"extra={sorted(set(closure_keys) - set(audit_keys))}"
            )
    gap_result_blockers = {
        status
        for status in closure_statuses
        if status in {"Not working", "Not proven", "Not configured"}
    }

    audit_current_instrumentation = audit_json.get("current_instrumentation", {})
    audit_incident_readiness = bool(
        audit_current_instrumentation.get("incident_readiness", [])
        if isinstance(audit_current_instrumentation, dict)
        else []
    )

    if audit_incident_readiness:
        if not re.search(r"^## Signals Changed\s*$", instrumentation, re.MULTILINE):
            fail(
                "incident-readiness audit requires ## Signals Changed with an "
                "Incident Readiness Signal Roles inventory"
            )
        signals_changed = section(instrumentation, "## Signals Changed")
        role_headings = list(
            re.finditer(
                r"^### Incident Readiness Signal Roles\s*$",
                signals_changed,
                re.MULTILINE,
            )
        )
        if len(role_headings) != 1:
            fail(
                "incident-readiness audit requires exactly one "
                "### Incident Readiness Signal Roles subsection under ## Signals Changed"
            )
        role_header, role_rows = table(
            subsection(signals_changed, "Incident Readiness Signal Roles"),
            "Incident Readiness Signal Roles",
        )
        if role_header != INCIDENT_SIGNAL_ROLE_HEADER:
            fail(
                "Incident Readiness Signal Roles header must be "
                f"{INCIDENT_SIGNAL_ROLE_HEADER}"
            )
        if not role_rows:
            fail("Incident Readiness Signal Roles must contain at least one signal row")
        for row in role_rows:
            if len(row) != len(INCIDENT_SIGNAL_ROLE_HEADER) or any(
                not cell for cell in row
            ):
                fail(f"malformed Incident Readiness Signal Roles row: {row}")
            if row[2] not in INCIDENT_SIGNAL_ROLES:
                fail(f"invalid Incident Readiness signal role: {row[2]}")

    audit_genai_rows = audit_json.get("genai_readiness", [])
    if not isinstance(audit_genai_rows, list):
        fail("canonical audit genai_readiness must be an array")
    genai_detected = bool(audit_genai_rows)
    instrumentation_genai_headings = list(
        re.finditer(
            r"^## GenAI Readiness Closure\s*$", instrumentation, re.MULTILINE
        )
    )
    if len(instrumentation_genai_headings) > 1:
        fail("instrumentation report must contain at most one ## GenAI Readiness Closure section")
    instrumentation_genai_heading = (
        instrumentation_genai_headings[0]
        if instrumentation_genai_headings
        else None
    )

    if genai_detected and not instrumentation_genai_heading:
        fail("GenAI audit requires ## GenAI Readiness Closure")
    if not genai_detected and instrumentation_genai_heading:
        fail("non-GenAI audit must not contain ## GenAI Readiness Closure")

    genai_surface_count = 0
    genai_result_blockers = set()
    genai_closure_rows: list[list[str]] = []
    if genai_detected:
        genai_closure_header, genai_closure_rows = table(
            section(instrumentation, "## GenAI Readiness Closure"),
            "GenAI Readiness Closure",
        )
        if genai_closure_header != GENAI_CLOSURE_HEADER:
            fail(f"GenAI Readiness Closure header must be {GENAI_CLOSURE_HEADER}")

        closure_by_surface = {}
        for row in genai_closure_rows:
            if len(row) != len(GENAI_CLOSURE_HEADER) or any(
                not row[index] for index in (0, 1, 4, 5)
            ):
                fail(f"malformed GenAI closure row: {row}")
            surface, required, implemented, _tests, remaining, result = row
            if result not in GENAI_RESULTS:
                fail(f"invalid GenAI closure result: {result}")
            if surface in closure_by_surface:
                fail(f"duplicate GenAI closure surface: {surface}")
            if result == "Working":
                if remaining != "None":
                    fail(f"Working GenAI surface must have Remaining signals None: {surface}")
                if not implemented or UNPROVEN_PROOF.search(implemented):
                    fail(f"Working GenAI surface must name implemented or proven signals: {surface}")
                if not _tests or UNPROVEN_PROOF.search(_tests):
                    fail(f"Working GenAI surface must name executed proof: {surface}")
            elif remaining == "None":
                fail(f"non-Working GenAI surface must name remaining signals: {surface}")
            if result in {"Partial", "Not working", "Not proven", "Not configured"}:
                genai_result_blockers.add(result)
            closure_by_surface[surface] = row

        gap_position = heading_match(instrumentation, "## Audit Gap Closure").start()
        genai_position = instrumentation_genai_heading.start()
        validation_position = heading_match(instrumentation, "## Validation Gates").start()
        if not gap_position < genai_position < validation_position:
            fail(
                "## GenAI Readiness Closure must appear after Audit Gap Closure "
                "and before Validation Gates"
            )
        genai_surface_count = len(genai_closure_rows)

    if report_result == "Pass" and (gap_result_blockers or genai_result_blockers):
        fail(
            "report Result Pass conflicts with unresolved closure results: "
            f"audit={sorted(gap_result_blockers)}, "
            f"genai={sorted(genai_result_blockers)}"
        )

    validate_json_projection(
        closure_rows,
        report_result,
        audit_json,
        selection_json,
        instrumentation_json,
        overlay_json,
        verification_overlay=verify_json_path is not None,
    )

    print(
        f"PASS: {instrumentation_path} closes {len(closure_rows)}/"
        f"{len(audit_keys)} prioritized audit rows and {genai_surface_count} "
        "GenAI readiness surfaces"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("instrumentation", type=Path)
    parser.add_argument("--audit-json", type=Path, required=True)
    parser.add_argument("--selection-json", type=Path)
    parser.add_argument("--instrumentation-json", type=Path, required=True)
    parser.add_argument("--verify-json", type=Path)
    args = parser.parse_args()
    validate(
        args.instrumentation,
        args.audit_json,
        args.instrumentation_json,
        args.selection_json,
        args.verify_json,
    )


if __name__ == "__main__":
    main()
