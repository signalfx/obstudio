"""Deterministic checks for the splunk-dashboard and splunk-dashboard-publish skills.

Sibling to ``test_genai_skill_guidance.py`` (same helpers, same style). These tests
pin the invariants of the dashboard generate/publish skill pair and the shared
``skills/references/`` files the detector skills were light-refactored onto.

NOTE: the dashboard skills and the shared reference files legitimately use a
concrete example service name ("checkout") in worked examples, so they are
intentionally NOT subjected to the provider-neutral "stays generic" blocked-term
guard in ``test_genai_skill_guidance.py``. That guard remains scoped to the GenAI
readiness reference + detector skills, where concrete names do not belong.
"""

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"

# Shared references (one source of truth, included by all four skills).
SHARED_REFS = SKILLS_DIR / "references"
SPLUNK_API_REF = SHARED_REFS / "splunk-api.md"
TERRAFORM_NORMALIZATION_REF = SHARED_REFS / "terraform-normalization.md"
SIGNALFLOW_PATTERNS_REF = SHARED_REFS / "signalflow-patterns.md"
LEDGER_TEMPLATE_REF = SHARED_REFS / "ledger-template.md"
COVERAGE_DECISION_TREE_REF = SHARED_REFS / "coverage-decision-tree.md"

# Dashboard generate skill.
SPLUNK_DASHBOARD = SKILLS_DIR / "splunk-dashboard" / "SKILL.md"
SPLUNK_DASHBOARD_REFS = SKILLS_DIR / "splunk-dashboard" / "references"
DASHBOARD_CLASSIFICATION = SPLUNK_DASHBOARD_REFS / "dashboard-classification.md"
DASHBOARD_TEMPLATES = SPLUNK_DASHBOARD_REFS / "dashboard-templates.md"

# Dashboard publish skill (canonical; splunk-dashboard-sync is the deprecated stub).
SPLUNK_DASHBOARD_PUBLISH = SKILLS_DIR / "splunk-dashboard-publish" / "SKILL.md"
SPLUNK_DASHBOARD_PUBLISH_REFS = SKILLS_DIR / "splunk-dashboard-publish" / "references"
DASHBOARD_COVERAGE_MODEL = SPLUNK_DASHBOARD_PUBLISH_REFS / "dashboard-coverage-model.md"

# Detector publish skill (canonical; splunk-sync is the deprecated stub).
SPLUNK_DETECTOR_PUBLISH = SKILLS_DIR / "splunk-detector-publish" / "SKILL.md"
SPLUNK_CONFIGURE_REFS = SKILLS_DIR / "splunk-configure" / "references"


def _read(path: Path) -> str:
    assert path.exists(), f"Expected file not found: {path}"
    return path.read_text()


def _normalized(path: Path) -> str:
    """Collapse all runs of whitespace so multi-line phrases match regardless of wrapping."""
    return " ".join(_read(path).split())


# ---------------------------------------------------------------------------
# Existence + frontmatter
# ---------------------------------------------------------------------------


def test_dashboard_skills_exist_with_references():
    assert SPLUNK_DASHBOARD.exists(), "skills/splunk-dashboard/SKILL.md not found"
    assert SPLUNK_DASHBOARD_PUBLISH.exists(), "skills/splunk-dashboard-publish/SKILL.md not found"
    assert DASHBOARD_CLASSIFICATION.exists(), "dashboard-classification.md not found"
    assert DASHBOARD_TEMPLATES.exists(), "dashboard-templates.md not found"
    assert DASHBOARD_COVERAGE_MODEL.exists(), "dashboard-coverage-model.md not found"


def test_dashboard_skill_frontmatter():
    text = _read(SPLUNK_DASHBOARD)
    assert "name: splunk-dashboard" in text, "SKILL.md must declare name: splunk-dashboard"
    assert "author: otel-studio" in text
    assert "category: observability" in text
    # Routing description must carry the intent triggers distinct from detectors.
    for trigger in (
        "generate a dashboard",
        "build a dashboard from",
        "create charts for my service",
        "visualize my metrics",
    ):
        assert trigger in text, f"description missing routing trigger: {trigger}"


def test_dashboard_publish_skill_frontmatter():
    text = _read(SPLUNK_DASHBOARD_PUBLISH)
    assert "name: splunk-dashboard-publish" in text, "SKILL.md must declare name: splunk-dashboard-publish"
    assert "author: otel-studio" in text
    assert "category: observability" in text
    for trigger in (
        "sync dashboards",
        "check which dashboards are missing",
        "create missing dashboards",
        "push",
    ):
        assert trigger in text, f"description missing routing trigger: {trigger}"


# ---------------------------------------------------------------------------
# Shared references + light-refactor guards
# ---------------------------------------------------------------------------


def test_shared_references_exist():
    for ref in (
        SPLUNK_API_REF,
        TERRAFORM_NORMALIZATION_REF,
        SIGNALFLOW_PATTERNS_REF,
        LEDGER_TEMPLATE_REF,
        COVERAGE_DECISION_TREE_REF,
    ):
        assert ref.exists(), f"shared reference not found: {ref}"


def test_detector_publish_skill_reaches_shared_references():
    """Light refactor: splunk-detector-publish/SKILL.md includes the shared refs by a plain
    relative path, and that path must resolve to the real shared file."""
    text = _read(SPLUNK_DETECTOR_PUBLISH)
    for relpath, target in (
        ("../references/splunk-api.md", SPLUNK_API_REF),
        ("../references/terraform-normalization.md", TERRAFORM_NORMALIZATION_REF),
        ("../references/ledger-template.md", LEDGER_TEMPLATE_REF),
        ("../references/coverage-decision-tree.md", COVERAGE_DECISION_TREE_REF),
    ):
        assert relpath in text, f"splunk-detector-publish/SKILL.md must include {relpath}"
        assert (SPLUNK_DETECTOR_PUBLISH.parent / relpath).resolve() == target.resolve()


def test_detector_templates_still_reach_shared_signalflow_reference():
    """Light refactor: splunk-configure's terraform-templates.md points the program_text
    fragment at the shared signalflow-patterns.md instead of restating it."""
    template = SPLUNK_CONFIGURE_REFS / "terraform-templates.md"
    text = _read(template)
    relpath = "../../references/signalflow-patterns.md"
    assert relpath in text, f"terraform-templates.md must include {relpath}"
    assert (template.parent / relpath).resolve() == SIGNALFLOW_PATTERNS_REF.resolve()


def test_dashboard_skills_reach_shared_references():
    """The dashboard skills reach the shared refs by the same relative-path idiom."""
    gen = _read(SPLUNK_DASHBOARD)
    for relpath, target in (
        ("../references/signalflow-patterns.md", SIGNALFLOW_PATTERNS_REF),
        ("../references/terraform-normalization.md", TERRAFORM_NORMALIZATION_REF),
    ):
        assert relpath in gen, f"splunk-dashboard/SKILL.md must include {relpath}"
        assert (SPLUNK_DASHBOARD.parent / relpath).resolve() == target.resolve()

    publish = _read(SPLUNK_DASHBOARD_PUBLISH)
    for relpath, target in (
        ("../references/splunk-api.md", SPLUNK_API_REF),
        ("../references/terraform-normalization.md", TERRAFORM_NORMALIZATION_REF),
        ("../references/ledger-template.md", LEDGER_TEMPLATE_REF),
        ("../references/coverage-decision-tree.md", COVERAGE_DECISION_TREE_REF),
    ):
        assert relpath in publish, f"splunk-dashboard-publish/SKILL.md must include {relpath}"
        assert (SPLUNK_DASHBOARD_PUBLISH.parent / relpath).resolve() == target.resolve()


def test_shared_signalflow_worked_fragments_all_aggregate_before_publish():
    """Regression guard (R2-skills-evals-54): every worked ``data(...).publish(...)`` fragment
    in signalflow-patterns.md must apply an aggregation (``.mean()``/``.sum()``/``.percentile(...)``)
    before ``.publish(...)``. A bare ``.publish()`` with no preceding aggregation renders no value
    in a single_value KPI panel (see dashboard-templates.md) — the Saturation worked example used to
    ship a bare publish that contradicted the file's own aggregation table and the SingleValue rule."""
    import re

    text = _read(SIGNALFLOW_PATTERNS_REF)
    # Every concrete fragment binds a stream from a real metric name (quoted, no angle brackets).
    fragment_lines = [
        line.strip()
        for line in text.splitlines()
        if "data('" in line and ".publish(" in line and "<metric_name>" not in line
    ]
    assert fragment_lines, "expected at least one concrete worked SignalFlow fragment"

    agg_before_publish = re.compile(r"\.(?:mean|sum|percentile|count|max|min)\([^)]*\)\.publish\(")
    for line in fragment_lines:
        assert agg_before_publish.search(line), (
            f"worked fragment has a bare .publish() with no preceding aggregation: {line!r}"
        )


def test_shared_signalflow_reference_omits_detector_tail_for_charts():
    """Dashboard charts reuse the data().agg().publish() fragment but must stop before the
    detector-only detect()/when()/threshold() tail. The concrete chart worked fragments must
    therefore END at .publish(...) and carry NO detect(when(...)) or threshold(...) clause;
    the detector tail may only appear in the prose contrast, never inside a chart fragment."""
    text = _read(SIGNALFLOW_PATTERNS_REF)
    assert "data('<metric_name>'" in text, "shared fragment must show the data('<metric>') call"
    assert ".publish(" in text
    assert "service.name" in text and "sf_service" in text
    # The file must still contrast against the detector tail somewhere (prose section).
    assert "detect(" in text, "must contrast against the detector detect() tail"

    # The concrete chart fragments (a bound stream from a real metric that ends at
    # .publish(...)) must NOT contain the detector-only tail. This is the real check:
    # a chart fragment that carried detect(when(...)) / threshold(...) would render as a
    # detector program, not a chart, and this test previously only asserted detect() was
    # present anywhere in the file — which a chart fragment leaking the tail would pass.
    chart_fragment_lines = [
        line.strip()
        for line in text.splitlines()
        if "data('" in line and ".publish(" in line and "<metric_name>" not in line
    ]
    assert chart_fragment_lines, "expected at least one concrete worked chart fragment"
    for line in chart_fragment_lines:
        assert "detect(when(" not in line, (
            f"chart fragment must not carry the detector detect(when(...)) tail: {line!r}"
        )
        assert "threshold(" not in line, (
            f"chart fragment must not carry the detector threshold(...) tail: {line!r}"
        )


# ---------------------------------------------------------------------------
# Generation skill — panels, sidecar, templates
# ---------------------------------------------------------------------------


def test_dashboard_skill_reads_audit_and_emits_three_level_terraform():
    text = _read(SPLUNK_DASHBOARD)
    assert ".observe/otel.md" in text, "must read the audit report"
    assert "$otel-audit" in text, "must point a missing-audit user at $otel-audit"
    # Three-level Terraform: group -> dashboard -> per-panel chart resources.
    assert "signalfx_dashboard_group" in text
    assert "signalfx_dashboard" in text
    assert "signalfx_" in text and "_chart" in text
    assert "dashboards.tf" in text
    assert "$splunk-dashboard-publish" in text, "must hand off to the publish skill"


def test_dashboard_skill_marks_api_token_sensitive():
    text = _read(SPLUNK_DASHBOARD)
    assert "sensitive = true" in text, "api_token Terraform variable must be sensitive = true"


# The single source of truth for the preview chartType vocabulary: the types the
# generator emits AND the Observer renderer understands. "event" was never emitted
# by any generator artifact and is intentionally excluded; "table" is emitted by the
# classification/templates and rendered by DashboardPanel.tsx, so it is included.
PREVIEW_CHART_TYPES = ("time_series", "single_value", "list", "heatmap", "text", "table")

# Renderer that must support every emitted chartType.
DASHBOARD_PANEL_TSX = REPO_ROOT / "observer" / "client" / "src" / "dashboards" / "DashboardPanel.tsx"

# The qual eval rubric that instructs the LLM judge which preview chartType vocabulary
# is valid. It must match PREVIEW_CHART_TYPES exactly or the judge penalizes correct
# 'table' panels and rewards a never-emitted 'event' panel (the F8/F9 drift).
CHECKOUT_RED_QUAL_RUBRIC = (
    REPO_ROOT / "evals" / "dashboards" / "checkout-red" / "eval" / "qual" / "dashboard.json"
)


def test_dashboard_skill_emits_preview_sidecar_contract():
    text = _read(SPLUNK_DASHBOARD)
    assert ".observe/dashboards.preview.json" in text, "must write the Observer preview sidecar"
    assert "schemaVersion" in text, "preview sidecar must declare schemaVersion"
    # The chart types the generator emits and the Observer renderer understands.
    for chart_type in PREVIEW_CHART_TYPES:
        assert chart_type in text, f"preview sidecar chartType vocabulary missing: {chart_type}"
    # "event" is never produced by any generator artifact: it must not reappear in the
    # generate contract vocabulary line.
    assert "| text | event" not in text and "text | event" not in text, (
        "SKILL.md preview vocabulary must not list the never-emitted 'event' chartType"
    )


def test_preview_chart_vocabulary_is_internally_consistent():
    """Vocabulary parity: every chartType the generate contract (SKILL.md) lists must
    also be the preview type in dashboard-templates.md's REST mapping and a rendered
    branch in DashboardPanel.tsx. Guards against the F8/F9 drift where SKILL.md listed
    the unused 'event' and templates/renderer emitted/rendered 'table' instead."""
    skill = _read(SPLUNK_DASHBOARD)
    templates = _read(DASHBOARD_TEMPLATES)
    renderer = _read(DASHBOARD_PANEL_TSX)

    # time_series is the renderer's implicit fallback branch (any unknown chartType
    # falls through to the shared SVG chart), so it has no `chartType === "time_series"`
    # dispatch token. Every other preview type is dispatched by an exact equality
    # branch, so it must appear as that exact token — a bare-substring check like
    # `"list" in renderer` / `"text" in renderer` / `"table" in renderer` is too loose
    # (those words occur in class names, comments, and labels) and would pass even if
    # the renderer never actually dispatched on the type.
    for chart_type in PREVIEW_CHART_TYPES:
        # SKILL.md generate-contract vocabulary line.
        assert chart_type in skill, f"SKILL.md missing preview chartType: {chart_type}"
        # dashboard-templates.md REST mapping column lists the preview type.
        assert chart_type in templates, f"dashboard-templates.md REST mapping missing: {chart_type}"
        # DashboardPanel.tsx dispatches on the type.
        if chart_type == "time_series":
            # Documented fallback: no explicit equality branch. Assert the label map
            # still knows the type so the badge renders, rather than a loose substring.
            assert f"{chart_type}:" in renderer, (
                f"DashboardPanel.tsx label map missing fallback chartType: {chart_type}"
            )
        else:
            dispatch_token = f'chartType === "{chart_type}"'
            assert dispatch_token in renderer, (
                f"DashboardPanel.tsx must dispatch on {dispatch_token!r} (exact token, "
                f"not a loose substring match on {chart_type!r})"
            )

    # The templates REST mapping must NOT advertise an "event" preview type.
    assert "| `event` |" not in templates and "`event`" not in templates, (
        "dashboard-templates.md REST mapping must not list the never-emitted 'event' chartType"
    )


def test_checkout_red_qual_rubric_matches_preview_chart_vocabulary():
    """The checkout-red qual rubric tells the LLM judge which preview chartType vocabulary
    is valid. It must list exactly PREVIEW_CHART_TYPES (includes 'table', excludes the
    never-emitted 'event'); otherwise the judge penalizes a correct 'table' panel and would
    reward an 'event' panel the generator never emits — the same F8/F9 drift the deterministic
    guard prevents in SKILL.md/templates/renderer but did not cover in the eval."""
    rubric = json.loads(_read(CHECKOUT_RED_QUAL_RUBRIC))
    joined = " ".join(rubric["rubric"])
    # The exact pipe-delimited vocabulary string the judge is handed.
    expected_vocab = "|".join(PREVIEW_CHART_TYPES)
    assert expected_vocab in joined, (
        f"qual rubric must list the preview vocabulary as {expected_vocab!r}"
    )
    # 'event' is never emitted by any generator artifact and must not appear in the vocabulary.
    assert "|event" not in joined and "event vocabulary" not in joined, (
        "qual rubric must not list the never-emitted 'event' chartType"
    )


def test_dashboard_classification_defines_grid_and_chart_vocabulary():
    text = _read(DASHBOARD_CLASSIFICATION)
    # RED-style grouping with the dashboard chart-type vocabulary.
    for chart_type in ("single_value", "time_series"):
        assert chart_type in text
    for signal in ("Latency", "Error", "Throughput", "Saturation"):
        assert signal in text, f"classification missing RED/saturation signal: {signal}"


def test_dashboard_classification_counter_test_covers_error_keyword_family():
    """Regression guard (R3-skills-evals-46): the counter gate in dashboard-classification.md
    must recognize the same error-keyword family the Error rule advertises. An audit report
    lists error counters with names like `checkout.payment.failures`/`rpc.failures`/
    `auth.rejected`/`db.query.timeouts` and a Type of auto/custom (the otel-audit report never
    emits a literal "counter" Type). If the counter suffix list only covers
    `.total`/`.count`/`.errors`/`.processed` and the gate leans on an "audit Type is a counter"
    signal, exactly the error signals a RED dashboard most needs fall through to skip, even
    though the Error rule's keyword list and SKILL.md both say they qualify."""
    text = _read(DASHBOARD_CLASSIFICATION)
    normalized = " ".join(text.split())

    # The counter gate must not depend on an "audit Type is a counter" signal the report
    # format (Type = auto/custom) never emits.
    assert "audit Type is a counter" not in normalized, (
        "counter gate must not rely on an 'audit Type is a counter' signal the otel-audit "
        "report (Type = auto/custom) does not emit"
    )

    # The counter test must recognize the same full bare-word error-keyword family the Error
    # rule lists (plural forms included), so error counters carrying those keywords classify
    # as counters. Bare words also subsume any dot-prefixed spelling (e.g. ".failures").
    for keyword in ("errors", "failures", "failed", "rejected", "timeouts", "exceptions", "invalid"):
        assert keyword in normalized, (
            f"counter test must recognize the error keyword {keyword!r}"
        )

    # The concrete plural error-counter examples from the audit report must appear as qualifying
    # error signals (they carry an error keyword, so the counter gate matches).
    for example in ("rpc.failures", "auth.rejected", "db.query.timeouts"):
        assert example in normalized, (
            f"classification must show {example} as a qualifying error counter"
        )


def test_dashboard_classification_counter_test_covers_singular_error_keywords():
    """Regression guard: the Error rule advertises bare SINGULAR error keywords
    (`error`, `failure`, `timeout`, `exception`), so the counter gate must recognize the
    SINGULAR forms too — not only the plural subset. A custom (Type=auto/custom) metric named
    `checkout.payment.error` / `rpc.timeout` / `auth.failure` / `worker.exception` contains an
    error keyword and no counter suffix; if the counter gate only recognizes plural forms, such
    a metric fails the counter test, falls through Latency/Error/Throughput/Saturation to skip,
    and the RED dashboard silently omits its core error panel. The gate must treat the counter
    test's error keywords as the SAME bare-word family the Error rule lists (singular + plural)."""
    text = _read(DASHBOARD_CLASSIFICATION)
    normalized = " ".join(text.split())

    # The counter test must recognize the singular bare error keywords, not only their plurals.
    for keyword in ("error", "failure", "timeout", "exception"):
        assert keyword in normalized, (
            f"counter test must recognize the singular error keyword {keyword!r}"
        )

    # The doc must state the counter test uses the SAME full family the Error rule advertises,
    # singular and plural alike — not only the dot-prefixed plural subset.
    assert "singular and plural" in normalized, (
        "classification must state the counter test recognizes singular and plural error "
        "keywords alike, matching the Error rule's full family"
    )

    # A concrete SINGULAR error-counter example must appear as a qualifying error signal.
    for example in ("checkout.payment.error", "rpc.timeout", "auth.failure", "worker.exception"):
        assert example in normalized, (
            f"classification must show {example} as a qualifying (singular) error counter"
        )


def test_dashboard_templates_map_hcl_chart_resources_to_rest_types():
    text = _read(DASHBOARD_TEMPLATES)
    # The HCL resource name vs the REST options.type — the chart-first publish depends on this.
    for hcl, rest in (
        ("signalfx_time_chart", "TimeSeriesChart"),
        ("signalfx_single_value_chart", "SingleValue"),
    ):
        assert hcl in text, f"templates missing HCL chart resource: {hcl}"
        assert rest in text, f"templates missing REST chart type: {rest}"
    # dashboard_group is the HCL attribute; the REST body uses groupId.
    assert "dashboard_group" in text
    assert "groupId" in text
    assert "sensitive = true" in text


# ---------------------------------------------------------------------------
# Publish skill — wire casing, chart-first ordering, orphan recovery
# ---------------------------------------------------------------------------


def test_dashboard_publish_reads_terraform_dashboards_tf():
    text = _read(SPLUNK_DASHBOARD_PUBLISH)
    assert "dashboards.tf" in text, "must parse .observe/terraform/dashboards.tf"
    assert "program_text" in text or "programText" in text


def test_dashboard_publish_uses_camel_case_rest_wire_names():
    """REST bodies use camelCase; HCL attributes stay snake_case. Both appear by design,
    so this asserts the camelCase wire names exist (mirrors the detectorOrigin casing test)
    and that the skill distinguishes the HCL spelling from the REST spelling."""
    text = _read(SPLUNK_DASHBOARD_PUBLISH)
    for wire in ("programText", "chartId", "groupId"):
        assert wire in text, f"publish SKILL.md must use camelCase REST wire name: {wire}"
    # The HCL spellings coexist (parsed from Terraform), and the skill must call out the mapping.
    assert "program_text" in text and "dashboard_group" in text, (
        "publish SKILL.md must show the HCL snake_case spellings it parses"
    )


def test_dashboard_publish_documents_chart_first_ordering():
    text = _read(SPLUNK_DASHBOARD_PUBLISH)
    assert "chart-first" in text, "must document chart-first creation ordering"
    assert "POST /v2/chart" in text, "must POST charts first to collect IDs"
    assert "POST /v2/dashboard" in text, "must POST the dashboard referencing chart IDs"
    # Chart create body shape that yields the referencible IDs.
    assert "packageSpecifications" in text
    assert "TimeSeriesChart" in text or "SingleValue" in text


def test_dashboard_publish_documents_orphan_chart_recovery():
    text = _read(SPLUNK_DASHBOARD_PUBLISH)
    assert "Orphan-chart recovery" in text or "orphan" in text.lower(), (
        "must document orphan-chart recovery when the dashboard POST fails after charts exist"
    )
    assert "DELETE /v2/chart" in text, "orphan recovery must clean up created charts"


def test_dashboard_publish_classifies_three_levels():
    text = _read(SPLUNK_DASHBOARD_PUBLISH)
    for status in ("COVERED", "GAP", "UNCERTAIN"):
        assert status in text, f"publish SKILL.md missing verdict status: {status}"
    coverage = _read(DASHBOARD_COVERAGE_MODEL)
    assert "three levels" in coverage, "coverage model must classify group/dashboard/chart"
    for status in ("COVERED", "GAP", "UNCERTAIN"):
        assert status in coverage


def test_dashboard_publish_requires_service_filter_for_chart_covered():
    coverage = _read(DASHBOARD_COVERAGE_MODEL)
    assert "service.name" in coverage, "chart COVERED must require the service.name filter"
    assert "sf_service" in coverage, "must treat sf_service as equivalent to service.name"
    assert "options.type" in coverage, "chart match must compare the live options.type"


def test_dashboard_publish_only_skips_http_500_and_forbids_bare_except():
    """Inverse of the detector test: the dashboard publish skill + shared splunk-api.md carry the
    explicit prohibition string ("never a bare except Exception"), so assert the guidance is
    PRESENT here rather than absent."""
    skill = _read(SPLUNK_DASHBOARD_PUBLISH)
    api = _read(SPLUNK_API_REF)
    assert "500" in skill and "500" in api, "skip-on-500 behavior must be documented"
    assert "Only HTTP 500 is skipped" in api, "splunk-api.md must state only 500 is skipped"
    # The shared ref forbids swallowing everything in a bare except.
    assert "except Exception" in api, "splunk-api.md must name the bare-except anti-pattern it forbids"
    assert "do **not**" in api.lower() or "do not" in api.lower(), (
        "splunk-api.md must explicitly forbid the bare except"
    )


def test_dashboard_publish_requires_confirmation_before_create():
    text = _read(SPLUNK_DASHBOARD_PUBLISH)
    assert "confirm" in text.lower() or "confirmation" in text.lower(), (
        "publish SKILL.md must require explicit user confirmation before any create"
    )
    # The confirmation diff is shown before writes.
    assert "before any write" in text.lower() or "before any writes" in text.lower(), (
        "publish SKILL.md must gate the confirmation diff before any write"
    )


def test_dashboard_publish_normalizes_program_text_before_create():
    text = _read(SPLUNK_DASHBOARD_PUBLISH)
    assert "dedent" in text.lower(), "must dedent the <<-EOF heredoc before POSTing programText"
    assert "<<-EOF" in text or "<<-eof" in text.lower(), "must call out the indented-heredoc hazard"
    assert "${var." in text, "must resolve every ${var.*} before the POST"
    # The shared normalization ref backs this and documents the field mapping.
    norm = _read(TERRAFORM_NORMALIZATION_REF)
    assert "dedent" in norm.lower()
    assert "${var." in norm
    assert "programText" in norm and "program_text" in norm


def test_dashboard_publish_writes_resumable_ledger():
    text = _read(SPLUNK_DASHBOARD_PUBLISH)
    assert "dashboard-sync.md" in text, "must write .observe/dashboard-sync.md as the resume ledger"
    ledger = _read(LEDGER_TEMPLATE_REF)
    assert "dashboard-sync.md" in ledger, "shared ledger template must cover dashboard-sync.md"


# ---------------------------------------------------------------------------
# Requirement #2 — every verdict carries a concrete, non-empty Reason
# ---------------------------------------------------------------------------


def test_explicit_reason_required_per_verdict():
    """User requirement: every group/dashboard/chart COVERED/GAP/UNCERTAIN verdict must
    record a concrete, non-empty Reason, shown in the confirmation diff and persisted in the
    ledger Reason column. Asserted across all four files that carry the contract."""
    publish = _normalized(SPLUNK_DASHBOARD_PUBLISH)
    assert "non-empty Reason on every row" in publish, (
        "confirmation diff must require a non-empty Reason on every row"
    )
    assert "Reason" in publish

    ledger = _read(LEDGER_TEMPLATE_REF)
    assert "Reason column is required and must be non-empty" in ledger, (
        "ledger template must mandate a non-empty Reason column"
    )

    tree = _read(COVERAGE_DECISION_TREE_REF)
    assert "never-empty Reason per verdict is a hard requirement" in tree, (
        "decision tree must state the never-empty Reason hard requirement"
    )
    assert "criterion that fired" in tree or "Record every criterion" in tree, (
        "decision tree must require recording every criterion that fired"
    )


def test_reason_examples_are_concrete_not_generic():
    """The reasons must name the live object + the exact match basis, not a bare 'matched'."""
    publish = _normalized(SPLUNK_DASHBOARD_PUBLISH)
    # A concrete COVERED reason cites metric + filter + type + the live chart id.
    assert "all matched live chart" in publish, "COVERED reason example must cite the matched live chart"
    # The skill must explicitly reject a generic reason note.
    assert "generic note" in publish.lower(), (
        "publish SKILL.md must explicitly reject a generic reason note"
    )

    coverage = _normalized(DASHBOARD_COVERAGE_MODEL)
    assert "chart COVERED:" in coverage
    assert "panel GAP:" in coverage or "GAP:" in coverage
    assert "UNCERTAIN:" in coverage


# ---------------------------------------------------------------------------
# M3 — token-secrecy guidance is guarded by tests
# ---------------------------------------------------------------------------


def test_splunk_access_token_secrecy_prose_in_shared_api_ref():
    """The REST auth secrecy contract must be present in splunk-api.md so that a
    future edit deleting it is caught before merge. Guards against a regression
    where the agent would start echoing the live token into ledger files."""
    text = _read(SPLUNK_API_REF)
    # These exact phrases must be present; any edit weakening them turns red.
    assert "never echo it" in text, "splunk-api.md must say 'never echo it'"
    assert "never write it" in text, "splunk-api.md must say 'never write it'"
    assert "never place it in prompt context" in text, (
        "splunk-api.md must say 'never place it in prompt context'"
    )
    assert "SPLUNK_ACCESS_TOKEN" in text, "secrecy prose must name SPLUNK_ACCESS_TOKEN"
    assert "X-SF-Token" in text, "secrecy prose must name the header X-SF-Token"


def test_splunk_dashboard_publish_skill_references_token_secrecy():
    """The publish skill itself must repeat the token-secrecy instruction so it is
    present in the model's loaded skill context, not only in the shared ref."""
    text = _read(SPLUNK_DASHBOARD_PUBLISH)
    # The skill must instruct the agent to never log or write the token.
    assert "never log" in text.lower() or "never write it to the ledger" in text.lower(), (
        "splunk-dashboard-publish/SKILL.md must explicitly forbid logging/writing SPLUNK_ACCESS_TOKEN"
    )
    assert "SPLUNK_ACCESS_TOKEN" in text, "publish SKILL.md must name SPLUNK_ACCESS_TOKEN"


def test_m6_500_counter_separate_from_empty_counter():
    """Regression guard for m6: the pagination loop must use separate counters
    for 500s and empty pages so a run of 500s before valid pages does not
    terminate pagination prematurely."""
    text = _read(SPLUNK_API_REF)
    # The fixed code has two distinct counter variables.
    assert "consecutive_500" in text, (
        "splunk-api.md must track HTTP 500s in a separate counter from consecutive_empty"
    )
    # The 500 branch must NOT increment consecutive_empty.
    # Check the comment that documents this invariant.
    assert "Do NOT increment consecutive_empty" in text or "do NOT increment consecutive_empty" in text, (
        "splunk-api.md 500-handler must document that it does not increment consecutive_empty"
    )


def test_m2_409_includes_get_for_existing_id():
    """m2 regression guard: a chart POST 409 must include a step to GET the
    existing chart's ID so it can be referenced in the dashboard charts[] array."""
    text = _read(SPLUNK_API_REF)
    # The 409 row now describes fetching the existing object's id.
    assert "GET /v2/" in text and "409" in text, (
        "splunk-api.md 409 row must instruct fetching the existing object's id"
    )
    assert "reuse" in text.lower(), "409 handling must say to reuse the existing id"


def test_m2_put_dashboard_documented_for_chart_gap():
    """M2 regression guard: adding a chart to a COVERED dashboard must use PUT,
    not recreate the whole dashboard."""
    api_text = _read(SPLUNK_API_REF)
    assert "PUT /v2/dashboard/" in api_text, (
        "splunk-api.md must document PUT /v2/dashboard/{id} for adding charts to a covered dashboard"
    )
    assert "duplicate" in api_text.lower(), (
        "splunk-api.md PUT section must warn against recreating (would produce a duplicate)"
    )

    publish_text = _read(SPLUNK_DASHBOARD_PUBLISH)
    assert "PUT /v2/dashboard" in publish_text, (
        "publish SKILL.md Step 6 must reference PUT /v2/dashboard for chart-level GAPs in covered dashboards"
    )

    coverage_text = _read(DASHBOARD_COVERAGE_MODEL)
    assert "PUT /v2/dashboard" in coverage_text, (
        "dashboard-coverage-model.md Example 2 must reference PUT, not recreate"
    )
    assert "duplicate" in coverage_text.lower(), (
        "coverage model must warn that recreating the whole dashboard produces a duplicate"
    )
