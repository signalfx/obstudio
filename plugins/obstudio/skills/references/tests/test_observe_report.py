from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace
from unittest import mock

from observe_report_fixtures import (
    MODULE,
    SCRIPT,
    sample_instrumentation,
    sample_report,
    sample_splunk_agent_observability_report,
    sample_verify,
)


class ObserveReportTest(unittest.TestCase):
    def test_split_modules_are_reexported_and_share_one_core(self) -> None:
        core = MODULE._load_sibling("observe_report_core.py")
        html_module = MODULE._load_sibling("observe_report_html.py")
        self.assertIs(html_module._core, core)
        for part in (core, html_module):
            for name, value in vars(part).items():
                if name.startswith("_"):
                    continue
                with self.subTest(name=name):
                    self.assertIs(getattr(MODULE, name), value)

    def test_markdown_web_link_targets_loopback_report(self) -> None:
        self.assertEqual(
            MODULE.markdown_web_link(
                "otel.html",
                "http://127.0.0.1:43123/otel.html",
            ),
            "[otel.html](http://127.0.0.1:43123/otel.html)",
        )

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

    def write_bound_instrumentation_flow(self, root: Path) -> SimpleNamespace:
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

        paths = SimpleNamespace(
            audit_json=root / "otel-audit.json",
            selection_json=root / "otel-selection.json",
            instrumentation_json=root / "otel-instrumentation.json",
        )
        paths.audit_json.write_text(json.dumps(sample_report()), encoding="utf-8")
        paths.selection_json.write_text(json.dumps(selection), encoding="utf-8")
        paths.instrumentation_json.write_text(
            json.dumps(instrumentation), encoding="utf-8"
        )
        return paths

    def test_instrumentation_digest_prints_only_bound_canonical_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.write_bound_instrumentation_flow(Path(directory))
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
            [],
        )
        self.assertEqual(
            [
                item["id"]
                for finding in verify["findings"]
                for item in finding["item_results"]
            ],
            [],
        )
        recommendation = " ".join(report["recommendation"])
        self.assertNotIn(".observe/otel-audit.selected.json", recommendation)
        self.assertNotIn("save the audit state over", recommendation)
        self.assertIn("copy and run the generated $otel-instrument command", recommendation)
        self.assertNotIn("$otel-instrument --ids", recommendation)
        instrumentation_html = (
            example_root / "otel-instrumentation.html"
        ).read_text()
        self.assertIn(
            f'<meta name="otel-selection-sha256" content="{MODULE.selection_digest(selection)}">',
            instrumentation_html,
        )
        self.assertIn("No telemetry changes were recorded; this is proof-only scope.", instrumentation_html)
        self.assertIn(
            "Scenario proof reached local OTLP; Splunk Observability Cloud was not checked.",
            instrumentation_html,
        )
        self.assertIn(
            "Confirmed in a running service: GET /health.",
            instrumentation_html,
        )
        self.assertNotIn("1 of 1 route check", instrumentation_html)
        self.assertNotIn("Removed span: HttpRequest", instrumentation_html)
        self.assertIn("were outside this instrumentation run", instrumentation_html)
        self.assertNotIn("were not implemented in this run", instrumentation_html)
        self.assertNotIn("Instrumentation JSON", instrumentation_html)
        self.assertNotIn("Verification JSON", instrumentation_html)
        audit_html = (example_root / "otel.html").read_text()
        self.assertIn('"service_root":null', audit_html)
        self.assertNotIn(str(repo_root), audit_html)

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

    def test_instrumentation_result_rejects_not_run(self) -> None:
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
        instrumentation_data["meta"]["result"] = "Not run"  # type: ignore[index]

        with self.assertRaisesRegex(
            MODULE.ReportError,
            "instrumentation.meta.result must be one of",
        ):
            MODULE.normalize_instrumentation(instrumentation_data, report, selection)

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

    def test_item_delivery_visibility_must_match_source_delivery_capability(self) -> None:
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
        instrumentation_data["findings"][0]["telemetry_changes"][0][
            "product_view"
        ] = "Local only; no OTLP export path exists for this signal."
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
                "visibility": "otlp_accepted",
                "observed_telemetry": ["The local receiver accepted the span."],
                "product_validation": ["The generated trace was accepted."],
            }
        )

        with self.assertRaisesRegex(
            MODULE.ReportError,
            "conflicts with the instrumentation item product_view",
        ):
            MODULE.normalize_verify(verify, report, selection, instrumentation)

    def test_consumer_compatibility_requires_valid_breaking_metadata(self) -> None:
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
        item = instrumentation_data["findings"][0]["telemetry_changes"][0]  # type: ignore[index]
        item["consumer_compatibility"] = {
            "status": "breaking",
            "existing_contract": ["metric dimension path"],
            "instrumentation_action": "Replace raw path with http.route.",
            "user_impact": "Dashboards grouped by path must migrate.",
            "migration": ["Use http.route instead of path."],
        }

        normalized = MODULE.normalize_instrumentation(
            instrumentation_data,
            report,
            selection,
        )

        compatibility = normalized["findings"][0]["telemetry_changes"][0][
            "consumer_compatibility"
        ]
        self.assertEqual(compatibility["status"], "breaking")
        self.assertEqual(compatibility["migration"], ["Use http.route instead of path."])

        item["consumer_compatibility"]["status"] = "renamed"
        with self.assertRaisesRegex(MODULE.ReportError, "consumer_compatibility.status"):
            MODULE.normalize_instrumentation(instrumentation_data, report, selection)

        item["consumer_compatibility"]["status"] = "breaking"
        item["consumer_compatibility"]["migration"] = []
        with self.assertRaisesRegex(MODULE.ReportError, "migration must name"):
            MODULE.normalize_instrumentation(instrumentation_data, report, selection)

    def test_instrumentation_html_surfaces_breaking_consumer_changes(self) -> None:
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
        item = instrumentation_data["findings"][0]["telemetry_changes"][0]  # type: ignore[index]
        item["consumer_compatibility"] = {
            "status": "breaking",
            "existing_contract": [
                "metric o11y.enp.ems.http.request.status dimension path",
                "dashboard filters using path",
            ],
            "instrumentation_action": "Removed raw path and added bounded http.route.",
            "user_impact": "Existing dashboards or detectors grouped by path need migration.",
            "migration": ["Update filters from path to http.route."],
        }
        instrumentation = MODULE.normalize_instrumentation(
            instrumentation_data,
            report,
            selection,
        )

        summary = MODULE.render_instrumentation_summary(selection, instrumentation, None)
        selected = MODULE.render_selected_issue_changes(
            report,
            selection,
            instrumentation,
            None,
        )

        self.assertIn(
            "Consumer compatibility: 1 breaking telemetry consumer change.",
            summary,
        )
        self.assertIn("Consumer compatibility", selected)
        self.assertIn("Existing consumer contract", selected)
        self.assertIn("metric o11y.enp.ems.http.request.status dimension path", selected)
        self.assertIn("Removed raw path and added bounded http.route.", selected)
        self.assertIn("Breaking change", selected)
        self.assertIn("Update filters from path to http.route.", selected)

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

    def test_empty_selection_cannot_pass_instrumentation(self) -> None:
        report = MODULE.normalize_audit_report(sample_report())
        selection = MODULE.empty_selection(report)
        instrumentation = {
            "schema_version": 1,
            "kind": "otel-instrumentation",
            "audit_id": report["meta"]["audit_id"],
            "audit_sha256": MODULE.audit_digest(report),
            "selection_sha256": MODULE.selection_digest(selection),
            "meta": {"service_name": "checkout", "date": "2026-07-17", "result": "Pass"},
            "findings": [],
            "next_steps": [],
        }

        with self.assertRaisesRegex(
            MODULE.ReportError,
            "Pass requires at least one selected instrumentation finding",
        ):
            MODULE.normalize_instrumentation(instrumentation, report, selection)

    def test_current_signal_extra_fields_participate_in_audit_digest(self) -> None:
        data = sample_report()
        data["current_instrumentation"]["metrics"] = [  # type: ignore[index]
            {
                "name": "http.server.request.duration",
                "source": "otelhttp",
                "type": "auto",
                "attributes": ["service.name", "http.route", "error.type"],
                "notes": [
                    "POST /payment failures are represented by http.route and error.type."
                ],
            }
        ]
        report = MODULE.normalize_audit_report(data)

        metric = report["current_instrumentation"]["metrics"][0]
        self.assertEqual(
            metric["attributes"],
            ["service.name", "http.route", "error.type"],
        )
        self.assertIn("notes", metric)

        changed = copy.deepcopy(data)
        changed["current_instrumentation"]["metrics"][0]["attributes"].append(  # type: ignore[index]
            "http.response.status_code"
        )
        changed_report = MODULE.normalize_audit_report(changed)
        self.assertNotEqual(
            MODULE.audit_digest(report),
            MODULE.audit_digest(changed_report),
        )

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
            "sha256:32ba9d96f7a301277b2ae3e2c9eb23066361d1b3fa17b66f196d0146dc784a91",
        )
        fallback_case = sample_report()
        fallback_case["findings"][0].pop("product_outcome")  # type: ignore[index]
        normalized_fallback = MODULE.normalize_audit_report(fallback_case)
        self.assertEqual(
            normalized_fallback["findings"][0]["product_outcome"],
            "Trace waterfall and route filtering",
        )

    def test_normalizes_optional_splunk_agent_observability_finding_group(self) -> None:
        legacy_report = MODULE.normalize_audit_report(sample_report())
        grouped_report = MODULE.normalize_audit_report(
            sample_splunk_agent_observability_report()
        )

        self.assertNotIn("finding_group", legacy_report["findings"][0])
        self.assertEqual(
            grouped_report["findings"][2]["finding_group"],
            "splunk-agent-observability",
        )
        for invalid_group in ("opentelemetry", "separate-section"):
            with self.subTest(invalid_group=invalid_group):
                invalid = sample_splunk_agent_observability_report()
                invalid["findings"][2]["finding_group"] = invalid_group  # type: ignore[index]
                with self.assertRaisesRegex(MODULE.ReportError, "finding_group"):
                    MODULE.normalize_audit_report(invalid)


if __name__ == "__main__":
    unittest.main()
