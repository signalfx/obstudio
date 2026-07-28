from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_SKILL = ROOT / "skills" / "otel-audit" / "SKILL.md"
INSTRUMENT_SKILL = ROOT / "skills" / "otel-instrument" / "SKILL.md"
VERIFY_SKILL = ROOT / "skills" / "otel-verify" / "SKILL.md"
INSTRUMENT_HANDOFF = ROOT / "skills" / "otel-instrument" / "references" / "json-approval-handoff.md"
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


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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

    assert "#### Reader Order" in instrument
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
    assert "Review report: [otel.html](http://127.0.0.1:<port>/otel.html)" in audit


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
    assert "Users open `.observe/otel-instrumentation.html` after instrumentation" in instrument
    assert "Do not use it to change selected scope" in instrument


def test_instrument_keeps_interactive_contract() -> None:
    instrument = _read(INSTRUMENT_SKILL)
    resolved = _resolved_contract(
        INSTRUMENT_SKILL,
        "instrumentation-report.md",
        "genai-instrumentation.md",
    )
    handoff = _read(INSTRUMENT_HANDOFF)
    opening = instrument.split("## Workflow", 1)[0]
    canonical_gate = instrument.split(
        "#### Canonical Audit And Selection Gate", 1
    )[1].split("### Fast Path", 1)[0]

    assert (
        "Before editing application code, read "
        "`../references/report-flow-contract.md`" in opening
    )
    assert "`./references/json-approval-handoff.md`" in opening
    assert "read and follow `./references/json-approval-handoff.md`" in " ".join(
        canonical_gate.split()
    )
    assert "#### Reader Order" in resolved


def test_instrument_interactive_references_are_resolvable() -> None:
    instrument = _read(INSTRUMENT_SKILL)
    resolved = _resolved_contract(INSTRUMENT_SKILL, "instrumentation-report.md")

    assert "./references/json-approval-handoff.md" in instrument
    assert INSTRUMENT_HANDOFF.is_file()
    assert "#### Signals Changed" in resolved


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

    for text in (audit, flow):
        for term in ("two or three", "`decision_options`", "`outcome`", "`unlocks`"):
            assert term in text
        assert "pairwise disjoint" in text
    assert "explicit selectable `decision_options`" in flow

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


def test_audit_final_handoff_requires_only_browser_link() -> None:
    audit = _read(AUDIT_SKILL)
    normalized = " ".join(audit.split())

    assert "the final response must contain exactly this one line and nothing else" in normalized
    assert "Copy `links.review_report`" in audit
    assert "Review report: [otel.html](http://127.0.0.1:<port>/otel.html)" in audit
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
