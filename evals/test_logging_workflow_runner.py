"""Mock external execution, exercise the candidate's real three-role orchestration."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

import run_logging_workflow as DRIVER
REPORT = load(ROOT / "skills/references/tests/observe_report_fixtures.py", "workflow_report_fixture")
from pytest_codex_evals.backends import AgentResult
from pytest_codex_evals.definitions import GradeCheckResult, GradeResult


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    driver = DRIVER
    workspace = tmp_path / "actor"
    workspace.mkdir()
    output = tmp_path / "archive"
    calls, expected_bytes = [], {}
    state = {"fault": None, "semantic": set(), "runtime": 0, "cleanup": True,
             "runtime_commands": []}
    monkeypatch.setattr(driver.os, "environ", dict(os.environ))
    monkeypatch.setattr(driver.tempfile, "mkdtemp", lambda **kwargs: str(workspace))
    monkeypatch.setattr(driver, "reserve_ports", lambda: dict(rest=1, http=2, grpc=3, app=4))
    monkeypatch.setattr(driver, "prepare_dependencies", lambda *args: None)
    monkeypatch.setattr(driver, "start_receiver", lambda *args: object())
    monkeypatch.setattr(driver, "stop_owned", lambda *args, **kwargs: state["cleanup"])

    def prepare(repo, case, side, target):
        (target / "service").mkdir()
        (target / "service/main.go").write_text("original source\n")
        skill = target / ".agents/skills/otel-audit"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("name: otel-audit\n")
    monkeypatch.setattr(driver, "prepare_side_workspace", prepare)

    class Backend:
        def __init__(self, **kwargs):
            pass

        def run_agent(self, *, prompt, exec_dir, model, timeout):
            role = prompt.split()[0].removeprefix("$otel-")
            assert prompt == f"$otel-{role} ./service"
            assert model == "gpt-6.1-sol"
            assert not any((exec_dir / name).exists() for name in driver.GRADER_FEEDBACK_ARTIFACTS)
            # Retain ordinary handoffs and application work, while excluding grader feedback.
            if calls:
                assert (exec_dir / "service/.observe/otel-audit.json").is_file()
                assert (exec_dir / "service/.observe/actor-audit.md").read_text() == "ordinary audit handoff"
            if role == "verify":
                assert (exec_dir / "service/main.go").read_text() == "instrumented source\n"
                assert (exec_dir / "service/.observe/actor-instrument.md").is_file()
            calls.append(role)
            if state.get("require_fresh_output"):
                assert not (exec_dir / "last_message.md").exists()
            observed = exec_dir / "service/.observe"
            observed.mkdir(exist_ok=True)
            if role == "audit":
                (observed / "otel-audit.json").write_text(json.dumps(REPORT.sample_report()))
            elif role == "instrument":
                (exec_dir / "service/main.go").write_text("instrumented source\n")
            (observed / f"actor-{role}.md").write_text(f"ordinary {role} handoff")
            fault = state["fault"]
            if role == "audit":
                if fault == "source":
                    (exec_dir / "service/main.go").write_text("audit changed application\n")
                if fault == "bundle":
                    (exec_dir / ".agents/skills/otel-audit/SKILL.md").write_text("changed")
                if fault == "blocked_audit":
                    report = REPORT.sample_report()
                    report["meta"]["status"] = "Blocked"
                    report["scan_blockers"] = [{"id": "missing-source", "check": "source-scan",
                        "blocked_scope": ["service"], "prerequisite": "read owned source",
                        "evidence": ["source missing"], "required_action": "restore readable source"}]
                    REPORT.MODULE.normalize_audit_report(report)
                    (observed / "otel-audit.json").write_text(json.dumps(report))
                if fault == "missing_audit":
                    (observed / "otel-audit.json").unlink()
                if fault == "invalid_audit":
                    (observed / "otel-audit.json").write_text('{"kind":"otel-audit"}')
                if fault == "actor_exception":
                    raise TimeoutError("mock actor timed out")
                if fault == "actor_interrupt":
                    raise KeyboardInterrupt
            if role == "instrument" and fault == "audit_binding":
                (observed / "otel-audit.json").write_text(json.dumps(REPORT.sample_report()) + "\n")
            for name in ("trace.jsonl", "last_message.md", "stderr.txt"):
                if name == "last_message.md" and state.get("missing_final_role") == role:
                    continue
                (exec_dir / name).write_text(f"actor {role}")
            if state.get("empty_final_role") == role:
                (exec_dir / "last_message.md").write_text("")
            return AgentResult(7 if fault == "actor_exit" else 0,
                               exec_dir / "trace.jsonl", exec_dir / "last_message.md", exec_dir / "stderr.txt")

        def run_judge(self, **kwargs):
            path = rubric(**kwargs)
            return AgentResult(8 if state["fault"] == "judge_exit" else 0,
                               workspace / "rubric_trace.jsonl", path, workspace / "rubric_stderr.txt")

        def parse_trace(self, trace_path):
            return None
    monkeypatch.setattr(driver, "CodexBackend", Backend)

    def metadata(*args):
        if state["fault"] == "metadata":
            raise AssertionError("unbound model")
        return {"model": "gpt-6.1-sol", "reasoning_effort": "high", "thread_id": "mock"}
    monkeypatch.setattr(driver, "bind_model_metadata", metadata)

    def guards(**kwargs):
        ids = ["final-message-present", "skills-loaded", "skill-instructions-read"]
        if state["fault"] == "missing_guard":
            ids.pop()
        return GradeResult(checks=[GradeCheckResult(id=id, description="mock guard", passed=state["fault"] != "guard",
                           skipped=state["fault"] == "skipped_guard") for id in ids])
    monkeypatch.setattr(driver, "grade_side", guards)

    class Runtime:
        returncode = 0
        def __init__(self, *args, **kwargs):
            state["runtime_commands"].append(args[0])
            self.returncode = state["runtime"]
        def wait(self, timeout):
            assert timeout == 720
            return self.returncode
        def poll(self):
            return self.returncode
    monkeypatch.setattr(driver.subprocess, "Popen", Runtime)

    def rubric(**kwargs):
        role = calls[-1]
        if state["fault"] == "judge_exception":
            raise RuntimeError("mock judge failed")
        checks = [{"id": f"rubric-{i}", "pass": role not in state["semantic"] or i != 2,
                   "evidence": f"private-grade-{role}-{i}", "notes": "mock"} for i in range(1, 15)]
        value = {"overall_pass": role not in state["semantic"], "score": 91, "checks": checks}
        if state["fault"] == "malformed_rubric":
            checks.pop()
        if state["fault"] == "string_bool":
            checks[0]["pass"] = "false"
        if state["fault"] == "invalid_json":
            (workspace / "rubric_grade.json").write_text("not json")
        else:
            (workspace / "rubric_grade.json").write_text(json.dumps(value))
        for name in ("rubric_trace.jsonl", "rubric_stderr.txt"):
            (workspace / name).write_text(f"private-grade-{role}-{name}")
        expected_bytes[role] = {name: (workspace / name).read_bytes() for name in driver.GRADER_FEEDBACK_ARTIFACTS}
        if state["fault"] == "grader_audit":
            path = workspace / "service/.observe/otel-audit.json"
            path.write_text(path.read_text() + "\n")
        if state["fault"] == "grader_bundle":
            (workspace / ".agents/skills/otel-audit/SKILL.md").write_text("grader changed skill")
        if state["fault"] == "grader_source":
            (workspace / "service/main.go").write_text("grader changed source")
        return workspace / "rubric_grade.json"

    args = argparse.Namespace(repo=ROOT, output=output, language="go", trial=1, studio_binary=tmp_path / "unused",
                              codex_home=tmp_path / "home", agent_timeout=1, judge_timeout=1)
    def run(collect=False):
        if collect:
            args.collect_semantic_failures = True
        code = driver.run(args)
        return code, json.loads((output / "summary.json").read_text())
    return SimpleNamespace(run=run, calls=calls, state=state, workspace=workspace, output=output,
                           expected=expected_bytes, driver=driver)


def assert_archives(w):
    for role, artifacts in w.expected.items():
        for name, raw in artifacts.items():
            assert (w.output / role / name).read_bytes() == raw
    audits = [(w.output / role / "service/.observe/otel-audit.json").read_bytes() for role in w.expected]
    assert len(set(audits)) == 1
    assert not any((w.workspace / name).exists() for name in w.driver.GRADER_FEEDBACK_ARTIFACTS)


def test_all_roles_are_bare_feedback_free_and_archives_byte_exact(workflow):
    code, summary = workflow.run()
    assert code == 0 and summary["status"] == "passed"
    assert workflow.calls == ["audit", "instrument", "verify"]
    assert summary["collect_semantic_failures"] is False and summary["diagnostic_only"] is False
    expected_command = [sys.executable, str(ROOT / "evals/logging_workflow_check.py"),
                        "--start-command-json", '["make","dev"]', "--operator-identity-profiles"]
    assert workflow.state["runtime_commands"] == [expected_command, expected_command]
    for stage in summary["stages"][1:]:
        assert stage["independent_runtime_command"] == expected_command
        assert stage["independent_runtime_timeout_seconds"] == 720
    assert_archives(workflow)


def test_default_stops_on_semantic_failure(workflow):
    workflow.state["semantic"] = {"audit"}
    code, summary = workflow.run()
    assert code == 1 and workflow.calls == ["audit"]
    assert summary["stages"][0]["status"] == "failed"
    assert summary["diagnostic_only"] is False
    assert_archives(workflow)


def test_failed_actor_is_archived_without_runtime_or_grading(workflow):
    workflow.state["fault"] = "actor_exit"
    code, summary = workflow.run(collect=True)
    assert code == 1 and workflow.calls == ["audit"]
    assert workflow.state["runtime_commands"] == [] and workflow.expected == {}
    stage = summary["stages"][0]
    assert stage["status"] == "failed" and stage["failure_kind"] == "fatal"
    assert stage["agent_exit_code"] == 7
    assert (workflow.output / "audit/last_message.md").read_text() == "actor audit"


@pytest.mark.parametrize("missing", [True, False])
def test_success_exit_without_current_final_cannot_reuse_prior_stage(workflow, missing):
    workflow.state["missing_final_role" if missing else "empty_final_role"] = "verify"
    code, summary = workflow.run(collect=True)
    assert code == 1 and workflow.calls == ["audit", "instrument", "verify"]
    assert list(workflow.expected) == ["audit", "instrument"]
    assert len(workflow.state["runtime_commands"]) == 1
    assert (workflow.output / "instrument/last_message.md").read_text() == "actor instrument"
    stage = summary["stages"][-1]
    assert stage["status"] == "failed" and stage["failure_kind"] == "fatal"
    assert stage["agent_exit_code"] == 0
    archived = workflow.output / "verify/last_message.md"
    if missing:
        assert not archived.exists()
    else:
        assert archived.read_text() == ""


def test_each_actor_receives_fresh_response_path_with_previous_archive_preserved(workflow):
    workflow.state["require_fresh_output"] = True
    code, summary = workflow.run()
    assert code == 0 and summary["status"] == "passed"
    for role in ["audit", "instrument", "verify"]:
        assert (workflow.output / role / "last_message.md").read_text() == f"actor {role}"


def test_interrupted_actor_records_terminal_failure_and_cleans_receiver(workflow):
    workflow.state["fault"] = "actor_interrupt"
    code, summary = workflow.run(collect=True)
    assert code == 1 and summary["status"] == "failed"
    assert summary["stages"][0]["status"] == "failed"
    assert summary["stages"][0]["failure_kind"] == "fatal"
    assert summary["receiver_cleanup_graceful"] is True
    assert not workflow.expected and not workflow.state["runtime_commands"]


def test_unverified_prior_response_is_preserved_and_blocks_next_actor(workflow, monkeypatch):
    archive = workflow.driver.archive_stage
    def corrupt_response(workspace, destination):
        archive(workspace, destination)
        (destination / "last_message.md").write_text("not the actor response")
    monkeypatch.setattr(workflow.driver, "archive_stage", corrupt_response)
    code, summary = workflow.run()
    assert code == 1 and workflow.calls == ["audit"]
    assert "not safely archived" in summary["error"]
    assert (workflow.workspace / "last_message.md").read_text() == "actor audit"


def test_opt_in_continues_semantic_failure_without_rewriting_grades_or_credit(workflow):
    workflow.state["semantic"] = {"audit", "instrument"}
    code, summary = workflow.run(collect=True)
    assert code == 1 and summary["status"] == "failed" and summary["diagnostic_only"] is True
    assert workflow.calls == ["audit", "instrument", "verify"]
    assert [s["status"] for s in summary["stages"]] == ["failed", "failed", "passed"]
    assert [s["rubric"]["overall_pass"] for s in summary["stages"]] == [False, False, True]
    assert all(s["failure_kind"] == "semantic" and s["diagnostic_continuation"] for s in summary["stages"][:2])
    assert_archives(workflow)


@pytest.mark.parametrize("fault", ["actor_exit", "actor_exception", "guard", "missing_guard", "skipped_guard",
    "source", "bundle", "missing_audit", "invalid_audit", "blocked_audit", "malformed_rubric", "string_bool", "invalid_json",
    "metadata", "judge_exception", "judge_exit", "grader_source", "grader_audit", "grader_bundle"])
def test_opt_in_never_continues_fatal_failures(workflow, fault):
    workflow.state.update(fault=fault, semantic={"audit"})
    code, summary = workflow.run(collect=True)
    assert code == 1 and summary["status"] == "failed" and workflow.calls == ["audit"]
    assert not summary["stages"][0].get("diagnostic_continuation", False)


@pytest.mark.parametrize("fault,runtime", [("audit_binding", 0), (None, 9)])
def test_fatal_later_stage_stops_even_after_diagnostic_continuation(workflow, fault, runtime):
    workflow.state.update(fault=fault, runtime=runtime, semantic={"audit", "instrument"})
    code, summary = workflow.run(collect=True)
    assert code == 1 and workflow.calls == ["audit", "instrument"]
    assert summary["stages"][1]["failure_kind"] == "fatal"


@pytest.mark.parametrize("failure", ["archive_exception", "archive_mismatch"])
def test_archive_failure_stops_before_next_actor_and_preserves_feedback(workflow, monkeypatch, failure):
    original = workflow.driver.archive_stage
    def archive(workspace, destination):
        if failure == "archive_exception":
            raise OSError("mock storage failure")
        original(workspace, destination)
        (destination / "rubric_grade.json").write_text("corrupt archive")
    monkeypatch.setattr(workflow.driver, "archive_stage", archive)
    code, summary = workflow.run(collect=True)
    assert code == 1 and workflow.calls == ["audit"]
    assert all((workflow.workspace / name).read_bytes() == raw for name, raw in workflow.expected["audit"].items())
    assert summary["status"] == "failed"


def test_receiver_cleanup_failure_cannot_get_credit(workflow):
    workflow.state["cleanup"] = False
    code, summary = workflow.run(collect=True)
    assert code == 1 and summary["status"] == "failed"
    assert summary["receiver_cleanup_graceful"] is False


def test_archive_cannot_be_actor_visible_subdirectory(tmp_path):
    with pytest.raises(ValueError, match="outside"):
        DRIVER.isolate_stage_feedback(tmp_path, tmp_path / "archive")


def test_cli_flag_defaults_off_and_is_explicit(monkeypatch):
    seen = []
    monkeypatch.setattr(DRIVER, "run", lambda args: seen.append(args) or 0)
    required = ["driver", "--language", "go", "--trial", "1", "--studio-binary", "unused", "--codex-home", "home", "--output", "output"]
    monkeypatch.setattr(sys, "argv", required)
    assert DRIVER.main() == 0 and seen[-1].collect_semantic_failures is False
    monkeypatch.setattr(sys, "argv", required + ["--collect-semantic-failures"])
    assert DRIVER.main() == 0 and seen[-1].collect_semantic_failures is True
