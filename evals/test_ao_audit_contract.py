"""Focused checks for AO audit evidence and local gateway selection guidance."""

from pathlib import Path
from skill_contract import read_contract


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_ao_audit_requires_early_compatibility_evidence_and_gateway_candidate():
    canonical = read_contract(REPO_ROOT / "skills/otel-audit/SKILL.md")
    bundled = read_contract(REPO_ROOT / "plugins/obstudio/skills/otel-audit/SKILL.md")
    assert canonical == bundled

    discovery = canonical.split("### Step 1 -- Repository Discovery", 1)[1].split(
        "### Step 2 -- Instrumentation Assessment", 1
    )[0]
    for term in (
        "Before scoring AO routing",
        "canonical Audit Evidence",
        "selected resource API/authentication",
        "existing exporter's",
        "per-request trace routing separately",
        "`supported`",
        "`unsupported`",
        "`unverified`",
        "exact package/runtime evidence unavailable",
        "Do not defer this classification",
        "fresh cloud Agent Stream receipt",
        "Splunk Observability Studio as the preferred local AO gateway candidate",
        "availability and concrete endpoint `unverified`",
        "never invent an address",
    ):
        assert term in " ".join(discovery.split())

    gate = canonical.split("Before `finalize-audit`, apply this AO acceptance gate", 1)[1]
    for term in (
        "selected resource client's project/Agent Stream API endpoint",
        "authentication and existing exporter's per-request trace-route compatibility",
        "SDK-owned path", "Do not require SDK variables or a new AO SDK dependency",
    ):
        assert term in " ".join(gate.split())
    assert "do not defer them to the acceptance scenario" in " ".join(gate.split())


def test_ao_route_dependency_closure_includes_nested_retrieval_producer():
    canonical = read_contract(REPO_ROOT / "skills/otel-audit/SKILL.md")
    contract = canonical.split("An AO routing finding's transitive dependency closure", 1)[1].split(
        "For a new live AO sink", 1
    )[0]
    for term in (
        "nested retrieval spans",
        "each required live GenAI readiness surface",
        "verification scenario",
        "included separately from the tool finding",
    ):
        assert term in " ".join(contract.split())


def test_ao_audit_reports_destination_scoped_header_contracts():
    import json

    canonical = read_contract(REPO_ROOT / "skills/otel-audit/SKILL.md")
    bundled = read_contract(REPO_ROOT / "plugins/obstudio/skills/otel-audit/SKILL.md")
    assert canonical == bundled
    contract = canonical.split("For AO/native routing assessments", 1)[1].split(
        "For each inspected creator", 1
    )[0]
    for term in (
        "separate destination-scoped header",
        "current Studio uses `projectid` and `logstreamid`",
        "public standalone AO uses `projectid` and `agentstreamid`",
        "applicability", "`supported`/`unsupported`/`unverified` status",
        "source or captured protocol evidence",
        "never call it a globally unsupported alias",
        "without claiming it was executed or changing the route",
    ):
        assert term in " ".join(contract.split())

    case = json.loads((REPO_ROOT / "evals/python/existing-otel-agent-demo/eval/qual/route-recovery-audit.json").read_text())
    criterion = case["rubric"][3]
    for term in ("separate applicability and status", "source evidence", "projectid/logstreamid",
                 "projectid/agentstreamid", "globally unsupported alias"):
        assert term in criterion


def test_galileo_preservation_audit_validates_and_selects_both_destination_choices(tmp_path):
    import json
    import subprocess
    import sys

    source = REPO_ROOT / "evals/python/galileo-agent-demo/eval/inputs/otel-audit-integration-choice.json"
    original = source.read_bytes()
    helper = REPO_ROOT / "skills/otel-audit/scripts/observe_report.py"
    validation = subprocess.run(
        [sys.executable, str(helper), "validate", str(source)], capture_output=True, text=True,
    )
    assert validation.returncode == 0, validation.stdout + validation.stderr
    for option, selected_id in (("keep-galileo", "OTEL-002"), ("route-existing-otel", "AO-001")):
        output = tmp_path / f"{option}.json"
        selected = subprocess.run(
            [sys.executable, str(helper), "select", str(source), "--ids", selected_id,
             "--decision", f"OTEL-001={option}", "--output", str(output)],
            capture_output=True, text=True,
        )
        assert selected.returncode == 0, selected.stdout + selected.stderr
        selection = json.loads(output.read_text())
        assert selection["requested_ids"] == selection["approved_ids"] == [selected_id]
        assert selection["decision_answers"] == [{"finding_id": "OTEL-001", "option_id": option}]
    assert source.read_bytes() == original
