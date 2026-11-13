from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock


SCRIPT = Path(__file__).parents[2] / "references" / "scripts" / "observe_report.py"
SPEC = importlib.util.spec_from_file_location("observe_evidence_report", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class EvidenceReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.artifact = self.root / "receipt.json"
        self.artifact.write_bytes(b'{"record_verified": true}\n')
        self.reference = {
            "path": "receipt.json",
            "sha256": hashlib.sha256(self.artifact.read_bytes()).hexdigest(),
        }

    def control(self, **changes: Any) -> dict[str, Any]:
        result = {
            "id": "control.health",
            "scenario_id": "http.health",
            "run_id": "run.normal",
            "operation_ids": ["operation.health"],
            "phase": "received",
            "match": {"method": "GET", "outcome": "success"},
            "expected": {"record_verified": True},
        }
        result.update(changes)
        return result

    def observation(self, **changes: Any) -> dict[str, Any]:
        result = {
            "id": "observation.health",
            "run_id": "run.normal",
            "operation_id": "operation.health",
            "phase": "received",
            "method": "GET",
            "outcome": "success",
            "trace_context": {
                "state": "context",
                "trace_id": "1" * 32,
                "span_id": "2" * 16,
            },
            "facts": {"record_verified": True},
            "artifacts": [copy.deepcopy(self.reference)],
        }
        result.update(changes)
        return result

    def manifest(self, *controls: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "otel-evidence-controls",
            "controls": list(controls) or [self.control()],
        }

    def bake(
        self,
        observations: list[dict[str, Any]] | None = None,
        controls: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return MODULE.bake_evidence_report(
            self.manifest(*(controls or [self.control()])),
            [self.observation()] if observations is None else observations,
            self.root,
        )

    def test_exact_operation_receipt_bakes_working(self) -> None:
        baked = self.bake()
        self.assertEqual(baked["controls"][0]["status"], "working")

    def test_same_run_receipts_do_not_supply_another_operation(self) -> None:
        for field, wrong in [
            ("operation_id", "operation.tasks"),
            ("operation_id", "operation.mapper"),
            ("operation_id", "operation.outside"),
            ("run_id", "run.previous"),
            ("phase", "client_result"),
        ]:
            with self.subTest(field=field, wrong=wrong):
                baked = self.bake([self.observation(**{field: wrong})])
                self.assertEqual(baked["status"], "not_proven")
                self.assertEqual(baked["scenarios"][0]["trace_ids"], [])
                self.assertTrue(any(v["fact"] == "observation" for v in baked["controls"][0]["verdicts"]))

    def test_method_and_outcome_are_joint_exact_selectors(self) -> None:
        wrong = self.observation(outcome="error", facts={"record_verified": False, "span_name": "GET /tasks"})
        right = self.observation(id="observation.success", facts={"record_verified": True, "span_name": "GET /tasks"})
        self.assertEqual(self.bake([wrong])["status"], "not_proven")
        baked = self.bake([wrong, right])
        self.assertEqual(baked["status"], "working")
        self.assertEqual([r["id"] for r in baked["controls"][0]["observations"]], [right["id"]])
        for match in [{"method": "GET"}, {"outcome": "success"}]:
            with self.subTest(match=match), self.assertRaises(MODULE.ReportError):
                self.bake(controls=[self.control(match=match)])

    def test_grouped_controls_require_every_operation_and_allow_evidence_reuse(self) -> None:
        grouped = self.control(operation_ids=["operation.health", "operation.tasks"])
        controls = [grouped, self.control(id="control.resource", scenario_id="runtime.identity")]
        incomplete = self.bake(controls=controls)
        statuses = {c["id"]: c["status"] for c in incomplete["controls"]}
        self.assertEqual(statuses, {"control.health": "not_proven", "control.resource": "working"})
        complete = self.bake([
            self.observation(),
            self.observation(id="observation.tasks", operation_id="operation.tasks", trace_context={"state": "context", "trace_id": "3" * 32}),
        ], controls)
        self.assertEqual(complete["status"], "working")
        self.assertEqual(complete["scenarios"][0]["trace_ids"], ["1" * 32, "3" * 32])

    def test_partial_observations_cannot_merge_into_complete_proof(self) -> None:
        control = self.control(expected={"record_verified": True, "native_count": 1})
        rows = [
            self.observation(facts={"record_verified": True}),
            self.observation(id="observation.partial", facts={"native_count": 1}),
        ]
        self.assertEqual(self.bake(rows, [control])["status"], "not_proven")

    def test_unsampled_context_only_and_outside_context_are_distinct(self) -> None:
        for context, expected_ids in [
            ({"state": "context", "trace_id": "1" * 32, "span_id": "2" * 16}, ["1" * 32]),
            ({"state": "context", "trace_id": "1" * 32}, ["1" * 32]),
            ({"state": "none"}, []),
            ({"state": "unknown"}, []),
        ]:
            with self.subTest(context=context):
                baked = self.bake([self.observation(trace_context=context, facts={"record_verified": True, "sampled": False, "exported_spans": 0})])
                self.assertEqual(baked["status"], "working")
                self.assertEqual(baked["scenarios"][0]["trace_ids"], expected_ids)
        with self.assertRaises(MODULE.ReportError):
            self.bake([self.observation(trace_context={"state": "none", "trace_id": "1" * 32})])

    def test_invalid_context_ids_are_not_converted_into_sdk_ids(self) -> None:
        for context in [
            {"state": "context", "trace_id": "0" * 32},
            {"state": "context", "trace_id": "A" * 32},
            {"state": "context", "trace_id": "short"},
            {"state": "context", "trace_id": int("1" * 32)},
            {"state": "context", "trace_id": "1" * 32, "span_id": int("2" * 16)},
            {"state": "context", "trace_id": "1" * 32, "span_id": "0" * 16},
            {"state": "unknown", "span_id": "2" * 16},
        ]:
            with self.subTest(context=context), self.assertRaises(MODULE.ReportError):
                self.bake([self.observation(trace_context=context)])

    def test_missing_unknown_and_unexecuted_controls_do_not_pass(self) -> None:
        for facts in [{}, {"record_verified": None}, {"record_verified": "unknown"}]:
            with self.subTest(facts=facts):
                self.assertEqual(self.bake([self.observation(facts=facts)])["status"], "not_proven")
        self.assertEqual(self.bake([])["status"], "not_proven")

    def test_scalar_fact_types_are_not_coerced(self) -> None:
        for expected, actual in [(True, 1), (False, 0), (1, "1"), ("true", True)]:
            with self.subTest(expected=expected, actual=actual):
                result = self.bake([self.observation(facts={"value": actual})], [self.control(expected={"value": expected})])
                self.assertEqual(result["status"], "failed")
                self.assertNotEqual(result["controls"][0]["verdicts"][0]["expected_type"], result["controls"][0]["verdicts"][0]["actual_type"])
        for value in [[], {}, float("nan"), float("inf")]:
            with self.subTest(value=value), self.assertRaises(MODULE.ReportError):
                self.bake([self.observation(facts={"record_verified": value})])

    def test_zero_export_requires_same_operation_window_and_continuation(self) -> None:
        control = self.control(mode="zero_export", expected={"exported_records": 0})
        good = self.observation(facts={"exported_records": 0, "operation_continues": True}, window={"start": 10, "end": 20})
        self.assertEqual(self.bake([good], [control])["status"], "working")
        for change in [
            {"window": None},
            {"window": {"start": 20, "end": 10}},
            {"window": {"start": 10, "end": 10}},
            {"window": {"start": True, "end": 20}},
            {"window": {"start": 10, "end": float("inf")}},
            {"facts": {"exported_records": 0}},
            {"facts": {"exported_records": 0, "operation_continues": False}},
            {"operation_id": "operation.mapper"},
        ]:
            with self.subTest(change=change):
                row = copy.deepcopy(good)
                row.update(change)
                self.assertEqual(self.bake([row], [control])["status"], "not_proven")
        other = self.observation(id="observation.continuation", facts={"operation_continues": True}, window={"start": 10, "end": 20})
        self.assertEqual(self.bake([self.observation(facts={"exported_records": 0}), other], [control])["status"], "not_proven")

    def test_artifacts_require_existing_confined_matching_regular_files(self) -> None:
        for reference in [
            {"path": "missing.json", "sha256": self.reference["sha256"]},
            {"path": "receipt.json", "sha256": "0" * 64},
            {"path": "receipt.json", "sha256": "not-a-digest"},
            {"path": "../receipt.json", "sha256": self.reference["sha256"]},
            {"path": str(self.artifact), "sha256": self.reference["sha256"]},
            {"path": ".", "sha256": self.reference["sha256"]},
            {"path": r"C:\receipt.json", "sha256": self.reference["sha256"]},
            {"path": "receipt\x00.json", "sha256": self.reference["sha256"]},
        ]:
            with self.subTest(reference=reference), self.assertRaises(MODULE.ReportError):
                self.bake([self.observation(artifacts=[reference])])
        with self.assertRaises(MODULE.ReportError):
            self.bake([self.observation(artifacts=[])])
        linked = self.root / "linked.json"
        linked.symlink_to(self.artifact)
        with self.assertRaises(MODULE.ReportError):
            self.bake([self.observation(artifacts=[{**self.reference, "path": "linked.json"}])])

    def test_source_path_replaced_or_unlinked_during_hashing_is_rejected(self) -> None:
        original_bytes = self.artifact.read_bytes()
        original_stat = self.artifact.stat()
        original_sha256 = hashlib.sha256
        for action in ("replace", "unlink"):
            with self.subTest(action=action):
                self.artifact.write_bytes(original_bytes)
                replacement = self.root / "replacement.json"
                replacement.write_bytes(original_bytes)
                os.utime(replacement, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
                target = self.artifact

                class MutatingHash:
                    def __init__(self) -> None:
                        self.inner = original_sha256()
                        self.mutated = False

                    def update(self, block: bytes) -> None:
                        if not self.mutated:
                            self.mutated = True
                            if action == "replace":
                                os.replace(replacement, target)
                            else:
                                target.unlink()
                        self.inner.update(block)

                    def hexdigest(self) -> str:
                        return self.inner.hexdigest()

                with mock.patch.object(hashlib, "sha256", MutatingHash):
                    with self.assertRaises(MODULE.ReportError):
                        self.bake()

    def test_duplicate_and_malformed_ownership_are_rejected(self) -> None:
        with self.assertRaises(MODULE.ReportError):
            self.bake([self.observation(), self.observation()])
        with self.assertRaises(MODULE.ReportError):
            self.bake(controls=[self.control(), self.control()])
        with self.assertRaises(MODULE.ReportError):
            self.bake(controls=[self.control(operation_ids=["operation.health", "operation.health"])])
        for key in ["id", "run_id", "operation_id", "phase"]:
            for value in ([None, "", 7] if key == "id" else ["", 7]):
                with self.subTest(key=key, value=value), self.assertRaises(MODULE.ReportError):
                    self.bake([self.observation(**{key: value})])

    def test_unknown_ownership_is_visible_diagnostic_and_never_scenario_proof(self) -> None:
        for key in ["run_id", "operation_id", "phase"]:
            for value in [None, "unknown"]:
                with self.subTest(key=key, value=value):
                    row = self.observation(**{key: value})
                    baked = self.bake([row])
                    self.assertEqual(baked["status"], "not_proven")
                    self.assertEqual(baked["scenarios"][0]["trace_ids"], [])
                    self.assertEqual([d["id"] for d in baked["diagnostics"]], [row["id"]])
        row = self.observation(operation_id=None, provenance="unattributed")
        self.assertEqual(self.bake([row])["status"], "not_proven")

    def test_delivery_stages_and_persistence_are_not_inferred_from_client_success(self) -> None:
        control = self.control(expected={"accepted_records": 1})
        for facts in [
            {"sdk_result": "success", "http_status": 200},
            {"received_records": 1, "http_status": 200},
            {"received_records": 1, "acknowledged_records": 1, "acknowledgement": "decoded_conformant"},
        ]:
            with self.subTest(facts=facts):
                self.assertEqual(self.bake([self.observation(facts=facts)], [control])["status"], "not_proven")
        valid = {"received_records": 1, "acknowledged_records": 1, "accepted_records": 1, "acknowledgement": "decoded_conformant"}
        accepted = self.bake([self.observation(facts=valid)], [control])
        self.assertEqual(accepted["status"], "working")
        self.assertNotIn("persisted_records", accepted["controls"][0]["observations"][0]["facts"])
        persisted = self.control(expected={"persisted_records": 1})
        self.assertEqual(self.bake([self.observation(facts=valid)], [persisted])["status"], "not_proven")
        with self.assertRaises(MODULE.ReportError):
            self.bake([self.observation(facts={**valid, "persisted_records": 1})], [persisted])
        complete = {**valid, "persisted_records": 1, "persistence": "observed", "persistence_observed": True}
        self.assertEqual(self.bake([self.observation(facts=complete)], [persisted])["status"], "working")
        for facts in [
            {"accepted": True},
            {"accepted_records": True},
            {"accepted_records": 1, "http_status": 200},
            {"received_records": 0, "acknowledged_records": 1, "acknowledgement": "decoded_conformant"},
            {"received_records": 1, "accepted_records": 1, "acknowledgement": "decoded_conformant"},
        ]:
            with self.subTest(facts=facts), self.assertRaises(MODULE.ReportError):
                self.bake([self.observation(facts=facts)], [control])
        wrong_phase = self.observation(phase="after_release", facts=valid)
        self.assertEqual(self.bake([wrong_phase], [control])["status"], "not_proven")

    def test_bake_and_render_are_deterministic_without_mutation(self) -> None:
        controls = [self.control(id="control.z"), self.control(id="control.a", scenario_id="runtime.identity")]
        rows = [self.observation(), self.observation(id="observation.z")]
        manifest = self.manifest(*controls)
        before = copy.deepcopy((manifest, rows))
        first = MODULE.bake_evidence_report(manifest, rows, self.root)
        second = MODULE.bake_evidence_report(self.manifest(*reversed(controls)), list(reversed(rows)), self.root)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertEqual(MODULE.render_evidence_report_markdown(first), MODULE.render_evidence_report_markdown(second))
        self.assertEqual((manifest, rows), before)
        markdown = MODULE.render_evidence_report_markdown(first)
        self.assertIn("record_verified", markdown)
        self.assertIn("boolean", markdown)

    def report(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "otel-verify",
            "audit_id": "audit.unchanged",
            "audit_sha256": "audit-binding",
            "selection_sha256": "selection-binding",
            "instrumentation_sha256": "instrumentation-binding",
            "meta": {"result": "Pass", "service_name": "service"},
            "unmodeled": {"retain": [1, 2]},
            "findings": [{
                "id": "OTEL-001",
                "status": "working",
                "scenarios": [{
                    "id": "http.health",
                    "status": "working",
                    "trace_ids": ["3" * 32],
                    "proof_mode": "full_runtime",
                    "visibility": "otlp_accepted",
                    "commands": ["original command"],
                    "evidence": ["original evidence"],
                    "observed_telemetry": ["original observed signals"],
                    "product_validation": ["original visibility proof"],
                    "blocker": {"source": "retained"},
                }],
                "item_results": [{"id": "item.original", "status": "working", "proof": "retained"}],
                "remaining": [],
            }],
        }

    def test_projection_malformed_nested_inputs_raise_report_errors(self) -> None:
        baked = self.bake()
        malformed = [
            (("meta",), None),
            (("meta",), [7]),
            (("meta", "result"), {}),
            (("findings",), {}),
            (("findings", 0), 7),
            (("findings", 0, "scenarios"), None),
            (("findings", 0, "scenarios", 0), 7),
            (("findings", 0, "scenarios", 0, "proof_mode"), {}),
            (("findings", 0, "item_results"), {}),
            (("findings", 0, "item_results", 0), 7),
            (("findings", 0, "item_results", 0, "status"), {}),
            (("findings", 0, "remaining"), [7]),
        ]
        for path, value in malformed:
            report = self.report()
            target = report
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path, value=value):
                for check in (MODULE.project_evidence_report, MODULE.check_evidence_report_projection):
                    with self.assertRaises(MODULE.ReportError):
                        check(report, baked)

    def test_projection_rejects_same_run_wrong_trace_and_preserves_non_derived_fields(self) -> None:
        report = self.report()
        before = copy.deepcopy(report)
        baked = self.bake()
        errors = MODULE.check_evidence_report_projection(report, baked)
        self.assertTrue(any("http.health.trace_ids" in message for message in errors))
        projected = MODULE.project_evidence_report(report, baked)
        self.assertEqual(MODULE.check_evidence_report_projection(projected, baked), [])
        self.assertEqual(projected["findings"][0]["scenarios"][0]["trace_ids"], ["1" * 32])
        self.assertEqual(report, before)
        for key in ["schema_version", "audit_id", "audit_sha256", "selection_sha256", "instrumentation_sha256", "unmodeled"]:
            self.assertEqual(projected[key], before[key])
        old_scenario = before["findings"][0]["scenarios"][0]
        new_scenario = projected["findings"][0]["scenarios"][0]
        for key in ["proof_mode", "visibility", "commands", "evidence", "blocker"]:
            self.assertEqual(new_scenario[key], old_scenario[key])
        self.assertEqual(projected["findings"][0]["item_results"], before["findings"][0]["item_results"])

    def test_projection_downgrade_has_precise_remaining_and_does_not_promote_unproven_items(self) -> None:
        report = self.report()
        report["findings"][0]["remaining"] = ["operator-owned remaining work"]
        baked = self.bake([])
        projected = MODULE.project_evidence_report(report, baked)
        self.assertEqual(projected["meta"]["result"], "Partial")
        remaining = projected["findings"][0]["remaining"]
        self.assertIn("operator-owned remaining work", remaining)
        self.assertTrue(any("http.health" in str(reason) and "not_proven" in str(reason) for reason in remaining))
        self.assertEqual(MODULE.project_evidence_report(projected, baked), projected)
        report = self.report()
        report["findings"][0]["item_results"][0]["status"] = "not_proven"
        projected = MODULE.project_evidence_report(report, self.bake())
        self.assertEqual(projected["meta"]["result"], "Partial")
        self.assertEqual(projected["findings"][0]["item_results"][0]["status"], "not_proven")

    def test_shared_scenario_projects_each_finding_without_losing_its_own_fields(self) -> None:
        report = self.report()
        second = copy.deepcopy(report["findings"][0])
        second["id"] = "OTEL-002"
        second["scenarios"][0]["commands"] = ["second owner command"]
        second["item_results"][0]["id"] = "item.second"
        report["findings"].append(second)
        before = copy.deepcopy(report)
        baked = self.bake()
        projected = MODULE.project_evidence_report(report, baked)
        self.assertEqual(MODULE.check_evidence_report_projection(projected, baked), [])
        for finding in projected["findings"]:
            self.assertEqual(finding["scenarios"][0]["trace_ids"], ["1" * 32])
        self.assertEqual(projected["findings"][1]["scenarios"][0]["commands"], ["second owner command"])
        self.assertEqual(projected["findings"][1]["item_results"][0]["id"], "item.second")
        self.assertEqual(report, before)

    def test_shared_scenario_cannot_borrow_execution_from_another_finding(self) -> None:
        report = self.report()
        second = copy.deepcopy(report["findings"][0])
        second["id"] = "OTEL-002"
        second["scenarios"][0].update(proof_mode="not_run", evidence=[])
        report["findings"].append(second)
        with self.assertRaisesRegex(MODULE.ReportError, "executed proof"):
            MODULE.project_evidence_report(report, self.bake())

    def test_reserved_delivery_facts_reject_invalid_types_and_enum_values(self) -> None:
        invalid = [
            ("client_outcome", True), ("client_outcome", 1), ("client_outcome", "ok"),
            ("final_record_before_exit", "yes"), ("persistence_observed", "true"),
            ("operation_continues", 1),
        ]
        for key, value in invalid:
            with self.subTest(key=key, value=value), self.assertRaises(MODULE.ReportError):
                self.bake([self.observation(facts={"record_verified": True, key: value})])

    def test_failed_fact_projects_canonical_failure_without_changing_visibility(self) -> None:
        projected = MODULE.project_evidence_report(
            self.report(), self.bake([self.observation(facts={"record_verified": False})])
        )
        self.assertEqual(projected["meta"]["result"], "Fail")
        self.assertEqual(projected["findings"][0]["status"], "not_working")
        self.assertEqual(projected["findings"][0]["scenarios"][0]["status"], "not_working")
        self.assertEqual(projected["findings"][0]["scenarios"][0]["visibility"], "otlp_accepted")

    def test_projection_cannot_invent_execution_or_erase_blockers(self) -> None:
        for key, missing in [
            ("proof_mode", "not_run"),
            ("evidence", []),
            ("observed_telemetry", []),
            ("product_validation", []),
            ("visibility", "not_proven"),
        ]:
            report = self.report()
            report["findings"][0]["scenarios"][0][key] = missing
            with self.subTest(key=key), self.assertRaises(MODULE.ReportError):
                MODULE.project_evidence_report(report, self.bake())
        report = self.report()
        scenario = report["findings"][0]["scenarios"][0]
        scenario.update(status="blocked", proof_mode="not_run", visibility="not_proven", blocking_reason="receiver unavailable", unobserved_outcome="No receiver evidence")
        projected = MODULE.project_evidence_report(report, self.bake([]))
        self.assertEqual(projected["findings"][0]["scenarios"][0]["status"], "blocked")
        self.assertEqual(projected["findings"][0]["scenarios"][0]["blocking_reason"], "receiver unavailable")
        self.assertEqual(projected["findings"][0]["scenarios"][0]["unobserved_outcome"], "No receiver evidence")
        self.assertEqual(projected["meta"]["result"], "Blocked")

    def test_unmanifested_branch_cannot_keep_historical_working_claim(self) -> None:
        report = self.report()
        branch = copy.deepcopy(report["findings"][0]["scenarios"][0])
        branch["id"] = "http.error"
        report["findings"][0]["scenarios"].append(branch)
        projected = MODULE.project_evidence_report(report, self.bake())
        self.assertEqual(projected["meta"]["result"], "Partial")
        self.assertEqual(projected["findings"][0]["scenarios"][1]["status"], "not_proven")
        self.assertEqual(projected["findings"][0]["scenarios"][1]["trace_ids"], [])
        self.assertTrue(any("http.error" in str(reason) for reason in projected["findings"][0]["remaining"]))

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(SCRIPT), "evidence-bake", *arguments], text=True, capture_output=True, check=False, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})

    def test_real_cli_json_jsonl_projection_and_check_report(self) -> None:
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps(self.manifest()), encoding="utf-8")
        report = self.root / "report.json"
        original_report = json.dumps(self.report())
        report.write_text(original_report, encoding="utf-8")
        outputs = []
        for suffix, contents in [("json", json.dumps([self.observation()])), ("jsonl", json.dumps(self.observation()) + "\n")]:
            ledger = self.root / ("ledger." + suffix)
            ledger.write_text(contents, encoding="utf-8")
            output = self.root / ("baked-" + suffix + ".json")
            markdown = self.root / ("baked-" + suffix + ".md")
            projected = self.root / ("projected-" + suffix + ".json")
            base = ["--manifest", str(manifest), "--ledger", str(ledger), "--artifact-root", str(self.root), "--output", str(output), "--markdown", str(markdown)]
            result = self.run_cli(*base, "--report", str(report), "--project-output", str(projected))
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs.append((output.read_bytes(), markdown.read_bytes()))
            self.assertEqual(json.loads(output.read_text())["status"], "working")
            self.assertEqual(json.loads(projected.read_text())["findings"][0]["scenarios"][0]["trace_ids"], ["1" * 32])
            checked = self.run_cli(*base, "--check-report", str(projected))
            self.assertEqual(checked.returncode, 0, checked.stderr)
            rejected = self.run_cli(*base, "--check-report", str(report))
            self.assertEqual(rejected.returncode, 1, rejected.stderr)
            self.assertIn("http.health.trace_ids", rejected.stderr + rejected.stdout)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(report.read_text(), original_report)

    def test_real_cli_require_working_writes_truthful_missing_and_failed_reports(self) -> None:
        manifest = self.root / "manifest.json"
        ledger = self.root / "ledger.json"
        output, markdown = self.root / "gated.json", self.root / "gated.md"
        manifest.write_text(json.dumps(self.manifest()), encoding="utf-8")
        for rows, expected_status in [
            ([], "not_proven"),
            ([self.observation(facts={"record_verified": False})], "failed"),
        ]:
            with self.subTest(status=expected_status):
                ledger.write_text(json.dumps(rows), encoding="utf-8")
                result = self.run_cli(
                    "--manifest", str(manifest), "--ledger", str(ledger),
                    "--artifact-root", str(self.root), "--output", str(output),
                    "--markdown", str(markdown), "--require-working",
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("--require-working", result.stderr)
                self.assertIn(expected_status, result.stderr)
                self.assertEqual(json.loads(output.read_text())["status"], expected_status)
                self.assertIn("Result: " + expected_status, markdown.read_text())

    def test_real_cli_require_working_preserves_success_and_projection_check(self) -> None:
        manifest = self.root / "manifest.json"
        ledger = self.root / "ledger.jsonl"
        output, markdown = self.root / "gated.json", self.root / "gated.md"
        report = self.root / "report.json"
        manifest.write_text(json.dumps(self.manifest()), encoding="utf-8")
        ledger.write_text(json.dumps(self.observation()) + "\n", encoding="utf-8")
        report.write_text(json.dumps(self.report()), encoding="utf-8")
        arguments = [
            "--manifest", str(manifest), "--ledger", str(ledger),
            "--artifact-root", str(self.root), "--output", str(output),
            "--markdown", str(markdown),
        ]
        default = self.run_cli(*arguments)
        self.assertEqual(default.returncode, 0, default.stderr)
        expected_bytes = output.read_bytes(), markdown.read_bytes()
        gated = self.run_cli(*arguments, "--require-working")
        self.assertEqual(gated.returncode, 0, gated.stderr)
        self.assertEqual((output.read_bytes(), markdown.read_bytes()), expected_bytes)
        checked = self.run_cli(*arguments, "--require-working", "--check-report", str(report))
        self.assertEqual(checked.returncode, 1, checked.stderr)
        self.assertIn("http.health.trace_ids", checked.stderr)
        self.assertNotIn("--require-working", checked.stderr)
        self.assertEqual((output.read_bytes(), markdown.read_bytes()), expected_bytes)

    def test_real_cli_rejects_source_and_output_collisions_without_writes(self) -> None:
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps(self.manifest()), encoding="utf-8")
        ledger = self.root / "ledger.json"
        unrelated = self.root / "unrelated.json"
        unrelated.write_bytes(b"unrelated original receipt\n")
        other = self.observation(
            id="observation.unrelated",
            operation_id="operation.tasks",
            artifacts=[{"path": unrelated.name, "sha256": hashlib.sha256(unrelated.read_bytes()).hexdigest()}],
        )
        ledger.write_text(json.dumps([self.observation(), other]), encoding="utf-8")
        before = {p: p.read_bytes() for p in [manifest, ledger, self.artifact, unrelated]}
        for destination in [manifest, ledger, self.artifact, unrelated]:
            with self.subTest(destination=destination):
                markdown = self.root / "must-not-write.md"
                result = self.run_cli("--manifest", str(manifest), "--ledger", str(ledger), "--artifact-root", str(self.root), "--output", str(destination), "--markdown", str(markdown))
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertFalse(markdown.exists())
                for path, contents in before.items():
                    self.assertEqual(path.read_bytes(), contents)
        same = self.root / "same-output"
        result = self.run_cli("--manifest", str(manifest), "--ledger", str(ledger), "--artifact-root", str(self.root), "--output", str(same), "--markdown", str(same))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(same.exists())

    def test_real_cli_malformed_projection_and_nul_artifact_are_actionable(self) -> None:
        manifest = self.root / "manifest.json"
        ledger = self.root / "ledger.json"
        report = self.root / "invalid-report.json"
        output, markdown = self.root / "unwritten.json", self.root / "unwritten.md"
        projected = self.root / "unwritten-projection.json"
        manifest.write_text(json.dumps(self.manifest()), encoding="utf-8")
        ledger.write_text(json.dumps([self.observation()]), encoding="utf-8")
        malformed = self.report()
        malformed["findings"] = [7]
        report.write_text(json.dumps(malformed), encoding="utf-8")
        base = [
            "--manifest", str(manifest), "--ledger", str(ledger),
            "--artifact-root", str(self.root), "--output", str(output),
            "--markdown", str(markdown),
        ]
        for options in (
            ["--report", str(report), "--project-output", str(projected)],
            ["--check-report", str(report)],
        ):
            result = self.run_cli(*base, *options)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("FAIL:", result.stderr)
            self.assertIn("report.findings[0]", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(output.exists())
            self.assertFalse(markdown.exists())
            self.assertFalse(projected.exists())
        invalid = self.observation(artifacts=[{**self.reference, "path": "receipt\x00.json"}])
        ledger.write_text(json.dumps([invalid]), encoding="utf-8")
        result = self.run_cli(*base)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("NUL", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(output.exists())
        self.assertFalse(markdown.exists())

    def test_real_cli_rejects_invalid_evidence_before_creating_reports(self) -> None:
        manifest = self.root / "manifest.json"
        ledger = self.root / "ledger.jsonl"
        manifest.write_text(json.dumps(self.manifest()), encoding="utf-8")
        ledger.write_text(json.dumps(self.observation(artifacts=[{**self.reference, "sha256": "0" * 64}])) + "\n", encoding="utf-8")
        output, markdown = self.root / "unwritten.json", self.root / "unwritten.md"
        result = self.run_cli("--manifest", str(manifest), "--ledger", str(ledger), "--artifact-root", str(self.root), "--output", str(output), "--markdown", str(markdown))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(output.exists())
        self.assertFalse(markdown.exists())
        ledger.write_text(json.dumps([]), encoding="utf-8")
        result = self.run_cli("--manifest", str(manifest), "--ledger", str(ledger), "--artifact-root", str(self.root), "--output", str(output), "--markdown", str(markdown))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(output.read_text())["status"], "not_proven")


    def receipt_fixture(self, *, partial: bool = False) -> tuple[list[str], dict[str, Path]]:
        paths = {name: self.root / filename for name, filename in {
            "manifest":"manifest.json", "ledger":"ledger.jsonl", "report":"canonical.json",
            "output":"baked.json", "markdown":"baked.md", "receipt":"proof/receipt.json",
        }.items()}
        paths["receipt"].parent.mkdir(exist_ok=True)
        paths["manifest"].write_text(json.dumps(self.manifest()))
        rows = [] if partial else [self.observation()]
        paths["ledger"].write_text("".join(json.dumps(row) + "\n" for row in rows))
        report = MODULE.project_evidence_report(self.report(), self.bake(rows))
        paths["report"].write_text(json.dumps(report))
        arguments = ["--manifest", str(paths["manifest"]), "--ledger", str(paths["ledger"]),
                     "--artifact-root", str(self.root), "--output", str(paths["output"]),
                     "--markdown", str(paths["markdown"]), "--check-report", str(paths["report"]),
                     "--receipt-output", str(paths["receipt"])]
        return arguments, paths

    def direct_fixture(self, *, status: str = "working") -> tuple[list[str], dict[str, Path]]:
        args, paths = self.receipt_fixture(partial=status == "not_proven")
        if status == "failed":
            paths["ledger"].write_text(json.dumps(self.observation(facts={"record_verified": False})) + "\n")
        paths["final_markdown"] = self.root / "otel-instrumentation.md"
        paths["final_json"] = self.root / "direct-results.json"
        paths["final_markdown"].write_text("# Direct instrumentation report\nExplicit scenario results are indexed beside this report.\n")
        paths["final_json"].write_text(json.dumps({"scope": "direct application proof"}))
        index = {"schema_version": 1, "kind": "otel-direct-evidence-index",
                 "result": {"working": "Pass", "failed": "Fail", "not_proven": "Partial"}[status],
                 "reports": [{"path": paths[key].name, "sha256": hashlib.sha256(paths[key].read_bytes()).hexdigest()}
                             for key in ["final_markdown", "final_json"]],
                 "scenarios": [{"id": "http.health", "execution": "executed", "status": status,
                                "control_ids": ["control.health"]}]}
        paths["report"].write_text(json.dumps(index))
        args[args.index("--check-report")] = "--check-direct-report"
        return args, paths

    def test_direct_report_cli_binds_actual_final_files_and_exact_baked_status(self) -> None:
        for status in ["working", "failed", "not_proven"]:
            with self.subTest(status=status):
                args, paths = self.direct_fixture(status=status)
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                before = {path: path.read_bytes() for path in paths.values()}
                validation = MODULE.validate_evidence_receipt(paths["receipt"], self.root)
                self.assertEqual(validation["baked_status"], status)
                self.assertEqual(validation["direct_index"]["executed_scenarios"], 1)
                self.assertEqual(set(validation["direct_index"]["report_paths"]),
                                 {str(paths[key].resolve()) for key in ["final_markdown", "final_json"]})
                self.assertEqual({path: path.read_bytes() for path in paths.values()}, before)

    def test_eight_host_joins_cannot_cover_claimed_privacy_optout_stop_and_fault(self) -> None:
        args, paths = self.direct_fixture()
        controls = [self.control(id=f"host.{profile}.{mode}", scenario_id="workflow.logs.concurrent")
                    for profile in range(4) for mode in ["sync", "async"]]
        paths["manifest"].write_text(json.dumps(self.manifest(*controls)))
        index = json.loads(paths["report"].read_text())
        index["scenarios"] = [{"id": "workflow.logs.concurrent", "execution": "executed", "status": "working",
                               "control_ids": [control["id"] for control in controls]}]
        for sid in ["privacy", "optout", "stop", "application_fault"]:
            index["scenarios"].append({"id": sid, "execution": "executed", "status": "working",
                                       "control_ids": ["host.0.sync"]})
        paths["report"].write_text(json.dumps(index))
        result = self.run_cli(*args)
        self.assertEqual(result.returncode, 1)
        self.assertIn("scenario privacy: executed claim requires declared baked controls", result.stderr)
        self.assertFalse(paths["receipt"].exists())
        self.assertFalse(paths["output"].exists())

    def test_direct_report_rebakes_despite_forged_matching_input_hashes(self) -> None:
        args, paths = self.direct_fixture()
        self.assertEqual(self.run_cli(*args).returncode, 0)
        original = {key: paths[key].read_bytes() for key in ["report", "manifest", "ledger", "receipt"]}
        for fault in ["missing_control", "wrong_control", "duplicate_control", "wrong_scenario", "status",
                      "orphan_baked_scenario", "false_pass", "removed_observation", "control_tamper"]:
            for key, raw in original.items():
                paths[key].write_bytes(raw)
            index = json.loads(paths["report"].read_text())
            row = index["scenarios"][0]
            if fault == "missing_control":
                row["control_ids"] = []
            elif fault == "wrong_control":
                row["control_ids"] = ["other.control"]
            elif fault == "duplicate_control":
                row["control_ids"] *= 2
            elif fault == "wrong_scenario":
                row["id"] = "unrelated.scenario"
            elif fault == "status":
                row["status"] = "failed"; index["result"] = "Fail"
            elif fault == "orphan_baked_scenario":
                index["scenarios"] = [{"id": "planned", "execution": "not_run", "status": "not_proven",
                                       "control_ids": [], "reason": "Not attempted"}]
                index["result"] = "Not run"
            elif fault == "false_pass":
                index["scenarios"].append({"id": "planned", "execution": "not_run", "status": "not_proven",
                                            "control_ids": [], "reason": "Not attempted"})
            elif fault == "removed_observation":
                paths["ledger"].write_text("")
            elif fault == "control_tamper":
                manifest = json.loads(paths["manifest"].read_text())
                manifest["controls"][0]["expected"]["record_verified"] = False
                paths["manifest"].write_text(json.dumps(manifest))
            paths["report"].write_text(json.dumps(index))
            receipt = json.loads(paths["receipt"].read_text())
            for key in ["report", "manifest", "ledger"]:
                receipt[key]["sha256"] = hashlib.sha256(paths[key].read_bytes()).hexdigest()
            paths["receipt"].write_text(json.dumps(receipt))
            with self.subTest(fault=fault), self.assertRaises(MODULE.ReportError):
                MODULE.validate_evidence_receipt(paths["receipt"], self.root)

    def test_direct_final_report_drift_missing_file_and_unsafe_refs_reject(self) -> None:
        args, paths = self.direct_fixture()
        self.assertEqual(self.run_cli(*args).returncode, 0)
        for key in ["final_markdown", "final_json"]:
            raw = paths[key].read_bytes()
            paths[key].write_bytes(raw + b" changed claim")
            with self.subTest(key=key, fault="drift"), self.assertRaises(MODULE.ReportError):
                MODULE.validate_evidence_receipt(paths["receipt"], self.root)
            paths[key].unlink()
            with self.subTest(key=key, fault="missing"), self.assertRaises(MODULE.ReportError):
                MODULE.validate_evidence_receipt(paths["receipt"], self.root)
            paths[key].write_bytes(raw)
        index = json.loads(paths["report"].read_text())
        for name in ["/tmp/outside", "../outside", "C:\\outside", "bad\x00path"]:
            invalid = copy.deepcopy(index); invalid["reports"][0]["path"] = name
            paths["report"].write_text(json.dumps(invalid))
            with self.subTest(path=name), self.assertRaises(MODULE.ReportError):
                MODULE.validate_direct_evidence_index(paths["report"], self.root, self.bake())
        paths["report"].write_text(json.dumps(index))
        target = paths["final_markdown"]
        saved = target.with_suffix(".saved"); target.rename(saved); target.symlink_to(saved)
        with self.assertRaises(MODULE.ReportError):
            MODULE.validate_evidence_receipt(paths["receipt"], self.root)

    def test_direct_cli_protects_bound_reports_and_requires_one_report_mode(self) -> None:
        args, paths = self.direct_fixture()
        for key in ["final_markdown", "final_json"]:
            changed = list(args); changed[changed.index("--output") + 1] = str(paths[key])
            result = self.run_cli(*changed)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("must not overwrite inputs", result.stderr)
        result = self.run_cli(*args, "--check-report", str(paths["report"]))
        self.assertEqual(result.returncode, 1)
        self.assertIn("mutually exclusive", result.stderr)
        self.assertFalse(paths["receipt"].exists())

    def test_direct_report_changes_during_validation_cannot_be_certified(self) -> None:
        args, paths = self.direct_fixture()
        self.assertEqual(self.run_cli(*args).returncode, 0)
        core = MODULE._load_sibling("observe_report_core.py")
        real_reference = core._receipt_reference
        changed = False
        def mutate(*args: Any, **kwargs: Any) -> Any:
            nonlocal changed
            result = real_reference(*args, **kwargs)
            if not changed and args[3] == "direct_index.reports[0]":
                paths["final_markdown"].write_text("Replaced report after first hash read")
                changed = True
            return result
        with mock.patch.object(core, "_receipt_reference", side_effect=mutate), self.assertRaises(MODULE.ReportError):
            MODULE.validate_evidence_receipt(paths["receipt"], self.root)

    def test_direct_no_execution_index_changes_during_validation_reject(self) -> None:
        _, paths = self.direct_fixture()
        index = json.loads(paths["report"].read_text())
        index.update(result="Not run", scenarios=[{"id": "http.health", "execution": "not_run",
                     "status": "not_proven", "control_ids": [], "reason": "Not attempted"}])
        paths["report"].write_text(json.dumps(index))
        core = MODULE._load_sibling("observe_report_core.py")
        real_reference = core._receipt_reference
        def mutate(*args: Any, **kwargs: Any) -> Any:
            result = real_reference(*args, **kwargs)
            paths["report"].write_text(paths["report"].read_text() + " ")
            return result
        with mock.patch.object(core, "_receipt_reference", side_effect=mutate), self.assertRaises(MODULE.ReportError):
            MODULE.validate_direct_evidence_index(paths["report"], self.root)

    def test_direct_not_run_and_prerequisite_only_need_explicit_truthful_rows(self) -> None:
        _, paths = self.direct_fixture()
        index = json.loads(paths["report"].read_text())
        for execution, status, result in [("not_run", "not_proven", "Not run"),
                                           ("prerequisite_only", "blocked", "Blocked")]:
            index.update(result=result, scenarios=[{"id": "http.health", "execution": execution,
                         "status": status, "control_ids": [], "reason": "Owned receiver unavailable"}])
            paths["report"].write_text(json.dumps(index))
            validated = MODULE.validate_direct_evidence_index(paths["report"], self.root)
            self.assertEqual(validated["result"], result)
            self.assertEqual(validated["executed_scenarios"], 0)
            for fault in ["empty", "no_reason", "false_working", "hidden_control", "duplicate_scenario"]:
                invalid = copy.deepcopy(index)
                if fault == "empty":
                    invalid["scenarios"] = []
                elif fault == "no_reason":
                    invalid["scenarios"][0].pop("reason")
                elif fault == "false_working":
                    invalid["scenarios"][0]["status"] = "working"
                elif fault == "hidden_control":
                    invalid["scenarios"][0]["control_ids"] = ["control.health"]
                else:
                    invalid["scenarios"] *= 2
                paths["report"].write_text(json.dumps(invalid))
                with self.subTest(execution=execution, fault=fault), self.assertRaises(MODULE.ReportError):
                    MODULE.validate_direct_evidence_index(paths["report"], self.root)

    def test_receipt_cli_roundtrip_repeat_relative_refs_and_readonly_validation(self) -> None:
        args, p = self.receipt_fixture()
        first = self.run_cli(*args)
        self.assertEqual(first.returncode, 0, first.stderr)
        receipt = json.loads(p["receipt"].read_text())
        self.assertEqual(receipt["schema_version"], 1)
        self.assertEqual(receipt["kind"], "otel-evidence-receipt")
        self.assertEqual(receipt["manifest"]["path"], "../manifest.json")
        self.assertEqual(receipt["artifact_root"]["path"], "..")
        self.assertNotIn("timestamp", receipt)
        before = {path: path.read_bytes() for path in p.values()}
        second = self.run_cli(*args)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual({path: path.read_bytes() for path in p.values()}, before)
        validated = MODULE.validate_evidence_receipt(p["receipt"], self.root)
        self.assertEqual(validated["status"], "valid")
        self.assertEqual(validated["baked_status"], "working")
        cli = subprocess.run([sys.executable, str(SCRIPT), "validate-evidence-receipt", "--receipt", str(p["receipt"]), "--service-root", str(self.root)], text=True, capture_output=True)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(json.loads(cli.stdout), validated)
        self.assertEqual({path: path.read_bytes() for path in p.values()}, before)

    def test_receipt_flag_requires_successful_final_check_and_respects_gate(self) -> None:
        args, p = self.receipt_fixture()
        index = args.index("--check-report")
        absent = self.run_cli(*(args[:index] + args[index + 2:]))
        self.assertEqual(absent.returncode, 1)
        self.assertIn("requires --check-report", absent.stderr)
        self.assertFalse(p["receipt"].exists())
        p["report"].write_text(json.dumps(self.report()))
        drift = self.run_cli(*args)
        self.assertEqual(drift.returncode, 1)
        self.assertFalse(p["receipt"].exists())
        args, p = self.receipt_fixture(partial=True)
        gated = self.run_cli(*args, "--require-working")
        self.assertEqual(gated.returncode, 1)
        self.assertFalse(p["receipt"].exists())
        partial = self.run_cli(*args)
        self.assertEqual(partial.returncode, 0, partial.stderr)
        self.assertEqual(MODULE.validate_evidence_receipt(p["receipt"], self.root)["baked_status"], "not_proven")
        self.assertEqual(json.loads(p["report"].read_text())["meta"]["result"], "Partial")

    def test_receipt_api_rehashes_every_input_and_raw_artifact(self) -> None:
        args, p = self.receipt_fixture()
        self.assertEqual(self.run_cli(*args).returncode, 0)
        for path in [p["manifest"],p["ledger"],p["report"],self.artifact]:
            saved = path.read_bytes()
            with self.subTest(path=path):
                path.write_bytes(saved + b" ")
                with self.assertRaises(MODULE.ReportError):
                    MODULE.validate_evidence_receipt(p["receipt"], self.root)
                path.write_bytes(saved)
                path.unlink()
                with self.assertRaises(MODULE.ReportError):
                    MODULE.validate_evidence_receipt(p["receipt"], self.root)
                path.write_bytes(saved)
        receipt = json.loads(p["receipt"].read_text())
        receipt["core_sha256"] = "0" * 64
        p["receipt"].write_text(json.dumps(receipt))
        with self.assertRaises(MODULE.ReportError):
            MODULE.validate_evidence_receipt(p["receipt"], self.root)

    def test_receipt_validation_rebakes_not_only_hashes(self) -> None:
        args, p = self.receipt_fixture()
        self.assertEqual(self.run_cli(*args).returncode, 0)
        original = {path: path.read_bytes() for path in [p["manifest"],p["ledger"],p["report"],p["receipt"]]}
        for drift in ["wrong_ids", "missing_observation", "missing_required_working_scenario", "wrong_report_ids"]:
            for path, value in original.items():
                path.write_bytes(value)
            receipt = json.loads(p["receipt"].read_text())
            if drift == "wrong_ids":
                m = json.loads(p["manifest"].read_text());m["controls"][0]["scenario_id"] = "unrelated.scenario";p["manifest"].write_text(json.dumps(m))
            elif drift == "missing_observation":
                p["ledger"].write_text("")
            else:
                r = json.loads(p["report"].read_text())
                if drift == "wrong_report_ids":
                    r["findings"][0]["scenarios"][0]["id"] = "unrelated.scenario"
                else:
                    branch = copy.deepcopy(r["findings"][0]["scenarios"][0]);branch["id"] = "required.unexecuted";r["findings"][0]["scenarios"].append(branch)
                p["report"].write_text(json.dumps(r))
            for key in ["manifest","ledger","report"]:
                receipt[key]["sha256"] = hashlib.sha256(p[key].read_bytes()).hexdigest()
            p["receipt"].write_text(json.dumps(receipt))
            with self.subTest(drift=drift), self.assertRaises(MODULE.ReportError):
                MODULE.validate_evidence_receipt(p["receipt"], self.root)

    def test_receipt_validation_confines_all_refs_and_receipt_itself(self) -> None:
        args, p = self.receipt_fixture()
        self.assertEqual(self.run_cli(*args).returncode, 0)
        original = p["receipt"].read_bytes()
        with tempfile.TemporaryDirectory() as elsewhere:
            outside = Path(elsewhere) / "copy.json"
            for key in ["manifest","ledger","report","artifact_root"]:
                for spelling in [str(outside.resolve()), "../../../outside.json", "C:\\outside.json", "bad\x00path"]:
                    receipt = json.loads(original);receipt[key]["path"] = spelling;p["receipt"].write_text(json.dumps(receipt))
                    with self.subTest(key=key,path=spelling), self.assertRaises(MODULE.ReportError):
                        MODULE.validate_evidence_receipt(p["receipt"], self.root)
            p["receipt"].write_bytes(original)
            outside.write_bytes(original)
            with self.assertRaises(MODULE.ReportError):
                MODULE.validate_evidence_receipt(outside, self.root)

    def test_receipt_validation_rejects_file_and_directory_symlinks(self) -> None:
        args, p = self.receipt_fixture()
        self.assertEqual(self.run_cli(*args).returncode, 0)
        for target in [p["manifest"],p["ledger"],p["report"],self.artifact,p["receipt"]]:
            saved = target.with_name(target.name + ".saved");target.rename(saved);target.symlink_to(saved)
            with self.subTest(path=target), self.assertRaises(MODULE.ReportError):
                MODULE.validate_evidence_receipt(p["receipt"], self.root)
            target.unlink();saved.rename(target)
        original = p["receipt"].read_bytes()
        link = self.root / "link";link.symlink_to(self.root, target_is_directory=True)
        for name in ["../link/manifest.json", "../link/../" + self.root.name + "/manifest.json"]:
            receipt = json.loads(original);receipt["manifest"]["path"] = name;p["receipt"].write_text(json.dumps(receipt))
            with self.subTest(path=name), self.assertRaises(MODULE.ReportError):
                MODULE.validate_evidence_receipt(p["receipt"], self.root)

    def test_receipt_cli_preflights_all_collisions_and_symlinks_before_writes(self) -> None:
        args, p = self.receipt_fixture()
        for destination in [p["manifest"],p["ledger"],p["report"],self.artifact,p["output"],p["markdown"]]:
            changed = args[:-1] + [str(destination)]
            result = self.run_cli(*changed)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse(p["output"].exists())
            self.assertFalse(p["markdown"].exists())
        alias = self.root / "hardlink"
        os.link(self.artifact, alias)
        result = self.run_cli(*(args[:-1] + [str(alias)]))
        self.assertEqual(result.returncode, 1, result.stderr)
        alias.unlink();alias.symlink_to(self.artifact)
        result = self.run_cli(*(args[:-1] + [str(alias)]))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(p["output"].exists())
        self.assertFalse(p["markdown"].exists())
        self.assertEqual(self.artifact.read_bytes(), b'{"record_verified": true}\n')

    def test_receipt_cli_protects_unmatched_raw_artifacts_and_input_links(self) -> None:
        args, p = self.receipt_fixture()
        unused = self.root / "unused-raw.json";unused.write_bytes(b"unmatched actual raw")
        row = self.observation(id="other",operation_id="other",artifacts=[{"path":unused.name,"sha256":hashlib.sha256(unused.read_bytes()).hexdigest()}])
        p["ledger"].write_text(json.dumps(self.observation()) + "\n" + json.dumps(row) + "\n")
        result = self.run_cli(*(args[:-1] + [str(unused)]))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(p["output"].exists())
        saved = p["manifest"].with_suffix(".saved");p["manifest"].rename(saved);p["manifest"].symlink_to(saved)
        result = self.run_cli(*args)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(p["output"].exists())
        self.assertFalse(p["receipt"].exists())


    def test_receipt_rejects_malformed_schema_missing_receipt_and_symlink_root(self) -> None:
        args, p = self.receipt_fixture()
        self.assertEqual(self.run_cli(*args).returncode, 0)
        original = json.loads(p["receipt"].read_text())
        for key, value in [("schema_version",True),("schema_version",2),("kind","other"),("manifest",None),("ledger",{}),("report",[]),("artifact_root",{})]:
            invalid = copy.deepcopy(original);invalid[key] = value;p["receipt"].write_text(json.dumps(invalid))
            with self.subTest(key=key,value=value), self.assertRaises(MODULE.ReportError):
                MODULE.validate_evidence_receipt(p["receipt"], self.root)
        p["receipt"].unlink()
        with self.assertRaises(MODULE.ReportError):
            MODULE.validate_evidence_receipt(p["receipt"], self.root)
        p["receipt"].write_text("not JSON")
        with self.assertRaises(MODULE.ReportError):
            MODULE.validate_evidence_receipt(p["receipt"], self.root)
        p["receipt"].write_text(json.dumps(original))
        link = self.root / "root-link";link.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(MODULE.ReportError):
            MODULE.validate_evidence_receipt(p["receipt"], link)
        original["artifact_root"]["path"] = "../root-link"
        p["receipt"].write_text(json.dumps(original))
        with self.assertRaises(MODULE.ReportError):
            MODULE.validate_evidence_receipt(p["receipt"], self.root)

    def test_receipt_detects_inputs_changed_during_rebake(self) -> None:
        args, p = self.receipt_fixture()
        self.assertEqual(self.run_cli(*args).returncode, 0)
        core = MODULE._load_sibling("observe_report_core.py")
        real = core.bake_evidence_report
        def mutate(*args: Any, **kwargs: Any) -> dict[str, Any]:
            baked = real(*args, **kwargs)
            p["report"].write_bytes(p["report"].read_bytes() + b" ")
            return baked
        with mock.patch.object(core,"bake_evidence_report",side_effect=mutate), self.assertRaises(MODULE.ReportError):
            MODULE.validate_evidence_receipt(p["receipt"], self.root)


    def test_receipt_remains_valid_after_service_tree_relocation(self) -> None:
        args, p = self.receipt_fixture()
        self.assertEqual(self.run_cli(*args).returncode, 0)
        expected = p["receipt"].read_bytes()
        with tempfile.TemporaryDirectory() as elsewhere:
            moved = Path(elsewhere) / "relocated-service"
            shutil.copytree(self.root, moved)
            receipt = moved / p["receipt"].relative_to(self.root)
            self.assertEqual(MODULE.validate_evidence_receipt(receipt,moved)["status"], "valid")
            self.assertEqual(receipt.read_bytes(), expected)


    def test_receipt_incompatible_filesystem_roots_fail_actionably(self) -> None:
        args, p = self.receipt_fixture()
        core = MODULE._load_sibling("observe_report_core.py")
        with mock.patch.object(core.os.path,"commonpath",side_effect=ValueError("different drives")):
            with self.assertRaises(MODULE.ReportError):
                MODULE.evidence_receipt_paths([p["manifest"]],[p["receipt"]],self.root,[])
            with self.assertRaises(MODULE.ReportError):
                MODULE.create_evidence_receipt(p["manifest"],p["ledger"],p["report"],self.root,p["receipt"])


    def test_unflagged_bake_preserves_input_root_and_output_ancestor_aliases(self) -> None:
        args, p = self.receipt_fixture()
        alias = self.root / "directory-alias"
        alias.symlink_to(self.root, target_is_directory=True)
        real_output = self.root / "existing-output"
        real_output.mkdir()
        ordinary = args[:-2]  # Explicit receipt mode is opt-in.
        cases = [
            ("--manifest", str(alias / p["manifest"].name)),
            ("--artifact-root", str(alias)),
            ("--output", str(alias / real_output.name / "baked.json")),
        ]
        for option, value in cases:
            changed = list(ordinary)
            changed[changed.index(option) + 1] = value
            with self.subTest(option=option):
                baked = self.run_cli(*changed)
                self.assertEqual(baked.returncode, 0, baked.stderr)
                output = Path(changed[changed.index("--output") + 1])
                self.assertEqual(json.loads(output.read_text())["status"], "working")
                original = output.read_bytes()
                rejected = self.run_cli(*changed, "--receipt-output", str(p["receipt"]))
                self.assertEqual(rejected.returncode, 1, rejected.stderr)
                self.assertIn("symlink", rejected.stderr)
                self.assertFalse(p["receipt"].exists())
                self.assertEqual(output.read_bytes(), original)


    def test_unflagged_bake_still_rejects_hardlink_input_and_raw_collisions(self) -> None:
        args, p = self.receipt_fixture()
        ordinary = args[:-2]
        for source in [p["manifest"],self.artifact]:
            alias = self.root / "hardlink-output"
            os.link(source, alias)
            saved = source.read_bytes()
            changed = list(ordinary)
            changed[changed.index("--output") + 1] = str(alias)
            with self.subTest(source=source):
                rejected = self.run_cli(*changed)
                self.assertEqual(rejected.returncode, 1, rejected.stderr)
                self.assertIn("overwrite", rejected.stderr)
                self.assertEqual(source.read_bytes(), saved)
                self.assertFalse(p["markdown"].exists())
            alias.unlink()



if __name__ == "__main__":
    unittest.main()
