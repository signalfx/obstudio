from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import aggregate_skill_benchmark as benchmark_module
from aggregate_skill_benchmark import (
    RunArtifact,
    build_benchmark,
    canonical_equality_satisfied,
    compare_provenance,
    definition_case_contract,
    gap_closure_validator_command,
    main,
    reader_validator_command,
    tree_sha256,
)
from pytest_codex_evals.report import write_capture_manifest


CANONICAL_HTML = "<!doctype html><html><body>canonical report</body></html>\n"


AUDIT_REPORT = """# Observability Report: sample
**Status:** Partial
**GenAI ownership detected:** No
## Executive Summary
- Missing telemetry.
## Routes
| Method | Path |
|---|---|
| GET | {route} |
## Current Instrumentation
### Spans
No spans detected.
### Metrics
No metrics detected.
### Logs
No OTel logs detected.
## Gaps
| Priority | Area | Instrument mode | Verification scenarios |
|---|---|---|---|
| required | HTTP | default | http.success |
## Verification Plan
### Test Environments
| Environment ID | Surface | Runner / Toolchain |
|---|---|---|
| go.local | API | go test ./... |
### Acceptance Scenarios
| Scenario ID | Proof Level | Environment |
|---|---|---|
| http.success | full runtime | go.local |
"""

INSTRUMENT_REPORT = """# OTel Instrumentation Report: sample
**Result:** Partial
## Signals Changed
| Signal type | Added | Modified | Removed | Verification status |
|---|---|---|---|---|
| Traces/spans | HTTP server span | None | None | partial |
## Audit Gap Closure
| Priority | Gap | Result |
|---|---|---|
## Validation Gates
| Gate | Result |
|---|---|
| Build | Pass |
"""

VERIFY_REPORT = """# OTel Verification Report: sample
**Result:** Partial
## What Changed
One span.
## Tested And Working
| OTel item | Type | Working status | How it was tested |
|---|---|---|---|
| HTTP server span | Span | Not proven | compile gate |
## Not Working Or Not Proven
| Item | State |
|---|---|
| HTTP server span | Not proven |
## Proof
| Proof type | What it proves |
|---|---|
| Compile | Source builds |
"""


class AggregateSkillBenchmarkTest(unittest.TestCase):
    def test_reader_validator_prefers_bound_json_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            report = root / "service/.observe/otel-verify.md"
            report.parent.mkdir(parents=True)
            report.write_text(VERIFY_REPORT, encoding="utf-8")
            (report.parent / "otel-instrumentation.json").write_text(
                "{}\n", encoding="utf-8"
            )
            (report.parent / "otel-verify.json").write_text(
                "{}\n", encoding="utf-8"
            )
            expected = report.parent / "tmp/otel-verify-expected-items.txt"
            expected.parent.mkdir()
            expected.write_text("HTTP server span\n", encoding="utf-8")

            command = reader_validator_command(repo, report)
            self.assertIn("--instrumentation-json", command)
            self.assertIn("--verify-json", command)
            self.assertNotIn("--expected-items-file", command)

            (report.parent / "otel-instrumentation.json").unlink()
            command = reader_validator_command(repo, report)
            self.assertIn("--expected-items-file", command)
            self.assertNotIn("--verify-json", command)

    def test_gap_closure_validator_uses_bound_json_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            observe = root / "service/.observe"
            observe.mkdir(parents=True)
            report = observe / "otel-instrumentation.md"
            for name in (
                "otel.md",
                "otel-audit.json",
                "otel-selection.json",
                "otel-instrumentation.json",
                "otel-verify.json",
            ):
                (observe / name).write_text("{}\n", encoding="utf-8")

            command = gap_closure_validator_command(repo, observe, report)
            self.assertIn("--audit-json", command)
            self.assertIn("--selection-json", command)
            self.assertIn("--verify-json", command)
            self.assertNotIn("--instrumentation-json", command)

            (observe / "otel-verify.json").unlink()
            command = gap_closure_validator_command(repo, observe, report)
            self.assertIn("--instrumentation-json", command)
            self.assertNotIn("--verify-json", command)

    def test_tree_hash_rejects_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            outside = root / "outside.txt"
            outside.write_text("first\n", encoding="utf-8")
            (source / "linked.txt").symlink_to(outside)

            with self.assertRaisesRegex(
                ValueError, "provenance source tree must not contain symlinks"
            ):
                tree_sha256(source)

            outside.write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "provenance source tree must not contain symlinks"
            ):
                tree_sha256(source)

    def make_repo(self, root: Path, *, verify_exit: int = 0) -> Path:
        repo = root / "repo"
        scripts = {
            "skills/otel-audit/scripts/validate_audit_report.py": 0,
            "skills/otel-instrument/scripts/validate_gap_closure.py": 0,
            "skills/otel-verify/scripts/validate_reader_report.py": verify_exit,
        }
        for relative, exit_code in scripts.items():
            path = repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"import sys\nprint('validator {exit_code}')\nraise SystemExit({exit_code})\n",
                encoding="utf-8",
            )
        for skill in ("otel-audit", "otel-instrument", "otel-verify"):
            (repo / f"skills/{skill}/SKILL.md").write_text(
                f"---\nname: {skill}\n---\n# {skill}\n",
                encoding="utf-8",
            )
        report_tool = repo / "skills/references/scripts/observe_report.py"
        report_tool.parent.mkdir(parents=True, exist_ok=True)
        report_tool.write_text(
            """import pathlib
import sys

if len(sys.argv) > 1 and sys.argv[1].startswith("render-"):
    output = pathlib.Path(sys.argv[sys.argv.index("-o") + 1])
    output.write_text(
        "<!doctype html><html><body>canonical report</body></html>\\n",
        encoding="utf-8",
    )
raise SystemExit(0)
""",
            encoding="utf-8",
        )
        (repo / "evals").mkdir(exist_ok=True)
        (repo / "evals/codex-evals.toml").write_text(
            '[run]\nmode = "with_skill"\n', encoding="utf-8"
        )
        harness_source = repo / "pytest-codex-evals/src/pytest_codex_evals"
        harness_source.mkdir(parents=True)
        (harness_source / "__init__.py").write_text(
            "# synthetic harness source\n", encoding="utf-8"
        )
        return repo

    def write_run(
        self,
        root: Path,
        *,
        side: str,
        skill: str,
        run: int,
        duration: float,
        commands: int,
        tokens: int,
        report: str,
        nested_verify: bool = False,
        canonical: bool = True,
    ) -> None:
        side_root = (
            root
            / side
            / skill
            / f"run{run}"
            / "cases/go/sample/benchmark/with_skill"
        )
        side_root.mkdir(parents=True)
        summary = {
            "side": "with_skill",
            "exit_code": 0,
            "trace_path": "/original/capture/path/trace.jsonl",
            "agent_duration_seconds": duration,
            "duration_seconds": duration + 1,
            "command_count": commands,
            "agent_tokens": tokens,
            "tokens": tokens,
            "errors": [],
        }
        (side_root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        skill_name = f"otel-{skill}"
        skill_path = root / "repo/skills" / skill_name
        repo = root / "repo"
        fixture = repo / "evals/go/sample"
        fixture.mkdir(parents=True, exist_ok=True)
        (fixture / "main.go").write_text("package main\n", encoding="utf-8")
        definition = fixture / f"eval/qual/benchmark-{skill}.json"
        definition.parent.mkdir(parents=True, exist_ok=True)
        canonical_task = {
            "audit": (
                "Write ./service/.observe/otel-audit.json and "
                "./service/.observe/otel.html."
            ),
            "instrument": (
                "Write ./service/.observe/otel-instrumentation.json and "
                "./service/.observe/otel-instrumentation.html."
            ),
            "verify": "Write ./service/.observe/otel-verify.json.",
        }[skill]
        task = canonical_task if canonical else "Write the compatibility Markdown report."
        definition.write_text(
            json.dumps(
                {
                    "skill": skill_name,
                    "prompts": [{"id": "benchmark", "task": task}],
                    "rubric": ["The generated report is correct."],
                }
            ),
            encoding="utf-8",
        )
        trace_event = {
            "type": "item.completed",
            "item": {
                "id": "item_skill",
                "type": "command_execution",
                "command": f"/bin/zsh -lc \"sed -n '1,999p' {skill_path / 'SKILL.md'}\"",
                "aggregated_output": (skill_path / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "exit_code": 0,
                "status": "completed",
            },
        }
        (side_root / "trace.jsonl").write_text(
            json.dumps(trace_event) + "\n", encoding="utf-8"
        )
        run_dir = root / side / skill / f"run{run}"
        run_configuration = {
            "config_path": "evals/codex-evals.toml",
            "mode": "with_skill",
        }
        validation_dir = run_dir / "runs"
        validation_dir.mkdir(parents=True)
        (validation_dir / "validation.json").write_text(
            json.dumps(
                {
                    "repo_root": str(repo),
                    "metadata": run_configuration,
                    "results": [
                        {
                            "id": f"go/sample/qual/benchmark-{skill}/benchmark",
                            "prompt_id": "benchmark",
                            "skill": skill_name,
                            "skill_path": str(skill_path),
                            "definition_path": str(definition),
                            "fixture_dir": str(fixture),
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "run.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "skill": skill_name,
                    "runs": ["runs/validation.json"],
                }
            ),
            encoding="utf-8",
        )
        task_hash = hashlib.sha256(task.encode("utf-8")).hexdigest()
        _, contract_hash, contract_errors = definition_case_contract(
            definition,
            "benchmark",
        )
        self.assertEqual(contract_errors, [])
        self.assertIsNotNone(contract_hash)
        run_configuration_hash = hashlib.sha256(
            json.dumps(
                run_configuration,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        (side_root / ".codex-eval-provenance.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "case": {
                        "id": f"go/sample/qual/benchmark-{skill}/benchmark",
                        "base_id": f"go/sample/qual/benchmark-{skill}",
                        "prompt_id": "benchmark",
                        "skill": skill_name,
                        "language": "go",
                        "service": "sample",
                        "task": task,
                        "task_sha256": task_hash,
                        "contract_sha256": contract_hash,
                    },
                    "definition": {
                        "path": str(definition),
                        "exists": True,
                        "sha256": hashlib.sha256(definition.read_bytes()).hexdigest(),
                    },
                    "config": {
                        "path": str(repo / "evals/codex-evals.toml"),
                        "exists": True,
                        "sha256": hashlib.sha256(
                            (repo / "evals/codex-evals.toml").read_bytes()
                        ).hexdigest(),
                    },
                    "run_configuration": {
                        "value": run_configuration,
                        "sha256": run_configuration_hash,
                    },
                    "fixture": {
                        "path": str(fixture),
                        "tree_sha256": tree_sha256(fixture),
                    },
                    "skill": {
                        "path": str(skill_path),
                        "tree_sha256": tree_sha256(skill_path),
                    },
                    "shared_references": {
                        "path": str(repo / "skills/references"),
                        "tree_sha256": tree_sha256(repo / "skills/references"),
                    },
                    "harness": {
                        "path": str(
                            repo / "pytest-codex-evals/src/pytest_codex_evals"
                        ),
                        "tree_sha256": tree_sha256(
                            repo / "pytest-codex-evals/src/pytest_codex_evals"
                        ),
                    },
                }
            ),
            encoding="utf-8",
        )
        observe = side_root / "service/.observe"
        observe.mkdir(parents=True)
        report_name = {
            "audit": "otel.md",
            "instrument": "otel-instrumentation.md",
            "verify": "otel-verify.md",
        }[skill]
        (observe / report_name).write_text(report, encoding="utf-8")
        if canonical:
            (observe / "otel-audit.json").write_text("{}\n", encoding="utf-8")
            if skill in {"instrument", "verify"}:
                (observe / "otel-selection.json").write_text(
                    "{}\n", encoding="utf-8"
                )
            if skill == "instrument":
                (observe / "otel-instrumentation.json").write_text(
                    "{}\n", encoding="utf-8"
                )
            if skill == "verify":
                (observe / "otel-verify.json").write_text("{}\n", encoding="utf-8")
            if skill == "audit":
                (observe / "otel.html").write_text(
                    CANONICAL_HTML, encoding="utf-8"
                )
            if skill == "instrument":
                (observe / "otel-instrumentation.html").write_text(
                    CANONICAL_HTML, encoding="utf-8"
                )
        if nested_verify:
            (observe / "otel-verify.md").write_text(VERIFY_REPORT, encoding="utf-8")
        write_capture_manifest(run_dir)

    def reseal(self, root: Path, side: str, skill: str, run: int = 1) -> None:
        write_capture_manifest(root / side / skill / f"run{run}")

    def test_three_run_metrics_and_exact_report_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for run, before, after in zip(range(1, 4), (10, 20, 30), (5, 10, 15)):
                self.write_run(
                    root,
                    side="before",
                    skill="audit",
                    run=run,
                    duration=before,
                    commands=run * 10,
                    tokens=run * 100,
                    report=AUDIT_REPORT.format(route="/tasks"),
                )
                self.write_run(
                    root,
                    side="after",
                    skill="audit",
                    run=run,
                    duration=after,
                    commands=run * 5,
                    tokens=run * 50,
                    report=AUDIT_REPORT.format(route="/tasks"),
                )

            result = build_benchmark(root, repo, ["audit"], 3)

        skill = result["skills"][0]
        duration = skill["performance"]["agent_duration_seconds"]
        self.assertEqual(duration["before"]["median"], 20.0)
        self.assertEqual(duration["after"]["median"], 10.0)
        self.assertEqual(duration["improvement_percent"], 50.0)
        self.assertEqual(
            duration["paired"]["runs"],
            [
                {
                    "run": "run1",
                    "before": 10,
                    "after": 5,
                    "delta": -5.0,
                    "change_percent": -50.0,
                    "improvement_percent": 50.0,
                },
                {
                    "run": "run2",
                    "before": 20,
                    "after": 10,
                    "delta": -10.0,
                    "change_percent": -50.0,
                    "improvement_percent": 50.0,
                },
                {
                    "run": "run3",
                    "before": 30,
                    "after": 15,
                    "delta": -15.0,
                    "change_percent": -50.0,
                    "improvement_percent": 50.0,
                },
            ],
        )
        self.assertEqual(
            duration["paired"]["delta"],
            {"count": 3, "min": -15.0, "median": -10.0, "mean": -10.0, "max": -5.0},
        )
        self.assertEqual(
            duration["paired"]["change_percent"],
            {"count": 3, "min": -50.0, "median": -50.0, "mean": -50.0, "max": -50.0},
        )
        self.assertEqual(
            duration["paired"]["improvement_percent"],
            {"count": 3, "min": 50.0, "median": 50.0, "mean": 50.0, "max": 50.0},
        )
        self.assertEqual(skill["reports"]["markdown"]["paired_count"], 3)
        self.assertEqual(skill["reports"]["markdown"]["exact_pairs"], 3)
        self.assertEqual(
            skill["reports"]["markdown"]["consensus"]["overlap"], 1.0
        )
        self.assertEqual(skill["reports"]["canonical_json"]["exact_pairs"], 3)
        self.assertTrue(canonical_equality_satisfied(result, 3))
        self.assertTrue(result["complete"])
        self.assertTrue(result["validators_ok"])

    def test_consensus_overlap_exposes_stable_report_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for run in range(1, 4):
                self.write_run(
                    root,
                    side="before",
                    skill="audit",
                    run=run,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=AUDIT_REPORT.format(route="/tasks"),
                )
                self.write_run(
                    root,
                    side="after",
                    skill="audit",
                    run=run,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=AUDIT_REPORT.format(route="/orders"),
                )

            result = build_benchmark(root, repo, ["audit"], 3)

        reports = result["skills"][0]["reports"]["markdown"]
        self.assertEqual(reports["exact_pairs"], 0)
        self.assertLess(reports["consensus"]["overlap"], 1.0)
        self.assertTrue(any("/tasks" in fact for fact in reports["consensus"]["lost_facts"]))
        self.assertTrue(any("/orders" in fact for fact in reports["consensus"]["added_facts"]))

    def test_canonical_json_comparison_detects_change_hidden_by_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="instrument",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=INSTRUMENT_REPORT,
                )
            selection = next(
                (root / "after/instrument/run1").rglob(
                    "service/.observe/otel-selection.json"
                )
            )
            selection.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "decision_answers": {"OTEL-002": "replace"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            self.reseal(root, "after", "instrument")

            result = build_benchmark(root, repo, ["instrument"], 1)

        reports = result["skills"][0]["reports"]
        self.assertEqual(reports["markdown"]["exact_pairs"], 1)
        self.assertEqual(reports["canonical_json"]["paired_count"], 1)
        self.assertEqual(reports["canonical_json"]["exact_pairs"], 0)
        self.assertNotEqual(
            reports["canonical_json"]["pairs"][0]["before_sha256"],
            reports["canonical_json"]["pairs"][0]["after_sha256"],
        )
        self.assertFalse(canonical_equality_satisfied(result, 1))

    def test_custom_treatment_directory_can_be_selected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            self.write_run(
                root,
                side="before",
                skill="audit",
                run=1,
                duration=10,
                commands=10,
                tokens=100,
                report=AUDIT_REPORT.format(route="/tasks"),
            )
            self.write_run(
                root,
                side="after-wrapper",
                skill="audit",
                run=1,
                duration=5,
                commands=5,
                tokens=50,
                report=AUDIT_REPORT.format(route="/tasks"),
            )

            result = build_benchmark(
                root,
                repo,
                ["audit"],
                1,
                {"before": "before", "after": "after-wrapper"},
            )

        self.assertTrue(result["complete"])
        self.assertEqual(result["side_directories"]["after"], "after-wrapper")
        after = result["skills"][0]["performance"]["agent_duration_seconds"]["after"]
        self.assertEqual(after["median"], 5.0)

    def test_equivalent_skill_content_at_a_different_path_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="audit",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=AUDIT_REPORT.format(route="/tasks"),
                )

            expected = repo / "skills/otel-audit/SKILL.md"
            equivalent = root / "preserved-skill/otel-audit/SKILL.md"
            equivalent.parent.mkdir(parents=True)
            equivalent.write_bytes(expected.read_bytes())
            trace = next((root / "after/audit/run1").rglob("with_skill/trace.jsonl"))
            event = json.loads(trace.read_text(encoding="utf-8"))
            event["item"]["command"] = (
                f"/bin/zsh -lc \"sed -n '1,999p' {equivalent}\""
            )
            trace.write_text(json.dumps(event) + "\n", encoding="utf-8")
            self.reseal(root, "after", "audit")

            result = build_benchmark(root, repo, ["audit"], 1)

        self.assertTrue(result["complete"])

    def test_message_and_reference_read_do_not_prove_the_skill_was_loaded(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="verify",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=VERIFY_REPORT,
                )

            unique_name = "otel-verify-benchmark"
            unique_skill = repo / "skills" / unique_name
            unique_skill.mkdir(parents=True)
            (unique_skill / "SKILL.md").write_text(
                f"---\nname: {unique_name}\n---\n# unique\n", encoding="utf-8"
            )
            shared_reference = repo / "skills/references/report-flow-contract.md"
            shared_reference.parent.mkdir(parents=True, exist_ok=True)
            shared_reference.write_text("# Report flow\n", encoding="utf-8")

            validation = root / "after/verify/run1/runs/validation.json"
            validation_data = json.loads(validation.read_text(encoding="utf-8"))
            validation_data["results"][0]["skill"] = unique_name
            validation_data["results"][0]["skill_path"] = str(unique_skill)
            validation.write_text(json.dumps(validation_data), encoding="utf-8")
            provenance = root / (
                "after/verify/run1/cases/go/sample/benchmark/with_skill/"
                ".codex-eval-provenance.json"
            )
            provenance_data = json.loads(provenance.read_text(encoding="utf-8"))
            provenance_data["case"]["skill"] = unique_name
            provenance_data["skill"] = {
                "path": str(unique_skill),
                "tree_sha256": tree_sha256(unique_skill),
            }
            provenance_data["shared_references"]["tree_sha256"] = tree_sha256(
                repo / "skills/references"
            )
            provenance.write_text(json.dumps(provenance_data), encoding="utf-8")
            before_provenance = root / (
                "before/verify/run1/cases/go/sample/benchmark/with_skill/"
                ".codex-eval-provenance.json"
            )
            before_provenance_data = json.loads(
                before_provenance.read_text(encoding="utf-8")
            )
            before_provenance_data["shared_references"]["tree_sha256"] = (
                tree_sha256(repo / "skills/references")
            )
            before_provenance.write_text(
                json.dumps(before_provenance_data), encoding="utf-8"
            )
            traced_reference = unique_skill / "../references/report-flow-contract.md"
            events = [
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_message",
                        "type": "agent_message",
                        "text": f"I’ll use the `{unique_name}` skill for this run.",
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_reference",
                        "type": "command_execution",
                        "command": f"sed -n '1,200p' {traced_reference}",
                        "aggregated_output": shared_reference.read_text(
                            encoding="utf-8"
                        ),
                        "exit_code": 0,
                    },
                },
            ]
            trace = next((root / "after/verify/run1").rglob("with_skill/trace.jsonl"))
            trace.write_text(
                "".join(json.dumps(event) + "\n" for event in events),
                encoding="utf-8",
            )
            self.reseal(root, "before", "verify")
            self.reseal(root, "after", "verify")

            result = build_benchmark(root, repo, ["verify"], 1)

        self.assertFalse(result["complete"])
        run = result["skills"][0]["sides"]["after"]["runs"][0]
        self.assertEqual(len(run["errors"]), 1)
        self.assertIn("skill load mismatch", run["errors"][0])
        self.assertIn(
            "a reference read or agent message cannot prove",
            run["errors"][0],
        )

    def test_stale_skill_read_marks_run_incomplete_even_if_discovery_mentions_expected_path(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="verify",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=VERIFY_REPORT,
                )

            expected = repo / "skills/otel-verify/SKILL.md"
            stale = root / "overlay/otel-verify/SKILL.md"
            stale.parent.mkdir(parents=True)
            stale.write_text("---\nname: otel-verify\n---\n# stale\n", encoding="utf-8")
            stale_reference = stale.parent / "references/project-runtime-resolution.md"
            stale_reference.parent.mkdir(parents=True)
            stale_reference.write_text("# stale reference\n", encoding="utf-8")
            trace = next((root / "after/verify/run1").rglob("with_skill/trace.jsonl"))
            events = [
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_message",
                        "type": "agent_message",
                        "text": "I’ll use the `otel-verify` skill for this run.",
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_discovery",
                        "type": "command_execution",
                        "command": f"rg --files {expected} {stale}",
                        "aggregated_output": f"{expected}\n{stale}\n",
                        "exit_code": 0,
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_skill",
                        "type": "command_execution",
                        "command": f"/bin/zsh -lc \"sed -n '1,999p' {stale}\"",
                        "aggregated_output": stale.read_text(encoding="utf-8"),
                        "exit_code": 0,
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_reference",
                        "type": "command_execution",
                        "command": f"sed -n '1,999p' {stale_reference}",
                        "aggregated_output": stale_reference.read_text(
                            encoding="utf-8"
                        ),
                        "exit_code": 0,
                    },
                },
            ]
            trace.write_text(
                "".join(json.dumps(event) + "\n" for event in events),
                encoding="utf-8",
            )
            self.reseal(root, "after", "verify")

            result = build_benchmark(root, repo, ["verify"], 1)

        self.assertFalse(result["complete"])
        run = result["skills"][0]["sides"]["after"]["runs"][0]
        self.assertEqual(len(run["errors"]), 1)
        self.assertIn("skill load mismatch", run["errors"][0])
        self.assertIn(str(expected), run["errors"][0])
        self.assertIn(str(stale), run["errors"][0])

    def test_instrument_without_audit_validates_nested_verify(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="instrument",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=INSTRUMENT_REPORT,
                    nested_verify=True,
                    canonical=False,
                )

            result = build_benchmark(root, repo, ["instrument"], 1)

        run = result["skills"][0]["sides"]["before"]["runs"][0]
        validators = {item["name"]: item["status"] for item in run["validators"]}
        self.assertEqual(validators["instrument_gap_closure"], "not_applicable")
        self.assertEqual(validators["nested_verify_reader_report"], "passed")
        self.assertEqual(run["validator_status"], "passed")

    def test_instrument_without_nested_verify_compares_primary_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="instrument",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=INSTRUMENT_REPORT,
                    nested_verify=False,
                    canonical=False,
                )

            result = build_benchmark(root, repo, ["instrument"], 1)

        for side in ("before", "after"):
            run = result["skills"][0]["sides"][side]["runs"][0]
            validators = {
                item["name"]: item["status"] for item in run["validators"]
            }
            self.assertEqual(
                validators["instrument_gap_closure"], "not_applicable"
            )
            self.assertEqual(
                validators["nested_verify_reader_report"], "not_applicable"
            )
            self.assertEqual(run["validator_status"], "not_applicable")

        reports = result["skills"][0]["reports"]["markdown"]
        self.assertEqual(reports["paired_count"], 1)
        self.assertEqual(reports["exact_pairs"], 1)
        self.assertTrue(result["complete"])
        self.assertFalse(result["validators_ok"])

    def test_required_canonical_json_and_html_are_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="audit",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=AUDIT_REPORT.format(route="/tasks"),
                )
            observe = next((root / "after/audit/run1").rglob("service/.observe"))
            (observe / "otel-audit.json").unlink()
            self.reseal(root, "after", "audit")

            result = build_benchmark(root, repo, ["audit"], 1)

        run = result["skills"][0]["sides"]["after"]["runs"][0]
        validators = {item["name"]: item for item in run["validators"]}
        self.assertEqual(validators["audit_canonical_json"]["status"], "missing")
        self.assertEqual(validators["audit_canonical_html"]["status"], "missing")
        self.assertFalse(result["validators_ok"])

    def test_noncanonical_html_fails_fresh_render_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="instrument",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=INSTRUMENT_REPORT,
                )
            html = next(
                (root / "after/instrument/run1").rglob(
                    "service/.observe/otel-instrumentation.html"
                )
            )
            html.write_text("<!doctype html><html>stale</html>\n", encoding="utf-8")
            self.reseal(root, "after", "instrument")

            result = build_benchmark(root, repo, ["instrument"], 1)

        run = result["skills"][0]["sides"]["after"]["runs"][0]
        validator = next(
            item
            for item in run["validators"]
            if item["name"] == "instrument_canonical_html"
        )
        self.assertEqual(validator["status"], "failed")
        self.assertIn("differs from a fresh canonical render", validator["reason"])
        self.assertFalse(result["validators_ok"])

    def test_provenance_binds_task_fixture_skill_config_and_run_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="verify",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=VERIFY_REPORT,
                )

            result = build_benchmark(root, repo, ["verify"], 1)

        run = result["skills"][0]["sides"]["after"]["runs"][0]
        provenance = run["provenance"]
        self.assertEqual(len(provenance["task_sha256"]), 64)
        self.assertTrue(provenance["fixture"]["verified"])
        self.assertEqual(
            provenance["fixture"]["recorded_tree_sha256"],
            provenance["fixture"]["computed_tree_sha256"],
        )
        self.assertTrue(provenance["skill"]["verified"])
        self.assertEqual(
            provenance["skill"]["recorded_tree_sha256"],
            provenance["skill"]["computed_tree_sha256"],
        )
        self.assertTrue(provenance["shared_references"]["verified"])
        self.assertTrue(provenance["harness"]["verified"])
        self.assertEqual(
            len(provenance["harness"]["computed_tree_sha256"]), 64
        )
        self.assertEqual(len(provenance["config"]["sha256"]), 64)
        self.assertEqual(len(provenance["run_manifest"]["sha256"]), 64)
        self.assertEqual(len(provenance["summary"]["sha256"]), 64)
        self.assertEqual(len(provenance["trace"]["sha256"]), 64)
        self.assertIn("otel-verify.json", provenance["outputs"])
        self.assertTrue(result["complete"])
        self.assertTrue(result["validators_ok"])

    def test_changed_rubric_with_same_task_rejects_replayed_case_contract(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="audit",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=AUDIT_REPORT.format(route="/tasks"),
                )

            definition = (
                repo
                / "evals/go/sample/eval/qual/benchmark-audit.json"
            )
            current = json.loads(definition.read_text(encoding="utf-8"))
            original_task = current["prompts"][0]["task"]
            current["rubric"] = ["A newly required semantic contract."]
            definition.write_text(json.dumps(current), encoding="utf-8")
            definition_hash = hashlib.sha256(
                definition.read_bytes()
            ).hexdigest()
            fixture_hash = tree_sha256(definition.parents[2])

            for side in ("before", "after"):
                provenance_path = next(
                    (root / side / "audit/run1").rglob(
                        "with_skill/.codex-eval-provenance.json"
                    )
                )
                provenance = json.loads(
                    provenance_path.read_text(encoding="utf-8")
                )
                self.assertEqual(provenance["case"]["task"], original_task)
                provenance["definition"]["sha256"] = definition_hash
                provenance["fixture"]["tree_sha256"] = fixture_hash
                provenance_path.write_text(
                    json.dumps(provenance),
                    encoding="utf-8",
                )
                self.reseal(root, side, "audit")

            result = build_benchmark(root, repo, ["audit"], 1)

        self.assertFalse(result["complete"])
        for side in ("before", "after"):
            run = result["skills"][0]["sides"][side]["runs"][0]
            self.assertTrue(
                any(
                    "case.contract_sha256 differs from the current eval definition"
                    in error
                    for error in run["errors"]
                )
            )

    def test_definition_snapshot_rejects_hybrid_contract_and_digest(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="audit",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=AUDIT_REPORT.format(route="/tasks"),
                )

            definition = (
                repo
                / "evals/go/sample/eval/qual/benchmark-audit.json"
            )
            original_bytes = definition.read_bytes()
            changed = json.loads(original_bytes)
            changed["rubric"] = ["A contract from different definition bytes."]
            changed_bytes = json.dumps(changed).encode("utf-8")
            definition.write_bytes(changed_bytes)
            changed_definition_hash = hashlib.sha256(
                changed_bytes
            ).hexdigest()
            changed_fixture_hash = tree_sha256(definition.parents[2])

            for side in ("before", "after"):
                provenance_path = next(
                    (root / side / "audit/run1").rglob(
                        "with_skill/.codex-eval-provenance.json"
                    )
                )
                provenance = json.loads(
                    provenance_path.read_text(encoding="utf-8")
                )
                provenance["definition"]["sha256"] = (
                    changed_definition_hash
                )
                provenance["fixture"]["tree_sha256"] = (
                    changed_fixture_hash
                )
                provenance_path.write_text(
                    json.dumps(provenance),
                    encoding="utf-8",
                )
                self.reseal(root, side, "audit")

            original_snapshot_reader = (
                benchmark_module.read_file_digest_snapshot
            )
            snapshot_reads = 0

            def read_original_then_swap(path: Path):
                nonlocal snapshot_reads
                if path.resolve() != definition.resolve():
                    return original_snapshot_reader(path)
                snapshot_reads += 1
                definition.write_bytes(original_bytes)
                captured = original_snapshot_reader(path)
                definition.write_bytes(changed_bytes)
                return captured

            with patch.object(
                benchmark_module,
                "read_file_digest_snapshot",
                side_effect=read_original_then_swap,
            ):
                result = build_benchmark(root, repo, ["audit"], 1)

        self.assertEqual(snapshot_reads, 2)
        self.assertFalse(result["complete"])
        for side in ("before", "after"):
            run = result["skills"][0]["sides"][side]["runs"][0]
            self.assertTrue(
                any(
                    "definition.sha256 does not match" in error
                    for error in run["errors"]
                )
            )

    def test_changed_harness_source_invalidates_captured_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="verify",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=VERIFY_REPORT,
                )
            (repo / "pytest-codex-evals/src/pytest_codex_evals/__init__.py").write_text(
                "# changed harness source\n", encoding="utf-8"
            )

            result = build_benchmark(root, repo, ["verify"], 1)

        self.assertFalse(result["complete"])
        for side in ("before", "after"):
            run = result["skills"][0]["sides"][side]["runs"][0]
            self.assertTrue(
                any("harness.tree_sha256 does not match" in error for error in run["errors"])
            )

    def test_capture_manifest_rejects_post_capture_mutations(self) -> None:
        targets = {
            "summary": "cases/go/sample/benchmark/with_skill/summary.json",
            "trace": "cases/go/sample/benchmark/with_skill/trace.jsonl",
            "raw result": "runs/validation.json",
            "report output": (
                "cases/go/sample/benchmark/with_skill/service/.observe/otel-verify.md"
            ),
        }
        for label, relative in targets.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                repo = self.make_repo(root)
                for side in ("before", "after"):
                    self.write_run(
                        root,
                        side=side,
                        skill="verify",
                        run=1,
                        duration=10,
                        commands=10,
                        tokens=100,
                        report=VERIFY_REPORT,
                    )
                target = root / "after/verify/run1" / relative
                target.write_bytes(target.read_bytes() + b"\npost-capture mutation\n")

                result = build_benchmark(root, repo, ["verify"], 1)

                self.assertFalse(result["complete"])
                run = result["skills"][0]["sides"]["after"]["runs"][0]
                self.assertTrue(
                    any(
                        f"captured artifact changed after capture: {relative}" in error
                        for error in run["errors"]
                    )
                )

    def test_capture_manifest_rejects_unsealed_added_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="audit",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=AUDIT_REPORT.format(route="/tasks"),
                )
            added = root / (
                "after/audit/run1/cases/go/sample/benchmark/with_skill/"
                "service/.observe/unsealed.json"
            )
            added.write_text("{}\n", encoding="utf-8")

            result = build_benchmark(root, repo, ["audit"], 1)

        self.assertFalse(result["complete"])
        errors = result["skills"][0]["sides"]["after"]["runs"][0]["errors"]
        self.assertTrue(any("unsealed artifacts were added" in error for error in errors))

    def test_unique_run_ids_do_not_break_behavioral_provenance_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for run_number in (1, 2, 3):
                for side in ("before", "after"):
                    self.write_run(
                        root,
                        side=side,
                        skill="audit",
                        run=run_number,
                        duration=10,
                        commands=10,
                        tokens=100,
                        report=AUDIT_REPORT.format(route="/tasks"),
                    )
                    provenance_path = root / (
                        f"{side}/audit/run{run_number}/cases/go/sample/benchmark/"
                        "with_skill/.codex-eval-provenance.json"
                    )
                    provenance = json.loads(
                        provenance_path.read_text(encoding="utf-8")
                    )
                    configuration = provenance["run_configuration"]["value"]
                    configuration["run_id"] = f"{side}-run-{run_number}"
                    provenance["run_configuration"]["sha256"] = hashlib.sha256(
                        json.dumps(
                            configuration,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()
                    provenance_path.write_text(
                        json.dumps(provenance), encoding="utf-8"
                    )
                    validation_path = (
                        root
                        / f"{side}/audit/run{run_number}/runs/validation.json"
                    )
                    validation = json.loads(
                        validation_path.read_text(encoding="utf-8")
                    )
                    validation["metadata"] = configuration
                    validation_path.write_text(
                        json.dumps(validation), encoding="utf-8"
                    )
                    self.reseal(root, side, "audit", run_number)

            result = build_benchmark(root, repo, ["audit"], 3)

        self.assertTrue(result["complete"])
        self.assertTrue(result["skills"][0]["provenance"]["comparable"])

    def test_each_side_requires_one_selected_skill_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for run_number in (1, 2):
                for side in ("before", "after"):
                    self.write_run(
                        root,
                        side=side,
                        skill="audit",
                        run=run_number,
                        duration=10,
                        commands=10,
                        tokens=100,
                        report=AUDIT_REPORT.format(route="/tasks"),
                    )
            alternate = repo / "skills/otel-audit-alternate"
            alternate.mkdir()
            (alternate / "SKILL.md").write_text(
                "---\nname: otel-audit\n---\n# alternate\n", encoding="utf-8"
            )
            run_dir = root / "after/audit/run2"
            validation_path = run_dir / "runs/validation.json"
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
            validation["results"][0]["skill_path"] = str(alternate)
            validation_path.write_text(json.dumps(validation), encoding="utf-8")
            provenance_path = run_dir / (
                "cases/go/sample/benchmark/with_skill/.codex-eval-provenance.json"
            )
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance["skill"] = {
                "path": str(alternate),
                "tree_sha256": tree_sha256(alternate),
            }
            provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
            trace_path = run_dir / "cases/go/sample/benchmark/with_skill/trace.jsonl"
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            trace["item"]["command"] = f"sed -n '1,999p' {alternate / 'SKILL.md'}"
            trace_path.write_text(json.dumps(trace) + "\n", encoding="utf-8")
            self.reseal(root, "after", "audit", 2)

            result = build_benchmark(root, repo, ["audit"], 2)

        self.assertFalse(result["complete"])
        comparison = result["skills"][0]["provenance"]
        self.assertEqual(comparison["skill_identity_count_by_side"]["before"], 1)
        self.assertEqual(comparison["skill_identity_count_by_side"]["after"], 2)

    def test_changed_definition_and_config_invalidate_captured_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="verify",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=VERIFY_REPORT,
                )
            definition = repo / "evals/go/sample/eval/qual/benchmark-verify.json"
            value = json.loads(definition.read_text(encoding="utf-8"))
            value["rubric"] = ["Changed rubric without renaming the prompt."]
            definition.write_text(json.dumps(value), encoding="utf-8")
            (repo / "evals/codex-evals.toml").write_text(
                '[run]\nmode = "ab"\n', encoding="utf-8"
            )

            result = build_benchmark(root, repo, ["verify"], 1)

        self.assertFalse(result["complete"])
        run = result["skills"][0]["sides"]["after"]["runs"][0]
        self.assertTrue(
            any("definition.sha256 does not match" in error for error in run["errors"])
        )
        self.assertTrue(
            any("config.sha256 does not match" in error for error in run["errors"])
        )

    def test_symlinked_preserved_output_is_rejected_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="verify",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=VERIFY_REPORT,
                )
            report = next(
                (root / "after/verify/run1").rglob(
                    "service/.observe/otel-verify.md"
                )
            )
            outside = root / "outside-report.md"
            outside.write_text(VERIFY_REPORT, encoding="utf-8")
            report.unlink()
            report.symlink_to(outside)

            result = build_benchmark(root, repo, ["verify"], 1)

        self.assertFalse(result["complete"])
        run = result["skills"][0]["sides"]["after"]["runs"][0]
        self.assertTrue(
            any("symlink" in error for error in run["errors"])
        )

    def test_symlinked_run_ancestor_cannot_escape_benchmark_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as external_directory:
            root = Path(directory)
            external = Path(external_directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="verify",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=VERIFY_REPORT,
                )
            escaped = external / "after"
            (root / "after").rename(escaped)
            (root / "after").symlink_to(escaped, target_is_directory=True)

            result = build_benchmark(root, repo, ["verify"], 1)

        self.assertFalse(result["complete"])
        run = result["skills"][0]["sides"]["after"]["runs"][0]
        self.assertTrue(
            any("traverses a symlink" in error for error in run["errors"])
        )

    def test_symlinked_nested_side_directory_cannot_escape_run_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="verify",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=VERIFY_REPORT,
                )
            side_dir = root / (
                "after/verify/run1/cases/go/sample/benchmark/with_skill"
            )
            escaped = root / "outside-with-skill"
            side_dir.rename(escaped)
            side_dir.symlink_to(escaped, target_is_directory=True)

            result = build_benchmark(root, repo, ["verify"], 1)

        self.assertFalse(result["complete"])
        errors = result["skills"][0]["sides"]["after"]["runs"][0]["errors"]
        self.assertTrue(any("symlink" in error for error in errors))

    def test_cli_output_rejects_precreated_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            benchmark_root = root / "benchmark"
            benchmark_root.mkdir()
            outside = root / "outside.json"
            outside.write_text('{"sentinel":true}\n', encoding="utf-8")
            output = benchmark_root / "aggregate.json"
            output.symlink_to(outside)
            argv = [
                "aggregate_skill_benchmark.py",
                str(benchmark_root),
                "--repo-root",
                str(repo),
                "--skills",
                "audit",
                "--expected-runs",
                "1",
                "--allow-incomplete",
                "--output",
                str(output),
            ]

            with patch("sys.argv", argv), self.assertRaisesRegex(
                ValueError, "aggregate output must not be a symlink"
            ):
                main()

            self.assertEqual(
                outside.read_text(encoding="utf-8"), '{"sentinel":true}\n'
            )

    def test_cli_output_rejects_symlinked_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            benchmark_root = root / "benchmark"
            benchmark_root.mkdir()
            outside = root / "outside"
            (outside / "sub").mkdir(parents=True)
            (benchmark_root / "link").symlink_to(
                outside, target_is_directory=True
            )
            output = benchmark_root / "link/sub/result.json"
            argv = [
                "aggregate_skill_benchmark.py",
                str(benchmark_root),
                "--repo-root",
                str(repo),
                "--skills",
                "audit",
                "--expected-runs",
                "1",
                "--allow-incomplete",
                "--output",
                str(output),
            ]

            with patch("sys.argv", argv), self.assertRaisesRegex(
                ValueError, "traverses a symlink"
            ):
                main()

            self.assertFalse((outside / "sub/result.json").exists())

    def test_capture_snapshot_creation_refuses_ancestor_namespace_swap(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "snapshot"
            destination.mkdir()
            stolen = root / "stolen-snapshot"
            outside = root / "outside"
            outside.mkdir()
            real_mkdir = benchmark_module.os.mkdir
            swapped = False

            def mkdir_after_swap(*args, **kwargs):
                nonlocal swapped
                if not swapped:
                    destination.rename(stolen)
                    destination.symlink_to(outside, target_is_directory=True)
                    swapped = True
                return real_mkdir(*args, **kwargs)

            with patch(
                "pytest_codex_evals.backends.os.mkdir",
                side_effect=mkdir_after_swap,
            ), self.assertRaisesRegex(ValueError, "namespace changed"):
                benchmark_module.materialize_capture_snapshot(
                    destination,
                    {"nested/artifact.bin": b"authenticated"},
                )

            self.assertTrue(swapped)
            self.assertFalse((outside / "nested").exists())
            self.assertFalse((outside / "nested/artifact.bin").exists())

    def test_capture_snapshot_has_portable_no_dir_fd_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "snapshot"
            destination.mkdir()

            with patch(
                "pytest_codex_evals.backends.descriptor_operations_supported",
                return_value=False,
            ):
                benchmark_module.materialize_capture_snapshot(
                    destination,
                    {"nested/artifact.bin": b"authenticated"},
                )

            self.assertEqual(
                (destination / "nested/artifact.bin").read_bytes(),
                b"authenticated",
            )

    def test_aggregate_output_creation_refuses_ancestor_namespace_swap(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            benchmark_root = root / "benchmark"
            benchmark_root.mkdir()
            stolen = root / "stolen-benchmark"
            outside = root / "outside"
            outside.mkdir()
            output = benchmark_root / "nested/result.json"
            real_mkdir = benchmark_module.os.mkdir
            swapped = False

            def mkdir_after_swap(*args, **kwargs):
                nonlocal swapped
                if not swapped:
                    benchmark_root.rename(stolen)
                    benchmark_root.symlink_to(
                        outside,
                        target_is_directory=True,
                    )
                    swapped = True
                return real_mkdir(*args, **kwargs)

            with patch(
                "pytest_codex_evals.backends.os.mkdir",
                side_effect=mkdir_after_swap,
            ), self.assertRaisesRegex(ValueError, "namespace changed"):
                benchmark_module.write_aggregate_output(
                    output,
                    "{}\n",
                    benchmark_root=benchmark_root,
                    repo_root=repo,
                )

            self.assertTrue(swapped)
            self.assertFalse((outside / "nested").exists())
            self.assertFalse((outside / "nested/result.json").exists())

    def test_missing_evaluator_provenance_makes_capture_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="verify",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=VERIFY_REPORT,
                )
            manifest = next(
                (root / "after/verify/run1").rglob(
                    "with_skill/.codex-eval-provenance.json"
                )
            )
            manifest.unlink()
            self.reseal(root, "after", "verify")

            result = build_benchmark(root, repo, ["verify"], 1)

        run = result["skills"][0]["sides"]["after"]["runs"][0]
        self.assertFalse(result["complete"])
        self.assertTrue(
            any("evaluator provenance manifest" in error for error in run["errors"])
        )

    def test_fixture_provenance_mismatch_invalidates_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="audit",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=AUDIT_REPORT.format(route="/tasks"),
                )
            manifest = next(
                (root / "after/audit/run1").rglob(
                    "with_skill/.codex-eval-provenance.json"
                )
            )
            manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
            manifest_data["fixture"]["tree_sha256"] = "f" * 64
            manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
            self.reseal(root, "after", "audit")

            result = build_benchmark(root, repo, ["audit"], 1)

        provenance = result["skills"][0]["provenance"]
        self.assertFalse(provenance["comparable"])
        self.assertFalse(provenance["pairs"][0]["match"])
        self.assertFalse(result["complete"])

    def test_identical_forged_fixture_digests_do_not_authenticate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="audit",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=AUDIT_REPORT.format(route="/tasks"),
                )
                manifest = next(
                    (root / f"{side}/audit/run1").rglob(
                        "with_skill/.codex-eval-provenance.json"
                    )
                )
                manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
                manifest_data["fixture"]["tree_sha256"] = "f" * 64
                manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
                self.reseal(root, side, "audit")

            result = build_benchmark(root, repo, ["audit"], 1)

        skill = result["skills"][0]
        self.assertFalse(skill["provenance"]["comparable"])
        self.assertFalse(result["complete"])
        for side in ("before", "after"):
            run = skill["sides"][side]["runs"][0]
            self.assertFalse(run["provenance"]["fixture"]["verified"])
            self.assertTrue(
                any("tree_sha256 does not match" in error for error in run["errors"])
            )

    def test_fixture_changed_after_capture_invalidates_both_sides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="audit",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=AUDIT_REPORT.format(route="/tasks"),
                )
            (repo / "evals/go/sample/main.go").write_text(
                "package main\n// changed after capture\n", encoding="utf-8"
            )

            result = build_benchmark(root, repo, ["audit"], 1)

        skill = result["skills"][0]
        self.assertFalse(skill["provenance"]["comparable"])
        self.assertFalse(result["complete"])
        for side in ("before", "after"):
            fixture = skill["sides"][side]["runs"][0]["provenance"]["fixture"]
            self.assertFalse(fixture["verified"])
            self.assertNotEqual(
                fixture["recorded_tree_sha256"], fixture["computed_tree_sha256"]
            )

    def test_validator_failure_is_an_aggregate_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root, verify_exit=1)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="verify",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=VERIFY_REPORT,
                )

            result = build_benchmark(root, repo, ["verify"], 1)

        self.assertTrue(result["complete"])
        self.assertFalse(result["validators_ok"])
        self.assertEqual(
            result["skills"][0]["sides"]["after"]["runs"][0]["validator_status"],
            "failed",
        )

    def test_missing_runs_are_reported_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            result = build_benchmark(root, repo, ["audit"], 3)

        self.assertFalse(result["complete"])
        first = result["skills"][0]["sides"]["before"]["runs"][0]
        self.assertIn("missing run directory", first["errors"][0])

    def test_missing_required_metric_makes_capture_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="audit",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=AUDIT_REPORT.format(route="/tasks"),
                )
            summary_path = next((root / "after/audit/run1").rglob("summary.json"))
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            del summary["agent_tokens"]
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            self.reseal(root, "after", "audit")

            result = build_benchmark(root, repo, ["audit"], 1)

        self.assertFalse(result["complete"])
        run = result["skills"][0]["sides"]["after"]["runs"][0]
        self.assertIn(
            "missing or non-numeric required metric: agent_tokens", run["errors"]
        )
        paired = result["skills"][0]["performance"]["agent_tokens"]["paired"]
        self.assertIsNone(paired["runs"][0]["after"])
        self.assertIsNone(paired["runs"][0]["delta"])
        self.assertEqual(
            paired["delta"],
            {"count": 0, "min": None, "median": None, "mean": None, "max": None},
        )

    def test_zero_paired_baseline_has_delta_but_no_percent_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            self.write_run(
                root,
                side="before",
                skill="audit",
                run=1,
                duration=0,
                commands=0,
                tokens=0,
                report=AUDIT_REPORT.format(route="/tasks"),
            )
            self.write_run(
                root,
                side="after",
                skill="audit",
                run=1,
                duration=5,
                commands=5,
                tokens=5,
                report=AUDIT_REPORT.format(route="/tasks"),
            )

            result = build_benchmark(root, repo, ["audit"], 1)

        paired = result["skills"][0]["performance"]["agent_duration_seconds"][
            "paired"
        ]
        self.assertEqual(
            paired["runs"][0],
            {
                "run": "run1",
                "before": 0,
                "after": 5,
                "delta": 5.0,
                "change_percent": None,
                "improvement_percent": None,
            },
        )
        self.assertEqual(
            paired["delta"],
            {"count": 1, "min": 5.0, "median": 5.0, "mean": 5.0, "max": 5.0},
        )
        empty_summary = {
            "count": 0,
            "min": None,
            "median": None,
            "mean": None,
            "max": None,
        }
        self.assertEqual(paired["change_percent"], empty_summary)
        self.assertEqual(paired["improvement_percent"], empty_summary)
        self.assertTrue(result["complete"])

    def test_non_numeric_paired_metric_is_reported_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="audit",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=AUDIT_REPORT.format(route="/tasks"),
                )
            summary_path = next((root / "after/audit/run1").rglob("summary.json"))
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["agent_tokens"] = "unknown"
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            self.reseal(root, "after", "audit")

            result = build_benchmark(root, repo, ["audit"], 1)

        self.assertFalse(result["complete"])
        run = result["skills"][0]["sides"]["after"]["runs"][0]
        self.assertIn(
            "missing or non-numeric required metric: agent_tokens", run["errors"]
        )
        paired = result["skills"][0]["performance"]["agent_tokens"]["paired"]
        self.assertEqual(paired["runs"][0]["after"], "unknown")
        self.assertIsNone(paired["runs"][0]["delta"])
        self.assertEqual(paired["delta"]["count"], 0)

    def test_non_list_summary_errors_makes_capture_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="audit",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=AUDIT_REPORT.format(route="/tasks"),
                )
            summary_path = next((root / "after/audit/run1").rglob("summary.json"))
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["errors"] = "unexpected"
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            self.reseal(root, "after", "audit")

            result = build_benchmark(root, repo, ["audit"], 1)

        self.assertFalse(result["complete"])
        run = result["skills"][0]["sides"]["after"]["runs"][0]
        self.assertIn("summary.errors must be a list when present", run["errors"])

    def test_aggregate_consumes_authenticated_summary_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for side in ("before", "after"):
                self.write_run(
                    root,
                    side=side,
                    skill="audit",
                    run=1,
                    duration=10,
                    commands=10,
                    tokens=100,
                    report=AUDIT_REPORT.format(route="/tasks"),
                )
            original_load = benchmark_module.load_capture_manifest
            mutated = False

            def load_then_mutate(run_dir: Path):
                nonlocal mutated
                authenticated, errors = original_load(run_dir)
                if not mutated:
                    summary = next(run_dir.rglob("with_skill/summary.json"))
                    forged = json.loads(summary.read_text(encoding="utf-8"))
                    forged["agent_duration_seconds"] = 999999
                    summary.write_text(json.dumps(forged), encoding="utf-8")
                    mutated = True
                return authenticated, errors

            with patch.object(
                benchmark_module,
                "load_capture_manifest",
                side_effect=load_then_mutate,
            ):
                result = build_benchmark(root, repo, ["audit"], 1)

        before = result["skills"][0]["performance"][
            "agent_duration_seconds"
        ]["before"]
        self.assertEqual(before["median"], 10.0)
        self.assertTrue(result["complete"])

    def test_authenticated_absence_is_a_comparable_identity(self) -> None:
        digest = "a" * 64

        def artifact(side: str, config: str | None) -> RunArtifact:
            return RunArtifact(
                side=side,
                skill="audit",
                run="run1",
                run_dir=Path(f"/{side}/run1"),
                provenance={
                    "task_sha256": digest,
                    "case_contract_sha256": digest,
                    "definition": {
                        "verified": True,
                        "computed_sha256": digest,
                    },
                    "fixture": {
                        "verified": True,
                        "computed_tree_sha256": digest,
                    },
                    "config": {
                        "verified": True,
                        "computed_sha256": config,
                    },
                    "run_configuration": {
                        "verified": True,
                        "value": {"mode": "with_skill"},
                    },
                    "shared_references": {
                        "verified": True,
                        "computed_tree_sha256": None,
                    },
                    "harness": {
                        "verified": True,
                        "computed_tree_sha256": digest,
                    },
                    "skill": {
                        "verified": True,
                        "computed_tree_sha256": digest,
                    },
                },
            )

        absent = compare_provenance(
            [artifact("before", None)], [artifact("after", None)]
        )
        mixed = compare_provenance(
            [artifact("before", None)], [artifact("after", digest)]
        )

        self.assertTrue(absent["comparable"])
        self.assertEqual(absent["identity_count"], 1)
        self.assertFalse(mixed["comparable"])


if __name__ == "__main__":
    unittest.main()
