import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

import run_logging_contract as runner


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
            "argv": ["--start-command-json", '["make","dev"]', "--operator-identity-profiles"],
            "cwd": str(service),
        }]
    else:
        assert calls == []
        assert "Host logging workflow check not configured" in result.stdout


def junit(directory, tag="", name="one"):
    Path(directory).mkdir(parents=True, exist_ok=True)
    child = f"<{tag}/>" if tag else ""
    (Path(directory) / "TEST-fixture.xml").write_text(
        f'<testsuite tests="1"><testcase classname="Fixture" name="{name}">{child}</testcase></testsuite>'
    )


def java_report(command):
    return Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("-Dlogging.contract.reportsDirectory=")))


@pytest.mark.parametrize("tag, passed, failed, errors, skipped", [
    ("", 1, 0, 0, 0),
    ("failure", 0, 1, 0, 0),
    ("error", 0, 0, 1, 0),
    ("skipped", 0, 0, 0, 1),
])
def test_junit_counts_actual_successes(tmp_path, tag, passed, failed, errors, skipped):
    junit(tmp_path, tag)
    result = runner.parse_results("java", "", tmp_path)
    assert result == {"executed_tests": 1, "passed_tests": passed, "failed_tests": failed, "error_tests": errors, "skipped_tests": skipped}


def test_missing_fresh_junit_is_not_a_pass(tmp_path):
    junit(tmp_path / "old")
    with pytest.raises(ValueError, match="No fresh"):
        runner.parse_results("java", "Tests are skipped.", tmp_path / "fresh")


def test_duplicate_junit_receipts_are_rejected(tmp_path):
    junit(tmp_path)
    (tmp_path / "copy.xml").write_bytes((tmp_path / "TEST-fixture.xml").read_bytes())
    with pytest.raises(ValueError, match="Duplicate"):
        runner.parse_results("java", "", tmp_path)


def test_go_package_and_subtest_passes_do_not_inflate_top_level_count(tmp_path):
    events = [
        {"Action": action, "Test": name}
        for name in ("TestOne", "TestOne/subcase")
        for action in ("run", "pass")
    ] + [{"Action": "pass", "Package": "fixture"}]
    result = runner.parse_results("go", "\n".join(json.dumps(row) for row in events), tmp_path)
    assert result == {"executed_tests": 1, "passed_tests": 1, "failed_tests": 0, "skipped_tests": 0}


@pytest.mark.parametrize("action, key", [("skip", "skipped_tests"), ("fail", "failed_tests")])
def test_go_subtest_failure_or_skip_remains_visible(tmp_path, action, key):
    result = runner.parse_results("go", json.dumps({"Action": action, "Test": "TestOne/subcase"}), tmp_path)
    assert result[key] == 1


def test_node_requires_all_outcome_counts(tmp_path):
    with pytest.raises(ValueError, match="Missing Node TAP"):
        runner.parse_results("node", "# pass 1\n", tmp_path)


def test_zero_exit_with_skipped_node_test_is_visible(tmp_path):
    output = "# tests 1\n# pass 0\n# fail 0\n# cancelled 0\n# skipped 1\n# todo 0\n"
    result = runner.parse_results("node", output, tmp_path)
    assert result["executed_tests"] == result["skipped_tests"] == 1
    assert result["passed_tests"] == 0


def test_command_timeout_retains_output_and_returns_bounded_failure(tmp_path):
    started = time.monotonic()
    result = runner.run_command(
        [sys.executable, "-u", "-c", "import time; print('started', flush=True); time.sleep(60)"],
        tmp_path, dict(os.environ), 0.15,
    )
    assert result.exit_code == 124
    assert result.timed_out
    assert "started" in result.output
    assert time.monotonic() - started < 3


def test_missing_executable_is_a_recordable_failure(tmp_path):
    result = runner.run_command([str(tmp_path / "missing-tool")], tmp_path, dict(os.environ), 1)
    assert result.exit_code == 127
    assert not result.timed_out
    assert "Cannot start" in result.output


def test_selected_interpreter_keeps_venv_symlink_path(tmp_path):
    selected = tmp_path / "venv-python"
    selected.symlink_to(sys.executable)
    assert runner.executable(str(selected)) == str(selected)
    assert runner.executable(str(selected)) != str(selected.resolve())


def test_reusing_output_directory_cannot_reuse_an_old_java_receipt(tmp_path, monkeypatch):
    monkeypatch.setitem(runner.EXPECTED_TEST_COUNTS, "java", 1)
    skip = False
    directories = []

    def execute(command, cwd, env, timeout):
        if "test-compile" in command:
            return runner.CommandResult(0, "compiled")
        directory = java_report(command)
        directories.append(directory)
        if not skip:
            junit(directory)
        return runner.CommandResult(0, "Tests are skipped." if skip else "Tests run: 1")

    monkeypatch.setattr(runner, "run_command", execute)
    args = ["--output", str(tmp_path), "--languages", "java"]
    assert runner.main(args) == 0
    skip = True
    monkeypatch.setenv("MAVEN_ARGS", "-DskipTests")
    assert runner.main(args) == 1
    rows = json.loads((tmp_path / "results.json").read_text())
    assert len(directories) == len(set(directories)) == 6
    assert len(rows) == 3
    assert all(not row["passed"] and "No fresh" in row["validation_error"] for row in rows)


@pytest.mark.parametrize("tag", ["skipped", "failure", "error"])
def test_zero_exit_cannot_mask_java_nonpassing_case(tmp_path, monkeypatch, tag):
    monkeypatch.setitem(runner.EXPECTED_TEST_COUNTS, "java", 1)

    def execute(command, cwd, env, timeout):
        if "test" in command:
            junit(java_report(command), tag)
        return runner.CommandResult(0, "build succeeded")

    monkeypatch.setattr(runner, "run_command", execute)
    assert runner.main(["--output", str(tmp_path), "--languages", "java", "--trials", "1"]) == 1
    row = json.loads((tmp_path / "results.json").read_text())[0]
    assert row["executed_tests"] == 1
    assert row["passed_tests"] == 0
    assert row["status"] == "fail"


def test_timeout_preserves_partial_matrix_and_continues_later_trials(tmp_path, monkeypatch):
    monkeypatch.setitem(runner.EXPECTED_TEST_COUNTS, "java", 1)
    calls = 0

    def execute(command, cwd, env, timeout):
        nonlocal calls
        if "test-compile" in command:
            return runner.CommandResult(0, "compiled")
        calls += 1
        persisted = json.loads((tmp_path / "results.json").read_text())
        assert persisted[-1]["status"] == "running"
        if calls == 2:
            assert persisted[0]["passed"]
            return runner.CommandResult(124, "partial output before timeout", timed_out=True)
        junit(java_report(command))
        return runner.CommandResult(0, "Tests run: 1")

    monkeypatch.setattr(runner, "run_command", execute)
    assert runner.main(["--output", str(tmp_path), "--languages", "java"]) == 1
    rows = json.loads((tmp_path / "results.json").read_text())
    assert [row["status"] for row in rows] == ["pass", "fail", "pass"]
    assert rows[1]["timed_out"]
    assert "partial output" in Path(rows[1]["log"]).read_text()


def test_failed_middle_language_preflight_does_not_stop_later_language(tmp_path, monkeypatch):
    monkeypatch.setitem(runner.EXPECTED_TEST_COUNTS, "java", 1)
    monkeypatch.setitem(runner.EXPECTED_TEST_COUNTS, "node", 1)
    commands = []

    def execute(command, cwd, env, timeout):
        commands.append(command)
        if "test-compile" in command:
            return runner.CommandResult(127, "missing JDK")
        if "ci" in command:
            return runner.CommandResult(0, "installed")
        return runner.CommandResult(0, "# tests 1\n# pass 1\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n")

    monkeypatch.setattr(runner, "run_command", execute)
    assert runner.main(["--output", str(tmp_path), "--languages", "java", "node"]) == 1
    rows = json.loads((tmp_path / "results.json").read_text())
    assert [row["status"] for row in rows] == ["blocked"] * 3 + ["pass"] * 3
    assert all(Path(row["log"]).is_file() for row in rows)
    assert not any("test" in command and command[0] == "mvn" for command in commands)
    assert any("ci" in command for command in commands)


def test_interrupt_preserves_completed_and_cancelled_rows(tmp_path, monkeypatch):
    monkeypatch.setitem(runner.EXPECTED_TEST_COUNTS, "java", 1)
    calls = 0

    def execute(command, cwd, env, timeout):
        nonlocal calls
        if "test-compile" in command:
            return runner.CommandResult(0, "compiled")
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        junit(java_report(command))
        return runner.CommandResult(0, "Tests run: 1")

    monkeypatch.setattr(runner, "run_command", execute)
    assert runner.main(["--output", str(tmp_path), "--languages", "java"]) == 130
    rows = json.loads((tmp_path / "results.json").read_text())
    assert [row["status"] for row in rows] == ["pass", "cancelled"]


def test_trial_environment_excludes_otel_values_without_exposing_them(tmp_path, monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "synthetic-secret")
    monkeypatch.setitem(runner.EXPECTED_TEST_COUNTS, "java", 1)

    def execute(command, cwd, env, timeout):
        assert "OTEL_EXPORTER_OTLP_HEADERS" not in env
        if "test" in command:
            junit(java_report(command))
        return runner.CommandResult(0, "ready")

    monkeypatch.setattr(runner, "run_command", execute)
    assert runner.main(["--output", str(tmp_path), "--languages", "java", "--trials", "1"]) == 0
    metadata = (tmp_path / "run.json").read_text()
    assert "OTEL_EXPORTER_OTLP_HEADERS" in metadata
    assert "synthetic-secret" not in metadata


def test_changed_fixture_source_invalidates_otherwise_successful_trial(tmp_path, monkeypatch):
    monkeypatch.setitem(runner.EXPECTED_TEST_COUNTS, "java", 1)
    calls = 0

    def sources(fixture):
        nonlocal calls
        calls += 1
        return {"fixture.java": "before" if calls == 1 else "after"}

    def execute(command, cwd, env, timeout):
        if "test" in command:
            junit(java_report(command))
        return runner.CommandResult(0, "ready")

    monkeypatch.setattr(runner, "fixture_sources", sources)
    monkeypatch.setattr(runner, "run_command", execute)
    assert runner.main(["--output", str(tmp_path), "--languages", "java", "--trials", "1"]) == 1
    row = json.loads((tmp_path / "results.json").read_text())[0]
    assert row["passed_tests"] == 1
    assert not row["passed"]
    assert "source changed" in row["validation_error"]


def test_fixture_source_binding_includes_node_code_and_excludes_dependency_trees(tmp_path):
    source = tmp_path / "logging.test.cjs"
    source.write_text("first source")
    dependency = tmp_path / "node_modules" / "dependency.cjs"
    dependency.parent.mkdir()
    dependency.write_text("not fixture code")
    before = runner.fixture_sources(tmp_path)
    assert set(before) == {"logging.test.cjs"}
    source.write_text("changed source")
    assert runner.fixture_sources(tmp_path) != before


def test_changed_shared_receiver_source_invalidates_trial(tmp_path, monkeypatch):
    monkeypatch.setitem(runner.EXPECTED_TEST_COUNTS, "java", 1)
    snapshots = iter([{"receiver": "before"}, {"receiver": "after"}])
    monkeypatch.setattr(runner, "shared_sources", lambda root: next(snapshots))

    def execute(command, cwd, env, timeout):
        if "test" in command:
            junit(java_report(command))
        return runner.CommandResult(0, "ready")

    monkeypatch.setattr(runner, "run_command", execute)
    assert runner.main(["--output", str(tmp_path), "--languages", "java", "--trials", "1"]) == 1
    row = json.loads((tmp_path / "results.json").read_text())[0]
    assert not row["passed"]
    assert "Shared" in row["validation_error"]


def test_parse_and_both_source_failures_remain_visible_together(tmp_path, monkeypatch):
    monkeypatch.setitem(runner.EXPECTED_TEST_COUNTS, "java", 1)
    fixture = iter([{"fixture.java": "before"}, {"fixture.java": "after"}])
    shared = iter([{"receiver": "before"}, {"receiver": "after"}])
    monkeypatch.setattr(runner, "fixture_sources", lambda _: next(fixture))
    monkeypatch.setattr(runner, "shared_sources", lambda _: next(shared))

    def execute(command, cwd, env, timeout):
        if "test" in command:
            junit(java_report(command))
            (java_report(command) / "TEST-fixture.xml").write_text("<broken")
        return runner.CommandResult(0, "ready")

    monkeypatch.setattr(runner, "run_command", execute)
    assert runner.main(["--output", str(tmp_path), "--languages", "java", "--trials", "1"]) == 1
    row = json.loads((tmp_path / "results.json").read_text())[0]
    assert row["passed"] is False
    assert "unclosed token" in row["validation_error"]
    assert "Fixture source changed" in row["validation_error"]
    assert "Shared runner/receiver source changed" in row["validation_error"]


def test_receiver_setup_failure_has_structured_error_without_false_success(tmp_path, monkeypatch):
    def unavailable(output):
        raise OSError("loopback receiver unavailable")

    monkeypatch.setattr(runner, "LogsReceiver", unavailable)
    assert runner.main(["--output", str(tmp_path), "--languages", "java"]) == 1
    assert json.loads((tmp_path / "results.json").read_text()) == []
    assert "loopback receiver unavailable" in json.loads((tmp_path / "run.json").read_text())["runner_error"]


def test_receiver_cleanup_error_still_preserves_run_metadata(tmp_path, monkeypatch):
    monkeypatch.setitem(runner.EXPECTED_TEST_COUNTS, "java", 1)
    close = runner.LogsReceiver.close

    def failing_close(receiver):
        close(receiver)
        raise OSError("receiver cleanup failed")

    def execute(command, cwd, env, timeout):
        if "test" in command:
            junit(java_report(command))
        return runner.CommandResult(0, "ready")

    monkeypatch.setattr(runner.LogsReceiver, "close", failing_close)
    monkeypatch.setattr(runner, "run_command", execute)
    with pytest.raises(OSError, match="receiver cleanup failed"):
        runner.main(["--output", str(tmp_path), "--languages", "java", "--trials", "1"])
    assert len(json.loads((tmp_path / "results.json").read_text())) == 1
    assert json.loads((tmp_path / "run.json").read_text())["preflight"]["java"]["exit_code"] == 0
