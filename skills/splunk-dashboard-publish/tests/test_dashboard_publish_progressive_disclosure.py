from pathlib import Path
import re

import pytest


SKILL_DIR = Path(__file__).resolve().parents[1]
SKILLS_DIR = SKILL_DIR.parent
SKILL = SKILL_DIR / "SKILL.md"
OFFLINE = SKILL_DIR / "references" / "offline-plan.md"
LIVE = SKILL_DIR / "references" / "live-publish.md"
CHART_WIRE = SKILL_DIR / "references" / "chart-wire-contract.md"
COVERAGE = SKILL_DIR / "references" / "dashboard-coverage-model.md"
SPLUNK_API = SKILLS_DIR / "references" / "splunk-api.md"


def test_entrypoint_is_a_bounded_safety_router() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert len(text.encode()) <= 11_000
    assert "## Always-Loaded Safety Contract" in text
    assert "## Reference Router" in text
    assert "Offline mode must not load" in text
    assert "references/offline-plan.md" in text
    assert "references/live-publish.md" in text
    normalized = " ".join(text.split())
    assert "Inside a loaded reference" in normalized
    assert "from that reference's directory" in normalized


def test_always_loaded_contract_keeps_publish_safety_visible() -> None:
    text = " ".join(SKILL.read_text(encoding="utf-8").split())

    for required in (
        "SPLUNK_ACCESS_TOKEN",
        "Never log it",
        "explicit current yes/no confirmation",
        "Create only GAPs",
        "Fetch and reclassify live state on every run",
        "Only HTTP 500 pages",
        "bare `except Exception`",
        "Orphan charts",
        "DELETE /v2/chart/{id}",
        "non-empty Reason",
    ):
        assert required in text


def test_covered_dashboard_put_is_a_narrow_chart_gap_attachment_exception() -> None:
    entrypoint = " ".join(SKILL.read_text(encoding="utf-8").split())
    live = " ".join(LIVE.read_text(encoding="utf-8").split())

    for required in (
        "On a COVERED dashboard, append only confirmed chart GAPs",
        "Never mutate UNCERTAIN objects",
    ):
        assert required in entrypoint

    for required in (
        "sole permitted mutation of a `COVERED` object",
        "does not reclassify the dashboard itself as GAP",
        "every existing `charts[]` placement retained",
        "only the confirmed new chart placements appended",
        "change only `charts[]`",
        "never remove or reorder an existing placement",
    ):
        assert required in live


def test_offline_reference_is_non_mutating_and_self_contained() -> None:
    text = " ".join(OFFLINE.read_text(encoding="utf-8").split())

    for required in (
        "never reads environment credentials",
        "never",
        "calls the Splunk API",
        "UNCERTAIN (offline plan)",
        "`GAP` is reserved for a live search",
        "reclassify against live state before execution",
        '"tags": ["obstudio"]',
        "POST /v2/chart",
        "POST /v2/dashboard",
        "Orphan charts",
        "stop after it",
        "inside the `Reason` cell itself",
        "Normalized Chart Programs",
        "placeholder such as `<normalized SignalFlow>`",
        "final response is incomplete unless",
        'literal `"tags": ["obstudio"]`',
    ):
        assert required in text
    assert "GAP (offline plan)" not in text


def test_offline_future_live_plan_keeps_covered_container_put_narrow() -> None:
    text = " ".join(OFFLINE.read_text(encoding="utf-8").split())

    for required in (
        "Retain every existing `charts[]` placement and its order",
        "append only confirmed new placements",
        "Never remove/reorder existing placements",
        "recreate or otherwise mutate the COVERED dashboard",
        "mutate UNCERTAIN",
        "sole permitted COVERED mutation",
        "does not make the dashboard a GAP",
        "after either the POST failure or the PUT failure",
        "create GAPs only",
        "append-only PUT preserving existing chart placements and order",
        "after dashboard POST or PUT failure record every unreferenced chart ID",
    ):
        assert required in text


def test_connected_dry_run_uses_live_read_only_classification() -> None:
    entrypoint = " ".join(SKILL.read_text(encoding="utf-8").split())
    live = " ".join(LIVE.read_text(encoding="utf-8").split())

    assert "Connected dry-run, live comparison, or mutation" in entrypoint
    assert "A dry-run request with usable live access is not offline" in entrypoint
    assert "perform the read-only live fetch" in entrypoint
    assert "later non-dry-run must re-fetch" in entrypoint
    assert "a connected dry run never writes one" in entrypoint
    assert "A connected dry run never writes a ledger" in live


def test_live_reference_preserves_status_idempotency_and_orphan_contracts() -> None:
    text = " ".join(LIVE.read_text(encoding="utf-8").split())

    for required in (
        "skip-on-500",
        "explicit yes/no",
        "changed live diff invalidates",
        "POST 409/duplicate",
        "POST/PUT 401 or 403",
        "PUT 404",
        "Immediately after each chart POST",
        "Orphan charts",
        "DELETE /v2/chart/{id}",
        "re-fetches and reclassifies live state",
        "Never include the access token",
    ):
        assert required in text


def _chart_options():
    text = CHART_WIRE.read_text(encoding="utf-8")
    blocks = re.findall(r"```python\n(.*?)```", text, flags=re.DOTALL)
    block = next(block for block in blocks if "def chart_options" in block)
    namespace = {}
    exec(block, namespace)
    return namespace["chart_options"]


def test_chart_wire_preserves_explicit_visualization_options() -> None:
    chart_options = _chart_options()

    assert chart_options(
        "time_series", plot_type="AreaChart", color_by="Metric"
    ) == {
        "type": "TimeSeriesChart",
        "colorBy": "Metric",
        "defaultPlotType": "AreaChart",
    }
    assert chart_options("single_value", color_by="Scale") == {
        "type": "SingleValue",
        "colorBy": "Scale",
    }
    assert chart_options("TimeSeriesChart", plot_type="AreaChart") == {
        "type": "TimeSeriesChart",
        "colorBy": "Dimension",
        "defaultPlotType": "AreaChart",
    }
    assert chart_options("SingleValue", color_by="Scale") == {
        "type": "SingleValue",
        "colorBy": "Scale",
    }
    assert chart_options("signalfx_time_chart", plot_type="ColumnChart")[
        "defaultPlotType"
    ] == "ColumnChart"
    assert chart_options("signalfx_single_value_chart", color_by="Scale") == {
        "type": "SingleValue",
        "colorBy": "Scale",
    }
    assert chart_options("time_series", color_by="Scale")["colorBy"] == "Scale"


def test_chart_wire_defaults_only_absent_options_and_rejects_invalid_values() -> None:
    chart_options = _chart_options()

    assert chart_options("time_series") == {
        "type": "TimeSeriesChart",
        "colorBy": "Dimension",
        "defaultPlotType": "LineChart",
    }
    assert chart_options("single_value") == {
        "type": "SingleValue",
        "colorBy": "Metric",
    }
    assert chart_options("list") == {"type": "List", "colorBy": "Dimension"}
    for chart_type in ("single_value", "list", "heatmap", "text", "table"):
        assert "defaultPlotType" not in chart_options(chart_type)

    with pytest.raises(ValueError, match="unsupported plot_type"):
        chart_options("time_series", plot_type="SplineChart")
    with pytest.raises(ValueError, match="unsupported plot_type"):
        chart_options("time_series", plot_type="")
    with pytest.raises(ValueError, match="plot_type is unsupported"):
        chart_options("single_value", plot_type="LineChart")
    with pytest.raises(ValueError, match="unsupported color_by"):
        chart_options("time_series", color_by="Value")
    with pytest.raises(ValueError, match="unsupported color_by"):
        chart_options("single_value", color_by="")
    with pytest.raises(ValueError, match="unsupported color_by"):
        chart_options("heatmap", color_by="Dimension")
    with pytest.raises(ValueError, match="unsupported chart type"):
        chart_options("GaugeChart")


def test_parse_contract_carries_visualization_options_into_wire_mapping() -> None:
    for path in (SKILL, OFFLINE):
        text = path.read_text(encoding="utf-8")
        assert "HCL resource/label" in text
        assert "`plot_type`/`color_by`" in text

    wire = CHART_WIRE.read_text(encoding="utf-8")
    assert '{name, programText, options, packageSpecifications: "signalfx"}' in wire


def test_put_404_requires_a_new_confirmed_diff() -> None:
    text = " ".join(SPLUNK_API.read_text(encoding="utf-8").split())

    assert "PUT 404 directly into an unconfirmed POST" in text
    assert "show a new diff, and obtain new confirmation" in text
    assert "re-classify as GAP and create from scratch" not in text


def test_routed_references_resolve_inside_the_skill_catalog() -> None:
    for relative in (
        "references/offline-plan.md",
        "references/live-publish.md",
        "../references/terraform-normalization.md",
        "../splunk-dashboard/references/dashboard-templates.md",
        "../references/splunk-api.md",
        "references/dashboard-coverage-model.md",
        "../references/ledger-template.md",
        "../references/coverage-decision-tree.md",
        "references/chart-wire-contract.md",
    ):
        target = (SKILL_DIR / relative).resolve()
        assert target.is_file()
        assert target.is_relative_to(SKILLS_DIR.resolve())

    for owner in (OFFLINE, LIVE, CHART_WIRE, COVERAGE):
        for relative in re.findall(r"`([^`]+\.md)`", owner.read_text()):
            if relative.startswith(".observe/"):
                continue
            target = (owner.parent / relative).resolve()
            assert target.is_file(), f"{owner} routes to missing {relative}"
            assert target.is_relative_to(SKILLS_DIR.resolve())
