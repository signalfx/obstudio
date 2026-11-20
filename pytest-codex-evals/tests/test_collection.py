from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError

from pytest_codex_evals.definitions.runtime import (
    RuntimeExpectations,
    ServiceLogExpectation,
)
from pytest_codex_evals.eval_files import iter_eval_files
from pytest_codex_evals.schema_resources import schema_validator


pytest_plugins = ("pytester",)


def write_eval_repo(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml(
        """
        [project]
        name = "sample-evals"
        version = "0.1.0"

        [tool.pytest.ini_options]
        testpaths = ["evals"]
        """
    )
    skill_dir = pytester.path / "skills" / "sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: sample-skill\n---\n", encoding="utf-8")

    other_skill_dir = pytester.path / "skills" / "other-skill"
    other_skill_dir.mkdir(parents=True)
    (other_skill_dir / "SKILL.md").write_text("---\nname: other-skill\n---\n", encoding="utf-8")

    service_dir = pytester.path / "evals" / "sample" / "service"
    service_dir.mkdir(parents=True)
    (service_dir / "app.py").write_text("print('hello')\n", encoding="utf-8")
    eval_dir = service_dir / "eval" / "qual"
    eval_dir.mkdir(parents=True)
    (eval_dir / "sample.json").write_text(
        json.dumps(
            {
                "skill": "sample-skill",
                "prompts": [
                    {"id": "direct", "task": "Scan the service."},
                    {"id": "runtime-preserving", "task": "Keep the runtime shape."},
                ],
                "rubric": ["The answer cites concrete evidence."],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    other_dir = pytester.path / "evals" / "sample" / "other"
    other_dir.mkdir(parents=True)
    (other_dir / "app.py").write_text("print('other')\n", encoding="utf-8")
    other_eval_dir = other_dir / "eval" / "qual"
    other_eval_dir.mkdir(parents=True)
    (other_eval_dir / "other.json").write_text(
        json.dumps(
            {
                "skill": "other-skill",
                "prompts": [{"id": "direct", "task": "Scan the other service."}],
                "rubric": ["The answer cites concrete evidence."],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def test_eval_json_files_collect_as_pytest_items(pytester: pytest.Pytester):
    write_eval_repo(pytester)
    skill_dir = pytester.path / "skills" / "sample-skill"

    result = pytester.runpytest("--collect-only", "-q", "--skill", str(skill_dir))

    result.assert_outcomes()
    result.stdout.fnmatch_lines(
        [
            "evals/sample/service/eval/qual/sample.json::sample-skill::sample/service::direct",
            "evals/sample/service/eval/qual/sample.json::sample-skill::sample/service::runtime-preserving",
            "2 tests collected*",
        ]
    )


def test_eval_json_files_validate_without_running_codex(pytester: pytest.Pytester):
    write_eval_repo(pytester)
    skill_dir = pytester.path / "skills" / "sample-skill"
    generated_target = pytester.path.parent / f"{pytester.path.name}-generated"
    generated_target.mkdir()
    (pytester.path / "evals" / "sample" / "service" / ".venv").symlink_to(
        generated_target,
        target_is_directory=True,
    )

    result = pytester.runpytest("--skill", str(skill_dir))

    result.assert_outcomes(passed=2)
    raw_runs = list(pytester.path.glob(".workspace/codex-evals/sample-skill/*/runs/validation.json"))
    assert len(raw_runs) == 1
    payload = json.loads(raw_runs[0].read_text(encoding="utf-8"))
    assert payload["metadata"]["mode"] == "validation"
    assert payload["metadata"]["eval_kind"] == "validation"
    assert payload["metadata"]["validation_scope"] == "full"
    assert len(payload["results"]) == 2
    assert not (pytester.path / "eval-reports" / "sample-skill" / "validation" / "report.md").exists()


@pytest.fixture
def recorded_eval_repo(pytester: pytest.Pytester) -> Path:
    import pytest_codex_evals.report as report_module

    write_eval_repo(pytester)
    bare = pytester.path / "evals/sample/service/eval/sanity/native.json"
    bare.parent.mkdir()
    bare.write_text(json.dumps({
        "skill": "sample-skill",
        "prompts": [{"id": "native", "task": "$sample-skill ./service"}],
        "checks": [],
    }), encoding="utf-8")
    package = pytester.path / "pytest-codex-evals/src/pytest_codex_evals"
    shutil.copytree(Path(report_module.__file__).parent, package,
                    ignore=shutil.ignore_patterns("__pycache__"))
    (package.parent.parent / "pyproject.toml").write_text(
        '[project]\nname = "pytest-codex-evals"\nversion = "0.2.0"\n', encoding="utf-8",
    )
    home = pytester.path / "codex-home"
    home.mkdir()
    calls = pytester.path / "actor-calls.jsonl"
    pytester.makeconftest(f'''
        import json
        import pytest
        from pathlib import Path
        from pytest_codex_evals import backends, codex_home, report

        def controlled_process(command, *, stdout_path, stderr_path, **kwargs):
            workspace = Path(command[command.index("--cd") + 1])
            prompt = command[-1]
            skills = sorted(path.parent.name for path in workspace.glob(".agents/skills/*/SKILL.md"))
            with Path({str(calls)!r}).open("a", encoding="utf-8") as output:
                output.write(json.dumps({{"prompt": prompt, "skills": skills, "side": workspace.name}}) + "\\n")
            read_skill = (prompt in {{"$sample-skill", "$sample-skill ./service"}}
                          and not Path({str(pytester.path / "omit-skill-read")!r}).exists())
            relative = ".agents/skills/sample-skill/SKILL.md" if read_skill else "service/app.py"
            trace = json.dumps({{"type": "item.completed", "item": {{
                "id": "first-action", "type": "command_execution", "status": "completed", "exit_code": 0,
                "command": "cat " + relative, "aggregated_output": (workspace / relative).read_text(),
            }}}}) + "\\n"
            stdout_path.write_text(trace, encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            Path(command[command.index("--output-last-message") + 1]).write_text("Done.", encoding="utf-8")
            return backends.StreamedCommandResult(0, trace, "")

        @pytest.hookimpl(trylast=True)
        def pytest_configure(config):
            patch = pytest.MonkeyPatch()
            config.add_cleanup(patch.undo)
            patch.setenv("CODEX_EVAL_HOME", {str(home)!r})
            patch.setattr(codex_home, "_temporary_directories", lambda: {{Path({str(pytester.path / "actor-tmp")!r})}})
            patch.setattr(report, "__file__", {str(package / "report.py")!r})
            patch.setattr(backends, "_prepare_eval_python_dependencies", lambda _: None)
            patch.setattr(backends, "run_streamed_command", controlled_process)
    ''')
    return calls


def test_collected_ab_uses_identical_tasks_and_isolated_skill_availability(
    pytester: pytest.Pytester, recorded_eval_repo: Path,
):
    definition = pytester.path / "evals/sample/service/eval/qual/sample.json"
    payload = json.loads(definition.read_text(encoding="utf-8"))
    payload["prompts"][0]["task"] = "Scan the service.\nKeep café output intact."
    definition.write_text(json.dumps(payload), encoding="utf-8")

    result = pytester.runpytest("--ab", "--no-rubric", "--skill",
                               str(pytester.path / "skills/sample-skill"), "-q", "-rs")

    result.assert_outcomes(passed=2, skipped=1)
    assert "Bare skill invocation checks run only in with_skill mode" in result.stdout.str()
    calls = [json.loads(line) for line in recorded_eval_repo.read_text(encoding="utf-8").splitlines()]
    assert [(call["prompt"].encode("utf-8"), call["skills"], call["side"]) for call in calls] == [
        (prompt["task"].encode("utf-8"), skills, side)
        for prompt in payload["prompts"]
        for skills, side in [(["sample-skill"], "with_skill"), ([], "baseline")]
    ]
    run = next(pytester.path.glob(".workspace/codex-evals/sample-skill/*/runs/standard-ab.json"))
    actual = json.loads(run.read_text(encoding="utf-8"))
    assert actual["metadata"]["comparison_prompt"] == "shared_task"
    assert actual["metadata"]["ab_enabled"] is True
    assert len(actual["results"]) == 2
    for item in actual["results"]:
        loaded = {check["id"]: check for check in item["with_skill"]["grade"]["checks"]}
        baseline = {check["id"]: check for check in item["baseline"]["grade"]["checks"]}
        assert loaded["skills-loaded"]["passed"] and not loaded["skills-loaded"]["skipped"]
        assert loaded["skill-instructions-read"]["skipped"]
        assert all(baseline[key]["passed"] and not baseline[key]["skipped"]
                   for key in ("skills-not-loaded", "baseline-skill-isolation", "final-message-present"))
        assert item["with_skill"]["errors"] == item["baseline"]["errors"] == []
    provenance = json.loads((run.parent / "validation.json").read_text(encoding="utf-8"))
    assert [item["prompt_id"] for item in provenance["results"]] == ["direct", "runtime-preserving"]
    assert provenance["metadata"]["comparison_prompt"] == "shared_task"
    for item in provenance["results"]:
        assert item["definition_path"] == str(definition)
        for source in ("ab.py", "runner.py", "graders/shared.py", "plugin.py"):
            relative = "pytest-codex-evals/src/pytest_codex_evals/" + source
            assert item["source_files"][relative] == hashlib.sha256((pytester.path / relative).read_bytes()).hexdigest()


    from pytest_codex_evals.report import render_reports_for_run_root, verify_published_report_sources
    destination = pytester.path / "eval-reports"
    _, benchmark = render_reports_for_run_root(run.parent.parent, "validation", output_dir=destination)
    assert json.loads(benchmark.read_text())["metadata"]["comparison_prompt"] == "shared_task"
    import pytest_codex_evals.report as report_module
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(report_module, "__file__", str(
            pytester.path / "pytest-codex-evals/src/pytest_codex_evals/report.py"
        ))
        assert verify_published_report_sources(pytester.path) == [destination / "sample-skill/validation/benchmark.json"]


def test_collected_baseline_skips_bare_loading_case(
    pytester: pytest.Pytester, recorded_eval_repo: Path,
):
    (pytester.path / "codex-evals.toml").write_text(
        '[run]\nmode = "with_baseline"\neval_kind = "standard"\n', encoding="utf-8",
    )

    result = pytester.runpytest("--no-rubric", "--skill", str(pytester.path / "skills/sample-skill"), "-q", "-rs")

    result.assert_outcomes(passed=2, skipped=1)
    assert "Bare skill invocation checks run only in with_skill mode" in result.stdout.str()
    calls = [json.loads(line) for line in recorded_eval_repo.read_text(encoding="utf-8").splitlines()]
    assert calls == [
        {"prompt": task, "skills": [], "side": "baseline"}
        for task in ("Scan the service.", "Keep the runtime shape.")
    ]
    run = next(pytester.path.glob(".workspace/codex-evals/sample-skill/*/runs/standard-with_baseline.json"))
    provenance = json.loads((run.parent / "validation.json").read_text(encoding="utf-8"))
    assert [item["prompt_id"] for item in provenance["results"]] == ["direct", "runtime-preserving"]


def test_collected_validation_includes_separate_bare_loading_case(
    pytester: pytest.Pytester, recorded_eval_repo: Path,
):
    result = pytester.runpytest("--skill", str(pytester.path / "skills/sample-skill"), "-q")

    result.assert_outcomes(passed=3)
    assert not recorded_eval_repo.exists()
    run = next(pytester.path.glob(".workspace/codex-evals/sample-skill/*/runs/validation.json"))
    provenance = json.loads(run.read_text(encoding="utf-8"))
    assert {item["prompt_id"] for item in provenance["results"]} == {"direct", "runtime-preserving", "native"}
    for item in provenance["results"]:
        harness_inputs = [path for path in item["source_files"] if path.startswith("pytest-codex-evals/src/")]
        assert bool(harness_inputs) is (item["prompt_id"] == "native")


@pytest.mark.parametrize("task", ["$sample-skill", "$sample-skill ./service"])
@pytest.mark.parametrize("complete_read", [True, False])
def test_collected_standalone_bare_loading_keeps_required_guards(
    pytester: pytest.Pytester, recorded_eval_repo: Path, task: str, complete_read: bool,
):
    bare = pytester.path / "evals/sample/service/eval/sanity/native.json"
    definition = json.loads(bare.read_text(encoding="utf-8"))
    definition["prompts"][0]["task"] = task
    bare.write_text(json.dumps(definition), encoding="utf-8")
    if not complete_read:
        (pytester.path / "omit-skill-read").touch()

    result = pytester.runpytest("--codex-eval-kind", "sanity", "--skill",
                               str(pytester.path / "skills/sample-skill"), "-q")

    result.assert_outcomes(**{"passed" if complete_read else "failed": 1})
    assert [json.loads(line) for line in recorded_eval_repo.read_text(encoding="utf-8").splitlines()] == [
        {"prompt": task, "skills": ["sample-skill"], "side": "with_skill"},
    ]
    run = next(pytester.path.glob(".workspace/codex-evals/sample-skill/*/runs/sanity-with_skill.json"))
    actual = json.loads(run.read_text(encoding="utf-8"))
    assert "comparison_prompt" not in actual["metadata"]
    assert len(actual["results"]) == 1
    side = actual["results"][0]
    assert side["baseline"] is None
    checks = {check["id"]: check for check in side["with_skill"]["grade"]["checks"]}
    assert set(checks) == {"skills-loaded", "skill-instructions-read", "skill-source-unchanged", "final-message-present"}
    assert all(not check["skipped"] for check in checks.values())
    assert checks["skill-instructions-read"]["passed"] is complete_read
    assert all(checks[key]["passed"] for key in ("skills-loaded", "skill-source-unchanged", "final-message-present"))
    if not complete_read:
        assert "with_skill guard failed: skill-instructions-read" in result.stdout.str()


@pytest.mark.parametrize(
    ("configured_agent", "configured_judge", "override", "expected_agent", "expected_judge"),
    [
        ("configured-actor", "", "cli-actor", "cli-actor", ""),
        ("configured-actor", "", "", "configured-actor", ""),
        ("configured-actor", "explicit-judge", "cli-actor", "cli-actor", ""),
        ("", "", "", "", ""),
    ],
)
def test_validation_metadata_does_not_claim_a_judge_model(
    pytester: pytest.Pytester,
    configured_agent: str,
    configured_judge: str,
    override: str,
    expected_agent: str,
    expected_judge: str,
):
    write_eval_repo(pytester)
    config = pytester.path / "codex-evals.toml"
    config.write_text(
        f'[models]\nagent = "{configured_agent}"\njudge = "{configured_judge}"\n',
        encoding="utf-8",
    )
    args = ["--skill", str(pytester.path / "skills" / "sample-skill")]
    if override:
        args.extend(["--model", override])

    result = pytester.runpytest(*args)

    result.assert_outcomes(passed=2)
    raw_runs = list(pytester.path.glob(".workspace/codex-evals/sample-skill/*/runs/validation.json"))
    assert len(raw_runs) == 1
    metadata = json.loads(raw_runs[0].read_text(encoding="utf-8"))["metadata"]
    assert metadata["agent_model"] == expected_agent
    assert metadata["judge_model"] == expected_judge


@pytest.mark.parametrize(
    ("kind", "mode", "judge", "enabled", "disabled_cli", "expected"),
    [
        ("rubric", "with_skill", "", True, False, "cli-actor"),
        ("rubric", "with_skill", "explicit-judge", True, False, "explicit-judge"),
        ("standard", "with_skill", "", True, False, "cli-actor"),
        ("rubric", "with_skill", "explicit-judge", True, True, ""),
        ("standard", "with_skill", "explicit-judge", False, False, ""),
        ("sanity", "with_skill", "explicit-judge", True, False, ""),
        ("runtime", "with_skill", "explicit-judge", True, False, ""),
        ("validation", "validation", "explicit-judge", True, False, ""),
        ("rubric", "validation", "explicit-judge", True, False, ""),
    ],
)
def test_judge_metadata_requires_a_rubric_capable_run(
    pytester: pytest.Pytester,
    kind: str,
    mode: str,
    judge: str,
    enabled: bool,
    disabled_cli: bool,
    expected: str,
):
    pytester.makefile(
        ".toml",
        **{"codex-evals": (
            f'[models]\nagent = "configured-actor"\njudge = "{judge}"\n'
            f'[rubric]\nenabled = {str(enabled).lower()}\n'
        )},
    )
    pytester.makepyfile(test_metadata=f'''
        from pytest_codex_evals.plugin import run_metadata

        def test_metadata(pytestconfig):
            metadata = run_metadata(pytestconfig, pytestconfig.rootpath, "sample-skill", {mode!r})
            assert metadata["agent_model"] == "cli-actor"
            assert metadata["judge_model"] == {expected!r}
            assert metadata["rubric_enabled"] is {bool(expected)!r}
    ''')
    args = ["test_metadata.py", "--codex-eval-kind", kind, "--model", "cli-actor"]
    if disabled_cli:
        args.append("--no-rubric")
    pytester.runpytest(*args).assert_outcomes(passed=1)


def test_validation_scope_tracks_pytest_deselect(pytester: pytest.Pytester):
    write_eval_repo(pytester)
    skill_dir = pytester.path / "skills" / "sample-skill"

    result = pytester.runpytest(
        "--skill",
        str(skill_dir),
        "--deselect",
        "evals/sample/service/eval/qual/sample.json::sample-skill::sample/service::direct",
    )

    result.assert_outcomes(passed=1, deselected=1)
    raw_runs = list(pytester.path.glob(".workspace/codex-evals/sample-skill/*/runs/validation.json"))
    assert len(raw_runs) == 1
    payload = json.loads(raw_runs[0].read_text(encoding="utf-8"))
    assert payload["metadata"]["validation_scope"] == "filtered"
    assert [item["prompt_id"] for item in payload["results"]] == ["runtime-preserving"]


@pytest.mark.parametrize("invalid_definition", ["{", "null"])
def test_validation_scope_tracks_pytest_ignore(
    pytester: pytest.Pytester,
    invalid_definition: str,
):
    write_eval_repo(pytester)
    skill_dir = pytester.path / "skills" / "sample-skill"
    ignored_eval = pytester.path / "evals" / "sample" / "service" / "eval" / "qual" / "sample.json"
    ignored_eval.write_text(invalid_definition, encoding="utf-8")
    secondary_dir = pytester.path / "evals" / "sample" / "secondary"
    secondary_dir.mkdir(parents=True)
    (secondary_dir / "app.py").write_text("print('secondary')\n", encoding="utf-8")
    secondary_eval_dir = secondary_dir / "eval" / "qual"
    secondary_eval_dir.mkdir(parents=True)
    (secondary_eval_dir / "secondary.json").write_text(
        json.dumps(
            {
                "skill": "sample-skill",
                "prompts": [{"id": "direct", "task": "Scan the secondary service."}],
                "rubric": ["The answer cites concrete evidence."],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = pytester.runpytest(
        "--skill",
        str(skill_dir),
        "--ignore=evals/sample/service/eval/qual/sample.json",
    )

    result.assert_outcomes(passed=1)
    raw_runs = list(pytester.path.glob(".workspace/codex-evals/sample-skill/*/runs/validation.json"))
    assert len(raw_runs) == 1
    payload = json.loads(raw_runs[0].read_text(encoding="utf-8"))
    assert payload["metadata"]["validation_scope"] == "filtered"
    assert [item["service"] for item in payload["results"]] == ["secondary"]


@pytest.mark.parametrize("symlink_kind", ["file", "directory"])
def test_validation_scope_rejects_ignored_symlinked_definition(
    pytester: pytest.Pytester,
    symlink_kind: str,
):
    write_eval_repo(pytester)
    skill_dir = pytester.path / "skills" / "sample-skill"
    ignored_eval = pytester.path / "evals" / "sample" / "service" / "eval" / "qual" / "sample.json"
    outside_root = pytester.path.parent / f"{pytester.path.name}-outside"
    outside_root.mkdir()
    outside = outside_root / "sample.json"
    outside.write_text("null", encoding="utf-8")
    ignored_eval.unlink()
    if symlink_kind == "file":
        ignored_eval.symlink_to(outside)
    else:
        ignored_eval.parent.rmdir()
        ignored_eval.parent.symlink_to(outside_root, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        iter_eval_files(pytester.path / "evals")
    secondary_dir = pytester.path / "evals" / "sample" / "secondary"
    secondary_dir.mkdir(parents=True)
    (secondary_dir / "app.py").write_text("print('secondary')\n", encoding="utf-8")
    secondary_eval_dir = secondary_dir / "eval" / "qual"
    secondary_eval_dir.mkdir(parents=True)
    (secondary_eval_dir / "secondary.json").write_text(
        json.dumps(
            {
                "skill": "sample-skill",
                "prompts": [{"id": "direct", "task": "Scan the secondary service."}],
                "rubric": ["The answer cites concrete evidence."],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = pytester.runpytest(
        "--skill",
        str(skill_dir),
        "--ignore=evals/sample/service/eval/qual/sample.json",
    )

    result.assert_outcomes(passed=1)
    raw_runs = list(pytester.path.glob(".workspace/codex-evals/sample-skill/*/runs/validation.json"))
    assert len(raw_runs) == 1
    payload = json.loads(raw_runs[0].read_text(encoding="utf-8"))
    assert payload["metadata"]["validation_scope"] == "filtered"


def test_eval_json_can_declare_a_plugin_local_skill_source(pytester: pytest.Pytester):
    pytester.makepyprojecttoml(
        """
        [project]
        name = "plugin-evals"
        version = "0.1.0"

        [tool.pytest.ini_options]
        testpaths = ["evals"]
        """
    )
    (pytester.path / "skills").mkdir()
    skill_dir = pytester.path / "plugins" / "sample" / "skills" / "observer-control" / "sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: sample-skill\n---\n", encoding="utf-8")
    eval_dir = pytester.path / "evals" / "plugins" / "sample" / "eval" / "qual"
    eval_dir.mkdir(parents=True)
    (eval_dir / "sample.json").write_text(
        json.dumps(
            {
                "skill": "sample-skill",
                "skill_source": "plugins/sample/skills/observer-control/sample-skill",
                "prompts": [{"id": "direct", "task": "Run the plugin skill."}],
                "rubric": ["The answer is valid."],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = pytester.runpytest()

    result.assert_outcomes(passed=1)


def test_prompt_selection_uses_pytest_k(pytester: pytest.Pytester):
    write_eval_repo(pytester)
    skill_dir = pytester.path / "skills" / "sample-skill"

    result = pytester.runpytest("--collect-only", "-q", "--skill", str(skill_dir), "-k", "runtime-preserving")

    result.assert_outcomes()
    result.stdout.fnmatch_lines(
        [
            "evals/sample/service/eval/qual/sample.json::sample-skill::sample/service::runtime-preserving",
            "1/2 tests collected*",
        ]
    )


def test_eval_json_files_do_not_require_fixture_files(pytester: pytest.Pytester):
    write_eval_repo(pytester)
    skill_dir = pytester.path / "skills" / "sample-skill"
    eval_dir = pytester.path / "evals" / "sample" / "no-fixture" / "eval" / "qual"
    eval_dir.mkdir(parents=True)
    (eval_dir / "sample.json").write_text(
        json.dumps(
            {
                "skill": "sample-skill",
                "prompts": [{"id": "direct", "task": "Classify the provided input."}],
                "rubric": ["The answer classifies the input."],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = pytester.runpytest("evals/sample/no-fixture", "--skill", str(skill_dir))

    result.assert_outcomes(passed=1)


def test_xdist_workers_merge_validation_reports(pytester: pytest.Pytester):
    write_eval_repo(pytester)
    skill_dir = pytester.path / "skills" / "sample-skill"

    result = pytester.runpytest("-n", "2", "--skill", str(skill_dir))

    result.assert_outcomes(passed=2)
    raw_runs = list(pytester.path.glob(".workspace/codex-evals/sample-skill/*/runs/validation.json"))
    assert len(raw_runs) == 1
    payload = json.loads(raw_runs[0].read_text(encoding="utf-8"))
    assert payload["metadata"]["mode"] == "validation"
    assert payload["metadata"]["validation_scope"] == "full"
    assert len(payload["results"]) == 2


def test_xdist_filtered_scope_is_computed_after_worker_merge(
    pytester: pytest.Pytester,
):
    write_eval_repo(pytester)
    skill_dir = pytester.path / "skills" / "sample-skill"

    result = pytester.runpytest(
        "-n",
        "2",
        "--skill",
        str(skill_dir),
        "--deselect",
        "evals/sample/service/eval/qual/sample.json::sample-skill::sample/service::direct",
    )

    result.assert_outcomes(passed=1)
    raw_runs = list(pytester.path.glob(".workspace/codex-evals/sample-skill/*/runs/validation.json"))
    assert len(raw_runs) == 1
    payload = json.loads(raw_runs[0].read_text(encoding="utf-8"))
    assert payload["metadata"]["validation_scope"] == "filtered"
    assert [item["prompt_id"] for item in payload["results"]] == ["runtime-preserving"]


def test_xdist_each_full_scope_uses_unique_selection_coverage(
    pytester: pytest.Pytester,
):
    write_eval_repo(pytester)
    skill_dir = pytester.path / "skills" / "sample-skill"

    result = pytester.runpytest(
        "-n",
        "2",
        "--dist=each",
        "--skill",
        str(skill_dir),
    )

    result.assert_outcomes(passed=4)
    raw_runs = list(pytester.path.glob(".workspace/codex-evals/sample-skill/*/runs/validation.json"))
    assert len(raw_runs) == 1
    payload = json.loads(raw_runs[0].read_text(encoding="utf-8"))
    assert payload["metadata"]["validation_scope"] == "full"
    assert len(payload["results"]) == 4


def test_eval_kind_filters_collection_by_file_role(pytester: pytest.Pytester):
    write_eval_repo(pytester)
    skill_dir = pytester.path / "skills" / "sample-skill"
    service_dir = pytester.path / "evals" / "sample" / "service"
    sanity_dir = service_dir / "eval" / "sanity"
    sanity_dir.mkdir(parents=True)
    (sanity_dir / "sample.json").write_text(
        json.dumps(
            {
                "skill": "sample-skill",
                "prompts": [{"id": "direct", "task": "Load the skill and report status."}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    runtime_dir = service_dir / "eval" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "sample.json").write_text(
        json.dumps(
            {
                "skill": "sample-skill",
                "prompts": [{"id": "runtime", "task": "Run runtime telemetry."}],
                "checks": [
                    {
                        "id": "runtime",
                        "description": "Runtime check.",
                        "compose_file": "docker-compose.yml",
                        "expect": {"endpoints": [{"id": "traces", "url": "/api/query/traces", "contains_any": ["sample-service"]}]},
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    sanity = pytester.runpytest("--collect-only", "-q", "--skill", str(skill_dir), "--codex-eval-kind", "sanity")
    sanity.assert_outcomes()
    sanity.stdout.fnmatch_lines(["evals/sample/service/eval/sanity/sample.json::sample-skill::sample/service::direct", "1 test collected*"])

    rubric = pytester.runpytest("--collect-only", "-q", "--skill", str(skill_dir), "--codex-eval-kind", "rubric")
    rubric.assert_outcomes()
    rubric.stdout.fnmatch_lines(
        [
            "evals/sample/service/eval/qual/sample.json::sample-skill::sample/service::direct",
            "evals/sample/service/eval/qual/sample.json::sample-skill::sample/service::runtime-preserving",
            "2 tests collected*",
        ]
    )

    runtime = pytester.runpytest("--collect-only", "-q", "--skill", str(skill_dir), "--codex-eval-kind", "runtime")
    runtime.assert_outcomes()
    runtime.stdout.fnmatch_lines(["evals/sample/service/eval/runtime/sample.json::sample-skill::sample/service::runtime", "1 test collected*"])


def test_runtime_eval_collects_shutdown_correlation_and_service_log_contract(
    pytester: pytest.Pytester,
):
    write_eval_repo(pytester)
    skill_dir = pytester.path / "skills" / "sample-skill"
    runtime_dir = pytester.path / "evals" / "sample" / "service" / "eval" / "runtime"
    runtime_dir.mkdir(parents=True)
    definition = {
        "skill": "sample-skill",
        "prompts": [{"id": "runtime", "task": "Run runtime telemetry."}],
        "checks": [
            {
                "id": "runtime",
                "description": "Runtime check.",
                "compose_file": "docker-compose.yml",
                "stop_services_before_validation": ["app"],
                "expect": {
                    "endpoints": [
                        {
                            "id": "logs",
                            "url": "/api/query/logs",
                            "record_checks": [
                                {
                                    "id": "request-log",
                                    "match": {"body": "request completed"},
                                    "exact_count": 1,
                                    "correlates_with_trace": True,
                                }
                            ],
                        }
                    ],
                    "service_logs": [
                        {
                            "id": "preserved-sink",
                            "occurrences": {"request completed": 1},
                        }
                    ],
                },
            }
        ],
    }
    (runtime_dir / "sample.json").write_text(
        json.dumps(definition, indent=2),
        encoding="utf-8",
    )

    result = pytester.runpytest(
        "--collect-only",
        "-q",
        "--skill",
        str(skill_dir),
        str(runtime_dir),
    )

    result.assert_outcomes()
    result.stdout.fnmatch_lines(
        [
            "evals/sample/service/eval/runtime/sample.json::sample-skill::sample/service::runtime",
            "1 test collected*",
        ]
    )


def test_runtime_schema_rejects_service_log_expectation_without_assertions():
    definition = {
        "skill": "sample-skill",
        "prompts": [{"id": "runtime", "task": "Run runtime telemetry."}],
        "checks": [
            {
                "id": "runtime",
                "description": "Runtime check.",
                "compose_file": "docker-compose.yml",
                "expect": {
                    "endpoints": [{"id": "logs", "url": "/api/query/logs"}],
                    "service_logs": [{"id": "no-op"}],
                },
            }
        ],
    }

    with pytest.raises(ValidationError):
        schema_validator("runtime.schema.json").validate(definition)


def test_runtime_schema_accepts_service_log_only_expectation():
    definition = {
        "skill": "sample-skill",
        "prompts": [{"id": "runtime", "task": "Run runtime telemetry."}],
        "checks": [
            {
                "id": "runtime",
                "description": "Runtime check.",
                "compose_file": "docker-compose.yml",
                "expect": {
                    "service_logs": [
                        {
                            "id": "preserved-sink",
                            "contains_all": ["request completed"],
                        }
                    ]
                },
            }
        ],
    }

    schema_validator("runtime.schema.json").validate(definition)


def test_runtime_schema_accepts_service_log_only_model_shape_with_empty_endpoints():
    expectations = RuntimeExpectations(
        service_logs=[
            ServiceLogExpectation(
                id="preserved-sink",
                contains_all=["request completed"],
            )
        ]
    )
    definition = {
        "skill": "sample-skill",
        "prompts": [{"id": "runtime", "task": "Run runtime telemetry."}],
        "checks": [
            {
                "id": "runtime",
                "description": "Runtime check.",
                "compose_file": "docker-compose.yml",
                "expect": expectations.model_dump(mode="json"),
            }
        ],
    }

    schema_validator("runtime.schema.json").validate(definition)


def test_runtime_schema_rejects_unknown_expectation_key():
    definition = {
        "skill": "sample-skill",
        "prompts": [{"id": "runtime", "task": "Run runtime telemetry."}],
        "checks": [
            {
                "id": "runtime",
                "description": "Runtime check.",
                "compose_file": "docker-compose.yml",
                "expect": {
                    "endpoints": [{"id": "logs", "url": "/api/query/logs"}],
                    "service_logz": [
                        {"id": "misspelled-sink", "contains_all": ["request"]}
                    ],
                },
            }
        ],
    }

    with pytest.raises(ValidationError):
        schema_validator("runtime.schema.json").validate(definition)


def test_runtime_schema_rejects_stopping_observer_before_validation():
    definition = {
        "skill": "sample-skill",
        "prompts": [{"id": "runtime", "task": "Run runtime telemetry."}],
        "checks": [
            {
                "id": "runtime",
                "description": "Runtime check.",
                "compose_file": "docker-compose.yml",
                "stop_services_before_validation": ["observer"],
                "expect": {
                    "service_logs": [
                        {
                            "id": "preserved-sink",
                            "contains_all": ["request completed"],
                        }
                    ]
                },
            }
        ],
    }

    with pytest.raises(ValidationError):
        schema_validator("runtime.schema.json").validate(definition)


def test_role_schemas_reject_cross_role_fields():
    rubric_payload = {
        "skill": "sample-skill",
        "prompts": [{"id": "direct", "task": "Scan."}],
        "rubric": ["Grade quality."],
        "checks": [],
    }
    runtime_payload = {
        "skill": "sample-skill",
        "prompts": [{"id": "direct", "task": "Run."}],
        "checks": [{"id": "runtime", "description": "Run", "compose_file": "docker-compose.yml", "expect": {"endpoints": [{"id": "traces", "url": "/api/query/traces", "contains_any": ["svc"]}]}}],
        "rubric": ["Not allowed."],
    }
    runtime_with_kind = {
        "skill": "sample-skill",
        "prompts": [{"id": "direct", "task": "Run."}],
        "checks": [{"id": "runtime", "description": "Run", "kind": "old_runtime_kind", "runtime": {"compose_file": "docker-compose.yml"}}],
    }
    sanity_payload = {
        "skill": "sample-skill",
        "prompts": [{"id": "direct", "task": "Check."}],
        "rubric": ["Not allowed."],
    }

    with pytest.raises(ValidationError):
        schema_validator("rubric.schema.json").validate(rubric_payload)
    with pytest.raises(ValidationError):
        schema_validator("runtime.schema.json").validate(runtime_payload)
    with pytest.raises(ValidationError):
        schema_validator("runtime.schema.json").validate(runtime_with_kind)
    with pytest.raises(ValidationError):
        schema_validator("sanity.schema.json").validate(sanity_payload)


def test_prompt_eval_inputs_are_accepted_and_must_be_unique():
    payload = {
        "skill": "sample-skill",
        "prompts": [
            {
                "id": "direct",
                "task": "Run.",
                "eval_inputs": ["eval/inputs/otel-audit.json"],
            }
        ],
        "rubric": ["Grade quality."],
    }

    schema_validator("rubric.schema.json").validate(payload)
    payload["prompts"][0]["eval_inputs"] = [
        "eval/inputs/otel-audit.json",
        "eval/inputs/otel-audit.json",
    ]
    with pytest.raises(ValidationError):
        schema_validator("rubric.schema.json").validate(payload)


def test_prompt_eval_inputs_schema_rejects_unsafe_paths():
    payload = {
        "skill": "sample-skill",
        "prompts": [{"id": "direct", "task": "Run."}],
        "rubric": ["Grade quality."],
    }
    unsafe_inputs = [
        "/tmp/otel-audit.json",
        "../otel-audit.json",
        "eval/inputs/../otel-audit.json",
        "eval/inputs/./otel-audit.json",
        "eval/inputs/",
        "eval/inputs/otel-audit.json/",
        "eval/inputs//otel-audit.json",
        "otel-audit.json",
        "eval\\inputs\\otel-audit.json",
    ]

    for unsafe in unsafe_inputs:
        payload["prompts"][0]["eval_inputs"] = [unsafe]
        with pytest.raises(ValidationError):
            schema_validator("rubric.schema.json").validate(payload)


@pytest.mark.parametrize("contract", ["legacy", "strict-valid", "strict-fail", "strict-not-proven", "strict-na", "strict-invalid", "strict-middle-error", "strict-disabled"])
def test_collected_strict_grading_preserves_legacy_skip_and_failure_isolation(pytester: pytest.Pytester, contract: str):
    write_eval_repo(pytester)
    sample = pytester.path / "evals/sample/service/eval/qual/sample.json"
    if contract != "legacy":
        definition = json.loads(sample.read_text())
        rubric = definition.pop("rubric")
        definition["rubric_base"] = "../../../../common.json"
        sample.write_text(json.dumps(definition))
        common = {"rubric": rubric, "judge_inputs": [], "strict_rubric_output": True}
        if contract == "strict-middle-error":
            common["rubric"] = ["Grade correctness.", "Grade evidence.", "Grade scope."]
            common["rubric_dimensions"] = [
                {"id": f"group-{index}", "criteria": [f"rubric-{index}"]} for index in range(1, 4)
            ]
        (pytester.path / "evals/common.json").write_text(json.dumps(common))
    other = pytester.path / "evals/sample/other"
    legacy = other / "eval/qual/other.json"
    definition = json.loads(legacy.read_text())
    definition["skill"] = "sample-skill"
    legacy.write_text(json.dumps(definition))
    other.rename(other.with_name("zz-other"))
    calls = pytester.path / "judge-calls.txt"
    pytester.makeconftest(f'''
        import json
        import pytest
        from pathlib import Path
        from pytest_codex_evals.backends import AgentResult
        from pytest_codex_evals.plugin import BACKEND_ATTR
        from pytest_codex_evals.trace import parse_trace

        class ControlledBackend:
            name = "codex"

            def run_agent(self, *, exec_dir, **kwargs):
                skill = exec_dir / ".agents/skills/sample-skill/SKILL.md"
                trace, final, stderr = [exec_dir / name for name in ("trace.jsonl", "last_message.md", "stderr.txt")]
                trace.write_text(json.dumps({{"type": "item.completed", "item": {{
                    "id": "load", "type": "command_execution", "status": "completed", "exit_code": 0,
                    "command": "cat .agents/skills/sample-skill/SKILL.md", "aggregated_output": skill.read_text(),
                }}}}) + "\\n")
                final.write_text("Done.")
                stderr.write_text("")
                return AgentResult(0, trace, final, stderr)

            def run_judge(self, *, exec_dir, schema_path, output_dir=None, **kwargs):
                with Path({str(calls)!r}).open("a") as output:
                    output.write("judge\\n")
                trace, grade, stderr = [(output_dir or exec_dir) / name for name in ("rubric_trace.jsonl", "rubric_grade.json", "rubric_stderr.txt")]
                trace.write_text("")
                stderr.write_text("controlled judge diagnostic")
                if schema_path.name == "rubric_dimension_grade.schema.json":
                    criterion = "rubric-1"
                    if {contract!r} == "strict-middle-error":
                        criterion = "rubric-" + output_dir.name.rsplit("-", 1)[1]
                        if criterion == "rubric-2":
                            raise RuntimeError("middle judge unavailable")
                    payload = {{"checks": [{{
                        "id": "quality" if {contract!r} == "strict-invalid" else criterion,
                        "result": {({'strict-fail': 'fail', 'strict-not-proven': 'not_proven', 'strict-na': 'not_applicable'}.get(contract, 'pass'))!r},
                        "notes": "Controlled verdict.", "evidence": "last_message.md:1",
                    }}]}}
                else:
                    payload = {{"overall_pass": True, "score": 100, "checks": [{{
                        "id": "quality", "pass": True,
                        "notes": "Controlled verdict.", "evidence": "last_message.md:1",
                    }}]}}
                grade.write_text(json.dumps(payload))
                return AgentResult(0, trace, grade, stderr)

            def parse_trace(self, trace_path):
                return parse_trace(trace_path)

        @pytest.hookimpl(trylast=True)
        def pytest_configure(config):
            setattr(config, BACKEND_ATTR, ControlledBackend())
    ''')
    args = ["--codex-eval-kind", "rubric", "--skill", str(pytester.path / "skills/sample-skill"), "-q"]
    if contract == "strict-disabled":
        args.append("--no-rubric")
    result = pytester.runpytest(*args)
    if contract in {"strict-invalid", "strict-middle-error"}:
        result.assert_outcomes(failed=2, passed=1)
        assert "rubric grading failed" in result.stdout.str()
    else:
        result.assert_outcomes(passed=3)
    if contract == "strict-disabled":
        assert not calls.exists()
    else:
        assert calls.read_text().splitlines() == ["judge"] * (7 if contract == "strict-middle-error" else 3)
    summaries = list(pytester.path.glob(".workspace/codex-evals/sample-skill/*/cases/sample/*/*/with_skill/summary.json"))
    assert len(summaries) == 3
    for path in summaries:
        summary = json.loads(path.read_text())
        strict = summary["strict_rubric_output"]
        if strict and contract != "strict-disabled":
            assert summary["rubric_grade_path"] is None
            result_path = Path(summary["rubric_result_path"])
            grade = json.loads(result_path.read_text())
            dimension = grade["dimensions"][0]
            assert (result_path.parent / dimension["artifacts"]["output"]).exists()
            assert (result_path.parent / dimension["artifacts"]["prompt"]).exists()
            assert (result_path.parent / dimension["artifacts"]["stderr"]).read_text() == "controlled judge diagnostic"
            if contract == "strict-invalid":
                assert summary["errors"]
                assert grade["status"] == "incomplete"
                assert grade["checks"][0]["result"] == "ungraded"
            elif contract == "strict-middle-error":
                assert summary["errors"]
                assert grade["status"] == "incomplete"
                assert grade["overall_pass"] is None
                assert [row["result"] for row in grade["checks"]] == ["pass", "ungraded", "pass"]
                assert [row["status"] for row in grade["dimensions"]] == ["graded", "grader_error", "graded"]
                assert "middle judge unavailable" in grade["dimensions"][1]["error"]
            else:
                assert not summary["errors"]
                assert grade["status"] == "complete"
                expected = {"strict-valid": "pass", "strict-fail": "fail",
                            "strict-not-proven": "not_proven", "strict-na": "not_applicable"}[contract]
                assert grade["checks"][0]["result"] == expected
                assert grade["overall_pass"] == {"pass": True, "fail": False, "not_proven": False,
                                                  "not_applicable": None}[expected]
        elif contract == "strict-disabled":
            assert summary["rubric_grade_path"] is None
            assert summary["rubric_result_path"] is None
            assert not path.parent.with_name(path.parent.name + ".rubric").exists()
        else:
            assert summary["rubric_grade_path"] is not None
