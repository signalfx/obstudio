from __future__ import annotations

import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .ab import side_prompt
from .backends import AgentBackend, CodexBackend
from .definitions import CaseResult, EvalCase, RubricEvalCase, SideResult, TokenUsage, resolve_skill_source
from .eval_files import (
    fixture_eval_input_sources,
    fixture_workspace_ignore,
    shared_skill_reference_source_files,
    skill_workspace_ignore,
    staged_fixture_source_files,
    staged_skill_source_files,
)
from .graders import grade_side
from .graders.rubric import run_rubric_grade
from .trace import TraceUsage, UsageProvider


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def new_run_root(repo_root: Path, skill: str, run_id: str | None = None) -> Path:
    run_id = run_id or new_run_id()
    return repo_root / ".workspace" / "codex-evals" / skill / run_id


def run_case(
    *,
    repo_root: Path,
    run_root: Path,
    case: EvalCase,
    skill_dir: Path | None = None,
    model: str | None = None,
    judge_model: str | None = None,
    rubric: bool = True,
    runtime: bool = False,
    eval_kind: str = "standard",
    sides: tuple[str, ...] = ("with_skill", "baseline"),
    backend: AgentBackend | None = None,
    agent_timeout: int = 1200,
    judge_timeout: int = 900,
) -> CaseResult:
    if backend is None:
        backend = CodexBackend()
    case_root = run_root / "cases" / case.language / case.service / case.prompt_id
    exec_case_root = Path(tempfile.mkdtemp(prefix=f"codex-eval-{case.skill}-{case.language}-{case.service}-{case.prompt_id}-"))
    try:
        with_skill = None
        baseline = None
        if "with_skill" in sides:
            with_skill = run_side(
                repo_root=repo_root,
                case=case,
                side="with_skill",
                exec_dir=exec_case_root / "with_skill",
                artifact_dir=case_root / "with_skill",
                prompt=side_prompt(case, "with_skill"),
                skill_dir=skill_dir,
                model=model,
                judge_model=judge_model,
                rubric=rubric,
                runtime=runtime,
                eval_kind=eval_kind,
                backend=backend,
                agent_timeout=agent_timeout,
                judge_timeout=judge_timeout,
            )
        if "baseline" in sides:
            baseline = run_side(
                repo_root=repo_root,
                case=case,
                side="baseline",
                exec_dir=exec_case_root / "baseline",
                artifact_dir=case_root / "baseline",
                prompt=side_prompt(case, "baseline"),
                skill_dir=skill_dir,
                model=model,
                judge_model=judge_model,
                rubric=rubric,
                runtime=runtime,
                eval_kind=eval_kind,
                backend=backend,
                agent_timeout=agent_timeout,
                judge_timeout=judge_timeout,
            )
        return CaseResult(
            id=case.id,
            base_id=case.base_id,
            prompt_id=case.prompt_id,
            skill=case.skill,
            language=case.language,
            service=case.service,
            with_skill=with_skill,
            baseline=baseline,
        )
    finally:
        shutil.rmtree(exec_case_root, ignore_errors=True)


def run_side(
    *,
    repo_root: Path,
    case: EvalCase,
    side: str,
    exec_dir: Path,
    artifact_dir: Path,
    prompt: str,
    skill_dir: Path | None,
    model: str | None,
    judge_model: str | None,
    rubric: bool,
    runtime: bool,
    eval_kind: str,
    backend: AgentBackend,
    agent_timeout: int,
    judge_timeout: int,
) -> SideResult:
    side_start = time.monotonic()
    prepare_side_workspace(repo_root, case, side, exec_dir, skill_dir)

    agent_start = time.monotonic()
    agent_result = backend.run_agent(
        prompt=prompt,
        exec_dir=exec_dir,
        model=model,
        timeout=agent_timeout,
    )
    agent_duration_seconds = time.monotonic() - agent_start

    trace = backend.parse_trace(agent_result.trace_path)
    agent_usage = token_usage_from_trace_usage(trace.usage)
    agent_tokens = flat_token_total(agent_usage)
    final_message = agent_result.final_message_path.read_text(encoding="utf-8", errors="replace")
    grade = grade_side(
        case=case,
        run_dir=exec_dir,
        final_message=final_message,
        trace=trace,
        side=side,
        runtime_enabled=runtime,
        repo_root=repo_root,
    )
    grade_path = exec_dir / "grade.json"
    grade_path.write_text(grade.model_dump_json(indent=2), encoding="utf-8")

    rubric_path: Path | None = None
    rubric_duration_seconds = 0.0
    rubric_tokens = 0
    rubric_usage: TokenUsage | None = None
    errors: list[str] = []
    if agent_result.returncode != 0:
        errors.append(f"{backend.name} exited with {agent_result.returncode}")
    if rubric and isinstance(case, RubricEvalCase) and case.rubric:
        rubric_usage = TokenUsage(provider=usage_provider_for_backend(backend))
        rubric_start = time.monotonic()
        try:
            rubric_path = run_rubric_grade(
                case=case,
                side_dir=exec_dir,
                model=judge_model or model,
                backend=backend,
                timeout=judge_timeout,
            )
        except Exception as exc:  # pragma: no cover - preserved in run artifacts
            errors.append(f"rubric grading failed: {exc}")
        finally:
            rubric_duration_seconds = time.monotonic() - rubric_start
            rubric_trace_path = exec_dir / "rubric_trace.jsonl"
            if rubric_trace_path.exists():
                try:
                    rubric_usage = token_usage_from_trace_usage(
                        backend.parse_trace(rubric_trace_path).usage
                    )
                    rubric_tokens = flat_token_total(rubric_usage)
                except Exception as exc:  # pragma: no cover - preserved in run artifacts
                    errors.append(f"rubric trace parsing failed: {exc}")

    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    shutil.copytree(exec_dir, artifact_dir, symlinks=True)

    artifact_trace_path = artifact_dir / "trace.jsonl"
    artifact_final_path = artifact_dir / "last_message.md"
    artifact_rubric_path = artifact_dir / "rubric_grade.json"
    artifact_rubric_trace_path = artifact_dir / "rubric_trace.jsonl"

    result = SideResult(
        side=side,
        exit_code=agent_result.returncode,
        trace_path=str(artifact_trace_path),
        final_message_path=str(artifact_final_path),
        grade=grade,
        rubric_grade_path=str(artifact_rubric_path) if rubric_path else None,
        rubric_trace_path=str(artifact_rubric_trace_path) if rubric_path else None,
        command_count=len(trace.commands),
        duration_seconds=round(time.monotonic() - side_start, 3),
        agent_duration_seconds=round(agent_duration_seconds, 3),
        rubric_duration_seconds=round(rubric_duration_seconds, 3),
        tokens=agent_tokens + rubric_tokens,
        agent_tokens=agent_tokens,
        rubric_tokens=rubric_tokens,
        agent_usage=agent_usage,
        rubric_usage=rubric_usage,
        errors=errors,
    )
    (artifact_dir / "summary.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result


def token_usage_from_trace_usage(usage: TraceUsage) -> TokenUsage:
    return TokenUsage(
        provider=usage.provider,
        source=usage.source,
        observed=usage.observed,
        usage_record_count=usage.usage_record_count,
        selected_record_count=usage.selected_record_count,
        input_tokens=usage.input_tokens,
        cached_input_tokens=usage.cached_input_tokens,
        cache_creation_input_tokens=usage.cache_creation_input_tokens,
        output_tokens=usage.output_tokens,
        reasoning_output_tokens=usage.reasoning_output_tokens,
        provider_total_tokens=usage.provider_total_tokens,
        derived_total_tokens=usage.derived_total_tokens,
        effective_total_tokens=usage.total_tokens,
    )


def flat_token_total(usage: TokenUsage | None) -> int:
    if usage is None or usage.total_tokens is None:
        return 0
    return usage.total_tokens


def usage_provider_for_backend(backend: AgentBackend) -> UsageProvider:
    if backend.name == "codex":
        return "codex"
    if backend.name == "claude":
        return "claude"
    return "unknown"


def prepare_side_workspace(repo_root: Path, case: EvalCase, side: str, side_dir: Path, skill_dir: Path | None = None) -> None:
    if side_dir.exists():
        shutil.rmtree(side_dir)
    side_dir.mkdir(parents=True)
    if case.fixture_dir is None:
        raise ValueError(f"case {case.id} has no fixture_dir")
    staged_fixture_source_files(case.fixture_dir)
    shutil.copytree(
        case.fixture_dir,
        side_dir / "service",
        ignore=fixture_workspace_ignore,
    )
    copy_eval_inputs(
        case.fixture_dir,
        side_dir / "service",
        case.eval_inputs,
    )
    if side == "with_skill":
        skills_dir = side_dir / ".agents" / "skills"
        skills_dir.mkdir(parents=True)
        target = resolve_skill_source(repo_root, case.skill, case.skill_source, skill_dir)
        staged_skill_source_files(target)
        if not (target / "SKILL.md").exists():
            raise FileNotFoundError(f"missing skill source: {target / 'SKILL.md'}")
        shutil.copytree(
            target,
            skills_dir / target.name,
            ignore=skill_workspace_ignore,
        )

        references = repo_root / "skills" / "references"
        if references.exists():
            shared_skill_reference_source_files(repo_root)
            shutil.copytree(
                references,
                skills_dir / "references",
                ignore=skill_workspace_ignore,
            )


def copy_eval_inputs(
    fixture_dir: Path,
    service_dir: Path,
    eval_inputs: list[str] | None,
) -> None:
    """Expose only prompt-approved eval seeds, never eval definitions."""

    for relative, source in fixture_eval_input_sources(fixture_dir, eval_inputs):
        destination = service_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination, follow_symlinks=False)
