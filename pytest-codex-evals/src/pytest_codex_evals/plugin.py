from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from .backends import (
    AgentBackend,
    atomic_text_write,
    create_backend,
    path_directory_identity,
    read_regular_text,
)
from .config import CodexEvalSettings, load_settings
from .eval_files import eval_file_layout, is_eval_file
from .definitions import (
    CaseResult,
    EvalCase,
    EvalDefinition,
    RubricEvalCase,
    RuntimeEvalCase,
    SanityEvalCase,
    ValidationResult,
)
from .eval_contracts import (
    case_from_definition,
    load_eval_definition,
)
from .report import ensure_safe_output_directory, write_session_results
from .runner import build_run_provenance, new_run_id, new_run_root, run_case


RUNS_ATTR = "_codex_eval_runs"
SETTINGS_ATTR = "_codex_eval_settings"
RUN_ID_ATTR = "_codex_eval_run_id"
BACKEND_ATTR = "_codex_eval_backend"
PROGRESS_ENABLED = False
PROGRESS_MODE = "validation"
PROGRESS_IS_WORKER = False


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("codex-evals")
    group.addoption("--codex-eval-config", default="codex-evals.toml", help="Path to codex eval TOML config")
    group.addoption(
        "--codex-eval-kind",
        default="",
        choices=("validation", "standard", "sanity", "rubric", "runtime"),
        help="Eval kind to run: validation, sanity, rubric, runtime, or standard",
    )
    group.addoption("--ab", action="store_true", default=False, help="Run loaded-skill and baseline sides")
    group.addoption("--skill", default="", help="Path to the skill directory to load and evaluate")
    group.addoption("--model", default="", help="Optional Codex model override")
    group.addoption("--no-rubric", action="store_true", default=False, help="Skip schema-constrained rubric grading")
    group.addoption("--codex-runtime", action="store_true", default=False, help="Run Docker-backed runtime checks")
    group.addoption("--codex-eval-progress", action="store_true", default=False, help="Print per-item eval progress")
    group.addoption("--agent-backend", default="", help="Agent backend: codex, cursor, or claude (default: from config or codex)")
    group.addoption("--agent-command", default="", help="Override the agent CLI binary path")
    group.addoption("--agent-timeout", type=int, default=0, help="Agent execution timeout in seconds (0 = use config default)")


def pytest_configure(config: pytest.Config) -> None:
    global PROGRESS_ENABLED, PROGRESS_MODE, PROGRESS_IS_WORKER
    config.addinivalue_line("markers", "codex_live: runs Codex subprocess evals")
    setattr(config, RUNS_ATTR, {})
    setattr(config, SETTINGS_ATTR, load_settings(config_path(config)))
    setattr(config, BACKEND_ATTR, _create_backend(config))
    PROGRESS_ENABLED = bool(config.getoption("--codex-eval-progress"))
    PROGRESS_MODE = progress_label(config)
    PROGRESS_IS_WORKER = is_xdist_worker(config)
    if is_xdist_worker(config):
        run_id = config.workerinput.get("codex_eval_run_id") or new_run_id()
    else:
        run_id = new_run_id()
    setattr(config, RUN_ID_ATTR, run_id)


def pytest_configure_node(node) -> None:
    node.workerinput["codex_eval_run_id"] = getattr(node.config, RUN_ID_ATTR, new_run_id())


def pytest_collect_file(file_path: Path, parent: pytest.Collector):
    if is_eval_file(file_path):
        return CodexEvalFile.from_parent(parent, path=file_path)
    return None


def pytest_runtest_logstart(nodeid: str, location) -> None:
    if PROGRESS_ENABLED and not PROGRESS_IS_WORKER:
        print(f"[codex-eval] START {PROGRESS_MODE} {nodeid}", flush=True)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if PROGRESS_ENABLED and not PROGRESS_IS_WORKER and report.when == "call":
        print(f"[codex-eval] {report.outcome.upper():5} {PROGRESS_MODE} {report.nodeid} ({report.duration:.1f}s)", flush=True)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED and eval_kind(session.config) != "validation":
        session.exitstatus = pytest.ExitCode.OK
        return

    runs: dict[tuple[str, str, str, str], dict[str, Any]] = getattr(session.config, RUNS_ATTR, {})
    if is_xdist_worker(session.config):
        write_worker_results(session.config, runs)
        return

    worker_runs = collect_worker_results(session.config)
    if worker_runs:
        write_grouped_results(worker_runs)
        return

    write_grouped_results(list(runs.values()))


def write_grouped_results(runs: list[dict[str, Any]]) -> None:
    write_session_results(runs)


def is_xdist_worker(config: pytest.Config) -> bool:
    return hasattr(config, "workerinput")


def worker_results_root(repo_root: Path, config: pytest.Config) -> Path:
    return repo_root / ".workspace" / "codex-evals" / "_worker-results" / getattr(config, RUN_ID_ATTR)


def write_worker_results(config: pytest.Config, runs: dict[tuple[str, str, str, str], dict[str, Any]]) -> None:
    worker_id = config.workerinput.get("workerid", "worker")
    for index, run in enumerate(runs.values()):
        results = run["results"]
        if not results:
            continue
        root = worker_results_root(run["repo_root"], config)
        ensure_safe_output_directory(root, run["repo_root"])
        root_identity = path_directory_identity(root)
        path = root / (
            f"{safe_name(worker_id)}-{index}-{safe_name(run['skill'])}-"
            f"{safe_name(run['eval_kind'])}-{safe_name(run['mode'])}.json"
        )
        payload = {
            "mode": run["mode"],
            "eval_kind": run["eval_kind"],
            "repo_root": str(run["repo_root"]),
            "run_root": str(run["run_root"]),
            "skill": run["skill"],
            "metadata": run.get("metadata", {}),
            "results": [result.model_dump(mode="json") for result in results],
        }
        atomic_text_write(
            path,
            json.dumps(payload, indent=2),
            boundary=root,
            expected_boundary_identity=root_identity,
        )


def collect_worker_results(config: pytest.Config) -> list[dict[str, Any]]:
    try:
        repo_root = infer_repo_root(config.rootpath)
    except AssertionError:
        return []
    root = worker_results_root(repo_root, config)
    if not root.is_dir():
        return []
    ensure_safe_output_directory(root, repo_root)

    repo_root = repo_root.resolve()
    run_id = getattr(config, RUN_ID_ATTR)
    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    seen_results: set[tuple[tuple[str, str, str, str, str], str]] = set()
    for path in sorted(root.glob("*.json")):
        if path.is_symlink():
            raise ValueError(f"worker result must not be a symlink: {path}")
        payload = json.loads(read_regular_text(path))
        if not isinstance(payload, dict):
            raise ValueError(f"worker result must be an object: {path}")
        mode = payload.get("mode")
        skill = payload.get("skill")
        eval_kind_value = payload.get("eval_kind", "validation" if mode == "validation" else "standard")
        for label, value in (
            ("mode", mode),
            ("skill", skill),
            ("eval kind", eval_kind_value),
        ):
            if (
                not isinstance(value, str)
                or not value
                or safe_name(value) != value
            ):
                raise ValueError(f"worker result has unsafe {label}: {value!r}")
        if mode not in {"validation", "with_skill", "with_baseline", "ab"}:
            raise ValueError(f"worker result has unsupported mode: {mode}")
        declared_repo = Path(str(payload.get("repo_root", ""))).resolve()
        if declared_repo != repo_root:
            raise ValueError(
                f"worker result repo_root does not match controller: {declared_repo}"
            )
        expected_run_root = (
            repo_root / ".workspace" / "codex-evals" / skill / run_id
        ).resolve()
        declared_run_root = Path(str(payload.get("run_root", ""))).resolve()
        if declared_run_root != expected_run_root:
            raise ValueError(
                "worker result run_root does not match the current controller run: "
                f"{declared_run_root}"
            )
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("worker result metadata must be an object")
        expected_metadata = {
            "mode": mode,
            "eval_kind": eval_kind_value,
            "skill": skill,
            "run_id": run_id,
        }
        for field, expected in expected_metadata.items():
            if metadata.get(field) != expected:
                raise ValueError(
                    f"worker result metadata {field} does not match payload"
                )
        key = (
            str(repo_root),
            str(expected_run_root),
            skill,
            eval_kind_value,
            mode,
        )
        if key not in grouped:
            grouped[key] = {
                "mode": mode,
                "eval_kind": eval_kind_value,
                "repo_root": repo_root,
                "run_root": expected_run_root,
                "skill": skill,
                "metadata": metadata,
                "results": [],
            }
        result_model = ValidationResult if mode == "validation" else CaseResult
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise ValueError("worker result results must be a list")
        for raw_result in raw_results:
            result = result_model.model_validate(raw_result)
            if result.skill != skill:
                raise ValueError(
                    f"worker result skill differs from payload: {result.id}"
                )
            identity = (key, result.id)
            if identity in seen_results:
                raise ValueError(
                    f"duplicate worker result for {mode}: {result.id}"
                )
            seen_results.add(identity)
            grouped[key]["results"].append(result)

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
def codex_rubric(pytestconfig: pytest.Config) -> bool:
    return rubric_enabled(pytestconfig)


class CodexEvalFile(pytest.File):
    def collect(self):
        definition = load_eval_definition(self.path)
        selected_skill = selected_skill_dir(self.config)
        if selected_skill and definition.skill != selected_skill.name:
            return
        if not definition_matches_eval_kind(definition, eval_kind(self.config), self.path):
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
        kind = eval_kind(self.config)
        validate_case(self.case, repo_root, skill_dir)

        validation_run = session_run(self.config, repo_root, self.case.skill, "validation", "validation")
        validation_run["results"].append(
            validation_result(
                self.case,
                repo_root,
                skill_dir,
                config_path=config_path(self.config),
                run_configuration=validation_run["metadata"],
            )
        )

        if mode == "validation":
            return

        sides = sides_for_mode(mode)
        run = session_run(self.config, repo_root, self.case.skill, mode, kind)
        result = run_case(
            repo_root=repo_root,
            run_root=run["run_root"],
            case=self.case,
            skill_dir=skill_dir,
            model=agent_model(self.config),
            judge_model=judge_model(self.config),
            rubric=rubric_enabled(self.config),
            runtime=runtime_enabled(self.config),
            eval_kind=kind,
            sides=sides,
            backend=get_backend(self.config),
            agent_timeout=agent_timeout(self.config),
            judge_timeout=judge_timeout(self.config),
            config_path=config_path(self.config),
            run_configuration=run["metadata"],
        )
        run["results"].append(result)
        validate_live_result(result)

    def reportinfo(self):
        return self.path, 0, self.name


def definition_matches_eval_kind(definition: EvalDefinition, kind: str, path: Path) -> bool:
    layout = eval_file_layout(path)
    role = layout.role if layout else definition.kind
    if kind in {"validation", "standard"}:
        return True
    return role == kind


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
    kind = eval_kind(config)
    if kind == "validation":
        return "validation"
    if config.getoption("--codex-eval-kind") or config.getoption("--ab"):
        return "ab" if bool(config.getoption("--ab")) else "with_skill"
    return settings(config).run_mode


def eval_kind(config: pytest.Config) -> str:
    value = config.getoption("--codex-eval-kind") or ""
    if value:
        return normalize_eval_kind(str(value))
    configured = settings(config).eval_kind
    if configured == "validation" and bool(config.getoption("--ab")):
        return "standard"
    return normalize_eval_kind(configured)


def normalize_eval_kind(value: str) -> str:
    return value


def sides_for_mode(mode: str) -> tuple[str, ...]:
    if mode == "with_skill":
        return ("with_skill",)
    if mode == "with_baseline":
        return ("baseline",)
    if mode == "ab":
        return ("with_skill", "baseline")
    raise ValueError(f"mode {mode} does not run Codex")


def rubric_enabled(config: pytest.Config) -> bool:
    kind = eval_kind(config)
    if kind == "rubric":
        return not bool(config.getoption("--no-rubric"))
    if kind in {"validation", "sanity", "runtime"}:
        return False
    return settings(config).rubric_enabled and not bool(config.getoption("--no-rubric"))


def runtime_enabled(config: pytest.Config) -> bool:
    return eval_kind(config) == "runtime" or settings(config).runtime_enabled or bool(config.getoption("--codex-runtime"))


def agent_model(config: pytest.Config) -> str | None:
    return config.getoption("--model") or settings(config).agent_model


def judge_model(config: pytest.Config) -> str | None:
    return settings(config).judge_model


def agent_timeout(config: pytest.Config) -> int:
    return int(config.getoption("--agent-timeout") or settings(config).agent_timeout)


def judge_timeout(config: pytest.Config) -> int:
    return settings(config).judge_timeout


def get_backend(config: pytest.Config) -> AgentBackend:
    return getattr(config, BACKEND_ATTR)


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


def session_run(config: pytest.Config, repo_root: Path, skill: str, mode: str, kind: str) -> dict[str, Any]:
    runs: dict[tuple[str, str, str, str], dict[str, Any]] = getattr(config, RUNS_ATTR)
    key = (str(repo_root), skill, kind, mode)
    if key not in runs:
        runs[key] = {
            "mode": mode,
            "eval_kind": kind,
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
    backend = get_backend(config)
    return {
        "mode": mode,
        "eval_kind": eval_kind(config) if mode != "validation" else "validation",
        "ab_enabled": mode == "ab",
        "skill": skill,
        "run_id": getattr(config, RUN_ID_ATTR, ""),
        "repo_root": str(repo_root),
        "config_path": display_path(path, repo_root) if path else "",
        "agent_model": agent_model(config) or "",
        "judge_model": judge_model(config) or "",
        "agent_backend": backend.name,
        "agent_timeout": str(agent_timeout(config)),
        "judge_timeout": str(judge_timeout(config)),
        "rubric_enabled": rubric_enabled(config),
        "runtime_enabled": runtime_enabled(config),
        "workers": str(workers),
    }


def progress_label(config: pytest.Config) -> str:
    kind = eval_kind(config)
    mode = run_mode(config)
    return kind if mode == "validation" else f"{kind}:{mode}"


def display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(path)


def validation_result(
    case: EvalCase,
    repo_root: Path,
    skill_dir: Path | None,
    *,
    config_path: Path | None,
    run_configuration: dict[str, object],
) -> ValidationResult:
    resolved_skill_dir = skill_dir or repo_root / "skills" / case.skill
    sanity_count = len(case.checks) if isinstance(case, SanityEvalCase) else 0
    rubric_count = len(case.rubric) if isinstance(case, RubricEvalCase) else 0
    runtime_count = len(case.checks) if isinstance(case, RuntimeEvalCase) else 0
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
        eval_kind=case.kind,
        sanity_check_count=sanity_count,
        rubric_check_count=rubric_count,
        runtime_check_count=runtime_count,
        provenance=build_run_provenance(
            repo_root,
            case,
            resolved_skill_dir,
            config_path=config_path,
            run_configuration=run_configuration,
        ),
    )


def _create_backend(config: pytest.Config) -> AgentBackend:
    s = settings(config)
    cli_backend = config.getoption("--agent-backend") or ""
    cli_command = config.getoption("--agent-command") or ""
    backend_name = cli_backend or s.agent_backend
    command = cli_command or s.agent_command or None
    extra_args = list(s.agent_extra_args) if s.agent_extra_args else None
    return create_backend(name=backend_name, command=command, extra_args=extra_args)


def validate_live_result(result: CaseResult) -> None:
    failures: list[str] = []
    if result.with_skill is not None and result.with_skill.exit_code != 0:
        failures.append(f"with_skill exited {result.with_skill.exit_code}")
    if result.baseline is not None and result.baseline.exit_code != 0:
        failures.append(f"baseline exited {result.baseline.exit_code}")
    if result.with_skill is not None and result.with_skill.grade.total == 0:
        failures.append("with_skill produced no checks")
    if result.baseline is not None and result.baseline.grade.total == 0:
        failures.append("baseline produced no checks")
    if result.with_skill is None and result.baseline is None:
        failures.append("no Codex side result was produced")
    if failures:
        raise AssertionError(f"{result.id}: " + "; ".join(failures))
