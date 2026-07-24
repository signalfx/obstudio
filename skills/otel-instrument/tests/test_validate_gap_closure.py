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

AUDIT_NO_GENAI = """# OTel Audit: sample

**Status:** Partial
**GenAI ownership detected:** No

## Gaps
| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|
| required | runtime bootstrap | No exporter | No telemetry | Add exporter | default | runtime.export |
"""

GENAI_READINESS = """## GenAI Readiness
| Surface | Status | Evidence | Required Signals | Owner / Source Files | Acceptance Criteria | Detection/Localization Impact |
|---|---|---|---|---|---|---|
| Workflow/agent trace | missing | Workflow has no GenAI span | `invoke_workflow` | App-owned: app.py | Trace proves workflow parentage | Workflow failures cannot be localized |
| Provider/model call | missing | Provider call has no GenAI span | `chat`; provider and model attributes | App-owned: app.py | Trace proves model-call attributes and parentage | Model failures cannot be localized |
| Privacy/cardinality | partial | Metadata-only spans, stdout IDs remain | metadata-only capture; bounded dimensions | App-owned: logging.py | Sentinel export is clean | Telemetry may expose identifiers |
"""

AUDIT_GENAI = AUDIT_NO_GENAI.replace(
    "**GenAI ownership detected:** No",
    "**GenAI ownership detected:** Yes",
).replace("## Gaps", f"{GENAI_READINESS}\n## Gaps")

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

AUDIT_INCIDENT = AUDIT_NO_GENAI.replace(
    "## Gaps",
    """## Current Instrumentation
### Incident Readiness
| Area | Status | Evidence | Required Signals / Gap | Detection / Localization Impact |
|---|---|---|---|---|
| runtime bootstrap | partial | Exporter configured | Runtime export failures | MTTD-improving |

## Gaps""",
)

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
        self, *, genai: bool = False, schema_version: int = 2
    ) -> dict:
        raw = copy.deepcopy(SHARED.sample_report())
        raw["schema_version"] = schema_version
        raw["findings"] = [raw["findings"][0]]
        raw["findings"][0]["area"] = "runtime bootstrap"
        raw["signal_flow"]["component_flow_map"] = (
            "service startup [GAP: runtime bootstrap]"
        )
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
        *,
        genai_closure: list[dict] | None = None,
    ) -> dict:
        raw = SHARED.sample_instrumentation(audit, REPORT_MODULE.audit_digest(audit))
        genai_complete = genai_closure is None or all(
            row["status"] in {"working", "deferred", "owner_mapped"}
            for row in genai_closure
        )
        raw["meta"]["result"] = "Pass" if genai_complete else "Partial"
        raw["findings"][0].update(
            {
                "status": "working",
                "changes": ["Added exporter"],
                "tests": ["runtime.export"],
                "evidence": ["Export test passed"],
            }
        )
        if genai_closure is not None:
            raw["genai_closure"] = genai_closure
        return REPORT_MODULE.normalize_instrumentation(raw, audit, selection)

    def validate(
        self, audit: str, instrumentation: str
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit_path = root / "otel.md"
            instrumentation_path = root / "otel-instrumentation.md"
            audit_path.write_text(audit, encoding="utf-8")
            instrumentation_path.write_text(instrumentation, encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    str(audit_path),
                    str(instrumentation_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

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
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit_path = root / "otel.md"
            instrumentation_path = root / "otel-instrumentation.md"
            audit_json_path = root / "otel-audit.json"
            selection_json_path = root / "otel-selection.json"
            instrumentation_json_path = root / instrumentation_json_name
            verify_json_path = root / "otel-verify.json"
            audit_path.write_text(AUDIT_NO_GENAI, encoding="utf-8")
            instrumentation_path.write_text(instrumentation, encoding="utf-8")
            audit_json = self.canonical_audit(schema_version=audit_schema_version)
            selection_json = self.canonical_selection(audit_json)
            instrumentation_json = self.canonical_instrumentation(
                audit_json, selection_json
            )
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
                    str(audit_path),
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
            audit_path = root / "otel.md"
            instrumentation_path = root / "otel-instrumentation.md"
            audit_json_path = root / "otel-audit.json"
            selection_json_path = root / "otel-selection.json"
            instrumentation_json_path = root / "otel-instrumentation.json"
            verify_json_path = root / "otel-verify.json"
            audit_path.write_text(AUDIT_GENAI, encoding="utf-8")
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
                    str(audit_path),
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

    def test_verify_overlay_rejects_omitted_instrumentation_path(self) -> None:
        with self.assertRaisesRegex(
            SystemExit,
            "requires the exact authoritative implementation overlay through "
            "--instrumentation-json",
        ):
            VALIDATOR_MODULE.validate_json_projection(
                [],
                [],
                False,
                "Pass",
                Path("otel-audit.json"),
                Path("otel-selection.json"),
                None,
                Path("otel-verify.json"),
            )

    def test_accepts_escaped_pipe_in_rendered_closure_cell(self) -> None:
        report = INSTRUMENT_NO_GENAI.replace(
            "Export test passed", r"Export test \| collector capture passed"
        )

        result = self.validate(AUDIT_NO_GENAI, report)

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

    def test_instrumentation_json_projects_genai_closure(self) -> None:
        result = self.validate_genai_with_json()

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_verify_result_is_aggregated_with_instrumentation_genai_closure(self) -> None:
        result = self.validate_genai_with_json(use_verify=True)

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
            "genai_closure": [],
        }
        self.assertEqual(
            VALIDATOR_MODULE.expected_report_result(
                no_proof, blocked_verify, verification_overlay=True
            ),
            "Blocked",
        )

        deferred_without_proof = copy.deepcopy(no_proof)
        deferred_without_proof["genai_closure"] = [
            {
                "status": "deferred",
                "implemented_proven": [],
                "tests": [],
                "evidence": [],
                "remaining_signals": ["External owner decision"],
            }
        ]
        self.assertEqual(
            VALIDATOR_MODULE.expected_report_result(
                deferred_without_proof,
                blocked_verify,
                verification_overlay=True,
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

        genai_proof = copy.deepcopy(no_proof)
        genai_proof["genai_closure"] = [
            {
                "status": "working",
                "implemented_proven": ["Provider span emitted."],
                "tests": ["provider.success"],
                "evidence": [".observe/evidence/provider.json"],
            }
        ]
        self.assertEqual(
            VALIDATOR_MODULE.expected_report_result(
                genai_proof, blocked_verify, verification_overlay=True
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
            "genai_closure": [
                {
                    "status": "partial",
                    "implemented_proven": ["Provider call site mapped in app.py"],
                    "tests": ["tests are blocked by missing credentials"],
                    "evidence": ["app.py:42"],
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
            "genai_closure": [],
        }
        self.assertFalse(
            VALIDATOR_MODULE.has_meaningful_instrumentation_proof(
                source_only_working_label
            )
        )

        negative_artifact_label = {
            "findings": [],
            "genai_closure": [
                {
                    "status": "partial",
                    "implemented_proven": ["Provider span emitted."],
                    "tests": ["not proven"],
                    "evidence": [".observe/evidence/not-proven.log"],
                }
            ],
        }
        failed_test_label = {
            "findings": [
                {
                    "status": "working",
                    "tests": ["go test ./... failed"],
                    "evidence": [".observe/evidence/go-test.log"],
                }
            ],
            "genai_closure": [],
        }
        for candidate in (negative_artifact_label, failed_test_label):
            self.assertFalse(
                VALIDATOR_MODULE.has_meaningful_instrumentation_proof(candidate)
            )
            self.assertEqual(
                VALIDATOR_MODULE.expected_report_result(
                    candidate, blocked_verify, verification_overlay=True
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
            "genai_closure": [],
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

        configured_only_test = {
            "findings": [],
            "genai_closure": [
                {
                    "status": "partial",
                    "implemented_proven": ["span implemented"],
                    "tests": ["collector configured"],
                    "evidence": [".observe/evidence/config.json"],
                }
            ],
        }
        self.assertFalse(
            VALIDATOR_MODULE.has_meaningful_instrumentation_proof(
                configured_only_test
            )
        )
        self.assertEqual(
            VALIDATOR_MODULE.expected_report_result(
                configured_only_test, blocked_verify, verification_overlay=True
            ),
            "Blocked",
        )

    def test_blocked_verify_accepts_positive_partial_genai_proof(self) -> None:
        blocked_verify = {"meta": {"result": "Blocked"}}
        partial_genai_proof = {
            "findings": [],
            "genai_closure": [
                {
                    "status": "partial",
                    "implemented_proven": ["Provider span emitted."],
                    "tests": ["provider.success"],
                    "evidence": [".observe/evidence/provider-success.json"],
                }
            ],
        }

        self.assertTrue(
            VALIDATOR_MODULE.has_meaningful_instrumentation_proof(
                partial_genai_proof
            )
        )
        self.assertEqual(
            VALIDATOR_MODULE.expected_report_result(
                partial_genai_proof,
                blocked_verify,
                verification_overlay=True,
            ),
            "Partial",
        )

    def test_genai_fails_without_authoritative_instrumentation(self) -> None:
        result = self.validate_genai_with_json(write_instrumentation_json=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("authoritative instrumentation JSON", result.stderr)

    def test_json_overlay_rejects_stale_genai_closure_content(self) -> None:
        result = self.validate_genai_with_json(
            edit_closure=lambda rows: rows[0].__setitem__(
                "implemented_proven", ["Changed workflow proof"]
            )
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Markdown GenAI closure disagrees", result.stderr)

    def test_json_overlay_rejects_genai_closure_out_of_audit_order(self) -> None:
        result = self.validate_genai_with_json(
            edit_closure=lambda rows: rows.__setitem__(slice(0, 2), [rows[1], rows[0]])
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must match the audit in source order", result.stderr)

    def test_json_projection_joins_lists_and_maps_owner_status(self) -> None:
        report = INSTRUMENT_GENAI.replace(
            "Workflow span emitted with parentage | trace.success",
            "Workflow span emitted; Parentage proven | trace.success; trace.parentage",
        ).replace("| OTLP log policy | Partial |", "| OTLP log policy | Owner-mapped |")
        report = report.replace("**Result:** Partial", "**Result:** Pass")

        def edit(rows) -> None:
            rows[0]["implemented_proven"] = ["Workflow span emitted", "Parentage proven"]
            rows[0]["tests"] = ["trace.success", "trace.parentage"]
            rows[2]["status"] = "owner_mapped"

        result = self.validate_genai_with_json(report, edit_closure=edit)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_json_projection_allows_empty_nonworking_proof_lists(self) -> None:
        old_row = (
            "| Privacy/cardinality | metadata-only capture; bounded dimensions "
            "| Span dimensions are bounded | telemetry.redaction | OTLP log policy | Partial |"
        )
        new_row = (
            "| Privacy/cardinality | metadata-only capture; bounded dimensions "
            "|  |  | OTLP log policy | Owner-mapped |"
        )
        report = INSTRUMENT_GENAI.replace(old_row, new_row)
        report = report.replace("**Result:** Partial", "**Result:** Pass")

        def edit(rows) -> None:
            rows[2]["implemented_proven"] = []
            rows[2]["tests"] = []
            rows[2]["evidence"] = []
            rows[2]["status"] = "owner_mapped"

        result = self.validate_genai_with_json(report, edit_closure=edit)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepts_one_to_one_genai_surface_closure(self) -> None:
        result = self.validate(AUDIT_GENAI, INSTRUMENT_GENAI)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("3 GenAI readiness surfaces", result.stdout)

    def test_pass_rejects_partial_genai_surface(self) -> None:
        result = self.validate(
            AUDIT_GENAI,
            INSTRUMENT_GENAI.replace("**Result:** Partial", "**Result:** Pass"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Result Pass conflicts", result.stderr)

    def test_pass_rejects_unproven_audit_gap(self) -> None:
        report = INSTRUMENT_NO_GENAI.replace(
            "| Working | Export test passed |",
            "| Not proven | No runtime proof |",
        )
        result = self.validate(AUDIT_NO_GENAI, report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Result Pass conflicts", result.stderr)

    def test_rejects_duplicate_report_result(self) -> None:
        report = INSTRUMENT_GENAI.replace(
            "**Result:** Partial",
            "**Result:** Partial\n**Result:** Pass",
        )
        result = self.validate(AUDIT_GENAI, report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly one valid Result declaration", result.stderr)

    def test_genai_audit_requires_closure_section(self) -> None:
        result = self.validate(AUDIT_GENAI, INSTRUMENT_NO_GENAI)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires ## GenAI Readiness Closure", result.stderr)

    def test_rejects_missing_genai_surface(self) -> None:
        missing_row = (
            "| Privacy/cardinality | metadata-only capture; bounded dimensions "
            "| Span dimensions are bounded | telemetry.redaction | OTLP log policy "
            "| Partial |\n"
        )
        result = self.validate(
            AUDIT_GENAI,
            INSTRUMENT_GENAI.replace(missing_row, ""),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing=['Privacy/cardinality']", result.stderr)

    def test_rejects_changed_required_signals(self) -> None:
        result = self.validate(
            AUDIT_GENAI,
            INSTRUMENT_GENAI.replace(
                "`chat`; provider and model attributes",
                "`chat`",
            ),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("required signals changed", result.stderr)

    def test_working_surface_requires_no_remaining_signals(self) -> None:
        result = self.validate(
            AUDIT_GENAI,
            INSTRUMENT_GENAI.replace(
                "| None | Working |",
                "| chat error proof | Working |",
            ),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Remaining signals None", result.stderr)

    def test_non_working_surface_names_remaining_signals(self) -> None:
        result = self.validate(
            AUDIT_GENAI,
            INSTRUMENT_GENAI.replace(
                "| OTLP log policy | Partial |",
                "| None | Partial |",
            ),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must name remaining signals", result.stderr)

    def test_working_surface_rejects_not_run_tests(self) -> None:
        result = self.validate(
            AUDIT_GENAI,
            INSTRUMENT_GENAI.replace(
                "| trace.success | None | Working |",
                "| Not run | None | Working |",
            ),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must name executed proof", result.stderr)

    def test_working_surface_rejects_diluted_not_run_tests(self) -> None:
        result = self.validate(
            AUDIT_GENAI,
            INSTRUMENT_GENAI.replace(
                "| trace.success | None | Working |",
                "| Tests blocked on CI and not run yet | None | Working |",
            ),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must name executed proof", result.stderr)

    def test_working_surface_allows_positive_proof_with_state_words(self) -> None:
        report = INSTRUMENT_GENAI.replace(
            "Both spans emitted with parentage",
            "All spans emitted with parentage; none missing",
        ).replace(
            "trace.success",
            "All pending-state and skipped-state label cases passed",
        )
        result = self.validate(AUDIT_GENAI, report)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_empty_genai_readiness_table(self) -> None:
        empty = AUDIT_GENAI.replace(
            "| Workflow/agent trace | missing | Workflow has no GenAI span | `invoke_workflow` | App-owned: app.py | Trace proves workflow parentage | Workflow failures cannot be localized |\n",
            "",
        ).replace(
            "| Provider/model call | missing | Provider call has no GenAI span | `chat`; provider and model attributes | App-owned: app.py | Trace proves model-call attributes and parentage | Model failures cannot be localized |\n",
            "",
        ).replace(
            "| Privacy/cardinality | partial | Metadata-only spans, stdout IDs remain | metadata-only capture; bounded dimensions | App-owned: logging.py | Sentinel export is clean | Telemetry may expose identifiers |\n",
            "",
        )
        result = self.validate(empty, INSTRUMENT_GENAI)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("at least one surface row", result.stderr)

    def test_rejects_genai_closure_after_validation_gates(self) -> None:
        misplaced = INSTRUMENT_NO_GENAI + "\n" + GENAI_CLOSURE
        result = self.validate(AUDIT_GENAI, misplaced)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("before Validation Gates", result.stderr)

    def test_rejects_duplicate_genai_closure_section(self) -> None:
        duplicated = INSTRUMENT_GENAI.replace(
            "\n## Validation Gates",
            f"\n{GENAI_CLOSURE}\n## Validation Gates",
        )
        result = self.validate(AUDIT_GENAI, duplicated)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("at most one ## GenAI Readiness Closure", result.stderr)

    def test_non_genai_audit_forbids_genai_closure(self) -> None:
        result = self.validate(AUDIT_NO_GENAI, INSTRUMENT_GENAI)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not contain ## GenAI Readiness Closure", result.stderr)

    def test_requires_source_audit_genai_ownership_declaration(self) -> None:
        incomplete = AUDIT_GENAI.replace(
            "**GenAI ownership detected:** Yes\n",
            "",
        )
        result = self.validate(incomplete, INSTRUMENT_GENAI)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly one GenAI ownership declaration", result.stderr)

    def test_rejects_duplicate_genai_closure_surface(self) -> None:
        row = (
            "| Privacy/cardinality | metadata-only capture; bounded dimensions "
            "| Span dimensions are bounded | telemetry.redaction | OTLP log policy "
            "| Partial |\n"
        )
        result = self.validate(
            AUDIT_GENAI,
            INSTRUMENT_GENAI.replace(row, row + row),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate GenAI closure surface", result.stderr)

    def test_rejects_duplicate_audit_genai_surface(self) -> None:
        row = (
            "| Privacy/cardinality | partial | Metadata-only spans, stdout IDs remain "
            "| metadata-only capture; bounded dimensions | App-owned: logging.py "
            "| Sentinel export is clean | Telemetry may expose identifiers |\n"
        )
        result = self.validate(
            AUDIT_GENAI.replace(row, row + row),
            INSTRUMENT_GENAI,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate audit GenAI readiness surface", result.stderr)

    def test_rejects_extra_genai_closure_surface(self) -> None:
        extra = (
            "| Evaluation quality | evaluation event | None | ownership review "
            "| evaluator owner | Owner-mapped |\n"
        )
        report = INSTRUMENT_GENAI.replace(
            "\n## Validation Gates",
            f"{extra}\n## Validation Gates",
        )
        result = self.validate(AUDIT_GENAI, report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("extra=['Evaluation quality']", result.stderr)

    def test_accepts_incident_readiness_signal_role_inventory(self) -> None:
        result = self.validate(AUDIT_INCIDENT, INSTRUMENT_INCIDENT)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_incident_readiness_requires_signal_role_inventory(self) -> None:
        result = self.validate(AUDIT_INCIDENT, INSTRUMENT_NO_GENAI)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires ## Signals Changed", result.stderr)

    def test_incident_readiness_rejects_unknown_signal_role(self) -> None:
        report = INSTRUMENT_INCIDENT.replace("MTTD-improving", "diagnostic")
        result = self.validate(AUDIT_INCIDENT, report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid Incident Readiness signal role", result.stderr)


if __name__ == "__main__":
    unittest.main()
