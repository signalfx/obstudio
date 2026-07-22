from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from compare_otel_reports import canonical_audit, canonical_instrument, canonical_verify, compare


class CompareOtelReportsTest(unittest.TestCase):
    def write(self, root: Path, name: str, text: str) -> Path:
        path = root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_audit_ignores_prose_dates_and_evidence_but_preserves_contract_rows(self) -> None:
        template = """# Observability Report: sample
**Date:** {date}
**Status:** Partial
**GenAI ownership detected:** No
## Executive Summary
{summary}
## Routes
| Method | Path |
|---|---|
| GET | /tasks/{{id}} |
## Current Instrumentation
### Spans
No spans detected.
### Metrics
No metrics detected.
### Logs
No OTel logs detected.
## Gaps
| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|
| required | HTTP | none | reason | fix | default | http.failure, http.success |
## Verification Plan
### Test Environments
| Environment ID | Surface | Config Evidence | Runner / Toolchain | Scope | Shared Prerequisites |
|---|---|---|---|---|---|
| go.local | API | go.mod | go test ./... | module | none |
### Acceptance Scenarios
| Scenario ID | Trigger / Path | Source Entrypoint | Expected Signals | Proof Level | Acceptance Criteria | Environment |
|---|---|---|---|---|---|---|
| http.success | GET /tasks/{{id}} | main.go | span | full runtime | one span | go.local |
## Anti-Patterns
None.
## Recommendation
Instrument it.
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = self.write(root, "before.md", template.format(date="2026-01-01", summary="Old prose."))
            after = self.write(root, "after.md", template.format(date="2026-07-09", summary="New prose."))
            result = compare("audit", before, after)
        self.assertTrue(result["equal"])

    def test_audit_detects_route_and_gap_changes(self) -> None:
        base = """# Observability Report: sample
**Status:** Partial
**GenAI ownership detected:** No
## Routes
| Method | Path |
|---|---|
| GET | {route} |
## Gaps
| Priority | Area | Instrument mode | Verification scenarios |
|---|---|---|---|
| required | HTTP | default | http.success |
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = self.write(root, "before.md", base.format(route="/tasks"))
            after = self.write(root, "after.md", base.format(route="/orders"))
            result = compare("audit", before, after)
        self.assertFalse(result["equal"])
        self.assertTrue(any("/tasks" in line for line in result["diff"]))

    def test_audit_table_backed_inventory_is_present_and_compared(self) -> None:
        template = """# Observability Report: sample
**Status:** Partial
**GenAI ownership detected:** No
## Current Instrumentation
### Spans
| Name | Source | Type |
|---|---|---|
| GET /tasks | {source} | auto |
### Metrics
No metrics detected.
### Logs
No OTel logs detected.
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = self.write(root, "before.md", template.format(source="main.go:10"))
            after = self.write(root, "after.md", template.format(source="main.go:20"))
            projection = canonical_audit(before)
            result = compare("audit", before, after)
        self.assertEqual(projection["inventory_state"]["spans"], "present")
        self.assertFalse(result["equal"])
        self.assertTrue(any("main.go:10" in line for line in result["diff"]))

    def test_instrument_projection_preserves_signal_and_gate_status(self) -> None:
        report = """# OTel Instrumentation Report: sample
**Result:** Partial
## Signals Changed
| Signal type | Added | Modified | Removed | Evidence | Verification status |
|---|---|---|---|---|---|
| Traces/spans | GET /tasks | None | None | main.go | partial |
## Audit Gap Closure
| Priority | Gap | What changed | Tested | Result | Evidence / reason |
|---|---|---|---|---|---|
| required | HTTP | middleware | test | Working | output |
## Validation Gates
| Gate | Command | Result |
|---|---|---|
| Build | go test ./... | Pass |
"""
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(Path(directory), "report.md", report)
            result = canonical_instrument(path)
        self.assertEqual(result["result"], "Partial")
        self.assertEqual(result["signals_changed"][0]["Added"], "GET /tasks")
        self.assertEqual(result["validation_gates"][0]["Result"], "Pass")

    def test_instrument_comparison_detects_previously_omitted_evidence(self) -> None:
        template = """# OTel Instrumentation Report: sample
**Result:** Partial
## Signals Changed
| Signal type | Added | Modified | Removed | Evidence | Verification status |
|---|---|---|---|---|---|
| Traces/spans | GET /tasks | None | None | {evidence} | partial |
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = self.write(root, "before.md", template.format(evidence="main.go:10"))
            after = self.write(root, "after.md", template.format(evidence="main.go:20"))
            result = compare("instrument", before, after)
        self.assertFalse(result["equal"])
        self.assertTrue(any("main.go:10" in line for line in result["diff"]))

    def test_verify_projection_preserves_item_status_and_proof_mode(self) -> None:
        report = """# OTel Verification Report: sample
**Result:** Partial
## What Changed
None.
## Tested And Working
| OTel item | Type | Added or modified | Working status | How it was tested | Evidence |
|---|---|---|---|---|---|
| HTTP server span | Span | Existing | Working | application test | output |
## Not Working Or Not Proven
| Item | State | Why | What is needed next |
|---|---|---|---|
| OTLP export | Not proven | no collector | collector |
## Proof
| Proof type | What it proves | Evidence |
|---|---|---|
| Application test | handler works | output |
"""
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(Path(directory), "report.md", report)
            result = canonical_verify(path)
        self.assertEqual(result["items"][0]["Working status"], "Working")
        self.assertEqual(result["not_working"][0]["State"], "Not proven")
        self.assertEqual(result["proof"][0]["Proof type"], "Application test")

    def test_verify_comparison_detects_added_state_and_evidence(self) -> None:
        template = """# OTel Verification Report: sample
**Result:** Partial
## Tested And Working
| OTel item | Type | Added or modified | Working status | How it was tested | Evidence |
|---|---|---|---|---|---|
| HTTP server span | Span | {state} | Working | application test | {evidence} |
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = self.write(
                root,
                "before.md",
                template.format(state="Existing", evidence="main.go:10"),
            )
            after = self.write(
                root,
                "after.md",
                template.format(state="Modified", evidence="main.go:20"),
            )
            result = compare("verify", before, after)
        self.assertFalse(result["equal"])
        self.assertTrue(any("Modified" in line for line in result["diff"]))


if __name__ == "__main__":
    unittest.main()
