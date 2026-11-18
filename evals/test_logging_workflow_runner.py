"""Mock external execution, exercise the candidate's real three-role orchestration."""
from __future__ import annotations

import argparse
import copy
import errno
import hashlib
import importlib.util
import json
import os
import re
import signal
import stat
import time
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
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
from pytest_codex_evals.backends import AgentResult, CodexBackend
from pytest_codex_evals.definitions import GradeCheckResult, GradeResult
from pytest_codex_evals.graders.rubric import run_rubric_dimensions


FIXTURE_CHECKS = {'go/chi-basic': ['go', 'test', './...'], 'java/springboot-basic': ['mvn', '-q', 'test'], 'python/flask-basic': ['uv', 'run', 'python', '-m', 'py_compile', 'app.py']}


@pytest.mark.skipif(os.name != "posix", reason="This receipt boundary test creates filesystem symlinks")
@pytest.mark.parametrize("name", ["evidence-receipt-check.tmp", "evidence-receipt-check.json"])
def test_host_receipt_does_not_follow_actor_output_links(tmp_path, name):
    workspace = tmp_path / "actor-workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("preserve outside actor\n")
    (workspace / name).symlink_to(outside)
    result = DRIVER.check_evidence_receipt(ROOT, workspace, "audit")
    assert result["status"] == "N_A"
    assert outside.read_text() == "preserve outside actor\n"
    receipt = workspace / "evidence-receipt-check.json"
    assert not receipt.is_symlink()
    assert json.loads(receipt.read_text()) == result
    assert not list(workspace.glob(".evidence-receipt-check.json.*.tmp"))


def test_host_save_keeps_prior_result_and_cleans_up_after_replace_failure(tmp_path, monkeypatch):
    path = tmp_path / "result.json"
    path.write_text('{"prior": true}\n')
    def fail_replace(self, target):
        raise OSError("replace unavailable")
    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="replace unavailable"):
        DRIVER.save(path, {"new": True})
    assert path.read_text() == '{"prior": true}\n'
    assert sorted(p.name for p in tmp_path.iterdir()) == ["result.json"]


@pytest.mark.skipif(os.name != "posix", reason="Owned dependency cleanup uses POSIX process groups")
@pytest.mark.parametrize("outcome", ["timeout", "interrupt", "success", "nonzero"])
def test_dependency_setup_stops_owned_children_and_retains_output(tmp_path, outcome):
    workspace, output, tools = (tmp_path / name for name in ("workspace", "output", "tools"))
    (workspace / "service").mkdir(parents=True)
    output.mkdir()
    tools.mkdir()
    ready, installer = tmp_path / "ready.json", tmp_path / "installer.pid"
    waiting = tmp_path / "waiting"
    child_code = (
        "import json,os,signal,sys,time\nfrom pathlib import Path\n"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
        "os.close(1);os.close(2)\n"
        "ready=Path(sys.argv[1]);temporary=ready.with_suffix('.tmp')\n"
        "temporary.write_text(json.dumps({'pid':os.getpid(),'group':os.getpgrp()}));temporary.replace(ready)\n"
        "while True: time.sleep(1)\n"
    )
    tool = tools / "uv"
    tool.write_text(
        "#!" + sys.executable + "\nimport os,subprocess,sys,time\nfrom pathlib import Path\n"
        + "os.write(1,b'installer output\\xff\\x00\\n')\n"
        + "subprocess.Popen([sys.executable,'-c'," + repr(child_code) + "," + repr(str(ready)) + "])\n"
        + "while not Path(" + repr(str(ready)) + ").exists(): time.sleep(.01)\n"
        + ("raise SystemExit(" + str(7 if outcome == "nonzero" else 0) + ")\n"
           if outcome in {"success", "nonzero"} else "while True: time.sleep(1)\n")
    )
    tool.chmod(0o700)
    harness = (
        "import json,signal,subprocess,sys,time\nfrom pathlib import Path\n"
        + "sys.path.insert(0," + repr(str(ROOT / "evals")) + ")\n"
        + "import run_logging_workflow as driver\n"
        + "signal.signal(signal.SIGTERM,driver.interrupt_owned_run)\n"
        + "real_popen=subprocess.Popen\n"
        + "def launch(*args,**kwargs):\n"
        + " process=real_popen(*args,**kwargs)\n"
        + " Path(" + repr(str(installer)) + ").write_text(str(process.pid))\n"
        + " deadline=time.monotonic()+5\n"
        + " while not Path(" + repr(str(ready)) + ").exists():\n"
        + "  if time.monotonic()>=deadline: raise RuntimeError('installer child did not become ready')\n"
        + "  time.sleep(.01)\n"
        + " real_wait=process.wait\n"
        + " def wait(timeout=None):\n"
        + "  if timeout==600: Path(" + repr(str(waiting)) + ").touch()\n"
        + "  return real_wait(timeout=timeout)\n"
        + " process.wait=wait\n"
        + " return process\n"
        + "subprocess.Popen=launch\n"
        + ("driver.DEPENDENCY_TIMEOUT_SECONDS=.2\n" if outcome == "timeout" else "")
        + "try:\n"
        + " driver.prepare_dependencies('python',Path(" + repr(str(workspace)) + "),Path(" + repr(str(output)) + "))\n"
        + " result='success'\n"
        + "except subprocess.TimeoutExpired: result='timeout'\n"
        + "except KeyboardInterrupt: result='interrupt'\n"
        + "except RuntimeError as error:\n"
        + " assert 'Baseline dependency preparation failed' in str(error)\n"
        + " result='nonzero'\n"
        + "print(json.dumps({'result':result}))\n"
    )
    environment = {**os.environ, "PATH": str(tools) + os.pathsep + os.environ.get("PATH", os.defpath),
                   "PYTHONDONTWRITEBYTECODE": "1"}
    process = subprocess.Popen([sys.executable, "-c", harness], env=environment,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               start_new_session=True)
    child = None
    try:
        deadline = time.monotonic() + 7
        while not ready.exists():
            assert process.poll() is None, process.communicate(timeout=1)
            assert time.monotonic() < deadline, "Dependency child did not become ready"
            time.sleep(.01)
        child = json.loads(ready.read_text())
        if outcome == "interrupt":
            while not waiting.exists():
                assert process.poll() is None, process.communicate(timeout=1)
                assert time.monotonic() < deadline, "Dependency wait did not start"
                time.sleep(.01)
            process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=8)
        assert process.returncode == 0, stderr
        assert json.loads(stdout) == {"result": outcome}
        assert (output / "baseline-dependencies.log").read_bytes() == b"installer output\xff\x00\n"
        deadline = time.monotonic() + 2
        while True:
            state = subprocess.run(["ps", "-o", "stat=", "-p", str(child["pid"])],
                                   capture_output=True, text=True, timeout=2)
            if state.returncode or state.stdout.strip().startswith("Z"):
                break
            assert time.monotonic() < deadline, "Owned dependency child still runs after setup ended"
            time.sleep(.01)
    finally:
        groups = {process.pid}
        if installer.exists():
            installer_pid = int(installer.read_text())
            groups.add(installer_pid)
            if child is None and ready.exists():
                child = json.loads(ready.read_text())
            if child is not None:
                assert child["group"] in groups
        for group in groups:
            try:
                os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=5)


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
    for name in ('go', 'mvn', 'uv'):
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


def test_stage_workspaces_preserve_application_inputs_and_exclude_eval_assets(tmp_path):
    from pytest_codex_evals.runner import prepare_side_workspace

    for role in ("audit", "instrument", "verify"):
        case = DRIVER.case_for(ROOT, "python", role, 1)
        workspace = tmp_path / role
        prepare_side_workspace(ROOT, case, "with_skill", workspace)
        assert (workspace / "service/README.md").read_bytes() == (case.fixture_dir / "README.md").read_bytes()
        assert not (workspace / "service/eval").exists()


@pytest.mark.parametrize("foreign_health", [False, True])
def test_receiver_readiness_binds_the_owned_launch(tmp_path, monkeypatch, foreign_health):
    binary = tmp_path / "receiver"
    binary.write_bytes(b"owned receiver binary")
    launches, stopped = [], []
    process = SimpleNamespace(pid=12345, poll=lambda: None)
    parent_home = os.environ.get("HOME")

    def launch(command, **kwargs):
        launches.append(kwargs["env"])
        assert command[0] == str(binary) and kwargs["start_new_session"]
        return process

    class Health:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            owner = "logging-workflow-eval" if foreign_health else launches[-1]["OBSTUDIO_OWNER"]
            return json.dumps({"owner": owner}).encode()

    monkeypatch.setattr(DRIVER.subprocess, "Popen", launch)
    monkeypatch.setattr(DRIVER.urllib.request, "urlopen", lambda *_args, **_kwargs: Health())
    monkeypatch.setattr(DRIVER, "stop_owned", lambda owned: stopped.append(owned))
    ports = {"rest": 1, "http": 2, "grpc": 3, "app": 4}
    for number in range(1 if foreign_health else 2):
        output = tmp_path / str(number)
        output.mkdir()
        if foreign_health:
            with pytest.raises(AssertionError, match="Receiver ownership mismatch"):
                DRIVER.start_receiver(binary, output, ports)
            assert stopped == [process] and not (output / "receiver.json").exists()
        else:
            assert DRIVER.start_receiver(binary, output, ports) is process
            assert json.loads((output / "receiver.json").read_text())["health"]["owner"] == launches[-1]["OBSTUDIO_OWNER"]
        home = output / "receiver-home"
        assert launches[-1]["HOME"] == str(home)
        assert home.stat().st_mode & 0o777 == 0o700
        assert not list(home.iterdir())
        assert os.environ.get("HOME") == parent_home
    if not foreign_health:
        assert not stopped
        assert launches[0]["OBSTUDIO_OWNER"] != launches[1]["OBSTUDIO_OWNER"]


@pytest.mark.skipif(not (ROOT / "build/obstudio").is_file(), reason="Build the native receiver with make build")
def test_receiver_does_not_restore_parent_connections(tmp_path, monkeypatch):
    parent_home = tmp_path / "parent-home"
    settings = parent_home / ".obstudio/connections.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"schemaVersion": "1", "logsEnabled": "true", "logsIndex": "parent-index-canary"}))
    before = {str(path.relative_to(parent_home)): path.read_bytes() for path in parent_home.rglob("*") if path.is_file()}
    monkeypatch.setenv("HOME", str(parent_home))
    output = tmp_path / "receiver"
    output.mkdir()
    ports = DRIVER.reserve_ports()
    process = DRIVER.start_receiver(ROOT / "build/obstudio", output, ports)
    try:
        with DRIVER.urllib.request.urlopen(f"http://127.0.0.1:{ports['rest']}/api/splunk/logs", timeout=2) as response:
            status = json.load(response)
        assert status["index"] != "parent-index-canary"
        assert not status["enabled"] and not status["tokenConfigured"]
    finally:
        DRIVER.stop_owned(process)
    assert os.environ["HOME"] == str(parent_home)
    assert {str(path.relative_to(parent_home)): path.read_bytes() for path in parent_home.rglob("*") if path.is_file()} == before


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


@pytest.mark.parametrize("language", sorted(DRIVER.SERVICES))
@pytest.mark.parametrize("role", ["audit", "instrument", "verify"])
def test_every_logging_definition_uses_focused_judging_for_each_trial(tmp_path, language, role):
    calls = []

    def judge(**kwargs):
        calls.append(kwargs["prompt"])
        output = kwargs["output_dir"]
        path, trace, stderr = [output / name for name in ("grade.json", "trace.jsonl", "stderr.txt")]
        ids = re.findall(r"^(rubric-\d+):", kwargs["prompt"], re.M)
        path.write_text(json.dumps({"checks": [
            {"id": id, "result": "pass", "notes": "Mock verdict.",
             "evidence": "Mock artifact:1; wiring only."} for id in ids]}))
        trace.write_text('')
        stderr.write_text('')
        return AgentResult(0, trace, path, stderr)

    backend = SimpleNamespace(name="codex", run_judge=judge, parse_trace=CodexBackend().parse_trace)
    workspace = tmp_path / "evidence"
    workspace.mkdir()
    for trial in range(1, 4):
        case = DRIVER.case_for(ROOT, language, role, trial)
        assert case.strict_rubric_output is True
        assert case.task == f"$otel-{role} ./service" and case.eval_inputs == []
        assert len(case.rubric) == 63 and len(case.rubric_dimensions) == 8
        assert case.judge_prompt is None and len(case.judge_inputs) == 7
        assigned = [id for group in case.rubric_dimensions for id in group.criteria]
        assert len(assigned) == len(set(assigned)) == 63
        assert set(assigned) == {f"rubric-{i}" for i in range(1, 64)}
        path = run_rubric_dimensions(case=case, workspace_dir=workspace,
            output_dir=tmp_path / f"trial-{trial}", model="gpt-6.1-sol", backend=backend,
            deadline=time.monotonic() + 30)
        result = json.loads(path.read_text())
        assert result["acceptance"] == "pass" and result["counts"]["pass"] == 63
        for prompt in calls[-8:]:
            assert f"Actor task: {case.task}\n" in prompt
            for instruction in case.judge_inputs:
                assert instruction in prompt
            assert "later checks are not_applicable, receive no runtime credit" in prompt
            assert "This exception never applies to a paired instrumented workflow." in prompt
            assert "Verification with satisfied prerequisites must execute its required read-only checks." in prompt
        assert len(calls) == trial * 8


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
    monkeypatch.setattr(driver, "tempfile", SimpleNamespace(
        mkdtemp=lambda **kwargs: str(workspace), mkstemp=driver.tempfile.mkstemp,
    ))
    monkeypatch.setattr(driver, "reserve_ports", lambda: dict(rest=1, http=2, grpc=3, app=4))
    monkeypatch.setattr(driver, "prepare_dependencies", lambda *args: None)
    monkeypatch.setattr(driver, "start_receiver", lambda *args: object())
    monkeypatch.setattr(driver, "stop_owned", lambda *args, **kwargs: state["cleanup"])
    monkeypatch.setattr(driver, "runtime_capture_context", lambda *args: [])

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
        (target / "service/README.md").write_text("Original operator privacy policy.\n")
        skill = target / ".agents/skills/otel-audit"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("name: otel-audit\n")
    monkeypatch.setattr(driver, "prepare_side_workspace", prepare)

    class Backend:
        name = "codex"

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
                assert not any(os.path.lexists(exec_dir / name) for name in driver.ACTOR_ARTIFACTS)
            observed = exec_dir / "service/.observe"
            observed.mkdir(exist_ok=True)
            if role == "audit":
                (observed / "otel-audit.json").write_text(json.dumps(REPORT.sample_report()))
            elif role == "instrument":
                (exec_dir / "service/main.go").write_text("instrumented source\n")
            (observed / f"actor-{role}.md").write_text(f"ordinary {role} handoff")
            if state.get("policy_edit_role") == role:
                (exec_dir / "service/README.md").write_text("Weakened operator privacy policy.\n")
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
                               kwargs["output_dir"] / "trace.jsonl", path, kwargs["output_dir"] / "stderr.txt")

        def parse_trace(self, trace_path):
            return CodexBackend().parse_trace(trace_path)
    monkeypatch.setattr(driver, "CodexBackend", Backend)

    def metadata(*args):
        if state["fault"] == "metadata" or (state["fault"] == "judge_metadata" and args[-1] != workspace):
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
            if state.get("runtime_diagnostic"):
                kwargs["stderr"].write("Harmless SDK warning\n")
                kwargs["stdout"].write('{"status":"passed"}\n')
        def wait(self, timeout):
            assert timeout == 720
            return self.returncode
        def poll(self):
            return self.returncode
    real_popen = subprocess.Popen
    def launch(command, *args, **kwargs):
        if len(command) > 1 and command[1] == str(ROOT / "evals/logging_workflow_check.py"):
            return Runtime(command, *args, **kwargs)
        return real_popen(command, *args, **kwargs)
    monkeypatch.setattr(driver.subprocess, "Popen", launch)

    def rubric(**kwargs):
        role = calls[-1]
        assert (workspace / "evidence-receipt-check.json").is_file(), "Independent guard must precede grading"
        if state["fault"] == "judge_exception":
            raise RuntimeError("mock judge failed")
        ids = re.findall(r"^(rubric-\d+):", kwargs["prompt"], re.M)
        checks = [{"id": id, "result": "fail" if role in state["semantic"] and id == "rubric-2" else "pass",
                   "evidence": f"private-grade-{role}-{id}", "notes": "mock"} for id in ids]
        value = {"checks": checks}
        if state["fault"] == "malformed_rubric":
            checks.pop()
        if state["fault"] == "string_bool":
            checks[0]["result"] = True
        if state.get("vacuous"):
            for check in checks:
                check["result"] = "not_applicable"
        directory = kwargs["output_dir"]
        path = directory / "grade.json"
        path.write_text("not json" if state["fault"] == "invalid_json" else json.dumps(value))
        (directory / "trace.jsonl").write_text("")
        (directory / "stderr.txt").write_text("")
        expected_bytes[role] = {name: (workspace / name).read_bytes() for name in driver.GRADER_FEEDBACK_ARTIFACTS}
        if state["fault"] == "grader_audit":
            path = workspace / "service/.observe/otel-audit.json"
            path.write_text(path.read_text() + "\n")
        if state["fault"] == "grader_bundle":
            (workspace / ".agents/skills/otel-audit/SKILL.md").write_text("grader changed skill")
        if state["fault"] == "grader_source":
            (workspace / "service/main.go").write_text("grader changed source")
        return path

    args = argparse.Namespace(repo=ROOT, output=output, language="go", trial=1, studio_binary=tmp_path / "unused",
                              codex_home=tmp_path / "home", agent_timeout=1, judge_timeout=30)
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



@pytest.mark.skipif(sys.platform not in {"linux", "darwin"}, reason="Native trial process inventory requires Linux or macOS")
@pytest.mark.parametrize("outcome", ["returned", "raised", "interrupted"])
@pytest.mark.parametrize("ignore_term", [False, True])
@pytest.mark.parametrize("cwd_outside", [False, True], ids=["cwd-in", "cwd-out"])
def test_runner_cleans_actor_probe_children_and_preserves_outside_work(workflow, tmp_path, monkeypatch, outcome, ignore_term, cwd_outside):
    backend = workflow.driver.CodexBackend
    original = backend.run_agent
    ready = tmp_path / "probe-ready"
    log_path = workflow.workspace / "service/.observe/evidence/probe.log"
    spawned = []
    controls = []

    def leak(self, **kwargs):
        result = original(self, **kwargs)
        code = (
            "import os,signal,sys,time\nfrom pathlib import Path\n"
            + ("signal.signal(signal.SIGTERM,signal.SIG_IGN)\n" if ignore_term else "")
            + "print('retained probe output',flush=True)\n"
            + "Path(sys.argv[1]).write_text(str(os.getpid()))\n"
            + "while True: time.sleep(1)\n"
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if not controls:
            control_ready = tmp_path / "reader-ready"
            control = subprocess.Popen(
                [sys.executable, "-c", "import sys,time; from pathlib import Path; "
                 "held=open(sys.argv[1]); Path(sys.argv[2]).touch(); time.sleep(60)",
                 str(workflow.workspace / "service/main.go"), str(control_ready)], cwd=tmp_path,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            )
            controls.append(control)
            deadline = time.monotonic() + 5
            while not control_ready.exists():
                assert control.poll() is None and time.monotonic() < deadline
                time.sleep(.01)
        with log_path.open("w") as log:
            child = subprocess.Popen([sys.executable, "-c", code, str(ready)],
                                     cwd=tmp_path if cwd_outside else workflow.workspace / "service",
                                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        spawned.append(child)
        deadline = time.monotonic() + 5
        while not ready.exists():
            assert child.poll() is None and time.monotonic() < deadline
            time.sleep(.01)
        if outcome == "raised":
            raise TimeoutError("actor timed out after spawning its probe")
        if outcome == "interrupted":
            raise KeyboardInterrupt
        return result

    monkeypatch.setattr(backend, "run_agent", leak)
    try:
        code, summary = workflow.run(collect=True)
        assert code == 1 and summary["status"] == "failed"
        assert workflow.calls == ["audit"]
        assert summary["stages"][0]["failure_kind"] == "fatal"
        assert not (workflow.output / "audit.rubric").exists()
        child = spawned[0]
        child.wait(timeout=2)
        assert summary["workspace_cleanup"]["complete"]
        assert controls[0].poll() is None
        assert log_path.read_text() == "retained probe output\n"
        assert (workflow.output / "audit/service/.observe/evidence/probe.log").read_text() == log_path.read_text()
        if outcome == "returned":
            stage = summary["stages"][0]
            assert stage["leaked_actor_processes"][0]["pid"] == child.pid
            witness = stage["leaked_actor_processes"][0]
            assert str(child.pid) in summary["error"]
            assert stage["probe_cleanup"]["complete"]
            assert stage["probe_cleanup"]["forced"] is ignore_term
        else:
            assert summary["workspace_cleanup"]["observed"][0]["pid"] == child.pid
            witness = summary["workspace_cleanup"]["observed"][0]
            assert summary["workspace_cleanup"]["forced"] is ignore_term
        assert witness["reason"] == ("fd" if cwd_outside else "cwd")
        assert witness["path"] == str(log_path if cwd_outside else workflow.workspace / "service")
    finally:
        for process in [*spawned, *controls]:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)



@pytest.fixture
def linux_process_table(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    proc.mkdir()
    workspace = tmp_path / "private-workspace"
    denied_cwds, denied_stats = set(), set()
    real_path = DRIVER.Path
    real_resolve, real_read_text = type(tmp_path).resolve, type(tmp_path).read_text

    def add(pid, start, cwd):
        process = proc / str(pid)
        process.mkdir(exist_ok=True)
        # starttime is field 22, after a comm value containing spaces/parentheses.
        fields = ["S", "1", str(pid), str(pid), *(["0"] * 15), str(start)]
        (process / "stat").write_text(f"{pid} (worker (name)) " + " ".join(fields))
        (process / "cwd").symlink_to(cwd)
        (process / "fd").mkdir()
        (process / "fdinfo").mkdir()
        return process

    def resolve(path, *args, **kwargs):
        if path in denied_cwds:
            raise PermissionError(13, "protected process cwd", str(path))
        return real_resolve(path, *args, **kwargs)

    def read_text(path, *args, **kwargs):
        if path in denied_stats:
            raise PermissionError(13, "protected process identity", str(path))
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(DRIVER.sys, "platform", "linux")
    monkeypatch.setattr(DRIVER, "Path", lambda value: proc if value == "/proc" else real_path(value))
    monkeypatch.setattr(type(tmp_path), "resolve", resolve)
    monkeypatch.setattr(type(tmp_path), "read_text", read_text)
    monkeypatch.setattr(DRIVER.os, "getpgid", lambda pid: pid)
    return SimpleNamespace(proc=proc, workspace=workspace, outside=tmp_path, add=add,
                           denied_cwds=denied_cwds, denied_stats=denied_stats,
                           host=os.getpid() + 1000)


def test_protected_preexisting_process_does_not_prevent_owned_cleanup(linux_process_table, monkeypatch):
    table = linux_process_table
    protected = table.add(table.host, 11, table.outside)
    readable = table.add(table.host + 1, 22, table.outside)
    table.denied_cwds.add(protected / "cwd")
    assert not table.workspace.exists()
    baseline = DRIVER.capture_process_baseline()
    table.workspace.mkdir()
    child = table.add(table.host + 2, 33, table.workspace)
    log = table.workspace / "probe.log"
    log.touch()
    (readable / "fd/1").symlink_to(log)
    (readable / "fdinfo/1").write_text("flags:\t0000002\n")
    signals = []

    def stop(pid, sig):
        signals.append((pid, sig))
        if pid == int(child.name):
            prefix, _, tail = (child / "stat").read_text().rpartition(")")
            (child / "stat").write_text(prefix + ") Z " + " ".join(tail.split()[1:]))
            table.denied_cwds.add(child / "cwd")
        else:
            shutil.rmtree(table.proc / str(pid))

    monkeypatch.setattr(DRIVER.os, "kill", stop)
    result = DRIVER.cleanup_workspace_processes(table.workspace, preexisting_processes=baseline)
    assert result["complete"] and not result["forced"]
    assert {(r["pid"], r["reason"]) for r in result["observed"]} == {
        (int(readable.name), "fd"), (int(child.name), "cwd")}
    assert set(signals) == {(int(readable.name), signal.SIGTERM), (int(child.name), signal.SIGTERM)}
    assert protected.is_dir() and child.is_dir()


@pytest.mark.parametrize("identity", ["new", "reused", "unknown"])
def test_protected_process_without_exact_baseline_fails_closed(linux_process_table, monkeypatch, identity):
    table = linux_process_table
    process = table.add(table.host, 11, table.outside)
    assert not table.workspace.exists()
    baseline = DRIVER.capture_process_baseline()
    table.workspace.mkdir()
    if identity == "new":
        process = table.add(table.host + 1, 22, table.outside)
    elif identity == "reused":
        (process / "stat").write_text(f"{table.host} (replacement) " + " ".join(["S", *(["0"] * 18), "44"]))
    else:
        table.denied_stats.add(process / "stat")
    table.denied_cwds.add(process / "cwd")
    signals = []
    monkeypatch.setattr(DRIVER.os, "kill", lambda *args: signals.append(args))
    with pytest.raises(RuntimeError, match="Cannot establish ownership of protected process"):
        DRIVER.cleanup_workspace_processes(table.workspace, preexisting_processes=baseline)
    assert not signals and process.is_dir()


@pytest.mark.skipif(sys.platform not in {"linux", "darwin"}, reason="Native trial process inventory requires Linux or macOS")
@pytest.mark.parametrize("cwd_outside", [False, True, "removed"])
def test_probe_cleanup_reserves_escalation_budget_for_multiple_children(tmp_path, monkeypatch, cwd_outside):
    baseline = DRIVER.capture_process_baseline()
    workspace = tmp_path / "work space\nprivate\\n"
    workspace.mkdir()
    children = []
    scan = DRIVER.workspace_processes
    def slow_scan(target, *, timeout=5, preexisting_processes=None):
        delay = .2
        if timeout <= delay:
            raise subprocess.TimeoutExpired("process inventory", timeout)
        time.sleep(delay)
        return scan(target, timeout=timeout - delay, preexisting_processes=preexisting_processes)
    try:
        for index in range(2):
            ready = workspace / f"ready-{index}"
            code = ("import signal,sys,time\nfrom pathlib import Path\n"
                    "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
                    "Path(sys.argv[1]).touch()\nwhile True:time.sleep(1)\n")
            cwd = tmp_path if cwd_outside else workspace
            if cwd_outside == "removed":
                cwd = tmp_path / f"removed-cwd-{index}"
                cwd.mkdir()
            with (workspace / f"native log\n{index}.log").open("w+") as log:
                child = subprocess.Popen([sys.executable, "-c", code, str(ready)],
                                         cwd=cwd,
                                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            children.append(child)
            deadline = time.monotonic() + 5
            while not ready.exists():
                assert child.poll() is None and time.monotonic() < deadline
                time.sleep(.01)
            if cwd_outside == "removed":
                cwd.rmdir()
        monkeypatch.setattr(DRIVER, "workspace_processes", slow_scan)
        started = time.monotonic()
        result = DRIVER.cleanup_workspace_processes(workspace, preexisting_processes=baseline)
        assert time.monotonic() - started < 6
        assert result["complete"] and result["forced"] and result["remaining"] == [], result
        assert {row["pid"] for row in result["observed"]} == {child.pid for child in children}
        for child in children:
            child.wait(timeout=2)
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)


@pytest.mark.skipif(sys.platform not in {"linux", "darwin"}, reason="Native trial process inventory requires Linux or macOS")
def test_writer_cleanup_fails_closed_after_inventory_timeout(tmp_path, monkeypatch):
    baseline = DRIVER.capture_process_baseline()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ready = tmp_path / "ready"
    code = ("import signal,sys,time; from pathlib import Path; "
            "signal.signal(signal.SIGTERM,signal.SIG_IGN); Path(sys.argv[1]).touch(); time.sleep(60)")
    with (workspace / "native.log").open("w") as log:
        child = subprocess.Popen([sys.executable, "-c", code, str(ready)], cwd=tmp_path,
                                 stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while not ready.exists():
            assert child.poll() is None and time.monotonic() < deadline
            time.sleep(.01)
        inventory = DRIVER.workspace_processes(workspace, preexisting_processes=baseline)
        assert set(inventory) == {child.pid} and inventory[child.pid]["reason"] == "fd"
        scans, signals = [], []
        kill = os.kill

        def scan(target, *, timeout=5, preexisting_processes=None):
            scans.append(timeout)
            if len(scans) == 1:
                return inventory
            raise TimeoutError("inventory deadline")

        def signal_child(pid, sig):
            signals.append((pid, sig))
            kill(pid, sig)

        monkeypatch.setattr(DRIVER, "workspace_processes", scan)
        monkeypatch.setattr(DRIVER.os, "kill", signal_child)
        started = time.monotonic()
        result = DRIVER.cleanup_workspace_processes(workspace, timeout=1, preexisting_processes=baseline)
        assert time.monotonic() - started < 2
        assert not result["complete"] and not result["forced"] and result["inventory_errors"]
        assert signals == [(child.pid, signal.SIGTERM)] and child.poll() is None
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
        child.wait(timeout=5)


@pytest.mark.skipif(sys.platform not in {"linux", "darwin"}, reason="Native trial process inventory requires Linux or macOS")
@pytest.mark.parametrize("different_tmpdir", [False, True])
@pytest.mark.parametrize("wrong_pid", [False, True])
def test_runner_report_server_identity_and_teardown(workflow, tmp_path, monkeypatch, different_tmpdir, wrong_pid):
    backend = workflow.driver.CodexBackend
    original = backend.run_agent
    cli = load(ROOT / "skills/references/scripts/observe_report.py", "workflow_report_server_cli")
    server = {}
    prepare = workflow.driver.prepare_side_workspace
    def prepare_with_helper(repo, case, side, workspace):
        prepare(repo, case, side, workspace)
        shutil.copytree(ROOT / "skills/references/scripts", workspace / ".agents/skills/references/scripts",
                        ignore=workflow.driver.skill_workspace_ignore)
    monkeypatch.setattr(workflow.driver, "prepare_side_workspace", prepare_with_helper)

    def finalize(self, **kwargs):
        result = original(self, **kwargs)
        directory = workflow.workspace / "service/.observe"
        if workflow.calls == ["audit"]:
            environment = dict(os.environ)
            if different_tmpdir:
                actor_temp = tmp_path / "actor-temp"
                actor_temp.mkdir()
                environment.update(TMPDIR=str(actor_temp), TMP=str(actor_temp), TEMP=str(actor_temp))
                with monkeypatch.context() as patch:
                    patch.setattr(cli.tempfile, "gettempdir", lambda: str(actor_temp))
                    server["state_path"] = cli.report_server_state_path(directory)
            else:
                server["state_path"] = cli.report_server_state_path(directory)
            helper = workflow.workspace / ".agents/skills/references/scripts/observe_report.py"
            subprocess.run([sys.executable, "-I", str(helper), "finalize-audit", str(directory / "otel-audit.json"),
                            "--html", str(directory / "otel.html")], cwd=workflow.workspace / "service", env=environment,
                           check=True, capture_output=True, text=True, timeout=10)
            state = cli.load_report_server_state(server["state_path"], directory)
            assert state is not None
            server.update(state)
            if wrong_pid:
                state["pid"] = os.getpid()
                server["state_path"].write_text(json.dumps(state))
        else:
            assert cli.load_report_server_state(server["state_path"], directory)["pid"] == server["pid"]
        return result

    monkeypatch.setattr(backend, "run_agent", finalize)
    try:
        code, summary = workflow.run()
        directory = workflow.workspace / "service/.observe"
        assert cli.load_report_server_state(server["state_path"], directory) is None
        assert summary["workspace_cleanup"]["complete"]
        if wrong_pid:
            assert code == 1 and workflow.calls == ["audit"]
            assert summary["stages"][0]["leaked_actor_processes"][0]["pid"] == server["pid"]
        else:
            assert code == 0 and len(summary["stages"]) == 3
            assert not any(stage.get("leaked_actor_processes") for stage in summary["stages"])
            assert server["pid"] in {row["pid"] for row in summary["workspace_cleanup"]["observed"]}
    finally:
        if server.get("pid"):
            try:
                os.kill(server["pid"], signal.SIGKILL)
            except ProcessLookupError:
                pass



def test_host_grade_writes_do_not_follow_actor_output_links(workflow, tmp_path, monkeypatch):
    outside = tmp_path / "outside-grade.txt"
    outside.write_text("preserve outside actor\n")
    grade_side = workflow.driver.grade_side
    def grade_with_actor_link(**kwargs):
        (kwargs["run_dir"] / "grade.json").symlink_to(outside)
        return grade_side(**kwargs)
    monkeypatch.setattr(workflow.driver, "grade_side", grade_with_actor_link)
    code, summary = workflow.run()
    assert code == 0
    assert len(summary["stages"]) == 3
    assert outside.read_text() == "preserve outside actor\n"


@pytest.mark.skipif(os.name != "posix", reason="The logging runner requires POSIX")
@pytest.mark.parametrize("name", DRIVER.ACTOR_ARTIFACTS)
@pytest.mark.parametrize("kind", ["symlink", "hardlink", "broken_symlink"])
def test_actor_output_links_stop_before_next_stage_without_outside_io(workflow, tmp_path, monkeypatch, name, kind):
    outside = tmp_path / "outside-actor.txt"
    canary = b"preserve outside actor canary\n"
    if kind != "broken_symlink":
        outside.write_bytes(canary)
    backend = workflow.driver.CodexBackend
    run_agent = backend.run_agent

    def plant_link(self, **kwargs):
        result = run_agent(self, **kwargs)
        if workflow.calls == ["audit"]:
            path = workflow.workspace / name
            path.unlink()
            if kind == "hardlink":
                path.hardlink_to(outside)
            else:
                path.symlink_to(outside)
        return result

    monkeypatch.setattr(backend, "run_agent", plant_link)
    code, summary = workflow.run()
    assert code == 1 and workflow.calls == ["audit"]
    assert summary["stages"][0]["failure_kind"] == "fatal"
    assert "single-link regular file" in summary["error"] and name in summary["error"]
    if kind == "broken_symlink":
        assert not outside.exists()
    else:
        assert outside.read_bytes() == canary
    assert not (workflow.output / "audit" / name).exists()
    for other in set(workflow.driver.ACTOR_ARTIFACTS) - {name}:
        assert (workflow.output / "audit" / other).read_bytes() == b"actor audit"
    assert (workflow.output / "audit/service/.observe/otel-audit.json").is_file()


def test_actor_file_replaced_during_open_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "trace.jsonl"
    path.write_text("original actor output")
    real_open = os.open

    def replace_before_open(target, flags):
        path.unlink()
        path.write_text("replacement actor output")
        return real_open(target, flags)

    monkeypatch.setattr(DRIVER.os, "open", replace_before_open)
    with pytest.raises(RuntimeError, match="changed while reading"):
        DRIVER.read_actor_file(path)


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="Requires no-follow file opens")
@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_actor_file_link_replaced_during_open_is_refused(tmp_path, monkeypatch, kind):
    path = tmp_path / "stderr.txt"
    path.write_text("original actor output")
    outside = tmp_path / "outside.txt"
    outside.write_text("private canary")
    real_open = os.open

    def link_before_open(target, flags):
        path.unlink()
        if kind == "fifo":
            # Bound this regression test too if the nonblocking flag is lost.
            assert flags & os.O_NONBLOCK
            os.mkfifo(path)
        elif kind == "hardlink":
            path.hardlink_to(outside)
        else:
            path.symlink_to(outside)
        return real_open(target, flags)

    monkeypatch.setattr(DRIVER.os, "open", link_before_open)
    expected = "Cannot safely read" if kind == "symlink" else "single-link regular file"
    with pytest.raises(RuntimeError, match=expected):
        DRIVER.read_actor_file(path)
    assert outside.read_text() == "private canary"


@pytest.mark.parametrize("remove", [False, True])
def test_changed_actor_diagnostics_are_not_archived_or_reused(workflow, monkeypatch, remove):
    grade_side = workflow.driver.grade_side

    def change_diagnostics(**kwargs):
        value = grade_side(**kwargs)
        path = workflow.workspace / "stderr.txt"
        if remove:
            path.unlink()
        else:
            path.write_text("replaced after actor completed")
        return value

    monkeypatch.setattr(workflow.driver, "grade_side", change_diagnostics)
    code, summary = workflow.run()
    assert code == 1 and workflow.calls == ["audit"]
    assert "Actor artifact changed before archive: stderr.txt" in summary["error"]
    assert not (workflow.output / "audit/stderr.txt").exists()
    assert (workflow.output / "audit/trace.jsonl").read_text() == "actor audit"
    assert (workflow.output / "audit/last_message.md").read_text() == "actor audit"


@pytest.mark.parametrize("outcome", ["unavailable", "unsupported", "error", "metadata-error"])
def test_archive_file_falls_back_to_copy2(tmp_path, monkeypatch, outcome):
    source, destination = tmp_path / "source", tmp_path / "copy"
    source.write_bytes(b"retained bytes\x00\xff")
    source.chmod(0o751)
    os.utime(source, ns=(1_600_000_000_123_456_789,) * 2)
    monkeypatch.setattr(DRIVER, "sys", SimpleNamespace(platform="darwin"))
    native_calls, copies = [], []
    def clone(src, dst, flags):
        native_calls.append((src, dst, flags))
        if outcome == "error":
            raise OSError("native clone unavailable")
        if outcome == "metadata-error":
            shutil.copyfile(src, dst)
            return 0
        return -1
    monkeypatch.setattr(DRIVER, "_CLONEFILE", None if outcome == "unavailable" else clone)
    copy2, copystat = shutil.copy2, shutil.copystat
    def copy(src, dst):
        copies.append((src, dst))
        return copy2(src, dst)
    monkeypatch.setattr(DRIVER.shutil, "copy2", copy)
    if outcome == "metadata-error":
        calls = []
        def metadata(src, dst, **kwargs):
            calls.append((src, dst))
            if len(calls) == 1:
                raise OSError("native metadata unavailable")
            return copystat(src, dst, **kwargs)
        monkeypatch.setattr(DRIVER.shutil, "copystat", metadata)
    assert DRIVER.copy_archive_file(str(source), str(destination)) == str(destination)
    assert copies == [(str(source), str(destination))]
    assert native_calls == ([] if outcome == "unavailable" else [(os.fsencode(source), os.fsencode(destination), 0x0002)])
    assert destination.read_bytes() == source.read_bytes()
    assert destination.stat().st_mode == source.stat().st_mode
    assert destination.stat().st_mtime_ns == source.stat().st_mtime_ns
    assert destination.stat().st_ino != source.stat().st_ino


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_archive_file_keeps_other_platforms_on_copy2(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(DRIVER, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(DRIVER, "_CLONEFILE", lambda *args: pytest.fail("macOS API used on another platform"))
    source, destination = tmp_path / "source", tmp_path / "copy"
    source.write_bytes(b"ordinary copy")
    source.chmod(0o640)
    assert DRIVER.copy_archive_file(str(source), str(destination)) == str(destination)
    assert destination.read_bytes() == source.read_bytes()
    assert destination.stat().st_mode == source.stat().st_mode


def test_archive_file_preserves_copy2_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(DRIVER, "_CLONEFILE", None)
    error = PermissionError("ordinary copy denied")
    def denied(src, dst):
        raise error
    monkeypatch.setattr(DRIVER.shutil, "copy2", denied)
    with pytest.raises(PermissionError) as failure:
        DRIVER.copy_archive_file(str(tmp_path / "source"), str(tmp_path / "copy"))
    assert failure.value is error


@pytest.mark.skipif(sys.platform != "darwin", reason="Native file flags require macOS")
@pytest.mark.parametrize("flag", [stat.UF_IMMUTABLE, stat.UF_APPEND])
def test_archive_file_keeps_flagged_files_on_copy2(tmp_path, monkeypatch, flag):
    source, ordinary, destination = (tmp_path / name for name in ("source", "ordinary", "copy"))
    source.write_bytes(b"flagged archive bytes")
    source.chmod(0o640)
    os.utime(source, ns=(1_600_000_000_123_456_789,) * 2)
    monkeypatch.setattr(DRIVER, "_CLONEFILE", lambda *args: pytest.fail("Flagged file was cloned"))
    try:
        os.chflags(source, flag)
        shutil.copy2(source, ordinary)
        assert DRIVER.copy_archive_file(str(source), str(destination)) == str(destination)
        assert destination.read_bytes() == ordinary.read_bytes() == source.read_bytes()
        for name in ("st_mode", "st_mtime_ns", "st_flags", "st_uid", "st_gid"):
            assert getattr(destination.stat(), name) == getattr(ordinary.stat(), name) == getattr(source.stat(), name)
    finally:
        for path in (source, ordinary, destination):
            if path.exists():
                os.chflags(path, 0)


def require_archive_clone_volume(tmp_path):
    import ctypes
    assert DRIVER._CLONEFILE is not None, "macOS clonefile binding unavailable"
    source, destination = tmp_path / "clone-probe-source", tmp_path / "clone-probe-copy"
    source.write_bytes(b"native volume probe")
    if DRIVER._CLONEFILE(os.fsencode(source), os.fsencode(destination), 0x0002) == 0:
        return
    code = ctypes.get_errno()
    if code == errno.ENOTSUP:
        pytest.skip("Test volume does not support clonefile (ENOTSUP)")
    raise OSError(code, os.strerror(code))


@pytest.mark.parametrize("code", [errno.ENOTSUP, errno.EACCES, errno.EXDEV, errno.ENOSPC])
def test_archive_clone_volume_probe_skips_only_unsupported_filesystems(tmp_path, monkeypatch, code):
    import ctypes
    monkeypatch.setattr(DRIVER, "_CLONEFILE", lambda *args: -1)
    monkeypatch.setattr(ctypes, "get_errno", lambda: code)
    if code == errno.ENOTSUP:
        with pytest.raises(pytest.skip.Exception, match="ENOTSUP"):
            require_archive_clone_volume(tmp_path)
    else:
        with pytest.raises(OSError) as error:
            require_archive_clone_volume(tmp_path)
        assert error.value.errno == code


@pytest.mark.skipif(sys.platform != "darwin", reason="Native clonefile isolation requires macOS")
def test_archive_stage_clones_two_independent_snapshots_without_changing_retention(tmp_path, monkeypatch, record_property):
    require_archive_clone_volume(tmp_path)
    workspace = tmp_path / "actor"
    service = workspace / "service"
    service.mkdir(parents=True)
    for name, data in {
        "src/main.txt": b"application source\n",
        ".observe/otel-audit.json": b'{"audit": true}\n',
        ".observe/evidence/nested/capture.bin": b"retained evidence\x00\xff",
        ".maven-runtime-repository/org/example/demo.jar": os.urandom(2 * 1024 * 1024),
        **{name + "/omit.txt": b"excluded" for name in (".venv", "node_modules", "target", "__pycache__")},
        "nested/target/omit.txt": b"excluded",
        ".observe/evidence/old.db": b"excluded by existing policy",
    }.items():
        path = service / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o751 if name.startswith("src/") else 0o640)
        os.utime(path, ns=(1_600_000_000_123_456_789,) * 2)
    (service / "source-link").symlink_to("src/main.txt")
    for name in (*DRIVER.ACTOR_ARTIFACTS, *DRIVER.GRADER_FEEDBACK_ARTIFACTS):
        (workspace / name).write_bytes(name.encode() + b"\x00\xff")
    def snapshot(root):
        result = {}
        for path in sorted(root.rglob("*")):
            metadata = path.lstat()
            result[str(path.relative_to(root))] = (
                metadata.st_mode, metadata.st_mtime_ns, metadata.st_uid, metadata.st_gid,
                os.readlink(path) if path.is_symlink() else hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
            )
        return result
    baseline = tmp_path / "ordinary-copy"
    shutil.copytree(service, baseline, symlinks=True,
                    ignore=shutil.ignore_patterns(".venv", "node_modules", "target", "__pycache__", "*.db"))
    native, calls = DRIVER._CLONEFILE, []
    def clone(src, dst, flags):
        result = native(src, dst, flags)
        calls.append(result)
        return result
    monkeypatch.setattr(DRIVER, "_CLONEFILE", clone)
    monkeypatch.setattr(DRIVER.shutil, "copy2", lambda *args: pytest.fail("Native clone fell back during kernel proof"))
    first, second = tmp_path / "first", tmp_path / "second"
    DRIVER.archive_stage(workspace, first)
    assert snapshot(first / "service") == snapshot(baseline)
    first_inventory = snapshot(first / "service")
    relative = ".maven-runtime-repository/org/example/demo.jar"
    source, copy_one = service / relative, first / "service" / relative
    original = source.read_bytes()
    def overwrite(path, prefix):
        with path.open("r+b") as stream:
            stream.write(prefix)
    overwrite(source, b"source changed")
    changed = source.read_bytes()
    assert copy_one.read_bytes() == original
    DRIVER.archive_stage(workspace, second)
    copy_two = second / "service" / relative
    expected_second = dict(first_inventory)
    metadata = source.stat()
    expected_second[relative] = (*first_inventory[relative][:-1], hashlib.sha256(changed).hexdigest())
    expected_second[relative] = (metadata.st_mode, metadata.st_mtime_ns, *expected_second[relative][2:])
    assert snapshot(second / "service") == expected_second
    assert copy_two.read_bytes() == changed
    for root in (first, second):
        assert (root / "service/.observe/evidence/nested/capture.bin").read_bytes() == b"retained evidence\x00\xff"
        assert (root / "service/source-link").is_symlink()
        assert not any(path.name in {".venv", "node_modules", "target", "__pycache__"} or path.suffix == ".db" for path in (root / "service").rglob("*"))
        for name in (*DRIVER.ACTOR_ARTIFACTS, *DRIVER.GRADER_FEEDBACK_ARTIFACTS):
            assert (root / name).read_bytes() == (workspace / name).read_bytes()
    overwrite(copy_one, b"archive one changed")
    assert source.read_bytes() == changed and copy_two.read_bytes() == changed
    overwrite(copy_two, b"archive two changed")
    assert source.read_bytes() == changed
    assert copy_one.read_bytes().startswith(b"archive one changed")
    overwrite(source, b"source changed again")
    assert copy_one.read_bytes().startswith(b"archive one changed")
    assert copy_two.read_bytes().startswith(b"archive two changed")
    assert len({path.stat().st_ino for path in (source, copy_one, copy_two)}) == 3
    assert calls and set(calls) == {0}
    record_property("successful_native_clones", len(calls))
    record_property("snapshots", 2)
    record_property("first_inventory_sha256", hashlib.sha256(json.dumps(first_inventory, sort_keys=True).encode()).hexdigest())
    record_property("bidirectional_modification_isolation", True)


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


@pytest.mark.parametrize("override", [None, 17])
def test_judge_budget_reaches_the_controller_from_config_or_cli(workflow, monkeypatch, tmp_path, override):
    driver = workflow.driver
    config_path = ROOT / "evals/codex-evals.logging.toml"
    configured = tomllib.loads(config_path.read_text())["agent"]["judge_timeout"]
    expected = configured if override is None else override
    arguments = ["run_logging_workflow.py", "--repo", str(ROOT), "--output", str(workflow.output),
                 "--language", "go", "--trial", "1", "--studio-binary", str(tmp_path / "unused"),
                 "--codex-home", str(tmp_path / "home"), "--agent-timeout", "1"]
    if override is not None:
        arguments.extend(["--judge-timeout", str(override)])
    monkeypatch.setattr(driver.sys, "argv", arguments)
    monkeypatch.setattr(driver, "time", SimpleNamespace(monotonic=lambda: 1000.0))
    deadlines = []

    def grade(**kwargs):
        deadlines.append(kwargs["deadline"])
        output = kwargs["output_dir"]
        output.mkdir()
        result = output / "rubric_result.json"
        result.write_text(json.dumps({"status": "complete", "acceptance": "pass"}))
        return result

    monkeypatch.setattr(driver, "run_rubric_dimensions", grade)
    code = driver.main()
    summary = json.loads((workflow.output / "summary.json").read_text())
    assert code == 0 and workflow.calls == ["audit", "instrument", "verify"]
    assert deadlines == [1000.0 + expected] * 3
    assert summary["configuration"] == {
        "path": str(config_path), "sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
    }
    for stage in summary["stages"]:
        assert stage["judge_timeout_seconds"] == expected
        assert stage["judge_timeout_source"] == ("config" if override is None else "cli")


def test_runtime_diagnostics_stay_outside_the_json_result_channel(workflow):
    workflow.state["runtime_diagnostic"] = True
    code, summary = workflow.run()
    assert code == 0 and summary["status"] == "passed"
    for role in ("instrument", "verify"):
        assert (workflow.output / f"{role}-independent-runtime.log").read_text() == '{"status":"passed"}\n'
        assert (workflow.output / f"{role}-independent-runtime.stderr.log").read_text() == "Harmless SDK warning\n"
    assert_archives(workflow)


@pytest.mark.parametrize("role", ["audit", "verify"])
@pytest.mark.parametrize("collect", [False, True])
def test_read_only_roles_cannot_change_operator_policy(workflow, role, collect):
    workflow.state["policy_edit_role"] = role
    code, summary = workflow.run(collect=collect)
    assert code == 1 and summary["status"] == "failed"
    assert workflow.calls == (["audit"] if role == "audit" else ["audit", "instrument", "verify"])
    stage = summary["stages"][-1]
    assert stage["role"] == role and stage["failure_kind"] == "fatal"
    assert stage["source_before"] != stage["source_after"]
    assert not stage.get("diagnostic_continuation", False)
    assert not summary["diagnostic_only"]


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


@pytest.mark.parametrize("name", DRIVER.ACTOR_ARTIFACTS)
def test_unverified_prior_response_is_preserved_and_blocks_next_actor(workflow, monkeypatch, name):
    archive = workflow.driver.archive_stage
    def corrupt_response(workspace, destination, **kwargs):
        archive(workspace, destination, **kwargs)
        (destination / name).write_text("not the actor response")
    monkeypatch.setattr(workflow.driver, "archive_stage", corrupt_response)
    code, summary = workflow.run()
    assert code == 1 and workflow.calls == ["audit"]
    assert "not safely archived" in summary["error"]
    assert (workflow.workspace / name).read_text() == "actor audit"


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


@pytest.mark.parametrize("collect", [False, True])
@pytest.mark.parametrize("fault", ["malformed_rubric", "invalid_json", "string_bool", "judge_exit", "judge_exception", "judge_metadata", "vacuous"])
def test_incomplete_or_vacuous_grading_stops_later_actors(workflow, collect, fault):
    if fault == "vacuous":
        workflow.state["vacuous"] = True
    else:
        workflow.state["fault"] = fault
    code, summary = workflow.run(collect=collect)
    assert code == 1 and workflow.calls == ["audit"]
    assert summary["stages"][0]["failure_kind"] == "grading"
    assert not summary["diagnostic_only"]
    result = json.loads((workflow.output / "audit.rubric/rubric_result.json").read_text())
    assert result["acceptance"] == ("vacuous" if fault == "vacuous" else "incomplete")
    assert result["overall_pass"] is None


@pytest.mark.parametrize("fault", [None, "model", "effort", "turn_cwd", "meta_cwd", "no_turns", "two_threads"])
def test_model_metadata_binds_actual_judge_directory_and_every_turn(tmp_path, fault):
    home, cwd = tmp_path / "home", tmp_path / "judge"
    cwd.mkdir()
    session = home / "sessions/session-thread.jsonl"
    session.parent.mkdir(parents=True)
    trace = tmp_path / "trace.jsonl"
    trace.write_text(json.dumps({"type": "thread.started", "thread_id": "thread"}) + "\n")
    if fault == "two_threads":
        trace.write_text(trace.read_text() + json.dumps({"type": "thread.started", "thread_id": "other"}) + "\n")
    context = {"cwd": str(cwd), "model": "gpt-6.1-sol", "effort": "high"}
    records = [{"type": "session_meta", "payload": {
        "id": "thread", "cwd": str(tmp_path if fault == "meta_cwd" else cwd), "timestamp": "test"}}]
    if fault != "no_turns":
        records.append({"type": "turn_context", "payload": dict(context)})
        if fault in {"model", "effort", "turn_cwd"}:
            context[{"turn_cwd": "cwd"}.get(fault, fault)] = "different"
        records.append({"type": "turn_context", "payload": context})
    session.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    if fault:
        with pytest.raises(AssertionError):
            DRIVER.bind_model_metadata(trace, home, cwd)
    else:
        metadata = DRIVER.bind_model_metadata(trace, home, cwd)
        assert metadata["turns"] == 2
        assert metadata["cwd"] == str(cwd.resolve())


@pytest.mark.parametrize("returncode", [0, 9])
def test_judge_adapter_binds_success_before_cwd_removal_and_preserves_failed_result(tmp_path, monkeypatch, returncode):
    cwd, output = tmp_path / "judge", tmp_path / "output"
    cwd.mkdir()
    result = AgentResult(returncode, output / "trace", output / "answer", output / "stderr")
    underlying = SimpleNamespace(name="codex", run_judge=lambda **kwargs: result)
    calls = []

    def metadata(trace, home, directory):
        assert directory.is_dir() and directory == cwd
        calls.append((trace, home, directory))
        return {"thread_id": "bound"}

    monkeypatch.setattr(DRIVER, "bind_model_metadata", metadata)
    adapter = DRIVER.BoundJudgeBackend(underlying, tmp_path / "home")
    assert adapter.run_judge(exec_dir=cwd, output_dir=output) is result
    assert len(calls) == (1 if returncode == 0 else 0)
    assert adapter.models == ({"output": {"thread_id": "bound"}} if returncode == 0 else {})


@pytest.mark.parametrize("fault", [None, "unreferenced", "duplicate", "profile", "symlink", "parent_symlink",
                                  "outside", "checker", "source", "cwd", "status"])
def test_runtime_context_requires_current_paths_returned_by_owned_checker(tmp_path, fault):
    workspace = tmp_path / "actor"
    service = workspace / "service"
    root = service / ".observe/logging-workflow-proof"
    root.mkdir(parents=True)
    (service / "app.py").write_text("print('application')\n")
    checker = ROOT / "evals/logging_workflow_check.py"
    sources = DRIVER.source_hashes(service)
    calls, values = [], []
    for profile in ["default", "resource-only", "explicit-override", "resource-whitespace"]:
        directory = root / profile
        directory.mkdir()
        path = directory / "result.json"
        value = {"status": "passed", "cwd": str(service), "source_before": sources, "source_after": sources,
                 "proof_directory": str(directory), "verifier_sha256": hashlib.sha256(checker.read_bytes()).hexdigest(),
                 "scope": "Bounded unit capture; no live application proof"}
        if profile != "default":
            value["identity_profile"] = profile
        values.append(value)
        path.write_text(json.dumps(value))
        calls.append({"status": "passed", "proof": str(path)})
    first = Path(calls[0]["proof"])
    value = values[0]
    if fault == "unreferenced":
        calls = []  # Valid-looking actor files alone supply no call provenance.
    elif fault == "duplicate":
        calls[1] = dict(calls[0])
    elif fault == "profile":
        value["identity_profile"] = "resource-only"
    elif fault == "symlink":
        other = first.with_name("actual.json")
        first.rename(other)
        first.symlink_to(other)
    elif fault == "parent_symlink":
        other = first.parent.with_name("actual-directory")
        first.parent.rename(other)
        first.parent.symlink_to(other, target_is_directory=True)
    elif fault == "outside":
        other = tmp_path / "outside.json"
        other.write_text(first.read_text())
        calls[0]["proof"] = str(other)
    elif fault == "checker":
        value["verifier_sha256"] = "0" * 64
    elif fault == "source":
        value["source_before"] = {}
    elif fault == "cwd":
        value["cwd"] = str(tmp_path)
    elif fault == "status":
        value["status"] = "failed"
    if fault not in {"symlink", "parent_symlink"}:
        first.write_text(json.dumps(value))
    log = tmp_path / "runtime.log"
    log.write_text("\n".join(json.dumps(call) for call in calls))
    if fault:
        with pytest.raises(ValueError):
            DRIVER.runtime_capture_context(log, workspace, checker)
    else:
        context = DRIVER.runtime_capture_context(log, workspace, checker)
        assert len(context) == 4
        assert all(row["sha256"] == hashlib.sha256(Path(row["proof"]).read_bytes()).hexdigest() for row in context)
        assert all("source_before" not in row for row in context)


@pytest.mark.parametrize("fault,runtime", [("audit_binding", 0), (None, 9)])
def test_fatal_later_stage_stops_even_after_diagnostic_continuation(workflow, fault, runtime):
    workflow.state.update(fault=fault, runtime=runtime, semantic={"audit", "instrument"})
    code, summary = workflow.run(collect=True)
    assert code == 1 and workflow.calls == ["audit", "instrument"]
    assert summary["stages"][1]["failure_kind"] == "fatal"


@pytest.mark.parametrize("failure", ["archive_exception", "archive_mismatch", "receipt_archive_mismatch"])
def test_archive_failure_stops_before_next_actor_and_preserves_feedback(workflow, monkeypatch, failure):
    original = workflow.driver.archive_stage
    def archive(workspace, destination, **kwargs):
        if failure == "archive_exception":
            raise OSError("mock storage failure")
        original(workspace, destination, **kwargs)
        name = "evidence-receipt-check.json" if failure == "receipt_archive_mismatch" else "grade.json"
        (destination / name).write_text("corrupt archive")
    monkeypatch.setattr(workflow.driver, "archive_stage", archive)
    code, summary = workflow.run(collect=True)
    assert code == 1 and workflow.calls == ["audit"]
    if failure == "archive_exception":
        assert workflow.expected == {}  # No judge is started before the actor archive succeeds.
        assert all((workflow.workspace / name).is_file() for name in workflow.driver.GRADER_FEEDBACK_ARTIFACTS)
    else:
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
def test_receipt_failure_is_gate_preserves_raw_rubric_and_isolates_feedback(workflow,collect):
    workflow.state["receipt_failures"] = {"instrument":"failed"}
    code, summary = workflow.run(collect=collect)
    assert code == 1
    assert workflow.calls == (["audit","instrument","verify"] if collect else ["audit","instrument"])
    stage = summary["stages"][1]
    assert stage["failure_kind"] == "gate"
    assert stage["semantic_passed"] is True and stage["evidence_gate_passed"] is False
    assert stage["evidence_receipt_guard"]["status"] == "failed"
    assert stage["rubric"]["overall_pass"] is True
    assert len(stage["rubric"]["checks"]) == stage["rubric_contract"]["criterion_count"]
    assert all(c["result"] == "pass" for c in stage["rubric"]["checks"])
    assert stage["task_model"]["model"] == "gpt-6.1-sol"
    assert len(stage["rubric_models"]) == len(stage["rubric"]["dimensions"]) == 8
    assert all(model["model"] == "gpt-6.1-sol" and model["reasoning_effort"] == "high"
               for model in stage["rubric_models"].values())
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


@pytest.mark.parametrize("collect", [False, True])
def test_mixed_semantic_and_gate_failure_keeps_both_results_and_diagnostic_scope(workflow, collect):
    workflow.state.update(semantic={"instrument"}, receipt_failures={"instrument": "failed"})
    code, summary = workflow.run(collect=collect)
    assert code == 1 and summary["status"] == "failed"
    assert workflow.calls == (["audit", "instrument", "verify"] if collect else ["audit", "instrument"])
    stage = summary["stages"][1]
    assert stage["failure_kind"] == "gate"
    assert stage["semantic_passed"] is False and stage["evidence_gate_passed"] is False
    assert stage["rubric"]["overall_pass"] is False
    assert stage["evidence_receipt_guard"]["status"] == "failed"
    assert bool(stage.get("diagnostic_continuation")) is collect
    assert summary["diagnostic_only"] is collect
    assert_archives(workflow)
