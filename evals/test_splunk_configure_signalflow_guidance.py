"""Deterministic checks for splunk-configure SignalFlow guardrails."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SPLUNK_CONFIGURE = REPO_ROOT / "skills" / "splunk-configure" / "SKILL.md"
TEMPLATES = (
    REPO_ROOT
    / "skills"
    / "splunk-configure"
    / "references"
    / "terraform-templates.md"
)


def _read(path: Path) -> str:
    assert path.exists(), f"Expected file not found: {path}"
    return path.read_text()


def test_configure_uses_only_proven_telemetry_dimensions():
    skill = _read(SPLUNK_CONFIGURE)
    templates = _read(TEMPLATES)
    required_skill_terms = [
        "Keep the Splunk Observability Cloud API `realm` variable separate",
        "Do not use `var.realm` as a SignalFlow filter",
        "`sfx_realm`",
        "approved Splunk API metadata",
        "Never use a dimension solely because referenced",
        "already-quantized",
        "threshold defaults",
    ]
    required_template_terms = [
        "provider/API `realm` variable",
        "telemetry dimension",
        "`sfx_realm`",
        "deployment.region",
        "cloud.region",
        "precomputed percentile metrics",
        "already-quantized",
        "`max()`/`max(by=[...])`",
    ]
    assert not [term for term in required_skill_terms if term not in skill]
    assert not [term for term in required_template_terms if term not in templates]
    assert "e.g. us1, eu0, lab0" not in skill
    assert "e.g. us1, eu0, lab0" not in templates
