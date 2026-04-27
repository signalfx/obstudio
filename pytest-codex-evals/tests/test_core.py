from __future__ import annotations

import json
import sys
from pathlib import Path

from pytest_codex_evals.ab import side_prompt
from pytest_codex_evals.config import load_settings
from pytest_codex_evals.deterministic import grade_deterministic
from pytest_codex_evals.models import CaseResult, DeterministicCheck, EvalCase, GradeCheckResult, GradeResult, SideResult
from pytest_codex_evals.models import ValidationResult
from pytest_codex_evals.report import write_ab_reports, write_combined_session_reports, write_side_reports
from pytest_codex_evals.runtime import cleanup_runtime_sources, prepare_runtime_sources
from pytest_codex_evals.trace import parse_trace


def test_side_prompt_generates_loaded_and_not_loaded_variants():
    case = EvalCase(
        id="sample/service/sample-skill/direct",
        base_id="sample/service/sample-skill",
        prompt_id="direct",
        skill="sample-skill",
        language="sample",
        service="service",
        task="Scan the service.",
        fixture_dir=Path("fixture"),
    )

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

        [qualitative]
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
    assert settings.qualitative_enabled is False
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


def test_command_backed_deterministic_check(tmp_path: Path):
    service_dir = tmp_path / "service"
    service_dir.mkdir()
    (service_dir / "package.json").write_text(
        json.dumps({"dependencies": {"@opentelemetry/sdk-node": "latest"}}),
        encoding="utf-8",
    )
    case = EvalCase(
        id="sample/service/sample-skill/direct",
        base_id="sample/service/sample-skill",
        prompt_id="direct",
        skill="sample-skill",
        language="sample",
        service="service",
        task="Scan the service.",
        deterministic_checks=[
            DeterministicCheck(
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
        ],
    )

    grade = grade_deterministic(case, tmp_path, "done", parse_trace(empty_trace(tmp_path)), "with_skill")

    check = next(item for item in grade.checks if item.id == "npm-pkg-dependency")
    assert check.passed
    assert "package.json" in check.evidence


def test_runtime_check_is_skipped_until_enabled(tmp_path: Path):
    (tmp_path / "service").mkdir()
    case = EvalCase(
        id="sample/service/sample-skill/direct",
        base_id="sample/service/sample-skill",
        prompt_id="direct",
        skill="sample-skill",
        language="sample",
        service="service",
        task="Exercise runtime telemetry.",
        deterministic_checks=[
            DeterministicCheck(
                id="observer-runtime",
                description="Runtime telemetry reaches Observer.",
                kind="observer_docker_runtime",
                runtime={"expect": {"traces": {"contains_any": ["sample-service"]}}},
            )
        ],
    )

    grade = grade_deterministic(case, tmp_path, "done", parse_trace(empty_trace(tmp_path)), "with_skill")

    check = next(item for item in grade.checks if item.id == "observer-runtime")
    assert check.category == "runtime"
    assert check.skipped
    assert grade.total == 2


def test_runtime_source_copies_are_staged_under_service_dir(tmp_path: Path):
    repo_root = tmp_path / "repo"
    observer = repo_root / "observer"
    observer.mkdir(parents=True)
    (observer / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (observer / "ignored.pyc").write_text("", encoding="utf-8")
    service_dir = tmp_path / "service"
    service_dir.mkdir()

    staged = prepare_runtime_sources(
        {"source_copies": [{"from": "observer", "to": ".codex-runtime/observer"}]},
        service_dir,
        repo_root,
    )

    assert staged == [service_dir / ".codex-runtime" / "observer"]
    assert (staged[0] / "Dockerfile").is_file()
    assert not (staged[0] / "ignored.pyc").exists()
    cleanup_runtime_sources(staged)
    assert not staged[0].exists()


def empty_trace(tmp_path: Path) -> Path:
    path = tmp_path / "trace.jsonl"
    path.write_text("", encoding="utf-8")
    return path


def test_deterministic_file_and_final_checks(tmp_path: Path):
    service = tmp_path / "service"
    service.mkdir()
    (service / "pyproject.toml").write_text("opentelemetry-api\nopentelemetry-sdk\n", encoding="utf-8")
    skills_dir = tmp_path / ".agents" / "skills"
    (skills_dir / "otel-instrument").mkdir(parents=True)
    (skills_dir / "otel-instrument" / "SKILL.md").write_text("name: otel-instrument\n", encoding="utf-8")
    case = EvalCase(
        id="python/example/instrument",
        base_id="python/example/instrument",
        prompt_id="direct",
        skill="otel-instrument",
        language="python",
        service="example",
        task="Add OpenTelemetry instrumentation.",
        deterministic_checks=[
            DeterministicCheck(
                id="deps",
                description="deps",
                kind="file_contains_all",
                path="pyproject.toml",
                values=["opentelemetry-api", "opentelemetry-sdk"],
            ),
            DeterministicCheck(
                id="final",
                description="final",
                kind="final_contains_all",
                values=["verified"],
            ),
        ],
    )
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text("", encoding="utf-8")
    grade = grade_deterministic(case, tmp_path, "verified", parse_trace(trace_path), "with_skill")
    assert grade.pass_rate == 1.0


def test_baseline_checks_skill_absence(tmp_path: Path):
    (tmp_path / "service").mkdir()
    case = EvalCase(
        id="python/example/audit",
        base_id="python/example/audit",
        prompt_id="direct",
        skill="otel-audit",
        language="python",
        service="example",
        task="Scan for observability gaps.",
    )
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text("", encoding="utf-8")
    grade = grade_deterministic(case, tmp_path, "done", parse_trace(trace_path), "baseline")
    check_ids = {check.id for check in grade.checks}
    assert "skills-not-loaded" in check_ids
    assert grade.pass_rate == 1.0


def test_ab_report_writes_mode_specific_and_legacy_paths(tmp_path: Path):
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    grade = GradeResult(checks=[GradeCheckResult(id="check", description="check", passed=True)])
    side = SideResult(
        side="with_skill",
        exit_code=0,
        trace_path="trace.jsonl",
        final_message_path="last_message.md",
        deterministic_grade=grade,
    )
    baseline = SideResult(
        side="baseline",
        exit_code=0,
        trace_path="trace.jsonl",
        final_message_path="last_message.md",
        deterministic_grade=grade,
    )
    result = CaseResult(
        id="sample/service/sample-skill/direct",
        base_id="sample/service/sample-skill",
        prompt_id="direct",
        skill="sample-skill",
        language="sample",
        service="service",
        with_skill=side,
        baseline=baseline,
    )

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
    side = SideResult(
        side="with_skill",
        exit_code=0,
        trace_path="trace.jsonl",
        final_message_path="last_message.md",
        deterministic_grade=grade,
    )
    result = CaseResult(
        id="sample/service/sample-skill/direct",
        base_id="sample/service/sample-skill",
        prompt_id="direct",
        skill="sample-skill",
        language="sample",
        service="service",
        with_skill=side,
    )

    write_side_reports(tmp_path, run_root, "sample-skill", "with_skill", [result])

    assert (run_root / "with_skill-report.md").is_file()
    assert (run_root / "with_skill-benchmark.json").is_file()
    assert (run_root / "results" / "sample" / "service" / "sample-skill" / "with_skill.json").is_file()
    assert (run_root / "results" / "sample" / "service" / "sample-skill" / "with_baseline.json").is_file()
    benchmark = json.loads((run_root / "with_skill-benchmark.json").read_text(encoding="utf-8"))
    assert benchmark["mode"] == "with_skill"
    assert benchmark["evals"][0]["with_baseline"] is None
    assert benchmark["failures"][0]["result"] == "deterministic:check FAIL"
    report = (run_root / "with_skill-report.md").read_text(encoding="utf-8")
    assert "| sample/service/sample-skill | sample/service | 1 | 0% (0/1) | - | 0 | 0.0s | - | - | - | - |" in report
    assert "deterministic:check FAIL" in report


def test_combined_report_has_validation_and_runtime_sections(tmp_path: Path):
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    deterministic = GradeCheckResult(id="file", description="file", passed=True)
    runtime = GradeCheckResult(id="observer", description="observer", passed=True, category="runtime")
    side = SideResult(
        side="with_skill",
        exit_code=0,
        trace_path="trace.jsonl",
        final_message_path="last_message.md",
        deterministic_grade=GradeResult(checks=[deterministic, runtime]),
        duration_seconds=12.3,
        tokens=456,
    )
    case = CaseResult(
        id="sample/service/sample-skill/direct",
        base_id="sample/service/sample-skill",
        prompt_id="direct",
        skill="sample-skill",
        language="sample",
        service="service",
        with_skill=side,
    )
    validation = ValidationResult(
        id=case.id,
        base_id=case.base_id,
        prompt_id=case.prompt_id,
        skill=case.skill,
        language=case.language,
        service=case.service,
        definition_path=str(tmp_path / "sample_eval.json"),
        fixture_dir=str(tmp_path),
        skill_path=str(tmp_path / "skills" / "sample-skill"),
        deterministic_check_count=1,
        qualitative_check_count=0,
        runtime_check_count=1,
    )

    write_combined_session_reports(
        [
            {
                "mode": "validation",
                "repo_root": tmp_path,
                "run_root": run_root,
                "skill": "sample-skill",
                "metadata": {"mode": "validation", "run_id": "run", "skill": "sample-skill"},
                "results": [validation],
            },
            {
                "mode": "with_skill",
                "repo_root": tmp_path,
                "run_root": run_root,
                "skill": "sample-skill",
                "metadata": {"mode": "with_skill", "run_id": "run", "skill": "sample-skill", "agent_model": "gpt-test"},
                "results": [case],
            },
        ]
    )

    report = (run_root / "report.md").read_text(encoding="utf-8")
    assert "## Validation" in report
    assert "## Deterministic" in report
    assert "## Qualitative" in report
    assert "## Runtime" in report
    assert "| with_skill | sample/service/sample-skill | sample/service | 1 | 100% (1/1) | 456 | 12.3s | - | - | - |" in report
