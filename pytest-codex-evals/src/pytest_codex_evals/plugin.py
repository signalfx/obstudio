from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from .config import CodexEvalSettings, load_settings
from .models import CaseResult, EvalCase, EvalDefinition, PromptVariant, ValidationResult
from .report import write_ab_reports, write_side_reports, write_validation_reports
from .runner import new_run_id, new_run_root, run_case
from .schema_resources import load_schema


RUNS_ATTR = "_codex_eval_runs"
SETTINGS_ATTR = "_codex_eval_settings"
RUN_ID_ATTR = "_codex_eval_run_id"
PROGRESS_ENABLED = False
PROGRESS_MODE = "validation"
PROGRESS_IS_WORKER = False


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("codex-evals")
    group.addoption("--codex-eval-config", default="codex-evals.toml", help="Path to codex eval TOML config")
    group.addoption("--skill", default="", help="Path to the skill directory to load and evaluate")
    group.addoption("--model", default="", help="Optional Codex model override")
    group.addoption("--no-qualitative", action="store_true", default=False, help="Skip schema-constrained qualitative grading")
    group.addoption("--codex-eval-progress", action="store_true", default=False, help="Print per-item eval progress")


def pytest_configure(config: pytest.Config) -> None:
    global PROGRESS_ENABLED, PROGRESS_MODE, PROGRESS_IS_WORKER
    config.addinivalue_line("markers", "codex_live: runs Codex subprocess evals")
    setattr(config, RUNS_ATTR, {})
    setattr(config, SETTINGS_ATTR, load_settings(config_path(config)))
    PROGRESS_ENABLED = bool(config.getoption("--codex-eval-progress"))
    PROGRESS_MODE = settings(config).run_mode
    PROGRESS_IS_WORKER = is_xdist_worker(config)
    if is_xdist_worker(config):
        run_id = config.workerinput.get("codex_eval_run_id") or new_run_id()
    else:
        run_id = new_run_id()
    setattr(config, RUN_ID_ATTR, run_id)


def pytest_configure_node(node) -> None:
    node.workerinput["codex_eval_run_id"] = getattr(node.config, RUN_ID_ATTR, new_run_id())


def pytest_collect_file(file_path: Path, parent: pytest.Collector):
    if file_path.name.endswith("_eval.json"):
        return CodexEvalFile.from_parent(parent, path=file_path)
    return None


def pytest_runtest_logstart(nodeid: str, location) -> None:
    if PROGRESS_ENABLED and not PROGRESS_IS_WORKER:
        print(f"[codex-eval] START {PROGRESS_MODE} {nodeid}", flush=True)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if PROGRESS_ENABLED and not PROGRESS_IS_WORKER and report.when == "call":
        print(f"[codex-eval] {report.outcome.upper():5} {PROGRESS_MODE} {report.nodeid} ({report.duration:.1f}s)", flush=True)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    runs: dict[tuple[str, str, str], dict[str, Any]] = getattr(session.config, RUNS_ATTR, {})
    if is_xdist_worker(session.config):
        write_worker_results(session.config, runs)
        return

    worker_runs = collect_worker_results(session.config)
    if worker_runs:
        write_grouped_reports(worker_runs)
        return

    write_grouped_reports(list(runs.values()))


def write_grouped_reports(runs: list[dict[str, Any]]) -> None:
    for run in runs:
        results = run["results"]
        if not results:
            continue
        metadata = run.get("metadata")
        if run["mode"] == "ab":
            write_ab_reports(run["repo_root"], run["run_root"], run["skill"], results, metadata)
        elif run["mode"] in {"with_skill", "with_baseline"}:
            write_side_reports(run["repo_root"], run["run_root"], run["skill"], run["mode"], results, metadata)
        elif run["mode"] == "validation":
            write_validation_reports(run["repo_root"], run["run_root"], run["skill"], results, metadata)


def is_xdist_worker(config: pytest.Config) -> bool:
    return hasattr(config, "workerinput")


def worker_results_root(repo_root: Path, config: pytest.Config) -> Path:
    return repo_root / ".workspace" / "codex-evals" / "_worker-results" / getattr(config, RUN_ID_ATTR)


def write_worker_results(config: pytest.Config, runs: dict[tuple[str, str, str], dict[str, Any]]) -> None:
    worker_id = config.workerinput.get("workerid", "worker")
    for index, run in enumerate(runs.values()):
        results = run["results"]
        if not results:
            continue
        root = worker_results_root(run["repo_root"], config)
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{worker_id}-{index}-{safe_name(run['skill'])}-{run['mode']}.json"
        payload = {
            "mode": run["mode"],
            "repo_root": str(run["repo_root"]),
            "run_root": str(run["run_root"]),
            "skill": run["skill"],
            "metadata": run.get("metadata", {}),
            "results": [result.model_dump(mode="json") for result in results],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def collect_worker_results(config: pytest.Config) -> list[dict[str, Any]]:
    try:
        repo_root = infer_repo_root(config.rootpath)
    except AssertionError:
        return []
    root = worker_results_root(repo_root, config)
    if not root.is_dir():
        return []

    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for path in sorted(root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        mode = payload["mode"]
        key = (payload["repo_root"], payload["run_root"], payload["skill"], mode)
        if key not in grouped:
            grouped[key] = {
                "mode": mode,
                "repo_root": Path(payload["repo_root"]),
                "run_root": Path(payload["run_root"]),
                "skill": payload["skill"],
                "metadata": payload.get("metadata", {}),
                "results": [],
            }
        result_model = ValidationResult if mode == "validation" else CaseResult
        grouped[key]["results"].extend(result_model.model_validate(result) for result in payload["results"])

    for run in grouped.values():
        run["results"].sort(key=lambda result: (result.language, result.service, result.prompt_id, result.id))
    return list(grouped.values())


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)


@pytest.fixture
def codex_run_requested(pytestconfig: pytest.Config) -> bool:
    return run_mode(pytestconfig) != "validation"


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
        mode = run_mode(self.config)
        validate_case(self.case, repo_root, skill_dir)

        validation_run = session_run(self.config, repo_root, self.case.skill, "validation")
        validation_run["results"].append(validation_result(self.case, repo_root, skill_dir))

        if mode == "validation":
            return

        sides = sides_for_mode(mode)
        run = session_run(self.config, repo_root, self.case.skill, mode)
        result = run_case(
            repo_root=repo_root,
            run_root=run["run_root"],
            case=self.case,
            skill_dir=skill_dir,
            model=agent_model(self.config),
            judge_model=judge_model(self.config),
            qualitative=qualitative_enabled(self.config),
            sides=sides,
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
    return run_mode(config) == "ab"


def run_mode(config: pytest.Config) -> str:
    return settings(config).run_mode


def sides_for_mode(mode: str) -> tuple[str, ...]:
    if mode == "with_skill":
        return ("with_skill",)
    if mode == "with_baseline":
        return ("baseline",)
    if mode == "ab":
        return ("with_skill", "baseline")
    raise ValueError(f"mode {mode} does not run Codex")


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
        raise AssertionError(f"{case.id}: eval directory is missing")

    skill_file = (skill_dir or repo_root / "skills" / case.skill) / "SKILL.md"
    if not skill_file.is_file():
        raise AssertionError(f"{case.id}: missing skill source {skill_file}")


def session_run(config: pytest.Config, repo_root: Path, skill: str, mode: str) -> dict[str, Any]:
    runs: dict[tuple[str, str, str], dict[str, Any]] = getattr(config, RUNS_ATTR)
    key = (str(repo_root), skill, mode)
    if key not in runs:
        runs[key] = {
            "mode": mode,
            "repo_root": repo_root,
            "run_root": new_run_root(repo_root, skill, getattr(config, RUN_ID_ATTR, None)),
            "skill": skill,
            "metadata": run_metadata(config, repo_root, skill, mode),
            "results": [],
        }
    return runs[key]


def run_metadata(config: pytest.Config, repo_root: Path, skill: str, mode: str) -> dict[str, Any]:
    path = config_path(config)
    workers = getattr(config.option, "numprocesses", None) or 1
    return {
        "mode": mode,
        "skill": skill,
        "run_id": getattr(config, RUN_ID_ATTR, ""),
        "repo_root": str(repo_root),
        "config_path": str(path) if path else "",
        "agent_model": agent_model(config) or "",
        "judge_model": judge_model(config) or "",
        "qualitative_enabled": qualitative_enabled(config),
        "workers": str(workers),
    }


def validation_result(case: EvalCase, repo_root: Path, skill_dir: Path | None) -> ValidationResult:
    resolved_skill_dir = skill_dir or repo_root / "skills" / case.skill
    return ValidationResult(
        id=case.id,
        base_id=case.base_id,
        prompt_id=case.prompt_id,
        skill=case.skill,
        language=case.language,
        service=case.service,
        definition_path=str((case.definition_path or Path()).resolve()),
        fixture_dir=str((case.fixture_dir or Path()).resolve()),
        skill_path=str(resolved_skill_dir.resolve()),
        deterministic_check_count=len(case.deterministic_checks),
        qualitative_check_count=len(case.qualitative_checks),
    )


def validate_live_result(result: CaseResult) -> None:
    failures: list[str] = []
    if result.with_skill is not None and result.with_skill.exit_code != 0:
        failures.append(f"with_skill exited {result.with_skill.exit_code}")
    if result.baseline is not None and result.baseline.exit_code != 0:
        failures.append(f"baseline exited {result.baseline.exit_code}")
    if result.with_skill is not None and result.with_skill.deterministic_grade.total == 0:
        failures.append("with_skill produced no deterministic checks")
    if result.baseline is not None and result.baseline.deterministic_grade.total == 0:
        failures.append("baseline produced no deterministic checks")
    if result.with_skill is None and result.baseline is None:
        failures.append("no Codex side result was produced")
    if failures:
        raise AssertionError(f"{result.id}: " + "; ".join(failures))
