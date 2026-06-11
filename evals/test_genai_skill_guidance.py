"""Deterministic checks for advanced readiness skill guidance."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
GENAI_REF = SKILLS_DIR / "references" / "genai-readiness.md"
SPLUNK_CONFIGURE = SKILLS_DIR / "splunk-configure" / "SKILL.md"
SPLUNK_CONFIGURE_REFS = SKILLS_DIR / "splunk-configure" / "references"


def _read(path: Path) -> str:
    assert path.exists(), f"Expected file not found: {path}"
    return path.read_text()


def test_genai_reference_covers_otel_semconv_signals():
    text = _read(GENAI_REF)
    required_terms = [
        "gen_ai.operation.name",
        "gen_ai.provider.name",
        "gen_ai.request.model",
        "gen_ai.response.model",
        "gen_ai.client.operation.duration",
        "gen_ai.client.token.usage",
        "invoke_agent",
        "invoke_workflow",
        "execute_tool",
        "retrieval",
        "error.type",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_genai_reference_requires_guild_like_trace_shape_generically():
    text = _read(GENAI_REF)
    required_terms = [
        "service workflow span",
        "agent/workflow span",
        "tool execution span",
        "LLM inference span",
        "retrieval span",
        "context propagation",
        "service.name",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_audit_and_instrument_load_genai_reference():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    for text in (audit, instrument):
        assert "../references/genai-readiness.md" in text
        assert "GenAI" in text
        assert "LLM" in text


def test_instrument_converts_incident_readiness_audit_to_patchable_work():
    text = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    required_terms = [
        "Audit-Driven Incident Readiness",
        "approved request for custom incident-readiness instrumentation",
        "Do not stop",
        "auto-instrumentation",
        "highest-value app-owned patchable signal",
        "workflow outcome/error/latency",
        "dependency timeout/retry/rate-limit/error",
        "queue/backpressure",
        "no safe app-owned",
        "incident-readiness patch found",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_instrument_skips_custom_prompt_for_incident_readiness_requests():
    text = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    required_terms = [
        "Skip this prompt",
        "incident-readiness work",
        "Audit-Driven Incident Readiness path applies",
        "implement the safe",
        "scoped",
        "signals",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_splunk_configure_generates_genai_readiness_categories():
    skill = _read(SPLUNK_CONFIGURE)
    classification = _read(SPLUNK_CONFIGURE_REFS / "detector-classification.md")
    templates = _read(SPLUNK_CONFIGURE_REFS / "terraform-templates.md")
    required_terms = [
        "genai-latency",
        "genai-token-pressure",
        "genai-provider",
        "genai-tool",
        "genai-model-config",
        "genai-workflow-fanout",
        "genai-retrieval",
    ]
    for text in (skill, classification, templates):
        missing = [term for term in required_terms if term not in text]
        assert not missing


def test_splunk_configure_prioritizes_genai_before_generic_red():
    classification = _read(SPLUNK_CONFIGURE_REFS / "detector-classification.md")
    assert "Classify GenAI metrics before generic latency" in classification
    assert "metric name starts with \"gen_ai.\"" in classification
    assert "gen_ai.client.operation.duration" in classification


def test_genai_guidance_stays_generic():
    paths = [
        GENAI_REF,
        SKILLS_DIR / "otel-audit" / "SKILL.md",
        SKILLS_DIR / "otel-instrument" / "SKILL.md",
        SPLUNK_CONFIGURE,
        SPLUNK_CONFIGURE_REFS / "detector-classification.md",
        SPLUNK_CONFIGURE_REFS / "terraform-templates.md",
    ]
    blocked_terms = [
        "IR-",
        "guildcore",
        "Guildcore",
        "guild.ai",
        "sb-rest",
        "US1",
        "EU0",
    ]
    for path in paths:
        text = _read(path)
        bad = [term for term in blocked_terms if term in text]
        assert not bad, f"{path} contains non-generic terms: {bad}"
