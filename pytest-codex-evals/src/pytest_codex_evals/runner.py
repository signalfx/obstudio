from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .ab import side_prompt
from .deterministic import grade_deterministic
from .models import CaseResult, EvalCase, SideResult
from .qualitative import run_qualitative_grade
from .trace import parse_trace


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
    qualitative: bool = True,
    sides: tuple[str, ...] = ("with_skill", "baseline"),
) -> CaseResult:
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
                qualitative=qualitative,
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
                qualitative=qualitative,
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
    qualitative: bool,
) -> SideResult:
    prepare_side_workspace(repo_root, case, side, exec_dir, skill_dir)
    trace_path = exec_dir / "trace.jsonl"
    final_path = exec_dir / "last_message.md"
    stderr_path = exec_dir / "stderr.txt"

    cmd = [
        "codex",
        "exec",
        "--json",
        "--full-auto",
        "--skip-git-repo-check",
        "--cd",
        str(exec_dir),
        "--output-last-message",
        str(final_path),
    ]
    if model:
        cmd.extend(["--model", model])
    cmd.append(prompt)

    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    trace_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    if not final_path.exists():
        final_path.write_text("", encoding="utf-8")

    trace = parse_trace(trace_path)
    final_message = final_path.read_text(encoding="utf-8", errors="replace")
    deterministic = grade_deterministic(case, exec_dir, final_message, trace, side)
    deterministic_path = exec_dir / "deterministic_grade.json"
    deterministic_path.write_text(deterministic.model_dump_json(indent=2), encoding="utf-8")

    qualitative_path: Path | None = None
    errors: list[str] = []
    if completed.returncode != 0:
        errors.append(f"codex exec exited with {completed.returncode}")
    if qualitative:
        try:
            qualitative_path = run_qualitative_grade(
                case=case,
                side_dir=exec_dir,
                model=judge_model or model,
            )
        except Exception as exc:  # pragma: no cover - preserved in run artifacts
            errors.append(f"qualitative grading failed: {exc}")

    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    shutil.copytree(exec_dir, artifact_dir, symlinks=True)

    artifact_trace_path = artifact_dir / "trace.jsonl"
    artifact_final_path = artifact_dir / "last_message.md"
    artifact_qualitative_path = artifact_dir / "qualitative_grade.json"

    result = SideResult(
        side=side,
        exit_code=completed.returncode,
        trace_path=str(artifact_trace_path),
        final_message_path=str(artifact_final_path),
        deterministic_grade=deterministic,
        qualitative_grade_path=str(artifact_qualitative_path) if qualitative_path else None,
        command_count=len(trace.commands),
        tokens=trace.usage.total_tokens,
        errors=errors,
    )
    (artifact_dir / "summary.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result


def prepare_side_workspace(repo_root: Path, case: EvalCase, side: str, side_dir: Path, skill_dir: Path | None = None) -> None:
    if side_dir.exists():
        shutil.rmtree(side_dir)
    side_dir.mkdir(parents=True)
    if case.fixture_dir is None:
        raise ValueError(f"case {case.id} has no fixture_dir")
    shutil.copytree(
        case.fixture_dir,
        side_dir / "service",
        ignore=shutil.ignore_patterns("*_eval.json", ".observe", ".venv", "__pycache__", "*.pyc", "uv.lock", "*.db"),
    )
    if side == "with_skill":
        skills_dir = side_dir / ".agents" / "skills"
        skills_dir.mkdir(parents=True)
        target = skill_dir or repo_root / "skills" / case.skill
        if not (target / "SKILL.md").exists():
            raise FileNotFoundError(f"missing skill source: {target / 'SKILL.md'}")
        create_skill_link(target, skills_dir / target.name)

        references = repo_root / "skills" / "references"
        if references.exists():
            create_skill_link(references, skills_dir / "references")


def create_skill_link(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        shutil.copytree(target, link)
