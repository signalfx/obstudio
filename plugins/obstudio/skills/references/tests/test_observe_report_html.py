from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from observe_report_fixtures import (
    MODULE,
    SCRIPT,
    make_external_follow_up,
    make_manual_decision,
    sample_report,
    sample_splunk_agent_observability_report,
)


class ObserveReportTest(unittest.TestCase):
    def test_renders_splunk_agent_observability_as_nested_findings_subsection(self) -> None:
        report = MODULE.normalize_audit_report(
            sample_splunk_agent_observability_report()
        )

        html = MODULE.render_html(report, MODULE.empty_selection(report))

        self.assertEqual(html.count('id="findings-heading"'), 1)
        self.assertIn(
            '<section class="finding-subsection" aria-labelledby="${esc(id)}"><h3 id="${esc(id)}">',
            html,
        )
        self.assertIn(
            '"Splunk Agent Observability findings", agentObservability',
            html,
        )
        self.assertNotIn('"opentelemetry-findings-heading", "OpenTelemetry findings"', html)
        self.assertIn('openTelemetry.map(row => row.html).join("")', html)
        self.assertNotIn("<h2>Splunk Agent Observability", html)
        self.assertNotIn('aria-labelledby="splunk-agent-observability-heading"', html)
        self.assertIn('"id":"AO-001"', html)
        self.assertIn('"id":"AO-002"', html)
        self.assertIn('id="plan-${esc(f.id)}"', html)
        self.assertIn("Agent Observability change", html)
        self.assertIn('"type":"configuration"', html)

    def test_grouped_cards_keep_global_priority_in_executed_renderer(self) -> None:
        script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const cards = { innerHTML: '' };
const context = {
  DISPLAY_FINDINGS: payload.findings,
  renderFindingCard: finding => `<article data-finding-id="${finding.id}"></article>`,
  document: { getElementById: id => id === 'cards' ? cards : null },
  syncFindingSelectionState: () => {},
  esc: value => String(value),
};
vm.runInNewContext(payload.source + '\nrenderCards();', context);
process.stdout.write(cards.innerHTML);
"""
        for recommended_agent_stream in (False, True):
            with self.subTest(recommended_agent_stream=recommended_agent_stream):
                data = sample_splunk_agent_observability_report()
                if recommended_agent_stream:
                    data["findings"][-1]["priority"] = "recommended"  # type: ignore[index]
                report = MODULE.normalize_audit_report(data)
                html = MODULE.render_html(report, MODULE.empty_selection(report))
                start = html.index("function renderCards() {")
                end = html.index("function orderedSelection()", start)
                payload = {
                    "source": html[start:end],
                    "findings": [
                        next(f for f in report["findings"] if f["id"] == finding_id)
                        for finding_id in MODULE.display_finding_ids(report)
                    ],
                }
                result = subprocess.run(
                    ["node", "-e", script],
                    input=json.dumps(payload),
                    text=True,
                    capture_output=True,
                    check=True,
                )
                rendered = result.stdout
                expected = ["OTEL-001", "AO-001", "AO-002", "OTEL-002"]
                if recommended_agent_stream:
                    expected = ["OTEL-001", "AO-001", "OTEL-002", "AO-002"]
                self.assertEqual(
                    re.findall(r'data-finding-id="([^"]+)"', rendered), expected
                )
                labels = re.findall(
                    r'<section class="finding-subsection" aria-labelledby="([^"]+)">'
                    r'<h3 id="\1">Splunk Agent Observability findings',
                    rendered,
                )
                self.assertEqual(len(labels), 2 if recommended_agent_stream else 1)
                self.assertEqual(len(labels), len(set(labels)))
                self.assertNotIn("OpenTelemetry findings", rendered)

    def test_grouped_card_detail_headings_are_below_subsection_heading(self) -> None:
        report = MODULE.normalize_audit_report(
            sample_splunk_agent_observability_report()
        )
        html = MODULE.render_html(report, MODULE.empty_selection(report))
        start = html.index("function renderFindingCard(f) {")
        end = html.index("function renderCards()", start)
        payload = {
            "source": html[start:end],
            "ordinary": next(f for f in report["findings"] if f["id"] == "OTEL-001"),
            "agentObservability": next(
                f for f in report["findings"] if f["id"] == "AO-001"
            ),
        }
        script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const context = {
  lifecycleStatus: () => 'proposed',
  modeGuidance: { default: { guidance: '', selection: 'Select' } },
  esc: value => String(value ?? ''),
  sourceHtml: value => String(value),
  telemetryShapeFor: () => 'configuration',
  findingPrimaryActionLabel: () => 'Change',
  decisionSelectionControl: () => '',
  findingSelectionPresentation: () => ({
    explicitlySelected: false, autoIncluded: false, ariaLabel: 'Select', label: 'Select'
  }),
  selectionEligibility: {
    'OTEL-001': { selectable: true }, 'AO-001': { selectable: true }
  },
  findingNextStep: () => 'Select this finding',
};
vm.runInNewContext(payload.source + '\nthis.card = renderFindingCard;', context);
process.stdout.write(JSON.stringify({
  ordinary: context.card(payload.ordinary),
  agentObservability: context.card(payload.agentObservability)
}));
"""
        result = subprocess.run(
            ["node", "-e", script],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=True,
        )
        cards = json.loads(result.stdout)
        self.assertIn("<section><h3>Gap</h3>", cards["ordinary"])
        self.assertIn("<section><h4>Gap</h4>", cards["agentObservability"])
        self.assertNotIn("<h3>", cards["agentObservability"])

    def test_splunk_agent_observability_selection_auto_includes_prerequisites(self) -> None:
        report = MODULE.normalize_audit_report(
            sample_splunk_agent_observability_report()
        )

        self.assertEqual(
            MODULE.dependency_closure(report, ["AO-002"]),
            ["OTEL-001", "AO-001", "AO-002"],
        )

    def test_schema_v1_audit_digest_remains_backward_compatible(self) -> None:
        schema_v1 = sample_report()
        schema_v1["schema_version"] = 1

        report = MODULE.normalize_audit_report(schema_v1)

        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(
            MODULE.audit_digest(report),
            "sha256:40119f93a31537edfa0ac816b0efeaa8ec18f0aee4de839e37ef6de74a9d5440",
        )
        html = MODULE.render_html(report, MODULE.empty_selection(report))
        self.assertNotIn("OTel concerns", html)
        self.assertIn("function telemetryShapeFor(finding)", html)

    def test_schema_v2_rejects_orphan_non_executable_findings(self) -> None:
        for mode in ("manual decision", "external follow-up"):
            with self.subTest(mode=mode):
                data = sample_report()
                finding = data["findings"][1]  # type: ignore[index]
                if mode == "manual decision":
                    make_manual_decision(finding)
                else:
                    make_external_follow_up(finding)
                finding["dependencies"] = []

                with self.assertRaisesRegex(
                    MODULE.ReportError,
                    r"orphan IDs: \['OTEL-002'\]",
                ):
                    MODULE.normalize_audit_report(data)

    def test_schema_v2_accepts_transitively_required_non_executable_findings(self) -> None:
        data = sample_report()
        executable = data["findings"][0]  # type: ignore[index]
        manual = data["findings"][1]  # type: ignore[index]
        external = copy.deepcopy(manual)

        make_manual_decision(manual)
        manual["dependencies"] = ["OTEL-003"]
        make_external_follow_up(external)
        external["id"] = "OTEL-003"
        external["area"] = "External payment receipt"
        external["dependencies"] = []
        executable["dependencies"] = ["OTEL-002"]
        data["findings"].append(external)  # type: ignore[index]
        data["signal_flow"]["component_flow_map"] += (  # type: ignore[index]
            "\npayment platform [GAP: External payment receipt]"
        )

        report = MODULE.normalize_audit_report(data)

        self.assertEqual(
            [finding["id"] for finding in report["findings"]],
            ["OTEL-001", "OTEL-002", "OTEL-003"],
        )

    def test_schema_v1_allows_orphan_non_executable_findings(self) -> None:
        for mode in ("manual decision", "external follow-up"):
            with self.subTest(mode=mode):
                schema_v1 = sample_report()
                schema_v1["schema_version"] = 1
                finding = schema_v1["findings"][1]  # type: ignore[index]
                if mode == "manual decision":
                    make_manual_decision(finding)
                else:
                    make_external_follow_up(finding)
                finding["dependencies"] = []

                report = MODULE.normalize_audit_report(schema_v1)

                self.assertEqual(report["findings"][1]["instrument_mode"], mode)
        html = MODULE.render_html(report, MODULE.empty_selection(report))
        self.assertNotIn("OTel concerns", html)

    def test_external_requirement_must_equal_required_fix(self) -> None:
        data = sample_report()
        finding = data["findings"][0]  # type: ignore[index]
        make_external_follow_up(finding)
        finding["required_fix"] = (
            f"{finding['external_requirement']} Also add a service-owned checkout span."
        )

        with self.assertRaisesRegex(MODULE.ReportError, "exact external_requirement"):
            MODULE.normalize_audit_report(data)

    def test_audit_status_is_source_gap_state_not_runtime_proof(self) -> None:
        report = sample_report()
        report["meta"]["status"] = "Pass"  # type: ignore[index]

        with self.assertRaisesRegex(MODULE.ReportError, "Pass requires zero source-visible findings"):
            MODULE.normalize_audit_report(report)

    def test_reconciles_incident_readiness_with_status_and_findings(self) -> None:
        missing = sample_report()
        missing["meta"]["status"] = "Pass"  # type: ignore[index]
        missing["findings"] = []
        missing["signal_flow"]["component_flow_map"] = "checkout [SOURCE-COVERED]"  # type: ignore[index]
        missing["current_instrumentation"]["incident_readiness"] = [  # type: ignore[index]
            {
                "area": "Checkout readiness telemetry",
                "status": "missing",
                "evidence": "main.go:42",
                "required_signals": "checkout.readiness metric",
                "impact": "No bounded readiness signal exists.",
            }
        ]
        with self.assertRaisesRegex(
            MODULE.ReportError,
            "require identical unresolved finding areas",
        ):
            MODULE.normalize_audit_report(missing)

        owner_mapped_without_owner = copy.deepcopy(missing)
        owner_mapped_without_owner["current_instrumentation"]["incident_readiness"][0][  # type: ignore[index]
            "status"
        ] = "owner-mapped"
        with self.assertRaisesRegex(
            MODULE.ReportError,
            "owner-mapped incident readiness areas require identical unresolved",
        ):
            MODULE.normalize_audit_report(owner_mapped_without_owner)

        covered = sample_report()
        covered["meta"]["status"] = "Pass"  # type: ignore[index]
        covered["findings"] = []
        covered["signal_flow"]["component_flow_map"] = "checkout [SOURCE-COVERED]"  # type: ignore[index]
        covered["current_instrumentation"]["incident_readiness"] = [  # type: ignore[index]
            {
                "area": "Checkout readiness telemetry",
                "status": "covered",
                "evidence": "main.go:42",
                "required_signals": "checkout.readiness metric",
                "impact": "Bounded readiness is source-covered.",
            }
        ]
        normalized = MODULE.normalize_audit_report(covered)
        self.assertEqual(normalized["meta"]["status"], "Pass")

        duplicate = sample_report()
        row = {
            "area": "Checkout latency",
            "status": "partial",
            "evidence": "main.go:42",
            "required_signals": "GET /checkout span",
            "impact": "Route telemetry is incomplete.",
        }
        duplicate["current_instrumentation"]["incident_readiness"] = [row, dict(row)]  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.ReportError, "duplicate incident readiness area"):
            MODULE.normalize_audit_report(duplicate)

        done_does_not_close_missing = sample_report()
        done_does_not_close_missing["findings"][0]["status"] = "done"  # type: ignore[index]
        done_does_not_close_missing["current_instrumentation"]["incident_readiness"] = [  # type: ignore[index]
            {
                "area": "Checkout latency",
                "status": "missing",
                "evidence": "main.go:42",
                "required_signals": "GET /checkout span",
                "impact": "Route telemetry remains missing.",
            }
        ]
        with self.assertRaisesRegex(MODULE.ReportError, "unresolved finding areas"):
            MODULE.normalize_audit_report(done_does_not_close_missing)

        done_does_not_conflict_with_covered = sample_report()
        done_does_not_conflict_with_covered["findings"][0]["status"] = "done"  # type: ignore[index]
        done_does_not_conflict_with_covered["current_instrumentation"]["incident_readiness"] = [  # type: ignore[index]
            {
                "area": "Checkout latency",
                "status": "covered",
                "evidence": "main.go:42",
                "required_signals": "GET /checkout span",
                "impact": "Route telemetry is source-covered.",
            }
        ]
        normalized_done = MODULE.normalize_audit_report(done_does_not_conflict_with_covered)
        self.assertEqual(
            normalized_done["current_instrumentation"]["incident_readiness"][0]["status"],
            "covered",
        )

    def test_genai_readiness_requires_valid_unique_mapped_state(self) -> None:
        invalid = sample_report()
        invalid["meta"]["genai_ownership_detected"] = True  # type: ignore[index]
        invalid["evidence"][-1]["finding"] = "Yes"  # type: ignore[index]
        row = {
            "surface": "Checkout latency",
            "status": "banana",
            "evidence": "assistant.go:20",
            "required_signals": "GET /checkout span",
            "owner": "assistant.go:20",
            "acceptance_criteria": "GET /checkout span is emitted",
            "impact": "Operators cannot localize assistant latency.",
        }
        invalid["genai_readiness"] = [row]
        with self.assertRaisesRegex(MODULE.ReportError, "status must be one of"):
            MODULE.normalize_audit_report(invalid)

        duplicate = copy.deepcopy(invalid)
        duplicate["genai_readiness"] = [
            {**row, "status": "partial"},
            {**row, "status": "missing"},
        ]
        with self.assertRaisesRegex(MODULE.ReportError, "duplicate GenAI readiness surface"):
            MODULE.normalize_audit_report(duplicate)

        unmapped = copy.deepcopy(invalid)
        unmapped["genai_readiness"] = [
            {**row, "surface": "Assistant model call", "status": "partial"}
        ]
        with self.assertRaisesRegex(MODULE.ReportError, "identical unresolved finding areas"):
            MODULE.normalize_audit_report(unmapped)

        contradictory = copy.deepcopy(invalid)
        contradictory["genai_readiness"] = [{**row, "status": "covered"}]
        with self.assertRaisesRegex(
            MODULE.ReportError, "covered or owner-mapped GenAI readiness surfaces"
        ):
            MODULE.normalize_audit_report(contradictory)

        owner_mapped_contradiction = copy.deepcopy(invalid)
        owner_mapped_contradiction["genai_readiness"] = [
            {
                **row,
                "status": "owner-mapped",
                "owner": "Provider/platform-owned: billing API",
            }
        ]
        with self.assertRaisesRegex(
            MODULE.ReportError, "covered or owner-mapped GenAI readiness surfaces"
        ):
            MODULE.normalize_audit_report(owner_mapped_contradiction)

        app_owned_mapping = copy.deepcopy(invalid)
        app_owned_mapping["genai_readiness"] = [
            {
                **row,
                "status": "owner-mapped",
                "owner": "App-owned: assistant.go",
            }
        ]
        with self.assertRaisesRegex(
            MODULE.ReportError, "must name an exact external"
        ):
            MODULE.normalize_audit_report(app_owned_mapping)

        generic_external_mapping = copy.deepcopy(invalid)
        generic_external_mapping["genai_readiness"] = [
            {**row, "status": "owner-mapped", "owner": "external team"}
        ]
        with self.assertRaisesRegex(
            MODULE.ReportError, "must name an exact external"
        ):
            MODULE.normalize_audit_report(generic_external_mapping)

        passed = copy.deepcopy(invalid)
        passed["meta"]["status"] = "Pass"  # type: ignore[index]
        passed["findings"] = []
        passed["genai_readiness"] = [{**row, "status": "partial"}]
        with self.assertRaisesRegex(MODULE.ReportError, "every GenAI readiness surface"):
            MODULE.normalize_audit_report(passed)

        owner_mapped_pass = copy.deepcopy(invalid)
        owner_mapped_pass["meta"]["status"] = "Pass"  # type: ignore[index]
        owner_mapped_pass["findings"] = []
        owner_mapped_pass["signal_flow"]["component_flow_map"] = (  # type: ignore[index]
            "assistant [SOURCE-COVERED] -> provider [SOURCE-COVERED]"
        )
        owner_mapped_pass["genai_readiness"] = [
            {
                **row,
                "surface": "Provider billing",
                "status": "owner-mapped",
                "evidence": "Provider billing API is outside the repository.",
                "required_signals": "provider token cost metric",
                "owner": "Provider/platform-owned: billing API",
                "acceptance_criteria": "Provider owner exports a bounded token cost metric.",
            }
        ]
        normalized_owner_mapped = MODULE.normalize_audit_report(owner_mapped_pass)
        self.assertEqual(normalized_owner_mapped["meta"]["status"], "Pass")
        self.assertEqual(
            normalized_owner_mapped["genai_readiness"][0]["status"],
            "owner-mapped",
        )

    def test_audit_rejects_duplicate_finding_scenario_references(self) -> None:
        data = sample_report()
        data["findings"][0]["verification_scenarios"] = [  # type: ignore[index]
            "http.checkout.success",
            "http.checkout.success",
        ]

        with self.assertRaisesRegex(MODULE.ReportError, "must not contain duplicates"):
            MODULE.normalize_audit_report(data)

    def test_blocked_audit_requires_structured_scan_blockers(self) -> None:
        blocked = sample_report()
        blocked["meta"]["status"] = "Blocked"  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.ReportError, "structured scan_blocker"):
            MODULE.normalize_audit_report(blocked)

        blocked["scan_blockers"] = [
            {
                "id": "BLOCK-001",
                "check": "source-scan",
                "blocked_scope": ["private/generated"],
                "prerequisite": "The generated source tree is unavailable.",
                "evidence": [".observe/evidence/source-scan.txt"],
                "required_action": "Provide the generated source tree.",
            }
        ]
        normalized = MODULE.normalize_audit_report(blocked)
        self.assertEqual(normalized["scan_blockers"][0]["id"], "BLOCK-001")

        partial = sample_report()
        partial["scan_blockers"] = blocked["scan_blockers"]
        with self.assertRaisesRegex(MODULE.ReportError, "valid only when meta.status is Blocked"):
            MODULE.normalize_audit_report(partial)

    def test_human_reports_render_blockers_but_not_readiness_ledgers(self) -> None:
        data = sample_report()
        data["meta"]["status"] = "Blocked"  # type: ignore[index]
        data["scan_blockers"] = [
            {
                "id": "BLOCK-001",
                "check": "source-scan",
                "blocked_scope": ["private/generated"],
                "prerequisite": "Generated sources are unavailable.",
                "evidence": [".observe/evidence/source-scan.txt"],
                "required_action": "Provide the generated source tree.",
            }
        ]
        data["current_instrumentation"]["incident_readiness"] = [  # type: ignore[index]
            {
                "area": "Checkout latency",
                "status": "partial",
                "evidence": "main.go:42",
                "required_signals": "GET /checkout span",
                "impact": "Operators cannot localize route latency.",
            }
        ]
        data["meta"]["genai_ownership_detected"] = True  # type: ignore[index]
        data["evidence"][-1]["finding"] = "Yes"  # type: ignore[index]
        data["genai_readiness"] = [
            {
                "surface": "Checkout assistant",
                "status": "covered",
                "evidence": "assistant.go:20",
                "required_signals": "assistant.request span",
                "owner": "assistant.go:20",
                "acceptance_criteria": "assistant.request span is emitted with a bounded outcome",
                "impact": "Operators cannot localize assistant latency.",
            }
        ]

        report = MODULE.normalize_audit_report(data)
        html = MODULE.render_html(report, MODULE.empty_selection(report))
        visible_html = re.sub(r"<script>.*?</script>", "", html, flags=re.DOTALL)

        for value in (
            "Scan incomplete",
            "BLOCK-001",
            "source-scan",
            "private/generated",
            "Generated sources are unavailable.",
            ".observe/evidence/source-scan.txt",
            "Provide the generated source tree.",
        ):
            self.assertIn(value, visible_html)
        for value in (
            "Incident telemetry readiness",
            "GenAI telemetry readiness",
            "Checkout assistant",
            "assistant.request span",
        ):
            self.assertNotIn(value, visible_html)
        self.assertEqual(report["scan_blockers"][0]["id"], "BLOCK-001")
        self.assertEqual(
            report["current_instrumentation"]["incident_readiness"][0]["area"],
            "Checkout latency",
        )
        self.assertEqual(report["genai_readiness"][0]["surface"], "Checkout assistant")

    def test_html_omits_anti_pattern_ledger_but_json_preserves_provenance(
        self,
    ) -> None:
        data = sample_report()
        mapped_anti_pattern = (
            "High-cardinality metric attributes: raw org_id and client values are "
            "attached to request, token, cost, and duration datapoints."
        )
        unique_context = (
            "A source-inactive no-op tracer compatibility shim remains for "
            "local compatibility profiles."
        )
        data["anti_patterns"] = [mapped_anti_pattern, unique_context]

        report = MODULE.normalize_audit_report(data)
        html = MODULE.render_html(report, MODULE.empty_selection(report))
        visible_html = re.sub(r"<script>.*?</script>", "", html, flags=re.DOTALL)

        self.assertEqual(report["anti_patterns"], [mapped_anti_pattern, unique_context])
        self.assertNotIn("<h2>Anti-Patterns</h2>", visible_html)
        self.assertNotIn(mapped_anti_pattern, visible_html)
        self.assertNotIn(unique_context, visible_html)

    def test_audit_rejects_otel_verify_as_reviewer_next_step(self) -> None:
        recommendation = sample_report()
        recommendation["recommendation"] = [
            "Run $otel-verify with the selected findings."
        ]
        with self.assertRaisesRegex(
            MODULE.ReportError,
            r"must not present \$otel-verify or generic verification",
        ):
            MODULE.normalize_audit_report(recommendation)

        generic = sample_report()
        generic["recommendation"] = ["Run verification after audit."]
        with self.assertRaisesRegex(
            MODULE.ReportError,
            r"must not present \$otel-verify or generic verification",
        ):
            MODULE.normalize_audit_report(generic)

        finding_follow_up = sample_report()
        finding_follow_up["findings"][0]["follow_up_actions"] = [  # type: ignore[index]
            "Run verification, then open the trace waterfall."
        ]
        with self.assertRaisesRegex(
            MODULE.ReportError,
            r"must not present \$otel-verify or generic verification",
        ):
            MODULE.normalize_audit_report(finding_follow_up)

        allowed = sample_report()
        allowed["recommendation"] = [
            "Select executable findings, save the audit state, and run $otel-instrument."
        ]
        allowed["findings"][0]["follow_up_actions"] = [  # type: ignore[index]
            "After instrumentation proof exists, filter the span in ObStudio before merge."
        ]
        report = MODULE.normalize_audit_report(allowed)
        self.assertIn("$otel-instrument", " ".join(report["recommendation"]))

    def test_builds_deterministic_decision_overview(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())

        overview = MODULE.decision_overview(report)

        self.assertEqual(
            overview["priority_counts"],
            {"required": 1, "recommended": 1, "deferred": 0},
        )
        self.assertEqual([row["id"] for row in overview["buckets"]["fix_now"]], ["OTEL-001"])
        self.assertEqual([row["id"] for row in overview["buckets"]["consider_next"]], ["OTEL-002"])
        self.assertEqual([row["id"] for row in overview["quick_wins"]], ["OTEL-001"])
        self.assertEqual(
            MODULE.finding_product_view(report["findings"][0]),
            "Each checkout request has one route-named trace that can be filtered in the waterfall.",
        )

    def test_display_order_uses_priority_without_mutating_canonical_order(self) -> None:
        data = sample_report()
        data["findings"].reverse()  # type: ignore[union-attr]
        report = MODULE.normalize_audit_report(data)

        self.assertEqual(
            [finding["id"] for finding in report["findings"]],
            ["OTEL-002", "OTEL-001"],
        )
        self.assertEqual(
            MODULE.display_finding_ids(report),
            ["OTEL-001", "OTEL-002"],
        )
        summary = MODULE.decision_summary_bullets(report)
        self.assertIn(
            "Start with OTEL-001 — Checkout latency is not measured. "
            "Expected result: Each checkout request has one route-named trace "
            "that can be filtered in the waterfall.",
            summary,
        )
        self.assertFalse(
            any("This audit proves only source and configuration state" in item for item in summary)
        )
        self.assertEqual(MODULE.display_finding_ids(report), ["OTEL-001", "OTEL-002"])

    def test_decision_summary_does_not_direct_resolved_work(self) -> None:
        data = sample_report()
        for finding in data["findings"]:  # type: ignore[union-attr]
            finding["status"] = "done"
            finding["resolution"] = "Implemented and verified."
            finding["resolved_commit"] = "abc1234"
        report = MODULE.normalize_audit_report(data)

        summary = MODULE.decision_summary_bullets(report)

        self.assertFalse(any(item.startswith("Start with ") for item in summary))
        self.assertFalse(any(item.startswith("Next: ") for item in summary))

    def test_decision_view_explains_one_priority_ordered_list(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())

        html = MODULE.render_decision_overview(
            report,
            {"approved_ids": ["OTEL-001", "OTEL-002"]},
        )

        self.assertNotIn('class="decision-stats"', html)
        self.assertNotIn("Small quick wins", html)
        self.assertIn("Current baseline", html)
        self.assertIn(
            "Source inventory: 1 routes · 0 span entries · 0 metric entries · 0 log integrations.",
            html,
        )
        self.assertIn("ordered by priority, highest first", html)
        self.assertNotIn("OTEL-001", html)
        self.assertNotIn("priority-action", html)
        self.assertNotIn("action-tag", html)

    def test_rejects_unknown_or_unsupported_flow_markers(self) -> None:
        unknown = sample_report()
        unknown["signal_flow"]["component_flow_map"] = "handler [GAP: Missing area]"  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.ReportError, "undefined finding areas"):
            MODULE.normalize_audit_report(unknown)

        unsupported = sample_report()
        unsupported["signal_flow"]["component_flow_map"] = "handler [RUNTIME-PROVEN]"  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.ReportError, "unsupported markers"):
            MODULE.normalize_audit_report(unsupported)

        unmapped = sample_report()
        unmapped["signal_flow"]["component_flow_map"] = (  # type: ignore[index]
            "Request path\nmain.go [SOURCE-COVERED] -> checkout [GAP: Checkout latency]"
        )
        with self.assertRaisesRegex(MODULE.ReportError, "not associated with a component-flow"):
            MODULE.normalize_audit_report(unmapped)

    def test_rejects_unknown_dependency(self) -> None:
        report = sample_report()
        report["findings"][1]["dependencies"] = ["OTEL-404"]  # type: ignore[index]

        with self.assertRaisesRegex(MODULE.ReportError, "undefined dependencies"):
            MODULE.normalize_audit_report(report)

    def test_rejects_unknown_verification_scenario(self) -> None:
        report = sample_report()
        report["findings"][0]["verification_scenarios"] = ["missing"]  # type: ignore[index]

        with self.assertRaisesRegex(MODULE.ReportError, "undefined scenarios"):
            MODULE.normalize_audit_report(report)

    def test_rejects_finding_without_evidence(self) -> None:
        report = sample_report()
        report["findings"][0]["evidence"] = []  # type: ignore[index]

        with self.assertRaisesRegex(MODULE.ReportError, "evidence must contain"):
            MODULE.normalize_audit_report(report)

    def test_rejects_missing_required_audit_evidence_check(self) -> None:
        report = sample_report()
        report["evidence"] = report["evidence"][1:]  # type: ignore[index]

        with self.assertRaisesRegex(MODULE.ReportError, "Manifest"):
            MODULE.normalize_audit_report(report)

    def test_cli_validate_checks_canonical_json_without_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / "otel-audit.json"
            audit.write_text(json.dumps(sample_report()), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "validate",
                    str(audit),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("PASS:", completed.stdout)
            self.assertEqual(json.loads(audit.read_text(encoding="utf-8"))["findings"][0]["id"], "OTEL-001")

    def test_cli_render_html_is_self_contained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / "otel-audit.json"
            html_path = root / "otel.html"
            audit.write_text(json.dumps(sample_report()), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "render-html",
                    str(audit),
                    "-o",
                    str(html_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            html = html_path.read_text(encoding="utf-8")
            self.assertIn("OTEL-001", html)
            self.assertNotIn("Save selection", html)
            self.assertIn("Copy this prompt and paste into AI chat", html)
            self.assertNotIn("navigator.clipboard", html)
            self.assertIn("Technical appendix", html)
            self.assertIn("Source-visible instrumentation evidence", html)
            self.assertIn("Verification plan", html)
            self.assertIn("ordered by priority, highest first", html)
            self.assertIn('"display_finding_ids":["OTEL-001","OTEL-002"]', html)
            self.assertIn("const DISPLAY_FINDINGS =", html)
            self.assertIn("DISPLAY_FINDINGS.map(f =>", html)
            self.assertNotRegex(
                html,
                r"\.card\.done\s*\{[^}]*\bopacity\s*:",
                "Completed cards must retain normal text opacity and contrast.",
            )
            self.assertIn(".card.done { border-color: #9bd5b7; }", html)
            self.assertIn(".card.done .spine { background: var(--ok); }", html)
            self.assertIn("function telemetryShapeFor(finding)", html)
            self.assertIn('const order = ["span", "metric", "log", "resource", "configuration"]', html)
            self.assertIn('class="finding-meta"', html)
            self.assertIn('Telemetry: <strong>${esc(telemetryShape)}</strong>', html)
            self.assertIn('Plan prerequisite${f.dependencies.length === 1 ? "" : "s"}', html)
            self.assertIn("Required telemetry:", html)
            self.assertIn('"selection":"Select"', html)
            self.assertNotIn("data-lifecycle-tag", html)
            self.assertNotIn('tag?.remove()', html)
            self.assertNotIn("optional work", html.lower())
            self.assertNotIn("small effort", html.lower())
            self.assertNotIn("medium effort", html.lower())
            self.assertNotIn("large effort", html.lower())
            self.assertNotIn('class="tag rank"', html)
            self.assertNotIn('<span class="tag">${esc(mode.label)}</span>', html)
            self.assertIn("Current baseline", html)
            self.assertNotIn("What you get after implementation and verification", html)
            self.assertIn("Instrumentation change", html)
            self.assertIn("Decision needed", html)
            self.assertIn("External requirement", html)
            self.assertIn("Next step", html)
            self.assertIn("function findingNextStep(finding)", html)
            self.assertIn('eligibility.blockers.join(", ")', html)
            self.assertIn(
                "This finding is selected. Copy the generated prompt and paste into AI chat.",
                html,
            )
            self.assertIn("included because selected work depends on it", html)
            self.assertIn('data-finding-next-step="${esc(f.id)}"', html)
            self.assertIn("nextStep.textContent = findingNextStep(finding)", html)
            self.assertIn("Technical details", html)
            self.assertIn('class="finding-technical-details"', html)
            self.assertIn('class="detail-counts"', html)
            self.assertIn('countLabel((f.acceptance_criteria || []).length, "acceptance check")', html)
            self.assertIn('countLabel((f.constraints || []).length, "implementation guardrail")', html)
            self.assertIn('countLabel((f.evidence || []).length, "source reference")', html)
            self.assertIn("This answer unlocks no instrumentation work.", html)
            self.assertNotIn("What you do next", html)
            self.assertNotIn('href="otel.md"', html)
            self.assertNotIn("Technical audit (Markdown)", html)
            self.assertIn('href="otel-audit.json">Canonical audit data (JSON)</a>', html)
            self.assertLess(
                html.index("<section><${detailHeading}>${esc(primaryActionLabel)}</${detailHeading}>"),
                html.index('<details class="finding-technical-details">'),
            )
            for technical_heading in (
                "Expected telemetry",
                "Acceptance criteria",
                "Implementation guardrails",
                "Evidence",
            ):
                self.assertGreater(
                    html.index(
                        f"<section><${{detailHeading}}>{technical_heading}"
                        "</${detailHeading}>"
                    ),
                    html.index('<details class="finding-technical-details">'),
                )
            self.assertNotIn("Small quick wins", html)
            self.assertNotIn("Service map", html)
            self.assertNotIn("Coverage gaps by component", html)
            self.assertNotIn("Connections by path", html)
            self.assertNotIn("Raw flow map", html)
            self.assertNotIn("linked coverage area", html)
            self.assertNotIn('id="filters"', html)
            self.assertLess(html.index('id="findings-heading"'), html.index("Technical appendix"))
            self.assertNotIn("<h2>Signal Flow</h2><pre>", html)
            self.assertNotIn("Review every finding decision", html)
            self.assertNotIn("componentJump", html)
            self.assertIn('event.target.closest("[data-finding-jump][href]")', html)
            self.assertIn('disclosure?.focus({preventScroll: true})', html)
            self.assertIn("revealCurrentHash()", html)
            self.assertIn("syncDependencyClosure", html)
            self.assertNotIn("renderDecisionProgress", html)
            self.assertNotIn("requiredInPlanIds", html)
            self.assertNotIn("selectable required items", html)
            self.assertIn("selected.clear()", html)
            self.assertIn(
                "input.checked = presentation.explicitlySelected",
                html,
            )
            self.assertIn(
                "input.indeterminate = presentation.autoIncluded",
                html,
            )
            self.assertIn(
                'data-selection-state="${selectionPresentation.autoIncluded ? "dependency"',
                html,
            )
            self.assertIn(
                "<span data-selection-label>${esc(selectionPresentation.label)}</span>",
                html,
            )
            self.assertNotIn("input.checked = selected.has(finding.id)", html)
            self.assertIn("const requested = new Set", html)
            self.assertIn("function orderedRequested()", html)
            self.assertIn("function orderedSelection()", html)
            self.assertNotIn(
                "requested_ids: orderedRequested(), approved_ids: orderedSelection()",
                html,
            )
            self.assertIn("requested.delete(id)", html)
            self.assertIn(
                '<h2 id="findings-heading" tabindex="-1">Findings '
                '<span class="findings-total">· 2</span></h2>',
                html,
            )
            for removed_filter in (
                'class="filters"',
                'class="filter-facet"',
                'class="chip"',
                "filterFacet(",
                "renderFilters(",
                "applyFilters(",
                "const filters =",
                'event.target.closest(".chip")',
                'data-effort="',
                'data-status="',
            ):
                self.assertNotIn(removed_filter, html)
            self.assertIn('id="tray" hidden inert aria-hidden="true"', html)
            self.assertIn("tray.hidden = !hasSelection", html)
            self.assertIn('tray.toggleAttribute("inert", !hasSelection)', html)
            self.assertNotIn('id="planPanel"', html)
            self.assertNotIn('aria-controls="planPanel"', html)
            self.assertIn(
                'id="selectionStatus" class="sr-only" aria-live="polite" aria-atomic="true"',
                html,
            )
            self.assertNotIn('id="planSummary"', html)
            self.assertNotIn('id="saveSelectionHint"', html)
            self.assertNotIn('id="saveSelection"', html)
            self.assertIn(
                'id="instrumentCommand" type="text" readonly '
                'aria-labelledby="instrumentCommandLabel"',
                html,
            )
            self.assertIn("if (node) node.value = terminalInstrumentCommand()", html)
            self.assertIn("function serviceRootFromLocation()", html)
            self.assertIn("function terminalInstrumentCommand()", html)
            self.assertIn(
                'location.protocol === "http:" || location.protocol === "https:"',
                html,
            )
            self.assertIn(
                "Copy this repository-relative source path",
                html,
            )
            self.assertIn("function neutralizeHttpSourceLinks()", html)
            self.assertIn(
                'document.querySelectorAll("a.source-link")',
                html,
            )
            self.assertIn("neutralizeHttpSourceLinks();", html)
            self.assertIn(
                "parts.map((part, index) => index === 0 ? part : commandPart(part)).join",
                html,
            )
            self.assertIn('parts.push("--decision", `${answer.finding_id}=${answer.option_id}`);', html)
            self.assertIn(
                "Select at least one executable finding to generate an instrumentation command.",
                html,
            )
            self.assertNotIn("function auditReviewDocument()", html)
            self.assertNotIn("document.review_selection = selectionDocument()", html)
            self.assertNotIn("window.showSaveFilePicker", html)
            self.assertNotIn('link.download = "otel-audit.selected.json"', html)
            self.assertNotIn('summaryParts.join(" · ")', html)
            self.assertIn('aria-controls="finding-body-${esc(f.id)}"', html)
            self.assertIn('name="plan-${esc(f.id)}"', html)
            self.assertIn(
                'aria-label="${esc(selectionPresentation.ariaLabel)}"',
                html,
            )
            self.assertIn(
                '"Included as dependency"',
                html,
            )
            self.assertIn('<span class="spine" aria-hidden="true"></span>', html)
            self.assertIn('<span class="caret" aria-hidden="true">›</span>', html)
            self.assertIn('</button>\n        ${selectionControl}', html)
            self.assertNotIn('data-remove-plan="', html)
            self.assertNotIn("setPlanOpen", html)
            self.assertNotIn('event.key === "Escape"', html)
            self.assertEqual(html.count('id="saveSelection"'), 0)
            self.assertEqual(html.count('id="reviewPlan"'), 0)
            self.assertEqual(html.count('id="downloadJson"'), 0)
            self.assertEqual(html.count('id="copyCommand"'), 0)
            self.assertNotIn(
                'document.getElementById("saveSelection").addEventListener("click"',
                html,
            )
            self.assertNotIn("Selected audit copy saved.", html)
            self.assertNotIn("Selected audit download fallback started.", html)
            self.assertNotIn("severityColor", html)
            self.assertNotIn("data-severity", html)
            self.assertNotIn("--required:", html)
            self.assertNotIn("--recommended:", html)
            self.assertNotIn("--deferred:", html)
            self.assertNotIn("document.execCommand", html)
            self.assertNotIn("https://fonts.googleapis.com", html)
            self.assertNotIn("<script src=", html.lower())
            self.assertNotIn("<link ", html.lower())

    def test_cli_render_html_escapes_inline_json_script_end_tags(self) -> None:
        report_data = sample_report()
        hostile_text = '</SCRIPT><script>alert("x")</script>'
        report_data["summary"] = [hostile_text]
        report_data["findings"][0]["impact"] = hostile_text
        report = MODULE.normalize_audit_report(report_data)

        html = MODULE.render_html(report, MODULE.empty_selection(report))

        self.assertEqual(html.lower().count("<script>"), 1)
        self.assertEqual(html.lower().count("</script>"), 1)
        self.assertNotIn("</script><script>", html.lower())
        self.assertIn("\\u003c/SCRIPT>", html)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JavaScript syntax validation")
    def test_cli_render_html_javascript_parses(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())
        html = MODULE.render_html(report, MODULE.empty_selection(report))
        scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, re.DOTALL)
        self.assertGreaterEqual(len(scripts), 1)

        with tempfile.TemporaryDirectory() as directory:
            script_path = Path(directory) / "otel-report.js"
            script_path.write_text(scripts[-1], encoding="utf-8")
            completed = subprocess.run(
                ["node", "--check", str(script_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JavaScript behavior validation")
    def test_html_syncs_auto_included_dependency_control_state(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())
        html = MODULE.render_html(report, MODULE.empty_selection(report))
        function_start = html.index("function findingSelectionPresentation(finding)")
        function_end = html.index(
            "\nfunction findingPrimaryActionLabel(finding)",
            function_start,
        )
        functions = html[function_start:function_end]
        script = f"""
const requested = new Set();
const selected = new Set(["OTEL-001"]);
const modeGuidance = {{default: {{selection: "Select"}}}};
{functions}
const classes = new Set();
const label = {{textContent: ""}};
const attributes = {{}};
const control = {{
  classList: {{
    toggle(name, enabled) {{
      if (enabled) classes.add(name);
      else classes.delete(name);
    }},
  }},
  querySelector(selector) {{
    if (selector !== "[data-selection-label]") throw new Error("unexpected selector " + selector);
    return label;
  }},
}};
const input = {{
  checked: false,
  indeterminate: false,
  dataset: {{}},
  setAttribute(name, value) {{ attributes[name] = value; }},
  closest(selector) {{
    if (selector !== ".plan-select") throw new Error("unexpected closest selector " + selector);
    return control;
  }},
}};
const finding = {{id: "OTEL-001", instrument_mode: "default"}};
function assert(condition, message) {{
  if (!condition) throw new Error(message);
}}

// Reopened saved scope: dependency closure includes OTEL-001, but the reviewer
// did not select it explicitly.
syncFindingSelectionControl(input, finding);
assert(!input.checked, "dependency must not look explicitly selected");
assert(input.indeterminate, "dependency must use the mixed checkbox state");
assert(input.dataset.selectionState === "dependency", "dependency state must be exposed");
assert(label.textContent === "Included as dependency", "dependency label must be visible");
assert(classes.has("included") && !classes.has("on"), "dependency styling must be distinct");
assert(attributes["aria-label"].includes("included as a required dependency"), "dependency must be named accessibly");

// Selecting the dependency explicitly promotes it to ordinary selected state.
requested.add("OTEL-001");
syncFindingSelectionControl(input, finding);
assert(input.checked && !input.indeterminate, "explicit selection must be checked");
assert(input.dataset.selectionState === "selected", "explicit state must be exposed");
assert(label.textContent === "Select", "explicit control keeps the normal action label");
assert(classes.has("on") && !classes.has("included"), "explicit styling must replace dependency styling");

// Removing the explicit request while another selected item still depends on it
// returns the control to the visible dependency state.
requested.delete("OTEL-001");
syncFindingSelectionControl(input, finding);
assert(!input.checked && input.indeterminate, "dependency state must be restored");
assert(label.textContent === "Included as dependency", "dependency label must be restored");

// Removing the dependency from closure returns the finding to available state.
selected.delete("OTEL-001");
syncFindingSelectionControl(input, finding);
assert(!input.checked && !input.indeterminate, "available state must be unchecked");
assert(input.dataset.selectionState === "available", "available state must be exposed");
assert(label.textContent === "Select", "available action label must be restored");
assert(!classes.has("on") && !classes.has("included"), "available state must clear selection styling");
"""

        completed = subprocess.run(
            ["node", "-e", script],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JavaScript behavior validation")
    def test_html_terminal_command_normalizes_platform_file_urls(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())
        html = MODULE.render_html(report, MODULE.empty_selection(report))
        function_body = html.split("function serviceRootFromLocation()", 1)[1].split(
            "function terminalInstrumentCommand()", 1
        )[0]
        script = (
            "function serviceRootFromLocation()"
            + function_body
            + """
const cases = [
  [null, {protocol: "file:", hostname: "", pathname: "/Users/a/repo/.observe/otel.html"}, "/Users/a/repo"],
  [null, {protocol: "file:", hostname: "", pathname: "/C:/repo/.observe/otel.html"}, "C:/repo"],
  [null, {protocol: "file:", hostname: "server", pathname: "/share/repo/.observe/otel.html"}, "//server/share/repo"],
  ["/Users/a/repo", {protocol: "http:", hostname: "127.0.0.1", pathname: "/otel.html"}, "/Users/a/repo"],
  [null, {protocol: "https:", hostname: "example.test", pathname: "/otel.html"}, ""],
];
for (const [serviceRoot, input, expected] of cases) {
  globalThis.DATA = {service_root: serviceRoot};
  globalThis.location = input;
  const actual = serviceRootFromLocation();
  if (actual !== expected) {
    throw new Error(`${JSON.stringify(input)}: expected ${expected}, got ${actual}`);
  }
}
"""
        )

        completed = subprocess.run(
            ["node", "-e", script],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_html_embeds_validated_service_root_for_loopback_report(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())

        with tempfile.TemporaryDirectory() as directory:
            source_root = Path(directory)
            html = MODULE.render_html(
                report,
                MODULE.empty_selection(report),
                source_root=source_root,
                output_dir=source_root / ".observe",
            )

        self.assertIn(
            f'"service_root":{json.dumps(MODULE.quote(str(source_root.resolve()), safe=""))}',
            html,
        )

    def test_html_progressively_discloses_verbose_finding_details(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())
        html = MODULE.render_html(report, MODULE.empty_selection(report))
        render_finding_card = html.split("function renderFindingCard(f)", 1)[1].split(
            "function renderCards()", 1
        )[0]
        card_start = render_finding_card.index("return `<article")
        card_end = render_finding_card.index("</article>`;", card_start)
        card = render_finding_card[card_start:card_end]
        details_start = card.index('<details class="finding-technical-details"')
        details_open_end = card.index(">", details_start) + 1
        details_end = card.index("</details>", details_open_end) + len("</details>")
        opening_tag = card[details_start:details_open_end]
        technical_details = card[details_start:details_end]
        concise_details = card[:details_start]

        self.assertNotRegex(opening_tag, r"\bopen\b")
        self.assertIn("<summary><span>Technical details</span>", technical_details)
        self.assertIn('class="detail-counts"', technical_details)
        self.assertIn('class="finding-meta"', concise_details)
        self.assertIn('Telemetry: <strong>${esc(telemetryShape)}</strong>', concise_details)
        self.assertIn("dependencyCue", concise_details)
        for label in ("Gap", "Why it matters", "Next step"):
            self.assertIn(f"<${{detailHeading}}>{label}</${{detailHeading}}>", concise_details)
        self.assertIn(
            "<${detailHeading}>${esc(primaryActionLabel)}</${detailHeading}>",
            concise_details,
        )
        for label in (
            "Expected telemetry",
            "Acceptance criteria",
            "Implementation guardrails",
            "Evidence",
        ):
            heading = f"<${{detailHeading}}>{label}</${{detailHeading}}>"
            self.assertEqual(card.count(heading), 1)
            self.assertIn(heading, technical_details)
            self.assertNotIn(heading, concise_details)
        for omitted in (
            "OTel closure",
            "Scope classification",
            "Verification scenarios",
            "After instrumentation",
            "After decision",
            "External follow-up",
            "<h3>Dependencies</h3>",
            "<h3>Resolution</h3>",
        ):
            self.assertNotIn(omitted, technical_details)
        self.assertNotIn("f.verification_scenarios", technical_details)
        self.assertNotIn("f.follow_up_actions", technical_details)
        self.assertNotIn("What you do next", card)


if __name__ == "__main__":
    unittest.main()
