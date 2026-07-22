import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "otel-audit" / "SKILL.md"
LANGUAGES = ROOT / "skills" / "otel-audit" / "references" / "languages"
REPORT_FLOW = ROOT / "skills" / "references" / "report-flow-contract.md"
BOUNDARY_FIXTURE = ROOT / "evals" / "go" / "chi-basic" / "OPERATIONS.md"
BOUNDARY_EVAL = (
    ROOT / "evals" / "go" / "chi-basic" / "eval" / "qual" / "audit.json"
)
SOURCE_BACKED_DEFAULT_EVAL = (
    ROOT / "evals" / "go" / "chi-partial" / "eval" / "qual" / "audit.json"
)


def test_audit_routes_to_only_the_detected_language_reference() -> None:
    text = SKILL.read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    assert "references/languages/{go,python,node,java}.md" in text
    assert "do not load or restate unrelated language guidance" in normalized
    for name in ("go", "python", "node", "java"):
        assert (LANGUAGES / f"{name}.md").is_file()


def test_go_reference_does_not_recommend_nonexistent_otelchi_module() -> None:
    text = (LANGUAGES / "go.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    assert "no official contrib `otelchi` module" in text
    assert "otelhttp.WithRouteTag" in text
    assert "name `go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp`" in normalized
    assert 'Do not write only "add HTTP instrumentation,"' in text
    assert (
        "go.opentelemetry.io/contrib/instrumentation/github.com/go-chi/chi/otelchi"
        not in text
    )


def test_conditional_genai_reference_is_routed_from_main_skill() -> None:
    text = SKILL.read_text(encoding="utf-8")
    reference = ROOT / "skills" / "otel-audit" / "references" / "genai-audit.md"
    assert "references/genai-audit.md" in text
    assert reference.is_file()
    assert "Do not load the audit-specific reference for non-GenAI services" in text


def test_audit_json_and_renderer_avoid_known_validator_repair_traps() -> None:
    text = SKILL.read_text(encoding="utf-8")
    normalized = " ".join(text.lower().split())
    assert "[GAP: ...]" not in text
    assert "`render-markdown` command owns the complete `.observe/otel.md`" in text
    assert "`meta.genai_ownership_detected` is the explicit ownership switch" in text
    assert "every gap marker must use the exact `area` of a finding" in normalized
    assert (
        "must have an unresolved (`proposed`, `approved`, or `in_progress`) "
        "finding with an identical `area`"
    ) in normalized
    assert "````markdown" not in text


def test_audit_human_report_is_decision_first_and_preserves_requested_scope() -> None:
    skill = " ".join(SKILL.read_text(encoding="utf-8").split())
    flow = " ".join(REPORT_FLOW.read_text(encoding="utf-8").split())

    for term in (
        "counts by `required`/`recommended`/`deferred`",
        "Do not present canonical `meta.status` as a human outcome in HTML",
        "Do not repeat a generic runtime-unproven warning",
        "states only the missing or incorrect condition",
        "stable `OTEL-###` ID only as a secondary reference",
        "`Pass` means no source-visible gaps",
        "monitoring and product outcomes",
        "Every new custom metric must name the chart/dashboard or detector decision",
        "Every new low-cardinality attribute or metric dimension",
        "deterministic local proof step before merge",
        "one concise `product_outcome` sentence",
        "Do not render the component map",
        "one collapsed technical appendix",
        "decision-focused HTML never renders a separate Anti-Patterns subsection",
        "do not render it as a second human ranking system",
        "every finding area must appear in at least one marker",
        "neutral `Select` checkbox only for executable",
        "never emit a checkbox for either",
        "Track external follow-up",
        "Resolve prerequisite first",
        "OTel finding boundary",
        "must not become OTel findings merely because telemetry could observe them",
        "Do not promote service code, configuration, contract, documentation, policy, or general test work into its own OTel finding",
        "dependency inclusion is derived separately",
        "do not render standalone priority or quick-win summary cards",
        "Group actions by priority",
        "action tag",
        "Show executable progress separately from open decisions",
        "Do not render Priority, Effort, or Status filter facets",
        "Findings · N",
        "exactly one highlighted action tag",
        "Omit the baseline `proposed` lifecycle tag",
        "N in selection · R of T required fixes",
        "primary `Save selection` action",
        "do not render `Copy command` or `Copy selection JSON` controls",
        "dependency-closed executable selection",
    ):
        assert term in skill

    for term in (
        "the HTML first screen is a decision view",
        "Fix now",
        "Resolve prerequisite first",
        "required decisions outside the instrumentation selection",
        "Do not surface canonical `meta.status` as a human outcome",
        "stable IDs with display-order aliases such as `gap-1`",
        "Audit `Pass` means no source-visible gaps",
        "unique accessible name",
        "Do not render standalone priority or quick-win summary cards",
        "group actions by priority",
        "action tag",
        "Show executable progress separately from open decisions",
        "Do not render Priority, Effort, or Status filter facets",
        "Findings · N",
        "exactly one highlighted applicable action tag",
        "Omit the baseline `proposed` lifecycle tag",
        "Do not render the canonical component flow",
        "do not render a severity bar, badge, or filter",
        "product_outcome",
        "Technical appendix",
        "Do not render a separate Anti-Patterns subsection in decision-focused HTML",
        "An actionable anti-pattern belongs in its finding card",
        "move keyboard focus",
        "Select",
        "ready to implement",
        "decision needed",
        "external follow-up",
        "has no checkbox and cannot enter selection JSON",
        "N in selection · R of T required fixes",
        "Save selection",
        "Do not require an intermediate review panel",
        "do not expose `Copy command` or `Copy selection JSON` controls",
        "self-contained `file://` report",
        ".observe/otel-selection.json",
        "requested_ids contains only the executable IDs the reviewer explicitly selected",
        "approved_ids contains that set plus executable dependency closure",
        "dependency-closed executable selection",
        "audit -> select -> instrument",
        'aria-live="polite"',
        "Do not render a duplicate all-findings decision table",
    ):
        assert term.replace("`", "") in flow.replace("`", "")

    assert "Resolve decision first" not in flow
    assert "renderer must show that same finding under each explicitly associated component" not in flow
    assert "renders that finding exactly once in the priority-first action view" in flow
    assert "Render authored Incident and GenAI telemetry-readiness tables as visible panels" in flow


def test_audit_finding_cards_hide_proof_detail_until_requested() -> None:
    skill = " ".join(SKILL.read_text(encoding="utf-8").split())
    flow = " ".join(REPORT_FLOW.read_text(encoding="utf-8").split())

    for term in (
        "expanded narrative decision-sized",
        "`Gap`, `Why it matters`, a mode-aware required action, and `Next step`",
        "`Instrumentation change` for executable work",
        "`Decision needed` for a manual prerequisite",
        "`External requirement` for an external prerequisite",
        "then run `$otel-instrument`",
        "auto-added dependency explains why it is included",
        "blocked work names the blocking `OTEL-###` IDs",
        "compact telemetry shape",
        "including configuration and resource items",
        "show their stable IDs as a selection effect",
        "Do not infer a material-safety badge",
        "one collapsed `Technical details` disclosure",
        "acceptance-check, guardrail, and source-reference counts",
        "Do not render raw verification-scenario IDs",
        "Those fields remain in canonical JSON",
        "`.observe/otel-instrumentation.html`",
        "must not require the reviewer to open Markdown",
    ):
        assert term in skill

    for term in (
        "expanded narrative decision-sized",
        "`Gap`, `Why it matters`, a mode-aware required action, and `Next step`",
        "`Instrumentation change` for executable work",
        "`Decision needed` for a manual prerequisite",
        "`External requirement` for an external prerequisite",
        "`Select` -> `Save selection` -> `$otel-instrument`",
        "auto-added dependency explains why it is included",
        "blocked executable work names its blocking `OTEL-###` IDs",
        "compact telemetry shape",
        "including configuration and resource items",
        "show their stable IDs as a selection effect",
        "Do not infer a material-safety badge",
        "one collapsed `Technical details` disclosure",
        "acceptance-check, guardrail, and source-reference counts",
        "Do not render raw verification-scenario IDs",
        "Those fields remain in canonical JSON",
        "`.observe/otel-instrumentation.html`",
        "optional alternate formats, not required reading",
    ):
        assert term in flow


def test_source_backed_safe_defaults_do_not_become_manual_decisions() -> None:
    skill = " ".join(SKILL.read_text(encoding="utf-8").split())
    flow = " ".join(REPORT_FLOW.read_text(encoding="utf-8").split())

    for text in (skill, flow):
        for term in (
            "one safe, reversible, app-owned OTel implementation",
            "must not become a `manual decision`",
            "two or three",
            "explicit selectable `decision_options`",
            "`outcome`",
            "`unlocks`",
        ):
            assert term in text

    evaluation = json.loads(SOURCE_BACKED_DEFAULT_EVAL.read_text(encoding="utf-8"))
    rubric = " ".join(evaluation["rubric"])
    for term in (
        "source-proven safe reversible OTel fixes executable",
        "rather than manual decision",
        "reuse the existing provider topology",
        "hardcoded exporter endpoint",
        "service.name resource",
        "TextMapPropagator",
        "MeterProvider",
        "graceful shutdown",
    ):
        assert term in rubric


def test_audit_eval_keeps_non_telemetry_debt_out_of_every_artifact_section() -> None:
    fixture = BOUNDARY_FIXTURE.read_text(encoding="utf-8")
    evaluation = json.loads(BOUNDARY_EVAL.read_text(encoding="utf-8"))
    rubric = " ".join(evaluation["rubric"])

    for planted_debt in (
        "OpenAPI definitions",
        "contract linting",
        "runbook and ownership links",
        "maximum task-list page size",
        "rejection response",
        "retry, timeout, cache, and fallback behavior",
        "liveness/readiness traffic-routing",
        "deployment rollout policy",
        "behavior-only test",
    ):
        assert planted_debt in fixture

    boundary = next(item for item in evaluation["rubric"] if "OPERATIONS.md" in item)
    for planted_concept in (
        "OpenAPI",
        "contract-lint",
        "runbook-link",
        "ownership-link",
        "page-limit",
        "rejection-policy",
        "retry/timeout/cache/fallback",
        "liveness/readiness",
        "deployment-policy",
        "behavior-only-test",
    ):
        assert planted_concept in boundary

    for excluded_section in (
        "final response",
        "audit summary",
        "evidence row",
        "readiness row",
        "finding",
        "expected telemetry",
        "anti-pattern",
        "recommendation",
        "verification scenario",
        "all generated audit artifacts",
    ):
        assert excluded_section in boundary

    assert "component map followed by" not in rubric
    assert "decision-first .observe/otel.html" in rubric
