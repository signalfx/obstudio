#!/usr/bin/env python3
"""Golden comparison eval: compare skill output against golden reference.

Compares the generated .observe/inventory.md against a golden reference
using structural similarity. Checks:
  - Signal count matches within tolerance (across Spans, Metrics, Logs)
  - Expected signal names are present
  - Component coverage matches
  - Category distribution matches (OOB/Custom/Derived)
  - Structural sections present

Usage:
  python run_golden_compare.py <fixture_dir> <golden_dir> [--threshold 0.80]
  python run_golden_compare.py --self-check <golden_dir>

In --self-check mode, validates the golden inventory for internal
consistency (sections, signal tables, category distribution) without
needing a fixture directory.

Exit code 0 if similarity >= threshold (or self-check passes), 1 otherwise.
"""

import argparse
import re
import sys
from pathlib import Path


def _parse_table(lines: list[str], start_idx: int) -> list[dict]:
    """Parse a markdown table starting at the header line index."""
    if start_idx >= len(lines):
        return []

    header_line = lines[start_idx]
    headers = [h.strip() for h in header_line.split("|") if h.strip()]
    rows = []
    i = start_idx + 1

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("|---"):
            i += 1
            continue
        if not line.strip() or not line.strip().startswith("|"):
            break
        if line.strip().startswith("##"):
            break
        cols = [c.strip() for c in line.split("|") if c.strip()]
        if len(cols) >= 2:
            row = {}
            for j, h in enumerate(headers):
                if j < len(cols):
                    row[h] = cols[j]
            rows.append(row)
        i += 1

    return rows


def parse_signal_tables(text: str) -> dict[str, list[dict]]:
    """Extract signal rows from all three signal tables."""
    lines = text.splitlines()
    tables: dict[str, list[dict]] = {"spans": [], "metrics": [], "logs": []}

    current_section = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "## Spans":
            current_section = "spans"
        elif stripped == "## Metrics":
            current_section = "metrics"
        elif stripped == "## Logs":
            current_section = "logs"
        elif stripped.startswith("## ") and current_section:
            current_section = None

        if current_section and "Signal Name" in line and "|" in line:
            tables[current_section] = _parse_table(lines, i)
            current_section = None

    return tables


def all_signals(tables: dict[str, list[dict]]) -> list[dict]:
    """Flatten all signal tables into a single list."""
    result = []
    for rows in tables.values():
        result.extend(rows)
    return result


def extract_signal_names(signals: list[dict]) -> set[str]:
    return {
        s.get("Signal Name", "").strip("`")
        for s in signals
        if s.get("Signal Name", "").strip("`")
    }


def extract_components(signals: list[dict]) -> set[str]:
    return {s.get("Component", "") for s in signals if s.get("Component")}


def count_by_category(signals: list[dict], category: str) -> int:
    return sum(1 for s in signals if s.get("Category", "") == category)


def check_sections(text: str) -> list[str]:
    """Return list of standard inventory sections found."""
    expected = [
        "Service Overview",
        "Architecture",
        "Components",
        "Fault Domains",
        "SLI Definitions",
        "Spans",
        "Metrics",
        "Logs",
        "Configurability",
        "Alerts",
        "Dashboard Recommendations",
    ]
    return [s for s in expected if f"## {s}" in text]


def self_check(golden_dir: Path) -> int:
    """Validate a golden inventory for internal consistency."""
    golden_path = golden_dir / "inventory.md"
    if not golden_path.exists():
        print(f"FAIL: No golden at {golden_path}")
        return 1

    text = golden_path.read_text()
    tables = parse_signal_tables(text)
    signals = all_signals(tables)

    results = []

    required_sections = ["SLI Definitions", "Spans", "Metrics", "Logs"]
    found_sections = [s for s in required_sections if f"## {s}" in text]
    results.append(("signal_sections", len(found_sections) == len(required_sections),
                     f"found {len(found_sections)}/{len(required_sections)}: {found_sections}"))

    results.append(("has_signals", len(signals) > 0,
                     f"{len(signals)} signals across tables"))

    names = extract_signal_names(signals)
    results.append(("unique_names", len(names) == len(signals),
                     f"{len(names)} unique / {len(signals)} total"))

    categories = {s.get("Category", "") for s in signals}
    valid_cats = {"OOB", "Custom", "Derived"}
    bad = categories - valid_cats - {""}
    results.append(("valid_categories", len(bad) == 0,
                     f"categories: {categories}" if bad else "all valid"))

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)

    print(f"\nGolden Self-Check: {golden_dir}")
    print("-" * 50)
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}: {detail}")
    print(f"\n  {passed}/{total} checks passed")

    return 0 if passed == total else 1


def main():
    parser = argparse.ArgumentParser(description="Golden comparison eval")
    parser.add_argument("fixture_dir", nargs="?", type=Path)
    parser.add_argument("golden_dir", nargs="?", type=Path)
    parser.add_argument("--threshold", type=float, default=0.80)
    parser.add_argument("--self-check", type=Path, dest="self_check_dir",
                        help="Validate golden inventory for internal consistency")
    args = parser.parse_args()

    if args.self_check_dir:
        sys.exit(self_check(args.self_check_dir))

    if not args.fixture_dir or not args.golden_dir:
        parser.error("fixture_dir and golden_dir are required (or use --self-check)")

    inventory_path = args.fixture_dir / ".observe" / "inventory.md"
    golden_path = args.golden_dir / "inventory.md"

    if not inventory_path.exists():
        print(f"FAIL: No inventory at {inventory_path}")
        sys.exit(1)
    if not golden_path.exists():
        print(f"FAIL: No golden at {golden_path}")
        sys.exit(1)

    actual_text = inventory_path.read_text()
    golden_text = golden_path.read_text()

    actual_tables = parse_signal_tables(actual_text)
    golden_tables = parse_signal_tables(golden_text)

    actual_all = all_signals(actual_tables)
    golden_all = all_signals(golden_tables)

    scores = []

    actual_count = len(actual_all)
    golden_count = len(golden_all)
    if golden_count > 0:
        count_ratio = min(actual_count, golden_count) / max(actual_count, golden_count)
    else:
        count_ratio = 1.0 if actual_count == 0 else 0.0
    scores.append(("signal_count", count_ratio, f"actual={actual_count} golden={golden_count}"))

    actual_names = extract_signal_names(actual_all)
    golden_names = extract_signal_names(golden_all)
    if golden_names:
        intersection = actual_names & golden_names
        union = actual_names | golden_names
        name_sim = len(intersection) / len(union) if union else 1.0
    else:
        name_sim = 1.0
    scores.append(("signal_name_overlap", name_sim, f"matched={len(actual_names & golden_names)}/{len(golden_names)}"))

    actual_comps = extract_components(actual_all)
    golden_comps = extract_components(golden_all)
    if golden_comps:
        comp_sim = len(actual_comps & golden_comps) / len(golden_comps)
    else:
        comp_sim = 1.0
    scores.append(("component_coverage", comp_sim, f"matched={len(actual_comps & golden_comps)}/{len(golden_comps)}"))

    actual_custom = count_by_category(actual_all, "Custom")
    golden_custom = count_by_category(golden_all, "Custom")
    if golden_custom > 0:
        custom_ratio = min(actual_custom, golden_custom) / max(actual_custom, golden_custom)
    else:
        custom_ratio = 1.0 if actual_custom == 0 else 0.0
    scores.append(("custom_signal_ratio", custom_ratio, f"actual={actual_custom} golden={golden_custom}"))

    actual_sections = check_sections(actual_text)
    section_score = len(actual_sections) / 11.0
    scores.append(("inventory_sections", section_score, f"found={len(actual_sections)}/11"))

    overall = sum(s for _, s, _ in scores) / len(scores)

    print(f"\nGolden Comparison Eval")
    print(f"  Fixture: {args.fixture_dir}")
    print(f"  Golden:  {args.golden_dir}")
    print(f"  Threshold: {args.threshold:.0%}")
    print("-" * 50)
    for name, score, detail in scores:
        status = "PASS" if score >= args.threshold else "WARN"
        print(f"  [{status}] {name}: {score:.0%} ({detail})")
    print("-" * 50)
    result = "PASS" if overall >= args.threshold else "FAIL"
    print(f"  Overall similarity: {overall:.0%} [{result}]")

    sys.exit(0 if overall >= args.threshold else 1)


if __name__ == "__main__":
    main()
