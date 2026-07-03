"""Deterministic checks for GenAI readiness skill guidance."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
GENAI_REF = SKILLS_DIR / "references" / "genai-readiness.md"
REPORT_FLOW = SKILLS_DIR / "references" / "report-flow-contract.md"
OTEL_VERIFY = SKILLS_DIR / "otel-verify" / "SKILL.md"
SPLUNK_CONFIGURE = SKILLS_DIR / "splunk-configure" / "SKILL.md"
SPLUNK_CONFIGURE_REFS = SKILLS_DIR / "splunk-configure" / "references"
SPLUNK_SYNC = SKILLS_DIR / "splunk-sync" / "SKILL.md"
SPLUNK_SYNC_REFS = SKILLS_DIR / "splunk-sync" / "references"
# splunk-sync was renamed to splunk-detector-publish; the full detector contract
# now lives in the canonical skill and splunk-sync is a deprecation stub.
SPLUNK_DETECTOR_PUBLISH = SKILLS_DIR / "splunk-detector-publish" / "SKILL.md"
SPLUNK_DETECTOR_PUBLISH_REFS = SKILLS_DIR / "splunk-detector-publish" / "references"


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
        "gen_ai.evaluation.result",
        "gen_ai.evaluation.name",
        "gen_ai.evaluation.score.value",
        "gen_ai.evaluation.score.label",
        "invoke_agent",
        "invoke_workflow",
        "plan",
        "execute_tool",
        "retrieval",
        "search_memory",
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


def test_genai_reference_requires_span_first_trace_explorer_contract():
    text = _read(GENAI_REF)
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    reference_required_terms = [
        "Obstudio GenAI Trace UI Contract",
        "span-first",
        "selected-trace summary",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "gen_ai.usage.total_tokens",
        "chat span",
        "workflow span",
        "first_event_timeout",
        "stream close reason family",
    ]
    instrument_required_terms = [
        "local span-first trace explorers such as Obstudio",
        "metrics alone are not enough",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "gen_ai.usage.total_tokens",
        "first_event_timeout",
        "send/write failure",
    ]
    missing = [term for term in reference_required_terms if term not in text]
    assert not missing
    missing = [term for term in instrument_required_terms if term not in instrument]
    assert not missing


def test_genai_skills_require_model_call_lifecycle_spans():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    reference = _read(GENAI_REF)
    required_terms = [
        "LLM Inference Lifecycle Contract",
        "model-call lifecycle",
        "on_chat_model_start",
        "on_chat_model_end",
        "on_chat_model_error",
        "final usage",
        "chat",
        "generate_content",
        "text_completion",
        "gen_ai.operation.name",
        "gen_ai.request.model",
        "gen_ai.response.model",
        "workflow-level token accounting",
        "remaining_signals",
    ]
    for text in (reference, audit, instrument):
        missing = [term for term in required_terms if term not in text]
        assert not missing


def test_genai_skills_require_single_canonical_span_source():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    reference = _read(GENAI_REF)
    shared_terms = [
        "Single-Source GenAI Span Contract",
        "framework/vendor",
        "provider SDK hooks",
        "auto-instrumentors",
        "one canonical GenAI span source per logical operation",
        "one GenAI node per logical operation",
        "wrapper",
        "expected LLM",
        "tool counts",
        "stable model/tool names",
        "parent shape",
    ]
    for raw_text in (reference, audit, instrument):
        text = " ".join(raw_text.split())
        missing = [term for term in shared_terms if term not in text]
        assert not missing

    instrument_only_terms = [
        "do not create duplicate app-owned",
        "disable, opt out of, or suppress overlapping framework/vendor GenAI instrumentation",
        "discovered runtime mechanism",
        "Do not hard-code this decision to one framework",
        "Keep HTTP/database/runtime auto-instrumentation",
    ]
    instrument_normalized = " ".join(instrument.split())
    missing = [
        term for term in instrument_only_terms if term not in instrument_normalized
    ]
    assert not missing


def test_genai_skills_require_pre_bootstrap_suppression_for_app_owned_spans():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    reference = _read(GENAI_REF)
    shared_terms = [
        "opentelemetry-instrument",
        "auto-instrumentation bootstrap",
        "launch environment",
        "before the bootstrap",
        "App module code that mutates environment variables",
        "not sufficient proof",
        "framework hooks may already be registered",
        "Makefile targets",
        "service runner scripts",
        "Docker or Helm env",
        "VS Code launch configs",
        "generated env scripts",
    ]
    for raw_text in (reference, audit, instrument):
        text = " ".join(raw_text.split())
        missing = [term for term in shared_terms if term not in text]
        assert not missing


def test_genai_nested_reference_paths_resolve():
    nested_reference = SKILLS_DIR / "otel-instrument" / "references" / "signal-mapping-guide.md"
    text = _read(nested_reference)
    required_path = "../../references/genai-readiness.md"
    assert required_path in text
    assert (nested_reference.parent / required_path).resolve() == GENAI_REF.resolve()

    configure_template = SPLUNK_CONFIGURE_REFS / "terraform-templates.md"
    configure_text = _read(configure_template)
    configure_required_path = "detector-classification.md"
    assert configure_required_path in configure_text
    assert (configure_template.parent / configure_required_path).resolve() == (
        SPLUNK_CONFIGURE_REFS / "detector-classification.md"
    ).resolve()
    assert "references/detector-classification.md" not in configure_text


def test_genai_skills_preserve_stable_workflow_identity():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    reference = _read(GENAI_REF)
    shared_terms = [
        "stable business workflow identity",
        "constants",
        "workflow registrations",
        "telemetry event names",
        "prior trace names",
        "Do not invent names from HTTP routes",
        "session-derived",
        "assistant_v3_turn",
        "assistant_v3_session_turn",
        "POST /v2/assistant/sessions",
    ]
    for raw_text in (reference, audit, instrument):
        text = " ".join(raw_text.split())
        missing = [term for term in shared_terms if term not in text]
        assert not missing


def test_genai_skills_preserve_stable_agent_identity():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    reference = _read(GENAI_REF)
    shared_terms = [
        "stable agent identity",
        "framework agent names",
        "agent factory names",
        "registration names",
        "callback owner names",
        "prior trace names",
        "DeepAgents",
        "deepagents",
        "assistant_v3_agent",
        "generic service-derived",
    ]
    for raw_text in (reference, audit, instrument):
        text = " ".join(raw_text.split())
        missing = [term for term in shared_terms if term not in text]
        assert not missing


def test_genai_skills_require_parent_context_and_workflow_aggregates():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    reference = _read(GENAI_REF)
    required_terms = [
        "owning workflow/agent context",
        "generic HTTP root span",
        "generic server span",
        "siblings of the workflow",
        "workflow -> chat",
        "workflow -> execute_tool",
        "parent-context",
        "gen_ai.usage.input_tokens",
        "assistant.llm.calls",
        "assistant.tool.calls",
        "most specific owning GenAI span",
        "remaining_signals",
    ]
    for text in (reference, audit, instrument):
        missing = [term for term in required_terms if term not in text]
        assert not missing


def test_genai_skills_require_helper_span_context_capture():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    reference = _read(GENAI_REF)
    required_terms = [
        "long-lived helper/setup spans",
        "memory store",
        "checkpointer",
        "database session",
        "stream-writer",
        "helper spans must not become the parent",
        "workflow/agent context before opening helper spans",
        "event-derived `chat` and `execute_tool` spans",
        "write aggregate counters to the workflow span",
        "whichever current span is active",
        "async generator",
        "create_task",
        "anext",
        "task handoff",
        "yield/task boundaries",
        "span/context handle",
        "callback/event translator",
    ]
    for raw_text in (reference, audit, instrument):
        text = " ".join(raw_text.split())
        missing = [term for term in required_terms if term not in text]
        assert not missing


def test_genai_skills_require_immutable_context_handoff():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    reference = _read(GENAI_REF)
    required_terms = [
        "immutable/frozen",
        "do not mutate",
        "Treat a carrier as immutable/frozen when source evidence shows",
        "readonly declarations",
        "record/value types",
        "no mutation API",
        "existing code constructs new copies",
        "idiomatic copy/replacement",
        "dataclasses.replace",
        "attrs.evolve",
        "model_copy(update=...)",
        "Java records",
        "TypeScript object spread",
        "structuredClone",
        "plain-data carriers",
        "live OTel `Context` or `Span` handles",
        "Readonly<T>",
        "Go value copies",
        "framework's request clone/with-context API",
        "If no safe copy path exists",
        "invocation-scoped sidecar context",
        "cleared after cleanup",
        "Do not key sidecar context by raw user, tenant, session, request, or trace IDs",
        "explicit static proof",
        "parent context is passed",
        "original immutable input remains unchanged",
        "FrozenInstanceError",
    ]
    for raw_text in (reference, audit, instrument):
        text = " ".join(raw_text.split())
        missing = [term for term in required_terms if term not in text]
        assert not missing


def test_genai_reference_requires_incident_evidence_mode():
    text = _read(GENAI_REF)
    required_terms = [
        "Incident-Evidence Mode",
        "incident class -> failure mechanism -> repo/service owner -> code surface -> signal -> MTTD impact -> remaining owner",
        "failure mechanism",
        "MTTD-improving",
        "localization-only",
        "provider/model gateway",
        "tool/session/stream lifecycle including MCP when present",
        "Do not call GenAI instrumentation complete",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_genai_reference_requires_current_semconv_source_contract():
    text = _read(GENAI_REF)
    required_terms = [
        "GenAI Semconv Source Contract",
        "open-telemetry/semantic-conventions-genai",
        "live official docs",
        "bundled semconv snapshot",
        "repo/branch-or-commit/docs/date/live-or-snapshot",
        "model spans",
        "agent spans",
        "metrics docs",
        "GenAI events",
        "MCP docs",
        "provider-specific docs only when that provider is detected",
        "surface -> official operation -> required attrs -> recommended attrs ->",
        "metrics/events -> implemented -> proven existing -> remaining",
        "Local operation and metric lists are examples only",
        "official docs win",
        "privacy/cardinality rules remain enforced",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_genai_reference_requires_ai_pathway_surface_patterns():
    text = _read(GENAI_REF)
    required_terms = [
        "Required GenAI Surface Patterns",
        "Provider/model gateway",
        "Agent/workflow orchestration",
        "Tool/function execution and AI-owned sessions/streams",
        "RAG/retrieval",
        "Token/context/cost pressure",
        "Safety/policy",
        "AI runtime state overlay",
        "Model/config compatibility",
        "AI-path readiness overlays",
        "streaming first chunk",
        "last-ingest age",
        "expected-vs-running model or AI config state",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_genai_reference_covers_evaluation_quality_contract():
    text = _read(GENAI_REF)
    required_terms = [
        "Evaluation Quality Contract",
        "gen_ai.evaluation.result",
        "gen_ai.evaluation.name",
        "gen_ai.evaluation.score.value",
        "gen_ai.evaluation.score.label",
        "gen_ai.evaluation.explanation",
        "gen_ai.response.id",
        "score distribution",
        "pass/fail",
        "evaluator",
        "no-data",
        "freshness",
        "Do not mark evaluation quality complete",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_genai_reference_covers_content_governance_contract():
    text = _read(GENAI_REF)
    required_terms = [
        "Content Capture Governance Contract",
        "gen_ai.input.messages",
        "gen_ai.output.messages",
        "gen_ai.system_instructions",
        "gen_ai.retrieval.documents",
        "gen_ai.retrieval.query.text",
        "gen_ai.tool.definitions",
        "gen_ai.tool.call.arguments",
        "disabled",
        "metadata-only",
        "redacted",
        "full-content",
        "opt-in config",
        "redaction/truncation hook",
        "retention/access owner",
        "Never",
        "metric dimensions",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_genai_reference_covers_memory_framework_and_cost_contracts():
    text = _read(GENAI_REF)
    required_terms = [
        "Memory/context and AI runtime state overlay",
        "create_memory_store",
        "search_memory",
        "create_memory",
        "update_memory",
        "upsert_memory",
        "delete_memory",
        "Framework Bridge Contract",
        "LangChain",
        "LangGraph",
        "CrewAI",
        "Strands",
        "LlamaIndex",
        "OpenInference",
        "TraceLoop/OpenLLMetry",
        "ADOT",
        "semconv source of usage",
        "accurate pricing map",
        "owner-map the exact source",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_genai_reference_requires_tool_stream_auth_and_send_failure():
    text = _read(GENAI_REF)
    required_terms = [
        "authentication/authorization",
        "invalid-token or permission failure outcome",
        "active sessions/streams",
        "close reason family",
        "stream duration/outcome",
        "send/write failure",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_genai_reference_blocks_mcp_high_cardinality_dimensions():
    text = _read(GENAI_REF)
    required_terms = [
        "MCP/JSON-RPC request IDs",
        "raw request IDs",
        "session IDs",
        "tool arguments",
        "not safe metric dimensions",
        "stable tool or method names",
        "unknown_method",
        "unsupported_method",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_genai_reference_covers_incident_discovered_ai_pathways():
    text = _read(GENAI_REF)
    required_terms = [
        "prompt/response parsing failures",
        "AI-derived data freshness",
        "model/prompt/tool-schema compatibility",
        "synthetic/canary workflow-check blind spots",
        "Prompt/response assembly",
        "AI-derived data freshness",
        "evaluation, feedback, export",
        "prompt/cache population",
        "Model/config compatibility",
        "AI-path readiness overlays",
        "fallback target readiness",
        "detector reliability evidence",
        "missed, flapping, auto-resolved, or no-data alerts",
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
        assert "GenAI Semconv Source Contract" in text
        assert "live-or-snapshot provenance" in text
        assert "semconv closure matrix" in text


def test_instrument_requires_genai_incident_gap_closure():
    text = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    required_terms = [
        "GenAI incident-evidence mode",
        "AI pathway failure mechanism",
        "provider/model gateway",
        "tool/function execution",
        "MCP when present",
        "retrieval",
        "streaming",
        "token/context",
        "prompt/response",
        "safety/policy",
        "AI-derived data",
        "model/config rollout",
        "AI-owned cache/session",
        "GenAI Readiness Contract",
        "surface -> required_signals -> implemented_signals -> tests",
        "Do not call GenAI instrumentation complete",
        "MTTD-improving",
        "localization-only",
        "remaining",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_genai_readiness_contract_does_not_require_opaque_ids():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    configure = _read(SPLUNK_CONFIGURE)
    audit_normalized = " ".join(audit.split())
    instrument_normalized = " ".join(instrument.split())
    required_audit_terms = [
        "GenAI readiness contract",
        "complete instrumentation contract",
        "surface`, `evidence`, `current_status`, `required_signals`",
        "the surface name as the human-facing identifier",
    ]
    required_instrument_terms = [
        "GenAI Readiness Contract",
        "Parse each row by human-readable `surface`",
        "Use the surface name as the human-facing identifier",
        "surface -> required_signals -> implemented_signals -> tests",
    ]
    assert not [term for term in required_audit_terms if term not in audit_normalized]
    assert not [
        term for term in required_instrument_terms if term not in instrument_normalized
    ]
    assert "every independently actionable surface row" in configure
    assert "| Surface | Audit Status | Missing Signal |" in configure


def test_audit_requires_single_deterministic_gap_section():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    normalized = " ".join(audit.split())
    required_terms = [
        "Deterministic gap section contract",
        "exactly one top-level gap section, named `## Gaps`",
        "Record GenAI detail in `## GenAI Readiness` table rows",
        "point back to the human-readable readiness surface name",
    ]
    assert not [term for term in required_terms if term not in normalized]


def test_assistant_v3_framework_bridge_eval_covers_duplicate_span_risk():
    fixture = REPO_ROOT / "evals" / "python" / "assistant-v3-framework-bridge-demo"
    files = [
        fixture / "app.py",
        fixture / "Makefile",
        fixture / "pyproject.toml",
        fixture / "eval" / "qual" / "audit.json",
        fixture / "eval" / "qual" / "instrument.json",
    ]
    for file in files:
        assert file.exists(), f"missing assistant_v3 framework fixture file: {file}"

    combined = "\n".join(_read(file) for file in files)
    required_terms = [
        "assistant_v3_turn",
        "deepagents",
        "opentelemetry-instrument",
        "langchain",
        "splunk-otel-instrumentation-langchain",
        "framework_shadow_nodes",
        "simulate_framework_shadow_nodes",
        "one canonical GenAI span source",
        "before opentelemetry-instrument bootstraps",
        "OTEL_PYTHON_DISABLED_INSTRUMENTATIONS",
        "POST /v2/assistant/sessions",
        "must not become the GenAI workflow card",
        "LangGraph",
        "step nodes",
    ]
    assert not [term for term in required_terms if term not in combined]


def test_instrument_requires_eval_trace_events_not_metrics_only():
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    reference = _read(GENAI_REF)
    required_instrument_terms = [
        "For evaluation quality surfaces",
        "evaluator classes",
        "scoring functions",
        "LLM-as-judge",
        "`EvalScore` models",
        "faithfulness/similarity/expectation metrics",
        "Metrics-only coverage does not satisfy selected-trace eval visibility",
        "`gen_ai.evaluation.result` on the relevant workflow/evaluation span",
        "`gen_ai.evaluation.score.value`",
        "`gen_ai.evaluation.score.label`",
        "span-level eval event",
        "keep the evaluation quality surface partial",
    ]
    required_reference_terms = [
        "counters/histograms without",
        "`gen_ai.evaluation.result`",
        "Metrics-only coverage does not satisfy selected-trace eval visibility",
    ]
    assert not [term for term in required_instrument_terms if term not in instrument]
    assert not [term for term in required_reference_terms if term not in reference]


def test_audit_requires_genai_incident_surface_mapping():
    text = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    required_terms = [
        "GenAI incident-evidence mode",
        "failure mechanism",
        "provider/model gateway",
        "tool/function execution",
        "MCP when present",
        "retrieval/RAG",
        "streaming",
        "token/context",
        "prompt/response",
        "safety/policy",
        "AI-derived data",
        "model/config rollout",
        "AI-owned cache/session",
        "AI-path synthetic/canary checks",
        "AI-derived data jobs",
        "incident class -> failure mechanism -> repo/service owner -> code surface ->",
        "MTTD-improving",
        "localization-only",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_audit_and_instrument_cover_genai_deployment_and_data_job_failures():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    required_terms = [
        "prompt/response assembly",
        "AI-derived data",
        "synthetic/canary",
        "model/config compatibility",
        "detector reliability evidence",
        "missed, flapping, auto-resolved, or no-data alerts",
        "$splunk-configure",
        "token/context pressure",
        "response parse failure",
        "prompt/tool schema version",
        "expected-vs-running model/config",
    ]
    for text in (audit, instrument):
        missing = [term for term in required_terms if term not in text]
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


def test_instrument_requires_token_pressure_residuals_in_final_closure():
    text = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    required_terms = [
        "broadly asks for GenAI readiness",
        "prompt/tool schema size or safe proxy",
        "detector-ready proxy metric",
        "schema JSON length bucket",
        "schema field count",
        "Span attributes like prompt template version",
        "do not close prompt/tool schema size pressure",
        "remaining_signals",
        "For every GenAI instrumentation run, include a concise closure summary",
        "For GenAI work without a source audit",
        "Remaining signals: none",
        "Final summaries, PR descriptions, and audit updates must not omit",
        "LLM-call fanout",
        "tool-call fanout",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_genai_reference_requires_schema_pressure_metric_or_remaining_signal():
    text = _read(GENAI_REF)
    required_terms = [
        "Prompt/tool schema pressure is detector-ready only when it is implemented or",
        "metric or equivalent detector source",
        "schema JSON length bucket",
        "schema field count",
        "prompt template length bucket",
        "Span attributes such as prompt template version",
        "do not close prompt/tool schema size pressure",
        "keep prompt/tool schema size in `remaining_signals`",
        "Every GenAI instrumentation result should include a closure summary",
        "Remaining signals: none",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_audit_requires_demo_clients_and_mcp_auth_outcomes():
    text = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    required_terms = [
        "Traffic and readiness clients",
        "demo, load, eval, or replay scripts",
        "load_demo.py",
        "authentication/authorization result",
        "invalid-token or permission failure outcome",
        "send/write failure",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_audit_distinguishes_demo_env_from_complete_genai_telemetry_setup():
    text = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    required_terms = [
        "demo-only environment hints",
        "OTEL_SERVICE_NAME",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "SDK setup",
        "exporter setup",
        "resource attributes",
        "incomplete resource/exporter configuration",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_instrument_requires_mcp_safe_dimensions_send_failure_and_tests():
    text = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    required_terms = [
        "Never record JSON-RPC request IDs",
        "known route/tool registration",
        "unknown_method",
        "send/write failure signal",
        "GenAI spans alone do not satisfy detector-ready",
        "tool-specific duration histogram",
        "tool error/timeout counter",
        "owner-map the missing source explicitly",
        "focused repo-native test",
        "Do not finalize with a compile",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_audit_places_genai_readiness_before_gaps_when_owned():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    assert "Use this template for `.observe/otel.md`:" in audit
    report_template = audit.split("Use this template for `.observe/otel.md`:")[1]
    assert "Report requirements:" in report_template
    report_template = report_template.split("Report requirements:")[0]
    assert "## Current Instrumentation" in report_template
    assert "## GenAI Readiness" in report_template
    assert "## Gaps" in report_template
    current_index = report_template.index("## Current Instrumentation")
    genai_index = report_template.index("## GenAI Readiness")
    gaps_index = report_template.index("## Gaps")
    assert current_index < genai_index < gaps_index


def test_audit_requires_reader_first_current_state_baseline():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    audit_normalized = " ".join(audit.split())
    assert "Use this template for `.observe/otel.md`:" in audit
    report_template = audit.split("Use this template for `.observe/otel.md`:")[1]
    assert "Report requirements:" in report_template
    report_template = report_template.split("Report requirements:")[0]

    evidence_index = report_template.index("## Audit Evidence")
    current_index = report_template.index("## Current Instrumentation")
    gaps_index = report_template.index("## Gaps")
    verification_index = report_template.index("## Verification Plan")
    assert evidence_index < current_index < gaps_index < verification_index

    required_terms = [
        "**GenAI ownership detected:** Yes | No",
        "| GenAI ownership |",
        "Always emit `**GenAI ownership detected:** Yes` or `No`",
        "Use only the top-level sections shown in the report template",
        "validator rejects additional top-level sections",
        "python3 scripts/validate_audit_report.py .observe/otel.md",
    ]
    missing = [term for term in required_terms if term not in audit_normalized]
    assert not missing


def test_audit_read_only_scope_still_writes_the_report_artifact():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    required_terms = [
        "Read-only for application code",
        "writes `.observe/otel.md`",
        "does not modify service code",
        "Write the report to `.observe/otel.md`",
    ]
    missing = [term for term in required_terms if term not in audit]
    assert not missing


def test_audit_keeps_genai_readiness_surfaces_independently_actionable():
    audit = " ".join(_read(SKILLS_DIR / "otel-audit" / "SKILL.md").split())
    required_terms = [
        "each telemetry-distinct owned surface, write one separate readiness row",
        "Keep workflow, provider/model, tool/function, token/context, stream/session",
        "distinct surfaces independently actionable for instrumentation closure",
    ]
    missing = [term for term in required_terms if term not in audit]
    assert not missing


def test_instrument_requires_signals_changed_and_gap_closure():
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    required_terms = [
        "## Signals Changed",
        "## Audit Gap Closure",
        "## GenAI Readiness Closure",
        "`Signals Changed` is the implementation-change inventory",
        "| Signal type | Added | Modified | Removed | Evidence | Verification status |",
        "Do not claim a removal unless the previous report or git diff proves",
        "Use one row per prioritized audit gap",
        "Derive the report-level `**Result:**` from both closure tables",
        "python3 scripts/validate_gap_closure.py",
    ]
    missing = [term for term in required_terms if term not in instrument]
    assert not missing


def test_instrument_requires_route_aware_http_proof_and_source_owned_closure():
    instrument = " ".join(
        _read(SKILLS_DIR / "otel-instrument" / "SKILL.md").split()
    )
    required_terms = [
        "route-aware server spans are required",
        "low-cardinality route pattern",
        "do not emit duplicate server spans",
        "When no source audit exists, do not create `## GenAI Readiness Closure`",
        "do not create a `GenAI Readiness Closure` table without source-audit rows",
    ]
    missing = [term for term in required_terms if term not in instrument]
    assert not missing


def test_instrument_requires_attempt_or_exact_full_runtime_blocker():
    instrument = " ".join(
        _read(SKILLS_DIR / "otel-instrument" / "SKILL.md").split()
    )
    required_terms = [
        "`Not run` or `no collector was run` alone is not an acceptable blocker",
        "record either the executed command and direct result or the concrete unavailable runtime",
        "Do not finalize while a safe local profile exists",
    ]
    missing = [term for term in required_terms if term not in instrument]
    assert not missing


def test_verify_requires_reader_first_individual_results():
    verify = _read(OTEL_VERIFY)
    report_flow = _read(REPORT_FLOW)
    required_terms = [
        "## What Changed",
        "## Tested And Working",
        "## Not Working Or Not Proven",
        "## Proof",
        "**Individual result:** <working>/<total> working",
    ]
    for text in (verify, report_flow):
        missing = [term for term in required_terms if term not in text]
        assert not missing
    assert "validate_reader_report.py" in verify


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
        "genai-memory-context",
        "genai-evaluation-quality",
        "genai-content-governance",
        "genai-cost",
    ]
    for text in (skill, classification, templates):
        missing = [term for term in required_terms if term not in text]
        assert not missing


def test_splunk_configure_summary_lists_all_genai_display_categories():
    skill = _read(SPLUNK_CONFIGURE)
    required_display_terms = [
        "GenAI Latency",
        "GenAI Token Pressure",
        "GenAI Provider",
        "GenAI Tool",
        "GenAI Model Config",
        "GenAI Workflow Fanout",
        "GenAI Retrieval",
        "GenAI Memory Context",
        "GenAI Evaluation Quality",
        "GenAI Content Governance",
        "GenAI Cost",
    ]
    for term in required_display_terms:
        assert skill.count(term) >= 2


def test_splunk_configure_consumes_all_genai_readiness_rows():
    skill = _read(SPLUNK_CONFIGURE)
    required_terms = [
        "GenAI Readiness",
        "every independently actionable surface row",
        "provider/model",
        "workflow/agent",
        "tool/function",
        "token/context",
        "stream/session",
        "retrieval",
        "memory/context",
        "evaluation/data export",
        "content governance",
        "cost ownership",
        "privacy/cardinality",
        "Do not merge distinct readiness surfaces",
        "Missing or partial GenAI areas become instrumentation prerequisites",
    ]
    missing = [term for term in required_terms if term not in skill]
    assert not missing


def test_splunk_configure_prioritizes_genai_before_generic_categories():
    classification = _read(SPLUNK_CONFIGURE_REFS / "detector-classification.md")
    assert "Classify GenAI metrics before generic latency" in classification
    assert "metric name starts with \"gen_ai.\"" in classification
    assert "gen_ai.client.operation.duration" in classification


def test_genai_classification_does_not_treat_generic_model_terms_as_genai():
    classification = _read(SPLUNK_CONFIGURE_REFS / "detector-classification.md")
    configure = _read(SPLUNK_CONFIGURE)
    assert "Do not classify generic" in classification
    for term in [
        "`model`",
        "`workflow`",
        "`tool`",
        "`config`",
        "`canary`",
        "`token`",
        "`session`",
        "`chat`",
        "`memory`",
        "`context`",
        "`evaluation`",
        "`evaluator`",
        "`quality`",
        "`cost`",
        "`billing`",
    ]:
        assert term in classification
        assert term in configure
    assert "require explicit GenAI context" in classification
    assert "The metric has GenAI context and the metric name contains one of:" in classification
    assert "Those generic words require audit evidence" in classification


def test_genai_audit_and_instrument_require_new_gap_closure_surfaces():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    required_audit_terms = [
        "memory/context",
        "evaluation quality",
        "content governance",
        "framework bridge",
        "cost ownership",
        "gen_ai.evaluation.result",
        "evaluation score distribution",
        "content capture mode/redaction/access owner",
        "owner-mapped billing source",
    ]
    required_instrument_terms = [
        "memory/context operations",
        "evaluation quality",
        "content governance",
        "framework bridge",
        "app-computed cost",
        "gen_ai.evaluation.result",
        "gen_ai.evaluation.score.value",
        "gen_ai.input.messages",
        "gen_ai.retrieval.documents",
        "gen_ai.tool.call.arguments",
        "search_memory",
        "accurate pricing map",
        "owner-map the billing or",
    ]
    assert not [term for term in required_audit_terms if term not in audit]
    assert not [term for term in required_instrument_terms if term not in instrument]


def test_genai_guidance_stays_generic():
    paths = [
        GENAI_REF,
        SKILLS_DIR / "otel-audit" / "SKILL.md",
        SKILLS_DIR / "otel-instrument" / "SKILL.md",
        SPLUNK_CONFIGURE,
        SPLUNK_CONFIGURE_REFS / "detector-classification.md",
        SPLUNK_CONFIGURE_REFS / "terraform-templates.md",
    ]
    # Keep skill guidance provider-neutral. Concrete provider names belong in
    # app-specific audits or examples, not reusable skill instructions.
    blocked_terms = [
        "IR-",
        "guildcore",
        "Guildcore",
        "guild.ai",
        "sb-rest",
        "signalboost",
        "signalboost-rest",
        "sbrest",
        "metadata-server",
        "matt-server",
        "Matt",
        "meatballs",
        "Meatballs",
        "AI Assistant",
        "AI assistant",
        "Azure OpenAI",
        "Gemini",
        "Vertex AI",
        "Anthropic",
        "Bedrock",
        "eval or feedback",
        "eval/feedback",
        "prompt-book",
        "checkout",
        "missing report output",
        "active-node",
        "active node",
        "Decision or delivery workflow",
        "decision or delivery workflow",
        "workflow delivery/evaluation",
    ]
    for path in paths:
        text = _read(path)
        bad = [term for term in blocked_terms if term in text]
        assert not bad, f"{path} contains non-generic terms: {bad}"


# ---------------------------------------------------------------------------
# splunk-detector-publish skill (canonical; formerly splunk-sync)
#
# The full detector-publish contract lives in skills/splunk-detector-publish.
# skills/splunk-sync is a backward-compatibility deprecation stub that redirects
# to it, so the full-contract checks below target the canonical skill and the
# alias only gets dedicated redirect/deprecation checks further down.
# ---------------------------------------------------------------------------


def test_splunk_detector_publish_skill_exists():
    assert SPLUNK_DETECTOR_PUBLISH.exists(), (
        "skills/splunk-detector-publish/SKILL.md not found"
    )
    assert (SPLUNK_DETECTOR_PUBLISH_REFS / "coverage-model.md").exists(), (
        "skills/splunk-detector-publish/references/coverage-model.md not found"
    )


def test_splunk_detector_publish_coverage_model_defines_all_statuses():
    text = _read(SPLUNK_DETECTOR_PUBLISH_REFS / "coverage-model.md")
    for status in ("COVERED", "GAP", "UNCERTAIN"):
        assert status in text, f"coverage-model.md missing status: {status}"


def test_splunk_detector_publish_coverage_model_uses_camel_case_detector_origin():
    text = _read(SPLUNK_DETECTOR_PUBLISH_REFS / "coverage-model.md")
    assert "detectorOrigin" in text, "coverage-model.md must use camelCase detectorOrigin"
    assert "detector_origin" not in text, (
        "coverage-model.md must not use snake_case detector_origin"
    )


def test_splunk_detector_publish_coverage_model_treats_autodetect_as_advisory_only():
    text = _read(SPLUNK_DETECTOR_PUBLISH_REFS / "coverage-model.md")
    assert "AutoDetect" in text
    # Advisory — never auto-covers a local spec
    assert "advisory" in text.lower()
    assert "never" in text.lower()


def test_splunk_detector_publish_skill_reads_terraform_detectors_tf():
    text = _read(SPLUNK_DETECTOR_PUBLISH)
    assert "detectors.tf" in text, "SKILL.md must reference detectors.tf parsing"
    assert "program_text" in text or "programText" in text, (
        "SKILL.md must reference programText/program_text field"
    )


def test_splunk_detector_publish_skill_requires_service_filter_for_covered():
    skill = _read(SPLUNK_DETECTOR_PUBLISH)
    coverage = _read(SPLUNK_DETECTOR_PUBLISH_REFS / "coverage-model.md")
    for text in (skill, coverage):
        assert "service.name" in text, "Must reference service.name filter for COVERED classification"
        assert "sf_service" in text, "Must reference sf_service as equivalent filter key"


def test_splunk_detector_publish_skill_only_skips_http_500():
    text = _read(SPLUNK_DETECTOR_PUBLISH)
    # The skill must mention 500 as the only skippable error
    assert "500" in text, "SKILL.md must document skip-on-500 behavior"
    # Must not suggest swallowing all errors (bare except-all patterns)
    assert "except Exception" not in text, (
        "SKILL.md must not use bare except Exception — only HTTPError 500 should be skipped"
    )


def test_splunk_detector_publish_skill_requires_detector_sync_md_output():
    text = _read(SPLUNK_DETECTOR_PUBLISH)
    assert "detector-sync.md" in text, (
        "SKILL.md must require writing .observe/detector-sync.md as the resume ledger"
    )


def test_splunk_detector_publish_skill_requires_confirmation_before_create():
    text = _read(SPLUNK_DETECTOR_PUBLISH)
    # The skill must gate creates on user confirmation
    assert "confirm" in text.lower() or "confirmation" in text.lower(), (
        "SKILL.md must require explicit user confirmation before creating detectors"
    )
    # There is no server-side if_not_exists flag on POST /v2/detector; idempotency
    # comes from diff-before-create plus 409-conflict tolerance. Assert that model.
    coverage = _read(SPLUNK_DETECTOR_PUBLISH_REFS / "coverage-model.md")
    combined = text + "\n" + coverage
    assert "409" in combined, (
        "Skill/coverage model must document 409-conflict tolerance for idempotency"
    )
    assert "if_not_exists" not in text, (
        "SKILL.md must not claim an if_not_exists flag — the Splunk API has none; "
        "idempotency is diff-before-create + 409 tolerance"
    )


def test_splunk_detector_publish_skill_normalizes_program_text_before_create():
    text = _read(SPLUNK_DETECTOR_PUBLISH)
    # Heredoc dedent: <<-EOF leading whitespace must be stripped or Splunk 400s.
    assert "dedent" in text.lower(), (
        "SKILL.md must require dedenting the <<-EOF heredoc before POSTing program_text"
    )
    assert "<<-EOF" in text or "<<-eof" in text.lower(), (
        "SKILL.md must call out the indented-heredoc (<<-EOF) parse hazard"
    )
    # Full variable resolution: every ${var.*}, not just service.name.
    assert "${var." in text, "SKILL.md must reference ${var.*} interpolation in program_text"
    assert "threshold" in text.lower() and "stddev" in text.lower(), (
        "SKILL.md must require resolving threshold/stddev variables, not just service.name"
    )
    # The failure is a SignalFlow parse 400, distinct from a field-name 400.
    assert "400" in text, "SKILL.md must document the HTTP 400 SignalFlow-parse failure"


# ---------------------------------------------------------------------------
# splunk-sync deprecation alias (redirects to splunk-detector-publish)
# ---------------------------------------------------------------------------


def test_splunk_sync_alias_exists_and_is_a_redirect_stub():
    text = _read(SPLUNK_SYNC)
    lowered = text.lower()
    assert "deprecated" in lowered, (
        "splunk-sync/SKILL.md must announce that the skill is deprecated"
    )
    assert "splunk-detector-publish" in text, (
        "splunk-sync/SKILL.md must redirect to the canonical splunk-detector-publish skill"
    )


def test_splunk_sync_alias_does_not_duplicate_full_contract():
    # The alias is a thin stub, not a second copy of the detector contract that
    # could silently drift from the canonical skill.
    text = _read(SPLUNK_SYNC)
    assert len(text.splitlines()) < 60, (
        "splunk-sync/SKILL.md should be a short redirect stub, not a full skill copy; "
        "the canonical contract lives in splunk-detector-publish"
    )
