"""Deterministic checks for the splunk-dashboard and splunk-dashboard-sync skills.

Sibling to ``test_genai_skill_guidance.py`` (same helpers, same style). These tests
pin the invariants of the dashboard generate/sync skill pair and the shared
``skills/references/`` files the detector skills were light-refactored onto.

NOTE: the dashboard skills and the shared reference files legitimately use a
concrete example service name ("checkout") in worked examples, so they are
intentionally NOT subjected to the provider-neutral "stays generic" blocked-term
guard in ``test_genai_skill_guidance.py``. That guard remains scoped to the GenAI
readiness reference + detector skills, where concrete names do not belong.
"""

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

# Dashboard sync skill.
SPLUNK_DASHBOARD_SYNC = SKILLS_DIR / "splunk-dashboard-sync" / "SKILL.md"
SPLUNK_DASHBOARD_SYNC_REFS = SKILLS_DIR / "splunk-dashboard-sync" / "references"
DASHBOARD_COVERAGE_MODEL = SPLUNK_DASHBOARD_SYNC_REFS / "dashboard-coverage-model.md"

# Detector skills the shared refs were extracted from (light-refactor guards).
SPLUNK_SYNC = SKILLS_DIR / "splunk-sync" / "SKILL.md"
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
    assert SPLUNK_DASHBOARD_SYNC.exists(), "skills/splunk-dashboard-sync/SKILL.md not found"
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


def test_dashboard_sync_skill_frontmatter():
    text = _read(SPLUNK_DASHBOARD_SYNC)
    assert "name: splunk-dashboard-sync" in text, "SKILL.md must declare name: splunk-dashboard-sync"
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


def test_detector_sync_skill_still_reaches_shared_references():
    """Light refactor: splunk-sync/SKILL.md now includes the shared refs by a plain
    relative path, and that path must resolve to the real shared file."""
    text = _read(SPLUNK_SYNC)
    for relpath, target in (
        ("../references/splunk-api.md", SPLUNK_API_REF),
        ("../references/terraform-normalization.md", TERRAFORM_NORMALIZATION_REF),
        ("../references/ledger-template.md", LEDGER_TEMPLATE_REF),
        ("../references/coverage-decision-tree.md", COVERAGE_DECISION_TREE_REF),
    ):
        assert relpath in text, f"splunk-sync/SKILL.md must include {relpath}"
        assert (SPLUNK_SYNC.parent / relpath).resolve() == target.resolve()


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

    sync = _read(SPLUNK_DASHBOARD_SYNC)
    for relpath, target in (
        ("../references/splunk-api.md", SPLUNK_API_REF),
        ("../references/terraform-normalization.md", TERRAFORM_NORMALIZATION_REF),
        ("../references/ledger-template.md", LEDGER_TEMPLATE_REF),
        ("../references/coverage-decision-tree.md", COVERAGE_DECISION_TREE_REF),
    ):
        assert relpath in sync, f"splunk-dashboard-sync/SKILL.md must include {relpath}"
        assert (SPLUNK_DASHBOARD_SYNC.parent / relpath).resolve() == target.resolve()


def test_shared_signalflow_reference_omits_detector_tail_for_charts():
    """Dashboard charts reuse the data().agg().publish() fragment but must stop before the
    detector-only detect()/when()/threshold() tail."""
    text = _read(SIGNALFLOW_PATTERNS_REF)
    assert "data('<metric_name>'" in text, "shared fragment must show the data('<metric>') call"
    assert ".publish(" in text
    assert "service.name" in text and "sf_service" in text
    assert "detect()" in text or "detect(" in text, "must contrast against the detector detect() tail"


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
    assert "$splunk-dashboard-sync" in text, "must hand off to the sync skill"


def test_dashboard_skill_marks_api_token_sensitive():
    text = _read(SPLUNK_DASHBOARD)
    assert "sensitive = true" in text, "api_token Terraform variable must be sensitive = true"


def test_dashboard_skill_emits_preview_sidecar_contract():
    text = _read(SPLUNK_DASHBOARD)
    assert ".observe/dashboards.preview.json" in text, "must write the Observer preview sidecar"
    assert "schemaVersion" in text, "preview sidecar must declare schemaVersion"
    # The six chart types the Observer renderer understands.
    for chart_type in ("time_series", "single_value", "list", "heatmap", "text", "event"):
        assert chart_type in text, f"preview sidecar chartType vocabulary missing: {chart_type}"


def test_dashboard_classification_defines_grid_and_chart_vocabulary():
    text = _read(DASHBOARD_CLASSIFICATION)
    # RED-style grouping with the dashboard chart-type vocabulary.
    for chart_type in ("single_value", "time_series"):
        assert chart_type in text
    for signal in ("Latency", "Error", "Throughput", "Saturation"):
        assert signal in text, f"classification missing RED/saturation signal: {signal}"


def test_dashboard_templates_map_hcl_chart_resources_to_rest_types():
    text = _read(DASHBOARD_TEMPLATES)
    # The HCL resource name vs the REST options.type — the chart-first sync depends on this.
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
# Sync skill — wire casing, chart-first ordering, orphan recovery
# ---------------------------------------------------------------------------


def test_dashboard_sync_reads_terraform_dashboards_tf():
    text = _read(SPLUNK_DASHBOARD_SYNC)
    assert "dashboards.tf" in text, "must parse .observe/terraform/dashboards.tf"
    assert "program_text" in text or "programText" in text


def test_dashboard_sync_uses_camel_case_rest_wire_names():
    """REST bodies use camelCase; HCL attributes stay snake_case. Both appear by design,
    so this asserts the camelCase wire names exist (mirrors the detectorOrigin casing test)
    and that the skill distinguishes the HCL spelling from the REST spelling."""
    text = _read(SPLUNK_DASHBOARD_SYNC)
    for wire in ("programText", "chartId", "groupId"):
        assert wire in text, f"sync SKILL.md must use camelCase REST wire name: {wire}"
    # The HCL spellings coexist (parsed from Terraform), and the skill must call out the mapping.
    assert "program_text" in text and "dashboard_group" in text, (
        "sync SKILL.md must show the HCL snake_case spellings it parses"
    )


def test_dashboard_sync_documents_chart_first_ordering():
    text = _read(SPLUNK_DASHBOARD_SYNC)
    assert "chart-first" in text, "must document chart-first creation ordering"
    assert "POST /v2/chart" in text, "must POST charts first to collect IDs"
    assert "POST /v2/dashboard" in text, "must POST the dashboard referencing chart IDs"
    # Chart create body shape that yields the referencible IDs.
    assert "packageSpecifications" in text
    assert "TimeSeriesChart" in text or "SingleValue" in text


def test_dashboard_sync_documents_orphan_chart_recovery():
    text = _read(SPLUNK_DASHBOARD_SYNC)
    assert "Orphan-chart recovery" in text or "orphan" in text.lower(), (
        "must document orphan-chart recovery when the dashboard POST fails after charts exist"
    )
    assert "DELETE /v2/chart" in text, "orphan recovery must clean up created charts"


def test_dashboard_sync_classifies_three_levels():
    text = _read(SPLUNK_DASHBOARD_SYNC)
    for status in ("COVERED", "GAP", "UNCERTAIN"):
        assert status in text, f"sync SKILL.md missing verdict status: {status}"
    coverage = _read(DASHBOARD_COVERAGE_MODEL)
    assert "three levels" in coverage, "coverage model must classify group/dashboard/chart"
    for status in ("COVERED", "GAP", "UNCERTAIN"):
        assert status in coverage


def test_dashboard_sync_requires_service_filter_for_chart_covered():
    coverage = _read(DASHBOARD_COVERAGE_MODEL)
    assert "service.name" in coverage, "chart COVERED must require the service.name filter"
    assert "sf_service" in coverage, "must treat sf_service as equivalent to service.name"
    assert "options.type" in coverage, "chart match must compare the live options.type"


def test_dashboard_sync_only_skips_http_500_and_forbids_bare_except():
    """Inverse of the detector test: the dashboard skill + shared splunk-api.md carry the
    explicit prohibition string ("never a bare except Exception"), so assert the guidance is
    PRESENT here rather than absent."""
    skill = _read(SPLUNK_DASHBOARD_SYNC)
    api = _read(SPLUNK_API_REF)
    assert "500" in skill and "500" in api, "skip-on-500 behavior must be documented"
    assert "Only HTTP 500 is skipped" in api, "splunk-api.md must state only 500 is skipped"
    # The shared ref forbids swallowing everything in a bare except.
    assert "except Exception" in api, "splunk-api.md must name the bare-except anti-pattern it forbids"
    assert "do **not**" in api.lower() or "do not" in api.lower(), (
        "splunk-api.md must explicitly forbid the bare except"
    )


def test_dashboard_sync_requires_confirmation_before_create():
    text = _read(SPLUNK_DASHBOARD_SYNC)
    assert "confirm" in text.lower() or "confirmation" in text.lower(), (
        "sync SKILL.md must require explicit user confirmation before any create"
    )
    # The confirmation diff is shown before writes.
    assert "before any write" in text.lower() or "before any writes" in text.lower(), (
        "sync SKILL.md must gate the confirmation diff before any write"
    )


def test_dashboard_sync_normalizes_program_text_before_create():
    text = _read(SPLUNK_DASHBOARD_SYNC)
    assert "dedent" in text.lower(), "must dedent the <<-EOF heredoc before POSTing programText"
    assert "<<-EOF" in text or "<<-eof" in text.lower(), "must call out the indented-heredoc hazard"
    assert "${var." in text, "must resolve every ${var.*} before the POST"
    # The shared normalization ref backs this and documents the field mapping.
    norm = _read(TERRAFORM_NORMALIZATION_REF)
    assert "dedent" in norm.lower()
    assert "${var." in norm
    assert "programText" in norm and "program_text" in norm


def test_dashboard_sync_writes_resumable_ledger():
    text = _read(SPLUNK_DASHBOARD_SYNC)
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
    sync = _normalized(SPLUNK_DASHBOARD_SYNC)
    assert "non-empty Reason on every row" in sync, (
        "confirmation diff must require a non-empty Reason on every row"
    )
    assert "Reason" in sync

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
    sync = _normalized(SPLUNK_DASHBOARD_SYNC)
    # A concrete COVERED reason cites metric + filter + type + the live chart id.
    assert "all matched live chart" in sync, "COVERED reason example must cite the matched live chart"
    # The skill must explicitly reject a generic reason note.
    assert "generic note" in sync.lower(), (
        "sync SKILL.md must explicitly reject a generic reason note"
    )

    coverage = _normalized(DASHBOARD_COVERAGE_MODEL)
    assert "chart COVERED:" in coverage
    assert "panel GAP:" in coverage or "GAP:" in coverage
    assert "UNCERTAIN:" in coverage
