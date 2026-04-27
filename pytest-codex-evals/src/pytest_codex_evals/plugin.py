from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from .config import CodexEvalSettings, load_settings
from .models import CaseResult, EvalCase, EvalDefinition, PromptVariant
from .report import write_reports
from .runner import new_run_root, run_case
from .schema_resources import load_schema


RUNS_ATTR = "_codex_eval_runs"
SETTINGS_ATTR = "_codex_eval_settings"


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("codex-evals")
    group.addoption("--codex-eval-config", default="codex-evals.toml", help="Path to codex eval TOML config")
    group.addoption("--skill", default="", help="Path to the skill directory to load and evaluate")
    group.addoption("--model", default="", help="Optional Codex model override")
    group.addoption("--no-qualitative", action="store_true", default=False, help="Skip schema-constrained qualitative grading")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "codex_live: runs Codex subprocess evals")
    setattr(config, RUNS_ATTR, {})
    setattr(config, SETTINGS_ATTR, load_settings(config_path(config)))


def pytest_collect_file(file_path: Path, parent: pytest.Collector):
    if file_path.name.endswith("_eval.json"):
        return CodexEvalFile.from_parent(parent, path=file_path)
    return None


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    runs: dict[tuple[str, str], dict[str, Any]] = getattr(session.config, RUNS_ATTR, {})
    for run in runs.values():
        results = run["results"]
        if results:
            write_reports(run["repo_root"], run["run_root"], run["skill"], results)


@pytest.fixture
def codex_run_requested(pytestconfig: pytest.Config) -> bool:
    return live_ab_enabled(pytestconfig)


@pytest.fixture
def codex_skill(pytestconfig: pytest.Config) -> Path | None:
    return selected_skill_dir(pytestconfig)


@pytest.fixture
def codex_model(pytestconfig: pytest.Config) -> str | None:
    return agent_model(pytestconfig)


@pytest.fixture
def codex_qualitative(pytestconfig: pytest.Config) -> bool:
    return qualitative_enabled(pytestconfig)


class CodexEvalFile(pytest.File):
    def collect(self):
        definition = load_eval_definition(self.path)
        selected_skill = selected_skill_dir(self.config)
        if selected_skill and definition.skill != selected_skill.name:
            return
        for prompt in definition.prompts:
            case = case_from_definition(definition, prompt, self.path)
            name = f"{case.skill}::{case.case_key}::{case.prompt_id}"
            yield CodexEvalItem.from_parent(self, name=name, case=case)


class CodexEvalItem(pytest.Item):
    def __init__(self, *, case: EvalCase, **kwargs):
        super().__init__(**kwargs)
        self.case = case
        self.add_marker("codex_live")

    def runtest(self) -> None:
        repo_root = infer_repo_root(self.case.definition_path or self.path)
        skill_dir = selected_skill_dir(self.config)
        validate_case(self.case, repo_root, skill_dir)

        if not live_ab_enabled(self.config):
            return

        run = session_run(self.config, repo_root, self.case.skill)
        result = run_case(
            repo_root=repo_root,
            run_root=run["run_root"],
            case=self.case,
            skill_dir=skill_dir,
            model=agent_model(self.config),
            judge_model=judge_model(self.config),
            qualitative=qualitative_enabled(self.config),
        )
        run["results"].append(result)
        validate_live_result(result)

    def reportinfo(self):
        return self.path, 0, self.name


def load_eval_definition(path: Path) -> EvalDefinition:
    data = json.loads(path.read_text(encoding="utf-8"))
    data = with_path_defaults(path, data)
    Draft202012Validator(load_schema("eval.schema.json")).validate(data)
    definition = EvalDefinition.model_validate(data)
    definition.definition_path = path
    definition.fixture_dir = path.parent
    return definition


def case_from_definition(definition: EvalDefinition, prompt: PromptVariant, path: Path) -> EvalCase:
    return EvalCase(
        id=f"{definition.id}/{prompt.id}",
        base_id=definition.id,
        prompt_id=prompt.id,
        skill=definition.skill,
        language=definition.language,
        service=definition.service,
        task=prompt.task,
        deterministic_checks=definition.deterministic_checks,
        qualitative_checks=definition.qualitative_checks,
        definition_path=path,
        fixture_dir=path.parent,
    )


def with_path_defaults(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    kind = path.name.removesuffix("_eval.json")
    service = path.parent.name
    language = path.parent.parent.name
    normalized.setdefault("language", language)
    normalized.setdefault("service", service)
    normalized.setdefault("id", f"{language}/{service}/{kind}")
    return normalized


def infer_repo_root(start: Path) -> Path:
    current = start if start.is_dir() else start.parent
    for candidate in (current, *current.parents):
        if (candidate / "skills").is_dir():
            return candidate
    raise AssertionError(f"could not find repo root with skills/ above {start}")


def selected_skill_dir(config: pytest.Config) -> Path | None:
    value = config.getoption("--skill") or ""
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not (path / "SKILL.md").is_file():
        raise pytest.UsageError(f"--skill must point to a skill directory containing SKILL.md: {path}")
    return path


def live_ab_enabled(config: pytest.Config) -> bool:
    return settings(config).live_ab


def qualitative_enabled(config: pytest.Config) -> bool:
    return settings(config).qualitative_enabled and not bool(config.getoption("--no-qualitative"))


def agent_model(config: pytest.Config) -> str | None:
    return config.getoption("--model") or settings(config).agent_model


def judge_model(config: pytest.Config) -> str | None:
    return settings(config).judge_model


def settings(config: pytest.Config) -> CodexEvalSettings:
    return getattr(config, SETTINGS_ATTR)


def config_path(config: pytest.Config) -> Path | None:
    value = config.getoption("--codex-eval-config") or ""
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = config.rootpath / path
    return path


def validate_case(case: EvalCase, repo_root: Path, skill_dir: Path | None = None) -> None:
    if case.fixture_dir is None or not case.fixture_dir.is_dir():
        raise AssertionError(f"{case.id}: fixture directory is missing")
    fixture_entries = [
        path
        for path in case.fixture_dir.iterdir()
        if not path.name.endswith("_eval.json") and path.name not in {".observe", ".venv", "__pycache__"}
    ]
    if not fixture_entries:
        raise AssertionError(f"{case.id}: fixture directory has no service files")

    skill_file = (skill_dir or repo_root / "skills" / case.skill) / "SKILL.md"
    if not skill_file.is_file():
        raise AssertionError(f"{case.id}: missing skill source {skill_file}")


def session_run(config: pytest.Config, repo_root: Path, skill: str) -> dict[str, Any]:
    runs: dict[tuple[str, str], dict[str, Any]] = getattr(config, RUNS_ATTR)
    key = (str(repo_root), skill)
    if key not in runs:
        runs[key] = {
            "repo_root": repo_root,
            "run_root": new_run_root(repo_root, skill),
            "skill": skill,
            "results": [],
        }
    return runs[key]


def validate_live_result(result: CaseResult) -> None:
    failures: list[str] = []
    if result.with_skill.exit_code != 0:
        failures.append(f"with_skill exited {result.with_skill.exit_code}")
    if result.baseline.exit_code != 0:
        failures.append(f"baseline exited {result.baseline.exit_code}")
    if result.with_skill.deterministic_grade.total == 0:
        failures.append("with_skill produced no deterministic checks")
    if result.baseline.deterministic_grade.total == 0:
        failures.append("baseline produced no deterministic checks")
    if failures:
        raise AssertionError(f"{result.id}: " + "; ".join(failures))
