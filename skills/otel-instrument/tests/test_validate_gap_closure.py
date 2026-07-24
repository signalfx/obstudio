from __future__ import annotations

import copy
import json
import hashlib
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


VALIDATOR = Path(__file__).parents[1] / "scripts" / "validate_gap_closure.py"
SHARED_TESTS = Path(__file__).parents[2] / "references" / "tests" / "test_observe_report.py"
SHARED_SPEC = importlib.util.spec_from_file_location(
    "observe_report_test_helpers_for_gap_closure", SHARED_TESTS
)
assert SHARED_SPEC and SHARED_SPEC.loader
SHARED = importlib.util.module_from_spec(SHARED_SPEC)
sys.modules[SHARED_SPEC.name] = SHARED
SHARED_SPEC.loader.exec_module(SHARED)
REPORT_MODULE = SHARED.MODULE
VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "validate_gap_closure_module", VALIDATOR
)
assert VALIDATOR_SPEC and VALIDATOR_SPEC.loader
VALIDATOR_MODULE = importlib.util.module_from_spec(VALIDATOR_SPEC)
VALIDATOR_SPEC.loader.exec_module(VALIDATOR_MODULE)


def digest(value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()

INSTRUMENT_NO_GENAI = """# OTel Instrumentation Report: sample

**Result:** Pass

## Audit Gap Closure
| Priority | Gap | What changed | Tested | Result | Evidence / reason |
|---|---|---|---|---|---|
| required | runtime bootstrap | Added exporter | runtime.export | Working | Export test passed |

## Validation Gates
| Gate | Result |
|---|---|
| Unit tests | Pass |
"""

CANONICAL_CLOSURE_HEADER = """| Finding | What changed | Tested | Result | Evidence / reason |
|---|---|---|---|---|"""
LEGACY_CLOSURE_HEADER = """| Priority | Gap | What changed | Tested | Result | Evidence / reason |
|---|---|---|---|---|---|"""

GENAI_CLOSURE = """## GenAI Readiness Closure
| Surface | Required signals | Implemented / proven | Tests | Remaining signals | Result |
|---|---|---|---|---|---|
| Workflow/agent trace | `invoke_workflow` | Workflow span emitted with parentage | trace.success | None | Working |
| Provider/model call | `chat`; provider and model attributes | Chat span emitted with bounded attributes and parentage | chat.success | None | Working |
| Privacy/cardinality | metadata-only capture; bounded dimensions | Span dimensions are bounded | telemetry.redaction | OTLP log policy | Partial |
"""

INSTRUMENT_GENAI = INSTRUMENT_NO_GENAI.replace(
    "**Result:** Pass",
    "**Result:** Partial",
).replace("## Validation Gates", f"{GENAI_CLOSURE}\n## Validation Gates")

INCIDENT_SIGNAL_ROLES = """## Signals Changed
### Incident Readiness Signal Roles
| Surface | Exact signal | Role | Detector use / reason | Proof | Remaining owner / prerequisite |
|---|---|---|---|---|---|
| runtime bootstrap | `otel.exporter.failures` | MTTD-improving | Detect export failure | runtime.export passed | None |
"""

INSTRUMENT_INCIDENT = INSTRUMENT_NO_GENAI.replace(
    "## Audit Gap Closure", f"{INCIDENT_SIGNAL_ROLES}\n## Audit Gap Closure"
)


class ValidateGapClosureTest(unittest.TestCase):
    def canonical_audit(
        self,
        *,
        genai: bool = False,
        incident_readiness: bool = False,
        schema_version: int = 2,
        include_unselected_finding: bool = False,
    ) -> dict:
        raw = copy.deepcopy(SHARED.sample_report())
        raw["schema_version"] = schema_version
        raw["findings"][0]["area"] = "runtime bootstrap"
        if include_unselected_finding:
            raw["signal_flow"]["component_flow_map"] = (
                "service startup [GAP: runtime bootstrap]\n"
                "payment client [GAP: Payment dependency]"
            )
        else:
            raw["findings"] = [raw["findings"][0]]
            raw["signal_flow"]["component_flow_map"] = (
                "service startup [GAP: runtime bootstrap]"
            )
        if incident_readiness:
            raw["current_instrumentation"]["incident_readiness"] = [
                {
                    "area": "runtime bootstrap",
                    "status": "partial",
                    "evidence": "Exporter configured",
                    "required_signals": "otel.exporter.failures",
                    "impact": "Runtime export failures increase detection time.",
                }
            ]
        if genai:
            raw["meta"]["genai_ownership_detected"] = True
            for row in raw["evidence"]:
                if row["check"] == "GenAI ownership":
                    row["finding"] = "Yes"
                    row["source"] = "app.py; logging.py"
            raw["genai_readiness"] = [
                {
                    "surface": "Workflow/agent trace",
                    "status": "covered",
                    "evidence": "Workflow span source is present.",
                    "required_signals": "`invoke_workflow`",
                    "owner": "App-owned: app.py",
                    "acceptance_criteria": "Trace proves workflow parentage.",
                    "impact": "Workflow failures are localized.",
                },
                {
                    "surface": "Provider/model call",
                    "status": "covered",
                    "evidence": "Provider span source is present.",
                    "required_signals": "`chat`; provider and model attributes",
                    "owner": "App-owned: app.py",
                    "acceptance_criteria": "Trace proves provider attributes.",
                    "impact": "Model failures are localized.",
                },
                {
                    "surface": "Privacy/cardinality",
                    "status": "covered",
                    "evidence": "Bounded metadata policy is source-defined.",
                    "required_signals": "metadata-only capture; bounded dimensions",
                    "owner": "App-owned: logging.py",
                    "acceptance_criteria": "Sentinel export is clean.",
                    "impact": "Telemetry excludes identifiers.",
                },
            ]
        return REPORT_MODULE.normalize_audit_report(raw)

    def canonical_selection(self, audit: dict) -> dict:
        return REPORT_MODULE.normalize_selection(
            {
                "schema_version": 1,
                "kind": "otel-selection",
                "audit_id": audit["meta"]["audit_id"],
                "audit_sha256": REPORT_MODULE.audit_digest(audit),
                "requested_ids": ["OTEL-001"],
                "approved_ids": ["OTEL-001"],
            },
            audit,
        )

    def canonical_instrumentation(
        self,
        audit: dict,
        selection: dict,
    ) -> dict:
        raw = SHARED.sample_instrumentation(audit, REPORT_MODULE.audit_digest(audit))
        raw["meta"]["result"] = "Pass"
        raw["findings"][0].update(
            {
                "status": "working",
                "changes": ["Added exporter"],
                "tests": ["runtime.export"],
                "evidence": ["Export test passed"],
            }
        )
        return REPORT_MODULE.normalize_instrumentation(raw, audit, selection)

    def validate_with_json(
        self,
        instrumentation: str,
        overlay_status: str,
        overlay_result: str,
        *,
        overlay_audit_sha256: str | None = None,
        audit_schema_version: int = 2,
        stale_selection_approved_by: str | None = None,
        raw_instrumentation_extension: bool = False,
        instrumentation_json_name: str = "otel-instrumentation.json",
        include_unselected_finding: bool = False,
        incident_readiness: bool = False,
        edit_instrumentation=None,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instrumentation_path = root / "otel-instrumentation.md"
            audit_json_path = root / "otel-audit.json"
            selection_json_path = root / "otel-selection.json"
            instrumentation_json_path = root / instrumentation_json_name
            verify_json_path = root / "otel-verify.json"
            audit_json = self.canonical_audit(
                incident_readiness=incident_readiness,
                schema_version=audit_schema_version,
                include_unselected_finding=include_unselected_finding,
            )
            canonical_instrumentation = instrumentation.replace(
                LEGACY_CLOSURE_HEADER,
                CANONICAL_CLOSURE_HEADER,
            ).replace(
                "| required | runtime bootstrap |",
                f"| OTEL-001 — {audit_json['findings'][0]['title']} |",
            )
            instrumentation_path.write_text(
                canonical_instrumentation, encoding="utf-8"
            )
            selection_json = self.canonical_selection(audit_json)
            instrumentation_json = self.canonical_instrumentation(
                audit_json, selection_json
            )
            if edit_instrumentation is not None:
                edit_instrumentation(instrumentation_json)
            verify_json = SHARED.sample_verify(
                audit_json,
                REPORT_MODULE.audit_digest(audit_json),
                REPORT_MODULE.instrumentation_digest(instrumentation_json),
            )
            verify_json["meta"]["result"] = overlay_result
            verify_finding = verify_json["findings"][0]
            verify_finding["status"] = overlay_status
            if overlay_status == "working":
                verify_finding["remaining"] = []
                verify_finding["scenarios"][0].update(
                    {
                        "status": "working",
                        "evidence": [".observe/evidence/runtime.json"],
                        "observed_telemetry": [
                            "Span GET /checkout emitted with http.route=/checkout"
                        ],
                        "product_validation": [
                            "The local receiver accepted the generated trace."
                        ],
                        "proof_mode": "full_runtime",
                        "visibility": "otlp_accepted",
                    }
                )
                verify_finding["item_results"][0].update(
                    {
                        "status": "working",
                        "direct_assertion_passed": True,
                        "evidence": [".observe/evidence/runtime.json"],
                        "observed_telemetry": [
                            "Span GET /checkout emitted with http.route=/checkout"
                        ],
                        "product_validation": [
                            "The local receiver accepted the generated trace."
                        ],
                        "proof_mode": "full_runtime",
                        "visibility": "otlp_accepted",
                    }
                )
            verify_json = REPORT_MODULE.normalize_verify(
                verify_json, audit_json, selection_json, instrumentation_json
            )
            if raw_instrumentation_extension:
                instrumentation_json["producer_context"] = {
                    "note": "not part of the normalized overlay"
                }
            if stale_selection_approved_by is not None:
                selection_json["approved_by"] = stale_selection_approved_by
            if overlay_audit_sha256 is not None:
                verify_json["audit_sha256"] = overlay_audit_sha256
            audit_json_path.write_text(json.dumps(audit_json), encoding="utf-8")
            selection_json_path.write_text(
                json.dumps(selection_json), encoding="utf-8"
            )
            instrumentation_json_path.write_text(
                json.dumps(instrumentation_json), encoding="utf-8"
            )
            verify_json_path.write_text(json.dumps(verify_json), encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    str(instrumentation_path),
                    "--audit-json",
                    str(audit_json_path),
                    "--selection-json",
                    str(selection_json_path),
                    "--instrumentation-json",
                    str(instrumentation_json_path),
                    "--verify-json",
                    str(verify_json_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

    def validate_genai_with_json(
        self,
        instrumentation: str = INSTRUMENT_GENAI,
        *,
        edit_closure=None,
        write_instrumentation_json: bool = True,
        use_verify: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instrumentation_path = root / "otel-instrumentation.md"
            audit_json_path = root / "otel-audit.json"
            selection_json_path = root / "otel-selection.json"
            instrumentation_json_path = root / "otel-instrumentation.json"
            verify_json_path = root / "otel-verify.json"
            instrumentation_path.write_text(instrumentation, encoding="utf-8")
            audit_json = self.canonical_audit(genai=True)
            selection_json = self.canonical_selection(audit_json)
            closure = [
                {
                    "surface": "Workflow/agent trace",
                    "required_signals": "`invoke_workflow`",
                    "owner": "App-owned: app.py",
                    "implemented_proven": ["Workflow span emitted with parentage"],
                    "tests": ["trace.success"],
                    "evidence": [".observe/evidence/trace-success.json"],
                    "remaining_signals": [],
                    "status": "working",
                },
                {
                    "surface": "Provider/model call",
                    "required_signals": "`chat`; provider and model attributes",
                    "owner": "App-owned: app.py",
                    "implemented_proven": [
                        "Chat span emitted with bounded attributes and parentage"
                    ],
                    "tests": ["chat.success"],
                    "evidence": [".observe/evidence/chat-success.json"],
                    "remaining_signals": [],
                    "status": "working",
                },
                {
                    "surface": "Privacy/cardinality",
                    "required_signals": "metadata-only capture; bounded dimensions",
                    "owner": "App-owned: logging.py",
                    "implemented_proven": ["Span dimensions are bounded"],
                    "tests": ["telemetry.redaction"],
                    "evidence": [".observe/evidence/redaction.json"],
                    "remaining_signals": ["OTLP log policy"],
                    "status": "partial",
                },
            ]
            if edit_closure is not None:
                edit_closure(closure)
            try:
                instrumentation_json = self.canonical_instrumentation(
                    audit_json, selection_json, genai_closure=closure
                )
            except REPORT_MODULE.ReportError as error:
                return subprocess.CompletedProcess([], 1, "", f"FAIL: {error}")
            audit_json_path.write_text(json.dumps(audit_json), encoding="utf-8")
            selection_json_path.write_text(
                json.dumps(selection_json), encoding="utf-8"
            )
            if write_instrumentation_json:
                instrumentation_json_path.write_text(
                    json.dumps(instrumentation_json), encoding="utf-8"
                )
            overlay_arguments = [
                "--instrumentation-json",
                str(instrumentation_json_path),
            ]
            if use_verify:
                verify_json = SHARED.sample_verify(
                    audit_json,
                    REPORT_MODULE.audit_digest(audit_json),
                    REPORT_MODULE.instrumentation_digest(instrumentation_json),
                )
                verify_json["meta"]["result"] = "Pass"
                verify_finding = verify_json["findings"][0]
                verify_finding["status"] = "working"
                verify_finding["remaining"] = []
                verify_finding["scenarios"][0].update(
                    {
                        "status": "working",
                        "evidence": [".observe/evidence/runtime.json"],
                        "observed_telemetry": [
                            "Span GET /checkout emitted with http.route=/checkout"
                        ],
                        "product_validation": [
                            "The local receiver accepted the generated trace."
                        ],
                        "proof_mode": "full_runtime",
                        "visibility": "otlp_accepted",
                    }
                )
                verify_finding["item_results"][0].update(
                    {
                        "status": "working",
                        "direct_assertion_passed": True,
                        "evidence": [".observe/evidence/runtime.json"],
                        "observed_telemetry": [
                            "Span GET /checkout emitted with http.route=/checkout"
                        ],
                        "product_validation": [
                            "The local receiver accepted the generated trace."
                        ],
                        "proof_mode": "full_runtime",
                        "visibility": "otlp_accepted",
                    }
                )
                verify_json = REPORT_MODULE.normalize_verify(
                    verify_json, audit_json, selection_json, instrumentation_json
                )
                verify_json_path.write_text(json.dumps(verify_json), encoding="utf-8")
                overlay_arguments = [
                    "--instrumentation-json",
                    str(instrumentation_json_path),
                    "--verify-json",
                    str(verify_json_path),
                ]
            return subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    str(instrumentation_path),
                    "--audit-json",
                    str(audit_json_path),
                    "--selection-json",
                    str(selection_json_path),
                    *overlay_arguments,
                ],
                check=False,
                capture_output=True,
                text=True,
            )

    def test_json_overlay_rejects_stale_markdown_result(self) -> None:
        result = self.validate_with_json(
            INSTRUMENT_NO_GENAI,
            overlay_status="not_proven",
            overlay_result="Partial",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Markdown Result disagrees", result.stderr)

    def test_verify_overlay_uses_explicit_non_sibling_instrumentation_path(self) -> None:
        result = self.validate_with_json(
            INSTRUMENT_NO_GENAI,
            overlay_status="working",
            overlay_result="Pass",
            instrumentation_json_name="bound-implementation-overlay.json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_requires_authoritative_instrumentation_json(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(VALIDATOR),
                "otel-instrumentation.md",
                "--audit-json",
                "otel-audit.json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("--instrumentation-json", result.stderr)
        self.assertIn("required", result.stderr)

    def test_accepts_escaped_pipe_in_rendered_closure_cell(self) -> None:
        report = INSTRUMENT_NO_GENAI.replace(
            "Export test passed", r"Export test \| collector capture passed"
        )

        result = self.validate_with_json(
            report,
            overlay_status="working",
            overlay_result="Pass",
            edit_instrumentation=lambda overlay: overlay["findings"][0].__setitem__(
                "evidence", ["Export test | collector capture passed"]
            ),
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_json_overlay_rejects_stale_markdown_closure(self) -> None:
        report = INSTRUMENT_NO_GENAI.replace("**Result:** Pass", "**Result:** Partial")
        result = self.validate_with_json(
            report,
            overlay_status="not_proven",
            overlay_result="Partial",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Markdown closure disagrees", result.stderr)

    def test_json_overlay_rejects_stale_markdown_closure_content(self) -> None:
        report = INSTRUMENT_NO_GENAI.replace(
            "Added exporter", "Changed unrelated logging"
        )
        result = self.validate_with_json(
            report,
            overlay_status="working",
            overlay_result="Pass",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("closure content disagrees", result.stderr)

    def test_json_overlay_rejects_same_audit_id_with_wrong_digest(self) -> None:
        result = self.validate_with_json(
            INSTRUMENT_NO_GENAI,
            overlay_status="working",
            overlay_result="Pass",
            overlay_audit_sha256="sha256:" + "f" * 64,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("audit_sha256 does not match", result.stderr)

    def test_json_overlay_rejects_stale_exact_selection_binding(self) -> None:
        result = self.validate_with_json(
            INSTRUMENT_NO_GENAI,
            overlay_status="working",
            overlay_result="Pass",
            stale_selection_approved_by="different-reviewer",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("selection_sha256 does not match selection", result.stderr)

    def test_json_projection_accepts_bound_schema_v1_audit(self) -> None:
        result = self.validate_with_json(
            INSTRUMENT_NO_GENAI,
            overlay_status="working",
            overlay_result="Pass",
            audit_schema_version=1,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_json_projection_hashes_shared_normalized_instrumentation(self) -> None:
        result = self.validate_with_json(
            INSTRUMENT_NO_GENAI,
            overlay_status="working",
            overlay_result="Pass",
            raw_instrumentation_extension=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_json_projection_accepts_selected_subset_of_audit_findings(self) -> None:
        result = self.validate_with_json(
            INSTRUMENT_NO_GENAI,
            overlay_status="working",
            overlay_result="Pass",
            include_unselected_finding=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_blocked_verify_is_partial_when_implementation_owned_proof_exists(self) -> None:
        blocked_verify = {"meta": {"result": "Blocked"}}
        no_proof = {
            "findings": [
                {
                    "status": "not_proven",
                    "tests": [],
                    "evidence": [],
                }
            ],
        }
        self.assertEqual(
            VALIDATOR_MODULE.expected_report_result(
                no_proof, blocked_verify, verification_overlay=True
            ),
            "Blocked",
        )

        finding_proof = copy.deepcopy(no_proof)
        finding_proof["findings"][0].update(
            {
                "status": "working",
                "tests": ["go test ./..."],
                "evidence": [".observe/evidence/go-test.txt"],
            }
        )
        self.assertEqual(
            VALIDATOR_MODULE.expected_report_result(
                finding_proof, blocked_verify, verification_overlay=True
            ),
            "Partial",
        )

        for command in (
            "./gradlew test",
            "./mvnw -DskipTests=false verify",
            "dotnet test Service.Tests",
        ):
            project_native_proof = copy.deepcopy(no_proof)
            project_native_proof["findings"][0].update(
                {
                    "status": "working",
                    "tests": [command],
                    "evidence": [".observe/evidence/project-test.txt"],
                }
            )
            with self.subTest(command=command):
                self.assertTrue(
                    VALIDATOR_MODULE.has_meaningful_instrumentation_proof(
                        project_native_proof
                    )
                )
                self.assertEqual(
                    VALIDATOR_MODULE.expected_report_result(
                        project_native_proof,
                        blocked_verify,
                        verification_overlay=True,
                    ),
                    "Partial",
                )

        for command in (
            "./gradlew test --dry-run",
            "./gradlew check -x test",
            "./mvnw -DskipTests verify",
            "./mvnw verify -Dmaven.test.skip=true",
        ):
            skipped_project_proof = copy.deepcopy(no_proof)
            skipped_project_proof["findings"][0].update(
                {
                    "status": "working",
                    "tests": [command],
                    "evidence": [".observe/evidence/project-test.txt"],
                }
            )
            with self.subTest(command=command):
                self.assertFalse(
                    VALIDATOR_MODULE.has_meaningful_instrumentation_proof(
                        skipped_project_proof
                    )
                )
                self.assertEqual(
                    VALIDATOR_MODULE.expected_report_result(
                        skipped_project_proof,
                        blocked_verify,
                        verification_overlay=True,
                    ),
                    "Blocked",
                )

    def test_blocked_verify_ignores_unproven_source_refs_and_not_run_text(self) -> None:
        blocked_verify = {"meta": {"result": "Blocked"}}
        unproven = {
            "findings": [
                {
                    "status": "not_proven",
                    "tests": ["not run: Docker unavailable"],
                    "evidence": ["main.go:12"],
                }
            ],
        }

        self.assertFalse(
            VALIDATOR_MODULE.has_meaningful_instrumentation_proof(unproven)
        )
        self.assertEqual(
            VALIDATOR_MODULE.expected_report_result(
                unproven, blocked_verify, verification_overlay=True
            ),
            "Blocked",
        )

        source_only_working_label = {
            "findings": [
                {
                    "status": "working",
                    "tests": ["go test ./..."],
                    "evidence": ["main.go:12"],
                }
            ],
        }
        self.assertFalse(
            VALIDATOR_MODULE.has_meaningful_instrumentation_proof(
                source_only_working_label
            )
        )

        failed_test_label = {
            "findings": [
                {
                    "status": "working",
                    "tests": ["go test ./... failed"],
                    "evidence": [".observe/evidence/go-test.log"],
                }
            ],
        }
        self.assertFalse(
            VALIDATOR_MODULE.has_meaningful_instrumentation_proof(failed_test_label)
        )
        self.assertEqual(
            VALIDATOR_MODULE.expected_report_result(
                failed_test_label, blocked_verify, verification_overlay=True
            ),
            "Blocked",
        )

        failure_scenario_artifact = {
            "findings": [
                {
                    "status": "working",
                    "tests": ["go test ./... passed"],
                    "evidence": [".observe/evidence/http-failure.json"],
                }
            ],
        }
        self.assertTrue(
            VALIDATOR_MODULE.has_meaningful_instrumentation_proof(
                failure_scenario_artifact
            )
        )
        self.assertEqual(
            VALIDATOR_MODULE.expected_report_result(
                failure_scenario_artifact,
                blocked_verify,
                verification_overlay=True,
            ),
            "Partial",
        )

    def test_accepts_one_to_one_genai_surface_closure(self) -> None:
        result = self.validate_genai_with_json()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("3 GenAI readiness surfaces", result.stdout)

    def test_pass_rejects_partial_genai_surface(self) -> None:
        result = self.validate_genai_with_json(
            INSTRUMENT_GENAI.replace("**Result:** Partial", "**Result:** Pass"),
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Result Pass conflicts", result.stderr)

    def test_pass_rejects_unproven_audit_gap(self) -> None:
        report = INSTRUMENT_NO_GENAI.replace(
            "| Working | Export test passed |",
            "| Not proven | No runtime proof |",
        )
        result = self.validate_with_json(
            report,
            overlay_status="not_proven",
            overlay_result="Partial",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Result Pass conflicts", result.stderr)

    def test_rejects_duplicate_report_result(self) -> None:
        report = INSTRUMENT_GENAI.replace(
            "**Result:** Partial",
            "**Result:** Partial\n**Result:** Pass",
        )
        result = self.validate_genai_with_json(report)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly one valid Result declaration", result.stderr)

    def test_genai_audit_requires_closure_section(self) -> None:
        result = self.validate_genai_with_json(INSTRUMENT_NO_GENAI)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires ## GenAI Readiness Closure", result.stderr)

    def test_rejects_missing_genai_surface(self) -> None:
        missing_row = (
            "| Privacy/cardinality | metadata-only capture; bounded dimensions "
            "| Span dimensions are bounded | telemetry.redaction | OTLP log policy "
            "| Partial |\n"
        )
        result = self.validate_genai_with_json(
            INSTRUMENT_GENAI.replace(missing_row, "")
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Markdown GenAI closure disagrees", result.stderr)

    def test_rejects_changed_required_signals(self) -> None:
        result = self.validate_genai_with_json(
            INSTRUMENT_GENAI.replace(
                "`chat`; provider and model attributes",
                "`chat`",
            ),
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Markdown GenAI closure disagrees", result.stderr)

    def test_working_surface_requires_no_remaining_signals(self) -> None:
        result = self.validate_genai_with_json(
            INSTRUMENT_GENAI.replace(
                "| None | Working |",
                "| chat error proof | Working |",
            ),
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Remaining signals None", result.stderr)

    def test_non_working_surface_names_remaining_signals(self) -> None:
        result = self.validate_genai_with_json(
            INSTRUMENT_GENAI.replace(
                "| OTLP log policy | Partial |",
                "| None | Partial |",
            ),
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must name remaining signals", result.stderr)

    def test_working_surface_rejects_not_run_tests(self) -> None:
        result = self.validate_genai_with_json(
            INSTRUMENT_GENAI.replace(
                "| trace.success | None | Working |",
                "| Not run | None | Working |",
            ),
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must name executed proof", result.stderr)

    def test_working_surface_rejects_diluted_not_run_tests(self) -> None:
        result = self.validate_genai_with_json(
            INSTRUMENT_GENAI.replace(
                "| trace.success | None | Working |",
                "| Tests blocked on CI and not run yet | None | Working |",
            ),
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must name executed proof", result.stderr)

    def test_working_surface_allows_positive_proof_with_state_words(self) -> None:
        report = INSTRUMENT_GENAI.replace(
            "trace.success",
            "All pending-state and skipped-state label cases passed",
        )

        result = self.validate_genai_with_json(
            report,
            edit_closure=lambda rows: rows[0].__setitem__(
                "tests", ["All pending-state and skipped-state label cases passed"]
            ),
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_genai_closure_after_validation_gates(self) -> None:
        misplaced = INSTRUMENT_NO_GENAI + "\n" + GENAI_CLOSURE
        result = self.validate_genai_with_json(misplaced)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("before Validation Gates", result.stderr)

    def test_rejects_duplicate_genai_closure_section(self) -> None:
        duplicated = INSTRUMENT_GENAI.replace(
            "\n## Validation Gates",
            f"\n{GENAI_CLOSURE}\n## Validation Gates",
        )
        result = self.validate_genai_with_json(duplicated)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("at most one ## GenAI Readiness Closure", result.stderr)

    def test_non_genai_audit_forbids_genai_closure(self) -> None:
        result = self.validate_with_json(
            INSTRUMENT_GENAI,
            overlay_status="working",
            overlay_result="Pass",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not contain ## GenAI Readiness Closure", result.stderr)

    def test_rejects_duplicate_genai_closure_surface(self) -> None:
        row = (
            "| Privacy/cardinality | metadata-only capture; bounded dimensions "
            "| Span dimensions are bounded | telemetry.redaction | OTLP log policy "
            "| Partial |\n"
        )
        result = self.validate_genai_with_json(INSTRUMENT_GENAI.replace(row, row + row))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate GenAI closure surface", result.stderr)

    def test_rejects_extra_genai_closure_surface(self) -> None:
        extra = (
            "| Evaluation quality | evaluation event | None | ownership review "
            "| evaluator owner | Owner-mapped |\n"
        )
        report = INSTRUMENT_GENAI.replace(
            "\n## Validation Gates",
            f"{extra}\n## Validation Gates",
        )
        result = self.validate_genai_with_json(report)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Markdown GenAI closure disagrees", result.stderr)

    def test_accepts_incident_readiness_signal_role_inventory(self) -> None:
        result = self.validate_with_json(
            INSTRUMENT_INCIDENT,
            overlay_status="working",
            overlay_result="Pass",
            incident_readiness=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_incident_readiness_requires_signal_role_inventory(self) -> None:
        result = self.validate_with_json(
            INSTRUMENT_NO_GENAI,
            overlay_status="working",
            overlay_result="Pass",
            incident_readiness=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires ## Signals Changed", result.stderr)

    def test_incident_readiness_rejects_unknown_signal_role(self) -> None:
        report = INSTRUMENT_INCIDENT.replace("MTTD-improving", "diagnostic")
        result = self.validate_with_json(
            report,
            overlay_status="working",
            overlay_result="Pass",
            incident_readiness=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid Incident Readiness signal role", result.stderr)


if __name__ == "__main__":
    unittest.main()
