from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_SKILL = ROOT / "skills" / "otel-audit" / "SKILL.md"
AUDIT_REFERENCES = ROOT / "skills" / "otel-audit" / "references"
INSTRUMENT_SKILL = ROOT / "skills" / "otel-instrument" / "SKILL.md"
VERIFY_SKILL = ROOT / "skills" / "otel-verify" / "SKILL.md"
INSTRUMENT_HANDOFF = ROOT / "skills" / "otel-instrument" / "references" / "json-approval-handoff.md"
INSTRUMENT_RUNTIME_REF = (
    ROOT
    / "skills"
    / "otel-instrument"
    / "references"
    / "project-runtime-validation.md"
)
VERIFY_HANDOFF = ROOT / "skills" / "otel-verify" / "references" / "json-approval-handoff.md"
AUDIT_INPUT = ROOT / "evals" / "go" / "chi-basic" / "eval" / "inputs" / "otel-audit.json"
REPORT_TOOL = ROOT / "skills" / "references" / "scripts" / "observe_report.py"
REPORT_FLOW = ROOT / "skills" / "references" / "report-flow-contract.md"
AUDIT_EVAL = ROOT / "evals" / "go" / "chi-basic" / "eval" / "qual" / "audit.json"
INSTRUMENT_EVAL = (
    ROOT / "evals" / "go" / "chi-basic" / "eval" / "qual" / "benchmark-instrument.json"
)
CHI_CANONICAL_VERIFY_EVAL = (
    ROOT / "evals" / "go" / "chi-basic" / "eval" / "qual" / "verify.json"
)
CHI_DIRECT_VERIFY_EVAL = (
    ROOT
    / "evals"
    / "go"
    / "chi-basic"
    / "eval"
    / "qual"
    / "verify-runtime-blocker.json"
)
CHI_DIRECT_VERIFY_PROBE = (
    ROOT
    / "evals"
    / "go"
    / "chi-basic"
    / "eval"
    / "inputs"
    / "conclusive-listener-probe.txt"
)
CHI_DIRECT_INSTRUMENT_EVAL = (
    ROOT / "evals" / "go" / "chi-basic" / "eval" / "qual" / "instrument.json"
)
CHI_DECISION_INSTRUMENT_EVAL = (
    ROOT
    / "evals"
    / "go"
    / "chi-basic"
    / "eval"
    / "qual"
    / "instrument-decision-gated.json"
)
CHI_RUNTIME_BLOCKER_INSTRUMENT_EVAL = (
    ROOT
    / "evals"
    / "go"
    / "chi-basic"
    / "eval"
    / "qual"
    / "instrument-runtime-blocker.json"
)


def _instrument_report_contract() -> str:
    text = REPORT_FLOW.read_text(encoding="utf-8")
    status_marker = "\n## Status Rules\n"
    audit_marker = "\n## Audit Contract\n"
    instrument_marker = "\n## Instrumentation Contract\n"
    verify_marker = "\n## Verification Report Contract\n"
    assert text.count("\nFor an audit,") == 1
    for marker in (status_marker, audit_marker, instrument_marker, verify_marker):
        assert text.count(marker) == 1
    prefix = text.split("\nFor an audit,", 1)[0].rstrip()
    status = "## Status Rules\n" + text.split(status_marker, 1)[1].split(
        audit_marker, 1
    )[0].rstrip()
    instrument = "## Instrumentation Contract\n" + text.split(
        instrument_marker, 1
    )[1].split(verify_marker, 1)[0].rstrip()
    return "\n\n".join((prefix, status, instrument)) + "\n"


def _read(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path == AUDIT_SKILL:
        text += "\n" + "\n".join(
            reference.read_text(encoding="utf-8")
            for reference in sorted(AUDIT_REFERENCES.rglob("*.md"))
        )
    if path == INSTRUMENT_SKILL:
        text += "\n".join(
            (
                "",
                INSTRUMENT_RUNTIME_REF.read_text(encoding="utf-8"),
                _instrument_report_contract(),
                INSTRUMENT_HANDOFF.read_text(encoding="utf-8"),
            )
        )
    return text


def _eval_contract(path: Path) -> str:
    data = json.loads(_read(path))
    return " ".join(
        [item["task"] for item in data["prompts"]] + data.get("rubric", [])
    )


def _resolved_contract(skill: Path, *reference_names: str) -> str:
    parts = [_read(skill)]
    for reference_name in reference_names:
        reference = skill.parent / "references" / reference_name
        if reference.is_file():
            parts.append(_read(reference))
    return "\n".join(parts)


def test_reader_report_contracts_are_available() -> None:
    instrument = _resolved_contract(
        INSTRUMENT_SKILL,
        "instrumentation-report.md",
        "genai-instrumentation.md",
    )
    verify = _resolved_contract(
        VERIFY_SKILL,
        "direct-verification.md",
        "verification-report.md",
    )

    assert "## Reader-First Report Order" in instrument
    assert "## Instrumentation Contract" in instrument
    assert "## Reader Report" in verify


def test_json_first_artifact_and_selection_contract_is_explicit() -> None:
    audit = _read(AUDIT_SKILL)
    instrument = _read(INSTRUMENT_SKILL)
    verify = _read(VERIFY_SKILL)

    for term in (".observe/otel-audit.json", ".observe/otel.html"):
        assert term in audit
    for term in (
        ".observe/otel-audit.json",
        ".observe/otel-selection.json",
        "--ids",
        "select --all",
        ".observe/otel-instrumentation.json",
        ".observe/otel-instrumentation.html",
    ):
        assert term in instrument
    assert ".observe/otel-verify.json" in verify

    instrument_normalized = " ".join(instrument.lower().split())
    assert "selected" in instrument_normalized
    assert "unselected" in instrument_normalized
    assert "dependencies" in instrument_normalized
    assert "manual decision" in instrument_normalized
    assert "external follow-up" in instrument_normalized
    assert "cannot enter the executable selection" in instrument_normalized
    assert "audit and scope-planning surface" in instrument_normalized

    handoff_normalized = " ".join(_read(INSTRUMENT_HANDOFF).lower().split())
    assert "selection gate" in handoff_normalized
    assert "adopt-selection" in handoff_normalized
    assert "select --all" in handoff_normalized
    assert "--all-if-empty" in handoff_normalized
    assert "manual-decision options" in handoff_normalized
    assert "blocker is the canonical audit" in handoff_normalized
    assert "selection_sha256" in handoff_normalized
    assert "changed answer invalidates older instrumentation" in handoff_normalized
    assert "cannot appear in either selection id list" in handoff_normalized
    assert "unresolved dependency" in handoff_normalized

    audit_normalized = " ".join(audit.split())
    assert "run `finalize-audit`" in audit_normalized
    assert "--html .observe/otel.html" in audit_normalized
    assert "bound only to `127.0.0.1`" in audit_normalized
    assert "available port" in audit_normalized
    assert "do not open the browser automatically" in audit_normalized.lower()
    assert "remote workspaces may require" in audit_normalized.lower()
    assert "do not present `$otel-verify` or generic `run verification` as the audit prompt's next step" in audit_normalized.lower()
    assert 'python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py"' in audit
    assert ".observe/otel-audit.json" in audit
    assert "Review report: [otel.html](http://127.0.0.1:<port>/<token>/otel.html)" in audit


def test_human_html_usage_flow_is_documented() -> None:
    flow = " ".join(_read(REPORT_FLOW).split())
    audit = " ".join(_read(AUDIT_SKILL).split())
    instrument = " ".join(_read(INSTRUMENT_SKILL).split())

    for term in (
        "Human HTML Usage Flow",
        "Open `.observe/otel.html` after `$otel-audit`",
        "audit and scope-planning surface",
        "Run `$otel-instrument` with the copied command",
        "Open `.observe/otel-instrumentation.html` after `$otel-instrument`",
        "change-impact and verification-status surface",
        "If scope is wrong, return to `.observe/otel.html`",
    ):
        assert term in flow

    assert "The reviewer uses `.observe/otel.html` to understand findings" in audit
    assert "It is not a proof report" in audit
    assert "Open `.observe/otel-instrumentation.html` after `$otel-instrument`" in instrument
    assert "not as a place to change audit scope" in instrument


def test_instrument_keeps_interactive_contract() -> None:
    core = INSTRUMENT_SKILL.read_text(encoding="utf-8")
    resolved = _resolved_contract(
        INSTRUMENT_SKILL,
        "instrumentation-report.md",
        "genai-instrumentation.md",
    )
    handoff = _read(INSTRUMENT_HANDOFF)

    assert "`../references/report-flow-contract.md`" in core
    assert "use one heading-bounded extraction" in core
    assert "fixed line offsets" in core
    normalized_core = " ".join(core.split())
    assert "loaded `otel-instrument/SKILL.md` directory" in normalized_core
    assert "loaded reference, resolve relative paths from its directory" in normalized_core
    assert (
        "<instrument-skill-dir>/../references/report-flow-contract.md" in core
    )
    assert REPORT_FLOW.is_file()
    assert "`./references/json-approval-handoff.md`" in core
    core_normalized = " ".join(core.split())
    assert "It is authoritative for selection precedence" in core_normalized
    assert "## Reader-First Report Order" in resolved
    assert "## Selection Gate" in handoff


def test_instrument_report_contract_route_excludes_unrelated_sections() -> None:
    routed = _instrument_report_contract()

    for required in (
        "# OTel Report Flow Contract",
        "## Canonical Artifact Chain",
        "## Document Ownership",
        "## Human HTML Usage Flow",
        "## Reader-First Report Order",
        "## Status Rules",
        "## Instrumentation Contract",
    ):
        assert required in routed
    assert "For an audit," not in routed
    for excluded_heading in (
        "Audit Contract",
        "Verification Report Contract",
        "Splunk Configure Contract",
    ):
        assert f"\n## {excluded_heading}\n" not in routed
    assert routed.rstrip().endswith(
        "explicit scope decision is fully recorded."
    )


def test_instrument_interactive_references_are_resolvable() -> None:
    instrument = _read(INSTRUMENT_SKILL)
    resolved = _resolved_contract(INSTRUMENT_SKILL, "instrumentation-report.md")

    assert "./references/json-approval-handoff.md" in instrument
    assert INSTRUMENT_HANDOFF.is_file()
    assert "## Signals Changed" in resolved


def test_verify_keeps_interactive_contract() -> None:
    verify = _read(VERIFY_SKILL)
    resolved = _resolved_contract(
        VERIFY_SKILL,
        "direct-verification.md",
        "verification-report.md",
    )
    handoff = _read(VERIFY_HANDOFF)
    opening = verify.split("## Contract", 1)[0]
    canonical_gate = verify.split("#### Canonical Scope Gate", 1)[1].split(
        "### 2.", 1
    )[0]

    assert (
        "Before writing verification artifacts, read "
        "`../references/report-flow-contract.md`"
        in " ".join(opening.split())
    )
    assert "`./references/json-approval-handoff.md`" in opening
    assert "read and follow `./references/json-approval-handoff.md`" in " ".join(
        canonical_gate.split()
    )
    assert "## Reader Report" in resolved
    assert "### 9. Final Response" in resolved


def test_verify_interactive_reference_is_resolvable() -> None:
    verify = _read(VERIFY_SKILL)
    resolved = _resolved_contract(VERIFY_SKILL, "verification-report.md")
    assert "./references/json-approval-handoff.md" in verify
    assert VERIFY_HANDOFF.is_file()
    assert "## Reader Report" in resolved
    assert "## Verification JSON" not in verify
    assert "## Verification JSON" in _read(VERIFY_HANDOFF)


def test_downstream_html_reports_use_browser_safe_loopback_links() -> None:
    instrument = " ".join(
        (_read(INSTRUMENT_SKILL) + _read(INSTRUMENT_HANDOFF)).split()
    )
    verify = " ".join((_read(VERIFY_SKILL) + _read(VERIFY_HANDOFF)).split())
    flow = " ".join(_read(REPORT_FLOW).split())

    for text in (instrument, verify, flow):
        assert "loopback" in text.lower()
        assert "otel-instrumentation.html" in text
        assert "otel.html" in text
        assert "do not open" in text.lower()
    assert (
        "[otel-instrumentation.html](http://127.0.0.1:<port>/<token>/otel-instrumentation.html)"
        in verify
    )
    assert "[otel.html](http://127.0.0.1:<port>/<token>/otel.html)" in verify


def test_instrument_keeps_verification_results_in_bound_overlay() -> None:
    definition = json.loads(_read(INSTRUMENT_EVAL))
    rubric = " ".join(definition["rubric"])
    instrument = " ".join(_read(INSTRUMENT_SKILL).split())
    handoff = " ".join(_read(INSTRUMENT_HANDOFF).split())

    assert "separately bound .observe/otel-verify.json carries verification results" in rubric
    assert "scenario mappings" in rubric
    assert "verification_handoff" not in rubric
    assert "remaining_gaps" not in rubric
    assert "separately bound `.observe/otel-verify.json`" in handoff
    assert "do not duplicate them as new instrumentation schema fields" in handoff


def test_instrumentation_phase_validation_is_not_bound_verification() -> None:
    instrument = " ".join(_read(INSTRUMENT_SKILL).split())
    rubric = " ".join(
        json.loads(_read(CHI_DIRECT_INSTRUMENT_EVAL))["rubric"]
    )

    assert "instrumentation-phase validation, never item proof" in instrument
    assert "With bound verification, HTML names the repair" in instrument
    assert "HTML keeps per-finding proof and OTLP/product visibility not run/not proven" in instrument
    assert "details stay in Markdown" in instrument
    assert "With a bound verification overlay, detailed item/scenario proof and coverage come from that overlay" in rubric
    assert "placeholder satisfies the HTML proof and coverage requirement" in rubric
    assert "detailed item/scenario proof is not required" in rubric
    assert "instrumentation-phase harness or exporter tests stay separately labeled" in rubric
    assert "rather than being promoted to bound proof" in rubric


def test_instrument_preflight_records_deployment_environment_ownership() -> None:
    instrument = " ".join(_read(INSTRUMENT_SKILL).split())
    rubric = " ".join(
        json.loads(_read(CHI_DIRECT_INSTRUMENT_EVAL))["rubric"]
    )

    assert "Before editing, record the `deployment.environment.name` source or explicit absence" in instrument
    assert "preserve operator `OTEL_RESOURCE_ATTRIBUTES`" in instrument
    assert "deployment.environment.name source or explicit absence before editing" in rubric


def test_instrument_rubric_allows_standard_runtime_auto_instrumentation() -> None:
    rubric = " ".join(
        json.loads(_read(CHI_DIRECT_INSTRUMENT_EVAL))["rubric"]
    )

    assert "does not add unselected OTEL-002 task.created, OTEL-004 task.create" in rubric
    assert "The Go guide's standard runtime metrics baseline" in rubric
    assert "is not a drive-by custom signal" in rubric


def test_instrumentation_meta_result_never_uses_not_run() -> None:
    handoff = " ".join(_read(INSTRUMENT_HANDOFF).split())

    assert "Use only `Pass`, `Partial`, `Fail`, or `Blocked` for instrumentation `meta.result`" in handoff
    assert "do not emit `Not run` for instrumentation `meta.result`" in handoff
    assert "or `Not run` for `meta.result`" not in handoff


def test_manual_decision_answers_are_separate_and_gate_matching_work() -> None:
    audit = " ".join(_read(AUDIT_SKILL).split())
    flow = " ".join(_read(REPORT_FLOW).split())
    instrument = " ".join(_read(INSTRUMENT_SKILL).split())
    handoff = " ".join(_read(INSTRUMENT_HANDOFF).split())

    for text in (audit,):
        for term in ("two or three", "`decision_options`", "`outcome`", "`unlocks`"):
            assert term in text
        assert "pairwise disjoint" in text
    assert "two or three explicit `decision_options`" in audit

    for text in (flow, instrument, handoff):
        for term in (
            "`decision_answers`",
            "`requested_ids`",
            "`approved_ids`",
            "`unlocks`",
        ):
            assert term in text

    assert "cannot appear in either selection ID list" in handoff
    assert (
        "Only executable findings listed in that option's `unlocks` may enter "
        "requested or approved scope"
    ) in handoff
    assert "An answer never auto-selects work" in handoff
    assert "work outside the recorded option's `unlocks`" in instrument
    assert (
        "its finding ID cannot enter `requested_ids` or `approved_ids`"
        in flow
    )
    assert (
        "`decision_answers` separately persists the stable "
        "`finding_id`/`option_id` pair"
    ) in flow
    assert (
        "`decision_answers` separately carries stable `finding_id`/`option_id` pairs"
        in flow
    )
    assert "A manual decision has no checkbox and cannot enter selection JSON" not in flow
    assert "only stable manual answer IDs are carried separately" not in flow


def test_current_audit_and_selection_versions_are_explicit() -> None:
    audit = _read(AUDIT_SKILL)
    report_tool = _read(REPORT_TOOL)
    audit_normalized = " ".join(audit.split())
    audit_input = json.loads(_read(AUDIT_INPUT))

    assert audit_input["schema_version"] == 2
    assert "Write new audits as schema v2" in audit
    assert "OVERLAY_SCHEMA_VERSION = 1" in report_tool
    assert "CURRENT_SELECTION_SCHEMA_VERSION = 2" in report_tool
    assert "CURRENT_AUDIT_SCHEMA_VERSION = 2" in report_tool
    assert "a selection carrying `decision_answers` is schema v2" in audit_normalized


def test_representative_evals_require_canonical_artifacts_and_scope() -> None:
    audit = _eval_contract(AUDIT_EVAL)
    instrument = _eval_contract(INSTRUMENT_EVAL)
    verify = _eval_contract(CHI_CANONICAL_VERIFY_EVAL)

    assert ".observe/otel-audit.json" in audit
    assert ".observe/otel.html" in audit
    assert "$otel-instrument --ids OTEL-001" in instrument
    assert "unselected OTEL-002" in instrument
    assert ".observe/otel-instrumentation.json" in instrument
    assert ".observe/otel-instrumentation.html" in instrument
    assert ".observe/otel-verify.json" in verify


def test_direct_verify_eval_covers_conclusive_runtime_blocker() -> None:
    canonical = json.loads(_read(CHI_CANONICAL_VERIFY_EVAL))
    direct = json.loads(_read(CHI_DIRECT_VERIFY_EVAL))
    contract = " ".join(
        [item["task"] for item in direct["prompts"]]
        + direct["rubric"]
        + [_read(CHI_DIRECT_VERIFY_PROBE)]
    )

    assert [item["id"] for item in canonical["prompts"]] == [
        "canonical-proof-packet"
    ]
    assert [item["id"] for item in direct["prompts"]] == [
        "conclusive-listener-blocker"
    ]
    assert direct["prompts"][0]["eval_inputs"] == [
        "eval/inputs/canonical-verify-evidence.txt",
        "eval/inputs/conclusive-listener-probe.txt",
        "eval/inputs/otel-audit.json",
        "eval/inputs/otel-instrumentation.json",
        "eval/inputs/otel-selection.json",
    ]
    for term in (
        "new direct verification",
        "exact bound audit -> selection -> instrumentation chain",
        "Write the bound canonical verification JSON",
        "Current-run prerequisite probe",
        "same selected Go runtime",
        "Checked-in application listener: :8000",
        "does not launch",
        "overall result as Blocked",
        "ambiguous probe",
        "application code, configuration, or tests",
        "free :8000 and rerun full-runtime proof",
        "does not substitute generated SDK telemetry",
    ):
        assert term in contract


def test_direct_instrument_eval_distinguishes_build_from_telemetry_proof() -> None:
    definition = json.loads(_read(CHI_RUNTIME_BLOCKER_INSTRUMENT_EVAL))
    task = definition["prompts"][0]["task"]
    rubric = " ".join(definition["rubric"])

    assert "build-viability gate passed" in task
    assert "No focused telemetry proof or runtime telemetry proof ran" in task
    assert "overall instrumentation verification result as Blocked" in rubric


def test_audit_final_handoff_requires_only_browser_link() -> None:
    audit = _read(AUDIT_SKILL)
    normalized = " ".join(audit.split())

    assert "the final response must contain exactly this one line and nothing else" in normalized
    assert "Copy `links.review_report`" in audit
    assert "Review report: [otel.html](http://127.0.0.1:<port>/<token>/otel.html)" in audit
    assert "Do not include summary bullets, finding counts, recommendations, a machine-report link" in normalized


def test_decision_gated_instrumentation_has_a_scope_specific_rubric() -> None:
    direct = json.loads(_read(CHI_DIRECT_INSTRUMENT_EVAL))
    decision = json.loads(_read(CHI_DECISION_INSTRUMENT_EVAL))
    direct_contract = " ".join(
        [item["task"] for item in direct["prompts"]] + direct["rubric"]
    )
    decision_contract = " ".join(
        [item["task"] for item in decision["prompts"]] + decision["rubric"]
    )

    assert {item["id"] for item in direct["prompts"]} == {
        "direct",
        "runtime-preserving",
    }
    assert [item["id"] for item in decision["prompts"]] == ["decision-gated"]
    assert direct["judge_inputs"] == decision["judge_inputs"]
    assert "For the decision-gated prompt" not in direct_contract
    assert "OTEL-001" not in decision_contract
    assert "OTEL-003=metric-counter" in decision_contract
    assert "only the unlocked OTEL-002" in decision_contract
    assert "unchosen OTEL-004" in decision_contract
    assert "unrelated HTTP tracing" in decision_contract


def test_canonical_overlays_join_code_telemetry_product_action_and_item_proof() -> None:
    instrument = " ".join((_read(INSTRUMENT_SKILL) + _read(INSTRUMENT_HANDOFF)).split())
    verify = " ".join((_read(VERIFY_SKILL) + _read(VERIFY_HANDOFF)).split())

    for term in (
        "stable item ID",
        "code/config change",
        "added_attributes",
        "verification_scenarios",
        "render-instrumentation-html",
        ".observe/otel-instrumentation.html",
    ):
        assert term in instrument

    assert "Leave `.observe/otel.html` as the audit and scope-planning" in instrument

    for term in (
        "item_results",
        "proof_mode",
        "visibility",
        "observed telemetry",
        "product validation",
        "--instrumentation-json .observe/otel-instrumentation.json",
        "not_explorer_visible",
        "explorer_visible",
    ):
        assert term in verify


def test_human_html_uses_generated_trace_without_raw_correlation_ids() -> None:
    flow = " ".join(_read(REPORT_FLOW).split())
    instrument = " ".join(
        (_read(INSTRUMENT_SKILL) + _read(INSTRUMENT_HANDOFF)).split()
    )
    verify = " ".join((_read(VERIFY_SKILL) + _read(VERIFY_HANDOFF)).split())

    for text in (flow, instrument, verify):
        assert "raw trace IDs or span IDs" in text
        assert "the generated trace" in text
        assert "canonical" in text
