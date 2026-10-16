from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from skill_contract import read_contract


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
    return read_contract(path)


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
    assert "DECISION_SELECTION_SCHEMA_VERSION = 2" in report_tool
    assert "CURRENT_SELECTION_SCHEMA_VERSION = 3" in report_tool
    assert "SUPPORTED_SELECTION_SCHEMA_VERSIONS = {1, 2, CURRENT_SELECTION_SCHEMA_VERSION}" in report_tool
    assert "CURRENT_AUDIT_SCHEMA_VERSION = 2" in report_tool
    assert "a selection carrying `decision_answers` is schema v2" in audit_normalized
    report_tests = _read(ROOT / "skills/references/tests/test_observe_report.py")
    assert "def test_ao_target_preserves_legacy_selection_shape_and_decisions" in report_tests
    assert "def test_selection_v3_ao_target_normalization_and_digest_binding" in report_tests


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


def test_shared_ao_target_binding_contract_is_explicit_for_every_consumer() -> None:
    flow = " ".join(_read(REPORT_FLOW).split())
    verification = flow.split("## Verification Report Contract", 1)[1]
    ownership = flow.split("## Document Ownership", 1)[1].split("## Human HTML Usage Flow", 1)[0]

    for term in (
        "any optional schema-v3 `ao_target`",
        "Changing an answer or AO target invalidates older instrumentation",
        "Preserve legacy schema-v1/v2 and targetless selection shapes and digests",
        "an absent `ao_target` stays absent",
        "exactly one Project name or ID and exactly one Agent Stream name or ID",
        "{create_if_missing: false}",
        "Reject partial selector pairs",
        "never change `requested_ids` or dependency-closed `approved_ids`",
    ):
        assert term in flow
    assert "optional schema-v3 `ao_target`" in ownership
    assert "changed decision answer, AO target" in verification
    assert "even when the selected finding IDs remain unchanged" in verification
    assert "`instrumentation_sha256`" in verification
    consumers = json.loads(_read(ROOT / "skills/references/consumers.json"))
    assert consumers["report-flow-contract.md"] == [
        "otel-audit", "otel-instrument", "otel-verify", "splunk-configure",
    ]
    assert _read(REPORT_FLOW) == _read(ROOT / "plugins/obstudio/skills/references/report-flow-contract.md")


def test_ao_target_handoff_evals_review_actual_snapshot_without_runtime_claims() -> None:
    fixture = ROOT / "evals/python/ai-assistant-demo/eval/inputs/ao-target-handoff-validator-snapshot.json"
    snapshot = json.loads(_read(fixture))
    resource_audit = json.loads(_read(fixture.parent / "ao-resource-audit.json"))
    readiness = resource_audit["genai_readiness"][0]
    runner = ast.parse(_read(ROOT / "evals/python/ai-assistant-demo/eval_runner.py"))
    logger_calls = {
        node.func.attr for node in ast.walk(runner)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name) and node.func.value.id == "logger"
    }
    assert {"start_trace", "add_llm_span", "conclude", "flush", "terminate"} <= logger_calls
    assert "add_workflow_span" not in logger_calls
    assert readiness["status"] == "partial"
    assert "Trace envelope" in readiness["required_signals"]
    assert "workflow" in readiness["acceptance_criteria"]
    assert "unproven" in readiness["acceptance_criteria"]
    assert snapshot["normalized_audit"]["genai_readiness"] == resource_audit["genai_readiness"]
    assert snapshot["producer"]["source"] == "skills/references/scripts/observe_report.py"
    assert snapshot["producer"]["source_sha256"] == "sha256:" + hashlib.sha256(REPORT_TOOL.read_bytes()).hexdigest()
    cases = {case["case"]: case for case in snapshot["selection_cases"]}
    for name in ("legacy-v1-no-target", "legacy-v2-no-target", "schema-v3-no-target"):
        assert cases[name]["outcome"] == "accepted"
        assert "ao_target" not in cases[name]["normalized_selection"]
    legacy_instrumentation = json.loads(_read(fixture.parent / "ao-resource-instrumentation.json"))
    assert cases["legacy-v1-no-target"]["selection_sha256"] == legacy_instrumentation["selection_sha256"]
    a, b = cases["schema-v3-names-a"], cases["schema-v3-names-b"]
    for ids in ("requested_ids", "approved_ids"):
        assert a["normalized_selection"][ids] == b["normalized_selection"][ids]
    assert a["selection_sha256"] != b["selection_sha256"]
    assert cases["schema-v3-policy-only-reuse"]["normalized_selection"]["ao_target"] == {"create_if_missing": False}
    assert cases["schema-v3-partial-selector"]["outcome"] == "rejected"
    for name in ("schema-v3-ids", "schema-v3-project-name-stream-id", "schema-v3-project-id-stream-name"):
        assert cases[name]["outcome"] == "accepted"
    bindings = snapshot["instrumentation_bindings"]
    assert bindings["names-a"]["instrumentation_sha256"] != bindings["names-b"]["instrumentation_sha256"]
    checks = {check["case"]: check for check in snapshot["binding_checks"]}
    assert checks["instrumentation-a-with-selection-a"]["outcome"] == "accepted"
    assert checks["stale-instrumentation-a-with-selection-b"]["error"] == "instrumentation.selection_sha256 does not match selection"
    assert checks["verification-a-with-instrumentation-a"]["outcome"] == "accepted"
    assert checks["stale-verification-a-with-instrumentation-b"]["error"] == "verify.instrumentation_sha256 does not match instrumentation"
    assert snapshot["normalized_verification_names_a"]["meta"]["result"] == "Not run"
    roles = {
        "audit": ("otel-audit", "proposed names"),
        "instrument": ("otel-instrument", "effective-profile precedence"),
        "verify": ("otel-verify", "Rejects cached verification"),
        "configure": ("splunk-configure", "metric readiness, detector coverage"),
    }
    for role, (skill, role_requirement) in roles.items():
        packet = json.loads(_read(ROOT / f"evals/python/ai-assistant-demo/eval/qual/ao-target-handoff-{role}.json"))
        assert packet["skill"] == skill
        assert len(packet["rubric"]) == (3 if role == "configure" else 4)
        assert role_requirement in packet["rubric"][2]
        if role != "configure":
            assert "aria-invalid" in packet["rubric"][3]
            assert "valid peer" in packet["rubric"][3]
        expected_inputs = {"eval/inputs/ao-target-handoff-validator-snapshot.json"}
        if role != "configure":
            expected_inputs.add("eval/inputs/ao-selector-field-validity-snapshot.json")
        inputs = packet["prompts"][0]["eval_inputs"]
        assert set(inputs) == expected_inputs
        assert len(inputs) == len(expected_inputs)
        task = packet["prompts"][0]["task"]
        for phrase in (
            "Read-only supplemental AO target handoff contract review",
            ("Review the supplied snapshot only" if role == "configure"
             else "Review the supplied snapshots only"),
            "do not invoke a new normalizer",
            "Write only ./service/.observe/ao-target-handoff-review.json and .md",
            "supplied canonical-validator evidence rather than engine execution",
        ):
            assert phrase.lower() in task.lower()
        assert "No resource creation" in snapshot["proof_limits"][2]


def test_ao_target_handoff_ui_snapshot_records_bound_field_validity() -> None:
    inputs = ROOT / "evals/python/ai-assistant-demo/eval/inputs"
    ui = json.loads(_read(inputs / "ao-selector-field-validity-snapshot.json"))
    validator = json.loads(_read(inputs / "ao-target-handoff-validator-snapshot.json"))
    assert ui["schema_version"] == 1
    assert ui["kind"] == "ao-selector-field-validity-browser-snapshot"
    assert ui["outcome"] == "pass"
    assert ui["producer"]["engine_sha256"] == hashlib.sha256(REPORT_TOOL.read_bytes()).hexdigest()
    assert ui["producer"]["audit_fixture_sha256"] == hashlib.sha256(
        (inputs / "ao-resource-audit.json").read_bytes()
    ).hexdigest()
    assert ui["fixture"]["normalized_audit_sha256"] == validator["audit_sha256"]
    assert ui["fixture"]["requested_finding_ids"] == ["AO-002"]
    assert ui["fixture"]["approved_finding_ids"] == ["AO-001", "AO-002"]
    assert ui["fixture"]["unselected_finding_ids"] == ["OTEL-001"]
    assert ui["scope_unchanged"]["initial"] == ui["scope_unchanged"]["final"] == {
        "requested": ui["fixture"]["requested_finding_ids"],
        "selected": ui["fixture"]["approved_finding_ids"],
    }
    assert ui["case_encoding"]["aria_invalid_order"] == ["project", "agent_stream"]
    assert {(case["resource"], case["selector"]) for case in ui["cases"]} == {
        (resource, selector)
        for resource in ("project", "agent_stream") for selector in ("name", "id")
    }
    count = 0
    for case in ui["cases"]:
        seen = set()
        for values in case["rows"]:
            assert len(values) == len(ui["case_encoding"]["columns"])
            row = dict(zip(ui["case_encoding"]["columns"], values))
            seen.add(row["scenario_id"])
            assert row["expected_aria_invalid"] == row["actual_aria_invalid"]
            assert row["expected_command_blocked"] is row["actual_command_blocked"]
            count += 1
        assert seen == set(ui["scenario_definitions"])
        assert len(case["rows"]) == len(seen)
    assert count == ui["field_matrix_case_count"]
    assert ui["case_count"] == count + len(ui["viewports"]) + 1


def test_ao_target_scope_snapshots_preserve_resource_and_content_boundary() -> None:
    inputs = ROOT / "evals/python/ai-assistant-demo/eval/inputs"
    validator = json.loads(_read(inputs / "ao-target-handoff-validator-snapshot.json"))
    cases = {case["case"]: case for case in validator["ao_target_scope_cases"]}
    assert len(cases) == len(validator["ao_target_scope_cases"]) == 14
    assert validator["producer"]["source_sha256"] == "sha256:" + hashlib.sha256(REPORT_TOOL.read_bytes()).hexdigest()
    assert cases["actual-callback-targetless"]["outcome"] == "accepted"
    assert cases["actual-callback-targetless"]["eligible_ids"] == []
    for name in ("actual-callback-target-pair-rejected", "actual-callback-policy-only-rejected",
                 "callback-ao-id-target-pair-rejected", "resource-unselected-otel-target-rejected",
                 "unmarked-unknown-route-rejected"):
        assert cases[name]["outcome"] == "rejected"
        assert "requires a selected Agent Observability resource or routing finding" in cases[name]["error"]
    marked = cases["explicit-marked-route-accepted"]
    assert marked["outcome"] == "accepted"
    assert marked["eligible_ids"] == ["AO-002"]
    assert any(finding.get("ao_target_scope") == "resource-routing" for finding in marked["finding_classification"])
    legacy_names = ("project", "agent-stream", "project-resource", "agent-stream-resource",
                    "runtime-routing", "splunk-ao-routing")
    for name in legacy_names:
        case = cases["legacy-agent-observability." + name + "-accepted"]
        assert case["outcome"] == "accepted"
        assert case["eligible_ids"] == ["AO-001", "AO-002"]
        assert all("ao_target_scope" not in finding for finding in case["finding_classification"])
    preserved = cases["targetless-fixture-digest-preserved"]
    selection = json.loads(_read(inputs / "ao-resource-selection.json"))
    assert preserved["legacy_normalized_audit_unchanged"] is True
    assert preserved["legacy_audit_sha256"] == selection["audit_sha256"] == validator["audit_sha256"]
    assert preserved["legacy_selection_sha256"] == json.loads(_read(inputs / "ao-resource-instrumentation.json"))["selection_sha256"]
    for role in ("audit", "instrument", "verify", "configure"):
        packet = json.loads(_read(ROOT / f"evals/python/ai-assistant-demo/eval/qual/ao-target-handoff-{role}.json"))
        assert "ao_target_scope_cases" in packet["prompts"][0]["task"]
        assert "resource-routing" in packet["rubric"][0]
        assert "callback" in packet["rubric"][0]
        criterion = packet["rubric"][0].lower()
        assert "marker" in criterion and ("absent" in criterion or "omitted" in criterion)
    ui = json.loads(_read(inputs / "ao-selector-field-validity-snapshot.json"))
    gate = ui["ao_target_scope_gate"]
    assert gate["producer_engine_sha256"] == hashlib.sha256(REPORT_TOOL.read_bytes()).hexdigest()
    assert len(gate["cases"]) == 4
    for case in gate["cases"]:
        assert case["outcome"] == "pass"
        assert case["actual"]["controls_visible"] is case["expected_controls_visible"]
        assert case["actual"]["command_has_ao_target_flags"] is case["expected_controls_visible"]
    browser = {case["case"]: case for case in gate["cases"]}
    assert browser["actual-callback-content-OTEL001"]["actual"]["controls_present"] is False
    hidden = browser["unselected-resource-findings-with-retained-values"]
    assert hidden["actual"]["controls_hidden"] is True
    assert hidden["actual"]["controls_inert"] is True
    assert hidden["retained_field_values_unchanged"] is True
    assert browser["reselected-resource-recovers-retained-values"]["retained_field_values_unchanged"] is True
    assert len(gate["canonical_selection_cases"]) == 4
    for case in gate["canonical_selection_cases"]:
        assert case["outcome"] == "pass"
        assert case["actual_outcome"] == case["expected_outcome"]
