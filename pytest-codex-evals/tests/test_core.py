from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from pytest_codex_evals.ab import side_prompt
from pytest_codex_evals.config import load_settings
from pytest_codex_evals.definitions import (
    CaseResult,
    EndpointExpectation,
    GradeCheckResult,
    GradeResult,
    PromptVariant,
    RubricEvalCase,
    RubricEvalDefinition,
    RuntimeCheck,
    RuntimeEvalCase,
    RuntimeExpectations,
    SanityCheck,
    SanityEvalCase,
    SideResult,
    ValidationResult,
)
from pytest_codex_evals.graders.rubric import rubric_prompt
from pytest_codex_evals.backends import (
    AgentResult,
    BACKEND_SCRATCH_DIRECTORY,
    _codex_subprocess_env,
    _merge_stream_observations,
    atomic_text_write,
    cleanup_anchored_temporary_output,
    create_anchored_temporary_output,
    create_backend_temporary_output,
    descriptor_operations_supported,
    ensure_anchored_directory,
    path_directory_identity,
    read_regular_text,
    run_streamed_command,
)
from pytest_codex_evals.graders.runtime import (
    base_url_from_port_output,
    grade_runtime,
    resolve_compose_file,
    runtime_env,
    service_url,
)
from pytest_codex_evals.graders.sanity import grade_sanity
from pytest_codex_evals.graders.shared import (
    check_companion_skill_source_isolation,
    check_selected_skill_source_isolation,
)
from pytest_codex_evals.cli import main as cli_main
from pytest_codex_evals.eval_contracts import (
    case_contract_payload,
    case_contract_sha256,
    case_from_definition,
    case_task_sha256,
    load_eval_definition,
)
from pytest_codex_evals.report import (
    build_validation_benchmark,
    normalize_rubric_score,
    report_metadata,
    render_reports_for_run_root,
    write_capture_manifest,
    write_report_outputs,
    write_session_results,
    verify_companion_skills,
)
from pytest_codex_evals.runner import (
    build_run_provenance,
    parse_trace_snapshot,
    prepare_side_workspace,
    run_case,
    tree_sha256,
)
from pytest_codex_evals.trace import TraceSummary, parse_trace


@pytest.fixture(autouse=True)
def isolated_execution_quarantine(tmp_path: Path, monkeypatch) -> Path:
    quarantine = tmp_path / "execution-quarantine"
    quarantine.mkdir(mode=0o700)
    monkeypatch.setenv("CODEX_EVAL_QUARANTINE_ROOT", str(quarantine))
    return quarantine


def test_side_prompt_generates_loaded_and_not_loaded_variants():
    case = sanity_case(task="Scan the service.")

    prompt = side_prompt(case, "with_skill")
    assert prompt.startswith("Use the $sample-skill skill.")
    assert ".agents/skills/sample-skill/SKILL.md" in prompt
    assert "alternate skill installations" in prompt
    assert prompt.endswith("Scan the service.")
    assert side_prompt(case, "baseline") == "Scan the service."


def test_side_prompt_makes_staged_instrument_companion_authoritative():
    case = sanity_case(
        skill="otel-instrument",
        task="Instrument the service.",
    )

    prompt = side_prompt(case, "with_skill")

    assert ".agents/skills/otel-verify/SKILL.md" in prompt
    assert "load it exactly once" in prompt
    assert "do not search CODEX_HOME" in prompt
    assert side_prompt(case, "baseline") == "Instrument the service."


def test_side_prompt_makes_staged_configure_support_tree_authoritative():
    case = sanity_case(
        skill="splunk-configure",
        task="Generate detectors.",
    )

    prompt = side_prompt(case, "with_skill")

    assert ".agents/skills/splunk-dashboard/SKILL.md" in prompt
    assert "Use companion scripts only" in prompt
    assert "alternate skill installations" in prompt
    assert "load it exactly once" not in prompt


def test_prompt_eval_inputs_require_safe_fixture_relative_paths():
    prompt = PromptVariant(
        id="direct",
        task="Run.",
        eval_inputs=["eval/inputs/otel-audit.json"],
    )

    assert prompt.eval_inputs == ["eval/inputs/otel-audit.json"]
    for unsafe in (
        "/tmp/otel-audit.json",
        "../otel-audit.json",
        "eval/inputs/../otel-audit.json",
        "eval/inputs/./otel-audit.json",
        "otel-audit.json",
        "eval\\inputs\\otel-audit.json",
    ):
        with pytest.raises(ValueError, match="safe relative file paths"):
            PromptVariant(id="direct", task="Run.", eval_inputs=[unsafe])


def test_case_preserves_prompt_eval_inputs(tmp_path: Path):
    prompt = PromptVariant(
        id="direct",
        task="Run.",
        eval_inputs=["eval/inputs/otel-audit.json"],
    )
    definition = RubricEvalDefinition(
        id="go/sample/instrument",
        skill="otel-instrument",
        language="go",
        service="sample",
        prompts=[prompt],
        rubric=["Grade quality."],
        fixture_dir=tmp_path,
    )

    case = case_from_definition(
        definition,
        prompt,
        tmp_path / "eval" / "qual" / "instrument.json",
    )

    assert case.eval_inputs == ["eval/inputs/otel-audit.json"]


def test_eval_input_allowlist_is_bound_into_case_contract():
    default_case = sanity_case(task="Run.")
    explicitly_empty_case = sanity_case(task="Run.", eval_inputs=[])
    scoped_case = sanity_case(
        task="Run.",
        eval_inputs=["eval/inputs/otel-audit.json"],
    )

    assert case_task_sha256(default_case) == case_task_sha256(scoped_case)
    assert "eval_inputs" not in case_contract_payload(default_case)
    assert case_contract_payload(explicitly_empty_case)["eval_inputs"] == []
    assert case_contract_payload(scoped_case)["eval_inputs"] == [
        "eval/inputs/otel-audit.json"
    ]
    assert case_contract_sha256(default_case) != case_contract_sha256(
        explicitly_empty_case
    )
    assert case_contract_sha256(default_case) != case_contract_sha256(
        scoped_case
    )


def test_unscoped_eval_input_case_preserves_legacy_contract_shape_and_hash():
    case = sanity_case()

    assert case_contract_payload(case) == {
        "id": "sample/service/sample-skill/direct",
        "base_id": "sample/service/sample-skill",
        "prompt_id": "direct",
        "skill": "sample-skill",
        "language": "sample",
        "service": "service",
        "task": "Scan the service.",
        "checks": [],
    }
    assert case_contract_sha256(case) == (
        "9507b918db7b4fe665e16d7f121b1129a970d225f5e06a1d1fadaa2d466cfae6"
    )


def test_trace_snapshot_parses_authenticated_bytes_without_a_temp_path(
    monkeypatch,
):
    def fail_temp_path(*_args, **_kwargs):
        raise AssertionError("trace parsing must not create a temp pathname")

    from pytest_codex_evals import runner as runner_module

    monkeypatch.setattr(runner_module.tempfile, "mkstemp", fail_temp_path)
    trace = (
        json.dumps(
            {"type": "turn.completed", "usage": {"total_tokens": 7}}
        )
        + "\n"
    ).encode("utf-8")

    summary = parse_trace_snapshot(RecordingBackend(), trace)

    assert summary.usage.total_tokens == 7


def test_codex_subprocess_env_uses_sandbox_local_package_caches(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("UV_CACHE_DIR", "/outside/uv-cache")
    monkeypatch.setenv("PIP_CACHE_DIR", "/outside/pip-cache")

    env = _codex_subprocess_env(tmp_path)

    assert env["UV_CACHE_DIR"] == str(tmp_path / ".uv-cache")
    assert env["PIP_CACHE_DIR"] == str(tmp_path / ".pip-cache")


def test_trace_parser_extracts_commands_and_tokens(tmp_path: Path):
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        "\n".join(
            [
                json.dumps({"type": "item.completed", "item": {"type": "command_execution", "command": "npm install", "status": "completed"}}),
                json.dumps({"type": "turn.completed", "usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7}}),
            ]
        ),
        encoding="utf-8",
    )
    trace = parse_trace(trace_path)
    assert [command.command for command in trace.commands] == ["npm install"]
    assert trace.usage.total_tokens == 7


def test_command_runner_records_output_without_terminal_echo(tmp_path: Path, capfd):
    trace_path = tmp_path / "trace.jsonl"
    stderr_path = tmp_path / "stderr.txt"

    result = run_streamed_command(
        [
            sys.executable,
            "-c",
            "import sys; print('trace line'); print('error line', file=sys.stderr)",
        ],
        stdout_path=trace_path,
        stderr_path=stderr_path,
        timeout=10,
    )
    captured = capfd.readouterr()

    assert result.returncode == 0
    assert result.stdout == "trace line\n"
    assert result.stderr == "error line\n"
    assert trace_path.read_text(encoding="utf-8") == "trace line\n"
    assert stderr_path.read_text(encoding="utf-8") == "error line\n"
    assert captured.out == ""
    assert captured.err == ""


def test_command_runner_persists_partial_output_before_timeout(
    tmp_path: Path, capfd
):
    import pytest as _pytest

    trace_path = tmp_path / "trace.jsonl"
    stderr_path = tmp_path / "stderr.txt"

    with _pytest.raises(subprocess.TimeoutExpired):
        run_streamed_command(
            [
                sys.executable,
                "-c",
                (
                    "import sys, time; "
                    "print('partial stdout', flush=True); "
                    "print('partial stderr', file=sys.stderr, flush=True); "
                    "time.sleep(30)"
                ),
            ],
            stdout_path=trace_path,
            stderr_path=stderr_path,
            timeout=1,
        )

    captured = capfd.readouterr()
    assert trace_path.read_text(encoding="utf-8") == "partial stdout\n"
    assert stderr_path.read_text(encoding="utf-8") == "partial stderr\n"
    assert captured.out == ""
    assert captured.err == ""


def test_timeout_stream_merge_decodes_and_deduplicates_observations():
    assert _merge_stream_observations(
        b"partial stdout\n",
        "partial stdout\ncomplete stdout\n",
        b"partial stdout\ncomplete stdout\n",
        encoding="utf-8",
    ) == "partial stdout\ncomplete stdout\n"


def test_command_runner_replaces_preexisting_output_symlinks(tmp_path: Path):
    outside_trace = tmp_path / "outside-trace.txt"
    outside_stderr = tmp_path / "outside-stderr.txt"
    outside_trace.write_text("sentinel trace\n", encoding="utf-8")
    outside_stderr.write_text("sentinel stderr\n", encoding="utf-8")
    trace_path = tmp_path / "trace.jsonl"
    stderr_path = tmp_path / "stderr.txt"
    trace_path.symlink_to(outside_trace)
    stderr_path.symlink_to(outside_stderr)

    run_streamed_command(
        [
            sys.executable,
            "-c",
            "import sys; print('trace'); print('error', file=sys.stderr)",
        ],
        stdout_path=trace_path,
        stderr_path=stderr_path,
        timeout=10,
    )

    assert outside_trace.read_text(encoding="utf-8") == "sentinel trace\n"
    assert outside_stderr.read_text(encoding="utf-8") == "sentinel stderr\n"
    assert not trace_path.is_symlink()
    assert not stderr_path.is_symlink()
    assert trace_path.read_text(encoding="utf-8") == "trace\n"
    assert stderr_path.read_text(encoding="utf-8") == "error\n"


def test_config_loads_live_ab_and_judge_model(tmp_path: Path):
    config_path = tmp_path / "codex-evals.ab.toml"
    config_path.write_text(
        """
        [run]
        live_ab = true

        [rubric]
        enabled = false

        [models]
        agent = "gpt-5.2"
        judge = "gpt-5.4"

        [runtime]
        enabled = true
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.run_mode == "ab"
    assert settings.eval_kind == "standard"
    assert settings.rubric_enabled is False
    assert settings.runtime_enabled is True
    assert settings.agent_model == "gpt-5.2"
    assert settings.judge_model == "gpt-5.4"


def test_config_loads_with_skill_and_with_baseline_modes(tmp_path: Path):
    skill_config = tmp_path / "codex-evals.toml"
    skill_config.write_text("[run]\nmode = \"with_skill\"\n", encoding="utf-8")
    baseline_config = tmp_path / "codex-evals.baseline.toml"
    baseline_config.write_text("[run]\nmode = \"with-baseline\"\n", encoding="utf-8")

    assert load_settings(skill_config).run_mode == "with_skill"
    assert load_settings(baseline_config).run_mode == "with_baseline"


def test_config_loads_eval_kind(tmp_path: Path):
    config_path = tmp_path / "codex-evals.toml"
    config_path.write_text("[run]\nmode = \"with_skill\"\neval_kind = \"sanity\"\n", encoding="utf-8")

    settings = load_settings(config_path)

    assert settings.run_mode == "with_skill"
    assert settings.eval_kind == "sanity"


def test_config_loads_agent_backend_settings(tmp_path: Path):
    config_path = tmp_path / "codex-evals.toml"
    config_path.write_text(
        """
        [run]
        mode = "with_skill"

        [agent]
        backend = "cursor"
        command = "/usr/local/bin/cursor"
        extra_args = ["--verbose"]
        timeout = 600
        judge_timeout = 300
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.agent_backend == "cursor"
    assert settings.agent_command == "/usr/local/bin/cursor"
    assert settings.agent_extra_args == ("--verbose",)
    assert settings.agent_timeout == 600
    assert settings.judge_timeout == 300


def test_config_defaults_agent_backend_to_codex(tmp_path: Path):
    config_path = tmp_path / "codex-evals.toml"
    config_path.write_text("[run]\nmode = \"with_skill\"\n", encoding="utf-8")

    settings = load_settings(config_path)

    assert settings.agent_backend == "codex"
    assert settings.agent_command is None
    assert settings.agent_extra_args == ()
    assert settings.agent_timeout == 1200
    assert settings.judge_timeout == 900


def test_command_backed_sanity_check(tmp_path: Path):
    service_dir = tmp_path / "service"
    service_dir.mkdir()
    write_loaded_skill(tmp_path, "sample-skill")
    (service_dir / "package.json").write_text(
        json.dumps({"dependencies": {"@opentelemetry/sdk-node": "latest"}}),
        encoding="utf-8",
    )
    case = sanity_case(
        checks=[
            SanityCheck(
                id="npm-pkg-dependency",
                description="A command can read the dependency from package.json.",
                kind="command_stdout_contains_all",
                command=[
                    sys.executable,
                    "-c",
                    "import json; print(json.load(open('package.json'))['dependencies']['@opentelemetry/sdk-node'])",
                ],
                values=["latest"],
            )
        ]
    )

    grade = grade_sanity(case, tmp_path, "done", parse_trace(empty_trace(tmp_path)), "with_skill")

    check = next(item for item in grade.checks if item.id == "npm-pkg-dependency")
    assert check.passed
    assert "package.json" in check.evidence


def test_runtime_check_is_skipped_until_enabled(tmp_path: Path):
    (tmp_path / "service").mkdir()
    write_loaded_skill(tmp_path, "sample-skill")
    case = runtime_case()

    grade = grade_runtime(
        case,
        tmp_path,
        "done",
        loaded_skill_trace(tmp_path, "sample-skill"),
        "with_skill",
        runtime_enabled=False,
        repo_root=tmp_path,
    )

    check = next(item for item in grade.checks if item.id == "observer-runtime")
    assert check.category == "runtime"
    assert check.skipped
    assert grade.total == 3
    assert next(
        item for item in grade.checks if item.id == "selected-skill-source-isolation"
    ).passed


def test_runtime_compose_file_resolves_relative_to_eval_json_dir(tmp_path: Path):
    service_dir = tmp_path / "run" / "service"
    eval_dir = tmp_path / "evals" / "sample" / "service" / "eval" / "runtime"
    service_dir.mkdir(parents=True)
    eval_dir.mkdir(parents=True)
    compose = eval_dir / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")

    resolved = resolve_compose_file(runtime_check(), service_dir, eval_dir)

    assert resolved == compose.resolve()


def test_runtime_env_points_to_instrumented_service_copy(tmp_path: Path):
    repo_root = tmp_path / "repo"
    service_dir = tmp_path / "run" / "service"
    repo_root.mkdir()
    service_dir.mkdir(parents=True)

    env = runtime_env(repo_root, service_dir, "codex-eval-sample")

    assert env["CODEX_EVAL_REPO_ROOT"] == str(repo_root.resolve())
    assert env["CODEX_EVAL_SERVICE_DIR"] == str(service_dir.resolve())
    assert env["COMPOSE_PROJECT_NAME"] == "codex-eval-sample"


def test_runtime_observer_url_uses_discovered_compose_port():
    assert base_url_from_port_output("0.0.0.0:49153\n") == "http://127.0.0.1:49153"
    assert base_url_from_port_output("[::]:49154\n") == "http://127.0.0.1:49154"
    assert service_url("http://127.0.0.1:49153", "/api/health") == "http://127.0.0.1:49153/api/health"


def test_sanity_file_and_final_checks(tmp_path: Path):
    service = tmp_path / "service"
    service.mkdir()
    (service / "pyproject.toml").write_text("opentelemetry-api\nopentelemetry-sdk\n", encoding="utf-8")
    write_loaded_skill(tmp_path, "sample-skill")
    case = sanity_case(
        skill="sample-skill",
        language="python",
        service="example",
        id="python/example/instrument/direct",
        base_id="python/example/instrument",
        task="Add OpenTelemetry instrumentation.",
        checks=[
            SanityCheck(
                id="deps",
                description="deps",
                kind="file_contains_all",
                path="pyproject.toml",
                values=["opentelemetry-api", "opentelemetry-sdk"],
            ),
            SanityCheck(
                id="final",
                description="final",
                kind="final_contains_all",
                values=["verified"],
            ),
        ],
    )

    grade = grade_sanity(
        case,
        tmp_path,
        "verified",
        loaded_skill_trace(tmp_path, "sample-skill"),
        "with_skill",
    )

    assert grade.pass_rate == 1.0


def test_instrument_trace_allows_no_companion_load_when_child_is_not_invoked(
    tmp_path: Path,
):
    write_loaded_skill(tmp_path, "otel-verify")
    trace = TraceSummary(
        [
            {
                "item": {
                    "type": "command_execution",
                    "command": "rg -n Tracer src",
                    "status": "completed",
                    "exit_code": 1,
                    "aggregated_output": "",
                }
            }
        ],
        "",
    )

    result = check_companion_skill_source_isolation(
        tmp_path, trace, "otel-instrument"
    )

    assert result.passed
    assert "not invoked" in result.evidence


def test_selected_skill_source_isolation_requires_complete_staged_read(
    tmp_path: Path,
):
    write_loaded_skill(tmp_path, "splunk-dashboard")
    staged = tmp_path / ".agents/skills/splunk-dashboard/SKILL.md"
    staged.write_text("name: splunk-dashboard\nfirst\nsecond\n", encoding="utf-8")

    def event(command: str, output: str, exit_code: int = 0) -> dict:
        return {
            "item": {
                "type": "command_execution",
                "command": command,
                "status": "completed",
                "exit_code": exit_code,
                "aggregated_output": output,
            }
        }

    split_read = TraceSummary(
        [
            event(
                "sed -n '1,2p' .agents/skills/splunk-dashboard/SKILL.md",
                "name: splunk-dashboard\nfirst\n",
            ),
            event(
                "sed -n '3,4p' .agents/skills/splunk-dashboard/SKILL.md",
                "second\n",
            ),
        ],
        "",
    )
    accepted = check_selected_skill_source_isolation(
        tmp_path, split_read, "splunk-dashboard"
    )
    assert accepted.passed
    assert "complete skill" in accepted.evidence

    metadata_then_split_read = check_selected_skill_source_isolation(
        tmp_path,
        TraceSummary(
            [
                event(
                    "zsh -lc \"wc -l .agents/skills/splunk-dashboard/SKILL.md && sed -n '1,2p' .agents/skills/splunk-dashboard/SKILL.md\"",
                    "3 .agents/skills/splunk-dashboard/SKILL.md\n"
                    "name: splunk-dashboard\nfirst\n",
                ),
                event(
                    "sed -n '3,4p' .agents/skills/splunk-dashboard/SKILL.md",
                    "second\n",
                ),
            ],
            "",
        ),
        "splunk-dashboard",
    )
    assert metadata_then_split_read.passed

    unsafe_shell_read = check_selected_skill_source_isolation(
        tmp_path,
        TraceSummary(
            [
                event(
                    "zsh -lc \"cat .agents/skills/splunk-dashboard/SKILL.md | tee /tmp/copy\"",
                    staged.read_text(encoding="utf-8"),
                )
            ],
            "",
        ),
        "splunk-dashboard",
    )
    assert not unsafe_shell_read.passed

    service_relative = check_selected_skill_source_isolation(
        tmp_path,
        TraceSummary(
            [
                event(
                    "cat ../.agents/skills/splunk-dashboard/SKILL.md",
                    staged.read_text(encoding="utf-8"),
                )
            ],
            "",
        ),
        "splunk-dashboard",
    )
    assert service_relative.passed

    incomplete = check_selected_skill_source_isolation(
        tmp_path,
        TraceSummary(
            [
                event(
                    "head -1 .agents/skills/splunk-dashboard/SKILL.md",
                    "name: splunk-dashboard\n",
                )
            ],
            "",
        ),
        "splunk-dashboard",
    )
    assert not incomplete.passed
    assert "No complete successful read" in incomplete.evidence


def test_selected_skill_source_isolation_rejects_global_or_alternate_skill(
    tmp_path: Path,
):
    write_loaded_skill(tmp_path, "splunk-dashboard")
    staged = tmp_path / ".agents/skills/splunk-dashboard/SKILL.md"
    output = staged.read_text(encoding="utf-8")

    for command in (
        "cat /Users/example/.codex/skills/obstudio/splunk-dashboard/SKILL.md",
        "cat /repo/skills/splunk-dashboard/SKILL.md",
        "find /Users/example/.codex/skills -name SKILL.md -print",
    ):
        trace = TraceSummary(
            [
                {
                    "item": {
                        "type": "command_execution",
                        "command": command,
                        "status": "completed",
                        "exit_code": 0,
                        "aggregated_output": output,
                    }
                }
            ],
            "",
        )
        rejected = check_selected_skill_source_isolation(
            tmp_path, trace, "splunk-dashboard"
        )
        assert not rejected.passed
        assert "Forbidden selected-skill path" in rejected.evidence


def test_instrument_trace_requires_one_exact_staged_companion_load_when_invoked(
    tmp_path: Path,
):
    write_loaded_skill(tmp_path, "otel-verify")
    staged = tmp_path / ".agents/skills/otel-verify/SKILL.md"
    output = staged.read_text(encoding="utf-8")

    def trace(*commands: str) -> TraceSummary:
        return TraceSummary(
            [
                {
                    "item": {
                        "type": "command_execution",
                        "command": command,
                        "status": "completed",
                        "exit_code": 0,
                        "aggregated_output": output,
                    }
                }
                for command in commands
            ],
            "",
        )

    exact = "cat .agents/skills/otel-verify/SKILL.md"
    accepted = check_companion_skill_source_isolation(
        tmp_path, trace(exact), "otel-instrument"
    )
    assert accepted.passed
    assert "loaded exactly once" in accepted.evidence

    service_relative = check_companion_skill_source_isolation(
        tmp_path,
        trace("cat ../.agents/skills/otel-verify/SKILL.md"),
        "otel-instrument",
    )
    assert service_relative.passed

    omitted = check_companion_skill_source_isolation(
        tmp_path,
        trace(
            "python .agents/skills/otel-verify/scripts/validate_verify.py "
            "--verify-json .observe/otel-verify.json"
        ),
        "otel-instrument",
    )
    assert not omitted.passed
    assert "observed 0" in omitted.evidence

    duplicated = check_companion_skill_source_isolation(
        tmp_path, trace(exact, exact), "otel-instrument"
    )
    assert not duplicated.passed
    assert "observed 2" in duplicated.evidence

    duplicated_in_one_command = check_companion_skill_source_isolation(
        tmp_path,
        trace(
            "cat .agents/skills/otel-verify/SKILL.md "
            ".agents/skills/otel-verify/SKILL.md"
        ),
        "otel-instrument",
    )
    assert not duplicated_in_one_command.passed
    assert "observed 2" in duplicated_in_one_command.evidence


def test_configure_companion_support_tree_does_not_require_skill_load(
    tmp_path: Path,
):
    write_loaded_skill(tmp_path, "splunk-dashboard")
    staged_command = (
        "python .agents/skills/splunk-dashboard/scripts/"
        "validate_dashboard_output.py --help"
    )
    accepted = check_companion_skill_source_isolation(
        tmp_path,
        TraceSummary(
            [
                {
                    "item": {
                        "type": "command_execution",
                        "command": staged_command,
                        "status": "completed",
                        "exit_code": 0,
                        "aggregated_output": "usage",
                    }
                }
            ],
            "",
        ),
        "splunk-configure",
    )
    assert accepted.passed
    assert "authenticated staged support tree" in accepted.evidence

    rejected = check_companion_skill_source_isolation(
        tmp_path,
        TraceSummary(
            [
                {
                    "item": {
                        "type": "command_execution",
                        "command": (
                            "python /Users/example/.codex/skills/obstudio/"
                            "splunk-dashboard/scripts/validate_dashboard_output.py"
                        ),
                        "status": "completed",
                        "exit_code": 0,
                        "aggregated_output": "usage",
                    }
                }
            ],
            "",
        ),
        "splunk-configure",
    )
    assert not rejected.passed
    assert "Forbidden companion-skill path" in rejected.evidence


@pytest.mark.parametrize(
    "command",
    (
        "find .agents/skills/otel-verify -maxdepth 2 -type f",
        "python .agents/skills/otel-verify/scripts/validate_verify.py",
        "jq . .observe/otel-verify.json",
        "$otel-verify --ids OTEL-001",
        "python observe_report.py finalize-instrumentation --project-root .",
    ),
)
def test_instrument_trace_rejects_companion_use_without_loading_skill(
    tmp_path: Path,
    command: str,
):
    write_loaded_skill(tmp_path, "otel-verify")
    trace = TraceSummary(
        [
            {
                "item": {
                    "type": "command_execution",
                    "command": command,
                    "status": "completed",
                    "exit_code": 0,
                    "aggregated_output": "",
                }
            }
        ],
        "",
    )

    result = check_companion_skill_source_isolation(
        tmp_path, trace, "otel-instrument"
    )

    assert not result.passed
    assert "workflow was invoked" in result.evidence
    assert "observed 0" in result.evidence


def test_instrument_trace_rejects_global_plugin_and_alternate_companion_paths(
    tmp_path: Path,
):
    write_loaded_skill(tmp_path, "otel-verify")
    staged = tmp_path / ".agents/skills/otel-verify/SKILL.md"
    output = staged.read_text(encoding="utf-8")
    exact_event = {
        "item": {
            "type": "command_execution",
            "command": "cat .agents/skills/otel-verify/SKILL.md",
            "status": "completed",
            "exit_code": 0,
            "aggregated_output": output,
        }
    }
    for command in (
        "find ~/.codex/skills -name SKILL.md -print",
        "cat /Users/example/.codex/skills/otel-verify/SKILL.md",
        "cat /Users/example/.codex/plugins/cache/x/otel-verify/SKILL.md",
        "find \"$CODEX_HOME\" -name SKILL.md -print",
        "cat /repo/skills/otel-verify/SKILL.md",
        "python /repo/skills/otel-verify/scripts/validate_verify.py",
    ):
        rejected = check_companion_skill_source_isolation(
            tmp_path,
            TraceSummary(
                [
                    exact_event,
                    {
                        "item": {
                            "type": "command_execution",
                            "command": command,
                            "status": "completed",
                            "exit_code": 0,
                            "aggregated_output": output,
                        }
                    },
                ],
                "",
            ),
            "otel-instrument",
        )
        assert not rejected.passed
        assert "Forbidden companion-skill path" in rejected.evidence


def test_baseline_checks_skill_absence(tmp_path: Path):
    (tmp_path / "service").mkdir()
    case = sanity_case(skill="otel-audit", language="python", service="example", id="python/example/audit/direct", base_id="python/example/audit")

    grade = grade_sanity(case, tmp_path, "done", parse_trace(empty_trace(tmp_path)), "baseline")

    check_ids = {check.id for check in grade.checks}
    assert "skills-not-loaded" in check_ids
    assert grade.pass_rate == 1.0


def test_rubric_prompt_can_be_overridden_without_service_assumptions():
    case = RubricEvalCase(
        id="sample/service/rubric/direct",
        base_id="sample/service/rubric",
        prompt_id="direct",
        skill="sample-skill",
        language="sample",
        service="service",
        task="Evaluate the answer.",
        rubric=["Must cite evidence."],
        judge_prompt="Case={case_id}\nInputs:\n{inputs}\nRubric:\n{rubric}",
        judge_inputs=["Read ./answer.md."],
    )

    prompt = " ".join(rubric_prompt(case).split())

    assert "Read ./answer.md." in prompt
    assert "Must cite evidence." in prompt
    assert "./service" not in prompt


def test_default_rubric_prompt_requires_percentage_style_score():
    case = RubricEvalCase(
        id="sample/service/rubric/direct",
        base_id="sample/service/rubric",
        prompt_id="direct",
        skill="sample-skill",
        language="sample",
        service="service",
        task="Evaluate the answer.",
        rubric=["Must cite evidence."],
    )

    prompt = " ".join(rubric_prompt(case).split())

    assert "0-100 percentage-style quality score" in prompt
    assert "Do not put the number of passed checks" in prompt


def test_report_normalizes_count_shaped_rubric_score():
    assert normalize_rubric_score(6, passed=6, total=6) == 100
    assert normalize_rubric_score(5, passed=5, total=6) == 83
    assert normalize_rubric_score(88, passed=5, total=6) == 88


def test_session_result_writer_writes_raw_json_without_markdown(tmp_path: Path):
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    grade = GradeResult(checks=[GradeCheckResult(id="check", description="check", passed=True)])
    side = side_result("with_skill", grade)
    baseline = side_result("baseline", grade)
    result = case_result(side, baseline)

    write_session_results(
        [
            {
                "mode": "ab",
                "eval_kind": "sanity",
                "repo_root": tmp_path,
                "run_root": run_root,
                "skill": "sample-skill",
                "metadata": {"mode": "ab", "eval_kind": "sanity", "run_id": "run", "skill": "sample-skill"},
                "results": [result],
            }
        ]
    )

    assert (run_root / "runs" / "sanity-ab.json").is_file()
    assert (run_root / "run.json").is_file()
    assert not (run_root / "report.md").exists()
    assert not (run_root / "benchmark.json").exists()
    assert (run_root / "results" / "sample" / "service" / "sample-skill" / "eval.json").is_file()
    assert (run_root / "results" / "sample" / "service" / "sample-skill" / "with_skill.json").is_file()
    assert (run_root / "results" / "sample" / "service" / "sample-skill" / "with_baseline.json").is_file()


def test_session_writer_replaces_precreated_result_symlinks(tmp_path: Path):
    run_root = tmp_path / ".workspace/codex-evals/sample-skill/run"
    result_dir = run_root / "results/sample/service/sample-skill"
    runs_dir = run_root / "runs"
    result_dir.mkdir(parents=True)
    runs_dir.mkdir()
    targets = [
        result_dir / "eval.json",
        result_dir / "with_skill.json",
        result_dir / "with_baseline.json",
        runs_dir / "sanity-with_skill.json",
        run_root / "run.json",
    ]
    outside = tmp_path / "outside-result.json"
    outside.write_text('{"sentinel":true}\n', encoding="utf-8")
    for target in targets:
        target.symlink_to(outside)
    grade = GradeResult(
        checks=[GradeCheckResult(id="check", description="check", passed=True)]
    )

    write_session_results(
        [
            {
                "mode": "with_skill",
                "eval_kind": "sanity",
                "repo_root": tmp_path,
                "run_root": run_root,
                "skill": "sample-skill",
                "metadata": {
                    "mode": "with_skill",
                    "eval_kind": "sanity",
                    "run_id": "run",
                    "skill": "sample-skill",
                },
                "results": [case_result(side_result("with_skill", grade), None)],
            }
        ]
    )

    assert outside.read_text(encoding="utf-8") == '{"sentinel":true}\n'
    assert all(target.is_file() and not target.is_symlink() for target in targets)


def test_session_writer_rejects_symlinked_raw_result_directory(tmp_path: Path):
    import pytest as _pytest

    run_root = tmp_path / ".workspace/codex-evals/sample-skill/run"
    run_root.mkdir(parents=True)
    outside = tmp_path / "outside-runs"
    outside.mkdir()
    sentinel = outside / "sentinel.json"
    sentinel.write_text('{"safe":true}\n', encoding="utf-8")
    (run_root / "runs").symlink_to(outside, target_is_directory=True)
    grade = GradeResult(
        checks=[GradeCheckResult(id="check", description="check", passed=True)]
    )

    with _pytest.raises(ValueError, match="must not be a symlink"):
        write_session_results(
            [
                {
                    "mode": "with_skill",
                    "eval_kind": "sanity",
                    "repo_root": tmp_path,
                    "run_root": run_root,
                    "skill": "sample-skill",
                    "metadata": {},
                    "results": [
                        case_result(side_result("with_skill", grade), None)
                    ],
                }
            ]
        )

    assert sentinel.read_text(encoding="utf-8") == '{"safe":true}\n'


def test_worker_result_writer_replaces_precreated_symlink(tmp_path: Path):
    from pytest_codex_evals.plugin import RUN_ID_ATTR, write_worker_results

    config = SimpleNamespace(workerinput={"workerid": "gw0"})
    setattr(config, RUN_ID_ATTR, "run")
    root = tmp_path / ".workspace/codex-evals/_worker-results/run"
    root.mkdir(parents=True)
    target = root / "gw0-0-sample-skill-sanity-with_skill.json"
    outside = tmp_path / "outside-worker.json"
    outside.write_text('{"sentinel":true}\n', encoding="utf-8")
    target.symlink_to(outside)
    grade = GradeResult(
        checks=[GradeCheckResult(id="check", description="check", passed=True)]
    )
    run = {
        "mode": "with_skill",
        "eval_kind": "sanity",
        "repo_root": tmp_path,
        "run_root": tmp_path / ".workspace/codex-evals/sample-skill/run",
        "skill": "sample-skill",
        "metadata": {},
        "results": [case_result(side_result("with_skill", grade), None)],
    }

    write_worker_results(config, {("key",): run})

    assert outside.read_text(encoding="utf-8") == '{"sentinel":true}\n'
    assert target.is_file()
    assert not target.is_symlink()


def test_worker_result_writer_rejects_symlinked_result_directory(tmp_path: Path):
    import pytest as _pytest
    from pytest_codex_evals.plugin import RUN_ID_ATTR, write_worker_results

    config = SimpleNamespace(workerinput={"workerid": "gw0"})
    setattr(config, RUN_ID_ATTR, "run")
    worker_parent = tmp_path / ".workspace/codex-evals/_worker-results"
    worker_parent.mkdir(parents=True)
    outside = tmp_path / "outside-worker"
    outside.mkdir()
    sentinel = outside / "sentinel.json"
    sentinel.write_text('{"safe":true}\n', encoding="utf-8")
    (worker_parent / "run").symlink_to(outside, target_is_directory=True)
    grade = GradeResult(
        checks=[GradeCheckResult(id="check", description="check", passed=True)]
    )
    run = {
        "mode": "with_skill",
        "eval_kind": "sanity",
        "repo_root": tmp_path,
        "run_root": tmp_path / ".workspace/codex-evals/sample-skill/run",
        "skill": "sample-skill",
        "metadata": {},
        "results": [case_result(side_result("with_skill", grade), None)],
    }

    with _pytest.raises(ValueError, match="must not be a symlink"):
        write_worker_results(config, {("key",): run})

    assert sentinel.read_text(encoding="utf-8") == '{"safe":true}\n'


def test_worker_result_collector_rejects_outside_run_root(tmp_path: Path):
    import pytest as _pytest
    from pytest_codex_evals.plugin import (
        RUN_ID_ATTR,
        collect_worker_results,
    )

    (tmp_path / "skills").mkdir()
    config = SimpleNamespace(rootpath=tmp_path)
    setattr(config, RUN_ID_ATTR, "run")
    worker_root = tmp_path / ".workspace/codex-evals/_worker-results/run"
    worker_root.mkdir(parents=True)
    outside = tmp_path / "outside-run"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep\n", encoding="utf-8")
    result = case_result(
        side_result(
            "with_skill",
            GradeResult(
                checks=[
                    GradeCheckResult(
                        id="check", description="check", passed=True
                    )
                ]
            ),
        ),
        None,
    )
    payload = {
        "mode": "with_skill",
        "eval_kind": "sanity",
        "repo_root": str(tmp_path),
        "run_root": str(outside),
        "skill": "sample-skill",
        "metadata": {
            "mode": "with_skill",
            "eval_kind": "sanity",
            "skill": "sample-skill",
            "run_id": "run",
        },
        "results": [result.model_dump(mode="json")],
    }
    (worker_root / "gw0.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    with _pytest.raises(ValueError, match="run_root does not match"):
        collect_worker_results(config)

    assert sentinel.read_text(encoding="utf-8") == "keep\n"


def test_duplicate_validation_results_cannot_report_full(tmp_path: Path):
    definition = write_scope_definition(tmp_path, "sanity")
    fixture = definition.parents[2]
    skill = tmp_path / "skills/sample-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("name: sample-skill\n", encoding="utf-8")
    result = ValidationResult(
        id="sample/service/sample-skill/direct",
        base_id="sample/service/sample-skill",
        prompt_id="direct",
        skill="sample-skill",
        language="sample",
        service="service",
        definition_path=str(definition),
        fixture_dir=str(fixture),
        skill_path=str(skill),
        eval_kind="sanity",
    )

    benchmark = build_validation_benchmark(
        tmp_path,
        "sample-skill",
        [result, result],
        {"mode": "validation"},
    )

    scope = benchmark["metadata"]["scope"]
    assert scope["status"] == "stale"
    assert "duplicate validation result: sample/service/sample-skill/direct" in scope[
        "errors"
    ]
    assert any("validation provenance" in error for error in scope["errors"])


def test_report_renderer_writes_kind_specific_outputs(tmp_path: Path):
    definition = write_scope_definition(tmp_path, "sanity")
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    grade = GradeResult(checks=[GradeCheckResult(id="check", description="check", passed=False, evidence="missing output")])
    result = case_result(side_result("with_skill", grade), None)
    metadata = report_metadata(
        "sample-skill",
        "with_skill",
        run_root,
        {
            "mode": "with_skill",
            "eval_kind": "sanity",
            "run_id": "run",
            "skill": "sample-skill",
            "agent_model": "gpt-test",
        },
    )
    attach_run_provenance(run_root, result, definition, metadata)

    write_session_results(
        [
            {
                "mode": "with_skill",
                "eval_kind": "sanity",
                "repo_root": tmp_path,
                "run_root": run_root,
                "skill": "sample-skill",
                    "metadata": metadata,
                "results": [result],
            }
        ]
    )
    report_path, benchmark_path = render_reports_for_run_root(run_root, "sanity")

    assert report_path == run_root / "sanity" / "report.md"
    assert benchmark_path == run_root / "sanity" / "benchmark.json"
    assert (tmp_path / "eval-reports" / "sample-skill" / "sanity" / "report.md").is_file()
    assert (run_root / "results" / "sample" / "service" / "sample-skill" / "with_skill.json").is_file()
    assert (run_root / "results" / "sample" / "service" / "sample-skill" / "with_baseline.json").is_file()
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    assert benchmark["kind"] == "sanity"
    assert benchmark["metadata"]["scope"]["status"] == "full"
    assert benchmark["evals"][0]["with_baseline"] is None
    assert set(benchmark["evals"][0]["with_skill"]) >= {"checks", "tokens", "duration_seconds"}
    assert "rubric" not in benchmark["evals"][0]["with_skill"]
    assert "runtime" not in benchmark["evals"][0]["with_skill"]
    assert benchmark["failures"][0]["result"] == "sanity:check FAIL"
    report = report_path.read_text(encoding="utf-8")
    assert "Task-agent tokens measure the model carrying out the skill" in report
    assert "With Skill Task-Agent Tokens" in report
    assert "| with_skill | sample/service/sample-skill | sample/service | 1 | 0% (0/1) | 0 | 0 | 0.0s | - | - | - | - |" in report
    assert "sanity:check FAIL" in report


def test_cli_report_renders_latest_run(tmp_path: Path):
    definition = write_scope_definition(tmp_path, "sanity")
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    grade = GradeResult(checks=[GradeCheckResult(id="check", description="check", passed=True)])
    result = case_result(side_result("with_skill", grade), None)
    metadata = report_metadata(
        "sample-skill",
        "with_skill",
        run_root,
        {
            "mode": "with_skill",
            "eval_kind": "sanity",
            "run_id": "run",
            "skill": "sample-skill",
        },
    )
    attach_run_provenance(run_root, result, definition, metadata)
    write_session_results(
        [
            {
                "mode": "with_skill",
                "eval_kind": "sanity",
                "repo_root": tmp_path,
                "run_root": run_root,
                "skill": "sample-skill",
                    "metadata": metadata,
                "results": [result],
            }
        ]
    )

    assert cli_main(["report", "--repo-root", str(tmp_path), "--skill", "sample-skill", "--kind", "sanity"]) == 0

    assert (tmp_path / "eval-reports" / "sample-skill" / "sanity" / "report.md").is_file()
    assert (tmp_path / "eval-reports" / "sample-skill" / "sanity" / "benchmark.json").is_file()


def test_scoped_report_does_not_replace_full_latest_report(tmp_path: Path):
    definition = write_scope_definition(
        tmp_path, "sanity", prompts=("direct", "alternate")
    )
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    grade = GradeResult(
        checks=[GradeCheckResult(id="check", description="check", passed=True)]
    )
    result = case_result(side_result("with_skill", grade), None)
    metadata = report_metadata(
        "sample-skill",
        "with_skill",
        run_root,
        {
            "mode": "with_skill",
            "eval_kind": "sanity",
            "run_id": "run",
            "skill": "sample-skill",
        },
    )
    attach_run_provenance(run_root, result, definition, metadata)
    write_session_results(
        [
            {
                "mode": "with_skill",
                "eval_kind": "sanity",
                "repo_root": tmp_path,
                "run_root": run_root,
                "skill": "sample-skill",
                    "metadata": metadata,
                "results": [result],
            }
        ]
    )
    latest = tmp_path / "eval-reports/sample-skill/sanity"
    latest.mkdir(parents=True)
    (latest / "report.md").write_text("full report\n", encoding="utf-8")
    (latest / "benchmark.json").write_text(
        '{"scope":"full"}\n', encoding="utf-8"
    )

    report_path, benchmark_path = render_reports_for_run_root(run_root, "sanity")

    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    scope = benchmark["metadata"]["scope"]
    assert scope["status"] == "scoped"
    assert scope["selected_prompt_count"] == 1
    assert scope["expected_prompt_count"] == 2
    assert scope["missing_prompt_ids"] == [
        "sample/service/sample-skill/alternate"
    ]
    assert (latest / "report.md").read_text(encoding="utf-8") == "full report\n"
    assert json.loads((latest / "benchmark.json").read_text(encoding="utf-8")) == {
        "scope": "full"
    }
    scoped = latest / "scoped/run"
    assert (scoped / "report.md").read_text(encoding="utf-8") == report_path.read_text(
        encoding="utf-8"
    )
    assert (scoped / "benchmark.json").is_file()


def test_changed_definition_and_config_cannot_replace_full_latest_report(
    tmp_path: Path,
):
    definition, config, run_root, result = captured_sanity_run(tmp_path)
    write_session_results([result])
    _, initial_benchmark_path = render_reports_for_run_root(run_root, "sanity")
    initial_benchmark = json.loads(initial_benchmark_path.read_text(encoding="utf-8"))
    assert initial_benchmark["metadata"]["scope"]["status"] == "full"
    latest = tmp_path / "eval-reports/sample-skill/sanity"
    latest_report = (latest / "report.md").read_text(encoding="utf-8")

    definition.write_text(
        json.dumps(
            {
                "id": "sample/service/sample-skill",
                "skill": "sample-skill",
                "prompts": [{"id": "direct", "task": "Changed task."}],
                "checks": [
                    {
                        "id": "changed-check",
                        "description": "Changed contract.",
                        "kind": "final_contains_all",
                        "values": ["changed"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    config.write_text('[run]\nmode = "ab"\n', encoding="utf-8")

    report_path, benchmark_path = render_reports_for_run_root(run_root, "sanity")

    scope = json.loads(benchmark_path.read_text(encoding="utf-8"))["metadata"][
        "scope"
    ]
    assert scope["status"] == "stale"
    assert scope["stale_prompt_ids"] == ["sample/service/sample-skill/direct"]
    assert any("eval definition changed after capture" in error for error in scope["errors"])
    assert any("eval config changed after capture" in error for error in scope["errors"])
    assert (latest / "report.md").read_text(encoding="utf-8") == latest_report
    assert (
        latest / "scoped" / run_root.name / "report.md"
    ).read_text(encoding="utf-8") == report_path.read_text(encoding="utf-8")


def test_report_rejects_replayed_case_contract_with_current_input_hashes(
    tmp_path: Path,
):
    definition = write_scope_definition(tmp_path, "sanity")
    run_root = tmp_path / ".workspace/codex-evals/sample-skill/run"
    result = case_result(
        side_result(
            "with_skill",
            GradeResult(
                checks=[
                    GradeCheckResult(
                        id="check",
                        description="check",
                        passed=True,
                    )
                ]
            ),
        ),
        None,
    )
    metadata = report_metadata(
        "sample-skill",
        "with_skill",
        run_root,
        {
            "mode": "with_skill",
            "eval_kind": "sanity",
            "run_id": "run",
            "skill": "sample-skill",
        },
    )
    attach_run_provenance(run_root, result, definition, metadata)

    changed_definition = json.loads(definition.read_text(encoding="utf-8"))
    changed_definition["prompts"][0]["task"] = "Run changed contract."
    definition.write_text(
        json.dumps(changed_definition),
        encoding="utf-8",
    )
    provenance_path = next(
        run_root.rglob("with_skill/.codex-eval-provenance.json")
    )
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["definition"]["sha256"] = hashlib.sha256(
        definition.read_bytes()
    ).hexdigest()
    provenance["fixture"]["tree_sha256"] = tree_sha256(
        definition.parents[2]
    )
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")

    write_session_results(
        [
            {
                "mode": "with_skill",
                "eval_kind": "sanity",
                "repo_root": tmp_path,
                "run_root": run_root,
                "skill": "sample-skill",
                "metadata": metadata,
                "results": [result],
            }
        ]
    )
    _, benchmark_path = render_reports_for_run_root(run_root, "sanity")

    scope = json.loads(benchmark_path.read_text(encoding="utf-8"))[
        "metadata"
    ]["scope"]
    assert scope["status"] == "stale"
    assert scope["stale_prompt_ids"] == [
        "sample/service/sample-skill/direct"
    ]
    assert any(
        "task differs from the current eval definition" in error
        for error in scope["errors"]
    )
    assert any(
        "case contract differs from the current eval definition" in error
        for error in scope["errors"]
    )


def test_changed_skill_and_shared_contract_cannot_report_full(tmp_path: Path):
    _, _, run_root, result = captured_sanity_run(tmp_path)
    write_session_results([result])
    _, initial_benchmark_path = render_reports_for_run_root(run_root, "sanity")
    assert (
        json.loads(initial_benchmark_path.read_text(encoding="utf-8"))["metadata"]
        ["scope"]["status"]
        == "full"
    )

    (tmp_path / "skills/sample-skill/SKILL.md").write_text(
        "name: sample-skill\nchanged: true\n", encoding="utf-8"
    )
    (tmp_path / "skills/references/contract.md").write_text(
        "changed contract\n", encoding="utf-8"
    )

    _, benchmark_path = render_reports_for_run_root(run_root, "sanity")

    scope = json.loads(benchmark_path.read_text(encoding="utf-8"))["metadata"][
        "scope"
    ]
    assert scope["status"] == "stale"
    assert any("skill tree changed after capture" in error for error in scope["errors"])
    assert any("shared references changed after capture" in error for error in scope["errors"])


def test_changed_harness_source_identity_cannot_report_full(tmp_path: Path):
    _, _, run_root, result = captured_sanity_run(tmp_path)
    write_session_results([result])
    provenance = next(run_root.rglob("with_skill/.codex-eval-provenance.json"))
    payload = json.loads(provenance.read_text(encoding="utf-8"))
    payload["harness"]["tree_sha256"] = "f" * 64
    provenance.write_text(json.dumps(payload), encoding="utf-8")
    write_capture_manifest(run_root)

    _, benchmark_path = render_reports_for_run_root(run_root, "sanity")

    scope = json.loads(benchmark_path.read_text(encoding="utf-8"))["metadata"][
        "scope"
    ]
    assert scope["status"] == "stale"
    assert any(
        "eval harness or grader source changed after capture" in error
        for error in scope["errors"]
    )


def test_report_rejects_stitched_skill_and_shared_reference_identities(
    tmp_path: Path,
):
    definition = write_scope_definition(
        tmp_path,
        "sanity",
        prompts=("direct", "alternate"),
    )
    fixture = definition.parents[2]
    (fixture / "main.txt").write_text("fixture\n", encoding="utf-8")
    canonical_skill = tmp_path / "skills/sample-skill"
    alternate_skill = tmp_path / "skills/sample-skill-copy"
    for skill in (canonical_skill, alternate_skill):
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("name: sample-skill\n", encoding="utf-8")
    shared = tmp_path / "skills/references"
    shared.mkdir()
    (shared / "contract.md").write_text("contract\n", encoding="utf-8")
    config = tmp_path / "codex-evals.toml"
    config.write_text('[run]\nmode = "with_skill"\n', encoding="utf-8")
    run_root = tmp_path / ".workspace/codex-evals/sample-skill/run"
    metadata = report_metadata(
        "sample-skill",
        "with_skill",
        run_root,
        {
            "mode": "with_skill",
            "eval_kind": "sanity",
            "run_id": "run",
            "skill": "sample-skill",
            "config_path": "codex-evals.toml",
        },
    )
    direct = run_case(
        repo_root=tmp_path,
        run_root=run_root,
        case=sanity_case(
            task="Run direct.",
            definition_path=definition,
            fixture_dir=fixture,
        ),
        skill_dir=canonical_skill,
        rubric=False,
        eval_kind="sanity",
        sides=("with_skill",),
        backend=RecordingBackend(),
        config_path=config,
        run_configuration=metadata,
    )
    alternate = run_case(
        repo_root=tmp_path,
        run_root=run_root,
        case=sanity_case(
            id="sample/service/sample-skill/alternate",
            prompt_id="alternate",
            task="Run alternate.",
            definition_path=definition,
            fixture_dir=fixture,
        ),
        skill_dir=alternate_skill,
        rubric=False,
        eval_kind="sanity",
        sides=("with_skill",),
        backend=RecordingBackend(),
        config_path=config,
        run_configuration=metadata,
    )
    alternate_manifest = next(
        (run_root / "cases/sample/service/alternate").rglob(
            "with_skill/.codex-eval-provenance.json"
        )
    )
    alternate_provenance = json.loads(
        alternate_manifest.read_text(encoding="utf-8")
    )
    alternate_provenance["shared_references"]["path"] = str(
        tmp_path / "skills/../skills/references"
    )
    alternate_manifest.write_text(
        json.dumps(alternate_provenance), encoding="utf-8"
    )
    run = {
        "mode": "with_skill",
        "eval_kind": "sanity",
        "repo_root": tmp_path,
        "run_root": run_root,
        "skill": "sample-skill",
        "metadata": metadata,
        "results": [direct, alternate],
    }
    write_session_results([run])

    _, benchmark_path = render_reports_for_run_root(run_root, "sanity")

    scope = json.loads(benchmark_path.read_text(encoding="utf-8"))["metadata"][
        "scope"
    ]
    assert scope["status"] == "stale"
    assert any("different selected skill paths" in error for error in scope["errors"])
    assert any("different shared-reference paths" in error for error in scope["errors"])


def test_validation_report_rejects_changed_definition_with_same_prompt_id(
    tmp_path: Path,
):
    from pytest_codex_evals.plugin import validation_result

    definition = write_scope_definition(tmp_path, "sanity")
    fixture = definition.parents[2]
    skill = tmp_path / "skills/sample-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("name: sample-skill\n", encoding="utf-8")
    config = tmp_path / "codex-evals.toml"
    config.write_text('[run]\nmode = "validation"\n', encoding="utf-8")
    metadata = {"mode": "validation"}
    result = validation_result(
        sanity_case(
            task="Run direct.",
            definition_path=definition,
            fixture_dir=fixture,
        ),
        tmp_path,
        skill,
        config_path=config,
        run_configuration=metadata,
    )
    initial = build_validation_benchmark(
        tmp_path,
        "sample-skill",
        [result],
        metadata,
    )
    assert initial["metadata"]["scope"]["status"] == "full"

    definition.write_text(
        json.dumps(
            {
                "id": "sample/service/sample-skill",
                "skill": "sample-skill",
                "prompts": [{"id": "direct", "task": "Run direct."}],
                "checks": [
                    {
                        "id": "new-check",
                        "description": "Changed contract.",
                        "kind": "final_contains_all",
                        "values": ["changed"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    changed = build_validation_benchmark(
        tmp_path,
        "sample-skill",
        [result],
        metadata,
    )
    scope = changed["metadata"]["scope"]
    assert scope["status"] == "stale"
    assert any(
        "eval definition changed after validation" in error
        for error in scope["errors"]
    )


def test_forged_payload_metadata_is_quarantined_and_not_displayed(tmp_path: Path):
    _, _, run_root, result = captured_sanity_run(tmp_path)
    write_session_results([result])
    raw_path = run_root / "runs/sanity-with_skill.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["metadata"]["agent_model"] = "forged-model"
    raw_path.write_text(json.dumps(raw), encoding="utf-8")
    write_capture_manifest(run_root)

    report_path, benchmark_path = render_reports_for_run_root(run_root, "sanity")

    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    scope = benchmark["metadata"]["scope"]
    assert scope["status"] == "stale"
    assert any(
        "payload metadata differs from captured run configuration" in error
        for error in scope["errors"]
    )
    assert benchmark["metadata"]["agent_model"] == "-"
    assert "forged-model" not in report_path.read_text(encoding="utf-8")


def test_duplicate_result_and_run_manifest_entries_are_rejected(tmp_path: Path):
    _, _, run_root, result = captured_sanity_run(tmp_path)
    write_session_results([result])
    raw_path = run_root / "runs/sanity-with_skill.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["results"].append(raw["results"][0])
    raw_path.write_text(json.dumps(raw), encoding="utf-8")
    write_capture_manifest(run_root)

    _, benchmark_path = render_reports_for_run_root(run_root, "sanity")

    scope = json.loads(benchmark_path.read_text(encoding="utf-8"))["metadata"][
        "scope"
    ]
    assert scope["status"] == "stale"
    assert any("duplicate captured result" in error for error in scope["errors"])

    manifest_path = run_root / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runs"].append(manifest["runs"][0])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    write_capture_manifest(run_root)
    import pytest as _pytest

    with _pytest.raises(ValueError, match="duplicate entries"):
        render_reports_for_run_root(run_root, "sanity")


def test_run_manifest_traversal_is_rejected(tmp_path: Path):
    _, _, run_root, result = captured_sanity_run(tmp_path)
    write_session_results([result])
    manifest_path = run_root / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runs"] = ["../outside.json"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    write_capture_manifest(run_root)
    import pytest as _pytest

    with _pytest.raises(ValueError, match="escapes run root"):
        render_reports_for_run_root(run_root, "sanity")


def test_report_rejects_artifact_mutation_after_capture(tmp_path: Path):
    _, _, run_root, result = captured_sanity_run(tmp_path)
    write_session_results([result])
    raw_path = run_root / "runs/sanity-with_skill.json"
    raw_path.write_text('{"forged":true}\n', encoding="utf-8")

    import pytest as _pytest

    with _pytest.raises(ValueError, match="changed after capture"):
        render_reports_for_run_root(run_root, "sanity")


def test_report_consumes_authenticated_bytes_after_verification(
    tmp_path: Path,
):
    from unittest.mock import patch
    from pytest_codex_evals import report as report_module

    _, _, run_root, result = captured_sanity_run(tmp_path)
    write_session_results([result])
    raw_path = run_root / "runs/sanity-with_skill.json"
    original_verify = report_module.verify_capture_manifest

    def verify_then_mutate(root: Path):
        authenticated = original_verify(root)
        forged = json.loads(raw_path.read_text(encoding="utf-8"))
        forged["results"][0]["with_skill"]["tokens"] = 999999
        raw_path.write_text(json.dumps(forged), encoding="utf-8")
        return authenticated

    with patch.object(
        report_module,
        "verify_capture_manifest",
        side_effect=verify_then_mutate,
    ):
        _, benchmark_path = render_reports_for_run_root(run_root, "sanity")

    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    assert benchmark["evals"][0]["with_skill"]["tokens"] != 999999


def test_atomic_writer_refuses_parent_namespace_swap(tmp_path: Path):
    import os
    import pytest as _pytest
    from unittest.mock import patch

    boundary = tmp_path / "output-root"
    parent = boundary / "nested"
    parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep\n", encoding="utf-8")
    stolen = tmp_path / "stolen-root"
    target = parent / "result.json"
    real_replace = os.replace
    swapped = False

    def replace_after_swap(*args, **kwargs):
        nonlocal swapped
        if not swapped:
            boundary.rename(stolen)
            boundary.symlink_to(outside, target_is_directory=True)
            swapped = True
        return real_replace(*args, **kwargs)

    with patch("pytest_codex_evals.backends.os.replace", replace_after_swap):
        with _pytest.raises(ValueError, match="namespace changed"):
            atomic_text_write(target, "forged\n", boundary=boundary)

    assert sentinel.read_text(encoding="utf-8") == "keep\n"
    assert not (outside / "nested/result.json").exists()
    assert (stolen / "nested/result.json").read_text(encoding="utf-8") == (
        "forged\n"
    )


def test_atomic_writer_does_not_unlink_replaced_leaf_after_failed_check(
    tmp_path: Path,
):
    import pytest as _pytest
    from unittest.mock import patch
    from pytest_codex_evals import backends as backends_module

    boundary = tmp_path / "output-root"
    boundary.mkdir()
    target = boundary / "result.json"
    real_namespace_check = backends_module.anchored_namespace_matches
    replaced = False

    def replace_before_failed_check(anchor):
        nonlocal replaced
        if not replaced and target.exists():
            target.unlink()
            target.write_text("replacement\n", encoding="utf-8")
            replaced = True
            return False
        return real_namespace_check(anchor)

    with patch(
        "pytest_codex_evals.backends.anchored_namespace_matches",
        replace_before_failed_check,
    ):
        with _pytest.raises(ValueError, match="namespace changed"):
            atomic_text_write(target, "generated\n", boundary=boundary)

    assert replaced
    assert target.read_text(encoding="utf-8") == "replacement\n"


def test_anchored_reader_rejects_parent_namespace_swap_during_read(
    tmp_path: Path,
):
    import os
    import pytest as _pytest
    from unittest.mock import patch
    from pytest_codex_evals import backends as backends_module

    if not backends_module.descriptor_operations_supported():
        _pytest.skip("descriptor-relative filesystem APIs are unavailable")

    boundary = tmp_path / "output-root"
    boundary.mkdir()
    target = boundary / "result.json"
    target.write_text("trusted\n", encoding="utf-8")
    expected_identity = path_directory_identity(boundary)
    stolen = tmp_path / "stolen-root"
    real_stat = os.stat
    swapped = False

    def stat_after_parent_swap(path, *args, **kwargs):
        nonlocal swapped
        if (
            not swapped
            and path == target.name
            and kwargs.get("dir_fd") is not None
        ):
            boundary.rename(stolen)
            boundary.mkdir()
            (boundary / target.name).write_text("attacker\n", encoding="utf-8")
            swapped = True
        return real_stat(path, *args, **kwargs)

    with patch("pytest_codex_evals.backends.os.stat", stat_after_parent_swap):
        with _pytest.raises(ValueError, match="namespace changed during read"):
            read_regular_text(
                target,
                boundary=boundary,
                expected_boundary_identity=expected_identity,
            )

    assert swapped
    assert (stolen / target.name).read_text(encoding="utf-8") == "trusted\n"
    assert (boundary / target.name).read_text(encoding="utf-8") == "attacker\n"


def test_temporary_output_cleanup_touches_neither_namespace_after_parent_swap(
    tmp_path: Path,
):
    import pytest as _pytest

    if not descriptor_operations_supported():
        _pytest.skip("requires directory-relative cleanup")
    exec_dir = tmp_path / "exec"
    exec_dir.mkdir()
    output = create_anchored_temporary_output(
        exec_dir,
        ".agent-final-",
        expected_parent_identity=path_directory_identity(exec_dir),
    )
    output.path.write_text("generated\n", encoding="utf-8")
    stolen = tmp_path / "stolen-exec"
    exec_dir.rename(stolen)
    exec_dir.mkdir()
    decoy = exec_dir / output.name
    decoy.write_text("keep\n", encoding="utf-8")

    cleanup_anchored_temporary_output(output)

    assert decoy.read_text(encoding="utf-8") == "keep\n"
    assert (stolen / output.name).read_text(encoding="utf-8") == "generated\n"


def test_temporary_output_cleanup_preserves_replaced_leaf(tmp_path: Path):
    import pytest as _pytest

    if not descriptor_operations_supported():
        _pytest.skip("requires directory-relative cleanup")
    exec_dir = tmp_path / "exec"
    exec_dir.mkdir()
    output = create_anchored_temporary_output(
        exec_dir,
        ".agent-final-",
        expected_parent_identity=path_directory_identity(exec_dir),
    )
    output.path.unlink()
    output.path.write_text("replacement\n", encoding="utf-8")

    cleanup_anchored_temporary_output(output)

    assert output.path.read_text(encoding="utf-8") == "replacement\n"


def test_temporary_output_cleanup_is_idempotent_and_leaves_exposed_leaf(
    tmp_path: Path,
):
    exec_dir = tmp_path / "exec"
    exec_dir.mkdir()
    output = create_anchored_temporary_output(
        exec_dir,
        ".agent-final-",
        expected_parent_identity=path_directory_identity(exec_dir),
    )
    output.path.write_text("generated\n", encoding="utf-8")

    cleanup_anchored_temporary_output(output)
    cleanup_anchored_temporary_output(output)

    assert output.path.read_text(encoding="utf-8") == "generated\n"


def test_backend_temporary_output_uses_capture_excluded_scratch(tmp_path: Path):
    exec_dir = tmp_path / "exec"
    exec_dir.mkdir()

    output, boundary, boundary_identity = create_backend_temporary_output(
        exec_dir,
        ".agent-final-",
        expected_exec_dir_identity=path_directory_identity(exec_dir),
    )
    output.path.write_text("generated\n", encoding="utf-8")

    assert boundary == exec_dir / BACKEND_SCRATCH_DIRECTORY
    assert output.path.parent == boundary
    assert read_regular_text(
        output.path,
        boundary=boundary,
        expected_boundary_identity=boundary_identity,
    ) == "generated\n"

    cleanup_anchored_temporary_output(output)


def test_anchored_reader_rejects_same_inode_mutation_during_read(tmp_path: Path):
    import os
    import pytest as _pytest
    from unittest.mock import patch
    from pytest_codex_evals import backends as backends_module

    if not backends_module.descriptor_operations_supported():
        _pytest.skip("descriptor-relative filesystem APIs are unavailable")

    boundary = tmp_path / "output-root"
    boundary.mkdir()
    target = boundary / "result.json"
    target.write_bytes(b"A" * (2 * 1024 * 1024))
    expected_identity = path_directory_identity(boundary)
    original_identity = target.stat().st_dev, target.stat().st_ino
    real_read = os.read
    mutated = False

    def read_then_mutate_same_inode(descriptor, size):
        nonlocal mutated
        payload = real_read(descriptor, size)
        if payload and not mutated:
            with target.open("r+b", buffering=0) as destination:
                destination.write(b"B" * (2 * 1024 * 1024))
            mutated = True
        return payload

    with patch("pytest_codex_evals.backends.os.read", read_then_mutate_same_inode):
        with _pytest.raises(ValueError, match="input changed during read"):
            read_regular_text(
                target,
                boundary=boundary,
                expected_boundary_identity=expected_identity,
            )

    assert mutated
    assert (target.stat().st_dev, target.stat().st_ino) == original_identity


def test_portable_reader_rejects_same_inode_mutation_during_read(
    tmp_path: Path,
    monkeypatch,
):
    import os
    import pytest as _pytest
    from unittest.mock import patch
    from pytest_codex_evals import backends as backends_module

    boundary = tmp_path / "output-root"
    boundary.mkdir()
    target = boundary / "result.json"
    target.write_bytes(b"A" * (2 * 1024 * 1024))
    expected_identity = path_directory_identity(boundary)
    original_identity = target.stat().st_dev, target.stat().st_ino
    real_read = os.read
    mutated = False

    monkeypatch.setattr(
        backends_module, "descriptor_operations_supported", lambda: False
    )

    def read_then_mutate_same_inode(descriptor, size):
        nonlocal mutated
        payload = real_read(descriptor, size)
        if payload and not mutated:
            with target.open("r+b", buffering=0) as destination:
                destination.write(b"B" * (2 * 1024 * 1024))
            mutated = True
        return payload

    with patch("pytest_codex_evals.backends.os.read", read_then_mutate_same_inode):
        with _pytest.raises(ValueError, match="input changed during read"):
            read_regular_text(
                target,
                boundary=boundary,
                expected_boundary_identity=expected_identity,
            )

    assert mutated
    assert (target.stat().st_dev, target.stat().st_ino) == original_identity


def test_anchored_reader_accepts_stable_regular_text(tmp_path: Path):
    boundary = tmp_path / "output-root"
    boundary.mkdir()
    target = boundary / "result.json"
    target.write_text("trusted\n", encoding="utf-8")

    assert read_regular_text(
        target,
        boundary=boundary,
        expected_boundary_identity=path_directory_identity(boundary),
    ) == "trusted\n"


def test_anchored_reader_rejects_regular_leaf_swap(tmp_path: Path):
    import os
    import pytest as _pytest
    from unittest.mock import patch
    from pytest_codex_evals import backends as backends_module

    if not backends_module.descriptor_operations_supported():
        _pytest.skip("descriptor-relative filesystem APIs are unavailable")

    boundary = tmp_path / "output-root"
    boundary.mkdir()
    target = boundary / "result.json"
    replacement = boundary / "replacement.json"
    target.write_text("trusted\n", encoding="utf-8")
    replacement.write_text("attacker\n", encoding="utf-8")
    expected_identity = path_directory_identity(boundary)
    real_open = os.open
    swapped = False

    def open_after_leaf_swap(path, flags, *args, **kwargs):
        nonlocal swapped
        if (
            not swapped
            and path == target.name
            and kwargs.get("dir_fd") is not None
        ):
            target.unlink()
            replacement.replace(target)
            swapped = True
        return real_open(path, flags, *args, **kwargs)

    with patch("pytest_codex_evals.backends.os.open", open_after_leaf_swap):
        with _pytest.raises(ValueError, match="input changed before read"):
            read_regular_text(
                target,
                boundary=boundary,
                expected_boundary_identity=expected_identity,
            )

    assert swapped
    assert target.read_text(encoding="utf-8") == "attacker\n"


def test_anchored_reader_rejects_fifo_leaf_without_blocking(tmp_path: Path):
    import os
    import pytest as _pytest
    from unittest.mock import patch
    from pytest_codex_evals import backends as backends_module

    if not hasattr(os, "mkfifo"):
        _pytest.skip("FIFO creation is unavailable")
    if not backends_module.descriptor_operations_supported():
        _pytest.skip("descriptor-relative filesystem APIs are unavailable")

    boundary = tmp_path / "output-root"
    boundary.mkdir()
    target = boundary / "result.json"
    target.write_text("trusted\n", encoding="utf-8")
    expected_identity = path_directory_identity(boundary)
    real_open = os.open
    swapped = False

    def open_after_fifo_swap(path, flags, *args, **kwargs):
        nonlocal swapped
        if (
            not swapped
            and path == target.name
            and kwargs.get("dir_fd") is not None
        ):
            target.unlink()
            os.mkfifo(target)
            swapped = True
            assert flags & os.O_NONBLOCK
        return real_open(path, flags, *args, **kwargs)

    with patch("pytest_codex_evals.backends.os.open", open_after_fifo_swap):
        with _pytest.raises(ValueError, match="input must be a regular file"):
            read_regular_text(
                target,
                boundary=boundary,
                expected_boundary_identity=expected_identity,
            )

    assert swapped


def test_portable_reader_rejects_fifo_leaf_without_blocking(
    tmp_path: Path,
    monkeypatch,
):
    import os
    import pytest as _pytest
    from pytest_codex_evals import backends as backends_module

    if not hasattr(os, "mkfifo"):
        _pytest.skip("FIFO creation is unavailable")

    boundary = tmp_path / "output-root"
    boundary.mkdir()
    target = boundary / "result.json"
    target.write_text("trusted\n", encoding="utf-8")
    expected_identity = path_directory_identity(boundary)
    real_open = os.open
    swapped = False

    monkeypatch.setattr(
        backends_module, "descriptor_operations_supported", lambda: False
    )

    def open_after_fifo_swap(path, flags, *args, **kwargs):
        nonlocal swapped
        if not swapped and Path(path) == target:
            target.unlink()
            os.mkfifo(target)
            swapped = True
            assert flags & os.O_NONBLOCK
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(backends_module.os, "open", open_after_fifo_swap)
    with _pytest.raises(ValueError, match="input must be a regular file"):
        read_regular_text(
            target,
            boundary=boundary,
            expected_boundary_identity=expected_identity,
        )

    assert swapped


def test_anchored_directory_creation_never_follows_swapped_parent(
    tmp_path: Path,
):
    import os
    import pytest as _pytest
    from unittest.mock import patch

    boundary = tmp_path / "root"
    boundary.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep\n", encoding="utf-8")
    stolen = tmp_path / "stolen-root"
    real_mkdir = os.mkdir
    swapped = False

    def mkdir_after_swap(*args, **kwargs):
        nonlocal swapped
        if not swapped:
            boundary.rename(stolen)
            boundary.symlink_to(outside, target_is_directory=True)
            swapped = True
        return real_mkdir(*args, **kwargs)

    with patch("pytest_codex_evals.backends.os.mkdir", mkdir_after_swap):
        with _pytest.raises(ValueError, match="namespace changed"):
            ensure_anchored_directory(
                boundary / "nested/leaf", boundary=boundary
            )

    assert sentinel.read_text(encoding="utf-8") == "keep\n"
    assert not (outside / "nested").exists()
    assert (stolen / "nested/leaf").is_dir()


def test_anchored_directory_creation_accepts_concurrent_directory_winner(
    tmp_path: Path,
):
    import os
    from unittest.mock import patch

    boundary = tmp_path / "root"
    boundary.mkdir()
    target = boundary / "nested/leaf"
    real_mkdir = os.mkdir
    simulated_race = False

    def mkdir_after_concurrent_winner(*args, **kwargs):
        nonlocal simulated_race
        if not simulated_race:
            simulated_race = True
            real_mkdir(*args, **kwargs)
            raise FileExistsError("created by another worker")
        return real_mkdir(*args, **kwargs)

    with patch(
        "pytest_codex_evals.backends.os.mkdir",
        mkdir_after_concurrent_winner,
    ):
        ensure_anchored_directory(target, boundary=boundary)

    assert simulated_race
    assert target.is_dir()


def test_report_outputs_replace_leaf_symlinks_without_following_them(
    tmp_path: Path,
):
    run_root = tmp_path / ".workspace/codex-evals/sample-skill/run"
    report_dir = run_root / "sanity"
    report_dir.mkdir(parents=True)
    latest_dir = tmp_path / "latest/sample-skill/sanity"
    latest_dir.mkdir(parents=True)
    outside_report = tmp_path / "outside-report.md"
    outside_benchmark = tmp_path / "outside-benchmark.json"
    outside_report.write_text("sentinel report\n", encoding="utf-8")
    outside_benchmark.write_text('{"sentinel":true}\n', encoding="utf-8")
    for directory in (report_dir, latest_dir):
        (directory / "report.md").symlink_to(outside_report)
        (directory / "benchmark.json").symlink_to(outside_benchmark)
    benchmark = {"metadata": {"scope": {"status": "full"}}}

    write_report_outputs(
        tmp_path,
        run_root,
        "sample-skill",
        "sanity",
        benchmark,
        "safe report\n",
        tmp_path / "latest",
    )

    assert outside_report.read_text(encoding="utf-8") == "sentinel report\n"
    assert outside_benchmark.read_text(encoding="utf-8") == '{"sentinel":true}\n'
    for directory in (report_dir, latest_dir):
        assert not (directory / "report.md").is_symlink()
        assert not (directory / "benchmark.json").is_symlink()


def test_latest_report_outputs_redact_machine_specific_repo_root(
    tmp_path: Path,
):
    repo_root = tmp_path / "private-machine" / "obstudio"
    run_root = repo_root / ".workspace/codex-evals/sample-skill/run"
    run_root.mkdir(parents=True)
    benchmark = {
        "metadata": {
            "repo_root": str(repo_root),
            "scope": {"status": "full"},
        },
        "evidence_path": str(repo_root / "evals/sample/case.json"),
    }
    report = (
        f"Repository: {repo_root}\n"
        f"Evidence: {repo_root / 'evals/sample/case.json'}\n"
    )

    report_path, benchmark_path = write_report_outputs(
        repo_root,
        run_root,
        "sample-skill",
        "sanity",
        benchmark,
        report,
    )

    latest = repo_root / "eval-reports/sample-skill/sanity"
    published_benchmark = json.loads(
        (latest / "benchmark.json").read_text(encoding="utf-8")
    )
    published_report = (latest / "report.md").read_text(encoding="utf-8")
    self_path = str(repo_root)
    assert self_path in benchmark_path.read_text(encoding="utf-8")
    assert self_path in report_path.read_text(encoding="utf-8")
    assert self_path not in json.dumps(published_benchmark)
    assert self_path not in published_report
    assert published_benchmark["metadata"]["repo_root"] == "."
    assert published_benchmark["evidence_path"] == "evals/sample/case.json"
    assert "Evidence: evals/sample/case.json" in published_report


def test_report_outputs_reject_symlinked_run_and_latest_directories(
    tmp_path: Path,
):
    import pytest as _pytest

    run_root = tmp_path / ".workspace/codex-evals/sample-skill/run"
    run_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (run_root / "sanity").symlink_to(outside)
    benchmark = {"metadata": {"scope": {"status": "full"}}}

    with _pytest.raises(ValueError, match="must not be a symlink"):
        write_report_outputs(
            tmp_path,
            run_root,
            "sample-skill",
            "sanity",
            benchmark,
            "report\n",
        )

    (run_root / "sanity").unlink()
    latest_root = tmp_path / "latest"
    latest_root.mkdir()
    (latest_root / "sample-skill").symlink_to(outside)
    with _pytest.raises(ValueError, match="must not be a symlink"):
        write_report_outputs(
            tmp_path,
            run_root,
            "sample-skill",
            "sanity",
            benchmark,
            "report\n",
            latest_root,
        )


def test_report_directory_creation_refuses_ancestor_namespace_swap(
    tmp_path: Path,
):
    import os
    import pytest as _pytest
    from unittest.mock import patch

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    run_root = repo_root / ".workspace/codex-evals/sample-skill/run"
    stolen_root = tmp_path / "stolen-repo"
    outside = tmp_path / "outside"
    outside.mkdir()
    real_mkdir = os.mkdir
    swapped = False

    def mkdir_after_swap(*args, **kwargs):
        nonlocal swapped
        if not swapped:
            repo_root.rename(stolen_root)
            repo_root.symlink_to(outside, target_is_directory=True)
            swapped = True
        return real_mkdir(*args, **kwargs)

    benchmark = {"metadata": {"scope": {"status": "full"}}}
    with patch(
        "pytest_codex_evals.backends.os.mkdir",
        side_effect=mkdir_after_swap,
    ):
        with _pytest.raises(ValueError, match="namespace changed"):
            write_report_outputs(
                repo_root,
                run_root,
                "sample-skill",
                "sanity",
                benchmark,
                "report\n",
            )

    assert swapped
    assert not (outside / ".workspace").exists()
    assert not (outside / "eval-reports").exists()
    assert not list(outside.rglob("report.md"))
    assert not list(outside.rglob("benchmark.json"))


def captured_sanity_run(
    tmp_path: Path,
) -> tuple[Path, Path, Path, dict[str, object]]:
    definition = write_scope_definition(tmp_path, "sanity")
    fixture = definition.parents[2]
    (fixture / "main.txt").write_text("fixture\n", encoding="utf-8")
    skill = tmp_path / "skills/sample-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("name: sample-skill\n", encoding="utf-8")
    shared = tmp_path / "skills/references"
    shared.mkdir()
    (shared / "contract.md").write_text("contract\n", encoding="utf-8")
    config = tmp_path / "codex-evals.toml"
    config.write_text('[run]\nmode = "with_skill"\n', encoding="utf-8")
    run_root = tmp_path / ".workspace/codex-evals/sample-skill/run"
    metadata = report_metadata(
        "sample-skill",
        "with_skill",
        run_root,
        {
            "mode": "with_skill",
            "eval_kind": "sanity",
            "run_id": "run",
            "skill": "sample-skill",
            "config_path": "codex-evals.toml",
        },
    )
    case = sanity_case(
        task="Run direct.",
        definition_path=definition,
        fixture_dir=fixture,
    )
    case_result_value = run_case(
        repo_root=tmp_path,
        run_root=run_root,
        case=case,
        skill_dir=skill,
        rubric=False,
        eval_kind="sanity",
        sides=("with_skill",),
        backend=RecordingBackend(),
        config_path=config,
        run_configuration=metadata,
    )
    run = {
        "mode": "with_skill",
        "eval_kind": "sanity",
        "repo_root": tmp_path,
        "run_root": run_root,
        "skill": "sample-skill",
        "metadata": metadata,
        "results": [case_result_value],
    }
    return definition, config, run_root, run


def test_runtime_report_uses_runtime_template_only(tmp_path: Path):
    report = report_for_kind(tmp_path, "runtime")

    assert "| sample/service/sample-skill | sample/service | 1 |" in report
    assert "Sanity Checks" not in report
    assert "Rubric Checks" not in report
    assert "## Sanity Summary" not in report
    assert "## Rubric Summary" not in report
    assert "## Runtime Summary" in report
    assert "## Runtime Failures" in report
    assert "## Compose Evidence" in report
    assert "| with_skill | sample/service/sample-skill | sample/service | 1 | 100% (1/1) | 456 | 0 | 12.3s | - | - | - | - |" in report


def test_sanity_report_uses_sanity_template_only(tmp_path: Path):
    report = report_for_kind(tmp_path, "sanity")

    assert "Rubric Checks" not in report
    assert "Runtime Checks" not in report
    assert "## Sanity Summary" in report
    assert "## Sanity Failures" in report
    assert "## Rubric Summary" not in report
    assert "## Runtime Summary" not in report
    assert "| with_skill | sample/service/sample-skill | sample/service | 1 | 100% (1/1) | 456 | 0 | 12.3s | - | - | - | - |" in report


def test_rubric_report_uses_rubric_template_only(tmp_path: Path):
    report = report_for_kind(tmp_path, "rubric")

    assert "Sanity Checks" not in report
    assert "Runtime Checks" not in report
    assert "## Sanity Summary" not in report
    assert "## Rubric Summary" in report
    assert "## Rubric Failures" in report
    assert "## Runtime Summary" not in report
    assert "| with_skill | sample/service/sample-skill | sample/service | 1 | 100% (1/1), avg score 4 | 400 | 56 | 12.3s | - | - | - | - |" in report


def report_for_kind(tmp_path: Path, eval_kind: str) -> str:
    write_scope_definition(tmp_path, eval_kind)
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    sanity = GradeCheckResult(id="file", description="file", passed=True)
    runtime = GradeCheckResult(id="observer", description="observer", passed=True, category="runtime")
    rubric_path = (
        run_root
        / "cases/sample/service/direct/with_skill/rubric_grade.json"
    )
    rubric_path.parent.mkdir(parents=True)
    rubric_path.write_text(
        json.dumps({"overall_pass": True, "score": 4, "checks": [{"id": "quality", "pass": True, "evidence": "ok"}]}),
        encoding="utf-8",
    )
    side = side_result(
        "with_skill",
        GradeResult(checks=[sanity, runtime]),
        rubric_grade_path=str(rubric_path),
        duration_seconds=12.3,
        tokens=456,
        agent_tokens=400 if eval_kind == "rubric" else 456,
        rubric_tokens=56 if eval_kind == "rubric" else 0,
    )
    case = case_result(side, None)

    write_session_results(
        [
            {
                "mode": "with_skill",
                "eval_kind": eval_kind,
                "repo_root": tmp_path,
                "run_root": run_root,
                "skill": "sample-skill",
                "metadata": {
                    "mode": "with_skill",
                    "run_id": "run",
                    "skill": "sample-skill",
                    "agent_model": "gpt-test",
                    "eval_kind": eval_kind,
                    "rubric_enabled": eval_kind == "rubric",
                    "runtime_enabled": eval_kind == "runtime",
                },
                "results": [case],
            },
        ]
    )
    report_path, _ = render_reports_for_run_root(run_root, eval_kind)

    return report_path.read_text(encoding="utf-8")


def write_scope_definition(
    root: Path, kind: str, *, prompts: tuple[str, ...] = ("direct",)
) -> Path:
    role = "qual" if kind == "rubric" else kind
    path = root / f"evals/sample/service/eval/{role}/sample.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": "sample/service/sample-skill",
        "skill": "sample-skill",
        "prompts": [
            {"id": prompt, "task": f"Run {prompt}."}
            for prompt in prompts
        ],
    }
    if kind == "rubric":
        payload["rubric"] = ["The response is correct."]
    elif kind == "runtime":
        payload["checks"] = [
            runtime_check().model_dump(mode="json", exclude_none=True)
        ]
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    return path


def attach_run_provenance(
    run_root: Path,
    result: CaseResult,
    definition: Path,
    metadata: dict[str, object],
) -> None:
    side = result.with_skill
    assert side is not None
    artifact_dir = (
        run_root
        / "cases"
        / result.language
        / result.service
        / result.prompt_id
        / "with_skill"
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    trace_path = artifact_dir / "trace.jsonl"
    final_path = artifact_dir / "last_message.md"
    trace_path.write_text("", encoding="utf-8")
    final_path.write_text("done\n", encoding="utf-8")
    side.trace_path = str(trace_path)
    side.final_message_path = str(final_path)
    fixture = definition.parents[2]
    skill = definition.parents[5] / "skills" / result.skill
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text("name: sample-skill\n", encoding="utf-8")
    shared_references = skill.parent / "references"
    harness_source = Path(__file__).resolve().parents[1] / "src/pytest_codex_evals"
    current_definition = load_eval_definition(definition)
    prompt = next(
        prompt
        for prompt in current_definition.prompts
        if prompt.id == result.prompt_id
    )
    current_case = case_from_definition(
        current_definition,
        prompt,
        definition,
    )
    manifest = {
        "schema_version": 2,
        "case": {
            "id": result.id,
            "task": current_case.task,
            "task_sha256": case_task_sha256(current_case),
            "contract_sha256": case_contract_sha256(current_case),
        },
        "definition": {
            "path": str(definition.resolve()),
            "exists": True,
            "sha256": hashlib.sha256(definition.read_bytes()).hexdigest(),
        },
        "config": {"path": None, "exists": False, "sha256": None},
        "run_configuration": {
            "value": metadata,
            "sha256": hashlib.sha256(
                json.dumps(
                    metadata,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        },
        "fixture": {
            "path": str(fixture.resolve()),
            "tree_sha256": tree_sha256(fixture),
        },
        "skill": {
            "path": str(skill.resolve()),
            "tree_sha256": tree_sha256(skill),
        },
        "shared_references": {
            "path": str(shared_references.resolve()),
            "tree_sha256": None,
        },
        "harness": {
            "path": str(harness_source.resolve()),
            "tree_sha256": tree_sha256(harness_source),
        },
    }
    (artifact_dir / ".codex-eval-provenance.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def sanity_case(**overrides) -> SanityEvalCase:
    values = {
        "id": "sample/service/sample-skill/direct",
        "base_id": "sample/service/sample-skill",
        "prompt_id": "direct",
        "skill": "sample-skill",
        "language": "sample",
        "service": "service",
        "task": "Scan the service.",
        "fixture_dir": Path("fixture"),
        "checks": [],
    }
    values.update(overrides)
    return SanityEvalCase(**values)


def runtime_case() -> RuntimeEvalCase:
    return RuntimeEvalCase(
        id="sample/service/runtime/direct",
        base_id="sample/service/runtime",
        prompt_id="direct",
        skill="sample-skill",
        language="sample",
        service="service",
        task="Exercise runtime telemetry.",
        checks=[runtime_check()],
    )


def runtime_check() -> RuntimeCheck:
    return RuntimeCheck(
        id="observer-runtime",
        description="Runtime telemetry reaches Observer.",
        compose_file="docker-compose.yml",
        expect=RuntimeExpectations(
            endpoints=[
                EndpointExpectation(
                    id="traces",
                    url="/api/query/traces",
                    contains_any=["sample-service"],
                )
            ]
        ),
    )


def side_result(side: str, grade: GradeResult, **overrides) -> SideResult:
    values = {
        "side": side,
        "exit_code": 0,
        "trace_path": "trace.jsonl",
        "final_message_path": "last_message.md",
        "grade": grade,
    }
    values.update(overrides)
    return SideResult(**values)


def case_result(with_skill: SideResult | None, baseline: SideResult | None) -> CaseResult:
    return CaseResult(
        id="sample/service/sample-skill/direct",
        base_id="sample/service/sample-skill",
        prompt_id="direct",
        skill="sample-skill",
        language="sample",
        service="service",
        with_skill=with_skill,
        baseline=baseline,
    )


def test_backend_registry_creates_backends():
    from pytest_codex_evals.backends import (
        ClaudeBackend,
        CodexBackend,
        CursorBackend,
        create_backend,
    )

    codex = create_backend("codex")
    assert isinstance(codex, CodexBackend)
    assert codex.name == "codex"

    cursor = create_backend("cursor", command="/usr/bin/cursor")
    assert isinstance(cursor, CursorBackend)
    assert cursor.name == "cursor"
    assert cursor.command == "/usr/bin/cursor"

    claude = create_backend("claude", extra_args=["--verbose"])
    assert isinstance(claude, ClaudeBackend)
    assert claude.name == "claude"
    assert claude.extra_args == ["--verbose"]

    import pytest as _pytest
    with _pytest.raises(ValueError, match="unknown agent backend"):
        create_backend("unsupported")


def test_builtin_backends_parse_captured_trace_bytes_without_paths():
    from pytest_codex_evals.backends import (
        ClaudeBackend,
        CodexBackend,
        CursorBackend,
    )

    jsonl = (
        json.dumps(
            {"type": "turn.completed", "usage": {"total_tokens": 11}}
        )
        + "\n"
    ).encode("utf-8")
    for backend in (CodexBackend(), CursorBackend()):
        assert backend.parse_trace_bytes(jsonl).usage.total_tokens == 11

    claude = json.dumps(
        {"type": "result", "usage": {"input_tokens": 3, "output_tokens": 5}}
    ).encode("utf-8")
    assert ClaudeBackend().parse_trace_bytes(claude).usage.total_tokens == 8


def test_runtime_expectations_generic_endpoints():
    from pytest_codex_evals.definitions.runtime import EndpointExpectation

    expectations = RuntimeExpectations(
        service_name="my-api",
        service_port=8080,
        health_path="/health",
        clear_path=None,
        endpoints=[
            EndpointExpectation(
                id="users",
                url="/api/users",
                contains_all=["admin"],
                field_checks={"roles": ["admin", "editor"]},
            )
        ],
    )

    assert expectations.service_name == "my-api"
    assert expectations.service_port == 8080
    assert expectations.health_path == "/health"
    assert expectations.clear_path is None
    assert len(expectations.endpoints) == 1
    assert expectations.endpoints[0].id == "users"
    assert expectations.endpoints[0].url == "/api/users"


def test_run_case_passes_configured_agent_and_judge_timeouts(tmp_path: Path):
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    nested_scratch = fixture_dir / "config" / BACKEND_SCRATCH_DIRECTORY
    nested_scratch.mkdir(parents=True)
    (nested_scratch / "schema.json").write_text(
        '{"source": "fixture"}\n', encoding="utf-8"
    )
    definition_path = fixture_dir / "eval/qual/sample.json"
    definition_path.parent.mkdir(parents=True)
    definition_path.write_text(
        json.dumps(
            {
                "id": "sample/service/rubric",
                "skill": "sample-skill",
                "prompts": [{"id": "direct", "task": "Evaluate the answer."}],
                "rubric": ["Must pass."],
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "codex-evals.toml"
    config_path.write_text('[run]\nmode = "with_skill"\n', encoding="utf-8")
    skill_dir = tmp_path / "skills" / "sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("name: sample-skill\n", encoding="utf-8")
    case = RubricEvalCase(
        id="sample/service/rubric/direct",
        base_id="sample/service/rubric",
        prompt_id="direct",
        skill="sample-skill",
        language="sample",
        service="service",
        task="Evaluate the answer.",
        definition_path=definition_path,
        fixture_dir=fixture_dir,
        rubric=["Must pass."],
    )
    backend = RecordingBackend()

    run_case(
        repo_root=tmp_path,
        run_root=tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run",
        case=case,
        skill_dir=skill_dir,
        model="agent-model",
        judge_model="judge-model",
        rubric=True,
        sides=("with_skill",),
        backend=backend,
        agent_timeout=2400,
        judge_timeout=1200,
        config_path=config_path,
        run_configuration={"mode": "with_skill", "eval_kind": "rubric"},
    )

    assert backend.agent_timeouts == [2400]
    assert backend.judge_timeouts == [1200]

    provenance_path = (
        tmp_path
        / ".workspace/codex-evals/sample-skill/run"
        / "cases/sample/service/direct/with_skill/.codex-eval-provenance.json"
    )
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert provenance["case"]["task"] == "Evaluate the answer."
    assert provenance["case"]["skill"] == "sample-skill"
    assert len(provenance["case"]["task_sha256"]) == 64
    assert len(provenance["case"]["contract_sha256"]) == 64
    assert provenance["definition"]["sha256"] == hashlib.sha256(
        definition_path.read_bytes()
    ).hexdigest()
    assert provenance["config"]["sha256"] == hashlib.sha256(
        config_path.read_bytes()
    ).hexdigest()
    assert len(provenance["run_configuration"]["sha256"]) == 64
    assert len(provenance["fixture"]["tree_sha256"]) == 64
    assert len(provenance["skill"]["tree_sha256"]) == 64
    assert provenance["skill"]["staged_path"].endswith(
        "/.agents/skills/sample-skill/SKILL.md"
    )
    assert not (
        provenance_path.parent / "service/target/generated-output.bin"
    ).exists()
    assert not (provenance_path.parent / ".uv-cache").exists()
    assert not (provenance_path.parent / ".pip-cache").exists()
    assert not (provenance_path.parent / BACKEND_SCRATCH_DIRECTORY).exists()
    assert (
        provenance_path.parent
        / "service"
        / "config"
        / BACKEND_SCRATCH_DIRECTORY
        / "schema.json"
    ).read_text(encoding="utf-8") == '{"source": "fixture"}\n'


def test_execution_quarantine_allocates_distinct_slots_atomically(
    isolated_execution_quarantine: Path,
    monkeypatch,
):
    from pytest_codex_evals import runner as runner_module

    monkeypatch.setattr(
        runner_module, "EXECUTION_QUARANTINE_MAX_WORKSPACES", 2
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        allocations = list(
            executor.map(
                lambda _: runner_module.allocate_execution_workspace(), range(2)
            )
        )
    try:
        paths = {path for path, _anchor in allocations}
        assert paths == {
            isolated_execution_quarantine
            / "workspace-000000"
            / "execution",
            isolated_execution_quarantine
            / "workspace-000001"
            / "execution",
        }
        for path in paths:
            assert path.is_dir()
    finally:
        for _path, anchor in allocations:
            runner_module.close_anchored_directory(anchor)

    with pytest.raises(RuntimeError, match="retained workspace limit reached"):
        runner_module.allocate_execution_workspace()


def test_execution_quarantine_creates_private_default_root(
    tmp_path: Path,
    monkeypatch,
):
    from pytest_codex_evals import runner as runner_module

    monkeypatch.delenv("CODEX_EVAL_QUARANTINE_ROOT")
    monkeypatch.setattr(
        runner_module.tempfile, "gettempdir", lambda: str(tmp_path)
    )
    monkeypatch.setattr(
        runner_module, "_DEFAULT_EXECUTION_QUARANTINE_ROOT", None
    )

    workspace, anchor = runner_module.allocate_execution_workspace()
    runner_module.close_anchored_directory(anchor)

    quarantine = workspace.parents[1]
    assert quarantine.parent == tmp_path
    assert quarantine.name.startswith(
        runner_module.EXECUTION_QUARANTINE_DIRECTORY_PREFIX
    )
    assert workspace == quarantine / "workspace-000000" / "execution"
    assert quarantine.stat().st_mode & 0o777 == 0o700


def test_default_quarantine_capacity_is_scoped_to_one_process_invocation(
    tmp_path: Path,
    monkeypatch,
):
    from pytest_codex_evals import runner as runner_module

    monkeypatch.delenv("CODEX_EVAL_QUARANTINE_ROOT")
    monkeypatch.setattr(
        runner_module.tempfile, "gettempdir", lambda: str(tmp_path)
    )
    monkeypatch.setattr(
        runner_module, "EXECUTION_QUARANTINE_MAX_WORKSPACES", 1
    )
    monkeypatch.setattr(
        runner_module, "_DEFAULT_EXECUTION_QUARANTINE_ROOT", None
    )

    first_workspace, first_anchor = runner_module.allocate_execution_workspace()
    runner_module.close_anchored_directory(first_anchor)
    with pytest.raises(RuntimeError, match="retained workspace limit reached"):
        runner_module.allocate_execution_workspace()

    # A fresh harness process starts with no module-local root. Simulate that
    # process boundary without removing the retained first root.
    monkeypatch.setattr(
        runner_module, "_DEFAULT_EXECUTION_QUARANTINE_ROOT", None
    )
    second_workspace, second_anchor = runner_module.allocate_execution_workspace()
    runner_module.close_anchored_directory(second_anchor)

    assert first_workspace.parents[1] != second_workspace.parents[1]
    assert first_workspace.name == second_workspace.name == "execution"
    assert first_workspace.parent.name == second_workspace.parent.name == (
        "workspace-000000"
    )
    assert first_workspace.parents[1].is_dir()
    assert second_workspace.parents[1].is_dir()


def test_execution_quarantine_rejects_unexpected_entries_before_allocation(
    isolated_execution_quarantine: Path,
):
    from pytest_codex_evals import runner as runner_module

    (isolated_execution_quarantine / "renamed-workspace").mkdir(mode=0o700)

    with pytest.raises(ValueError, match="contains unexpected entries"):
        runner_module.allocate_execution_workspace()

    assert not (
        isolated_execution_quarantine / "workspace-000000"
    ).exists()


def test_run_case_refuses_full_quarantine_before_backend(
    tmp_path: Path,
    isolated_execution_quarantine: Path,
    monkeypatch,
):
    from pytest_codex_evals import runner as runner_module

    monkeypatch.setattr(
        runner_module, "EXECUTION_QUARANTINE_MAX_WORKSPACES", 1
    )
    (isolated_execution_quarantine / "workspace-000000").mkdir(mode=0o700)
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "name: sample-skill\n", encoding="utf-8"
    )
    backend = RecordingBackend()

    with pytest.raises(RuntimeError, match="refusing to start the agent backend"):
        run_case(
            repo_root=tmp_path,
            run_root=tmp_path / ".workspace/codex-evals/sample-skill/run",
            case=sanity_case(fixture_dir=fixture_dir),
            skill_dir=skill_dir,
            rubric=False,
            sides=("with_skill",),
            backend=backend,
        )

    assert backend.agent_timeouts == []


def test_run_case_uses_portable_filesystem_fallback_when_dir_fd_is_unavailable(
    tmp_path: Path,
    monkeypatch,
):
    from pytest_codex_evals import backends as backends_module
    from pytest_codex_evals import runner as runner_module

    monkeypatch.setattr(
        backends_module, "descriptor_operations_supported", lambda: False
    )
    monkeypatch.setattr(
        runner_module, "descriptor_operations_supported", lambda: False
    )

    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    (fixture_dir / "README.md").write_text("fixture\n", encoding="utf-8")
    nested_scratch = fixture_dir / "config" / BACKEND_SCRATCH_DIRECTORY
    nested_scratch.mkdir(parents=True)
    (nested_scratch / "schema.json").write_text(
        '{"source": "fixture"}\n', encoding="utf-8"
    )
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "name: sample-skill\n", encoding="utf-8"
    )
    run_root = tmp_path / ".workspace/codex-evals/sample-skill/portable"

    result = run_case(
        repo_root=tmp_path,
        run_root=run_root,
        case=sanity_case(fixture_dir=fixture_dir),
        skill_dir=skill_dir,
        rubric=False,
        sides=("with_skill",),
        backend=RecordingBackend(),
    )

    assert result.with_skill is not None
    artifact = run_root / "cases/sample/service/direct/with_skill"
    assert (artifact / "last_message.md").read_text(encoding="utf-8") == "done"
    assert (artifact / ".codex-eval-provenance.json").is_file()
    assert not (artifact / "service/target").exists()
    assert (
        artifact
        / "service"
        / "config"
        / BACKEND_SCRATCH_DIRECTORY
        / "schema.json"
    ).read_text(encoding="utf-8") == '{"source": "fixture"}\n'


def test_harness_owned_outputs_replace_agent_planted_symlinks(tmp_path: Path):
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("name: sample-skill\n", encoding="utf-8")
    outside = {
        name: tmp_path / f"outside-{name}.txt"
        for name in ("grade", "provenance", "summary")
    }
    for path in outside.values():
        path.write_text("sentinel\n", encoding="utf-8")
    run_root = tmp_path / ".workspace/codex-evals/sample-skill/run"

    run_case(
        repo_root=tmp_path,
        run_root=run_root,
        case=sanity_case(fixture_dir=fixture_dir),
        skill_dir=skill_dir,
        rubric=False,
        sides=("with_skill",),
        backend=SymlinkPlantingBackend(outside),
    )

    artifact_dir = run_root / "cases/sample/service/direct/with_skill"
    for path in outside.values():
        assert path.read_text(encoding="utf-8") == "sentinel\n"
    for name in ("grade.json", ".codex-eval-provenance.json", "summary.json"):
        path = artifact_dir / name
        assert path.is_file()
        assert not path.is_symlink()


def test_run_case_rejects_backend_execution_directory_swap(tmp_path: Path):
    import pytest as _pytest

    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("name: sample-skill\n", encoding="utf-8")
    outside = tmp_path / "outside"

    with _pytest.raises(ValueError, match="execution directory was replaced"):
        run_case(
            repo_root=tmp_path,
            run_root=tmp_path / ".workspace/codex-evals/sample-skill/run",
            case=sanity_case(fixture_dir=fixture_dir),
            skill_dir=skill_dir,
            rubric=False,
            sides=("with_skill",),
            backend=ExecutionDirectorySwapBackend(outside),
        )

    for name in ("grade.json", ".codex-eval-provenance.json", "summary.json"):
        assert (outside / "stolen-exec" / name).read_text(encoding="utf-8") == (
            "sentinel\n"
        )


def test_run_case_cleanup_does_not_delete_replacement_victim(
    tmp_path: Path,
    isolated_execution_quarantine: Path,
):
    import pytest as _pytest

    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("name: sample-skill\n", encoding="utf-8")
    backend = ExecutionRootVictimSwapBackend(tmp_path / "outside")

    with _pytest.raises(ValueError, match="execution directory was replaced"):
        run_case(
            repo_root=tmp_path,
            run_root=tmp_path / ".workspace/codex-evals/sample-skill/run",
            case=sanity_case(fixture_dir=fixture_dir),
            skill_dir=skill_dir,
            rubric=False,
            sides=("with_skill",),
            backend=backend,
        )

    assert backend.replaced_root is not None
    assert (backend.replaced_root / "sentinel.txt").read_text(encoding="utf-8") == (
        "keep\n"
    )
    # Moving the nested execution root does not free its retained reservation.
    assert (
        isolated_execution_quarantine / "workspace-000000"
    ).is_dir()
    shutil.rmtree(backend.replaced_root)
    assert backend.stolen_root is not None
    shutil.rmtree(backend.stolen_root)


def test_run_case_rejects_execution_root_swap_between_sides(
    tmp_path: Path,
    monkeypatch,
):
    import pytest as _pytest
    from pytest_codex_evals import runner as runner_module

    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "name: sample-skill\n", encoding="utf-8"
    )
    real_run_side = runner_module.run_side
    swapped_root: Path | None = None
    stolen_root: Path | None = None

    def run_side_then_swap(**kwargs):
        nonlocal swapped_root, stolen_root
        result = real_run_side(**kwargs)
        if kwargs["side"] == "with_skill":
            swapped_root = kwargs["exec_dir"].parent
            stolen_root = tmp_path / "stolen-case-root"
            swapped_root.rename(stolen_root)
            swapped_root.mkdir()
            (swapped_root / "sentinel.txt").write_text(
                "keep\n", encoding="utf-8"
            )
        return result

    monkeypatch.setattr(runner_module, "run_side", run_side_then_swap)

    with _pytest.raises(
        ValueError, match="execution root was replaced between sides"
    ):
        run_case(
            repo_root=tmp_path,
            run_root=tmp_path / ".workspace/codex-evals/sample-skill/run",
            case=sanity_case(fixture_dir=fixture_dir),
            skill_dir=skill_dir,
            rubric=False,
            sides=("with_skill", "baseline"),
            backend=RecordingBackend(),
        )

    assert swapped_root is not None
    assert (swapped_root / "sentinel.txt").read_text(encoding="utf-8") == (
        "keep\n"
    )
    assert stolen_root is not None
    shutil.rmtree(swapped_root)
    shutil.rmtree(stolen_root)


def test_run_case_does_not_delete_artifact_directory_planted_by_agent(
    tmp_path: Path,
):
    import pytest as _pytest

    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "name: sample-skill\n", encoding="utf-8"
    )
    run_root = tmp_path / ".workspace/codex-evals/sample-skill/run"
    artifact_dir = (
        run_root / "cases/sample/service/direct/with_skill"
    )
    victim = tmp_path / "victim"
    backend = ArtifactDirectoryPlantingBackend(victim, artifact_dir)

    with _pytest.raises(ValueError, match="appeared during agent execution"):
        run_case(
            repo_root=tmp_path,
            run_root=run_root,
            case=sanity_case(fixture_dir=fixture_dir),
            skill_dir=skill_dir,
            rubric=False,
            sides=("with_skill",),
            backend=backend,
        )

    assert (artifact_dir / "sentinel.txt").read_text(encoding="utf-8") == (
        "keep\n"
    )
    shutil.rmtree(artifact_dir)


def test_run_case_refuses_stale_artifact_without_deleting_it(tmp_path: Path):
    import pytest as _pytest

    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "name: sample-skill\n", encoding="utf-8"
    )
    run_root = tmp_path / ".workspace/codex-evals/sample-skill/run"
    artifact_dir = run_root / "cases/sample/service/direct/with_skill"
    artifact_dir.mkdir(parents=True)
    sentinel = artifact_dir / "sentinel.txt"
    sentinel.write_text("keep\n", encoding="utf-8")

    with _pytest.raises(ValueError, match="refusing to replace"):
        run_case(
            repo_root=tmp_path,
            run_root=run_root,
            case=sanity_case(fixture_dir=fixture_dir),
            skill_dir=skill_dir,
            rubric=False,
            sides=("with_skill",),
            backend=RecordingBackend(),
        )

    assert sentinel.read_text(encoding="utf-8") == "keep\n"


def test_run_case_rejects_replacement_trace_and_final_bytes(tmp_path: Path):
    import pytest as _pytest

    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "name: sample-skill\n", encoding="utf-8"
    )
    backend = OutputReadReplacementBackend(tmp_path / "outside")

    with _pytest.raises(ValueError, match="replaced during agent output read"):
        run_case(
            repo_root=tmp_path,
            run_root=tmp_path / ".workspace/codex-evals/sample-skill/run",
            case=sanity_case(fixture_dir=fixture_dir),
            skill_dir=skill_dir,
            rubric=False,
            sides=("with_skill",),
            backend=backend,
        )

    assert backend.replacement is not None
    assert (backend.replacement / "last_message.md").read_text(
        encoding="utf-8"
    ) == "FORGED\n"


def test_run_case_copies_retained_source_not_replacement_tree(tmp_path: Path):
    import pytest as _pytest
    from unittest.mock import patch
    from pytest_codex_evals import runner as runner_module

    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "name: sample-skill\n", encoding="utf-8"
    )
    backend = TrackingBackend()
    run_root = tmp_path / ".workspace/codex-evals/sample-skill/run"
    artifact_dir = run_root / "cases/sample/service/direct/with_skill"
    original_copy = runner_module.copy_artifact_tree_fd
    swapped = False
    stolen = tmp_path / "stolen-exec"

    def swap_then_copy(source_descriptor: int, destination_descriptor: int, **kwargs):
        nonlocal swapped
        if not swapped:
            assert backend.exec_dir is not None
            backend.exec_dir.rename(stolen)
            backend.exec_dir.mkdir()
            (backend.exec_dir / "trace.jsonl").write_text(
                "FORGED\n", encoding="utf-8"
            )
            (backend.exec_dir / ".codex-eval-provenance.json").write_text(
                "FORGED\n", encoding="utf-8"
            )
            swapped = True
        return original_copy(
            source_descriptor, destination_descriptor, **kwargs
        )

    with patch.object(
        runner_module, "copy_artifact_tree_fd", side_effect=swap_then_copy
    ):
        with _pytest.raises(ValueError, match="replaced during capture"):
            run_case(
                repo_root=tmp_path,
                run_root=run_root,
                case=sanity_case(fixture_dir=fixture_dir),
                skill_dir=skill_dir,
                rubric=False,
                sides=("with_skill",),
                backend=backend,
            )

    assert (artifact_dir / "trace.jsonl").read_text(encoding="utf-8") != (
        "FORGED\n"
    )
    assert json.loads(
        (artifact_dir / ".codex-eval-provenance.json").read_text(
            encoding="utf-8"
        )
    )["schema_version"] == 2


def test_run_case_never_copies_through_swapped_artifact_parent(
    tmp_path: Path,
):
    import pytest as _pytest
    from unittest.mock import patch
    from pytest_codex_evals import runner as runner_module

    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "name: sample-skill\n", encoding="utf-8"
    )
    run_root = tmp_path / ".workspace/codex-evals/sample-skill/run"
    artifact_parent = run_root / "cases/sample/service/direct"
    outside = tmp_path / "outside-artifacts"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep\n", encoding="utf-8")
    stolen = tmp_path / "stolen-artifact-parent"
    original_copy = runner_module.copy_artifact_tree_fd
    swapped = False

    def swap_then_copy(source_descriptor: int, destination_descriptor: int, **kwargs):
        nonlocal swapped
        if not swapped:
            artifact_parent.rename(stolen)
            artifact_parent.symlink_to(outside, target_is_directory=True)
            swapped = True
        return original_copy(
            source_descriptor, destination_descriptor, **kwargs
        )

    with patch.object(
        runner_module, "copy_artifact_tree_fd", side_effect=swap_then_copy
    ):
        with _pytest.raises(ValueError, match="artifact directory was replaced"):
            run_case(
                repo_root=tmp_path,
                run_root=run_root,
                case=sanity_case(fixture_dir=fixture_dir),
                skill_dir=skill_dir,
                rubric=False,
                sides=("with_skill",),
                backend=RecordingBackend(),
            )

    assert sentinel.read_text(encoding="utf-8") == "keep\n"
    assert not (outside / "with_skill").exists()
    assert (stolen / "with_skill/trace.jsonl").is_file()


def test_prepare_side_workspace_copies_only_explicit_eval_inputs(
    tmp_path: Path,
    monkeypatch,
):
    from pytest_codex_evals import runner as runner_module

    def fail_cleanup_sensitive_snapshot(*_args, **_kwargs):
        raise AssertionError("workspace preparation must not use TemporaryDirectory")

    monkeypatch.setattr(
        runner_module.tempfile,
        "TemporaryDirectory",
        fail_cleanup_sensitive_snapshot,
    )
    fixture_dir = tmp_path / "fixture"
    (fixture_dir / "eval/inputs").mkdir(parents=True)
    (fixture_dir / "eval/qual").mkdir(parents=True)
    (fixture_dir / "internal/eval").mkdir(parents=True)
    (fixture_dir / "target/classes").mkdir(parents=True)
    (fixture_dir / ".observe").mkdir()
    (fixture_dir / "main.go").write_text("package main\n", encoding="utf-8")
    (fixture_dir / "eval/inputs/otel-audit.json").write_text(
        '{"kind":"otel-audit"}\n', encoding="utf-8"
    )
    (fixture_dir / "eval/qual/audit.json").write_text("{}\n", encoding="utf-8")
    (fixture_dir / "internal/eval/runtime.go").write_text(
        "package eval\n", encoding="utf-8"
    )
    (fixture_dir / "target/classes/App.class").write_bytes(b"compiled")
    (fixture_dir / ".observe/stale.json").write_text("{}\n", encoding="utf-8")
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("name: sample-skill\n", encoding="utf-8")
    case = sanity_case(
        fixture_dir=fixture_dir,
        eval_inputs=["eval/inputs/otel-audit.json"],
    )
    side_dir = tmp_path / "run"

    snapshot = prepare_side_workspace(
        tmp_path, case, "with_skill", side_dir, skill_dir
    )

    service = side_dir / "service"
    assert (service / "main.go").is_file()
    assert (service / "eval/inputs/otel-audit.json").is_file()
    assert not (service / "eval/qual").exists()
    assert (service / "internal/eval/runtime.go").is_file()
    assert not (service / "target").exists()
    assert not (service / ".observe").exists()
    assert snapshot.staged_skill_path == str(
        side_dir / ".agents/skills/sample-skill/SKILL.md"
    )

    baseline_dir = tmp_path / "baseline"
    baseline_snapshot = prepare_side_workspace(
        tmp_path, case, "baseline", baseline_dir, skill_dir
    )
    assert baseline_snapshot.staged_skill_path is None
    assert not (baseline_dir / ".agents").exists()


def test_prepare_side_workspace_honors_prompt_eval_input_allowlist(
    tmp_path: Path,
):
    fixture_dir = tmp_path / "fixture"
    inputs = fixture_dir / "eval/inputs"
    inputs.mkdir(parents=True)
    (fixture_dir / "main.go").write_text("package main\n", encoding="utf-8")
    (inputs / "otel-audit.json").write_text("{}\n", encoding="utf-8")
    (inputs / "otel-verify.json").write_text("{}\n", encoding="utf-8")
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "name: sample-skill\n", encoding="utf-8"
    )
    case = sanity_case(
        fixture_dir=fixture_dir,
        eval_inputs=["eval/inputs/otel-audit.json"],
    )

    prepare_side_workspace(
        tmp_path, case, "with_skill", tmp_path / "run", skill_dir
    )

    service = tmp_path / "run/service"
    assert (service / "main.go").is_file()
    assert (service / "eval/inputs/otel-audit.json").is_file()
    assert not (service / "eval/inputs/otel-verify.json").exists()


def test_prepare_side_workspace_omits_unapproved_eval_inputs(tmp_path: Path):
    fixture_dir = tmp_path / "fixture"
    inputs = fixture_dir / "eval/inputs"
    inputs.mkdir(parents=True)
    (fixture_dir / "main.go").write_text("package main\n", encoding="utf-8")
    (inputs / "otel-audit.json").write_text("{}\n", encoding="utf-8")
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "name: sample-skill\n", encoding="utf-8"
    )

    prepare_side_workspace(
        tmp_path,
        sanity_case(fixture_dir=fixture_dir),
        "baseline",
        tmp_path / "run",
        skill_dir,
    )

    service = tmp_path / "run/service"
    assert (service / "main.go").is_file()
    assert not (service / "eval").exists()


def test_prepare_side_workspace_rejects_missing_allowlisted_eval_input(
    tmp_path: Path,
):
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "name: sample-skill\n", encoding="utf-8"
    )
    case = sanity_case(
        fixture_dir=fixture_dir,
        eval_inputs=["eval/inputs/missing.json"],
    )

    with pytest.raises(ValueError, match="must name fixture files"):
        prepare_side_workspace(
            tmp_path, case, "with_skill", tmp_path / "run", skill_dir
        )


def test_prepare_side_workspace_stages_authenticated_instrument_companion(
    tmp_path: Path,
):
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    skills = tmp_path / "skills"
    instrument = skills / "otel-instrument"
    verify = skills / "otel-verify"
    instrument.mkdir(parents=True)
    verify.mkdir()
    (instrument / "SKILL.md").write_text(
        "name: otel-instrument\n", encoding="utf-8"
    )
    (verify / "SKILL.md").write_text(
        "name: otel-verify\n", encoding="utf-8"
    )
    (verify / "contract.md").write_text("verify-v1\n", encoding="utf-8")
    case = sanity_case(
        skill="otel-instrument",
        fixture_dir=fixture_dir,
    )

    loaded = prepare_side_workspace(
        tmp_path, case, "with_skill", tmp_path / "loaded", instrument
    )
    loaded_provenance = build_run_provenance(
        tmp_path, case, instrument, input_snapshot=loaded
    )

    staged_verify = tmp_path / "loaded/.agents/skills/otel-verify"
    assert (staged_verify / "SKILL.md").is_file()
    assert (staged_verify / "contract.md").read_text(
        encoding="utf-8"
    ) == "verify-v1\n"
    assert len(loaded.companion_skills) == 1
    companion = loaded_provenance["companion_skills"][0]
    assert companion["name"] == "otel-verify"
    assert companion["tree_sha256"] == tree_sha256(verify)
    assert companion["staged_path"] == str(staged_verify / "SKILL.md")

    baseline = prepare_side_workspace(
        tmp_path, case, "baseline", tmp_path / "baseline", instrument
    )
    baseline_provenance = build_run_provenance(
        tmp_path, case, instrument, input_snapshot=baseline
    )
    assert not (tmp_path / "baseline/.agents").exists()
    assert baseline_provenance["companion_skills"][0]["tree_sha256"] == (
        companion["tree_sha256"]
    )
    assert baseline_provenance["companion_skills"][0]["staged_path"] is None


def test_prepare_side_workspace_stages_configure_dashboard_support_tree(
    tmp_path: Path,
):
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    skills = tmp_path / "skills"
    configure = skills / "splunk-configure"
    dashboard = skills / "splunk-dashboard"
    configure.mkdir(parents=True)
    dashboard.mkdir()
    (configure / "SKILL.md").write_text(
        "name: splunk-configure\n", encoding="utf-8"
    )
    (dashboard / "SKILL.md").write_text(
        "name: splunk-dashboard\n", encoding="utf-8"
    )
    (dashboard / "validator.py").write_text("pass\n", encoding="utf-8")
    case = sanity_case(
        skill="splunk-configure",
        fixture_dir=fixture_dir,
    )

    loaded = prepare_side_workspace(
        tmp_path, case, "with_skill", tmp_path / "loaded", configure
    )

    staged = tmp_path / "loaded/.agents/skills/splunk-dashboard"
    assert (staged / "SKILL.md").is_file()
    assert (staged / "validator.py").read_text(encoding="utf-8") == "pass\n"
    assert [item.name for item in loaded.companion_skills] == ["splunk-dashboard"]
    assert loaded.companion_skills[0].tree_sha256 == tree_sha256(dashboard)


def test_report_authenticates_instrument_companion_tree(tmp_path: Path):
    skills = tmp_path / "skills"
    instrument = skills / "otel-instrument"
    verify = skills / "otel-verify"
    instrument.mkdir(parents=True)
    verify.mkdir()
    (instrument / "SKILL.md").write_text(
        "name: otel-instrument\n", encoding="utf-8"
    )
    verify_skill = verify / "SKILL.md"
    verify_skill.write_text("name: otel-verify\n", encoding="utf-8")
    record = {
        "name": "otel-verify",
        "path": str(verify),
        "tree_sha256": tree_sha256(verify),
        "staged_path": str(
            tmp_path / "run/.agents/skills/otel-verify/SKILL.md"
        ),
    }

    assert verify_companion_skills(
        [record],
        "otel-instrument",
        instrument,
        "test provenance",
        staged=True,
    ) == []

    verify_skill.write_text(
        "name: otel-verify\nchanged: true\n", encoding="utf-8"
    )
    errors = verify_companion_skills(
        [record],
        "otel-instrument",
        instrument,
        "test provenance",
        staged=True,
    )
    assert errors == [
        "test provenance companion skill otel-verify changed after capture"
    ]


def test_prepare_side_workspace_rejects_symlinked_eval_input(tmp_path: Path):
    fixture_dir = tmp_path / "fixture"
    (fixture_dir / "eval/inputs").mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    (fixture_dir / "eval/inputs/otel-audit.json").symlink_to(outside)
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("name: sample-skill\n", encoding="utf-8")
    case = sanity_case(fixture_dir=fixture_dir)

    import pytest as _pytest

    with _pytest.raises(ValueError, match="must not contain symlinks"):
        prepare_side_workspace(
            tmp_path, case, "with_skill", tmp_path / "run", skill_dir
        )


def test_prepare_side_workspace_rejects_symlink_anywhere_in_fixture(
    tmp_path: Path,
):
    fixture_dir = tmp_path / "fixture"
    (fixture_dir / "config").mkdir(parents=True)
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("first secret\n", encoding="utf-8")
    (fixture_dir / "config/secret.txt").symlink_to(outside)
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "name: sample-skill\n", encoding="utf-8"
    )
    case = sanity_case(fixture_dir=fixture_dir)

    import pytest as _pytest

    with _pytest.raises(
        ValueError, match="provenance source tree must not contain symlinks"
    ):
        tree_sha256(fixture_dir)

    with _pytest.raises(ValueError, match="fixture must not contain symlinks"):
        prepare_side_workspace(
            tmp_path, case, "with_skill", tmp_path / "run", skill_dir
        )

    outside.write_text("changed secret\n", encoding="utf-8")
    with _pytest.raises(
        ValueError, match="provenance source tree must not contain symlinks"
    ):
        tree_sha256(fixture_dir)
    with _pytest.raises(ValueError, match="fixture must not contain symlinks"):
        prepare_side_workspace(
            tmp_path, case, "with_skill", tmp_path / "run", skill_dir
        )


def test_run_case_seals_snapshot_bytes_when_sources_change_between_copy_and_hash(
    tmp_path: Path, monkeypatch
):
    from pytest_codex_evals import runner as runner_module

    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    fixture_file = fixture_dir / "main.txt"
    fixture_file.write_text("fixture-old\n", encoding="utf-8")
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("skill-old\n", encoding="utf-8")
    references_dir = tmp_path / "skills/references"
    references_dir.mkdir()
    reference_file = references_dir / "contract.md"
    reference_file.write_text("reference-old\n", encoding="utf-8")
    expected_hashes = {
        "fixture": tree_sha256(fixture_dir),
        "skill": tree_sha256(skill_dir),
        "references": tree_sha256(references_dir),
    }
    original_capture_source_tree = runner_module.capture_source_tree
    mutated: set[str] = set()

    def capture_then_mutate_source(path: Path):
        path = Path(path)
        snapshot = original_capture_source_tree(path)
        if path == fixture_dir and "fixture" not in mutated:
            fixture_file.write_text("fixture-new\n", encoding="utf-8")
            mutated.add("fixture")
        elif path == skill_dir and "skill" not in mutated:
            skill_file.write_text("skill-new\n", encoding="utf-8")
            mutated.add("skill")
        elif path == references_dir and "references" not in mutated:
            reference_file.write_text("reference-new\n", encoding="utf-8")
            mutated.add("references")
        return snapshot

    monkeypatch.setattr(
        runner_module, "capture_source_tree", capture_then_mutate_source
    )
    backend = SnapshotObservingBackend()
    run_root = tmp_path / ".workspace/codex-evals/sample-skill/run"

    run_case(
        repo_root=tmp_path,
        run_root=run_root,
        case=sanity_case(fixture_dir=fixture_dir),
        skill_dir=skill_dir,
        rubric=False,
        sides=("with_skill",),
        backend=backend,
    )

    assert mutated == {"fixture", "skill", "references"}
    assert backend.observed == {
        "fixture": "fixture-old\n",
        "skill": "skill-old\n",
        "references": "reference-old\n",
    }
    provenance = json.loads(
        (
            run_root
            / "cases/sample/service/direct/with_skill/.codex-eval-provenance.json"
        ).read_text(encoding="utf-8")
    )
    assert provenance["fixture"]["tree_sha256"] == expected_hashes["fixture"]
    assert provenance["skill"]["tree_sha256"] == expected_hashes["skill"]
    assert (
        provenance["shared_references"]["tree_sha256"]
        == expected_hashes["references"]
    )


def test_run_case_reads_snapshots_when_sources_change_after_hash_before_agent(
    tmp_path: Path,
):
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    fixture_file = fixture_dir / "main.txt"
    fixture_file.write_text("fixture-old\n", encoding="utf-8")
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("skill-old\n", encoding="utf-8")
    references_dir = tmp_path / "skills/references"
    references_dir.mkdir()
    reference_file = references_dir / "contract.md"
    reference_file.write_text("reference-old\n", encoding="utf-8")
    expected_hashes = {
        "fixture": tree_sha256(fixture_dir),
        "skill": tree_sha256(skill_dir),
        "references": tree_sha256(references_dir),
    }

    def mutate_sources() -> None:
        fixture_file.write_text("fixture-new\n", encoding="utf-8")
        skill_file.write_text("skill-new\n", encoding="utf-8")
        reference_file.write_text("reference-new\n", encoding="utf-8")

    backend = SnapshotObservingBackend(mutate_sources)
    run_root = tmp_path / ".workspace/codex-evals/sample-skill/run"
    run_case(
        repo_root=tmp_path,
        run_root=run_root,
        case=sanity_case(fixture_dir=fixture_dir),
        skill_dir=skill_dir,
        rubric=False,
        sides=("with_skill",),
        backend=backend,
    )

    assert backend.observed == {
        "fixture": "fixture-old\n",
        "skill": "skill-old\n",
        "references": "reference-old\n",
    }
    provenance = json.loads(
        (
            run_root
            / "cases/sample/service/direct/with_skill/.codex-eval-provenance.json"
        ).read_text(encoding="utf-8")
    )
    assert provenance["fixture"]["tree_sha256"] == expected_hashes["fixture"]
    assert provenance["skill"]["tree_sha256"] == expected_hashes["skill"]
    assert (
        provenance["shared_references"]["tree_sha256"]
        == expected_hashes["references"]
    )


def test_run_case_rejects_definition_changed_after_case_collection(
    tmp_path: Path,
):
    import pytest as _pytest

    definition_path = write_scope_definition(tmp_path, "sanity")
    definition = load_eval_definition(definition_path)
    case = case_from_definition(
        definition,
        definition.prompts[0],
        definition_path,
    )
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "name: sample-skill\n",
        encoding="utf-8",
    )
    changed = json.loads(definition_path.read_text(encoding="utf-8"))
    changed["prompts"][0]["task"] = "Run changed contract."
    definition_path.write_text(json.dumps(changed), encoding="utf-8")
    backend = RecordingBackend()
    run_root = tmp_path / ".workspace/codex-evals/sample-skill/run"

    with _pytest.raises(
        ValueError,
        match="eval definition changed after case collection",
    ):
        run_case(
            repo_root=tmp_path,
            run_root=run_root,
            case=case,
            skill_dir=skill_dir,
            rubric=False,
            sides=("with_skill",),
            backend=backend,
        )

    assert backend.agent_timeouts == []
    assert not run_root.exists()


def test_run_case_rejects_task_changed_after_case_collection(
    tmp_path: Path,
):
    import pytest as _pytest

    definition_path = write_scope_definition(tmp_path, "sanity")
    definition = load_eval_definition(definition_path)
    case = case_from_definition(
        definition,
        definition.prompts[0],
        definition_path,
    )
    case.task = "Run a task that is not in the collected definition."
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "name: sample-skill\n",
        encoding="utf-8",
    )
    backend = RecordingBackend()
    run_root = tmp_path / ".workspace/codex-evals/sample-skill/run"

    with _pytest.raises(
        ValueError,
        match="eval case contract changed after collection",
    ):
        run_case(
            repo_root=tmp_path,
            run_root=run_root,
            case=case,
            skill_dir=skill_dir,
            rubric=False,
            sides=("with_skill",),
            backend=backend,
        )

    assert backend.agent_timeouts == []
    assert not run_root.exists()


def test_run_case_rejects_nested_contract_changed_after_collection(
    tmp_path: Path,
):
    import pytest as _pytest

    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "name: sample-skill\n",
        encoding="utf-8",
    )

    for kind in ("rubric", "runtime"):
        definition_path = write_scope_definition(tmp_path, kind)
        definition = load_eval_definition(definition_path)
        case = case_from_definition(
            definition,
            definition.prompts[0],
            definition_path,
        )
        if isinstance(case, RubricEvalCase):
            case.rubric.append("A requirement added after collection.")
        elif isinstance(case, RuntimeEvalCase):
            case.checks[0].expect.service_port += 1
        else:  # pragma: no cover - guarded by the test inputs
            raise AssertionError(f"unexpected case type: {type(case).__name__}")
        backend = RecordingBackend()
        run_root = (
            tmp_path / f".workspace/codex-evals/sample-skill/{kind}-run"
        )

        with _pytest.raises(
            ValueError,
            match="eval case contract changed after collection",
        ):
            run_case(
                repo_root=tmp_path,
                run_root=run_root,
                case=case,
                skill_dir=skill_dir,
                rubric=False,
                sides=("with_skill",),
                backend=backend,
            )

        assert backend.agent_timeouts == []
        assert not run_root.exists()


def test_run_case_rechecks_definition_in_fixture_snapshot_before_agent(
    tmp_path: Path,
    monkeypatch,
):
    import pytest as _pytest
    from pytest_codex_evals import runner as runner_module

    definition_path = write_scope_definition(tmp_path, "sanity")
    definition = load_eval_definition(definition_path)
    case = case_from_definition(
        definition,
        definition.prompts[0],
        definition_path,
    )
    skill_dir = tmp_path / "skills/sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "name: sample-skill\n",
        encoding="utf-8",
    )
    backend = RecordingBackend()
    original_prepare = runner_module.prepare_side_workspace
    mutated = False

    def mutate_definition_then_prepare(*args, **kwargs):
        nonlocal mutated
        if not mutated:
            changed = json.loads(
                definition_path.read_text(encoding="utf-8")
            )
            changed["prompts"][0]["task"] = "Run changed contract."
            definition_path.write_text(json.dumps(changed), encoding="utf-8")
            mutated = True
        return original_prepare(*args, **kwargs)

    monkeypatch.setattr(
        runner_module,
        "prepare_side_workspace",
        mutate_definition_then_prepare,
    )

    with _pytest.raises(
        ValueError,
        match="eval definition changed after case collection",
    ):
        run_case(
            repo_root=tmp_path,
            run_root=tmp_path / ".workspace/codex-evals/sample-skill/run",
            case=case,
            skill_dir=skill_dir,
            rubric=False,
            sides=("with_skill",),
            backend=backend,
        )

    assert mutated
    assert backend.agent_timeouts == []


def write_loaded_skill(root: Path, skill: str) -> None:
    skill_dir = root / ".agents" / "skills" / skill
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"name: {skill}\n", encoding="utf-8")


def loaded_skill_trace(root: Path, skill: str) -> TraceSummary:
    path = root / ".agents" / "skills" / skill / "SKILL.md"
    return TraceSummary(
        [
            {
                "item": {
                    "type": "command_execution",
                    "command": f"cat .agents/skills/{skill}/SKILL.md",
                    "status": "completed",
                    "exit_code": 0,
                    "aggregated_output": path.read_text(encoding="utf-8"),
                }
            }
        ],
        "",
    )


def empty_trace(tmp_path: Path) -> Path:
    path = tmp_path / "trace.jsonl"
    path.write_text("", encoding="utf-8")
    return path


class RecordingBackend:
    name = "recording"

    def __init__(self) -> None:
        self.agent_timeouts: list[int] = []
        self.judge_timeouts: list[int] = []

    def run_agent(self, *, prompt: str, exec_dir: Path, model: str | None = None, timeout: int = 1200) -> AgentResult:
        self.agent_timeouts.append(timeout)
        scratch = exec_dir / BACKEND_SCRATCH_DIRECTORY
        scratch.mkdir(exist_ok=True)
        (scratch / ".codex-final-random.tmp").write_text(
            "raw\n", encoding="utf-8"
        )
        for cache_name in (".uv-cache", ".pip-cache"):
            cache_file = exec_dir / cache_name / "archive.bin"
            cache_file.parent.mkdir(parents=True)
            cache_file.write_bytes(b"cache")
        generated = exec_dir / "service/target/generated-output.bin"
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_bytes(b"generated")
        trace_path = exec_dir / "trace.jsonl"
        final_path = exec_dir / "last_message.md"
        stderr_path = exec_dir / "stderr.txt"
        trace_path.write_text(json.dumps({"type": "turn.completed", "usage": {"total_tokens": 1}}) + "\n", encoding="utf-8")
        final_path.write_text("done", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return AgentResult(returncode=0, trace_path=trace_path, final_message_path=final_path, stderr_path=stderr_path)

    def run_judge(
        self,
        *,
        prompt: str,
        exec_dir: Path,
        model: str | None = None,
        schema_path: Path | None = None,
        timeout: int = 900,
    ) -> AgentResult:
        self.judge_timeouts.append(timeout)
        trace_path = exec_dir / "rubric_trace.jsonl"
        output_path = exec_dir / "rubric_grade.json"
        stderr_path = exec_dir / "rubric_stderr.txt"
        trace_path.write_text(json.dumps({"type": "turn.completed", "usage": {"total_tokens": 1}}) + "\n", encoding="utf-8")
        output_path.write_text(
            json.dumps(
                {
                    "overall_pass": True,
                    "score": 100,
                    "checks": [{"id": "rubric-1", "pass": True, "notes": "ok", "evidence": "recorded"}],
                }
            ),
            encoding="utf-8",
        )
        stderr_path.write_text("", encoding="utf-8")
        return AgentResult(returncode=0, trace_path=trace_path, final_message_path=output_path, stderr_path=stderr_path)

    def parse_trace(self, trace_path: Path):
        return parse_trace(trace_path)

    def parse_trace_bytes(self, value: bytes):
        raw = value.decode("utf-8", errors="replace")
        events = [json.loads(line) for line in raw.splitlines() if line.strip()]
        return TraceSummary(events, raw)


class SymlinkPlantingBackend(RecordingBackend):
    def __init__(self, outside: dict[str, Path]) -> None:
        super().__init__()
        self.outside = outside

    def run_agent(
        self,
        *,
        prompt: str,
        exec_dir: Path,
        model: str | None = None,
        timeout: int = 1200,
    ) -> AgentResult:
        result = super().run_agent(
            prompt=prompt,
            exec_dir=exec_dir,
            model=model,
            timeout=timeout,
        )
        for name, target in (
            ("grade.json", self.outside["grade"]),
            (".codex-eval-provenance.json", self.outside["provenance"]),
            ("summary.json", self.outside["summary"]),
        ):
            (exec_dir / name).symlink_to(target)
        return result


class ExecutionDirectorySwapBackend(RecordingBackend):
    def __init__(self, outside: Path) -> None:
        super().__init__()
        self.outside = outside

    def run_agent(
        self,
        *,
        prompt: str,
        exec_dir: Path,
        model: str | None = None,
        timeout: int = 1200,
    ) -> AgentResult:
        result = super().run_agent(
            prompt=prompt,
            exec_dir=exec_dir,
            model=model,
            timeout=timeout,
        )
        stolen = self.outside / "stolen-exec"
        self.outside.mkdir(parents=True)
        shutil.move(str(exec_dir), str(stolen))
        exec_dir.symlink_to(stolen, target_is_directory=True)
        for name in ("grade.json", ".codex-eval-provenance.json", "summary.json"):
            (stolen / name).write_text("sentinel\n", encoding="utf-8")
        return result


class ExecutionRootVictimSwapBackend(RecordingBackend):
    def __init__(self, outside: Path) -> None:
        super().__init__()
        self.outside = outside
        self.replaced_root: Path | None = None
        self.stolen_root: Path | None = None

    def run_agent(
        self,
        *,
        prompt: str,
        exec_dir: Path,
        model: str | None = None,
        timeout: int = 1200,
    ) -> AgentResult:
        result = super().run_agent(
            prompt=prompt,
            exec_dir=exec_dir,
            model=model,
            timeout=timeout,
        )
        original_root = exec_dir.parent
        self.outside.mkdir(parents=True)
        stolen_root = self.outside / "stolen-root"
        original_root.rename(stolen_root)
        victim = self.outside / "victim"
        victim.mkdir()
        (victim / "sentinel.txt").write_text("keep\n", encoding="utf-8")
        victim.rename(original_root)
        self.replaced_root = original_root
        self.stolen_root = stolen_root
        return result


class ArtifactDirectoryPlantingBackend(RecordingBackend):
    def __init__(self, victim: Path, artifact_dir: Path) -> None:
        super().__init__()
        self.victim = victim
        self.artifact_dir = artifact_dir

    def run_agent(
        self,
        *,
        prompt: str,
        exec_dir: Path,
        model: str | None = None,
        timeout: int = 1200,
    ) -> AgentResult:
        result = super().run_agent(
            prompt=prompt,
            exec_dir=exec_dir,
            model=model,
            timeout=timeout,
        )
        self.victim.mkdir()
        (self.victim / "sentinel.txt").write_text(
            "keep\n", encoding="utf-8"
        )
        self.victim.rename(self.artifact_dir)
        return result


class OutputReadReplacementBackend(RecordingBackend):
    def __init__(self, outside: Path) -> None:
        super().__init__()
        self.outside = outside
        self.replacement: Path | None = None

    def run_agent(
        self,
        *,
        prompt: str,
        exec_dir: Path,
        model: str | None = None,
        timeout: int = 1200,
    ) -> AgentResult:
        result = super().run_agent(
            prompt=prompt,
            exec_dir=exec_dir,
            model=model,
            timeout=timeout,
        )
        self.outside.mkdir()
        stolen = self.outside / "original"
        exec_dir.rename(stolen)
        exec_dir.mkdir()
        (exec_dir / "trace.jsonl").write_text(
            json.dumps({"type": "turn.completed", "usage": {"total_tokens": 999}})
            + "\n",
            encoding="utf-8",
        )
        (exec_dir / "last_message.md").write_text(
            "FORGED\n", encoding="utf-8"
        )
        self.replacement = exec_dir
        return result


class TrackingBackend(RecordingBackend):
    def __init__(self) -> None:
        super().__init__()
        self.exec_dir: Path | None = None

    def run_agent(
        self,
        *,
        prompt: str,
        exec_dir: Path,
        model: str | None = None,
        timeout: int = 1200,
    ) -> AgentResult:
        self.exec_dir = exec_dir
        return super().run_agent(
            prompt=prompt,
            exec_dir=exec_dir,
            model=model,
            timeout=timeout,
        )


class SnapshotObservingBackend(RecordingBackend):
    def __init__(self, mutate_sources=None) -> None:
        super().__init__()
        self.mutate_sources = mutate_sources
        self.observed: dict[str, str] = {}

    def run_agent(
        self,
        *,
        prompt: str,
        exec_dir: Path,
        model: str | None = None,
        timeout: int = 1200,
    ) -> AgentResult:
        if self.mutate_sources is not None:
            self.mutate_sources()
        skill_snapshot = exec_dir / ".agents/skills/sample-skill"
        references_snapshot = exec_dir / ".agents/skills/references"
        assert not skill_snapshot.is_symlink()
        assert not references_snapshot.is_symlink()
        self.observed = {
            "fixture": (exec_dir / "service/main.txt").read_text(
                encoding="utf-8"
            ),
            "skill": (skill_snapshot / "SKILL.md").read_text(
                encoding="utf-8"
            ),
            "references": (references_snapshot / "contract.md").read_text(
                encoding="utf-8"
            ),
        }
        return super().run_agent(
            prompt=prompt,
            exec_dir=exec_dir,
            model=model,
            timeout=timeout,
        )
