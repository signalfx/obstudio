from __future__ import annotations

import json

import pytest


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
    (service_dir / "sample_eval.json").write_text(
        json.dumps(
            {
                "skill": "sample-skill",
                "prompts": [
                    {"id": "direct", "task": "Scan the service."},
                    {"id": "runtime-preserving", "task": "Keep the runtime shape."},
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    other_dir = pytester.path / "evals" / "sample" / "other"
    other_dir.mkdir(parents=True)
    (other_dir / "app.py").write_text("print('other')\n", encoding="utf-8")
    (other_dir / "other_eval.json").write_text(
        json.dumps(
            {
                "skill": "other-skill",
                "prompts": [{"id": "direct", "task": "Scan the other service."}],
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
            "evals/sample/service/sample_eval.json::sample-skill::sample/service::direct",
            "evals/sample/service/sample_eval.json::sample-skill::sample/service::runtime-preserving",
            "2 tests collected*",
        ]
    )


def test_eval_json_files_validate_without_running_codex(pytester: pytest.Pytester):
    write_eval_repo(pytester)
    skill_dir = pytester.path / "skills" / "sample-skill"

    result = pytester.runpytest("--skill", str(skill_dir))

    result.assert_outcomes(passed=2)
    latest_dir = pytester.path / "eval-reports" / "sample-skill"
    assert (latest_dir / "REPORT.md").is_file()
    benchmark = json.loads((latest_dir / "benchmark.json").read_text(encoding="utf-8"))
    assert benchmark["metadata"]["mode"] == "validation"
    assert benchmark["validation"]["summary"]["case_count"] == 2
    assert not (latest_dir / "AB_REPORT.md").exists()
    assert not (latest_dir / "VALIDATION_REPORT.md").exists()


def test_prompt_selection_uses_pytest_k(pytester: pytest.Pytester):
    write_eval_repo(pytester)
    skill_dir = pytester.path / "skills" / "sample-skill"

    result = pytester.runpytest("--collect-only", "-q", "--skill", str(skill_dir), "-k", "runtime-preserving")

    result.assert_outcomes()
    result.stdout.fnmatch_lines(
        [
            "evals/sample/service/sample_eval.json::sample-skill::sample/service::runtime-preserving",
            "1/2 tests collected*",
        ]
    )


def test_eval_json_files_do_not_require_fixture_files(pytester: pytest.Pytester):
    write_eval_repo(pytester)
    skill_dir = pytester.path / "skills" / "sample-skill"
    eval_dir = pytester.path / "evals" / "sample" / "no-fixture"
    eval_dir.mkdir(parents=True)
    (eval_dir / "sample_eval.json").write_text(
        json.dumps(
            {
                "skill": "sample-skill",
                "prompts": [{"id": "direct", "task": "Classify the provided input."}],
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
    latest_dir = pytester.path / "eval-reports" / "sample-skill"
    benchmark = json.loads((latest_dir / "benchmark.json").read_text(encoding="utf-8"))
    assert benchmark["metadata"]["mode"] == "validation"
    assert benchmark["validation"]["summary"]["case_count"] == 2
