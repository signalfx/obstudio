from __future__ import annotations

import hashlib
import json
import runpy
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "evals/python/ai-assistant-demo/eval/inputs"
REPORT_TOOL = ROOT / "skills/otel-verify/scripts/observe_report.py"
INPUTS = {
    "otel-audit.json": "otel-audit.json",
    "otel-selection-ao.json": "otel-selection.json",
    "otel-instrumentation-ao.json": "otel-instrumentation.json",
    "otel-verify-ao.json": "otel-verify.json",
}


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPORT_TOOL), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_ao_verify_packet_is_bound_and_local_ack_is_not_cloud_proof() -> None:
    audit = FIXTURE / "otel-audit.json"
    selection = FIXTURE / "otel-selection-ao.json"
    instrumentation = FIXTURE / "otel-instrumentation-ao.json"
    verify = FIXTURE / "otel-verify-ao.json"
    result = _run(
        "validate-flow",
        str(audit),
        "--selection-json",
        str(selection),
        "--instrumentation-json",
        str(instrumentation),
        "--verify-json",
        str(verify),
    )
    assert result.returncode == 0, result.stderr

    selected = json.loads(selection.read_text(encoding="utf-8"))
    proof = json.loads(verify.read_text(encoding="utf-8"))
    assert selected["requested_ids"] == ["AO-003"]
    assert selected["approved_ids"] == ["OTEL-001", "AO-001", "AO-002", "AO-003"]
    assert proof["meta"]["result"] == "Partial"
    assert all(row["status"] == "not_proven" for row in proof["findings"])
    routing = proof["findings"][-1]["scenarios"][-1]
    assert routing["id"] == "ao.runtime.routing"
    assert routing["status"] == "not_proven"
    assert routing["proof_mode"] == "contract_only"
    assert routing["visibility"] == "otlp_accepted"
    assert proof["findings"][-1]["remaining"]

    evidence = (FIXTURE / "ao-gateway-verify-evidence.txt").read_text(encoding="utf-8")
    for header in ("projectid=", "logstreamid="):
        assert evidence.count(header) == 2
    assert "HTTP 202" in evidence
    assert "No cloud Agent Stream query" in evidence


def test_verify_render_preserves_existing_audit_html_bytes(tmp_path: Path) -> None:
    observe = tmp_path / ".observe"
    observe.mkdir()
    for source, dest in INPUTS.items():
        shutil.copyfile(FIXTURE / source, observe / dest)

    audit = observe / "otel-audit.json"
    selection = observe / "otel-selection.json"
    instrumentation = observe / "otel-instrumentation.json"
    verify = observe / "otel-verify.json"
    audit_html = observe / "otel.html"
    instrument_html = observe / "otel-instrumentation.html"

    rendered_audit = _run(
        "render-html", str(audit), "--selection-json", str(selection),
        "--repo-root", str(tmp_path), "-o", str(audit_html),
    )
    assert rendered_audit.returncode == 0, rendered_audit.stderr
    audit_before = hashlib.sha256(audit_html.read_bytes()).digest()

    rendered_instrumentation = _run(
        "render-instrumentation-html", str(audit),
        "--selection-json", str(selection),
        "--instrumentation-json", str(instrumentation),
        "--verify-json", str(verify),
        "--repo-root", str(tmp_path), "-o", str(instrument_html),
    )
    assert rendered_instrumentation.returncode == 0, rendered_instrumentation.stderr
    assert instrument_html.is_file()
    assert hashlib.sha256(audit_html.read_bytes()).digest() == audit_before
    audit_text = audit_html.read_text(encoding="utf-8")
    assert "Splunk Agent Observability" in audit_text
    assert "AO-003" in audit_text


def test_local_ack_cannot_be_promoted_to_pass(tmp_path: Path) -> None:
    inflated = json.loads((FIXTURE / "otel-verify-ao.json").read_text(encoding="utf-8"))
    inflated["meta"]["result"] = "Pass"
    inflated_path = tmp_path / "otel-verify.json"
    inflated_path.write_text(json.dumps(inflated), encoding="utf-8")
    result = _run(
        "validate-flow", str(FIXTURE / "otel-audit.json"),
        "--selection-json", str(FIXTURE / "otel-selection-ao.json"),
        "--instrumentation-json", str(FIXTURE / "otel-instrumentation-ao.json"),
        "--verify-json", str(inflated_path),
    )
    assert result.returncode != 0
    assert "Pass requires every finding to be working" in result.stderr


def test_reuse_policy_digest_comparison_isolates_only_target(tmp_path: Path) -> None:
    packet_paths = [
        FIXTURE / "ao-resource-audit.json",
        FIXTURE / "ao-resource-selection.json",
        FIXTURE / "ao-resource-instrumentation.json",
    ]
    original_bytes = {path: path.read_bytes() for path in packet_paths}
    original_selection = json.loads(original_bytes[packet_paths[1]])
    assert original_selection["requested_ids"] == ["AO-001", "AO-002"]

    engine = runpy.run_path(str(ROOT / "skills/references/scripts/observe_report.py"))
    audit = engine["normalize_audit_report"](json.loads(original_bytes[packet_paths[0]]))
    raw_paths = [tmp_path / "no-policy.raw.json", tmp_path / "reuse.raw.json"]
    for output, policy_flags in zip(raw_paths, [(), ("--ao-reuse-only",)]):
        selected = _run(
            "select", str(packet_paths[0]), "--ids", "AO-002",
            *policy_flags, "-o", str(output),
        )
        assert selected.returncode == 0, selected.stderr
    raw_packets = [json.loads(path.read_text(encoding="utf-8")) for path in raw_paths]
    assert [packet["schema_version"] for packet in raw_packets] == [1, 3]
    raw_before = [path.read_bytes() for path in raw_paths]

    no_policy, reuse = [
        engine["normalize_selection"]({**packet, "schema_version": 3}, audit)
        for packet in raw_packets
    ]
    for index, packet in enumerate((no_policy, reuse)):
        (tmp_path / f"paired-{index}.v3.json").write_text(
            json.dumps(packet, indent=2) + "\n", encoding="utf-8",
        )
        assert packet["requested_ids"] == ["AO-002"]
        assert packet["approved_ids"] == ["AO-001", "AO-002"]
        assert packet["schema_version"] == 3
        assert packet["decision_answers"] == []
        assert packet["approved_by"] is None
        assert packet["approved_at"] is None
    assert "ao_target" not in no_policy
    assert reuse["ao_target"] == {"create_if_missing": False}
    reuse_without_target = dict(reuse)
    del reuse_without_target["ao_target"]
    assert reuse_without_target == no_policy
    assert engine["selection_digest"](no_policy) != engine["selection_digest"](reuse)
    assert [path.read_bytes() for path in raw_paths] == raw_before
    assert {path: path.read_bytes() for path in packet_paths} == original_bytes


def test_destination_inputs_are_required_without_expanding_resource_scope(tmp_path: Path) -> None:
    audit_path = FIXTURE / "ao-resource-audit.json"
    original_bytes = audit_path.read_bytes()
    engine = runpy.run_path(str(ROOT / "skills/references/scripts/observe_report.py"))
    legacy = engine["normalize_audit_report"](json.loads(original_bytes))
    assert engine["ao_target_eligible_finding_ids"](legacy) == ["AO-001", "AO-002"]

    callback_path = ROOT / "evals/python/splunk-ao-langchain-demo/eval/inputs/otel-audit.json"
    callback_bytes = callback_path.read_bytes()
    callback_report = engine["normalize_audit_report"](json.loads(callback_bytes))
    assert engine["ao_target_eligible_finding_ids"](callback_report) == []
    assert all("ao_target_scope" not in row for row in callback_report["findings"])
    callback_copy = tmp_path / "actual-callback-unchanged.json"
    callback_copy.write_bytes(callback_bytes)
    callback_selection_path = tmp_path / "actual-callback-targetless.json"
    callback_selected = _run(
        "select", str(callback_copy), "--ids", "OTEL-001",
        "-o", str(callback_selection_path),
    )
    assert callback_selected.returncode == 0, callback_selected.stderr
    callback_selection = engine["normalize_selection"](
        json.loads(callback_selection_path.read_text(encoding="utf-8")), callback_report,
    )
    assert "ao_target" not in callback_selection
    assert 'id="ao-target-controls"' in engine["render_html"](callback_report, callback_selection)
    assert not engine["required_input_status"](engine["required_input_groups"](callback_report), callback_selection)["ready"]
    for target_flags in (
        ("--ao-reuse-only",),
        ("--ao-project", "review-project", "--ao-agent-stream", "review-agent"),
    ):
        output = tmp_path / f"actual-callback-{len(target_flags)}-target.json"
        targeted = _run(
            "select", str(callback_copy), "--ids", "OTEL-001",
            *target_flags, "-o", str(output),
        )
        assert targeted.returncode == 0, targeted.stderr
        bound = json.loads(output.read_text(encoding="utf-8"))
        assert bound["approved_ids"] == callback_selection["approved_ids"]
        assert engine["required_input_status"](engine["required_input_groups"](callback_report), bound)["ready"] is (len(target_flags) > 1)
    assert callback_copy.read_bytes() == callback_bytes
    assert callback_path.read_bytes() == callback_bytes

    for marked in (False, True):
        scratch = json.loads(original_bytes)
        for finding in scratch["findings"]:
            if finding["id"] in {"AO-001", "AO-002"}:
                finding.pop("ao_target_scope", None)
                for telemetry in finding["expected_telemetry"]:
                    if telemetry["type"] == "configuration":
                        telemetry["name"] = (
                            "custom.project-routing" if finding["id"] == "AO-001"
                            else "custom.agent-stream-routing"
                        )
                if marked:
                    finding["ao_target_scope"] = "resource-routing"
        report = engine["normalize_audit_report"](scratch)
        scratch_path = tmp_path / f"custom-routing-{marked}.json"
        scratch_path.write_text(json.dumps(report), encoding="utf-8")
        selection_path = tmp_path / f"custom-routing-{marked}-selection.json"
        targetless = _run(
            "select", str(scratch_path), "--ids", "AO-002",
            "-o", str(selection_path),
        )
        assert targetless.returncode == 0, targetless.stderr
        selection = engine["normalize_selection"](
            json.loads(selection_path.read_text(encoding="utf-8")), report,
        )
        assert "ao_target" not in selection
        expected_ids = ["AO-001", "AO-002"] if marked else []
        assert engine["ao_target_eligible_finding_ids"](report) == expected_ids
        rendered = engine["render_html"](report, selection)
        data_line = next(line for line in rendered.splitlines() if line.startswith("const DATA = "))
        data = json.loads(data_line.removeprefix("const DATA = ").removesuffix(";"))
        assert data["required_input_groups"][0]["finding_ids"] == [
            finding["id"] for finding in report["findings"]
            if finding.get("finding_group") == "splunk-agent-observability"
        ]
        assert 'id="ao-target-controls"' in rendered

        for target_flags in (
            ("--ao-reuse-only",),
            ("--ao-project", "review-project", "--ao-agent-stream", "review-agent"),
        ):
            output = tmp_path / f"custom-routing-{marked}-{len(target_flags)}-target.json"
            targeted = _run(
                "select", str(scratch_path), "--ids", "AO-002",
                *target_flags, "-o", str(output),
            )
            assert targeted.returncode == 0, targeted.stderr
            bound = json.loads(output.read_text(encoding="utf-8"))
            assert "ao_target" in bound
            assert bound["approved_ids"] == selection["approved_ids"]
            assert engine["required_input_status"](engine["required_input_groups"](report), bound)["ready"] is (len(target_flags) > 1)
    assert audit_path.read_bytes() == original_bytes
