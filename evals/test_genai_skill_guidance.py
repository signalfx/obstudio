"""Deterministic checks for incident and GenAI readiness skill guidance."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
GENAI_REF = SKILLS_DIR / "references" / "genai-readiness.md"
INCIDENT_REF = SKILLS_DIR / "references" / "incident-readiness.md"
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


def test_genai_reference_requires_nested_trace_shape_generically():
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


def test_incident_reference_covers_generic_incident_patterns():
    text = _read(INCIDENT_REF)
    required_terms = [
        "API/workflow",
        "Customer impact",
        "Dependency",
        "Freshness",
        "Backpressure",
        "Auth/edge",
        "Capacity",
        "Release context",
        "detector group-by keys",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_incident_reference_covers_generic_mttd_signal_checklist():
    text = _read(INCIDENT_REF)
    required_terms = [
        "service.version",
        "deployment.environment",
        "deployment.region",
        "deployment.platform",
        "container.image.tag",
        "artifact version",
        "config version",
        "canary/rollout batch",
        "restart/crash-loop",
        "desired-vs-healthy",
        "startup/readiness/healthcheck",
        "CPU/memory/disk",
        "concurrency",
        "quota",
        "throttling",
        "endpoint health",
        "target health",
        "traffic target health",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_audit_and_instrument_load_incident_reference():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    for text in (audit, instrument):
        assert "../references/incident-readiness.md" in text
        assert "incident-readiness" in text
        assert "faster incident detection" in text


def test_audit_and_instrument_load_genai_reference():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    for text in (audit, instrument):
        assert "../references/genai-readiness.md" in text
        assert "GenAI" in text
        assert "LLM" in text


def test_instrument_allows_recommended_semconv_readiness_signals():
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    required_terms = [
        "recommended optional metrics or attributes",
        "requested readiness",
        "observe the values accurately",
        "privacy/cardinality",
    ]
    missing = [term for term in required_terms if term not in instrument]
    assert not missing


def test_instrument_converts_incident_readiness_audit_to_patchable_work():
    text = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    required_terms = [
        "Audit-Driven Incident Readiness",
        "approved request for custom incident-readiness instrumentation",
        "Do not stop",
        "auto-instrumentation",
        "gap-closure matrix",
        "workflow outcome/error/latency",
        "dependency timeout/retry/rate-limit/error",
        "queue/backpressure",
        "Do not call incident-readiness instrumentation complete",
        "no safe app-owned",
        "incident-readiness patch found",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_instrument_requires_gap_closure_matrix_for_incident_readiness():
    text = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    required_terms = [
        "gap-closure matrix",
        "gap -> repo evidence -> owner -> code location",
        "add instrumentation",
        "prove existing instrumentation",
        "mark out of scope with owner",
        "Do not call incident-readiness instrumentation complete",
        "executor/backpressure",
        "streaming",
        "auth/edge",
        "freshness/job",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_instrument_requires_all_safe_app_owned_gap_closure():
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    genai_reference = _read(GENAI_REF)

    required_instrument_terms = [
        "all discovered app-owned gaps",
        "Do not select",
        "one representative",
        "Implement every safe app-owned patchable signal",
        "Every discovered gap must resolve",
        "add instrumentation",
        "prove existing instrumentation",
        "mark out of scope with owner",
        "must not say",
        "complete",
        "covered",
        "fixed",
    ]
    missing_instrument = [term for term in required_instrument_terms if term not in instrument]
    assert not missing_instrument

    required_audit_terms = [
        "Do not mark a GenAI area complete just because one",
        "representative signal exists",
        "list every discovered app-owned gap separately",
    ]
    missing_audit = [term for term in required_audit_terms if term not in audit]
    assert not missing_audit

    required_reference_terms = [
        "close every safe app-owned GenAI gap",
        "Do not pick",
        "highest-value or easiest",
        "provider, token, stream, tool, retrieval",
    ]
    missing_reference = [term for term in required_reference_terms if term not in genai_reference]
    assert not missing_reference


def test_genai_guidance_rejects_metric_only_closure_for_patchable_surfaces():
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    genai_reference = _read(GENAI_REF)

    required_reference_terms = [
        "Completion Contract",
        "Trace:",
        "Metric:",
        "Log/event:",
        "metric-only",
        "trace evidence",
        "metric evidence",
        "log/span-event evidence",
        "Do not call GenAI instrumentation complete",
    ]
    missing_reference = [term for term in required_reference_terms if term not in genai_reference]
    assert not missing_reference

    required_instrument_terms = [
        "Metric-only closure is not acceptable",
        "trace, metric, and",
        "log/span-event planes",
        "trace evidence -> metric evidence -> log/event evidence",
        "error status",
        "error.type",
        "span event",
        "trace-correlated",
    ]
    missing_instrument = [term for term in required_instrument_terms if term not in instrument]
    assert not missing_instrument


def test_instrument_requires_incident_evidence_gap_closure():
    skill = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    reference = _read(INCIDENT_REF)
    required_skill_terms = [
        "incident-evidence mode",
        "failure mechanism",
        "owning code surface",
        "MTTD/localization impact",
        "executor/backpressure",
        "streaming",
        "auth/edge",
        "freshness/job",
        "release/config",
    ]
    missing_skill = [term for term in required_skill_terms if term not in skill]
    assert not missing_skill

    required_reference_terms = [
        "Incident-Evidence Mode",
        "MTTD-improving",
        "localization-only",
        "Required Surface Patterns",
        "Auth, edge, and secrets",
        "Jobs, reports, exports, sync, and notifications",
        "expected-vs-running version",
    ]
    missing_reference = [term for term in required_reference_terms if term not in reference]
    assert not missing_reference


def test_instrument_requires_generic_runtime_surface_closure():
    text = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    required_terms = [
        "generic runtime surfaces",
        "executor services",
        "thread pools",
        "worker pools",
        "bounded queues",
        "rejected-execution paths",
        "queue-full handling",
        "queue depth",
        "active/inflight work",
        "pool capacity",
        "rejected/shed work",
        "saturation outcome",
        "long-lived connection or streaming surfaces",
        "WebSocket",
        "SSE",
        "streaming HTTP/RPC",
        "broker streams",
        "bidirectional",
        "client streams",
        "connect/open",
        "authentication/authorization",
        "start/stop/detach/keepalive",
        "close reason family",
        "send/write failure",
        "active",
        "connections/channels/streams",
        "stream duration/outcome",
        "remains only",
        "listed as a follow-up",
        "explicitly narrowed scope",
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


def test_incident_readiness_guidance_is_present_across_all_skills():
    paths = [
        SKILLS_DIR / "otel-audit" / "SKILL.md",
        SKILLS_DIR / "otel-instrument" / "SKILL.md",
        SPLUNK_CONFIGURE,
    ]
    required_terms = [
        "customer-impact",
        "dependency",
        "freshness",
        "backpressure",
        "auth/edge",
        "capacity",
        "release/config",
    ]
    for path in paths:
        text = _read(path)
        missing = [term for term in required_terms if term not in text]
        assert not missing, f"{path} missing incident-readiness terms: {missing}"


def test_audit_places_incident_readiness_before_genai_readiness():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    report_template = audit.split("Use this template for `.observe/otel.md`:")[1]
    report_template = report_template.split("Report requirements:")[0]
    red_index = report_template.index("## RED Signals")
    incident_index = report_template.index("## Incident Readiness")
    genai_index = report_template.index("## GenAI Readiness")
    assert red_index < incident_index < genai_index


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


def test_splunk_configure_consumes_current_main_gaps_section():
    skill = _read(SPLUNK_CONFIGURE)
    required_terms = [
        "## Gaps",
        "current-main",
        "instrumentation prerequisite",
        "Instrumentation Prerequisites",
        "detector for a missing signal",
    ]
    missing = [term for term in required_terms if term not in skill]
    assert not missing


def test_audit_emits_gap_ledger_contract():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    required_terms = [
        "## Gap Ledger",
        "gap_id",
        "required_signals",
        "owner",
        "code_surface",
        "acceptance_criteria",
        "audit output is a contract",
        "not background context",
        "partial",
    ]
    missing = [term for term in required_terms if term not in audit]
    assert not missing


def test_instrument_reconciles_audit_gap_contract():
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    required_terms = [
        "Audit Gap Contract",
        "gap_id",
        "required_signals",
        "implemented_signals",
        "remaining_signals",
        "App-owned + patchable",
        "Code added + tests",
        "App-owned but unsafe/too large",
        "Explicitly split into named follow-up batch",
        "Provider/platform-owned",
        "Owner mapped with exact missing source",
        "Already covered",
        "Proven with source path and signal name",
        "cannot say",
        "covered",
        "fixed",
        "closed",
    ]
    missing = [term for term in required_terms if term not in instrument]
    assert not missing


def test_genai_token_pressure_partial_closure_contract():
    genai_reference = _read(GENAI_REF)
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    required_terms = [
        "context budget percent",
        "truncation rate",
        "token-limit errors",
        "prompt/tool schema size",
        "LLM call count per turn",
        "tool call count per turn",
        "Partial: token usage and context window added",
        "truncation, token-limit error, prompt/tool schema size, and LLM-call fanout remain missing",
    ]
    for text in (genai_reference, instrument):
        missing = [term for term in required_terms if term not in text]
        assert not missing


def test_splunk_configure_demotes_partial_gap_coverage():
    skill = _read(SPLUNK_CONFIGURE)
    required_terms = [
        "partial closure",
        "generate detectors only for implemented or proven signals",
        "Do not imply complete coverage",
        "remaining_signals",
        "Instrumentation Prerequisites",
    ]
    missing = [term for term in required_terms if term not in skill]
    assert not missing


def test_splunk_configure_no_metrics_still_reports_prerequisites():
    skill = _read(SPLUNK_CONFIGURE)
    required_terms = [
        "No metrics detected",
        "do not generate detector or",
        "Continue processing `## Gaps`",
        "`## Incident Readiness`",
        ".observe/detectors.md",
        "alert coverage matrix",
    ]
    missing = [term for term in required_terms if term not in skill]
    assert not missing


def test_splunk_configure_consumes_incident_readiness_section():
    skill = _read(SPLUNK_CONFIGURE)
    required_terms = [
        "## Incident Readiness",
        "incident-readiness areas become instrumentation",
        "For every incident-readiness area",
        "unless equivalent metrics are present",
        "Do not generate detectors",
    ]
    missing = [term for term in required_terms if term not in skill]
    assert not missing


def test_splunk_configure_covers_dependency_release_and_capacity_mttd_signals():
    skill = _read(SPLUNK_CONFIGURE)
    classification = _read(SPLUNK_CONFIGURE_REFS / "detector-classification.md")
    required_terms = [
        "endpoint health",
        "target health",
        "rate-limit",
        "unhealthy target",
        "disk",
        "filesystem",
        "desired-vs-healthy",
        "startup/readiness/healthcheck",
        "deployment.region",
        "deployment.platform",
        "container.image.tag",
        "artifact version",
    ]
    for text in (skill, classification):
        missing = [term for term in required_terms if term not in text]
        assert not missing


def test_splunk_configure_dashboard_signalflow_guardrails():
    skill = _read(SPLUNK_CONFIGURE)
    templates = _read(SPLUNK_CONFIGURE_REFS / "terraform-templates.md")
    required_skill_terms = [
        "Keep the Splunk Observability Cloud API `realm` variable separate",
        "Do not use `var.realm` as a SignalFlow filter",
        "`sfx_realm`",
        "dashboard variables",
        "Before writing chart `program_text`",
        "pre-aggregated percentile metrics",
        "do not average",
        "value sanity check",
        "apply_if_exist = true",
        "stale `configId` parameter",
        "mixed-unit signals",
        "separate panels",
        "provider-derived",
        "stale/unowned evidence",
        "source-backed coverage",
        "cumulative counters",
        "`rollup='rate'`",
    ]
    required_template_terms = [
        "Do not equate the provider/API `realm` variable with telemetry",
        "`sfx_realm`",
        "dashboard variables",
        "apply_if_exist = true",
        "apply_if_exist = false",
        "pre-aggregated",
        "do not average",
        "known-traffic window",
        "unverified in `.observe/dashboards.md`",
        "stale `configId` parameter",
        "mixed-unit signals",
        "separate panels",
        "provider-derived",
        "stale/unowned evidence",
        "source-backed emitter",
        "cumulative timers",
        "`rollup='rate'`",
    ]
    assert not [term for term in required_skill_terms if term not in skill]
    assert not [term for term in required_template_terms if term not in templates]
    assert "e.g. us1, eu0, lab0" not in skill
    assert "e.g. us1, eu0, lab0" not in templates


def test_splunk_configure_preserves_runtime_cpu_coverage():
    skill = _read(SPLUNK_CONFIGURE)
    classification = _read(SPLUNK_CONFIGURE_REFS / "detector-classification.md")
    templates = _read(SPLUNK_CONFIGURE_REFS / "terraform-templates.md")
    required_terms = [
        "source-backed CPU utilization",
        "CPU saturation detector",
        "Do not use thread count",
        "cumulative CPU time",
        "diagnostic rate",
        "`rollup='rate'`",
        "normalized CPU utilization",
    ]
    for text in (skill, classification, templates):
        missing = [term for term in required_terms if term not in text]
        assert not missing


def test_audit_keeps_current_main_report_contract():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    unmerged_report_terms = [
        "## Signal Flow",
        "### Component Flow Map",
        "### Step-by-Step Signal Coverage",
        "| Priority | Area | Gap | User Impact | Fix | Instrument Mode |",
    ]
    present = [term for term in unmerged_report_terms if term in audit]
    assert not present


def test_splunk_configure_prioritizes_genai_before_generic_red():
    classification = _read(SPLUNK_CONFIGURE_REFS / "detector-classification.md")
    assert "Classify GenAI metrics before generic latency" in classification
    assert "metric name starts with \"gen_ai.\"" in classification
    assert "gen_ai.client.operation.duration" in classification


def test_genai_classification_does_not_treat_generic_model_terms_as_genai():
    classification = _read(SPLUNK_CONFIGURE_REFS / "detector-classification.md")
    assert "Do not classify generic" in classification
    for term in ["`model`", "`workflow`", "`tool`", "`config`", "`canary`"]:
        assert term in classification
    assert "require explicit GenAI context" in classification
    assert "The metric has GenAI context and the metric name contains one of:" in classification


def test_genai_guidance_stays_generic():
    paths = [
        INCIDENT_REF,
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
