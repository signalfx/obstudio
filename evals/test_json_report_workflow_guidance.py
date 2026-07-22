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
AUDIT_EVAL = ROOT / "evals" / "go" / "chi-basic" / "eval" / "qual" / "benchmark-audit.json"
INSTRUMENT_EVAL = (
    ROOT / "evals" / "go" / "chi-basic" / "eval" / "qual" / "benchmark-instrument.json"
)
VERIFY_EVAL = (
    ROOT / "evals" / "go" / "chi-partial" / "eval" / "qual" / "benchmark-verify.json"
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
    assert "cannot enter the selection" in instrument_normalized
    assert "audit and scope-planning surface" in instrument_normalized
    assert "selected-scope closure" in instrument_normalized

    handoff_normalized = " ".join(_read(INSTRUMENT_HANDOFF).lower().split())
    assert "selection gate" in handoff_normalized
    assert "selection_sha256" in handoff_normalized
    assert "changed answer invalidates older instrumentation" in handoff_normalized
    assert "cannot appear in either selection id list" in handoff_normalized
    assert "unresolved dependency" in handoff_normalized

    audit_normalized = " ".join(audit.split())
    assert "`render-markdown` command owns the complete `.observe/otel.md`" in audit_normalized
    assert "Do not embed a second Markdown template" in audit_normalized
    assert 'python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py"' in audit
    assert "--normalized-out" not in audit
    assert "otel-audit.normalized.json" not in audit


def test_instrument_progressively_loads_only_the_report_contract_it_needs() -> None:
    instrument = _read(INSTRUMENT_SKILL)
    handoff = _read(INSTRUMENT_HANDOFF)
    opening = instrument.split("## Workflow", 1)[0]
    canonical_gate = instrument.split(
        "#### Canonical Audit And Selection Gate", 1
    )[1].split("### Fast Path", 1)[0]

    assert (
        "Before editing application code, read "
        "`../references/report-flow-contract.md`" not in instrument
    )
    assert "Do not load `../references/report-flow-contract.md` as an up-front" in opening
    assert "For a canonical JSON flow, read" in opening
    assert "`./references/json-approval-handoff.md`" in opening
    assert "legacy no-audit flow" in opening
    assert "contained in this `SKILL.md`" in opening
    assert "read and follow `./references/json-approval-handoff.md`" in " ".join(
        canonical_gate.split()
    )
    assert "this file is the scoped instrumentation and reader-report authority" in " ".join(
        handoff.split()
    )
    assert "Do not also load `../../references/report-flow-contract.md`" in handoff
    assert "unless a conditional downstream workflow explicitly requires" in " ".join(
        handoff.split()
    )


def test_audit_does_not_duplicate_the_shared_report_contract_up_front() -> None:
    audit = _read(AUDIT_SKILL)
    opening = audit.split("## Process", 1)[0]
    normalized = " ".join(opening.split())

    assert "Do not load `../references/report-flow-contract.md` as an up-front" in opening
    assert "This `SKILL.md` contains the audit finding" in normalized
    assert "reader-report, selection-handoff, and finalization contract" in normalized
    assert "only when a conditional downstream workflow explicitly requires" in normalized
    assert audit.count("`../references/report-flow-contract.md`") == 1


def test_instrument_terminal_boundary_forbids_post_gate_inspection() -> None:
    instrument = " ".join(_read(INSTRUMENT_SKILL).split())
    handoff = " ".join(_read(INSTRUMENT_HANDOFF).split())
    go_guide = " ".join(
        _read(
            ROOT
            / "skills"
            / "otel-instrument"
            / "references"
            / "languages"
            / "go.md"
        ).split()
    )

    assert "passing `instrumentation-final-gate`" in instrument
    assert "successful explicit no-child" in instrument
    assert "successful terminal stopped-failure validation" in instrument
    assert "emit the final response without another command" in instrument
    assert "`git status`" in instrument
    assert "`git diff`" in instrument
    assert "inspect `go.sum`" in instrument
    assert "repeat a validator/test" in instrument
    assert "duplicate final review" in instrument
    assert "do not fabricate one" in instrument.lower()
    assert "without `--verify-json`" in instrument
    assert "terminal validation for this explicit no-child branch" in instrument
    assert "do not set the overall result to `Blocked` or `Not run`" in instrument
    assert "terminal stopped-failure validation" in instrument
    assert "not a completed or verified handoff" in instrument
    assert "`meta.result: Fail`" in instrument
    assert "authority boundary does not turn an observed telemetry failure" in instrument
    assert "top-level `stop_boundaries[]`" in instrument
    assert "finding `remaining` and top-level `next_steps` repair-only" in instrument

    assert "Do not run `instrumentation-final-gate`" in handoff
    assert "fixed-Go cleanup, or the final response from this Step 5 reference" in handoff
    assert "the parent `SKILL.md` owns the actual gate" in handoff
    assert "This is preliminary Step 5 validation" in handoff
    assert "stopped-failure handoff" in handoff
    assert "not a completed or verified instrumentation result" in handoff
    assert "`meta.result: Fail`" in handoff
    assert "do not relabel observed failure as `Blocked` or `not_proven`" in handoff
    assert "top-level `stop_boundaries[]`" in handoff
    assert "finding `remaining` and top-level `next_steps` repair-only" in handoff
    assert "Treat a passing `instrumentation-final-gate`" not in handoff

    terminal = instrument.index("After completing every Step 7")
    assert instrument.index("### 7. Finalize") < terminal
    assert instrument.index("## Credential Safety") < terminal
    assert instrument.index("Verify no tokens in tracked files") < terminal
    assert instrument.index("## Scope") < terminal
    assert instrument.rfind("## ") == instrument.index("## Terminal Sequence")
    assert instrument.index("Write `.observe/otel-instrumentation.md`") < terminal
    assert instrument.index("render `.observe/otel-instrumentation.html`") < terminal
    assert instrument.index("On the fixed Go bundle branch") < terminal
    assert "requested detector/configure workflow" in instrument
    assert "last validation before fixed-Go cleanup" in instrument
    assert "For a legacy no-audit flow" in instrument
    assert "successful legacy terminal validation" in instrument
    assert "do not look for or invoke the canonical gate" in instrument
    assert "do not fabricate audit" in instrument
    assert instrument.index("When verified metric evidence exists") < terminal
    assert "Successful cleanup is the terminal boundary" in go_guide
    assert "explicit canonical no-child validation" in go_guide
    assert "legacy no-audit validation" in go_guide
    assert "emit the final response immediately" in go_guide
    assert "a `go.sum` inspection" in go_guide
    assert "repeated validators/tests" in go_guide


def test_manual_decision_answers_are_separate_and_gate_matching_work() -> None:
    audit = " ".join(_read(AUDIT_SKILL).split())
    flow = " ".join(_read(REPORT_FLOW).split())
    instrument = " ".join(_read(INSTRUMENT_SKILL).split())
    handoff = " ".join(_read(INSTRUMENT_HANDOFF).split())

    for text in (audit, flow):
        for term in (
            "two or three",
            "explicit selectable `decision_options`",
            "`outcome`",
            "`unlocks`",
        ):
            assert term in text
        assert "pairwise disjoint" in text

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


def test_audit_v2_and_legacy_overlay_versions_are_explicit() -> None:
    audit = _read(AUDIT_SKILL)
    report_tool = _read(REPORT_TOOL)
    report_flow = _read(REPORT_FLOW)
    audit_normalized = " ".join(audit.split())
    report_flow_normalized = " ".join(report_flow.split())
    audit_input = json.loads(_read(AUDIT_INPUT))

    assert audit_input["schema_version"] == 2
    assert "Write new audits as schema v2" in audit
    assert "Schema v1 remains a frozen read-only legacy" in audit
    assert "Preserve optional concerns and decision/external ownership" in audit_normalized
    assert "Frozen schema-v1 inputs may retain legacy `Blocked` status" in audit
    assert (
        "Preserve optional concerns and decision/external ownership fields"
        in report_flow_normalized
    )
    assert "OVERLAY_SCHEMA_VERSION = 1" in report_tool
    assert "CURRENT_SELECTION_SCHEMA_VERSION = 2" in report_tool
    assert "CURRENT_AUDIT_SCHEMA_VERSION = 2" in report_tool
    assert "A selection without answers remains schema v1" in audit
    assert "a selection carrying `decision_answers` is schema v2" in audit_normalized
    assert "A selection without answers remains schema v1" in report_flow


def test_representative_evals_require_canonical_artifacts_and_scope() -> None:
    audit = _eval_contract(AUDIT_EVAL)
    instrument = _eval_contract(INSTRUMENT_EVAL)
    verify = _eval_contract(VERIFY_EVAL)

    assert ".observe/otel-audit.json" in audit
    assert ".observe/otel.html" in audit
    assert "$otel-instrument --ids OTEL-001" in instrument
    assert "unselected OTEL-002" in instrument
    assert ".observe/otel-instrumentation.json" in instrument
    assert ".observe/otel-instrumentation.html" in instrument
    assert ".observe/otel-verify.json" in verify


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


def test_canonical_verify_eval_requires_only_real_item_local_proof() -> None:
    verify = _eval_contract(CHI_CANONICAL_VERIFY_EVAL)

    assert "single OTEL-001.http-health-span item result" in verify
    assert "GET /health with http.route=/health" in verify
    assert "Does not fabricate a removed HttpRequest telemetry item" in verify
    assert "both telemetry item results" not in verify
    assert "structured removal_proof for HttpRequest" not in verify


def test_ci_gate_is_headless_and_has_distinct_policy_exit_codes() -> None:
    audit_skill = " ".join(_read(AUDIT_SKILL).replace("`", "").split())
    audit_eval = " ".join(_eval_contract(AUDIT_EVAL).replace("`", "").split())

    for text in (audit_skill, audit_eval):
        assert "observe_report.py" in text and " gate " in f" {text} "
        assert ".observe/otel-audit.json" in text
        assert "--fail-on required" in text
        assert "exit 1" in text
        assert "exit 2" in text

    assert "For CI/MR use, generate the audit first" in audit_skill
    assert "headless" in audit_eval.lower()
    assert "external CI" in audit_eval
    assert "do not claim" in audit_eval.lower()


def test_canonical_overlays_join_code_telemetry_product_action_and_item_proof() -> None:
    instrument = " ".join((_read(INSTRUMENT_SKILL) + _read(INSTRUMENT_HANDOFF)).split())
    verify = " ".join((_read(VERIFY_SKILL) + _read(VERIFY_HANDOFF)).split())

    for term in (
        "stable item ID",
        "code/config change",
        "added_attributes",
        "chart/dashboard or detector",
        "filter, slice, group-by",
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


def test_failed_child_stop_boundaries_are_separate_from_repairs() -> None:
    instrument = " ".join(
        (_read(INSTRUMENT_SKILL) + _read(INSTRUMENT_HANDOFF)).split()
    )
    verify = " ".join((_read(VERIFY_SKILL) + _read(VERIFY_HANDOFF)).split())
    flow = " ".join(_read(REPORT_FLOW).split())

    for text in (instrument, verify, flow):
        assert "stop_boundaries[]" in text
        assert "remaining" in text and "next_steps" in text
        assert "repair-only" in text
        assert "external_prerequisite" in text
        assert "lifecycle: intermediate" in text
    for kind in (
        "unselected_work",
        "material_decision",
        "new_authority",
        "external_prerequisite",
    ):
        assert kind in verify


def test_item_proof_cannot_borrow_aggregate_or_different_signal_evidence() -> None:
    instrument = " ".join(_read(INSTRUMENT_SKILL).split())
    verify = " ".join(_read(VERIFY_SKILL).split())
    flow = " ".join(_read(REPORT_FLOW).split())

    for text in (instrument, verify, flow):
        assert "aggregate receiver counts" in text.lower()
        assert "differently named signal" in text
        assert "not_proven" in text
    assert "render it as **Not proven**, not **Observed**" in instrument
    assert "never as `Observed`" in verify
    assert "must leave it `not_proven`" in flow


def test_item_direct_assertion_is_independent_from_finding_coverage() -> None:
    instrument = " ".join(_read(INSTRUMENT_SKILL).split())
    verify = " ".join((_read(VERIFY_SKILL) + _read(VERIFY_HANDOFF)).split())
    flow = " ".join(_read(REPORT_FLOW).split())
    report_tool = " ".join(_read(REPORT_TOOL).split())

    for text in (instrument, verify, flow):
        assert "direct_assertion_passed" in text
        assert "exact item or call site" in text
        assert "removed" in text.lower()
        assert "replacement owner" in text.lower()
    assert "finding or scenario coverage cannot" in report_tool
    assert "downgrade a passed item assertion" in report_tool
    assert 'direct_assertion_passed != (item_status == "working")' in report_tool
    assert "proof_mode not in ITEM_DIRECT_PROOF_MODES" in report_tool


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
