from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .ab import SKILL_COMPANIONS, side_prompt
from .backends import (
    AgentBackend,
    AnchoredDirectory,
    BACKEND_SCRATCH_DIRECTORY,
    CodexBackend,
    anchored_namespace_matches,
    atomic_text_write,
    close_anchored_directory,
    descriptor_operations_supported,
    ensure_anchored_directory,
    open_anchored_directory,
    path_is_link_or_reparse,
    regular_file_stability,
)
from .definitions import CaseResult, EvalCase, RubricEvalCase, SideResult
from .definitions.base import validate_eval_input_paths
from .eval_contracts import (
    canonical_sha256,
    case_contract_sha256,
    case_task_sha256,
)
from .graders import grade_side
from .graders.rubric import run_rubric_grade


PROVENANCE_FILE = ".codex-eval-provenance.json"
WORKSPACE_IGNORED_NAMES = {
    ".observe",
    ".venv",
    "__pycache__",
    "target",
    "uv.lock",
}
WORKSPACE_IGNORED_SUFFIXES = (".db", ".pyc")
HASH_IGNORED_NAMES = {".observe", ".venv", "__pycache__", "target"}
HASH_IGNORED_SUFFIXES = (".db", ".pyc")
ARTIFACT_IGNORED_NAMES = {
    ".agents",
    ".pip-cache",
    ".uv-cache",
    ".venv",
    "__pycache__",
    "target",
}
ARTIFACT_IGNORED_SUFFIXES = (".pyc",)
EXECUTION_QUARANTINE_ROOT_ENV = "CODEX_EVAL_QUARANTINE_ROOT"
EXECUTION_QUARANTINE_DIRECTORY_PREFIX = "codex-eval-quarantine-v1" + (
    f"-{os.geteuid()}" if hasattr(os, "geteuid") else ""
) + "-"
EXECUTION_QUARANTINE_MAX_WORKSPACES = 1024
EXECUTION_QUARANTINE_SLOT_PREFIX = "workspace-"
EXECUTION_QUARANTINE_SLOT_WIDTH = 6
EXECUTION_WORKSPACE_DIRECTORY = "execution"
_DEFAULT_EXECUTION_QUARANTINE_LOCK = threading.Lock()
_DEFAULT_EXECUTION_QUARANTINE_ROOT: Path | None = None


class DigestWriter(Protocol):
    """Minimal interface shared by the hashlib digest implementations."""

    def update(self, value: bytes, /) -> None: ...


@dataclass(frozen=True)
class CompanionSkillInputSnapshot:
    """One authenticated companion exposed beside the selected skill."""

    name: str
    source_path: str
    tree_sha256: str
    staged_skill_path: str | None


@dataclass(frozen=True)
class WorkspaceInputSnapshot:
    """Hashes of the immutable input copies prepared for one eval side."""

    fixture_path: str
    fixture_tree_sha256: str
    skill_path: str
    skill_tree_sha256: str
    staged_skill_path: str | None
    shared_references_path: str
    shared_references_tree_sha256: str | None
    definition_path: str | None
    definition_exists: bool
    definition_sha256: str | None
    companion_skills: tuple[CompanionSkillInputSnapshot, ...]


@dataclass(frozen=True)
class SourceTreeEntry:
    """One immutable directory or regular-file entry captured from a source."""

    relative: Path
    mode: int
    content: bytes | None


@dataclass(frozen=True)
class SourceTreeSnapshot:
    """Exact source bytes used for both provenance and workspace materialization."""

    source: Path
    entries: tuple[SourceTreeEntry, ...]
    tree_sha256: str

    def file_bytes(self, relative: Path) -> bytes | None:
        for entry in self.entries:
            if entry.relative == relative and entry.content is not None:
                return entry.content
        return None


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def new_run_root(repo_root: Path, skill: str, run_id: str | None = None) -> Path:
    run_id = run_id or new_run_id()
    return repo_root / ".workspace" / "codex-evals" / skill / run_id


def allocate_execution_workspace() -> tuple[Path, AnchoredDirectory]:
    """Atomically reserve one retained execution workspace.

    The harness never deliberately releases a normally retained reservation.
    The fixed namespace limits cooperative allocator use, but it is not a
    same-UID security or resource boundary: evaluated code can move a
    top-level reservation and make that name reusable. Callers must place the
    quarantine on an isolated, quota-limited disposable filesystem when
    evaluated code is untrusted.
    """

    quarantine_anchor = open_execution_quarantine()
    try:
        validate_execution_quarantine(quarantine_anchor)
        for index in range(EXECUTION_QUARANTINE_MAX_WORKSPACES):
            slot_name = (
                f"{EXECUTION_QUARANTINE_SLOT_PREFIX}"
                f"{index:0{EXECUTION_QUARANTINE_SLOT_WIDTH}d}"
            )
            try:
                create_anchored_child_directory(
                    quarantine_anchor, slot_name, mode=0o700
                )
            except FileExistsError:
                continue

            # The harness never deliberately releases this reservation on a
            # later failure. Never delete through this pathname: evaluated
            # code may retain a concurrent renamer and substitute a victim.
            if not anchored_namespace_matches(quarantine_anchor):
                raise ValueError(
                    "eval execution quarantine changed during allocation"
                )
            slot_path = quarantine_anchor.path / slot_name
            slot_anchor = open_anchored_directory(
                slot_path, quarantine_anchor.path
            )
            try:
                if (
                    slot_anchor.boundary_identity
                    != quarantine_anchor.parent_identity
                ):
                    raise ValueError(
                        "eval execution quarantine was replaced during allocation"
                    )
                validate_private_directory(
                    slot_anchor, f"eval execution reservation {slot_name}"
                )
                create_anchored_child_directory(
                    slot_anchor, EXECUTION_WORKSPACE_DIRECTORY, mode=0o700
                )
                if not anchored_namespace_matches(slot_anchor):
                    raise ValueError(
                        "eval execution reservation changed during allocation"
                    )
            finally:
                close_anchored_directory(slot_anchor)

            workspace_path = slot_path / EXECUTION_WORKSPACE_DIRECTORY
            workspace_anchor = open_anchored_directory(
                workspace_path, quarantine_anchor.path
            )
            if (
                workspace_anchor.boundary_identity
                != quarantine_anchor.parent_identity
                or not anchored_namespace_matches(workspace_anchor)
            ):
                close_anchored_directory(workspace_anchor)
                raise ValueError(
                    "eval execution workspace was replaced during allocation"
                )
            return workspace_path, workspace_anchor

        raise RuntimeError(
            "eval execution quarantine retained workspace limit reached "
            f"({EXECUTION_QUARANTINE_MAX_WORKSPACES}); refusing to start the "
            "agent backend. Start a fresh harness invocation, or provision a "
            "fresh quota-limited disposable filesystem via "
            f"{EXECUTION_QUARANTINE_ROOT_ENV} only after all processes from "
            "the previous quarantine have stopped."
        )
    finally:
        close_anchored_directory(quarantine_anchor)


def open_execution_quarantine() -> AnchoredDirectory:
    configured = os.environ.get(EXECUTION_QUARANTINE_ROOT_ENV)
    if configured:
        quarantine_root = Path(configured)
        if not quarantine_root.is_absolute():
            raise ValueError(
                f"{EXECUTION_QUARANTINE_ROOT_ENV} must be an absolute path"
            )
        try:
            return open_anchored_directory(quarantine_root, quarantine_root)
        except FileNotFoundError as error:
            raise ValueError(
                f"{EXECUTION_QUARANTINE_ROOT_ENV} must name a pre-provisioned "
                "private directory"
            ) from error

    quarantine_root = default_execution_quarantine_root()
    return open_anchored_directory(quarantine_root, quarantine_root)


def default_execution_quarantine_root() -> Path:
    """Return this process's retained private default quarantine.

    A random process-local root prevents normal prior invocations from
    consuming the current invocation's fixed reservation namespace. It is
    intentionally never pathname-deleted; the operating-system temporary
    directory lifecycle owns eventual cleanup.
    """

    global _DEFAULT_EXECUTION_QUARANTINE_ROOT
    with _DEFAULT_EXECUTION_QUARANTINE_LOCK:
        if _DEFAULT_EXECUTION_QUARANTINE_ROOT is None:
            temporary_root = Path(os.path.abspath(tempfile.gettempdir()))
            temporary_anchor = open_anchored_directory(
                temporary_root, temporary_root
            )
            try:
                quarantine_root = Path(
                    tempfile.mkdtemp(
                        prefix=EXECUTION_QUARANTINE_DIRECTORY_PREFIX,
                        dir=temporary_root,
                    )
                )
                if not anchored_namespace_matches(temporary_anchor):
                    raise ValueError(
                        "operating-system temporary directory changed during "
                        "quarantine setup"
                    )
                quarantine_anchor = open_anchored_directory(
                    quarantine_root, temporary_root
                )
                try:
                    if (
                        quarantine_anchor.boundary_identity
                        != temporary_anchor.parent_identity
                    ):
                        raise ValueError(
                            "operating-system temporary directory was replaced "
                            "during quarantine setup"
                        )
                    validate_private_directory(
                        quarantine_anchor, "eval execution quarantine"
                    )
                finally:
                    close_anchored_directory(quarantine_anchor)
            finally:
                close_anchored_directory(temporary_anchor)
            _DEFAULT_EXECUTION_QUARANTINE_ROOT = quarantine_root
        return _DEFAULT_EXECUTION_QUARANTINE_ROOT


def validate_execution_quarantine(anchor: AnchoredDirectory) -> None:
    validate_private_directory(anchor, "eval execution quarantine")
    expected_names = {
        (
            f"{EXECUTION_QUARANTINE_SLOT_PREFIX}"
            f"{index:0{EXECUTION_QUARANTINE_SLOT_WIDTH}d}"
        )
        for index in range(EXECUTION_QUARANTINE_MAX_WORKSPACES)
    }
    names = (
        os.listdir(anchor.descriptor)
        if anchor.descriptor is not None
        else os.listdir(anchor.path)
    )
    unexpected = sorted(set(names) - expected_names)
    if unexpected:
        raise ValueError(
            "eval execution quarantine contains unexpected entries; "
            f"refusing allocation: {', '.join(unexpected)}"
        )
    for name in names:
        details = (
            os.stat(name, dir_fd=anchor.descriptor, follow_symlinks=False)
            if anchor.descriptor is not None
            else os.lstat(anchor.path / name)
        )
        if path_is_link_or_reparse(details) or not stat.S_ISDIR(details.st_mode):
            raise ValueError(
                "eval execution quarantine reservation must be a real "
                f"directory: {name}"
            )
        validate_private_directory_status(
            details, f"eval execution reservation {name}"
        )
    if not anchored_namespace_matches(anchor):
        raise ValueError("eval execution quarantine changed during validation")


def validate_private_directory(anchor: AnchoredDirectory, label: str) -> None:
    details = (
        os.fstat(anchor.descriptor)
        if anchor.descriptor is not None
        else os.lstat(anchor.path)
    )
    validate_private_directory_status(details, label)
    if not anchored_namespace_matches(anchor):
        raise ValueError(f"{label} changed during validation")


def validate_private_directory_status(details: os.stat_result, label: str) -> None:
    if path_is_link_or_reparse(details) or not stat.S_ISDIR(details.st_mode):
        raise ValueError(f"{label} must be a real directory")
    if hasattr(os, "geteuid") and details.st_uid != os.geteuid():
        raise ValueError(f"{label} must be owned by the current user")
    if os.name == "posix" and stat.S_IMODE(details.st_mode) != 0o700:
        raise ValueError(f"{label} must have mode 0700")


def create_anchored_child_directory(
    parent: AnchoredDirectory, name: str, *, mode: int
) -> None:
    if parent.descriptor is None:
        (parent.path / name).mkdir(mode=mode)
    else:
        os.mkdir(name, mode=mode, dir_fd=parent.descriptor)


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
    config_path: Path | None = None,
    run_configuration: dict[str, object] | None = None,
) -> CaseResult:
    require_collected_definition(case)
    if backend is None:
        backend = CodexBackend()
    run_root_identity = ensure_real_directory(run_root, repo_root, create=True)
    case_root = run_root / "cases" / case.language / case.service / case.prompt_id
    exec_case_root, exec_case_anchor = allocate_execution_workspace()
    exec_case_root_identity = exec_case_anchor.parent_identity
    try:
        with_skill = None
        baseline = None
        if "with_skill" in sides:
            if not anchored_namespace_matches(exec_case_anchor):
                raise ValueError("eval execution root was replaced between sides")
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
                config_path=config_path,
                run_configuration=run_configuration,
                run_root=run_root,
                run_root_identity=run_root_identity,
                exec_root_identity=exec_case_root_identity,
            )
        if "baseline" in sides:
            if not anchored_namespace_matches(exec_case_anchor):
                raise ValueError("eval execution root was replaced between sides")
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
                config_path=config_path,
                run_configuration=run_configuration,
                run_root=run_root,
                run_root_identity=run_root_identity,
                exec_root_identity=exec_case_root_identity,
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
        close_anchored_directory(exec_case_anchor)
        # Code evaluated in this directory is untrusted and can retain a
        # concurrent renamer. There is no portable conditional-rmdir syscall,
        # so deleting by pathname here could delete a replacement victim.
        # The harness intentionally does not release the reservation. Treat
        # this as cooperative bookkeeping only: same-UID code can move the
        # top-level slot. Reclaim the isolated quarantine externally after
        # every descendant process has stopped.


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
    config_path: Path | None,
    run_configuration: dict[str, object] | None,
    run_root: Path,
    run_root_identity: tuple[int, int],
    exec_root_identity: tuple[int, int],
) -> SideResult:
    require_directory_identity(run_root, run_root_identity, "eval run root")
    artifact_parent_anchor = open_anchored_directory(
        artifact_dir.parent, run_root, create=True
    )
    if artifact_parent_anchor.boundary_identity != run_root_identity:
        close_anchored_directory(artifact_parent_anchor)
        raise ValueError("eval run root was replaced before artifact setup")
    try:
        if not anchored_namespace_matches(artifact_parent_anchor):
            raise ValueError("eval artifact parent was replaced during setup")
        if directory_entry_exists(artifact_parent_anchor, artifact_dir.name):
            raise ValueError(
                f"artifact directory already exists; refusing to replace it: {artifact_dir}"
            )
        input_snapshot = prepare_side_workspace(
            repo_root,
            case,
            side,
            exec_dir,
            skill_dir,
            exec_root_identity=exec_root_identity,
        )
        exec_anchor = open_anchored_directory(exec_dir, exec_dir.parent)
        if exec_anchor.boundary_identity != exec_root_identity:
            close_anchored_directory(exec_anchor)
            raise ValueError("eval execution root was replaced before agent launch")
        try:
            return _run_side_anchored(
                repo_root=repo_root,
                case=case,
                side=side,
                exec_dir=exec_dir,
                artifact_dir=artifact_dir,
                prompt=prompt,
                skill_dir=skill_dir,
                model=model,
                judge_model=judge_model,
                rubric=rubric,
                runtime=runtime,
                eval_kind=eval_kind,
                backend=backend,
                agent_timeout=agent_timeout,
                judge_timeout=judge_timeout,
                config_path=config_path,
                run_configuration=run_configuration,
                input_snapshot=input_snapshot,
                run_root=run_root,
                run_root_identity=run_root_identity,
                exec_anchor=exec_anchor,
                artifact_parent_anchor=artifact_parent_anchor,
            )
        finally:
            close_anchored_directory(exec_anchor)
    finally:
        close_anchored_directory(artifact_parent_anchor)


def _run_side_anchored(
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
    config_path: Path | None,
    run_configuration: dict[str, object] | None,
    input_snapshot: WorkspaceInputSnapshot,
    run_root: Path,
    run_root_identity: tuple[int, int],
    exec_anchor: AnchoredDirectory,
    artifact_parent_anchor: AnchoredDirectory,
) -> SideResult:
    side_start = time.monotonic()
    provenance = build_run_provenance(
        repo_root,
        case,
        skill_dir,
        config_path=config_path,
        run_configuration=run_configuration,
        input_snapshot=input_snapshot,
    )
    exec_dir_identity = exec_anchor.parent_identity

    agent_start = time.monotonic()
    agent_result = backend.run_agent(
        prompt=prompt,
        exec_dir=exec_dir,
        model=model,
        timeout=agent_timeout,
    )
    agent_duration_seconds = time.monotonic() - agent_start

    trace_relative = relative_artifact_path(agent_result.trace_path, exec_dir)
    final_relative = relative_artifact_path(
        agent_result.final_message_path, exec_dir
    )
    trace_bytes = read_regular_from_directory(exec_anchor, trace_relative)
    final_bytes = read_regular_from_directory(exec_anchor, final_relative)
    if not anchored_namespace_matches(exec_anchor):
        raise ValueError("eval execution directory was replaced during agent output read")
    trace = parse_trace_snapshot(backend, trace_bytes)
    agent_tokens = trace.usage.total_tokens
    final_message = final_bytes.decode("utf-8", errors="replace")
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
    atomic_text_write(
        grade_path,
        grade.model_dump_json(indent=2),
        boundary=exec_dir,
        expected_boundary_identity=exec_dir_identity,
    )

    rubric_path: Path | None = None
    rubric_duration_seconds = 0.0
    rubric_tokens = 0
    errors: list[str] = []
    if agent_result.returncode != 0:
        errors.append(f"{backend.name} exited with {agent_result.returncode}")
    if rubric and isinstance(case, RubricEvalCase) and case.rubric:
        if not anchored_namespace_matches(exec_anchor):
            raise ValueError("eval execution directory was replaced before rubric grading")
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
            rubric_trace_relative = Path("rubric_trace.jsonl")
            if directory_entry_exists(exec_anchor, rubric_trace_relative.name):
                try:
                    rubric_trace_bytes = read_regular_from_directory(
                        exec_anchor, rubric_trace_relative
                    )
                    rubric_tokens = parse_trace_snapshot(
                        backend, rubric_trace_bytes
                    ).usage.total_tokens
                except Exception as exc:  # pragma: no cover - preserved in run artifacts
                    errors.append(f"rubric trace parsing failed: {exc}")

    if not anchored_namespace_matches(exec_anchor):
        raise ValueError("eval execution directory was replaced after grading")
    for harness_artifact in (grade_path, rubric_path):
        if harness_artifact is None:
            continue
        relative = relative_artifact_path(harness_artifact, exec_dir)
        read_regular_from_directory(exec_anchor, relative)

    # Write this after the agent completes so the preserved manifest is owned by
    # the harness, not by code running inside the evaluation workspace.
    atomic_text_write(
        exec_dir / PROVENANCE_FILE,
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        boundary=exec_dir,
        expected_boundary_identity=exec_dir_identity,
    )

    provenance_bytes = (
        json.dumps(provenance, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if not anchored_namespace_matches(exec_anchor):
        raise ValueError("eval execution directory was replaced before capture")
    if not anchored_namespace_matches(artifact_parent_anchor):
        raise ValueError("eval artifact parent was replaced before capture")
    if directory_entry_exists(artifact_parent_anchor, artifact_dir.name):
        raise ValueError(
            f"artifact directory appeared during agent execution: {artifact_dir}"
        )
    artifact_anchor = create_child_directory_anchor(
        artifact_parent_anchor, artifact_dir.name
    )
    artifact_dir_identity = artifact_anchor.parent_identity
    try:
        copy_artifact_tree(exec_anchor, artifact_anchor)
        if not anchored_namespace_matches(exec_anchor):
            raise ValueError("eval execution directory was replaced during capture")
        if not anchored_namespace_matches(artifact_anchor):
            raise ValueError("eval artifact directory was replaced during capture")
        if read_regular_from_directory(artifact_anchor, trace_relative) != trace_bytes:
            raise ValueError("captured trace differs from the authenticated agent output")
        if read_regular_from_directory(artifact_anchor, final_relative) != final_bytes:
            raise ValueError(
                "captured final message differs from the authenticated agent output"
            )
        if read_regular_from_directory(
            artifact_anchor, Path(PROVENANCE_FILE)
        ) != provenance_bytes:
            raise ValueError("captured provenance differs from harness-owned bytes")

        artifact_trace_path = artifact_dir / trace_relative
        artifact_final_path = artifact_dir / final_relative
        artifact_rubric_path = artifact_dir / "rubric_grade.json"
        artifact_rubric_trace_path = artifact_dir / "rubric_trace.jsonl"

        result = SideResult(
            side=side,
            exit_code=agent_result.returncode,
            trace_path=str(artifact_trace_path),
            final_message_path=str(artifact_final_path),
            grade=grade,
            rubric_grade_path=(
                str(artifact_rubric_path) if rubric_path else None
            ),
            rubric_trace_path=(
                str(artifact_rubric_trace_path) if rubric_path else None
            ),
            command_count=len(trace.commands),
            duration_seconds=round(time.monotonic() - side_start, 3),
            agent_duration_seconds=round(agent_duration_seconds, 3),
            rubric_duration_seconds=round(rubric_duration_seconds, 3),
            tokens=agent_tokens + rubric_tokens,
            agent_tokens=agent_tokens,
            rubric_tokens=rubric_tokens,
            errors=errors,
        )
        atomic_text_write(
            artifact_dir / "summary.json",
            result.model_dump_json(indent=2),
            boundary=artifact_dir,
            expected_boundary_identity=artifact_dir_identity,
        )
        if not anchored_namespace_matches(artifact_anchor):
            raise ValueError("eval artifact directory was replaced after summary write")
        return result
    finally:
        close_anchored_directory(artifact_anchor)


def ensure_real_directory(
    path: Path,
    boundary: Path,
    *,
    create: bool,
) -> tuple[int, int]:
    boundary_identity = directory_identity(boundary)
    if create:
        return ensure_anchored_directory(
            path,
            boundary=boundary,
            expected_boundary_identity=boundary_identity,
        )
    anchor = open_anchored_directory(path, boundary)
    try:
        if anchor.boundary_identity != boundary_identity:
            raise ValueError(f"trusted directory boundary was replaced: {boundary}")
        if not anchored_namespace_matches(anchor):
            raise ValueError(f"directory namespace changed while opening: {path}")
        return anchor.parent_identity
    finally:
        close_anchored_directory(anchor)


def directory_entry_exists(anchor: AnchoredDirectory, name: str) -> bool:
    try:
        if anchor.descriptor is not None:
            os.stat(name, dir_fd=anchor.descriptor, follow_symlinks=False)
        else:
            os.lstat(anchor.path / name)
    except FileNotFoundError:
        return False
    return True


def descriptor_identity(descriptor: int) -> tuple[int, int]:
    details = os.fstat(descriptor)
    if not stat.S_ISDIR(details.st_mode):
        raise ValueError("expected an open directory descriptor")
    return details.st_dev, details.st_ino


def create_child_directory_anchor(
    parent: AnchoredDirectory, name: str
) -> AnchoredDirectory:
    if parent.descriptor is None:
        child = parent.path / name
        child.mkdir(mode=0o755)
        anchor = open_anchored_directory(child, parent.boundary)
        if anchor.boundary_identity != parent.boundary_identity:
            close_anchored_directory(anchor)
            raise ValueError("directory boundary changed while creating child")
        return anchor
    os.mkdir(name, mode=0o755, dir_fd=parent.descriptor)
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(name, directory_flags, dir_fd=parent.descriptor)
    return AnchoredDirectory(
        descriptor=descriptor,
        boundary=parent.boundary,
        relative_parts=(*parent.relative_parts, name),
        boundary_identity=parent.boundary_identity,
        parent_identity=descriptor_identity(descriptor),
        path=parent.path / name,
    )


def relative_artifact_path(path: Path, boundary: Path) -> Path:
    candidate = path if path.is_absolute() else boundary / path
    candidate = Path(os.path.abspath(candidate))
    root = Path(os.path.abspath(boundary))
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"backend artifact escapes execution directory: {path}") from error
    if not relative.parts:
        raise ValueError(f"backend artifact must name a file: {path}")
    return relative


def read_regular_from_directory(
    anchor: AnchoredDirectory, relative: Path
) -> bytes:
    if anchor.descriptor is None:
        candidate = anchor.path / relative
        current = anchor.path
        for component in relative.parts[:-1]:
            current = current / component
            details = os.lstat(current)
            if path_is_link_or_reparse(details) or not stat.S_ISDIR(details.st_mode):
                raise ValueError(f"artifact path must contain real directories: {relative}")
        details = os.lstat(candidate)
        if path_is_link_or_reparse(details) or not stat.S_ISREG(details.st_mode):
            raise ValueError(f"artifact must be a regular file: {relative}")
        file_descriptor = os.open(
            candidate, os.O_RDONLY | getattr(os, "O_BINARY", 0)
        )
        try:
            if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
                raise ValueError(f"artifact must be a regular file: {relative}")
            chunks: list[bytes] = []
            while chunk := os.read(file_descriptor, 1024 * 1024):
                chunks.append(chunk)
        finally:
            os.close(file_descriptor)
        if not anchored_namespace_matches(anchor):
            raise ValueError("artifact directory changed during portable read")
        return b"".join(chunks)

    current = os.dup(anchor.descriptor)
    try:
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        for component in relative.parts[:-1]:
            next_descriptor = os.open(
                component, directory_flags, dir_fd=current
            )
            os.close(current)
            current = next_descriptor
        file_descriptor = os.open(
            relative.parts[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=current,
        )
        try:
            details = os.fstat(file_descriptor)
            if not stat.S_ISREG(details.st_mode):
                raise ValueError(f"artifact must be a regular file: {relative}")
            chunks: list[bytes] = []
            while chunk := os.read(file_descriptor, 1024 * 1024):
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(file_descriptor)
    finally:
        os.close(current)


def parse_trace_snapshot(backend: AgentBackend, value: bytes):
    """Parse already-authenticated trace bytes without an exposed temp path."""

    return backend.parse_trace_bytes(value)


def copy_regular_file_fd(
    source_descriptor: int,
    destination_descriptor: int,
    name: str,
    mode: int,
) -> None:
    source = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=source_descriptor,
    )
    destination: int | None = None
    try:
        if not stat.S_ISREG(os.fstat(source).st_mode):
            raise ValueError(f"unsupported non-regular artifact: {name}")
        destination = os.open(
            name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            mode & 0o777,
            dir_fd=destination_descriptor,
        )
        while chunk := os.read(source, 1024 * 1024):
            offset = 0
            while offset < len(chunk):
                offset += os.write(destination, chunk[offset:])
        os.fsync(destination)
    finally:
        os.close(source)
        if destination is not None:
            os.close(destination)


def copy_artifact_tree_fd(
    source_descriptor: int,
    destination_descriptor: int,
    *,
    root: bool = True,
) -> None:
    names = sorted(os.listdir(source_descriptor))
    ignored = artifact_ignore("", names)
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    for name in names:
        if name in ignored or (
            root and name in {BACKEND_SCRATCH_DIRECTORY, "summary.json"}
        ):
            continue
        details = os.stat(name, dir_fd=source_descriptor, follow_symlinks=False)
        if stat.S_ISLNK(details.st_mode):
            raise ValueError(f"artifact tree must not contain symlinks: {name}")
        if stat.S_ISDIR(details.st_mode):
            os.mkdir(name, mode=details.st_mode & 0o777, dir_fd=destination_descriptor)
            source_child = os.open(name, directory_flags, dir_fd=source_descriptor)
            destination_child = os.open(
                name, directory_flags, dir_fd=destination_descriptor
            )
            try:
                copy_artifact_tree_fd(
                    source_child, destination_child, root=False
                )
            finally:
                os.close(source_child)
                os.close(destination_child)
            continue
        if stat.S_ISREG(details.st_mode):
            copy_regular_file_fd(
                source_descriptor,
                destination_descriptor,
                name,
                details.st_mode,
            )
            continue
        raise ValueError(f"unsupported artifact tree entry: {name}")


def copy_artifact_tree(
    source: AnchoredDirectory,
    destination: AnchoredDirectory,
) -> None:
    if source.descriptor is not None and destination.descriptor is not None:
        copy_artifact_tree_fd(source.descriptor, destination.descriptor)
        return
    if source.descriptor is not None or destination.descriptor is not None:
        raise ValueError("artifact copy capabilities changed during execution")
    copy_artifact_tree_portable(source.path, destination.path)


def copy_artifact_tree_portable(
    source: Path,
    destination: Path,
    *,
    root: bool = True,
) -> None:
    names = sorted(entry.name for entry in os.scandir(source))
    ignored = artifact_ignore("", names)
    for name in names:
        if name in ignored or (
            root and name in {BACKEND_SCRATCH_DIRECTORY, "summary.json"}
        ):
            continue
        source_path = source / name
        destination_path = destination / name
        details = os.lstat(source_path)
        if path_is_link_or_reparse(details):
            raise ValueError(f"artifact tree must not contain links: {source_path}")
        if stat.S_ISDIR(details.st_mode):
            destination_path.mkdir(mode=details.st_mode & 0o777)
            copy_artifact_tree_portable(
                source_path, destination_path, root=False
            )
            continue
        if stat.S_ISREG(details.st_mode):
            copy_regular_file_portable(
                source_path, destination_path, details.st_mode
            )
            continue
        raise ValueError(f"unsupported artifact tree entry: {source_path}")


def copy_regular_file_portable(
    source: Path,
    destination: Path,
    mode: int,
) -> None:
    source_descriptor = os.open(
        source, os.O_RDONLY | getattr(os, "O_BINARY", 0)
    )
    destination_descriptor: int | None = None
    try:
        if not stat.S_ISREG(os.fstat(source_descriptor).st_mode):
            raise ValueError(f"source must be a regular file: {source}")
        destination_descriptor = os.open(
            destination,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0),
            mode & 0o777,
        )
        while chunk := os.read(source_descriptor, 1024 * 1024):
            offset = 0
            while offset < len(chunk):
                offset += os.write(destination_descriptor, chunk[offset:])
        os.fsync(destination_descriptor)
    finally:
        os.close(source_descriptor)
        if destination_descriptor is not None:
            os.close(destination_descriptor)


def directory_identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    if path_is_link_or_reparse(details) or not stat.S_ISDIR(details.st_mode):
        raise ValueError(f"expected a real directory: {path}")
    return details.st_dev, details.st_ino


def require_directory_identity(
    path: Path,
    expected: tuple[int, int],
    label: str,
) -> None:
    try:
        current = directory_identity(path)
    except (OSError, ValueError) as error:
        raise ValueError(f"{label} was replaced or became unsafe: {path}") from error
    if current != expected:
        raise ValueError(f"{label} was replaced during execution: {path}")


def ensure_contained_regular_path(path: Path, boundary: Path) -> None:
    candidate = path if path.is_absolute() else boundary / path
    absolute_candidate = candidate.absolute()
    absolute_boundary = boundary.absolute()
    try:
        relative = absolute_candidate.relative_to(absolute_boundary)
    except ValueError as error:
        raise ValueError(f"backend artifact escapes execution directory: {path}") from error
    current = absolute_boundary
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise ValueError(f"backend artifact path traverses a symlink: {current}")
    try:
        absolute_candidate.resolve().relative_to(absolute_boundary.resolve())
    except ValueError as error:
        raise ValueError(f"backend artifact resolves outside execution directory: {path}") from error


def workspace_ignore(fixture_dir: Path):
    fixture_root = fixture_dir.resolve()

    def ignore(directory: str, names: list[str]) -> set[str]:
        excluded = {
            name
            for name in names
            if name in WORKSPACE_IGNORED_NAMES
            or name.endswith(WORKSPACE_IGNORED_SUFFIXES)
            or name.endswith("_eval.json")
        }
        if Path(directory).resolve() == fixture_root and "eval" in names:
            excluded.add("eval")
        return excluded

    return ignore


def artifact_ignore(_directory: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name in ARTIFACT_IGNORED_NAMES
        or name.endswith(ARTIFACT_IGNORED_SUFFIXES)
    }


def copy_eval_inputs(fixture_dir: Path, service_dir: Path) -> None:
    """Copy only explicit eval seeds while keeping eval definitions private."""

    source = fixture_dir / "eval" / "inputs"
    if source.is_symlink():
        raise ValueError(f"eval input seed must be a real directory: {source}")
    if not source.exists():
        return
    if not source.is_dir():
        raise ValueError(f"eval input seed must be a real directory: {source}")
    for candidate in source.rglob("*"):
        if candidate.is_symlink():
            raise ValueError(f"eval input seed must not contain symlinks: {candidate}")
        if not candidate.is_dir() and not candidate.is_file():
            raise ValueError(f"unsupported eval input seed entry: {candidate}")
    destination = service_dir / "eval" / "inputs"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)


def validate_fixture_tree(fixture_dir: Path) -> None:
    """Reject fixture symlinks before copytree can dereference outside content."""

    if fixture_dir.is_symlink():
        raise ValueError(f"eval fixture must not be a symlink: {fixture_dir}")
    for directory, dirnames, filenames in os.walk(fixture_dir, followlinks=False):
        parent = Path(directory)
        for name in [*dirnames, *filenames]:
            candidate = parent / name
            if candidate.is_symlink():
                raise ValueError(
                    f"eval fixture must not contain symlinks: {candidate}"
                )


def tree_sha256(root: Path) -> str:
    if root.is_symlink():
        raise ValueError(f"provenance source tree must not be a symlink: {root}")
    if not root.is_dir():
        raise FileNotFoundError(root)
    digest = hashlib.sha256()
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        parent = Path(directory)
        retained_dirs: list[str] = []
        for name in sorted(dirnames):
            if name in HASH_IGNORED_NAMES:
                continue
            candidate = parent / name
            relative = candidate.relative_to(root)
            digest.update(relative.as_posix().encode("utf-8"))
            digest.update(b"\0")
            if candidate.is_symlink():
                raise ValueError(
                    f"provenance source tree must not contain symlinks: {candidate}"
                )
            digest.update(b"dir\0")
            retained_dirs.append(name)
            digest.update(b"\0")
        dirnames[:] = retained_dirs
        for name in sorted(filenames):
            if name.endswith(HASH_IGNORED_SUFFIXES):
                continue
            candidate = parent / name
            relative = candidate.relative_to(root)
            digest.update(relative.as_posix().encode("utf-8"))
            digest.update(b"\0")
            if candidate.is_symlink():
                raise ValueError(
                    f"provenance source tree must not contain symlinks: {candidate}"
                )
            digest.update(b"file\0")
            digest.update(candidate.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def build_run_provenance(
    repo_root: Path,
    case: EvalCase,
    skill_dir: Path | None,
    *,
    config_path: Path | None = None,
    run_configuration: dict[str, object] | None = None,
    input_snapshot: WorkspaceInputSnapshot | None = None,
) -> dict[str, object]:
    if case.fixture_dir is None:
        raise ValueError(f"case {case.id} has no fixture_dir")
    selected_skill = skill_dir or repo_root / "skills" / case.skill
    shared_references = repo_root / "skills" / "references"
    if input_snapshot is None:
        validate_fixture_tree(case.fixture_dir)
    harness_source = Path(__file__).resolve().parent
    normalized_run_configuration = dict(run_configuration or {})
    fixture_tree_digest = (
        input_snapshot.fixture_tree_sha256
        if input_snapshot is not None
        else tree_sha256(case.fixture_dir)
    )
    skill_tree_digest = (
        input_snapshot.skill_tree_sha256
        if input_snapshot is not None
        else tree_sha256(selected_skill)
    )
    shared_references_tree_digest = (
        input_snapshot.shared_references_tree_sha256
        if input_snapshot is not None
        else (
            tree_sha256(shared_references)
            if shared_references.is_dir()
            else None
        )
    )
    fixture_path = (
        input_snapshot.fixture_path
        if input_snapshot is not None
        else str(case.fixture_dir.resolve())
    )
    skill_path = (
        input_snapshot.skill_path
        if input_snapshot is not None
        else str(selected_skill.resolve())
    )
    shared_references_path = (
        input_snapshot.shared_references_path
        if input_snapshot is not None
        else str(shared_references.resolve())
    )
    if input_snapshot is not None:
        companion_skills = [
            {
                "name": companion.name,
                "path": companion.source_path,
                "tree_sha256": companion.tree_sha256,
                "staged_path": companion.staged_skill_path,
            }
            for companion in input_snapshot.companion_skills
        ]
    else:
        companion_skills = []
        for name in SKILL_COMPANIONS.get(case.skill, ()):
            source = selected_skill.parent / name
            companion_skills.append(
                {
                    "name": name,
                    "path": str(source.resolve()),
                    "tree_sha256": tree_sha256(source),
                    "staged_path": None,
                }
            )
    definition = (
        {
            "path": input_snapshot.definition_path,
            "exists": input_snapshot.definition_exists,
            "sha256": input_snapshot.definition_sha256,
        }
        if input_snapshot is not None
        else file_provenance(case.definition_path)
    )
    require_collected_definition(case, definition)
    return {
        "schema_version": 2,
        "case": {
            "id": case.id,
            "base_id": case.base_id,
            "prompt_id": case.prompt_id,
            "skill": case.skill,
            "language": case.language,
            "service": case.service,
            "task": case.task,
            "task_sha256": case_task_sha256(case),
            "contract_sha256": case_contract_sha256(case),
        },
        "definition": definition,
        "config": file_provenance(config_path),
        "run_configuration": {
            "value": normalized_run_configuration,
            "sha256": canonical_sha256(normalized_run_configuration),
        },
        "fixture": {
            "path": fixture_path,
            "tree_sha256": fixture_tree_digest,
        },
        "skill": {
            "path": skill_path,
            "tree_sha256": skill_tree_digest,
            "staged_path": (
                input_snapshot.staged_skill_path
                if input_snapshot is not None
                else None
            ),
        },
        "companion_skills": companion_skills,
        "shared_references": {
            "path": shared_references_path,
            "tree_sha256": shared_references_tree_digest,
        },
        "harness": {
            "path": str(harness_source),
            "tree_sha256": tree_sha256(harness_source),
        },
    }


def file_provenance(path: Path | None) -> dict[str, object]:
    if path is None:
        return {"path": None, "exists": False, "sha256": None}
    if path.is_symlink():
        raise ValueError(f"provenance source file must not be a symlink: {path}")
    resolved = path.resolve()
    if not resolved.exists():
        return {"path": str(resolved), "exists": False, "sha256": None}
    if not resolved.is_file():
        raise ValueError(f"provenance source must be a file: {resolved}")
    return {
        "path": str(resolved),
        "exists": True,
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
    }


def require_collected_definition(
    case: EvalCase,
    provenance: dict[str, object] | None = None,
) -> None:
    """Fail before execution when a collected case no longer matches its file."""

    if case.definition_sha256 is None:
        return
    if case.definition_path is None:
        raise ValueError(
            f"{case.id}: collected eval case has no definition path"
        )
    if case.collected_contract_sha256 is None:
        raise ValueError(
            f"{case.id}: collected eval case has no contract hash"
        )
    if case_contract_sha256(case) != case.collected_contract_sha256:
        raise ValueError(
            f"{case.id}: eval case contract changed after collection"
        )
    current = provenance or file_provenance(case.definition_path)
    if (
        not current.get("exists")
        or current.get("sha256") != case.definition_sha256
    ):
        raise ValueError(
            f"{case.id}: eval definition changed after case collection"
        )


def prepare_side_workspace(
    repo_root: Path,
    case: EvalCase,
    side: str,
    side_dir: Path,
    skill_dir: Path | None = None,
    *,
    exec_root_identity: tuple[int, int] | None = None,
) -> WorkspaceInputSnapshot:
    if case.fixture_dir is None:
        raise ValueError(f"case {case.id} has no fixture_dir")
    validate_fixture_tree(case.fixture_dir)
    expected_root_identity = exec_root_identity or directory_identity(
        side_dir.parent
    )
    parent_anchor = open_anchored_directory(side_dir.parent, side_dir.parent)
    try:
        if parent_anchor.boundary_identity != expected_root_identity:
            raise ValueError("eval execution root was replaced during setup")
        if directory_entry_exists(parent_anchor, side_dir.name):
            raise ValueError(
                f"eval execution directory already exists: {side_dir}"
            )
        if parent_anchor.descriptor is None:
            (parent_anchor.path / side_dir.name).mkdir(mode=0o755)
        else:
            os.mkdir(
                side_dir.name,
                mode=0o755,
                dir_fd=parent_anchor.descriptor,
            )
        if not anchored_namespace_matches(parent_anchor):
            raise ValueError("eval execution root was replaced during setup")
    finally:
        close_anchored_directory(parent_anchor)
    # Capture immutable source bytes in memory. This keeps the eval definition
    # private, derives the service and provenance from the same bytes, and
    # avoids a TemporaryDirectory cleanup that a retained agent descendant
    # could redirect to a replacement victim.
    fixture_snapshot = capture_source_tree(case.fixture_dir)
    definition = snapshot_definition_provenance(case, fixture_snapshot)
    require_collected_definition(case, definition)
    fixture_tree_digest = fixture_snapshot.tree_sha256
    materialize_fixture_workspace(
        fixture_snapshot,
        side_dir / "service",
        eval_inputs=case.eval_inputs,
    )

    target = skill_dir or repo_root / "skills" / case.skill
    skill_source_snapshot = capture_source_tree(target)
    if skill_source_snapshot.file_bytes(Path("SKILL.md")) is None:
        raise FileNotFoundError(f"missing skill source: {target / 'SKILL.md'}")
    references = repo_root / "skills" / "references"
    references_snapshot = (
        capture_source_tree(references) if references.is_dir() else None
    )
    companion_source_snapshots: list[tuple[str, SourceTreeSnapshot]] = []
    for name in SKILL_COMPANIONS.get(case.skill, ()):
        companion_source = target.parent / name
        companion_snapshot = capture_source_tree(companion_source)
        if companion_snapshot.file_bytes(Path("SKILL.md")) is None:
            raise FileNotFoundError(
                f"missing companion skill source: {companion_source / 'SKILL.md'}"
            )
        companion_source_snapshots.append((name, companion_snapshot))

    staged_skill_path: str | None = None
    companion_skills: list[CompanionSkillInputSnapshot] = []
    if side == "with_skill":
        skills_dir = side_dir / ".agents" / "skills"
        skills_dir.mkdir(parents=True)
        skill_snapshot = skills_dir / target.name
        materialize_source_tree(skill_source_snapshot, skill_snapshot)
        skill_tree_digest = skill_source_snapshot.tree_sha256
        staged_skill_path = str(
            Path(os.path.abspath(skill_snapshot / "SKILL.md"))
        )

        shared_references_tree_digest: str | None = None
        if references_snapshot is not None:
            staged_references = skills_dir / "references"
            materialize_source_tree(references_snapshot, staged_references)
            shared_references_tree_digest = references_snapshot.tree_sha256
        for name, companion_snapshot in companion_source_snapshots:
            staged_companion = skills_dir / name
            materialize_source_tree(companion_snapshot, staged_companion)
            companion_skills.append(
                CompanionSkillInputSnapshot(
                    name=name,
                    source_path=str(
                        Path(os.path.abspath(companion_snapshot.source))
                    ),
                    tree_sha256=companion_snapshot.tree_sha256,
                    staged_skill_path=str(
                        Path(os.path.abspath(staged_companion / "SKILL.md"))
                    ),
                )
            )
    else:
        # Baseline sides bind the exact compared bytes without materializing
        # those instructions anywhere the baseline agent can discover.
        skill_tree_digest = skill_source_snapshot.tree_sha256
        shared_references_tree_digest = (
            None
            if references_snapshot is None
            else references_snapshot.tree_sha256
        )
        companion_skills.extend(
            CompanionSkillInputSnapshot(
                name=name,
                source_path=str(
                    Path(os.path.abspath(companion_snapshot.source))
                ),
                tree_sha256=companion_snapshot.tree_sha256,
                staged_skill_path=None,
            )
            for name, companion_snapshot in companion_source_snapshots
        )

    return WorkspaceInputSnapshot(
        fixture_path=str(Path(os.path.abspath(case.fixture_dir))),
        fixture_tree_sha256=fixture_tree_digest,
        skill_path=str(Path(os.path.abspath(target))),
        skill_tree_sha256=skill_tree_digest,
        staged_skill_path=staged_skill_path,
        shared_references_path=str(Path(os.path.abspath(references))),
        shared_references_tree_sha256=shared_references_tree_digest,
        definition_path=definition["path"],
        definition_exists=bool(definition["exists"]),
        definition_sha256=definition["sha256"],
        companion_skills=tuple(companion_skills),
    )


def snapshot_definition_provenance(
    case: EvalCase,
    fixture_snapshot: SourceTreeSnapshot,
) -> dict[str, object]:
    """Hash the definition bytes from the same fixture snapshot used by a side."""

    if case.definition_path is None:
        return {"path": None, "exists": False, "sha256": None}
    if case.fixture_dir is None:
        raise ValueError(f"case {case.id} has no fixture_dir")
    definition_path = Path(os.path.abspath(case.definition_path))
    fixture_path = Path(os.path.abspath(case.fixture_dir))
    try:
        relative = definition_path.relative_to(fixture_path)
    except ValueError:
        return file_provenance(definition_path)
    definition_bytes = fixture_snapshot.file_bytes(relative)
    if definition_bytes is None:
        return {
            "path": str(definition_path.resolve()),
            "exists": False,
            "sha256": None,
        }
    return {
        "path": str(definition_path.resolve()),
        "exists": True,
        "sha256": hashlib.sha256(definition_bytes).hexdigest(),
    }


def snapshot_source_tree(source: Path, destination: Path) -> None:
    """Copy one immutable in-memory source capture to a new directory."""

    materialize_source_tree(capture_source_tree(source), destination)


def capture_source_tree(source: Path) -> SourceTreeSnapshot:
    """Capture one no-link source tree without a cleanup-sensitive temp path."""

    source = Path(os.path.abspath(source))
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"snapshot source must be a real directory: {source}")
    entries: list[SourceTreeEntry] = []
    digest = hashlib.sha256()
    if not descriptor_operations_supported():
        source_identity = directory_identity(source)
        capture_source_tree_portable(
            source,
            Path(),
            entries,
            digest,
        )
        require_directory_identity(
            source, source_identity, "snapshot source directory"
        )
    else:
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        source_descriptor = os.open(source, directory_flags)
        source_identity = descriptor_identity(source_descriptor)
        try:
            capture_source_tree_fd(
                source_descriptor,
                Path(),
                entries,
                digest,
            )
        finally:
            os.close(source_descriptor)
        require_directory_identity(
            source, source_identity, "snapshot source directory"
        )
    return SourceTreeSnapshot(
        source=source,
        entries=tuple(entries),
        tree_sha256=digest.hexdigest(),
    )


def captured_tree_digest_entry(
    digest: DigestWriter,
    relative: Path,
    kind: bytes,
    content: bytes | None = None,
) -> None:
    digest.update(relative.as_posix().encode("utf-8"))
    digest.update(b"\0")
    digest.update(kind)
    digest.update(b"\0")
    if content is not None:
        digest.update(content)
    digest.update(b"\0")


def capture_source_tree_fd(
    source_descriptor: int,
    prefix: Path,
    entries: list[SourceTreeEntry],
    digest: DigestWriter,
) -> None:
    """Capture stable bytes recursively through retained directory fds."""

    names = sorted(os.listdir(source_descriptor))
    statuses = {
        name: os.stat(name, dir_fd=source_descriptor, follow_symlinks=False)
        for name in names
    }
    for name, details in statuses.items():
        if path_is_link_or_reparse(details):
            raise ValueError(
                f"provenance source tree must not contain links: {prefix / name}"
            )
        if not stat.S_ISDIR(details.st_mode) and not stat.S_ISREG(details.st_mode):
            raise ValueError(
                f"unsupported provenance source tree entry: {prefix / name}"
            )

    retained_directories: list[tuple[str, os.stat_result]] = []
    for name, details in statuses.items():
        if not stat.S_ISDIR(details.st_mode) or name in HASH_IGNORED_NAMES:
            continue
        relative = prefix / name
        entries.append(
            SourceTreeEntry(relative, details.st_mode & 0o777, None)
        )
        captured_tree_digest_entry(digest, relative, b"dir")
        retained_directories.append((name, details))

    for name, details in statuses.items():
        if not stat.S_ISREG(details.st_mode) or name.endswith(
            HASH_IGNORED_SUFFIXES
        ):
            continue
        relative = prefix / name
        content = read_stable_source_file_fd(
            source_descriptor,
            name,
            details,
            relative,
        )
        entries.append(
            SourceTreeEntry(relative, details.st_mode & 0o777, content)
        )
        captured_tree_digest_entry(digest, relative, b"file", content)

    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    for name, before in retained_directories:
        child = os.open(name, directory_flags, dir_fd=source_descriptor)
        try:
            opened = os.fstat(child)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise ValueError(f"snapshot source changed before read: {prefix / name}")
            capture_source_tree_fd(child, prefix / name, entries, digest)
            after = os.stat(
                name,
                dir_fd=source_descriptor,
                follow_symlinks=False,
            )
            if (
                path_is_link_or_reparse(after)
                or not stat.S_ISDIR(after.st_mode)
                or (after.st_dev, after.st_ino)
                != (opened.st_dev, opened.st_ino)
            ):
                raise ValueError(
                    f"snapshot source changed during read: {prefix / name}"
                )
        finally:
            os.close(child)
    if sorted(os.listdir(source_descriptor)) != names:
        raise ValueError(f"snapshot source directory changed during read: {prefix}")


def read_stable_source_file_fd(
    source_descriptor: int,
    name: str,
    before: os.stat_result,
    relative: Path,
) -> bytes:
    descriptor = os.open(
        name,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0),
        dir_fd=source_descriptor,
    )
    try:
        opened = os.fstat(descriptor)
        if (
            path_is_link_or_reparse(opened)
            or not stat.S_ISREG(opened.st_mode)
            or regular_file_stability(opened) != regular_file_stability(before)
        ):
            raise ValueError(f"snapshot source changed before read: {relative}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        current = os.stat(
            name,
            dir_fd=source_descriptor,
            follow_symlinks=False,
        )
        if (
            regular_file_stability(opened) != regular_file_stability(after)
            or path_is_link_or_reparse(current)
            or not stat.S_ISREG(current.st_mode)
            or regular_file_stability(current) != regular_file_stability(after)
        ):
            raise ValueError(f"snapshot source changed during read: {relative}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def capture_source_tree_portable(
    source: Path,
    prefix: Path,
    entries: list[SourceTreeEntry],
    digest: DigestWriter,
) -> None:
    """Best available stable source capture without directory-relative APIs."""

    source_identity = directory_identity(source)
    names = sorted(entry.name for entry in os.scandir(source))
    statuses = {name: os.lstat(source / name) for name in names}
    for name, details in statuses.items():
        if path_is_link_or_reparse(details):
            raise ValueError(
                f"provenance source tree must not contain links: {source / name}"
            )
        if not stat.S_ISDIR(details.st_mode) and not stat.S_ISREG(details.st_mode):
            raise ValueError(
                f"unsupported provenance source tree entry: {source / name}"
            )

    for name, details in statuses.items():
        if not stat.S_ISDIR(details.st_mode) or name in HASH_IGNORED_NAMES:
            continue
        relative = prefix / name
        entries.append(
            SourceTreeEntry(relative, details.st_mode & 0o777, None)
        )
        captured_tree_digest_entry(digest, relative, b"dir")

    for name, details in statuses.items():
        if not stat.S_ISREG(details.st_mode) or name.endswith(
            HASH_IGNORED_SUFFIXES
        ):
            continue
        relative = prefix / name
        content = read_stable_source_file_portable(
            source / name,
            details,
            relative,
        )
        entries.append(
            SourceTreeEntry(relative, details.st_mode & 0o777, content)
        )
        captured_tree_digest_entry(digest, relative, b"file", content)

    for name, details in statuses.items():
        if not stat.S_ISDIR(details.st_mode) or name in HASH_IGNORED_NAMES:
            continue
        capture_source_tree_portable(
            source / name,
            prefix / name,
            entries,
            digest,
        )
    if sorted(entry.name for entry in os.scandir(source)) != names:
        raise ValueError(f"snapshot source directory changed during read: {source}")
    require_directory_identity(source, source_identity, "snapshot source directory")


def read_stable_source_file_portable(
    path: Path,
    before: os.stat_result,
    relative: Path,
) -> bytes:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        opened = os.fstat(descriptor)
        if (
            path_is_link_or_reparse(opened)
            or not stat.S_ISREG(opened.st_mode)
            or regular_file_stability(opened) != regular_file_stability(before)
        ):
            raise ValueError(f"snapshot source changed before read: {relative}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        current = os.lstat(path)
        if (
            regular_file_stability(opened) != regular_file_stability(after)
            or path_is_link_or_reparse(current)
            or not stat.S_ISREG(current.st_mode)
            or regular_file_stability(current) != regular_file_stability(after)
        ):
            raise ValueError(f"snapshot source changed during read: {relative}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def materialize_source_tree(
    snapshot: SourceTreeSnapshot,
    destination: Path,
    *,
    entries: tuple[SourceTreeEntry, ...] | None = None,
) -> None:
    """Materialize captured regular bytes without later pathname cleanup."""

    destination = Path(os.path.abspath(destination))
    if os.path.lexists(destination):
        raise ValueError(f"snapshot destination already exists: {destination}")
    destination.mkdir(mode=0o755)
    selected = snapshot.entries if entries is None else entries
    for entry in sorted(
        (entry for entry in selected if entry.content is None),
        key=lambda item: (len(item.relative.parts), item.relative.as_posix()),
    ):
        (destination / entry.relative).mkdir(
            mode=entry.mode,
            parents=True,
            exist_ok=True,
        )
    for entry in sorted(
        (entry for entry in selected if entry.content is not None),
        key=lambda item: item.relative.as_posix(),
    ):
        target = destination / entry.relative
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            target,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            entry.mode,
        )
        try:
            content = entry.content or b""
            offset = 0
            while offset < len(content):
                offset += os.write(descriptor, content[offset:])
        finally:
            os.close(descriptor)


def materialize_fixture_workspace(
    snapshot: SourceTreeSnapshot,
    destination: Path,
    *,
    eval_inputs: list[str] | None = None,
) -> None:
    """Expose only service files and explicit eval inputs to the agent."""

    validate_eval_input_paths(eval_inputs)
    allowed_eval_inputs = {Path(value) for value in eval_inputs or ()}
    if allowed_eval_inputs:
        available_files = {
            entry.relative
            for entry in snapshot.entries
            if entry.content is not None
        }
        missing = sorted(
            path.as_posix()
            for path in allowed_eval_inputs
            if path not in available_files
        )
        if missing:
            raise ValueError(
                "eval_inputs entries must name fixture files: "
                + ", ".join(missing)
            )

    selected = tuple(
        entry
        for entry in snapshot.entries
        if fixture_entry_is_visible(entry.relative)
        or (
            entry.relative.parts[:2] == ("eval", "inputs")
            and entry.relative in allowed_eval_inputs
        )
    )
    materialize_source_tree(snapshot, destination, entries=selected)


def fixture_entry_is_visible(relative: Path) -> bool:
    if not relative.parts or relative.parts[0] == "eval":
        return False
    return not any(
        part in WORKSPACE_IGNORED_NAMES
        or part.endswith(WORKSPACE_IGNORED_SUFFIXES)
        or part.endswith("_eval.json")
        for part in relative.parts
    )


def copy_snapshot_tree_fd(
    source_descriptor: int,
    destination_descriptor: int,
) -> None:
    """Recursively snapshot regular files through retained directory fds."""

    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    for name in sorted(os.listdir(source_descriptor)):
        details = os.stat(name, dir_fd=source_descriptor, follow_symlinks=False)
        if stat.S_ISLNK(details.st_mode):
            raise ValueError(
                f"provenance source tree must not contain symlinks: {name}"
            )
        if stat.S_ISDIR(details.st_mode):
            if name in HASH_IGNORED_NAMES:
                continue
            os.mkdir(
                name,
                mode=details.st_mode & 0o777,
                dir_fd=destination_descriptor,
            )
            source_child = os.open(
                name, directory_flags, dir_fd=source_descriptor
            )
            destination_child = os.open(
                name, directory_flags, dir_fd=destination_descriptor
            )
            try:
                copy_snapshot_tree_fd(source_child, destination_child)
            finally:
                os.close(source_child)
                os.close(destination_child)
            continue
        if stat.S_ISREG(details.st_mode):
            if name.endswith(HASH_IGNORED_SUFFIXES):
                continue
            copy_regular_file_fd(
                source_descriptor,
                destination_descriptor,
                name,
                details.st_mode,
            )
            continue
        raise ValueError(f"unsupported provenance source tree entry: {name}")


def copy_snapshot_tree_portable(source: Path, destination: Path) -> None:
    """Best available no-link snapshot without directory-relative APIs."""

    for entry in sorted(os.scandir(source), key=lambda item: item.name):
        name = entry.name
        source_path = source / name
        destination_path = destination / name
        details = os.lstat(source_path)
        if path_is_link_or_reparse(details):
            raise ValueError(
                f"provenance source tree must not contain links: {source_path}"
            )
        if stat.S_ISDIR(details.st_mode):
            if name in HASH_IGNORED_NAMES:
                continue
            destination_path.mkdir(mode=details.st_mode & 0o777)
            copy_snapshot_tree_portable(source_path, destination_path)
            continue
        if stat.S_ISREG(details.st_mode):
            if name.endswith(HASH_IGNORED_SUFFIXES):
                continue
            copy_regular_file_portable(
                source_path, destination_path, details.st_mode
            )
            continue
        raise ValueError(
            f"unsupported provenance source tree entry: {source_path}"
        )
