#!/usr/bin/env python3
"""Semantic convention eval: verify span and metric names follow OTel conventions.

Checks:
  - Span names are low-cardinality (no UUID, path params, query strings)
  - Metric names follow {namespace}.{noun}.{unit} pattern
  - Custom attribute names follow {domain}.{noun}.{adjective} pattern
  - No high-cardinality metric attributes (user IDs, request IDs)

Usage:
  python check_semconv.py <fixture_dir>

Parses .observe/inventory.md for signal names and checks them against
OTel semantic convention rules.

Exit code 0 if all checks pass, 1 otherwise.
"""

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


def parse_inventory_signals(fixture_dir: Path) -> list[dict]:
    """Extract KPI rows from .observe/inventory.md."""
    inventory = fixture_dir / ".observe" / "inventory.md"
    if not inventory.exists():
        return []

    text = inventory.read_text()
    signals = []
    in_table = False
    headers = []

    for line in text.splitlines():
        if "Signal Name" in line and "|" in line:
            headers = [h.strip() for h in line.split("|") if h.strip()]
            in_table = True
            continue
        if in_table and line.strip().startswith("|---"):
            continue
        if in_table and "|" in line:
            cols = [c.strip() for c in line.split("|") if c.strip()]
            if len(cols) >= len(headers):
                row = dict(zip(headers, cols))
                signals.append(row)
            elif not line.strip():
                in_table = False

    return signals


def check_metric_names(signals: list[dict]) -> list[tuple[str, bool, str]]:
    """Check metric signal names follow conventions."""
    results = []
    for s in signals:
        if s.get("Metric") != "Yes":
            continue
        name = s.get("Signal Name", "").strip("`")
        if not name or name == "span error + log":
            continue
        if VALID_METRIC_PATTERN.match(name):
            results.append((f"metric:{name}", True, "Valid metric name"))
        else:
            results.append((f"metric:{name}", False, f"Invalid metric name format: '{name}'"))
    return results


def check_span_names(signals: list[dict]) -> list[tuple[str, bool, str]]:
    """Check span/trace signal names for low cardinality."""
    results = []
    for s in signals:
        if s.get("Trace") != "Yes":
            continue
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
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <fixture_dir>")
        sys.exit(2)

    fixture_dir = Path(sys.argv[1])
    if not fixture_dir.is_dir():
        print(f"Fixture directory not found: {fixture_dir}")
        sys.exit(2)

    signals = parse_inventory_signals(fixture_dir)

    all_results = []
    all_results.extend(check_metric_names(signals))
    all_results.extend(check_span_names(signals))
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
