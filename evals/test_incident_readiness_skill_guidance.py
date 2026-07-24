"""Deterministic checks for incident-readiness skill guidance."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
INCIDENT_REF = SKILLS_DIR / "references" / "incident-readiness.md"
REPORT_FLOW = SKILLS_DIR / "references" / "report-flow-contract.md"
AUDIT_SKILL = SKILLS_DIR / "otel-audit" / "SKILL.md"
INSTRUMENT_DIR = SKILLS_DIR / "otel-instrument"
INSTRUMENT_SKILL = INSTRUMENT_DIR / "SKILL.md"
INSTRUMENT_REPORT = (
    INSTRUMENT_DIR / "references" / "instrumentation-report.md"
)
SPLUNK_CONFIGURE = SKILLS_DIR / "splunk-configure" / "SKILL.md"
SPLUNK_CONFIGURE_REFS = SKILLS_DIR / "splunk-configure" / "references"
CONFIGURE_PROGRESSIVE_REFS = (
    SPLUNK_CONFIGURE_REFS / "canonical-input-contract.md",
    SPLUNK_CONFIGURE_REFS / "dashboard-output-contract.md",
    SPLUNK_CONFIGURE_REFS / "configure-report-contract.md",
    SPLUNK_CONFIGURE_REFS / "detector-classification.md",
    SPLUNK_CONFIGURE_REFS / "incident-detector-classification.md",
    SPLUNK_CONFIGURE_REFS / "genai-detector-classification.md",
    SPLUNK_CONFIGURE_REFS / "terraform-templates.md",
    SPLUNK_CONFIGURE_REFS / "readiness-detector-templates.md",
    SPLUNK_CONFIGURE_REFS / "dashboard-terraform-contract.md",
    SPLUNK_CONFIGURE_REFS / "readiness-report-contract.md",
)


def _read(path: Path) -> str:
    assert path.exists(), f"Expected file not found: {path}"
    text = path.read_text()
    if path == SPLUNK_CONFIGURE:
        text += "\n" + "\n".join(reference.read_text() for reference in CONFIGURE_PROGRESSIVE_REFS)
    return text


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
    audit = _read(AUDIT_SKILL)
    instrument = _read(SKILLS_DIR / "otel-instrument" / "SKILL.md")
    for text in (audit, instrument):
        assert "../references/incident-readiness.md" in text
        assert "incident-readiness" in text
        assert "faster incident detection" in text


def test_audit_excludes_general_operational_hygiene_from_otel_findings():
    audit = _squash(_read(AUDIT_SKILL))
    incident = _squash(_read(INCIDENT_REF))
    report_flow = _squash(_read(REPORT_FLOW))

    required_audit_terms = [
        "OTel finding boundary",
        "If no OTel-specific closure remains, omit the finding",
        "must not become OTel findings merely because telemetry could observe them",
        "Do not relabel those outputs as `configuration` expected telemetry",
        "Omit unrelated contract, documentation, link, policy, security, or product debt from every audit section",
        "Do not promote service code, configuration, contract, documentation, policy, or general test work into its own OTel finding",
        "A `configuration` item may describe only OTel SDK",
        "Every `configuration` item must include `configuration_scope`",
        "`otel-sdk`, `otel-resource`, `otel-exporter`, `otel-sampling`, `otel-propagation`, `otel-instrumentation`, or `otel-collector`",
        "Configuration is insufficient by itself",
        "Contract lint, link validation, behavior-only tests, and policy approval without telemetry proof are not audit verification scenarios",
        "must have an unresolved (`proposed`, `approved`, or `in_progress`) finding with an identical `area`",
        "Validate incident `area` and `required_signals`, plus GenAI `surface`, `required_signals`, and `acceptance_criteria`, as OTel closure fields",
    ]
    assert not [term for term in required_audit_terms if term not in audit]

    required_incident_terms = [
        "telemetry-readiness reference, not a general production-readiness audit",
        "leaves no OTel closure, omit the surface",
        "A general policy may constrain or explain telemetry, but it cannot block or become an OTel finding",
        "omit the candidate until the remaining choice is telemetry-specific",
        "Omit unrelated contract, documentation, link, policy, security, or product debt from all audit sections",
        "do not make an OTel finding responsible for choosing or enforcing product semantics",
    ]
    assert not [term for term in required_incident_terms if term not in incident]

    required_flow_terms = [
        "An OTel finding ID is not a general operational task container",
        "If no independently useful OTel closure remains, omit the finding",
        "neither mode makes a general operational task an OTel finding",
        "Omit unrelated non-telemetry debt from summary, top-level evidence, readiness, anti-patterns, recommendations, findings, and scenarios",
        "Apply instrument modes only after the OTel finding boundary",
        "Omit non-telemetry service code, configuration, contract, documentation, policy, or general test work instead of splitting it into another finding",
        "`done`, `rejected`, and `deferred` findings do not satisfy an unresolved readiness row",
        "Render authored Incident and GenAI telemetry-readiness tables as visible panels",
    ]
    assert not [term for term in required_flow_terms if term not in report_flow]


def test_audit_schema_v2_non_executable_findings_are_only_prerequisites():
    audit = _squash(_read(AUDIT_SKILL))
    report_flow = _squash(_read(REPORT_FLOW))

    for text in (audit, report_flow):
        for term in (
            "Dependency direction is executable finding -> prerequisite",
            "transitively required by at least one executable finding",
            "orphan non-executable findings",
        ):
            assert term in text

    assert (
        "In schema v2, every `manual decision` and `external follow-up` must be "
        "in the transitive dependency closure of at least one `default`/`fix all` finding"
        in audit
    )
    assert (
        "Keep a schema-v2 `manual decision` or `external follow-up` only when it is "
        "transitively required by at least one executable finding"
        in report_flow
    )


def test_instrument_allows_recommended_semconv_readiness_signals():
    instrument = _squash(_read(SKILLS_DIR / "otel-instrument" / "SKILL.md"))
    required_terms = [
        "Use only stable semantic-convention signals where defined",
        "Start with signals needed for selected closure",
        "add broader signals only when an approved requirement needs them",
        "accuracy, privacy, and cardinality permit them",
    ]
    missing = [term for term in required_terms if term not in instrument]
    assert not missing


def test_instrument_requires_signal_level_mttd_role_inventory():
    instrument = _read(INSTRUMENT_SKILL)
    instrumentation_report = _squash(_read(INSTRUMENT_REPORT))
    report_contract = _squash(
        _read(SKILLS_DIR / "references" / "report-flow-contract.md")
    )
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
    assert "references/instrumentation-report.md" in instrument
    for text in (instrumentation_report, report_contract):
        missing = [term for term in required_terms if term not in text]
        assert not missing


def test_instrument_requires_multi_process_and_concurrency_proof():
    instrument = _read(INSTRUMENT_SKILL)
    incident = _read(INCIDENT_REF)
    required_terms = [
        "distinct, operator-overridable `service.name` default",
        "real entrypoint or startup hook",
        "must not initialize",
        "explicitly record failure outcome",
        "enqueue success/failure and worker task success/failure",
        "AST/source-string checks do not prove telemetry",
        "`go test -race`",
        "normal `go test` pass",
        "toolchain/platform blocker",
        "drive the underlying app state to a non-default value",
        "metric-name presence, and zero-value gauge collection",
        "saturated or deterministic backpressure path",
        "nonzero depth and oldest-age values",
        "keep the verification result `Partial`",
    ]
    combined = _squash(f"{instrument}\n{incident}")
    missing = [term for term in required_terms if term not in combined]
    assert not missing
    assert "load `../references/incident-readiness.md`" in _squash(instrument)
    assert "multi-process" in _squash(instrument)


def test_incident_freshness_age_requires_demand_or_cadence_evidence():
    instrument = _squash(_read(INSTRUMENT_SKILL)).casefold()
    incident = _squash(_read(INCIDENT_REF)).casefold()
    required_terms = [
        "healthy idle",
        "expected cadence",
        "pending/backlogged work",
        "accepted input",
        "localization-only",
        "backlog, queue delay, or missed schedule",
    ]
    assert "healthy-idle age" in instrument
    missing = [term for term in required_terms if term not in incident]
    assert not missing


def test_instrument_converts_incident_readiness_audit_to_patchable_work():
    text = _squash(_read(INSTRUMENT_SKILL))
    required_terms = [
        "Audit-Driven Incident Readiness",
        "partial or missing `current_instrumentation.incident_readiness` rows",
        "selected finding with the same `area`",
        "resolve every safe app-owned incident gap",
        "to exact IDs and create the selection before editing",
        "Do not choose one representative gap unless the user explicitly narrows scope",
        "Apply every source-evidenced surface it requires",
        "no placeholder instrument",
        "MTTD-improving",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_instrument_requires_gap_closure_matrix_for_incident_readiness():
    skill = _read(INSTRUMENT_SKILL)
    text = _squash(skill + "\n" + _read(INSTRUMENT_REPORT))
    assert "references/instrumentation-report.md" in skill
    required_terms = [
        "Audit-Driven Gap Closure",
        "validated dependency-closed selected finding set as the implementation queue",
        "exactly the selected IDs plus executable dependencies added by `select`",
        "one row per prioritized audit gap",
        "Working / Not working / Not proven / Not configured / Deferred",
        "unselected rows `Deferred`",
        "canonical instrumentation JSON contains selected rows only",
        "manual decision",
        "owner-map the exact prerequisite",
        "required signals",
        "remaining signals",
    ]
    missing = [term for term in required_terms if term not in text]
    assert not missing


def test_instrument_requires_incident_evidence_gap_closure():
    skill = _read(INSTRUMENT_SKILL)
    reference = _squash(_read(INCIDENT_REF))
    required_skill_terms = [
        "Incident-Evidence Mode",
        "failure mechanism",
        "owning code or platform surface",
        "MTTD-improving",
        "`../references/incident-readiness.md`",
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
    skill = _squash(_read(INSTRUMENT_SKILL))
    reference = _squash(_read(INCIDENT_REF))
    required_skill_terms = [
        "load `../references/incident-readiness.md`",
        "readiness work",
        "source-evidenced surface",
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
    text = _squash(_read(INSTRUMENT_SKILL))
    required_terms = [
        "Skip the prompt in canonical, readiness, GenAI, or explicit-signal scope",
        "validated canonical selection already defines the scope",
        "direct request is scope authority only on the direct no-canonical-audit path",
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
        if path == INSTRUMENT_SKILL:
            assert "../references/incident-readiness.md" in text
            text += "\n" + _read(INCIDENT_REF)
        missing = [term for term in required_terms if term not in text]
        assert not missing, f"{path} missing incident-readiness terms: {missing}"


def test_splunk_configure_consumes_canonical_findings():
    skill = _squash(_read(SPLUNK_CONFIGURE))
    required_terms = [
        "Read telemetry gaps and readiness from `findings`, `current_instrumentation.incident_readiness`, and `genai_readiness`.",
        "Preserve unselected findings as audit context, not implemented work.",
        "instrumentation prerequisite",
        "Instrumentation Prerequisites",
        "Do not generate a detector for a missing or unverified signal",
    ]
    missing = [term for term in required_terms if term not in skill]
    assert not missing


def test_audit_maps_incident_readiness_to_current_gap_contract():
    audit = _squash(_read(AUDIT_SKILL))
    report_contract = _squash(_read(REPORT_FLOW))
    required_terms = [
        "OTel finding boundary",
        "`current_instrumentation.incident_readiness`",
        "Record only telemetry-scoped readiness surfaces",
        "single canonical `findings` array",
        "`Area` is the stable human-readable gap identity",
        "`Required fix` names every required signal",
        "mapped acceptance scenarios",
        "Split a telemetry gap when required signals have different owners",
        "Do not mark a partial surface covered",
    ]
    missing = [term for term in required_terms if term not in audit]
    assert not missing
    required_contract_terms = [
        "Write and validate `.observe/otel-audit.json` first",
        "Render `.observe/otel.html` from the validated JSON",
        "Every telemetry-scoped `partial`, `missing`, or `owner-mapped` Incident Readiness row",
        "`area` is identical",
        "Do not add a readiness row solely for API behavior",
        "not a second top-level gap ledger",
        "canonical `current_instrumentation.incident_readiness` is non-empty",
        "reconcile those rows through the matching findings",
        "Without canonical audit JSON, derive readiness only from explicit user scope and current source",
    ]
    assert not [term for term in required_contract_terms if term not in report_contract]


def test_instrument_reconciles_current_audit_gap_contract():
    skill = _read(INSTRUMENT_SKILL)
    assert "references/instrumentation-report.md" in skill
    instrument = _squash(skill + "\n" + _read(INSTRUMENT_REPORT))
    required_terms = [
        "Audit-Driven Gap Closure",
        "validated dependency-closed selected finding set as the implementation queue",
        "exactly the selected IDs plus executable dependencies added by `select`",
        "Build an internal closure matrix before editing",
        "finding ID -> area -> priority -> required fix -> instrument mode -> planned action",
        "one row per prioritized audit gap",
        "exact audit `Area` value",
        "unselected rows `Deferred`",
        "Not working",
        "Not proven",
        "Not configured",
        "Deferred",
    ]
    missing = [term for term in required_terms if term not in instrument]
    assert not missing


def test_splunk_configure_demotes_partial_gap_coverage():
    skill = _squash(_read(SPLUNK_CONFIGURE))
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
    skill = _squash(_read(SPLUNK_CONFIGURE))
    required_terms = [
        "audit contains no usable detector input",
        "do not generate detector or",
        "continue processing gaps and readiness sections",
        "incident-readiness",
        ".observe/detectors.md",
        "alert coverage matrix",
    ]
    missing = [term for term in required_terms if term not in skill]
    assert not missing


def test_splunk_configure_consumes_canonical_incident_readiness():
    skill = _squash(_read(SPLUNK_CONFIGURE))
    required_terms = [
        "Consume every telemetry-scoped row in `current_instrumentation.incident_readiness`.",
        "Reconcile each `partial`, `missing`, or `owner_mapped` row through its matching source finding.",
        "Preserve the human-readable area, exact required signals, owner, evidence, and detection/localization impact.",
        "unless exact equivalent metrics are source-backed and proven",
        "Do not generate a detector for a missing or unverified signal",
        "Never infer approval from priority, report prose, HTML state, or an instrumentation row.",
    ]
    missing = [term for term in required_terms if term not in skill]
    assert not missing


def test_splunk_configure_owns_detector_reliability_handoff():
    skill = _read(SPLUNK_CONFIGURE)
    classification = _read(
        SPLUNK_CONFIGURE_REFS / "incident-detector-classification.md"
    )
    templates = _read(SPLUNK_CONFIGURE_REFS / "readiness-detector-templates.md")
    required_terms = [
        "detector reliability evidence",
        "missed, flapping, auto-resolved, or no-data alerts",
        "alert-coverage-audit",
        "Do not ask app instrumentation",
        "Do not generate service metric Terraform",
    ]
    combined = _squash("\n".join((skill, classification, templates)))
    missing = [term for term in required_terms if term not in combined]
    assert not missing


def test_splunk_configure_covers_dependency_release_and_capacity_mttd_signals():
    skill = _read(SPLUNK_CONFIGURE)
    classification = _read(
        SPLUNK_CONFIGURE_REFS / "incident-detector-classification.md"
    )
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
        normalized = _squash(text).casefold()
        missing = [term for term in required_terms if term.casefold() not in normalized]
        assert not missing


def test_splunk_configure_dashboard_signalflow_guardrails():
    skill = _read(SPLUNK_CONFIGURE)
    templates = _read(SPLUNK_CONFIGURE_REFS / "dashboard-terraform-contract.md")
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
    normalized_skill = _squash(skill).casefold()
    normalized_templates = _squash(templates).casefold()
    assert not [
        term for term in required_skill_terms if term.casefold() not in normalized_skill
    ]
    assert not [
        term
        for term in required_template_terms
        if term.casefold() not in normalized_templates
    ]
    assert 'property       = "deployment.environment.name"' in templates
    assert (
        "newly instrumented services should emit `deployment.environment.name`"
        in normalized_templates
    )
    for term in ["e.g. us1, eu0, lab0", "e.g. us1, eu0", "us1", "eu0", "lab0"]:
        assert term not in skill
        assert term not in templates


def test_splunk_configure_preserves_runtime_cpu_coverage():
    skill = _read(SPLUNK_CONFIGURE)
    classification = _read(
        SPLUNK_CONFIGURE_REFS / "incident-detector-classification.md"
    )
    templates = "\n".join(
        (
            _read(SPLUNK_CONFIGURE_REFS / "readiness-detector-templates.md"),
            _read(SPLUNK_CONFIGURE_REFS / "dashboard-terraform-contract.md"),
        )
    )
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
        normalized = _squash(text).casefold()
        missing = [term for term in required_terms if term.casefold() not in normalized]
        assert not missing


def test_splunk_configure_prevents_generic_keywords_from_shadowing_fault_domains():
    classification = _read(
        SPLUNK_CONFIGURE_REFS / "incident-detector-classification.md"
    )
    templates = _read(SPLUNK_CONFIGURE_REFS / "readiness-detector-templates.md")
    required_classification_terms = [
        "`availability` or `unavailable` alone is not sufficient",
        "dependency-specific",
        "`operation` alone is not sufficient",
        "rather than a client or dependency",
        "newest-event-age, event-age, ingest-lag, processing-lag, data-age, or staleness",
        "There is no universal count threshold for queue depth or consumer lag",
        "Use `85` only for a normalized percentage",
        "Use `capacity-saturation` when an evidenced gauge/up-down counter",
        "capacity/utilization/cpu/memory/heap/",
        "cumulative CPU time as a diagnostic rate",
    ]
    normalized_classification = _squash(classification)
    assert not [
        term
        for term in required_classification_terms
        if term not in normalized_classification
    ]
    assert "Use 85% only for normalized saturation" in _squash(templates)


def test_dashboard_group_template_includes_provider_required_description():
    dashboard_shape = _read(
        SPLUNK_CONFIGURE_REFS / "dashboard-terraform-contract.md"
    )
    assert 'resource "signalfx_dashboard_group" "service"' in dashboard_shape
    assert 'description = "Service health dashboards for ${var.service_name}"' in dashboard_shape


def test_audit_keeps_current_canonical_report_contract():
    audit = _read(SKILLS_DIR / "otel-audit" / "SKILL.md")
    canonical_terms = [
        "`.observe/otel-audit.json` -- canonical machine-readable audit source.",
        "`.observe/otel.html` -- self-contained human review report generated from the",
        '"evidence": [',
        '"current_instrumentation": {',
        '"findings": [',
        '"verification": {',
        '"environments": [',
        '"scenarios": [',
        "Write two audit artifacts",
        "Omit `flow` and `signal_flow` from new audits",
    ]
    assert not [term for term in canonical_terms if term not in audit]
    assert ".observe/otel.md" not in audit
    assert "`render-markdown`" not in audit
    assert '"flow": {' not in audit
    assert '"signal_flow": {' not in audit
    assert "# Observability Report: {service-name}" not in audit
    assert "````markdown" not in audit


def test_incident_readiness_guidance_stays_generic_and_non_genai():
    shared_skill_paths = [
        SKILLS_DIR / "otel-audit" / "SKILL.md",
        SKILLS_DIR / "otel-instrument" / "SKILL.md",
        SPLUNK_CONFIGURE,
        SPLUNK_CONFIGURE_REFS / "detector-classification.md",
        SPLUNK_CONFIGURE_REFS / "incident-detector-classification.md",
        SPLUNK_CONFIGURE_REFS / "terraform-templates.md",
        SPLUNK_CONFIGURE_REFS / "readiness-detector-templates.md",
        SPLUNK_CONFIGURE_REFS / "dashboard-terraform-contract.md",
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
