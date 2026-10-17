from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "report_writer", ROOT / "skills/references/scripts/report_writer.py"
)
WRITER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WRITER)


class ReportWriterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / ".observe"
        self.directory.mkdir()
        self.inputs = ROOT / "evals/go/chi-basic/eval/inputs"
        for name in (
            "otel-audit",
            "otel-selection",
            "otel-instrumentation",
            "otel-verify",
        ):
            shutil.copyfile(
                self.inputs / (name + ".json"), self.directory / (name + ".json")
            )

    def publish(self, kind, report=None):
        name = WRITER.NAMES[kind]
        if report is None:
            report = json.loads((self.directory / name).read_text())
        return WRITER.publish(
            {"kind": kind, "repoRoot": str(self.root), "report": report, "serve": False}
        )

    def test_complete_flow_and_existing_verify_reader(self):
        audit = self.publish("audit")
        html = (self.directory / "otel.html").read_bytes()
        instrument = self.publish("instrumentation")
        verify = self.publish("verification")
        self.assertTrue(
            audit["validated"] and instrument["validated"] and verify["validated"]
        )
        self.assertEqual(html, (self.directory / "otel.html").read_bytes())
        self.assertTrue(self.publish("verification")["reused"])
        spec = importlib.util.spec_from_file_location(
            "reader", ROOT / "skills/otel-verify/scripts/validate_reader_report.py"
        )
        reader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reader)
        ids = reader.validate(
            self.directory / "otel-verify.md",
            None,
            self.directory / "otel-instrumentation.json",
            self.directory / "otel-verify.json",
            self.directory / "otel-audit.json",
            self.directory / "otel-selection.json",
        )
        expected = [
            i["id"]
            for f in json.loads(
                (self.directory / "otel-instrumentation.json").read_text()
            )["findings"]
            for i in f["telemetry_changes"]
        ]
        self.assertEqual(ids, expected)

    def test_invalid_or_stale_overlay_preserves_existing_artifacts(self):
        self.publish("verification")
        before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        data = json.loads((self.directory / "otel-verify.json").read_text())
        data["instrumentation_sha256"] = "sha256:" + "0" * 64
        with self.assertRaises(ValueError):
            self.publish("verification", data)
        self.assertEqual(
            before, {p.name: p.read_bytes() for p in self.directory.iterdir()}
        )
        data = copy.deepcopy(data)
        data["kind"] = "arbitrary"
        with self.assertRaises(ValueError):
            self.publish("verification", data)

    def test_missing_prerequisite_leaves_no_report(self):
        (self.directory / "otel-selection.json").unlink()
        with self.assertRaisesRegex(ValueError, "Missing prerequisite"):
            self.publish("verification")
        self.assertFalse((self.directory / "otel-verify.md").exists())

    def test_changed_audit_cannot_silently_rebind_downstream_proof(self):
        data = json.loads((self.directory / "otel-audit.json").read_text())
        data["summary"].append("New source evidence")
        with self.assertRaisesRegex(ValueError, "bound downstream"):
            self.publish("audit", data)

    def test_symbolic_output_and_observe_directory_are_rejected(self):
        outside = self.root / "outside"
        outside.write_text("preserve")
        (self.directory / "otel-verify.md").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symbolic"):
            self.publish("verification")
        self.assertEqual(outside.read_text(), "preserve")
        (self.directory / "otel-verify.md").unlink()
        shutil.rmtree(self.directory)
        self.directory.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symbolic"):
            self.publish("audit", {})

    def test_no_claim_that_report_publication_reproduces_evidence(self):
        result = self.publish("verification")
        self.assertIn("not independently reproduced", result["scope"])
        self.assertNotIn("findings", result)
        self.assertLess(len(json.dumps(result)), 4000)
        self.assertIn(
            str(self.directory / "otel-verify.md"), result["links"]["technical_report"]
        )

    def test_telemetry_item_projection_escapes_and_preserves_reader_contract(self):
        spec = importlib.util.spec_from_file_location(
            "samples", Path(__file__).with_name("test_observe_report.py")
        )
        samples = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(samples)
        audit = WRITER.ENGINE.normalize_audit_report(samples.sample_report())
        digest = WRITER.ENGINE.audit_digest(audit)
        selection = WRITER.ENGINE.normalize_selection(
            {
                "schema_version": 1,
                "kind": "otel-selection",
                "audit_id": audit["meta"]["audit_id"],
                "audit_sha256": digest,
                "requested_ids": ["OTEL-001"],
                "approved_ids": ["OTEL-001"],
            },
            audit,
        )
        implementation = samples.sample_instrumentation(audit, digest, selection)
        implementation["findings"][0]["telemetry_changes"][0][
            "change"
        ] = "Wrapped <handler> & kept response | behavior.\nPreserved multiline evidence."
        implementation = WRITER.ENGINE.normalize_instrumentation(
            implementation, audit, selection
        )
        verification = samples.sample_verify(
            audit, digest, WRITER.ENGINE.instrumentation_digest(implementation)
        )
        verification["findings"][0]["scenarios"][0]["trace_ids"] = ["a" * 32]
        for name, data in [
            ("otel-audit.json", audit),
            ("otel-selection.json", selection),
            ("otel-instrumentation.json", implementation),
            ("otel-verify.json", verification),
        ]:
            (self.directory / name).write_text(json.dumps(data))
        self.publish("verification")
        text = (self.directory / "otel-verify.md").read_text()
        self.assertIn("&lt;handler&gt; &amp;", text)
        self.assertNotIn("a" * 32, text)
        spec = importlib.util.spec_from_file_location(
            "reader", ROOT / "skills/otel-verify/scripts/validate_reader_report.py"
        )
        reader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reader)
        self.assertEqual(
            reader.validate(
                self.directory / "otel-verify.md",
                None,
                self.directory / "otel-instrumentation.json",
                self.directory / "otel-verify.json",
                self.directory / "otel-audit.json",
                self.directory / "otel-selection.json",
            ),
            ["OTEL-001.http-server-span"],
        )

    def test_details_survive_verification_refresh_and_server_failure_is_separate(self):
        implementation = json.loads(
            (self.directory / "otel-instrumentation.json").read_text()
        )
        result = WRITER.publish(
            {
                "kind": "instrumentation",
                "repoRoot": str(self.root),
                "report": implementation,
                "serve": False,
                "details": {
                    "supplementalEvidence": [
                        "Pinned SDK creator inspection: source and version retained."
                    ]
                },
            }
        )
        self.assertTrue(result["validated"])
        self.publish("verification")
        self.assertIn(
            "Pinned SDK creator inspection",
            (self.directory / "otel-instrumentation.md").read_text(),
        )
        audit = json.loads((self.directory / "otel-audit.json").read_text())
        with mock.patch.object(
            WRITER.ENGINE,
            "start_or_reuse_report_server",
            side_effect=WRITER.ENGINE.ReportError("loopback unavailable"),
        ):
            result = WRITER.publish(
                {"kind": "audit", "repoRoot": str(self.root), "report": audit}
            )
        self.assertTrue(result["validated"])
        self.assertFalse(result["server"]["available"])

    def test_concurrent_input_change_and_invalid_details_reject_before_mutation(self):
        audit = json.loads((self.directory / "otel-audit.json").read_text())
        original = WRITER.ENGINE.render_html

        def changed(*args):
            (self.directory / "otel-selection.json").write_text("external update")
            return original(*args)

        with mock.patch.object(WRITER.ENGINE, "render_html", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "inputs changed"):
                self.publish("audit", audit)
        self.assertFalse((self.directory / "otel.html").exists())
        with self.assertRaisesRegex(ValueError, "Invalid table rows"):
            WRITER.validate_details({"genaiClosure": [["not enough cells"]]}, audit)

    def test_genai_and_incident_reader_context_cannot_be_silently_dropped(self):
        source = ROOT / "evals/python/ai-assistant-demo/eval/inputs"
        for target, name in [
            ("otel-audit.json", "otel-audit.json"),
            ("otel-selection.json", "otel-selection-ao.json"),
            ("otel-instrumentation.json", "otel-instrumentation-ao.json"),
        ]:
            shutil.copyfile(source / name, self.directory / target)
        (self.directory / "otel-verify.json").unlink()
        with self.assertRaisesRegex(ValueError, "GenAI ownership requires"):
            self.publish("instrumentation")
        audit = json.loads((self.directory / "otel-audit.json").read_text())
        details = {
            "genaiClosure": [
                [
                    r["surface"],
                    r["required_signals"],
                    "No independent application proof",
                    "Not run; supplied proof-only fixture",
                    "Execute the mapped application scenario",
                    "Not proven",
                ]
                for r in audit["genai_readiness"]
            ],
            "incidentRoles": [
                [
                    r["area"],
                    "None",
                    "uncovered",
                    "No detector-ready proof in this fixture",
                    r["evidence"],
                    "Application owner must supply tested signals",
                ]
                for r in audit["current_instrumentation"]["incident_readiness"]
            ],
        }
        data = json.loads((self.directory / "otel-instrumentation.json").read_text())
        result = WRITER.publish(
            {
                "kind": "instrumentation",
                "repoRoot": str(self.root),
                "report": data,
                "details": details,
                "serve": False,
            }
        )
        self.assertEqual(result["reportResult"], "Partial")
        text = (self.directory / "otel-instrumentation.md").read_text()
        for row in audit["genai_readiness"]:
            self.assertIn(WRITER.cell(row["surface"]), text)
        self.assertIn("## GenAI Readiness Closure", text)

    def test_oversized_generated_view_is_rejected_before_any_report_write(self):
        before = (self.directory / "otel-audit.json").read_bytes()
        with mock.patch.object(
            WRITER,
            "audit_html",
            return_value="x" * (WRITER.MAX_REPORT_FILE_BYTES + 1),
        ):
            with self.assertRaisesRegex(ValueError, "artifact limit"):
                self.publish("audit")
        self.assertEqual(before, (self.directory / "otel-audit.json").read_bytes())
        self.assertFalse((self.directory / "otel.html").exists())

    def test_empty_item_report_prominently_preserves_bounded_proof_and_unknowns(self):
        verification = json.loads((self.directory / "otel-verify.json").read_text())
        WRITER.publish(
            {
                "kind": "verification",
                "repoRoot": str(self.root),
                "report": verification,
                "serve": False,
                "details": {
                    "summary": [
                        "Bounded fixture compatibility proof; application tests were not reproduced."
                    ],
                    "remainingGaps": [
                        "Independent correctness is unknown: the application capture witness is absent."
                    ],
                },
            }
        )
        text = (self.directory / "otel-verify.md").read_text()
        self.assertLess(
            text.index("Bounded fixture compatibility"), text.index("## What Changed")
        )
        self.assertLess(
            text.index("Independent correctness is unknown"), text.index("## Proof")
        )
        self.assertIn("0/0 item count does not establish", text)
        self.assertNotIn("\n\nNone.\n\nNone.", text)

    def test_audit_ownership_is_visible_without_opening_technical_appendix(self):
        self.publish("audit")
        text = (self.directory / "otel.html").read_text()
        declaration = text.index("GenAI ownership detected: <b>No</b>")
        self.assertLess(declaration, text.index('<section class="findings-section"'))

    def test_audit_republication_keeps_saved_and_embedded_review_scope(self):
        report = json.loads((self.directory / "otel-audit.json").read_text())
        selection = json.loads((self.directory / "otel-selection.json").read_text())
        for embedded in (False, True):
            if embedded:
                (self.directory / "otel-selection.json").unlink()
                report["review_selection"] = selection
            with mock.patch.object(
                WRITER.ENGINE, "render_html", wraps=WRITER.ENGINE.render_html
            ) as renderer:
                self.publish("audit", report)
            self.assertEqual(
                renderer.call_args.args[1]["approved_ids"], selection["approved_ids"]
            )


if __name__ == "__main__":
    unittest.main()
