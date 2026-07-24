from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "observe_report.py"
SPEC = importlib.util.spec_from_file_location("observe_report", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

def sample_report() -> dict[str, object]:
    return {
        "schema_version": 2,
        "kind": "otel-audit",
        "meta": {
            "audit_id": "checkout-20260717",
            "service_name": "checkout",
            "commit": "abc1234",
            "language": "go",
            "framework": "chi",
            "date": "2026-07-17",
            "status": "Partial",
            "genai_ownership_detected": False,
        },
        "summary": ["Checkout telemetry needs route-level latency coverage."],
        "flow": "audit -> instrument -> verify -> configure",
        "evidence": [
            {"check": "Manifest", "finding": "Go module", "source": "go.mod"},
            {"check": "Entry point", "finding": "HTTP API", "source": "main.go"},
            {"check": "Route source", "finding": "GET /checkout", "source": "main.go:42"},
            {"check": "Runtime/startup", "finding": "go run", "source": "Makefile"},
            {"check": "GenAI ownership", "finding": "No", "source": "bounded repository scan"},
        ],
        "routes": [{"method": "GET", "path": "/checkout"}],
        "signal_flow": {
            "component_flow_map": (
                "Request path\n"
                "main.go [SOURCE-COVERED] -> checkout [GAP: Checkout latency]\n\n"
                "Dependency path\n"
                "checkout [SOURCE-COVERED] -> payment provider [GAP: Payment dependency]"
            )
        },
        "current_instrumentation": {
            "spans": [],
            "metrics": [],
            "logs": [],
            "incident_readiness": [],
        },
        "genai_readiness": [],
        "findings": [
            {
                "id": "OTEL-001",
                "title": "Checkout latency is not measured",
                "priority": "required",
                "effort": "small",
                "otel_concerns": ["signal-emission", "semantic-attributes"],
                "area": "Checkout latency",
                "gap": "No route-level latency metric or span timing exists.",
                "impact": "Operators cannot isolate slow checkout requests.",
                "product_outcome": "Each checkout request has one route-named trace that can be filtered in the waterfall.",
                "required_fix": "Add HTTP server instrumentation and route span attributes.",
                "instrument_mode": "default",
                "verification_scenarios": ["http.checkout.success"],
                "evidence": ["main.go:42"],
                "acceptance_criteria": ["A request emits one server span with http.route."],
                "constraints": ["Keep route values low cardinality."],
                "expected_telemetry": [
                    {
                        "type": "span",
                        "name": "GET /checkout",
                        "attributes": ["http.route"],
                        "product_view": "Trace waterfall and route filtering",
                    }
                ],
                "follow_up_actions": ["Verify the span in ObStudio before merge."],
            },
            {
                "id": "OTEL-002",
                "title": "Payment provider dimension is missing",
                "severity": "medium",
                "priority": "recommended",
                "effort": "medium",
                "otel_concerns": ["signal-emission", "semantic-attributes"],
                "area": "Payment dependency",
                "gap": "Provider calls are not distinguishable.",
                "impact": "Operators cannot compare provider-specific latency.",
                "product_outcome": "Traces can be filtered by a bounded payment-provider name.",
                "required_fix": "Add a low-cardinality payment.provider span attribute.",
                "instrument_mode": "fix all",
                "verification_scenarios": ["http.checkout.success"],
                "dependencies": ["OTEL-001"],
                "evidence": ["payments.go:18"],
                "acceptance_criteria": ["Provider is filterable without raw provider IDs."],
                "constraints": ["Use a bounded provider name."],
                "expected_telemetry": [
                    {
                        "type": "span",
                        "name": "payment.authorize",
                        "attributes": ["payment.provider"],
                        "product_view": "Provider-specific trace filtering",
                    }
                ],
                "follow_up_actions": ["Slice the trace view by payment.provider."],
            },
        ],
        "verification": {
            "environments": [
                {
                    "id": "go.local",
                    "surface": "checkout service",
                    "config_evidence": "go.mod",
                    "runner": "go test ./...",
                    "scope": "module",
                    "prerequisites": "none",
                }
            ],
            "scenarios": [
                {
                    "id": "http.checkout.success",
                    "trigger": "GET /checkout",
                    "entrypoint": "main.go:42",
                    "expected_signals": "GET /checkout span and payment.request.duration metric",
                    "proof_level": "full runtime",
                    "acceptance_criteria": "span is emitted with route attribute",
                    "environments": ["go.local"],
                }
            ],
        },
        "anti_patterns": [],
        "recommendation": ["Run $otel-instrument for OTEL-001."],
    }


def make_manual_decision(finding: dict[str, object]) -> None:
    finding["instrument_mode"] = "manual decision"
    finding["decision_owner"] = "service telemetry owner"
    telemetry = finding["expected_telemetry"]
    signal_name = telemetry[0]["name"]  # type: ignore[index]
    finding["decision_question"] = (
        f"Which owner and bounded attributes should the OTel signal {signal_name} use?"
    )
    finding.pop("external_owner", None)
    finding.pop("external_requirement", None)


def sample_decision_branch_report() -> dict[str, object]:
    data = sample_report()
    decision = data["findings"][0]  # type: ignore[index]
    make_manual_decision(decision)
    decision.update(
        {
            "title": "Choose the checkout span owner",
            "effort": "decision",
            "area": "Checkout tracing owner",
            "gap": "The source does not define which OpenTelemetry owner emits the GET /checkout span.",
            "impact": "Two competing span owners can duplicate or suppress the checkout trace.",
            "product_outcome": "Each checkout request has one canonical GET /checkout span in the trace waterfall.",
            "required_fix": "Choose which OpenTelemetry path emits the GET /checkout span.",
            "follow_up_actions": [
                "Select the GET /checkout span emission path before instrumentation."
            ],
            "dependencies": [],
            "decision_options": [
                {
                    "id": "application-owned",
                    "label": "Application-owned span",
                    "outcome": "Emit the GET /checkout span from application-owned OpenTelemetry instrumentation.",
                    "unlocks": ["OTEL-002"],
                },
                {
                    "id": "runtime-owned",
                    "label": "Runtime-owned span",
                    "outcome": "Emit the GET /checkout span from OpenTelemetry runtime auto-instrumentation.",
                    "unlocks": ["OTEL-003"],
                },
            ],
        }
    )

    application_branch = data["findings"][1]  # type: ignore[index]
    application_branch.update(
        {
            "title": "Implement application-owned checkout tracing",
            "priority": "required",
            "effort": "small",
            "area": "Application checkout tracing",
            "gap": "The application does not emit the canonical GET /checkout span.",
            "impact": "Checkout requests have no application-owned trace waterfall.",
            "product_outcome": "The trace waterfall shows one application-owned GET /checkout span.",
            "required_fix": "Emit the GET /checkout span from application OpenTelemetry instrumentation.",
            "instrument_mode": "default",
            "dependencies": ["OTEL-001"],
            "expected_telemetry": copy.deepcopy(decision["expected_telemetry"]),
            "acceptance_criteria": [
                "Application instrumentation emits one GET /checkout span with http.route."
            ],
            "follow_up_actions": [
                "Verify the application-owned GET /checkout span before merge."
            ],
        }
    )

    runtime_branch = copy.deepcopy(application_branch)
    runtime_branch.update(
        {
            "id": "OTEL-003",
            "title": "Configure runtime-owned checkout tracing",
            "priority": "recommended",
            "area": "Runtime checkout tracing",
            "gap": "Runtime auto-instrumentation does not emit the canonical GET /checkout span.",
            "impact": "Checkout requests have no runtime-owned trace waterfall.",
            "product_outcome": "The trace waterfall shows one runtime-owned GET /checkout span.",
            "required_fix": "Emit the GET /checkout span from OpenTelemetry runtime auto-instrumentation.",
            "instrument_mode": "fix all",
            "acceptance_criteria": [
                "Runtime auto-instrumentation emits one GET /checkout span with http.route."
            ],
            "follow_up_actions": [
                "Verify the runtime-owned GET /checkout span before merge."
            ],
        }
    )
    data["findings"].append(runtime_branch)  # type: ignore[index]
    data["signal_flow"]["component_flow_map"] = (  # type: ignore[index]
        "main.go [GAP: Checkout tracing owner]\n"
        "checkout handler [GAP: Application checkout tracing]\n"
        "runtime bootstrap [GAP: Runtime checkout tracing]"
    )
    return data


def make_external_follow_up(finding: dict[str, object]) -> None:
    finding["instrument_mode"] = "external follow-up"
    finding["external_owner"] = "telemetry platform team"
    telemetry = finding["expected_telemetry"]
    signal_name = telemetry[0]["name"]  # type: ignore[index]
    requirement = f"Supply the platform-owned OTel signal {signal_name} and saved telemetry proof."
    finding["external_requirement"] = requirement
    finding["required_fix"] = requirement
    finding.pop("decision_owner", None)
    finding.pop("decision_question", None)


def sample_instrumentation(
    report: dict[str, object],
    digest: str,
    selection: dict[str, object] | None = None,
) -> dict[str, object]:
    if selection is None:
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
    return {
        "schema_version": 1,
        "kind": "otel-instrumentation",
        "audit_id": report["meta"]["audit_id"],  # type: ignore[index]
        "audit_sha256": digest,
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
                "follow_up_actions": ["Run verification, then review the route trace."],
            }
        ],
        "next_steps": ["Run verification."],
    }


def sample_verify(
    report: dict[str, object],
    digest: str,
    instrumentation_sha256: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "otel-verify",
        "audit_id": report["meta"]["audit_id"],  # type: ignore[index]
        "audit_sha256": digest,
        "instrumentation_sha256": instrumentation_sha256,
        "meta": {"service_name": "checkout", "date": "2026-07-20", "result": "Partial"},
        "findings": [
            {
                "id": "OTEL-001",
                "status": "not_proven",
                "scenarios": [
                    {
                        "id": "http.checkout.success",
                        "status": "not_proven",
                        "commands": ["go test ./..."],
                        "evidence": [".observe/evidence/run/test.txt"],
                        "observed_telemetry": [],
                        "trace_ids": [],
                        "product_validation": ["Target-product query was not run."],
                        "proof_mode": "app_test",
                        "visibility": "not_explorer_visible",
                    }
                ],
                "item_results": [
                    {
                        "id": "OTEL-001.http-server-span",
                        "status": "not_proven",
                        "direct_assertion_passed": False,
                        "scenarios": ["http.checkout.success"],
                        "proof_mode": "app_test",
                        "visibility": "not_explorer_visible",
                        "evidence": [".observe/evidence/run/test.txt"],
                        "observed_telemetry": [],
                        "product_validation": ["Target-product query was not run."],
                    }
                ],
                "remaining": ["Capture the remaining route topology proof."],
            }
        ],
        "next_steps": ["Capture the remaining route topology proof."],
    }


class ObserveReportTest(unittest.TestCase):
    def test_markdown_local_file_link_is_platform_safe(self) -> None:
        self.assertEqual(
            MODULE.markdown_local_file_link(
                "otel.html",
                PureWindowsPath(r"C:\Users\A User\audit#one\otel.html"),
            ),
            "[otel.html](<C:/Users/A User/audit%23one/otel.html>)",
        )
        self.assertEqual(
            MODULE.markdown_local_file_link(
                "otel-audit.json",
                PurePosixPath("/tmp/A Report/otel?.json"),
            ),
            "[otel-audit.json](</tmp/A Report/otel%3F.json>)",
        )

    def write_finalize_flow(
        self,
        root: Path,
        *,
        failed_child: bool = False,
        stale_parent_handoff: bool = False,
        stale_telemetry_handoff: bool = False,
        generic_product_verification: bool = False,
        workflow_mode: str = "instrumentation_child",
    ) -> SimpleNamespace:
        report = MODULE.normalize_audit_report(sample_report())
        audit_digest = MODULE.audit_digest(report)
        selection = {
            "schema_version": 1,
            "kind": "otel-selection",
            "audit_id": report["meta"]["audit_id"],
            "audit_sha256": audit_digest,
            "requested_ids": ["OTEL-001"],
            "approved_ids": ["OTEL-001"],
        }
        normalized_selection = MODULE.normalize_selection(selection, report)
        instrumentation = sample_instrumentation(
            report, audit_digest, normalized_selection
        )
        if not stale_parent_handoff:
            instrumentation["findings"][0]["follow_up_actions"] = [  # type: ignore[index]
                "Capture the remaining route topology proof."
            ]
            instrumentation["next_steps"] = [
                "Capture the remaining route topology proof."
            ]
        telemetry_change = instrumentation["findings"][0]["telemetry_changes"][0]  # type: ignore[index]
        if stale_telemetry_handoff:
            telemetry_change["follow_up_actions"] = [
                "Run $otel-verify, then filter the trace waterfall by http.route."
            ]
        elif generic_product_verification:
            telemetry_change["follow_up_actions"] = [
                "Run verification in Splunk Observability Cloud, then filter the "
                "trace waterfall by http.route."
            ]
        normalized_instrumentation = MODULE.normalize_instrumentation(
            instrumentation, report, normalized_selection
        )
        verify = sample_verify(
            report,
            audit_digest,
            MODULE.instrumentation_digest(normalized_instrumentation),
        )
        verify["meta"].update(  # type: ignore[union-attr]
            {"workflow_mode": workflow_mode, "lifecycle": "final"}
        )
        if failed_child:
            verify["meta"].update(  # type: ignore[union-attr]
                {"result": "Fail", "lifecycle": "intermediate"}
            )
            finding = verify["findings"][0]  # type: ignore[index]
            finding["status"] = "not_working"
            finding["remaining"] = ["Repair the server span wiring."]
            scenario = finding["scenarios"][0]
            scenario.update(
                {
                    "status": "not_working",
                    "observed_telemetry": [
                        "The GET /checkout server span with http.route was absent."
                    ],
                }
            )
            item = finding["item_results"][0]
            item.update(
                {
                    "status": "not_working",
                    "observed_telemetry": [
                        "The GET /checkout server span with http.route was absent."
                    ],
                }
            )
            verify["next_steps"] = ["Repair the server span wiring."]

        paths = SimpleNamespace(
            audit_json=root / "otel-audit.json",
            selection_json=root / "otel-selection.json",
            instrumentation_json=root / "otel-instrumentation.json",
            verify_json=root / "otel-verify.json",
            audit_markdown=None,
            instrumentation_markdown=None,
            verify_markdown=None,
            output=root / "otel-instrumentation.html",
            repo_root=root,
            gate_output=root / "otel-instrumentation-gate.json",
        )
        paths.audit_json.write_text(json.dumps(sample_report()), encoding="utf-8")
        paths.selection_json.write_text(json.dumps(selection), encoding="utf-8")
        paths.instrumentation_json.write_text(
            json.dumps(instrumentation), encoding="utf-8"
        )
        paths.verify_json.write_text(json.dumps(verify), encoding="utf-8")
        for markdown in (
            root / "otel.md",
            root / "otel-instrumentation.md",
            root / "otel-verify.md",
        ):
            markdown.write_text("projection\n", encoding="utf-8")
        return paths

    def test_finalize_instrumentation_uses_active_bundle_validators_then_renders_and_gates(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.write_finalize_flow(Path(directory))
            completed = subprocess.CompletedProcess([], 0, "PASS\n", "")
            with (
                mock.patch.object(
                    MODULE.subprocess, "run", side_effect=[completed, completed]
                ) as run,
                mock.patch.object(
                    MODULE,
                    "render_instrumentation_html",
                    return_value="<html>final</html>\n",
                ) as render,
            ):
                result = MODULE.cmd_finalize_instrumentation(paths)

            self.assertEqual(result, 0)
            self.assertEqual(
                paths.output.read_text(encoding="utf-8"),
                "<html>final</html>\n",
            )
            gate = json.loads(paths.gate_output.read_text(encoding="utf-8"))
            self.assertTrue(gate["passed"])
            render.assert_called_once()
            self.assertEqual(run.call_count, 2)
            skills_root = SCRIPT.resolve().parents[2]
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(commands[0][1], "-I")
            self.assertEqual(commands[1][1], "-I")
            self.assertEqual(
                Path(commands[0][2]),
                skills_root
                / "otel-verify"
                / "scripts"
                / "validate_reader_report.py",
            )
            self.assertEqual(
                Path(commands[1][2]),
                skills_root
                / "otel-instrument"
                / "scripts"
                / "validate_gap_closure.py",
            )
            self.assertIn(str(paths.instrumentation_json), commands[0])
            self.assertIn(str(paths.verify_json), commands[0])
            self.assertIn(str(paths.audit_json), commands[0])
            self.assertIn(str(paths.selection_json), commands[0])
            self.assertIn(str(paths.audit_json.with_name("otel.md")), commands[1])
            self.assertIn(str(paths.audit_json), commands[1])
            self.assertIn(str(paths.selection_json), commands[1])
            self.assertIn(str(paths.instrumentation_json), commands[1])
            self.assertIn(str(paths.verify_json), commands[1])

    def test_finalize_instrumentation_passes_exact_non_sibling_overlay_to_gap_validator(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.write_finalize_flow(Path(directory))
            explicit = paths.instrumentation_json.with_name("selected-overlay.json")
            paths.instrumentation_json.rename(explicit)
            paths.instrumentation_json = explicit
            completed = subprocess.CompletedProcess([], 0, "PASS\n", "")
            with (
                mock.patch.object(
                    MODULE.subprocess, "run", side_effect=[completed, completed]
                ) as run,
                mock.patch.object(
                    MODULE,
                    "render_instrumentation_html",
                    return_value="<html>final</html>\n",
                ),
            ):
                result = MODULE.cmd_finalize_instrumentation(paths)

            self.assertEqual(result, 0)
            gap_command = run.call_args_list[1].args[0]
            index = gap_command.index("--instrumentation-json")
            self.assertEqual(gap_command[index + 1], str(explicit))
            self.assertFalse(explicit.with_name("otel-instrumentation.json").exists())

    def test_instrumentation_digest_prints_only_bound_canonical_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.write_finalize_flow(Path(directory))
            inputs = {
                path: path.read_bytes()
                for path in (
                    paths.audit_json,
                    paths.selection_json,
                    paths.instrumentation_json,
                )
            }
            report = MODULE.normalize_audit_report(MODULE.load_json(paths.audit_json))
            selection = MODULE.load_selection(paths.selection_json, report)
            instrumentation = MODULE.normalize_instrumentation(
                MODULE.load_json(paths.instrumentation_json), report, selection
            )
            expected = MODULE.instrumentation_digest(instrumentation)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "instrumentation-digest",
                    str(paths.audit_json),
                    "--selection-json",
                    str(paths.selection_json),
                    "--instrumentation-json",
                    str(paths.instrumentation_json),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout, expected + "\n")
            self.assertEqual(completed.stderr, "")
            for path, content in inputs.items():
                self.assertEqual(path.read_bytes(), content)

    def test_finalize_instrumentation_rejects_stale_digest_before_calls_or_writes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.write_finalize_flow(Path(directory))
            verify = json.loads(paths.verify_json.read_text(encoding="utf-8"))
            verify["instrumentation_sha256"] = "sha256:" + "0" * 64
            paths.verify_json.write_text(json.dumps(verify), encoding="utf-8")
            instrumentation_before = paths.instrumentation_json.read_bytes()
            verify_before = paths.verify_json.read_bytes()
            paths.output.write_text("existing html\n", encoding="utf-8")
            paths.gate_output.write_text("existing gate\n", encoding="utf-8")
            with (
                mock.patch.object(MODULE.subprocess, "run") as run,
                mock.patch.object(MODULE, "render_instrumentation_html") as render,
                self.assertRaisesRegex(
                    MODULE.ReportError,
                    "instrumentation_sha256 does not match instrumentation",
                ),
            ):
                MODULE.cmd_finalize_instrumentation(paths)

            run.assert_not_called()
            render.assert_not_called()
            self.assertEqual(paths.instrumentation_json.read_bytes(), instrumentation_before)
            self.assertEqual(paths.verify_json.read_bytes(), verify_before)
            self.assertEqual(paths.output.read_text(encoding="utf-8"), "existing html\n")
            self.assertEqual(
                paths.gate_output.read_text(encoding="utf-8"), "existing gate\n"
            )

    def test_finalize_instrumentation_rejects_stale_parent_verify_cta_before_calls_or_writes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.write_finalize_flow(
                Path(directory), stale_parent_handoff=True
            )
            instrumentation_before = paths.instrumentation_json.read_bytes()
            verify_before = paths.verify_json.read_bytes()
            paths.output.write_text("existing html\n", encoding="utf-8")
            paths.gate_output.write_text("existing gate\n", encoding="utf-8")
            with (
                mock.patch.object(MODULE.subprocess, "run") as run,
                mock.patch.object(MODULE, "render_instrumentation_html") as render,
                self.assertRaisesRegex(
                    MODULE.ReportError,
                    "stale parent actions that ask to run the already-present child",
                ),
            ):
                MODULE.cmd_finalize_instrumentation(paths)

            run.assert_not_called()
            render.assert_not_called()
            self.assertEqual(
                paths.instrumentation_json.read_bytes(), instrumentation_before
            )
            self.assertEqual(paths.verify_json.read_bytes(), verify_before)
            self.assertEqual(
                paths.output.read_text(encoding="utf-8"), "existing html\n"
            )
            self.assertEqual(
                paths.gate_output.read_text(encoding="utf-8"), "existing gate\n"
            )

    def test_stale_parent_verification_action_patterns_are_product_aware(self) -> None:
        stale = (
            "Continue the active instrumentation workflow through verification.",
            "Run $otel-verify.",
            "Execute the child verification workflow.",
            "Continue with the verification workflow.",
            "Run verification.",
            "Run $otel-verify, then inspect Splunk Observability Cloud.",
        )
        durable = (
            "Run verification in Splunk Observability Cloud.",
            "Run verification against the target product.",
            "Run product verification for the generated trace.",
            "Query Splunk Observability Cloud for the generated trace.",
            "Capture the remaining route topology proof.",
        )

        for action in stale:
            with self.subTest(stale=action):
                self.assertTrue(MODULE.is_stale_parent_verification_action(action))
        for action in durable:
            with self.subTest(durable=action):
                self.assertFalse(MODULE.is_stale_parent_verification_action(action))

    def test_finalize_instrumentation_rejects_stale_telemetry_verify_cta_before_calls_or_writes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.write_finalize_flow(
                Path(directory), stale_telemetry_handoff=True
            )
            paths.output.write_text("existing html\n", encoding="utf-8")
            paths.gate_output.write_text("existing gate\n", encoding="utf-8")
            with (
                mock.patch.object(MODULE.subprocess, "run") as run,
                mock.patch.object(MODULE, "render_instrumentation_html") as render,
                self.assertRaisesRegex(
                    MODULE.ReportError,
                    r"telemetry_changes\[0\]\.follow_up_actions\[0\]",
                ),
            ):
                MODULE.cmd_finalize_instrumentation(paths)

            run.assert_not_called()
            render.assert_not_called()
            self.assertEqual(
                paths.output.read_text(encoding="utf-8"), "existing html\n"
            )
            self.assertEqual(
                paths.gate_output.read_text(encoding="utf-8"), "existing gate\n"
            )

    def test_finalize_instrumentation_allows_generic_product_verification_action(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.write_finalize_flow(
                Path(directory), generic_product_verification=True
            )
            completed = subprocess.CompletedProcess([], 0, "PASS\n", "")
            with (
                mock.patch.object(
                    MODULE.subprocess, "run", side_effect=[completed, completed]
                ),
                mock.patch.object(
                    MODULE,
                    "render_instrumentation_html",
                    return_value="<html>final</html>\n",
                ),
            ):
                result = MODULE.cmd_finalize_instrumentation(paths)

            self.assertEqual(result, 0)
            self.assertEqual(
                paths.output.read_text(encoding="utf-8"), "<html>final</html>\n"
            )

    def test_finalize_instrumentation_rejects_standalone_verify_before_calls_or_writes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.write_finalize_flow(Path(directory), workflow_mode="standalone")
            paths.output.write_text("existing html\n", encoding="utf-8")
            paths.gate_output.write_text("existing gate\n", encoding="utf-8")
            with (
                mock.patch.object(MODULE.subprocess, "run") as run,
                mock.patch.object(MODULE, "render_instrumentation_html") as render,
                self.assertRaisesRegex(
                    MODULE.ReportError,
                    "requires verify.meta.workflow_mode instrumentation_child",
                ),
            ):
                MODULE.cmd_finalize_instrumentation(paths)

            run.assert_not_called()
            render.assert_not_called()
            self.assertEqual(
                paths.output.read_text(encoding="utf-8"), "existing html\n"
            )
            self.assertEqual(
                paths.gate_output.read_text(encoding="utf-8"), "existing gate\n"
            )

    def test_finalize_instrumentation_projection_failure_prevents_render_and_gate(
        self,
    ) -> None:
        for failing_call in (1, 2):
            with self.subTest(failing_call=failing_call), tempfile.TemporaryDirectory() as directory:
                paths = self.write_finalize_flow(Path(directory))
                success = subprocess.CompletedProcess([], 0, "PASS\n", "")
                failure = subprocess.CompletedProcess([], 1, "", "bad projection\n")
                results = [failure] if failing_call == 1 else [success, failure]
                with (
                    mock.patch.object(
                        MODULE.subprocess, "run", side_effect=results
                    ) as run,
                    mock.patch.object(
                        MODULE, "render_instrumentation_html"
                    ) as render,
                    self.assertRaisesRegex(MODULE.ReportError, "bad projection"),
                ):
                    MODULE.cmd_finalize_instrumentation(paths)

                self.assertEqual(run.call_count, failing_call)
                render.assert_not_called()
                self.assertFalse(paths.output.exists())
                self.assertFalse(paths.gate_output.exists())

    def test_finalize_instrumentation_renders_failed_intermediate_then_exits_two(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.write_finalize_flow(Path(directory), failed_child=True)
            completed = subprocess.CompletedProcess([], 0, "PASS\n", "")
            with (
                mock.patch.object(
                    MODULE.subprocess, "run", side_effect=[completed, completed]
                ),
                mock.patch.object(
                    MODULE,
                    "render_instrumentation_html",
                    return_value="<html>repair required</html>\n",
                ),
            ):
                result = MODULE.cmd_finalize_instrumentation(paths)

            self.assertEqual(result, 2)
            self.assertTrue(paths.output.is_file())
            gate = json.loads(paths.gate_output.read_text(encoding="utf-8"))
            self.assertFalse(gate["passed"])
            self.assertEqual(gate["verification_lifecycle"], "intermediate")
            self.assertEqual(gate["failed_findings"], ["OTEL-001"])

    def test_example_report_companions_are_canonical_and_bound(self) -> None:
        repo_root = Path(__file__).parents[3]
        example_root = repo_root / "docs" / "example-reports"
        fixture_root = (
            repo_root / "evals" / "go" / "chi-basic" / "eval" / "inputs"
        )
        audit_raw = json.loads((example_root / "otel-audit.json").read_text())
        selection_raw = json.loads(
            (example_root / "otel-selection.json").read_text()
        )
        instrumentation_raw = json.loads(
            (example_root / "otel-instrumentation.json").read_text()
        )
        verify_raw = json.loads((example_root / "otel-verify.json").read_text())

        report = MODULE.normalize_audit_report(audit_raw)
        self.assertEqual(
            report,
            MODULE.normalize_audit_report(
                json.loads((fixture_root / "otel-audit.json").read_text())
            ),
        )
        for filename, published in (
            ("otel-selection.json", selection_raw),
            ("otel-instrumentation.json", instrumentation_raw),
            ("otel-verify.json", verify_raw),
        ):
            self.assertEqual(
                published,
                json.loads((fixture_root / filename).read_text()),
                f"published {filename} must match its canonical fixture input",
            )
        self.assertEqual(audit_raw, report)
        selection = MODULE.normalize_selection(selection_raw, report)
        instrumentation = MODULE.normalize_instrumentation(
            instrumentation_raw, report, selection
        )
        verify = MODULE.normalize_verify(
            verify_raw, report, selection, instrumentation
        )

        self.assertEqual(selection_raw, selection)
        self.assertEqual(instrumentation_raw, instrumentation)
        self.assertEqual(verify_raw, verify)
        self.assertEqual(selection["audit_sha256"], MODULE.audit_digest(report))
        self.assertEqual(
            instrumentation["selection_sha256"],
            MODULE.selection_digest(selection),
        )
        self.assertEqual(
            verify["instrumentation_sha256"],
            MODULE.instrumentation_digest(instrumentation),
        )
        self.assertEqual(
            [
                item["id"]
                for finding in instrumentation["findings"]
                for item in finding["telemetry_changes"]
            ],
            ["OTEL-001.http-health-span"],
        )
        self.assertEqual(
            [
                item["id"]
                for finding in verify["findings"]
                for item in finding["item_results"]
            ],
            ["OTEL-001.http-health-span"],
        )
        recommendation = " ".join(report["recommendation"])
        self.assertIn(".observe/otel-audit.json", recommendation)
        self.assertIn("$otel-instrument", recommendation)
        self.assertNotIn("$otel-instrument --ids", recommendation)
        instrumentation_html = (
            example_root / "otel-instrumentation.html"
        ).read_text()
        self.assertIn(
            f'<meta name="otel-selection-sha256" content="{MODULE.selection_digest(selection)}">',
            instrumentation_html,
        )
        self.assertIn("1 of 1 telemetry change is proven", instrumentation_html)
        self.assertIn(
            "Confirmed in a running service: GET /health.",
            instrumentation_html,
        )
        self.assertNotIn("1 of 1 route check", instrumentation_html)
        self.assertNotIn("Removed span: HttpRequest", instrumentation_html)
        self.assertIn("were outside this instrumentation run", instrumentation_html)
        self.assertNotIn("were not implemented in this run", instrumentation_html)

    def test_report_writes_reject_symlinked_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            repository.mkdir()
            outside = root / "outside"
            outside.mkdir()
            victim = outside / "otel.html"
            victim.write_text("must survive\n", encoding="utf-8")
            (repository / ".observe").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(OSError):
                MODULE.write_text(repository / ".observe" / "otel.html", "forged\n")

            self.assertEqual(victim.read_text(encoding="utf-8"), "must survive\n")

    def test_report_writes_reject_symlinked_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / ".observe" / "otel-audit.json"
            output.parent.mkdir()
            victim = root / "victim.json"
            victim.write_text("must survive\n", encoding="utf-8")
            output.symlink_to(victim)

            with self.assertRaises(MODULE.ReportError):
                MODULE.write_json(output, {"forged": True})

            self.assertEqual(victim.read_text(encoding="utf-8"), "must survive\n")

    def test_portable_report_writer_creates_and_replaces_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = (
                Path(directory).resolve()
                / "repository"
                / ".observe"
                / "otel.html"
            )
            with mock.patch.object(
                MODULE, "descriptor_atomic_writes_supported", return_value=False
            ):
                MODULE.write_text(output, "first\n")
                MODULE.write_text(output, "second\n")

            self.assertEqual(output.read_text(encoding="utf-8"), "second\n")

    def test_portable_report_writer_rejects_symlink_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            outside = root / "outside"
            outside.mkdir()
            victim = outside / "otel.html"
            victim.write_text("must survive\n", encoding="utf-8")
            repository = root / "repository"
            repository.mkdir()
            (repository / ".observe").symlink_to(outside, target_is_directory=True)
            with mock.patch.object(
                MODULE, "descriptor_atomic_writes_supported", return_value=False
            ):
                with self.assertRaises(MODULE.ReportError):
                    MODULE.write_text(
                        repository / ".observe" / "otel.html", "forged\n"
                    )
            self.assertEqual(victim.read_text(encoding="utf-8"), "must survive\n")

            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_output = real_parent / "otel.json"
            linked_output.symlink_to(victim)
            with mock.patch.object(
                MODULE, "descriptor_atomic_writes_supported", return_value=False
            ):
                with self.assertRaises(MODULE.ReportError):
                    MODULE.write_json(linked_output, {"forged": True})
            self.assertEqual(victim.read_text(encoding="utf-8"), "must survive\n")

    def test_portable_report_writer_detects_parent_swap_after_replace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            parent = root / "repository" / ".observe"
            parent.mkdir(parents=True)
            output = parent / "otel.html"
            moved = parent.with_name("moved-observe")
            real_replace = MODULE.os.replace

            def replace_then_swap(source: Path, target: Path) -> None:
                real_replace(source, target)
                parent.rename(moved)
                parent.mkdir()

            with mock.patch.object(
                MODULE, "descriptor_atomic_writes_supported", return_value=False
            ), mock.patch.object(MODULE.os, "replace", replace_then_swap):
                with self.assertRaisesRegex(
                    MODULE.ReportError, "lacks descriptor-relative"
                ):
                    MODULE.write_text(output, "generated\n")

            self.assertFalse(output.exists())
            self.assertEqual(
                (moved / output.name).read_text(encoding="utf-8"),
                "generated\n",
            )

    def test_windows_reparse_attribute_is_rejected(self) -> None:
        status = type(
            "ReparseStatus",
            (),
            {
                "st_mode": MODULE.stat.S_IFDIR,
                "st_file_attributes": getattr(
                    MODULE.stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
                ),
            },
        )()
        self.assertTrue(MODULE.path_is_link_or_reparse(status))

    def test_descriptor_writer_requires_complete_platform_capabilities(self) -> None:
        if MODULE.os.name != "posix":
            self.assertFalse(MODULE.descriptor_atomic_writes_supported())
            return
        without_rename = set(MODULE.os.supports_dir_fd) - {MODULE.os.rename}
        with mock.patch.object(MODULE.os, "supports_dir_fd", without_rename):
            self.assertFalse(MODULE.descriptor_atomic_writes_supported())
        without_nofollow_stat = set(MODULE.os.supports_follow_symlinks) - {
            MODULE.os.stat
        }
        with mock.patch.object(
            MODULE.os, "supports_follow_symlinks", without_nofollow_stat
        ):
            self.assertFalse(MODULE.descriptor_atomic_writes_supported())

    def test_exact_telemetry_reference_rejects_identifier_prefix_collisions(self) -> None:
        item = {
            "name": "http.server.request.duration",
            "attributes": ["http.route"],
        }
        self.assertFalse(
            MODULE.exact_telemetry_item_is_referenced(
                "http.server.request.duration.total with http.route_id", item
            )
        )
        self.assertFalse(
            MODULE.exact_telemetry_item_is_referenced(
                "http.server.request.duration with http.route did not emit", item
            )
        )
        self.assertTrue(
            MODULE.exact_telemetry_item_is_referenced(
                "http.server.request.duration emitted with http.route", item
            )
        )
        self.assertTrue(
            MODULE.exact_telemetry_item_is_referenced(
                "No errors occurred. http.server.request.duration"
                "{http.route=/checkout} emitted",
                item,
            )
        )

    def test_positive_telemetry_reference_requires_one_affirmative_clause(self) -> None:
        item = {
            "name": "http.server.request.duration",
            "attributes": ["http.route"],
        }
        aspirational_or_disjoint = (
            "Expected http.server.request.duration; http.route should be configured.",
            "Expected http.server.request.duration with http.route was emitted.",
            "http.server.request.duration with http.route was not confirmed.",
            "http.server.request.duration may have emitted with http.route.",
            "Observed http.server.request.duration. Recorded http.route.",
            "Source code contains http.server.request.duration with http.route.",
            "Configuration contains http.server.request.duration with http.route.",
            "The test plan recorded the string http.server.request.duration with http.route.",
            "A comment asserted http.server.request.duration with http.route.",
            "The unit test asserted http.server.request.duration with http.route.",
            "The report found http.server.request.duration with http.route.",
            "The unit test source recorded http.server.request.duration with http.route.",
            "The build produced http.server.request.duration with http.route.",
        )
        for observation in aspirational_or_disjoint:
            with self.subTest(observation=observation):
                self.assertFalse(
                    MODULE.exact_telemetry_item_is_referenced(observation, item)
                )
        self.assertTrue(
            MODULE.exact_telemetry_item_is_referenced(
                "The receiver observed http.server.request.duration with "
                "http.route=/checkout.",
                item,
            )
        )

    def test_exact_telemetry_reference_requires_signal_kind_and_authored_values(
        self,
    ) -> None:
        item = {
            "type": "metric",
            "name": "task.created",
            "attributes": ["http.route=/health"],
        }
        self.assertFalse(
            MODULE.exact_telemetry_item_is_referenced(
                "The generated trace contained span task.created with "
                "http.route=/health.",
                item,
            )
        )
        self.assertFalse(
            MODULE.exact_telemetry_item_is_referenced(
                "The receiver observed metric task.created with "
                "http.route=/wrong.",
                item,
            )
        )
        self.assertTrue(
            MODULE.exact_telemetry_item_is_referenced(
                "The receiver observed metric task.created with "
                "http.route=/health.",
                item,
            )
        )
        for observation in (
            "Metric task.created was emitted, and metric other.signal had "
            "http.route=/health.",
            "Metric task.created with http.route=/health was emitted. No metric "
            "task.created with http.route=/health was emitted.",
            "No data points were recorded for metric task.created with "
            "http.route=/health.",
            "The receiver recorded zero metric task.created with "
            "http.route=/health.",
            "Metric task.created with http.route=/health was emitted. It was "
            "actually a span.",
        ):
            with self.subTest(observation=observation):
                self.assertFalse(
                    MODULE.exact_telemetry_item_is_referenced(observation, item)
                )

    def test_exact_telemetry_reference_does_not_combine_contrasting_assertions(
        self,
    ) -> None:
        metric = {
            "type": "metric",
            "name": "task.created",
            "attributes": ["http.route=/health"],
        }
        rejected = (
            "Only a span task.created with http.route=/health, not a metric "
            "task.created with http.route=/health, was emitted.",
            "A span task.created with http.route=/health was emitted, whereas a "
            "metric task.created with http.route=/health was absent.",
            "A span task.created with http.route=/health was emitted, but a metric "
            "task.created with http.route=/health was not emitted.",
            "A span task.created with http.route=/health, rather than a metric "
            "task.created with http.route=/health, was emitted.",
            "The metric receiver observed a span task.created with "
            "http.route=/health.",
            "A span task.created with http.route=/health was emitted and the "
            "metric exporter accepted another signal.",
        )
        for observation in rejected:
            with self.subTest(observation=observation):
                self.assertFalse(
                    MODULE.exact_telemetry_item_is_referenced(observation, metric)
                )

        self.assertTrue(
            MODULE.exact_telemetry_item_is_referenced(
                "A metric task.created with http.route=/health was emitted, but a "
                "span task.created with http.route=/health was not emitted.",
                metric,
            )
        )

        span = {**metric, "type": "span"}
        self.assertFalse(
            MODULE.exact_telemetry_item_is_referenced(
                "Metric task.created with http.route=/health was absent; span "
                "task.created with http.route=/health was emitted.",
                span,
                reference_outcome="negative",
            )
        )
        self.assertTrue(
            MODULE.exact_telemetry_item_is_referenced(
                "Span task.created with http.route=/health was absent; metric "
                "task.created with http.route=/health was emitted.",
                span,
                reference_outcome="negative",
            )
        )

    def test_signal_kind_must_be_separate_from_name_and_embedded_kind_words(self) -> None:
        embedded_kind = {
            "type": "metric",
            "name": "application.log.count",
            "attributes": [],
        }
        self.assertFalse(
            MODULE.exact_telemetry_item_is_referenced(
                "application.log.count was emitted.", embedded_kind
            )
        )
        self.assertTrue(
            MODULE.exact_telemetry_item_is_referenced(
                "Metric application.log.count was emitted.", embedded_kind
            )
        )

        metric_word_in_name = {
            "type": "metric",
            "name": "custom.metric",
            "attributes": [],
        }
        self.assertFalse(
            MODULE.exact_telemetry_item_is_referenced(
                "custom.metric was emitted.", metric_word_in_name
            )
        )

    def test_exact_telemetry_reference_requires_result_appropriate_polarity(self) -> None:
        item = {
            "name": "GET /checkout",
            "attributes": ["http.route"],
        }
        negative_observations = (
            "The expected GET /checkout server span with http.route was absent.",
            "GET /checkout was emitted, but http.route is missing.",
            "GET /checkout and http.route could not be found.",
            "Could not find GET /checkout or http.route.",
            "Unable to observe GET /checkout with http.route.",
            "No evidence of GET /checkout or http.route was retained.",
            "GET /checkout with http.route yielded no data.",
            "GET /checkout with http.route was unavailable.",
        )
        for observation in negative_observations:
            with self.subTest(observation=observation):
                self.assertFalse(
                    MODULE.exact_telemetry_item_is_referenced(observation, item)
                )
                self.assertTrue(
                    MODULE.exact_telemetry_item_is_referenced(
                        observation, item, reference_outcome="negative"
                    )
                )

        positive = "The generated trace contained GET /checkout with http.route."
        self.assertTrue(MODULE.exact_telemetry_item_is_referenced(positive, item))
        self.assertFalse(
            MODULE.exact_telemetry_item_is_referenced(
                positive, item, reference_outcome="negative"
            )
        )

    def test_finding_badge_describes_partially_configured_scope(self) -> None:
        self.assertEqual(
            MODULE.human_finding_proof_status("not_configured", True),
            "implementation incomplete",
        )
        self.assertEqual(
            MODULE.human_item_proof_status(
                {"status": "not_configured", "proof_mode": "not_run"}
            ),
            "not implemented",
        )

    def test_overlay_rejects_ephemeral_absolute_artifact_paths(self) -> None:
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
        instrumentation_data = sample_instrumentation(report, digest, selection)
        instrumentation_data["findings"][0]["evidence"] = [  # type: ignore[index]
            "/private/tmp/runtime-result.json"
        ]
        with self.assertRaisesRegex(MODULE.ReportError, "ephemeral absolute path"):
            MODULE.normalize_instrumentation(instrumentation_data, report, selection)

        instrumentation_data = sample_instrumentation(report, digest)
        instrumentation_data["findings"][0]["evidence"] = [  # type: ignore[index]
            "Docker daemon is unavailable at unix:///tmp/docker.sock"
        ]
        normalized = MODULE.normalize_instrumentation(
            instrumentation_data, report, selection
        )
        self.assertIn("unix:///tmp/docker.sock", normalized["findings"][0]["evidence"][0])

    def test_genai_closure_is_authoritative_in_instrumentation_overlay(self) -> None:
        data = sample_report()
        data["meta"]["genai_ownership_detected"] = True  # type: ignore[index]
        data["evidence"][-1]["finding"] = "Yes"  # type: ignore[index]
        data["genai_readiness"] = [
            {
                "surface": "Checkout latency",
                "status": "partial",
                "evidence": "assistant.go:20",
                "required_signals": "GET /checkout span",
                "owner": "App-owned: assistant.go:20",
                "acceptance_criteria": "GET /checkout span is emitted with bounded attributes",
                "impact": "Operators cannot localize assistant latency.",
            }
        ]
        report = MODULE.normalize_audit_report(data)
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
        raw = sample_instrumentation(report, digest)
        with self.assertRaisesRegex(MODULE.ReportError, "exactly one row"):
            MODULE.normalize_instrumentation(raw, report, selection)

        raw["genai_closure"] = [
            {
                "surface": "Checkout latency",
                "required_signals": "GET /checkout span",
                "owner": "App-owned: assistant.go:20",
                "implemented_proven": ["Route-aware server span is implemented."],
                "tests": ["go test ./..."],
                "evidence": [".observe/evidence/checkout-test.txt"],
                "remaining_signals": ["Runtime route-span delivery proof"],
                "status": "partial",
            }
        ]
        first = MODULE.normalize_instrumentation(raw, report, selection)
        first_digest = MODULE.instrumentation_digest(first)

        changed = copy.deepcopy(raw)
        changed["genai_closure"][0]["implemented_proven"] = [  # type: ignore[index]
            "A different closure claim."
        ]
        second = MODULE.normalize_instrumentation(changed, report, selection)

        self.assertNotEqual(first_digest, MODULE.instrumentation_digest(second))
        self.assertEqual(first["genai_closure"][0]["status"], "partial")

    def test_instrumentation_html_aggregates_and_projects_partial_genai_closure(
        self,
    ) -> None:
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
        instrumentation["meta"]["result"] = "Partial"
        instrumentation["genai_closure"] = [
            {
                "surface": "Model identity",
                "required_signals": "model name and version",
                "owner": "assistant runtime team",
                "implemented_proven": ["Bounded model name is recorded."],
                "tests": ["Model-name unit test passed."],
                "evidence": [".observe/evidence/genai/model-name.json"],
                "remaining_signals": ["Runtime model-version proof"],
                "status": "partial",
            }
        ]
        verify = sample_verify(
            report,
            digest,
            MODULE.instrumentation_digest(instrumentation),
        )
        verify["meta"]["result"] = "Pass"
        finding = verify["findings"][0]
        finding["status"] = "working"
        finding["remaining"] = []
        finding["scenarios"][0]["status"] = "working"
        finding["item_results"][0].update(
            {
                "status": "working",
                "direct_assertion_passed": True,
                "observed_telemetry": [
                    "The generated trace contains span GET /checkout with "
                    "http.route."
                ],
                "product_validation": ["The local receiver accepted the span."],
            }
        )

        summary = MODULE.render_instrumentation_summary(
            selection, instrumentation, verify
        )
        rendered = MODULE.render_instrumentation_html(
            report, selection, instrumentation, verify
        )

        self.assertEqual(
            MODULE.aggregate_instrumentation_result(instrumentation, verify),
            "Partial",
        )
        self.assertIn("Overall result: Partial", summary)
        self.assertIn("Verification complete — GenAI closure remains", summary)
        self.assertNotIn("Instrumentation and verification complete", summary)
        self.assertIn("GenAI telemetry closure", rendered)
        self.assertIn("0 of 1 surface is closed", rendered)
        self.assertIn("Model identity", rendered)
        self.assertIn("Bounded model name is recorded.", rendered)
        self.assertIn("Runtime model-version proof", rendered)
        self.assertIn("Owner: assistant runtime team", rendered)

        instrumentation["meta"]["result"] = "Fail"
        instrumentation["genai_closure"][0]["status"] = "not_working"
        verify["meta"]["result"] = "Partial"
        failed_summary = MODULE.render_instrumentation_summary(
            selection, instrumentation, verify
        )
        self.assertIn(
            "Instrumentation failed — GenAI closure has a failed surface",
            failed_summary,
        )
        self.assertNotIn(
            "Verification incomplete — no observed failures", failed_summary
        )

    def test_aggregate_result_keeps_blocked_without_implementation_proof(self) -> None:
        instrumentation = {
            "meta": {"result": "Partial"},
            "findings": [
                {
                    "status": "working",
                    "tests": ["go test ./..."],
                    "evidence": ["main.go:42"],
                }
            ],
            "genai_closure": [],
        }
        verify = {"meta": {"result": "Blocked"}, "findings": []}

        self.assertEqual(
            MODULE.aggregate_instrumentation_result(instrumentation, verify),
            "Blocked",
        )
        instrumentation["findings"][0]["evidence"] = [
            ".observe/evidence/go-test.txt"
        ]
        self.assertEqual(
            MODULE.aggregate_instrumentation_result(instrumentation, verify),
            "Partial",
        )

        instrumentation["findings"][0].update(
            {
                "tests": ["go test ./... failed"],
                "evidence": [".observe/evidence/go-test.log"],
            }
        )
        self.assertEqual(
            MODULE.aggregate_instrumentation_result(instrumentation, verify),
            "Blocked",
        )
        instrumentation["findings"] = []
        instrumentation["genai_closure"] = [
            {
                "status": "partial",
                "implemented_proven": ["Provider span emitted."],
                "tests": ["not proven"],
                "evidence": [".observe/evidence/not-proven.log"],
            }
        ]
        self.assertEqual(
            MODULE.aggregate_instrumentation_result(instrumentation, verify),
            "Blocked",
        )

        instrumentation["findings"] = [
            {
                "status": "working",
                "tests": ["go test ./... passed"],
                "evidence": [".observe/evidence/http-failure.json"],
            }
        ]
        instrumentation["genai_closure"] = []
        self.assertEqual(
            MODULE.aggregate_instrumentation_result(instrumentation, verify),
            "Partial",
        )

        instrumentation["findings"] = []
        instrumentation["genai_closure"] = [
            {
                "status": "partial",
                "implemented_proven": ["span implemented"],
                "tests": ["collector configured"],
                "evidence": [".observe/evidence/config.json"],
            }
        ]
        self.assertEqual(
            MODULE.aggregate_instrumentation_result(instrumentation, verify),
            "Blocked",
        )

    def test_verify_result_and_failed_repairs_are_semantically_consistent(self) -> None:
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
        verify = sample_verify(report, digest, MODULE.instrumentation_digest(instrumentation))
        finding = verify["findings"][0]  # type: ignore[index]
        finding["status"] = "not_working"
        finding["scenarios"][0]["status"] = "not_working"
        finding["scenarios"][0]["observed_telemetry"] = [
            "The expected GET /checkout server span with http.route was absent."
        ]
        finding["item_results"][0]["status"] = "not_working"
        finding["item_results"][0]["observed_telemetry"] = [
            "The expected GET /checkout server span with http.route was absent."
        ]
        finding["remaining"] = ["Use $otel-instrument to repair the Tracer binding."]

        with self.assertRaisesRegex(MODULE.ReportError, "must be Fail"):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

        verify["meta"]["result"] = "Fail"  # type: ignore[index]
        finding["remaining"] = [
            "Use $otel-instrument to repair the Tracer binding, then rerun verification."
        ]
        with self.assertRaisesRegex(MODULE.ReportError, "repairs, not confirmation"):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

        finding["remaining"] = ["Use $otel-instrument to repair the Tracer binding."]
        verify["next_steps"] = ["Run $otel-instrument to repair the Tracer binding."]
        normalized = MODULE.normalize_verify(verify, report, selection, instrumentation)
        self.assertEqual(normalized["meta"]["result"], "Fail")

        verify = sample_verify(report, digest, MODULE.instrumentation_digest(instrumentation))
        verify["meta"]["result"] = "Fail"  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.ReportError, "requires at least one not_working"):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

    def test_unknown_verify_finding_fails_cleanly_before_proof_lookup(self) -> None:
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

        for scenario_status in ("working", "not_working"):
            with self.subTest(scenario_status=scenario_status):
                verify = sample_verify(
                    report,
                    digest,
                    MODULE.instrumentation_digest(instrumentation),
                )
                finding = verify["findings"][0]  # type: ignore[index]
                finding["id"] = "OTEL-999"
                scenario = finding["scenarios"][0]
                scenario["status"] = scenario_status
                scenario["observed_telemetry"] = [
                    "The expected GET /checkout server span with http.route "
                    + ("was emitted." if scenario_status == "working" else "was absent.")
                ]

                with self.assertRaisesRegex(
                    MODULE.ReportError,
                    r"verify\.findings\[0\]\.id OTEL-999 is not present in the bound audit",
                ):
                    MODULE.normalize_verify(
                        verify, report, selection, instrumentation
                    )

    def test_blocked_scenario_requires_structured_reader_context(self) -> None:
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
        verify = sample_verify(
            report, digest, MODULE.instrumentation_digest(instrumentation)
        )
        scenario = verify["findings"][0]["scenarios"][0]  # type: ignore[index]
        scenario.update(
            {
                "status": "blocked",
                "proof_mode": "not_run",
                "visibility": "not_proven",
                "blocking_reason": (
                    "Exact locked dependencies could not be restored because "
                    "Artifactory authentication expired."
                ),
                "unobserved_outcome": (
                    "Final metric delivery from the real process is not yet observed."
                ),
            }
        )

        normalized = MODULE.normalize_verify(
            verify, report, selection, instrumentation
        )
        normalized_scenario = normalized["findings"][0]["scenarios"][0]
        self.assertEqual(
            normalized_scenario["blocking_reason"],
            "Exact locked dependencies could not be restored because Artifactory authentication expired.",
        )
        self.assertEqual(
            normalized_scenario["unobserved_outcome"],
            "Final metric delivery from the real process is not yet observed.",
        )

        missing_reason = copy.deepcopy(verify)
        missing_reason["findings"][0]["scenarios"][0].pop("blocking_reason")
        with self.assertRaisesRegex(MODULE.ReportError, "requires blocking_reason"):
            MODULE.normalize_verify(
                missing_reason, report, selection, instrumentation
            )

        imperative_reason = copy.deepcopy(verify)
        imperative_reason["findings"][0]["scenarios"][0]["blocking_reason"] = (
            "Restore the exact locked dependencies."
        )
        with self.assertRaisesRegex(MODULE.ReportError, "cause, not an imperative"):
            MODULE.normalize_verify(
                imperative_reason, report, selection, instrumentation
            )

        stale_context = sample_verify(
            report, digest, MODULE.instrumentation_digest(instrumentation)
        )
        stale_context["findings"][0]["scenarios"][0]["blocking_reason"] = (  # type: ignore[index]
            "Artifactory authentication expired."
        )
        stale_context["findings"][0]["scenarios"][0]["unobserved_outcome"] = (  # type: ignore[index]
            "Runtime delivery is not yet observed."
        )
        with self.assertRaisesRegex(MODULE.ReportError, "valid only when status is blocked"):
            MODULE.normalize_verify(
                stale_context, report, selection, instrumentation
            )

    def test_verify_result_is_derived_from_scenario_and_item_execution(self) -> None:
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
        instrumentation_sha256 = MODULE.instrumentation_digest(instrumentation)

        no_proof = sample_verify(report, digest, instrumentation_sha256)
        no_proof["findings"][0]["scenarios"][0]["proof_mode"] = "not_run"  # type: ignore[index]
        no_proof["findings"][0]["scenarios"][0]["visibility"] = "not_proven"  # type: ignore[index]
        no_proof["findings"][0]["item_results"][0]["proof_mode"] = "not_run"  # type: ignore[index]
        no_proof["findings"][0]["item_results"][0]["visibility"] = "not_proven"  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.ReportError, "must be Not run"):
            MODULE.normalize_verify(no_proof, report, selection, instrumentation)

        no_proof["meta"]["result"] = "Not run"  # type: ignore[index]
        MODULE.normalize_verify(no_proof, report, selection, instrumentation)

        item_only = copy.deepcopy(no_proof)
        item_only["findings"][0]["item_results"][0]["proof_mode"] = "unit"  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.ReportError, "must be Partial"):
            MODULE.normalize_verify(item_only, report, selection, instrumentation)

        mixed_blocked = copy.deepcopy(item_only)
        mixed_blocked["meta"]["result"] = "Blocked"  # type: ignore[index]
        scenario = mixed_blocked["findings"][0]["scenarios"][0]  # type: ignore[index]
        scenario.update(
            {
                "status": "blocked",
                "blocking_reason": "Artifactory authentication expired.",
                "unobserved_outcome": "Runtime telemetry was not observed.",
            }
        )
        with self.assertRaisesRegex(MODULE.ReportError, "must be Partial"):
            MODULE.normalize_verify(
                mixed_blocked, report, selection, instrumentation
            )

        blocked = copy.deepcopy(no_proof)
        blocked["meta"]["result"] = "Blocked"  # type: ignore[index]
        blocked_scenario = blocked["findings"][0]["scenarios"][0]  # type: ignore[index]
        blocked_scenario.update(
            {
                "status": "blocked",
                "blocking_reason": "Artifactory authentication expired.",
                "unobserved_outcome": "Runtime telemetry was not observed.",
            }
        )
        MODULE.normalize_verify(blocked, report, selection, instrumentation)

    def test_proven_item_can_coexist_with_incomplete_scenario_coverage(self) -> None:
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
        verify = sample_verify(
            report, digest, MODULE.instrumentation_digest(instrumentation)
        )
        finding = verify["findings"][0]  # type: ignore[index]
        finding["scenarios"][0]["observed_telemetry"] = [
            "The focused check observed span GET /checkout with http.route."
        ]
        finding["item_results"][0]["status"] = "working"
        finding["item_results"][0]["direct_assertion_passed"] = True
        finding["item_results"][0]["observed_telemetry"] = [
            "The focused check observed span GET /checkout with http.route."
        ]

        normalized = MODULE.normalize_verify(
            verify, report, selection, instrumentation
        )

        self.assertEqual(normalized["meta"]["result"], "Partial")
        self.assertEqual(normalized["findings"][0]["status"], "not_proven")
        self.assertEqual(
            normalized["findings"][0]["scenarios"][0]["status"], "not_proven"
        )
        self.assertEqual(
            normalized["findings"][0]["item_results"][0]["status"], "working"
        )

    def test_item_direct_assertion_cannot_be_downgraded_by_finding_coverage(self) -> None:
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
        verify = sample_verify(
            report, digest, MODULE.instrumentation_digest(instrumentation)
        )
        item = verify["findings"][0]["item_results"][0]  # type: ignore[index]
        item.update(
            {
                "direct_assertion_passed": True,
                "proof_mode": "full_runtime",
                "visibility": "otlp_accepted",
                "evidence": [".observe/evidence/runtime/trace.json"],
                "observed_telemetry": [
                    "The bounded trace has one GET /checkout SERVER span with "
                    "http.route and no manual HttpRequest span."
                ],
                "product_validation": [
                    "The local OTLP trace directly satisfies the item contract."
                ],
            }
        )

        with self.assertRaisesRegex(
            MODULE.ReportError, "finding or scenario coverage cannot downgrade"
        ):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

        item["status"] = "working"
        normalized = MODULE.normalize_verify(
            verify, report, selection, instrumentation
        )
        self.assertEqual(
            normalized["findings"][0]["item_results"][0]["status"], "working"
        )

        item["direct_assertion_passed"] = False
        with self.assertRaisesRegex(
            MODULE.ReportError, "direct_assertion_passed must be true exactly"
        ):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

    def test_working_item_rejects_unbound_zero_and_contradictory_observations(
        self,
    ) -> None:
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
        observations = (
            "Span GET /checkout was emitted, and span payment.authorize had http.route.",
            "Span GET /checkout with http.route was emitted. No span GET /checkout "
            "with http.route was emitted.",
            "No data points were recorded for span GET /checkout with http.route.",
        )
        for observation in observations:
            with self.subTest(observation=observation):
                verify = sample_verify(
                    report, digest, MODULE.instrumentation_digest(instrumentation)
                )
                item = verify["findings"][0]["item_results"][0]  # type: ignore[index]
                item.update(
                    {
                        "status": "working",
                        "direct_assertion_passed": True,
                        "proof_mode": "full_runtime",
                        "visibility": "otlp_accepted",
                        "observed_telemetry": [observation],
                        "product_validation": ["The local receiver check ran."],
                    }
                )
                with self.assertRaisesRegex(
                    MODULE.ReportError, "positive proof semantics"
                ):
                    MODULE.normalize_verify(
                        verify, report, selection, instrumentation
                    )

    def test_item_proof_must_use_its_instrumentation_scenario_mapping(self) -> None:
        data = sample_report()
        second = copy.deepcopy(data["verification"]["scenarios"][0])  # type: ignore[index]
        second["id"] = "http.checkout.failure"
        data["verification"]["scenarios"].append(second)  # type: ignore[index]
        data["findings"][0]["verification_scenarios"] = [  # type: ignore[index]
            "http.checkout.success",
            "http.checkout.failure",
        ]
        report = MODULE.normalize_audit_report(data)
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
        verify = sample_verify(
            report, digest, MODULE.instrumentation_digest(instrumentation)
        )
        second_result = copy.deepcopy(verify["findings"][0]["scenarios"][0])  # type: ignore[index]
        second_result["id"] = "http.checkout.failure"
        verify["findings"][0]["scenarios"].append(second_result)  # type: ignore[index]
        verify["findings"][0]["item_results"][0]["scenarios"] = [  # type: ignore[index]
            "http.checkout.failure"
        ]

        with self.assertRaisesRegex(MODULE.ReportError, "not mapped to the telemetry item"):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

    def test_working_removed_item_requires_absence_and_replacement_proof(self) -> None:
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
        instrumentation_data = sample_instrumentation(report, digest)
        telemetry_item = instrumentation_data["findings"][0]["telemetry_changes"][0]  # type: ignore[index]
        telemetry_item.update(
            {
                "change_kind": "removed",
                "name": "HttpRequest",
                "added_attributes": [],
                "product_view": "One canonical route-named SERVER span",
                "follow_up_actions": ["Inspect the canonical route trace."],
            }
        )
        instrumentation = MODULE.normalize_instrumentation(
            instrumentation_data, report, selection
        )
        verify = sample_verify(
            report, digest, MODULE.instrumentation_digest(instrumentation)
        )
        item = verify["findings"][0]["item_results"][0]  # type: ignore[index]
        item.update(
            {
                "status": "working",
                "direct_assertion_passed": True,
                "proof_mode": "full_runtime",
                "visibility": "otlp_accepted",
                "observed_telemetry": [
                    "The generated trace has no HttpRequest span and one GET /checkout SERVER span."
                ],
                "product_validation": ["The local receiver captured the generated trace."],
            }
        )

        with self.assertRaisesRegex(MODULE.ReportError, "structured proof"):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

        item["removal_proof"] = {
            "removed_signal": "HttpRequest",
            "replacement_signal": "GET /checkout",
            "absence_assertion_passed": True,
            "replacement_assertion_passed": False,
        }
        with self.assertRaisesRegex(MODULE.ReportError, "structured proof"):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

        item["removal_proof"]["replacement_assertion_passed"] = True
        normalized = MODULE.normalize_verify(
            verify, report, selection, instrumentation
        )
        self.assertTrue(
            normalized["findings"][0]["item_results"][0]["removal_proof"][
                "replacement_assertion_passed"
            ]
        )

        wrong_kind = copy.deepcopy(verify)
        wrong_kind_item = wrong_kind["findings"][0]["item_results"][0]  # type: ignore[index]
        wrong_kind_item["observed_telemetry"] = [
            "Span HttpRequest was absent. Metric GET /checkout was emitted."
        ]
        with self.assertRaisesRegex(MODULE.ReportError, "replacement proof"):
            MODULE.normalize_verify(
                wrong_kind, report, selection, instrumentation
            )

        instrumentation_with_attribute_data = copy.deepcopy(instrumentation_data)
        instrumentation_with_attribute_data["findings"][0]["telemetry_changes"][0][  # type: ignore[index]
            "added_attributes"
        ] = ["http.route"]
        instrumentation_with_attribute_data["findings"][0]["telemetry_changes"][0][  # type: ignore[index]
            "follow_up_actions"
        ] = ["Filter canonical route traces by http.route."]
        instrumentation_with_attribute = MODULE.normalize_instrumentation(
            instrumentation_with_attribute_data, report, selection
        )
        attribute_only = sample_verify(
            report,
            digest,
            MODULE.instrumentation_digest(instrumentation_with_attribute),
        )
        attribute_only_item = attribute_only["findings"][0]["item_results"][0]  # type: ignore[index]
        attribute_only_item.update(
            {
                "status": "working",
                "direct_assertion_passed": True,
                "proof_mode": "full_runtime",
                "visibility": "otlp_accepted",
                "observed_telemetry": [
                    "Span HttpRequest was emitted without http.route. Span GET "
                    "/checkout was emitted."
                ],
                "product_validation": ["The local receiver captured telemetry."],
                "removal_proof": {
                    "removed_signal": "HttpRequest",
                    "replacement_signal": "GET /checkout",
                    "absence_assertion_passed": True,
                    "replacement_assertion_passed": True,
                },
            }
        )
        with self.assertRaisesRegex(MODULE.ReportError, "negative proof semantics"):
            MODULE.normalize_verify(
                attribute_only,
                report,
                selection,
                instrumentation_with_attribute,
            )

        contradictory = copy.deepcopy(verify)
        contradictory_item = contradictory["findings"][0]["item_results"][0]  # type: ignore[index]
        contradictory_item["observed_telemetry"] = [
            "The generated trace emitted HttpRequest and one GET /checkout SERVER span."
        ]
        with self.assertRaisesRegex(MODULE.ReportError, "negative proof semantics"):
            MODULE.normalize_verify(
                contradictory, report, selection, instrumentation
            )

        missing_replacement = copy.deepcopy(verify)
        missing_replacement_item = missing_replacement["findings"][0]["item_results"][0]  # type: ignore[index]
        missing_replacement_item["observed_telemetry"] = [
            "The generated trace contained no HttpRequest span."
        ]
        with self.assertRaisesRegex(MODULE.ReportError, "replacement proof"):
            MODULE.normalize_verify(
                missing_replacement, report, selection, instrumentation
            )

    def test_contextual_item_evidence_can_remain_not_proven(self) -> None:
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
        verify = sample_verify(
            report, digest, MODULE.instrumentation_digest(instrumentation)
        )
        item = verify["findings"][0]["item_results"][0]  # type: ignore[index]
        item.update(
            {
                "direct_assertion_passed": False,
                "proof_mode": "app_test",
                "visibility": "otlp_accepted",
                "evidence": [".observe/evidence/runtime/receiver-stats.json"],
                "observed_telemetry": [
                    "Aggregate receiver counts increased, but the exact item was not asserted."
                ],
                "product_validation": [
                    "The exact telemetry item remains unobserved."
                ],
            }
        )

        normalized = MODULE.normalize_verify(
            verify, report, selection, instrumentation
        )
        self.assertEqual(
            normalized["findings"][0]["item_results"][0]["status"],
            "not_proven",
        )

    def test_item_direct_assertion_flag_is_required_boolean(self) -> None:
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
        verify = sample_verify(
            report, digest, MODULE.instrumentation_digest(instrumentation)
        )
        item = verify["findings"][0]["item_results"][0]  # type: ignore[index]
        del item["direct_assertion_passed"]
        with self.assertRaisesRegex(MODULE.ReportError, "must be a boolean"):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

        item["direct_assertion_passed"] = "true"
        with self.assertRaisesRegex(MODULE.ReportError, "must be a boolean"):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

    def test_static_or_contract_only_cannot_prove_item_result(self) -> None:
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
        verify = sample_verify(
            report, digest, MODULE.instrumentation_digest(instrumentation)
        )
        item = verify["findings"][0]["item_results"][0]  # type: ignore[index]
        item.update(
            {
                "status": "working",
                "direct_assertion_passed": True,
                "observed_telemetry": [
                    "The focused check observed span GET /checkout with http.route."
                ],
            }
        )

        for proof_mode in ("static", "contract_only"):
            with self.subTest(proof_mode=proof_mode):
                item["proof_mode"] = proof_mode
                with self.assertRaisesRegex(
                    MODULE.ReportError, "direct unit/application/runtime proof mode"
                ):
                    MODULE.normalize_verify(verify, report, selection, instrumentation)

    def test_telemetry_change_requires_concrete_correction_text(self) -> None:
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
        instrumentation = sample_instrumentation(report, digest)
        instrumentation["findings"][0]["telemetry_changes"][0]["change"] = (  # type: ignore[index]
            "Modified GET /checkout for the selected bounded telemetry contract."
        )

        with self.assertRaisesRegex(MODULE.ReportError, "concrete code/config behavior"):
            MODULE.normalize_instrumentation(instrumentation, report, selection)

    def test_instrumentation_result_rollup_is_bidirectional(self) -> None:
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
        instrumentation = sample_instrumentation(report, digest)
        instrumentation["meta"]["result"] = "Pass"  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.ReportError, "Pass requires every selected"):
            MODULE.normalize_instrumentation(instrumentation, report, selection)

        instrumentation = sample_instrumentation(report, digest)
        instrumentation["findings"][0]["status"] = "working"  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.ReportError, "must be Pass"):
            MODULE.normalize_instrumentation(instrumentation, report, selection)

    def test_verify_is_bound_to_exact_instrumentation_overlay(self) -> None:
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
        verify = sample_verify(report, digest, MODULE.instrumentation_digest(instrumentation))
        MODULE.normalize_verify(verify, report, selection, instrumentation)

        unbound = copy.deepcopy(verify)
        unbound.pop("instrumentation_sha256")
        with self.assertRaisesRegex(MODULE.ReportError, "is required to bind proof"):
            MODULE.normalize_verify(unbound, report, selection, instrumentation)

        changed = sample_instrumentation(report, digest)
        changed["findings"][0]["telemetry_changes"][0]["change"] = (  # type: ignore[index]
            "Wrapped the server handler and closed the span on cancellation."
        )
        changed_instrumentation = MODULE.normalize_instrumentation(
            changed, report, selection
        )
        with self.assertRaisesRegex(MODULE.ReportError, "does not match instrumentation"):
            MODULE.normalize_verify(
                verify, report, selection, changed_instrumentation
            )

    def test_verify_rejects_otlp_delivery_that_contradicts_product_view(self) -> None:
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
        raw_instrumentation = sample_instrumentation(report, digest)
        raw_instrumentation["findings"][0]["telemetry_changes"][0]["product_view"] = (  # type: ignore[index]
            "Trace-correlated search; no OTLP log pipeline claimed."
        )
        instrumentation = MODULE.normalize_instrumentation(
            raw_instrumentation, report, selection
        )
        verify = sample_verify(
            report, digest, MODULE.instrumentation_digest(instrumentation)
        )
        item = verify["findings"][0]["item_results"][0]  # type: ignore[index]
        item["visibility"] = "otlp_accepted"
        item["observed_telemetry"] = ["The receiver saved the expected log."]
        item["product_validation"] = ["Local OTLP receipt was saved."]

        with self.assertRaisesRegex(MODULE.ReportError, "denies an OTLP delivery path"):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

    def test_reader_prose_hides_schema_enum_tokens(self) -> None:
        self.assertEqual(
            MODULE.reader_prose(
                "The item remains not_proven; no not_working or not_configured claim."
            ),
            "The item remains not proven; no not working or not configured claim.",
        )
        trace_id = "0123456789abcdef0123456789abcdef"
        span_id = "0123456789abcdef"
        self.assertEqual(
            MODULE.reader_prose(
                f"Bounded trace {trace_id} contains one SERVER span ({span_id})."
            ),
            "The generated trace contains one SERVER span.",
        )
        self.assertEqual(
            MODULE.reader_prose(f"Live trace {trace_id} reached the receiver."),
            "The generated trace reached the receiver.",
        )
        self.assertEqual(
            MODULE.reader_prose(
                f"The log has traceId={trace_id} and spanId={span_id}, matching the span."
            ),
            "The log has the generated trace context, matching the span.",
        )
        redacted = MODULE.reader_prose(
            f"trace_id={trace_id}; span-id={span_id}; evidence/trace_{trace_id}.json"
        )
        self.assertNotIn(trace_id, redacted)
        self.assertNotIn(span_id, redacted)
        self.assertIn("the generated trace", redacted)
        self.assertIn("the generated span", redacted)
        self.assertIn("trace_generated-trace.json", redacted)

    def test_verify_rejects_unevidenced_delivery_and_contradictory_next_step(self) -> None:
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
        verify = sample_verify(report, digest, MODULE.instrumentation_digest(instrumentation))
        verify["findings"][0]["item_results"][0]["visibility"] = "otlp_accepted"  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.ReportError, "otlp_accepted requires"):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

        verify = sample_verify(report, digest, MODULE.instrumentation_digest(instrumentation))
        verify["next_steps"] = ["No further action is required."]
        with self.assertRaisesRegex(MODULE.ReportError, "remain unresolved"):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

    def test_failed_instrumentation_child_is_intermediate_only(self) -> None:
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
        verify = sample_verify(report, digest, MODULE.instrumentation_digest(instrumentation))
        verify["instrumentation_sha256"] = MODULE.instrumentation_digest(instrumentation)
        verify["meta"].update(  # type: ignore[union-attr]
            {
                "result": "Fail",
                "workflow_mode": "instrumentation_child",
                "lifecycle": "final",
            }
        )
        finding = verify["findings"][0]  # type: ignore[index]
        finding["status"] = "not_working"
        finding["scenarios"][0].update(
            {
                "status": "not_working",
                "observed_telemetry": [
                    "The GET /checkout server span with http.route was absent."
                ],
            }
        )
        finding["item_results"][0].update(
            {
                "status": "not_working",
                "observed_telemetry": [
                    "The GET /checkout server span with http.route was absent."
                ],
            }
        )
        finding["remaining"] = ["Repair the server span wiring."]
        verify["next_steps"] = ["Repair the server span wiring."]

        with self.assertRaisesRegex(MODULE.ReportError, "must be intermediate"):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

        verify["meta"]["lifecycle"] = "intermediate"  # type: ignore[index]
        normalized = MODULE.normalize_verify(
            verify, report, selection, instrumentation
        )
        self.assertEqual(normalized["meta"]["lifecycle"], "intermediate")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit_path = root / "otel-audit.json"
            selection_path = root / "otel-selection.json"
            instrumentation_path = root / "otel-instrumentation.json"
            verify_path = root / "otel-verify.json"
            audit_path.write_text(json.dumps(sample_report()), encoding="utf-8")
            selection_path.write_text(json.dumps(selection), encoding="utf-8")
            instrumentation_path.write_text(
                json.dumps(instrumentation), encoding="utf-8"
            )
            verify_path.write_text(json.dumps(verify), encoding="utf-8")
            gate = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "instrumentation-final-gate",
                    str(audit_path),
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
            self.assertEqual(gate.returncode, 2)
            self.assertIn("REPAIR REQUIRED", gate.stdout)

    def test_stopped_failed_child_validates_and_renders_external_boundary(self) -> None:
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
        raw_instrumentation = sample_instrumentation(report, digest, selection)
        raw_instrumentation["meta"]["result"] = "Fail"  # type: ignore[index]
        instrumentation_finding = raw_instrumentation["findings"][0]  # type: ignore[index]
        instrumentation_finding["status"] = "not_working"
        instrumentation = MODULE.normalize_instrumentation(
            raw_instrumentation, report, selection
        )
        verify = sample_verify(
            report, digest, MODULE.instrumentation_digest(instrumentation)
        )
        verify["meta"].update(  # type: ignore[union-attr]
            {
                "result": "Fail",
                "workflow_mode": "instrumentation_child",
                "lifecycle": "intermediate",
            }
        )
        finding = verify["findings"][0]  # type: ignore[index]
        finding["status"] = "not_working"
        finding["scenarios"][0].update(
            {
                "status": "not_working",
                "observed_telemetry": [
                    "The GET /checkout server span with http.route was absent."
                ],
            }
        )
        finding["item_results"][0].update(
            {
                "status": "not_working",
                "observed_telemetry": [
                    "The GET /checkout server span with http.route was absent."
                ],
            }
        )
        finding["remaining"] = ["Repair the server span wiring."]
        verify["next_steps"] = ["Repair the server span wiring."]
        external_action = (
            "Renew the private module registry credential and restore the exact "
            "locked dependencies."
        )
        verify["stop_boundaries"] = [
            {
                "finding_ids": ["OTEL-001"],
                "kind": "external_prerequisite",
                "reason": (
                    "The private module registry rejected the locked dependency "
                    "restore because its repository credential had expired."
                ),
                "required_action": external_action,
                "evidence": [
                    ".observe/evidence/run/dependency-restore.log"
                ],
            }
        ]

        non_failed_instrumentation = MODULE.normalize_instrumentation(
            sample_instrumentation(report, digest, selection), report, selection
        )
        result_mismatch = copy.deepcopy(verify)
        result_mismatch["instrumentation_sha256"] = (
            MODULE.instrumentation_digest(non_failed_instrumentation)
        )
        with self.assertRaisesRegex(
            MODULE.ReportError,
            r"bound instrumentation meta\.result to be Fail",
        ):
            MODULE.normalize_verify(
                result_mismatch, report, selection, non_failed_instrumentation
            )

        status_mismatch_instrumentation = copy.deepcopy(instrumentation)
        status_mismatch_instrumentation["findings"][0]["status"] = "not_proven"
        status_mismatch = copy.deepcopy(verify)
        status_mismatch["instrumentation_sha256"] = MODULE.instrumentation_digest(
            status_mismatch_instrumentation
        )
        with self.assertRaisesRegex(
            MODULE.ReportError,
            r"instrumentation findings with status not_working",
        ):
            MODULE.normalize_verify(
                status_mismatch,
                report,
                selection,
                status_mismatch_instrumentation,
            )

        duplicate_action = (
            "RENEW the private module-registry credential, and restore the exact "
            "locked dependencies!"
        )
        duplicated_remaining = copy.deepcopy(verify)
        duplicated_remaining["findings"][0]["remaining"] = [duplicate_action]
        with self.assertRaisesRegex(
            MODULE.ReportError,
            r"required_action must remain only in stop_boundaries",
        ):
            MODULE.normalize_verify(
                duplicated_remaining, report, selection, instrumentation
            )

        duplicated_next_step = copy.deepcopy(verify)
        duplicated_next_step["next_steps"] = [duplicate_action]
        with self.assertRaisesRegex(
            MODULE.ReportError,
            r"required_action must remain only in stop_boundaries",
        ):
            MODULE.normalize_verify(
                duplicated_next_step, report, selection, instrumentation
            )

        shortened_external_action = "Configure the private module registry credential."
        shortened_remaining = copy.deepcopy(verify)
        shortened_remaining["stop_boundaries"][0]["required_action"] = (
            "Configure the private module registry credential and restore the "
            "locked dependencies."
        )
        shortened_remaining["findings"][0]["remaining"] = [
            shortened_external_action
        ]
        with self.assertRaisesRegex(
            MODULE.ReportError,
            r"required_action must remain only in stop_boundaries",
        ):
            MODULE.normalize_verify(
                shortened_remaining, report, selection, instrumentation
            )

        shortened_next_step = copy.deepcopy(shortened_remaining)
        shortened_next_step["findings"][0]["remaining"] = [
            "Repair the server span wiring."
        ]
        shortened_next_step["next_steps"] = [shortened_external_action]
        with self.assertRaisesRegex(
            MODULE.ReportError,
            r"required_action must remain only in stop_boundaries",
        ):
            MODULE.normalize_verify(
                shortened_next_step, report, selection, instrumentation
            )

        normalized = MODULE.normalize_verify(
            verify, report, selection, instrumentation
        )
        self.assertEqual(
            normalized["stop_boundaries"], verify["stop_boundaries"]
        )
        self.assertEqual(
            normalized["findings"][0]["remaining"],
            ["Repair the server span wiring."],
        )
        self.assertEqual(
            normalized["next_steps"], ["Repair the server span wiring."]
        )
        self.assertIsNone(
            MODULE.failed_verification_repair_action(external_action)
        )

        wrong_workflow = copy.deepcopy(verify)
        wrong_workflow["meta"]["workflow_mode"] = "standalone"  # type: ignore[index]
        with self.assertRaisesRegex(
            MODULE.ReportError,
            "stop_boundaries is allowed only for an instrumentation_child",
        ):
            MODULE.normalize_verify(
                wrong_workflow, report, selection, instrumentation
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit_path = root / "otel-audit.json"
            selection_path = root / "otel-selection.json"
            instrumentation_path = root / "otel-instrumentation.json"
            verify_path = root / "otel-verify.json"
            html_path = root / "otel-instrumentation.html"
            audit_path.write_text(json.dumps(report), encoding="utf-8")
            selection_path.write_text(json.dumps(selection), encoding="utf-8")
            instrumentation_path.write_text(
                json.dumps(instrumentation), encoding="utf-8"
            )
            verify_path.write_text(json.dumps(verify), encoding="utf-8")

            flow = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "validate-flow",
                    str(audit_path),
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
            self.assertEqual(flow.returncode, 0, flow.stderr)
            self.assertIn(
                "PASS: audit -> selection -> instrumentation -> verify",
                flow.stdout,
            )

            render = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "render-instrumentation-html",
                    str(audit_path),
                    "-o",
                    str(html_path),
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
            self.assertEqual(render.returncode, 0, render.stderr)
            html = html_path.read_text(encoding="utf-8")
            self.assertIn("Why the repair loop stopped", html)
            self.assertIn("External prerequisite", html)
            self.assertIn(external_action, html)
            self.assertIn(
                "Required action outside the instrumentation repair scope", html
            )
            self.assertIn("dependency-restore.log", html)

            gate = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "instrumentation-final-gate",
                    str(audit_path),
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
            self.assertEqual(gate.returncode, 2)
            self.assertIn("REPAIR REQUIRED", gate.stdout)

    def test_parses_component_flow_lanes_and_markers(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())
        lanes = MODULE.component_flow_lanes(report["signal_flow"]["component_flow_map"])

        self.assertEqual([lane["title"] for lane in lanes], ["Request path", "Dependency path"])
        self.assertEqual(lanes[0]["chains"][0][0]["label"], "main.go")
        self.assertTrue(lanes[0]["chains"][0][0]["source_covered"])
        self.assertEqual(lanes[0]["chains"][0][1]["gaps"], ["Checkout latency"])

        model = MODULE.component_flow_model(report["signal_flow"]["component_flow_map"])
        self.assertEqual(
            [component["label"] for component in model["components"]],
            ["main.go", "checkout", "payment provider"],
        )
        checkout_component = next(
            component for component in model["components"] if component["label"] == "checkout"
        )
        self.assertEqual(checkout_component["lanes"], ["Request path", "Dependency path"])
        self.assertEqual(
            model["lanes"],
            [
                {"title": "Request path", "edges": [{"source": "main.go", "target": "checkout"}]},
                {
                    "title": "Dependency path",
                    "edges": [{"source": "checkout", "target": "payment provider"}],
                },
            ],
        )

        groups = MODULE.component_coverage_groups(report)
        checkout = next(group for group in groups if group["label"] == "checkout")
        self.assertEqual(checkout["lanes"], ["Request path", "Dependency path"])
        self.assertEqual([row["id"] for row in checkout["findings"]], ["OTEL-001"])
        self.assertEqual(checkout["priority_counts"]["required"], 1)
        self.assertEqual(checkout["signals"], ["span"])

    def test_source_reference_parts_are_safe_and_preserve_notes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = root / "checkout"
            output = service / ".observe"
            source = service / "internal" / "checkout.go"
            output.mkdir(parents=True)
            source.parent.mkdir(parents=True)
            source.write_text("package checkout\n", encoding="utf-8")
            outside = root / "outside.go"
            outside.write_text("package outside\n", encoding="utf-8")
            (service / "escape.go").symlink_to(outside)

            citation = "internal/checkout.go:42-56 (pre-existing test intent; not executed)"
            parts = MODULE.source_reference_parts(citation, service, output)

            self.assertEqual(parts[0], {"text": "internal/checkout.go:42-56", "href": "../internal/checkout.go#L42-L56"})
            self.assertEqual(parts[1], {"text": " (pre-existing test intent; not executed)"})
            rendered = MODULE.source_reference_html(citation, {citation: parts})
            self.assertIn('href="../internal/checkout.go#L42-L56"', rendered)
            self.assertIn("</a> (pre-existing test intent; not executed)", rendered)

            malicious = "internal/checkout.go:42 (<img src=x onerror=alert(1)>)"
            malicious_parts = MODULE.source_reference_parts(malicious, service, output)
            malicious_html = MODULE.source_reference_html(malicious, {malicious: malicious_parts})
            self.assertIn("&lt;img src=x onerror=alert(1)&gt;", malicious_html)
            self.assertNotIn("<img", malicious_html)
            trace_id = "0123456789abcdef0123456789abcdef"
            evidence = output / "evidence" / f"trace_{trace_id}.json"
            evidence.parent.mkdir()
            evidence.write_text("{}\n", encoding="utf-8")
            evidence_citation = f".observe/evidence/trace_{trace_id}.json"
            evidence_parts = MODULE.source_reference_parts(
                evidence_citation, service, output
            )
            evidence_html = MODULE.source_reference_html(
                evidence_citation, {evidence_citation: evidence_parts}
            )
            self.assertNotIn(trace_id, re.sub(r'href="[^"]+"', "", evidence_html))
            self.assertIn("trace_generated-trace.json", evidence_html)
            self.assertIsNone(MODULE.source_reference_parts("../outside.go:1", service, output))
            self.assertIsNone(MODULE.source_reference_parts("escape.go:1", service, output))

    def test_normalizes_defaults_and_references(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())

        self.assertEqual(report["findings"][0]["severity"], "high")
        self.assertEqual(report["findings"][0]["status"], "proposed")
        self.assertEqual(report["findings"][1]["dependencies"], ["OTEL-001"])
        self.assertEqual(
            MODULE.audit_digest(report),
            "sha256:632beff003108a9aa5c199e8059612c6cfba9a7fdbbdebb0a3a79646b1ec34f9",
        )
        self.assertNotIn(
            "configuration_scope",
            report["findings"][0]["expected_telemetry"][0],
        )

        legacy = sample_report()
        legacy["findings"][0].pop("product_outcome")  # type: ignore[index]
        normalized_legacy = MODULE.normalize_audit_report(legacy)
        self.assertEqual(
            normalized_legacy["findings"][0]["product_outcome"],
            "Trace waterfall and route filtering",
        )

    def test_requires_supported_structured_otel_concerns(self) -> None:
        missing = sample_report()
        missing["findings"][0].pop("otel_concerns")  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.ReportError, "required by audit schema v2"):
            MODULE.normalize_audit_report(missing)

        invalid = sample_report()
        invalid["findings"][0]["otel_concerns"] = ["api-contract"]  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.ReportError, "unsupported OpenTelemetry concerns"):
            MODULE.normalize_audit_report(invalid)

        duplicate = sample_report()
        duplicate["findings"][0]["otel_concerns"] = [  # type: ignore[index]
            "signal-emission",
            "signal-emission",
        ]
        with self.assertRaisesRegex(MODULE.ReportError, "must not contain duplicates"):
            MODULE.normalize_audit_report(duplicate)

        canonical = sample_report()
        canonical["findings"][0]["otel_concerns"] = [  # type: ignore[index]
            "semantic-attributes",
            "signal-emission",
        ]
        normalized = MODULE.normalize_audit_report(canonical)
        self.assertEqual(
            normalized["findings"][0]["otel_concerns"],
            ["signal-emission", "semantic-attributes"],
        )

    def test_schema_v1_audit_digest_remains_backward_compatible(self) -> None:
        legacy = sample_report()
        legacy["schema_version"] = 1
        for finding in legacy["findings"]:  # type: ignore[index]
            finding.pop("otel_concerns")

        report = MODULE.normalize_audit_report(legacy)

        self.assertEqual(report["schema_version"], 1)
        self.assertNotIn("otel_concerns", report["findings"][0])
        self.assertEqual(
            MODULE.audit_digest(report),
            "sha256:40119f93a31537edfa0ac816b0efeaa8ec18f0aee4de839e37ef6de74a9d5440",
        )
        self.assertIn("Legacy v1 — unclassified", MODULE.render_markdown(report))
        html = MODULE.render_html(report, MODULE.empty_selection(report))
        self.assertNotIn(
            'REPORT.schema_version === 1 ? "Legacy v1 — unclassified"',
            html,
        )
        self.assertIn("function telemetryShapeFor(finding)", html)

    def test_schema_v1_preserves_authored_transitional_fields_and_digest(self) -> None:
        legacy = sample_report()
        legacy["schema_version"] = 1
        finding = legacy["findings"][0]  # type: ignore[index]
        finding["otel_concerns"] = ["semantic-attributes", "signal-emission"]
        make_manual_decision(finding)

        report = MODULE.normalize_audit_report(legacy)

        self.assertEqual(
            report["findings"][0]["otel_concerns"],
            ["semantic-attributes", "signal-emission"],
        )
        self.assertEqual(
            report["findings"][0]["decision_owner"],
            "service telemetry owner",
        )
        self.assertIn("GET /checkout", report["findings"][0]["decision_question"])
        self.assertEqual(
            MODULE.audit_digest(report),
            "sha256:b9d59feb352514214f7c076ebf4017d8575fd00e2215041f58e23613de35b748",
        )

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
                legacy = sample_report()
                legacy["schema_version"] = 1
                finding = legacy["findings"][1]  # type: ignore[index]
                if mode == "manual decision":
                    make_manual_decision(finding)
                else:
                    make_external_follow_up(finding)
                finding["dependencies"] = []

                report = MODULE.normalize_audit_report(legacy)

                self.assertEqual(report["findings"][1]["instrument_mode"], mode)
        self.assertIn("Legacy v1 — unclassified", MODULE.render_markdown(report))

    def test_otel_concerns_must_match_the_structured_closure(self) -> None:
        configuration_without_concern = sample_report()
        configuration_without_concern["findings"][0]["expected_telemetry"].append(  # type: ignore[index]
            {
                "type": "configuration",
                "configuration_scope": "otel-resource",
                "name": "service resource configuration",
                "attributes": ["service.name"],
                "product_view": "Canonical service identity",
            }
        )
        with self.assertRaisesRegex(MODULE.ReportError, "must include otel-configuration"):
            MODULE.normalize_audit_report(configuration_without_concern)

        concern_without_configuration = sample_report()
        concern_without_configuration["findings"][0]["otel_concerns"].append(  # type: ignore[index]
            "otel-configuration"
        )
        with self.assertRaisesRegex(MODULE.ReportError, "has no configuration item"):
            MODULE.normalize_audit_report(concern_without_configuration)

        correlation_without_log = sample_report()
        correlation_without_log["findings"][0]["otel_concerns"] = [  # type: ignore[index]
            "trace-log-correlation"
        ]
        with self.assertRaisesRegex(MODULE.ReportError, "requires a log outcome"):
            MODULE.normalize_audit_report(correlation_without_log)

    def test_rejects_unscoped_configuration_for_executable_finding(self) -> None:
        data = sample_report()
        data["findings"][0]["expected_telemetry"] = [  # type: ignore[index]
            {
                "type": "configuration",
                "name": "canonical API contract",
                "attributes": ["contract.owner", "drift.status"],
                "product_view": "CI contract-drift status",
            }
        ]

        with self.assertRaisesRegex(
            MODULE.ReportError,
            "configuration_scope is required for OpenTelemetry configuration",
        ):
            MODULE.normalize_audit_report(data)

    def test_rejects_unscoped_configuration_mixed_with_real_telemetry(self) -> None:
        data = sample_report()
        data["findings"][0]["expected_telemetry"].append(  # type: ignore[index]
            {
                "type": "configuration",
                "name": "service documentation links",
                "attributes": ["runbook", "chat"],
                "product_view": "Service documentation",
            }
        )

        with self.assertRaisesRegex(
            MODULE.ReportError,
            "configuration_scope is required for OpenTelemetry configuration",
        ):
            MODULE.normalize_audit_report(data)

    def test_rejects_non_otel_closure_work_with_decoy_telemetry_in_every_mode(self) -> None:
        for mode in ("default", "manual decision", "external follow-up"):
            with self.subTest(mode=mode):
                data = sample_report()
                finding = data["findings"][0]  # type: ignore[index]
                finding["expected_telemetry"].append(
                    {
                        "type": "configuration",
                        "configuration_scope": "otel-resource",
                        "name": "checkout service resource",
                        "attributes": ["service.name"],
                        "product_view": "Canonical service identity",
                    }
                )
                finding["otel_concerns"].append("otel-configuration")
                if mode == "manual decision":
                    make_manual_decision(finding)
                    finding["decision_question"] = (
                        "Which GET /checkout span profile should update the OpenAPI contract?"
                    )
                elif mode == "external follow-up":
                    make_external_follow_up(finding)
                    requirement = (
                        "Supply GET /checkout span proof and publish the OpenAPI contract."
                    )
                    finding["external_requirement"] = requirement
                    finding["required_fix"] = requirement
                else:
                    finding["required_fix"] = (
                        "Emit the GET /checkout span, update openapi.yaml, publish the "
                        "runbook, and enforce approval policy."
                    )

                with self.assertRaisesRegex(
                    MODULE.ReportError,
                    "prohibited non-OpenTelemetry",
                ):
                    MODULE.normalize_audit_report(data)

        route_signal = sample_report()
        route_signal["summary"] = ["The GET /openapi.json span lacks route attributes."]
        MODULE.normalize_audit_report(route_signal)

    def test_rejects_isolated_openapi_and_policy_work_in_every_mode(self) -> None:
        cases = (
            ("default", "Add the OpenAPI contract and emit the GET /checkout span."),
            (
                "manual decision",
                "Which GET /checkout span profile should add the OpenAPI contract?",
            ),
            (
                "external follow-up",
                "Provide the GET /checkout span proof and add the OpenAPI contract.",
            ),
            ("default", "Emit the GET /checkout span and enforce the approval policy."),
            (
                "manual decision",
                "Which approval policy should govern the GET /checkout span?",
            ),
            (
                "external follow-up",
                "Provide the GET /checkout span proof and enforce the approval policy.",
            ),
        )
        for mode, value in cases:
            with self.subTest(mode=mode, value=value):
                data = sample_report()
                finding = data["findings"][0]  # type: ignore[index]
                if mode == "manual decision":
                    make_manual_decision(finding)
                    finding["decision_question"] = value
                elif mode == "external follow-up":
                    make_external_follow_up(finding)
                    finding["external_requirement"] = value
                    finding["required_fix"] = value
                else:
                    finding["required_fix"] = value

                with self.assertRaisesRegex(
                    MODULE.ReportError,
                    "prohibited non-OpenTelemetry",
                ):
                    MODULE.normalize_audit_report(data)

    def test_external_requirement_must_equal_required_fix(self) -> None:
        data = sample_report()
        finding = data["findings"][0]  # type: ignore[index]
        make_external_follow_up(finding)
        finding["required_fix"] = (
            f"{finding['external_requirement']} Also add a service-owned checkout span."
        )

        with self.assertRaisesRegex(MODULE.ReportError, "exact external_requirement"):
            MODULE.normalize_audit_report(data)

    def test_allows_behavior_evidence_but_rejects_behavior_only_scenario_output(self) -> None:
        allowed = sample_report()
        finding = allowed["findings"][0]  # type: ignore[index]
        finding["evidence"].append("OPERATIONS.md requires OpenAPI and runbook updates.")
        finding["constraints"].append("Do not change retry, timeout, or cache policy.")
        finding["required_fix"] = (
            "Record retry outcome on the GET /checkout span attribute retry.result."
        )
        finding["expected_telemetry"][0]["attributes"].append("retry.result")
        MODULE.normalize_audit_report(allowed)

        rejected = sample_report()
        rejected["verification"]["scenarios"][0]["expected_signals"] = (  # type: ignore[index]
            "GET /checkout span and OpenAPI contract lint result"
        )
        with self.assertRaisesRegex(MODULE.ReportError, "prohibited non-OpenTelemetry"):
            MODULE.normalize_audit_report(rejected)

    def test_accepts_scoped_configuration_with_signal_outcome_for_executable_finding(self) -> None:
        scopes = (
            "otel-sdk",
            "otel-resource",
            "otel-exporter",
            "otel-sampling",
            "otel-propagation",
            "otel-instrumentation",
            "otel-collector",
        )
        self.assertEqual(MODULE.CONFIGURATION_SCOPES, set(scopes))
        for scope in scopes:
            with self.subTest(scope=scope):
                data = sample_report()
                finding = data["findings"][0]  # type: ignore[index]
                data["findings"] = [finding]
                data["signal_flow"]["component_flow_map"] = (  # type: ignore[index]
                    "checkout [GAP: OpenTelemetry runtime configuration]"
                )
                finding.update(
                    {
                        "title": "Configure the OpenTelemetry runtime and service resource",
                        "otel_concerns": ["signal-emission", "otel-configuration"],
                        "area": "OpenTelemetry runtime configuration",
                        "gap": "The selected OTel runtime configuration does not emit a canonical service resource.",
                        "impact": "Telemetry can be split across service identities.",
                        "product_outcome": "All emitted telemetry is queryable under one canonical service resource.",
                        "required_fix": "Configure the OTel runtime and emit the canonical service resource.",
                        "acceptance_criteria": [
                            "Runtime proof contains one canonical service resource."
                        ],
                        "follow_up_actions": [
                            "Verify the canonical resource in ObStudio before merge."
                        ],
                    }
                )
                data["findings"][0]["expected_telemetry"] = [  # type: ignore[index]
                    {
                        "type": "configuration",
                        "configuration_scope": scope,
                        "name": "OpenTelemetry runtime configuration",
                        "attributes": ["service.name"],
                        "product_view": "Telemetry runtime diagnostics",
                    },
                    {
                        "type": "resource",
                        "name": "checkout service resource",
                        "attributes": ["service.name"],
                        "product_view": "One queryable service identity",
                    },
                ]
                data["verification"]["scenarios"][0].update(  # type: ignore[index]
                    {
                        "trigger": "Start the checkout service with the selected OTel runtime",
                        "expected_signals": "checkout service resource",
                        "acceptance_criteria": "one canonical service resource is emitted",
                    }
                )

                report = MODULE.normalize_audit_report(data)

                self.assertEqual(
                    report["findings"][0]["expected_telemetry"][0]["configuration_scope"],
                    scope,
                )

    def test_rejects_scoped_configuration_without_signal_outcome(self) -> None:
        data = sample_report()
        data["findings"][0]["expected_telemetry"] = [  # type: ignore[index]
            {
                "type": "configuration",
                "configuration_scope": "otel-exporter",
                "name": "OTLP exporter configuration",
                "attributes": ["endpoint"],
                "product_view": "Exporter diagnostics",
            }
        ]

        with self.assertRaisesRegex(
            MODULE.ReportError,
            "scoped configuration alone is insufficient",
        ):
            MODULE.normalize_audit_report(data)

    def test_rejects_invalid_or_misplaced_configuration_scope(self) -> None:
        invalid = sample_report()
        invalid["findings"][0]["expected_telemetry"] = [  # type: ignore[index]
            {
                "type": "configuration",
                "configuration_scope": "api-contract",
                "name": "canonical API contract",
                "attributes": [],
                "product_view": "API documentation",
            }
        ]
        with self.assertRaisesRegex(MODULE.ReportError, "must be one of"):
            MODULE.normalize_audit_report(invalid)

        misplaced = sample_report()
        misplaced["findings"][0]["expected_telemetry"][0][  # type: ignore[index]
            "configuration_scope"
        ] = "otel-exporter"
        with self.assertRaisesRegex(
            MODULE.ReportError,
            "configuration_scope is only valid when type is configuration",
        ):
            MODULE.normalize_audit_report(misplaced)

    def test_rejects_generic_configuration_for_external_follow_up(self) -> None:
        data = sample_report()
        finding = data["findings"][1]  # type: ignore[index]
        make_external_follow_up(finding)
        finding["dependencies"] = []
        finding["expected_telemetry"] = [
            {
                "type": "configuration",
                "name": "platform telemetry owner map",
                "attributes": ["owner", "runbook"],
                "product_view": "External telemetry ownership",
            }
        ]

        with self.assertRaisesRegex(
            MODULE.ReportError,
            "configuration_scope is required for OpenTelemetry configuration",
        ):
            MODULE.normalize_audit_report(data)

    def test_accepts_scoped_external_configuration_with_signal_and_keeps_it_unselectable(self) -> None:
        data = sample_report()
        finding = data["findings"][1]  # type: ignore[index]
        finding.update(
            {
                "title": "Obtain external collector receipt telemetry",
                "otel_concerns": ["signal-emission", "otel-configuration"],
                "area": "External collector receipt telemetry",
                "gap": "The platform-owned collector has no saved receipt signal for this service.",
                "impact": "The service cannot distinguish export loss from application silence.",
                "product_outcome": "A platform-owned receipt metric proves collector acceptance for this service.",
                "required_fix": "Supply collector configuration evidence and a bounded receipt metric.",
                "instrument_mode": "external follow-up",
                "external_owner": "telemetry platform team",
                "external_requirement": "Supply collector configuration evidence and a bounded receipt metric.",
                "dependencies": [],
                "verification_scenarios": ["platform.collector.receipt"],
                "acceptance_criteria": [
                    "The platform receipt metric records this service with a bounded outcome."
                ],
                "follow_up_actions": [
                    "Have the telemetry platform owner save collector receipt proof."
                ],
            }
        )
        finding["expected_telemetry"] = [
            {
                "type": "configuration",
                "configuration_scope": "otel-collector",
                "name": "platform telemetry pipeline owner",
                "attributes": ["owner"],
                "product_view": "External telemetry ownership",
            },
            {
                "type": "metric",
                "name": "platform.synthetic.result",
                "attributes": ["outcome"],
                "product_view": "External synthetic result",
            },
        ]
        data["signal_flow"]["component_flow_map"] = (  # type: ignore[index]
            data["signal_flow"]["component_flow_map"].replace(
                "Payment dependency", "External collector receipt telemetry"
            )
        )
        data["findings"][0]["dependencies"] = ["OTEL-002"]  # type: ignore[index]
        data["verification"]["scenarios"].append(  # type: ignore[index]
            {
                "id": "platform.collector.receipt",
                "trigger": "Send one bounded telemetry batch through the platform collector",
                "entrypoint": "platform collector",
                "expected_signals": "platform.synthetic.result receipt metric",
                "proof_level": "full runtime",
                "acceptance_criteria": "the bounded receipt metric identifies this service and outcome",
                "environments": ["go.local"],
            }
        )

        report = MODULE.normalize_audit_report(data)

        self.assertEqual(
            report["findings"][1]["expected_telemetry"][0]["configuration_scope"],
            "otel-collector",
        )
        self.assertFalse(
            MODULE.finding_selection_eligibility(report, "OTEL-002")["selectable"]
        )

    def test_decision_and_external_modes_require_structured_telemetry_ownership(self) -> None:
        manual = sample_report()
        manual["findings"][0]["instrument_mode"] = "manual decision"  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.ReportError, "requires decision_owner"):
            MODULE.normalize_audit_report(manual)

        external = sample_report()
        external["findings"][0]["instrument_mode"] = "external follow-up"  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.ReportError, "requires a known external_owner"):
            MODULE.normalize_audit_report(external)

        misplaced = sample_report()
        misplaced["findings"][0]["external_owner"] = "platform team"  # type: ignore[index]
        misplaced["findings"][0]["external_requirement"] = "Supply an OTel receipt metric."  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.ReportError, "valid only for external follow-up"):
            MODULE.normalize_audit_report(misplaced)

        generic_decision = sample_report()
        make_manual_decision(generic_decision["findings"][0])  # type: ignore[index]
        generic_decision["findings"][0]["decision_owner"] = "TBD"  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.ReportError, "concrete responsible owner"):
            MODULE.normalize_audit_report(generic_decision)

        generic_reference = sample_report()
        make_manual_decision(generic_reference["findings"][0])  # type: ignore[index]
        generic_reference["findings"][0]["decision_question"] = (  # type: ignore[index]
            "Which generic telemetry signal should be used?"
        )
        with self.assertRaisesRegex(MODULE.ReportError, "expected OTel signal name"):
            MODULE.normalize_audit_report(generic_reference)

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

    def test_rejects_non_otel_work_in_readiness_closure_fields(self) -> None:
        incident = sample_report()
        incident["current_instrumentation"]["incident_readiness"] = [  # type: ignore[index]
            {
                "area": "Checkout latency",
                "status": "partial",
                "evidence": "OPERATIONS.md records the current process.",
                "required_signals": "Publish the OpenAPI contract and runbook ownership link.",
                "impact": "Operators lack route telemetry.",
            }
        ]
        with self.assertRaisesRegex(MODULE.ReportError, "prohibited non-OpenTelemetry"):
            MODULE.normalize_audit_report(incident)

        genai = sample_report()
        genai["meta"]["genai_ownership_detected"] = True  # type: ignore[index]
        genai["evidence"][-1]["finding"] = "Yes"  # type: ignore[index]
        genai["genai_readiness"] = [
            {
                "surface": "Checkout assistant",
                "status": "partial",
                "evidence": "assistant.go:20",
                "required_signals": "assistant.request span",
                "owner": "assistant.go:20",
                "acceptance_criteria": "Publish the runbook and emit assistant.request span.",
                "impact": "Operators cannot localize assistant latency.",
            }
        ]
        with self.assertRaisesRegex(MODULE.ReportError, "prohibited non-OpenTelemetry"):
            MODULE.normalize_audit_report(genai)

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

    def test_human_reports_visibly_render_blockers_and_readiness(self) -> None:
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
        markdown = MODULE.render_markdown(report)

        for value in (
            "Scan incomplete",
            "BLOCK-001",
            "source-scan",
            "private/generated",
            "Generated sources are unavailable.",
            ".observe/evidence/source-scan.txt",
            "Provide the generated source tree.",
            "Incident telemetry readiness",
            "Checkout latency",
            "GET /checkout span",
            "GenAI telemetry readiness",
            "Checkout assistant",
            "assistant.request span",
        ):
            self.assertIn(value, visible_html)
        self.assertIn("## Scan Blockers", markdown)
        self.assertIn("BLOCK-001", markdown)
        self.assertIn("### Incident Readiness", markdown)
        self.assertIn("## GenAI Readiness", markdown)

    def test_html_omits_anti_pattern_ledger_but_markdown_preserves_provenance(
        self,
    ) -> None:
        data = sample_report()
        mapped_anti_pattern = (
            "High-cardinality metric attributes: raw org_id and client values are "
            "attached to request, token, cost, and duration datapoints."
        )
        unique_context = (
            "A source-inactive no-op tracer compatibility shim remains for "
            "legacy local profiles."
        )
        data["anti_patterns"] = [mapped_anti_pattern, unique_context]

        report = MODULE.normalize_audit_report(data)
        html = MODULE.render_html(report, MODULE.empty_selection(report))
        visible_html = re.sub(r"<script>.*?</script>", "", html, flags=re.DOTALL)
        markdown = MODULE.render_markdown(report)

        self.assertEqual(report["anti_patterns"], [mapped_anti_pattern, unique_context])
        self.assertNotIn("<h2>Anti-Patterns</h2>", visible_html)
        self.assertNotIn(mapped_anti_pattern, visible_html)
        self.assertNotIn(unique_context, visible_html)
        self.assertIn("## Anti-Patterns", markdown)
        self.assertIn(mapped_anti_pattern, markdown)
        self.assertIn(unique_context, markdown)

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
        markdown = MODULE.render_markdown(report)
        self.assertNotIn("### Priority-ordered findings", markdown)
        gaps = markdown.split("## Gaps", 1)[1].split("### OTel Closure Details", 1)[0]
        self.assertLess(
            gaps.index("| required | Checkout latency |"),
            gaps.index("| recommended | Payment dependency |"),
        )

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
            self.assertNotIn("Copy selection JSON", html)
            self.assertIn("Save selection", html)
            self.assertIn("Copy/paste terminal fallback when saving is unreliable", html)
            self.assertNotIn("Download handoff", html)
            self.assertNotIn("Copy command", html)
            self.assertNotIn("navigator.clipboard", html)
            self.assertNotIn("Review plan", html)
            self.assertIn("Technical appendix", html)
            self.assertIn("Source-visible instrumentation evidence", html)
            self.assertIn("Verification plan", html)
            self.assertNotIn("Code-to-Telemetry Mapping", html)
            self.assertIn("ordered by priority, highest first", html)
            self.assertIn('"display_finding_ids":["OTEL-001","OTEL-002"]', html)
            self.assertIn("const DISPLAY_FINDINGS =", html)
            self.assertIn("DISPLAY_FINDINGS.map(f =>", html)
            self.assertNotIn("priority-action-groups", html)
            self.assertNotIn("data-priority-group", html)
            self.assertNotIn("action-tag", html)
            self.assertNotIn("Ready to select", html)
            self.assertNotIn("Fix now", html)
            self.assertNotIn("Consider next", html)
            self.assertNotIn("data-priority-progress", html)
            self.assertNotIn("priorityColor", html)
            self.assertNotIn('class="decision-stats"', html)
            self.assertNotIn("Fix now · safe required", html)
            self.assertNotIn("<span>Outcome</span>", html)
            self.assertNotIn("<h3>What remains unproven</h3>", html)
            self.assertNotIn("<span>status <b>", html)
            self.assertNotIn("decision-finding-link", html)
            self.assertIn("function telemetryShapeFor(finding)", html)
            self.assertIn('const order = ["span", "metric", "log", "resource", "configuration"]', html)
            self.assertIn('class="finding-meta"', html)
            self.assertIn('Telemetry: <strong>${esc(telemetryShape)}</strong>', html)
            self.assertIn('Plan prerequisite${f.dependencies.length === 1 ? "" : "s"}', html)
            self.assertIn("scope: ${esc(item.configuration_scope)}", html)
            self.assertIn("Required telemetry:", html)
            self.assertIn('"selection":"Select"', html)
            self.assertNotIn("const findingActionLabels", html)
            self.assertNotIn('class="tag action"', html)
            self.assertNotIn('class="tag"', html)
            self.assertNotIn("function findingEffortTag", html)
            self.assertNotIn("function findingLifecycleTag", html)
            self.assertNotIn('["small", "medium", "large"].includes(f.effort)', html)
            self.assertNotIn('${esc(f.effort)} effort</span>', html)
            self.assertNotIn('data-finding-tags', html)
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
            self.assertIn("This finding is selected. Save the selection", html)
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
            self.assertIn('href="otel.md">Technical audit (Markdown)</a>', html)
            self.assertIn('href="otel-audit.json">Canonical audit data (JSON)</a>', html)
            self.assertLess(
                html.index("<section><h3>${esc(primaryActionLabel)}</h3>"),
                html.index('<details class="finding-technical-details">'),
            )
            for technical_heading in (
                "Expected telemetry",
                "Acceptance criteria",
                "Implementation guardrails",
                "Evidence",
            ):
                self.assertGreater(
                    html.index(f"<section><h3>{technical_heading}</h3>"),
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
            self.assertIn("requested_ids: orderedRequested(), approved_ids: orderedSelection()", html)
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
            self.assertIn(
                'id="saveSelection" class="primary" type="button" '
                'aria-describedby="saveSelectionHint">Save selection</button>',
                html,
            )
            self.assertIn('id="instrumentCommand"', html)
            self.assertIn("function serviceRootFromLocation()", html)
            self.assertIn("function terminalInstrumentCommand()", html)
            self.assertIn(
                "parts.map((part, index) => index === 0 ? part : commandPart(part)).join",
                html,
            )
            self.assertIn('parts.push("--decision", `${answer.finding_id}=${answer.option_id}`);', html)
            self.assertIn(
                "Select at least one executable finding to generate an instrumentation command.",
                html,
            )
            self.assertIn(
                "Save this audit state over <code>.observe/otel-audit.json</code>",
                html,
            )
            self.assertIn("function auditReviewDocument()", html)
            self.assertIn("document.review_selection = selectionDocument()", html)
            self.assertIn('suggestedName: "otel-audit.json"', html)
            self.assertIn('link.download = "otel-audit.selected.json"', html)
            self.assertNotIn("const unresolvedManualIds = inPlanIds.filter", html)
            self.assertIn('summaryParts.join(" · ")', html)
            self.assertNotIn('"decision needed", "decisions needed"', html)
            self.assertIn('"dependency", "dependencies"', html)
            self.assertNotIn("Required instrumentation work", html)
            self.assertNotIn("Recommended instrumentation work", html)
            self.assertNotIn('heading: "Decisions needed"', html)
            self.assertNotIn("Added because required by ", html)
            self.assertNotIn("You selected", html)
            self.assertNotIn("function instrumentCommand()", html)
            self.assertNotIn("function copyText", html)
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
            self.assertEqual(html.count('id="saveSelection"'), 1)
            self.assertEqual(html.count('id="reviewPlan"'), 0)
            self.assertEqual(html.count('id="downloadJson"'), 0)
            self.assertEqual(html.count('id="copyCommand"'), 0)
            self.assertIn(
                'document.getElementById("saveSelection").addEventListener("click"',
                html,
            )
            self.assertIn("window.showSaveFilePicker", html)
            self.assertIn("Audit selection saved into the audit report.", html)
            self.assertIn('link.download = "otel-audit.selected.json"', html)
            self.assertIn("Saved audit download fallback started.", html)
            self.assertNotIn("severityColor", html)
            self.assertNotIn("data-severity", html)
            self.assertNotIn("--required:", html)
            self.assertNotIn("--recommended:", html)
            self.assertNotIn("--deferred:", html)
            self.assertNotIn("document.execCommand", html)
            self.assertNotIn("https://fonts.googleapis.com", html)
            self.assertNotIn("<script src=", html.lower())
            self.assertNotIn("<link ", html.lower())

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
  [{protocol: "file:", hostname: "", pathname: "/Users/a/repo/.observe/otel.html"}, "/Users/a/repo"],
  [{protocol: "file:", hostname: "", pathname: "/C:/repo/.observe/otel.html"}, "C:/repo"],
  [{protocol: "file:", hostname: "server", pathname: "/share/repo/.observe/otel.html"}, "//server/share/repo"],
  [{protocol: "https:", hostname: "example.test", pathname: "/otel.html"}, "<service-root>"],
];
for (const [input, expected] of cases) {
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

    def test_html_progressively_discloses_verbose_finding_details(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())
        html = MODULE.render_html(report, MODULE.empty_selection(report))
        render_cards = html.split("function renderCards()", 1)[1].split(
            "function orderedSelection()", 1
        )[0]
        card_start = render_cards.index("return `<article")
        card_end = render_cards.index("</article>`;", card_start)
        card = render_cards[card_start:card_end]
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
            self.assertIn(f"<h3>{label}</h3>", concise_details)
        self.assertIn("<h3>${esc(primaryActionLabel)}</h3>", concise_details)
        for label in (
            "Expected telemetry",
            "Acceptance criteria",
            "Implementation guardrails",
            "Evidence",
        ):
            heading = f"<h3>{label}</h3>"
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

    def test_html_renders_decision_answers_without_a_manual_plan_checkbox(self) -> None:
        report = MODULE.normalize_audit_report(sample_decision_branch_report())
        html = MODULE.render_html(report, MODULE.empty_selection(report))

        self.assertIn("return (option.unlocks || []).length", html)
        self.assertIn(
            "This answer unlocks no instrumentation work. Keep the decision in the audit; no selection is needed.",
            html,
        )
        self.assertIn('class="decision-options"', html)
        self.assertIn("<fieldset", html)
        self.assertIn("<legend", html)
        self.assertIn('type="radio"', html)
        self.assertIn('name="decision-${esc(finding.id)}"', html)
        self.assertIn(
            'const inputId = `decision-${finding.id}-${option.id}`',
            html,
        )
        self.assertIn(
            'id="${esc(inputId)}"',
            html,
        )
        self.assertIn(
            'for="${esc(inputId)}"',
            html,
        )
        self.assertIn('data-decision-id="${esc(finding.id)}"', html)
        self.assertIn('data-option-id="${esc(option.id)}"', html)
        self.assertIn(
            'if (finding.instrument_mode !== "manual decision" || !options.length) return "";',
            html,
        )
        self.assertIn("const decisionControl = decisionSelectionControl(f);", html)
        self.assertIn(
            "const selectionControl = decisionControl || (eligibility.selectable",
            html,
        )
        self.assertIn('</button>\n        ${selectionControl}', html)

    def test_html_serializes_answers_and_prunes_stale_branch_work(self) -> None:
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

        self.assertIn("const decisionAnswers = new Map", html)
        self.assertNotIn("const findingActionLabels", html)
        self.assertNotIn("function findingActionLabelFor(finding)", html)
        self.assertIn("decisionAnswers.set(decisionId, optionId)", html)
        self.assertIn("document.decision_answers = answers", html)
        self.assertIn(
            "schema_version: answers.length ? 2 : 1",
            html,
        )
        self.assertIn("requested.delete(finding.id)", html)
        self.assertIn("Removed incompatible selected work", html)

        answer_handler_start = html.index(
            "function applyDecisionAnswer(decisionId, optionId)"
        )
        plan_handler_start = html.index(
            "\nfunction syncFindingSelectionState()",
            answer_handler_start,
        )
        answer_handler = html[answer_handler_start:plan_handler_start]
        self.assertIn("decisionAnswers.set", answer_handler)
        self.assertIn("pruneIncompatibleSelections()", answer_handler)
        self.assertNotIn("requested.add", answer_handler)

    def test_cli_render_html_links_existing_repository_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = root / "checkout"
            observe = service / ".observe"
            audit = observe / "otel-audit.json"
            html_path = observe / "otel.html"
            base_path = "service/src/main/java/example/BaseDao.java"
            metric_path = "service/src/main/java/example/MetricDao.java"
            test_path = "service/src/test/java/example/DaoTracingTest.java"
            for path in (base_path, metric_path, test_path):
                source = service / path
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text("// fixture\n", encoding="utf-8")
            observe.mkdir(parents=True, exist_ok=True)

            report = sample_report()
            base_ref = f"{base_path}:43-108"
            metric_ref = f"{metric_path}:29-71"
            test_ref = f"{test_path}:23-56 (untracked pre-existing test intent; not executed)"
            report["evidence"][1]["source"] = base_ref  # type: ignore[index]
            report["findings"][0]["evidence"] = [base_ref, metric_ref, test_ref, "missing.go:1"]  # type: ignore[index]
            report["verification"]["environments"][0]["config_evidence"] = metric_ref  # type: ignore[index]
            report["verification"]["scenarios"][0]["entrypoint"] = base_ref  # type: ignore[index]
            report["current_instrumentation"]["spans"] = [  # type: ignore[index]
                {"name": "create", "source": metric_ref, "type": "custom"}
            ]
            audit.write_text(json.dumps(report), encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "render-html", str(audit), "-o", str(html_path)],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            html = html_path.read_text(encoding="utf-8")
            self.assertIn(f'href="../{base_path}#L43-L108"', html)
            self.assertIn(f'href="../{metric_path}#L29-L71"', html)
            self.assertIn(f'"href":"../{test_path}#L23-L56"', html)
            self.assertIn("untracked pre-existing test intent; not executed", html)
            self.assertIn('target="_blank" rel="noopener"', html)
            self.assertIn("<th>Config evidence</th>", html)
            self.assertIn("<th>Source entrypoint</th>", html)
            self.assertIn("sourceHtml(item)", html)
            self.assertNotIn('href="../missing.go', html)
            self.assertNotIn(str(service), html)
            self.assertNotIn("file://", html)

    def test_select_closes_dependencies_and_writes_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / "otel-audit.json"
            selection = root / "otel-selection.json"
            scope = root / "selected-findings.json"
            audit.write_text(json.dumps(sample_report()), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "select",
                    str(audit),
                    "--ids",
                    "OTEL-002",
                    "-o",
                    str(selection),
                    "--scoped-out",
                    str(scope),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            selected = json.loads(selection.read_text(encoding="utf-8"))
            scoped = json.loads(scope.read_text(encoding="utf-8"))
            self.assertEqual(selected["schema_version"], 1)
            self.assertEqual(scoped["schema_version"], 1)
            self.assertEqual(selected["requested_ids"], ["OTEL-002"])
            self.assertEqual(selected["approved_ids"], ["OTEL-001", "OTEL-002"])
            self.assertEqual(scoped["kind"], "otel-audit-scope")
            self.assertEqual([row["id"] for row in scoped["findings"]], ["OTEL-001", "OTEL-002"])
            selected_finding = scoped["findings"][1]
            for retained_field in (
                "expected_telemetry",
                "verification_scenarios",
                "follow_up_actions",
                "constraints",
            ):
                self.assertEqual(
                    selected_finding[retained_field],
                    sample_report()["findings"][1][retained_field],
                )
            self.assertEqual(
                [row["id"] for row in scoped["verification"]["scenarios"]],
                ["http.checkout.success"],
            )

    def test_select_all_selects_every_eligible_executable_finding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / "otel-audit.json"
            selection = root / "otel-selection.json"
            scope = root / "selected-findings.json"
            audit.write_text(json.dumps(sample_report()), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "select",
                    str(audit),
                    "--all",
                    "-o",
                    str(selection),
                    "--scoped-out",
                    str(scope),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            selected = json.loads(selection.read_text(encoding="utf-8"))
            scoped = json.loads(scope.read_text(encoding="utf-8"))
            self.assertEqual(selected["schema_version"], 1)
            self.assertEqual(selected["requested_ids"], ["OTEL-001", "OTEL-002"])
            self.assertEqual(selected["approved_ids"], ["OTEL-001", "OTEL-002"])
            self.assertEqual(
                [row["id"] for row in scoped["findings"]],
                ["OTEL-001", "OTEL-002"],
            )
            self.assertIn(
                "selected all eligible executable findings",
                completed.stdout,
            )

    def test_select_all_requires_manual_decision_answers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / "otel-audit.json"
            selection = root / "otel-selection.json"
            audit.write_text(
                json.dumps(sample_decision_branch_report()),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "select",
                    str(audit),
                    "--all",
                    "-o",
                    str(selection),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 1)
            self.assertFalse(selection.exists())
            self.assertIn(
                "select --all requires manual decision answers",
                completed.stderr,
            )
            self.assertIn(
                "--decision OTEL-001=application-owned",
                completed.stderr,
            )
            self.assertIn(
                "--decision OTEL-001=runtime-owned",
                completed.stderr,
            )

    def test_select_all_with_decision_selects_matching_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / "otel-audit.json"
            selection = root / "otel-selection.json"
            scope = root / "selected-findings.json"
            audit.write_text(
                json.dumps(sample_decision_branch_report()),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "select",
                    str(audit),
                    "--all",
                    "--decision",
                    "OTEL-001=application-owned",
                    "-o",
                    str(selection),
                    "--scoped-out",
                    str(scope),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            selected = json.loads(selection.read_text(encoding="utf-8"))
            scoped = json.loads(scope.read_text(encoding="utf-8"))
            self.assertEqual(selected["schema_version"], 2)
            self.assertEqual(selected["requested_ids"], ["OTEL-002"])
            self.assertEqual(selected["approved_ids"], ["OTEL-002"])
            self.assertEqual(
                selected["decision_answers"],
                [{"finding_id": "OTEL-001", "option_id": "application-owned"}],
            )
            self.assertEqual([row["id"] for row in scoped["findings"]], ["OTEL-002"])
            self.assertNotIn("OTEL-003", selected["approved_ids"])

    def test_adopt_selection_copies_newest_matching_saved_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observe = root / ".observe"
            observe.mkdir()
            downloads = root / "Downloads"
            downloads.mkdir()
            audit = observe / "otel-audit.json"
            output = observe / "otel-selection.json"
            scope = observe / "selected-findings.json"
            report = MODULE.normalize_audit_report(sample_report())
            audit.write_text(json.dumps(report), encoding="utf-8")
            older = {
                "schema_version": 1,
                "kind": "otel-selection",
                "audit_id": report["meta"]["audit_id"],
                "audit_sha256": MODULE.audit_digest(report),
                "requested_ids": ["OTEL-001"],
                "approved_ids": ["OTEL-001"],
            }
            newest = {
                **older,
                "requested_ids": ["OTEL-002"],
                "approved_ids": ["OTEL-001", "OTEL-002"],
            }
            older_path = downloads / "otel-selection.json"
            newest_path = downloads / "otel-selection (9).json"
            older_path.write_text(json.dumps(older), encoding="utf-8")
            newest_path.write_text(json.dumps(newest), encoding="utf-8")
            os.utime(older_path, ns=(1_000, 1_000))
            os.utime(newest_path, ns=(2_000, 2_000))

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "adopt-selection",
                    str(audit),
                    "-o",
                    str(output),
                    "--scoped-out",
                    str(scope),
                    "--search-dir",
                    str(downloads),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            selected = json.loads(output.read_text(encoding="utf-8"))
            scoped = json.loads(scope.read_text(encoding="utf-8"))
            self.assertEqual(selected["requested_ids"], ["OTEL-002"])
            self.assertEqual(selected["approved_ids"], ["OTEL-001", "OTEL-002"])
            self.assertEqual([row["id"] for row in scoped["findings"]], ["OTEL-001", "OTEL-002"])
            self.assertIn("wrote", completed.stdout)
            self.assertIn("otel-selection (9).json", completed.stdout)

    def test_adopt_selection_replaces_existing_output_with_newer_saved_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observe = root / ".observe"
            observe.mkdir()
            audit = observe / "otel-audit.json"
            output = observe / "otel-selection.json"
            report_data = sample_report()
            report = MODULE.normalize_audit_report(report_data)
            old_selection = {
                "schema_version": 1,
                "kind": "otel-selection",
                "audit_id": report["meta"]["audit_id"],
                "audit_sha256": MODULE.audit_digest(report),
                "requested_ids": ["OTEL-001"],
                "approved_ids": ["OTEL-001"],
            }
            saved_selection = {
                **old_selection,
                "requested_ids": ["OTEL-002"],
                "approved_ids": ["OTEL-001", "OTEL-002"],
            }
            report_data["review_selection"] = saved_selection
            audit.write_text(json.dumps(report_data), encoding="utf-8")
            output.write_text(json.dumps(old_selection), encoding="utf-8")
            os.utime(output, ns=(1_000, 1_000))
            os.utime(audit, ns=(2_000, 2_000))

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "adopt-selection",
                    str(audit),
                    "-o",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            selected = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(selected["requested_ids"], ["OTEL-002"])
            self.assertEqual(selected["approved_ids"], ["OTEL-001", "OTEL-002"])
            self.assertIn("otel-audit.json", completed.stdout)

    def test_adopt_selection_all_if_empty_uses_saved_decision_answer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observe = root / ".observe"
            observe.mkdir()
            audit = observe / "otel-audit.json"
            output = observe / "otel-selection.json"
            scope = observe / "selected-findings.json"
            report = MODULE.normalize_audit_report(sample_decision_branch_report())
            audit.write_text(json.dumps(report), encoding="utf-8")
            output.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "kind": "otel-selection",
                        "audit_id": report["meta"]["audit_id"],
                        "audit_sha256": MODULE.audit_digest(report),
                        "requested_ids": [],
                        "approved_ids": [],
                        "decision_answers": [
                            {
                                "finding_id": "OTEL-001",
                                "option_id": "application-owned",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "adopt-selection",
                    str(audit),
                    "-o",
                    str(output),
                    "--scoped-out",
                    str(scope),
                    "--all-if-empty",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            selected = json.loads(output.read_text(encoding="utf-8"))
            scoped = json.loads(scope.read_text(encoding="utf-8"))
            self.assertEqual(selected["requested_ids"], ["OTEL-002"])
            self.assertEqual(selected["approved_ids"], ["OTEL-002"])
            self.assertEqual(
                selected["decision_answers"],
                [{"finding_id": "OTEL-001", "option_id": "application-owned"}],
            )
            self.assertEqual([row["id"] for row in scoped["findings"]], ["OTEL-002"])
            self.assertIn(
                "selected all eligible executable findings",
                completed.stdout,
            )

    def test_adopt_selection_reports_invalid_canonical_audit_before_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observe = root / ".observe"
            observe.mkdir()
            downloads = root / "Downloads"
            downloads.mkdir()
            audit = observe / "otel-audit.json"
            output = observe / "otel-selection.json"
            audit.write_text(
                json.dumps({"kind": "otel-audit", "schema_version": 2}),
                encoding="utf-8",
            )
            (downloads / "otel-selection.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "otel-selection",
                        "audit_id": "checkout-20260717",
                        "audit_sha256": "does-not-matter",
                        "requested_ids": ["OTEL-001"],
                        "approved_ids": ["OTEL-001"],
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "adopt-selection",
                    str(audit),
                    "-o",
                    str(output),
                    "--search-dir",
                    str(downloads),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 1)
            self.assertIn("canonical audit is invalid", completed.stderr)
            self.assertFalse(output.exists())

    def test_duplicate_remediation_accepts_source_proven_java_agent_owner(self) -> None:
        data = sample_report()
        finding = data["findings"][0]  # type: ignore[index]
        finding["gap"] = "HTTP server spans can duplicate because two owners overlap."
        finding["required_fix"] = (
            "Make the OpenTelemetry Java agent the canonical HTTP server "
            "telemetry owner and suppress the overlapping manual owner."
        )

        report = MODULE.normalize_audit_report(data)

        self.assertEqual(report["findings"][0]["required_fix"], finding["required_fix"])

    def test_proof_level_aliases_normalize_to_supported_contract(self) -> None:
        data = sample_report()
        data["verification"]["scenarios"][0]["proof_level"] = "unit plus runtime"  # type: ignore[index]

        report = MODULE.normalize_audit_report(data)

        self.assertEqual(
            report["verification"]["scenarios"][0]["proof_level"],
            "full runtime",
        )

    def test_readiness_rows_compact_structured_cells_deterministically(self) -> None:
        data = sample_report()
        data["meta"]["genai_ownership_detected"] = True  # type: ignore[index]
        data["evidence"][-1] = {  # type: ignore[index]
            "check": "GenAI ownership",
            "finding": "Yes",
            "source": "app.py",
        }
        data["genai_readiness"] = [
            {
                "surface": "Checkout latency",
                "status": "partial",
                "evidence": ["app.py:42", "router.py:9"],
                "required_signals": "GET /checkout span",
                "owner": ["service code", "app.py"],
                "acceptance_criteria": "span is emitted",
                "impact": {"mttd": "operators can detect checkout latency"},
            }
        ]

        report = MODULE.normalize_audit_report(data)

        self.assertEqual(report["genai_readiness"][0]["owner"], "service code; app.py")
        self.assertEqual(
            report["genai_readiness"][0]["impact"],
            "mttd: operators can detect checkout latency",
        )

    def test_selection_rejects_decisions_external_followups_and_blocked_work(self) -> None:
        manual_data = sample_report()
        make_manual_decision(manual_data["findings"][1])  # type: ignore[index]
        manual_data["findings"][1]["dependencies"] = []  # type: ignore[index]
        manual_data["findings"][0]["dependencies"] = ["OTEL-002"]  # type: ignore[index]
        manual = MODULE.normalize_audit_report(manual_data)
        self.assertEqual(
            MODULE.finding_selection_eligibility(manual, "OTEL-002"),
            {
                "selectable": False,
                "blockers": [],
                "reason": "Resolve decision first",
            },
        )
        with self.assertRaisesRegex(
            MODULE.ReportError,
            "OTEL-002 cannot be selected for instrumentation: Resolve decision first",
        ):
            MODULE.dependency_closure(manual, ["OTEL-002"])

        external_data = sample_report()
        make_external_follow_up(external_data["findings"][1])  # type: ignore[index]
        external_data["findings"][1]["dependencies"] = []  # type: ignore[index]
        external_data["findings"][0]["dependencies"] = ["OTEL-002"]  # type: ignore[index]
        external = MODULE.normalize_audit_report(external_data)
        with self.assertRaisesRegex(
            MODULE.ReportError,
            "OTEL-002 cannot be selected for instrumentation: Not selectable",
        ):
            MODULE.dependency_closure(external, ["OTEL-002"])

        blocked_data = sample_report()
        make_manual_decision(blocked_data["findings"][0])  # type: ignore[index]
        blocked = MODULE.normalize_audit_report(blocked_data)
        self.assertEqual(MODULE.selection_blockers(blocked, "OTEL-002"), ["OTEL-001"])
        self.assertEqual(
            MODULE.finding_selection_eligibility(blocked, "OTEL-002")["reason"],
            "Blocked by OTEL-001",
        )
        with self.assertRaisesRegex(
            MODULE.ReportError,
            "OTEL-002 cannot be selected for instrumentation: Blocked by OTEL-001",
        ):
            MODULE.dependency_closure(blocked, ["OTEL-002"])

    def test_terminal_executable_prerequisites_have_identical_python_and_html_semantics(
        self,
    ) -> None:
        done_data = sample_report()
        done_data["findings"][0]["status"] = "done"  # type: ignore[index]
        done = MODULE.normalize_audit_report(done_data)
        digest = MODULE.audit_digest(done)
        selection = MODULE.normalize_selection(
            {
                "schema_version": 1,
                "kind": "otel-selection",
                "audit_id": done["meta"]["audit_id"],
                "audit_sha256": digest,
                "requested_ids": ["OTEL-002"],
                "approved_ids": ["OTEL-002"],
            },
            done,
        )
        self.assertEqual(MODULE.dependency_closure(done, ["OTEL-002"]), ["OTEL-002"])
        self.assertEqual(selection["approved_ids"], ["OTEL-002"])

        html = MODULE.render_html(done, selection)
        self.assertIn(
            'dependency.status === "done"',
            html,
        )
        self.assertIn(
            '["rejected", "deferred"].includes(dependency.status)',
            html,
        )
        self.assertIn(
            'finding.status === "done") return;',
            html,
        )

        for status in ("rejected", "deferred"):
            with self.subTest(status=status):
                blocked_data = sample_report()
                blocked_data["findings"][0]["status"] = status  # type: ignore[index]
                blocked = MODULE.normalize_audit_report(blocked_data)
                self.assertEqual(
                    MODULE.finding_selection_eligibility(blocked, "OTEL-002"),
                    {
                        "selectable": False,
                        "blockers": ["OTEL-001"],
                        "reason": "Blocked by OTEL-001",
                    },
                )
                with self.assertRaisesRegex(
                    MODULE.ReportError, "Blocked by OTEL-001"
                ):
                    MODULE.dependency_closure(blocked, ["OTEL-002"])

    def test_selection_v2_answer_unlocks_only_its_direct_executable_branch(self) -> None:
        report = MODULE.normalize_audit_report(sample_decision_branch_report())
        answers = [
            {"finding_id": "OTEL-001", "option_id": "application-owned"}
        ]

        self.assertEqual(MODULE.dependency_closure(report, [], answers), [])
        self.assertTrue(
            MODULE.finding_selection_eligibility(
                report, "OTEL-002", answers
            )["selectable"]
        )
        self.assertEqual(
            MODULE.finding_selection_eligibility(report, "OTEL-003", answers),
            {
                "selectable": False,
                "blockers": ["OTEL-001"],
                "reason": "Blocked by OTEL-001",
            },
        )

        selection = MODULE.normalize_selection(
            {
                "schema_version": 2,
                "kind": "otel-selection",
                "audit_id": report["meta"]["audit_id"],
                "audit_sha256": MODULE.audit_digest(report),
                "requested_ids": ["OTEL-002"],
                "approved_ids": ["OTEL-002"],
                "decision_answers": answers,
            },
            report,
        )
        self.assertEqual(selection["schema_version"], 2)
        self.assertEqual(selection["requested_ids"], ["OTEL-002"])
        self.assertEqual(selection["approved_ids"], ["OTEL-002"])
        self.assertEqual(selection["decision_answers"], answers)
        self.assertNotIn("OTEL-001", selection["requested_ids"])
        self.assertNotIn("OTEL-001", selection["approved_ids"])

        with self.assertRaisesRegex(
            MODULE.ReportError,
            "OTEL-003 cannot be selected for instrumentation: Blocked by OTEL-001",
        ):
            MODULE.normalize_selection(
                {
                    "schema_version": 2,
                    "kind": "otel-selection",
                    "audit_id": report["meta"]["audit_id"],
                    "audit_sha256": MODULE.audit_digest(report),
                    "requested_ids": ["OTEL-003"],
                    "approved_ids": ["OTEL-003"],
                    "decision_answers": answers,
                },
                report,
            )

        with self.assertRaisesRegex(
            MODULE.ReportError,
            "OTEL-001 cannot be selected for instrumentation",
        ):
            MODULE.dependency_closure(report, ["OTEL-001"], answers)

    def test_selection_closure_includes_prerequisites_behind_answered_decision(self) -> None:
        report = MODULE.normalize_audit_report(sample_decision_branch_report())
        prerequisite = copy.deepcopy(report["findings"][1])
        prerequisite.update({"id": "OTEL-004", "dependencies": []})
        report["findings"].insert(0, prerequisite)
        report["findings"][1]["dependencies"] = ["OTEL-004"]
        answers = [
            {"finding_id": "OTEL-001", "option_id": "application-owned"}
        ]

        self.assertEqual(
            MODULE.dependency_closure(report, ["OTEL-002"], answers),
            ["OTEL-004", "OTEL-002"],
        )

        html = MODULE.render_html(report, MODULE.empty_selection(report))
        self.assertIn(
            'if (!selectable && finding.instrument_mode !== "manual decision") return;',
            html,
        )

    def test_decision_options_validate_cardinality_ids_and_direct_unlocks(self) -> None:
        report = MODULE.normalize_audit_report(sample_decision_branch_report())
        self.assertEqual(
            [option["id"] for option in report["findings"][0]["decision_options"]],
            ["application-owned", "runtime-owned"],
        )

        one_option = sample_decision_branch_report()
        one_option["findings"][0]["decision_options"].pop()  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.ReportError, "must contain 2 or 3"):
            MODULE.normalize_audit_report(one_option)

        duplicate = sample_decision_branch_report()
        duplicate["findings"][0]["decision_options"][1]["id"] = "application-owned"  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.ReportError, "unique option IDs"):
            MODULE.normalize_audit_report(duplicate)

        unknown = sample_decision_branch_report()
        unknown["findings"][0]["decision_options"][0]["unlocks"] = ["OTEL-999"]  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.ReportError, "undefined finding OTEL-999"):
            MODULE.normalize_audit_report(unknown)

        indirect = sample_decision_branch_report()
        indirect["findings"][1]["dependencies"] = []  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.ReportError, "must directly depend"):
            MODULE.normalize_audit_report(indirect)

        incomplete = sample_decision_branch_report()
        incomplete["findings"][0]["decision_options"][0]["unlocks"] = []  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.ReportError, "unlock every direct executable dependent"):
            MODULE.normalize_audit_report(incomplete)

        overlapping = sample_decision_branch_report()
        overlapping["findings"][0]["decision_options"][1]["unlocks"] = [  # type: ignore[index]
            "OTEL-002",
            "OTEL-003",
        ]
        with self.assertRaisesRegex(MODULE.ReportError, "pairwise disjoint"):
            MODULE.normalize_audit_report(overlapping)

    def test_selection_v2_persists_answer_without_authorizing_code(self) -> None:
        report = MODULE.normalize_audit_report(sample_decision_branch_report())
        selection = MODULE.normalize_selection(
            {
                "schema_version": 2,
                "kind": "otel-selection",
                "audit_id": report["meta"]["audit_id"],
                "audit_sha256": MODULE.audit_digest(report),
                "requested_ids": [],
                "approved_ids": [],
                "decision_answers": [
                    {"finding_id": "OTEL-001", "option_id": "application-owned"}
                ],
            },
            report,
        )

        self.assertEqual(selection["requested_ids"], [])
        self.assertEqual(selection["approved_ids"], [])
        self.assertEqual(
            selection["decision_answers"],
            [{"finding_id": "OTEL-001", "option_id": "application-owned"}],
        )

    def test_instrumentation_is_bound_to_exact_decision_answer_when_scope_is_unchanged(
        self,
    ) -> None:
        report = MODULE.normalize_audit_report(sample_decision_branch_report())
        digest = MODULE.audit_digest(report)

        def answer_selection(option_id: str) -> dict[str, object]:
            return MODULE.normalize_selection(
                {
                    "schema_version": 2,
                    "kind": "otel-selection",
                    "audit_id": report["meta"]["audit_id"],
                    "audit_sha256": digest,
                    "requested_ids": [],
                    "approved_ids": [],
                    "decision_answers": [
                        {"finding_id": "OTEL-001", "option_id": option_id}
                    ],
                },
                report,
            )

        application_owned = answer_selection("application-owned")
        runtime_owned = answer_selection("runtime-owned")
        self.assertEqual(application_owned["approved_ids"], runtime_owned["approved_ids"])
        self.assertNotEqual(
            MODULE.selection_digest(application_owned),
            MODULE.selection_digest(runtime_owned),
        )

        raw_instrumentation = {
            "schema_version": 1,
            "kind": "otel-instrumentation",
            "audit_id": report["meta"]["audit_id"],
            "audit_sha256": digest,
            "selection_sha256": MODULE.selection_digest(application_owned),
            "meta": {
                "service_name": "checkout",
                "date": "2026-07-21",
                "result": "Partial",
            },
            "findings": [],
            "next_steps": ["Select the executable branch after recording the answer."],
        }
        normalized = MODULE.normalize_instrumentation(
            raw_instrumentation, report, application_owned
        )
        self.assertEqual(
            normalized["selection_sha256"],
            MODULE.selection_digest(application_owned),
        )

        with self.assertRaisesRegex(
            MODULE.ReportError, "selection_sha256 does not match selection"
        ):
            MODULE.normalize_instrumentation(
                raw_instrumentation, report, runtime_owned
            )

        unbound = copy.deepcopy(raw_instrumentation)
        unbound.pop("selection_sha256")
        with self.assertRaisesRegex(
            MODULE.ReportError, "selection_sha256 is required"
        ):
            MODULE.normalize_instrumentation(unbound, report, application_owned)

    def test_cli_select_can_persist_an_answer_only_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / "otel-audit.json"
            selection_path = root / "otel-selection.json"
            scope_path = root / "otel-scope.json"
            audit.write_text(
                json.dumps(sample_decision_branch_report()), encoding="utf-8"
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "select",
                    str(audit),
                    "--decision",
                    "OTEL-001=application-owned",
                    "-o",
                    str(selection_path),
                    "--scoped-out",
                    str(scope_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            selection = json.loads(selection_path.read_text(encoding="utf-8"))
            scope = json.loads(scope_path.read_text(encoding="utf-8"))
            self.assertEqual(selection["schema_version"], 2)
            self.assertEqual(selection["requested_ids"], [])
            self.assertEqual(selection["approved_ids"], [])
            self.assertEqual(scope["findings"], [])
            self.assertEqual(
                scope["decision_answers"][0]["outcome"],
                "Emit the GET /checkout span from application-owned OpenTelemetry instrumentation.",
            )

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
        self.assertIn("parts.push(serviceRootFromLocation());", html)
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
            scope_path = observe / "tmp" / "otel-selected-findings.json"
            scope_path.parent.mkdir()
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
                    "--scoped-out",
                    str(scope_path),
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
            scope = json.loads(scope_path.read_text(encoding="utf-8"))
            self.assertEqual(selection["requested_ids"], ["OTEL-001"])
            self.assertEqual(selection["approved_ids"], ["OTEL-001"])
            self.assertEqual([finding["id"] for finding in scope["findings"]], ["OTEL-001"])

    def test_manual_without_options_remains_a_static_blocker_for_legacy_audits(self) -> None:
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

    def test_instrumentation_requires_product_actions_for_metrics_and_dimensions(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())
        report["findings"][0]["expected_telemetry"][0]["type"] = "metric"  # type: ignore[index]
        report["findings"][0]["expected_telemetry"][0]["attributes"] = []  # type: ignore[index]
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
        metric = sample_instrumentation(report, MODULE.audit_digest(report))
        item = metric["findings"][0]["telemetry_changes"][0]  # type: ignore[index]
        item["type"] = "metric"
        item["added_attributes"] = []
        item["follow_up_actions"] = ["Run the scenario."]
        with self.assertRaisesRegex(MODULE.ReportError, "chart, dashboard, detector"):
            MODULE.normalize_instrumentation(metric, report, selection)

        dimension_report = MODULE.normalize_audit_report(sample_report())
        dimension_selection = MODULE.normalize_selection(
            {
                "schema_version": 1,
                "kind": "otel-selection",
                "audit_id": dimension_report["meta"]["audit_id"],  # type: ignore[index]
                "audit_sha256": MODULE.audit_digest(dimension_report),
                "requested_ids": ["OTEL-001"],
                "approved_ids": ["OTEL-001"],
            },
            dimension_report,
        )
        dimension = sample_instrumentation(
            dimension_report, MODULE.audit_digest(dimension_report)
        )
        dimension_item = dimension["findings"][0]["telemetry_changes"][0]  # type: ignore[index]
        dimension_item["follow_up_actions"] = ["Open the trace waterfall."]
        with self.assertRaisesRegex(MODULE.ReportError, "filter, slice, group-by"):
            MODULE.normalize_instrumentation(
                dimension, dimension_report, dimension_selection
            )

    def test_instrumentation_change_must_match_audit_expected_telemetry(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())
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
        instrumentation = sample_instrumentation(report, digest)
        item = instrumentation["findings"][0]["telemetry_changes"][0]  # type: ignore[index]
        item["name"] = "totally.unrelated.signal"

        with self.assertRaisesRegex(MODULE.ReportError, "exact expected telemetry item"):
            MODULE.normalize_instrumentation(instrumentation, report, selection)

        instrumentation = sample_instrumentation(report, digest)
        item = instrumentation["findings"][0]["telemetry_changes"][0]  # type: ignore[index]
        item["added_attributes"] = ["http.route=/admin"]
        with self.assertRaisesRegex(MODULE.ReportError, "attributes not promised"):
            MODULE.normalize_instrumentation(instrumentation, report, selection)

        report["findings"][0]["expected_telemetry"][0]["attributes"] = [  # type: ignore[index]
            "http.route=/checkout"
        ]
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
        instrumentation = sample_instrumentation(report, digest)
        item = instrumentation["findings"][0]["telemetry_changes"][0]  # type: ignore[index]
        item["added_attributes"] = ["http.route=/checkout"]
        normalized = MODULE.normalize_instrumentation(
            instrumentation, report, selection
        )
        self.assertEqual(
            normalized["findings"][0]["telemetry_changes"][0]["added_attributes"],
            ["http.route=/checkout"],
        )

    def test_verify_closure_must_account_for_expected_attributes(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())
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
        item = instrumentation_data["findings"][0]["telemetry_changes"][0]  # type: ignore[index]
        item["added_attributes"] = []
        instrumentation_data["meta"]["result"] = "Pass"  # type: ignore[index]
        instrumentation_data["findings"][0]["status"] = "working"  # type: ignore[index]
        instrumentation = MODULE.normalize_instrumentation(
            instrumentation_data, report, selection
        )
        verify = sample_verify(
            report, digest, MODULE.instrumentation_digest(instrumentation)
        )
        verify["meta"]["result"] = "Pass"  # type: ignore[index]
        finding = verify["findings"][0]  # type: ignore[index]
        finding["status"] = "working"
        finding["remaining"] = []
        finding["scenarios"][0].update(
            {
                "status": "working",
                "commands": ["go test ./..."],
                "evidence": [".observe/evidence/runtime.json"],
                "observed_telemetry": ["GET /checkout"],
                "product_validation": ["Captured by the local OTLP receiver."],
                "proof_mode": "full_runtime",
                "visibility": "otlp_accepted",
            }
        )
        finding["item_results"][0].update(
            {
                "status": "working",
                "direct_assertion_passed": True,
                "evidence": [".observe/evidence/runtime.json"],
                "observed_telemetry": ["GET /checkout"],
                "product_validation": ["Captured by the local OTLP receiver."],
                "proof_mode": "full_runtime",
                "visibility": "otlp_accepted",
            }
        )

        with self.assertRaisesRegex(MODULE.ReportError, "GET /checkout"):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

    def test_verify_pass_must_cover_every_audit_expected_item(self) -> None:
        raw_report = sample_report()
        raw_report["findings"][0]["expected_telemetry"].append(  # type: ignore[index]
            {
                "type": "span",
                "name": "checkout.payment",
                "attributes": ["payment.provider"],
                "product_view": "Payment trace waterfall",
            }
        )
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
        instrumentation_data["findings"][0]["status"] = "working"  # type: ignore[index]
        instrumentation = MODULE.normalize_instrumentation(
            instrumentation_data, report, selection
        )
        verify = sample_verify(
            report, digest, MODULE.instrumentation_digest(instrumentation)
        )
        verify["meta"]["result"] = "Pass"  # type: ignore[index]
        finding = verify["findings"][0]  # type: ignore[index]
        finding["status"] = "working"
        finding["remaining"] = []
        finding["scenarios"][0].update(
            {
                "status": "working",
                "commands": ["go test ./..."],
                "evidence": [".observe/evidence/runtime.json"],
                "observed_telemetry": ["GET /checkout with http.route"],
                "product_validation": ["Captured by the local OTLP receiver."],
                "proof_mode": "full_runtime",
                "visibility": "otlp_accepted",
            }
        )
        finding["item_results"][0].update(
            {
                "status": "working",
                "direct_assertion_passed": True,
                "evidence": [".observe/evidence/runtime.json"],
                "observed_telemetry": ["GET /checkout with http.route"],
                "product_validation": ["Captured by the local OTLP receiver."],
                "proof_mode": "full_runtime",
                "visibility": "otlp_accepted",
            }
        )

        with self.assertRaisesRegex(MODULE.ReportError, "checkout.payment"):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

    def test_item_proof_must_reference_its_exact_instrumentation_signal(self) -> None:
        raw_report = sample_report()
        raw_report["findings"][0]["expected_telemetry"].append(  # type: ignore[index]
            {
                "type": "span",
                "name": "checkout.payment",
                "attributes": ["payment.provider"],
                "product_view": "Payment trace waterfall",
            }
        )
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
        instrumentation_data["findings"][0]["telemetry_changes"].append(  # type: ignore[index]
            {
                "id": "OTEL-001.payment-span",
                "change_kind": "added",
                "change": "Added a bounded payment dependency span.",
                "type": "span",
                "name": "checkout.payment",
                "source": "payments.go:18",
                "added_attributes": ["payment.provider"],
                "product_view": "Payment trace waterfall",
                "follow_up_actions": ["Filter the trace by payment.provider."],
                "verification_scenarios": ["http.checkout.success"],
            }
        )
        instrumentation = MODULE.normalize_instrumentation(
            instrumentation_data, report, selection
        )
        verify = sample_verify(
            report, digest, MODULE.instrumentation_digest(instrumentation)
        )
        second = copy.deepcopy(verify["findings"][0]["item_results"][0])  # type: ignore[index]
        second.update(
            {
                "id": "OTEL-001.payment-span",
                "status": "working",
                "direct_assertion_passed": True,
                "observed_telemetry": ["GET /checkout with http.route"],
            }
        )
        verify["findings"][0]["item_results"].append(second)  # type: ignore[index]

        with self.assertRaisesRegex(MODULE.ReportError, "checkout.payment"):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

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
            verify["meta"].update(  # type: ignore[union-attr]
                {"workflow_mode": "instrumentation_child", "lifecycle": "final"}
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

            final_gate = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "instrumentation-final-gate",
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
            self.assertEqual(final_gate.returncode, 0, final_gate.stderr)
            self.assertIn("no executed verification failures", final_gate.stdout)

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
            self.assertIn("Telemetry change</th><th>What was observed</th><th>Status", html)
            self.assertIn(
                "The generated trace contains one SERVER span GET /checkout with "
                "http.route=/checkout.",
                html,
            )
            self.assertNotIn("mapped scenarios meet required proof", html)
            self.assertNotIn("scenarios were exercised", html)
            self.assertNotIn("Run verification.", html)
            self.assertNotIn("What changed by area", html)
            self.assertNotIn('class="executive-grid"', html)
            self.assertNotIn("Code → telemetry → product result", html)
            self.assertNotIn("telemetry-item mappings and direct proof", html)
            self.assertNotIn("Technical closure ledger", html)
            self.assertNotIn("finding-level closure rows", html)
            self.assertNotIn("Verification proof", html)
            self.assertNotIn("Scenario proof", html)
            self.assertNotIn("Item-level proof", html)
            self.assertNotIn("Instrumentation-phase checks", html)
            self.assertNotIn("Instrumentation-phase snapshot:", html)
            self.assertNotIn("Target product:", html)
            self.assertNotIn("Not checked for these telemetry changes", html)
            self.assertNotIn("Executed checks:", html)
            self.assertNotIn("No executed check failed", html)
            self.assertEqual(html.count("Splunk Observability Cloud"), 0)
            self.assertIn(
                "Local OTLP delivery and the configured telemetry explorer were checked.",
                html,
            )
            self.assertIn("You selected", html)
            self.assertNotIn("selected findings <b>", html)
            self.assertNotIn("scope <b>", html)
            self.assertNotIn("verification <b>", html)
            self.assertIn("Audit and scope report", html)
            self.assertNotIn("Approved gap closure", html)
            self.assertNotIn("Not approved; no implementation claim.", html)
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
            self.assertEqual(html_path.read_text(encoding="utf-8"), audit_html)
            self.assertNotIn("OTEL-001.http-server-span", audit_html)
            self.assertNotIn("Route trace waterfall", audit_html)

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
        self.assertIn(">Proven</strong>", selected)
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

        rendered = MODULE.render_telemetry_proof_table(implementation, proof)

        self.assertIn("Added span: entity-metric-metadata.upgrade", rendered)
        self.assertIn(
            "no saved assertion directly observed the exact span "
            "entity-metric-metadata.upgrade",
            rendered,
        )
        self.assertIn("not observed in an OTLP receiver", rendered)
        self.assertIn(">Not proven</strong>", rendered)
        self.assertNotIn("aggregate live metric delivery", rendered)
        self.assertNotIn(">Observed</strong>", rendered)

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
        self.assertIn(">Proven</strong>", selected)
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
        self.assertIn(">Proven</strong>", working_item_selected)
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
        self.assertIn("$otel-instrument: Repair the Tracer binding.", failed_selected)
        self.assertNotIn("Rerun the HTTP lifecycle scenarios", failed_selected)
        self.assertIn("How the repair is confirmed", failed_selected)
        self.assertIn("automatically runs the affected verification checks", failed_selected)
        self.assertIn("Verification only reports whether the repair worked", failed_selected)
        self.assertNotIn("Why verification is pending", failed_selected)

        repair_actions = MODULE.failed_verification_repair_actions(
            [
                "Use $otel-instrument to repair the Tracer binding.",
                "Add a Guice integration test, then rerun the affected checks.",
                "After the repair, rerun $otel-verify and save proof.",
            ]
        )
        self.assertEqual(
            repair_actions,
            [
                "$otel-instrument: Repair the Tracer binding.",
                "$otel-instrument: Add a Guice integration test",
            ],
        )

        verify["next_steps"] = [
            "Run $otel-instrument to repair the Tracer binding.",
            "After the repair, rerun $otel-verify and save proof.",
        ]
        self.assertEqual(
            MODULE.instrumentation_report_next_steps(instrumentation, verify),
            ["$otel-instrument: Repair the Tracer binding."],
        )

    def test_instrumentation_report_never_makes_child_verify_the_next_step(self) -> None:
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
        self.assertIn("verification runs automatically", no_child_steps[0])
        self.assertNotIn("$otel-verify", no_child_steps[0])
        self.assertNotIn("Run verification", no_child_steps[0])

        verify = sample_verify(
            report,
            digest,
            MODULE.instrumentation_digest(instrumentation),
        )
        verify["meta"].update(  # type: ignore[union-attr]
            {
                "result": "Not run",
                "workflow_mode": "instrumentation_child",
                "lifecycle": "final",
            }
        )
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
        self.assertIn("verification runs automatically", not_run_steps[0])
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

    def test_current_java_agent_attachment_suppresses_stale_path_blocker(self) -> None:
        verify = {
            "findings": [
                {
                    "id": "OTEL-001",
                    "status": "not_working",
                    "scenarios": [
                        {
                            "id": "runtime.preflight",
                            "status": "blocked",
                            "commands": ["test -f /opt/opentelemetry-javaagent.jar"],
                            "evidence": [
                                "/opt/opentelemetry-javaagent.jar is absent",
                                "Docker daemon is unavailable at unix:///tmp/docker.sock",
                            ],
                            "proof_mode": "not_run",
                        },
                        {
                            "id": "runtime.executed",
                            "status": "not_working",
                            "commands": [
                                "java -javaagent:/cache/splunk-otel-javaagent-2.27.0.jar -jar app.jar"
                            ],
                            "evidence": ["Splunk Java agent 2.27.0 loaded."],
                            "proof_mode": "full_runtime",
                        },
                    ],
                }
            ]
        }

        blockers = MODULE.verification_environment_blockers(verify)

        self.assertFalse(
            any("Java agent was unavailable" in label for label, _ in blockers)
        )
        self.assertTrue(any("Docker-backed" in label for label, _ in blockers))

    def test_verify_rejects_agent_provisioning_after_current_attachment(self) -> None:
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
        verify = {
            "schema_version": 1,
            "kind": "otel-verify",
            "audit_id": report["meta"]["audit_id"],
            "audit_sha256": digest,
            "instrumentation_sha256": MODULE.instrumentation_digest(instrumentation),
            "meta": {
                "service_name": "checkout",
                "date": "2026-07-20",
                "result": "Fail",
            },
            "findings": [
                {
                    "id": "OTEL-001",
                    "status": "not_working",
                    "scenarios": [
                        {
                            "id": "http.checkout.success",
                            "status": "not_working",
                            "commands": [
                                "java -javaagent:/cache/opentelemetry-javaagent-2.0.0.jar -jar app.jar"
                            ],
                            "evidence": ["The agent loaded; the app assertion failed."],
                            "observed_telemetry": [
                                "The expected GET /checkout server span with http.route was absent."
                            ],
                            "trace_ids": [],
                            "product_validation": ["No expected span was visible."],
                            "proof_mode": "full_runtime",
                            "visibility": "not_proven",
                        }
                    ],
                    "item_results": [
                        {
                            "id": "OTEL-001.http-server-span",
                            "status": "not_working",
                            "direct_assertion_passed": False,
                            "scenarios": ["http.checkout.success"],
                            "proof_mode": "full_runtime",
                            "visibility": "not_proven",
                            "evidence": ["The agent loaded; the app assertion failed."],
                            "observed_telemetry": [
                                "The expected GET /checkout server span with http.route was absent."
                            ],
                            "product_validation": ["No expected span was visible."],
                        }
                    ],
                    "remaining": ["Provide the pinned Java agent, then rerun."],
                }
            ],
            "next_steps": ["Fix the app assertion."],
        }

        with self.assertRaisesRegex(
            MODULE.ReportError, "after a current full-runtime -javaagent attachment"
        ):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

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

    def test_render_markdown_passes_legacy_validator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / "otel-audit.json"
            markdown = root / "otel.md"
            audit.write_text(json.dumps(sample_report()), encoding="utf-8")
            rendered = subprocess.run(
                [sys.executable, str(SCRIPT), "render-markdown", str(audit), "-o", str(markdown)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(rendered.returncode, 0, rendered.stderr)
            validator = SCRIPT.parents[2] / "otel-audit" / "scripts" / "validate_audit_report.py"
            validated = subprocess.run(
                [sys.executable, str(validator), str(markdown)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(validated.returncode, 0, validated.stderr)
            markdown_text = markdown.read_text(encoding="utf-8")
            self.assertIn("# Observability Report: checkout", markdown_text)
            self.assertIn(
                "**Language:** go | **Framework:** chi | **Date:** 2026-07-17",
                markdown_text,
            )
            self.assertIn("### OTel Closure Details", markdown_text)
            self.assertIn("signal-emission", markdown_text)
            self.assertIn("Decision / external handoff", markdown_text)

    def test_default_duplicate_remediation_requires_canonical_owner(self) -> None:
        report = sample_report()
        finding = report["findings"][0]
        finding["gap"] = "Two overlapping HTTP server spans can be emitted."
        finding["required_fix"] = "Remove the duplicate span."

        with self.assertRaisesRegex(
            MODULE.ReportError, "must name the canonical telemetry owner"
        ):
            MODULE.normalize_audit_report(report)

        finding["required_fix"] = (
            "Keep the agent-owned server span and remove the duplicate manual span."
        )
        normalized = MODULE.normalize_audit_report(report)
        self.assertEqual(
            normalized["findings"][0]["required_fix"],
            finding["required_fix"],
        )

    def test_finalize_audit_renders_and_validates_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observe = root / ".observe"
            observe.mkdir()
            audit = observe / "otel-audit.json"
            html = observe / "otel.html"
            markdown = observe / "otel.md"
            audit.write_text(json.dumps(sample_report()), encoding="utf-8")
            validator = (
                SCRIPT.parents[2]
                / "otel-audit"
                / "scripts"
                / "validate_audit_report.py"
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(SCRIPT),
                    "finalize-audit",
                    ".observe/otel-audit.json",
                    "--html",
                    ".observe/otel.html",
                    "--markdown",
                    ".observe/otel.md",
                    "--compat-validator",
                    str(validator),
                    "--repo-root",
                    ".",
                ],
                check=False,
                capture_output=True,
                text=True,
                cwd=root,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(result["result"], "PASS")
            self.assertEqual(result["compatibility"], "pass")
            self.assertEqual(result["findings"], 2)
            self.assertEqual(result["scenarios"], 1)
            self.assertEqual(result["audit"], str(audit.resolve()))
            self.assertEqual(result["html"], str(html.resolve()))
            self.assertEqual(result["markdown"], str(markdown.resolve()))
            self.assertEqual(
                result["links"],
                {
                    "review_report": f"[otel.html](<{html.resolve()}>)",
                    "machine_report": (
                        f"[otel-audit.json](<{audit.resolve()}>)"
                    ),
                },
            )
            self.assertTrue(html.is_file())
            self.assertTrue(markdown.is_file())
            self.assertIn("OpenTelemetry audit", html.read_text(encoding="utf-8"))
            self.assertIn(
                "# Observability Report", markdown.read_text(encoding="utf-8")
            )

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
            validator = (
                SCRIPT.parents[2]
                / "otel-audit"
                / "scripts"
                / "validate_audit_report.py"
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(SCRIPT),
                    "finalize-audit",
                    str(audit),
                    "--html",
                    str(observe / "otel.html"),
                    "--markdown",
                    str(observe / "otel.md"),
                    "--compat-validator",
                    str(validator),
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
                "findings[0].required_fix must name the canonical telemetry owner",
            ):
                self.assertIn(message, completed.stderr)

    def test_gate_has_distinct_gap_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / "otel-audit.json"
            audit.write_text(json.dumps(sample_report()), encoding="utf-8")
            blocked = subprocess.run(
                [sys.executable, str(SCRIPT), "gate", str(audit), "--fail-on", "required"],
                check=False,
                capture_output=True,
                text=True,
            )
            allowed = subprocess.run(
                [sys.executable, str(SCRIPT), "gate", str(audit), "--fail-on", "none"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_gate_rejects_structurally_blocked_v2_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / "otel-audit.json"
            output = root / "gate.json"
            data = sample_report()
            data["meta"]["status"] = "Blocked"  # type: ignore[index]
            data["scan_blockers"] = [
                {
                    "id": "BLOCK-001",
                    "check": "source-scan",
                    "blocked_scope": ["private/generated"],
                    "prerequisite": "The generated source tree is unavailable.",
                    "evidence": [".observe/evidence/source-scan.txt"],
                    "required_action": "Provide the generated source tree.",
                }
            ]
            audit.write_text(json.dumps(data), encoding="utf-8")

            blocked = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "gate",
                    str(audit),
                    "--fail-on",
                    "required",
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            validation_only = subprocess.run(
                [sys.executable, str(SCRIPT), "gate", str(audit), "--fail-on", "none"],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(blocked.returncode, 2, blocked.stderr)
            self.assertIn("BLOCKED: audit scan is incomplete", blocked.stdout)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(result["passed"])
            self.assertFalse(result["policy_evaluated"])
            self.assertEqual(result["scan_blockers"], ["BLOCK-001"])
            self.assertEqual(validation_only.returncode, 0, validation_only.stderr)
            self.assertIn("BLOCKED: audit scan is incomplete", validation_only.stdout)


if __name__ == "__main__":
    unittest.main()
