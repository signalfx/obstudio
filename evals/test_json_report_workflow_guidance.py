from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_SKILL = ROOT / "skills" / "otel-audit" / "SKILL.md"
INSTRUMENT_SKILL = ROOT / "skills" / "otel-instrument" / "SKILL.md"
VERIFY_SKILL = ROOT / "skills" / "otel-verify" / "SKILL.md"
INSTRUMENT_HANDOFF = ROOT / "skills" / "otel-instrument" / "references" / "json-approval-handoff.md"
INSTRUMENT_REPORT = (
    ROOT
    / "skills"
    / "otel-instrument"
    / "references"
    / "instrumentation-report.md"
)
INSTRUMENT_REPAIR = (
    ROOT / "skills" / "otel-instrument" / "references" / "repair-loop.md"
)
INSTRUMENT_FINALIZATION = (
    ROOT / "skills" / "otel-instrument" / "references" / "finalization.md"
)
VERIFY_HANDOFF = ROOT / "skills" / "otel-verify" / "references" / "json-approval-handoff.md"
VERIFY_DIRECT = ROOT / "skills" / "otel-verify" / "references" / "direct-verification.md"
VERIFY_REPORT = ROOT / "skills" / "otel-verify" / "references" / "verification-report.md"
JAVA_INSTRUMENT_REFERENCE = (
    ROOT / "skills" / "otel-instrument" / "references" / "languages" / "java.md"
)
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


def test_active_report_references_do_not_use_legacy_paths() -> None:
    assert INSTRUMENT_REPORT.is_file()
    assert VERIFY_DIRECT.is_file()
    assert not INSTRUMENT_REPORT.with_name(
        "legacy-instrumentation-report.md"
    ).exists()
    assert not VERIFY_DIRECT.with_name("legacy-verification.md").exists()


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
    assert "cannot enter the selection" in instrument_normalized
    assert "audit and scope-planning surface" in instrument_normalized
    assert "selected-scope closure" in instrument_normalized

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
    assert "Write two audit artifacts" in audit_normalized
    assert "Omit `flow` and `signal_flow` from new audits" in audit_normalized
    assert "do not present `$otel-verify` or generic `run verification` as the audit prompt's next step" in audit_normalized.lower()
    assert 'python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py"' in audit
    assert "--normalized-out" not in audit
    assert "otel-audit.normalized.json" not in audit


def test_context_handoffs_are_binding_and_fail_closed() -> None:
    instrument = " ".join(_read(INSTRUMENT_HANDOFF).split())
    verify = " ".join(_read(VERIFY_HANDOFF).split())
    shared = " ".join(_read(REPORT_FLOW).split())
    java = " ".join(_read(JAVA_INSTRUMENT_REFERENCE).split())

    for term in (
        "binding non-regression obligations",
        "inventory every source consumer",
        "preserve the producer-to-consumer handoff",
        "focused consumer-side test",
        "one `context_handoffs` row per source consumer",
    ):
        assert term in instrument

    for term in (
        "inspect every source consumer",
        "downstream consumer",
        "context_propagation_proof",
        "same_trace_assertion_passed",
        "relationship_assertion_passed",
        "Missing mapped proof is `not_proven`",
        "scenario `not_working`",
    ):
        assert term in verify

    for term in (
        "context_propagation_proof",
        "Older context-propagation instrumentation and verification overlays",
        "not grandfathered",
    ):
        assert term in shared

    for term in (
        "contextWrite",
        "deferContextual",
        "ContextView.get",
        "subscriber-side test",
    ):
        assert term in java


def test_instrument_progressively_loads_only_the_report_contract_it_needs() -> None:
    instrument = _read(INSTRUMENT_SKILL)
    handoff = _read(INSTRUMENT_HANDOFF)
    report = _read(INSTRUMENT_REPORT)
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
    assert "direct no-audit flow" in opening
    assert "`./references/instrumentation-report.md`" in instrument
    assert "only when producing" in instrument
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
    assert "## Reader Order" in report
    assert "Markdown is output, not scope" in report
    assert len(instrument.splitlines()) < 500
    assert len(instrument.split()) < 4500


def test_instrument_routes_conditional_detail_to_resolvable_local_references() -> None:
    instrument = _read(INSTRUMENT_SKILL)
    go_reference = (
        INSTRUMENT_SKILL.parent / "references" / "languages" / "go.md"
    )

    for route, reference in (
        ("./references/instrumentation-report.md", INSTRUMENT_REPORT),
        ("./references/repair-loop.md", INSTRUMENT_REPAIR),
        ("./references/finalization.md", INSTRUMENT_FINALIZATION),
    ):
        assert route in instrument
        assert reference.is_file()

    assert "./references/languages/{python,node,java,go}.md" in instrument
    assert go_reference.is_file()
    assert "## Signals Changed" not in instrument
    assert "## Signals Changed" in _read(INSTRUMENT_REPORT)
    assert "## Failure Ownership" not in instrument
    assert "## Failure Ownership" in _read(INSTRUMENT_REPAIR)
    assert "## Terminal Sequence" not in instrument
    assert "## Terminal Sequence" in _read(INSTRUMENT_FINALIZATION)
    assert "scripts/resolve_go_otel_versions.py" not in instrument
    assert "scripts/resolve_go_otel_versions.py" in _read(go_reference)


def test_verify_progressively_loads_only_the_report_contract_it_needs() -> None:
    verify = _read(VERIFY_SKILL)
    handoff = _read(VERIFY_HANDOFF)
    direct = _read(VERIFY_DIRECT)
    report = _read(VERIFY_REPORT)
    opening = verify.split("## Contract", 1)[0]
    opening_normalized = " ".join(opening.split())
    canonical_gate = verify.split("#### Canonical Scope Gate", 1)[1].split(
        "### 2.", 1
    )[0]

    assert "Do not load `../references/report-flow-contract.md` as an up-front" in opening
    assert "For canonical JSON flow, read" in opening_normalized
    assert "`./references/json-approval-handoff.md`" in opening_normalized
    assert "no canonical audit exists" in opening_normalized
    assert "`./references/direct-verification.md`" in opening_normalized
    assert "`./references/verification-report.md`" in opening_normalized
    assert "read and follow `./references/json-approval-handoff.md`" in " ".join(
        canonical_gate.split()
    )
    assert "this file is the scoped verification and reader-report authority" in " ".join(
        handoff.split()
    )
    assert "Do not also load `../../references/report-flow-contract.md`" in handoff
    assert "unless a conditional downstream workflow explicitly requires" in " ".join(
        handoff.split()
    )
    direct_normalized = " ".join(direct.split())
    assert "direct explicit-user verification scope" in direct_normalized
    assert "direct concrete user request and current source as scope" in direct_normalized
    assert "Never combine this path with canonical" in direct_normalized
    assert "## Reader Report" in report
    assert len(verify.splitlines()) < 500
    assert len(verify.split()) < 3500


def test_verify_routes_conditional_detail_to_resolvable_local_references() -> None:
    verify = _read(VERIFY_SKILL)
    routes = (
        ("./references/json-approval-handoff.md", VERIFY_HANDOFF),
        ("./references/direct-verification.md", VERIFY_DIRECT),
        ("./references/verification-report.md", VERIFY_REPORT),
    )
    for route, reference in routes:
        assert route in verify
        assert reference.is_file()

    assert "## Reader Report" not in verify
    assert "## Reader Report" in _read(VERIFY_REPORT)
    assert "## Conservative Closure" not in verify
    assert "## Conservative Closure" in _read(VERIFY_DIRECT)
    assert "## Verification JSON" not in verify
    assert "## Verification JSON" in _read(VERIFY_HANDOFF)


def test_instrument_resolves_one_bundle_local_verifier() -> None:
    instrument = _read(INSTRUMENT_SKILL)
    normalized = " ".join(instrument.split())

    assert "../otel-verify/SKILL.md" in instrument
    assert "only authoritative verifier" in normalized
    assert "Never search `$CODEX_HOME`" in instrument
    assert "never compare alternate installed copies" in normalized
    assert "installed Obstudio skill bundle is incomplete" in normalized
    assert "Load that sibling once and reuse it" in normalized


def test_instrument_keeps_verification_results_in_bound_child_overlay() -> None:
    definition = json.loads(_read(INSTRUMENT_EVAL))
    rubric = " ".join(definition["rubric"])
    instrument = " ".join(_read(INSTRUMENT_SKILL).split())
    handoff = " ".join(_read(INSTRUMENT_HANDOFF).split())

    assert "separately bound .observe/otel-verify.json carries verification results" in rubric
    assert "scenario mappings" in rubric
    assert "verification_handoff" not in rubric
    assert "remaining_gaps" not in rubric
    assert "separately bound verify overlay owns verification results" in instrument
    assert "do not duplicate them as new instrumentation schema fields" in handoff
    assert "rejects any stale pending-verification CTA" in handoff


def test_chi_prompts_expose_only_the_inputs_the_workflow_owns() -> None:
    fixture = ROOT / "evals" / "go" / "chi-basic" / "eval" / "qual"
    audit_definitions = ("audit.json", "benchmark-audit.json")
    instrument_definitions = (
        "benchmark-instrument.json",
        "instrument.json",
        "instrument-decision-gated.json",
    )

    for name in audit_definitions:
        definition = json.loads(_read(fixture / name))
        assert all(prompt["eval_inputs"] == [] for prompt in definition["prompts"])

    for name in instrument_definitions:
        definition = json.loads(_read(fixture / name))
        assert all(
            prompt["eval_inputs"] == ["eval/inputs/otel-audit.json"]
            for prompt in definition["prompts"]
        )

    verify = json.loads(_read(fixture / "verify.json"))
    assert verify["prompts"][0]["eval_inputs"] == [
        "eval/inputs/canonical-verify-evidence.txt",
        "eval/inputs/otel-audit.json",
        "eval/inputs/otel-instrumentation.json",
        "eval/inputs/otel-selection.json",
        "eval/inputs/otel-verify.json",
    ]

    ai_instrument = json.loads(
        _read(
            ROOT
            / "evals"
            / "python"
            / "ai-assistant-demo"
            / "eval"
            / "qual"
            / "instrument.json"
        )
    )
    assert ai_instrument["prompts"][0]["eval_inputs"] == [
        "eval/inputs/otel-audit.json"
    ]


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
    skill = _read(INSTRUMENT_SKILL)
    instrument = " ".join(skill.split())
    finalization_raw = _read(INSTRUMENT_FINALIZATION)
    finalization = " ".join(finalization_raw.split())
    repair = " ".join(_read(INSTRUMENT_REPAIR).split())
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

    assert "`./references/finalization.md` exactly once" in instrument
    for term in (
        "`finalize-instrumentation`",
        "includes `instrumentation-final-gate`",
        "successful explicit no-child validation",
        "successful stopped-failure validation",
        "emit the final response without another command",
        "`git status`",
        "`git diff`",
        "inspect `go.sum`",
        "repeat a validator/test",
        "duplicate final review",
        "without `--verify-json`",
        "Never fabricate audit, selection, instrumentation, or verification JSON",
    ):
        assert term in finalization

    for term in (
        "`meta.result: Fail`",
        "`stop_boundaries[]`",
        "repair-only finding `remaining`",
        "never turns an observed telemetry failure into `Blocked` or `not_proven`",
    ):
        assert term in repair

    assert "Do not run `instrumentation-final-gate`" in handoff
    assert "the parent `SKILL.md` owns the actual gate" in handoff
    assert "This is preliminary Step 5 validation" in handoff
    assert "stopped-failure handoff" in handoff
    assert "not a completed or verified instrumentation result" in handoff
    assert "Treat a passing `instrumentation-final-gate`" not in handoff

    terminal = finalization_raw.index("## Terminal Sequence")
    assert finalization_raw.index("## VS Code Debugging") < terminal
    assert finalization_raw.index("## Final Report And Response") < terminal
    assert finalization_raw.index("## Credential Safety") < terminal
    assert finalization_raw.rfind("\n## ") + 1 == terminal
    assert "requested detector/configure workflow" in finalization
    assert "Direct No-Audit Branch" in finalization
    assert "Do not seek or invoke a canonical gate" in finalization
    assert "The last successful applicable validation is terminal" in finalization
    assert "direct no-audit workflow remains available" in instrument
    assert "Successful cleanup is the terminal boundary" in go_guide
    assert "explicit canonical no-child validation" in go_guide
    assert "applicable terminal check" in go_guide
    assert "direct no-audit validation" in go_guide
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


def test_audit_final_handoff_requires_clickable_report_links() -> None:
    audit = _read(AUDIT_SKILL)
    normalized = " ".join(audit.split())

    assert "`links.review_report` and" in audit
    assert "`links.machine_report`; copy those Markdown link values verbatim" in audit
    assert "Review report: [otel.html](/absolute/repo/.observe/otel.html)" in audit
    assert "Review report: .observe/otel.html` is an invalid handoff" in normalized


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
        (
            _read(INSTRUMENT_SKILL)
            + _read(INSTRUMENT_HANDOFF)
            + _read(INSTRUMENT_REPAIR)
        ).split()
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
