"""Semantic convention eval tests."""

import re
from pathlib import Path

import pytest

from conftest import parse_signal_tables

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

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
    re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}"),
    re.compile(r"/\d+"),
    re.compile(r"\?"),
]

_SKIP_DIRS = {"node_modules", ".venv", "__pycache__", "build", "dist", ".git"}
_SOURCE_EXTS = {".py", ".js", ".mjs", ".ts", ".go"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_metric_names(metrics: list[dict]) -> list[tuple[str, bool, str]]:
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


def _check_span_names(spans: list[dict]) -> list[tuple[str, bool, str]]:
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


def _check_source_for_bad_attrs(fixture_dir: Path) -> list[tuple[str, bool, str]]:
    results = []
    for src in fixture_dir.rglob("*"):
        if any(s in src.parts for s in _SKIP_DIRS):
            continue
        if src.suffix not in _SOURCE_EXTS:
            continue
        text = src.read_text(errors="replace")
        for attr in HIGH_CARDINALITY_ATTRS:
            if attr in text:
                ctx_lines = [
                    ln.strip() for ln in text.splitlines()
                    if attr in ln and (
                        "metric" in ln.lower()
                        or "attribute" in ln.lower()
                        or "set_attribute" in ln.lower()
                        or "setAttribute" in ln
                    )
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGoldenSemconv:
    """Validate golden inventories follow OTel semantic conventions."""

    def test_metric_names_valid(self, golden_inventory):
        tables = parse_signal_tables(golden_inventory.read_text())
        results = _check_metric_names(tables["metrics"])
        assert results, "No metrics found in golden inventory"
        failures = [(n, m) for n, ok, m in results if not ok]
        assert not failures, f"Invalid metric names: {failures}"

    def test_span_names_low_cardinality(self, golden_inventory):
        tables = parse_signal_tables(golden_inventory.read_text())
        results = _check_span_names(tables["spans"])
        assert results, "No spans found in golden inventory"
        failures = [(n, m) for n, ok, m in results if not ok]
        assert not failures, f"High-cardinality span names: {failures}"


class TestFixtureSemconv:
    """Validate an instrumented app's semconv compliance (requires --app)."""

    def test_no_high_cardinality_attrs(self, app_dir):
        if app_dir is None:
            pytest.skip("No --app provided")
        results = _check_source_for_bad_attrs(app_dir)
        failures = [(n, m) for n, ok, m in results if not ok]
        assert not failures, f"High-cardinality attributes found: {failures}"

    def test_fixture_metric_names(self, app_dir):
        if app_dir is None:
            pytest.skip("No --app provided")
        inv = app_dir / ".observe" / "inventory.md"
        if not inv.exists():
            pytest.skip("No .observe/inventory.md in app")
        tables = parse_signal_tables(inv.read_text())
        results = _check_metric_names(tables["metrics"])
        failures = [(n, m) for n, ok, m in results if not ok]
        assert not failures, f"Invalid metric names: {failures}"

    def test_fixture_span_names(self, app_dir):
        if app_dir is None:
            pytest.skip("No --app provided")
        inv = app_dir / ".observe" / "inventory.md"
        if not inv.exists():
            pytest.skip("No .observe/inventory.md in app")
        tables = parse_signal_tables(inv.read_text())
        results = _check_span_names(tables["spans"])
        failures = [(n, m) for n, ok, m in results if not ok]
        assert not failures, f"High-cardinality span names: {failures}"
