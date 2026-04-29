from __future__ import annotations

import json

import pytest
from jsonschema.exceptions import ValidationError

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

    result = pytester.runpytest("--skill", str(skill_dir))

    result.assert_outcomes(passed=2)
    raw_runs = list(pytester.path.glob(".workspace/codex-evals/sample-skill/*/runs/validation.json"))
    assert len(raw_runs) == 1
    payload = json.loads(raw_runs[0].read_text(encoding="utf-8"))
    assert payload["metadata"]["mode"] == "validation"
    assert payload["metadata"]["eval_kind"] == "validation"
    assert len(payload["results"]) == 2
    assert not (pytester.path / "eval-reports" / "sample-skill" / "validation" / "report.md").exists()


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
    assert len(payload["results"]) == 2


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
                        "expect": {"traces": {"contains_any": ["sample-service"]}},
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
        "checks": [{"id": "runtime", "description": "Run", "compose_file": "docker-compose.yml", "expect": {"traces": {"contains_any": ["svc"]}}}],
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
