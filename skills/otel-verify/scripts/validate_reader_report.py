#!/usr/bin/env python3
"""Validate the reader-facing structure and per-OTel coverage of a verify report."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_SECTIONS = (
    "What Changed",
    "Tested And Working",
    "Not Working Or Not Proven",
    "Proof",
)
EXPECTED_HEADER = (
    "OTel item",
    "Type",
    "Added or modified",
    "Working status",
    "How it was tested",
    "Evidence",
)
ALLOWED_STATUSES = {"Working", "Not working", "Not proven", "Not configured"}
PLACEHOLDERS = {"", "n/a", "none", "tested", "verified", "unknown", "-"}


def normalize_item(value: str) -> str:
    """Compare item identities independently of reader-facing Markdown code style."""
    return re.sub(r"\s+", " ", value.replace("`", "")).strip()


def section_bounds(text: str, heading: str) -> tuple[int, int]:
    match = re.search(rf"^## {re.escape(heading)}\s*$", text, re.MULTILINE)
    if not match:
        raise ValueError(f"missing required section: ## {heading}")
    next_heading = re.search(r"^## ", text[match.end() :], re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(text)
    return match.start(), end


def split_row(line: str) -> tuple[str, ...]:
    return tuple(cell.strip() for cell in line.strip().strip("|").split("|"))


def parse_signal_table(section: str) -> list[tuple[str, ...]]:
    lines = section.splitlines()
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        header = split_row(line)
        if header != EXPECTED_HEADER:
            continue
        if index + 1 >= len(lines) or not re.fullmatch(
            r"\s*\|(?:\s*:?-+:?\s*\|){6}\s*", lines[index + 1]
        ):
            raise ValueError("per-OTel table is missing its separator row")
        rows: list[tuple[str, ...]] = []
        for row_line in lines[index + 2 :]:
            if not row_line.lstrip().startswith("|"):
                break
            row = split_row(row_line)
            if len(row) != len(EXPECTED_HEADER):
                raise ValueError(f"per-OTel row has {len(row)} columns, expected 6: {row_line}")
            rows.append(row)
        if not rows:
            raise ValueError("per-OTel table has no item rows")
        return rows
    raise ValueError(
        "missing per-OTel table with header: " + " | ".join(EXPECTED_HEADER)
    )


def load_expected_items(path: Path) -> set[str]:
    return {
        normalize_item(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def validate(report: Path, expected_items_path: Path | None) -> list[str]:
    text = report.read_text(encoding="utf-8")
    positions = []
    bounds = {}
    for section in REQUIRED_SECTIONS:
        start, end = section_bounds(text, section)
        positions.append(start)
        bounds[section] = (start, end)
    if positions != sorted(positions):
        raise ValueError("required reader sections are not in the expected order")

    tested_start, tested_end = bounds["Tested And Working"]
    tested_section = text[tested_start:tested_end]
    rows = parse_signal_table(tested_section)
    items: set[str] = set()
    non_working: list[str] = []
    errors: list[str] = []

    for item, item_type, changed, status, tested, evidence in rows:
        if not item:
            errors.append("a per-OTel row has an empty item")
            continue
        item_identity = normalize_item(item)
        if item_identity in items:
            errors.append(f"duplicate OTel item row: {item}")
        items.add(item_identity)
        if not item_type:
            errors.append(f"{item}: Type is empty")
        if changed.casefold() in PLACEHOLDERS:
            errors.append(f"{item}: Added or modified is not specific")
        if status not in ALLOWED_STATUSES:
            errors.append(f"{item}: invalid Working status: {status}")
        if tested.casefold() in PLACEHOLDERS:
            errors.append(f"{item}: How it was tested is not specific")
        if status == "Working" and evidence.casefold() in PLACEHOLDERS:
            errors.append(f"{item}: Working row lacks direct evidence")
        if status != "Working":
            non_working.append(item)

    result_match = re.search(
        r"\*\*Individual result:\*\*\s*(\d+)\s*/\s*(\d+)\s+working\b",
        tested_section,
    )
    working_count = sum(1 for row in rows if row[3] == "Working")
    if not result_match:
        errors.append("Tested And Working is missing the Individual result summary")
    else:
        reported_working, reported_total = map(int, result_match.groups())
        if reported_working != working_count or reported_total != len(rows):
            errors.append(
                "Individual result count does not match the per-OTel table: "
                f"reported {reported_working}/{reported_total}, "
                f"actual {working_count}/{len(rows)}"
            )

    gaps_start, gaps_end = bounds["Not Working Or Not Proven"]
    gaps_section = text[gaps_start:gaps_end]
    normalized_gaps_section = normalize_item(gaps_section)
    if non_working:
        for item in non_working:
            if normalize_item(item) not in normalized_gaps_section:
                errors.append(f"{item}: non-working row is missing from gap section")
    elif not re.search(r"\bNone\b", gaps_section):
        errors.append("all rows are Working but the gap section does not say None")

    if expected_items_path:
        expected_items = load_expected_items(expected_items_path)
        missing = sorted(expected_items - items)
        unexpected = sorted(items - expected_items)
        if missing:
            errors.append("missing expected OTel items: " + ", ".join(missing))
        if unexpected:
            errors.append("unexpected OTel items: " + ", ".join(unexpected))

    if errors:
        raise ValueError("\n".join(errors))
    return sorted(items)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--expected-items-file", type=Path)
    args = parser.parse_args()
    try:
        items = validate(args.report, args.expected_items_file)
    except (OSError, ValueError) as error:
        print(f"reader report validation failed:\n{error}", file=sys.stderr)
        return 1
    print(f"reader report validation passed: {len(items)} individual OTel items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
