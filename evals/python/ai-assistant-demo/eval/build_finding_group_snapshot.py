"""Capture real report projections for bounded consumer-contract reviews."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess


GENERATOR = Path(__file__).resolve()
ROOT = GENERATOR.parents[4]
HELPER = ROOT / "skills/references/tests/test_observe_report.py"
SPEC = importlib.util.spec_from_file_location("group_fixture", HELPER)
assert SPEC and SPEC.loader
FIXTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIXTURE)
ENGINE = FIXTURE.MODULE
NODE = r"""
const fs = require('node:fs'), vm = require('node:vm');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const cards = {innerHTML: ''};
const context = {
  DISPLAY_FINDINGS: payload.findings,
  renderFindingCard: f => `<article data-finding-id="${f.id}"></article>`,
  document: {getElementById: id => id === 'cards' ? cards : null},
  syncFindingSelectionState: () => {}, esc: value => String(value),
};
vm.runInNewContext(payload.source + '\nrenderCards();', context);
process.stdout.write(cards.innerHTML);
"""


def projection(report: dict, source: str, ids: list[str]) -> str:
    by_id = {f["id"]: f for f in report["findings"]}
    return subprocess.run(
        ["node", "-e", NODE],
        input=json.dumps({"source": source, "findings": [by_id[i] for i in ids]}),
        text=True,
        capture_output=True,
        check=True,
    ).stdout


def render_source(report: dict) -> str:
    html = ENGINE.render_html(report, ENGINE.empty_selection(report))
    return html[
        html.index("function renderCards() {") : html.index(
            "function orderedSelection()"
        )
    ]


def main() -> None:
    data = FIXTURE.sample_splunk_agent_observability_report()
    data["signal_flow"] = {
        "component_flow_map": "Synthetic report projection; no application execution."
    }
    data["findings"][1]["id"] = "OTEL-007"
    for identifier in ("OTEL-008", "OTEL-009", "AO-777"):
        row = copy.deepcopy(data["findings"][1])
        row.update(
            id=identifier,
            area=f"Projection diagnostic {identifier}",
            priority="deferred" if identifier == "AO-777" else "recommended",
        )
        data["findings"].insert(2, row)
    data["findings"][-1]["priority"] = "recommended"
    row = copy.deepcopy(data["findings"][-2])
    row.update(
        id="OTEL-777",
        area="AO callback content guard",
        priority="deferred",
        title="AO callback content guard",
    )
    row["expected_telemetry"][0]["name"] = "splunk-ao.callback.capture-guard"
    data["findings"].append(row)
    data["recommendation"] = ["Select executable findings and run $otel-instrument."]
    data["signal_flow"]["component_flow_map"] = "\n".join(
        f"fixture [GAP: {f['area']}]" for f in data["findings"]
    )
    report = ENGINE.normalize_audit_report(data)
    selection = ENGINE.normalize_selection(
        {
            "schema_version": 2,
            "kind": "otel-selection",
            "audit_id": report["meta"]["audit_id"],
            "audit_sha256": ENGINE.audit_digest(report),
            "requested_ids": ["AO-002", "OTEL-008"],
        },
        report,
    )
    before = copy.deepcopy(report)
    source = render_source(report)
    records = [
        {
            "id": "record-a",
            "audit": report,
            "selection": selection,
            "display_finding_ids": ENGINE.display_finding_ids(report),
            "rendered_cards_html": projection(
                report, source, ENGINE.display_finding_ids(report)
            ),
        }
    ]
    interleaved_ids = [
        f["id"]
        for f in sorted(
            report["findings"], key=lambda f: ENGINE.PRIORITY_RANK[f["priority"]]
        )
    ]
    interleaved_source = """
function renderCards() {
  document.getElementById('cards').innerHTML = DISPLAY_FINDINGS.map(f => {
    const card = renderFindingCard(f);
    return f.finding_group === 'splunk-agent-observability'
      ? `<section><h3>Splunk Agent Observability findings</h3>${card}</section>`
      : card;
  }).join('');
}
"""
    records.append(
        {
            **records[0],
            "id": "record-b",
            "display_finding_ids": interleaved_ids,
            "rendered_cards_html": projection(report, interleaved_source, interleaved_ids),
        }
    )
    prefix_source = source.replace(
        'row.finding.finding_group !== "splunk-agent-observability"',
        '!row.finding.id.startsWith("AO-")',
    ).replace(
        'row.finding.finding_group === "splunk-agent-observability"',
        'row.finding.id.startsWith("AO-")',
    )
    records.append(
        {
            **records[0],
            "id": "record-c",
            "rendered_cards_html": projection(
                report, prefix_source, ENGINE.display_finding_ids(report)
            ),
        }
    )
    for name, keep in (("record-d", False), ("record-e", True), ("record-f", None)):
        raw = copy.deepcopy(data)
        raw["findings"] = [
            f
            for f in raw["findings"]
            if keep is not None
            and (f.get("finding_group") == "splunk-agent-observability") == keep
        ]
        if not raw["findings"]:
            raw["meta"]["status"] = "Pass"
        present = {f["id"] for f in raw["findings"]}
        for finding in raw["findings"]:
            finding["dependencies"] = [
                i for i in finding.get("dependencies", []) if i in present
            ]
        raw["signal_flow"]["component_flow_map"] = (
            "\n".join(f"fixture [GAP: {f['area']}]" for f in raw["findings"])
            or "No fixture gaps."
        )
        subset = ENGINE.normalize_audit_report(raw)
        records.append(
            {
                "id": name,
                "audit": subset,
                "selection": ENGINE.empty_selection(subset),
                "display_finding_ids": ENGINE.display_finding_ids(subset),
                "rendered_cards_html": projection(
                    subset, render_source(subset), ENGINE.display_finding_ids(subset)
                ),
            }
        )
    assert report == before
    snapshot = {
        "evidence_basis": "Executed Python normalizers and Node VM renderCards with a stub card renderer; no browser, application, SDK, Terraform or cloud execution.",
        "producer": {
            "engine_sha256": hashlib.sha256(
                Path(ENGINE.__file__).read_bytes()
            ).hexdigest(),
            "script_sha256": hashlib.sha256(GENERATOR.read_bytes()).hexdigest(),
            "functions": [
                "normalize_audit_report",
                "normalize_selection",
                "display_finding_ids",
                "renderCards",
            ],
            "projection_source_sha256": {
                "record-a": hashlib.sha256(source.encode()).hexdigest(),
                "record-b": hashlib.sha256(interleaved_source.encode()).hexdigest(),
                "record-c": hashlib.sha256(prefix_source.encode()).hexdigest(),
            },
            "counterexamples": {
                "record-b": "Synthetic invalid per-card grouping, executed in Node VM.",
                "record-c": "Synthetic invalid ID-prefix classification, executed in Node VM.",
            },
        },
        "identity_checks": {
            "canonical_audit_unchanged": report == before,
            "audit_sha256": ENGINE.audit_digest(report),
            "selection_sha256": ENGINE.selection_digest(selection),
            "requested_ids": selection["requested_ids"],
            "approved_ids": selection["approved_ids"],
        },
        "records": records,
    }
    requirements = []
    for case_id, ids, target in (
        ("ordinary-only", ["OTEL-007"], None),
        ("agent-targetless", ["AO-002"], None),
        ("agent-policy-only", ["AO-002"], {"create_if_missing": False}),
        (
            "agent-complete",
            ["AO-002"],
            {"project_name": "review-project", "agent_stream_id": "review-stream"},
        ),
        (
            "callback-complete",
            ["OTEL-777"],
            {"project_id": "review-project", "agent_stream_name": "review-stream"},
        ),
        ("callback-targetless", ["OTEL-777"], None),
        ("ordinary-ao-prefix", ["AO-777"], None),
    ):
        packet = {
            "schema_version": 3,
            "kind": "otel-selection",
            "audit_id": report["meta"]["audit_id"],
            "audit_sha256": ENGINE.audit_digest(report),
            "requested_ids": ids,
        }
        if target is not None:
            packet["ao_target"] = target
        normalized = ENGINE.normalize_selection(packet, report)
        requirements.append(
            {
                "id": case_id,
                "selection": normalized,
                "selection_sha256": ENGINE.selection_digest(normalized),
                "resource_routing_selected": any(
                    finding_id in normalized["approved_ids"]
                    for finding_id in ENGINE.ao_target_eligible_finding_ids(report)
                ),
                "status": ENGINE.required_input_status(
                    ENGINE.required_input_groups(report), normalized
                ),
            }
        )
    groups = [
        {
            "key": "deployment",
            "finding_ids": ["DEPLOY-1"],
            "fields": [
                {
                    "key": "region",
                    "label": "Deployment region",
                    "selectors": ["region_name", "region_id"],
                },
                {"key": "cluster", "label": "Cluster", "selectors": ["cluster"]},
            ],
        }
    ]
    values = {"approved_ids": ["DEPLOY-1"], "deployment": {"region_id": "region-1"}}
    requirements.append(
        {
            "id": "generic-partial",
            "groups": groups,
            "selection": values,
            "status": ENGINE.required_input_status(groups, values),
        }
    )
    snapshot["required_inputs_cases"] = requirements
    snapshot["required_input_groups"] = ENGINE.required_input_groups(report)
    output = GENERATOR.parent / "inputs/finding-group-snapshot.json"
    output.write_text(json.dumps(snapshot, indent=2) + "\n")
    print(f"Wrote {output.relative_to(ROOT)} ({len(records)} projections)")
    refresh_handoff_snapshot()


def refresh_handoff_snapshot() -> None:
    inputs = GENERATOR.parent / "inputs"
    output = inputs / "ao-target-handoff-validator-snapshot.json"
    previous = json.loads(output.read_text())
    audit = ENGINE.normalize_audit_report(json.loads((inputs / "ao-resource-audit.json").read_text()))
    cases = []
    for case in previous["selection_cases"]:
        row = {"case": case["case"], "input": case["input"]}
        try:
            selection = ENGINE.normalize_selection(row["input"], audit)
            row.update(outcome="accepted", normalized_selection=selection,
                       selection_sha256=ENGINE.selection_digest(selection),
                       required_inputs=ENGINE.required_input_status(ENGINE.required_input_groups(audit), selection))
        except ENGINE.ReportError as error:
            row.update(outcome="rejected", error=str(error))
        cases.append(row)
    selections = {case["case"]: case["normalized_selection"] for case in cases if case["outcome"] == "accepted"}
    bindings = {}
    for name in ("names-a", "names-b"):
        selection = selections[f"schema-v3-{name}"]
        raw = json.loads((inputs / "ao-resource-instrumentation.json").read_text())
        raw["selection_sha256"] = ENGINE.selection_digest(selection)
        instrumentation = ENGINE.normalize_instrumentation(raw, audit, selection)
        bindings[name] = {"normalized_instrumentation": instrumentation,
                          "instrumentation_sha256": ENGINE.instrumentation_digest(instrumentation)}
    raw_verify = previous["normalized_verification_names_a"]
    raw_verify["instrumentation_sha256"] = bindings["names-a"]["instrumentation_sha256"]
    verification = ENGINE.normalize_verify(raw_verify, audit, selections["schema-v3-names-a"],
                                          bindings["names-a"]["normalized_instrumentation"])
    checks = []
    for case in previous["binding_checks"]:
        name = case["case"]
        row = {"case": name}
        try:
            selection = selections["schema-v3-names-b" if name.startswith("stale-") else "schema-v3-names-a"]
            instrumentation = bindings["names-b" if name.startswith("stale-verification") else "names-a"]["normalized_instrumentation"]
            if "verification" in name:
                normalized = ENGINE.normalize_verify(verification, audit, selection, instrumentation)
            else:
                normalized = ENGINE.normalize_instrumentation(instrumentation, audit, selection)
            row.update(outcome="accepted", normalized_output=normalized)
        except ENGINE.ReportError as error:
            row.update(outcome="rejected", error=str(error))
        checks.append(row)
    snapshot = {
        "kind": previous["kind"], "schema_version": 1,
        "producer": {"source": "skills/references/scripts/observe_report.py",
                     "source_sha256": "sha256:" + hashlib.sha256(Path(ENGINE.__file__).read_bytes()).hexdigest(),
                     "generator_sha256": hashlib.sha256(GENERATOR.read_bytes()).hexdigest(),
                     "functions_executed": ["normalize_audit_report", "audit_digest", "normalize_selection", "selection_digest",
                                            "normalize_instrumentation", "instrumentation_digest", "normalize_verify",
                                            "required_input_groups", "required_input_status"],
                     "execution": "Executed the current canonical Python normalizers and required-input checks; no browser, application, SDK, Terraform or cloud execution."},
        "proof_limits": previous["proof_limits"], "normalized_audit": audit,
        "audit_sha256": ENGINE.audit_digest(audit), "selection_cases": cases,
        "instrumentation_bindings": bindings, "normalized_verification_names_a": verification,
        "binding_checks": checks,
    }
    output.write_text(json.dumps(snapshot, indent=2) + "\n")
    print(f"Wrote {output.relative_to(ROOT)} ({len(cases)} selection cases)")


if __name__ == "__main__":
    main()
