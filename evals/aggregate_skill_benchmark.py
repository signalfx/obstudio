#!/usr/bin/env python3
"""Aggregate repeated before/after OTel skill benchmark artifacts.

The benchmark runner stores one copied pytest-codex-evals run under
``<root>/<side>/<skill>/runN``.  This script reads the preserved ``summary.json``
and report artifacts, reruns the applicable report validators, and compares
both the stable Markdown reader projections produced by
``compare_otel_reports.py`` and the bound canonical JSON report flows.

Skill-load authentication intentionally accepts only bounded POSIX shell read
forms. Live model execution and aggregation therefore require POSIX; unsupported
platforms fail closed instead of treating command text as proof.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import itertools
import json
import os
import re
import shlex
import stat
import statistics
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, TypeGuard

from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

PYTEST_EVALS_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "pytest-codex-evals"
    / "src"
)
if str(PYTEST_EVALS_SOURCE) not in sys.path:
    sys.path.insert(0, str(PYTEST_EVALS_SOURCE))

from compare_otel_reports import CANONICALIZERS
from pytest_codex_evals.backends import (
    AnchoredDirectory,
    anchored_namespace_matches,
    atomic_text_write,
    close_anchored_directory,
    ensure_anchored_directory,
    open_anchored_directory,
    path_directory_identity,
    path_is_link_or_reparse,
    read_anchored_regular_bytes,
)
from pytest_codex_evals.eval_contracts import (
    case_contract_sha256,
    case_from_definition,
    load_eval_definition,
)


SIDES = ("before", "after")
SKILL_REPORTS = {
    "audit": "otel.md",
    "instrument": "otel-instrumentation.md",
    "verify": "otel-verify.md",
}
METRICS = ("agent_duration_seconds", "command_count", "agent_tokens")
SKILL_NAMES = {
    "audit": "otel-audit",
    "instrument": "otel-instrument",
    "verify": "otel-verify",
}
CANONICAL_JSON_REPORTS = {
    "audit": "otel-audit.json",
    "instrument": "otel-instrumentation.json",
    "verify": "otel-verify.json",
}
CANONICAL_HTML_REPORTS = {
    "audit": "otel.html",
    "instrument": "otel-instrumentation.html",
    "verify": "otel-instrumentation.html",
}
CANONICAL_FLOW_REPORTS = {
    "audit": ("otel-audit.json",),
    "instrument": (
        "otel-audit.json",
        "otel-selection.json",
        "otel-instrumentation.json",
        "otel-verify.json",
    ),
    "verify": (
        "otel-audit.json",
        "otel-selection.json",
        "otel-instrumentation.json",
        "otel-verify.json",
    ),
}
PROVENANCE_FILE = ".codex-eval-provenance.json"
CAPTURE_MANIFEST_FILE = ".codex-eval-capture.json"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
HASH_IGNORED_NAMES = {".observe", ".venv", "__pycache__", "target"}
HASH_IGNORED_SUFFIXES = (".db", ".pyc")
SKILL_READ_COMMANDS = {"cat", "head", "sed", "tail"}
SHELL_COMMANDS = {"bash", "dash", "sh", "zsh"}
TRUSTED_COMMAND_DIRECTORIES = {Path("/bin"), Path("/usr/bin")}


def skill_trace_platform_error(platform_name: str | None = None) -> str | None:
    """Return a deterministic diagnostic for unsupported trace platforms."""

    platform_name = os.name if platform_name is None else platform_name
    if platform_name == "posix":
        return None
    return (
        "unsupported skill-load trace platform: before/after aggregation "
        "requires POSIX execution and POSIX aggregation"
    )


@dataclass
class RunArtifact:
    side: str
    skill: str
    run: str
    run_dir: Path
    summary_path: Path | None = None
    report_path: Path | None = None
    summary: dict[str, Any] | None = None
    projection: dict[str, object] | None = None
    facts: set[str] | None = None
    canonical_json_projection: dict[str, object] | None = None
    canonical_json_facts: set[str] | None = None
    validators: list[dict[str, object]] | None = None
    provenance: dict[str, object] | None = None
    captured_files: dict[str, bytes] | None = None
    task: str = ""
    load_errors: list[str] | None = None

    def errors(self) -> list[str]:
        return self.load_errors if self.load_errors is not None else []

    def validator_results(self) -> list[dict[str, object]]:
        return self.validators if self.validators is not None else []


@dataclass(frozen=True)
class FileDigestSnapshot:
    """Content identity captured by one authenticated file read."""

    exists: bool
    sha256: str | None


@dataclass(frozen=True)
class SkillTreeSnapshot:
    """Canonical skill bytes and tree identity captured in one traversal."""

    root: Path
    skill_path: Path
    skill_bytes: bytes
    tree_sha256: str


def round_number(value: float) -> float:
    return round(value, 3)


def metric_summary(values: Iterable[float | int]) -> dict[str, float | int | None]:
    collected = list(values)
    if not collected:
        return {"count": 0, "min": None, "median": None, "mean": None, "max": None}
    return {
        "count": len(collected),
        "min": round_number(float(min(collected))),
        "median": round_number(float(statistics.median(collected))),
        "mean": round_number(float(statistics.fmean(collected))),
        "max": round_number(float(max(collected))),
    }


def metric_delta(before: dict[str, float | int | None], after: dict[str, float | int | None]) -> dict[str, float | None]:
    before_median = before["median"]
    after_median = after["median"]
    if before_median is None or after_median is None:
        return {"median_delta": None, "change_percent": None, "improvement_percent": None}
    delta = float(after_median) - float(before_median)
    if float(before_median) == 0:
        change = None
        improvement = None
    else:
        change = delta / float(before_median) * 100
        improvement = -change
    return {
        "median_delta": round_number(delta),
        "change_percent": None if change is None else round_number(change),
        "improvement_percent": None if improvement is None else round_number(improvement),
    }


def metric_value(artifact: RunArtifact, metric: str) -> object:
    if artifact.summary is None:
        return None
    return artifact.summary.get(metric)


def is_numeric_metric(value: object) -> TypeGuard[int | float]:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def paired_metric_analysis(
    before: list[RunArtifact],
    after: list[RunArtifact],
    metric: str,
) -> dict[str, object]:
    """Compare same-name runs while retaining independent side summaries.

    Invalid values remain visible in the per-run records and are excluded from
    arithmetic. ``run_payload`` reports the corresponding completeness error.
    Percent changes are undefined when a paired baseline is zero, so those
    entries are ``None`` and are excluded from the percent summaries.
    """

    before_by_run = {artifact.run: artifact for artifact in before}
    after_by_run = {artifact.run: artifact for artifact in after}
    pairs: list[dict[str, object]] = []
    deltas: list[float] = []
    changes: list[float] = []
    improvements: list[float] = []
    for run in sorted(before_by_run.keys() & after_by_run.keys()):
        before_value = metric_value(before_by_run[run], metric)
        after_value = metric_value(after_by_run[run], metric)
        delta = None
        change = None
        improvement = None
        if is_numeric_metric(before_value) and is_numeric_metric(after_value):
            delta = float(after_value) - float(before_value)
            deltas.append(delta)
            if float(before_value) != 0:
                change = delta / float(before_value) * 100
                improvement = -change
                changes.append(change)
                improvements.append(improvement)
        pairs.append(
            {
                "run": run,
                "before": before_value,
                "after": after_value,
                "delta": None if delta is None else round_number(delta),
                "change_percent": None if change is None else round_number(change),
                "improvement_percent": (
                    None if improvement is None else round_number(improvement)
                ),
            }
        )

    return {
        "runs": pairs,
        "delta": metric_summary(deltas),
        "change_percent": metric_summary(changes),
        "improvement_percent": metric_summary(improvements),
    }


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def flatten_facts(value: object, path: tuple[str, ...] = ()) -> set[str]:
    """Turn a projection into set-like facts for stable overlap measurement.

    Lists of report rows become one fact per row.  This intentionally ignores
    row order for overlap; exact projection equality still checks heading and
    row order where the canonicalizer preserves it.
    """

    label = ".".join(path) or "$"
    if isinstance(value, dict):
        facts: set[str] = set()
        for key in sorted(value):
            facts.update(flatten_facts(value[key], (*path, str(key))))
        return facts
    if isinstance(value, list):
        return {f"{label}[]={canonical_json(item)}" for item in value}
    return {f"{label}={canonical_json(value)}"}


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    if not union:
        return 1.0
    return round_number(len(left & right) / len(union))


def find_summary(
    run_dir: Path, captured_files: dict[str, bytes]
) -> tuple[Path | None, list[str]]:
    matches = sorted(
        run_dir / relative
        for relative in captured_files
        if relative.endswith("/with_skill/summary.json")
    )
    if len(matches) != 1:
        return None, [f"expected one with_skill/summary.json, found {len(matches)}"]
    return matches[0], []


def load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError(f"artifact must not be a symlink: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def load_json_bytes(value: bytes, label: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError(f"expected JSON object in {label}")
    return parsed


def regular_file_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"artifact must be a regular file: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def regular_file_hash(path: Path) -> str:
    return hashlib.sha256(regular_file_bytes(path)).hexdigest()


def load_capture_manifest(run_dir: Path) -> tuple[dict[str, bytes], list[str]]:
    manifest_path = run_dir / CAPTURE_MANIFEST_FILE
    if not confined_path(manifest_path, run_dir):
        return {}, [f"capture manifest escapes run root or traverses a symlink: {manifest_path}"]
    if manifest_path.is_symlink() or not manifest_path.is_file():
        return {}, [f"missing or unsafe capture manifest: {manifest_path}"]
    try:
        manifest = load_json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {}, [f"failed to read capture manifest: {error}"]
    if manifest.get("schema_version") != 1:
        return {}, ["capture manifest schema is unsupported"]
    entries = manifest.get("files")
    if not isinstance(entries, list):
        return {}, ["capture manifest files must be a list"]

    authenticated: dict[str, bytes] = {}
    errors: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("capture manifest file entry must be an object")
            continue
        value = entry.get("path")
        digest = entry.get("sha256")
        if (
            not isinstance(value, str)
            or not value
            or not isinstance(digest, str)
            or not SHA256_PATTERN.fullmatch(digest)
        ):
            errors.append("capture manifest file entry is invalid")
            continue
        if value in authenticated:
            errors.append(f"capture manifest contains duplicate path: {value}")
            continue
        relative = Path(value)
        path = run_dir / relative
        if relative.is_absolute() or not confined_path(path, run_dir):
            errors.append(f"captured artifact escapes run root or traverses a symlink: {value}")
            continue
        if path.is_symlink() or not path.is_file():
            errors.append(f"captured artifact is missing or unsafe: {value}")
            continue
        try:
            current_bytes = regular_file_bytes(path)
            current_digest = hashlib.sha256(current_bytes).hexdigest()
        except (OSError, ValueError) as error:
            errors.append(f"failed to hash captured artifact {value}: {error}")
            continue
        if current_digest != digest:
            errors.append(f"captured artifact changed after capture: {value}")
            continue
        authenticated[value] = current_bytes
    current_paths, current_errors = current_capture_paths(run_dir)
    errors.extend(current_errors)
    manifest_paths = {
        str(entry.get("path"))
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    added = current_paths - manifest_paths
    missing = manifest_paths - current_paths
    if added:
        errors.append(
            "unsealed artifacts were added after capture: " + ", ".join(sorted(added))
        )
    if missing:
        errors.append(
            "sealed artifacts are missing after capture: " + ", ".join(sorted(missing))
        )
    return authenticated, errors


def current_capture_paths(run_dir: Path) -> tuple[set[str], list[str]]:
    paths: set[str] = set()
    errors: list[str] = []
    for name in ("cases", "results", "runs"):
        root = run_dir / name
        if not root.exists():
            continue
        if root.is_symlink() or not root.is_dir() or not confined_path(root, run_dir):
            errors.append(f"capture artifact root is unsafe: {root}")
            continue
        for directory, dirnames, filenames in os.walk(root, followlinks=False):
            parent = Path(directory)
            retained: list[str] = []
            for directory_name in sorted(dirnames):
                candidate = parent / directory_name
                if directory_name == ".agents":
                    continue
                if candidate.is_symlink() or not confined_path(candidate, run_dir):
                    errors.append(f"capture artifact tree contains a symlink: {candidate}")
                    continue
                retained.append(directory_name)
            dirnames[:] = retained
            for filename in sorted(filenames):
                candidate = parent / filename
                if (
                    candidate.is_symlink()
                    or not candidate.is_file()
                    or not confined_path(candidate, run_dir)
                ):
                    errors.append(f"capture artifact is unsafe: {candidate}")
                    continue
                paths.add(candidate.relative_to(run_dir).as_posix())
    run_manifest = run_dir / "run.json"
    if run_manifest.exists():
        if (
            run_manifest.is_symlink()
            or not run_manifest.is_file()
            or not confined_path(run_manifest, run_dir)
        ):
            errors.append(f"preserved run manifest is unsafe: {run_manifest}")
        else:
            paths.add("run.json")
    return paths, errors


def captured_file_error(
    path: Path,
    run_dir: Path,
    captured_files: dict[str, bytes],
    label: str,
) -> str | None:
    relative = captured_relative_path(path, run_dir)
    if relative is None:
        return f"{label} escapes run root: {path}"
    if relative not in captured_files:
        return f"{label} is not bound by the capture manifest: {relative}"
    return None


def captured_relative_path(path: Path, run_dir: Path) -> str | None:
    root = Path(os.path.abspath(run_dir))
    candidate = path if path.is_absolute() else root / path
    candidate = Path(os.path.abspath(candidate))
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return None
    return relative.as_posix() if relative.parts else None


def captured_bytes(
    path: Path, run_dir: Path, captured_files: dict[str, bytes]
) -> bytes:
    relative = captured_relative_path(path, run_dir)
    if relative is None or relative not in captured_files:
        raise ValueError(f"artifact is not authenticated: {path}")
    return captured_files[relative]


def captured_json(
    path: Path, run_dir: Path, captured_files: dict[str, bytes]
) -> dict[str, Any]:
    return load_json_bytes(captured_bytes(path, run_dir, captured_files), str(path))


def find_validation(
    run_dir: Path, captured_files: dict[str, bytes]
) -> tuple[Path | None, list[str]]:
    direct = run_dir / "runs/validation.json"
    if "runs/validation.json" in captured_files:
        return direct, []
    matches = sorted(
        run_dir / relative
        for relative in captured_files
        if relative.endswith("/runs/validation.json")
    )
    if len(matches) != 1:
        return None, [f"expected one runs/validation.json, found {len(matches)}"]
    return matches[0], []


def find_trace(
    run_dir: Path,
    summary_path: Path,
    captured_files: dict[str, bytes],
) -> tuple[Path | None, list[str]]:
    direct = summary_path.with_name("trace.jsonl")
    direct_relative = captured_relative_path(direct, run_dir)
    if direct_relative in captured_files:
        return direct, []
    matches = sorted(
        run_dir / relative
        for relative in captured_files
        if relative.endswith("/with_skill/trace.jsonl")
    )
    if len(matches) != 1:
        return None, [f"expected one with_skill/trace.jsonl, found {len(matches)}"]
    return matches[0], []


def skill_file(path: str) -> Path:
    candidate = Path(path).expanduser()
    return candidate if candidate.name == "SKILL.md" else candidate / "SKILL.md"


def lexical_path(path: Path) -> str:
    return os.path.normpath(str(path))


def file_hash(path: Path) -> str | None:
    if path.is_symlink():
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def read_tree_snapshot(
    root: Path,
    *,
    capture: Path | None = None,
) -> tuple[str, bytes | None]:
    """Hash one tree and optionally retain one file's exact hashed bytes."""

    if root.is_symlink():
        raise ValueError(f"provenance source tree must not be a symlink: {root}")
    if not root.is_dir():
        raise FileNotFoundError(root)
    capture_relative = None if capture is None else capture.relative_to(root)
    captured: bytes | None = None
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
            value = candidate.read_bytes()
            digest.update(value)
            if capture_relative is not None and relative == capture_relative:
                captured = value
            digest.update(b"\0")
    return digest.hexdigest(), captured


def tree_sha256(root: Path) -> str:
    """Hash a source tree with the same rules as the eval runner."""

    digest, _ = read_tree_snapshot(root)
    return digest


def read_skill_tree_snapshot(path: Path) -> SkillTreeSnapshot:
    """Capture canonical SKILL.md bytes and their tree digest together."""

    root = path.parent
    digest, skill_bytes = read_tree_snapshot(root, capture=path)
    if skill_bytes is None:
        raise FileNotFoundError(path)
    return SkillTreeSnapshot(
        root=Path(os.path.abspath(root)),
        skill_path=Path(os.path.abspath(path)),
        skill_bytes=skill_bytes,
        tree_sha256=digest,
    )


def expected_result(validation: dict[str, Any], skill: str) -> dict[str, Any]:
    results = validation.get("results")
    if not isinstance(results, list):
        raise ValueError("validation results must be a list")
    base_name = SKILL_NAMES[skill]
    declarations = [
        result
        for result in results
        if isinstance(result, dict)
        and isinstance(result.get("skill"), str)
        and (
            result["skill"] in {skill, base_name}
            or result["skill"].startswith(f"{base_name}-")
        )
        and isinstance(result.get("skill_path"), str)
        and result["skill_path"].strip()
    ]
    if len(declarations) != 1:
        raise ValueError(
            f"expected one declared skill/path for {base_name}, found {len(declarations)}"
        )
    return declarations[0]


def expected_skill(validation: dict[str, Any], skill: str) -> tuple[str, Path]:
    result = expected_result(validation, skill)
    return str(result["skill"]), skill_file(str(result["skill_path"]))


def file_record(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "sha256": file_hash(path),
        "symlink": path.is_symlink(),
    }


def captured_file_record(
    path: Path, run_dir: Path, captured_files: dict[str, bytes]
) -> dict[str, object]:
    relative = captured_relative_path(path, run_dir)
    value = None if relative is None else captured_files.get(relative)
    return {
        "path": str(path),
        "sha256": None if value is None else hashlib.sha256(value).hexdigest(),
        "symlink": False,
        "authenticated": value is not None,
    }


def resolve_recorded_path(
    value: object,
    base: Path,
    *,
    boundary: Path | None = None,
) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    candidate = path if path.is_absolute() else base / path
    if boundary is not None and not confined_path(candidate, boundary):
        return None
    return candidate


def confined_path(path: Path, boundary: Path) -> bool:
    """Require lexical and resolved containment with no symlinks below boundary."""

    absolute_path = path.absolute()
    absolute_boundary = boundary.absolute()
    if absolute_boundary.is_symlink():
        return False
    try:
        relative = absolute_path.relative_to(absolute_boundary)
    except ValueError:
        return False
    current = absolute_boundary
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            return False
    try:
        absolute_path.resolve().relative_to(absolute_boundary.resolve())
    except ValueError:
        return False
    return True


def authenticated_tree_record(
    name: str,
    record: object,
    expected_path: Path,
    path_base: Path,
    errors: list[str],
    *,
    optional: bool = False,
    snapshot: SkillTreeSnapshot | None = None,
) -> dict[str, object]:
    """Bind a manifest tree digest to its declared source byte snapshot."""

    if not isinstance(record, dict):
        errors.append(f"evaluator provenance {name} must be an object")
        return {
            "path": str(expected_path),
            "recorded_path": None,
            "recorded_tree_sha256": None,
            "computed_tree_sha256": None,
            "verified": False,
        }

    recorded_path = resolve_recorded_path(
        record.get("path"), path_base, boundary=path_base
    )
    recorded_digest = record.get("tree_sha256")
    expected_resolved = expected_path.resolve()
    recorded_resolved = recorded_path.resolve() if recorded_path is not None else None
    path_matches = recorded_resolved == expected_resolved
    if recorded_path is None:
        errors.append(f"evaluator provenance {name}.path is missing")
    elif not path_matches:
        errors.append(
            f"evaluator provenance {name}.path mismatch: expected "
            f"{expected_resolved}, got {recorded_resolved}"
        )

    computed_digest: str | None = None
    if snapshot is not None:
        snapshot_matches = snapshot.root == Path(os.path.abspath(expected_path))
        if not snapshot_matches:
            errors.append(
                f"evaluator provenance {name} snapshot path mismatch: expected "
                f"{expected_resolved}, got {snapshot.root}"
            )
        else:
            computed_digest = snapshot.tree_sha256
    elif expected_resolved.is_dir():
        try:
            computed_digest = tree_sha256(expected_resolved)
        except (OSError, ValueError) as error:
            errors.append(
                f"failed to hash evaluator provenance {name} tree "
                f"{expected_resolved}: {error}"
            )
    elif not optional:
        errors.append(
            f"evaluator provenance {name} source tree is unavailable: "
            f"{expected_resolved}"
        )

    digest_is_valid = (
        recorded_digest is None
        if optional and computed_digest is None
        else isinstance(recorded_digest, str)
        and bool(SHA256_PATTERN.fullmatch(recorded_digest))
    )
    if not digest_is_valid:
        errors.append(f"evaluator provenance {name}.tree_sha256 is invalid")
    elif recorded_digest != computed_digest:
        errors.append(
            f"evaluator provenance {name}.tree_sha256 does not match "
            f"{expected_resolved}: recorded {recorded_digest!r}, "
            f"computed {computed_digest!r}"
        )

    return {
        "path": str(expected_resolved),
        "recorded_path": (
            None if recorded_resolved is None else str(recorded_resolved)
        ),
        "recorded_tree_sha256": recorded_digest,
        "computed_tree_sha256": computed_digest,
        "verified": bool(
            path_matches
            and digest_is_valid
            and recorded_digest == computed_digest
        ),
    }


def authenticated_staged_skill_path(
    record: object,
    expected_skill: Path,
    errors: list[str],
) -> str | None:
    """Validate the harness-owned staged path without touching it live."""

    value = record.get("staged_path") if isinstance(record, dict) else None
    if not isinstance(value, str) or not value.strip():
        errors.append("evaluator provenance skill.staged_path is missing")
        return None
    candidate = Path(value)
    normalized = lexical_path(candidate)
    if not candidate.is_absolute() or normalized != value:
        errors.append(
            "evaluator provenance skill.staged_path must be a normalized "
            "absolute path"
        )
        return None
    expected_suffix = (
        ".agents",
        "skills",
        expected_skill.parent.name,
        "SKILL.md",
    )
    if tuple(candidate.parts[-4:]) != expected_suffix:
        errors.append(
            "evaluator provenance skill.staged_path does not identify the "
            "declared staged skill"
        )
        return None
    return normalized


def authenticated_file_record(
    name: str,
    record: object,
    expected_path: Path | None,
    path_base: Path,
    errors: list[str],
    *,
    optional: bool = False,
    snapshot: FileDigestSnapshot | None = None,
) -> dict[str, object]:
    """Authenticate a file digest against one captured source snapshot."""

    if not isinstance(record, dict):
        errors.append(f"evaluator provenance {name} must be an object")
        return {
            "path": None if expected_path is None else str(expected_path),
            "recorded_path": None,
            "sha256": None,
            "computed_sha256": None,
            "verified": False,
        }

    recorded_path = resolve_recorded_path(
        record.get("path"), path_base, boundary=path_base
    )
    recorded_exists = record.get("exists")
    recorded_digest = record.get("sha256")
    expected_resolved = expected_path.resolve() if expected_path is not None else None
    recorded_resolved = recorded_path.resolve() if recorded_path is not None else None
    path_matches = recorded_resolved == expected_resolved
    if expected_resolved is None and optional:
        path_matches = recorded_resolved is None
    if not path_matches:
        errors.append(
            f"evaluator provenance {name}.path mismatch: expected "
            f"{expected_resolved}, got {recorded_resolved}"
        )

    if expected_path is not None and expected_path.is_symlink():
        errors.append(f"evaluator provenance {name} source must not be a symlink")
        path_matches = False

    if snapshot is None:
        current_exists = bool(
            expected_resolved is not None and expected_resolved.is_file()
        )
        computed_digest = (
            file_hash(expected_resolved) if current_exists else None
        )
    else:
        current_exists = snapshot.exists
        computed_digest = snapshot.sha256
    digest_is_valid = (
        recorded_digest is None
        if not current_exists
        else isinstance(recorded_digest, str)
        and bool(SHA256_PATTERN.fullmatch(recorded_digest))
    )
    if recorded_exists is not current_exists:
        errors.append(
            f"evaluator provenance {name}.exists does not match current source"
        )
    if not digest_is_valid:
        errors.append(f"evaluator provenance {name}.sha256 is invalid")
    elif recorded_digest != computed_digest:
        errors.append(
            f"evaluator provenance {name}.sha256 does not match "
            f"{expected_resolved}: recorded {recorded_digest!r}, "
            f"computed {computed_digest!r}"
        )

    return {
        "path": None if expected_resolved is None else str(expected_resolved),
        "recorded_path": (
            None if recorded_resolved is None else str(recorded_resolved)
        ),
        "sha256": recorded_digest,
        "computed_sha256": computed_digest,
        "verified": bool(
            path_matches
            and recorded_exists is current_exists
            and digest_is_valid
            and recorded_digest == computed_digest
        ),
    }


def authenticated_run_configuration(
    record: object,
    errors: list[str],
) -> dict[str, object]:
    if not isinstance(record, dict):
        errors.append("evaluator provenance run_configuration must be an object")
        return {"sha256": None, "verified": False}
    recorded_digest = record.get("sha256")
    computed_digest = hashlib.sha256(
        canonical_json(record.get("value")).encode("utf-8")
    ).hexdigest()
    verified = (
        isinstance(recorded_digest, str)
        and bool(SHA256_PATTERN.fullmatch(recorded_digest))
        and recorded_digest == computed_digest
    )
    if not verified:
        errors.append(
            "evaluator provenance run_configuration.sha256 is invalid"
        )
    return {
        "value": record.get("value"),
        "sha256": recorded_digest,
        "computed_sha256": computed_digest,
        "verified": verified,
    }


def definition_case_contract(
    definition_path: Path,
    prompt_id: str,
    *,
    definition_bytes: bytes | None = None,
) -> tuple[str, str | None, list[str]]:
    errors: list[str] = []
    try:
        definition = load_eval_definition(
            definition_path,
            definition_bytes=definition_bytes,
        )
    except (OSError, ValueError, TypeError, JsonSchemaValidationError) as error:
        return "", None, [f"failed to read eval definition: {error}"]
    matches = [
        prompt
        for prompt in definition.prompts
        if prompt.id == prompt_id
    ]
    if len(matches) != 1:
        errors.append(
            f"expected one prompt {prompt_id!r} in {definition_path}, found {len(matches)}"
        )
        return "", None, errors
    case = case_from_definition(definition, matches[0], definition_path)
    return case.task, case_contract_sha256(case), errors


def read_file_digest_snapshot(
    path: Path,
) -> tuple[bytes, FileDigestSnapshot]:
    """Read one file once and retain the digest of those exact bytes."""

    value = path.read_bytes()
    return value, FileDigestSnapshot(
        exists=True,
        sha256=hashlib.sha256(value).hexdigest(),
    )


def load_run_provenance(
    run_dir: Path,
    summary_path: Path,
    validation_path: Path,
    validation: dict[str, Any],
    repo_root: Path,
    skill: str,
    captured_files: dict[str, bytes],
    *,
    skill_snapshot: SkillTreeSnapshot | None = None,
) -> tuple[dict[str, object], str, list[str]]:
    errors: list[str] = []
    result = expected_result(validation, skill)
    prompt_id = str(result.get("prompt_id") or "")
    validation_repo = resolve_recorded_path(
        validation.get("repo_root"), repo_root, boundary=repo_root
    )
    if validation_repo is None or validation_repo.resolve() != repo_root.resolve():
        errors.append("validation repo_root does not match the benchmark repository")
    source_base = repo_root
    definition_path = resolve_recorded_path(
        result.get("definition_path"), source_base, boundary=source_base
    )
    fixture_path = resolve_recorded_path(
        result.get("fixture_dir"), source_base, boundary=source_base
    )
    declared_skill_path = resolve_recorded_path(
        result.get("skill_path"), source_base, boundary=source_base
    )
    if declared_skill_path is not None and declared_skill_path.name == "SKILL.md":
        declared_skill_path = declared_skill_path.parent
    shared_references_path = source_base / "skills/references"
    harness_source_path = (
        source_base / "pytest-codex-evals/src/pytest_codex_evals"
    )
    manifest_path = summary_path.parent / PROVENANCE_FILE
    run_manifest_path = run_dir / "run.json"

    manifest_error = captured_file_error(
        manifest_path,
        run_dir,
        captured_files,
        "evaluator provenance manifest",
    )
    run_manifest_error = captured_file_error(
        run_manifest_path,
        run_dir,
        captured_files,
        "preserved run manifest",
    )
    if manifest_error:
        errors.append(manifest_error)
    if run_manifest_error:
        errors.append(run_manifest_error)

    current_task = ""
    current_case_contract_sha256: str | None = None
    definition_snapshot = FileDigestSnapshot(exists=False, sha256=None)
    if definition_path is None:
        errors.append("validation result has no definition_path")
    else:
        try:
            definition_bytes, definition_snapshot = (
                read_file_digest_snapshot(definition_path)
            )
        except OSError as error:
            errors.append(f"failed to read eval definition: {error}")
        else:
            (
                current_task,
                current_case_contract_sha256,
                definition_errors,
            ) = definition_case_contract(
                definition_path,
                prompt_id,
                definition_bytes=definition_bytes,
            )
            errors.extend(definition_errors)
    if fixture_path is None or not fixture_path.is_dir():
        errors.append(f"validation fixture_dir is unavailable: {fixture_path}")
    if declared_skill_path is None or not declared_skill_path.is_dir():
        errors.append(
            f"validation skill_path is unavailable: {declared_skill_path}"
        )

    manifest: dict[str, Any] = {}
    if not manifest_error:
        try:
            manifest = captured_json(manifest_path, run_dir, captured_files)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"failed to read evaluator provenance manifest: {error}")

    if not isinstance(manifest.get("schema_version"), int) or int(
        manifest.get("schema_version") or 0
    ) < 2:
        errors.append(
            "evaluator provenance manifest does not bind definition/config bytes"
        )

    case = manifest.get("case") if isinstance(manifest, dict) else None
    task = ""
    task_sha256: object = None
    recorded_case_contract_sha256: object = None
    if not isinstance(case, dict):
        errors.append("evaluator provenance case must be an object")
    else:
        expected_case = {
            "id": str(result.get("id") or ""),
            "prompt_id": prompt_id,
            "skill": str(result.get("skill") or ""),
        }
        for key, expected_value in expected_case.items():
            if case.get(key) != expected_value:
                errors.append(
                    f"evaluator provenance case.{key} mismatch: "
                    f"expected {expected_value!r}, got {case.get(key)!r}"
                )
        recorded_task = case.get("task")
        recorded_task_hash = case.get("task_sha256")
        recorded_case_contract_sha256 = case.get("contract_sha256")
        if not isinstance(recorded_task, str) or not recorded_task.strip():
            errors.append("evaluator provenance case.task is missing")
        else:
            task = recorded_task
        if current_task and recorded_task != current_task:
            errors.append("evaluator provenance task differs from eval definition")
        calculated_task_hash = (
            hashlib.sha256(recorded_task.encode("utf-8")).hexdigest()
            if isinstance(recorded_task, str)
            else None
        )
        if recorded_task_hash != calculated_task_hash:
            errors.append("evaluator provenance task_sha256 is invalid")
        else:
            task_sha256 = recorded_task_hash
        if not isinstance(
            recorded_case_contract_sha256,
            str,
        ) or not SHA256_PATTERN.fullmatch(
            recorded_case_contract_sha256
        ):
            errors.append("evaluator provenance case.contract_sha256 is invalid")
        elif recorded_case_contract_sha256 != current_case_contract_sha256:
            errors.append(
                "evaluator provenance case.contract_sha256 differs from "
                "the current eval definition"
            )

    definition_record = authenticated_file_record(
        "definition",
        manifest.get("definition") if isinstance(manifest, dict) else None,
        definition_path,
        source_base,
        errors,
        snapshot=definition_snapshot,
    )

    fixture_record = authenticated_tree_record(
        "fixture",
        manifest.get("fixture") if isinstance(manifest, dict) else None,
        fixture_path or source_base / ".missing-fixture",
        source_base,
        errors,
    )
    skill_record = authenticated_tree_record(
        "skill",
        manifest.get("skill") if isinstance(manifest, dict) else None,
        declared_skill_path or source_base / ".missing-skill",
        source_base,
        errors,
        snapshot=skill_snapshot,
    )
    staged_skill_path = authenticated_staged_skill_path(
        manifest.get("skill") if isinstance(manifest, dict) else None,
        (
            declared_skill_path / "SKILL.md"
            if declared_skill_path is not None
            else source_base / ".missing-skill/SKILL.md"
        ),
        errors,
    )
    skill_record["staged_path"] = staged_skill_path
    skill_record["staged_path_verified"] = bool(
        skill_record.get("verified") is True and staged_skill_path is not None
    )
    shared_references_record = authenticated_tree_record(
        "shared_references",
        manifest.get("shared_references") if isinstance(manifest, dict) else None,
        shared_references_path,
        source_base,
        errors,
        optional=True,
    )
    harness_record = authenticated_tree_record(
        "harness",
        manifest.get("harness") if isinstance(manifest, dict) else None,
        harness_source_path,
        source_base,
        errors,
    )

    if run_manifest_error:
        run_manifest: dict[str, Any] = {}
    else:
        try:
            run_manifest = captured_json(
                run_manifest_path, run_dir, captured_files
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"failed to read preserved run manifest: {error}")
            run_manifest = {}
    if run_manifest and run_manifest.get("skill") not in {skill, SKILL_NAMES[skill]}:
        errors.append(
            f"preserved run manifest skill mismatch: {run_manifest.get('skill')!r}"
        )

    metadata = validation.get("metadata")
    config_value = metadata.get("config_path") if isinstance(metadata, dict) else None
    config_path = resolve_recorded_path(
        config_value,
        repo_root,
        boundary=repo_root,
    )
    if config_value and (config_path is None or not config_path.is_file()):
        errors.append(f"recorded eval config is unavailable: {config_path}")
    config_record = authenticated_file_record(
        "config",
        manifest.get("config") if isinstance(manifest, dict) else None,
        config_path,
        source_base,
        errors,
        optional=not bool(config_value),
    )
    run_configuration_record = authenticated_run_configuration(
        manifest.get("run_configuration") if isinstance(manifest, dict) else None,
        errors,
    )
    if not isinstance(metadata, dict):
        errors.append("validation metadata must be an object")
    elif run_configuration_record.get("value") != metadata:
        errors.append(
            "evaluator provenance run_configuration differs from sealed validation metadata"
        )

    raw_run_records: list[dict[str, object]] = []
    raw_run_values = run_manifest.get("runs") if isinstance(run_manifest, dict) else None
    if raw_run_values is not None and not isinstance(raw_run_values, list):
        errors.append("preserved run manifest runs must be a list")
    elif isinstance(raw_run_values, list):
        for value in raw_run_values:
            path = resolve_recorded_path(value, run_dir, boundary=run_dir)
            if path is None:
                errors.append(f"preserved raw run artifact is unavailable: {path}")
            elif error := captured_file_error(
                path,
                run_dir,
                captured_files,
                "preserved raw run artifact",
            ):
                errors.append(error)
            elif path.name != "validation.json":
                raw_run_records.append(
                    captured_file_record(path, run_dir, captured_files)
                )

    provenance = {
        "manifest": captured_file_record(
            manifest_path, run_dir, captured_files
        ),
        "validation": captured_file_record(
            validation_path, run_dir, captured_files
        ),
        "definition": definition_record,
        "fixture": fixture_record,
        "skill": skill_record,
        "shared_references": shared_references_record,
        "harness": harness_record,
        "config": config_record,
        "run_configuration": run_configuration_record,
        "run_manifest": captured_file_record(
            run_manifest_path, run_dir, captured_files
        ),
        "raw_runs": raw_run_records,
        "summary": captured_file_record(
            summary_path, run_dir, captured_files
        ),
        "trace": captured_file_record(
            summary_path.with_name("trace.jsonl"), run_dir, captured_files
        ),
        "task_sha256": task_sha256,
        "case_contract_sha256": recorded_case_contract_sha256,
    }
    return provenance, task, errors


def shell_tokens(command: str) -> list[str]:
    lexer = shlex.shlex(
        command,
        posix=True,
        punctuation_chars=";&|<>",
    )
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def trusted_command_name(token: str, allowed: set[str]) -> str | None:
    """Recognize an ordinary PATH command or a standard absolute binary."""

    candidate = Path(token)
    name = candidate.name
    if name not in allowed:
        return None
    if "/" not in token:
        return name
    if candidate.parent in TRUSTED_COMMAND_DIRECTORIES:
        return name
    return None


def reader_uses_only_stdin(reader: str, arguments: list[str]) -> bool:
    """Recognize a small, auditable set of stdin-only reader filters."""

    if arguments and arguments[-1] == "-":
        arguments = arguments[:-1]
    if reader == "cat":
        return not arguments
    if reader in {"head", "tail"}:
        count_pattern = r"\d+" if reader == "head" else r"\+?\d+"
        return not arguments or (
            len(arguments) == 2
            and arguments[0] == "-n"
            and re.fullmatch(count_pattern, arguments[1]) is not None
        )
    if reader == "sed":
        return (
            len(arguments) == 2
            and arguments[0] == "-n"
            and re.fullmatch(r"[1-9]\d*(?:,[1-9]\d*)?p", arguments[1])
            is not None
        )
    return False


def skill_reader_path(reader: str, arguments: list[str]) -> Path | None:
    """Recognize one direct reader with exactly one SKILL.md input."""

    if not arguments or Path(arguments[-1]).name != "SKILL.md":
        return None
    path = arguments[-1]
    options = arguments[:-1]
    if reader == "cat" and not options:
        return skill_file(path)
    if reader in {"head", "tail"} and (
        not options
        or (
            len(options) == 2
            and options[0] == "-n"
            and re.fullmatch(
                r"\d+" if reader == "head" else r"\+?\d+",
                options[1],
            )
            is not None
        )
    ):
        return skill_file(path)
    if reader == "sed" and (
        len(options) == 2
        and options[0] == "-n"
        and re.fullmatch(r"[1-9]\d*(?:,[1-9]\d*)?p", options[1])
        is not None
    ):
        return skill_file(path)
    return None


def shell_payload(tokens: list[str]) -> str | None:
    """Return the command string from a minimal supported shell wrapper."""

    shell = trusted_command_name(tokens[0], SHELL_COMMANDS)
    if shell is None:
        return None
    arguments = tokens[1:]
    if shell == "bash" and arguments[:1] == ["--norc"]:
        arguments = arguments[1:]
    if not arguments or arguments[0] not in {"-c", "-lc"}:
        return None
    arguments = arguments[1:]
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    return arguments[0] if len(arguments) == 1 else None


def shell_operator(token: str) -> bool:
    return bool(token) and not set(token).difference(";&|<>")


def traced_skill_paths(command: str) -> list[Path]:
    """Return SKILL.md operands from structurally recognized read commands."""

    if "\n" in command:
        return []
    try:
        tokens = shell_tokens(command)
    except ValueError:
        return []
    if not tokens:
        return []

    if trusted_command_name(tokens[0], SHELL_COMMANDS) is not None:
        payload = shell_payload(tokens)
        return traced_skill_paths(payload) if payload is not None else []

    operators = [token for token in tokens if shell_operator(token)]
    if any(operator != "|" for operator in operators):
        return []

    segments: list[list[str]] = [[]]
    for token in tokens:
        if token == "|":
            segments.append([])
        else:
            segments[-1].append(token)
    if any(not segment for segment in segments):
        return []

    source_reader = trusted_command_name(segments[0][0], SKILL_READ_COMMANDS)
    if source_reader is None:
        return []
    source = skill_reader_path(source_reader, segments[0][1:])
    if source is None:
        return []

    for segment in segments[1:]:
        reader = trusted_command_name(segment[0], SKILL_READ_COMMANDS)
        if reader is None or not reader_uses_only_stdin(reader, segment[1:]):
            return []
    return [source]


def output_covers_skill(
    expected: Path | bytes,
    outputs: list[str],
) -> bool:
    try:
        value = expected.read_bytes() if isinstance(expected, Path) else expected
        expected_lines = value.decode("utf-8").splitlines()
    except (OSError, UnicodeError):
        return False
    if not expected_lines:
        return False
    covered: set[int] = set()
    for output in outputs:
        matcher = difflib.SequenceMatcher(
            None,
            expected_lines,
            output.splitlines(),
            autojunk=False,
        )
        for block in matcher.get_matching_blocks():
            covered.update(range(block.a, block.a + block.size))
    return len(covered) == len(expected_lines)


def skill_read_proven(
    expected: Path,
    reads_by_path: dict[Path, list[str]],
    *,
    expected_bytes: bytes | None = None,
    staged_path: str | None = None,
) -> bool:
    """Require one declared or harness-staged path to expose the full skill."""

    expected_lexical = lexical_path(expected)
    expected_value: Path | bytes = (
        expected if expected_bytes is None else expected_bytes
    )
    matching_outputs: dict[str, list[str]] = {}
    for candidate, outputs in reads_by_path.items():
        candidate_lexical = lexical_path(candidate)
        if candidate_lexical in {expected_lexical, staged_path}:
            matching_outputs.setdefault(candidate_lexical, []).extend(outputs)
    return any(
        output_covers_skill(expected_value, outputs)
        for outputs in matching_outputs.values()
    )


def traced_skill_evidence(
    trace_bytes: bytes,
    trace_label: str,
) -> dict[Path, list[str]]:
    reads_by_path: dict[Path, list[str]] = {}
    for line_number, line in enumerate(
        trace_bytes.decode("utf-8").splitlines(), 1
    ):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"invalid trace JSON at {trace_label}:{line_number}: {error.msg}"
            ) from error
        if not isinstance(event, dict) or event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("type") != "command_execution":
            continue
        if item.get("exit_code") != 0 or not isinstance(item.get("command"), str):
            continue
        output = item.get("aggregated_output")
        if not isinstance(output, str):
            continue
        for path in dict.fromkeys(traced_skill_paths(str(item["command"]))):
            reads_by_path.setdefault(path, []).append(output)
    return reads_by_path


def validate_skill_load(
    run_dir: Path,
    summary_path: Path,
    expected: Path,
    skill_snapshot: SkillTreeSnapshot,
    staged_path: str | None,
    captured_files: dict[str, bytes],
) -> list[str]:
    if platform_error := skill_trace_platform_error():
        return [platform_error]
    trace_path, trace_errors = find_trace(
        run_dir, summary_path, captured_files
    )
    if trace_path is None:
        return trace_errors
    if error := captured_file_error(
        trace_path,
        run_dir,
        captured_files,
        "agent trace",
    ):
        return [*trace_errors, error]
    try:
        skill_reads = traced_skill_evidence(
            captured_bytes(trace_path, run_dir, captured_files), str(trace_path)
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"failed to verify loaded skill: {error}"]

    expected_lexical = lexical_path(expected)
    if skill_read_proven(
        expected,
        skill_reads,
        expected_bytes=skill_snapshot.skill_bytes,
        staged_path=staged_path,
    ):
        return []

    expected_hash = hashlib.sha256(skill_snapshot.skill_bytes).hexdigest()
    if skill_reads:
        loaded = ", ".join(
            sorted({lexical_path(candidate) for candidate in skill_reads})
        )
    else:
        loaded = "no successful SKILL.md content reads"
    return [
        "skill load mismatch: validation expected "
        f"{expected_lexical} (sha256={expected_hash}), but trace loaded {loaded}; "
        "a reference read or agent message cannot prove that the governing "
        "SKILL.md was loaded"
    ]


def validator_result(
    name: str,
    command: list[str] | None,
    *,
    reason: str | None = None,
    workspaces: tuple["RetainedWorkspace", ...] = (),
) -> dict[str, object]:
    if command is None:
        return {
            "name": name,
            "status": "not_applicable",
            "reason": reason or "validator does not apply",
        }
    try:
        for workspace in workspaces:
            workspace.require_current(f"before {name}")
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        for workspace in workspaces:
            workspace.require_current(f"after {name}")
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        return {
            "name": name,
            "status": "error",
            "command": command,
            "reason": str(error),
        }
    return {
        "name": name,
        "status": "passed" if completed.returncode == 0 else "failed",
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def reader_validator_command(repo_root: Path, report: Path) -> list[str]:
    command = [
        sys.executable,
        str(repo_root / "skills/otel-verify/scripts/validate_reader_report.py"),
        str(report),
    ]
    instrumentation = report.parent / "otel-instrumentation.json"
    verification = report.parent / "otel-verify.json"
    if instrumentation.is_file():
        command.extend(["--instrumentation-json", str(instrumentation)])
        if verification.is_file():
            command.extend(["--verify-json", str(verification)])
    else:
        expected = report.parent / "tmp/otel-verify-expected-items.txt"
        if expected.is_file():
            command.extend(["--expected-items-file", str(expected)])
    return command


def gap_closure_validator_command(
    repo_root: Path,
    observe_dir: Path,
    instrumentation_report: Path,
) -> list[str]:
    command = [
        sys.executable,
        str(repo_root / "skills/otel-instrument/scripts/validate_gap_closure.py"),
        str(observe_dir / "otel.md"),
        str(instrumentation_report),
    ]
    audit = observe_dir / "otel-audit.json"
    selection = observe_dir / "otel-selection.json"
    instrumentation = observe_dir / "otel-instrumentation.json"
    verification = observe_dir / "otel-verify.json"
    if audit.is_file() and selection.is_file() and instrumentation.is_file():
        command.extend(
            [
                "--audit-json",
                str(audit),
                "--selection-json",
                str(selection),
            ]
        )
        if verification.is_file():
            command.extend(["--verify-json", str(verification)])
        else:
            command.extend(["--instrumentation-json", str(instrumentation)])
    return command


def missing_validator(name: str, reason: str) -> dict[str, object]:
    return {"name": name, "status": "missing", "reason": reason}


@dataclass
class RetainedWorkspace:
    """Private retained tree whose original root stays descriptor-anchored."""

    path: Path
    anchor: AnchoredDirectory

    @property
    def identity(self) -> tuple[int, int]:
        return self.anchor.parent_identity

    def require_current(self, operation: str) -> None:
        if not anchored_namespace_matches(self.anchor):
            raise ValueError(
                f"retained workspace namespace changed {operation}: {self.path}"
            )

    def read_bytes(self, path: Path, operation: str) -> bytes:
        absolute = Path(os.path.abspath(path))
        try:
            absolute.relative_to(self.path)
        except ValueError as error:
            raise ValueError(
                f"retained workspace read escapes root: {absolute}"
            ) from error
        self.require_current(f"before {operation}")
        value = read_anchored_regular_bytes(
            absolute,
            boundary=self.path,
            expected_boundary_identity=self.identity,
        )
        self.require_current(f"after {operation}")
        return value

    def verify_files(
        self,
        expected: dict[str, bytes],
        operation: str,
    ) -> None:
        """Verify every authenticated file and reject added regular files."""

        self.require_current(f"before {operation}")
        actual_paths: set[str] = set()
        for directory, dirnames, filenames in os.walk(
            self.path, followlinks=False
        ):
            parent = Path(directory)
            retained: list[str] = []
            for name in sorted(dirnames):
                candidate = parent / name
                details = os.lstat(candidate)
                if path_is_link_or_reparse(details) or not stat.S_ISDIR(
                    details.st_mode
                ):
                    raise ValueError(
                        f"retained workspace contains an unsafe directory: {candidate}"
                    )
                retained.append(name)
            dirnames[:] = retained
            for name in sorted(filenames):
                candidate = parent / name
                details = os.lstat(candidate)
                if path_is_link_or_reparse(details) or not stat.S_ISREG(
                    details.st_mode
                ):
                    raise ValueError(
                        f"retained workspace contains an unsafe file: {candidate}"
                    )
                actual_paths.add(candidate.relative_to(self.path).as_posix())
        if actual_paths != set(expected):
            added = sorted(actual_paths - set(expected))
            missing = sorted(set(expected) - actual_paths)
            raise ValueError(
                f"retained workspace file set changed {operation}; "
                f"added={added}, missing={missing}"
            )
        for relative, value in expected.items():
            current = self.read_bytes(
                self.path / relative,
                f"{operation} read {relative}",
            )
            if current != value:
                raise ValueError(
                    f"retained workspace file changed {operation}: {relative}"
                )
        self.require_current(f"after {operation}")

    def close(self) -> None:
        close_anchored_directory(self.anchor)


def retained_workspace(prefix: str) -> RetainedWorkspace:
    """Create and retain an authenticated private workspace root."""

    workspace = Path(tempfile.mkdtemp(prefix=prefix))
    details = workspace.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise ValueError(
            f"retained workspace is not a private directory: {workspace}"
        )
    if hasattr(os, "getuid") and details.st_uid != os.getuid():
        raise ValueError(
            "retained workspace is not owned by the current user: "
            f"{workspace}"
        )
    anchor = open_anchored_directory(workspace, workspace.parent)
    if anchor.parent_identity != (details.st_dev, details.st_ino):
        close_anchored_directory(anchor)
        raise ValueError(
            f"retained workspace changed while it was opened: {workspace}"
        )
    retained = RetainedWorkspace(workspace, anchor)
    try:
        retained.require_current("during creation")
    except BaseException:
        retained.close()
        raise
    return retained


def task_requires(task: str, filename: str) -> bool:
    return filename in task


def canonical_flow_command(
    repo_root: Path,
    observe_dir: Path,
    skill: str,
) -> tuple[list[str] | None, str | None]:
    report_tool = repo_root / "skills/references/scripts/observe_report.py"
    audit = observe_dir / "otel-audit.json"
    selection = observe_dir / "otel-selection.json"
    instrumentation = observe_dir / "otel-instrumentation.json"
    verify = observe_dir / "otel-verify.json"
    if skill == "audit":
        if not audit.is_file():
            return None, f"canonical audit JSON is missing: {audit}"
        return [sys.executable, str(report_tool), "validate", str(audit)], None

    required = [audit, selection]
    if skill == "instrument":
        required.append(instrumentation)
    else:
        required.append(verify)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        return None, "bound canonical flow is missing: " + ", ".join(missing)
    command = [
        sys.executable,
        str(report_tool),
        "validate-flow",
        str(audit),
        "--selection-json",
        str(selection),
    ]
    if instrumentation.is_file():
        command.extend(["--instrumentation-json", str(instrumentation)])
    if verify.is_file():
        command.extend(["--verify-json", str(verify)])
    return command, None


def canonical_html_result(
    repo_root: Path,
    observe_dir: Path,
    skill: str,
    html_path: Path,
    source_workspace: RetainedWorkspace | None = None,
) -> dict[str, object]:
    name = f"{skill}_canonical_html"
    if not html_path.is_file():
        return missing_validator(name, f"canonical HTML is missing: {html_path}")
    report_tool = repo_root / "skills/references/scripts/observe_report.py"
    audit = observe_dir / "otel-audit.json"
    selection = observe_dir / "otel-selection.json"
    instrumentation = observe_dir / "otel-instrumentation.json"
    verify = observe_dir / "otel-verify.json"
    if not audit.is_file():
        return missing_validator(name, f"canonical audit JSON is missing: {audit}")

    generated_workspace: RetainedWorkspace | None = None
    try:
        generated_workspace = retained_workspace("otel-benchmark-render-")
        temporary = generated_workspace.path / "rendered.html"
        if skill == "audit":
            command = [
                sys.executable,
                str(report_tool),
                "render-html",
                str(audit),
                "-o",
                str(temporary),
                "--repo-root",
                str(observe_dir.parent),
            ]
            if selection.is_file():
                command.extend(["--selection-json", str(selection)])
        else:
            required = [selection, instrumentation]
            missing = [str(path) for path in required if not path.is_file()]
            if missing:
                return missing_validator(
                    name,
                    "canonical instrumentation HTML inputs are missing: "
                    + ", ".join(missing),
                )
            command = [
                sys.executable,
                str(report_tool),
                "render-instrumentation-html",
                str(audit),
                "-o",
                str(temporary),
                "--selection-json",
                str(selection),
                "--instrumentation-json",
                str(instrumentation),
                "--repo-root",
                str(observe_dir.parent),
            ]
            if verify.is_file():
                command.extend(["--verify-json", str(verify)])
        monitored = (
            (generated_workspace,)
            if source_workspace is None
            else (source_workspace, generated_workspace)
        )
        result = validator_result(name, command, workspaces=monitored)
        if result["status"] != "passed":
            return result
        rendered = generated_workspace.read_bytes(
            temporary, "while reading the fresh canonical HTML"
        )
        preserved = (
            source_workspace.read_bytes(
                html_path, "while reading the preserved canonical HTML"
            )
            if source_workspace is not None
            else regular_file_bytes(html_path)
        )
        if rendered != preserved:
            result["status"] = "failed"
            result["reason"] = (
                "checked-in HTML differs from a fresh canonical render of the "
                "preserved JSON flow"
            )
        return result
    except (OSError, ValueError) as error:
        return {"name": name, "status": "error", "reason": str(error)}
    finally:
        if generated_workspace is not None:
            generated_workspace.close()


def validate_run(
    repo_root: Path,
    artifact: RunArtifact,
    workspace: RetainedWorkspace | None = None,
) -> list[dict[str, object]]:
    monitored = () if workspace is None else (workspace,)
    if workspace is not None:
        workspace.require_current("before run validation")
    if artifact.report_path is None or not artifact.report_path.is_file():
        return [
            {
                "name": f"{artifact.skill}_report",
                "status": "missing",
                "reason": "primary report is missing",
            }
        ]

    observe_dir = artifact.report_path.parent
    symlinked_outputs = sorted(
        path for path in observe_dir.rglob("*") if path.is_symlink()
    )
    if symlinked_outputs:
        return [
            {
                "name": f"{artifact.skill}_artifact_safety",
                "status": "failed",
                "reason": "preserved outputs must not be symlinks: "
                + ", ".join(str(path) for path in symlinked_outputs),
            }
        ]
    results: list[dict[str, object]] = []

    if artifact.skill == "audit":
        results.append(
            validator_result(
                "audit_report",
                [
                    sys.executable,
                    str(repo_root / "skills/otel-audit/scripts/validate_audit_report.py"),
                    str(artifact.report_path),
                ],
                workspaces=monitored,
            )
        )
    elif artifact.skill == "verify":
        results.append(
            validator_result(
                "verify_reader_report",
                reader_validator_command(repo_root, artifact.report_path),
                workspaces=monitored,
            )
        )

    canonical_json = observe_dir / CANONICAL_JSON_REPORTS[artifact.skill]
    if canonical_json.is_file() or task_requires(
        artifact.task, CANONICAL_JSON_REPORTS[artifact.skill]
    ):
        flow_command, reason = canonical_flow_command(
            repo_root, observe_dir, artifact.skill
        )
        if flow_command is None:
            results.append(
                missing_validator(f"{artifact.skill}_canonical_json", reason or "missing")
            )
        else:
            results.append(
                validator_result(
                    f"{artifact.skill}_canonical_json",
                    flow_command,
                    workspaces=monitored,
                )
            )

    canonical_html = observe_dir / CANONICAL_HTML_REPORTS[artifact.skill]
    if canonical_html.is_file() or task_requires(
        artifact.task, CANONICAL_HTML_REPORTS[artifact.skill]
    ):
        results.append(
            canonical_html_result(
                repo_root,
                observe_dir,
                artifact.skill,
                canonical_html,
                workspace,
            )
        )

    if artifact.skill != "instrument":
        return results

    audit_report = observe_dir / "otel.md"
    if audit_report.is_file():
        results.append(
            validator_result(
                "instrument_gap_closure",
                gap_closure_validator_command(
                    repo_root, observe_dir, artifact.report_path
                ),
                workspaces=monitored,
            )
        )
    else:
        results.append(
            validator_result(
                "instrument_gap_closure",
                None,
                reason="source audit is absent in this benchmark fixture",
            )
        )

    nested_verify = observe_dir / "otel-verify.md"
    if nested_verify.is_file():
        results.append(
            validator_result(
                "nested_verify_reader_report",
                reader_validator_command(repo_root, nested_verify),
                workspaces=monitored,
            )
        )
    else:
        results.append(
            validator_result(
                "nested_verify_reader_report",
                None,
                reason=(
                    "nested verification report is absent; the required "
                    "primary instrumentation report remains the benchmark "
                    "artifact"
                ),
            )
        )
    return results


def materialize_capture_snapshot(
    destination: Path,
    captured_files: dict[str, bytes],
    *,
    expected_destination_identity: tuple[int, int] | None = None,
) -> None:
    """Create a process-owned tree from the exact authenticated capture bytes."""

    destination_identity = path_directory_identity(destination)
    if (
        expected_destination_identity is not None
        and destination_identity != expected_destination_identity
    ):
        raise ValueError(
            "capture snapshot root changed before materialization"
        )
    for relative, value in sorted(captured_files.items()):
        target = destination / relative
        normalized = captured_relative_path(target, destination)
        if normalized != relative:
            raise ValueError(f"invalid captured artifact path: {relative}")
        anchor = open_anchored_directory(
            target.parent,
            destination,
            create=True,
        )
        descriptor: int | None = None
        try:
            if anchor.boundary_identity != destination_identity:
                raise ValueError(
                    "capture snapshot boundary was replaced during creation"
                )
            if not anchored_namespace_matches(anchor):
                raise ValueError(
                    "capture snapshot namespace changed during creation"
                )
            if anchor.descriptor is None:
                if os.path.lexists(target):
                    status = os.lstat(target)
                    if path_is_link_or_reparse(status):
                        raise ValueError(
                            f"capture snapshot target is a link: {target}"
                        )
                    raise FileExistsError(target)
                descriptor = os.open(
                    target,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_BINARY", 0),
                    0o600,
                )
            else:
                descriptor = os.open(
                    target.name,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=anchor.descriptor,
                )
            offset = 0
            while offset < len(value):
                offset += os.write(descriptor, value[offset:])
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            if not anchored_namespace_matches(anchor):
                raise ValueError(
                    "capture snapshot namespace changed during write"
                )
        finally:
            if descriptor is not None:
                os.close(descriptor)
            # Snapshot consumers may retain a concurrent renamer. Do not
            # pathname-delete an exposed entry after a failed identity check.
            close_anchored_directory(anchor)


def load_run(
    root: Path,
    repo_root: Path,
    side: str,
    skill: str,
    run: str,
    *,
    side_dir: str | None = None,
) -> RunArtifact:
    run_dir = root / (side_dir or side) / skill / run
    artifact = RunArtifact(side=side, skill=skill, run=run, run_dir=run_dir, load_errors=[], validators=[])
    if not confined_path(run_dir, root):
        artifact.errors().append(
            f"run directory escapes benchmark root or traverses a symlink: {run_dir}"
        )
        return artifact
    if not run_dir.is_dir():
        artifact.errors().append(f"missing run directory: {run_dir}")
        return artifact

    captured_files, capture_errors = load_capture_manifest(run_dir)
    artifact.captured_files = captured_files
    artifact.errors().extend(capture_errors)
    if capture_errors:
        return artifact

    summary_path, errors = find_summary(run_dir, captured_files)
    artifact.summary_path = summary_path
    artifact.errors().extend(errors)
    if summary_path is None:
        return artifact
    if error := captured_file_error(
        summary_path,
        run_dir,
        captured_files,
        "run summary",
    ):
        artifact.errors().append(error)
        return artifact

    try:
        artifact.summary = captured_json(
            summary_path, run_dir, captured_files
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        artifact.errors().append(f"failed to read summary: {error}")
        return artifact

    validation_path, validation_errors = find_validation(
        run_dir, captured_files
    )
    artifact.errors().extend(validation_errors)
    if validation_path is not None:
        validation_error = captured_file_error(
            validation_path,
            run_dir,
            captured_files,
            "validation result",
        )
        if validation_error:
            artifact.errors().append(validation_error)
            return artifact
        try:
            validation = captured_json(
                validation_path, run_dir, captured_files
            )
            result = expected_result(validation, skill)
            declared_skill = resolve_recorded_path(
                result.get("skill_path"),
                repo_root,
                boundary=repo_root,
            )
            if declared_skill is None:
                raise ValueError(
                    "validation skill_path is outside the benchmark repository"
                )
            expected = (
                declared_skill
                if declared_skill.name == "SKILL.md"
                else declared_skill / "SKILL.md"
            )
            skill_snapshot = read_skill_tree_snapshot(expected)
            provenance, task, provenance_errors = load_run_provenance(
                run_dir,
                summary_path,
                validation_path,
                validation,
                repo_root,
                skill,
                captured_files,
                skill_snapshot=skill_snapshot,
            )
            artifact.provenance = provenance
            artifact.task = task
            artifact.errors().extend(provenance_errors)
            skill_record = provenance.get("skill")
            staged_path = (
                skill_record.get("staged_path")
                if isinstance(skill_record, dict)
                and skill_record.get("staged_path_verified") is True
                and isinstance(skill_record.get("staged_path"), str)
                else None
            )
            artifact.errors().extend(
                validate_skill_load(
                    run_dir,
                    summary_path,
                    expected,
                    skill_snapshot,
                    staged_path,
                    captured_files,
                )
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            artifact.errors().append(f"failed to verify run provenance: {error}")

    artifact.report_path = summary_path.parent / "service/.observe" / SKILL_REPORTS[skill]
    report_error = captured_file_error(
        artifact.report_path,
        run_dir,
        captured_files,
        "primary report",
    )
    if report_error:
        artifact.errors().append(report_error)
        return artifact

    observe_dir = artifact.report_path.parent
    output_candidates = {
        observe_dir / "otel.md",
        observe_dir / "otel-audit.json",
        observe_dir / "otel-selection.json",
        observe_dir / "otel-instrumentation.md",
        observe_dir / "otel-instrumentation.json",
        observe_dir / "otel-verify.md",
        observe_dir / "otel-verify.json",
        observe_dir / "otel.html",
        observe_dir / "otel-instrumentation.html",
        observe_dir / "tmp/otel-verify-expected-items.txt",
    }
    output_errors = []
    for path in sorted(output_candidates):
        relative = captured_relative_path(path, run_dir)
        if relative is None:
            output_errors.append(
                f"preserved report artifact escapes run root: {path}"
            )
    artifact.errors().extend(output_errors)
    if output_errors:
        return artifact

    if artifact.provenance is not None:
        artifact.provenance["outputs"] = {
            filename: captured_file_record(
                observe_dir / filename, run_dir, captured_files
            )
            for filename in sorted(
                {
                    SKILL_REPORTS[skill],
                    CANONICAL_HTML_REPORTS[skill],
                    *CANONICAL_FLOW_REPORTS[skill],
                }
            )
            if captured_relative_path(observe_dir / filename, run_dir)
            in captured_files
        }
    canonical_json_projection: dict[str, object] = {}
    for filename in CANONICAL_FLOW_REPORTS[skill]:
        path = observe_dir / filename
        relative = captured_relative_path(path, run_dir)
        if relative not in captured_files:
            continue
        try:
            canonical_json_projection[filename] = load_json_bytes(
                captured_files[relative], str(path)
            )
        except (ValueError, json.JSONDecodeError) as error:
            artifact.errors().append(
                f"failed to load canonical JSON {path}: {error}"
            )
    if canonical_json_projection:
        artifact.canonical_json_projection = canonical_json_projection
        artifact.canonical_json_facts = flatten_facts(canonical_json_projection)

    snapshot_workspace = retained_workspace("otel-benchmark-capture-")
    snapshot_root = snapshot_workspace.path
    try:
        materialize_capture_snapshot(
            snapshot_root,
            captured_files,
            expected_destination_identity=snapshot_workspace.identity,
        )
        snapshot_workspace.verify_files(
            captured_files, "after authenticated materialization"
        )
        report_relative = captured_relative_path(
            artifact.report_path, run_dir
        )
        if report_relative is None:
            raise ValueError("primary report escapes run root")
        snapshot_report = snapshot_root / report_relative
        expected_report = captured_files.get(report_relative)
        if expected_report is None:
            raise ValueError("primary report is absent from authenticated capture")
        if snapshot_workspace.read_bytes(
            snapshot_report, "before report canonicalization"
        ) != expected_report:
            raise ValueError(
                "primary report differs from authenticated capture before canonicalization"
            )
        projection = CANONICALIZERS[skill](snapshot_report)
        snapshot_workspace.require_current("after report canonicalization")
        if snapshot_workspace.read_bytes(
            snapshot_report, "after report canonicalization"
        ) != expected_report:
            raise ValueError(
                "primary report differs from authenticated capture after canonicalization"
            )
        artifact.projection = projection
        artifact.facts = flatten_facts(projection)
        original_report_path = artifact.report_path
        artifact.report_path = snapshot_report
        try:
            validators = validate_run(
                repo_root, artifact, snapshot_workspace
            )
        finally:
            artifact.report_path = original_report_path
        snapshot_workspace.verify_files(
            captured_files, "after report validation"
        )
        artifact.validators = validators
    except (OSError, ValueError, KeyError) as error:
        artifact.errors().append(
            f"failed to consume authenticated report snapshot: {error}"
        )
    finally:
        snapshot_workspace.close()
    return artifact


def overall_validator_status(results: list[dict[str, object]]) -> str:
    statuses = {str(result["status"]) for result in results}
    if statuses & {"failed", "error", "missing"}:
        return "failed"
    if "passed" in statuses:
        return "passed"
    return "not_applicable"


def run_payload(artifact: RunArtifact) -> dict[str, object]:
    summary = artifact.summary or {}
    metrics = {metric: summary.get(metric) for metric in METRICS}
    errors = list(artifact.errors())
    for metric, value in metrics.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"missing or non-numeric required metric: {metric}")
    summary_errors = summary.get("errors", [])
    if isinstance(summary_errors, list):
        errors.extend(str(error) for error in summary_errors)
    else:
        errors.append("summary.errors must be a list when present")
    exit_code = summary.get("exit_code")
    if exit_code not in (None, 0):
        errors.append(f"agent exit_code={exit_code}")
    return {
        "run": artifact.run,
        "run_dir": str(artifact.run_dir),
        "summary_path": None if artifact.summary_path is None else str(artifact.summary_path),
        "report_path": None if artifact.report_path is None else str(artifact.report_path),
        "exit_code": exit_code,
        "metrics": metrics,
        "validators": artifact.validator_results(),
        "validator_status": overall_validator_status(artifact.validator_results()),
        "markdown_projection_sha256": (
            None
            if artifact.projection is None
            else canonical_hash(artifact.projection)
        ),
        "markdown_fact_count": 0 if artifact.facts is None else len(artifact.facts),
        "canonical_json_sha256": (
            None
            if artifact.canonical_json_projection is None
            else canonical_hash(artifact.canonical_json_projection)
        ),
        "canonical_json_fact_count": (
            0
            if artifact.canonical_json_facts is None
            else len(artifact.canonical_json_facts)
        ),
        "provenance": artifact.provenance,
        "errors": errors,
    }


def pairwise_stability(
    artifacts: list[RunArtifact],
    projection_attribute: str,
    facts_attribute: str,
) -> dict[str, object]:
    usable = [
        artifact
        for artifact in artifacts
        if getattr(artifact, projection_attribute) is not None
        and getattr(artifact, facts_attribute) is not None
    ]
    pairs = []
    for left, right in itertools.combinations(usable, 2):
        left_projection = getattr(left, projection_attribute)
        right_projection = getattr(right, projection_attribute)
        left_facts = getattr(left, facts_attribute)
        right_facts = getattr(right, facts_attribute)
        pairs.append(
            {
                "left": left.run,
                "right": right.run,
                "exact": left_projection == right_projection,
                "overlap": jaccard(left_facts or set(), right_facts or set()),
            }
        )
    return {
        "pair_count": len(pairs),
        "exact_pairs": sum(1 for pair in pairs if pair["exact"]),
        "overlap": metric_summary(float(pair["overlap"]) for pair in pairs),
        "pairs": pairs,
    }


def consensus_facts(
    artifacts: list[RunArtifact], facts_attribute: str
) -> set[str]:
    fact_sets = [
        getattr(artifact, facts_attribute)
        for artifact in artifacts
        if getattr(artifact, facts_attribute) is not None
    ]
    if not fact_sets:
        return set()
    return set.intersection(*(set(facts) for facts in fact_sets))


def compare_projections(
    before: list[RunArtifact],
    after: list[RunArtifact],
    projection_attribute: str,
    facts_attribute: str,
) -> dict[str, object]:
    before_by_run = {artifact.run: artifact for artifact in before}
    after_by_run = {artifact.run: artifact for artifact in after}
    paired = []
    for run in sorted(before_by_run.keys() & after_by_run.keys()):
        left = before_by_run[run]
        right = after_by_run[run]
        left_projection = getattr(left, projection_attribute)
        right_projection = getattr(right, projection_attribute)
        left_facts = getattr(left, facts_attribute)
        right_facts = getattr(right, facts_attribute)
        if (
            left_projection is None
            or right_projection is None
            or left_facts is None
            or right_facts is None
        ):
            continue
        paired.append(
            {
                "run": run,
                "exact": left_projection == right_projection,
                "overlap": jaccard(left_facts, right_facts),
                "before_sha256": canonical_hash(left_projection),
                "after_sha256": canonical_hash(right_projection),
            }
        )

    before_consensus = consensus_facts(before, facts_attribute)
    after_consensus = consensus_facts(after, facts_attribute)
    lost = sorted(before_consensus - after_consensus)
    added = sorted(after_consensus - before_consensus)
    return {
        "paired_count": len(paired),
        "exact_pairs": sum(1 for pair in paired if pair["exact"]),
        "paired_overlap": metric_summary(float(pair["overlap"]) for pair in paired),
        "pairs": paired,
        "before_internal_stability": pairwise_stability(
            before, projection_attribute, facts_attribute
        ),
        "after_internal_stability": pairwise_stability(
            after, projection_attribute, facts_attribute
        ),
        "consensus": {
            "before_fact_count": len(before_consensus),
            "after_fact_count": len(after_consensus),
            "shared_fact_count": len(before_consensus & after_consensus),
            "overlap": jaccard(before_consensus, after_consensus),
            "lost_facts": lost,
            "added_facts": added,
        },
    }


def compare_markdown_reports(
    before: list[RunArtifact], after: list[RunArtifact]
) -> dict[str, object]:
    return compare_projections(before, after, "projection", "facts")


def compare_canonical_json_reports(
    before: list[RunArtifact], after: list[RunArtifact]
) -> dict[str, object]:
    return compare_projections(
        before,
        after,
        "canonical_json_projection",
        "canonical_json_facts",
    )


def nested_value(value: object, *keys: str) -> object:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def authenticated_identity_digest(
    record: object,
    digest_key: str,
    *,
    allow_absent: bool = False,
) -> object:
    if not isinstance(record, dict) or record.get("verified") is not True:
        return None
    digest = record.get(digest_key)
    if isinstance(digest, str) and SHA256_PATTERN.fullmatch(digest):
        return digest
    if allow_absent and digest is None:
        return "__authenticated_absent__"
    return None


def provenance_identity(artifact: RunArtifact) -> dict[str, object]:
    provenance = artifact.provenance or {}
    fixture_tree_sha256 = authenticated_identity_digest(
        provenance.get("fixture"), "computed_tree_sha256"
    )
    shared_references_sha256 = authenticated_identity_digest(
        provenance.get("shared_references"),
        "computed_tree_sha256",
        allow_absent=True,
    )
    harness_sha256 = authenticated_identity_digest(
        provenance.get("harness"), "computed_tree_sha256"
    )
    run_configuration = provenance.get("run_configuration")
    behavioral_run_configuration_sha256 = None
    if isinstance(run_configuration, dict) and run_configuration.get("verified") is True:
        value = run_configuration.get("value")
        if isinstance(value, dict):
            behavioral_run_configuration_sha256 = canonical_hash(
                {key: item for key, item in value.items() if key != "run_id"}
            )
    return {
        "task_sha256": provenance.get("task_sha256"),
        "case_contract_sha256": provenance.get("case_contract_sha256"),
        "fixture_tree_sha256": fixture_tree_sha256,
        "definition_sha256": authenticated_identity_digest(
            provenance.get("definition"), "computed_sha256"
        ),
        "config_sha256": authenticated_identity_digest(
            provenance.get("config"), "computed_sha256", allow_absent=True
        ),
        "behavioral_run_configuration_sha256": behavioral_run_configuration_sha256,
        "shared_references_tree_sha256": shared_references_sha256,
        "harness_tree_sha256": harness_sha256,
    }


def skill_provenance_digest(artifact: RunArtifact) -> object:
    skill = (artifact.provenance or {}).get("skill")
    if isinstance(skill, dict) and skill.get("verified") is True:
        return skill.get("computed_tree_sha256")
    return None


def compare_provenance(
    before: list[RunArtifact], after: list[RunArtifact]
) -> dict[str, object]:
    before_by_run = {artifact.run: artifact for artifact in before}
    after_by_run = {artifact.run: artifact for artifact in after}
    pairs: list[dict[str, object]] = []
    identities: set[str] = set()
    for artifact in [*before, *after]:
        identity = provenance_identity(artifact)
        if all(value is not None for value in identity.values()):
            identities.add(canonical_json(identity))
    for run in sorted(before_by_run.keys() & after_by_run.keys()):
        before_identity = provenance_identity(before_by_run[run])
        after_identity = provenance_identity(after_by_run[run])
        pairs.append(
            {
                "run": run,
                "match": before_identity == after_identity,
                "before": before_identity,
                "after": after_identity,
            }
        )
    comparable = bool(pairs) and all(bool(pair["match"]) for pair in pairs)
    comparable = comparable and len(identities) == 1
    side_skill_digests = {
        "before": {
            skill_provenance_digest(artifact) for artifact in before
        },
        "after": {
            skill_provenance_digest(artifact) for artifact in after
        },
    }
    side_skill_comparable = all(
        None not in digests and len(digests) == 1
        for digests in side_skill_digests.values()
    )
    comparable = comparable and side_skill_comparable
    return {
        "comparable": comparable,
        "identity_count": len(identities),
        "skill_identity_count_by_side": {
            side: len(digests - {None})
            for side, digests in side_skill_digests.items()
        },
        "pairs": pairs,
    }


def side_payload(artifacts: list[RunArtifact]) -> dict[str, object]:
    metrics: dict[str, dict[str, float | int | None]] = {}
    for metric in METRICS:
        values = []
        for artifact in artifacts:
            if artifact.summary is None:
                continue
            value = artifact.summary.get(metric)
            if is_numeric_metric(value):
                values.append(value)
        metrics[metric] = metric_summary(values)
    validator_counts: dict[str, int] = {}
    for artifact in artifacts:
        status = overall_validator_status(artifact.validator_results())
        validator_counts[status] = validator_counts.get(status, 0) + 1
    return {
        "metrics": metrics,
        "validator_counts": validator_counts,
        "runs": [run_payload(artifact) for artifact in artifacts],
    }


def skill_payload(
    root: Path,
    repo_root: Path,
    skill: str,
    expected_runs: int,
    side_dirs: dict[str, str],
) -> dict[str, object]:
    names = [f"run{index}" for index in range(1, expected_runs + 1)]
    artifacts = {
        side: [
            load_run(root, repo_root, side, skill, name, side_dir=side_dirs[side])
            for name in names
        ]
        for side in SIDES
    }
    sides = {side: side_payload(artifacts[side]) for side in SIDES}
    performance = {}
    for metric in METRICS:
        before = sides["before"]["metrics"][metric]  # type: ignore[index]
        after = sides["after"]["metrics"][metric]  # type: ignore[index]
        performance[metric] = {
            "before": before,
            "after": after,
            **metric_delta(before, after),  # type: ignore[arg-type]
            "paired": paired_metric_analysis(
                artifacts["before"], artifacts["after"], metric
            ),
        }

    run_payloads = [payload for side in SIDES for payload in sides[side]["runs"]]  # type: ignore[index]
    provenance_comparison = compare_provenance(
        artifacts["before"], artifacts["after"]
    )
    complete = all(not payload["errors"] for payload in run_payloads)
    complete = complete and bool(provenance_comparison["comparable"])
    validators_ok = all(payload["validator_status"] == "passed" for payload in run_payloads)
    report_comparison = {
        "markdown": compare_markdown_reports(
            artifacts["before"], artifacts["after"]
        ),
        "canonical_json": compare_canonical_json_reports(
            artifacts["before"], artifacts["after"]
        ),
    }
    return {
        "skill": skill,
        "expected_runs_per_side": expected_runs,
        "complete": complete,
        "validators_ok": validators_ok,
        "performance": performance,
        "reports": report_comparison,
        "provenance": provenance_comparison,
        "sides": sides,
    }


def build_benchmark(
    root: Path,
    repo_root: Path,
    skills: list[str],
    expected_runs: int,
    side_dirs: dict[str, str] | None = None,
) -> dict[str, object]:
    side_dirs = side_dirs or {"before": "before", "after": "after"}
    skill_results = [skill_payload(root, repo_root, skill, expected_runs, side_dirs) for skill in skills]
    return {
        "schema_version": 2,
        "benchmark_root": str(root),
        "repo_root": str(repo_root),
        "side_directories": side_dirs,
        "expected_runs_per_side": expected_runs,
        "complete": all(bool(result["complete"]) for result in skill_results),
        "validators_ok": all(bool(result["validators_ok"]) for result in skill_results),
        "skills": skill_results,
    }


def canonical_equality_satisfied(
    payload: dict[str, object], expected_runs: int
) -> bool:
    skills = payload.get("skills")
    if not isinstance(skills, list):
        return False
    for skill in skills:
        if not isinstance(skill, dict):
            return False
        reports = nested_value(skill, "reports", "canonical_json")
        if not isinstance(reports, dict):
            return False
        if (
            reports.get("paired_count") != expected_runs
            or reports.get("exact_pairs") != expected_runs
        ):
            return False
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Root containing before/ and after/ benchmark artifacts")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository containing the current report validators",
    )
    parser.add_argument("--expected-runs", type=int, default=3)
    parser.add_argument("--before-side", default="before", help="Directory name for the baseline side")
    parser.add_argument("--after-side", default="after", help="Directory name for the treatment side")
    parser.add_argument("--skills", nargs="+", choices=sorted(SKILL_REPORTS), default=list(SKILL_REPORTS))
    parser.add_argument("--output", type=Path, help="Also write the aggregate JSON to this path")
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Return success while captures are still missing or validators fail",
    )
    parser.add_argument(
        "--require-canonical-equality",
        action="store_true",
        help=(
            "Fail unless every paired before/after canonical JSON flow is "
            "exactly equal; Markdown projection equality is reported separately"
        ),
    )
    return parser.parse_args()


def write_aggregate_output(
    output: Path,
    rendered: str,
    *,
    benchmark_root: Path,
    repo_root: Path,
) -> None:
    lexical_output = output.expanduser().absolute()
    if lexical_output.is_symlink():
        raise ValueError(f"aggregate output must not be a symlink: {lexical_output}")
    lexical_boundaries = []
    for candidate in (benchmark_root, repo_root):
        boundary = candidate.absolute()
        try:
            lexical_output.relative_to(boundary)
        except ValueError:
            continue
        lexical_boundaries.append(boundary)
    if not lexical_boundaries:
        raise ValueError(
            "aggregate output must be inside the benchmark root or repository root"
        )
    boundary = lexical_boundaries[0]
    boundary_identity = path_directory_identity(boundary)
    if not confined_path(lexical_output, boundary):
        raise ValueError(
            f"aggregate output escapes or traverses a symlink below {boundary}: {lexical_output}"
        )
    ensure_anchored_directory(
        lexical_output.parent,
        boundary=boundary,
        expected_boundary_identity=boundary_identity,
    )
    if not confined_path(lexical_output.parent, boundary):
        raise ValueError(
            f"aggregate output parent traverses a symlink: {lexical_output.parent}"
        )
    if lexical_output.is_symlink():
        raise ValueError(f"aggregate output must not be a symlink: {lexical_output}")
    atomic_text_write(
        lexical_output,
        rendered,
        boundary=boundary,
        expected_boundary_identity=boundary_identity,
    )


def main() -> int:
    args = parse_args()
    if args.expected_runs < 1:
        raise SystemExit("--expected-runs must be positive")
    lexical_root = args.root.expanduser().absolute()
    lexical_repo_root = args.repo_root.expanduser().absolute()
    root = args.root.expanduser().resolve()
    repo_root = args.repo_root.expanduser().resolve()
    payload = build_benchmark(
        root,
        repo_root,
        args.skills,
        args.expected_runs,
        {"before": args.before_side, "after": args.after_side},
    )
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        write_aggregate_output(
            args.output,
            rendered,
            benchmark_root=lexical_root,
            repo_root=lexical_repo_root,
        )
    print(rendered, end="")

    if args.allow_incomplete:
        return 0
    if not payload["complete"] or not payload["validators_ok"]:
        return 1
    if args.require_canonical_equality:
        if not canonical_equality_satisfied(payload, args.expected_runs):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
