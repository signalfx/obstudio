"""Mock external execution, exercise the candidate's real three-role orchestration."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
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
from pytest_codex_evals.graders.rubric import rubric_prompt, run_rubric_grade


FIXTURE_CHECKS = {
    "go/chi-basic": ["go", "test", "./..."],
    "java/springboot-basic": ["mvn", "-q", "test"],
    "python/flask-basic": ["uv", "run", "python", "-m", "py_compile", "app.py"],
    "node/express-basic": ["node", "--check", "app.js"],
}


@pytest.mark.parametrize("case", FIXTURE_CHECKS)
@pytest.mark.parametrize("target,configured", [
    ("logging-workflow-check", True), ("test", True), ("test", False),
])
def test_public_make_targets_forward_identity_profiles(tmp_path, case, target, configured):
    service = tmp_path / "service with spaces"
    service.mkdir()
    shutil.copyfile(Path(__file__).parent / case / "Makefile", service / "Makefile")
    verifier = tmp_path / "recording verifier with spaces.py"
    verifier.write_text(
        "import json,os,sys\nfrom pathlib import Path\n"
        "with Path(os.environ['VERIFIER_CALLS']).open('a') as out:\n"
        " out.write(json.dumps({'argv':sys.argv[1:],'cwd':os.getcwd()})+'\\n')\n"
    )
    tools = tmp_path / "fake tools"
    tools.mkdir()
    for name in ("go", "mvn", "uv", "node"):
        executable = tools / name
        executable.write_text(
            "#!" + sys.executable + "\nimport json,os,sys\nfrom pathlib import Path\n"
            "with Path(os.environ['TOOL_CALLS']).open('a') as out:\n"
            " out.write(json.dumps([Path(sys.argv[0]).name,*sys.argv[1:]])+'\\n')\n"
        )
        executable.chmod(0o700)
    env = dict(os.environ)
    for name in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "GNUMAKEFLAGS",
                 "LOGGING_WORKFLOW_VERIFIER", "LOGGING_WORKFLOW_PYTHON"):
        env.pop(name, None)
    env.update(
        PATH=str(tools) + os.pathsep + env.get("PATH", os.defpath),
        PYTHONDONTWRITEBYTECODE="1", LOGGING_WORKFLOW_PYTHON=sys.executable,
        VERIFIER_CALLS=str(tmp_path / "verifier.jsonl"),
        TOOL_CALLS=str(tmp_path / "tools.jsonl"),
    )
    if configured:
        env["LOGGING_WORKFLOW_VERIFIER"] = str(verifier)
    result = subprocess.run(
        ["make", target], cwd=service, env=env, text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls_path, tools_path = Path(env["VERIFIER_CALLS"]), Path(env["TOOL_CALLS"])
    calls = [json.loads(line) for line in calls_path.read_text().splitlines()] if calls_path.exists() else []
    tool_calls = [json.loads(line) for line in tools_path.read_text().splitlines()] if tools_path.exists() else []
    assert tool_calls == ([FIXTURE_CHECKS[case]] if target == "test" else [])
    if configured:
        assert calls == [{
            "argv": ["--start-command-json", '["make","dev"]', "--operator-identity-profiles", "--bake-evidence"],
            "cwd": str(service),
        }]
    else:
        assert calls == []
        assert "Host logging workflow check not configured" in result.stdout


@pytest.mark.parametrize("script", ["logging_workflow_check.py", "run_logging_workflow.py"])
@pytest.mark.parametrize("flags,optimize", [([], None), (["-O"], None), (["-OO"], None), ([], "1"), ([], "2")])
def test_logging_workflow_requires_python_assertions(script, flags, optimize):
    environment = dict(os.environ)
    environment.pop("PYTHONOPTIMIZE", None)
    if optimize is not None:
        environment["PYTHONOPTIMIZE"] = optimize

    result = subprocess.run([sys.executable, *flags, str(ROOT / "evals" / script), "--help"],
                            env=environment, capture_output=True, text=True, timeout=10)

    if flags or optimize is not None:
        assert result.returncode != 0
        assert "Logging workflow requires Python assertions" in result.stderr
        assert "usage:" not in result.stdout
    else:
        assert result.returncode == 0
        assert "usage:" in result.stdout


def test_logging_topics_have_separate_addressable_verdicts():
    common = json.loads((ROOT / "evals/rubrics/logging-common.json").read_text())
    topics = []
    for criterion in common["rubric"]:
        label = re.match(r"\[([A-Z][A-Z0-9-]+)\]\s+\S", criterion)
        assert label, "Each independent verdict needs a named topic"
        topics.append(label.group(1))
        assert not re.search(r"^\(\d+\.[A-Z] ", criterion, re.MULTILINE)
    assert len(topics) == len(set(topics)), "Repeated topics would obscure independent failures"


@pytest.mark.parametrize("language", sorted(DRIVER.SERVICES))
@pytest.mark.parametrize("role", ["audit", "instrument", "verify"])
def test_every_logging_definition_uses_strict_judging_for_each_trial(tmp_path, language, role):
    path = tmp_path / "rubric_grade.json"

    def judge(**kwargs):
        assert kwargs["model"] == "gpt-6.1-sol"
        return AgentResult(0, tmp_path / "trace.jsonl", path, tmp_path / "stderr.txt")

    backend = SimpleNamespace(run_judge=judge)
    for trial in range(1, 4):
        case = DRIVER.case_for(ROOT, language, role, trial)
        count = len(case.rubric)
        checks = [{"id": f"rubric-{i}", "pass": True, "notes": "Mock verdict.",
                   "evidence": "Mock artifact:1; validator wiring only."} for i in range(1, count + 1)]
        assert case.strict_rubric_output is True
        assert case.task == f"$otel-{role} ./service" and case.eval_inputs == []
        assert case.rubric and case.judge_prompt is None
        rendered = rubric_prompt(case)
        sections = ["## 1. Task and scope", "## 2. Evidence map",
                    "## 3. Rubric", "## 4. Output protocol"]
        assert [rendered.index(section) for section in sections] == sorted(
            rendered.index(section) for section in sections)
        assert f"Actor task: {case.task}\n" in rendered
        assert case.judge_inputs
        assert any("evidence-receipt-check.json" in item for item in case.judge_inputs)
        assert "\n".join(f"{i}. {item}" for i, item in enumerate(case.judge_inputs, 1)) in rendered

        raw = json.dumps({"overall_pass": True, "score": 93, "checks": checks[:-1]})
        path.write_text(raw)
        with pytest.raises(ValueError, match=f"exactly {count} checks"):
            run_rubric_grade(case=case, side_dir=tmp_path, model="gpt-6.1-sol", backend=backend)
        assert path.read_text() == raw

        path.write_text(json.dumps({"overall_pass": True, "score": 93, "checks": checks}))
        assert run_rubric_grade(case=case, side_dir=tmp_path, model="gpt-6.1-sol", backend=backend) == path


@pytest.mark.parametrize("count", [1, 3, 14, 60])
def test_workflow_grade_coverage_uses_the_selected_definition(count):
    checks = [{"id": f"rubric-{i}", "pass": True} for i in range(1, count + 1)]
    grade = {"overall_pass": True, "checks": checks}
    assert DRIVER.valid_rubric(grade, count)
    assert not DRIVER.valid_rubric(grade, count + 1)
    assert not DRIVER.valid_rubric(grade, count - 1)
    assert not DRIVER.valid_rubric(grade, True)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "reordered", "string_bool", "false_overall", "hidden_failure"])
def test_workflow_grade_rejects_incomplete_or_inconsistent_independent_verdicts(fault):
    checks = [{"id": f"rubric-{i}", "pass": True} for i in range(1, 4)]
    grade = {"overall_pass": True, "checks": checks}
    if fault == "missing":
        checks.pop()
    elif fault == "duplicate":
        checks[1]["id"] = checks[0]["id"]
    elif fault == "reordered":
        checks.reverse()
    elif fault == "string_bool":
        checks[0]["pass"] = "false"
    elif fault == "false_overall":
        grade["overall_pass"] = False
    else:
        checks[1]["pass"] = False
    assert not DRIVER.valid_rubric(grade, 3)


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

    real_receipt_guard = driver.check_evidence_receipt
    def receipt_guard(repo, target, role):
        if state.get("real_receipt_guard"):
            if role != "audit" and state.get("direct_report_result"):
                direct_flow(target, result=state["direct_report_result"])
            return real_receipt_guard(repo, target, role)
        value = {"status": state.get("receipt_failures", {}).get(role, "N_A"),
                 "reason": "Mock orchestration fixture does not generate canonical verification proof",
                 "command": [], "role": role}
        driver.save(target / "evidence-receipt-check.json", value)
        return value
    monkeypatch.setattr(driver, "check_evidence_receipt", receipt_guard)

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
        assert (workspace / "evidence-receipt-check.json").is_file(), "Independent guard must precede grading"
        if state["fault"] == "judge_exception":
            raise RuntimeError("mock judge failed")
        checks = [{"id": f"rubric-{i}", "pass": role not in state["semantic"] or i != 2,
                   "evidence": f"private-grade-{role}-{i}", "notes": "mock"}
                  for i in range(1, len(driver.case_for(args.repo, args.language, role, args.trial).rubric) + 1)]
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
    for stage in summary["stages"]:
        case = DRIVER.case_for(ROOT, "go", stage["role"], 1)
        contract = json.dumps({"rubric": case.rubric, "judge_inputs": case.judge_inputs},
                              sort_keys=True, separators=(",", ":")).encode()
        assert stage["rubric_contract"] == {
            "criterion_count": len(case.rubric), "sha256": hashlib.sha256(contract).hexdigest(),
        }
    expected_command = [sys.executable, str(ROOT / "evals/logging_workflow_check.py"),
                        "--start-command-json", '["make","dev"]', "--operator-identity-profiles", "--bake-evidence"]
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


@pytest.mark.parametrize("fault", ["missing_audit", "invalid_audit", "blocked_audit"])
def test_default_rejects_unusable_audit_at_the_audit_stage(workflow, fault):
    workflow.state["fault"] = fault
    code, summary = workflow.run()
    assert code == 1 and workflow.calls == ["audit"]
    assert len(summary["stages"]) == 1
    stage = summary["stages"][0]
    assert stage["status"] == "failed" and stage["failure_kind"] == "fatal"
    assert stage["audit_handoff_error"]
    assert not stage.get("diagnostic_continuation", False)
    assert workflow.state["runtime_commands"] == []


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


def test_documented_helper_caches_do_not_change_shipped_bundle_identity(tmp_path):
    workspace = tmp_path / "workspace"
    scripts = workspace / ".agents/skills/references/scripts"
    shutil.copytree(ROOT / "skills/references/scripts", scripts, ignore=DRIVER.skill_workspace_ignore)
    application = workspace / "service/app.py"
    application.parent.mkdir()
    application.write_text('setting = "OTEL_TEST_SETTING"\n')
    before = DRIVER.bundle_hashes(workspace)
    result = subprocess.run(
        [sys.executable, "-I", str(scripts / "observe_report.py"), "source-settings", "--source", str(application)],
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["candidates"][0]["name"] == "OTEL_TEST_SETTING"
    assert list(scripts.rglob("*.pyc")), "Isolated Python ignores the environment-only bytecode flag"
    assert DRIVER.bundle_hashes(workspace) == before
    source = scripts / "observe_report_core.py"
    source.write_bytes(source.read_bytes() + b"\n")
    assert DRIVER.bundle_hashes(workspace) != before


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


@pytest.mark.parametrize("failure", ["archive_exception", "archive_mismatch", "receipt_archive_mismatch"])
def test_archive_failure_stops_before_next_actor_and_preserves_feedback(workflow, monkeypatch, failure):
    original = workflow.driver.archive_stage
    def archive(workspace, destination):
        if failure == "archive_exception":
            raise OSError("mock storage failure")
        original(workspace, destination)
        name = "evidence-receipt-check.json" if failure == "receipt_archive_mismatch" else "rubric_grade.json"
        (destination / name).write_text("corrupt archive")
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


def receipt_flow(workspace, *, result="Pass", missing_manifest_scenario=False):
    """Real canonical fixtures and real receipt API; no model or application run."""
    core = REPORT.MODULE
    service = workspace / "service"
    observed = service / ".observe"
    observed.mkdir(parents=True)
    raw_audit = REPORT.sample_report()
    if missing_manifest_scenario:
        raw_audit["findings"][0]["verification_scenarios"].append("http.checkout.error")
        extra = copy.deepcopy(raw_audit["verification"]["scenarios"][0])
        extra["id"] = "http.checkout.error"
        raw_audit["verification"]["scenarios"].append(extra)
    audit = core.normalize_audit_report(raw_audit)
    digest = core.audit_digest(audit)
    selection = core.normalize_selection({"schema_version":1,"kind":"otel-selection",
        "audit_id":audit["meta"]["audit_id"],"audit_sha256":digest,
        "requested_ids":["OTEL-001"],"approved_ids":["OTEL-001"]},audit)
    instrumentation = REPORT.sample_instrumentation(audit,digest,selection)
    if missing_manifest_scenario:
        instrumentation["findings"][0]["telemetry_changes"][0]["verification_scenarios"].append("http.checkout.error")
    instrumentation = core.normalize_instrumentation(instrumentation,audit,selection)
    report = REPORT.sample_verify(audit,digest,core.instrumentation_digest(instrumentation))
    finding = report["findings"][0]
    scenario, item = finding["scenarios"][0], finding["item_results"][0]
    if result in {"Pass","Fail"}:
        report["meta"]["result"] = result
        status = "working" if result == "Pass" else "not_working"
        finding.update(status=status,remaining=[] if result == "Pass" else ["Observed own-operation mismatch"])
        for row in [scenario,item]:
            row.update(status=status,proof_mode="full_runtime",visibility="otlp_accepted",
                       observed_telemetry=["Own operation record decoded"],product_validation=["Own receiver receipt"])
        scenario["trace_ids"] = ["1" * 32]
        item["direct_assertion_passed"] = result == "Pass"
    elif result in {"Not run","Blocked"}:
        report["meta"]["result"] = result
        for row in [scenario,item]:
            row.update(proof_mode="not_run",visibility="not_proven",evidence=[],
                       observed_telemetry=[],product_validation=[])
        scenario["commands"] = []
        if result == "Blocked":
            scenario.update(status="blocked",blocking_reason="Owned receiver unavailable",
                            unobserved_outcome="No runtime capture",commands=["make test"],
                            evidence=[".observe/evidence/prerequisite.txt"])
    if missing_manifest_scenario:
        extra = copy.deepcopy(scenario);extra["id"] = "http.checkout.error"
        finding["scenarios"].append(extra)
        item["scenarios"].append("http.checkout.error")
    files = {name:observed/filename for name,filename in {
        "audit":"otel-audit.json","selection":"otel-selection.json",
        "instrumentation":"otel-instrumentation.json","report":"otel-verify.json",
        "manifest":"manifest.json","ledger":"observations.json",
        "receipt":"otel-evidence-receipt.json","raw":"raw.json"}.items()}
    files["raw"].write_text('{"actual_test_receipt":true}\n')
    manifest = {"schema_version":1,"kind":"otel-evidence-controls","controls":[{
        "id":"control.checkout","scenario_id":"http.checkout.success","run_id":"owned.run",
        "operation_ids":["checkout.request"],"phase":"source_alive",
        "match":{"method":"GET","outcome":200},"expected":{"joined":True}}]}
    rows = [] if result == "Partial" else [{"id":"own.receipt","run_id":"owned.run",
        "operation_id":"checkout.request","phase":"source_alive","method":"GET","outcome":200,
        "trace_context":{"state":"context","trace_id":"1"*32,"span_id":"2"*16},
        "facts":{"joined":result != "Fail"},"artifacts":[{"path":".observe/raw.json",
        "sha256":hashlib.sha256(files["raw"].read_bytes()).hexdigest()}]}]
    if result in {"Pass","Partial","Fail"} and not missing_manifest_scenario:
        report = core.project_evidence_report(report,core.bake_evidence_report(manifest,rows,service))
    report = core.normalize_verify(report,audit,selection,instrumentation)
    for name,value in [("audit",audit),("selection",selection),("instrumentation",instrumentation),
                       ("report",report),("manifest",manifest),("ledger",rows)]:
        files[name].write_text(json.dumps(value))
    if result in {"Pass","Partial","Fail"}:
        if missing_manifest_scenario:
            # Deliberately forge matching input hashes: rebaking, not a hash-only seal, must reject it.
            receipt = {"schema_version":1,"kind":"otel-evidence-receipt",
                       "artifact_root":{"path":".."},
                       "core_sha256":hashlib.sha256((ROOT/"skills/references/scripts/observe_report_core.py").read_bytes()).hexdigest()}
            for key in ["manifest","ledger","report"]:
                receipt[key] = {"path":files[key].name,"sha256":hashlib.sha256(files[key].read_bytes()).hexdigest()}
        else:
            receipt = core.create_evidence_receipt(files["manifest"],files["ledger"],files["report"],service,files["receipt"])
        files["receipt"].write_text(json.dumps(receipt))
    return files


@pytest.mark.parametrize("result",["Pass","Partial","Fail"])
def test_real_receipt_guard_accepts_bound_canonical_proof_without_mutation(tmp_path,result):
    files = receipt_flow(tmp_path,result=result)
    # A malicious staged helper is never imported by the independent guard.
    staged = tmp_path/".agents/skills/references/scripts/observe_report_core.py"
    staged.parent.mkdir(parents=True)
    staged.write_text('raise RuntimeError("actor-controlled parser executed")\n')
    before = {path:path.read_bytes() for path in files.values()}
    guard = DRIVER.check_evidence_receipt(ROOT,tmp_path,"verify")
    assert guard["status"] == "valid",guard
    assert guard["canonical_result"] == result
    assert guard["validation"]["baked_status"] == {"Pass":"working","Partial":"not_proven","Fail":"failed"}[result]
    assert guard["core"] == str(ROOT/"skills/references/scripts/observe_report_core.py")
    assert guard["execution"] == "in_process_canonical_api"
    assert {path:path.read_bytes() for path in files.values()} == before
    assert json.loads((tmp_path/"evidence-receipt-check.json").read_text()) == guard


@pytest.mark.parametrize("fault",["no_receipt","input_hash_drift","raw_hash_drift","wrong_ids","missing_required_ids","missing_canonical_scenario","different_report"])
def test_real_receipt_guard_rejects_stale_unbound_and_node_style_working_claims(tmp_path,fault):
    files = receipt_flow(tmp_path,missing_manifest_scenario=fault in {"missing_required_ids","missing_canonical_scenario"})
    if fault == "no_receipt":
        files["receipt"].unlink()
    elif fault == "input_hash_drift":
        files["report"].write_text(files["report"].read_text()+"\n")
    elif fault == "raw_hash_drift":
        files["raw"].write_text("tampered raw")
    elif fault == "wrong_ids":
        manifest = json.loads(files["manifest"].read_text())
        manifest["controls"][0]["scenario_id"] = "unrelated.operation"
        files["manifest"].write_text(json.dumps(manifest))
        receipt = json.loads(files["receipt"].read_text())
        receipt["manifest"]["sha256"] = hashlib.sha256(files["manifest"].read_bytes()).hexdigest()
        files["receipt"].write_text(json.dumps(receipt))
    elif fault == "missing_canonical_scenario":
        report = json.loads(files["report"].read_text())
        report["findings"][0]["scenarios"].pop()
        files["report"].write_text(json.dumps(report))
        receipt = json.loads(files["receipt"].read_text())
        receipt["report"]["sha256"] = hashlib.sha256(files["report"].read_bytes()).hexdigest()
        files["receipt"].write_text(json.dumps(receipt))
    elif fault == "different_report":
        other = files["report"].with_name("other-report.json")
        other.write_bytes(files["report"].read_bytes())
        receipt = REPORT.MODULE.create_evidence_receipt(files["manifest"],files["ledger"],other,
            tmp_path/"service",files["receipt"])
        files["receipt"].write_text(json.dumps(receipt))
    before = {p:p.read_bytes() for p in (tmp_path/"service").rglob("*") if p.is_file()}
    guard = DRIVER.check_evidence_receipt(ROOT,tmp_path,"instrument")
    assert guard["status"] == "failed",guard
    assert guard["reason"] and guard["command"]
    assert {p:p.read_bytes() for p in (tmp_path/"service").rglob("*") if p.is_file()} == before
    if fault == "missing_required_ids":
        assert "http.checkout.error" in guard["reason"]
    if fault == "different_report":
        assert "final canonical" in guard["reason"]


@pytest.mark.parametrize("result",["Not run","Blocked"])
def test_receipt_guard_skips_only_valid_canonical_no_execution(tmp_path,result):
    receipt_flow(tmp_path,result=result)
    guard = DRIVER.check_evidence_receipt(ROOT,tmp_path,"verify")
    assert guard["status"] == "N_A",guard
    assert guard["canonical_result"] == result
    assert "no executed proof" in guard["reason"]


@pytest.mark.parametrize("fault",["invalid_json","wrong_kind","fake_not_run","bad_scenarios","executed_blocked"])
def test_malformed_canonical_cannot_bypass_receipt_guard_as_not_applicable(tmp_path,fault):
    files = receipt_flow(tmp_path,result="Not run")
    report = json.loads(files["report"].read_text())
    if fault == "wrong_kind":
        report["kind"] = "unrelated"
    elif fault == "fake_not_run":
        report = {"kind":"otel-verify","meta":{"result":"Not run"}}
    elif fault == "bad_scenarios":
        report["findings"][0]["scenarios"] = None
    elif fault == "executed_blocked":
        report["meta"]["result"] = "Blocked"
        report["findings"][0]["scenarios"][0]["proof_mode"] = "app_test"
    files["report"].write_text("not JSON" if fault == "invalid_json" else json.dumps(report))
    guard = DRIVER.check_evidence_receipt(ROOT,tmp_path,"verify")
    assert guard["status"] == "failed",guard


def test_receipt_guard_plan_and_direct_markdown_scopes_are_explicit(tmp_path):
    observed = tmp_path/"service/.observe"
    observed.mkdir(parents=True)
    (observed/"otel-verify.md").write_text("Direct Markdown proof remains grader-owned")
    guard = DRIVER.check_evidence_receipt(ROOT,tmp_path,"instrument")
    assert guard["status"] == "failed" and "otel-direct-evidence-index.json" in guard["reason"]
    (observed/"otel-verify.json").write_text("malformed overlay")
    guard = DRIVER.check_evidence_receipt(ROOT,tmp_path,"audit")
    assert guard["status"] == "N_A" and "plan-only" in guard["reason"]


@pytest.mark.parametrize("collect",[False,True])
def test_receipt_failure_is_semantic_preserves_raw_rubric_and_isolates_feedback(workflow,collect):
    workflow.state["receipt_failures"] = {"instrument":"failed"}
    code, summary = workflow.run(collect=collect)
    assert code == 1
    assert workflow.calls == (["audit","instrument","verify"] if collect else ["audit","instrument"])
    stage = summary["stages"][1]
    assert stage["failure_kind"] == "semantic"
    assert stage["evidence_receipt_guard"]["status"] == "failed"
    assert stage["rubric"]["overall_pass"] is True
    assert len(stage["rubric"]["checks"]) == stage["rubric_contract"]["criterion_count"]
    assert all(c["pass"] for c in stage["rubric"]["checks"])
    assert stage["task_model"]["model"] == stage["rubric_model"]["model"] == "gpt-6.1-sol"
    assert bool(stage.get("diagnostic_continuation")) == collect
    assert summary["diagnostic_only"] == collect
    assert_archives(workflow)
    assert json.loads((workflow.output/"instrument/evidence-receipt-check.json").read_text())["status"] == "failed"


@pytest.mark.parametrize("claim",["trace_ids","observed_telemetry"])
def test_no_execution_receipt_exemption_cannot_hide_recorded_telemetry_claims(tmp_path,claim):
    files = receipt_flow(tmp_path,result="Not run")
    report = json.loads(files["report"].read_text())
    report["findings"][0]["scenarios"][0][claim] = ["1"*32] if claim == "trace_ids" else ["Observed span"]
    files["report"].write_text(json.dumps(report))
    guard = DRIVER.check_evidence_receipt(ROOT,tmp_path,"verify")
    assert guard["status"] == "failed",guard
    assert "receipt" in guard["reason"]


def test_receipt_failure_does_not_weaken_fatal_runtime_guard(workflow):
    workflow.state.update(receipt_failures={"instrument":"failed"},runtime=9)
    code, summary = workflow.run(collect=True)
    assert code == 1 and workflow.calls == ["audit","instrument"]
    stage = summary["stages"][1]
    assert stage["failure_kind"] == "fatal"
    assert not stage.get("diagnostic_continuation",False)


def direct_flow(workspace, *, result="Pass", role="instrument"):
    """Real direct report, explicit index and receipt; no audit/selection fabrication."""
    core = REPORT.MODULE
    service = workspace / "service"
    observed = service / ".observe"
    observed.mkdir(parents=True, exist_ok=True)
    files = {key: observed / name for key, name in {
        "manifest": "direct-controls.json", "ledger": "direct-observations.json",
        "report": "otel-direct-evidence-index.json", "receipt": "otel-evidence-receipt.json",
        "final": "otel-instrumentation.md" if role == "instrument" else "otel-verify.md",
        "raw": "direct-raw.json"}.items()}
    files["final"].write_text("# Direct report\nScenario results are declared in the adjacent evidence index.\n")
    files["raw"].write_text('{"received_records":1}\n')
    manifest = {"schema_version": 1, "kind": "otel-evidence-controls", "controls": [{
        "id": "control.direct", "scenario_id": "direct.operation", "run_id": "owned.run",
        "operation_ids": ["own.operation"], "phase": "received", "expected": {"received_records": 1}}]}
    rows = [] if result == "Partial" else [{"id": "own.receipt", "run_id": "owned.run",
        "operation_id": "own.operation", "phase": "received", "trace_context": {"state": "none"},
        "facts": {"received_records": 0 if result == "Fail" else 1},
        "artifacts": [{"path": ".observe/direct-raw.json", "sha256": hashlib.sha256(files["raw"].read_bytes()).hexdigest()}]}]
    status = {"Pass": "working", "Partial": "not_proven", "Fail": "failed",
              "Not run": "not_proven", "Blocked": "blocked"}[result]
    scenario = {"id": "direct.operation", "execution": "executed", "status": status,
                "control_ids": ["control.direct"]}
    if result in {"Not run", "Blocked"}:
        scenario.update(execution="not_run" if result == "Not run" else "prerequisite_only",
                        control_ids=[], reason="Owned runtime prerequisite unavailable")
    index = {"schema_version": 1, "kind": "otel-direct-evidence-index", "result": result,
             "reports": [{"path": files["final"].name, "sha256": hashlib.sha256(files["final"].read_bytes()).hexdigest()}],
             "scenarios": [scenario]}
    for key, value in [("report", index), ("manifest", manifest), ("ledger", rows)]:
        files[key].write_text(json.dumps(value))
    if result in {"Pass", "Partial", "Fail"}:
        receipt = core.create_evidence_receipt(files["manifest"], files["ledger"], files["report"], service, files["receipt"])
        files["receipt"].write_text(json.dumps(receipt))
    return files


@pytest.mark.parametrize("role", ["instrument", "verify"])
@pytest.mark.parametrize("result", ["Pass", "Partial", "Fail"])
def test_real_direct_guard_accepts_only_bound_role_report_and_rebaked_scenarios(tmp_path, role, result):
    files = direct_flow(tmp_path, role=role, result=result)
    before = {path: path.read_bytes() for path in files.values()}
    guard = DRIVER.check_evidence_receipt(ROOT, tmp_path, role)
    assert guard["status"] == "valid", guard
    assert guard["direct_result"] == result
    assert guard["validation"]["direct_index"]["executed_scenarios"] == 1
    assert {path: path.read_bytes() for path in files.values()} == before
    assert not (tmp_path / "service/.observe/otel-audit.json").exists()
    assert not (tmp_path / "service/.observe/otel-selection.json").exists()
    assert not (tmp_path / "service/.observe/otel-verify.json").exists()


@pytest.mark.parametrize("fault", ["no_index", "no_receipt", "final_report_drift", "raw_drift",
                                  "uncovered_claim", "control_tamper", "status_tamper", "wrong_role", "detached_index", "role_symlink"])
def test_real_direct_guard_rejects_uncovered_tampered_and_detached_claims(tmp_path, fault):
    files = direct_flow(tmp_path, role="verify" if fault == "wrong_role" else "instrument")
    if fault == "no_index":
        files["report"].unlink()
    elif fault == "no_receipt":
        files["receipt"].unlink()
    elif fault == "final_report_drift":
        files["final"].write_text("Different final report claims")
    elif fault == "raw_drift":
        files["raw"].write_text("Different raw receipts")
    elif fault == "wrong_role":
        pass
    elif fault == "role_symlink":
        other = files["final"].with_name("unrelated-final.md")
        files["final"].rename(other)
        files["final"].symlink_to(other)
        index = json.loads(files["report"].read_text())
        index["reports"][0]["path"] = other.name
        files["report"].write_text(json.dumps(index))
        receipt = REPORT.MODULE.create_evidence_receipt(files["manifest"], files["ledger"], files["report"],
                                                      tmp_path / "service", files["receipt"])
        files["receipt"].write_text(json.dumps(receipt))
    elif fault == "detached_index":
        other = files["report"].with_name("unrelated-index.json")
        other.write_bytes(files["report"].read_bytes())
        receipt = REPORT.MODULE.create_evidence_receipt(files["manifest"], files["ledger"], other,
                                                      tmp_path / "service", files["receipt"])
        files["receipt"].write_text(json.dumps(receipt))
    else:
        index = json.loads(files["report"].read_text())
        if fault == "uncovered_claim":
            index["scenarios"].append({"id": "executed.privacy", "execution": "executed", "status": "working",
                                       "control_ids": ["control.direct"]})
        elif fault == "control_tamper":
            manifest = json.loads(files["manifest"].read_text())
            manifest["controls"][0]["scenario_id"] = "unrelated.operation"
            files["manifest"].write_text(json.dumps(manifest))
        else:
            index["scenarios"][0]["status"] = "failed"; index["result"] = "Fail"
        files["report"].write_text(json.dumps(index))
        receipt = json.loads(files["receipt"].read_text())
        for key in ["report", "manifest"]:
            receipt[key]["sha256"] = hashlib.sha256(files[key].read_bytes()).hexdigest()
        files["receipt"].write_text(json.dumps(receipt))
    before = {path: path.read_bytes() for path in (tmp_path / "service").rglob("*") if path.is_file()}
    guard = DRIVER.check_evidence_receipt(ROOT, tmp_path, "instrument")
    assert guard["status"] == "failed", guard
    assert {path: path.read_bytes() for path in (tmp_path / "service").rglob("*") if path.is_file()} == before
    if fault == "uncovered_claim":
        assert "executed.privacy" in guard["reason"]
    if fault == "wrong_role":
        assert "otel-instrumentation.md" in guard["reason"]
    if fault == "detached_index":
        assert "final direct-report index" in guard["reason"]


@pytest.mark.parametrize("result", ["Not run", "Blocked"])
def test_real_direct_no_execution_is_na_only_after_index_and_report_validation(tmp_path, result):
    files = direct_flow(tmp_path, result=result)
    guard = DRIVER.check_evidence_receipt(ROOT, tmp_path, "instrument")
    assert guard["status"] == "N_A", guard
    assert guard["direct_result"] == result
    assert not files["receipt"].exists()
    for fault in ["empty", "false_working", "false_result", "executed_without_receipt"]:
        index = json.loads(files["report"].read_text())
        if fault == "empty":
            index["scenarios"] = []
        elif fault == "false_working":
            index["scenarios"][0]["status"] = "working"
        elif fault == "false_result":
            index["result"] = "Pass"
        else:
            index["scenarios"][0].update(execution="executed", status="working", control_ids=["control.direct"])
        original = files["report"].read_bytes()
        files["report"].write_text(json.dumps(index))
        guard = DRIVER.check_evidence_receipt(ROOT, tmp_path, "instrument")
        assert guard["status"] == "failed", guard
        files["report"].write_bytes(original)


def test_direct_no_execution_exemption_does_not_authorize_failed_runtime(workflow):
    workflow.state.update(real_receipt_guard=True, direct_report_result="Not run", runtime=9)
    code, summary = workflow.run(collect=True)
    assert code == 1 and workflow.calls == ["audit", "instrument"]
    stage = summary["stages"][1]
    assert stage["evidence_receipt_guard"]["status"] == "N_A"
    assert stage["evidence_receipt_guard"]["direct_result"] == "Not run"
    assert stage["independent_runtime_exit_code"] == 9
    assert stage["rubric"]["overall_pass"] is True
    assert stage["failure_kind"] == "fatal"
