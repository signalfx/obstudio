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
INSTRUMENT_MODES = {"default", "fix all", "manual decision", "external follow-up"}
PROOF_LEVELS = {"focused call-site", "full runtime", "either"}
GENAI_STATUSES = {"covered", "partial", "missing", "owner-mapped"}
INCIDENT_READINESS_HEADER = [
    "Area",
    "Status",
    "Evidence",
    "Required Signals / Gap",
    "Detection / Localization Impact",
]
INCIDENT_READINESS_STATUSES = {"covered", "partial", "missing", "owner-mapped"}
STABLE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
EXTERNAL_OWNER_CATEGORY = re.compile(
    r"(?:external|provider|platform|vendor|third[- ]party|managed[- ]service)"
    r"(?:\s*/\s*(?:external|provider|platform|vendor|third[- ]party|"
    r"managed[- ]service))?(?:[- ]owned|\s+owner)?",
    re.IGNORECASE,
)
OWNER_PLACEHOLDER = re.compile(
    r"^(?:tbd|unknown|owner|someone|team|n/?a)$", re.IGNORECASE
)
GENERIC_EXTERNAL_OWNER_DETAIL = re.compile(
    r"(?:(?:external|provider|platform|vendor|third[- ]party|managed[- ]service)"
    r"(?:[- ]owned)?(?:\s+(?:owner|team))?|owner|team)",
    re.IGNORECASE,
)
REQUIRED_TOP_LEVEL_HEADINGS = [
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
ALLOWED_TOP_LEVEL_HEADINGS = set(REQUIRED_TOP_LEVEL_HEADINGS) | {
    "## Routes",
    "## Scan Blockers",
    "## GenAI Readiness",
}


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def has_exact_external_owner(value: str) -> bool:
    """Require a category-prefixed owner with a concrete named source."""

    category, separator, detail = value.partition(":")
    detail = detail.strip()
    return bool(
        separator
        and EXTERNAL_OWNER_CATEGORY.fullmatch(category.strip())
        and detail
        and not OWNER_PLACEHOLDER.fullmatch(detail)
        and not GENERIC_EXTERNAL_OWNER_DETAIL.fullmatch(detail)
    )


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
    lines = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line.startswith("|"):
            lines.append(line)
        elif lines and line:
            break
    if len(lines) < 2:
        fail(f"{label} table is missing")
    header = split_row(lines[0])
    rows = [split_row(line) for line in lines[2:]]
    return header, rows


def validate(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    top_level_headings = re.findall(r"^## [^\n]+$", text, re.MULTILINE)
    unexpected_headings = sorted(set(top_level_headings) - ALLOWED_TOP_LEVEL_HEADINGS)
    if unexpected_headings:
        fail(f"unexpected top-level sections: {unexpected_headings}")
    duplicate_headings = sorted(
        heading for heading in set(top_level_headings) if top_level_headings.count(heading) > 1
    )
    if duplicate_headings:
        fail(f"duplicate top-level sections: {duplicate_headings}")
    if text.count("\n## Gaps\n") != 1:
        fail("report must contain exactly one top-level ## Gaps section")

    positions = [
        heading_match(text, heading).start()
        for heading in REQUIRED_TOP_LEVEL_HEADINGS
    ]
    if positions != sorted(positions):
        fail("reader-first section order is incorrect")

    routes_match = re.search(r"^## Routes\s*$", text, re.MULTILINE)
    if routes_match:
        evidence_position = heading_match(text, "## Audit Evidence").start()
        routes_position = routes_match.start()
        signal_flow_position = heading_match(text, "## Signal Flow").start()
        if not evidence_position < routes_position < signal_flow_position:
            fail("## Routes must appear after Audit Evidence and before Signal Flow")

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

    status_match = re.search(
        r"^\*\*Status:\*\* (Pass|Partial|Blocked)$", text, re.MULTILINE
    )
    if not status_match:
        fail("Status must be Pass, Partial, or Blocked")
    status = status_match.group(1)
    if status == "Blocked" and "Scan blocked:" not in section(text, "## Executive Summary"):
        fail("Status Blocked requires structured scan-blocker details in Executive Summary")
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

    readiness_rows: list[list[str]] = []
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
            if row[1] == "owner-mapped" and not has_exact_external_owner(row[4]):
                fail(
                    "owner-mapped GenAI readiness must name an exact external, "
                    f"provider, or platform owner: {row[0]}"
                )
            if row[0] in readiness_surfaces:
                fail(f"duplicate GenAI readiness surface: {row[0]}")
            readiness_surfaces.add(row[0])

    gap_body = section(text, "## Gaps")
    gap_header, gap_rows = table(gap_body, "Gaps")
    if gap_header != GAP_HEADER:
        fail(f"Gaps header must be {GAP_HEADER}")
    if not gap_rows and "No gaps found." not in gap_body:
        fail("an empty Gaps table must be followed by 'No gaps found.'")
    if gap_rows and "No gaps found." in gap_body:
        fail("a non-empty Gaps table must not say 'No gaps found.'")
    if status == "Pass" and gap_rows:
        fail("Status Pass requires zero source-visible gaps")
    if status == "Partial" and not gap_rows:
        fail("Status Partial requires at least one source-visible gap")

    gap_areas = {row[1] for row in gap_rows if len(row) == len(GAP_HEADER)}
    incomplete_genai_surfaces = {
        row[0] for row in readiness_rows if row[1] in {"partial", "missing"}
    }
    unmapped_genai_surfaces = sorted(incomplete_genai_surfaces - gap_areas)
    if unmapped_genai_surfaces:
        fail(
            "partial or missing GenAI readiness surfaces require identical "
            f"prioritized Gaps Area values: {unmapped_genai_surfaces}"
        )
    complete_genai_with_gaps = sorted(
        {
            row[0]
            for row in readiness_rows
            if row[1] in {"covered", "owner-mapped"}
        }
        & gap_areas
    )
    if complete_genai_with_gaps:
        fail(
            "covered or owner-mapped GenAI readiness surfaces must not have "
            f"prioritized gaps: {complete_genai_with_gaps}"
        )
    if status == "Pass" and any(
        row[1] not in {"covered", "owner-mapped"} for row in readiness_rows
    ):
        fail(
            "Status Pass requires every GenAI readiness surface to be covered "
            "or owner-mapped"
        )

    areas = set()
    gap_rows_by_area: dict[str, list[list[str]]] = {}
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
                "service-owned",
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
        gap_rows_by_area.setdefault(row[1], []).append(row)

    current_instrumentation = section(text, "## Current Instrumentation")
    incident_headings = list(
        re.finditer(r"^### Incident Readiness\s*$", current_instrumentation, re.MULTILINE)
    )
    if len(incident_headings) > 1:
        fail("Current Instrumentation must contain at most one Incident Readiness subsection")

    incident_rows: list[list[str]] = []
    if incident_headings:
        incident_header, incident_rows = table(
            subsection(current_instrumentation, "Incident Readiness"),
            "Incident Readiness",
        )
        if incident_header != INCIDENT_READINESS_HEADER:
            fail(f"Incident Readiness header must be {INCIDENT_READINESS_HEADER}")
        if not incident_rows:
            fail("Incident Readiness must contain at least one area row")

        incident_areas = set()
        for row in incident_rows:
            if len(row) != len(INCIDENT_READINESS_HEADER) or any(not cell for cell in row):
                fail(f"malformed Incident Readiness row: {row}")
            if row[1] not in INCIDENT_READINESS_STATUSES:
                fail(f"invalid Incident Readiness status: {row[1]}")
            if row[0] in incident_areas:
                fail(f"duplicate Incident Readiness area: {row[0]}")
            incident_areas.add(row[0])
            if row[1] in {"partial", "missing", "owner-mapped"} and row[0] not in gap_rows_by_area:
                fail(
                    "partial, missing, or owner-mapped Incident Readiness area has no identical "
                    f"prioritized Gaps Area: {row[0]}"
                )
        complete_incident_with_gaps = sorted(
            {
                row[0]
                for row in incident_rows
                if row[1] == "covered"
            }
            & areas
        )
        if complete_incident_with_gaps:
            fail(
                "covered Incident Readiness areas must not have "
                f"prioritized gaps: {complete_incident_with_gaps}"
            )

    flow = section(text, "## Signal Flow")
    if "### Component Flow Map" not in flow:
        fail("Signal Flow must contain one Component Flow Map")
    if "[SOURCE-COVERED]" not in flow:
        fail("Component Flow Map must use source-only coverage semantics")
    flow_markers = re.findall(r"\[([^\]\n]+)\]", flow)
    unexpected_markers = sorted(
        marker
        for marker in set(flow_markers)
        if marker != "SOURCE-COVERED" and not marker.startswith("GAP: ")
    )
    if unexpected_markers:
        fail(f"unexpected Component Flow Map markers: {unexpected_markers}")
    map_areas = set(re.findall(r"\[GAP: ([^\]]+)\]", flow))
    missing = map_areas - areas
    if missing:
        fail(f"flow-map gap markers have no prioritized row: {sorted(missing)}")
    if re.search(r"\b(working|verified)\b", flow, re.IGNORECASE):
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

    for incident_row in incident_rows:
        area, status = incident_row[0], incident_row[1]
        if status not in {"partial", "missing"}:
            continue
        for gap_row in gap_rows_by_area[area]:
            references = [
                value.strip().strip("`")
                for value in re.split(r"\s*(?:,|<br\s*/?>)\s*", gap_row[6])
                if value.strip()
            ]
            if not references or any(not STABLE_ID.fullmatch(value) for value in references):
                fail(
                    "Verification scenarios for Incident Readiness area "
                    f"{area} must contain only stable scenario IDs"
                )
            unknown = set(references) - scenario_ids
            if unknown:
                fail(
                    "Incident Readiness area references undefined verification "
                    f"scenario IDs: {area}: {sorted(unknown)}"
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
