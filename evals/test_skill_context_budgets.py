"""Static guards for progressively disclosed skill context."""

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS = REPO_ROOT / "skills"
CONFIGURE = SKILLS / "splunk-configure" / "SKILL.md"
CONFIGURE_DIR = CONFIGURE.parent
REPORT_FLOW = SKILLS / "references" / "report-flow-contract.md"
CLASSIFICATION = CONFIGURE_DIR / "references" / "detector-classification.md"
TEMPLATES = CONFIGURE_DIR / "references" / "terraform-templates.md"
SIGNALFLOW_PATTERNS = SKILLS / "references" / "signalflow-patterns.md"
ENTRYPOINT_BUDGETS = {
    SKILLS / "otel-audit" / "SKILL.md": 71_000,
    SKILLS / "otel-instrument" / "SKILL.md": 92_000,
    SKILLS / "otel-verify" / "SKILL.md": 37_000,
    CONFIGURE: 39_000,
}
ROUTING_TERMS = {
    SKILLS / "otel-audit" / "SKILL.md": (
        "$otel-audit",
        "coverage/readiness",
        "incident detection or localization",
        "GenAI/LLM",
        "$otel-instrument",
    ),
    SKILLS / "otel-instrument" / "SKILL.md": (
        "$otel-instrument",
        ".observe/otel-selection.json",
        "specific spans or metrics",
        "incident-detection",
        "GenAI/LLM",
    ),
    SKILLS / "otel-verify" / "SKILL.md": (
        "$otel-verify",
        "approved audit IDs",
        "per-path coverage",
        "local OTLP emission",
        "$otel-instrument",
    ),
    CONFIGURE: (
        "$splunk-configure",
        "detectors",
        "dashboards",
        "alert-coverage",
        "GenAI/LLM",
    ),
}


def _description(text: str) -> str:
    frontmatter = text.split("---", 2)[1]
    return frontmatter.split("description: >-", 1)[1].split("metadata:", 1)[0]


def _non_shell_fences(text: str) -> list[str]:
    languages = re.findall(r"^```([^\n]*)$", text, re.MULTILINE)
    assert len(languages) % 2 == 0, "unbalanced Markdown fences"
    return [language for language in languages[::2] if language not in {"bash", "sh"}]


def _long_prose_paragraphs(text: str) -> set[str]:
    paragraphs: set[str] = set()
    lines: list[str] = []
    in_fence = False

    def flush() -> None:
        normalized = " ".join(" ".join(lines).split())
        if len(normalized) >= 120:
            paragraphs.add(normalized)
        lines.clear()

    for line in text.splitlines():
        if line.startswith("```"):
            flush()
            in_fence = not in_fence
        elif (
            in_fence
            or not line.strip()
            or line.startswith("#")
            or line.lstrip().startswith(("-", "*", "|"))
        ):
            flush()
        else:
            lines.append(line.strip())
    flush()
    return paragraphs


def _section_tail_bytes(path: Path, heading: str) -> int:
    text = path.read_text()
    assert text.count(heading) == 1, f"expected one {heading!r} heading in {path}"
    tail = heading + text.split(heading, 1)[1]
    return len(tail.encode())


def test_core_entrypoints_and_catalog_descriptions_are_bounded() -> None:
    total_bytes = 0

    for path, byte_budget in ENTRYPOINT_BUDGETS.items():
        raw = path.read_bytes()
        text = raw.decode()
        description = " ".join(_description(text).split())
        total_bytes += len(raw)
        assert len(raw) <= byte_budget, f"{path} exceeds its entrypoint budget"
        assert len(description.split()) <= 55
        for term in ROUTING_TERMS[path]:
            assert term in description, f"{path} description lost routing term {term}"

    assert total_bytes <= 236_000


def test_splunk_configure_entrypoint_is_a_bounded_router() -> None:
    raw = CONFIGURE.read_bytes()
    text = raw.decode()
    configure_contract_bytes = _section_tail_bytes(
        REPORT_FLOW, "## Splunk Configure Contract"
    )
    default_load_bytes = len(raw) + configure_contract_bytes
    full_load_bytes = (
        default_load_bytes
        + CLASSIFICATION.stat().st_size
        + TEMPLATES.stat().st_size
        + SIGNALFLOW_PATTERNS.stat().st_size
    )

    assert len(raw) <= 39_000
    assert default_load_bytes <= 42_000
    assert full_load_bytes <= 97_000
    assert not _non_shell_fences(text)
    assert "read only the tail" in text
    assert "Do not load the preceding audit" in text


def test_splunk_configure_routes_to_single_contract_owners() -> None:
    text = CONFIGURE.read_text()
    normalized = " ".join(text.split())
    core_paragraphs = _long_prose_paragraphs(text)
    references = (
        "../references/report-flow-contract.md",
        "references/detector-classification.md",
        "references/terraform-templates.md",
    )

    for relative in references:
        assert relative in text
        target = (CONFIGURE_DIR / relative).resolve()
        assert target.is_file()
        assert target.is_relative_to(SKILLS.resolve())
        assert not core_paragraphs.intersection(_long_prose_paragraphs(target.read_text()))

    assert "that reference owns the HCL examples and category defaults" in normalized
    assert "Do not copy those authorities into the report" in normalized


def test_configure_verification_shape_is_owned_by_report_flow() -> None:
    configure = CONFIGURE.read_text()
    section = REPORT_FLOW.read_text().split("## Splunk Configure Verification", 1)[1]
    report_shape = section.split("```markdown", 1)[1].split("```", 1)[0]
    headings = [line for line in report_shape.splitlines() if line.startswith("#")]

    assert "exact report shape and heading order" in configure
    assert headings == [
        "# Splunk Configure Verification: <service>",
        "## Executive Summary",
        "## What Was Added",
        "## Tested And Working",
        "## Not Yet Proven",
        "## Validation Notes",
        "## Next Steps",
    ]
    assert "Resource Label | Metric | Detect Condition | Severity" in configure


def test_splunk_configure_keeps_its_configure_specific_flow() -> None:
    configure = " ".join(CONFIGURE.read_text().split())

    assert "audit -> instrument -> verify -> configure -> configure-verify" in configure


def test_splunk_configure_reference_owns_sensitive_hcl_shapes() -> None:
    templates = TEMPLATES.read_text()

    for required in (
        'source  = "splunk-terraform/signalfx"',
        'provider "signalfx"',
        "auth_token = var.api_token",
        'api_url    = "https://api.${var.realm}.signalfx.com"',
        'variable "realm"',
        'variable "api_token"',
        "sensitive   = true",
        'variable "service_name"',
        'variable "notification_channel"',
    ):
        assert required in templates

    nested_reference = "../../references/signalflow-patterns.md"
    assert nested_reference in templates
    assert (TEMPLATES.parent / nested_reference).resolve() == SIGNALFLOW_PATTERNS.resolve()


def test_alert_coverage_mode_loads_its_contract_without_metrics() -> None:
    configure = " ".join(CONFIGURE.read_text().split())
    templates = TEMPLATES.read_text()

    assert (
        "For `alert-coverage-audit` mode, load the Alert Coverage Audit Output "
        "section in `references/terraform-templates.md` even when no "
        "detector-ready metric exists"
    ) in configure
    assert "## Alert Coverage Audit Output" in templates
    for required_row in (
        "Primary workflow availability",
        "API error/latency",
        "Ingest lag/drops/freshness",
        "Queue/backpressure",
        "Dependency health",
        "Auth/domain-routing/edge",
        "Critical business workflow",
        "Multi-region blast radius",
        "Capacity saturation",
        "Release/config/canary correlation",
    ):
        assert required_row in templates
