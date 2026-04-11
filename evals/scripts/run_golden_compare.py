#!/usr/bin/env python3
"""Golden comparison eval: compare skill output against golden reference.

Compares the generated .observe/inventory.md against a golden reference
using structural similarity. Checks:
  - KPI count matches within tolerance
  - Expected signal names are present
  - Component coverage matches
  - Business vs Standard class distribution matches
  - Structural sections present

Usage:
  python run_golden_compare.py <fixture_dir> <golden_dir> [--threshold 0.80]

Exit code 0 if similarity >= threshold, 1 otherwise.
"""

import argparse
import re
import sys
from pathlib import Path


def parse_kpi_table(text: str) -> list[dict]:
    """Extract KPI rows from markdown table."""
    rows = []
    in_table = False
    headers = []

    for line in text.splitlines():
        if "Signal Name" in line and "|" in line:
            headers = [h.strip() for h in line.split("|") if h.strip()]
            in_table = True
            continue
        if in_table and line.strip().startswith("|---"):
            continue
        if in_table and "|" in line and line.strip():
            cols = [c.strip() for c in line.split("|") if c.strip()]
            if len(cols) >= 4:
                row = {}
                for i, h in enumerate(headers):
                    if i < len(cols):
                        row[h] = cols[i]
                rows.append(row)
        elif in_table and not line.strip():
            in_table = False

    return rows


def extract_signal_names(kpis: list[dict]) -> set[str]:
    return {
        k.get("Signal Name", "").strip("`")
        for k in kpis
        if k.get("Signal Name", "").strip("`")
    }


def extract_components(kpis: list[dict]) -> set[str]:
    return {k.get("Component", "") for k in kpis if k.get("Component")}


def count_by_class(kpis: list[dict], cls: str) -> int:
    return sum(1 for k in kpis if k.get("Class", "") == cls)


def check_sections(text: str) -> list[str]:
    """Return list of standard inventory sections found."""
    expected = [
        "Service Overview",
        "Architecture",
        "Components",
        "Fault Domains",
        "KPI Table",
        "Configurability",
        "Alerts",
        "Dashboard Recommendations",
    ]
    return [s for s in expected if f"## {s}" in text]


def main():
    parser = argparse.ArgumentParser(description="Golden comparison eval")
    parser.add_argument("fixture_dir", type=Path)
    parser.add_argument("golden_dir", type=Path)
    parser.add_argument("--threshold", type=float, default=0.80)
    args = parser.parse_args()

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

    actual_kpis = parse_kpi_table(actual_text)
    golden_kpis = parse_kpi_table(golden_text)

    scores = []

    # 1. KPI count similarity
    actual_count = len(actual_kpis)
    golden_count = len(golden_kpis)
    if golden_count > 0:
        count_ratio = min(actual_count, golden_count) / max(actual_count, golden_count)
    else:
        count_ratio = 1.0 if actual_count == 0 else 0.0
    scores.append(("kpi_count", count_ratio, f"actual={actual_count} golden={golden_count}"))

    # 2. Signal name overlap (Jaccard)
    actual_signals = extract_signal_names(actual_kpis)
    golden_signals = extract_signal_names(golden_kpis)
    if golden_signals:
        intersection = actual_signals & golden_signals
        union = actual_signals | golden_signals
        signal_sim = len(intersection) / len(union) if union else 1.0
    else:
        signal_sim = 1.0
    scores.append(("signal_overlap", signal_sim, f"matched={len(actual_signals & golden_signals)}/{len(golden_signals)}"))

    # 3. Component coverage
    actual_comps = extract_components(actual_kpis)
    golden_comps = extract_components(golden_kpis)
    if golden_comps:
        comp_sim = len(actual_comps & golden_comps) / len(golden_comps)
    else:
        comp_sim = 1.0
    scores.append(("component_coverage", comp_sim, f"matched={len(actual_comps & golden_comps)}/{len(golden_comps)}"))

    # 4. Class distribution
    actual_biz = count_by_class(actual_kpis, "Business")
    golden_biz = count_by_class(golden_kpis, "Business")
    if golden_biz > 0:
        biz_ratio = min(actual_biz, golden_biz) / max(actual_biz, golden_biz)
    else:
        biz_ratio = 1.0 if actual_biz == 0 else 0.0
    scores.append(("business_kpi_ratio", biz_ratio, f"actual={actual_biz} golden={golden_biz}"))

    # 5. Section presence
    actual_sections = check_sections(actual_text)
    section_score = len(actual_sections) / 8.0
    scores.append(("inventory_sections", section_score, f"found={len(actual_sections)}/8"))

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
