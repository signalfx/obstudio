from __future__ import annotations

import hashlib
import json
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
