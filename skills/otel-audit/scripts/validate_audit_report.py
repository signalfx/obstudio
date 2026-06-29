#!/usr/bin/env python3
"""Validate the reader-facing and handoff structure of an OTel audit report."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


EVIDENCE_HEADER = ["Check", "Finding", "Source"]
GENAI_READINESS_HEADER = [
    "Surface",
    "Status",
    "Evidence",
    "Required Signals",
    "Owner / Source Files",
    "Acceptance Criteria",
    "Detection/Localization Impact",
]
GAP_HEADER = [
    "Priority",
    "Area",
    "Gap",
    "Why it matters",
    "Required fix",
    "Instrument mode",
    "Verification scenarios",
]
TEST_ENVIRONMENT_HEADER = [
    "Environment ID",
    "Surface",
    "Config Evidence",
    "Runner / Toolchain",
    "Scope",
    "Shared Prerequisites",
]
ACCEPTANCE_SCENARIO_HEADER = [
    "Scenario ID",
    "Trigger / Path",
    "Source Entrypoint",
    "Expected Signals",
    "Proof Level",
    "Acceptance Criteria",
    "Environment",
]
PRIORITIES = {"required", "recommended", "deferred"}
INSTRUMENT_MODES = {"default", "fix all", "manual decision"}
PROOF_LEVELS = {"focused call-site", "full runtime", "either"}
GENAI_STATUSES = {"covered", "partial", "missing", "owner-mapped"}
STABLE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
FORBIDDEN = (
    "## RED Signals",
    "## Instrumentation Delta",
    "## Step-by-Step Signal Coverage",
    "Shows Today",
    "[COVERED]",
    "## Verification Contract",
    "### Project Runtime",
    "### Path Scenarios",
    "Local-Safe Fixture / Prerequisite",
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


def validate(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count("\n## Gaps\n") != 1:
        fail("report must contain exactly one top-level ## Gaps section")

    required_order = [
        "## Executive Summary",
        "## Flow",
        "## Audit Evidence",
        "## Signal Flow",
        "## Current Instrumentation",
        "## Gaps",
        "## Verification Plan",
        "## Anti-Patterns",
        "## Recommendation",
    ]
    positions = [heading_match(text, heading).start() for heading in required_order]
    if positions != sorted(positions):
        fail("reader-first section order is incorrect")

    ownership_matches = list(
        re.finditer(
            r"^\*\*GenAI ownership detected:\*\* (Yes|No)\s*$",
            text,
            re.MULTILINE,
        )
    )
    if len(ownership_matches) != 1:
        fail("report must contain exactly one GenAI ownership declaration")
    ownership_match = ownership_matches[0]
    genai_detected = ownership_match.group(1) == "Yes"

    genai_headings = list(
        re.finditer(r"^## GenAI Readiness\s*$", text, re.MULTILINE)
    )
    if len(genai_headings) > 1:
        fail("report must contain at most one ## GenAI Readiness section")
    genai_heading = genai_headings[0] if genai_headings else None
    if genai_detected and not genai_heading:
        fail("GenAI ownership is Yes but ## GenAI Readiness is missing")
    if not genai_detected and genai_heading:
        fail("GenAI ownership is No but ## GenAI Readiness is present")
    if genai_heading:
        current_position = heading_match(text, "## Current Instrumentation").start()
        genai_position = genai_heading.start()
        gaps_position = heading_match(text, "## Gaps").start()
        if not current_position < genai_position < gaps_position:
            fail(
                "## GenAI Readiness must appear after Current Instrumentation "
                "and before Gaps"
            )

    if not re.search(r"^\*\*Status:\*\* (Pass|Partial|Blocked)$", text, re.MULTILINE):
        fail("Status must be Pass, Partial, or Blocked")
    for forbidden in FORBIDDEN:
        if forbidden in text:
            fail(f"forbidden audit content: {forbidden}")

    evidence_header, evidence_rows = table(section(text, "## Audit Evidence"), "Audit Evidence")
    if evidence_header != EVIDENCE_HEADER:
        fail(f"Audit Evidence header must be {EVIDENCE_HEADER}")
    if len(evidence_rows) < 4:
        fail("Audit Evidence must include manifest, entry point, route, and runtime checks")

    ownership_rows = [
        row for row in evidence_rows if row and row[0] == "GenAI ownership"
    ]
    if len(ownership_rows) != 1:
        fail("Audit Evidence must contain exactly one GenAI ownership row")
    ownership_row = ownership_rows[0]
    if len(ownership_row) != len(EVIDENCE_HEADER):
        fail(f"malformed GenAI ownership evidence row: {ownership_row}")
    expected_ownership = "Yes" if genai_detected else "No"
    if ownership_row[1] != expected_ownership:
        fail("GenAI ownership declaration and Audit Evidence row disagree")
    if not ownership_row[2]:
        fail("GenAI ownership evidence must cite source paths or scan evidence")

    if genai_detected:
        readiness_header, readiness_rows = table(
            section(text, "## GenAI Readiness"), "GenAI Readiness"
        )
        if readiness_header != GENAI_READINESS_HEADER:
            fail(f"GenAI Readiness header must be {GENAI_READINESS_HEADER}")
        if not readiness_rows:
            fail("GenAI Readiness must contain at least one surface row")
        readiness_surfaces = set()
        for row in readiness_rows:
            if len(row) != len(GENAI_READINESS_HEADER) or any(not cell for cell in row):
                fail(f"malformed GenAI Readiness row: {row}")
            if row[1] not in GENAI_STATUSES:
                fail(f"invalid GenAI readiness status: {row[1]}")
            if row[0] in readiness_surfaces:
                fail(f"duplicate GenAI readiness surface: {row[0]}")
            readiness_surfaces.add(row[0])

    gap_body = section(text, "## Gaps")
    gap_header, gap_rows = table(gap_body, "Gaps")
    if gap_header != GAP_HEADER:
        fail(f"Gaps header must be {GAP_HEADER}")
    if not gap_rows and "No gaps found." not in gap_body:
        fail("an empty Gaps table must be followed by 'No gaps found.'")

    areas = set()
    for row in gap_rows:
        if len(row) != len(GAP_HEADER):
            fail(f"malformed Gaps row: {row}")
        if row[0] not in PRIORITIES:
            fail(f"invalid gap priority: {row[0]}")
        if row[5] not in INSTRUMENT_MODES:
            fail(f"invalid instrument mode: {row[5]}")
        if not row[1] or not row[2] or not row[3] or not row[4] or not row[6]:
            fail(f"incomplete gap handoff for area: {row[1] or '<empty>'}")
        duplicate_contract = f"{row[1]} {row[2]} {row[4]}".lower()
        if row[5] == "default" and any(
            term in duplicate_contract for term in ("duplicate", "overlap", "canonical")
        ):
            ownership_terms = (
                "app-owned",
                "framework-owned",
                "bridge-owned",
                "agent-owned",
                "callback",
                "provider sdk",
            )
            if not any(term in row[4].lower() for term in ownership_terms):
                fail(
                    "default duplicate-remediation row must name its canonical owner "
                    f"or use manual decision: {row[1]}"
                )
        areas.add(row[1])

    flow = section(text, "## Signal Flow")
    if "### Component Flow Map" not in flow:
        fail("Signal Flow must contain one Component Flow Map")
    if "[SOURCE-COVERED]" not in flow:
        fail("Component Flow Map must use source-only coverage semantics")
    map_areas = set(re.findall(r"\[GAP: ([^\]]+)\]", flow))
    missing = map_areas - areas
    if missing:
        fail(f"flow-map gap markers have no prioritized row: {sorted(missing)}")
    if re.search(r"\b(working|verified|shows today)\b", flow, re.IGNORECASE):
        fail("Component Flow Map may not claim runtime proof")

    verification_plan = section(text, "## Verification Plan")
    environment_header, environment_rows = table(
        subsection(verification_plan, "Test Environments"), "Test Environments"
    )
    if environment_header != TEST_ENVIRONMENT_HEADER:
        fail(f"Test Environments header must be {TEST_ENVIRONMENT_HEADER}")

    environment_ids = set()
    for row in environment_rows:
        if len(row) != len(TEST_ENVIRONMENT_HEADER) or any(not cell for cell in row):
            fail(f"malformed Test Environments row: {row}")
        environment_id = row[0].strip("`")
        if not STABLE_ID.fullmatch(environment_id):
            fail(f"invalid environment ID: {row[0]}")
        if environment_id in environment_ids:
            fail(f"duplicate environment ID: {environment_id}")
        environment_ids.add(environment_id)

    scenario_header, scenario_rows = table(
        subsection(verification_plan, "Acceptance Scenarios"),
        "Acceptance Scenarios",
    )
    if scenario_header != ACCEPTANCE_SCENARIO_HEADER:
        fail(f"Acceptance Scenarios header must be {ACCEPTANCE_SCENARIO_HEADER}")

    scenario_ids = set()
    for row in scenario_rows:
        if len(row) != len(ACCEPTANCE_SCENARIO_HEADER) or any(not cell for cell in row):
            fail(f"malformed Acceptance Scenarios row: {row}")
        scenario_id = row[0].strip("`")
        if not STABLE_ID.fullmatch(scenario_id):
            fail(f"invalid scenario ID: {row[0]}")
        if scenario_id in scenario_ids:
            fail(f"duplicate scenario ID: {scenario_id}")
        scenario_ids.add(scenario_id)
        if row[4].strip("`") not in PROOF_LEVELS:
            fail(f"invalid proof level for {scenario_id}: {row[4]}")

        references = [
            value.strip().strip("`")
            for value in re.split(r"\s*(?:,|<br\s*/?>)\s*", row[6])
            if value.strip()
        ]
        if not references or any(not STABLE_ID.fullmatch(value) for value in references):
            fail(f"Environment for {scenario_id} must contain only stable IDs")
        unknown = set(references) - environment_ids
        if unknown:
            fail(
                f"Acceptance Scenario {scenario_id} references undefined "
                f"environment IDs: {sorted(unknown)}"
            )

    if not environment_rows and "No runnable surface detected" not in verification_plan:
        fail("Test Environments must define a profile or state no runnable surface")
    if scenario_rows and not environment_rows:
        fail("Acceptance Scenarios cannot exist without a Test Environments profile")

    print(
        f"PASS: {path} ({len(evidence_rows)} evidence rows, "
        f"{len(gap_rows)} prioritized gaps, {len(environment_rows)} test environments, "
        f"{len(scenario_rows)} acceptance scenarios)"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    validate(args.report)


if __name__ == "__main__":
    main()
