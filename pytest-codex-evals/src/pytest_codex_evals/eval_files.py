from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path

from .definitions.base import validate_eval_input_paths


EVAL_ROLE_DIRS = {
    "qual": "rubric",
    "rubric": "rubric",
    "runtime": "runtime",
    "sanity": "sanity",
}

FIXTURE_GENERATED_PATTERNS = (
    ".observe",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "*.pyc",
    "uv.lock",
    "*.db",
    "*_eval.json",
    ".DS_Store",
)
FIXTURE_WORKSPACE_IGNORE_PATTERNS = ("eval", *FIXTURE_GENERATED_PATTERNS)
RUNTIME_REPOSITORY_GENERATED_PATTERNS = (
    ".observe",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "*.pyc",
    "*.db",
    ".DS_Store",
    ".workspace",
    "node_modules",
    "dist",
    "build",
    ".release",
    "coverage",
    ".cache",
    ".git",
    "_skills",
)
RUNTIME_OBSERVER_GENERATED_PATHS = (
    "obstudio",
    "build-client",
    "internal/web/static/assets",
    "client/public/assets",
)


@dataclass(frozen=True)
class EvalFileLayout:
    path: Path
    fixture_dir: Path
    language: str
    service: str
    eval_name: str
    role: str | None
    default_id: str


def is_eval_file(path: Path) -> bool:
    return eval_file_layout(path) is not None


def iter_eval_files(eval_root: Path) -> list[Path]:
    if eval_root.is_symlink():
        raise ValueError(f"eval source root must not be a symlink: {eval_root}")
    resolved_root = eval_root.resolve()
    files = []
    for directory, dirnames, filenames in os.walk(eval_root, followlinks=False):
        current = Path(directory)
        kept_directories = []
        for name in sorted(dirnames):
            path = current / name
            if fixture_name_matches(name, FIXTURE_GENERATED_PATTERNS):
                continue
            if path.is_symlink():
                raise ValueError(f"eval source input must not be a symlink: {path}")
            kept_directories.append(name)
        dirnames[:] = kept_directories
        for name in sorted(filenames):
            path = current / name
            if not is_eval_file(path):
                continue
            source = regular_source_file(path)
            if source is None:
                raise ValueError(f"eval source input is missing: {path}")
            try:
                source.resolve().relative_to(resolved_root)
            except ValueError as exc:
                raise ValueError(f"eval source input escapes its root: {path}") from exc
            files.append(source)
    return sorted(files)


def eval_file_layout(path: Path) -> EvalFileLayout | None:
    if path.suffix != ".json":
        return None
    if path.parent.parent.name == "eval" and path.parent.name in EVAL_ROLE_DIRS:
        return nested_eval_file_layout(path)
    return None


def nested_eval_file_layout(path: Path) -> EvalFileLayout:
    fixture_dir = path.parents[2]
    language = fixture_dir.parent.name
    service = fixture_dir.name
    role_dir = path.parent.name
    eval_name = path.stem
    return EvalFileLayout(
        path=path,
        fixture_dir=fixture_dir,
        language=language,
        service=service,
        eval_name=eval_name,
        role=EVAL_ROLE_DIRS[role_dir],
        default_id=f"{language}/{service}/{role_dir}/{eval_name}",
    )


def fixture_workspace_ignore(_directory: str, names: list[str]) -> set[str]:
    """Apply the same generated-input policy used by source provenance."""

    return {
        name
        for name in names
        if fixture_name_matches(name, FIXTURE_WORKSPACE_IGNORE_PATTERNS)
    }


def skill_workspace_ignore(_directory: str, names: list[str]) -> set[str]:
    """Exclude the same generated entries omitted from skill provenance."""

    return {
        name
        for name in names
        if fixture_name_matches(name, FIXTURE_GENERATED_PATTERNS)
    }


def staged_fixture_source_files(fixture_dir: Path) -> list[Path]:
    """Return regular files copied into an eval side's service workspace."""

    return source_tree_files(fixture_dir, FIXTURE_WORKSPACE_IGNORE_PATTERNS)


def runtime_definition_asset_files(definition_path: Path) -> list[Path]:
    """Return non-definition assets beside a runtime eval definition."""

    return [
        path
        for path in source_tree_files(
            definition_path.parent,
            FIXTURE_GENERATED_PATTERNS,
        )
        if not is_eval_file(path)
    ]


def shared_runtime_source_files(eval_root: Path) -> list[Path]:
    """Return shared Docker/runtime inputs consumed by runtime eval fixtures."""

    return source_tree_files(eval_root / "runtime", FIXTURE_GENERATED_PATTERNS)


def shared_skill_reference_source_files(repo_root: Path) -> list[Path]:
    """Return the shared references exposed to every with-skill eval side."""

    return source_tree_files(
        repo_root / "skills" / "references",
        FIXTURE_GENERATED_PATTERNS,
    )


def staged_skill_source_files(skill_root: Path) -> list[Path]:
    """Return canonical skill inputs after rejecting unmanifested symlinks."""

    return source_tree_files(
        skill_root,
        FIXTURE_GENERATED_PATTERNS,
    )


def regular_source_file(path: Path) -> Path | None:
    """Return an optional singleton provenance input, rejecting non-regular paths."""

    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(
            f"eval source input must be a regular file, not a symlink: {path}"
        )
    return path if path.is_file() else None


def runtime_repository_source_files(repo_root: Path) -> list[Path]:
    """Return canonical repository trees copied by the runtime Observer image."""

    files = source_tree_files(
        repo_root / "observer",
        RUNTIME_REPOSITORY_GENERATED_PATTERNS,
        ignore_relative_paths=RUNTIME_OBSERVER_GENERATED_PATHS,
    )
    files.extend(
        source_tree_files(
            repo_root / "skills",
            RUNTIME_REPOSITORY_GENERATED_PATTERNS,
        )
    )
    examples = repo_root / "docs" / "examples.md"
    if examples.is_symlink() or (examples.exists() and not examples.is_file()):
        raise ValueError(
            f"eval source input must be a regular file, not a symlink: {examples}"
        )
    if examples.is_file():
        files.append(examples)
    return files


def fixture_eval_input_sources(
    fixture_dir: Path,
    eval_inputs: list[str] | None,
) -> list[tuple[Path, Path]]:
    """Resolve prompt-approved eval seeds to safe regular fixture files."""

    validate_eval_input_paths(eval_inputs)
    if not eval_inputs:
        return []
    input_root = fixture_dir / "eval" / "inputs"
    if (
        fixture_dir.is_symlink()
        or (fixture_dir / "eval").is_symlink()
        or input_root.is_symlink()
    ):
        raise ValueError(f"eval input directory must not be a symlink: {input_root}")
    resolved_input_root = input_root.resolve()
    sources: list[tuple[Path, Path]] = []
    for value in eval_inputs:
        relative = Path(value)
        source = fixture_dir / relative
        if source.is_symlink() or not source.is_file():
            raise ValueError(
                f"eval_inputs entry must name a regular fixture file: {value}"
            )
        try:
            source.resolve().relative_to(resolved_input_root)
        except ValueError as exc:
            raise ValueError(
                f"eval_inputs entry resolves outside eval/inputs: {value}"
            ) from exc
        sources.append((relative, source))
    return sources


def source_tree_files(
    root: Path,
    ignore_patterns: tuple[str, ...],
    *,
    ignore_relative_paths: tuple[str, ...] = (),
) -> list[Path]:
    """Walk an input tree deterministically and reject unmanifested symlinks."""

    if not root.exists():
        return []
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"eval source tree must be a regular directory: {root}")
    ignored_paths = {Path(value).as_posix() for value in ignore_relative_paths}
    files: list[Path] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(directory)
        kept_directories: list[str] = []
        for name in sorted(dirnames):
            path = current / name
            relative = path.relative_to(root).as_posix()
            if (
                fixture_name_matches(name, ignore_patterns)
                or relative in ignored_paths
            ):
                continue
            if path.is_symlink():
                raise ValueError(f"eval source input must not be a symlink: {path}")
            kept_directories.append(name)
        dirnames[:] = kept_directories
        for name in sorted(filenames):
            path = current / name
            relative = path.relative_to(root).as_posix()
            if (
                fixture_name_matches(name, ignore_patterns)
                or relative in ignored_paths
            ):
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError(
                    f"eval source input must be a regular file, not a symlink: {path}"
                )
            files.append(path)
    return files


def fixture_name_matches(name: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)
