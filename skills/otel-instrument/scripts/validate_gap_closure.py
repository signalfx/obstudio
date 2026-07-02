#!/usr/bin/env python3
"""Validate one-to-one audit gap closure in an instrumentation report."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


GAP_HEADER = [
    "Priority",
    "Area",
    "Gap",
    "Why it matters",
    "Required fix",
    "Instrument mode",
    "Verification scenarios",
]
CLOSURE_HEADER = [
    "Priority",
    "Gap",
    "What changed",
    "Tested",
    "Result",
    "Evidence / reason",
]
RESULTS = {"Working", "Not working", "Not proven", "Not configured", "Deferred"}
GENAI_READINESS_HEADER = [
    "Surface",
    "Status",
    "Evidence",
    "Required Signals",
    "Owner / Source Files",
    "Acceptance Criteria",
    "Detection/Localization Impact",
]
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


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


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


def table(body: str, label: str) -> tuple[list[str], list[list[str]]]:
    lines = [line.strip() for line in body.splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        fail(f"{label} table is missing")
    header = [cell.strip() for cell in lines[0].strip("|").split("|")]
    rows = [
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in lines[2:]
    ]
    return header, rows


def validate(audit_path: Path, instrumentation_path: Path) -> None:
    audit = audit_path.read_text(encoding="utf-8")
    instrumentation = instrumentation_path.read_text(encoding="utf-8")

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

    gap_header, gap_rows = table(section(audit, "## Gaps"), "audit Gaps")
    if gap_header != GAP_HEADER:
        fail(f"audit Gaps header must be {GAP_HEADER}")
    closure_header, closure_rows = table(
        section(instrumentation, "## Audit Gap Closure"), "Audit Gap Closure"
    )
    if closure_header != CLOSURE_HEADER:
        fail(f"Audit Gap Closure header must be {CLOSURE_HEADER}")

    audit_keys = [(row[0], row[1]) for row in gap_rows]
    closure_keys = []
    for row in closure_rows:
        if len(row) != len(CLOSURE_HEADER):
            fail(f"malformed closure row: {row}")
        if row[4] not in RESULTS:
            fail(f"invalid closure result: {row[4]}")
        if not row[2] or not row[3] or not row[5]:
            fail(f"closure row lacks action, test, or evidence: {row[1]}")
        closure_keys.append((row[0], row[1]))

    if sorted(audit_keys) != sorted(closure_keys):
        fail(
            "audit and closure rows differ: "
            f"missing={sorted(set(audit_keys) - set(closure_keys))}, "
            f"extra={sorted(set(closure_keys) - set(audit_keys))}"
        )
    gap_result_blockers = {
        row[4] for row in closure_rows if row[4] in {"Not working", "Not proven", "Not configured"}
    }

    audit_current_instrumentation = re.search(
        r"^## Current Instrumentation\s*$", audit, re.MULTILINE
    )
    audit_incident_readiness = False
    if audit_current_instrumentation:
        current_body = section(audit, "## Current Instrumentation")
        audit_incident_readiness = bool(
            re.search(r"^### Incident Readiness\s*$", current_body, re.MULTILINE)
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

    ownership_matches = list(
        re.finditer(
            r"^\*\*GenAI ownership detected:\*\* (Yes|No)\s*$",
            audit,
            re.MULTILINE,
        )
    )
    if len(ownership_matches) != 1:
        fail("source audit must contain exactly one GenAI ownership declaration")
    ownership_match = ownership_matches[0]
    audit_genai_heading = re.search(
        r"^## GenAI Readiness\s*$", audit, re.MULTILINE
    )
    genai_detected = ownership_match.group(1) == "Yes"
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

    if genai_detected and not audit_genai_heading:
        fail("source audit declares GenAI ownership but lacks ## GenAI Readiness")
    if ownership_match.group(1) == "No" and audit_genai_heading:
        fail("source audit declares no GenAI ownership but has ## GenAI Readiness")
    if genai_detected and not instrumentation_genai_heading:
        fail("GenAI audit requires ## GenAI Readiness Closure")
    if not genai_detected and instrumentation_genai_heading:
        fail("non-GenAI audit must not contain ## GenAI Readiness Closure")

    genai_surface_count = 0
    genai_result_blockers = set()
    if genai_detected:
        readiness_header, readiness_rows = table(
            section(audit, "## GenAI Readiness"), "audit GenAI Readiness"
        )
        if readiness_header != GENAI_READINESS_HEADER:
            fail(f"audit GenAI Readiness header must be {GENAI_READINESS_HEADER}")
        if not readiness_rows:
            fail("audit GenAI Readiness must contain at least one surface row")

        genai_closure_header, genai_closure_rows = table(
            section(instrumentation, "## GenAI Readiness Closure"),
            "GenAI Readiness Closure",
        )
        if genai_closure_header != GENAI_CLOSURE_HEADER:
            fail(f"GenAI Readiness Closure header must be {GENAI_CLOSURE_HEADER}")

        readiness_by_surface = {}
        for row in readiness_rows:
            if len(row) != len(GENAI_READINESS_HEADER) or any(not cell for cell in row):
                fail(f"malformed audit GenAI Readiness row: {row}")
            if row[0] in readiness_by_surface:
                fail(f"duplicate audit GenAI readiness surface: {row[0]}")
            readiness_by_surface[row[0]] = row

        closure_by_surface = {}
        for row in genai_closure_rows:
            if len(row) != len(GENAI_CLOSURE_HEADER) or any(not cell for cell in row):
                fail(f"malformed GenAI closure row: {row}")
            surface, required, implemented, _tests, remaining, result = row
            if result not in GENAI_RESULTS:
                fail(f"invalid GenAI closure result: {result}")
            if surface in closure_by_surface:
                fail(f"duplicate GenAI closure surface: {surface}")
            if result == "Working":
                if remaining != "None":
                    fail(f"Working GenAI surface must have Remaining signals None: {surface}")
                if UNPROVEN_PROOF.search(implemented):
                    fail(f"Working GenAI surface must name implemented or proven signals: {surface}")
                if UNPROVEN_PROOF.search(_tests):
                    fail(f"Working GenAI surface must name executed proof: {surface}")
            elif remaining == "None":
                fail(f"non-Working GenAI surface must name remaining signals: {surface}")
            if result in {"Partial", "Not working", "Not proven", "Not configured"}:
                genai_result_blockers.add(result)
            closure_by_surface[surface] = row

        if sorted(readiness_by_surface) != sorted(closure_by_surface):
            fail(
                "audit and GenAI closure surfaces differ: "
                f"missing={sorted(set(readiness_by_surface) - set(closure_by_surface))}, "
                f"extra={sorted(set(closure_by_surface) - set(readiness_by_surface))}"
            )
        for surface, audit_row in readiness_by_surface.items():
            if closure_by_surface[surface][1] != audit_row[3]:
                fail(f"GenAI required signals changed for surface: {surface}")

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

    print(
        f"PASS: {instrumentation_path} closes {len(closure_rows)}/"
        f"{len(gap_rows)} prioritized audit rows and {genai_surface_count} "
        "GenAI readiness surfaces"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audit", type=Path)
    parser.add_argument("instrumentation", type=Path)
    args = parser.parse_args()
    validate(args.audit, args.instrumentation)


if __name__ == "__main__":
    main()
