from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from pytest_codex_evals.ab import side_prompt
from pytest_codex_evals.config import load_settings
from pytest_codex_evals.definitions import (
    CaseResult,
    EndpointExpectation,
    GradeCheckResult,
    GradeResult,
    JSONRecordExpectation,
    PromptVariant,
    RubricEvalCase,
    RubricEvalDefinition,
    RuntimeCheck,
    RuntimeEvalCase,
    RuntimeExpectations,
    SanityCheck,
    SanityEvalCase,
    ServiceLogExpectation,
    SideResult,
    ValidationResult,
)
from pytest_codex_evals.graders.rubric import rubric_prompt
from pytest_codex_evals.backends import (
    AgentResult,
    CodexBackend,
    StreamedCommandResult,
    _codex_subprocess_env,
    run_streamed_command,
)
from pytest_codex_evals.graders.runtime import (
    base_url_from_port_output,
    check_json_record_expectations,
    compose_ps_records,
    grade_runtime,
    resolve_compose_file,
    run_runtime_check,
    request_json_text,
    runtime_env,
    service_url,
    stop_compose_services,
    validate_service_log_expectations,
)
from pytest_codex_evals.graders.sanity import grade_sanity
from pytest_codex_evals.cli import main as cli_main
from pytest_codex_evals.report import (
    normalize_rubric_score,
    render_reports_for_run_root,
    write_session_results,
)
from pytest_codex_evals.plugin import case_from_definition
from pytest_codex_evals.runner import prepare_side_workspace, run_case
from pytest_codex_evals.trace import parse_trace


def test_side_prompt_generates_loaded_and_not_loaded_variants():
    case = sanity_case(task="Scan the service.")

    assert side_prompt(case, "with_skill") == "Use the $sample-skill skill. Scan the service."
    assert side_prompt(case, "baseline") == "Scan the service."


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


def test_prepare_side_workspace_stages_only_explicit_eval_inputs(
    tmp_path: Path,
):
    fixture_dir = tmp_path / "fixture"
    inputs = fixture_dir / "eval" / "inputs"
    inputs.mkdir(parents=True)
    (fixture_dir / "eval" / "qual").mkdir()
    (fixture_dir / "main.go").write_text("package main\n", encoding="utf-8")
    (inputs / "otel-audit.json").write_text("{}\n", encoding="utf-8")
    (inputs / "otel-verify.json").write_text("{}\n", encoding="utf-8")
    (fixture_dir / "eval" / "qual" / "audit.json").write_text(
        "{}\n", encoding="utf-8"
    )

    scoped = sanity_case(
        fixture_dir=fixture_dir,
        eval_inputs=["eval/inputs/otel-audit.json"],
    )
    prepare_side_workspace(
        tmp_path,
        scoped,
        "baseline",
        tmp_path / "scoped",
    )
    service = tmp_path / "scoped" / "service"
    assert (service / "main.go").is_file()
    assert (service / "eval" / "inputs" / "otel-audit.json").is_file()
    assert not (service / "eval" / "inputs" / "otel-verify.json").exists()
    assert not (service / "eval" / "qual").exists()

    unscoped = sanity_case(fixture_dir=fixture_dir)
    prepare_side_workspace(
        tmp_path,
        unscoped,
        "baseline",
        tmp_path / "unscoped",
    )
    assert not (tmp_path / "unscoped" / "service" / "eval").exists()


def test_prepare_side_workspace_rejects_missing_eval_input(tmp_path: Path):
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    case = sanity_case(
        fixture_dir=fixture_dir,
        eval_inputs=["eval/inputs/missing.json"],
    )

    with pytest.raises(ValueError, match="regular fixture file"):
        prepare_side_workspace(
            tmp_path,
            case,
            "baseline",
            tmp_path / "run",
        )


def test_prepare_side_workspace_rejects_symlinked_eval_input(tmp_path: Path):
    fixture_dir = tmp_path / "fixture"
    inputs = fixture_dir / "eval" / "inputs"
    inputs.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    (inputs / "otel-audit.json").symlink_to(outside)
    case = sanity_case(
        fixture_dir=fixture_dir,
        eval_inputs=["eval/inputs/otel-audit.json"],
    )

    with pytest.raises(ValueError, match="regular fixture file"):
        prepare_side_workspace(
            tmp_path,
            case,
            "baseline",
            tmp_path / "run",
        )


def test_codex_subprocess_env_uses_sandbox_local_package_caches(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("UV_CACHE_DIR", "/outside/uv-cache")
    monkeypatch.setenv("PIP_CACHE_DIR", "/outside/pip-cache")

    env = _codex_subprocess_env(tmp_path)

    assert env["UV_CACHE_DIR"] == str(tmp_path / ".uv-cache")
    assert env["PIP_CACHE_DIR"] == str(tmp_path / ".pip-cache")


def test_codex_backend_uses_current_workspace_write_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    captured: list[str] = []

    def fake_run(command, **_kwargs):
        captured.extend(command)
        return StreamedCommandResult(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("pytest_codex_evals.backends.run_streamed_command", fake_run)

    CodexBackend(command="codex").run_agent(
        prompt="Run the skill.",
        exec_dir=tmp_path,
    )

    assert "--full-auto" not in captured
    assert captured[captured.index("--config") + 1] == "shell_environment_policy.inherit=all"
    assert captured[captured.index("--sandbox") + 1] == "workspace-write"
    assert "--approve-for-me" not in captured


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

    grade = grade_runtime(case, tmp_path, "done", parse_trace(empty_trace(tmp_path)), "with_skill", runtime_enabled=False, repo_root=tmp_path)

    check = next(item for item in grade.checks if item.id == "observer-runtime")
    assert check.category == "runtime"
    assert check.skipped
    assert grade.total == 2


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
    write_loaded_skill(tmp_path, "otel-instrument")
    case = sanity_case(
        skill="otel-instrument",
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

    grade = grade_sanity(case, tmp_path, "verified", parse_trace(empty_trace(tmp_path)), "with_skill")

    assert grade.pass_rate == 1.0


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


def test_report_renderer_writes_kind_specific_outputs(tmp_path: Path):
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    grade = GradeResult(checks=[GradeCheckResult(id="check", description="check", passed=False, evidence="missing output")])
    result = case_result(side_result("with_skill", grade), None)

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
                    "agent_model": "gpt-test",
                },
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
    assert benchmark["evals"][0]["with_baseline"] is None
    assert set(benchmark["evals"][0]["with_skill"]) >= {"checks", "tokens", "duration_seconds"}
    assert "rubric" not in benchmark["evals"][0]["with_skill"]
    assert "runtime" not in benchmark["evals"][0]["with_skill"]
    assert benchmark["failures"][0]["result"] == "sanity:check FAIL"
    report = report_path.read_text(encoding="utf-8")
    assert "| with_skill | sample/service/sample-skill | sample/service | 1 | 0% (0/1) | 0 | 0.0s | - | - | - |" in report
    assert "sanity:check FAIL" in report


def test_cli_report_renders_latest_run(tmp_path: Path):
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    grade = GradeResult(checks=[GradeCheckResult(id="check", description="check", passed=True)])
    result = case_result(side_result("with_skill", grade), None)
    write_session_results(
        [
            {
                "mode": "with_skill",
                "eval_kind": "sanity",
                "repo_root": tmp_path,
                "run_root": run_root,
                "skill": "sample-skill",
                "metadata": {"mode": "with_skill", "eval_kind": "sanity", "run_id": "run", "skill": "sample-skill"},
                "results": [result],
            }
        ]
    )

    assert cli_main(["report", "--repo-root", str(tmp_path), "--skill", "sample-skill", "--kind", "sanity"]) == 0

    assert (tmp_path / "eval-reports" / "sample-skill" / "sanity" / "report.md").is_file()
    assert (tmp_path / "eval-reports" / "sample-skill" / "sanity" / "benchmark.json").is_file()


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
    assert "| with_skill | sample/service/sample-skill | sample/service | 1 | 100% (1/1) | 456 | 12.3s | - | - | - |" in report


def test_sanity_report_uses_sanity_template_only(tmp_path: Path):
    report = report_for_kind(tmp_path, "sanity")

    assert "Rubric Checks" not in report
    assert "Runtime Checks" not in report
    assert "## Sanity Summary" in report
    assert "## Sanity Failures" in report
    assert "## Rubric Summary" not in report
    assert "## Runtime Summary" not in report
    assert "| with_skill | sample/service/sample-skill | sample/service | 1 | 100% (1/1) | 456 | 12.3s | - | - | - |" in report


def test_rubric_report_uses_rubric_template_only(tmp_path: Path):
    report = report_for_kind(tmp_path, "rubric")

    assert "Sanity Checks" not in report
    assert "Runtime Checks" not in report
    assert "## Sanity Summary" not in report
    assert "## Rubric Summary" in report
    assert "## Rubric Failures" in report
    assert "## Runtime Summary" not in report
    assert "| with_skill | sample/service/sample-skill | sample/service | 1 | 100% (1/1), avg score 4 | 456 | 12.3s | - | - | - |" in report


def report_for_kind(tmp_path: Path, eval_kind: str) -> str:
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    sanity = GradeCheckResult(id="file", description="file", passed=True)
    runtime = GradeCheckResult(id="observer", description="observer", passed=True, category="runtime")
    rubric_path = tmp_path / "rubric_grade.json"
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
    from pytest_codex_evals.backends import create_backend, CodexBackend, CursorBackend, ClaudeBackend

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


def test_runtime_expectations_accept_service_logs_only():
    expectations = RuntimeExpectations(
        service_logs=[
            ServiceLogExpectation(
                id="preserved-sink",
                contains_all=["runtime request completed"],
            )
        ]
    )

    assert expectations.has_expectations() is True
    assert expectations.endpoints == []


def test_runtime_expectations_reject_unknown_keys():
    with pytest.raises(ValueError, match="service_logz"):
        RuntimeExpectations(
            endpoints=[EndpointExpectation(id="logs", url="/api/query/logs")],
            service_logz=[{"id": "misspelled-sink"}],
        )


@pytest.mark.parametrize(
    ("model", "values", "unknown_key"),
    [
        (
            JSONRecordExpectation,
            {"id": "request-log", "match": {}, "field_equalz": {}},
            "field_equalz",
        ),
        (
            EndpointExpectation,
            {"id": "logs", "record_checkz": []},
            "record_checkz",
        ),
        (
            ServiceLogExpectation,
            {
                "id": "preserved-sink",
                "contains_all": ["request completed"],
                "occurrencez": {},
            },
            "occurrencez",
        ),
        (
            RuntimeCheck,
            {
                "id": "observer-runtime",
                "description": "Runtime telemetry reaches Observer.",
                "compose_file": "docker-compose.yml",
                "expect": {
                    "endpoints": [{"id": "logs", "url": "/api/query/logs"}]
                },
                "stop_service_before_validation": ["app"],
            },
            "stop_service_before_validation",
        ),
    ],
)
def test_runtime_models_reject_unknown_keys(model, values, unknown_key):
    with pytest.raises(ValueError, match=unknown_key):
        model.model_validate(values)


def test_runtime_json_request_rejects_non_success_status(monkeypatch):
    import pytest_codex_evals.graders.runtime as runtime_grader

    monkeypatch.setattr(
        runtime_grader,
        "request_text",
        lambda *_args, **_kwargs: (503, "[]"),
    )

    with pytest.raises(RuntimeError, match="returned HTTP 503"):
        request_json_text("http://observer/api/query/logs")


def test_runtime_check_rejects_non_app_shutdown_service():
    with pytest.raises(ValueError, match="stop_services_before_validation"):
        RuntimeCheck(
            id="observer-runtime",
            description="Runtime telemetry reaches Observer.",
            compose_file="docker-compose.yml",
            stop_services_before_validation=["observer"],
            expect=RuntimeExpectations(
                service_logs=[
                    ServiceLogExpectation(
                        id="preserved-sink",
                        contains_all=["runtime request completed"],
                    )
                ]
            ),
        )


def test_runtime_structured_record_expectation_proves_log_fields_correlation_and_uniqueness(
    monkeypatch: pytest.MonkeyPatch,
):
    import pytest_codex_evals.graders.runtime as runtime_grader

    trace_ids = ["a" * 32, "b" * 32]
    span_ids = ["1" * 16, "2" * 16]
    records = [
        {
            "body": "runtime request completed",
            "severityText": "WARN",
            "traceId": trace_ids[0],
            "spanId": span_ids[0],
            "resource": {"serviceName": "sample-service"},
        },
        {
            "body": "runtime request completed",
            "severityText": "WARNING",
            "traceId": trace_ids[1],
            "spanId": span_ids[1],
            "resource": {"serviceName": "sample-service"},
        },
    ]
    requested: list[str] = []

    def trace_detail(url: str, **_kwargs):
        requested.append(url)
        trace_id = url.rsplit("/", 1)[-1]
        span_id = span_ids[trace_ids.index(trace_id)]
        return 200, json.dumps(
            {
                "traceId": trace_id,
                "spans": [{"traceId": trace_id, "spanId": span_id}],
            }
        )

    monkeypatch.setattr(runtime_grader, "request_text", trace_detail)
    expectation = JSONRecordExpectation(
        id="request-logs",
        match={"body": "runtime request completed"},
        field_contains={"severityText": "WARN"},
        field_equals={"resource.serviceName": "sample-service"},
        non_empty=["traceId", "spanId"],
        exact_count=2,
        unique_by=["traceId", "spanId"],
        correlates_with_trace=True,
    )
    evidence: list[str] = []
    failures: list[str] = []

    check_json_record_expectations(
        "logs",
        json.dumps(records),
        [expectation],
        evidence,
        failures,
        base_url="http://observer",
    )

    assert failures == []
    assert evidence == ["logs/request-logs matched 2 structured record(s)"]
    assert requested == [
        f"http://observer/api/query/traces/{trace_ids[0]}",
        f"http://observer/api/query/traces/{trace_ids[1]}",
    ]


@pytest.mark.parametrize(
    ("trace_id", "span_id", "failure"),
    [
        ("trace-1", "1" * 16, "nonzero 32-hex OTel ID"),
        ("0" * 32, "1" * 16, "nonzero 32-hex OTel ID"),
        ("a" * 32, "span-1", "nonzero 16-hex OTel ID"),
        ("a" * 32, "0" * 16, "nonzero 16-hex OTel ID"),
    ],
)
def test_runtime_trace_correlation_rejects_invalid_or_zero_otel_ids(
    trace_id: str,
    span_id: str,
    failure: str,
):
    expectation = JSONRecordExpectation(
        id="request-log",
        match={"body": "runtime request completed"},
        exact_count=1,
        correlates_with_trace=True,
    )
    failures: list[str] = []

    check_json_record_expectations(
        "logs",
        json.dumps(
            [
                {
                    "body": "runtime request completed",
                    "traceId": trace_id,
                    "spanId": span_id,
                }
            ]
        ),
        [expectation],
        [],
        failures,
        base_url="http://observer",
    )

    assert any(failure in item for item in failures)


def test_runtime_trace_correlation_requires_span_in_observer_detail(
    monkeypatch: pytest.MonkeyPatch,
):
    import pytest_codex_evals.graders.runtime as runtime_grader

    trace_id = "a" * 32
    span_id = "1" * 16
    monkeypatch.setattr(
        runtime_grader,
        "request_text",
        lambda *_args, **_kwargs: (
            200,
            json.dumps(
                {
                    "traceId": trace_id,
                    "spans": [{"traceId": trace_id, "spanId": "2" * 16}],
                }
            ),
        ),
    )
    expectation = JSONRecordExpectation(
        id="request-log",
        match={"body": "runtime request completed"},
        exact_count=1,
        correlates_with_trace=True,
    )
    failures: list[str] = []

    check_json_record_expectations(
        "logs",
        json.dumps(
            [
                {
                    "body": "runtime request completed",
                    "traceId": trace_id,
                    "spanId": span_id,
                }
            ]
        ),
        [expectation],
        [],
        failures,
        base_url="http://observer",
    )

    assert failures == [
        "logs/request-log record 0 trace detail did not contain correlated span "
        + span_id
    ]


@pytest.mark.parametrize(
    ("records", "failure"),
    [
        (
            [
                {
                    "body": "runtime request completed",
                    "severityText": "INFO",
                    "traceId": "trace-1",
                    "spanId": "span-1",
                    "resource": {"serviceName": "sample-service"},
                }
            ],
            "expected severityText to contain 'WARN'",
        ),
        (
            [
                {
                    "body": "runtime request completed",
                    "severityText": "WARN",
                    "traceId": "",
                    "spanId": "span-1",
                    "resource": {"serviceName": "sample-service"},
                }
            ],
            "expected non-empty traceId",
        ),
        (
            [
                {
                    "body": "runtime request completed",
                    "severityText": "WARN",
                    "traceId": "trace-1",
                    "spanId": "span-1",
                    "resource": {"serviceName": "sample-service"},
                },
                {
                    "body": "runtime request completed",
                    "severityText": "WARN",
                    "traceId": "trace-1",
                    "spanId": "span-1",
                    "resource": {"serviceName": "sample-service"},
                },
            ],
            "expected 1 matching records, got 2",
        ),
    ],
)
def test_runtime_structured_record_expectation_rejects_incomplete_or_duplicate_logs(
    records: list[dict[str, object]], failure: str
):
    expectation = JSONRecordExpectation(
        id="request-log",
        match={"body": "runtime request completed"},
        field_contains={"severityText": "WARN"},
        field_equals={"resource.serviceName": "sample-service"},
        non_empty=["traceId", "spanId"],
        exact_count=1,
        unique_by=["traceId", "spanId"],
    )
    failures: list[str] = []

    check_json_record_expectations(
        "logs", json.dumps(records), [expectation], [], failures
    )

    assert any(failure in item for item in failures)


def test_runtime_zero_record_expectation_proves_logs_opt_out():
    expectation = JSONRecordExpectation(
        id="no-logs",
        match={"body": "runtime request completed"},
        exact_count=0,
    )
    failures: list[str] = []
    check_json_record_expectations("logs", "[]", [expectation], [], failures)
    assert failures == []

    check_json_record_expectations(
        "logs",
        json.dumps([{"body": "runtime request completed"}]),
        [expectation],
        [],
        failures,
    )
    assert failures == ["logs/no-logs expected 0 matching records, got 1"]


def test_runtime_structured_record_expectation_rejects_duplicate_correlation_ids():
    duplicate = {
        "body": "runtime request completed",
        "traceId": "trace-1",
        "spanId": "span-1",
    }
    expectation = JSONRecordExpectation(
        id="request-logs",
        match={"body": "runtime request completed"},
        exact_count=2,
        unique_by=["traceId", "spanId"],
    )
    failures: list[str] = []

    check_json_record_expectations(
        "logs", json.dumps([duplicate, duplicate]), [expectation], [], failures
    )

    assert failures == [
        "logs/request-logs expected unique records by traceId, spanId"
    ]


def test_runtime_service_log_expectation_proves_preserved_sink(monkeypatch, tmp_path: Path):
    import pytest_codex_evals.graders.runtime as runtime_grader

    monkeypatch.setattr(
        runtime_grader,
        "compose_service_logs",
        lambda *_args: "runtime request completed\n",
    )
    expectation = ServiceLogExpectation(
        id="preserved-sink",
        contains_all=["runtime request completed"],
        occurrences={"runtime request completed": 1},
    )

    passed, evidence = validate_service_log_expectations(
        [expectation], tmp_path / "compose.yml", "project", {}
    )

    assert passed is True
    assert evidence == "preserved-sink preserved service log output"


@pytest.mark.parametrize(
    "expectation",
    [
        {"id": "empty"},
        {"id": "empty-list", "contains_all": []},
        {"id": "empty-map", "occurrences": {}},
        {"id": "empty-value", "contains_all": [" "]},
    ],
)
def test_runtime_service_log_expectation_requires_nonempty_assertion(
    expectation: dict[str, object],
):
    with pytest.raises(ValueError, match="service log expectation"):
        ServiceLogExpectation.model_validate(expectation)


def test_runtime_service_log_expectation_fails_when_compose_logs_fail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    import pytest_codex_evals.graders.runtime as runtime_grader

    def unavailable(*_args):
        raise RuntimeError("docker compose logs exited 1")

    monkeypatch.setattr(runtime_grader, "compose_service_logs", unavailable)
    expectation = ServiceLogExpectation(
        id="preserved-sink",
        contains_all=["runtime request completed"],
    )

    passed, evidence = validate_service_log_expectations(
        [expectation], tmp_path / "compose.yml", "project", {}
    )

    assert passed is False
    assert "service logs unavailable for app" in evidence
    assert "docker compose logs exited 1" in evidence


def test_runtime_stops_only_configured_app_before_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    import pytest_codex_evals.graders.runtime as runtime_grader

    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    check = runtime_check()
    check.stop_services_before_validation = ["app"]
    check.settle_seconds = 0
    commands: list[list[str]] = []
    events: list[str] = []

    def record_process(command, *_args, **_kwargs):
        commands.append(command)
        if "stop" in command:
            events.append("stop")
        if "ps" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    [{"Service": "app", "State": "exited", "ExitCode": 0}]
                ),
                "",
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    def validate_endpoints(*_args):
        events.append("validate-endpoints")
        return True, "endpoints passed"

    def validate_logs(*_args):
        events.append("validate-logs")
        return True, ""

    monkeypatch.setattr(runtime_grader, "run_process", record_process)
    monkeypatch.setattr(
        runtime_grader,
        "discover_service_base_url",
        lambda *_args: "http://observer",
    )
    monkeypatch.setattr(runtime_grader, "wait_for_service", lambda *_args: None)
    monkeypatch.setattr(runtime_grader, "clear_service", lambda *_args: None)
    monkeypatch.setattr(
        runtime_grader,
        "validate_endpoint_expectations",
        validate_endpoints,
    )
    monkeypatch.setattr(
        runtime_grader,
        "validate_service_log_expectations",
        validate_logs,
    )

    result = run_runtime_check(
        check,
        tmp_path / "service",
        repo_root=tmp_path,
        eval_dir=tmp_path,
    )

    stop_command = next(command for command in commands if "stop" in command)
    traffic_command = next(command for command in commands if "traffic" in command)
    assert result.passed is True
    assert stop_command[-4:] == ["stop", "--timeout", "30", "app"]
    assert "observer" not in stop_command[stop_command.index("stop") + 1 :]
    assert commands.index(traffic_command) < commands.index(stop_command)
    assert events == ["stop", "validate-endpoints", "validate-logs"]


@pytest.mark.parametrize("exit_code", [1, 137, 143])
def test_runtime_shutdown_rejects_forced_or_nonzero_app_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    exit_code: int,
):
    import pytest_codex_evals.graders.runtime as runtime_grader

    def record_process(command, *_args, **_kwargs):
        stdout = ""
        if "ps" in command:
            stdout = json.dumps(
                [{"Service": "app", "State": "exited", "ExitCode": exit_code}]
            )
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(runtime_grader, "run_process", record_process)

    with pytest.raises(RuntimeError, match="did not stop gracefully"):
        stop_compose_services(
            tmp_path / "docker-compose.yml",
            "project",
            {},
            ["app"],
            30,
        )


def test_compose_ps_records_accepts_array_and_json_lines():
    records = [
        {"Service": "app", "State": "exited", "ExitCode": 0},
        {"Service": "worker", "State": "exited", "ExitCode": 0},
    ]

    assert compose_ps_records(json.dumps(records)) == records
    assert compose_ps_records("\n".join(json.dumps(item) for item in records)) == records


def test_runtime_service_log_only_check_skips_endpoint_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    import pytest_codex_evals.graders.runtime as runtime_grader

    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    check = RuntimeCheck(
        id="service-log-runtime",
        description="Runtime sink output is preserved.",
        compose_file="docker-compose.yml",
        settle_seconds=0,
        expect=RuntimeExpectations(
            service_logs=[
                ServiceLogExpectation(
                    id="preserved-sink",
                    contains_all=["runtime request completed"],
                )
            ]
        ),
    )

    monkeypatch.setattr(
        runtime_grader,
        "run_process",
        lambda command, *_args, **_kwargs: subprocess.CompletedProcess(
            command, 0, "", ""
        ),
    )
    monkeypatch.setattr(
        runtime_grader,
        "discover_service_base_url",
        lambda *_args: "http://observer",
    )
    monkeypatch.setattr(runtime_grader, "wait_for_service", lambda *_args: None)
    monkeypatch.setattr(runtime_grader, "clear_service", lambda *_args: None)

    def unexpected_endpoint_validation(*_args):
        raise AssertionError("endpoint validation must not run")

    monkeypatch.setattr(
        runtime_grader,
        "validate_endpoint_expectations",
        unexpected_endpoint_validation,
    )
    monkeypatch.setattr(
        runtime_grader,
        "validate_service_log_expectations",
        lambda *_args: (True, "preserved-sink preserved service log output"),
    )

    result = run_runtime_check(
        check,
        tmp_path / "service",
        repo_root=tmp_path,
        eval_dir=tmp_path,
    )

    assert result.passed is True
    assert result.evidence == "preserved-sink preserved service log output"


def test_runtime_environment_overrides_are_isolated(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CODEX_EVAL_OTEL_LOGS_EXPORTER", "host-value")

    env = runtime_env(
        tmp_path,
        tmp_path / "service",
        "project",
        {
            "CODEX_EVAL_OTEL_LOGS_EXPORTER": "none",
            "CODEX_EVAL_SERVICE_DIR": "/untrusted/service",
            "COMPOSE_PROJECT_NAME": "untrusted-project",
        },
    )

    assert env["CODEX_EVAL_OTEL_LOGS_EXPORTER"] == "none"
    assert env["CODEX_EVAL_SERVICE_DIR"] == str((tmp_path / "service").resolve())
    assert env["COMPOSE_PROJECT_NAME"] == "project"


def test_run_case_passes_configured_agent_and_judge_timeouts(tmp_path: Path):
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
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
    )

    assert backend.agent_timeouts == [2400]
    assert backend.judge_timeouts == [1200]


def write_loaded_skill(root: Path, skill: str) -> None:
    skill_dir = root / ".agents" / "skills" / skill
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"name: {skill}\n", encoding="utf-8")


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
