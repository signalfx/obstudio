from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import json
import hashlib
from pathlib import Path


VALIDATOR = Path(__file__).parents[1] / "scripts" / "validate_reader_report.py"
SKILL = Path(__file__).parents[1] / "SKILL.md"


def digest(value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()

REPORT = """# OTel Verification Report: sample

**Result:** Partial

## What Changed
One metric changed.

## Tested And Working

**Individual result:** 1/2 working: metrics 1/2.

| Item ID | OTel item | Type | Added or modified | Working status | How it was tested | Product result / visibility | Evidence |
|---|---|---|---|---|---|---|---|
| OTEL-001.http-duration | `http.server.request.duration` | Metric | Canonical exporter | Working | proof_mode=full_runtime; scenarios=http.duration.runtime | Route latency chart; explorer visible; visibility=explorer_visible | collector.txt |
| OTEL-002.stdout-correlation | stdout `traceId`/`spanId` correlation | Log | Canonical context | Not proven | proof_mode=app_test; scenarios=http.correlation.runtime | Log correlation not proven; visibility=not_proven | no matching record |

## Not Working Or Not Proven

| Item | State | Why | What is needed next |
|---|---|---|---|
| OTEL-002.stdout-correlation | Not proven | No matching record | Exercise a request |

## Proof
Collector output and logs.
"""


class ValidateReaderReportTest(unittest.TestCase):
    def validate(
        self,
        report: str,
        expected: str,
        instrumentation_ids: list[str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "otel-verify.md"
            expected_path = Path(directory) / "expected.txt"
            instrumentation_path = Path(directory) / "otel-instrumentation.json"
            report_path.write_text(report, encoding="utf-8")
            expected_path.write_text(expected, encoding="utf-8")
            command = [
                sys.executable,
                str(VALIDATOR),
                str(report_path),
                "--expected-items-file",
                str(expected_path),
            ]
            if instrumentation_ids is not None:
                instrumentation_path.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "kind": "otel-instrumentation",
                            "selection_sha256": "sha256:" + "b" * 64,
                            "findings": [
                                {
                                    "id": "OTEL-001",
                                    "telemetry_changes": [
                                        {"id": item_id} for item_id in instrumentation_ids
                                    ],
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                command.extend(["--instrumentation-json", str(instrumentation_path)])
            return subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )

    def test_expected_items_ignore_markdown_code_formatting(self) -> None:
        result = self.validate(
            REPORT,
            "http.server.request.duration\nstdout traceId/spanId correlation\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("2 individual OTel items", result.stdout)

    def test_skill_and_validator_reject_stale_six_column_item_contract(self) -> None:
        expected_header = (
            "| Item ID | OTel item | Type | Added or modified | Working status | "
            "How it was tested | Product result / visibility | Evidence |"
        )
        stale_header = (
            "| OTel item | Type | Added or modified | Working status | "
            "How it was tested | Evidence |"
        )
        skill = SKILL.read_text(encoding="utf-8")
        self.assertGreaterEqual(skill.count(expected_header), 2)
        self.assertNotIn(stale_header, skill)

        stale_report = """# OTel Verification Report: stale

**Result:** Pass

## What Changed
One metric changed.

## Tested And Working

**Individual result:** 1/1 working.

| OTel item | Type | Added or modified | Working status | How it was tested | Evidence |
|---|---|---|---|---|---|
| http.server.request.duration | Metric | Exporter | Working | full runtime | collector.txt |

## Not Working Or Not Proven
None

## Proof
Collector output.
"""
        result = self.validate(stale_report, "http.server.request.duration\n")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing per-OTel table with header", result.stderr)

    def test_duplicate_items_are_compared_after_normalization(self) -> None:
        duplicate = REPORT.replace(
            "| stdout `traceId`/`spanId` correlation | Log |",
            "| `http.server.request.duration` | Log |",
            1,
        )
        result = self.validate(duplicate, "http.server.request.duration\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate OTel item row", result.stderr)

    def test_escaped_pipe_inside_table_cell_is_not_a_column_separator(self) -> None:
        escaped = REPORT.replace(
            "proof_mode=full_runtime; scenarios=http.duration.runtime",
            r"proof_mode=full_runtime; scenarios=http.duration.runtime with `rg 'trace\|metric'`",
            1,
        )
        result = self.validate(
            escaped,
            "http.server.request.duration\nstdout traceId/spanId correlation\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("2 individual OTel items", result.stdout)

    def test_instrumentation_json_is_the_expected_item_authority(self) -> None:
        ids = ["OTEL-001.http-duration", "OTEL-002.stdout-correlation"]
        passed = self.validate(
            REPORT,
            "http.server.request.duration\nstdout traceId/spanId correlation\n",
            ids,
        )
        self.assertEqual(passed.returncode, 0, passed.stderr)

        missing = self.validate(
            REPORT,
            "http.server.request.duration\nstdout traceId/spanId correlation\n",
            ids + ["OTEL-003.cache-age"],
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("missing instrumentation item IDs: OTEL-003.cache-age", missing.stderr)

    def test_verify_json_is_the_exact_reader_projection_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / "otel-verify.md"
            instrumentation_path = root / "otel-instrumentation.json"
            verify_path = root / "otel-verify.json"
            report_path.write_text(REPORT, encoding="utf-8")
            instrumentation = {
                "schema_version": 1,
                "kind": "otel-instrumentation",
                "audit_id": "audit-1",
                "audit_sha256": "sha256:" + "a" * 64,
                "selection_sha256": "sha256:" + "b" * 64,
                "findings": [
                    {
                        "id": "OTEL-001",
                        "telemetry_changes": [
                            {
                                "id": "OTEL-001.http-duration",
                                "name": "http.server.request.duration",
                                "type": "Metric",
                                "change": "Canonical exporter",
                            },
                            {
                                "id": "OTEL-002.stdout-correlation",
                                "name": "stdout traceId/spanId correlation",
                                "type": "Log",
                                "change": "Canonical context",
                            },
                        ],
                    }
                ],
            }
            verification = {
                "schema_version": 1,
                "kind": "otel-verify",
                "audit_id": "audit-1",
                "audit_sha256": instrumentation["audit_sha256"],
                "instrumentation_sha256": digest(instrumentation),
                "meta": {"result": "Partial"},
                "findings": [
                    {
                        "id": "OTEL-001",
                        "item_results": [
                            {
                                "id": "OTEL-001.http-duration",
                                "status": "working",
                                "proof_mode": "full_runtime",
                                "scenarios": ["http.duration.runtime"],
                                "visibility": "explorer_visible",
                                "observed_telemetry": ["Full runtime OTLP"],
                                "product_validation": [
                                    "Route latency chart; explorer visible"
                                ],
                                "evidence": ["collector.txt"],
                            },
                            {
                                "id": "OTEL-002.stdout-correlation",
                                "status": "not_proven",
                                "proof_mode": "app_test",
                                "scenarios": ["http.correlation.runtime"],
                                "visibility": "not_proven",
                                "observed_telemetry": ["Runtime log capture"],
                                "product_validation": ["Log correlation not proven"],
                                "evidence": ["no matching record"],
                            },
                        ],
                    }
                ],
            }
            instrumentation_path.write_text(
                json.dumps(instrumentation), encoding="utf-8"
            )
            verify_path.write_text(json.dumps(verification), encoding="utf-8")
            command = [
                sys.executable,
                str(VALIDATOR),
                str(report_path),
                "--instrumentation-json",
                str(instrumentation_path),
                "--verify-json",
                str(verify_path),
            ]

            passed = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(passed.returncode, 0, passed.stderr)

            report_path.write_text(
                REPORT.replace("proof_mode=app_test", "proof_mode=static"),
                encoding="utf-8",
            )
            stale = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn("reader row disagrees", stale.stderr)

            report_path.write_text(REPORT, encoding="utf-8")
            missing_visibility = verification["findings"][0]["item_results"][0].pop(
                "visibility"
            )
            verify_path.write_text(json.dumps(verification), encoding="utf-8")
            invalid_visibility = subprocess.run(
                command, check=False, capture_output=True, text=True
            )
            self.assertNotEqual(invalid_visibility.returncode, 0)
            self.assertIn("verify visibility must be one of", invalid_visibility.stderr)
            verification["findings"][0]["item_results"][0][
                "visibility"
            ] = missing_visibility
            verify_path.write_text(json.dumps(verification), encoding="utf-8")

            instrumentation.pop("selection_sha256")
            instrumentation_path.write_text(
                json.dumps(instrumentation), encoding="utf-8"
            )
            unbound = subprocess.run(
                command, check=False, capture_output=True, text=True
            )
            self.assertNotEqual(unbound.returncode, 0)
            self.assertIn("selection_sha256 must be a canonical", unbound.stderr)

    def test_explicit_zero_item_report_requires_bound_empty_inventory(self) -> None:
        report = """# OTel Verification Report: proof-first

**Result:** Partial

## What Changed
No telemetry inventory was selected.

## Tested And Working

**Individual result:** 0/0 working.

| Item ID | OTel item | Type | Added or modified | Working status | How it was tested | Product result / visibility | Evidence |
|---|---|---|---|---|---|---|---|

No telemetry items. Selected findings are proof-first verification scope.

## Not Working Or Not Proven
None

## Proof
Finding-level scenarios remain authoritative.
"""
        bound = self.validate(report, "", [])
        self.assertEqual(bound.returncode, 0, bound.stderr)
        self.assertIn("0 individual OTel items", bound.stdout)

        unbound = self.validate(report, "")
        self.assertNotEqual(unbound.returncode, 0)
        self.assertIn("per-OTel table has no item rows", unbound.stderr)

        missing_marker = self.validate(
            report.replace(
                "No telemetry items. Selected findings are proof-first verification scope.\n",
                "",
            ),
            "",
            [],
        )
        self.assertNotEqual(missing_marker.returncode, 0)
        self.assertIn("per-OTel table has no item rows", missing_marker.stderr)

        nonempty = self.validate(report, "", ["OTEL-001.http-duration"])
        self.assertNotEqual(nonempty.returncode, 0)
        self.assertIn("per-OTel table has no item rows", nonempty.stderr)

    def test_gap_mirror_uses_exact_item_id_cells(self) -> None:
        prefixed = REPORT.replace(
            "| OTEL-002.stdout-correlation | Not proven |",
            "| OTEL-002.stdout-correlation-extra | Not proven |",
        )

        result = self.validate(
            prefixed,
            "http.server.request.duration\nstdout traceId/spanId correlation\n",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "OTEL-002.stdout-correlation: non-working item ID is missing",
            result.stderr,
        )

    def test_gap_mirror_rejects_duplicate_and_unexpected_item_ids(self) -> None:
        gap_row = (
            "| OTEL-002.stdout-correlation | Not proven | No matching record | "
            "Exercise a request |"
        )
        duplicate = self.validate(
            REPORT.replace(gap_row, f"{gap_row}\n{gap_row}"),
            "http.server.request.duration\nstdout traceId/spanId correlation\n",
        )
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn(
            "duplicate item IDs in Not Working Or Not Proven: "
            "OTEL-002.stdout-correlation",
            duplicate.stderr,
        )

        unexpected = self.validate(
            REPORT.replace(
                gap_row,
                f"{gap_row}\n| OTEL-999.unrelated | Not proven | Unrelated | "
                "Exercise another request |",
            ),
            "http.server.request.duration\nstdout traceId/spanId correlation\n",
        )
        self.assertNotEqual(unexpected.returncode, 0)
        self.assertIn(
            "unexpected item IDs in Not Working Or Not Proven: OTEL-999.unrelated",
            unexpected.stderr,
        )


if __name__ == "__main__":
    unittest.main()
