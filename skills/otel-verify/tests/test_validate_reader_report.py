from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


VALIDATOR = Path(__file__).parents[1] / "scripts" / "validate_reader_report.py"

REPORT = """# OTel Verification Report: sample

**Result:** Partial

## What Changed
One metric changed.

## Tested And Working

**Individual result:** 1/2 working: metrics 1/2.

| OTel item | Type | Added or modified | Working status | How it was tested | Evidence |
|---|---|---|---|---|---|
| `http.server.request.duration` | Metric | Canonical exporter | Working | Full runtime OTLP | collector.txt |
| stdout `traceId`/`spanId` correlation | Log | Canonical context | Not proven | Runtime log capture | no matching record |

## Not Working Or Not Proven

| Item | State | Why | What is needed next |
|---|---|---|---|
| stdout `traceId`/`spanId` correlation | Not proven | No matching record | Exercise a request |

## Proof
Collector output and logs.
"""


class ValidateReaderReportTest(unittest.TestCase):
    def validate(self, report: str, expected: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "otel-verify.md"
            expected_path = Path(directory) / "expected.txt"
            report_path.write_text(report, encoding="utf-8")
            expected_path.write_text(expected, encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    str(report_path),
                    "--expected-items-file",
                    str(expected_path),
                ],
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

    def test_duplicate_items_are_compared_after_normalization(self) -> None:
        duplicate = REPORT.replace(
            "| stdout `traceId`/`spanId` correlation |",
            "| `http.server.request.duration` |",
            1,
        )
        result = self.validate(duplicate, "http.server.request.duration\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate OTel item row", result.stderr)


if __name__ == "__main__":
    unittest.main()
