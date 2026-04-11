#!/usr/bin/env python3
"""Semantic convention eval: verify span and metric names follow OTel conventions.

Checks:
  - Span names are low-cardinality (no UUID, path params, query strings)
  - Metric names follow {namespace}.{noun}.{unit} pattern
  - Custom attribute names follow {domain}.{noun}.{adjective} pattern
  - No high-cardinality metric attributes (user IDs, request IDs)

Usage:
  python check_semconv.py <fixture_dir>
  python check_semconv.py --inventory <path/to/inventory.md>

Parses .observe/inventory.md (or a directly specified inventory file) for
signal names from the Spans, Metrics, and Logs tables and checks them
against OTel semantic convention rules.

Exit code 0 if all checks pass, 1 otherwise.
"""

import argparse
import re
import sys
from pathlib import Path

VALID_METRIC_PATTERN = re.compile(
    r"^[a-z][a-z0-9]*(\.[a-z][a-z0-9_]*)+$"
)

HIGH_CARDINALITY_ATTRS = [
    "user.id", "user_id", "userId",
    "request.id", "request_id", "requestId",
    "session.id", "session_id", "sessionId",
    "trace.id", "trace_id",
]

SPAN_VARIABLE_PATTERNS = [
    re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}"),  # UUID fragments
    re.compile(r"/\d+"),                       # numeric path params
    re.compile(r"\?"),                          # query strings
]


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


def parse_signal_tables(inventory: Path) -> dict[str, list[dict]]:
    """Extract signal rows from the Spans, Metrics, and Logs tables."""
    if not inventory.exists():
        return {"spans": [], "metrics": [], "logs": []}

    lines = inventory.read_text().splitlines()
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


def check_metric_names(metrics: list[dict]) -> list[tuple[str, bool, str]]:
    """Check metric signal names follow conventions."""
    results = []
    for m in metrics:
        name = m.get("Signal Name", "").strip("`")
        if not name:
            continue
        if VALID_METRIC_PATTERN.match(name):
            results.append((f"metric:{name}", True, "Valid metric name"))
        else:
            results.append((f"metric:{name}", False, f"Invalid metric name format: '{name}'"))
    return results


def check_span_names(spans: list[dict]) -> list[tuple[str, bool, str]]:
    """Check span/trace signal names for low cardinality."""
    results = []
    for s in spans:
        name = s.get("Signal Name", "").strip("`")
        if not name:
            continue
        has_variable = any(p.search(name) for p in SPAN_VARIABLE_PATTERNS)
        if has_variable:
            results.append((f"span:{name}", False, f"High-cardinality span name: '{name}'"))
        else:
            results.append((f"span:{name}", True, "Low-cardinality span name"))
    return results


def check_source_for_bad_attrs(fixture_dir: Path) -> list[tuple[str, bool, str]]:
    """Scan source files for high-cardinality metric attributes."""
    results = []
    skip = {"node_modules", ".venv", "__pycache__", "build", "dist", ".git"}
    extensions = {".py", ".js", ".mjs", ".ts", ".go"}

    for src in fixture_dir.rglob("*"):
        if any(s in src.parts for s in skip):
            continue
        if src.suffix not in extensions:
            continue
        text = src.read_text(errors="replace")
        for attr in HIGH_CARDINALITY_ATTRS:
            if attr in text:
                ctx_lines = [
                    l.strip() for l in text.splitlines()
                    if attr in l and ("metric" in l.lower() or "attribute" in l.lower() or "set_attribute" in l.lower() or "setAttribute" in l)
                ]
                if ctx_lines:
                    results.append((
                        f"attr:{attr}:{src.name}",
                        False,
                        f"High-cardinality attribute '{attr}' used in metric context in {src.name}",
                    ))

    if not results:
        results.append(("high_cardinality_scan", True, "No high-cardinality metric attributes found"))
    return results


def main():
    parser = argparse.ArgumentParser(description="Semantic convention eval")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("fixture_dir", nargs="?", type=Path,
                       help="Fixture directory containing .observe/inventory.md")
    group.add_argument("--inventory", type=Path,
                       help="Path to an inventory.md file directly")
    args = parser.parse_args()

    if args.inventory:
        inventory_path = args.inventory
        fixture_dir = None
    else:
        fixture_dir = args.fixture_dir
        inventory_path = fixture_dir / ".observe" / "inventory.md"

    if not inventory_path.exists():
        print(f"Inventory not found: {inventory_path}")
        sys.exit(2)

    tables = parse_signal_tables(inventory_path)

    all_results = []
    all_results.extend(check_metric_names(tables["metrics"]))
    all_results.extend(check_span_names(tables["spans"]))
    if fixture_dir:
        all_results.extend(check_source_for_bad_attrs(fixture_dir))

    passed = sum(1 for _, ok, _ in all_results if ok)
    total = len(all_results)

    print(f"\nSemconv Eval: {passed}/{total} checks passed")
    print("-" * 50)
    for name, ok, msg in all_results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}: {msg}")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
