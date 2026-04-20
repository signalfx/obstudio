"""Golden inventory self-consistency tests."""

import pytest

from conftest import all_signals, extract_signal_names, parse_signal_tables


class TestGoldenConsistency:
    """Validate golden inventories are internally consistent."""

    def test_signal_sections_present(self, golden_inventory):
        text = golden_inventory.read_text()
        required = ["SLI Definitions", "Spans", "Metrics", "Logs"]
        found = [s for s in required if f"## {s}" in text]
        assert found == required, f"Missing sections: {set(required) - set(found)}"

    def test_has_signals(self, golden_inventory):
        tables = parse_signal_tables(golden_inventory.read_text())
        signals = all_signals(tables)
        assert len(signals) > 0, "No signals found in golden inventory"

    def test_unique_signal_names(self, golden_inventory):
        tables = parse_signal_tables(golden_inventory.read_text())
        signals = all_signals(tables)
        names = extract_signal_names(signals)
        assert len(names) == len(signals), (
            f"{len(signals) - len(names)} duplicate signal names"
        )

    def test_valid_categories(self, golden_inventory):
        tables = parse_signal_tables(golden_inventory.read_text())
        signals = all_signals(tables)
        valid = {"OOB", "Custom", "Derived"}
        categories = {s.get("Category", "") for s in signals} - {""}
        bad = categories - valid
        assert not bad, f"Invalid categories: {bad}"


class TestGoldenComparison:
    """Compare fixture output against golden (requires --app)."""

    def test_signal_count_similarity(self, app_dir, golden_inventory, request):
        if app_dir is None:
            pytest.skip("No --app provided")
        inv = app_dir / ".observe" / "inventory.md"
        if not inv.exists():
            pytest.skip("No .observe/inventory.md in app")

        threshold = request.config.getoption("--pass-rate")
        actual = all_signals(parse_signal_tables(inv.read_text()))
        golden = all_signals(parse_signal_tables(golden_inventory.read_text()))

        if len(golden) == 0:
            return
        ratio = min(len(actual), len(golden)) / max(len(actual), len(golden))
        assert ratio >= threshold, (
            f"Signal count ratio {ratio:.0%} below {threshold:.0%} "
            f"(actual={len(actual)}, golden={len(golden)})"
        )

    def test_signal_name_overlap(self, app_dir, golden_inventory, request):
        if app_dir is None:
            pytest.skip("No --app provided")
        inv = app_dir / ".observe" / "inventory.md"
        if not inv.exists():
            pytest.skip("No .observe/inventory.md in app")

        threshold = request.config.getoption("--pass-rate")
        actual_names = extract_signal_names(
            all_signals(parse_signal_tables(inv.read_text()))
        )
        golden_names = extract_signal_names(
            all_signals(parse_signal_tables(golden_inventory.read_text()))
        )

        if not golden_names:
            return
        union = actual_names | golden_names
        jaccard = len(actual_names & golden_names) / len(union) if union else 1.0
        assert jaccard >= threshold, (
            f"Name overlap {jaccard:.0%} below {threshold:.0%} "
            f"(matched {len(actual_names & golden_names)}/{len(golden_names)})"
        )
