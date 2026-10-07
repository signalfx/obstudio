"""Deterministic checks for GenAI readiness skill guidance."""

import ast
import copy
import json
from pathlib import Path
import runpy
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
GENAI_REF = SKILLS_DIR / "references" / "genai-readiness.md"
REPORT_FLOW = SKILLS_DIR / "references" / "report-flow-contract.md"
OTEL_VERIFY = SKILLS_DIR / "otel-verify" / "SKILL.md"
SPLUNK_CONFIGURE = SKILLS_DIR / "splunk-configure" / "SKILL.md"
SPLUNK_CONFIGURE_REFS = SKILLS_DIR / "splunk-configure" / "references"
SPLUNK_DETECTOR_PUBLISH = SKILLS_DIR / "splunk-detector-publish" / "SKILL.md"
SPLUNK_DETECTOR_PUBLISH_REFS = SKILLS_DIR / "splunk-detector-publish" / "references"
SPLUNK_AO_REF = SKILLS_DIR / "references" / "splunk-agent-observability.md"


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
        "Splunk Observability Studio GenAI Trace UI Contract",
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
        "local span-first trace explorers such as Splunk Observability Studio",
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


def test_genai_instrumentation_keeps_token_metric_dimensions_when_known():
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    rubric = " ".join(
        json.loads(
            _read(REPO_ROOT / "evals/python/ai-assistant-demo/eval/qual/instrument.json")
        )["rubric"]
    )
    for text in (instrument, rubric):
        assert "gen_ai.client.token.usage" in text
        assert "gen_ai.token.type" in text
        assert "gen_ai.operation.name" in text
        assert "gen_ai.provider.name" in text
        assert "gen_ai.request.model" in text
        assert "on the token metric" in text


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


def test_splunk_ao_skills_explain_span_creation_and_export_paths():
    audit = " ".join(_read(SKILLS_DIR / "otel-audit" / "SKILL.md").split())
    instrument = " ".join(_read(SKILLS_DIR / "otel-instrument" / "SKILL.md").split())
    reference = " ".join(_read(SPLUNK_AO_REF).split())

    detection_terms = [
        "from splunk_ao import log",
        "@log",
        'span_type="tool"',
        'span_type="retriever"',
        "SplunkAOLogger",
        "SplunkAOCallback",
        "add_splunk_ao_span_processor",
        "configure_distributed_tracing",
        "instrument_distributed_tracing",
    ]
    assert not [term for term in detection_terms if term not in audit]
    audit_outcome_terms = [
        "separate selectable lifecycle finding",
        "logger.terminate()",
        "supported process teardown",
    ]
    assert not [term for term in audit_outcome_terms if term not in audit]

    instrument_lifecycle_terms = [
        "splunk_ao_context.get_logger_instance()",
        "flush alone does not terminate",
        "both independent entrypoints",
        "capture both SDK-created and app-owned spans",
    ]
    assert not [term for term in instrument_lifecycle_terms if term not in instrument]

    compatibility_terms = [
        "span creation",
        "export-only",
        "transport-only",
        "combined setup",
        "resource management",
        "one span source per logical operation",
        "captures function arguments and return values",
        "raw content capture is approved",
        "existing provider",
        "provider.shutdown()",
        "logger.terminate()",
        "no live credentials",
        "no duplicate workflow, model, tool, or retrieval spans",
        "Do not leave the reader or a downstream skill to infer `export-only`",
        "does not create missing workflow, model, tool, or retrieval operations",
        "Do not weaken that fact to “may capture”",
    ]
    assert not [term for term in compatibility_terms if term not in reference]

    instrument_terms = [
        "Splunk AO Python compatibility",
        "existing OpenTelemetry provider",
        "no existing OpenTelemetry provider",
        "preserve valid `@log`",
        "do not add an app-owned OTel span around the same logical operation",
        "add_splunk_ao_span_processor",
        "metadata-only",
        "reuse of the existing provider",
        "processor count",
        "duplicate-span",
    ]
    assert not [term for term in instrument_terms if term not in instrument]


def test_splunk_ao_integration_eval_is_local_and_outcome_based():
    fixture = REPO_ROOT / "evals" / "python" / "splunk-ao-integration-demo"
    files = [
        fixture / "decorator_app.py",
        fixture / "existing_otel_app.py",
        fixture / "pyproject.toml",
        fixture / "eval" / "qual" / "audit.json",
        fixture / "eval" / "qual" / "instrument.json",
    ]
    for file in files:
        assert file.exists(), f"missing Splunk AO integration fixture file: {file}"

    audit_eval = json.loads(_read(fixture / "eval" / "qual" / "audit.json"))
    instrument_eval = json.loads(
        _read(fixture / "eval" / "qual" / "instrument.json")
    )
    combined = " ".join(
        [
            _read(fixture / "decorator_app.py"),
            _read(fixture / "existing_otel_app.py"),
            *audit_eval["rubric"],
            *instrument_eval["rubric"],
        ]
    )
    for term in (
        "@log",
        'span_type="tool"',
        'span_type="retriever"',
        "add_splunk_ao_span_processor",
        "SDK-created spans",
        "export-only",
        "one span for every logical operation",
        "provider reuse",
        "raw question",
        "raw retrieved documents",
        "without live Splunk or model credentials",
    ):
        assert term in combined


def test_audit_keeps_configurable_ao_prerequisites_selectable():
    audit = " ".join(_read(SKILLS_DIR / "otel-audit" / "SKILL.md").split())
    for term in (
        "missing audit-time credentials alone do not make an AO finding external",
        "selectable project configuration",
        "selectable Agent Stream configuration",
        "reserve `external follow-up` for a source-proven outside owner",
        "separate selectable AO findings for project, Agent Stream, and runtime routing",
        "Agent Stream depends on project",
        "runtime routing depends on project, Agent Stream, and OTel export",
    ):
        assert term in audit


def test_audit_requires_process_relative_ao_runtime_coverage():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    contract = " ".join(
        audit.split("**Splunk AO Runtime Coverage Contract**", 1)[1]
        .split("**Deterministic gap section contract**", 1)[0]
        .split()
    )
    for term in (
        "every in-scope GenAI runtime independently",
        "entry point and reachable AO setup",
        "searched registration/configuration call sites",
        "does not cover a separate interactive runtime",
        "missing project binding, dedicated runtime Agent Stream binding",
        "separate readiness surfaces with distinct `surface` names",
        "selectable `finding_group: splunk-agent-observability` findings",
        "no explicitly selected product target, use `fix all`",
        "Every missing or partial app-owned AO configuration row",
        "unresolved AO-group finding with the same `area`",
        "covered row must cite reachable setup for that exact runtime",
        "Never patch HTML or add empty AO cards",
        "transitive dependency closure must support its own acceptance criteria",
        "canonical workflow, agent, model, or tool spans",
        "include the unresolved producer and semantic-continuity findings",
        "include any unresolved ordinary provider-lifecycle finding needed by that route",
        "local proof scenario for the exact live entry point",
        "attach one AO sink/processor",
        "emit no duplicate logical spans",
        "flush/shut down the owned sink/provider",
        "evaluation logger's teardown does not prove a new live sink's lifecycle",
    ):
        assert term in contract


def test_ai_assistant_eval_fixture_is_independent_from_live_runtime():
    fixture = REPO_ROOT / "evals/python/ai-assistant-demo"
    for filename, forbidden in (
        ("app.py", {"eval_runner", "splunk_ao"}),
        ("eval_runner.py", {"app", "fastapi"}),
    ):
        tree = ast.parse(_read(fixture / filename))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        assert not imported & forbidden

    audit_eval = json.loads(_read(fixture / "eval/qual/audit.json"))
    normal_prompt = next(
        row["task"] for row in audit_eval["prompts"] if row["id"] == "genai-readiness"
    )
    assert "Splunk" not in normal_prompt
    assert " AO " not in normal_prompt
    rubric = " ".join(audit_eval["rubric"])
    for term in (
        "including genai-readiness without explicit AO wording",
        "evaluation-only configuration is not reachable from live app.py chat",
        "never lets that covered evaluation row mask absent interactive project binding",
        "separate independently selectable configuration findings",
        "Uses fix all for optional live adoption",
    ):
        assert term in rubric


def _independent_evaluation_with_fake_sdk(monkeypatch, *, stream_exists, fail_span=False):
    """Exercise the runner without credentials, a model, or a product API."""

    calls = []
    monkeypatch.delenv("SPLUNK_AO_EVAL_PROJECT", raising=False)
    monkeypatch.delenv("SPLUNK_AO_EVAL_STREAM", raising=False)

    class Projects:
        def get(self, **kwargs):
            calls.append(("project", kwargs))
            return SimpleNamespace(id="eval-project-id")

    class AgentStreams:
        def get(self, **kwargs):
            calls.append(("stream.get", kwargs))
            return SimpleNamespace(id="eval-stream-id") if stream_exists else None

        def create(self, **kwargs):
            calls.append(("stream.create", kwargs))
            return SimpleNamespace(id="eval-stream-id")

    class SplunkAOLogger:
        def __init__(self, **kwargs):
            calls.append(("logger", kwargs))

        def start_trace(self, **kwargs):
            calls.append(("trace", kwargs))

        def add_llm_span(self, **kwargs):
            calls.append(("model", kwargs))
            if fail_span:
                raise RuntimeError("synthetic SDK failure")

        def conclude(self, **kwargs):
            calls.append(("conclude", kwargs))

        def flush(self):
            calls.append(("flush", {}))

        def terminate(self):
            calls.append(("terminate", {}))

    for name, member, implementation in (
        ("splunk_ao", "SplunkAOLogger", SplunkAOLogger),
        ("splunk_ao.projects", "Projects", Projects),
        ("splunk_ao.agent_streams", "AgentStreams", AgentStreams),
    ):
        module = ModuleType(name)
        setattr(module, member, implementation)
        monkeypatch.setitem(sys.modules, name, module)
    namespace = runpy.run_path(
        str(REPO_ROOT / "evals/python/ai-assistant-demo/eval_runner.py"),
        run_name="independent_evaluation_fixture",
    )
    assert calls == []
    return namespace["run_evaluation"], calls


def test_ai_assistant_eval_resolves_only_its_own_route_and_terminates(monkeypatch):
    for stream_exists in (True, False):
        run, calls = _independent_evaluation_with_fake_sdk(
            monkeypatch, stream_exists=stream_exists
        )
        assert run() == "eval-stream-id"
        assert calls[0] == ("project", {"name": "ai-assistant-demo-evaluation"})
        assert calls[1] == (
            "stream.get",
            {"name": "offline-evaluations", "project_id": "eval-project-id"},
        )
        assert ("stream.create" in [name for name, _ in calls]) is not stream_exists
        assert ("logger", {
            "project": "ai-assistant-demo-evaluation",
            "agent_stream_id": "eval-stream-id",
        }) in calls
        assert [name for name, _ in calls].count("trace") == 1
        assert [name for name, _ in calls].count("model") == 1
        assert calls[-3:] == [
            ("conclude", {"output": "synthetic evaluation passed"}),
            ("flush", {}),
            ("terminate", {}),
        ]


def test_ai_assistant_eval_terminates_its_logger_on_failure(monkeypatch):
    run, calls = _independent_evaluation_with_fake_sdk(
        monkeypatch, stream_exists=True, fail_span=True
    )
    with pytest.raises(RuntimeError, match="synthetic SDK failure"):
        run()
    assert calls[-1] == ("terminate", {})
    assert [name for name, _ in calls].count("terminate") == 1
    assert "conclude" not in [name for name, _ in calls]


def test_splunk_ao_langchain_demo_is_local_runnable_and_outcome_based():
    fixture = REPO_ROOT / "evals" / "python" / "splunk-ao-langchain-demo"
    files = [
        fixture / "app.py",
        fixture / "README.md",
        fixture / "pyproject.toml",
        fixture / "tests" / "test_app.py",
        fixture / "eval" / "qual" / "audit.json",
        fixture / "eval" / "qual" / "instrument.json",
    ]
    for file in files:
        assert file.exists(), f"missing Splunk AO LangChain demo file: {file}"

    combined = " ".join(_read(file) for file in files)
    for term in (
        "SplunkAOCallback",
        "FakeListLLM",
        "ingestion_hook",
        "logger.terminate()",
        "no OpenAI API key",
        "no Splunk access token",
        "single SplunkAOCallback span",
        "without network access",
        "create_connection",
        'name.startswith("OBSTUDIO_")',
    ):
        assert term in combined
    app_and_tests = " ".join(
        _read(file)
        for file in (fixture / "app.py", fixture / "tests" / "test_app.py")
    )
    for forbidden in (
        "observer_status",
        "route-registration",
        "OBSTUDIO_OBSERVER_URL",
    ):
        assert forbidden not in app_and_tests


def test_galileo_choice_fixture_citations_cover_the_claimed_behavior():
    fixture = REPO_ROOT / "evals" / "python" / "galileo-agent-demo"
    audit = json.loads(
        _read(fixture / "eval" / "inputs" / "otel-audit-integration-choice.json")
    )

    def cited_text(reference: str) -> str:
        path, location = reference.split(":", 1)
        first, _, last = location.partition("-")
        lines = _read(fixture / path).splitlines()
        return "\n".join(lines[int(first) - 1 : int(last or first)])

    evidence = {
        entry["check"]: cited_text(entry["source"])
        for entry in audit["evidence"]
        if ":" in entry["source"]
    }
    entry_point = evidence["Entry point"]
    assert "GalileoSpanProcessor" in entry_point
    assert '"gen_ai.operation.name": "invoke_workflow"' in entry_point
    assert '"gen_ai.operation.name": "execute_tool"' in entry_point
    assert '"gen_ai.operation.name": "chat"' in entry_point
    assert "GALILEO_PROJECT" in evidence["Runtime/startup"]
    assert "GALILEO_LOG_STREAM" in evidence["Runtime/startup"]
    assert "splunk-ao" in evidence["Target-product evidence"]
    assert "twice" in evidence["Target-product evidence"]

    for span in audit["current_instrumentation"]["spans"]:
        assert span["name"].split()[0] in cited_text(span["source"])


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


def test_otel_audit_requires_separate_retrieval_detection_inside_tools():
    audit = " ".join(_read(SKILLS_DIR / "otel-audit" / "SKILL.md").split())
    required_terms = [
        "Retrieval detection inside tools",
        "search_docs",
        "retrieval-like operation",
        "generic tool span is not complete retrieval coverage",
        "retrieval-specific readiness row",
        "selectable retrieval finding",
        "nested retrieval span",
        "gen_ai.operation.name=retrieval",
    ]
    missing = [term for term in required_terms if term not in audit]
    assert not missing


def test_ai_assistant_instrument_case_requires_nested_retrieval_closure():
    audit_input = json.loads(
        _read(
            REPO_ROOT
            / "evals/python/ai-assistant-demo/eval/inputs/otel-audit.json"
        )
    )
    instrument_eval = json.loads(
        _read(
            REPO_ROOT
            / "evals/python/ai-assistant-demo/eval/qual/instrument.json"
        )
    )
    instrument_skill = " ".join(
        _read(SKILLS_DIR / "otel-instrument" / "SKILL.md").split()
    )

    findings = {finding["id"]: finding for finding in audit_input["findings"]}
    retrieval = findings["OTEL-002"]
    assert "finding_group" not in retrieval
    assert retrieval["dependencies"] == ["OTEL-001"]
    assert retrieval["verification_scenarios"] == ["genai.search_docs.retrieval"]
    assert any(
        item["type"] == "span"
        and item["name"] == "retrieval demo-knowledge-base"
        and "gen_ai.operation.name=retrieval" in item["attributes"]
        and "gen_ai.data_source.id=demo-knowledge-base" in item["attributes"]
        for item in retrieval["expected_telemetry"]
    )

    scenarios = {
        scenario["id"]: scenario
        for scenario in audit_input["verification"]["scenarios"]
    }
    scenario = " ".join(
        json.dumps(scenarios["genai.search_docs.retrieval"], sort_keys=True).split()
    ).lower()
    for term in (
        "exactly one execute_tool search_docs",
        "exactly one nested retrieval demo-knowledge-base",
        "parent",
        "gen_ai.retrieval.query.text",
        "gen_ai.retrieval.documents",
    ):
        assert term in scenario

    prompt = instrument_eval["prompts"][0]["task"]
    assert "OTEL-002 and AO-003" in prompt
    rubric = " ".join(instrument_eval["rubric"]).lower()
    for term in (
        "exactly one execute_tool search_docs",
        "exactly one nested retrieval demo-knowledge-base",
        "gen_ai.operation.name=retrieval",
        "gen_ai.data_source.id=demo-knowledge-base",
        "direct child",
        "no raw retrieval query or document content",
    ):
        assert term in rubric

    for term in (
        "Retrieval inside a tool",
        "preserve exactly one `execute_tool {tool}` span",
        "exactly one nested `retrieval {source}` child span",
        "`gen_ai.operation.name=retrieval`",
        "`gen_ai.data_source.id`",
        "`gen_ai.retrieval.query.text`",
        "`gen_ai.retrieval.documents`",
        "parent span ID",
        "asserts `gen_ai.operation.name` and `gen_ai.data_source.id`",
    ):
        assert term in instrument_skill


def test_ai_assistant_instrument_case_selects_distinct_ao_routing(tmp_path):
    audit_path = REPO_ROOT / "evals/python/ai-assistant-demo/eval/inputs/otel-audit.json"
    audit_input = json.loads(_read(audit_path))
    instrument_eval = json.loads(
        _read(REPO_ROOT / "evals/python/ai-assistant-demo/eval/qual/instrument.json")
    )
    findings = {finding["id"]: finding for finding in audit_input["findings"]}
    ao_findings = [
        finding
        for finding in findings.values()
        if finding.get("finding_group") == "splunk-agent-observability"
    ]
    assert len(ao_findings) == 3
    assert findings["AO-001"]["dependencies"] == []
    assert findings["AO-002"]["dependencies"] == ["AO-001"]
    assert findings["AO-003"]["dependencies"] == [
        "OTEL-001",
        "AO-001",
        "AO-002",
    ]
    selection_path = tmp_path / "otel-selection.json"
    subprocess.run(
        [
            sys.executable,
            str(SKILLS_DIR / "references/scripts/observe_report.py"),
            "select",
            str(audit_path),
            "--ids",
            "OTEL-002,AO-003",
            "-o",
            str(selection_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    selection = json.loads(_read(selection_path))
    assert selection["requested_ids"] == ["OTEL-002", "AO-003"]
    assert selection["approved_ids"] == [
        "OTEL-001",
        "OTEL-002",
        "AO-001",
        "AO-002",
        "AO-003",
    ]
    assert "OTEL-002 and AO-003" in instrument_eval["prompts"][0]["task"]
    rubric = " ".join(instrument_eval["rubric"]).lower()
    for term in ("project resource", "agent stream resource", "runtime routing"):
        assert term in rubric


@pytest.mark.parametrize("mode,connection", [
    ("gateway", "available"),
    ("gateway", "disconnected"),
    ("direct-cloud", "not required"),
])
def test_ao_endpoint_mode_preserves_executable_resource_selection(
    tmp_path, mode, connection,
):
    """Use the real selector; transport/access gaps do not externalize resources."""

    audit = json.loads(_read(
        REPO_ROOT / "evals/python/ai-assistant-demo/eval/inputs/otel-audit.json"
    ))
    original_findings = copy.deepcopy(audit["findings"])
    route = next(row for row in audit["findings"] if row["id"] == "AO-003")
    route["constraints"].append(
        f"Selected endpoint mode: {mode}; connection: {connection}; no live cloud proof supplied."
    )
    audit_path = tmp_path / "configured-audit.json"
    audit_path.write_text(json.dumps(audit))
    selection_path = tmp_path / "otel-selection.json"
    subprocess.run(
        [sys.executable, str(SKILLS_DIR / "references/scripts/observe_report.py"),
         "select", str(audit_path), "--ids", "AO-003", "-o", str(selection_path)],
        check=True, capture_output=True, text=True,
    )
    selection = json.loads(_read(selection_path))
    assert selection["requested_ids"] == ["AO-003"]
    assert selection["approved_ids"] == ["OTEL-001", "AO-001", "AO-002", "AO-003"]
    # Selection is authorization, not successful resource resolution or delivery.
    assert json.loads(_read(audit_path)) == audit
    for finding in audit["findings"]:
        original = next(row for row in original_findings if row["id"] == finding["id"])
        assert finding["dependencies"] == original["dependencies"]
        assert finding["status"] == "proposed"
        assert finding["instrument_mode"] != "external follow-up"
        assert finding["expected_telemetry"] == original["expected_telemetry"]
    assert "OTEL-002" not in selection["approved_ids"]

    scenarios = {row["id"]: row for row in audit["verification"]["scenarios"]}
    assert "ao.runtime.routing" in route["verification_scenarios"]
    assert scenarios["ao.runtime.routing"]["proof_level"] == "full runtime"
    assert "two distinct dedicated Agent Streams" in scenarios["ao.runtime.routing"]["trigger"]
    assert "local ACK is not cloud visibility" in scenarios["ao.runtime.routing"]["acceptance_criteria"]


def test_ao_gateway_and_direct_configuration_use_the_same_normal_app_calls(monkeypatch):
    """Prove fixture destination-independence, not real SDK transport/cloud proof."""

    observations = []
    settings = (
        {
            "SPLUNK_AO_API_URL": "http://127.0.0.1:55300",
            "SPLUNK_AO_CONSOLE_URL": "http://127.0.0.1:55300",
            "SPLUNK_AO_API_KEY": "local-gateway",
        },
        {
            "SPLUNK_AO_REALM": "lab0",
            "SPLUNK_AO_O11Y_TOKEN": "synthetic-unit-test-token",
        },
    )
    for environment in settings:
        with monkeypatch.context() as isolated:
            for name in {key for item in settings for key in item}:
                isolated.delenv(name, raising=False)
            for name, value in environment.items():
                isolated.setenv(name, value)
            run, calls = _independent_evaluation_with_fake_sdk(
                isolated, stream_exists=False,
            )
            assert run() == "eval-stream-id"
            observations.append(calls)
    assert observations[0] == observations[1]
    assert [name for name, _ in observations[0]] == [
        "project", "stream.get", "stream.create", "logger", "trace", "model",
        "conclude", "flush", "terminate",
    ]
    # The actual installed SDK/auth/proxy/export contract has a separate
    # TestAgentObservabilitySDKInstalledCompatibility Go integration test.
    # This fake does not make gateway compatibility or cloud visibility proven.


def test_ao_endpoint_rubrics_require_mode_specific_delivery_evidence():
    fixture = REPO_ROOT / "evals/python/ai-assistant-demo"
    instrument = json.loads(_read(fixture / "eval/qual/instrument.json"))
    audit = json.loads(_read(fixture / "eval/inputs/otel-audit.json"))
    route = next(row for row in audit["findings"] if row["id"] == "AO-003")
    contract = " ".join(route["acceptance_criteria"] + route["constraints"])
    rubric = " ".join(instrument["rubric"])
    for term in (
        "normal SDK/API calls", "active connection/realm",
        "no application cloud token", "per-request project/stream isolation",
        "old-organization IDs", "explicit direct-cloud mode remains valid",
        "upstream ingest acknowledgement", "ordinary APM receipt is not that proof",
    ):
        assert term in rubric
    for term in (
        "Two application streams", "without cross-application leakage",
        "changing a global AO destination", "cloud AO delivery Not proven",
        "local credentials are not represented as cloud credentials",
        "honest runtime availability dependency",
    ):
        assert term in contract
    reference = " ".join(_read(SPLUNK_AO_REF).split())
    for term in (
        "alternative routing modes, not two mandatory exporters",
        "SPLUNK_AO_API_URL", "SPLUNK_AO_CONSOLE_URL", "SPLUNK_AO_API_KEY",
        "not an O11y override", "do not mix these variables",
        "not proof of cloud Agent Observability visibility",
        "do not claim delivery continues while the gateway is stopped",
    ):
        assert term in reference


def test_live_ao_route_selection_closes_promised_producers_and_live_teardown(tmp_path):
    """Exercise the real selector on a test-local, acceptance-complete graph."""

    audit = json.loads(_read(
        REPO_ROOT / "evals/python/ai-assistant-demo/eval/inputs/otel-audit.json"
    ))
    findings = {finding["id"]: finding for finding in audit["findings"]}

    def prerequisite(identifier, area, expected, dependencies, scenario):
        finding = copy.deepcopy(findings["OTEL-001"])
        finding.update({
            "id": identifier,
            "title": area,
            "area": area,
            "dependencies": dependencies,
            "expected_telemetry": expected,
            "verification_scenarios": [scenario],
            "acceptance_criteria": [f"The live route includes {area}."],
        })
        return finding

    agent = prerequisite(
        "OTEL-AGENT", "Live agent producer",
        [{"type": "span", "name": "invoke_agent fixture-agent",
          "attributes": ["gen_ai.operation.name=invoke_agent"],
          "product_view": "Live agent trace"}],
        ["OTEL-001"], "genai.turn.lifecycle",
    )
    workflow = prerequisite(
        "OTEL-WORKFLOW", "Live workflow producer",
        [{"type": "span", "name": "invoke_workflow build_turn",
          "attributes": ["gen_ai.operation.name=invoke_workflow"],
          "product_view": "Live workflow trace"}],
        ["OTEL-AGENT"], "genai.turn.lifecycle",
    )
    lifecycle = prerequisite(
        "OTEL-LIVE-LIFECYCLE", "Live provider lifecycle",
        [{"type": "configuration", "name": "live.provider.shutdown",
          "attributes": [], "product_view": "Live provider lifecycle"}],
        [], "live.ao.shutdown",
    )
    evaluation_lifecycle = prerequisite(
        "OTEL-EVAL-LIFECYCLE", "Independent evaluation logger lifecycle",
        [{"type": "configuration", "name": "evaluation.logger.terminate",
          "attributes": [], "product_view": "Evaluation logger lifecycle"}],
        [], "evaluation.ao.shutdown",
    )
    routing = findings["AO-003"]
    routing["dependencies"] = ["AO-002", "OTEL-WORKFLOW", "OTEL-LIVE-LIFECYCLE"]
    routing["verification_scenarios"] = ["genai.turn.lifecycle", "live.ao.shutdown"]
    routing["acceptance_criteria"].append(
        "One live workflow -> agent -> model/tool tree is drained at provider shutdown."
    )
    audit["findings"] = [
        findings["OTEL-001"], findings["OTEL-002"], agent, workflow,
        lifecycle, evaluation_lifecycle, findings["AO-001"], findings["AO-002"], routing,
    ]
    audit["signal_flow"]["component_flow_map"] += (
        "\nLive operation production\n"
        "workflow [GAP: Live workflow producer] -> agent [GAP: Live agent producer]\n"
        "live provider [GAP: Live provider lifecycle]\n"
        "independent evaluation logger [GAP: Independent evaluation logger lifecycle]"
    )
    scenario = copy.deepcopy(audit["verification"]["scenarios"][0])
    scenario.update({
        "id": "live.ao.shutdown",
        "trigger": "Close the live runtime after a completed assistant turn",
        "expected_signals": "One AO sink/processor and completed live operation spans",
        "acceptance_criteria": "Inspect active sink outputs; force_flush/shutdown drains completed spans, releases resources, and emits no duplicate operations or duplicate export to the AO destination.",
    })
    evaluation_scenario = copy.deepcopy(scenario)
    evaluation_scenario.update({
        "id": "evaluation.ao.shutdown",
        "entrypoint": "eval_runner.py:run_evaluation",
        "trigger": "Complete the independent offline evaluation",
        "expected_signals": "Evaluation logger terminate",
    })
    audit["verification"]["scenarios"].extend([scenario, evaluation_scenario])
    audit_path = tmp_path / "live-ao-audit.json"
    audit_path.write_text(json.dumps(audit))
    selection_path = tmp_path / "live-ao-selection.json"
    subprocess.run(
        [sys.executable, str(SKILLS_DIR / "references/scripts/observe_report.py"),
         "select", str(audit_path), "--ids", "AO-003", "-o", str(selection_path)],
        check=True, capture_output=True, text=True,
    )
    selection = json.loads(_read(selection_path))
    assert selection["requested_ids"] == ["AO-003"]
    assert selection["approved_ids"] == [
        "OTEL-001", "OTEL-AGENT", "OTEL-WORKFLOW", "OTEL-LIVE-LIFECYCLE",
        "AO-001", "AO-002", "AO-003",
    ]
    selected = [finding for finding in audit["findings"]
                if finding["id"] in selection["approved_ids"]]
    operations = {attribute for finding in selected
                  for item in finding["expected_telemetry"]
                  for attribute in item["attributes"]}
    assert {
        "gen_ai.operation.name=invoke_workflow", "gen_ai.operation.name=invoke_agent",
        "gen_ai.operation.name=chat", "gen_ai.operation.name=execute_tool",
    } <= operations
    selected_scenarios = {identifier for finding in selected
                          for identifier in finding["verification_scenarios"]}
    assert "live.ao.shutdown" in selected_scenarios
    assert "evaluation.ao.shutdown" not in selected_scenarios
    assert "OTEL-002" not in selection["approved_ids"]

    assert "OTEL-EVAL-LIFECYCLE" not in selection["approved_ids"]
    assert all("finding_group" not in finding for finding in selected
               if finding["id"].startswith("OTEL-"))

    rubric = " ".join(json.loads(_read(
        REPO_ROOT / "evals/python/ai-assistant-demo/eval/qual/audit.json"
    ))["rubric"])
    for term in (
        "transitive dependency closure includes every missing workflow, agent, model, tool, or retrieval span producer",
        "source-covered creation reachable from that exact runtime",
        "eval_runner.py logger.terminate never closes interactive provider.shutdown",
        "pending completed spans are drained and resources released",
        "duplicate export to the same AO destination",
    ):
        assert term in rubric


def test_ai_assistant_instrument_rubric_stays_within_selected_signal_contract():
    audit_input = json.loads(
        _read(REPO_ROOT / "evals/python/ai-assistant-demo/eval/inputs/otel-audit.json")
    )
    instrument_eval = json.loads(
        _read(REPO_ROOT / "evals/python/ai-assistant-demo/eval/qual/instrument.json")
    )
    selected = next(
        finding for finding in audit_input["findings"] if finding["id"] == "OTEL-001"
    )
    expected_names = {item["name"] for item in selected["expected_telemetry"]}
    assert "gen_ai.client.token.usage" in expected_names
    assert "assistant.stream.active" in expected_names
    assert "invoke_workflow build_turn" not in expected_names
    coverage_rubric = instrument_eval["rubric"][1].lower()
    pressure_rubric = instrument_eval["rubric"][5].lower()
    assert "feedback export" not in coverage_rubric
    assert "assistant-turn" not in coverage_rubric
    assert "token-limit errors" not in pressure_rubric
    assert "selected" in coverage_rubric
    assert "selected" in pressure_rubric


def test_instrument_selected_tools_keep_other_tool_behavior_without_new_spans():
    instrument = " ".join(
        _read(SKILLS_DIR / "otel-instrument" / "SKILL.md").split()
    )
    rubric = json.loads(
        _read(REPO_ROOT / "evals/python/ai-assistant-demo/eval/qual/instrument.json")
    )["rubric"][1]
    for term in (
        "only selected tool operations",
        "unselected tool names",
        "same result or error",
    ):
        assert term in instrument
    assert "unselected tool names" in rubric
    assert "existing behavior" in rubric


def test_instrument_retrieval_proof_compares_actual_span_ids():
    instrument = " ".join(
        _read(SKILLS_DIR / "otel-instrument" / "SKILL.md").split()
    )
    rubric = json.loads(
        _read(REPO_ROOT / "evals/python/ai-assistant-demo/eval/qual/instrument.json")
    )["rubric"][4]
    for term in (
        "in-memory SDK exporter",
        "retrieval parent span ID equals the tool span ID",
        "object-parent equality",
    ):
        assert term in instrument
    assert "actual parent span ID" in rubric
    assert "tool span ID" in rubric


def test_instrument_persists_selected_export_dependencies_separately_from_credentials():
    instrument = " ".join(
        _read(SKILLS_DIR / "otel-instrument" / "SKILL.md").split()
    )
    rubric = json.loads(
        _read(REPO_ROOT / "evals/python/ai-assistant-demo/eval/qual/instrument.json")
    )["rubric"][9]
    for term in (
        "project lockfile",
        "uv.lock",
        "uv sync --locked",
        "missing credentials",
        "dependency resolution",
    ):
        assert term in instrument
    assert "locked dependencies" in rubric
    assert "credential" in rubric


def test_instrument_runs_local_verify_when_remote_export_is_blocked():
    instrument = " ".join(
        _read(SKILLS_DIR / "otel-instrument" / "SKILL.md").split()
    )
    rubric = json.loads(
        _read(REPO_ROOT / "evals/python/ai-assistant-demo/eval/qual/instrument.json")
    )["rubric"][11]
    for term in (
        "local `$otel-verify`",
        "remote export credentials",
        "## What Changed",
        "## Tested And Working",
        "## Not Working Or Not Proven",
        "## Proof",
    ):
        assert term in instrument
    assert "local otel-verify" in rubric
    assert "remote export" in rubric


def test_ai_assistant_rubric_distinguishes_selection_refresh_from_instrument_overwrite():
    instrument_eval = json.loads(
        _read(REPO_ROOT / "evals/python/ai-assistant-demo/eval/qual/instrument.json")
    )
    reader_rubric = instrument_eval["rubric"][10].lower()
    assert "explicit selection-aware refresh" in reader_rubric
    assert "instrumentation renderer" in reader_rubric
    assert "must not overwrite" in reader_rubric


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
        "complete GenAI observability ledger",
        "Only telemetry closure rows from that ledger become instrumentation findings",
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


def test_audit_keeps_genai_governance_and_cost_context_out_of_default_findings():
    audit = " ".join(_read(SKILLS_DIR / "otel-audit" / "SKILL.md").split())
    required_terms = [
        "Telemetry closure rows may become findings",
        "Governance/context rows stay in `## GenAI Readiness`",
        "Content capture policy",
        "safety/refusal policy",
        "cost/billing ownership are not default service instrumentation findings",
        "Evaluation telemetry can be a finding",
        "Do not bundle that with safety or content-governance work",
        "Cost telemetry can be a finding only when the repository owns an authoritative pricing source",
    ]
    assert not [term for term in required_terms if term not in audit]


def test_audit_requires_single_deterministic_gap_section():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    normalized = " ".join(audit.split())
    required_terms = [
        "Deterministic gap section contract",
        "canonical audit has exactly one actionable gap source: `findings`",
        "Record GenAI detail in canonical `genai_readiness` rows",
        "promote service-owned OTel telemetry closure rows into `findings`",
        "put source-backed actionable product or routing gaps in the same `findings` array",
        "finding_group: splunk-agent-observability",
        "keep the HTML decision view focused on those findings",
    ]
    assert not [term for term in required_terms if term not in normalized]


def test_audit_groups_sdk_specific_content_capture_with_agent_observability():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    gap_contract = audit.split("**Deterministic gap section contract**", 1)[1].split(
        "**", 1
    )[0]
    assert "SplunkAOCallback" in gap_contract
    assert "raw caller content" in gap_contract
    assert "finding_group: splunk-agent-observability" in gap_contract


def test_audit_requires_source_backed_overlap_inventory_for_sdk_callbacks():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    callback_guidance = " ".join(
        audit.split("For Python with Splunk AO", 1)[1]
        .split("Audit teardown", 1)[0]
        .split()
    )
    assert "second callback" in callback_guidance
    assert "framework auto" in callback_guidance
    assert "source-backed negative evidence" in callback_guidance


def test_audit_reports_sdk_teardown_as_current_state_even_when_covered():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    lifecycle_guidance = " ".join(
        audit.split("Audit teardown for every detected Splunk AO span source", 1)[1]
        .split("Audit workflow naming", 1)[0]
        .split()
    )
    assert "current-state lifecycle assessment" in lifecycle_guidance
    assert "source-covered" in lifecycle_guidance
    assert "future verification scenario" in lifecycle_guidance


def test_instrument_keeps_selected_scope_and_audit_group_ownership():
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    closure = instrument.split("### Audit-Driven Gap Closure", 1)[1].split("###", 1)[0]
    assert "unselected local log export" in closure
    assert "audit finding_group" in closure

    rubric = _read(
        REPO_ROOT
        / "evals/python/ai-assistant-demo/eval/qual/instrument.json"
    )
    assert "bound audit" in rubric
    assert "instrumentation overlay" in rubric


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
        "If canonical audit JSON is absent",
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


def test_audit_keeps_readiness_ledgers_out_of_human_html():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    audit_normalized = " ".join(audit.split())
    flow = _read(SKILLS_DIR / "references" / "report-flow-contract.md")
    combined = " ".join((audit + "\n" + flow).split())
    assert "preserve authored readiness rows in canonical JSON" in audit_normalized
    assert "Human HTML must not render full Incident or GenAI readiness ledgers" in audit_normalized
    assert "Do not render authored readiness tables as visible peer sections in audit HTML" in audit_normalized
    assert "The human HTML decision view renders actionable findings only" in combined
    assert "readiness ledgers reserved for downstream tooling" in combined
    assert "Human HTML must visibly render authored GenAI readiness" not in combined


def test_audit_requires_reader_first_current_state_baseline():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    audit_normalized = " ".join(audit.split())
    flow = _read(SKILLS_DIR / "references" / "report-flow-contract.md")
    combined = " ".join((audit + "\n" + flow).split())
    reader_order = flow.split("Use this reader order", 1)[1].split(
        "Do not put command inventories", 1
    )[0]

    evidence_index = reader_order.index("Audit Evidence")
    current_index = reader_order.index("Current Instrumentation")
    gaps_index = reader_order.index("Gaps")
    verification_index = reader_order.index("Verification Plan")
    assert evidence_index < current_index < gaps_index < verification_index

    required_terms = [
        "meta.genai_ownership_detected",
        "GenAI ownership",
        "Declare `**GenAI ownership detected:** Yes` or `No`",
        "Use only the top-level sections in the reader order",
        "finalize-audit",
        "--html .observe/otel.html",
    ]
    missing = [term for term in required_terms if term not in combined]
    assert not missing


def test_audit_read_only_scope_still_writes_the_report_artifact():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    required_terms = [
        "Read-only for application code",
        "writes `.observe/otel-audit.json` and `.observe/otel.html`",
        "does not modify service code",
        "Write two audit artifacts",
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
        "| Signal type | Added | Modified | Removed | Product result / next product action | Evidence | Verification status |",
        "Do not claim a removal unless the previous report or Git diff proves",
        "Use one row per selected audit finding",
        "Derive `**Result:**` from all applicable closure tables",
        "render `.observe/otel-instrumentation.html` using",
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
        "When no canonical source audit exists, do not create `## GenAI Readiness Closure`",
        "do not collapse absent GenAI readiness into a generic implementation claim",
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
# splunk-detector-publish skill
#
# The full detector-publish contract lives in skills/splunk-detector-publish.
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
