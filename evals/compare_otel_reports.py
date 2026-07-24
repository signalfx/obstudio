#!/usr/bin/env python3
"""Compare stable observability-report contracts across benchmark runs."""

from __future__ import annotations

import argparse
import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")
VOLATILE_DATE = re.compile(r"\b20\d{2}-\d{2}-\d{2}(?:[ T][0-9:.+-]+(?:Z| UTC)?)?\b")
TEMP_PATH = re.compile(r"(?:/private)?/tmp/[A-Za-z0-9_./-]+")


@dataclass(frozen=True)
class Table:
    section: tuple[str, ...]
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


def normalize(value: str) -> str:
    value = value.replace("<br>", ", ").replace("<br/>", ", ")
    value = value.replace("`", "").replace("**", "")
    value = VOLATILE_DATE.sub("<date>", value)
    value = TEMP_PATH.sub("<tmp>", value)
    return " ".join(value.split()).strip()


def split_row(line: str) -> tuple[str, ...]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith(r"\|"):
        text = text[:-1]

    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in text:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            cells.append(normalize("".join(current)))
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    cells.append(normalize("".join(current)))
    return tuple(cells)


def is_separator(row: tuple[str, ...]) -> bool:
    return bool(row) and all(SEPARATOR_CELL.fullmatch(cell.replace(" ", "")) for cell in row)


def parse_report(path: Path) -> tuple[str, list[str], dict[str, str], list[Table], dict[str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    title = normalize(lines[0].lstrip("# ")) if lines else ""
    headings: list[str] = []
    metadata: dict[str, str] = {}
    section_text: dict[str, list[str]] = {}
    tables: list[Table] = []
    section_stack: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        heading = re.match(r"^(#{2,6})\s+(.+?)\s*$", line)
        if heading:
            level = len(heading.group(1))
            name = normalize(heading.group(2))
            if level == 2:
                headings.append(name)
            depth = level - 1
            section_stack = section_stack[: depth - 1]
            section_stack.append(name)
            index += 1
            continue

        for match in re.finditer(r"\*\*([^*]+):\*\*\s*([^|]+)", line):
            metadata[normalize(match.group(1)).lower()] = normalize(match.group(2))

        if section_stack and line.strip() and not line.lstrip().startswith("|"):
            section_text.setdefault(" / ".join(section_stack), []).append(normalize(line))

        if line.lstrip().startswith("|") and index + 1 < len(lines):
            header = split_row(line)
            separator = split_row(lines[index + 1])
            if len(header) == len(separator) and is_separator(separator):
                rows = []
                index += 2
                while index < len(lines) and lines[index].lstrip().startswith("|"):
                    row = split_row(lines[index])
                    if len(row) == len(header):
                        rows.append(row)
                    index += 1
                tables.append(Table(tuple(section_stack), header, tuple(rows)))
                continue
        index += 1

    return title, headings, metadata, tables, {
        key: normalize(" ".join(value)) for key, value in section_text.items()
    }


def table_rows(
    tables: Iterable[Table],
    section: str,
    selected: tuple[str, ...],
    *,
    sort_list_columns: tuple[str, ...] = (),
) -> list[dict[str, str]]:
    wanted = {column.lower(): column for column in selected}
    for table in tables:
        if section.lower() not in {part.lower() for part in table.section}:
            continue
        indexes = {name.lower(): idx for idx, name in enumerate(table.header)}
        if not wanted.keys() <= indexes.keys():
            continue
        result = []
        for row in table.rows:
            projected: dict[str, str] = {}
            for lower, display in wanted.items():
                value = row[indexes[lower]]
                if display in sort_list_columns:
                    parts = sorted(
                        normalize(part)
                        for part in re.split(r"\s*,\s*", value)
                        if normalize(part)
                    )
                    value = ", ".join(parts)
                projected[display] = value
            result.append(projected)
        return sorted(result, key=lambda item: tuple(item[column] for column in selected))
    return []


def canonical_tables(tables: Iterable[Table]) -> dict[str, list[dict[str, str]]]:
    """Preserve every normalized report-table cell for contract comparison."""

    result: dict[str, list[dict[str, str]]] = {}
    for table in tables:
        section = " / ".join(table.section) or "<root>"
        key = f"{section} :: {' | '.join(table.header)}"
        rows = [
            {column: row[index] for index, column in enumerate(table.header)}
            for row in table.rows
        ]
        result.setdefault(key, []).extend(rows)
    return {key: result[key] for key in sorted(result)}


def section_none_state(
    section_text: dict[str, str], tables: Iterable[Table], subsection: str
) -> str:
    if any(
        table.rows and subsection.lower() in {part.lower() for part in table.section}
        for table in tables
    ):
        return "present"
    text = " ".join(
        value for key, value in section_text.items() if key.lower().endswith(" / " + subsection.lower())
    ).lower()
    if not text:
        return "missing"
    if "no " in text or "not configured" in text or "none" in text:
        return "none"
    return "present"


def canonical_audit(path: Path) -> dict[str, object]:
    title, headings, metadata, tables, section_text = parse_report(path)
    return {
        "kind": "audit",
        "title": title,
        "status": metadata.get("status", ""),
        "genai_ownership": metadata.get("genai ownership detected", ""),
        "heading_order": headings,
        "routes": table_rows(tables, "Routes", ("Method", "Path")),
        "inventory_state": {
            "spans": section_none_state(section_text, tables, "Spans"),
            "metrics": section_none_state(section_text, tables, "Metrics"),
            "logs": section_none_state(section_text, tables, "Logs"),
        },
        "gaps": table_rows(
            tables,
            "Gaps",
            ("Priority", "Area", "Instrument mode", "Verification scenarios"),
            sort_list_columns=("Verification scenarios",),
        ),
        "test_environments": table_rows(
            tables,
            "Test Environments",
            ("Environment ID", "Surface", "Runner / Toolchain"),
        ),
        "acceptance_scenarios": table_rows(
            tables,
            "Acceptance Scenarios",
            ("Scenario ID", "Proof Level", "Environment"),
            sort_list_columns=("Environment",),
        ),
        "contract_tables": canonical_tables(tables),
    }


def canonical_instrument(path: Path) -> dict[str, object]:
    title, headings, metadata, tables, _ = parse_report(path)
    return {
        "kind": "instrument",
        "title": title,
        "result": metadata.get("result", ""),
        "heading_order": headings,
        "signals_changed": table_rows(
            tables,
            "Signals Changed",
            ("Signal type", "Added", "Modified", "Removed", "Verification status"),
        ),
        "gap_closure": table_rows(
            tables,
            "Audit Gap Closure",
            ("Priority", "Gap", "Result"),
        ),
        "validation_gates": table_rows(
            tables,
            "Validation Gates",
            ("Gate", "Result"),
        ),
        "contract_tables": canonical_tables(tables),
    }


def canonical_verify(path: Path) -> dict[str, object]:
    title, headings, metadata, tables, _ = parse_report(path)
    return {
        "kind": "verify",
        "title": title,
        "result": metadata.get("result", ""),
        "heading_order": headings,
        "items": table_rows(
            tables,
            "Tested And Working",
            ("OTel item", "Type", "Working status", "How it was tested"),
        ),
        "not_working": table_rows(
            tables,
            "Not Working Or Not Proven",
            ("Item", "State"),
        ),
        "proof": table_rows(tables, "Proof", ("Proof type", "What it proves")),
        "contract_tables": canonical_tables(tables),
    }


CANONICALIZERS = {
    "audit": canonical_audit,
    "instrument": canonical_instrument,
    "verify": canonical_verify,
}


def compare(kind: str, before: Path, after: Path) -> dict[str, object]:
    canonicalizer = CANONICALIZERS[kind]
    before_data = canonicalizer(before)
    after_data = canonicalizer(after)
    before_json = json.dumps(before_data, indent=2, sort_keys=True).splitlines()
    after_json = json.dumps(after_data, indent=2, sort_keys=True).splitlines()
    return {
        "equal": before_data == after_data,
        "kind": kind,
        "before": str(before),
        "after": str(after),
        "diff": list(
            difflib.unified_diff(
                before_json,
                after_json,
                fromfile="before",
                tofile="after",
                lineterm="",
            )
        ),
        "before_projection": before_data,
        "after_projection": after_data,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=sorted(CANONICALIZERS))
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument(
        "--projection",
        action="store_true",
        help="Print the canonical projection for the before report instead of comparing.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.projection:
        print(json.dumps(CANONICALIZERS[args.kind](args.before), indent=2, sort_keys=True))
        return 0
    result = compare(args.kind, args.before, args.after)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["equal"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
