from __future__ import annotations

import json
import sys
from pathlib import Path

from pytest_codex_evals.ab import side_prompt
from pytest_codex_evals.config import load_settings
from pytest_codex_evals.definitions import (
    CaseResult,
    GradeCheckResult,
    GradeResult,
    ObserverExpectation,
    RubricEvalCase,
    RuntimeCheck,
    RuntimeEvalCase,
    RuntimeExpectations,
    SanityCheck,
    SanityEvalCase,
    SideResult,
    ValidationResult,
)
from pytest_codex_evals.graders.rubric import rubric_prompt
from pytest_codex_evals.graders.runtime import grade_runtime, resolve_compose_file, runtime_env
from pytest_codex_evals.graders.sanity import grade_sanity
from pytest_codex_evals.report import write_ab_reports, write_combined_session_reports, write_side_reports
from pytest_codex_evals.trace import parse_trace


def test_side_prompt_generates_loaded_and_not_loaded_variants():
    case = sanity_case(task="Scan the service.")

    assert side_prompt(case, "with_skill") == "Use the $sample-skill skill. Scan the service."
    assert side_prompt(case, "baseline") == "Scan the service."


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

    prompt = rubric_prompt(case)

    assert "Read ./answer.md." in prompt
    assert "Must cite evidence." in prompt
    assert "./service" not in prompt


def test_ab_report_writes_mode_specific_and_legacy_paths(tmp_path: Path):
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    grade = GradeResult(checks=[GradeCheckResult(id="check", description="check", passed=True)])
    side = side_result("with_skill", grade)
    baseline = side_result("baseline", grade)
    result = case_result(side, baseline)

    write_ab_reports(tmp_path, run_root, "sample-skill", [result])

    assert (run_root / "ab-report.md").is_file()
    assert (run_root / "ab-benchmark.json").is_file()
    assert (run_root / "report.md").is_file()
    assert (run_root / "results" / "sample" / "service" / "sample-skill" / "eval.json").is_file()
    assert (run_root / "results" / "sample" / "service" / "sample-skill" / "with_skill.json").is_file()
    assert (run_root / "results" / "sample" / "service" / "sample-skill" / "with_baseline.json").is_file()
    benchmark = json.loads((run_root / "ab-benchmark.json").read_text(encoding="utf-8"))
    assert benchmark["mode"] == "ab"
    assert benchmark["summary"]["eval_count"] == 1
    assert benchmark["evals"][0]["prompt_count"] == 1


def test_side_report_writes_with_skill_paths(tmp_path: Path):
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    grade = GradeResult(checks=[GradeCheckResult(id="check", description="check", passed=False, evidence="missing output")])
    result = case_result(side_result("with_skill", grade), None)

    write_side_reports(tmp_path, run_root, "sample-skill", "with_skill", [result])

    assert (run_root / "with_skill-report.md").is_file()
    assert (run_root / "with_skill-benchmark.json").is_file()
    assert (run_root / "results" / "sample" / "service" / "sample-skill" / "with_skill.json").is_file()
    assert (run_root / "results" / "sample" / "service" / "sample-skill" / "with_baseline.json").is_file()
    benchmark = json.loads((run_root / "with_skill-benchmark.json").read_text(encoding="utf-8"))
    assert benchmark["mode"] == "with_skill"
    assert benchmark["evals"][0]["with_baseline"] is None
    assert benchmark["failures"][0]["result"] == "sanity:check FAIL"
    report = (run_root / "with_skill-report.md").read_text(encoding="utf-8")
    assert "| sample/service/sample-skill | sample/service | 1 | 0% (0/1) | - | 0 | 0.0s | - | - | - | - |" in report
    assert "sanity:check FAIL" in report


def test_runtime_combined_report_uses_runtime_template_only(tmp_path: Path):
    report = combined_report_for_kind(tmp_path, "runtime")

    assert "## Validation" in report
    assert "## Sanity Summary" not in report
    assert "## Rubric Summary" not in report
    assert "## Runtime Summary" in report
    assert "## Runtime Failures" in report
    assert "## Compose Evidence" in report
    assert "| with_skill | sample/service/sample-skill | sample/service | 1 | 100% (1/1) | 456 | 12.3s | - | - | - |" in report


def test_sanity_combined_report_uses_sanity_template_only(tmp_path: Path):
    report = combined_report_for_kind(tmp_path, "sanity")

    assert "## Validation" in report
    assert "## Sanity Summary" in report
    assert "## Sanity Failures" in report
    assert "## Rubric Summary" not in report
    assert "## Runtime Summary" not in report
    assert "| with_skill | sample/service/sample-skill | sample/service | 1 | 100% (1/1) | 456 | 12.3s | - | - | - |" in report


def test_rubric_combined_report_uses_rubric_template_only(tmp_path: Path):
    report = combined_report_for_kind(tmp_path, "rubric")

    assert "## Validation" in report
    assert "## Sanity Summary" not in report
    assert "## Rubric Summary" in report
    assert "## Rubric Failures" in report
    assert "## Runtime Summary" not in report
    assert "| with_skill | sample/service/sample-skill | sample/service | 1 | 100% (1/1), avg score 4 | 456 | 12.3s | - | - | - |" in report


def test_standard_combined_report_keeps_all_live_sections(tmp_path: Path):
    report = combined_report_for_kind(tmp_path, "standard")

    assert "## Validation" in report
    assert "## Sanity Summary" in report
    assert "## Rubric Summary" in report
    assert "## Runtime Summary" in report


def combined_report_for_kind(tmp_path: Path, eval_kind: str) -> str:
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
    validation = ValidationResult(
        id=case.id,
        base_id=case.base_id,
        prompt_id=case.prompt_id,
        skill=case.skill,
        language=case.language,
        service=case.service,
        definition_path=str(tmp_path / "sample.json"),
        fixture_dir=str(tmp_path),
        skill_path=str(tmp_path / "skills" / "sample-skill"),
        eval_kind=eval_kind if eval_kind in {"sanity", "rubric", "runtime"} else "sanity",
        sanity_check_count=1,
        rubric_check_count=1,
        runtime_check_count=1,
    )

    write_combined_session_reports(
        [
            {
                "mode": "validation",
                "repo_root": tmp_path,
                "run_root": run_root,
                "skill": "sample-skill",
                "metadata": {"mode": "validation", "run_id": "run", "skill": "sample-skill", "eval_kind": eval_kind},
                "results": [validation],
            },
            {
                "mode": "with_skill",
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

    return (run_root / "report.md").read_text(encoding="utf-8")


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
        expect=RuntimeExpectations(traces=ObserverExpectation(contains_any=["sample-service"])),
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


def write_loaded_skill(root: Path, skill: str) -> None:
    skill_dir = root / ".agents" / "skills" / skill
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"name: {skill}\n", encoding="utf-8")


def empty_trace(tmp_path: Path) -> Path:
    path = tmp_path / "trace.jsonl"
    path.write_text("", encoding="utf-8")
    return path
