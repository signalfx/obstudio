"""Static guards for the splunk-dashboard progressive-loading contract."""

from pathlib import Path
import re


SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL = SKILL_DIR / "SKILL.md"
CLASSIFICATION = SKILL_DIR / "references" / "dashboard-classification.md"
TEMPLATES = SKILL_DIR / "references" / "dashboard-templates.md"
ARTIFACTS = SKILL_DIR / "references" / "artifact-contract.md"


def _read(path: Path) -> str:
    assert path.is_file(), f"missing dashboard skill file: {path}"
    return path.read_text()


def _normalized(*paths: Path) -> str:
    return " ".join("\n".join(_read(path) for path in paths).split())


def test_entrypoint_is_small_and_preserves_trigger_phrases() -> None:
    text = _read(SKILL)
    assert len(text.encode()) <= 6_000
    for trigger in (
        "$splunk-dashboard",
        "generate a dashboard",
        "build a dashboard from an audit",
        "create charts for my service",
        "visualize my metrics",
    ):
        assert trigger in text

    normalized = " ".join(text.split())
    assert "Resolve paths in this entrypoint from the skill directory" in normalized
    assert "Inside a loaded reference" in normalized
    assert "from that reference's directory" in normalized


def test_references_are_routed_after_input_gates() -> None:
    raw = _read(SKILL)
    text = " ".join(raw.split())
    gate = raw.index("The first skill action after reading this entrypoint")
    routed = raw.index("## Reference routing after the gate")
    assert gate < routed
    assert "Do not copy or replace the audit" in text
    assert "create output directories, or load any reference before this parse" in text
    assert "valid JSON" in text
    assert "select the mode: standard dashboards" in text
    assert "Only after confirming the audited service, non-empty metric inventory, and mode" in text
    for path in (
        "references/dashboard-classification.md",
        "references/dashboard-templates.md",
        "references/artifact-contract.md",
    ):
        assert path in text
        assert raw.index(path) > routed
    assert "signalflow-patterns.md` only for" in text
    assert "terraform-normalization.md` only when" in text
    assert "Do not load publishing or detector references" in text


def test_ordinary_generation_route_stays_bounded() -> None:
    routed = sum(
        len(_read(path).encode())
        for path in (SKILL, CLASSIFICATION, TEMPLATES, ARTIFACTS)
    )
    assert routed <= 24_000


def test_nested_reference_routes_resolve_from_their_owner() -> None:
    skills_dir = SKILL_DIR.parent.resolve()
    for owner in (CLASSIFICATION, TEMPLATES, ARTIFACTS):
        for relative in re.findall(r"`([^`]+\.md)`", _read(owner)):
            if relative.startswith(".observe/") or "/SKILL.md" in relative:
                continue
            target = (owner.parent / relative).resolve()
            assert target.is_file(), f"{owner} routes to missing {relative}"
            assert target.is_relative_to(skills_dir)


def test_generation_and_publish_have_separate_wire_authorities() -> None:
    templates = _read(TEMPLATES)
    assert "Chart resource ↔ preview mapping" in templates
    assert "REST `options.type`" not in templates
    assert "Live REST type and body rules belong exclusively" in templates


def test_split_contract_preserves_dashboard_semantics_and_safety() -> None:
    text = _normalized(SKILL, CLASSIFICATION, TEMPLATES, ARTIFACTS)
    for required in (
        "signalfx_dashboard_group",
        "signalfx_dashboard",
        "signalfx_time_chart",
        "chart_id",
        "12-column",
        "column + width <= 12",
        "sensitive = true",
        ".observe/dashboards.preview.json",
        "schemaVersion",
        "groups -> dashboards -> charts",
        ".observe/dashboards.md",
        "data(...).<aggregation>().publish(...)",
        "$splunk-dashboard-publish",
        "do not call a network",
        "do not run Terraform",
    ):
        assert required in text
    for chart_type in (
        "time_series",
        "single_value",
        "list",
        "heatmap",
        "text",
        "table",
    ):
        assert chart_type in text
    for genai_category in (
        "genai-latency",
        "genai-token-pressure",
        "genai-provider",
        "genai-tool",
        "genai-model-config",
        "genai-workflow-fanout",
        "genai-retrieval",
        "genai-memory-context",
        "genai-evaluation-quality",
        "genai-content-governance",
        "genai-cost",
    ):
        assert genai_category in text
    for genai_match in (
        "requested/response model",
        "agent/model/tool call counts",
        "bounded numeric capture, redaction, privacy",
        "app-computed cost",
    ):
        assert genai_match in text
    assert "generic words such as model, memory, quality, or cost alone do not qualify" in text
    assert "counts, outcomes, and cost use a `time_series` sum" in text
    assert "current state, score, or ratio uses `single_value`" in text
    assert "detect()/when()/threshold()" in text
