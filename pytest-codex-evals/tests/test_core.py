from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from jsonschema.exceptions import ValidationError as JSONSchemaValidationError

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
    TokenUsage,
    ValidationResult,
)
from pytest_codex_evals.graders.rubric import rubric_prompt, run_rubric_dimensions, run_rubric_grade
from pytest_codex_evals.backends import (
    AgentResult,
    ClaudeBackend,
    CodexBackend,
    CursorBackend,
    StreamedCommandResult,
    _codex_subprocess_env,
    _extract_claude_final_message,
    _parse_claude_trace,
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
    LEGACY_SHARED_REFERENCE_CONSUMERS,
    aggregate_usage,
    build_kind_benchmark,
    compact_token_count,
    evaluator_semantics_version,
    format_tokens,
    kind_report_metadata,
    report_metadata,
    legacy_shared_reference_consumers,
    load_rubric_grade,
    normalize_rubric_score,
    render_reports_for_run_root,
    source_input_digests,
    source_inputs_match_for_skill,
    source_manifest_digest,
    usage_status,
    verify_published_report_sources,
    write_session_results,
)
from pytest_codex_evals.plugin import (
    case_from_definition,
    load_eval_definition,
    validate_live_result,
    validation_result,
)
from pytest_codex_evals.runner import (
    prepare_side_workspace,
    run_case,
    token_usage_from_trace_usage,
)
from pytest_codex_evals.trace import (
    TraceSummary,
    TraceUsage,
    extract_usage,
    parse_trace,
)


TOKEN_USAGE_FIXTURES = Path(__file__).parent / "fixtures" / "token_usage"


@pytest.fixture(autouse=True)
def evaluator_semantics_fixture(tmp_path: Path):
    path = tmp_path / "evals" / "evaluator-semantics.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("version = 1\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("contents", "error"),
    [
        ("version = [", "evaluator semantics file contains invalid TOML"),
        ("other = 1\n", "evaluator semantics version is missing"),
        ('version = "1"\n', "evaluator semantics version must be a positive integer"),
        ("version = 0\n", "evaluator semantics version must be a positive integer"),
        ("version = -1\n", "evaluator semantics version must be a positive integer"),
    ],
)
def test_evaluator_semantics_version_rejects_invalid_configuration(
    tmp_path: Path, contents: str | None, error: str
):
    path = tmp_path / "evals" / "evaluator-semantics.toml"
    if contents is None:
        path.unlink()
    else:
        path.write_text(contents, encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        evaluator_semantics_version(tmp_path)


def test_evaluator_semantics_version_defaults_when_not_configured(tmp_path: Path):
    (tmp_path / "evals" / "evaluator-semantics.toml").unlink()

    assert evaluator_semantics_version(tmp_path) == 1


def test_evaluator_semantics_version_rejects_invalid_encoding(tmp_path: Path):
    path = tmp_path / "evals" / "evaluator-semantics.toml"
    path.write_bytes(b"\xff")
    with pytest.raises(ValueError, match="cannot read evaluator semantics file"):
        evaluator_semantics_version(tmp_path)


def test_side_prompt_generates_loaded_and_not_loaded_variants():
    case = sanity_case(task="Scan the service.")

    assert side_prompt(case, "with_skill") == (
        "Use the $sample-skill skill. Before doing or saying anything else, run exactly "
        "this one read-only command and wait for it to complete: cat "
        ".agents/skills/sample-skill/SKILL.md. Do not combine that read with pwd or any "
        "other command, and do not emit commentary before or during the read. Then "
        "follow the skill. Scan the service."
    )
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


@pytest.mark.parametrize("strict_output", [False, True])
def test_case_preserves_prompt_eval_inputs(tmp_path: Path, strict_output: bool):
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
        strict_rubric_output=strict_output,
        fixture_dir=tmp_path,
    )

    case = case_from_definition(
        definition,
        prompt,
        tmp_path / "eval" / "qual" / "instrument.json",
    )

    assert case.eval_inputs == ["eval/inputs/otel-audit.json"]
    assert case.strict_rubric_output is strict_output


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
    (fixture_dir / "eval" / "qual" / "audit.json").write_text("{}\n", encoding="utf-8")

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


def test_prepare_side_workspace_rejects_symlinked_fixture_source(tmp_path: Path):
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("print('outside')\n", encoding="utf-8")
    (fixture_dir / "app.py").symlink_to(outside)
    case = sanity_case(fixture_dir=fixture_dir)

    with pytest.raises(ValueError, match="eval source input.*symlink"):
        prepare_side_workspace(
            tmp_path,
            case,
            "baseline",
            tmp_path / "run",
        )


@pytest.mark.parametrize(
    "link_directory",
    [
        False,
        True,
    ],
)
def test_skill_source_symlinks_are_rejected_before_exposure_or_manifesting(
    tmp_path: Path,
    link_directory: bool,
):
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    skill_dir = tmp_path / "skills" / "sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("name: sample-skill\n", encoding="utf-8")
    outside = tmp_path / ("outside" if link_directory else "outside.md")
    if link_directory:
        outside.mkdir()
        (outside / "instructions.md").write_text(
            "outside instructions\n", encoding="utf-8"
        )
    else:
        outside.write_text("outside instructions\n", encoding="utf-8")
    (skill_dir / "reference").symlink_to(
        outside,
        target_is_directory=link_directory,
    )
    case = sanity_case(
        fixture_dir=fixture_dir,
        skill="sample-skill",
    )

    with pytest.raises(ValueError, match="symlink"):
        prepare_side_workspace(
            tmp_path,
            case,
            "with_skill",
            tmp_path / "run",
        )
    with pytest.raises(ValueError, match="symlink"):
        source_input_digests(tmp_path, "sample-skill", "rubric", skill_dir)


def test_ignored_skill_sources_are_neither_exposed_nor_manifested(tmp_path: Path):
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    skill_dir = tmp_path / "skills" / "sample-skill"
    cache_dir = skill_dir / "__pycache__"
    cache_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("name: sample-skill\n", encoding="utf-8")
    outside = tmp_path / "outside.pyc"
    outside.write_bytes(b"outside bytecode")
    (skill_dir / "ignored.pyc").symlink_to(outside)
    (cache_dir / "linked.pyc").symlink_to(outside)
    case = sanity_case(fixture_dir=fixture_dir, skill="sample-skill")

    run_dir = tmp_path / "run"
    prepare_side_workspace(tmp_path, case, "with_skill", run_dir)
    staged_skill = run_dir / ".agents" / "skills" / "sample-skill"

    assert not staged_skill.is_symlink()
    assert not (staged_skill / "ignored.pyc").exists()
    assert not (staged_skill / "__pycache__").exists()
    assert list(source_input_digests(tmp_path, "sample-skill", "rubric", skill_dir)) == [
        "skills/sample-skill/SKILL.md"
    ]


def test_source_manifest_rejects_symlinked_eval_config(tmp_path: Path):
    skill_dir = tmp_path / "skills" / "sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("name: sample-skill\n", encoding="utf-8")
    outside = tmp_path / "outside-input"
    outside.write_text("outside input\n", encoding="utf-8")
    linked = tmp_path / "evals" / "codex-evals.linked.toml"
    linked.parent.mkdir(parents=True, exist_ok=True)
    linked.symlink_to(outside)

    with pytest.raises(ValueError, match="symlink"):
        source_input_digests(
            tmp_path,
            "sample-skill",
            "rubric",
            skill_dir,
            linked,
        )


@pytest.mark.parametrize("selected", [False, True])
def test_shared_rubric_extends_without_replacement_and_binds_source(tmp_path, selected):
    skill = tmp_path / "skills/sample-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("name: sample-skill\n")
    fixture = tmp_path / "evals/python/example"
    directory = fixture / "eval/qual"
    directory.mkdir(parents=True)
    base = tmp_path / "evals/common.json"
    common = {"rubric": ["Common first.", "Common second."],
              "judge_inputs": ["Read answer.md."], "strict_rubric_output": True}
    base.write_text(json.dumps(common))
    path = directory / "shared.json"
    leaf = {"skill": "sample-skill", "prompts": [{"id": "direct", "task": "Assess the service.", "eval_inputs": []}],
            "rubric_base": "../../../../common.json", "rubric_additions": {"rubric-2": "Selected second obligation."}}
    path.write_text(json.dumps(leaf))
    definition = load_eval_definition(path)
    assert definition.rubric == ["Common first.", "Common second.\n\nSelected second obligation."]
    assert definition.judge_inputs == common["judge_inputs"] and definition.strict_rubric_output
    assert "rubric_base" not in definition.model_dump()
    case = case_from_definition(definition, definition.prompts[0], path)
    workspace = tmp_path / "actor"
    prepare_side_workspace(tmp_path, case, "with_skill", workspace)
    assert not (workspace / "service/eval").exists()
    assert not (workspace / "common.json").exists()

    kwargs = {"definition_path": path, "fixture_dir": fixture, "prompt_id": "direct", "eval_inputs": []} if selected else {}
    before = source_input_digests(tmp_path, "sample-skill", "rubric", skill, **kwargs)
    assert "evals/common.json" in before
    common["rubric"][0] = "Changed common obligation."
    base.write_text(json.dumps(common))
    after = source_input_digests(tmp_path, "sample-skill", "rubric", skill, **kwargs)
    assert before != after
    assert load_eval_definition(path).rubric[0] == "Changed common obligation."


@pytest.mark.parametrize("fault", ["missing", "escape", "absolute", "symlink", "directory_symlink", "nested", "unknown_id", "invalid_id",
                                    "replace_rubric", "replace_inputs", "replace_strict", "replace_prompt", "replace_dimensions", "invalid_base", "invalid_json", "inline_additions", "inside_fixture", "fixture_eval_input"])
def test_shared_rubric_rejects_invalid_sources_and_common_overrides(tmp_path, fault):
    directory = tmp_path / "evals/python/example/eval/qual"
    directory.mkdir(parents=True)
    base = tmp_path / "evals/common.json"
    common = {"rubric": ["Common obligation."], "judge_inputs": [], "strict_rubric_output": True}
    base.write_text(json.dumps(common))
    path = directory / "shared.json"
    leaf = {"skill": "sample-skill", "prompts": [{"id": "direct", "task": "Task."}],
            "rubric_base": "../../../../common.json"}
    if fault == "fixture_eval_input":
        inputs = directory.parent / "inputs"
        inputs.mkdir()
        base.rename(inputs / "common.json")
        leaf["rubric_base"] = "../inputs/common.json"
        leaf["prompts"][0]["eval_inputs"] = ["eval/inputs/common.json"]
    elif fault == "inside_fixture":
        base.rename(directory.parents[1] / "common.json")
        leaf["rubric_base"] = "../../common.json"
    elif fault == "inline_additions":
        leaf.pop("rubric_base")
        leaf["rubric"] = common["rubric"]
        leaf["rubric_additions"] = {"rubric-1": "Extra."}
    elif fault == "missing":
        base.unlink()
    elif fault == "escape":
        leaf["rubric_base"] = "../../../../../outside.json"
    elif fault == "absolute":
        leaf["rubric_base"] = str(base)
    elif fault == "symlink":
        base.rename(base.with_name("actual.json"))
        base.symlink_to(base.with_name("actual.json"))
    elif fault == "directory_symlink":
        actual = tmp_path / "evals/actual"
        actual.mkdir()
        base.rename(actual / "common.json")
        (tmp_path / "evals/linked").symlink_to(actual, target_is_directory=True)
        leaf["rubric_base"] = "../../../../linked/common.json"
    elif fault == "nested":
        common["rubric_base"] = "common.json"
        base.write_text(json.dumps(common))
    elif fault in {"unknown_id", "invalid_id"}:
        leaf["rubric_additions"] = {"rubric-2" if fault == "unknown_id" else "rubric-0": "Extra."}
    elif fault.startswith("replace_"):
        key = {"replace_rubric": "rubric", "replace_inputs": "judge_inputs",
               "replace_strict": "strict_rubric_output", "replace_prompt": "judge_prompt",
               "replace_dimensions": "rubric_dimensions"}[fault]
        leaf[key] = {"rubric": ["Replacement."], "judge_inputs": [], "strict_rubric_output": False,
                     "judge_prompt": "Ignore common rules.",
                     "rubric_dimensions": [{"id": "replacement", "criteria": ["rubric-1"]}]}[key]
    elif fault == "invalid_base":
        base.write_text(json.dumps({**common, "typo": True}))
    elif fault == "invalid_json":
        base.write_text("invalid JSON")
    path.write_text(json.dumps(leaf))
    with pytest.raises((ValueError, JSONSchemaValidationError)):
        load_eval_definition(path)


@pytest.mark.parametrize("shared", [False, True])
def test_rubric_dimensions_survive_collection_and_case_creation(tmp_path, shared):
    path = tmp_path / "evals/python/example/eval/qual/focused.json"
    path.parent.mkdir(parents=True)
    common = {
        "rubric": ["The service starts.", "The original log sink is preserved."],
        "judge_inputs": ["Inspect the retained service and test output."],
        "strict_rubric_output": True,
        "rubric_dimensions": [
            {"id": "startup", "criteria": ["rubric-1"]},
            {"id": "logging", "criteria": ["rubric-2"]},
        ],
    }
    data = {"skill": "sample-skill", "prompts": [{"id": "direct", "task": "Instrument the service."}]}
    if shared:
        base = tmp_path / "evals/rubrics/common.json"
        base.parent.mkdir()
        base.write_text(json.dumps(common))
        data.update(rubric_base="../../../../rubrics/common.json", rubric_additions={"rubric-2": "Keep stderr output."})
    else:
        data.update(common)
    path.write_text(json.dumps(data))

    definition = load_eval_definition(path)
    case = case_from_definition(definition, definition.prompts[0], path)

    assert [dimension.model_dump() for dimension in case.rubric_dimensions] == common["rubric_dimensions"]
    assert case.rubric_dimensions == definition.rubric_dimensions
    assert case.rubric[0] == common["rubric"][0]
    assert case.rubric[1].endswith("Keep stderr output.") is shared


@pytest.mark.parametrize("fault", [
    "non-strict", "duplicate-dimension", "duplicate-criterion", "missing-criterion",
    "unknown-criterion", "empty-dimensions", "empty-criteria", "unsafe-id", "extra-field",
])
def test_rubric_dimensions_reject_ambiguous_or_non_strict_partitions(tmp_path, fault):
    path = tmp_path / "evals/python/example/eval/qual/focused.json"
    path.parent.mkdir(parents=True)
    data = {
        "skill": "sample-skill", "prompts": [{"id": "direct", "task": "Instrument the service."}],
        "rubric": ["The service starts.", "The original log sink is preserved."],
        "strict_rubric_output": True,
        "rubric_dimensions": [
            {"id": "startup", "criteria": ["rubric-1"]},
            {"id": "logging", "criteria": ["rubric-2"]},
        ],
    }
    dimensions = data["rubric_dimensions"]
    if fault == "non-strict":
        data["strict_rubric_output"] = False
    elif fault == "duplicate-dimension":
        dimensions[1]["id"] = dimensions[0]["id"]
    elif fault == "duplicate-criterion":
        dimensions[1]["criteria"].append("rubric-1")
    elif fault == "missing-criterion":
        dimensions.pop()
    elif fault == "unknown-criterion":
        dimensions[1]["criteria"] = ["rubric-3"]
    elif fault == "empty-dimensions":
        data["rubric_dimensions"] = []
    elif fault == "empty-criteria":
        dimensions[1]["criteria"] = []
    elif fault == "unsafe-id":
        dimensions[1]["id"] = "../logging"
    else:
        dimensions[1]["weight"] = 2
    path.write_text(json.dumps(data))

    with pytest.raises((ValueError, JSONSchemaValidationError)):
        load_eval_definition(path)


def test_codex_subprocess_env_uses_sandbox_local_package_caches(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("UV_CACHE_DIR", "/outside/uv-cache")
    monkeypatch.setenv("PIP_CACHE_DIR", "/outside/pip-cache")

    env = _codex_subprocess_env(tmp_path)

    assert env["UV_CACHE_DIR"] == str(tmp_path / ".uv-cache")
    assert env["PIP_CACHE_DIR"] == str(tmp_path / ".pip-cache")


def test_codex_subprocess_env_uses_isolated_eval_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    eval_home = tmp_path / "codex-home"
    eval_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", "/personal/codex-home")
    monkeypatch.setenv("CODEX_EVAL_HOME", str(eval_home))

    env = _codex_subprocess_env()

    assert env["CODEX_HOME"] == str(eval_home.resolve())


def test_codex_subprocess_env_rejects_missing_eval_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CODEX_EVAL_HOME", str(tmp_path / "missing-codex-home"))

    with pytest.raises(ValueError, match="make eval-codex-home"):
        _codex_subprocess_env()


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
    assert (
        captured[captured.index("--config") + 1]
        == "shell_environment_policy.inherit=all"
    )
    assert captured[captured.index("--sandbox") + 1] == "workspace-write"
    assert "--approve-for-me" not in captured


def test_claude_backend_extracts_final_message_after_oversized_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    oversized = "9" * 5000
    raw = (
        '[{"type":"result","usage":{"total_tokens":'
        + oversized
        + '}},{"type":"result","result":"done","usage":{"total_tokens":7}}]'
    )

    def fake_run(_command, *, stdout_path: Path, stderr_path: Path, **_kwargs):
        stdout_path.write_text(raw, encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return StreamedCommandResult(returncode=0, stdout=raw, stderr="")

    monkeypatch.setattr("pytest_codex_evals.backends.run_streamed_command", fake_run)

    result = ClaudeBackend(command="claude").run_agent(
        prompt="Run the skill.",
        exec_dir=tmp_path,
    )

    assert result.final_message_path.read_text(encoding="utf-8") == "done"
    trace = ClaudeBackend().parse_trace(result.trace_path)
    assert len(trace.events) == 2
    assert trace.usage.usage_record_count == 2
    assert trace.usage.provider_total_tokens == 7


def test_claude_backend_preserves_result_with_oversized_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    raw = (
        '{"type":"result","result":"done","usage":{"total_tokens":'
        + ("9" * 5000)
        + "}}"
    )

    def fake_run(_command, *, stdout_path: Path, stderr_path: Path, **_kwargs):
        stdout_path.write_text(raw, encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return StreamedCommandResult(returncode=0, stdout=raw, stderr="")

    monkeypatch.setattr("pytest_codex_evals.backends.run_streamed_command", fake_run)

    result = ClaudeBackend(command="claude").run_agent(
        prompt="Run the skill.",
        exec_dir=tmp_path,
    )

    assert result.final_message_path.read_text(encoding="utf-8") == "done"
    trace = ClaudeBackend().parse_trace(result.trace_path)
    assert len(trace.events) == 1
    assert trace.usage.observed is True
    assert trace.usage.recognized is False


def test_codex_and_claude_judges_disable_provider_telemetry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"result": "ok", "usage": {"total_tokens": 1}}),
            stderr="",
        )

    monkeypatch.setattr("pytest_codex_evals.backends.subprocess.run", fake_run)

    CodexBackend(
        command="codex",
        extra_args=["--config", 'otel.exporter="otlp"'],
    ).run_judge(prompt="Grade it.", exec_dir=tmp_path)
    ClaudeBackend(command="claude").run_judge(prompt="Grade it.", exec_dir=tmp_path)

    codex_command, codex_kwargs = calls[0]
    assert 'otel.exporter="none"' in codex_command
    assert 'otel.trace_exporter="none"' in codex_command
    assert codex_command.index('otel.exporter="none"') > codex_command.index(
        'otel.exporter="otlp"'
    )
    assert codex_kwargs["env"]["OTEL_SDK_DISABLED"] == "true"
    assert codex_kwargs["env"]["OTEL_LOGS_EXPORTER"] == "none"
    assert codex_kwargs["env"]["OTEL_TRACES_EXPORTER"] == "none"
    assert codex_kwargs["env"]["OTEL_METRICS_EXPORTER"] == "none"

    _, claude_kwargs = calls[1]
    assert claude_kwargs["env"]["OTEL_SDK_DISABLED"] == "true"
    assert claude_kwargs["env"]["OTEL_LOGS_EXPORTER"] == "none"
    assert claude_kwargs["env"]["OTEL_TRACES_EXPORTER"] == "none"
    assert claude_kwargs["env"]["OTEL_METRICS_EXPORTER"] == "none"
    assert claude_kwargs["env"]["CLAUDE_CODE_ENABLE_TELEMETRY"] == "0"
    assert claude_kwargs["env"]["CLAUDE_CODE_ENHANCED_TELEMETRY_BETA"] == "0"


def test_trace_parser_extracts_commands_and_tokens(tmp_path: Path):
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "command": "npm install",
                            "status": "completed",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 3,
                            "output_tokens": 4,
                            "total_tokens": 7,
                        },
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    trace = parse_trace(trace_path)
    assert [command.command for command in trace.commands] == ["npm install"]
    assert trace.usage.total_tokens == 7


def test_codex_usage_prefers_cumulative_record_without_double_counting():
    trace = parse_trace(TOKEN_USAGE_FIXTURES / "codex-cumulative.jsonl")

    assert len(trace.events) == 2
    assert trace.usage.provider == "codex"
    assert trace.usage.source == "cumulative"
    assert trace.usage.usage_record_count == 3
    assert trace.usage.selected_record_count == 1
    assert trace.usage.input_tokens == 120
    assert trace.usage.cached_input_tokens == 30
    assert trace.usage.cache_creation_input_tokens == 10
    assert trace.usage.output_tokens == 20
    assert trace.usage.reasoning_output_tokens == 8
    assert trace.usage.provider_total_tokens == 140
    assert trace.usage.derived_total_tokens == 140


def test_codex_usage_sums_incremental_records_when_no_cumulative_record_exists():
    trace = parse_trace(TOKEN_USAGE_FIXTURES / "codex-incremental.jsonl")

    assert trace.usage.source == "incremental"
    assert trace.usage.usage_record_count == 2
    assert trace.usage.selected_record_count == 2
    assert trace.usage.input_tokens == 30
    assert trace.usage.cached_input_tokens == 7
    assert trace.usage.cache_creation_input_tokens == 1
    assert trace.usage.output_tokens == 10
    assert trace.usage.reasoning_output_tokens == 3
    assert trace.usage.provider_total_tokens == 40
    assert trace.usage.derived_total_tokens == 40


def test_claude_usage_normalizes_cache_breakdown_and_prefers_result_total():
    trace = ClaudeBackend().parse_trace(TOKEN_USAGE_FIXTURES / "claude-cumulative.json")

    assert len(trace.events) == 3
    assert trace.usage.provider == "claude"
    assert trace.usage.source == "cumulative"
    assert trace.usage.usage_record_count == 3
    assert trace.usage.selected_record_count == 1
    assert trace.usage.input_tokens == 50
    assert trace.usage.cached_input_tokens == 30
    assert trace.usage.cache_creation_input_tokens == 8
    assert trace.usage.output_tokens == 14
    assert trace.usage.reasoning_output_tokens == 4
    assert trace.usage.provider_total_tokens is None
    assert trace.usage.derived_total_tokens == 64
    assert trace.usage.total_tokens == 64


def test_claude_usage_sums_incremental_records_without_a_result_record():
    trace = ClaudeBackend().parse_trace(
        TOKEN_USAGE_FIXTURES / "claude-incremental.jsonl"
    )

    assert trace.usage.source == "incremental"
    assert trace.usage.selected_record_count == 2
    assert trace.usage.input_tokens == 24
    assert trace.usage.cached_input_tokens == 8
    assert trace.usage.cache_creation_input_tokens == 10
    assert trace.usage.output_tokens == 12
    assert trace.usage.reasoning_output_tokens == 3
    assert trace.usage.derived_total_tokens == 36


def test_incremental_usage_preserves_per_record_provider_total_precedence(
    tmp_path: Path,
):
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 5,
                            "total_tokens": 20,
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "usage": {"input_tokens": 7, "output_tokens": 3},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    usage = parse_trace(trace_path).usage

    assert usage.provider_total_tokens is None
    assert usage.derived_total_tokens == 25
    assert usage.total_tokens == 30


def test_malformed_incremental_usage_preserves_recognized_fields_but_not_total(
    tmp_path: Path,
):
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "usage": {
                            "input_tokens": 6,
                            "output_tokens": 4,
                            "total_tokens": 10,
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "usage": {"input_tokens": True},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    usage = parse_trace(trace_path).usage

    assert usage.observed is True
    assert usage.usage_record_count == 2
    assert usage.selected_record_count == 1
    assert usage.input_tokens == 6
    assert usage.output_tokens == 4
    assert usage.provider_total_tokens == 10
    assert usage.derived_total_tokens == 10
    assert usage.total_tokens is None


def test_effective_only_incremental_total_is_recognized_in_reports(tmp_path: Path):
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "usage": {"total_tokens": 20},
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "usage": {"input_tokens": 7, "output_tokens": 3},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    trace_usage = parse_trace(trace_path).usage
    usage = token_usage_from_trace_usage(trace_usage)
    aggregate = aggregate_usage([usage], expected_records=1)

    assert trace_usage.total_tokens == 30
    assert trace_usage.recognized is True
    assert usage.recognized is True
    assert aggregate is not None
    assert aggregate["coverage"]["recognized_count"] == 1
    assert usage_status(aggregate, 1) == "measured"
    assert format_tokens({"agent_usage": aggregate, "agent_tokens": 30}) == "30"


def test_usage_distinguishes_explicit_zero_unrecognized_and_absent(tmp_path: Path):
    zero = parse_trace(TOKEN_USAGE_FIXTURES / "explicit-zero.jsonl").usage
    unrecognized = parse_trace(TOKEN_USAGE_FIXTURES / "unrecognized.jsonl").usage
    missing_path = tmp_path / "missing.jsonl"
    missing_path.write_text('{"type":"turn.completed"}\n', encoding="utf-8")
    absent = parse_trace(missing_path).usage

    assert zero.observed is True
    assert zero.recognized is True
    assert zero.total_tokens == 0
    assert zero.cached_input_tokens == 0
    assert unrecognized.observed is True
    assert unrecognized.recognized is False
    assert unrecognized.total_tokens is None
    assert absent.observed is False
    assert absent.recognized is False
    assert absent.total_tokens is None


def test_usage_parser_preserves_raw_events_and_ignores_malformed_values():
    trace = parse_trace(TOKEN_USAGE_FIXTURES / "malformed.jsonl")

    assert "{not-json" in trace.raw_text
    assert len(trace.events) == 2
    assert trace.usage.observed is True
    assert trace.usage.usage_record_count == 2
    assert trace.usage.selected_record_count == 1
    assert trace.usage.provider_total_tokens == 7
    assert trace.usage.input_tokens is None
    assert trace.usage.output_tokens is None


def test_usage_parser_ignores_non_ascii_digit_strings(tmp_path: Path):
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": "²"}}) + "\n",
        encoding="utf-8",
    )

    usage = parse_trace(trace_path).usage

    assert usage.observed is True
    assert usage.recognized is False
    assert usage.input_tokens is None


def test_usage_parser_retains_oversized_json_integers_without_aborting(tmp_path: Path):
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        '{"type":"turn.completed","usage":{"total_tokens":'
        + ("9" * 5000)
        + "}}\n"
        + json.dumps({"type": "turn.completed", "usage": {"total_tokens": 7}})
        + "\n",
        encoding="utf-8",
    )

    trace = parse_trace(trace_path)

    assert len(trace.events) == 2
    assert trace.usage.usage_record_count == 2
    assert trace.usage.provider_total_tokens == 7


def test_usage_parser_preserves_event_with_oversized_usage_integer(tmp_path: Path):
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        '{"type":"item.completed","item":{"type":"command_execution",'
        '"command":"pytest","status":"completed"},"usage":{"total_tokens":'
        + ("9" * 5000)
        + "}}\n",
        encoding="utf-8",
    )

    trace = parse_trace(trace_path)

    assert len(trace.events) == 1
    assert [command.command for command in trace.commands] == ["pytest"]
    assert trace.usage.observed is True
    assert trace.usage.recognized is False
    assert trace.usage.usage_record_count == 1


def test_usage_parser_does_not_treat_oversized_integer_as_command_text(
    tmp_path: Path,
):
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        '{"type":"item.completed","item":{"type":"command_execution",'
        '"command":' + ("9" * 5000) + "}}\n",
        encoding="utf-8",
    )

    trace = parse_trace(trace_path)

    assert len(trace.events) == 1
    assert trace.commands == []


@pytest.mark.parametrize("pretty", [False, True])
def test_usage_parser_retains_oversized_json_integers_in_array_without_aborting(
    tmp_path: Path, pretty: bool
):
    trace_path = tmp_path / "trace.json"
    oversized = "9" * 5000
    if pretty:
        malformed = (
            '{\n  "type": "result",\n  "usage": {\n'
            f'    "total_tokens": {oversized}\n'
            "  }\n}"
        )
        valid = json.dumps({"type": "result", "usage": {"total_tokens": 7}}, indent=2)
        raw = "[\n  " + malformed.replace("\n", "\n  ") + ",\n  "
        raw += valid.replace("\n", "\n  ") + "\n]\n"
    else:
        malformed = '{"type":"result","usage":{"total_tokens":' + oversized + "}}"
        valid = json.dumps({"type": "result", "usage": {"total_tokens": 7}})
        raw = "[" + malformed + "," + valid + "]"
    trace_path.write_text(raw, encoding="utf-8")

    trace = ClaudeBackend().parse_trace(trace_path)

    assert len(trace.events) == 2
    assert trace.usage.usage_record_count == 2
    assert trace.usage.provider_total_tokens == 7


@pytest.mark.parametrize(
    ("provider", "event"),
    [
        ("codex", {"type": "turn.completed", "usage": []}),
        ("claude", {"type": "result", "usage": []}),
        (
            "codex",
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"total_token_usage": []},
                },
            },
        ),
        ("claude", {"message": {"usage": []}}),
    ],
)
def test_usage_parser_treats_malformed_usage_containers_as_unrecognized(
    provider: str,
    event: dict[str, object],
):
    usage = extract_usage([event], provider=provider)

    assert usage.observed is True
    assert usage.recognized is False
    assert usage.usage_record_count == 1


def test_codex_usage_falls_back_when_cumulative_record_is_unrecognized(tmp_path: Path):
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        json.dumps(
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {"input_tokens": True},
                        "last_token_usage": {
                            "input_tokens": 6,
                            "cached_input_tokens": 2,
                            "output_tokens": 4,
                            "total_tokens": 10,
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    usage = parse_trace(trace_path).usage

    assert usage.source == "incremental"
    assert usage.usage_record_count == 2
    assert usage.selected_record_count == 1
    assert usage.input_tokens == 6
    assert usage.cached_input_tokens == 2
    assert usage.total_tokens == 10


def test_usage_preserves_provider_and_derived_total_disagreement(tmp_path: Path):
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":5,"total_tokens":20}}\n',
        encoding="utf-8",
    )

    usage = parse_trace(trace_path).usage

    assert usage.provider_total_tokens == 20
    assert usage.derived_total_tokens == 15
    assert usage.total_tokens == 20


def test_trace_parser_deduplicates_command_lifecycle_and_preserves_other_actions(
    tmp_path: Path,
):
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.started",
                        "item": {
                            "id": "command-1",
                            "type": "command_execution",
                            "command": "cat SKILL.md",
                            "status": "in_progress",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "command-1",
                            "type": "command_execution",
                            "command": "cat SKILL.md",
                            "aggregated_output": "instructions\n",
                            "exit_code": 0,
                            "status": "completed",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "change-1",
                            "type": "file_change",
                            "status": "completed",
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    trace = parse_trace(trace_path)

    assert [(action.name, action.status) for action in trace.actions] == [
        ("command_execution", "completed"),
        ("file_change", "completed"),
    ]
    assert trace.actions[0].start_order == 0
    assert trace.actions[0].completion_order == 1
    assert [command.command for command in trace.commands] == ["cat SKILL.md"]


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
    skill_config.write_text('[run]\nmode = "with_skill"\n', encoding="utf-8")
    baseline_config = tmp_path / "codex-evals.baseline.toml"
    baseline_config.write_text('[run]\nmode = "with-baseline"\n', encoding="utf-8")

    assert load_settings(skill_config).run_mode == "with_skill"
    assert load_settings(baseline_config).run_mode == "with_baseline"


def test_config_loads_eval_kind(tmp_path: Path):
    config_path = tmp_path / "codex-evals.toml"
    config_path.write_text(
        '[run]\nmode = "with_skill"\neval_kind = "sanity"\n', encoding="utf-8"
    )

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
    config_path.write_text('[run]\nmode = "with_skill"\n', encoding="utf-8")

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

    grade = grade_sanity(
        case, tmp_path, "done", parse_trace(empty_trace(tmp_path)), "with_skill"
    )

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
        parse_trace(empty_trace(tmp_path)),
        "with_skill",
        runtime_enabled=False,
        repo_root=tmp_path,
    )

    check = next(item for item in grade.checks if item.id == "observer-runtime")
    assert check.category == "runtime"
    assert check.skipped
    assert grade.total == 3


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
    assert (
        service_url("http://127.0.0.1:49153", "/api/health")
        == "http://127.0.0.1:49153/api/health"
    )


def test_sanity_file_and_final_checks(tmp_path: Path):
    service = tmp_path / "service"
    service.mkdir()
    (service / "pyproject.toml").write_text(
        "opentelemetry-api\nopentelemetry-sdk\n", encoding="utf-8"
    )
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

    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        json.dumps(
            {
                "item": {
                    "type": "command_execution",
                    "command": "cat .agents/skills/otel-instrument/SKILL.md",
                    "aggregated_output": "name: otel-instrument\n",
                    "status": "completed",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    grade = grade_sanity(
        case, tmp_path, "verified", parse_trace(trace_path), "with_skill"
    )

    assert grade.pass_rate == 1.0


def test_with_skill_guard_fails_when_agent_does_not_read_instructions(tmp_path: Path):
    (tmp_path / "service").mkdir()
    write_loaded_skill(tmp_path, "otel-audit")
    case = sanity_case(
        skill="otel-audit",
        language="python",
        service="example",
        id="python/example/audit/direct",
        base_id="python/example/audit",
    )

    grade = grade_sanity(
        case, tmp_path, "done", parse_trace(empty_trace(tmp_path)), "with_skill"
    )

    instruction_check = next(
        check for check in grade.checks if check.id == "skill-instructions-read"
    )
    assert instruction_check.passed is False
    assert "Did not successfully read all" in instruction_check.evidence


def test_with_skill_guard_ignores_transport_error_before_skill_read(tmp_path: Path):
    write_loaded_skill(tmp_path, "otel-audit")
    events = [
        {
            "type": "item.completed",
            "item": {
                "id": "transport-1",
                "type": "error",
                "message": "Falling back from WebSockets to HTTPS transport",
            },
        },
        codex_command_event(
            "cat .agents/skills/otel-audit/SKILL.md",
            "completed",
            item_id="read-1",
            output="name: otel-audit\n",
        ),
    ]

    check = instruction_guard_check(tmp_path, events)

    assert check.passed is True


@pytest.mark.parametrize(
    ("command", "status"),
    [
        ("echo .agents/skills/otel-audit/SKILL.md", "completed"),
        ("cat .agents/skills/otel-audit/SKILL.md", "failed"),
    ],
)
def test_with_skill_guard_rejects_non_reading_or_failed_commands(
    tmp_path: Path,
    command: str,
    status: str,
):
    (tmp_path / "service").mkdir()
    write_loaded_skill(tmp_path, "otel-audit")
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        json.dumps(
            {
                "item": {
                    "type": "command_execution",
                    "command": command,
                    "status": status,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    case = sanity_case(
        skill="otel-audit",
        language="python",
        service="example",
        id="python/example/audit/direct",
        base_id="python/example/audit",
    )

    grade = grade_sanity(case, tmp_path, "done", parse_trace(trace_path), "with_skill")

    instruction_check = next(
        check for check in grade.checks if check.id == "skill-instructions-read"
    )
    assert instruction_check.passed is False


def test_with_skill_guard_rejects_read_after_another_completed_command(tmp_path: Path):
    (tmp_path / "service").mkdir()
    write_loaded_skill(tmp_path, "otel-audit")
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "item": {
                            "type": "command_execution",
                            "command": "rg --files service",
                            "status": "completed",
                        },
                    }
                ),
                json.dumps(
                    {
                        "item": {
                            "type": "command_execution",
                            "command": "cat .agents/skills/otel-audit/SKILL.md",
                            "aggregated_output": "name: otel-audit\n",
                            "status": "completed",
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    case = sanity_case(
        skill="otel-audit",
        language="python",
        service="example",
        id="python/example/audit/direct",
        base_id="python/example/audit",
    )

    grade = grade_sanity(case, tmp_path, "done", parse_trace(trace_path), "with_skill")

    instruction_check = next(
        check for check in grade.checks if check.id == "skill-instructions-read"
    )
    assert instruction_check.passed is False
    assert "before another action" in instruction_check.evidence


def test_with_skill_guard_rejects_successful_read_after_failed_first_read(
    tmp_path: Path,
):
    skill_path = write_loaded_skill(tmp_path, "otel-audit")
    events = [
        codex_command_event(
            "cat .agents/skills/otel-audit/SKILL.md", "failed", item_id="read-1"
        ),
        codex_command_event(
            "cat .agents/skills/otel-audit/SKILL.md",
            "completed",
            item_id="read-2",
            output="name: otel-audit\n",
        ),
    ]

    check = instruction_guard_check(tmp_path, events)

    assert skill_path.is_file()
    assert check.passed is False
    assert "before another action" in check.evidence


@pytest.mark.parametrize(
    ("command", "output"),
    [
        ("head -1 .agents/skills/otel-audit/SKILL.md", "name: otel-audit\n"),
        ("rg name .agents/skills/otel-audit/SKILL.md", "name: otel-audit\n"),
        ("sed -n '1,1p' .agents/skills/otel-audit/SKILL.md", "name: otel-audit\n"),
    ],
)
def test_with_skill_guard_rejects_head_rg_and_partial_reads(
    tmp_path: Path,
    command: str,
    output: str,
):
    skill_path = write_loaded_skill(tmp_path, "otel-audit")
    skill_path.write_text("name: otel-audit\nsecond: instruction\n", encoding="utf-8")

    check = instruction_guard_check(
        tmp_path,
        [codex_command_event(command, "completed", output=output, item_id="read-1")],
    )

    assert check.passed is False


def test_with_skill_guard_accepts_sed_only_when_output_is_the_complete_skill(
    tmp_path: Path,
):
    skill_path = write_loaded_skill(tmp_path, "otel-audit")
    skill_text = "name: otel-audit\nsecond: instruction\n"
    skill_path.write_text(skill_text, encoding="utf-8")
    command = "/bin/zsh -lc \"sed -n '1,240p' .agents/skills/otel-audit/SKILL.md\""

    check = instruction_guard_check(
        tmp_path,
        [
            codex_command_event(
                command, "completed", output=skill_text, item_id="read-1"
            )
        ],
    )

    assert check.passed is True


def test_with_skill_guard_accepts_contiguous_initial_sed_reads_through_eof(
    tmp_path: Path,
):
    skill_path = write_loaded_skill(tmp_path, "otel-audit")
    lines = [f"instruction {index}\n" for index in range(1, 310)]
    skill_path.write_text("".join(lines), encoding="utf-8")
    events = [
        codex_command_event(
            "sed -n '1,240p' .agents/skills/otel-audit/SKILL.md",
            "completed",
            output="".join(lines[:240]),
            item_id="read-1",
        ),
        codex_command_event(
            "sed -n '241,520p' .agents/skills/otel-audit/SKILL.md",
            "completed",
            output="".join(lines[240:]),
            item_id="read-2",
        ),
    ]

    check = instruction_guard_check(tmp_path, events)

    assert check.passed is True


def test_with_skill_guard_rejects_side_effecting_sed_even_with_full_output(
    tmp_path: Path,
):
    skill_path = write_loaded_skill(tmp_path, "otel-audit")
    skill_text = "name: otel-audit\nsecond: instruction\n"
    skill_path.write_text(skill_text, encoding="utf-8")
    command = (
        "sed -n -e '1,$p' -e 'w service/copied-skill' "
        ".agents/skills/otel-audit/SKILL.md"
    )

    check = instruction_guard_check(
        tmp_path,
        [
            codex_command_event(
                command, "completed", output=skill_text, item_id="read-1"
            )
        ],
    )

    assert check.passed is False


def test_claude_stream_trace_records_successful_read_and_extracts_result(
    tmp_path: Path,
):
    trace_path = tmp_path / "trace.jsonl"
    final_path = tmp_path / "last_message.md"
    events = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "read-1",
                        "name": "Read",
                        "input": {"file_path": ".agents/skills/otel-audit/SKILL.md"},
                    }
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "read-1", "content": "skill"}
                ],
            },
        },
        {
            "type": "result",
            "result": "done",
            "usage": {
                "input_tokens": 2,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "output_tokens": 1,
            },
        },
    ]
    trace_path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8"
    )

    trace = _parse_claude_trace(trace_path)
    _extract_claude_final_message(trace_path, final_path)

    assert [(command.command, command.status) for command in trace.commands] == [
        ("read .agents/skills/otel-audit/SKILL.md", "completed"),
    ]
    assert trace.usage.total_tokens == 3
    assert final_path.read_text(encoding="utf-8") == "done"


def test_claude_edit_before_read_is_preserved_and_fails_instruction_guard(
    tmp_path: Path,
):
    write_loaded_skill(tmp_path, "otel-audit")
    events = [
        claude_tool_use(
            "edit-1", "Edit", {"file_path": "service/app.py", "new_string": "changed"}
        ),
        claude_tool_result("edit-1", "updated"),
        claude_tool_use(
            "read-1", "Read", {"file_path": ".agents/skills/otel-audit/SKILL.md"}
        ),
        claude_tool_result("read-1", "name: otel-audit\n"),
    ]
    trace = write_claude_trace(tmp_path, events)

    check = instruction_guard_check(tmp_path, events, trace=trace)

    assert [action.name for action in trace.actions] == ["edit", "read"]
    assert check.passed is False
    assert "before another action" in check.evidence


def test_claude_truncated_read_fails_instruction_guard(tmp_path: Path):
    skill_path = write_loaded_skill(tmp_path, "otel-audit")
    skill_path.write_text("name: otel-audit\nsecond: instruction\n", encoding="utf-8")
    events = [
        claude_tool_use(
            "read-1",
            "Read",
            {
                "file_path": ".agents/skills/otel-audit/SKILL.md",
                "limit": 1,
            },
        ),
        claude_tool_result("read-1", "name: otel-audit\n"),
    ]

    check = instruction_guard_check(
        tmp_path, events, trace=write_claude_trace(tmp_path, events)
    )

    assert check.passed is False


def test_claude_unbounded_plain_text_read_must_match_complete_skill(tmp_path: Path):
    skill_path = write_loaded_skill(tmp_path, "otel-audit")
    skill_path.write_text("name: otel-audit\nsecond: instruction\n", encoding="utf-8")
    truncated_events = [
        claude_tool_use(
            "read-1", "Read", {"file_path": ".agents/skills/otel-audit/SKILL.md"}
        ),
        claude_tool_result("read-1", "name: otel-audit\n"),
    ]
    complete_events = [
        claude_tool_use(
            "read-2", "Read", {"file_path": ".agents/skills/otel-audit/SKILL.md"}
        ),
        claude_tool_result("read-2", skill_path.read_text(encoding="utf-8")),
    ]

    assert instruction_guard_check(
        tmp_path,
        truncated_events,
        trace=write_claude_trace(tmp_path, truncated_events),
    ).passed is False
    assert instruction_guard_check(
        tmp_path,
        complete_events,
        trace=write_claude_trace(tmp_path, complete_events),
    ).passed is True


def test_claude_completed_full_read_passes_instruction_guard(tmp_path: Path):
    write_loaded_skill(tmp_path, "otel-audit")
    events = [
        claude_tool_use(
            "read-1", "Read", {"file_path": ".agents/skills/otel-audit/SKILL.md"}
        ),
        claude_tool_result(
            "read-1",
            {
                "file": {
                    "filePath": "SKILL.md",
                    "startLine": 1,
                    "numLines": 1,
                    "totalLines": 1,
                },
            },
        ),
    ]

    check = instruction_guard_check(
        tmp_path, events, trace=write_claude_trace(tmp_path, events)
    )

    assert check.passed is True


def test_claude_read_must_complete_before_a_later_action_starts(tmp_path: Path):
    write_loaded_skill(tmp_path, "otel-audit")
    events = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "read-1",
                        "name": "Read",
                        "input": {"file_path": ".agents/skills/otel-audit/SKILL.md"},
                    },
                    {
                        "type": "tool_use",
                        "id": "edit-1",
                        "name": "Edit",
                        "input": {
                            "file_path": "service/app.py",
                            "new_string": "changed",
                        },
                    },
                ],
            },
        },
        claude_tool_result("read-1", "name: otel-audit\n"),
        claude_tool_result("edit-1", "updated"),
    ]

    check = instruction_guard_check(
        tmp_path, events, trace=write_claude_trace(tmp_path, events)
    )

    assert check.passed is False


def test_failed_loaded_side_guard_rejects_live_result(tmp_path: Path):
    failed_guard = GradeCheckResult(
        id="skill-instructions-read",
        description="read skill",
        passed=False,
        category="sanity",
    )
    passing_guards = [
        GradeCheckResult(
            id="final-message-present",
            description="final",
            passed=True,
            category="sanity",
        ),
        GradeCheckResult(
            id="skills-loaded", description="loaded", passed=True, category="sanity"
        ),
    ]
    result = case_result(
        side_result("with_skill", GradeResult(checks=[*passing_guards, failed_guard])),
        None,
    )

    with pytest.raises(
        AssertionError, match="with_skill guard failed: skill-instructions-read"
    ):
        validate_live_result(result)


def test_baseline_checks_skill_absence(tmp_path: Path):
    (tmp_path / "service").mkdir()
    case = sanity_case(
        skill="otel-audit",
        language="python",
        service="example",
        id="python/example/audit/direct",
        base_id="python/example/audit",
    )

    grade = grade_sanity(
        case, tmp_path, "done", parse_trace(empty_trace(tmp_path)), "baseline"
    )

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


@pytest.mark.parametrize("with_inputs, expected", [
    (False, (
        "Evaluate the completed eval run in this directory.\n"
        "\n"
        "Case: sample/service/rubric\n"
        "Prompt variant: direct\n"
        "Task: Assess the answer.\n"
        "\n"
        "Return only JSON matching the provided schema. Grade against this rubric:\n"
        "- Must cite evidence.\n"
        "- Check ownership.\n"
        "\n"
        "Set `score` to a 0-100 percentage-style quality score. Do not put the number\n"
        "of passed checks in `score`.\n"
        "Use check ids derived from the rubric order, such as rubric-1, rubric-2, etc.\n"
    )),
    (True, (
        "Evaluate the completed eval run in this directory.\n"
        "\n"
        "Case: sample/service/rubric\n"
        "Prompt variant: direct\n"
        "Task: Assess the answer.\n"
        "\n"
        "Suggested inputs:\n"
        "- Read ./answer.md.\n"
        "- Inspect ./result.json.\n"
        "\n"
        "Return only JSON matching the provided schema. Grade against this rubric:\n"
        "- Must cite evidence.\n"
        "- Check ownership.\n"
        "\n"
        "Set `score` to a 0-100 percentage-style quality score. Do not put the number\n"
        "of passed checks in `score`.\n"
        "Use check ids derived from the rubric order, such as rubric-1, rubric-2, etc.\n"
    )),
])
def test_legacy_default_rubric_prompt_preserves_exact_contract(with_inputs, expected):
    case = RubricEvalCase(
        id="sample/service/rubric/direct", base_id="sample/service/rubric", prompt_id="direct",
        skill="sample-skill", language="sample", service="service", task="Assess the answer.",
        rubric=["Must cite evidence.", "Check ownership."],
        judge_inputs=["Read ./answer.md.", "Inspect ./result.json."] if with_inputs else [],
    )

    assert rubric_prompt(case) == expected


def test_legacy_custom_rubric_prompt_preserves_exact_inputs_and_rubric():
    case = RubricEvalCase(
        id="sample/service/rubric/direct", base_id="sample/service/rubric", prompt_id="direct",
        skill="sample-skill", language="sample", service="service", task="Assess the answer.",
        rubric=["Must cite evidence.", "Check ownership."],
        judge_inputs=["Read ./answer.md.", "Inspect ./result.json."],
        judge_prompt='Case={case_id}; Prompt={prompt_id}; Task={task}\nInputs:\n{inputs}\nRubric:\n{rubric}',
    )
    expected = (
        "Case=sample/service/rubric; Prompt=direct; Task=Assess the answer.\n"
        "Inputs:\n"
        "- Read ./answer.md.\n"
        "- Inspect ./result.json.\n"
        "Rubric:\n"
        "- Must cite evidence.\n"
        "- Check ownership."
    )

    assert rubric_prompt(case) == expected


@pytest.mark.parametrize("custom_prompt", [None, "Dimension={dimension}; {task}\nInputs:\n{inputs}\nRubric:\n{rubric}"])
def test_dimension_grading_anchors_evidence_and_formats_only_assigned_criteria(tmp_path, custom_prompt):
    workspace = tmp_path / "task"
    workspace.mkdir()
    case = dimension_case(2, judge_prompt=custom_prompt,
                          judge_inputs=["Read ./answer.md.", "Inspect ./result.json."],
                          rubric_dimensions=[{"id": "second", "criteria": ["rubric-2"]},
                                             {"id": "first", "criteria": ["rubric-1"]}])
    backend = DimensionBackend([dimension_grade("pass", start=2), dimension_grade("pass")])
    path = run_rubric_dimensions(case=case, workspace_dir=workspace, output_dir=tmp_path / "grades",
                                 model="judge", deadline=time.monotonic() + 30, backend=backend)
    assert json.loads(path.read_text())["status"] == "complete"
    prompt = backend.prompts[0]
    assert str(workspace.resolve()) in prompt
    assert "1. Read ./answer.md.\n2. Inspect ./result.json." in prompt
    assert "rubric-2: Requirement 2." in prompt
    assert "rubric-1:" not in prompt
    if custom_prompt is None:
        assert "read-only grader" in prompt
        assert "not_proven" in prompt and "not_applicable" in prompt
        assert "all applicable obligations" in prompt
    else:
        assert "Dimension=second" in prompt


@pytest.mark.parametrize("custom_contract", ["legacy-default", "custom-prompt", "custom-schema"])
def test_existing_judge_output_contracts_remain_unchanged(tmp_path, custom_contract):
    case = RubricEvalCase(
        id="sample/service/rubric/direct", base_id="sample/service/rubric", prompt_id="direct",
        skill="sample-skill", language="sample", service="service", task="Assess the answer.",
        rubric=["Correct answer."],
        judge_prompt="Grade {task}." if custom_contract == "custom-prompt" else None,
    )

    class Judge:
        def run_judge(self, **kwargs):
            output = tmp_path / "rubric_grade.json"
            output.write_text(json.dumps({"overall_pass": True, "score": 80, "checks": [
                {"id": "quality", "pass": True, "notes": "", "evidence": ""},
            ]}))
            return AgentResult(0, tmp_path / "trace.jsonl", output, tmp_path / "stderr.txt")

    schema = None
    if custom_contract == "custom-schema":
        schema = tmp_path / "custom.schema.json"
        schema.write_text(json.dumps({"type": "object", "required": ["overall_pass", "score", "checks"]}))

    result = run_rubric_grade(case=case, side_dir=tmp_path, model="test", backend=Judge(), schema_path=schema)

    assert json.loads(result.read_text())["checks"][0]["id"] == "quality"
    assert not (tmp_path / "rubric_prompt.txt").exists()
    if custom_contract == "legacy-default":
        assert "read-only grader" not in rubric_prompt(case)


@pytest.mark.parametrize("custom_schema", [False, True])
def test_strict_grading_uses_separate_api_before_inference(tmp_path, custom_schema):
    case = RubricEvalCase(
        id="sample/service/rubric/direct", base_id="sample/service/rubric", prompt_id="direct",
        skill="sample-skill", language="sample", service="service", task="Assess the answer.",
        rubric=["Correct answer."], strict_rubric_output=True,
    )
    backend = RecordingBackend()

    with pytest.raises(ValueError, match="Use run_rubric_dimensions"):
        run_rubric_grade(case=case, side_dir=tmp_path, model="test", backend=backend,
                         schema_path=tmp_path / "custom.schema.json" if custom_schema else None)

    assert backend.judge_timeouts == []


@pytest.mark.parametrize("strict_output", [False, True])
@pytest.mark.parametrize("valid_grade", [False, True])
def test_live_result_requires_valid_grade_only_for_opted_in_rubric_runs(tmp_path, strict_output, valid_grade):
    guards = GradeResult(checks=[
        GradeCheckResult(id=name, description=name, passed=True, category="sanity")
        for name in ("final-message-present", "skills-loaded", "skill-instructions-read")
    ])
    side = side_result("with_skill", guards)
    side.strict_rubric_output = strict_output
    if valid_grade and strict_output:
        workspace = tmp_path / "task"
        workspace.mkdir()
        side.rubric_result_path = str(run_rubric_dimensions(
            case=dimension_case(1), workspace_dir=workspace, output_dir=tmp_path / "grades",
            model=None, deadline=time.monotonic() + 30, backend=DimensionBackend([dimension_grade("pass")]),
        ))
    elif valid_grade:
        grade_path = tmp_path / "rubric_grade.json"
        grade_path.write_text(json.dumps({"overall_pass": True, "score": 100, "checks": [
            {"id": "rubric-1", "pass": True, "notes": "Requirement met.", "evidence": "answer.md:1"},
        ]}))
        side.rubric_grade_path = str(grade_path)
    else:
        side.errors = ["rubric grading failed: inconsistent checks"]
    result = case_result(side, None)

    if strict_output and not valid_grade:
        with pytest.raises(AssertionError, match="with_skill rubric grading failed: .*inconsistent checks"):
            validate_live_result(result, require_valid_rubric=True)
    else:
        validate_live_result(result, require_valid_rubric=strict_output)


def test_legacy_grade_count_score_conversion_is_preserved(tmp_path):
    raw = json.dumps({
        "overall_pass": False,
        "score": 10,
        "checks": [{"id": f"rubric-{index}", "pass": index <= 10,
                    "notes": "Observed result.", "evidence": "answer.md:1"}
                   for index in range(1, 15)],
    })
    path = tmp_path / "rubric_grade.json"
    path.write_text(raw)
    side = side_result("with_skill", GradeResult())
    side.rubric_grade_path = str(path)
    restored = SideResult.model_validate_json(side.model_dump_json())

    loaded = load_rubric_grade(restored)

    assert loaded["score"] == 71
    assert (loaded["passed"], loaded["total"]) == (10, 14)
    assert path.read_text() == raw


def test_report_normalizes_count_shaped_rubric_score():
    assert normalize_rubric_score(6, passed=6, total=6) == 100
    assert normalize_rubric_score(5, passed=5, total=6) == 83
    assert normalize_rubric_score(88, passed=5, total=6) == 88


def test_session_result_writer_writes_raw_json_without_markdown(tmp_path: Path):
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    grade = GradeResult(
        checks=[GradeCheckResult(id="check", description="check", passed=True)]
    )
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
                "metadata": {
                    "mode": "ab",
                    "eval_kind": "sanity",
                    "run_id": "run",
                    "skill": "sample-skill",
                },
                "results": [result],
            }
        ]
    )

    assert (run_root / "runs" / "sanity-ab.json").is_file()
    assert (run_root / "run.json").is_file()
    assert not (run_root / "report.md").exists()
    assert not (run_root / "benchmark.json").exists()
    assert (
        run_root / "results" / "sample" / "service" / "sample-skill" / "eval.json"
    ).is_file()
    assert (
        run_root / "results" / "sample" / "service" / "sample-skill" / "with_skill.json"
    ).is_file()
    assert (
        run_root
        / "results"
        / "sample"
        / "service"
        / "sample-skill"
        / "with_baseline.json"
    ).is_file()


def test_report_renderer_writes_kind_specific_outputs(tmp_path: Path):
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    grade = GradeResult(
        checks=[
            GradeCheckResult(
                id="check", description="check", passed=False, evidence="missing output"
            )
        ]
    )
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
                    "repo_root": str(tmp_path),
                },
                "results": [result],
            }
        ]
    )
    report_path, benchmark_path = render_reports_for_run_root(run_root, "sanity")

    assert report_path == run_root / "sanity" / "report.md"
    assert benchmark_path == run_root / "sanity" / "benchmark.json"
    assert (
        tmp_path / "eval-reports" / "sample-skill" / "sanity" / "report.md"
    ).is_file()
    assert (
        run_root / "results" / "sample" / "service" / "sample-skill" / "with_skill.json"
    ).is_file()
    assert (
        run_root
        / "results"
        / "sample"
        / "service"
        / "sample-skill"
        / "with_baseline.json"
    ).is_file()
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    assert benchmark["kind"] == "sanity"
    assert benchmark["evals"][0]["with_baseline"] is None
    assert set(benchmark["evals"][0]["with_skill"]) >= {
        "checks",
        "tokens",
        "duration_seconds",
    }
    assert "repo_root" not in benchmark["metadata"]
    assert "rubric" not in benchmark["evals"][0]["with_skill"]
    assert "runtime" not in benchmark["evals"][0]["with_skill"]
    assert benchmark["failures"][0]["result"] == "sanity:check FAIL"
    report = report_path.read_text(encoding="utf-8")
    assert (
        "| with_skill | sample/service/sample-skill | sample/service | 1 | 0% (0/1) | 0 | 0.0s | - | - | - |"
        in report
    )
    assert "sanity:check FAIL" in report


def _write_validation_manifest_fixture(
    tmp_path: Path,
    *,
    selected_prompt_ids: tuple[str, ...],
    selection_scope: str,
) -> Path:
    skill_dir = tmp_path / "skills" / "sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Sample skill\n", encoding="utf-8")
    fixture_dir = tmp_path / "evals" / "sample" / "service"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "app.py").write_text("print('sample')\n", encoding="utf-8")
    eval_dir = fixture_dir / "eval" / "qual"
    eval_dir.mkdir(parents=True)
    definition_path = eval_dir / "sample.json"
    definition_path.write_text(
        json.dumps(
            {
                "skill": "sample-skill",
                "language": "sample",
                "service": "service",
                "prompts": [
                    {"id": "direct", "task": "Evaluate directly."},
                    {"id": "sibling", "task": "Evaluate the sibling."},
                ],
                "rubric": ["Must pass."],
            }
        ),
        encoding="utf-8",
    )
    results = []
    for prompt_id in selected_prompt_ids:
        case = RubricEvalCase(
            id=f"sample/service/sample-skill/{prompt_id}",
            base_id="sample/service/sample-skill",
            prompt_id=prompt_id,
            skill="sample-skill",
            language="sample",
            service="service",
            task=f"Evaluate {prompt_id}.",
            definition_path=str(definition_path),
            fixture_dir=str(fixture_dir),
            rubric=["Must pass."],
        )
        results.append(validation_result(case, tmp_path, skill_dir, None))
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    write_session_results(
        [
            {
                "mode": "validation",
                "eval_kind": "validation",
                "repo_root": tmp_path,
                "run_root": run_root,
                "skill": "sample-skill",
                "metadata": {"validation_scope": selection_scope},
                "results": results,
            }
        ]
    )
    render_reports_for_run_root(run_root, "validation")
    return (
        tmp_path
        / "eval-reports"
        / "sample-skill"
        / "validation"
        / "benchmark.json"
    )


def test_source_manifest_v4_binds_validation_selection_scope(tmp_path: Path):
    benchmark_path = _write_validation_manifest_fixture(
        tmp_path,
        selected_prompt_ids=("direct", "sibling"),
        selection_scope="full",
    )
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    assert benchmark["source"]["digest_version"] == 4
    assert benchmark["source"]["evaluator_semantics_version"] == 1
    assert verify_published_report_sources(tmp_path) == [benchmark_path]

    benchmark["source"]["selection_scope"] = "filtered"
    benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")
    with pytest.raises(ValueError, match="inputs are stale"):
        verify_published_report_sources(tmp_path)


def test_report_freshness_rejects_invalid_evaluator_semantics_configuration(
    tmp_path: Path,
):
    _write_validation_manifest_fixture(
        tmp_path,
        selected_prompt_ids=("direct",),
        selection_scope="filtered",
    )
    (tmp_path / "evals" / "evaluator-semantics.toml").write_text(
        "version = [", encoding="utf-8"
    )

    with pytest.raises(
        ValueError,
        match="evaluator semantics configuration is invalid: evaluator semantics file contains invalid TOML",
    ):
        verify_published_report_sources(tmp_path)


@pytest.mark.parametrize("recorded_version", [None, "1", 0, -1])
def test_report_freshness_rejects_malformed_recorded_evaluator_semantics_version(
    tmp_path: Path, recorded_version: object | None
):
    benchmark_path = _write_validation_manifest_fixture(
        tmp_path,
        selected_prompt_ids=("direct",),
        selection_scope="filtered",
    )
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    if recorded_version is None:
        benchmark["source"].pop("evaluator_semantics_version")
    else:
        benchmark["source"]["evaluator_semantics_version"] = recorded_version
    benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")

    with pytest.raises(ValueError, match="evaluator semantics version is malformed"):
        verify_published_report_sources(tmp_path)


def test_report_freshness_accepts_v2_source_manifests(tmp_path: Path):
    benchmark_path = _write_validation_manifest_fixture(
        tmp_path,
        selected_prompt_ids=("direct",),
        selection_scope="filtered",
    )
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    source = benchmark["source"]
    source["digest_version"] = 2
    source.pop("evaluator_semantics_version")
    source["digest"] = source_manifest_digest(
        source["files"],
        digest_version=2,
        eval_kinds=source.get("eval_kinds"),
        skill_path=source.get("skill_path"),
        config_path=source.get("config_path"),
        selections=source.get("selections"),
        selection_scope=source.get("selection_scope"),
    )
    benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")
    (tmp_path / "evals" / "evaluator-semantics.toml").unlink()

    assert verify_published_report_sources(tmp_path) == [benchmark_path]


def test_report_freshness_ignores_shared_reference_changes_for_other_consumers(
    tmp_path: Path,
):
    references = tmp_path / "skills" / "references"
    references.mkdir(parents=True)
    consumed = references / "consumed.md"
    consumed.write_text("# Consumed\n", encoding="utf-8")
    unrelated = references / "unrelated.md"
    unrelated.write_text("# Unrelated\n", encoding="utf-8")
    consumers = references / "consumers.json"
    consumers.write_text(
        json.dumps(
            {
                "consumed.md": ["sample-skill"],
                "unrelated.md": ["other-skill"],
            }
        ),
        encoding="utf-8",
    )
    benchmark_path = _write_validation_manifest_fixture(
        tmp_path,
        selected_prompt_ids=("direct",),
        selection_scope="filtered",
    )

    assert verify_published_report_sources(tmp_path) == [benchmark_path]

    unrelated.write_text("# Unrelated changed\n", encoding="utf-8")
    late_unrelated = references / "late-unrelated.md"
    late_unrelated.write_text("# Late unrelated\n", encoding="utf-8")
    consumers.write_text(
        json.dumps(
            {
                "consumed.md": ["sample-skill"],
                "unrelated.md": ["other-skill"],
                "late-unrelated.md": ["other-skill"],
            }
        ),
        encoding="utf-8",
    )
    assert verify_published_report_sources(tmp_path) == [benchmark_path]

    consumers.write_text(
        json.dumps(
            {
                "consumed.md": ["other-skill"],
                "unrelated.md": ["other-skill"],
                "late-unrelated.md": ["other-skill"],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="inputs are stale"):
        verify_published_report_sources(tmp_path)

    consumers.write_text(
        json.dumps(
            {
                "consumed.md": ["sample-skill"],
                "unrelated.md": ["other-skill"],
                "late-unrelated.md": ["other-skill"],
            }
        ),
        encoding="utf-8",
    )
    assert verify_published_report_sources(tmp_path) == [benchmark_path]

    consumed.write_text("# Consumed changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="inputs are stale"):
        verify_published_report_sources(tmp_path)
    consumed.write_text("# Consumed\n", encoding="utf-8")

    unrelated.unlink()
    late_unrelated.unlink()
    consumers.write_text(
        json.dumps({"consumed.md": ["sample-skill"]}), encoding="utf-8"
    )
    assert verify_published_report_sources(tmp_path) == [benchmark_path]

    undeclared = references / "undeclared.md"
    undeclared.write_text("# Undeclared\n", encoding="utf-8")
    with pytest.raises(ValueError, match="inputs are stale"):
        verify_published_report_sources(tmp_path)


@pytest.mark.parametrize("digest_version", [2, 3])
def test_legacy_report_stales_when_former_shared_reference_changes(
    tmp_path: Path, digest_version: int
):
    references = tmp_path / "skills" / "references"
    references.mkdir(parents=True)
    shared = references / "shared.md"
    shared.write_text("# Original\n", encoding="utf-8")
    consumers = references / "consumers.json"
    consumers.write_text(json.dumps({"shared.md": ["sample-skill"]}), encoding="utf-8")
    benchmark_path = _write_validation_manifest_fixture(
        tmp_path, selected_prompt_ids=("direct",), selection_scope="filtered"
    )
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    source = benchmark["source"]
    source["digest_version"] = digest_version
    source.pop("shared_reference_consumers", None)
    if digest_version == 2:
        source.pop("evaluator_semantics_version", None)
    source["digest"] = source_manifest_digest(
        source["files"],
        digest_version=digest_version,
        evaluator_semantics_version=source.get("evaluator_semantics_version"),
        eval_kinds=source.get("eval_kinds"),
        skill_path=source.get("skill_path"),
        config_path=source.get("config_path"),
        selections=source.get("selections"),
        selection_scope=source.get("selection_scope"),
    )
    benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")
    assert verify_published_report_sources(tmp_path) == [benchmark_path]

    consumers.write_text(json.dumps({"shared.md": ["other-skill"]}), encoding="utf-8")
    shared.write_text("# Changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="inputs are stale"):
        verify_published_report_sources(tmp_path)
    shared.unlink()
    with pytest.raises(ValueError, match="source input is missing"):
        verify_published_report_sources(tmp_path)


def test_known_v3_consumer_map_keeps_unrelated_reports_fresh(tmp_path: Path):
    digest = next(iter(LEGACY_SHARED_REFERENCE_CONSUMERS))
    references = tmp_path / "skills" / "references"
    references.mkdir(parents=True)
    (references / "consumers.json").write_text(
        json.dumps(
            {
                "genai-readiness.md": ["otel-audit", "otel-instrument"],
                "report-flow-contract.md": ["otel-audit", "splunk-configure"],
                "signalflow-patterns.md": ["splunk-configure"],
                "splunk-agent-observability.md": ["otel-audit", "otel-instrument"],
            }
        ),
        encoding="utf-8",
    )
    recorded = {
        "skills/references/consumers.json": digest,
        "skills/references/genai-readiness.md": "old-genai",
        "skills/references/report-flow-contract.md": "same-flow",
        "skills/references/signalflow-patterns.md": "same-patterns",
    }
    current = {
        "skills/references/consumers.json": "new-map",
        "skills/references/genai-readiness.md": "new-genai",
        "skills/references/report-flow-contract.md": "same-flow",
        "skills/references/signalflow-patterns.md": "same-patterns",
        "skills/references/splunk-agent-observability.md": "new-ao",
    }
    former = legacy_shared_reference_consumers(recorded, "splunk-configure")
    assert former == {
        "skills/references/report-flow-contract.md",
        "skills/references/signalflow-patterns.md",
    }
    assert source_inputs_match_for_skill(
        tmp_path, "splunk-configure", current, recorded, former
    )
    current["skills/references/report-flow-contract.md"] = "changed-flow"
    assert not source_inputs_match_for_skill(
        tmp_path, "splunk-configure", current, recorded, former
    )
    current["skills/references/report-flow-contract.md"] = "same-flow"
    audit_former = legacy_shared_reference_consumers(recorded, "otel-audit")
    assert not source_inputs_match_for_skill(
        tmp_path, "otel-audit", current, recorded, audit_former
    )


def test_report_freshness_allows_reports_without_legacy_manifests(tmp_path: Path):
    report_path = tmp_path / "eval-reports" / "sample-skill" / "sanity" / "benchmark.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps({"skill": "sample-skill", "kind": "sanity"}), encoding="utf-8")

    assert verify_published_report_sources(tmp_path) == []


def test_source_manifest_v3_binds_sibling_prompt_selection(tmp_path: Path):
    benchmark_path = _write_validation_manifest_fixture(
        tmp_path,
        selected_prompt_ids=("direct",),
        selection_scope="filtered",
    )
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    original_files = benchmark["source"]["files"]
    benchmark["source"]["selections"][0]["prompt_id"] = "sibling"
    benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")
    assert benchmark["source"]["files"] == original_files
    with pytest.raises(ValueError, match="inputs are stale"):
        verify_published_report_sources(tmp_path)


def test_source_manifest_v3_rejects_incomplete_full_selection(tmp_path: Path):
    benchmark_path = _write_validation_manifest_fixture(
        tmp_path,
        selected_prompt_ids=("direct",),
        selection_scope="full",
    )

    with pytest.raises(ValueError, match="inputs are stale"):
        verify_published_report_sources(tmp_path)


def test_live_report_rejects_unreported_validation_provenance(tmp_path: Path):
    grade = GradeResult(
        checks=[GradeCheckResult(id="check", description="check", passed=True)]
    )
    live_result = case_result(side_result("with_skill", grade), None)
    matching = ValidationResult(
        id=live_result.id,
        base_id=live_result.base_id,
        prompt_id=live_result.prompt_id,
        skill=live_result.skill,
        language=live_result.language,
        service=live_result.service,
        definition_path="evals/sample/service/eval/qual/sample.json",
        fixture_dir="evals/sample/service",
        skill_path="skills/sample-skill",
        eval_kind="rubric",
    )
    unreported = matching.model_copy(
        update={
            "id": "sample/service/sample-skill/sibling",
            "prompt_id": "sibling",
        }
    )

    with pytest.raises(
        ValueError,
        match="live report results do not match validation provenance selections",
    ):
        build_kind_benchmark(
            tmp_path,
            tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run",
            "sample-skill",
            "rubric",
            [
                {
                    "mode": "with_skill",
                    "metadata": {},
                    "results": [live_result.model_dump(mode="json")],
                    "result_paths": {},
                }
            ],
            [matching, unreported],
        )


def test_live_report_accepts_repeated_matching_provenance(tmp_path: Path):
    grade = GradeResult(
        checks=[GradeCheckResult(id="check", description="check", passed=True)]
    )
    live_result = case_result(side_result("with_skill", grade), None)
    matching = ValidationResult(
        id=live_result.id,
        base_id=live_result.base_id,
        prompt_id=live_result.prompt_id,
        skill=live_result.skill,
        language=live_result.language,
        service=live_result.service,
        definition_path="evals/sample/service/eval/qual/sample.json",
        fixture_dir="evals/sample/service",
        skill_path="skills/sample-skill",
        eval_kind="rubric",
    )

    benchmark = build_kind_benchmark(
        tmp_path,
        tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run",
        "sample-skill",
        "rubric",
        [
            {
                "mode": "with_skill",
                "metadata": {},
                "results": [
                    live_result.model_dump(mode="json"),
                    live_result.model_dump(mode="json"),
                ],
                "result_paths": {},
            }
        ],
        [matching, matching.model_copy(deep=True)],
    )

    assert benchmark["summary"]["prompt_count"] == 2


def test_live_report_source_manifest_detects_changed_and_added_inputs(tmp_path: Path):
    skill_dir = tmp_path / "skills" / "sample-skill"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Sample skill\n", encoding="utf-8")
    shared_reference = tmp_path / "skills" / "references" / "shared.md"
    shared_reference.parent.mkdir()
    shared_reference.write_text("# Shared reference\n", encoding="utf-8")
    shared_reference_cache = (
        shared_reference.parent / "__pycache__" / "shared.cpython-313.pyc"
    )
    shared_reference_cache.parent.mkdir()
    shared_reference_cache.write_bytes(b"generated cache")
    shared_reference_bytecode = shared_reference.parent / "generated.pyc"
    shared_reference_bytecode.write_bytes(b"generated bytecode")
    eval_dir = tmp_path / "evals" / "sample" / "service" / "eval" / "qual"
    eval_dir.mkdir(parents=True)
    fixture_dir = eval_dir.parent.parent
    fixture_source = fixture_dir / "main.go"
    fixture_source.write_text("package main\n", encoding="utf-8")
    input_dir = fixture_dir / "eval" / "inputs"
    input_dir.mkdir()
    selected_input = input_dir / "seed.json"
    selected_input.write_text('{"selected":true}\n', encoding="utf-8")
    unused_input = input_dir / "unused.json"
    unused_input.write_text('{"selected":false}\n', encoding="utf-8")
    generated_output = fixture_dir / ".observe" / "generated.json"
    generated_output.parent.mkdir()
    generated_output.write_text("{}\n", encoding="utf-8")
    pytest_cache = fixture_dir / ".pytest_cache" / "state"
    pytest_cache.parent.mkdir()
    pytest_cache.write_text("generated\n", encoding="utf-8")
    definition = {
        "skill": "sample-skill",
        "language": "sample",
        "service": "service",
        "prompts": [
            {
                "id": "direct",
                "task": "Evaluate the answer.",
                "eval_inputs": ["eval/inputs/seed.json"],
            },
            {
                "id": "unused",
                "task": "Evaluate another answer.",
                "eval_inputs": ["eval/inputs/unused.json"],
            },
        ],
        "rubric": ["Must cite evidence."],
    }
    definition_path = eval_dir / "sample.json"
    definition_path.write_text(json.dumps(definition), encoding="utf-8")
    sanity_dir = tmp_path / "evals" / "sample" / "service" / "eval" / "sanity"
    sanity_dir.mkdir(parents=True)
    sanity_definition_path = sanity_dir / "sample.json"
    sanity_definition_path.write_text(
        json.dumps(
            {
                "skill": "sample-skill",
                "language": "sample",
                "service": "service",
                "prompts": [{"id": "quick", "task": "Run a quick check."}],
                "checks": [{"type": "file_exists", "path": "result.txt"}],
            }
        ),
        encoding="utf-8",
    )
    unrelated_fixture_dir = tmp_path / "evals" / "sample" / "other"
    unrelated_fixture_dir.mkdir(parents=True)
    unrelated_fixture_source = unrelated_fixture_dir / "other.go"
    unrelated_fixture_source.write_text("package other\n", encoding="utf-8")
    unrelated_eval_dir = unrelated_fixture_dir / "eval" / "qual"
    unrelated_eval_dir.mkdir(parents=True)
    unrelated_definition_path = unrelated_eval_dir / "other.json"
    unrelated_definition_path.write_text(
        json.dumps(
            {
                "skill": "sample-skill",
                "prompts": [{"id": "other", "task": "Evaluate other."}],
                "rubric": ["Must pass."],
            }
        ),
        encoding="utf-8",
    )
    selected_config = tmp_path / "evals" / "custom-eval-config.toml"
    selected_config.write_text("[pytest]\n", encoding="utf-8")
    selected_config_display = "evals/custom-eval-config.toml"
    eval_pyproject = tmp_path / "evals" / "pyproject.toml"
    eval_pyproject.write_text("[project]\nname = 'evals'\n", encoding="utf-8")
    eval_lockfile = tmp_path / "evals" / "uv.lock"
    eval_lockfile.write_text("version = 1\n", encoding="utf-8")
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    grade = GradeResult(
        checks=[GradeCheckResult(id="check", description="check", passed=True)]
    )
    live_result = case_result(side_result("with_skill", grade), None)
    selected_case = RubricEvalCase(
        id="sample/service/sample-skill/direct",
        base_id="sample/service/sample-skill",
        prompt_id="direct",
        skill="sample-skill",
        language="sample",
        service="service",
        task="Evaluate the answer.",
        eval_inputs=["eval/inputs/seed.json"],
        definition_path=str(definition_path),
        fixture_dir=str(fixture_dir),
        rubric=["Must cite evidence."],
    )
    validation = validation_result(
        selected_case,
        tmp_path,
        skill_dir,
        selected_config,
    )
    write_session_results(
        [
            {
                "mode": "validation",
                "eval_kind": "validation",
                "repo_root": tmp_path,
                "run_root": run_root,
                "skill": "sample-skill",
                "metadata": {
                    "config_path": selected_config_display,
                    "validation_scope": "filtered",
                },
                "results": [validation],
            },
            {
                "mode": "with_skill",
                "eval_kind": "rubric",
                "repo_root": tmp_path,
                "run_root": run_root,
                "skill": "sample-skill",
                "metadata": {"config_path": selected_config_display},
                "results": [live_result],
            },
        ]
    )
    _, validation_benchmark_path = render_reports_for_run_root(run_root, "validation")
    _, benchmark_path = render_reports_for_run_root(run_root, "rubric")

    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    validation_benchmark = json.loads(
        validation_benchmark_path.read_text(encoding="utf-8")
    )
    assert benchmark["source"]["skill_path"] == "skills/sample-skill"
    assert validation_benchmark["source"]["selection_scope"] == "filtered"
    assert {
        key: value
        for key, value in validation_benchmark["source"].items()
        if key not in {"digest", "selection_scope"}
    } == {
        key: value
        for key, value in benchmark["source"].items()
        if key != "digest"
    }
    assert validation_benchmark["source"]["digest"] != benchmark["source"]["digest"]
    assert benchmark["source"]["eval_kinds"] == ["rubric"]
    assert benchmark["source"]["selections"] == [
        {
            "definition_path": "evals/sample/service/eval/qual/sample.json",
            "fixture_dir": "evals/sample/service",
            "prompt_id": "direct",
            "eval_kind": "rubric",
            "eval_inputs": ["eval/inputs/seed.json"],
        }
    ]
    assert (
        "evals/sample/service/eval/sanity/sample.json"
        not in benchmark["source"]["files"]
    )
    assert benchmark["source"]["config_path"] == selected_config_display
    assert selected_config_display in benchmark["source"]["files"]
    assert "evals/codex-eval-home.config.toml" not in benchmark["source"]["files"]
    assert "evals/pyproject.toml" not in benchmark["source"]["files"]
    assert "evals/uv.lock" not in benchmark["source"]["files"]
    assert "skills/references/shared.md" in benchmark["source"]["files"]
    assert (
        "skills/references/__pycache__/shared.cpython-313.pyc"
        not in benchmark["source"]["files"]
    )
    assert (
        "skills/references/generated.pyc" not in benchmark["source"]["files"]
    )
    assert "evals/sample/service/main.go" in benchmark["source"]["files"]
    assert (
        "evals/sample/service/eval/inputs/seed.json"
        in benchmark["source"]["files"]
    )
    assert (
        "evals/sample/service/eval/inputs/unused.json"
        not in benchmark["source"]["files"]
    )
    assert (
        "evals/sample/other/eval/qual/other.json"
        not in benchmark["source"]["files"]
    )
    assert "evals/sample/other/other.go" not in benchmark["source"]["files"]
    assert (
        "evals/sample/service/.observe/generated.json"
        not in benchmark["source"]["files"]
    )
    assert (
        "evals/sample/service/.pytest_cache/state"
        not in benchmark["source"]["files"]
    )
    assert verify_published_report_sources(tmp_path) == [
        tmp_path / "eval-reports" / "sample-skill" / "rubric" / "benchmark.json",
        tmp_path / "eval-reports" / "sample-skill" / "validation" / "benchmark.json",
    ]

    semantics_path = tmp_path / "evals" / "evaluator-semantics.toml"
    semantics_path.write_text("version = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="evaluator semantics version mismatch"):
        verify_published_report_sources(tmp_path)
    semantics_path.write_text("version = 1\n", encoding="utf-8")
    assert len(verify_published_report_sources(tmp_path)) == 2

    fixture_source.write_text("package changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="inputs are stale"):
        verify_published_report_sources(tmp_path)
    fixture_source.write_text("package main\n", encoding="utf-8")
    assert len(verify_published_report_sources(tmp_path)) == 2

    shared_reference.write_text("# Changed shared reference\n", encoding="utf-8")
    with pytest.raises(ValueError, match="inputs are stale"):
        verify_published_report_sources(tmp_path)
    shared_reference.write_text("# Shared reference\n", encoding="utf-8")
    assert len(verify_published_report_sources(tmp_path)) == 2

    shared_reference_cache.write_bytes(b"changed cache")
    shared_reference_bytecode.write_bytes(b"changed bytecode")
    late_reference_cache = (
        shared_reference.parent
        / "nested"
        / "__pycache__"
        / "late.cpython-313.pyc"
    )
    late_reference_cache.parent.mkdir(parents=True)
    late_reference_cache.write_bytes(b"late generated cache")
    assert len(verify_published_report_sources(tmp_path)) == 2

    selected_input.write_text('{"selected":"changed"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="inputs are stale"):
        verify_published_report_sources(tmp_path)
    selected_input.write_text('{"selected":true}\n', encoding="utf-8")
    assert len(verify_published_report_sources(tmp_path)) == 2

    unused_input.write_text('{"selected":"changed"}\n', encoding="utf-8")
    unrelated_fixture_source.write_text("package changed\n", encoding="utf-8")
    unrelated_definition_path.write_text(
        unrelated_definition_path.read_text(encoding="utf-8").replace(
            "Evaluate other.", "Evaluate changed other."
        ),
        encoding="utf-8",
    )
    generated_output.write_text('{"generated":"changed"}\n', encoding="utf-8")
    pytest_cache.write_text("changed\n", encoding="utf-8")
    assert len(verify_published_report_sources(tmp_path)) == 2

    sanity_definition_path.write_text(
        sanity_definition_path.read_text(encoding="utf-8").replace(
            "quick", "quick-updated"
        ),
        encoding="utf-8",
    )
    assert len(verify_published_report_sources(tmp_path)) == 2

    published_benchmark_path = (
        tmp_path / "eval-reports" / "sample-skill" / "rubric" / "benchmark.json"
    )
    published_benchmark_path.write_text(
        json.dumps({key: value for key, value in benchmark.items() if key != "source"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="source manifest is missing"):
        verify_published_report_sources(tmp_path)
    published_benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")

    added_definition = dict(definition)
    added_definition["prompts"] = [{"id": "added", "task": "Evaluate another answer."}]
    (eval_dir / "added.json").write_text(json.dumps(added_definition), encoding="utf-8")
    assert len(verify_published_report_sources(tmp_path)) == 2

    (eval_dir / "added.json").unlink()

    selected_config.write_text("[pytest]\nchanged = true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="inputs are stale"):
        verify_published_report_sources(tmp_path)

    selected_config.write_text("[pytest]\n", encoding="utf-8")
    assert len(verify_published_report_sources(tmp_path)) == 2

    eval_pyproject.write_text("[project]\nname = 'changed-evals'\n", encoding="utf-8")
    eval_lockfile.write_text("version = 2\n", encoding="utf-8")
    assert len(verify_published_report_sources(tmp_path)) == 2


def test_full_validation_source_detects_the_first_new_eval_kind(tmp_path: Path):
    skill_dir = tmp_path / "skills" / "sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Sample skill\n", encoding="utf-8")
    qual_dir = tmp_path / "evals" / "sample" / "service" / "eval" / "qual"
    qual_dir.mkdir(parents=True)
    definition_path = qual_dir / "sample.json"
    definition_path.write_text(
        json.dumps(
            {
                "skill": "sample-skill",
                "prompts": [{"id": "direct", "task": "Evaluate."}],
                "rubric": [],
            }
        ),
        encoding="utf-8",
    )
    fixture_dir = qual_dir.parent.parent
    validation = ValidationResult(
        id="sample/service/sample-skill/direct",
        base_id="sample/service/sample-skill",
        prompt_id="direct",
        skill="sample-skill",
        language="sample",
        service="service",
        definition_path=str(definition_path),
        fixture_dir=str(fixture_dir),
        skill_path=str(skill_dir),
        eval_kind="rubric",
        selected_eval_inputs=[],
        rubric_check_count=1,
        source_files=source_input_digests(
            tmp_path,
            "sample-skill",
            "rubric",
            skill_dir,
            definition_path=definition_path,
            fixture_dir=fixture_dir,
            prompt_id="direct",
        ),
    )
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    write_session_results(
        [
            {
                "mode": "validation",
                "eval_kind": "validation",
                "repo_root": tmp_path,
                "run_root": run_root,
                "skill": "sample-skill",
                "metadata": {"validation_scope": "full"},
                "results": [validation],
            }
        ]
    )
    render_reports_for_run_root(run_root, "validation")

    assert len(verify_published_report_sources(tmp_path)) == 1

    sanity_dir = tmp_path / "evals" / "sample" / "service" / "eval" / "sanity"
    sanity_dir.mkdir()
    (sanity_dir / "sample.json").write_text(
        json.dumps(
            {
                "skill": "sample-skill",
                "prompts": [{"id": "quick", "task": "Check."}],
                "checks": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="inputs are stale"):
        verify_published_report_sources(tmp_path)


def test_runtime_source_manifest_tracks_runtime_assets_only_for_matching_inputs(
    tmp_path: Path,
):
    skill_dir = tmp_path / "skills" / "sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Sample skill\n", encoding="utf-8")

    fixture_dir = tmp_path / "evals" / "sample" / "service"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "app.py").write_text("print('fixture')\n", encoding="utf-8")
    runtime_dir = fixture_dir / "eval" / "runtime"
    runtime_dir.mkdir(parents=True)
    definition_path = runtime_dir / "sample.json"
    definition_path.write_text(
        json.dumps(
            {
                "skill": "sample-skill",
                "prompts": [{"id": "direct", "task": "Run the fixture."}],
                "checks": [],
            }
        ),
        encoding="utf-8",
    )
    compose_file = runtime_dir / "docker-compose.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    app_dockerfile = runtime_dir / "App.Dockerfile"
    app_dockerfile.write_text("FROM scratch\n", encoding="utf-8")
    traffic_script = runtime_dir / "run-traffic.sh"
    traffic_script.write_text("#!/bin/sh\n", encoding="utf-8")
    runtime_generated = runtime_dir / ".pytest_cache" / "state"
    runtime_generated.parent.mkdir()
    runtime_generated.write_text("generated\n", encoding="utf-8")

    shared_runtime_dir = tmp_path / "evals" / "runtime"
    shared_runtime_dir.mkdir()
    shared_runtime = shared_runtime_dir / "traffic.Dockerfile"
    shared_runtime.write_text("FROM scratch\n", encoding="utf-8")
    observer_source = tmp_path / "observer" / "internal" / "api" / "handler.go"
    observer_source.parent.mkdir(parents=True)
    observer_source.write_text("package api\n", encoding="utf-8")
    generated_dependency = (
        tmp_path / "observer" / "client" / "node_modules" / "generated.js"
    )
    generated_dependency.parent.mkdir(parents=True)
    generated_dependency.write_text("generated\n", encoding="utf-8")
    staged_skill = (
        tmp_path / "observer" / "cmd" / "obstudio" / "_skills" / "SKILL.md"
    )
    staged_skill.parent.mkdir(parents=True)
    staged_skill.write_text("generated\n", encoding="utf-8")
    generated_static = (
        tmp_path
        / "observer"
        / "internal"
        / "web"
        / "static"
        / "assets"
        / "main.js"
    )
    generated_static.parent.mkdir(parents=True)
    generated_static.write_text("generated\n", encoding="utf-8")
    observer_binary = tmp_path / "observer" / "obstudio"
    observer_binary.write_bytes(b"generated")
    docs_example = tmp_path / "docs" / "examples.md"
    docs_example.parent.mkdir()
    docs_example.write_text("# Example\n", encoding="utf-8")

    unrelated_kind_dir = fixture_dir / "eval" / "qual"
    unrelated_kind_dir.mkdir()
    unrelated_kind = unrelated_kind_dir / "sample.json"
    unrelated_kind.write_text(
        json.dumps(
            {
                "skill": "sample-skill",
                "prompts": [{"id": "direct", "task": "Review."}],
                "rubric": ["Pass."],
            }
        ),
        encoding="utf-8",
    )
    other_fixture = tmp_path / "evals" / "sample" / "other"
    other_runtime_dir = other_fixture / "eval" / "runtime"
    other_runtime_dir.mkdir(parents=True)
    (other_fixture / "other.py").write_text("print('other')\n", encoding="utf-8")
    (other_runtime_dir / "other.json").write_text(
        json.dumps(
            {
                "skill": "other-skill",
                "prompts": [{"id": "direct", "task": "Run."}],
                "checks": [],
            }
        ),
        encoding="utf-8",
    )
    unrelated_skill_asset = other_runtime_dir / "docker-compose.yml"
    unrelated_skill_asset.write_text("services: {}\n", encoding="utf-8")

    validation = ValidationResult(
        id="sample/service/sample-skill/direct",
        base_id="sample/service/sample-skill",
        prompt_id="direct",
        skill="sample-skill",
        language="sample",
        service="service",
        definition_path=str(definition_path),
        fixture_dir=str(fixture_dir),
        skill_path=str(skill_dir),
        eval_kind="runtime",
        selected_eval_inputs=[],
        runtime_check_count=1,
        source_files=source_input_digests(
            tmp_path,
            "sample-skill",
            "runtime",
            skill_dir,
            definition_path=definition_path,
            fixture_dir=fixture_dir,
            prompt_id="direct",
        ),
    )
    grade = GradeResult(
        checks=[
            GradeCheckResult(
                id="runtime",
                description="runtime",
                passed=True,
                category="runtime",
            )
        ]
    )
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    write_session_results(
        [
            {
                "mode": "validation",
                "eval_kind": "validation",
                "repo_root": tmp_path,
                "run_root": run_root,
                "skill": "sample-skill",
                "metadata": {"validation_scope": "filtered"},
                "results": [validation],
            },
            {
                "mode": "with_skill",
                "eval_kind": "runtime",
                "repo_root": tmp_path,
                "run_root": run_root,
                "skill": "sample-skill",
                "results": [case_result(side_result("with_skill", grade), None)],
            },
        ]
    )
    _, benchmark_path = render_reports_for_run_root(run_root, "runtime")
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    source_files = benchmark["source"]["files"]
    for expected in (
        "evals/sample/service/app.py",
        "evals/sample/service/eval/runtime/sample.json",
        "evals/sample/service/eval/runtime/docker-compose.yml",
        "evals/sample/service/eval/runtime/App.Dockerfile",
        "evals/sample/service/eval/runtime/run-traffic.sh",
        "evals/runtime/traffic.Dockerfile",
        "observer/internal/api/handler.go",
        "docs/examples.md",
    ):
        assert expected in source_files
    for excluded in (
        "evals/sample/service/eval/runtime/.pytest_cache/state",
        "evals/sample/service/eval/qual/sample.json",
        "evals/sample/other/other.py",
        "evals/sample/other/eval/runtime/docker-compose.yml",
        "observer/client/node_modules/generated.js",
        "observer/cmd/obstudio/_skills/SKILL.md",
        "observer/internal/web/static/assets/main.js",
        "observer/obstudio",
    ):
        assert excluded not in source_files
    assert len(verify_published_report_sources(tmp_path)) == 1

    compose_file.write_text("services:\n  changed: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="inputs are stale"):
        verify_published_report_sources(tmp_path)
    compose_file.write_text("services: {}\n", encoding="utf-8")
    assert len(verify_published_report_sources(tmp_path)) == 1

    shared_runtime.write_text("FROM changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="inputs are stale"):
        verify_published_report_sources(tmp_path)
    shared_runtime.write_text("FROM scratch\n", encoding="utf-8")
    assert len(verify_published_report_sources(tmp_path)) == 1

    observer_source.write_text("package changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="inputs are stale"):
        verify_published_report_sources(tmp_path)
    observer_source.write_text("package api\n", encoding="utf-8")
    assert len(verify_published_report_sources(tmp_path)) == 1

    runtime_generated.write_text("changed\n", encoding="utf-8")
    generated_dependency.write_text("changed\n", encoding="utf-8")
    staged_skill.write_text("changed\n", encoding="utf-8")
    generated_static.write_text("changed\n", encoding="utf-8")
    observer_binary.write_bytes(b"changed")
    unrelated_kind.write_text('{"changed":true}\n', encoding="utf-8")
    unrelated_skill_asset.write_text("services:\n  changed: {}\n", encoding="utf-8")
    assert len(verify_published_report_sources(tmp_path)) == 1


def test_cli_report_renders_latest_run(tmp_path: Path):
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    grade = GradeResult(
        checks=[GradeCheckResult(id="check", description="check", passed=True)]
    )
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
                },
                "results": [result],
            }
        ]
    )

    assert (
        cli_main(
            [
                "report",
                "--repo-root",
                str(tmp_path),
                "--skill",
                "sample-skill",
                "--kind",
                "sanity",
            ]
        )
        == 0
    )

    assert (
        tmp_path / "eval-reports" / "sample-skill" / "sanity" / "report.md"
    ).is_file()
    assert (
        tmp_path / "eval-reports" / "sample-skill" / "sanity" / "benchmark.json"
    ).is_file()


def test_usage_aggregation_keeps_partial_record_and_field_coverage():
    usage = aggregate_usage(
        [
            TokenUsage(
                provider="codex",
                source="cumulative",
                observed=True,
                usage_record_count=2,
                selected_record_count=1,
                input_tokens=10,
                cached_input_tokens=0,
                output_tokens=5,
                reasoning_output_tokens=0,
                provider_total_tokens=15,
                derived_total_tokens=15,
            ),
            TokenUsage(provider="unknown", observed=False),
            None,
        ],
        expected_records=3,
    )

    assert usage is not None
    assert usage["provider"] == "mixed"
    assert usage["input_tokens"] == 10
    assert usage["cached_input_tokens"] == 0
    assert usage["cache_creation_input_tokens"] is None
    assert usage["provider_total_tokens"] == 15
    assert usage["coverage"] == {
        "record_count": 3,
        "modeled_count": 2,
        "observed_count": 1,
        "recognized_count": 1,
        "preferred_total_count": 1,
        "field_counts": {
            "input_tokens": 1,
            "cached_input_tokens": 1,
            "cache_creation_input_tokens": 0,
            "output_tokens": 1,
            "reasoning_output_tokens": 1,
            "provider_total_tokens": 1,
            "derived_total_tokens": 1,
        },
    }


def test_report_total_preserves_per_record_provider_precedence():
    usage = aggregate_usage(
        [
            TokenUsage(
                provider="codex",
                observed=True,
                provider_total_tokens=20,
                derived_total_tokens=15,
            ),
            TokenUsage(
                provider="codex",
                observed=True,
                derived_total_tokens=10,
            ),
        ],
        expected_records=2,
    )

    assert usage is not None
    assert format_tokens({"agent_usage": usage, "agent_tokens": 30}) == "30"


def test_report_does_not_infer_effective_total_from_partial_incremental_fields():
    usage = aggregate_usage(
        [
            TokenUsage(
                provider="codex",
                source="incremental",
                observed=True,
                usage_record_count=2,
                selected_record_count=1,
                input_tokens=6,
                output_tokens=4,
                provider_total_tokens=10,
                derived_total_tokens=10,
                effective_total_tokens=None,
            )
        ],
        expected_records=1,
    )

    assert usage is not None
    assert usage["effective_total_tokens"] is None
    assert usage["coverage"]["preferred_total_count"] == 0
    assert format_tokens({"agent_usage": usage, "agent_tokens": 0}) == "unknown"


def test_legacy_token_usage_without_effective_total_uses_existing_precedence():
    usage = TokenUsage.model_validate(
        {
            "provider": "codex",
            "observed": True,
            "provider_total_tokens": 20,
            "derived_total_tokens": 15,
        }
    )

    assert usage.total_tokens == 20


def test_legacy_trace_usage_without_effective_total_uses_existing_precedence():
    trace_usage = TraceUsage(
        provider="codex",
        observed=True,
        provider_total_tokens=20,
        derived_total_tokens=15,
    )

    assert trace_usage.effective_total_tokens == 20
    assert trace_usage.total_tokens == 20
    assert token_usage_from_trace_usage(trace_usage).total_tokens == 20


def test_usage_status_is_partial_when_preferred_total_is_unknown():
    usage = aggregate_usage(
        [
            TokenUsage(
                provider="claude",
                source="incremental",
                observed=True,
                cached_input_tokens=8,
            )
        ],
        expected_records=1,
    )

    assert usage is not None
    assert usage["coverage"]["recognized_count"] == 1
    assert usage["coverage"]["preferred_total_count"] == 0
    assert usage_status(usage, 1) == "partial"


def test_compact_token_count_formats_oversized_values_without_float_conversion():
    assert compact_token_count(10**1000).endswith(".0M")


def test_report_renders_partial_usage_unknown_and_explicit_zero(tmp_path: Path):
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    grade = GradeResult(
        checks=[GradeCheckResult(id="check", description="check", passed=True)]
    )
    measured = TokenUsage(
        provider="codex",
        source="cumulative",
        observed=True,
        usage_record_count=2,
        selected_record_count=1,
        input_tokens=10,
        cached_input_tokens=0,
        cache_creation_input_tokens=None,
        output_tokens=5,
        reasoning_output_tokens=0,
        provider_total_tokens=15,
        derived_total_tokens=15,
    )
    first = case_result(
        side_result(
            "with_skill", grade, agent_tokens=15, tokens=15, agent_usage=measured
        ),
        None,
    )
    second = case_result(
        side_result(
            "with_skill",
            grade,
            agent_usage=TokenUsage(provider="codex", observed=False),
        ),
        None,
    ).model_copy(
        update={
            "id": "sample/service/sample-skill/alternate",
            "prompt_id": "alternate",
        }
    )
    zero = case_result(
        side_result(
            "baseline",
            grade,
            agent_usage=TokenUsage(
                provider="codex",
                source="cumulative",
                observed=True,
                usage_record_count=1,
                selected_record_count=1,
                input_tokens=0,
                cached_input_tokens=0,
                cache_creation_input_tokens=0,
                output_tokens=0,
                reasoning_output_tokens=0,
                provider_total_tokens=0,
                derived_total_tokens=0,
            ),
        ),
        None,
    )
    zero = zero.model_copy(update={"with_skill": None, "baseline": zero.with_skill})

    write_session_results(
        [
            {
                "mode": "ab",
                "eval_kind": "sanity",
                "repo_root": tmp_path,
                "run_root": run_root,
                "skill": "sample-skill",
                "metadata": {
                    "mode": "ab",
                    "eval_kind": "sanity",
                    "run_id": "run",
                    "skill": "sample-skill",
                },
                "results": [first, second, zero],
            }
        ]
    )
    report_path, benchmark_path = render_reports_for_run_root(run_root, "sanity")

    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    with_skill = benchmark["evals"][0]["with_skill"]
    baseline = benchmark["evals"][0]["with_baseline"]
    assert with_skill["agent_usage"]["coverage"]["record_count"] == 2
    assert with_skill["agent_usage"]["coverage"]["recognized_count"] == 1
    assert baseline["agent_usage"]["provider_total_tokens"] == 0

    report = report_path.read_text(encoding="utf-8")
    assert (
        "| ab | sample/service/sample-skill | sample/service | 3 | 100% (2/2) | unknown |"
        in report
    )
    assert (
        "| with_skill | codex | mixed | partial | 1/2 recognized; 1/2 observed | 10 (1/2) | 0 (1/2) | unknown | 5 (1/2) | 0 (1/2) | 15 (1/2) | 15 (1/2) |"
        in report
    )
    assert (
        "| with_baseline | codex | cumulative | measured | 1/1 recognized | 0 | 0 | 0 | 0 | 0 | 0 | 0 |"
        in report
    )


def test_legacy_flat_usage_json_still_loads_and_renders_without_usage_section(
    tmp_path: Path,
):
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    grade = GradeResult(
        checks=[GradeCheckResult(id="check", description="check", passed=True)]
    )
    result = case_result(
        side_result("with_skill", grade, tokens=456, agent_tokens=456), None
    )

    write_session_results(
        [
            {
                "mode": "with_skill",
                "eval_kind": "sanity",
                "repo_root": tmp_path,
                "run_root": run_root,
                "skill": "sample-skill",
                "results": [result],
            }
        ]
    )
    raw_path = run_root / "runs" / "sanity-with_skill.json"
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    side = payload["results"][0]["with_skill"]
    side.pop("agent_usage")
    side.pop("rubric_usage")
    raw_path.write_text(json.dumps(payload), encoding="utf-8")

    report_path, benchmark_path = render_reports_for_run_root(run_root, "sanity")

    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    assert benchmark["evals"][0]["with_skill"]["agent_usage"] is None
    report = report_path.read_text(encoding="utf-8")
    assert (
        "| with_skill | sample/service/sample-skill | sample/service | 1 | 100% (1/1) | 456 |"
        in report
    )
    assert "## Agent Token Usage" not in report


def test_legacy_flat_usage_keeps_explicit_zero_agent_tokens_separate():
    assert format_tokens({"tokens": 17, "agent_tokens": 0, "rubric_tokens": 17}) == "0"
    assert format_tokens({"tokens": 17}) == "17"


def test_judge_usage_is_rendered_only_in_rubric_report(tmp_path: Path):
    usage = TokenUsage(
        provider="claude",
        source="cumulative",
        observed=True,
        usage_record_count=1,
        selected_record_count=1,
        input_tokens=10,
        cached_input_tokens=0,
        cache_creation_input_tokens=0,
        output_tokens=5,
        derived_total_tokens=15,
    )
    grade = GradeResult(
        checks=[GradeCheckResult(id="check", description="check", passed=True)]
    )
    rubric_path = tmp_path / "rubric.json"
    rubric_path.write_text(
        json.dumps({"overall_pass": True, "score": 100, "checks": []}),
        encoding="utf-8",
    )
    result = case_result(
        side_result(
            "with_skill",
            grade,
            agent_tokens=15,
            rubric_tokens=15,
            tokens=30,
            agent_usage=usage,
            rubric_usage=usage,
            rubric_grade_path=str(rubric_path),
        ),
        None,
    )

    reports = {}
    for kind in ("sanity", "rubric"):
        run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / kind
        write_session_results(
            [
                {
                    "mode": "with_skill",
                    "eval_kind": kind,
                    "repo_root": tmp_path,
                    "run_root": run_root,
                    "skill": "sample-skill",
                    "results": [result],
                }
            ]
        )
        report_path, _ = render_reports_for_run_root(run_root, kind)
        reports[kind] = report_path.read_text(encoding="utf-8")

    assert "## Agent Token Usage" in reports["sanity"]
    assert "## Judge Token Usage" not in reports["sanity"]
    assert "## Agent Token Usage" in reports["rubric"]
    assert "## Judge Token Usage" in reports["rubric"]


@pytest.mark.parametrize(
    ("kind", "actor", "judge", "expected"),
    [
        ("rubric", "actor-override", "", "actor-override"),
        ("rubric", "actor-override", "explicit-judge", "explicit-judge"),
        ("rubric", "", "", "-"),
        ("sanity", "actor-override", "", "-"),
        ("runtime", "actor-override", "", "-"),
        ("sanity", "actor-override", "configured-judge", "-"),
        ("runtime", "actor-override", "configured-judge", "-"),
    ],
)
def test_legacy_report_records_effective_judge_without_changing_raw_run(
    tmp_path: Path, kind: str, actor: str, judge: str, expected: str
):
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    grade = GradeResult(
        checks=[GradeCheckResult(id="check", description="check", passed=True)]
    )
    rubric_path = tmp_path / "rubric_grade.json"
    rubric_path.write_text(
        json.dumps({"overall_pass": True, "score": 100, "checks": []}),
        encoding="utf-8",
    )
    result = case_result(
        side_result("with_skill", grade, rubric_grade_path=str(rubric_path)), None
    )
    write_session_results([
        {
            "mode": "with_skill",
            "eval_kind": kind,
            "repo_root": tmp_path,
            "run_root": run_root,
            "skill": "sample-skill",
            "metadata": {"agent_model": actor, "judge_model": judge},
            "results": [result],
        }
    ])
    raw_path = run_root / "runs" / f"{kind}-with_skill.json"
    original_raw = raw_path.read_bytes()

    report_path, benchmark_path = render_reports_for_run_root(run_root, kind)

    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    assert benchmark["metadata"]["judge_model"] == expected
    if kind == "rubric":
        assert f"| Judge model | {expected} |" in report_path.read_text(encoding="utf-8")
    assert raw_path.read_bytes() == original_raw


def test_rubric_report_resolves_judge_model_for_each_metadata_source(tmp_path: Path):
    metadata = kind_report_metadata(
        "sample-skill",
        tmp_path,
        "rubric",
        [
            {"agent_model": "actor-a", "judge_model": "explicit-judge"},
            {"agent_model": "actor-b", "judge_model": ""},
        ],
    )

    assert metadata["judge_model"] == "actor-b, explicit-judge"


def test_disabled_rubric_report_does_not_claim_configured_judge(tmp_path: Path):
    metadata = kind_report_metadata(
        "sample-skill", tmp_path, "rubric",
        [{"agent_model": "actor", "judge_model": "configured-judge", "rubric_enabled": False}],
    )

    assert metadata["judge_model"] == "-"


@pytest.mark.parametrize(
    ("mode", "kind", "enabled", "expected"),
    [
        ("validation", "rubric", True, ""),
        ("with_skill", "validation", True, ""),
        ("with_skill", "sanity", True, ""),
        ("with_skill", "runtime", True, ""),
        ("with_skill", "standard", False, ""),
        ("with_skill", "rubric", True, "configured-judge"),
    ],
)
def test_legacy_report_metadata_hides_inactive_judge_without_mutating_input(
    tmp_path: Path, mode: str, kind: str, enabled: bool, expected: str
):
    original = {"eval_kind": kind, "judge_model": "configured-judge", "rubric_enabled": enabled}

    metadata = report_metadata("sample-skill", mode, tmp_path, original)

    assert metadata["judge_model"] == expected
    assert original == {"eval_kind": kind, "judge_model": "configured-judge", "rubric_enabled": enabled}


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
    assert (
        "| with_skill | sample/service/sample-skill | sample/service | 1 | 100% (1/1) | 456 | 12.3s | - | - | - |"
        in report
    )


def test_sanity_report_uses_sanity_template_only(tmp_path: Path):
    report = report_for_kind(tmp_path, "sanity")

    assert "Rubric Checks" not in report
    assert "Runtime Checks" not in report
    assert "## Sanity Summary" in report
    assert "## Sanity Failures" in report
    assert "## Rubric Summary" not in report
    assert "## Runtime Summary" not in report
    assert (
        "| with_skill | sample/service/sample-skill | sample/service | 1 | 100% (1/1) | 456 | 12.3s | - | - | - |"
        in report
    )


def test_rubric_report_uses_rubric_template_only(tmp_path: Path):
    report = report_for_kind(tmp_path, "rubric")

    assert "Sanity Checks" not in report
    assert "Runtime Checks" not in report
    assert "## Sanity Summary" not in report
    assert "## Rubric Summary" in report
    assert "## Rubric Failures" in report
    assert "## Runtime Summary" not in report
    assert (
        "| with_skill | sample/service/sample-skill | sample/service | 1 | 100% (1/1), avg score 4 | 456 | 12.3s | - | - | - |"
        in report
    )


def report_for_kind(tmp_path: Path, eval_kind: str) -> str:
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    sanity = GradeCheckResult(id="file", description="file", passed=True)
    runtime = GradeCheckResult(
        id="observer", description="observer", passed=True, category="runtime"
    )
    rubric_path = tmp_path / "rubric_grade.json"
    rubric_path.write_text(
        json.dumps(
            {
                "overall_pass": True,
                "score": 4,
                "checks": [{"id": "quality", "pass": True, "evidence": "ok"}],
            }
        ),
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
        description="Runtime telemetry reaches Splunk Observability Studio.",
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


def case_result(
    with_skill: SideResult | None, baseline: SideResult | None
) -> CaseResult:
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
        create_backend,
        CodexBackend,
        CursorBackend,
        ClaudeBackend,
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
                "description": "Runtime telemetry reaches Splunk Observability Studio.",
                "compose_file": "docker-compose.yml",
                "expect": {"endpoints": [{"id": "logs", "url": "/api/query/logs"}]},
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
            description="Runtime telemetry reaches Splunk Observability Studio.",
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

    assert failures == ["logs/request-logs expected unique records by traceId, spanId"]


def test_runtime_service_log_expectation_proves_preserved_sink(
    monkeypatch, tmp_path: Path
):
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
                json.dumps([{"Service": "app", "State": "exited", "ExitCode": 0}]),
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
    assert (
        compose_ps_records("\n".join(json.dumps(item) for item in records)) == records
    )


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


@pytest.mark.parametrize("strict_output", [False, True])
def test_run_case_passes_configured_agent_and_judge_timeouts(tmp_path: Path, strict_output: bool):
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
        strict_rubric_output=strict_output,
    )
    backend = DimensionBackend([dimension_grade("pass")]) if strict_output else RecordingBackend()

    result = run_case(
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
    assert len(backend.judge_timeouts) == 1
    assert 0 < backend.judge_timeouts[0] <= 1200
    if not strict_output:
        assert backend.judge_timeouts == [1200]
    assert result.with_skill is not None
    assert result.with_skill.strict_rubric_output is strict_output
    assert not result.with_skill.errors
    assert result.with_skill.agent_tokens == 1
    assert result.with_skill.rubric_tokens == 1
    assert result.with_skill.tokens == 2
    assert result.with_skill.agent_usage is not None
    assert result.with_skill.agent_usage.provider_total_tokens == 1
    assert result.with_skill.rubric_usage is not None
    assert result.with_skill.rubric_usage.provider_total_tokens == 1
    summary = json.loads(
        (Path(result.with_skill.trace_path).parent / "summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["agent_usage"]["provider_total_tokens"] == 1
    assert summary["rubric_usage"]["provider_total_tokens"] == 1
    assert summary["strict_rubric_output"] is strict_output


def write_loaded_skill(root: Path, skill: str) -> Path:
    skill_dir = root / ".agents" / "skills" / skill
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(f"name: {skill}\n", encoding="utf-8")
    return skill_path


def instruction_guard_check(
    root: Path,
    events: list[dict[str, Any]],
    *,
    trace: TraceSummary | None = None,
) -> GradeCheckResult:
    (root / "service").mkdir(exist_ok=True)
    if trace is None:
        trace_path = root / "instruction-trace.jsonl"
        trace_path.write_text(
            "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8"
        )
        trace = parse_trace(trace_path)
    case = sanity_case(
        skill="otel-audit",
        language="python",
        service="example",
        id="python/example/audit/direct",
        base_id="python/example/audit",
    )
    grade = grade_sanity(case, root, "done", trace, "with_skill")
    return next(
        check for check in grade.checks if check.id == "skill-instructions-read"
    )


def codex_command_event(
    command: str,
    status: str,
    *,
    item_id: str,
    output: str = "",
) -> dict[str, Any]:
    return {
        "type": "item.completed",
        "item": {
            "id": item_id,
            "type": "command_execution",
            "command": command,
            "aggregated_output": output,
            "exit_code": 0 if status == "completed" else 1,
            "status": status,
        },
    }


def claude_tool_use(
    tool_id: str, name: str, tool_input: dict[str, Any]
) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}
            ],
        },
    }


def claude_tool_result(
    tool_id: str, content: Any, *, is_error: bool = False
) -> dict[str, Any]:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": content,
                    "is_error": is_error,
                }
            ],
        },
    }


def write_claude_trace(root: Path, events: list[dict[str, Any]]) -> TraceSummary:
    trace_path = root / "claude-instruction-trace.jsonl"
    trace_path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8"
    )
    return _parse_claude_trace(trace_path)


def empty_trace(tmp_path: Path) -> Path:
    path = tmp_path / "trace.jsonl"
    path.write_text("", encoding="utf-8")
    return path


class RecordingBackend:
    name = "recording"

    def __init__(self) -> None:
        self.agent_timeouts: list[int] = []
        self.judge_timeouts: list[int] = []

    def run_agent(
        self,
        *,
        prompt: str,
        exec_dir: Path,
        model: str | None = None,
        timeout: int = 1200,
    ) -> AgentResult:
        self.agent_timeouts.append(timeout)
        trace_path = exec_dir / "trace.jsonl"
        final_path = exec_dir / "last_message.md"
        stderr_path = exec_dir / "stderr.txt"
        trace_path.write_text(
            json.dumps({"type": "turn.completed", "usage": {"total_tokens": 1}}) + "\n",
            encoding="utf-8",
        )
        final_path.write_text("done", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return AgentResult(
            returncode=0,
            trace_path=trace_path,
            final_message_path=final_path,
            stderr_path=stderr_path,
        )

    def run_judge(
        self,
        *,
        prompt: str,
        exec_dir: Path,
        model: str | None = None,
        schema_path: Path | None = None,
        timeout: int = 900,
        output_dir: Path | None = None,
        read_dirs: tuple[Path, ...] = (),
    ) -> AgentResult:
        self.judge_timeouts.append(timeout)
        trace_path = (output_dir or exec_dir) / "rubric_trace.jsonl"
        output_path = (output_dir or exec_dir) / "rubric_grade.json"
        stderr_path = (output_dir or exec_dir) / "rubric_stderr.txt"
        trace_path.write_text(
            json.dumps({"type": "turn.completed", "usage": {"total_tokens": 1}}) + "\n",
            encoding="utf-8",
        )
        output_path.write_text(
            json.dumps(
                {
                    "overall_pass": True,
                    "score": 100,
                    "checks": [
                        {
                            "id": "rubric-1",
                            "pass": True,
                            "notes": "ok",
                            "evidence": "recorded",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        stderr_path.write_text("", encoding="utf-8")
        return AgentResult(
            returncode=0,
            trace_path=trace_path,
            final_message_path=output_path,
            stderr_path=stderr_path,
        )

    def parse_trace(self, trace_path: Path):
        return parse_trace(trace_path)


class FailingJudgeBackend(RecordingBackend):
    name = "codex"

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
        raise RuntimeError("judge unavailable")


def test_failed_judge_attempt_reports_absent_usage_in_rubric_artifacts(
    tmp_path: Path,
):
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
    run_root = tmp_path / ".workspace" / "codex-evals" / "sample-skill" / "run"
    result = run_case(
        repo_root=tmp_path,
        run_root=run_root,
        case=case,
        skill_dir=skill_dir,
        model="agent-model",
        judge_model="judge-model",
        rubric=True,
        sides=("with_skill",),
        backend=FailingJudgeBackend(),
    )

    assert result.with_skill is not None
    assert result.with_skill.rubric_usage is not None
    assert result.with_skill.rubric_usage.provider == "codex"
    assert result.with_skill.rubric_usage.observed is False
    write_session_results(
        [
            {
                "mode": "with_skill",
                "eval_kind": "rubric",
                "repo_root": tmp_path,
                "run_root": run_root,
                "skill": "sample-skill",
                "results": [result],
            }
        ]
    )
    report_path, benchmark_path = render_reports_for_run_root(run_root, "rubric")

    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    coverage = benchmark["evals"][0]["with_skill"]["rubric_usage"]["coverage"]
    assert coverage["modeled_count"] == 1
    assert coverage["observed_count"] == 0
    report = report_path.read_text(encoding="utf-8")
    assert "## Judge Token Usage" in report
    assert "| codex | unknown | absent |" in report


def dimension_case(count=3, **updates):
    return RubricEvalCase(
        id="sample/service/rubric/direct", base_id="sample/service/rubric",
        prompt_id="direct", skill="sample-skill", language="sample", service="service",
        task="Assess the candidate.", rubric=[f"Requirement {index}." for index in range(1, count + 1)],
        strict_rubric_output=True, **updates,
    )


def dimension_grade(*outcomes, start=1):
    return {"checks": [
        {"id": f"rubric-{index}", "result": outcome,
         "notes": "Inspected the requirement.", "evidence": "service/answer.md:1"}
        for index, outcome in enumerate(outcomes, start)
    ]}


class DimensionBackend(RecordingBackend):
    def __init__(self, outputs, hook=None):
        super().__init__()
        self.outputs = outputs
        self.hook = hook
        self.directories = []
        self.output_directories = []
        self.prompts = []

    def run_judge(self, **kwargs):
        index = len(self.directories)
        self.directories.append(kwargs["exec_dir"])
        self.output_directories.append(kwargs["output_dir"])
        self.prompts.append(kwargs["prompt"])
        result = super().run_judge(**kwargs)
        output = self.outputs[index]
        if self.hook:
            replacement = self.hook(index, kwargs, result)
            if replacement is not None:
                return replacement
        if isinstance(output, BaseException):
            raise output
        result.final_message_path.write_text(
            output if isinstance(output, str) else json.dumps(output), encoding="utf-8",
        )
        return result


def test_dimension_grading_keeps_independent_artifacts_and_continues_after_error(tmp_path):
    workspace = tmp_path / "task"
    workspace.mkdir()
    # Candidate files with grader-like names remain evidence and are never overwritten.
    for name in ("rubric_grade.json", "rubric_trace.jsonl", "prompt.txt"):
        (workspace / name).write_text("candidate evidence", encoding="utf-8")
    case = dimension_case(rubric_dimensions=[
        {"id": name, "criteria": [f"rubric-{index}"]}
        for index, name in enumerate(("correctness", "proof", "scope"), 1)
    ])
    backend = DimensionBackend([
        dimension_grade("pass"), RuntimeError("judge unavailable"), dimension_grade("fail", start=3),
    ])
    path = run_rubric_dimensions(
        case=case, workspace_dir=workspace, output_dir=tmp_path / "grades",
        model="judge-model", deadline=time.monotonic() + 30, backend=backend,
    )
    data = json.loads(path.read_text())
    assert data["status"] == "incomplete"
    assert data["acceptance"] == "incomplete"
    assert data["overall_pass"] is None
    assert data["score"] == 50
    assert data["counts"] == {"pass": 1, "fail": 1, "not_proven": 0,
                              "not_applicable": 0, "ungraded": 1, "total": 3}
    assert [row["result"] for row in data["checks"]] == ["pass", "ungraded", "fail"]
    assert [row["status"] for row in data["dimensions"]] == ["graded", "grader_error", "graded"]
    assert len(set(backend.directories)) == 3
    for index, (directory, prompt, dimension) in enumerate(zip(
        backend.directories, backend.prompts, data["dimensions"], strict=True,
    ), 1):
        assert backend.output_directories[index - 1] == path.parent / f"dimension-{index}"
        assert not directory.resolve().is_relative_to(path.parent)
        assert not directory.resolve().is_relative_to(workspace.resolve())
        assert not directory.exists()
        assert str(workspace.resolve()) in prompt
        assert f"rubric-{index}: Requirement {index}." in prompt
        assert all(f"rubric-{other}:" not in prompt for other in range(1, 4) if other != index)
        assert (path.parent / dimension["artifacts"]["prompt"]).read_text() == prompt
        assert (path.parent / dimension["artifacts"]["trace"]).exists()
        assert dimension["usage"]["provider_total_tokens"] == 1
    assert "judge unavailable" in data["dimensions"][1]["error"]
    assert all(path.read_text() == "candidate evidence" for path in workspace.iterdir())


@pytest.mark.parametrize(("outcomes", "acceptance", "score"), [
    (["pass", "pass"], "pass", 100),
    (["pass", "fail"], "fail", 50),
    (["pass", "not_proven"], "fail", 50),
    (["pass", "not_applicable"], "pass", 100),
    (["not_applicable", "not_applicable"], "vacuous", None),
])
def test_dimension_grading_computes_credit_without_awarding_inapplicability(tmp_path, outcomes, acceptance, score):
    workspace = tmp_path / "task"
    workspace.mkdir()
    path = run_rubric_dimensions(
        case=dimension_case(2), workspace_dir=workspace, output_dir=tmp_path / "grades",
        model=None, deadline=time.monotonic() + 30,
        backend=DimensionBackend([dimension_grade(*outcomes)]),
    )
    data = json.loads(path.read_text())
    assert data["status"] == "complete"
    assert data["acceptance"] == acceptance
    assert data["score"] == score
    assert data["overall_pass"] == ({"pass": True, "fail": False, "vacuous": None}[acceptance])
    assert data["counts"]["not_applicable"] == outcomes.count("not_applicable")
    assert data["counts"]["ungraded"] == 0


@pytest.mark.parametrize("fault", ["missing", "duplicate", "reordered", "blank", "blank_notes", "unknown_result", "extra", "malformed", "exit"])
def test_dimension_grading_rejects_invalid_results_and_preserves_raw_output(tmp_path, fault):
    workspace = tmp_path / "task"
    workspace.mkdir()
    output = dimension_grade("pass", "pass")
    if fault == "missing":
        output["checks"].pop()
    elif fault == "duplicate":
        output["checks"][1]["id"] = "rubric-1"
    elif fault == "reordered":
        output["checks"].reverse()
    elif fault == "blank":
        output["checks"][0]["evidence"] = " \n "
    elif fault == "blank_notes":
        output["checks"][0]["notes"] = " \n "
    elif fault == "unknown_result":
        output["checks"][0]["result"] = "probably"
    elif fault == "extra":
        output["score"] = 100
    elif fault == "malformed":
        output = "not JSON"

    def hook(index, kwargs, result):
        if fault == "exit":
            result.final_message_path.write_text(json.dumps(output))
            return AgentResult(returncode=1, trace_path=result.trace_path,
                               final_message_path=result.final_message_path, stderr_path=result.stderr_path)

    path = run_rubric_dimensions(
        case=dimension_case(2), workspace_dir=workspace, output_dir=tmp_path / "grades",
        model=None, deadline=time.monotonic() + 30,
        backend=DimensionBackend([output], hook),
    )
    data = json.loads(path.read_text())
    assert data["status"] == "incomplete"
    assert data["score"] is None
    assert data["counts"]["ungraded"] == 2
    assert data["dimensions"][0]["status"] == "grader_error"
    assert data["dimensions"][0]["error"]
    assert (path.parent / data["dimensions"][0]["artifacts"]["output"]).exists()


def test_dimension_grading_uses_one_elapsed_budget(tmp_path, monkeypatch):
    import pytest_codex_evals.graders.rubric as module

    workspace = tmp_path / "task"
    workspace.mkdir()
    now = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    def advance(index, kwargs, result):
        now[0] += [2.25, 7.25][index]
    case = dimension_case(rubric_dimensions=[
        {"id": f"group-{index}", "criteria": [f"rubric-{index}"]} for index in range(1, 4)
    ])
    backend = DimensionBackend([dimension_grade("pass"), dimension_grade("pass", start=2)], advance)
    path = run_rubric_dimensions(case=case, workspace_dir=workspace, output_dir=tmp_path / "grades",
                                 model=None, deadline=110.0, backend=backend)
    data = json.loads(path.read_text())
    assert backend.judge_timeouts == [10, 7]
    assert now[0] == 109.5
    assert [row["status"] for row in data["dimensions"]] == ["graded", "graded", "not_run"]
    assert "budget exhausted" in data["dimensions"][2]["error"]
    assert data["score"] == 100
    assert data["overall_pass"] is None
    assert data["counts"]["ungraded"] == 1


def test_dimension_grading_discards_changed_evidence_and_stops_later_judges(tmp_path):
    workspace = tmp_path / "task"
    workspace.mkdir()
    def mutate(index, kwargs, result):
        (workspace / "answer.md").write_text("grader changed evidence")
    case = dimension_case(2, rubric_dimensions=[
        {"id": "first", "criteria": ["rubric-1"]}, {"id": "second", "criteria": ["rubric-2"]},
    ])
    backend = DimensionBackend([dimension_grade("pass")], mutate)
    path = run_rubric_dimensions(case=case, workspace_dir=workspace, output_dir=tmp_path / "grades",
                                 model=None, deadline=time.monotonic() + 30, backend=backend)
    data = json.loads(path.read_text())
    assert len(backend.directories) == 1
    assert [row["status"] for row in data["dimensions"]] == ["grader_error", "not_run"]
    assert all("modified" in row["error"] for row in data["dimensions"])
    assert data["score"] is None
    assert data["counts"]["ungraded"] == 2


def test_dimension_grading_keeps_timeout_diagnostics(tmp_path):
    workspace = tmp_path / "task"
    workspace.mkdir()
    class TimeoutBackend(RecordingBackend):
        def run_judge(self, **kwargs):
            raise subprocess.TimeoutExpired("judge", kwargs["timeout"], output=b"partial trace", stderr="partial error")
    path = run_rubric_dimensions(case=dimension_case(1), workspace_dir=workspace, output_dir=tmp_path / "grades",
                                 model=None, deadline=time.monotonic() + 30, backend=TimeoutBackend())
    data = json.loads(path.read_text())
    dimension = data["dimensions"][0]
    assert dimension["status"] == "grader_error"
    assert (path.parent / dimension["artifacts"]["trace"]).read_bytes() == b"partial trace"
    assert (path.parent / dimension["artifacts"]["stderr"]).read_text() == "partial error"


def test_dimension_grading_records_interruption_before_propagating(tmp_path):
    workspace = tmp_path / "task"
    workspace.mkdir()
    output = tmp_path / "grades"
    with pytest.raises(KeyboardInterrupt):
        run_rubric_dimensions(case=dimension_case(1), workspace_dir=workspace, output_dir=output,
                              model=None, deadline=time.monotonic() + 30,
                              backend=DimensionBackend([KeyboardInterrupt()]))
    data = json.loads((output / "rubric_result.json").read_text())
    assert data["status"] == "incomplete"
    assert data["dimensions"][0]["status"] == "grader_error"
    assert "KeyboardInterrupt" in data["dimensions"][0]["error"]
    assert (output / data["dimensions"][0]["artifacts"]["trace"]).exists()


@pytest.mark.parametrize("placement", ["custom", "outside", "symlink"])
def test_dimension_grading_requires_artifacts_owned_by_that_judge(tmp_path, placement):
    workspace = tmp_path / "task"
    workspace.mkdir()
    def relocate(index, kwargs, result):
        root = kwargs["output_dir"] if placement == "custom" else tmp_path
        output = root / "custom-output.json"
        output.write_text(json.dumps(dimension_grade("pass")))
        if placement == "symlink":
            link = kwargs["output_dir"] / "linked.json"
            link.symlink_to(output)
            output = link
        return AgentResult(0, result.trace_path, output, result.stderr_path)
    path = run_rubric_dimensions(case=dimension_case(1), workspace_dir=workspace, output_dir=tmp_path / "grades",
                                 model=None, deadline=time.monotonic() + 30,
                                 backend=DimensionBackend([None], relocate))
    data = json.loads(path.read_text())
    dimension = data["dimensions"][0]
    if placement == "custom":
        assert data["acceptance"] == "pass"
        assert dimension["artifacts"]["output"] == "dimension-1/custom-output.json"
    else:
        assert data["status"] == "incomplete"
        assert "inside their own output directory" in dimension["error"]


@pytest.mark.parametrize("missing", ["metadata", "grade"])
def test_dimension_grading_distinguishes_missing_usage_from_missing_verdict(tmp_path, missing):
    workspace = tmp_path / "task"
    workspace.mkdir()
    def remove(index, kwargs, result):
        result.final_message_path.write_text(json.dumps(dimension_grade("pass")))
        paths = [result.trace_path, result.stderr_path] if missing == "metadata" else [result.final_message_path]
        for path in paths:
            path.unlink()
        return result
    path = run_rubric_dimensions(case=dimension_case(1), workspace_dir=workspace, output_dir=tmp_path / "grades",
                                 model=None, deadline=time.monotonic() + 30,
                                 backend=DimensionBackend([None], remove))
    data = json.loads(path.read_text())
    dimension = data["dimensions"][0]
    if missing == "metadata":
        assert data["acceptance"] == "pass"
        assert dimension["usage"] is None
        assert dimension["artifacts"]["trace"] is None
        assert dimension["artifacts"]["stderr"] is None
    else:
        assert data["status"] == "incomplete"
        assert data["counts"]["ungraded"] == 1
        assert dimension["artifacts"]["output"] is None
        assert "FileNotFoundError" in dimension["error"]


@pytest.mark.parametrize("when", ["before", "after"])
def test_dimension_grading_stops_if_evidence_cannot_be_inspected(tmp_path, monkeypatch, when):
    workspace = tmp_path / "task"
    workspace.mkdir()
    original = Path.iterdir
    inspections = []
    def inspect(path):
        if path == workspace.resolve():
            inspections.append(path)
            if when == "before" or len(inspections) > 1:
                raise PermissionError("task evidence is unreadable")
        return original(path)
    monkeypatch.setattr(Path, "iterdir", inspect)
    case = dimension_case(2, rubric_dimensions=[
        {"id": "first", "criteria": ["rubric-1"]}, {"id": "second", "criteria": ["rubric-2"]},
    ])
    backend = DimensionBackend([dimension_grade("pass")])
    path = run_rubric_dimensions(case=case, workspace_dir=workspace, output_dir=tmp_path / "grades",
                                 model=None, deadline=time.monotonic() + 30, backend=backend)
    data = json.loads(path.read_text())
    assert len(backend.directories) == (0 if when == "before" else 1)
    assert data["counts"]["ungraded"] == 2
    assert all("unreadable" in row["error"] for row in data["dimensions"])


def test_dimension_grading_rechecks_budget_after_preparing_prompt(tmp_path, monkeypatch):
    import pytest_codex_evals.graders.rubric as module

    workspace = tmp_path / "task"
    workspace.mkdir()
    ticks = iter([0.0, 0.0, 1.5])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks, 1.5))
    backend = DimensionBackend([])
    path = run_rubric_dimensions(case=dimension_case(1), workspace_dir=workspace, output_dir=tmp_path / "grades",
                                 model=None, deadline=2.0, backend=backend)
    data = json.loads(path.read_text())
    assert not backend.directories
    assert data["dimensions"][0]["status"] == "not_run"
    assert "budget exhausted" in data["dimensions"][0]["error"]


def test_dimension_grading_refuses_temporary_cwd_inside_a_repository(tmp_path, monkeypatch):
    import tempfile

    repository = tmp_path / "consumer"
    (repository / ".git").mkdir(parents=True)
    temporary = repository / "tmp"
    temporary.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temporary))
    workspace = tmp_path / "task"
    workspace.mkdir()
    backend = DimensionBackend([])
    path = run_rubric_dimensions(case=dimension_case(1), workspace_dir=workspace, output_dir=tmp_path / "grades",
                                 model=None, deadline=time.monotonic() + 30, backend=backend)
    data = json.loads(path.read_text())
    assert not backend.directories
    assert data["status"] == "incomplete"
    assert data["counts"]["ungraded"] == 1
    assert "temporary location outside" in data["dimensions"][0]["error"]
    assert not list(temporary.iterdir())


@pytest.mark.parametrize("failure", ["mutation", "interruption"])
def test_strict_runner_preserves_actor_evidence_before_grading(tmp_path, failure):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "answer.md").write_text("original actor evidence")
    skill = tmp_path / "skills/sample-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("name: sample-skill\n")
    class MutatingBackend(DimensionBackend):
        def run_agent(self, **kwargs):
            self.task_dir = kwargs["exec_dir"]
            return super().run_agent(**kwargs)
    def change(index, kwargs, result):
        (backend.task_dir / "service/answer.md").write_text("changed by grader")
    backend = MutatingBackend([KeyboardInterrupt() if failure == "interruption" else dimension_grade("pass")], change)
    run_root = tmp_path / ".workspace/codex-evals/sample-skill/run"
    def execute():
        return run_case(repo_root=tmp_path, run_root=run_root,
                        case=dimension_case(1, fixture_dir=fixture), skill_dir=skill,
                        sides=("with_skill",), backend=backend)
    if failure == "interruption":
        with pytest.raises(KeyboardInterrupt):
            execute()
    else:
        assert execute().with_skill.errors
    artifact = run_root / "cases/sample/service/direct/with_skill"
    summary = json.loads((artifact / "summary.json").read_text())
    assert (artifact / "service/answer.md").read_text() == "original actor evidence"
    assert Path(summary["trace_path"]).is_file()
    assert Path(summary["final_message_path"]).read_text() == "done"
    assert (artifact / "grade.json").is_file()
    assert json.loads(Path(summary["rubric_result_path"]).read_text())["status"] == "incomplete"
    assert not backend.task_dir.exists()


@pytest.mark.parametrize("outcomes", [["pass", "not_proven", "not_applicable"], ["not_applicable"] * 3,
                                      ["pass", RuntimeError("unavailable"), "pass"]])
def test_strict_results_survive_reports_without_hiding_gaps_or_missing_usage(tmp_path, outcomes):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    skill = tmp_path / "skills/sample-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("name: sample-skill\n")
    class PartialUsageBackend(DimensionBackend):
        def parse_trace(self, path):
            if path.parent.name == "dimension-2":
                raise ValueError("usage unavailable")
            return super().parse_trace(path)
    case = dimension_case(3, fixture_dir=fixture, rubric_dimensions=[
        {"id": f"group-{index}", "criteria": [f"rubric-{index}"]} for index in range(1, 4)
    ])
    backend = PartialUsageBackend([value if isinstance(value, Exception) else dimension_grade(value, start=index)
                                   for index, value in enumerate(outcomes, 1)])
    run_root = tmp_path / ".workspace/codex-evals/sample-skill/run"
    result = run_case(repo_root=tmp_path, run_root=run_root, case=case, skill_dir=skill,
                      sides=("with_skill",), backend=backend)
    side = SideResult.model_validate_json(result.with_skill.model_dump_json())
    assert side.rubric_tokens == 2
    assert side.rubric_usage.provider_total_tokens is None
    assert side.rubric_usage.total_tokens is None
    loaded = load_rubric_grade(side)
    assert loaded["counts"]["total"] == 3
    assert len(loaded["dimensions"]) == 3
    assert loaded["dimensions"][1]["usage"] is None
    assert "usage unavailable" in loaded["dimensions"][1]["usage_error"]
    write_session_results([{"mode": "with_skill", "eval_kind": "rubric", "repo_root": tmp_path,
                            "run_root": run_root, "skill": "sample-skill", "results": [result]}])
    report_path, benchmark_path = render_reports_for_run_root(run_root, "rubric")
    benchmark = json.loads(benchmark_path.read_text())
    summary = benchmark["evals"][0]["with_skill"]
    strict = summary["rubric"]["strict"]
    coverage = summary["rubric_usage"]["coverage"]
    assert coverage["record_count"] == 3
    assert coverage["preferred_total_count"] == 2
    assert strict["counts"] == loaded["counts"]
    report = report_path.read_text()
    if isinstance(outcomes[1], Exception):
        assert loaded["score"] == 100
        assert loaded["overall_pass"] is None
        assert summary["rubric"]["average_score"] is None
        assert strict["incomplete"] == 1
        assert "1/1 strict runs incomplete" in report
        assert "1 ungraded" in report
        assert "UNGRADED" in report
    elif outcomes[0] == "not_applicable":
        assert loaded["score"] is None
        assert loaded["overall_pass"] is None
        assert strict["vacuous"] == 1
        assert "1 all-N/A" in report
        assert "FAIL" not in report
    else:
        assert loaded["score"] == 50
        assert loaded["overall_pass"] is False
        assert "1 not proven" in report
        assert "NOT_PROVEN" in report


@pytest.mark.parametrize('extra_result', [None, 7, 'pass', 'not_applicable'])
def test_custom_schema_metadata_does_not_change_legacy_failure_reporting(tmp_path, extra_result):
    case = RubricEvalCase(id='sample/service/direct', base_id='sample/service', prompt_id='direct',
                         skill='sample-skill', language='sample', service='service', task='Assess.',
                         rubric=['Correct output.'])
    payload = {'overall_pass': True, 'score': 0, 'checks': [
        {'id': 'quality', 'pass': False, 'result': extra_result,
         'notes': 'Observed failure.', 'evidence': 'answer.md:1'},
    ]}
    schema = tmp_path / 'custom.schema.json'
    schema.write_text(json.dumps({'type': 'object', 'required': ['overall_pass', 'score', 'checks']}))
    class Backend:
        def run_judge(self, **kwargs):
            output = tmp_path / 'rubric_grade.json'
            output.write_text(json.dumps(payload))
            return AgentResult(0, tmp_path / 'trace.jsonl', output, tmp_path / 'stderr.txt')
    grade = run_rubric_grade(case=case, side_dir=tmp_path, schema_path=schema, model=None, backend=Backend())
    side = SideResult(side='with_skill', exit_code=0, trace_path='trace.jsonl', final_message_path='last_message.md',
                      grade=GradeResult(), rubric_grade_path=str(grade))
    result = CaseResult(id=case.id, base_id=case.base_id, prompt_id=case.prompt_id, skill=case.skill,
                        language=case.language, service=case.service, with_skill=side)
    run_root = tmp_path / '.workspace/codex-evals/sample-skill/run'
    write_session_results([{'mode': 'with_skill', 'eval_kind': 'rubric', 'repo_root': tmp_path,
                            'run_root': run_root, 'skill': 'sample-skill', 'results': [result]}])
    report, benchmark = render_reports_for_run_root(run_root, 'rubric')
    assert 'rubric:quality FAIL' in report.read_text()
    assert json.loads(benchmark.read_text())['evals'][0]['with_skill']['rubric']['passed'] == 0


@pytest.mark.parametrize("backend_type", [CodexBackend, CursorBackend, ClaudeBackend])
@pytest.mark.parametrize("separate_output", [False, True])
def test_judge_backends_keep_working_directory_output_and_read_access_separate(tmp_path, monkeypatch, backend_type, separate_output):
    working = tmp_path / "working"
    output = tmp_path / "output" if separate_output else working
    evidence = tmp_path / "evidence"
    for directory in {working, output, evidence}:
        directory.mkdir()
    payload = dimension_grade("pass")
    calls = []
    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if "--output-last-message" in command:
            Path(command[command.index("--output-last-message") + 1]).write_text(json.dumps(payload))
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"result": json.dumps(payload)}), stderr="diagnostic")
    monkeypatch.setattr("pytest_codex_evals.backends.subprocess.run", fake_run)
    backend = backend_type(command="judge-cli", extra_args=["--test-extra"])
    result = backend.run_judge(prompt="Grade it.", exec_dir=working, model="judge-model", timeout=17,
                               output_dir=output if separate_output else None,
                               read_dirs=(evidence,) if separate_output else ())
    command, options = calls[0]
    assert result.final_message_path == output / "rubric_grade.json"
    assert json.loads(result.final_message_path.read_text()) == payload
    assert result.trace_path == output / "rubric_trace.jsonl"
    assert result.trace_path.is_file()
    assert result.stderr_path.read_text() == "diagnostic"
    assert options["timeout"] == 17
    assert "--test-extra" in command
    assert command[command.index("--model") + 1] == "judge-model"
    if backend_type is ClaudeBackend:
        assert options["cwd"] == working
        assert ("--add-dir" in command) is separate_output
        assert ("--setting-sources" in command) is separate_output
        if separate_output:
            assert command[command.index("--add-dir") + 1] == str(evidence)
            assert command[command.index("--setting-sources") + 1] == "user"
            assert command.index("--setting-sources") < command.index("--test-extra")
    else:
        assert command[command.index("--cd") + 1] == str(working)
        assert options["cwd"] == (working if separate_output else None)
    if separate_output:
        assert not list(working.iterdir())
