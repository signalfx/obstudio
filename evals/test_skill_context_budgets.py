"""Static guards for progressively disclosed skill context."""

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS = REPO_ROOT / "skills"
PLUGIN_CONTROLS = REPO_ROOT / "plugins" / "obstudio" / "skills" / "observer-control"
CONFIGURE = SKILLS / "splunk-configure" / "SKILL.md"
CONFIGURE_DIR = CONFIGURE.parent
REPORT_FLOW = SKILLS / "references" / "report-flow-contract.md"
CLASSIFICATION = CONFIGURE_DIR / "references" / "detector-classification.md"
TEMPLATES = CONFIGURE_DIR / "references" / "terraform-templates.md"
SIGNALFLOW_PATTERNS = SKILLS / "references" / "signalflow-patterns.md"
TERRAFORM_NORMALIZATION = SKILLS / "references" / "terraform-normalization.md"
SPLUNK_API = SKILLS / "references" / "splunk-api.md"
LEDGER = SKILLS / "references" / "ledger-template.md"
COVERAGE_TREE = SKILLS / "references" / "coverage-decision-tree.md"
INCIDENT = SKILLS / "references" / "incident-readiness.md"
GENAI = SKILLS / "references" / "genai-readiness.md"
FULL_RUNTIME = SKILLS / "references" / "full-runtime-acceptance.md"

AUDIT_DIR = SKILLS / "otel-audit"
INSTRUMENT_DIR = SKILLS / "otel-instrument"
VERIFY_DIR = SKILLS / "otel-verify"
DASHBOARD_DIR = SKILLS / "splunk-dashboard"
DASHBOARD_PUBLISH_DIR = SKILLS / "splunk-dashboard-publish"
DETECTOR_PUBLISH_DIR = SKILLS / "splunk-detector-publish"
ENTRYPOINT_BUDGETS = {
    SKILLS / "connect-splunk-observability-cloud" / "SKILL.md": 4_000,
    SKILLS / "create-splunk-free-account" / "SKILL.md": 19_000,
    SKILLS / "otel-audit" / "SKILL.md": 10_000,
    SKILLS / "otel-instrument" / "SKILL.md": 22_000,
    SKILLS / "otel-verify" / "SKILL.md": 12_000,
    CONFIGURE: 39_000,
    SKILLS / "splunk-dashboard" / "SKILL.md": 6_000,
    SKILLS / "splunk-dashboard-publish" / "SKILL.md": 11_000,
    SKILLS / "splunk-dashboard-sync" / "SKILL.md": 1_000,
    SKILLS / "splunk-detector-publish" / "SKILL.md": 10_000,
    SKILLS / "splunk-sync" / "SKILL.md": 1_000,
    PLUGIN_CONTROLS / "observer-open" / "SKILL.md": 1_800,
    PLUGIN_CONTROLS / "observer-restart" / "SKILL.md": 3_200,
    PLUGIN_CONTROLS / "observer-status" / "SKILL.md": 2_000,
    PLUGIN_CONTROLS / "observer-stop" / "SKILL.md": 3_000,
}
ROUTING_TERMS = {
    SKILLS / "connect-splunk-observability-cloud" / "SKILL.md": (
        "connect an existing or newly ready",
        "outside agent context",
        "Do not use this skill to create",
        "$create-splunk-free-account",
    ),
    SKILLS / "create-splunk-free-account" / "SKILL.md": (
        "consent-gated",
        "reviewed supported region",
        "explicitly asks to submit another intake",
        "explicit terms acceptance",
        "never uses the Splunk web form",
    ),
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
    SKILLS / "splunk-dashboard" / "SKILL.md": (
        "$splunk-dashboard",
        "generate a dashboard",
        "create charts for my service",
        "$splunk-configure",
        "$splunk-dashboard-publish",
    ),
    SKILLS / "splunk-dashboard-publish" / "SKILL.md": (
        "$splunk-dashboard-publish",
        "COVERED/GAP/UNCERTAIN",
        "sync dashboards",
        "create missing dashboards",
    ),
    SKILLS / "splunk-dashboard-sync" / "SKILL.md": (
        "DEPRECATED",
        "$splunk-dashboard-publish",
    ),
    SKILLS / "splunk-detector-publish" / "SKILL.md": (
        "$splunk-detector-publish",
        "COVERED/GAP/UNCERTAIN",
        "sync detectors",
        "create missing monitors",
    ),
    SKILLS / "splunk-sync" / "SKILL.md": (
        "DEPRECATED",
        "$splunk-detector-publish",
    ),
    PLUGIN_CONTROLS / "observer-open" / "SKILL.md": (
        "Open the local Obstudio Observer",
        "host-provided browser",
        "safe clickable-URL fallback",
    ),
    PLUGIN_CONTROLS / "observer-restart" / "SKILL.md": (
        "refresh or restart",
        "UI is stale",
        "MCP endpoint is unavailable",
        "bootstrap state",
    ),
    PLUGIN_CONTROLS / "observer-status" / "SKILL.md": (
        "installed",
        "bootstrapped",
        "reachable",
        "MCP endpoint and browser URL",
    ),
    PLUGIN_CONTROLS / "observer-stop" / "SKILL.md": (
        "stop or disconnect",
        "intentionally wants",
        "managed runtime",
        "shared Observer",
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


def _section_bytes(path: Path, start: str, end: str) -> int:
    text = path.read_text()
    start_marker = f"\n{start}\n"
    end_marker = f"\n{end}\n"
    assert text.count(start_marker) == 1, f"expected one {start!r} heading in {path}"
    assert text.count(end_marker) == 1, f"expected one {end!r} heading in {path}"
    section = start + "\n" + text.split(start_marker, 1)[1].split(end_marker, 1)[0]
    return len(section.encode())


def _instrument_report_contract_bytes() -> int:
    text = REPORT_FLOW.read_text()
    audit_intro = "\nFor an audit,"
    status = "\n## Status Rules\n"
    audit = "\n## Audit Contract\n"
    instrument = "\n## Instrumentation Contract\n"
    verify = "\n## Verification Report Contract\n"
    for marker in (audit_intro, status, audit, instrument, verify):
        assert text.count(marker) == 1

    prefix = text.split(audit_intro, 1)[0].rstrip()
    status_section = "## Status Rules\n" + text.split(status, 1)[1].split(
        audit, 1
    )[0].rstrip()
    instrument_section = "## Instrumentation Contract\n" + text.split(
        instrument, 1
    )[1].split(verify, 1)[0].rstrip()
    routed = "\n\n".join((prefix, status_section, instrument_section)) + "\n"
    return len(routed.encode())


def _verify_full_route_bytes() -> int:
    refs = VERIFY_DIR / "references"
    return (
        _bytes(
            VERIFY_DIR / "SKILL.md",
            refs / "verification-report.md",
            refs / "json-approval-handoff.md",
            refs / "direct-verification.md",
            refs / "project-runtime-resolution.md",
            refs / "path-scenario-coverage.md",
            refs / "explorer-witness.md",
            refs / "app-code-test-authoring.md",
            FULL_RUNTIME,
        )
        + _section_bytes(
            REPORT_FLOW,
            "## Verification Report Contract",
            "## Splunk Configure Contract",
        )
    )


def _bytes(*paths: Path) -> int:
    return sum(path.stat().st_size for path in paths)


def test_all_shipped_entrypoints_and_catalog_descriptions_are_bounded() -> None:
    discovered = set(SKILLS.glob("*/SKILL.md")) | set(
        PLUGIN_CONTROLS.glob("*/SKILL.md")
    )
    assert set(ENTRYPOINT_BUDGETS) == discovered
    assert set(ROUTING_TERMS) == discovered

    total_bytes = 0

    for path, byte_budget in ENTRYPOINT_BUDGETS.items():
        raw = path.read_bytes()
        text = raw.decode()
        description = " ".join(_description(text).split())
        total_bytes += len(raw)
        assert len(raw) <= byte_budget, f"{path} exceeds its entrypoint budget"
        assert len(description.split()) <= 60
        for term in ROUTING_TERMS[path]:
            assert term in description, f"{path} description lost routing term {term}"

    assert total_bytes <= 142_000


def test_otel_audit_routes_have_explicit_context_budgets() -> None:
    core = AUDIT_DIR / "SKILL.md"
    assessment = AUDIT_DIR / "references" / "telemetry-assessment.md"
    report = AUDIT_DIR / "references" / "report-contract.md"
    genai_local = AUDIT_DIR / "references" / "genai-audit.md"
    languages = tuple((AUDIT_DIR / "references" / "languages").glob("*.md"))
    standard = _bytes(core, assessment, report) + max(
        path.stat().st_size for path in languages
    )

    assert standard <= 60_000
    assert standard + INCIDENT.stat().st_size <= 73_000
    assert standard + GENAI.stat().st_size + genai_local.stat().st_size <= 113_000
    assert (
        standard
        + INCIDENT.stat().st_size
        + GENAI.stat().st_size
        + genai_local.stat().st_size
        <= 126_000
    )


def test_otel_instrument_routes_have_explicit_context_budgets() -> None:
    core = INSTRUMENT_DIR / "SKILL.md"
    runtime = INSTRUMENT_DIR / "references" / "project-runtime-validation.md"
    handoff = INSTRUMENT_DIR / "references" / "json-approval-handoff.md"
    incident_local = INSTRUMENT_DIR / "references" / "incident-implementation.md"
    genai_local = INSTRUMENT_DIR / "references" / "genai-implementation.md"
    languages = tuple((INSTRUMENT_DIR / "references" / "languages").glob("*.md"))
    direct = _bytes(core, runtime) + _instrument_report_contract_bytes() + max(
        path.stat().st_size for path in languages
    )
    canonical_instrument = direct + handoff.stat().st_size
    canonical_end_to_end = canonical_instrument + _verify_full_route_bytes()

    assert direct <= 85_000
    assert direct + FULL_RUNTIME.stat().st_size <= 89_000
    assert canonical_instrument <= 103_000
    assert canonical_end_to_end <= 175_000
    assert (
        canonical_instrument + INCIDENT.stat().st_size + incident_local.stat().st_size
        <= 122_000
    )
    assert canonical_instrument + GENAI.stat().st_size + genai_local.stat().st_size <= 152_000
    assert (
        canonical_end_to_end
        + INCIDENT.stat().st_size
        + incident_local.stat().st_size
        + GENAI.stat().st_size
        + genai_local.stat().st_size
        <= 246_000
    )


def test_otel_verify_routes_have_explicit_context_budgets() -> None:
    core = VERIFY_DIR / "SKILL.md"
    refs = VERIFY_DIR / "references"
    report = refs / "verification-report.md"
    handoff = refs / "json-approval-handoff.md"
    shared_contract = _section_bytes(
        REPORT_FLOW, "## Verification Report Contract", "## Splunk Configure Contract"
    )
    durable = _bytes(core, report, handoff) + shared_contract
    full = _verify_full_route_bytes()

    assert durable <= 34_000
    assert full <= 71_000


def test_dashboard_generation_routes_have_explicit_context_budgets() -> None:
    ordinary = _bytes(
        DASHBOARD_DIR / "SKILL.md",
        DASHBOARD_DIR / "references" / "dashboard-classification.md",
        DASHBOARD_DIR / "references" / "dashboard-templates.md",
        DASHBOARD_DIR / "references" / "artifact-contract.md",
    )

    assert ordinary <= 24_000
    assert ordinary + SIGNALFLOW_PATTERNS.stat().st_size <= 31_000
    assert ordinary + SIGNALFLOW_PATTERNS.stat().st_size + TERRAFORM_NORMALIZATION.stat().st_size <= 36_000


def test_dashboard_publish_routes_have_explicit_context_budgets() -> None:
    core = DASHBOARD_PUBLISH_DIR / "SKILL.md"
    refs = DASHBOARD_PUBLISH_DIR / "references"
    wire = refs / "chart-wire-contract.md"
    offline = _bytes(
        core,
        refs / "offline-plan.md",
        wire,
        TERRAFORM_NORMALIZATION,
    )
    live = _bytes(
        core,
        refs / "live-publish.md",
        refs / "dashboard-coverage-model.md",
        wire,
        TERRAFORM_NORMALIZATION,
        SPLUNK_API,
        LEDGER,
        COVERAGE_TREE,
    )

    assert offline <= 24_000
    assert live <= 47_000


def test_detector_publish_routes_have_explicit_context_budgets() -> None:
    core = DETECTOR_PUBLISH_DIR / "SKILL.md"
    refs = DETECTOR_PUBLISH_DIR / "references"
    offline = _bytes(core, refs / "offline-plan.md", TERRAFORM_NORMALIZATION)
    live = _bytes(
        core,
        refs / "live-publish.md",
        refs / "coverage-model.md",
        TERRAFORM_NORMALIZATION,
        SPLUNK_API,
        LEDGER,
    )

    assert offline <= 18_500
    assert live <= 39_000


def test_deprecated_alias_targets_resolve() -> None:
    aliases = {
        SKILLS / "splunk-sync" / "SKILL.md": "../splunk-detector-publish/SKILL.md",
        SKILLS / "splunk-dashboard-sync" / "SKILL.md": "../splunk-dashboard-publish/SKILL.md",
    }

    for alias, relative in aliases.items():
        assert relative in alias.read_text()
        target = (alias.parent / relative).resolve()
        assert target.is_file()
        assert target.is_relative_to(SKILLS.resolve())


def test_splunk_configure_entrypoint_is_a_bounded_router() -> None:
    raw = CONFIGURE.read_bytes()
    text = raw.decode()
    normalized = " ".join(text.split())
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
    assert "Resolve paths in this entrypoint" in normalized
    assert "Inside a loaded reference" in normalized
    assert "from that reference's directory" in normalized
    assert "do not probe for alternate copies unless it is missing" in text
    assert "Do not read its source before" in text


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
