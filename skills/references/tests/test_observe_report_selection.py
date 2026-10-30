from __future__ import annotations

import copy
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from observe_report_fixtures import (
    MODULE,
    SCRIPT,
    make_external_follow_up,
    make_manual_decision,
    sample_decision_branch_report,
    sample_instrumentation,
    sample_report,
    sample_splunk_agent_observability_report,
)


class ObserveReportTest(unittest.TestCase):
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

    def test_html_commands_include_answers_and_prune_stale_branch_work(self) -> None:
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
        self.assertIn(
            'parts.push("--decision", `${answer.finding_id}=${answer.option_id}`);',
            html,
        )
        self.assertNotIn("document.decision_answers = answers", html)
        self.assertNotIn("schema_version: answers.length ? 2 : 1", html)
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
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            selected = json.loads(selection.read_text(encoding="utf-8"))
            self.assertEqual(selected["schema_version"], 1)
            self.assertEqual(selected["requested_ids"], ["OTEL-002"])
            self.assertEqual(selected["approved_ids"], ["OTEL-001", "OTEL-002"])

    def test_select_all_selects_every_eligible_executable_finding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / "otel-audit.json"
            selection = root / "otel-selection.json"
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
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            selected = json.loads(selection.read_text(encoding="utf-8"))
            self.assertEqual(selected["schema_version"], 1)
            self.assertEqual(selected["requested_ids"], ["OTEL-001", "OTEL-002"])
            self.assertEqual(selected["approved_ids"], ["OTEL-001", "OTEL-002"])
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
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            selected = json.loads(selection.read_text(encoding="utf-8"))
            self.assertEqual(selected["schema_version"], 2)
            self.assertEqual(selected["requested_ids"], ["OTEL-002"])
            self.assertEqual(selected["approved_ids"], ["OTEL-002"])
            self.assertEqual(
                selected["decision_answers"],
                [{"finding_id": "OTEL-001", "option_id": "application-owned"}],
            )
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
                    "--search-dir",
                    str(downloads),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            selected = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(selected["requested_ids"], ["OTEL-002"])
            self.assertEqual(selected["approved_ids"], ["OTEL-001", "OTEL-002"])
            self.assertIn("wrote", completed.stdout)
            self.assertIn("otel-selection (9).json", completed.stdout)

    def test_adopt_selection_prefers_repository_state_over_newer_search_candidate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observe = root / ".observe"
            observe.mkdir()
            downloads = root / "Downloads"
            downloads.mkdir()
            audit = observe / "otel-audit.json"
            output = observe / "otel-selection.json"
            report_data = sample_report()
            report = MODULE.normalize_audit_report(report_data)
            repository_selection = {
                "schema_version": 1,
                "kind": "otel-selection",
                "audit_id": report["meta"]["audit_id"],
                "audit_sha256": MODULE.audit_digest(report),
                "requested_ids": ["OTEL-001"],
                "approved_ids": ["OTEL-001"],
            }
            downloaded_selection = {
                **repository_selection,
                "requested_ids": ["OTEL-002"],
                "approved_ids": ["OTEL-001", "OTEL-002"],
            }
            audit.write_text(json.dumps(report_data), encoding="utf-8")
            output.write_text(json.dumps(repository_selection), encoding="utf-8")
            downloaded = downloads / "otel-selection (9).json"
            downloaded.write_text(json.dumps(downloaded_selection), encoding="utf-8")
            os.utime(output, ns=(1_000, 1_000))
            os.utime(downloaded, ns=(2_000, 2_000))

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

            self.assertEqual(completed.returncode, 0, completed.stderr)
            selected = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(selected["requested_ids"], ["OTEL-001"])
            self.assertEqual(selected["approved_ids"], ["OTEL-001"])
            self.assertIn("otel-selection.json", completed.stdout)

    def test_adopt_selection_explicit_candidate_can_replace_repository_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observe = root / ".observe"
            observe.mkdir()
            audit = observe / "otel-audit.json"
            output = observe / "otel-selection.json"
            explicit = root / "chosen-selection.json"
            report = MODULE.normalize_audit_report(sample_report())
            audit.write_text(json.dumps(report), encoding="utf-8")
            repository_selection = {
                "schema_version": 1,
                "kind": "otel-selection",
                "audit_id": report["meta"]["audit_id"],
                "audit_sha256": MODULE.audit_digest(report),
                "requested_ids": ["OTEL-001"],
                "approved_ids": ["OTEL-001"],
            }
            explicit_selection = {
                **repository_selection,
                "requested_ids": ["OTEL-002"],
                "approved_ids": ["OTEL-001", "OTEL-002"],
            }
            output.write_text(json.dumps(repository_selection), encoding="utf-8")
            explicit.write_text(json.dumps(explicit_selection), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "adopt-selection",
                    str(audit),
                    "-o",
                    str(output),
                    "--candidate",
                    str(explicit),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            selected = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(selected["requested_ids"], ["OTEL-002"])
            self.assertEqual(selected["approved_ids"], ["OTEL-001", "OTEL-002"])
            self.assertIn("chosen-selection.json", completed.stdout)

    def test_adopt_selection_skips_invalid_utf8_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observe = root / ".observe"
            observe.mkdir()
            audit = observe / "otel-audit.json"
            output = observe / "otel-selection.json"
            corrupt = root / "otel-selection-corrupt.json"
            valid = root / "otel-selection-valid.json"
            report = MODULE.normalize_audit_report(sample_report())
            audit.write_text(json.dumps(report), encoding="utf-8")
            corrupt.write_bytes(b"\xff\xfe\x00")
            valid.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "otel-selection",
                        "audit_id": report["meta"]["audit_id"],
                        "audit_sha256": MODULE.audit_digest(report),
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
                    "--candidate",
                    str(corrupt),
                    "--candidate",
                    str(valid),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            selected = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(selected["approved_ids"], ["OTEL-001"])
            self.assertIn("otel-selection-valid.json", completed.stdout)

    def test_adopt_selection_all_if_empty_uses_saved_decision_answer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observe = root / ".observe"
            observe.mkdir()
            audit = observe / "otel-audit.json"
            output = observe / "otel-selection.json"
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
                    "--all-if-empty",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            selected = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(selected["requested_ids"], ["OTEL-002"])
            self.assertEqual(selected["approved_ids"], ["OTEL-002"])
            self.assertEqual(
                selected["decision_answers"],
                [{"finding_id": "OTEL-001", "option_id": "application-owned"}],
            )
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

    def test_selection_v3_ao_target_normalization_and_digest_binding(self) -> None:
        report = MODULE.normalize_audit_report(sample_splunk_agent_observability_report())
        base = {
            "schema_version": 3,
            "kind": "otel-selection",
            "audit_id": report["meta"]["audit_id"],
            "audit_sha256": MODULE.audit_digest(report),
            "requested_ids": ["AO-002"],
        }
        target = {"project_name": " checkout ", "agent_stream_name": "live"}
        selection = MODULE.normalize_selection({**base, "ao_target": target}, report)
        self.assertEqual(selection["schema_version"], 3)
        self.assertEqual(selection["decision_answers"], [])
        self.assertEqual(selection["ao_target"], {
            "project_name": "checkout", "agent_stream_name": "live", "create_if_missing": True,
        })
        other = MODULE.normalize_selection({**base, "ao_target": {
            "project_name": "other", "agent_stream_name": "live", "create_if_missing": False,
        }}, report)
        self.assertEqual(selection["approved_ids"], other["approved_ids"])
        self.assertNotEqual(MODULE.selection_digest(selection), MODULE.selection_digest(other))
        instrumentation = sample_instrumentation(report, MODULE.audit_digest(report), selection)
        with self.assertRaisesRegex(MODULE.ReportError, "selection_sha256 does not match selection"):
            MODULE.normalize_instrumentation(instrumentation, report, other)
        ids = MODULE.normalize_selection({**base, "ao_target": {
            "project_id": "project-123", "agent_stream_id": "stream-123",
        }}, report)
        self.assertEqual(ids["ao_target"]["project_id"], "project-123")

    def test_ao_target_scope_rejects_actual_callback_even_with_ao_ids_and_dependencies(self) -> None:
        fixture = SCRIPT.parents[3] / "evals/python/splunk-ao-langchain-demo/eval/inputs/otel-audit.json"
        raw = json.loads(fixture.read_text(encoding="utf-8"))
        target = {"project_name": "project", "agent_stream_name": "stream"}
        for renamed in (False, True):
            candidate = copy.deepcopy(raw)
            if renamed:
                prerequisite = copy.deepcopy(candidate["findings"][0])
                prerequisite["id"] = "AO-001"
                prerequisite["area"] = "Callback content prerequisite"
                candidate["signal_flow"]["component_flow_map"] += "\nCallback configuration [GAP: Callback content prerequisite]"
                callback = copy.deepcopy(candidate["findings"][0])
                callback["id"] = "AO-002"
                callback["dependencies"] = ["AO-001"]
                candidate["findings"] = [prerequisite, callback]
            report = MODULE.normalize_audit_report(candidate)
            requested = "AO-002" if renamed else "OTEL-001"
            base = {"schema_version": 3, "kind": "otel-selection",
                    "audit_id": report["meta"]["audit_id"],
                    "audit_sha256": MODULE.audit_digest(report), "requested_ids": [requested]}
            blank = MODULE.normalize_selection(base, report)
            expected = ["AO-001", "AO-002"] if renamed else ["OTEL-001"]
            self.assertEqual(blank["approved_ids"], expected)
            self.assertFalse(MODULE.has_selected_ao_configuration(report, expected))
            for value in (target, {"create_if_missing": False}):
                with self.subTest(renamed=renamed, target=value), self.assertRaisesRegex(
                    MODULE.ReportError, "requires a selected Agent Observability resource or routing finding"
                ):
                    MODULE.normalize_selection({**base, "approved_ids": expected, "ao_target": value}, report)

    def test_ao_target_scope_explicit_marker_and_legacy_names(self) -> None:
        for name in MODULE.AO_TARGET_LEGACY_CONFIGURATION_NAMES:
            finding = {"finding_group": "splunk-agent-observability",
                       "expected_telemetry": [{"type": "configuration", "name": name}]}
            self.assertTrue(MODULE.is_ao_target_configuration(finding), name)
            self.assertFalse(MODULE.is_ao_target_configuration({
                **finding, "expected_telemetry": [{"type": "span", "name": name}]
            }))
        raw = sample_splunk_agent_observability_report()
        raw["findings"][2]["expected_telemetry"][0]["name"] = "custom.project-routing"
        self.assertFalse(MODULE.is_ao_target_configuration(raw["findings"][2]))
        raw["findings"][2]["ao_target_scope"] = "resource-routing"
        report = MODULE.normalize_audit_report(raw)
        self.assertEqual(report["findings"][2]["ao_target_scope"], "resource-routing")
        self.assertNotIn("ao_target_scope", report["findings"][3])
        selection = MODULE.normalize_selection({
            "schema_version": 3, "kind": "otel-selection",
            "audit_id": report["meta"]["audit_id"], "audit_sha256": MODULE.audit_digest(report),
            "requested_ids": ["AO-002"],
            "ao_target": {"project_name": "project", "agent_stream_name": "stream"},
        }, report)
        self.assertEqual(selection["approved_ids"], ["OTEL-001", "AO-001", "AO-002"])
        for value in (None, "", "capture", True, 3):
            invalid = copy.deepcopy(raw)
            invalid["findings"][2]["ao_target_scope"] = value
            with self.subTest(scope=value), self.assertRaises(MODULE.ReportError):
                MODULE.normalize_audit_report(invalid)
        for wrong_group in (True, False):
            invalid = copy.deepcopy(raw)
            if wrong_group:
                invalid["findings"][2].pop("finding_group")
            else:
                invalid["findings"][2]["expected_telemetry"][0]["type"] = "span"
            with self.subTest(wrong_group=wrong_group), self.assertRaisesRegex(
                MODULE.ReportError, "ao_target_scope requires an Agent Observability configuration finding"
            ):
                MODULE.normalize_audit_report(invalid)

    def test_ao_target_scope_omission_preserves_actual_targetless_digests(self) -> None:
        inputs = SCRIPT.parents[3] / "evals/python/ai-assistant-demo/eval/inputs"
        report = MODULE.normalize_audit_report(json.loads((inputs / "ao-resource-audit.json").read_text()))
        raw_selection = json.loads((inputs / "ao-resource-selection.json").read_text())
        instrumentation = json.loads((inputs / "ao-resource-instrumentation.json").read_text())
        self.assertTrue(all("ao_target_scope" not in finding for finding in report["findings"]))
        self.assertEqual(MODULE.audit_digest(report), raw_selection["audit_sha256"])
        selection = MODULE.normalize_selection(raw_selection, report)
        self.assertEqual(selection, raw_selection)
        self.assertEqual(MODULE.selection_digest(selection), instrumentation["selection_sha256"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JavaScript behavior validation")
    def test_ao_target_ui_uses_server_resource_eligibility(self) -> None:
        fixture = SCRIPT.parents[3] / "evals/python/splunk-ao-langchain-demo/eval/inputs/otel-audit.json"
        callback = MODULE.normalize_audit_report(json.loads(fixture.read_text()))
        reports = [(callback, []), (MODULE.normalize_audit_report(sample_splunk_agent_observability_report()), ["AO-001", "AO-002"])]
        for report, eligible in reports:
            rendered = MODULE.render_html(report, MODULE.empty_selection(report))
            payload = json.loads(rendered.split("const DATA = ", 1)[1].split(";\nconst REPORT", 1)[0])
            self.assertEqual(payload["ao_target_eligible_finding_ids"], eligible)
            self.assertEqual('id="ao-target-controls"' in rendered, bool(eligible))
            function = rendered[rendered.index("function hasSelectedAoConfiguration()"):rendered.index("function aoTargetArguments()") ]
            script = "const DATA = " + json.dumps(payload) + ";const selected = new Set();" + function
            script += "selected.add('OTEL-001');if(hasSelectedAoConfiguration())throw new Error('unrelated scope');"
            if eligible:
                script += "selected.add('AO-002');if(!hasSelectedAoConfiguration())throw new Error('resource dependency scope');"
            result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_ao_target_length_counts_unicode_codepoints(self) -> None:
        for key in ("project_name", "project_id", "agent_stream_name", "agent_stream_id"):
            for character in ("x", "\U0001f9ea"):
                target = {"project_name": "project", "agent_stream_name": "stream"}
                if key.endswith("_id"):
                    target.pop(key.removesuffix("_id") + "_name")
                target[key] = character * 512
                self.assertEqual(MODULE.normalize_ao_target(target, "target")[key], character * 512)
                target[key] += character
                with self.assertRaisesRegex(MODULE.ReportError, "512 characters"):
                    MODULE.normalize_ao_target(target, "target")

    def test_selection_ao_target_requires_valid_selectors_and_selected_configuration(self) -> None:
        report = MODULE.normalize_audit_report(sample_splunk_agent_observability_report())
        base = {
            "schema_version": 3, "kind": "otel-selection",
            "audit_id": report["meta"]["audit_id"], "audit_sha256": MODULE.audit_digest(report),
            "requested_ids": ["AO-002"],
        }
        target = {"project_name": "checkout", "agent_stream_name": "live"}
        env_policy = MODULE.normalize_selection({**base, "ao_target": {"create_if_missing": False}}, report)
        self.assertEqual(env_policy["ao_target"], {"create_if_missing": False})
        bad_targets = [
            {},
            {"create_if_missing": True},
            {"create_if_missing": "false"},
            {"project_name": "checkout"},
            {**target, "project_id": "project-123"},
            {**target, "project_name": " "},
            {**target, "agent_stream_name": "bad\nname"},
            {**target, "agent_stream_name": "\nlive"},
            {**target, "create_if_missing": "true"},
            {**target, "token": "not-allowed"},
        ]
        for bad in bad_targets:
            with self.subTest(target=bad), self.assertRaises(MODULE.ReportError):
                MODULE.normalize_selection({**base, "ao_target": bad}, report)
        for schema in (1, 2):
            with self.subTest(schema=schema), self.assertRaisesRegex(MODULE.ReportError, "schema_version must be 3"):
                MODULE.normalize_selection({**base, "schema_version": schema, "ao_target": target}, report)
        with self.assertRaisesRegex(MODULE.ReportError, "requires a selected Agent Observability"):
            MODULE.normalize_selection({**base, "requested_ids": ["OTEL-001"], "ao_target": target}, report)
        # Resource classification is independent of numeric finding IDs.
        renamed = copy.deepcopy(report)
        renamed["findings"][2]["id"] = "PROJECT-BINDING"
        renamed["findings"][3]["dependencies"] = ["PROJECT-BINDING", "OTEL-001"]
        accepted = MODULE.normalize_selection({**base, "audit_sha256": MODULE.audit_digest(renamed),
            "requested_ids": ["PROJECT-BINDING"], "ao_target": target}, renamed)
        self.assertIn("ao_target", accepted)

    def test_ao_target_preserves_legacy_selection_shape_and_decisions(self) -> None:
        report = MODULE.normalize_audit_report(sample_decision_branch_report())
        answers = [{"finding_id": "OTEL-001", "option_id": "application-owned"}]
        expected = {
            "schema_version": 2, "kind": "otel-selection", "audit_id": report["meta"]["audit_id"],
            "audit_sha256": MODULE.audit_digest(report), "requested_ids": ["OTEL-002"],
            "approved_ids": ["OTEL-002"], "approved_by": None, "approved_at": None,
            "decision_answers": answers,
        }
        self.assertEqual(MODULE.normalize_selection(expected, report), expected)
        self.assertEqual(MODULE.selection_digest(MODULE.normalize_selection(expected, report)), MODULE.selection_digest(expected))
        v3 = MODULE.normalize_selection({**expected, "schema_version": 3}, report)
        self.assertEqual(v3["decision_answers"], answers)
        self.assertNotIn("ao_target", v3)
        ao_report = MODULE.normalize_audit_report(sample_splunk_agent_observability_report())
        all_selected = MODULE.select_all_selection(ao_report, ao_target={
            "project_name": "checkout", "agent_stream_id": "existing-stream", "create_if_missing": False,
        })
        self.assertEqual(all_selected["schema_version"], 3)
        self.assertEqual(all_selected["ao_target"]["agent_stream_id"], "existing-stream")

    def test_cli_ao_target_roundtrip_and_adoption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / "otel-audit.json"
            selection = root / "otel-selection.json"
            adopted = root / "adopted.json"
            audit.write_text(json.dumps(sample_splunk_agent_observability_report()), encoding="utf-8")
            command = [sys.executable, str(SCRIPT), "select", str(audit), "--ids", "AO-002",
                "--ao-project", "checkout's project", "--ao-agent-stream-id", "stream-123",
                "--ao-reuse-only", "-o", str(selection)]
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            selected = json.loads(selection.read_text(encoding="utf-8"))
            self.assertEqual(selected["schema_version"], 3)
            self.assertEqual(selected["ao_target"], {
                "project_name": "checkout's project", "agent_stream_id": "stream-123", "create_if_missing": False,
            })
            result = subprocess.run([sys.executable, str(SCRIPT), "adopt-selection", str(audit),
                "--candidate", str(selection), "--all-if-empty", "-o", str(adopted)],
                capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(adopted.read_text(encoding="utf-8")), selected)
            result = subprocess.run([sys.executable, str(SCRIPT), "select", str(audit), "--ids", "AO-002",
                "--ao-project=--ao-reuse-only", "--ao-agent-stream=-stream name", "-o", str(selection)],
                capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            negative = json.loads(selection.read_text(encoding="utf-8"))["ao_target"]
            self.assertEqual(negative, {
                "project_name": "--ao-reuse-only", "agent_stream_name": "-stream name", "create_if_missing": True,
            })
            result = subprocess.run([sys.executable, str(SCRIPT), "select", str(audit), "--ids", "AO-002",
                "--ao-reuse-only", "-o", str(selection)], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            env_policy = json.loads(selection.read_text(encoding="utf-8"))
            self.assertEqual(env_policy["schema_version"], 3)
            self.assertEqual(env_policy["ao_target"], {"create_if_missing": False})
            self.assertEqual(env_policy["approved_ids"], selected["approved_ids"])
            self.assertNotEqual(MODULE.selection_digest(env_policy), MODULE.selection_digest(selected))

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JavaScript behavior validation")
    def test_html_ao_resource_inputs_generate_validated_quoted_commands(self) -> None:
        report = MODULE.normalize_audit_report(sample_splunk_agent_observability_report())
        selection = MODULE.normalize_selection({
            "schema_version": 3, "kind": "otel-selection", "audit_id": report["meta"]["audit_id"],
            "audit_sha256": MODULE.audit_digest(report), "requested_ids": ["AO-002"],
            "ao_target": {"project_id": "project-123", "agent_stream_id": "stream-123"},
        }, report)
        rendered = MODULE.render_html(report, selection)
        self.assertIn('for="ao-project-value">Project ID</label>', rendered)
        self.assertIn('value="project-123"', rendered)
        self.assertIn('aria-describedby="ao-target-help ao-target-error"', rendered)
        functions = rendered[rendered.index("function shellQuote(value)"):rendered.index("function syncDependencyClosure()")]
        payload = json.loads(rendered.split("const DATA = ", 1)[1].split(";\nconst REPORT", 1)[0])
        payload["service_root"] = "/repo with spaces"
        script = """
const REPORT = REPORT_VALUE;
const DATA = DATA_VALUE;
const selected = new Set(["AO-002"]);
const decisionAnswers = new Map();
const nodes = {};
for (const id of ["ao-project-selector", "ao-agent_stream-selector", "ao-project-value", "ao-agent_stream-value",
  "ao-project-label", "ao-agent_stream-label", "ao-reuse-only", "ao-target-error", "ao-target-controls", "tray", "instrumentCommand"]) {
  nodes[id] = {value: "", textContent: "", hidden: true, checked: false, toggleAttribute() {}, setAttribute() {}};
}
const document = {getElementById(id) {return nodes[id];}};
function orderedRequested() {return selected.has("AO-002") ? ["AO-002"] : [];}
function orderedDecisionAnswers() {return [];}
function assert(condition, message) {if (!condition) throw new Error(message);}
FUNCTIONS_VALUE
nodes["ao-project-selector"].value = "id";
nodes["ao-agent_stream-selector"].value = "id";
nodes["ao-project-value"].value = "project-123";
nodes["ao-agent_stream-value"].value = "stream-123";
renderTray();
assert(!nodes["ao-target-controls"].hidden, "AO selection exposes destination controls");
assert(nodes.instrumentCommand.value.includes("--ao-project-id project-123"), "saved ID is retained");
nodes["ao-project-selector"].value = "name";
updateAoTargetInput("project", true);
assert(!nodes["ao-project-value"].value, "changing selector clears incompatible value");
assert(nodes["ao-project-label"].textContent === "Project name", "input label follows selector");
assert(nodes["ao-target-error"].textContent.includes("Provide both"), "partial target exposes error");
nodes["ao-project-value"].value = "checkout's $(project)";
nodes["ao-reuse-only"].checked = true;
updateAoTargetInput("project");
assert(!nodes["ao-target-error"].textContent, "complete target clears error");
assert(nodes.instrumentCommand.value.includes("--ao-reuse-only"), "reuse choice reaches command");
const command = nodes.instrumentCommand.value;
nodes["ao-project-value"].value = "--ao-reuse-only";
nodes["ao-agent_stream-value"].value = "-stream name";
nodes["ao-agent_stream-selector"].value = "name";
nodes["ao-reuse-only"].checked = false;
updateAoTargetInput("project");
const negativeCommand = nodes.instrumentCommand.value;
assert(negativeCommand.includes("--ao-project=--ao-reuse-only"), "option-like values stay resource values");
nodes["ao-project-value"].value = "bad\\nname";
updateAoTargetInput("project");
assert(nodes["ao-target-error"].textContent.includes("control characters"), "invalid names block command");
nodes["ao-project-value"].value = "";
nodes["ao-agent_stream-value"].value = "";
nodes["ao-reuse-only"].checked = false;
updateAoTargetInput("project");
assert(!nodes.instrumentCommand.value.includes("--ao-"), "cleared target restores application configuration");
nodes["ao-reuse-only"].checked = true;
updateAoTargetInput("project");
assert(!nodes["ao-target-error"].textContent, "reuse-only permits env fallback");
assert(nodes.instrumentCommand.value.includes("--ao-reuse-only"), "env reuse policy reaches command");
assert(!nodes.instrumentCommand.value.includes("--ao-project"), "env fallback does not invent selectors");
selected.clear();
renderTray();
assert(nodes["ao-target-controls"].hidden, "deselecting AO hides optional controls");
process.stdout.write(JSON.stringify({command, negativeCommand}));
""".replace("REPORT_VALUE", json.dumps(report)).replace("DATA_VALUE", json.dumps(payload)).replace("FUNCTIONS_VALUE", functions)
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(shlex.split(json.loads(result.stdout)["command"]), [
            "$otel-instrument", "--ids", "AO-002", "--ao-project", "checkout's $(project)",
            "--ao-agent-stream-id", "stream-123", "--ao-reuse-only", "/repo with spaces",
        ])
        self.assertEqual(shlex.split(json.loads(result.stdout)["negativeCommand"]), [
            "$otel-instrument", "--ids", "AO-002", "--ao-project=--ao-reuse-only",
            "--ao-agent-stream=-stream name", "/repo with spaces",
        ])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JavaScript behavior validation")
    def test_html_ao_resource_invalid_state_is_specific_to_each_field(self) -> None:
        report = MODULE.normalize_audit_report(sample_splunk_agent_observability_report())
        rendered = MODULE.render_html(report, MODULE.empty_selection(report))
        functions = rendered[rendered.index("function shellQuote(value)"):rendered.index("function syncDependencyClosure()")]
        payload = json.loads(rendered.split("const DATA = ", 1)[1].split(";\nconst REPORT", 1)[0])
        script = """
const REPORT = REPORT_VALUE;
const DATA = DATA_VALUE;
const selected = new Set(["AO-002"]);
const nodes = {};
for (const resource of ["project", "agent_stream"]) {
  nodes[`ao-${resource}-selector`] = {value: "name"};
  nodes[`ao-${resource}-value`] = {value: "valid", attributes: {},
    setAttribute(name, value) {this.attributes[name] = value;}};
}
nodes["ao-reuse-only"] = {checked: false};
nodes["ao-target-error"] = {textContent: ""};
const document = {getElementById(id) {return nodes[id];}};
function assert(condition, message) {if (!condition) throw new Error(message);}
function invalid(resource) {return nodes[`ao-${resource}-value`].attributes["aria-invalid"] === "true";}
function fill(project, stream) {
  nodes["ao-project-value"].value = project;
  nodes["ao-agent_stream-value"].value = stream;
  return aoTargetArguments();
}
FUNCTIONS_VALUE
for (const resource of ["project", "agent_stream"]) {
  const other = resource === "project" ? "agent_stream" : "project";
  for (const mode of ["name", "id"]) {
    nodes[`ao-${resource}-selector`].value = mode;
    for (const value of ["x".repeat(513), "🧪".repeat(513), "bad\u202evalue"]) {
      fill("valid-project", "valid-stream");
      nodes[`ao-${resource}-value`].value = value;
      const target = aoTargetArguments();
      assert(target.error, `${resource}/${mode}: invalid field blocks command`);
      assert(invalid(resource), `${resource}/${mode}: offending field is invalid`);
      assert(!invalid(other), `${resource}/${mode}: valid peer stays valid`);
      const repaired = fill("valid-project", "valid-stream");
      assert(!repaired.error && !invalid(resource) && !invalid(other), "repair clears field errors");
    }
    fill("valid-project", "valid-stream");
    nodes[`ao-${resource}-value`].value = "";
    assert(aoTargetArguments().error, "partial pair blocks command");
    assert(invalid(resource) && !invalid(other), "only actually missing selector is invalid");
  }
}
assert(!fill("", "").error && !invalid("project") && !invalid("agent_stream"), "empty fallback is valid");
fill("x".repeat(513), "");
assert(invalid("project") && invalid("agent_stream"), "offending value and missing peer are both invalid");
fill("valid-project", "");
assert(!invalid("project") && invalid("agent_stream"), "repair keeps only missing peer invalid");
assert(!fill("valid-project", "valid-stream").error && !invalid("project") && !invalid("agent_stream"), "complete pair clears both");
""".replace("REPORT_VALUE", json.dumps(report)).replace("DATA_VALUE", json.dumps(payload)).replace("FUNCTIONS_VALUE", functions)
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

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
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            selection = json.loads(selection_path.read_text(encoding="utf-8"))
            self.assertEqual(selection["schema_version"], 2)
            self.assertEqual(selection["requested_ids"], [])
            self.assertEqual(selection["approved_ids"], [])


if __name__ == "__main__":
    unittest.main()
