from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .ab import side_prompt
from .backends import (
    AgentBackend,
    AnchoredDirectory,
    CodexBackend,
    anchored_namespace_matches,
    atomic_text_write,
    ensure_anchored_directory,
    open_anchored_directory,
)
from .definitions import CaseResult, EvalCase, RubricEvalCase, SideResult
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
    config_path: Path | None = None,
    run_configuration: dict[str, object] | None = None,
) -> CaseResult:
    if backend is None:
        backend = CodexBackend()
    run_root_identity = ensure_real_directory(run_root, repo_root, create=True)
    case_root = run_root / "cases" / case.language / case.service / case.prompt_id
    exec_case_root = Path(tempfile.mkdtemp(prefix=f"codex-eval-{case.skill}-{case.language}-{case.service}-{case.prompt_id}-"))
    exec_case_root_identity = directory_identity(exec_case_root)
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
                config_path=config_path,
                run_configuration=run_configuration,
                run_root=run_root,
                run_root_identity=run_root_identity,
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
                config_path=config_path,
                run_configuration=run_configuration,
                run_root=run_root,
                run_root_identity=run_root_identity,
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
        # Code evaluated in this directory is untrusted and can retain a
        # concurrent renamer. There is no portable conditional-rmdir syscall,
        # so deleting by pathname here could delete a replacement victim.
        # The OS temporary-directory lifecycle owns eventual cleanup.
        del exec_case_root_identity


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
) -> SideResult:
    require_directory_identity(run_root, run_root_identity, "eval run root")
    artifact_parent_anchor = open_anchored_directory(
        artifact_dir.parent, run_root, create=True
    )
    if artifact_parent_anchor.boundary_identity != run_root_identity:
        os.close(artifact_parent_anchor.descriptor)
        raise ValueError("eval run root was replaced before artifact setup")
    try:
        if not anchored_namespace_matches(artifact_parent_anchor):
            raise ValueError("eval artifact parent was replaced during setup")
        if directory_entry_exists(
            artifact_parent_anchor.descriptor, artifact_dir.name
        ):
            raise ValueError(
                f"artifact directory already exists; refusing to replace it: {artifact_dir}"
            )
        exec_root_identity = directory_identity(exec_dir.parent)
        prepare_side_workspace(
            repo_root,
            case,
            side,
            exec_dir,
            skill_dir,
            exec_root_identity=exec_root_identity,
        )
        exec_anchor = open_anchored_directory(exec_dir, exec_dir.parent)
        if exec_anchor.boundary_identity != exec_root_identity:
            os.close(exec_anchor.descriptor)
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
                run_root=run_root,
                run_root_identity=run_root_identity,
                exec_anchor=exec_anchor,
                artifact_parent_anchor=artifact_parent_anchor,
            )
        finally:
            os.close(exec_anchor.descriptor)
    finally:
        os.close(artifact_parent_anchor.descriptor)


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
    trace_bytes = read_regular_from_directory(
        exec_anchor.descriptor, trace_relative
    )
    final_bytes = read_regular_from_directory(
        exec_anchor.descriptor, final_relative
    )
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
            if directory_entry_exists(
                exec_anchor.descriptor, rubric_trace_relative.name
            ):
                try:
                    rubric_trace_bytes = read_regular_from_directory(
                        exec_anchor.descriptor, rubric_trace_relative
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
        read_regular_from_directory(exec_anchor.descriptor, relative)

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
    if directory_entry_exists(
        artifact_parent_anchor.descriptor, artifact_dir.name
    ):
        raise ValueError(
            f"artifact directory appeared during agent execution: {artifact_dir}"
        )
    os.mkdir(
        artifact_dir.name,
        mode=0o755,
        dir_fd=artifact_parent_anchor.descriptor,
    )
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    artifact_descriptor = os.open(
        artifact_dir.name,
        directory_flags,
        dir_fd=artifact_parent_anchor.descriptor,
    )
    artifact_dir_identity = descriptor_identity(artifact_descriptor)
    artifact_anchor = AnchoredDirectory(
        descriptor=artifact_descriptor,
        boundary=artifact_parent_anchor.boundary,
        relative_parts=(
            *artifact_parent_anchor.relative_parts,
            artifact_dir.name,
        ),
        boundary_identity=artifact_parent_anchor.boundary_identity,
        parent_identity=artifact_dir_identity,
    )
    try:
        copy_artifact_tree_fd(exec_anchor.descriptor, artifact_descriptor)
        if not anchored_namespace_matches(exec_anchor):
            raise ValueError("eval execution directory was replaced during capture")
        if not anchored_namespace_matches(artifact_anchor):
            raise ValueError("eval artifact directory was replaced during capture")
        if read_regular_from_directory(
            artifact_descriptor, trace_relative
        ) != trace_bytes:
            raise ValueError("captured trace differs from the authenticated agent output")
        if read_regular_from_directory(
            artifact_descriptor, final_relative
        ) != final_bytes:
            raise ValueError(
                "captured final message differs from the authenticated agent output"
            )
        if read_regular_from_directory(
            artifact_descriptor, Path(PROVENANCE_FILE)
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
        os.close(artifact_descriptor)


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
        os.close(anchor.descriptor)


def directory_entry_exists(descriptor: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def descriptor_identity(descriptor: int) -> tuple[int, int]:
    details = os.fstat(descriptor)
    if not stat.S_ISDIR(details.st_mode):
        raise ValueError("expected an open directory descriptor")
    return details.st_dev, details.st_ino


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


def read_regular_from_directory(descriptor: int, relative: Path) -> bytes:
    current = os.dup(descriptor)
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
    descriptor, name = tempfile.mkstemp(prefix="codex-eval-trace-", suffix=".jsonl")
    path = Path(name)
    try:
        offset = 0
        while offset < len(value):
            offset += os.write(descriptor, value[offset:])
        os.close(descriptor)
        descriptor = -1
        return backend.parse_trace(path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        path.unlink(missing_ok=True)


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
        if name in ignored or (root and name == "summary.json"):
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


def directory_identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    if not stat.S_ISDIR(details.st_mode) or path.is_symlink():
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
) -> dict[str, object]:
    if case.fixture_dir is None:
        raise ValueError(f"case {case.id} has no fixture_dir")
    validate_fixture_tree(case.fixture_dir)
    selected_skill = skill_dir or repo_root / "skills" / case.skill
    shared_references = repo_root / "skills" / "references"
    harness_source = Path(__file__).resolve().parent
    task_sha256 = hashlib.sha256(case.task.encode("utf-8")).hexdigest()
    case_contract = case.model_dump(
        mode="json",
        exclude={"definition_path", "fixture_dir"},
    )
    normalized_run_configuration = dict(run_configuration or {})
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
            "task_sha256": task_sha256,
            "contract_sha256": canonical_sha256(case_contract),
        },
        "definition": file_provenance(case.definition_path),
        "config": file_provenance(config_path),
        "run_configuration": {
            "value": normalized_run_configuration,
            "sha256": canonical_sha256(normalized_run_configuration),
        },
        "fixture": {
            "path": str(case.fixture_dir.resolve()),
            "tree_sha256": tree_sha256(case.fixture_dir),
        },
        "skill": {
            "path": str(selected_skill.resolve()),
            "tree_sha256": tree_sha256(selected_skill),
        },
        "shared_references": {
            "path": str(shared_references.resolve()),
            "tree_sha256": (
                tree_sha256(shared_references)
                if shared_references.is_dir()
                else None
            ),
        },
        "harness": {
            "path": str(harness_source),
            "tree_sha256": tree_sha256(harness_source),
        },
    }


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def prepare_side_workspace(
    repo_root: Path,
    case: EvalCase,
    side: str,
    side_dir: Path,
    skill_dir: Path | None = None,
    *,
    exec_root_identity: tuple[int, int] | None = None,
) -> None:
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
        if directory_entry_exists(parent_anchor.descriptor, side_dir.name):
            raise ValueError(
                f"eval execution directory already exists: {side_dir}"
            )
        os.mkdir(side_dir.name, mode=0o755, dir_fd=parent_anchor.descriptor)
        if not anchored_namespace_matches(parent_anchor):
            raise ValueError("eval execution root was replaced during setup")
    finally:
        os.close(parent_anchor.descriptor)
    shutil.copytree(
        case.fixture_dir,
        side_dir / "service",
        ignore=workspace_ignore(case.fixture_dir),
    )
    copy_eval_inputs(case.fixture_dir, side_dir / "service")
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
