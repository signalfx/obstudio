from __future__ import annotations

import copy
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.error import HTTPError

from observe_report_fixtures import (
    MODULE,
    SCRIPT,
    make_manual_decision,
    sample_decision_branch_report,
    sample_instrumentation,
    sample_report,
    sample_verify,
)


class ObserveReportTest(unittest.TestCase):
    def test_cli_render_html_reads_review_selection_from_saved_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / "otel-audit.json"
            html_path = root / "otel.html"
            data = sample_report()
            report = MODULE.normalize_audit_report(data)
            data["review_selection"] = {
                "schema_version": 1,
                "kind": "otel-selection",
                "audit_id": report["meta"]["audit_id"],
                "audit_sha256": MODULE.audit_digest(report),
                "requested_ids": ["OTEL-001"],
                "approved_ids": ["OTEL-001"],
            }
            audit.write_text(json.dumps(data), encoding="utf-8")

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
            self.assertIn('const requested = new Set(DATA.selection?.requested_ids', html)
            self.assertIn('"requested_ids":["OTEL-001"]', html)
            self.assertIn('"approved_ids":["OTEL-001"]', html)

    def test_render_html_terminal_fallback_preserves_decision_answers(self) -> None:
        report = MODULE.normalize_audit_report(sample_decision_branch_report())
        selection = MODULE.normalize_selection(
            {
                "schema_version": 2,
                "kind": "otel-selection",
                "audit_id": report["meta"]["audit_id"],
                "audit_sha256": MODULE.audit_digest(report),
                "requested_ids": ["OTEL-002"],
                "approved_ids": ["OTEL-002"],
                "decision_answers": [
                    {"finding_id": "OTEL-001", "option_id": "application-owned"}
                ],
            },
            report,
        )

        html = MODULE.render_html(report, selection)

        self.assertIn('"requested_ids":["OTEL-002"]', html)
        self.assertIn('"approved_ids":["OTEL-002"]', html)
        self.assertIn(
            '"decision_answers":[{"finding_id":"OTEL-001","option_id":"application-owned"}]',
            html,
        )
        self.assertIn('parts.push("--decision", `${answer.finding_id}=${answer.option_id}`);', html)
        self.assertIn("const serviceRoot = serviceRootFromLocation();", html)
        self.assertIn("parts.push(serviceRoot);", html)
        self.assertIn(
            "Regenerate this report with its validated service root before instrumenting.",
            html,
        )
        self.assertIn(
            "parts.map((part, index) => index === 0 ? part : commandPart(part)).join",
            html,
        )

    def test_cli_adopts_review_selection_from_saved_audit_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observe = root / ".observe"
            downloads = root / "Downloads"
            observe.mkdir()
            downloads.mkdir()
            audit = observe / "otel-audit.json"
            selection_path = observe / "otel-selection.json"
            data = sample_report()
            report = MODULE.normalize_audit_report(data)
            audit.write_text(json.dumps(data), encoding="utf-8")
            saved_audit = copy.deepcopy(data)
            saved_audit["review_selection"] = {
                "schema_version": 1,
                "kind": "otel-selection",
                "audit_id": report["meta"]["audit_id"],
                "audit_sha256": MODULE.audit_digest(report),
                "requested_ids": ["OTEL-001"],
                "approved_ids": ["OTEL-001"],
            }
            (downloads / "otel-audit (3).json").write_text(
                json.dumps(saved_audit),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "adopt-selection",
                    str(audit),
                    "-o",
                    str(selection_path),
                    "--search-dir",
                    str(downloads),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("otel-audit (3).json", completed.stdout)
            selection = json.loads(selection_path.read_text(encoding="utf-8"))
            self.assertEqual(selection["requested_ids"], ["OTEL-001"])
            self.assertEqual(selection["approved_ids"], ["OTEL-001"])

    def test_manual_without_options_remains_a_static_blocker_without_answers(self) -> None:
        for schema_version in (1, 2):
            with self.subTest(schema_version=schema_version):
                data = sample_report()
                data["schema_version"] = schema_version
                make_manual_decision(data["findings"][0])  # type: ignore[index]

                report = MODULE.normalize_audit_report(data)

                self.assertNotIn("decision_options", report["findings"][0])
                self.assertEqual(
                    MODULE.finding_selection_eligibility(report, "OTEL-001"),
                    {
                        "selectable": False,
                        "blockers": [],
                        "reason": "Resolve decision first",
                    },
                )
                self.assertEqual(
                    MODULE.finding_selection_eligibility(report, "OTEL-002"),
                    {
                        "selectable": False,
                        "blockers": ["OTEL-001"],
                        "reason": "Blocked by OTEL-001",
                    },
                )
                with self.assertRaisesRegex(
                    MODULE.ReportError,
                    "has no selectable decision_options",
                ):
                    MODULE.normalize_selection(
                        {
                            "schema_version": 2,
                            "kind": "otel-selection",
                            "audit_id": report["meta"]["audit_id"],
                            "audit_sha256": MODULE.audit_digest(report),
                            "requested_ids": ["OTEL-002"],
                            "approved_ids": ["OTEL-002"],
                            "decision_answers": [
                                {
                                    "finding_id": "OTEL-001",
                                    "option_id": "application-owned",
                                }
                            ],
                        },
                        report,
                    )

    def test_selection_must_be_nonempty_and_unique(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())
        base = {
            "schema_version": 1,
            "kind": "otel-selection",
            "audit_id": report["meta"]["audit_id"],
            "audit_sha256": MODULE.audit_digest(report),
            "approved_ids": [],
        }

        with self.assertRaisesRegex(MODULE.ReportError, "at least one"):
            MODULE.normalize_selection({**base, "requested_ids": []}, report)
        with self.assertRaisesRegex(MODULE.ReportError, "duplicates"):
            MODULE.normalize_selection(
                {
                    **base,
                    "requested_ids": ["OTEL-001", "OTEL-001"],
                    "approved_ids": ["OTEL-001"],
                },
                report,
            )

    def test_schema_v2_selection_requires_explicit_requested_ids(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())
        selection = {
            "schema_version": 2,
            "kind": "otel-selection",
            "audit_id": report["meta"]["audit_id"],
            "audit_sha256": MODULE.audit_digest(report),
            "approved_ids": ["OTEL-001"],
            "decision_answers": [],
        }

        with self.assertRaisesRegex(MODULE.ReportError, "requested_ids is required"):
            MODULE.normalize_selection(selection, report)

    def test_validate_flow_rejects_stale_selection(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())
        selection = {
            "schema_version": 1,
            "kind": "otel-selection",
            "audit_id": report["meta"]["audit_id"],
            "audit_sha256": "sha256:stale",
            "requested_ids": ["OTEL-001"],
            "approved_ids": ["OTEL-001"],
        }

        with self.assertRaisesRegex(MODULE.ReportError, "does not match audit"):
            MODULE.normalize_selection(selection, report)

    def test_verify_pass_requires_scenario_or_item_proof(self) -> None:
        raw_report = sample_report()
        raw_report["findings"][0]["verification_scenarios"] = []  # type: ignore[index]
        report = MODULE.normalize_audit_report(raw_report)
        digest = MODULE.audit_digest(report)
        selection = MODULE.normalize_selection(
            {
                "schema_version": 1,
                "kind": "otel-selection",
                "audit_id": report["meta"]["audit_id"],  # type: ignore[index]
                "audit_sha256": digest,
                "requested_ids": ["OTEL-001"],
                "approved_ids": ["OTEL-001"],
            },
            report,
        )
        instrumentation_data = sample_instrumentation(report, digest)
        instrumentation_data["meta"]["result"] = "Pass"  # type: ignore[index]
        implementation = instrumentation_data["findings"][0]  # type: ignore[index]
        implementation["status"] = "working"
        implementation["telemetry_changes"] = []
        instrumentation = MODULE.normalize_instrumentation(
            instrumentation_data, report, selection
        )
        verify = {
            "schema_version": 1,
            "kind": "otel-verify",
            "audit_id": report["meta"]["audit_id"],  # type: ignore[index]
            "audit_sha256": digest,
            "instrumentation_sha256": MODULE.instrumentation_digest(instrumentation),
            "meta": {
                "service_name": "checkout",
                "date": "2026-07-21",
                "result": "Pass",
            },
            "findings": [
                {
                    "id": "OTEL-001",
                    "status": "working",
                    "scenarios": [],
                    "item_results": [],
                    "remaining": [],
                }
            ],
            "next_steps": [],
        }

        with self.assertRaisesRegex(MODULE.ReportError, "scenario or telemetry-item proof"):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

    def test_verify_item_results_must_cover_instrumentation_items(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())
        selection = MODULE.normalize_selection(
            {
                "schema_version": 1,
                "kind": "otel-selection",
                "audit_id": report["meta"]["audit_id"],
                "audit_sha256": MODULE.audit_digest(report),
                "requested_ids": ["OTEL-001"],
                "approved_ids": ["OTEL-001"],
            },
            report,
        )
        instrumentation = MODULE.normalize_instrumentation(
            sample_instrumentation(report, MODULE.audit_digest(report)), report, selection
        )
        verify = {
            "schema_version": 1,
            "kind": "otel-verify",
            "audit_id": report["meta"]["audit_id"],
            "audit_sha256": MODULE.audit_digest(report),
            "instrumentation_sha256": MODULE.instrumentation_digest(instrumentation),
            "meta": {"service_name": "checkout", "date": "2026-07-17", "result": "Partial"},
            "findings": [
                {
                    "id": "OTEL-001",
                    "status": "not_proven",
                    "scenarios": [
                        {
                            "id": "http.checkout.success",
                            "status": "not_proven",
                            "commands": [],
                            "evidence": [],
                            "observed_telemetry": [
                                "The expected GET /checkout server span with http.route was absent."
                            ],
                            "trace_ids": [],
                            "product_validation": [],
                            "proof_mode": "not_run",
                            "visibility": "not_proven",
                        }
                    ],
                    "item_results": [],
                    "remaining": ["Run the scenario."],
                }
            ],
            "next_steps": ["Run verification."],
        }
        with self.assertRaisesRegex(MODULE.ReportError, "item_results must exactly cover"):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

    def test_cli_validates_overlay_flow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / "otel-audit.json"
            selection_path = root / "otel-selection.json"
            instrumentation_path = root / "otel-instrumentation.json"
            verify_path = root / "otel-verify.json"
            html_path = root / "otel.html"
            instrumentation_html_path = root / "otel-instrumentation.html"
            audit.write_text(json.dumps(sample_report()), encoding="utf-8")
            report = MODULE.normalize_audit_report(sample_report())
            digest = MODULE.audit_digest(report)
            selection = {
                "schema_version": 1,
                "kind": "otel-selection",
                "audit_id": report["meta"]["audit_id"],
                "audit_sha256": digest,
                "requested_ids": ["OTEL-001"],
                "approved_ids": ["OTEL-001"],
            }
            instrumentation = {
                "schema_version": 1,
                "kind": "otel-instrumentation",
                "audit_id": report["meta"]["audit_id"],
                "audit_sha256": digest,
                "selection_sha256": MODULE.selection_digest(
                    MODULE.normalize_selection(selection, report)
                ),
                "meta": {"service_name": "checkout", "date": "2026-07-17", "result": "Pass"},
                "findings": [
                    {
                        "id": "OTEL-001",
                        "status": "working",
                        "changes": ["Wrapped the server handler."],
                        "telemetry_changes": [
                            {
                                "id": "OTEL-001.http-server-span",
                                "change_kind": "modified",
                                "change": "Wrapped the server handler with route-aware tracing.",
                                "type": "span",
                                "name": "GET /checkout",
                                "source": "main.go:42",
                                "added_attributes": ["http.route"],
                                "product_view": "Route trace waterfall",
                                "follow_up_actions": ["Filter the trace waterfall by http.route."],
                                "verification_scenarios": ["http.checkout.success"],
                            }
                        ],
                        "tests": ["go test ./..."],
                        "evidence": ["PASS"],
                        "follow_up_actions": ["Open the trace in ObStudio."],
                    }
                ],
                "next_steps": ["Run verification."],
            }
            verify = {
                "schema_version": 1,
                "kind": "otel-verify",
                "audit_id": report["meta"]["audit_id"],
                "audit_sha256": digest,
                "meta": {"service_name": "checkout", "date": "2026-07-17", "result": "Pass"},
                "findings": [
                    {
                        "id": "OTEL-001",
                        "status": "working",
                        "scenarios": [
                            {
                                "id": "http.checkout.success",
                                "status": "working",
                                "commands": ["curl localhost:8080/checkout"],
                                "evidence": ["one server span observed"],
                                "observed_telemetry": [
                                    "Span GET /checkout emitted with http.route=/checkout"
                                ],
                                "trace_ids": ["0123456789abcdef0123456789abcdef"],
                                "product_validation": ["Visible in ObStudio trace waterfall"],
                                "proof_mode": "full_runtime",
                                "visibility": "explorer_visible",
                            }
                        ],
                        "item_results": [
                            {
                                "id": "OTEL-001.http-server-span",
                                "status": "working",
                                "direct_assertion_passed": True,
                                "scenarios": ["http.checkout.success"],
                                "proof_mode": "full_runtime",
                                "visibility": "explorer_visible",
                                "evidence": [".observe/evidence/http-checkout.json"],
                                "observed_telemetry": [
                                    "Bounded trace 0123456789abcdef0123456789abcdef "
                                    "contains one SERVER span GET /checkout "
                                    "(0123456789abcdef) with http.route=/checkout."
                                ],
                                "product_validation": ["Visible in ObStudio trace waterfall"],
                            }
                        ],
                        "remaining": [],
                    }
                ],
                "next_steps": ["Generate a dashboard."],
            }
            normalized_selection = MODULE.normalize_selection(selection, report)
            normalized_instrumentation = MODULE.normalize_instrumentation(
                instrumentation, report, normalized_selection
            )
            verify["instrumentation_sha256"] = MODULE.instrumentation_digest(
                normalized_instrumentation
            )
            selection_path.write_text(json.dumps(selection), encoding="utf-8")
            instrumentation_path.write_text(json.dumps(instrumentation), encoding="utf-8")
            verify_path.write_text(json.dumps(verify), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "validate-flow",
                    str(audit),
                    "--selection-json",
                    str(selection_path),
                    "--instrumentation-json",
                    str(instrumentation_path),
                    "--verify-json",
                    str(verify_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("audit -> selection -> instrumentation -> verify", completed.stdout)

            audit_rendered = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "render-html",
                    str(audit),
                    "-o",
                    str(html_path),
                    "--selection-json",
                    str(selection_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(audit_rendered.returncode, 0, audit_rendered.stderr)
            audit_html = html_path.read_text(encoding="utf-8")

            mixed_render = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "render-html",
                    str(audit),
                    "-o",
                    str(html_path),
                    "--selection-json",
                    str(selection_path),
                    "--instrumentation-json",
                    str(instrumentation_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(mixed_render.returncode, 1)
            self.assertIn("use render-instrumentation-html", mixed_render.stderr)
            self.assertEqual(html_path.read_text(encoding="utf-8"), audit_html)

            instrumentation_rendered = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "render-instrumentation-html",
                    str(audit),
                    "-o",
                    str(instrumentation_html_path),
                    "--selection-json",
                    str(selection_path),
                    "--instrumentation-json",
                    str(instrumentation_path),
                    "--verify-json",
                    str(verify_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(instrumentation_rendered.returncode, 0, instrumentation_rendered.stderr)
            self.assertEqual(html_path.read_text(encoding="utf-8"), audit_html)
            instrumentation_result = json.loads(instrumentation_rendered.stdout)
            server = instrumentation_result["server"]
            self.assertTrue(server["requested"])
            self.assertTrue(
                server["url"].startswith("http://127.0.0.1:")
            )
            self.assertTrue(server["url"].endswith("/otel-instrumentation.html"))
            self.assertEqual(
                instrumentation_result["links"],
                {
                    "instrumentation_report": (
                        f"[otel-instrumentation.html]({server['url']})"
                    ),
                    "audit_report": (
                        f"[otel.html]({MODULE.report_server_url(server, 'otel.html')})"
                    ),
                },
            )
            state_path = MODULE.report_server_state_path(root)
            try:
                with MODULE.urlopen(server["url"], timeout=1) as response:
                    served_instrumentation = response.read().decode("utf-8")
                with MODULE.urlopen(
                    MODULE.report_server_url(server, "otel.html"),
                    timeout=1,
                ) as response:
                    served_audit = response.read().decode("utf-8")
                self.assertIn(
                    "OpenTelemetry instrumentation report",
                    served_instrumentation,
                )
                self.assertIn("OpenTelemetry audit report", served_audit)
                with self.assertRaises(HTTPError) as unauthorized:
                    MODULE.urlopen(
                        f"http://127.0.0.1:{server['port']}/otel.html",
                        timeout=1,
                    )
                self.assertEqual(unauthorized.exception.code, 404)
                unauthorized.exception.close()
            finally:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(server["pid"]), "/T", "/F"],
                        check=False,
                        capture_output=True,
                    )
                else:
                    try:
                        os.kill(server["pid"], signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                state_path.unlink(missing_ok=True)
            html = instrumentation_html_path.read_text(encoding="utf-8")
            self.assertIn("OpenTelemetry instrumentation report", html)
            self.assertIn("What changed", html)
            self.assertIn("How it improves observability", html)
            self.assertIn("Selected issues and changes", html)
            self.assertIn("Each checkout request has one route-named trace", html)
            self.assertIn("Verification complete", html)
            self.assertIn(
                "Confirmed in a running service: GET /checkout.", html
            )
            self.assertIn("Confirmed in a running service", html)
            self.assertIn("Telemetry proof", html)
            self.assertIn(
                "The generated trace contains one SERVER span GET /checkout with "
                "http.route=/checkout.",
                html,
            )
            self.assertEqual(html.count("Splunk Observability Cloud"), 0)
            self.assertIn(
                "1 of 1 telemetry changes were confirmed in the configured telemetry explorer.",
                html,
            )
            self.assertIn("You selected", html)
            self.assertIn("Audit and scope report", html)
            self.assertNotIn("Instrumentation JSON", html)
            self.assertNotIn("Verification JSON", html)
            self.assertNotIn("main.go:42", html)
            self.assertNotIn("0123456789abcdef0123456789abcdef", html)
            self.assertNotIn("0123456789abcdef", html)
            self.assertIn(
                "0123456789abcdef0123456789abcdef",
                verify_path.read_text(encoding="utf-8"),
            )
            self.assertNotIn("OTEL-001.http-server-span", html)
            self.assertNotIn("OTLP-delivered items", html)
            self.assertNotIn("Failed findings", html)
            self.assertIn('href="otel.html"', html)
            self.assertNotIn("<script", html.lower())
            self.assertNotIn("<link ", html.lower())
            preserved_audit_html = html_path.read_text(encoding="utf-8")
            self.assertEqual(preserved_audit_html, audit_html)
            self.assertNotIn("OTEL-001.http-server-span", preserved_audit_html)
            self.assertNotIn("OTEL-001.http-server-span", audit_html)
            self.assertNotIn("Route trace waterfall", audit_html)

            html_path.unlink()
            fallback_render = subprocess.run(
                instrumentation_rendered.args,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(fallback_render.returncode, 0, fallback_render.stderr)
            fallback_server = json.loads(fallback_render.stdout)["server"]
            try:
                self.assertEqual(html_path.read_text(encoding="utf-8"), audit_html)
            finally:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(fallback_server["pid"]), "/T", "/F"],
                        check=False,
                        capture_output=True,
                    )
                else:
                    try:
                        os.kill(fallback_server["pid"], signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                state_path.unlink(missing_ok=True)

    def test_instrumentation_html_lists_every_selected_issue_without_truncation(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())
        digest = MODULE.audit_digest(report)
        selection = MODULE.normalize_selection(
            {
                "schema_version": 1,
                "kind": "otel-selection",
                "audit_id": report["meta"]["audit_id"],
                "audit_sha256": digest,
                "requested_ids": ["OTEL-001", "OTEL-002"],
                "approved_ids": ["OTEL-001", "OTEL-002"],
            },
            report,
        )
        instrumentation_data = sample_instrumentation(report, digest, selection)
        instrumentation_data["findings"].append(  # type: ignore[index]
            {
                "id": "OTEL-002",
                "status": "not_proven",
                "changes": [
                    "Kept the runtime-owned signal as proof-first scope.",
                    "Added no duplicate application signal.",
                ],
                "telemetry_changes": [],
                "tests": ["Runtime verification pending."],
                "evidence": ["runtime bootstrap"],
                "follow_up_actions": ["Run the runtime scenario."],
            }
        )
        instrumentation = MODULE.normalize_instrumentation(
            instrumentation_data,
            report,
            selection,
        )

        html = MODULE.render_selected_issue_changes(
            report,
            selection,
            instrumentation,
            None,
        )

        self.assertEqual(html.count('class="selected-issue"'), 2)
        self.assertLess(
            html.index(report["findings"][0]["title"]),
            html.index(report["findings"][1]["title"]),
        )
        self.assertIn("Wrapped the handler.", html)
        self.assertIn("Kept the runtime-owned signal as proof-first scope.", html)
        self.assertIn("Added no duplicate application signal.", html)
        self.assertIn(report["findings"][0]["product_outcome"], html)
        self.assertIn(report["findings"][1]["product_outcome"], html)
        self.assertIn("proof-only scope; no application telemetry item", html)
        self.assertNotIn("No product result recorded", html)

    def test_instrumentation_issue_cards_hide_priority_and_area_labels(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())
        digest = MODULE.audit_digest(report)
        selection = MODULE.normalize_selection(
            {
                "schema_version": 1,
                "kind": "otel-selection",
                "audit_id": report["meta"]["audit_id"],
                "audit_sha256": digest,
                "requested_ids": ["OTEL-001"],
                "approved_ids": ["OTEL-001"],
            },
            report,
        )
        instrumentation = MODULE.normalize_instrumentation(
            sample_instrumentation(report, digest, selection),
            report,
            selection,
        )
        finding = report["findings"][0]
        finding["priority"] = "INTERNAL-PRIORITY-SENTINEL"
        finding["area"] = "INTERNAL-CATEGORY-SENTINEL"

        html = MODULE.render_selected_issue_changes(
            report,
            selection,
            instrumentation,
            None,
        )
        visible_text = re.sub(r"<[^>]+>", " ", html)

        self.assertIn('data-priority="INTERNAL-PRIORITY-SENTINEL"', html)
        self.assertIn('data-area="INTERNAL-CATEGORY-SENTINEL"', html)
        self.assertNotIn("INTERNAL-PRIORITY-SENTINEL", visible_text)
        self.assertNotIn("INTERNAL-CATEGORY-SENTINEL", visible_text)
        self.assertIn("<code>OTEL-001</code>", html)

    def test_instrumentation_card_names_mixed_scenario_evidence(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())
        digest = MODULE.audit_digest(report)
        selection = MODULE.normalize_selection(
            {
                "schema_version": 1,
                "kind": "otel-selection",
                "audit_id": report["meta"]["audit_id"],
                "audit_sha256": digest,
                "requested_ids": ["OTEL-001"],
                "approved_ids": ["OTEL-001"],
            },
            report,
        )
        instrumentation = MODULE.normalize_instrumentation(
            sample_instrumentation(report, digest),
            report,
            selection,
        )
        report["verification"]["scenarios"].extend(
            [
                {
                    "id": "http.checkout.failure",
                    "trigger": "Force a checkout failure",
                    "entrypoint": "main.go:42",
                    "expected_signals": "ERROR server span",
                    "proof_level": "full runtime",
                    "acceptance_criteria": "The failure is recorded once.",
                    "environments": ["go.local"],
                },
                {
                    "id": "http.checkout.cancel",
                    "trigger": "Cancel checkout before completion",
                    "entrypoint": "main.go:42",
                    "expected_signals": "cancelled request outcome",
                    "proof_level": "full runtime",
                    "acceptance_criteria": "Cancellation closes telemetry once.",
                    "environments": ["go.local"],
                },
            ]
        )
        verify = {
            "meta": {"result": "Partial"},
            "findings": [
                {
                    "id": "OTEL-001",
                    "status": "not_proven",
                    "scenarios": [
                        {
                            "id": "http.checkout.success",
                            "status": "working",
                            "commands": ["go test ./..."],
                            "evidence": [".observe/evidence/runtime.json"],
                            "observed_telemetry": ["GET /checkout SERVER span"],
                            "trace_ids": [],
                            "product_validation": ["Local OTLP capture saved."],
                            "proof_mode": "full_runtime",
                            "visibility": "otlp_accepted",
                        },
                        {
                            "id": "http.checkout.failure",
                            "status": "not_proven",
                            "commands": ["go test ./..."],
                            "evidence": [".observe/evidence/test.txt"],
                            "observed_telemetry": ["Focused error assertion passed."],
                            "trace_ids": [],
                            "product_validation": ["Runtime capture still required."],
                            "proof_mode": "app_test",
                            "visibility": "not_explorer_visible",
                        },
                        {
                            "id": "http.checkout.cancel",
                            "status": "not_proven",
                            "commands": [],
                            "evidence": [],
                            "observed_telemetry": [],
                            "trace_ids": [],
                            "product_validation": ["Not run."],
                            "proof_mode": "not_run",
                            "visibility": "not_proven",
                        },
                    ],
                    "item_results": [
                        {
                            "id": "OTEL-001.http-server-span",
                            "status": "working",
                            "scenarios": ["http.checkout.success"],
                            "proof_mode": "full_runtime",
                            "visibility": "otlp_accepted",
                            "evidence": [".observe/evidence/runtime.json"],
                            "observed_telemetry": ["GET /checkout SERVER span"],
                            "product_validation": ["Local OTLP capture saved."],
                        }
                    ],
                    "remaining": ["Finish the running-service matrix."],
                }
            ],
            "next_steps": ["Finish the running-service matrix."],
        }

        selected = MODULE.render_selected_issue_changes(
            report,
            selection,
            instrumentation,
            verify,
        )

        self.assertIn("<h4>Verification incomplete</h4>", selected)
        self.assertNotIn("Verification incomplete — no observed failures", selected)
        self.assertIn("Confirmed in a running service", selected)
        self.assertIn("GET /checkout", selected)
        self.assertIn("Force a checkout failure", selected)
        self.assertIn("Focused evidence obtained", selected)
        self.assertIn(
            "Focused evidence is incomplete for: Force a checkout failure.",
            selected,
        )
        self.assertNotIn("Passed focused checks", selected)
        self.assertIn("Not exercised", selected)
        self.assertIn("Cancel checkout before completion", selected)
        self.assertIn(
            "Not exercised: Cancel checkout before completion.", selected
        )
        self.assertIn("Coverage details", selected)
        self.assertIn("Modified span: GET /checkout", selected)
        self.assertIn("GET /checkout SERVER span", selected)
        self.assertIn(">Proven</span>", selected)
        self.assertNotIn("Splunk Observability Cloud", selected)
        self.assertNotIn("Target product:", selected)
        self.assertNotIn("Not checked for these telemetry changes", selected)
        self.assertNotIn("Executed checks:", selected)
        self.assertNotIn("No executed check failed", selected)
        self.assertNotIn("Checks needed to finish this finding", selected)
        self.assertNotIn("stronger proof", selected)
        self.assertNotIn("mapped scenarios meet required proof", selected)
        self.assertNotIn("scenarios were exercised", selected)
        self.assertNotRegex(selected, r"\b\d+/\d+\b")

    def test_verification_summary_does_not_infer_compound_trigger_grammar(self) -> None:
        scenario = {
            "id": "http.entities-and-relations",
            "status": "not_proven",
            "proof_mode": "not_run",
            "visibility": "not_proven",
            "evidence": [],
            "observed_telemetry": [],
            "product_validation": [],
        }

        summary = MODULE.finding_verification_summary(
            {"scenarios": [scenario]},
            {
                scenario["id"]: {
                    "trigger": "GET /entities and GET /relations",
                }
            },
        )

        self.assertEqual(
            summary,
            "Not exercised: GET /entities and GET /relations.",
        )

    def test_verification_summary_separates_compound_trigger_labels(self) -> None:
        scenarios = [
            {
                "id": scenario_id,
                "status": "not_proven",
                "proof_mode": "not_run",
                "visibility": "not_proven",
                "evidence": [],
                "observed_telemetry": [],
                "product_validation": [],
            }
            for scenario_id in ("http.entities-and-relations", "http.health")
        ]

        summary = MODULE.finding_verification_summary(
            {"scenarios": scenarios},
            {
                "http.entities-and-relations": {
                    "trigger": "GET /entities and GET /relations",
                },
                "http.health": {"trigger": "GET /health"},
            },
        )

        self.assertEqual(
            summary,
            "Not exercised: GET /entities and GET /relations; GET /health.",
        )

    def test_not_proven_item_does_not_upgrade_indirect_evidence(self) -> None:
        implementation = {
            "telemetry_changes": [
                {
                    "id": "OTEL-005.metric-metadata-upgrade-span",
                    "change_kind": "added",
                    "type": "span",
                    "name": "entity-metric-metadata.upgrade",
                }
            ]
        }
        proof = {
            "item_results": [
                {
                    "id": "OTEL-005.metric-metadata-upgrade-span",
                    "status": "not_proven",
                    "proof_mode": "app_test",
                    "visibility": "not_explorer_visible",
                    "evidence": ["UpgradeTelemetryTest.xml", "receiver-stats.json"],
                    "observed_telemetry": [
                        "Focused helper tests ran; aggregate live metric delivery is present."
                    ],
                    "product_validation": ["The exact span was not saved."],
                }
            ]
        }

        rendered = MODULE.render_telemetry_proof_summary(implementation, proof)

        self.assertIn("Added span: entity-metric-metadata.upgrade", rendered)
        self.assertIn('<table class="telemetry-proof-table">', rendered)
        self.assertIn("<th>Telemetry change</th>", rendered)
        self.assertIn("<th>What was observed</th>", rendered)
        self.assertIn("<th>Status</th>", rendered)
        self.assertIn(
            "no saved assertion directly observed the exact span "
            "entity-metric-metadata.upgrade",
            rendered,
        )
        self.assertIn("not observed in an OTLP receiver", rendered)
        self.assertIn(">Not proven</span>", rendered)
        self.assertNotIn("aggregate live metric delivery", rendered)
        self.assertNotIn(">Observed</span>", rendered)

        technical = MODULE.render_verification_details(
            {
                "findings": [
                    {
                        "scenarios": [],
                        "item_results": proof["item_results"],
                    }
                ]
            },
            {"findings": [{"telemetry_changes": implementation["telemetry_changes"]}]},
            {},
        )
        self.assertIn("not observed in an OTLP receiver", technical)
        self.assertNotIn("aggregate live metric delivery", technical)

    def test_instrumentation_summary_separates_pending_proof_from_failure(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())
        digest = MODULE.audit_digest(report)
        selection = MODULE.normalize_selection(
            {
                "schema_version": 1,
                "kind": "otel-selection",
                "audit_id": report["meta"]["audit_id"],
                "audit_sha256": digest,
                "requested_ids": ["OTEL-001"],
                "approved_ids": ["OTEL-001"],
            },
            report,
        )
        instrumentation = MODULE.normalize_instrumentation(
            sample_instrumentation(report, digest),
            report,
            selection,
        )
        verify = {
            "meta": {"result": "Partial"},
            "findings": [
                {
                    "id": "OTEL-001",
                    "status": "not_proven",
                    "scenarios": [
                        {
                            "id": "http.checkout.success",
                            "status": "blocked",
                            "commands": [
                                "test -f /opt/opentelemetry-javaagent.jar",
                                "docker info",
                            ],
                            "evidence": [
                                "/opt/opentelemetry-javaagent.jar is absent",
                                "Docker daemon is unavailable at unix:///tmp/docker.sock",
                            ],
                            "observed_telemetry": [
                                "The expected GET /checkout server span with http.route was absent."
                            ],
                            "trace_ids": [],
                            "product_validation": ["No collector result was produced."],
                            "proof_mode": "not_run",
                            "visibility": "not_proven",
                            "blocking_reason": (
                                "The pinned Java agent and Docker-backed collector "
                                "were unavailable."
                            ),
                            "unobserved_outcome": (
                                "Runtime server-span delivery was not observed."
                            ),
                        }
                    ],
                    "item_results": [
                        {
                            "id": "OTEL-001.http-server-span",
                            "status": "working",
                            "scenarios": ["http.checkout.success"],
                            "proof_mode": "app_test",
                            "visibility": "not_explorer_visible",
                            "evidence": ["focused test passed"],
                            "observed_telemetry": ["one recording-exporter span"],
                            "product_validation": ["Product query not run."],
                        }
                    ],
                    "remaining": [
                        "Run the route with a pinned Java agent and inspectable collector."
                    ],
                }
            ],
            "next_steps": ["Provide the pinned agent and collector."],
        }

        summary = MODULE.render_instrumentation_summary(
            selection,
            instrumentation,
            verify,
        )
        selected = MODULE.render_selected_issue_changes(
            report,
            selection,
            instrumentation,
            verify,
        )

        self.assertIn("Verification incomplete — no observed failures", summary)
        self.assertIn(
            "1 of 1 telemetry change is proven. Local OTLP delivery and Splunk "
            "Observability Cloud were not checked.",
            summary,
        )
        self.assertNotIn("Selected findings represented", summary)
        self.assertNotIn("Failed findings", summary)
        self.assertNotIn("audit-mapped checks", summary)
        self.assertNotIn("Remaining proof plan", summary)
        self.assertIn("verification incomplete", selected)
        self.assertIn(">Proven</span>", selected)
        self.assertIn("Coverage details", selected)
        self.assertIn("Runtime verification unavailable", selected)
        self.assertIn("Why runtime verification is unavailable", selected)
        self.assertIn(
            "The pinned Java agent and Docker-backed collector were unavailable.",
            selected,
        )
        self.assertIn("Already proven", selected)
        self.assertIn("one recording-exporter span", selected)
        self.assertIn("Still unobserved", selected)
        self.assertIn("Runtime server-span delivery was not observed.", selected)
        self.assertNotIn("Checks needed to finish this finding", selected)
        self.assertNotIn("Why verification is pending", selected)
        self.assertNotIn("/opt/opentelemetry-javaagent.jar is absent", selected)
        self.assertNotIn("Docker daemon is unavailable at unix:///tmp/docker.sock", selected)
        self.assertNotIn("Run the route with a pinned Java agent", selected)
        self.assertIn("Selected issue:", selected)
        self.assertIn("What changed / was corrected", selected)

        verify["findings"][0]["item_results"][0]["visibility"] = "otlp_accepted"
        otlp_summary = MODULE.render_instrumentation_summary(
            selection,
            instrumentation,
            verify,
        )
        self.assertIn(
            "Local OTLP delivery was checked; Splunk Observability Cloud was not checked.",
            otlp_summary,
        )
        self.assertNotIn("OTLP-delivered items", otlp_summary)

        verify["findings"][0]["item_results"][0].update(
            {
                "status": "working",
                "visibility": "not_explorer_visible",
            }
        )
        working_item_selected = MODULE.render_selected_issue_changes(
            report,
            selection,
            instrumentation,
            verify,
        )
        self.assertIn(">Proven</span>", working_item_selected)
        self.assertIn("Modified span: GET /checkout", working_item_selected)
        self.assertNotIn("mapped scenarios meet required proof", working_item_selected)
        self.assertNotIn("scenarios were exercised", working_item_selected)
        self.assertNotIn(
            "Expected until the required runtime and product proof is recorded",
            working_item_selected,
        )

        verify["meta"]["result"] = "Fail"
        verify["findings"][0]["status"] = "not_working"
        verify["findings"][0]["scenarios"][0].update(
            {
                "status": "not_working",
                "evidence": [".observe/evidence/runtime/stats-after.json"],
                "product_validation": ["The query returned no expected telemetry."],
                "proof_mode": "full_runtime",
            }
        )
        verify["findings"][0]["item_results"][0].update(
            {
                "status": "not_working",
                "proof_mode": "full_runtime",
                "visibility": "not_proven",
                "evidence": [".observe/evidence/runtime/stats-after.json"],
                "product_validation": ["The query returned no expected telemetry."],
            }
        )
        verify["findings"][0]["scenarios"][0]["observed_telemetry"] = [
            "HTTP 500 was classified as cancellation."
        ]
        verify["findings"][0]["remaining"] = [
            "Use $otel-instrument to repair the Tracer binding.",
            "Rerun the HTTP lifecycle scenarios and save trace proof.",
        ]
        verify["next_steps"] = []
        failed_summary = MODULE.render_instrumentation_summary(
            selection,
            instrumentation,
            verify,
        )
        failed_selected = MODULE.render_selected_issue_changes(
            report,
            selection,
            instrumentation,
            verify,
        )
        self.assertIn("Verification failed — 1 observed failure", failed_summary)
        self.assertIn("0 of 1 telemetry change is proven.", failed_summary)
        self.assertIn(
            "Local OTLP delivery and Splunk Observability Cloud were not checked.",
            failed_summary,
        )
        self.assertNotIn("Next repair steps", failed_summary)
        self.assertIn("What verification found", failed_selected)
        self.assertIn("HTTP 500 was classified as cancellation.", failed_selected)
        self.assertIn("Code repair required", failed_selected)
        self.assertIn("$otel-verify</code> never repairs application code", failed_selected)
        self.assertIn("Use $otel-instrument to repair the Tracer binding.", failed_selected)
        self.assertIn("Rerun the HTTP lifecycle scenarios", failed_selected)
        self.assertNotIn("How the repair is confirmed", failed_selected)
        self.assertNotIn("Why verification is pending", failed_selected)

        verify["next_steps"] = [
            "Run $otel-instrument to repair the Tracer binding.",
            "After the repair, rerun $otel-verify and save proof.",
        ]
        self.assertEqual(
            MODULE.instrumentation_report_next_steps(instrumentation, verify),
            ["Run $otel-instrument to repair the Tracer binding."],
        )

    def test_instrumentation_report_never_makes_verification_the_next_step(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())
        digest = MODULE.audit_digest(report)
        selection = MODULE.normalize_selection(
            {
                "schema_version": 1,
                "kind": "otel-selection",
                "audit_id": report["meta"]["audit_id"],
                "audit_sha256": digest,
                "requested_ids": ["OTEL-001"],
                "approved_ids": ["OTEL-001"],
            },
            report,
        )
        instrumentation = MODULE.normalize_instrumentation(
            sample_instrumentation(report, digest), report, selection
        )

        no_child_steps = MODULE.instrumentation_report_next_steps(
            instrumentation, None
        )
        self.assertEqual(len(no_child_steps), 1)
        self.assertIn("Resolve any recorded prerequisite", no_child_steps[0])
        self.assertNotIn("$otel-verify", no_child_steps[0])
        self.assertNotIn("Run verification", no_child_steps[0])

        verify = sample_verify(
            report,
            digest,
            MODULE.instrumentation_digest(instrumentation),
        )
        verify["meta"]["result"] = "Not run"  # type: ignore[index]
        verify["findings"][0]["status"] = "not_proven"  # type: ignore[index]
        verify["findings"][0]["scenarios"][0].update(  # type: ignore[index]
            {
                "proof_mode": "not_run",
                "visibility": "not_proven",
                "evidence": [],
                "observed_telemetry": [],
                "product_validation": [],
            }
        )
        verify["findings"][0]["item_results"][0].update(  # type: ignore[index]
            {
                "proof_mode": "not_run",
                "visibility": "not_proven",
                "evidence": [],
                "observed_telemetry": [],
                "product_validation": [],
            }
        )
        verify["next_steps"] = ["Run $otel-verify with the same instrumentation selection."]
        normalized_verify = MODULE.normalize_verify(
            verify, report, selection, instrumentation
        )
        not_run_steps = MODULE.instrumentation_report_next_steps(
            instrumentation, normalized_verify
        )
        self.assertEqual(len(not_run_steps), 1)
        self.assertIn("Resolve the prerequisite", not_run_steps[0])
        self.assertNotIn("$otel-verify", not_run_steps[0])
        self.assertNotIn("Run verification", not_run_steps[0])

    def test_blocked_coverage_explains_reason_proof_and_unobserved_result(self) -> None:
        proof = {
            "status": "not_proven",
            "remaining": [
                "Refresh the Artifactory session and restore the lock."
            ],
            "scenarios": [
                {
                    "id": "runtime.orchestrator.shutdown",
                    "status": "blocked",
                    "blocking_reason": (
                        "Exact locked dependencies could not be restored because "
                        "Artifactory authentication expired."
                    ),
                    "unobserved_outcome": (
                        "Final metric delivery from the real orchestrator and MCP "
                        "processes is not yet observed."
                    ),
                    "proof_mode": "not_run",
                    "visibility": "not_proven",
                    "evidence": [".observe/evidence/dev-login-status.txt"],
                    "observed_telemetry": [],
                    "product_validation": [],
                },
                {
                    "id": "runtime.mcp.shutdown",
                    "status": "blocked",
                    "blocking_reason": (
                        "Exact locked dependencies could not be restored because "
                        "Artifactory authentication expired."
                    ),
                    "unobserved_outcome": (
                        "Final metric delivery from the real orchestrator and MCP "
                        "processes is not yet observed."
                    ),
                    "proof_mode": "not_run",
                    "visibility": "not_proven",
                    "evidence": [".observe/evidence/dev-login-status.txt"],
                    "observed_telemetry": [],
                    "product_validation": [],
                },
            ],
            "item_results": [
                {
                    "id": "OTEL-002.metrics-provider-lifecycle",
                    "status": "working",
                    "scenarios": [
                        "runtime.orchestrator.shutdown",
                        "runtime.mcp.shutdown",
                    ],
                    "proof_mode": "unit",
                    "visibility": "not_explorer_visible",
                    "evidence": ["metrics_test.py:408"],
                    "observed_telemetry": [
                        "The lifecycle assertion called force_flush and shutdown "
                        "exactly once."
                    ],
                    "product_validation": [
                        "Final metric delivery from the real orchestrator and MCP "
                        "processes was not exercised."
                    ],
                }
            ],
        }
        report = {
            "verification": {
                "scenarios": [
                    {
                        "id": "runtime.orchestrator.shutdown",
                        "trigger": (
                            "Record an orchestrator metric and terminate gracefully"
                        ),
                    },
                    {
                        "id": "runtime.mcp.shutdown",
                        "trigger": "Record an MCP metric and terminate gracefully",
                    },
                ]
            }
        }
        implementation = {
            "telemetry_changes": [
                {
                    "id": "OTEL-002.metrics-provider-lifecycle",
                    "type": "configuration",
                    "change_kind": "modified",
                    "name": "custom MeterProvider shutdown lifecycle",
                }
            ]
        }

        rendered = MODULE.render_named_finding_proof(report, implementation, proof)

        self.assertIn("Runtime verification unavailable", rendered)
        self.assertIn("Why runtime verification is unavailable", rendered)
        self.assertIn(
            "Exact locked dependencies could not be restored because Artifactory "
            "authentication expired.",
            rendered,
        )
        self.assertIn("Already proven", rendered)
        self.assertIn("force_flush and shutdown exactly once", rendered)
        self.assertIn("Still unobserved", rendered)
        self.assertIn(
            "Final metric delivery from the real orchestrator and MCP processes is "
            "not yet observed.",
            rendered,
        )
        self.assertNotIn("2 checks were blocked.", rendered)
        self.assertLess(
            rendered.index("Runtime verification unavailable"),
            rendered.index("Coverage details"),
        )

    def test_working_verify_requires_working_complete_scenarios(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())
        selection = MODULE.normalize_selection(
            {
                "schema_version": 1,
                "kind": "otel-selection",
                "audit_id": report["meta"]["audit_id"],
                "audit_sha256": MODULE.audit_digest(report),
                "requested_ids": ["OTEL-001"],
                "approved_ids": ["OTEL-001"],
            },
            report,
        )
        instrumentation = MODULE.normalize_instrumentation(
            {
                "schema_version": 1,
                "kind": "otel-instrumentation",
                "audit_id": report["meta"]["audit_id"],
                "audit_sha256": MODULE.audit_digest(report),
                "selection_sha256": MODULE.selection_digest(selection),
                "meta": {"service_name": "checkout", "date": "2026-07-17", "result": "Partial"},
                "findings": [
                    {
                        "id": "OTEL-001",
                        "status": "not_proven",
                        "changes": ["Wrapped the handler."],
                        "telemetry_changes": [
                            {
                                "id": "OTEL-001.http-server-span",
                                "change_kind": "modified",
                                "change": "Wrapped the server handler with route-aware tracing.",
                                "type": "span",
                                "name": "GET /checkout",
                                "source": "main.go:42",
                                "added_attributes": ["http.route"],
                                "product_view": "Route trace waterfall",
                                "follow_up_actions": ["Filter the trace waterfall by http.route."],
                                "verification_scenarios": ["http.checkout.success"],
                            }
                        ],
                        "tests": ["go test ./..."],
                        "evidence": ["main.go:42"],
                        "follow_up_actions": ["Run verification."],
                    }
                ],
                "next_steps": ["Run verification."],
            },
            report,
            selection,
        )
        verify = {
            "schema_version": 1,
            "kind": "otel-verify",
            "audit_id": report["meta"]["audit_id"],
            "audit_sha256": MODULE.audit_digest(report),
            "instrumentation_sha256": MODULE.instrumentation_digest(instrumentation),
            "meta": {"service_name": "checkout", "date": "2026-07-17", "result": "Pass"},
            "findings": [
                {
                    "id": "OTEL-001",
                    "status": "working",
                    "scenarios": [
                        {
                            "id": "http.checkout.success",
                            "status": "not_proven",
                            "commands": [],
                            "evidence": [],
                            "observed_telemetry": [],
                            "trace_ids": [],
                            "product_validation": [],
                            "proof_mode": "not_run",
                            "visibility": "not_proven",
                        }
                    ],
                    "item_results": [
                        {
                            "id": "OTEL-001.http-server-span",
                            "status": "not_proven",
                            "direct_assertion_passed": False,
                            "scenarios": ["http.checkout.success"],
                            "proof_mode": "not_run",
                            "visibility": "not_proven",
                            "evidence": [],
                            "observed_telemetry": [],
                            "product_validation": [],
                        }
                    ],
                    "remaining": [],
                }
            ],
            "next_steps": [],
        }

        with self.assertRaisesRegex(MODULE.ReportError, "every scenario"):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

    def test_render_html_cli_omits_audit_markdown_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / "otel-audit.json"
            html = root / "otel.html"
            audit.write_text(json.dumps(sample_report()), encoding="utf-8")
            rendered = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "render-html",
                    str(audit),
                    "-o",
                    str(html),
                    "--repo-root",
                    str(root),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(rendered.returncode, 0, rendered.stderr)
            html_text = html.read_text(encoding="utf-8")
            self.assertIn("OpenTelemetry audit report", html_text)
            self.assertIn('href="otel-audit.json">Canonical audit data (JSON)</a>', html_text)
            self.assertNotIn("otel.md", html_text)

    def test_finalize_audit_renders_and_validates_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observe = root / ".observe"
            observe.mkdir()
            audit = observe / "otel-audit.json"
            html = observe / "otel.html"
            audit.write_text(json.dumps(sample_report()), encoding="utf-8")

            command = [
                sys.executable,
                "-I",
                str(SCRIPT),
                "finalize-audit",
                ".observe/otel-audit.json",
                "--html",
                ".observe/otel.html",
                "--repo-root",
                ".",
            ]
            server_pid: int | None = None
            state_path = MODULE.report_server_state_path(observe)
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    cwd=root,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                result = json.loads(completed.stdout)
                self.assertEqual(result["result"], "PASS")
                self.assertEqual(result["findings"], 2)
                self.assertEqual(result["scenarios"], 1)
                self.assertEqual(result["audit"], str(audit.resolve()))
                self.assertEqual(result["html"], str(html.resolve()))
                server = result["server"]
                server_pid = server["pid"]
                self.assertTrue(server["requested"])
                self.assertFalse(server["reused"])
                self.assertTrue(server["url"].startswith("http://127.0.0.1:"))
                if os.name == "posix":
                    self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(
                    result["links"],
                    {
                        "review_report": f"[otel.html]({server['url']})",
                        "machine_report": (
                            f"[otel-audit.json](<{audit.resolve()}>)"
                        ),
                    },
                )
                with MODULE.urlopen(server["url"], timeout=1) as response:
                    rendered = response.read().decode("utf-8")
                    self.assertEqual(
                        response.headers["Content-Type"],
                        "text/html; charset=utf-8",
                    )
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertEqual(
                        response.headers["X-Content-Type-Options"],
                        "nosniff",
                    )
                    self.assertEqual(
                        response.headers["Referrer-Policy"],
                        "no-referrer",
                    )
                    self.assertIn(
                        "default-src 'none'",
                        response.headers["Content-Security-Policy"],
                    )
                self.assertIn("OpenTelemetry audit report", rendered)
                denied_url = server["url"].replace("/otel.html", "/not-allowed")
                with self.assertRaises(HTTPError) as denied:
                    MODULE.urlopen(denied_url, timeout=1)
                self.assertEqual(denied.exception.code, 404)
                denied.exception.close()

                repeated = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    cwd=root,
                )
                self.assertEqual(repeated.returncode, 0, repeated.stderr)
                repeated_result = json.loads(repeated.stdout)
                self.assertTrue(repeated_result["server"]["reused"])
                self.assertEqual(repeated_result["server"]["url"], server["url"])
                self.assertTrue(html.is_file())
                self.assertFalse((observe / "otel.md").exists())
                self.assertIn("OpenTelemetry audit", html.read_text(encoding="utf-8"))
            finally:
                if server_pid is not None:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/PID", str(server_pid), "/T", "/F"],
                            check=False,
                            capture_output=True,
                        )
                    else:
                        try:
                            os.kill(server_pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                state_path.unlink(missing_ok=True)

    def test_report_commands_reject_noncanonical_html_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observe = root / ".observe"
            observe.mkdir()
            audit = observe / "otel-audit.json"
            audit.write_text(json.dumps(sample_report()), encoding="utf-8")

            finalized = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(SCRIPT),
                    "finalize-audit",
                    str(audit),
                    "--html",
                    str(observe / "custom.html"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(finalized.returncode, 1)
            self.assertIn("canonical report name otel.html", finalized.stderr)
            self.assertFalse((observe / "custom.html").exists())

            rendered = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(SCRIPT),
                    "render-instrumentation-html",
                    str(audit),
                    "-o",
                    str(observe / "custom.html"),
                    "--selection-json",
                    str(observe / "missing-selection.json"),
                    "--instrumentation-json",
                    str(observe / "missing-instrumentation.json"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(rendered.returncode, 1)
            self.assertIn(
                "canonical report name otel-instrumentation.html",
                rendered.stderr,
            )
            self.assertFalse((observe / "custom.html").exists())

    def test_report_commands_bind_audit_to_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            output = root / "output"
            source.mkdir()
            output.mkdir()
            audit = source / "otel-audit.json"
            audit.write_text(json.dumps(sample_report()), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(SCRIPT),
                    "finalize-audit",
                    str(audit),
                    "--html",
                    str(output / "otel.html"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertIn(
                "canonical otel-audit.json beside otel.html",
                completed.stderr,
            )
            self.assertFalse((output / "otel.html").exists())

    def test_portable_report_read_rejects_symlink(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks are unavailable")
        with tempfile.TemporaryDirectory() as directory:
            report_directory = Path(directory)
            target = report_directory / "target.html"
            target.write_text("private", encoding="utf-8")
            link = report_directory / "otel.html"
            try:
                link.symlink_to(target.name)
            except OSError as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")

            with self.assertRaises(OSError):
                MODULE.read_report_file(None, report_directory, "otel.html")

    def test_report_server_launch_does_not_put_token_in_process_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report_directory = Path(directory)
            process = mock.Mock()
            process.poll.return_value = 1
            with mock.patch.object(MODULE.subprocess, "Popen", return_value=process) as popen:
                with self.assertRaisesRegex(
                    MODULE.ReportError,
                    "could not start the loopback audit report server",
                ):
                    MODULE.start_or_reuse_report_server(report_directory)

            command = popen.call_args.args[0]
            self.assertNotIn("--token", command)
            state = MODULE.read_report_server_state_file(
                MODULE.report_server_state_path(report_directory)
            )
            self.assertIsNotNone(state)
            self.assertNotIn(state["token"], command)
            MODULE.report_server_state_path(report_directory).unlink(missing_ok=True)

    def test_report_server_launch_lock_is_kernel_owned_and_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "server.lock"
            first = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            second = os.open(lock_path, os.O_RDWR, 0o600)
            first_locked = False
            second_locked = False
            try:
                first_locked = MODULE.try_acquire_report_server_lock(first)
                self.assertTrue(first_locked)
                self.assertFalse(MODULE.try_acquire_report_server_lock(second))
                MODULE.release_report_server_lock(first)
                first_locked = False
                first = -1
                second_locked = MODULE.try_acquire_report_server_lock(second)
                self.assertTrue(second_locked)
            finally:
                if first_locked:
                    MODULE.release_report_server_lock(first)
                elif first >= 0:
                    os.close(first)
                if second_locked:
                    MODULE.release_report_server_lock(second)
                else:
                    os.close(second)

    def test_report_server_state_directory_is_per_user(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = MODULE.report_server_state_path(Path(directory))
            if os.name != "nt" and hasattr(os, "getuid"):
                self.assertEqual(
                    state_path.parent.name,
                    f"obstudio-report-servers-{os.getuid()}",
                )

    def test_report_server_state_directory_symlink_is_not_chmodded(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks are unavailable")
        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory)
            victim = temporary_root / "victim"
            victim.mkdir(mode=0o755)
            suffix = (
                f"-{os.getuid()}"
                if os.name != "nt" and hasattr(os, "getuid")
                else ""
            )
            state_directory = (
                temporary_root / f"obstudio-report-servers{suffix}"
            )
            try:
                state_directory.symlink_to(victim, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")
            original_mode = victim.stat().st_mode & 0o777

            with mock.patch.object(
                MODULE.tempfile,
                "gettempdir",
                return_value=str(temporary_root),
            ):
                with self.assertRaises((OSError, MODULE.ReportError)):
                    MODULE.report_server_state_path(temporary_root)

            self.assertEqual(victim.stat().st_mode & 0o777, original_mode)

    def test_report_server_rejects_replaced_directory_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_directory = root / "report"
            report_directory.mkdir()
            status = report_directory.stat()
            state_path = MODULE.report_server_state_path(report_directory)
            try:
                state_path.write_text(
                    json.dumps(
                        {
                            "schema_version": MODULE.REPORT_SERVER_SCHEMA_VERSION,
                            "directory": str(report_directory.resolve()),
                            "directory_device": status.st_dev,
                            "directory_inode": status.st_ino,
                            "pid": 123,
                            "port": 1,
                            "token": "old-directory-token",
                        }
                    ),
                    encoding="utf-8",
                )
                state_path.chmod(0o600)
                report_directory.rename(root / "old-report")
                report_directory.mkdir()

                self.assertIsNone(
                    MODULE.load_report_server_state(state_path, report_directory)
                )
            finally:
                state_path.unlink(missing_ok=True)

    def test_report_server_cleanup_does_not_delete_replacement_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report_directory = Path(directory)
            state_path = MODULE.report_server_state_path(report_directory)
            state_path.write_text(
                json.dumps({"token": "replacement-token"}),
                encoding="utf-8",
            )
            state_path.chmod(0o600)
            lock_path = state_path.with_suffix(".lock")
            lock_descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            self.assertTrue(
                MODULE.try_acquire_report_server_lock(lock_descriptor)
            )
            try:
                MODULE.cleanup_report_server_state(
                    state_path,
                    "old-token",
                )
                self.assertTrue(state_path.exists())
            finally:
                MODULE.release_report_server_lock(lock_descriptor)

            MODULE.cleanup_report_server_state(
                state_path,
                "replacement-token",
            )
            self.assertFalse(state_path.exists())

    def test_report_server_idle_expiry_allows_owned_state_cleanup(self) -> None:
        server = SimpleNamespace(
            last_report_access=0.0,
            handle_request=mock.Mock(),
        )
        with mock.patch.object(
            MODULE.time,
            "monotonic",
            side_effect=[0.5, 1.1],
        ):
            MODULE.serve_report_until_idle(
                server,
                idle_timeout_seconds=1.0,
            )
        server.handle_request.assert_called_once_with()

        with tempfile.TemporaryDirectory() as directory:
            state_path = MODULE.report_server_state_path(Path(directory))
            state_path.write_text(
                json.dumps({"token": "idle-server-token"}),
                encoding="utf-8",
            )
            state_path.chmod(0o600)
            MODULE.cleanup_report_server_state(
                state_path,
                "idle-server-token",
            )
            self.assertFalse(state_path.exists())

    def test_report_server_rejects_state_from_an_older_capability_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report_directory = Path(directory)
            state_path = MODULE.report_server_state_path(report_directory)
            try:
                state_path.write_text(
                    json.dumps(
                        {
                            "schema_version": MODULE.REPORT_SERVER_SCHEMA_VERSION - 1,
                            "directory": str(report_directory.resolve()),
                            "pid": 123,
                            "port": 1,
                            "token": "old-server-token",
                        }
                    ),
                    encoding="utf-8",
                )

                self.assertIsNone(
                    MODULE.load_report_server_state(
                        state_path,
                        report_directory,
                    )
                )
            finally:
                state_path.unlink(missing_ok=True)

    def test_finalize_audit_reports_independent_shape_errors_together(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observe = root / ".observe"
            observe.mkdir()
            audit = observe / "otel-audit.json"
            report = sample_report()
            report["meta"]["genai_ownership_detected"] = True
            report["genai_readiness"] = [
                {
                    "surface": "GenAI workflow telemetry",
                    "evidence": "app.py:42",
                    "required_signals": "invoke_workflow span",
                    "acceptance_criteria": "invoke_workflow span is emitted",
                }
            ]
            report["current_instrumentation"]["incident_readiness"] = [
                {
                    "area": "HTTP latency",
                    "status": "partial",
                    "evidence": "main.go:42",
                    "required_signals": "http.server.request.duration metric",
                }
            ]
            finding = report["findings"][0]
            finding["gap"] = "Overlapping HTTP server spans are possible."
            finding["required_fix"] = "Remove the duplicate manual span."
            audit.write_text(json.dumps(report), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(SCRIPT),
                    "finalize-audit",
                    str(audit),
                    "--html",
                    str(observe / "otel.html"),
                    "--repo-root",
                    str(root),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 1)
            for message in (
                "genai_readiness[0].status must be a string",
                "genai_readiness[0].owner must be a string",
                "genai_readiness[0].impact must be a string",
                "current_instrumentation.incident_readiness[0].impact must be a string",
            ):
                self.assertIn(message, completed.stderr)


if __name__ == "__main__":
    unittest.main()
