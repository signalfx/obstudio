from __future__ import annotations

import json
from pathlib import Path

from pytest_codex_evals.ab import side_prompt
from pytest_codex_evals.config import load_settings
from pytest_codex_evals.deterministic import grade_deterministic
from pytest_codex_evals.models import CaseResult, DeterministicCheck, EvalCase, GradeCheckResult, GradeResult, SideResult
from pytest_codex_evals.report import write_ab_reports
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
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.live_ab is True
    assert settings.qualitative_enabled is False
    assert settings.agent_model == "gpt-5.2"
    assert settings.judge_model == "gpt-5.4"


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
    benchmark = json.loads((run_root / "ab-benchmark.json").read_text(encoding="utf-8"))
    assert benchmark["mode"] == "ab"
    assert (tmp_path / "eval-reports" / "sample-skill" / "AB_REPORT.md").is_file()
