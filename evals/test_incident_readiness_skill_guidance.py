"""Deterministic checks for incident-readiness skill guidance."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
INCIDENT_REF = SKILLS_DIR / "references" / "incident-readiness.md"
SPLUNK_CONFIGURE = SKILLS_DIR / "splunk-configure" / "SKILL.md"
SPLUNK_CONFIGURE_REFS = SKILLS_DIR / "splunk-configure" / "references"


def _read(path: Path) -> str:
    assert path.exists(), f"Expected file not found: {path}"
    return path.read_text()


def _squash(text: str) -> str:
    return " ".join(text.split())


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
        "deployment.environment.name",
        "cloud.region",
        "cloud.platform",
        "container.image.name",
        "container.image.tags",
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
        "Synthetic/canary workflow checks",
        "input size/complexity bucket",
        "metadata count when relevant",
        "offline/derived data",
        "schema/migration version when present",
        "fallback target readiness",
        "compatibility failure class",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_incident_reference_prefers_current_resource_semconv_names():
    text = _squash(_read(INCIDENT_REF))
    assert "deployment.environment.name" in text
    assert "`deployment.environment`" in text
    assert "legacy or custom" in text
    assert "do not newly emit them" in text
    for standard_name in [
        "cloud.region",
        "cloud.platform",
        "container.image.name",
        "container.image.tags",
    ]:
        assert standard_name in text


def test_java_agent_example_uses_current_environment_attribute():
    java = _read(SKILLS_DIR / "otel-instrument" / "references" / "languages" / "java.md")
    assert "deployment.environment.name=production" in java
    assert "deployment.environment=production" not in java


def test_python_auto_instrumentation_example_uses_current_environment_attribute():
    python = _read(SKILLS_DIR / "otel-instrument" / "references" / "languages" / "python.md")
    assert "deployment.environment.name=production" in python
    assert "deployment.environment=production" not in python


def test_audit_and_instrument_load_incident_reference():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    for text in (audit, instrument):
        assert "../references/incident-readiness.md" in text
        assert "incident-readiness" in text
        assert "faster incident detection" in text


def test_instrument_allows_recommended_semconv_readiness_signals():
    instrument = _squash(_read(SKILLS_DIR / "otel-instrument" / "SKILL.md"))
    required_terms = [
        "recommended optional signals",
        "approved readiness or verification requirement",
        "service can observe the value accurately",
        "privacy/cardinality rules permit it",
    ]
    missing = [term for term in required_terms if term not in instrument]
    assert not missing


def test_instrument_requires_signal_level_mttd_role_inventory():
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    report_contract = _read(SKILLS_DIR / "references" / "report-flow-contract.md")
    required_terms = [
        "### Incident Readiness Signal Roles",
        "| Surface | Exact signal | Role | Detector use / reason | Proof | Remaining owner / prerequisite |",
        "`MTTD-improving`",
        "`localization-only`",
        "`provider/platform-owned`",
        "`uncovered`",
        "one row per exact",
        "not another gap ledger",
    ]
    for text in (instrument, report_contract):
        missing = [term for term in required_terms if term not in text]
        assert not missing


def test_instrument_requires_multi_process_and_concurrency_proof():
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    incident = _read(INCIDENT_REF)
    required_terms = [
        "distinct, operator-overridable `service.name` default",
        "actual entrypoint or startup hook",
        "must not initialize",
        "explicitly record failure outcome",
        "enqueue success/failure and worker task success/failure",
        "AST/source-string checks do not prove telemetry",
        "`go test -race`",
        "normal `go test` pass",
        "toolchain/platform blocker",
        "drive each incident state to a non-default value",
        "metric registration, name presence, or a zero-value observation",
        "saturated or deterministic backpressure path",
        "nonzero depth and oldest-age values",
        "keep the verification result `Partial`",
    ]
    combined = _squash(f"{instrument}\n{incident}")
    missing = [term for term in required_terms if term not in combined]
    assert not missing
    for required in [
        "distinct, operator-overridable `service.name` default",
        "`go test -race`",
    ]:
        assert required in _squash(instrument)
        assert required in _squash(incident)


def test_incident_freshness_age_requires_demand_or_cadence_evidence():
    instrument = _squash(_read(SKILLS_DIR / "otel-instrument" / "SKILL.md")).casefold()
    incident = _squash(_read(INCIDENT_REF)).casefold()
    required_terms = [
        "healthy idle",
        "expected cadence",
        "pending/backlogged work",
        "accepted input",
        "localization-only",
        "backlog, queue delay, or missed schedule",
    ]
    for text in (instrument, incident):
        missing = [term for term in required_terms if term not in text]
        assert not missing


def test_instrument_converts_incident_readiness_audit_to_patchable_work():
    text = _squash(_read(SKILLS_DIR / "otel-instrument" / "SKILL.md"))
    required_terms = [
        "Audit-Driven Incident Readiness",
        "partial or missing readiness row",
        "matching prioritized `## Gaps` row",
        "every safe app-owned incident gap",
        "`required` / `default`",
        "`recommended` / `fix all`",
        "Do not choose one representative gap",
        "add or prove the applicable surfaces",
        "no placeholder instrument",
        "MTTD-improving",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_instrument_requires_gap_closure_matrix_for_incident_readiness():
    text = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    required_terms = [
        "Audit-Driven Gap Closure",
        "prioritized `## Gaps` table as the implementation queue",
        "one row per prioritized audit gap",
        "Working / Not working / Not proven / Not configured / Deferred",
        "all untouched rows",
        "manual decision",
        "owner-map the exact prerequisite",
        "required signals",
        "remaining signals",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_instrument_requires_incident_evidence_gap_closure():
    skill = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    reference = _squash(_read(INCIDENT_REF))
    required_skill_terms = [
        "Incident-Evidence Mode",
        "failure mechanism",
        "owning code or platform surface",
        "MTTD-improving",
        "queue depth/lag/oldest age",
        "stream/long-lived connection",
        "auth/edge",
        "scheduled-job last success",
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
        "missing or stale output",
        "dependency target loss",
        "Jobs and offline/derived data outputs",
        "expected-vs-running version",
    ]
    missing_reference = [term for term in required_reference_terms if term not in reference]
    assert not missing_reference


def test_instrument_requires_generic_runtime_surface_closure():
    skill = _squash(_read(SKILLS_DIR / "otel-instrument" / "SKILL.md"))
    reference = _squash(_read(INCIDENT_REF))
    required_skill_terms = [
        "load `../references/incident-readiness.md`",
        "queue depth/lag/oldest age",
        "worker/pool saturation",
        "stream/long-lived connection",
        "active count",
        "send/write failure",
        "A row cannot be `Working` while any required signal is absent",
    ]
    required_reference_terms = [
        "Executors and queues",
        "queue remaining/capacity",
        "active or inflight work",
        "rejected/shed work",
        "Streams and long-lived connections",
        "open/connect",
        "stop/detach/keepalive",
        "connections/channels/streams",
    ]
    assert not [term for term in required_skill_terms if term not in skill]
    assert not [term for term in required_reference_terms if term not in reference]


def test_instrument_skips_custom_prompt_for_incident_readiness_requests():
    text = _squash(_read(SKILLS_DIR / "otel-instrument" / "SKILL.md"))
    required_terms = [
        "Skip this prompt",
        "incident-readiness or GenAI/LLM",
        "Audit-Driven Readiness path",
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
        "customer",
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


def test_splunk_configure_consumes_current_main_gaps_section():
    skill = _read(SPLUNK_CONFIGURE)
    required_terms = [
        "prioritized `## Gaps` table",
        "instrumentation prerequisite",
        "Instrumentation Prerequisites",
        "Do not generate a detector for a missing or unverified signal",
    ]
    missing = [term for term in required_terms if term not in skill]
    assert not missing


def test_audit_maps_incident_readiness_to_current_gap_contract():
    audit = _squash(_read(SKILLS_DIR / "otel-audit" / "SKILL.md"))
    report_contract = _squash(_read(SKILLS_DIR / "references" / "report-flow-contract.md"))
    required_terms = [
        "### Incident Readiness",
        "single prioritized `## Gaps` table",
        "`Area` is the stable human-readable gap identity",
        "`Required fix` names every required signal",
        "mapped acceptance scenarios",
        "Split a gap when required signals have different owners",
        "Do not mark a partial surface covered",
    ]
    missing = [term for term in required_terms if term not in audit]
    assert not missing
    assert "## Gap Ledger" not in audit
    required_contract_terms = [
        "one `### Incident Readiness` subsection",
        "Every `partial` or `missing` row",
        "`Area` cell is identical",
        "not a second top-level gap ledger",
        "reconcile those rows through the matching prioritized gaps",
    ]
    assert not [term for term in required_contract_terms if term not in report_contract]


def test_instrument_reconciles_current_audit_gap_contract():
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    required_terms = [
        "Audit-Driven Gap Closure",
        "prioritized `## Gaps` table as the implementation queue",
        "Build an internal closure matrix before editing",
        "area -> priority -> required fix -> instrument mode -> planned action",
        "one row per prioritized audit gap",
        "exact audit `Area` value",
        "Not working",
        "Not proven",
        "Not configured",
        "Deferred",
    ]
    missing = [term for term in required_terms if term not in instrument]
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
        "audit report contains no metrics",
        "do not generate detector or",
        "continue processing gaps and readiness sections",
        "incident-readiness",
        ".observe/detectors.md",
        "alert coverage matrix",
    ]
    missing = [term for term in required_terms if term not in skill]
    assert not missing


def test_splunk_configure_consumes_incident_readiness_section():
    skill = _read(SPLUNK_CONFIGURE)
    required_terms = [
        "Parse `### Incident Readiness` inside `## Current Instrumentation`",
        "Join every partial or missing row to the prioritized `## Gaps` row",
        "legacy top-level `## Incident Readiness`",
        "For every incident-readiness area",
        "unless equivalent metrics are source-backed and proven",
        "Do not generate a detector for a missing or unverified signal",
        "audit's prioritized `## Gaps` table",
    ]
    missing = [term for term in required_terms if term not in skill]
    assert not missing


def test_splunk_configure_owns_detector_reliability_handoff():
    skill = _read(SPLUNK_CONFIGURE)
    classification = _read(SPLUNK_CONFIGURE_REFS / "detector-classification.md")
    templates = _read(SPLUNK_CONFIGURE_REFS / "terraform-templates.md")
    required_terms = [
        "detector reliability evidence",
        "missed, flapping, auto-resolved, or no-data alerts",
        "alert-coverage-audit",
        "Do not ask app instrumentation",
        "Do not generate service metric Terraform",
    ]
    combined = "\n".join((skill, classification, templates))
    missing = [term for term in required_terms if term not in combined]
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
        "deployment.environment.name",
        "cloud.region",
        "cloud.platform",
        "container.image.name",
        "container.image.tags",
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
    assert 'property       = "deployment.environment.name"' in templates
    assert "newly instrumented services should emit `deployment.environment.name`" in templates
    for term in ["e.g. us1, eu0, lab0", "e.g. us1, eu0", "us1", "eu0", "lab0"]:
        assert term not in skill
        assert term not in templates


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


def test_splunk_configure_prevents_generic_keywords_from_shadowing_fault_domains():
    classification = _read(SPLUNK_CONFIGURE_REFS / "detector-classification.md")
    templates = _read(SPLUNK_CONFIGURE_REFS / "terraform-templates.md")
    required_classification_terms = [
        "`availability` or `unavailable` alone is not sufficient",
        "dependency-specific",
        "`operation` alone is not sufficient",
        "rather than a client or dependency",
        "freshness/newest-event-age/event-age/ingest-lag/processing-lag/data-age/staleness",
        "There is no universal count threshold for queue depth or consumer lag",
        "Use `85` only for a normalized percentage",
        "metric matches the Capacity Saturation rule",
        "capacity/utilization/cpu/memory/heap/",
        "a gauge/up-down counter",
        "cumulative-CPU-time exclusion",
    ]
    assert not [
        term for term in required_classification_terms if term not in classification
    ]
    assert "85% only for normalized saturation" in templates


def test_dashboard_group_template_includes_provider_required_description():
    templates = _read(SPLUNK_CONFIGURE_REFS / "terraform-templates.md")
    dashboard_shape = templates.split("## Dashboard Terraform Shape", 1)[1]
    assert 'resource "signalfx_dashboard_group" "service"' in dashboard_shape
    assert 'description = "Service health dashboards for ${var.service_name}"' in dashboard_shape


def test_audit_keeps_current_main_report_contract():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    current_report_terms = [
        "## Signal Flow",
        "### Component Flow Map",
        "## Audit Evidence",
        "## Current Instrumentation",
        "| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |",
        "### Test Environments",
        "### Acceptance Scenarios",
    ]
    assert not [term for term in current_report_terms if term not in audit]
    assert "| Priority | Area | Gap | User Impact | Fix | Instrument Mode |" not in audit


def test_incident_readiness_guidance_stays_generic_and_non_genai():
    shared_skill_paths = [
        SKILLS_DIR / "otel-audit" / "SKILL.md",
        SKILLS_DIR / "otel-instrument" / "SKILL.md",
        SPLUNK_CONFIGURE,
        SPLUNK_CONFIGURE_REFS / "detector-classification.md",
        SPLUNK_CONFIGURE_REFS / "terraform-templates.md",
    ]
    genai_terms = [
        "GenAI",
        "LLM",
        "gen_ai",
        "RAG",
    ]
    assert not [term for term in genai_terms if term in _read(INCIDENT_REF)]

    blocked_project_terms = [
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
        "US1",
        "EU0",
        "us1",
        "eu0",
        "lab0",
        "checkout",
        "missing report output",
        "active-node",
        "active node",
        "Decision or delivery workflow",
        "decision or delivery workflow",
        "workflow delivery/evaluation",
    ]
    for path in [INCIDENT_REF, *shared_skill_paths]:
        text = _read(path)
        bad = [term for term in blocked_project_terms if term in text]
        assert not bad, f"{path} contains project-specific terms: {bad}"
