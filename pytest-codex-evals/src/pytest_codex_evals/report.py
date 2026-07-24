from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError

from .ab import SKILL_COMPANIONS
from .definitions import (
    CaseResult,
    GradeCheckResult,
    RubricEvalCase,
    RuntimeEvalCase,
    SanityEvalCase,
    SideResult,
    ValidationResult,
)
from .backends import (
    atomic_text_write,
    ensure_anchored_directory,
    path_directory_identity,
    read_anchored_regular_bytes,
    read_regular_text,
)
from .eval_contracts import (
    case_contract_sha256,
    case_from_definition,
    case_task_sha256,
    load_eval_definition,
)
from .eval_files import eval_file_layout, iter_eval_files
from .reports import ReportTemplate, template_for_kind
from .runner import tree_sha256


LIVE_MODES = {"with_skill", "with_baseline", "ab"}
SIDE_ATTRS = {
    "with_skill": "with_skill",
    "with_baseline": "baseline",
}
RAW_RUNS_DIR = "runs"
PROVENANCE_FILE = ".codex-eval-provenance.json"
CAPTURE_MANIFEST_FILE = ".codex-eval-capture.json"
SHA256_LENGTH = 64
AUTHENTICATED_FILES_KEY = "_authenticated_files"


def write_session_results(runs: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for run in runs:
        if not run.get("results"):
            continue
        key = (str(run["repo_root"]), str(run["run_root"]), run["skill"])
        grouped.setdefault(key, []).append(run)

    for run_group in grouped.values():
        first = run_group[0]
        repo_root = first["repo_root"]
        run_root = first["run_root"]
        skill = first["skill"]
        ensure_safe_output_directory(run_root, repo_root)
        run_files = []
        for run in sorted(run_group, key=lambda item: (item["eval_kind"], item["mode"])):
            path = write_raw_run_result(
                repo_root=run["repo_root"],
                run_root=run["run_root"],
                skill=run["skill"],
                mode=run["mode"],
                eval_kind=run["eval_kind"],
                results=run["results"],
                metadata=run.get("metadata", {}),
            )
            run_files.append(relative_to_run_root(run_root, path))
        write_run_manifest(repo_root, run_root, skill, run_files)
        write_capture_manifest(run_root)


def write_capture_manifest(run_root: Path) -> Path:
    """Seal harness and agent artifacts before reporting or copying a run."""

    if run_root.is_symlink() or not run_root.is_dir():
        raise ValueError(f"capture run root must be a real directory: {run_root}")
    run_root_identity = path_directory_identity(run_root)
    records = [
        capture_file_record(
            run_root,
            path,
            expected_run_root_identity=run_root_identity,
        )
        for path in capture_files(run_root)
    ]
    payload = {
        "schema_version": 1,
        "files": records,
    }
    path = run_root / CAPTURE_MANIFEST_FILE
    atomic_text_write(
        path,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        boundary=run_root,
        expected_boundary_identity=run_root_identity,
    )
    return path


def verify_capture_manifest(run_root: Path) -> dict[str, bytes]:
    """Verify every sealed artifact and retain the exact authenticated bytes."""

    run_root_identity = path_directory_identity(run_root)
    manifest_path = run_root / CAPTURE_MANIFEST_FILE
    if not path_is_within(manifest_path, run_root) or manifest_path.is_symlink():
        raise ValueError(f"capture manifest is unsafe: {manifest_path}")
    try:
        manifest = json.loads(
            read_regular_text(
                manifest_path,
                boundary=run_root,
                expected_boundary_identity=run_root_identity,
            )
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"capture manifest is unreadable: {error}") from error
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("capture manifest schema is unsupported")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ValueError("capture manifest files must be a list")
    authenticated: dict[str, bytes] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("capture manifest file entry must be an object")
        value = entry.get("path")
        digest = entry.get("sha256")
        if not isinstance(value, str) or not value or not valid_sha256(digest):
            raise ValueError("capture manifest file entry is invalid")
        if value in authenticated:
            raise ValueError(f"capture manifest contains duplicate path: {value}")
        path = confined_run_artifact(run_root, value)
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"captured artifact is missing or unsafe: {value}")
        current_bytes = regular_file_bytes(
            path,
            boundary=run_root,
            expected_boundary_identity=run_root_identity,
        )
        current_digest = hashlib.sha256(current_bytes).hexdigest()
        if current_digest != digest:
            raise ValueError(f"captured artifact changed after capture: {value}")
        authenticated[value] = current_bytes
    current_paths = {
        path.relative_to(run_root).as_posix() for path in capture_files(run_root)
    }
    sealed_paths = set(authenticated)
    if added := current_paths - sealed_paths:
        raise ValueError(
            "unsealed artifacts were added after capture: "
            + ", ".join(sorted(added))
        )
    if missing := sealed_paths - current_paths:
        raise ValueError(
            "sealed artifacts are missing after capture: "
            + ", ".join(sorted(missing))
        )
    return authenticated


def capture_files(run_root: Path) -> list[Path]:
    files: list[Path] = []
    for name in ("cases", "results", "runs"):
        root = run_root / name
        if not root.exists():
            continue
        if root.is_symlink() or not root.is_dir():
            raise ValueError(f"capture artifact root must be a real directory: {root}")
        for directory, dirnames, filenames in os.walk(root, followlinks=False):
            parent = Path(directory)
            retained: list[str] = []
            for directory_name in sorted(dirnames):
                candidate = parent / directory_name
                if directory_name == ".agents":
                    continue
                if candidate.is_symlink():
                    raise ValueError(
                        f"capture artifact tree must not contain symlinks: {candidate}"
                    )
                retained.append(directory_name)
            dirnames[:] = retained
            for filename in sorted(filenames):
                candidate = parent / filename
                if candidate.is_symlink() or not candidate.is_file():
                    raise ValueError(
                        f"capture artifact must be a regular file: {candidate}"
                    )
                files.append(candidate)
    run_manifest = run_root / "run.json"
    if run_manifest.exists():
        if run_manifest.is_symlink() or not run_manifest.is_file():
            raise ValueError(f"run manifest must be a regular file: {run_manifest}")
        files.append(run_manifest)
    return sorted(set(files), key=lambda path: path.relative_to(run_root).as_posix())


def capture_file_record(
    run_root: Path,
    path: Path,
    *,
    expected_run_root_identity: tuple[int, int] | None = None,
) -> dict[str, object]:
    if not path_is_within(path, run_root):
        raise ValueError(f"capture artifact escapes run root: {path}")
    captured = regular_file_bytes(
        path,
        boundary=run_root,
        expected_boundary_identity=expected_run_root_identity,
    )
    return {
        "path": path.relative_to(run_root).as_posix(),
        "sha256": hashlib.sha256(captured).hexdigest(),
        "size": len(captured),
    }


def regular_file_sha256(path: Path) -> str:
    return hashlib.sha256(regular_file_bytes(path)).hexdigest()


def regular_file_bytes(
    path: Path,
    *,
    boundary: Path | None = None,
    expected_boundary_identity: tuple[int, int] | None = None,
) -> bytes:
    try:
        return read_anchored_regular_bytes(
            path,
            boundary=boundary or path.parent,
            expected_boundary_identity=expected_boundary_identity,
        )
    except OSError as error:
        raise ValueError(f"artifact must be a stable regular file: {path}") from error


def write_raw_run_result(
    *,
    repo_root: Path,
    run_root: Path,
    skill: str,
    mode: str,
    eval_kind: str,
    results: list[ValidationResult] | list[CaseResult],
    metadata: dict[str, Any] | None = None,
) -> Path:
    ensure_safe_output_directory(run_root, repo_root)
    run_root_identity = path_directory_identity(run_root)
    result_paths: dict[str, dict[str, str]] = {}
    if mode in LIVE_MODES:
        result_paths = write_live_result_jsons(repo_root, run_root, mode, results)  # type: ignore[arg-type]

    payload = {
        "schema_version": 1,
        "mode": mode,
        "eval_kind": eval_kind,
        "repo_root": str(repo_root),
        "run_root": str(run_root),
        "skill": skill,
        "metadata": report_metadata(skill, mode, run_root, metadata),
        "result_paths": result_paths,
        "results": [result.model_dump(mode="json") for result in results],
    }
    path = raw_run_path(run_root, eval_kind, mode)
    ensure_safe_output_directory(path.parent, run_root)
    atomic_text_write(
        path,
        json.dumps(payload, indent=2),
        boundary=run_root,
        expected_boundary_identity=run_root_identity,
    )
    return path


def raw_run_path(run_root: Path, eval_kind: str, mode: str) -> Path:
    name = "validation.json" if mode == "validation" else f"{safe_name(eval_kind)}-{safe_name(mode)}.json"
    return run_root / RAW_RUNS_DIR / name


def write_run_manifest(repo_root: Path, run_root: Path, skill: str, run_files: list[str]) -> None:
    manifest = {
        "schema_version": 1,
        "repo_root": str(repo_root),
        "run_root": str(run_root),
        "run_id": run_root.name,
        "skill": skill,
        "runs": run_files,
    }
    ensure_safe_output_directory(run_root, repo_root)
    run_root_identity = path_directory_identity(run_root)
    atomic_text_write(
        run_root / "run.json",
        json.dumps(manifest, indent=2),
        boundary=run_root,
        expected_boundary_identity=run_root_identity,
    )


def render_reports_for_run_root(
    run_root: Path,
    kind: str,
    *,
    skill: str | None = None,
    output_dir: Path | None = None,
) -> tuple[Path, Path]:
    payloads = load_raw_run_payloads(run_root)
    if skill:
        payloads = [payload for payload in payloads if payload.get("skill") == skill]
    if not payloads:
        raise ValueError(f"no raw eval results found in {run_root}")

    repo_root = Path(str(payloads[0]["repo_root"]))
    resolved_skill = skill or str(payloads[0]["skill"])
    if kind == "validation":
        benchmark = validation_benchmark_from_payloads(repo_root, run_root, resolved_skill, payloads)
        report = render_validation_report(resolved_skill, benchmark)
    else:
        benchmark = kind_benchmark_from_payloads(repo_root, run_root, resolved_skill, kind, payloads)
        report = render_kind_report(resolved_skill, benchmark)
    return write_report_outputs(repo_root, run_root, resolved_skill, kind, benchmark, report, output_dir)


def load_raw_run_payloads(run_root: Path) -> list[dict[str, Any]]:
    authenticated_files = verify_capture_manifest(run_root)
    manifest_bytes = authenticated_files.get("run.json")
    if manifest_bytes is None:
        raise ValueError("capture manifest does not authenticate run.json")
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as error:
        raise ValueError(f"run manifest is unreadable: {error}") from error
    run_entries = manifest.get("runs", [])
    if not isinstance(run_entries, list) or not all(
        isinstance(entry, str) and entry for entry in run_entries
    ):
        raise ValueError("run manifest entries must be non-empty paths")
    if len(run_entries) != len(set(run_entries)):
        raise ValueError("run manifest contains duplicate entries")
    payloads = []
    for entry in run_entries:
        path = confined_run_artifact(run_root, entry)
        relative = path.relative_to(run_root.absolute()).as_posix()
        captured = authenticated_files.get(relative)
        if captured is None:
            raise ValueError(f"raw run result is not authenticated: {entry}")
        try:
            payload = json.loads(captured)
        except json.JSONDecodeError as error:
            raise ValueError(f"raw run result is unreadable: {entry}: {error}") from error
        if not isinstance(payload, dict):
            raise ValueError(f"raw run result must be an object: {entry}")
        payload[AUTHENTICATED_FILES_KEY] = authenticated_files
        payloads.append(payload)
    return payloads


def confined_run_artifact(run_root: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError(f"run manifest entry must be relative: {value}")
    candidate = (run_root / candidate).absolute()
    if not path_is_within(candidate, run_root):
        raise ValueError(f"run manifest entry escapes run root: {value}")
    relative = candidate.relative_to(run_root.absolute())
    current = run_root.absolute()
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise ValueError(f"run manifest entry traverses a symlink: {value}")
    return candidate


def captured_relative_path(run_root: Path, value: str) -> str:
    """Normalize an artifact reference without consulting mutable path contents."""

    root = Path(os.path.abspath(run_root))
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = Path(os.path.abspath(candidate))
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"artifact escapes run root: {value}") from error
    if not relative.parts:
        raise ValueError(f"artifact does not name a file: {value}")
    return relative.as_posix()


def validation_benchmark_from_payloads(
    repo_root: Path,
    run_root: Path,
    skill: str,
    payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    validation_payloads = [payload for payload in payloads if payload.get("mode") == "validation"]
    if not validation_payloads:
        raise ValueError(f"no validation results found in {run_root}")
    results: list[ValidationResult] = []
    metadata: dict[str, Any] = {}
    for payload in validation_payloads:
        metadata = payload.get("metadata", metadata)
        results.extend(ValidationResult.model_validate(item) for item in payload.get("results", []))
    return build_validation_benchmark(repo_root, skill, results, report_metadata(skill, "validation", run_root, metadata))


def kind_benchmark_from_payloads(
    repo_root: Path,
    run_root: Path,
    skill: str,
    kind: str,
    payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    live_payloads = [
        payload
        for payload in payloads
        if payload.get("mode") in LIVE_MODES and normalize_kind(str(payload.get("eval_kind", ""))) == kind
    ]
    if not live_payloads:
        raise ValueError(f"no {kind} live results found in {run_root}")
    return build_kind_benchmark(repo_root, run_root, skill, kind, live_payloads)


def build_kind_benchmark(
    repo_root: Path,
    run_root: Path,
    skill: str,
    kind: str,
    live_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    evals = []
    failures = []
    metadata_sources = []
    observed_prompt_ids: set[str] = set()
    all_results: list[CaseResult] = []
    run_captures: list[
        tuple[CaseResult, dict[str, Any], dict[str, bytes]]
    ] = []
    capture_keys: set[tuple[str, str]] = set()
    scope_errors: list[str] = []
    for payload in sorted(live_payloads, key=lambda item: str(item.get("mode", ""))):
        mode = str(payload["mode"])
        payload_metadata = payload.get("metadata", {})
        if not isinstance(payload_metadata, dict):
            payload_metadata = {}
            scope_errors.append(f"{mode} payload metadata must be an object")
        authenticated_files = payload.get(AUTHENTICATED_FILES_KEY)
        if not isinstance(authenticated_files, dict) or not all(
            isinstance(path, str) and isinstance(value, bytes)
            for path, value in authenticated_files.items()
        ):
            authenticated_files = {}
            scope_errors.append(f"{mode} payload lacks authenticated capture bytes")
        results = [CaseResult.model_validate(item) for item in payload.get("results", [])]
        metadata_sources.append(
            captured_payload_metadata(run_root, results, authenticated_files) or {}
        )
        all_results.extend(results)
        if payload_metadata.get("mode") != mode:
            scope_errors.append(f"{mode} payload metadata mode does not match")
        if normalize_kind(str(payload_metadata.get("eval_kind", ""))) != kind:
            scope_errors.append(f"{mode} payload metadata eval kind does not match")
        if payload_metadata.get("skill") != skill:
            scope_errors.append(f"{mode} payload metadata skill does not match")
        for result in results:
            capture_key = (mode, result.id)
            if capture_key in capture_keys:
                scope_errors.append(
                    f"duplicate captured result for mode {mode}: {result.id}"
                )
            capture_keys.add(capture_key)
            scope_errors.extend(validate_mode_sides(mode, result))
            run_captures.append((result, payload_metadata, authenticated_files))
        observed_prompt_ids.update(result.id for result in results)
        result_paths = payload.get("result_paths", {})
        for base_id, group in grouped_case_results(results).items():
            item = aggregate_kind_case_group(
                kind, group, run_root, authenticated_files
            )
            item["mode"] = mode
            item["result_paths"] = result_paths.get(base_id, {})
            evals.append(item)
        failures.extend(collect_kind_failures(results, kind, mode))

    metadata = kind_report_metadata(skill, run_root, kind, metadata_sources)
    metadata["scope"] = report_scope_metadata(
        repo_root,
        skill,
        kind,
        observed_prompt_ids,
        run_results=all_results,
        run_captures=run_captures,
        run_root=run_root,
        additional_errors=scope_errors,
    )
    return {
        "schema_version": 1,
        "kind": kind,
        "mode": metadata["mode"],
        "skill": skill,
        "metadata": metadata,
        "summary": {
            "eval_count": len(evals),
            "prompt_count": sum(int(item["prompt_count"]) for item in evals),
            "failure_count": len(failures),
            "with_skill": aggregate_kind_evals(evals, "with_skill", kind),
            "with_baseline": aggregate_kind_evals(evals, "with_baseline", kind),
        },
        "evals": evals,
        "failures": failures,
    }


def aggregate_kind_case_group(
    kind: str,
    group: list[CaseResult],
    run_root: Path,
    authenticated_files: dict[str, bytes],
) -> dict[str, Any]:
    first = group[0]
    return {
        "id": first.base_id,
        "case": f"{first.language}/{first.service}",
        "language": first.language,
        "service": first.service,
        "prompt_count": len(group),
        "prompts": [result.prompt_id for result in group],
        "with_skill": aggregate_kind_side(
            kind, group, "with_skill", run_root, authenticated_files
        ),
        "with_baseline": aggregate_kind_side(
            kind, group, "with_baseline", run_root, authenticated_files
        ),
    }


def aggregate_kind_side(
    kind: str,
    results: list[CaseResult],
    side_key: str,
    run_root: Path,
    authenticated_files: dict[str, bytes],
) -> dict[str, Any] | None:
    sides = [side for result in results if (side := side_for_key(result, side_key)) is not None]
    if not sides:
        return None
    summary: dict[str, Any] = {
        "prompt_count": len(sides),
        "command_count": sum(side.command_count for side in sides),
        "duration_seconds": round(sum(side.duration_seconds for side in sides), 3),
        "agent_duration_seconds": round(sum(side.agent_duration_seconds for side in sides), 3),
        "tokens": sum(side.tokens for side in sides),
        "agent_tokens": sum(side.agent_tokens for side in sides),
        "error_count": sum(len(side.errors) for side in sides),
    }
    if kind == "rubric":
        rubric = [
            grade
            for side in sides
            if (
                grade := load_rubric_grade(
                    side, run_root, authenticated_files
                )
            )
            is not None
        ]
        rubric_total = sum(int(grade["total"]) for grade in rubric)
        rubric_passed = sum(int(grade["passed"]) for grade in rubric)
        scores = [int(grade["score"]) for grade in rubric if isinstance(grade.get("score"), int)]
        summary["rubric"] = None if not rubric else {"passed": rubric_passed, "total": rubric_total, "average_score": average(scores) if scores else None}
        summary["rubric_tokens"] = sum(side.rubric_tokens for side in sides)
        summary["rubric_duration_seconds"] = round(sum(side.rubric_duration_seconds for side in sides), 3)
    else:
        summary["checks"] = aggregate_check_category(sides, kind)
    return summary


def aggregate_kind_evals(evals: list[dict[str, Any]], side_key: str, kind: str) -> dict[str, Any] | None:
    sides = [item[side_key] for item in evals if item.get(side_key) is not None]
    if not sides:
        return None
    summary: dict[str, Any] = {
        "prompt_count": sum(int(side["prompt_count"]) for side in sides),
        "command_count": sum(int(side["command_count"]) for side in sides),
        "duration_seconds": round(sum(float(side["duration_seconds"]) for side in sides), 3),
        "agent_duration_seconds": round(sum(float(side["agent_duration_seconds"]) for side in sides), 3),
        "tokens": sum(int(side["tokens"]) for side in sides),
        "agent_tokens": sum(int(side["agent_tokens"]) for side in sides),
        "error_count": sum(int(side["error_count"]) for side in sides),
    }
    if kind == "rubric":
        rubric_summaries = [side["rubric"] for side in sides if side.get("rubric") is not None]
        scores = [float(rubric["average_score"]) for rubric in rubric_summaries if rubric.get("average_score") is not None]
        summary["rubric"] = None if not rubric_summaries else {
            "passed": sum(int(rubric["passed"]) for rubric in rubric_summaries),
            "total": sum(int(rubric["total"]) for rubric in rubric_summaries),
            "average_score": average(scores) if scores else None,
        }
        summary["rubric_tokens"] = sum(int(side.get("rubric_tokens") or 0) for side in sides)
        summary["rubric_duration_seconds"] = round(sum(float(side.get("rubric_duration_seconds") or 0.0) for side in sides), 3)
    else:
        checks = [side["checks"] for side in sides]
        summary["checks"] = {
            "passed": sum(int(item["passed"]) for item in checks),
            "total": sum(int(item["total"]) for item in checks),
            "skipped": sum(int(item["skipped"]) for item in checks),
        }
    return summary


def collect_kind_failures(results: list[CaseResult], kind: str, mode: str) -> list[dict[str, str]]:
    failures = []
    for failure in collect_failures(results):
        if failure.get("category") != kind:
            continue
        with_mode = dict(failure)
        with_mode["mode"] = mode
        failures.append(with_mode)
    return failures


def kind_report_metadata(skill: str, run_root: Path, kind: str, metadata_sources: list[dict[str, Any]]) -> dict[str, Any]:
    modes = sorted({str(meta.get("mode") or "-") for meta in metadata_sources if meta.get("mode")}) or ["-"]
    agent_models = sorted({str(meta.get("agent_model") or "-") for meta in metadata_sources if meta.get("agent_model")}) or ["-"]
    judge_models = sorted({str(meta.get("judge_model") or "-") for meta in metadata_sources if meta.get("judge_model")}) or ["-"]
    config_paths = sorted({str(meta.get("config_path") or "-") for meta in metadata_sources if meta.get("config_path")}) or ["-"]
    return {
        "mode": ", ".join(modes),
        "eval_kind": kind,
        "skill": skill,
        "run_id": run_root.name,
        "agent_model": ", ".join(agent_models),
        "judge_model": ", ".join(judge_models),
        "rubric_enabled": any(bool(meta.get("rubric_enabled")) for meta in metadata_sources),
        "runtime_enabled": any(bool(meta.get("runtime_enabled")) for meta in metadata_sources),
        "workers": ", ".join(sorted({str(meta.get("workers") or "-") for meta in metadata_sources if meta.get("workers")})) or "-",
        "config_path": ", ".join(config_paths),
    }


def expected_prompt_contracts(
    repo_root: Path, skill: str, kind: str
) -> tuple[dict[str, dict[str, Any]] | None, list[str]]:
    """Discover the current complete prompt set for a skill/report kind."""

    eval_root = repo_root / "evals" if (repo_root / "evals").is_dir() else repo_root
    expected: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for path in iter_eval_files(eval_root):
        layout = eval_file_layout(path)
        if layout is None:
            continue
        if kind != "validation" and layout.role != kind:
            continue
        try:
            definition_bytes = path.read_bytes()
            definition = load_eval_definition(
                path,
                definition_bytes=definition_bytes,
            )
        except (
            OSError,
            json.JSONDecodeError,
            JsonSchemaValidationError,
            PydanticValidationError,
            TypeError,
            ValueError,
        ) as error:
            errors.append(f"failed to inspect {path}: {error}")
            continue
        if definition.skill != skill:
            continue
        for prompt in definition.prompts:
            case = case_from_definition(definition, prompt, path)
            full_id = case.id
            if full_id in expected:
                errors.append(f"duplicate eval scope prompt {full_id}: {path}")
                continue
            expected[full_id] = {
                "path": str(path.resolve()),
                "sha256": hashlib.sha256(definition_bytes).hexdigest(),
                "fixture_path": str(
                    (definition.fixture_dir or layout.fixture_dir).resolve()
                ),
                "base_id": case.base_id,
                "language": case.language,
                "service": case.service,
                "eval_kind": case.kind,
                "task_sha256": case_task_sha256(case),
                "contract_sha256": case_contract_sha256(case),
                "sanity_check_count": (
                    len(case.checks)
                    if isinstance(case, SanityEvalCase)
                    else 0
                ),
                "rubric_check_count": (
                    len(case.rubric)
                    if isinstance(case, RubricEvalCase)
                    else 0
                ),
                "runtime_check_count": (
                    len(case.checks)
                    if isinstance(case, RuntimeEvalCase)
                    else 0
                ),
            }
    if errors:
        return None, errors
    if not expected:
        return None, [f"no {kind} eval definitions found for {skill}"]
    return expected, []


def expected_prompt_ids(
    repo_root: Path, skill: str, kind: str
) -> tuple[set[str] | None, list[str]]:
    contracts, errors = expected_prompt_contracts(repo_root, skill, kind)
    return (None if contracts is None else set(contracts), errors)


def report_scope_metadata(
    repo_root: Path,
    skill: str,
    kind: str,
    observed_prompt_ids: set[str],
    *,
    run_results: list[CaseResult] | None = None,
    run_captures: list[
        tuple[CaseResult, dict[str, Any], dict[str, bytes]]
    ] | None = None,
    run_root: Path | None = None,
    additional_errors: list[str] | None = None,
) -> dict[str, Any]:
    contracts, errors = expected_prompt_contracts(repo_root, skill, kind)
    if contracts is None:
        return {
            "status": "unknown",
            "selected_prompt_count": len(observed_prompt_ids),
            "expected_prompt_count": None,
            "selected_prompt_ids": sorted(observed_prompt_ids),
            "missing_prompt_ids": [],
            "unexpected_prompt_ids": [],
            "errors": errors,
        }
    expected = set(contracts)
    missing = expected - observed_prompt_ids
    unexpected = observed_prompt_ids - expected
    provenance_errors: list[str] = list(additional_errors or [])
    stale_prompt_ids: set[str] = set()
    if run_results is not None:
        verification_errors, stale_prompt_ids = verify_run_contracts(
            repo_root,
            run_root or repo_root,
            run_captures
            or [(result, {}, {}) for result in run_results],
            contracts,
        )
        provenance_errors.extend(verification_errors)
    if provenance_errors:
        status = "stale"
    elif missing or unexpected:
        status = "scoped"
    else:
        status = "full"
    return {
        "status": status,
        "selected_prompt_count": len(observed_prompt_ids),
        "expected_prompt_count": len(expected),
        "selected_prompt_ids": sorted(observed_prompt_ids),
        "missing_prompt_ids": sorted(missing),
        "unexpected_prompt_ids": sorted(unexpected),
        "stale_prompt_ids": sorted(stale_prompt_ids),
        "errors": provenance_errors,
    }


def verify_run_contracts(
    repo_root: Path,
    run_root: Path,
    captures: list[
        tuple[CaseResult, dict[str, Any], dict[str, bytes]]
    ],
    current_contracts: dict[str, dict[str, Any]],
) -> tuple[list[str], set[str]]:
    errors: list[str] = []
    stale_prompt_ids: set[str] = set()
    run_configuration_hashes: set[str] = set()
    config_identities: set[tuple[object, object, object]] = set()
    skill_identities: set[tuple[object, object]] = set()
    companion_skill_identities: set[tuple[object, ...]] = set()
    shared_reference_identities: set[tuple[object, object]] = set()
    harness_identities: set[tuple[object, object]] = set()
    reserved_path_identities: set[str] = set()
    results = [result for result, _metadata, _files in captures]
    for result, payload_metadata, authenticated_files in captures:
        current = current_contracts.get(result.id)
        if current is None:
            stale_prompt_ids.add(result.id)
            continue
        for side in (result.with_skill, result.baseline):
            if side is None:
                continue
            raw_paths = [side.trace_path, side.final_message_path]
            if side.rubric_grade_path:
                raw_paths.append(side.rubric_grade_path)
            try:
                reserved_paths = [
                    captured_relative_path(run_root, raw_path)
                    for raw_path in raw_paths
                ]
            except ValueError as error:
                stale_prompt_ids.add(result.id)
                errors.append(f"{result.id} has unsafe run artifacts: {error}")
                continue
            missing_paths = [
                path for path in reserved_paths if path not in authenticated_files
            ]
            if missing_paths:
                stale_prompt_ids.add(result.id)
                errors.append(
                    f"{result.id} has unauthenticated run artifacts: "
                    + ", ".join(missing_paths)
                )
                continue
            duplicates = [
                path
                for path in reserved_paths
                if path in reserved_path_identities
            ]
            if duplicates:
                stale_prompt_ids.add(result.id)
                errors.append(
                    f"{result.id} reuses captured run artifact paths: "
                    + ", ".join(duplicates)
                )
                continue
            reserved_path_identities.update(reserved_paths)
            manifest_relative = (
                Path(reserved_paths[0]).parent / PROVENANCE_FILE
            ).as_posix()
            manifest_bytes = authenticated_files.get(manifest_relative)
            if manifest_bytes is None:
                stale_prompt_ids.add(result.id)
                errors.append(
                    f"{result.id} provenance is not authenticated: "
                    f"{manifest_relative}"
                )
                continue
            manifest_path = run_root / manifest_relative
            try:
                manifest = json.loads(manifest_bytes)
            except json.JSONDecodeError as error:
                stale_prompt_ids.add(result.id)
                errors.append(
                    f"{result.id} provenance is unreadable: {error}"
                )
                continue
            prompt_errors = verify_run_contract_manifest(
                repo_root,
                manifest_path,
                manifest,
                result,
                current,
            )
            if prompt_errors:
                stale_prompt_ids.add(result.id)
                errors.extend(prompt_errors)
                continue
            run_configuration = manifest.get("run_configuration", {})
            if isinstance(run_configuration, dict):
                digest = run_configuration.get("sha256")
                if isinstance(digest, str):
                    run_configuration_hashes.add(digest)
                if run_configuration.get("value") != payload_metadata:
                    stale_prompt_ids.add(result.id)
                    errors.append(
                        f"{result.id} payload metadata differs from captured run configuration"
                    )
            config = manifest.get("config", {})
            if isinstance(config, dict):
                config_identities.add(
                    (config.get("path"), config.get("exists"), config.get("sha256"))
                )
            selected_skill = manifest.get("skill", {})
            if isinstance(selected_skill, dict):
                skill_identities.add(
                    (selected_skill.get("path"), selected_skill.get("tree_sha256"))
                )
            companion_skill_identities.add(
                companion_skill_identity(manifest.get("companion_skills"))
            )
            shared_references = manifest.get("shared_references", {})
            if isinstance(shared_references, dict):
                shared_reference_identities.add(
                    (
                        shared_references.get("path"),
                        shared_references.get("tree_sha256"),
                    )
                )
            harness = manifest.get("harness", {})
            if isinstance(harness, dict):
                harness_identities.add(
                    (harness.get("path"), harness.get("tree_sha256"))
                )
    if len(run_configuration_hashes) > 1:
        errors.append("captured sides used different effective run configurations")
        stale_prompt_ids.update(result.id for result in results)
    if len(config_identities) > 1:
        errors.append("captured sides used different eval config files or bytes")
        stale_prompt_ids.update(result.id for result in results)
    if len(skill_identities) > 1:
        errors.append("captured sides used different selected skill paths or tree bytes")
        stale_prompt_ids.update(result.id for result in results)
    if len(companion_skill_identities) > 1:
        errors.append(
            "captured sides used different companion skill paths or tree bytes"
        )
        stale_prompt_ids.update(result.id for result in results)
    if len(shared_reference_identities) > 1:
        errors.append("captured sides used different shared-reference paths or tree bytes")
        stale_prompt_ids.update(result.id for result in results)
    if len(harness_identities) > 1:
        errors.append("captured sides used different eval harness paths or tree bytes")
        stale_prompt_ids.update(result.id for result in results)
    return errors, stale_prompt_ids


def captured_payload_metadata(
    run_root: Path,
    results: list[CaseResult],
    authenticated_files: dict[str, bytes],
) -> dict[str, Any] | None:
    for result in results:
        for side in (result.with_skill, result.baseline):
            if side is None:
                continue
            try:
                trace_relative = captured_relative_path(
                    run_root, side.trace_path
                )
            except ValueError:
                continue
            manifest_relative = (
                Path(trace_relative).parent / PROVENANCE_FILE
            ).as_posix()
            manifest_bytes = authenticated_files.get(manifest_relative)
            if manifest_bytes is None:
                continue
            try:
                manifest = json.loads(manifest_bytes)
            except json.JSONDecodeError:
                continue
            run_configuration = manifest.get("run_configuration")
            if not isinstance(run_configuration, dict):
                continue
            value = run_configuration.get("value")
            digest = run_configuration.get("sha256")
            if not isinstance(value, dict) or not valid_sha256(digest):
                continue
            if hashlib.sha256(
                json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest() == digest:
                return value
    return None


def validate_mode_sides(mode: str, result: CaseResult) -> list[str]:
    expected = {
        "with_skill": (True, False),
        "with_baseline": (False, True),
        "ab": (True, True),
    }.get(mode)
    if expected is None:
        return [f"unsupported live result mode: {mode}"]
    actual = (result.with_skill is not None, result.baseline is not None)
    if actual == expected:
        return []
    return [
        f"{result.id} side multiplicity does not match mode {mode}: "
        f"with_skill={actual[0]}, baseline={actual[1]}"
    ]


def verify_run_contract_manifest(
    repo_root: Path,
    manifest_path: Path,
    manifest: Any,
    result: CaseResult,
    current_definition: dict[str, Any],
) -> list[str]:
    prefix = f"{result.id} provenance"
    if not isinstance(manifest, dict) or int(manifest.get("schema_version") or 0) < 2:
        return [f"{prefix} does not bind the eval definition and config"]

    errors: list[str] = []
    case = manifest.get("case")
    if not isinstance(case, dict) or case.get("id") != result.id:
        errors.append(f"{prefix} case id does not match the captured result")
    else:
        if case.get("task_sha256") != current_definition["task_sha256"]:
            errors.append(f"{prefix} task differs from the current eval definition")
        if (
            case.get("contract_sha256")
            != current_definition["contract_sha256"]
        ):
            errors.append(
                f"{prefix} case contract differs from the current eval definition"
            )

    definition = manifest.get("definition")
    if not authenticated_file_matches(
        definition,
        Path(current_definition["path"]),
        current_definition["sha256"],
        required=True,
    ):
        errors.append(f"{prefix} eval definition changed after capture")

    config = manifest.get("config")
    if not authenticated_current_file(config, repo_root):
        errors.append(f"{prefix} eval config changed after capture")

    if not authenticated_current_tree(
        manifest.get("fixture"),
        Path(current_definition["fixture_path"]),
    ):
        errors.append(f"{prefix} fixture tree changed after capture")
    if not authenticated_current_tree(manifest.get("skill"), None):
        errors.append(f"{prefix} skill tree changed after capture")
    selected_skill = manifest.get("skill")
    selected_path = (
        Path(selected_skill["path"])
        if isinstance(selected_skill, dict)
        and isinstance(selected_skill.get("path"), str)
        else None
    )
    errors.extend(
        verify_companion_skills(
            manifest.get("companion_skills"),
            str(case.get("skill") or "") if isinstance(case, dict) else "",
            selected_path,
            prefix,
            staged=manifest_path.parent.name == "with_skill",
        )
    )
    shared_references = repo_root / "skills" / "references"
    if not authenticated_current_tree(
        manifest.get("shared_references"),
        shared_references,
        optional=not shared_references.is_dir(),
    ):
        errors.append(f"{prefix} shared references changed after capture")
    harness_source = Path(__file__).resolve().parent
    if not authenticated_current_tree(manifest.get("harness"), harness_source):
        errors.append(f"{prefix} eval harness or grader source changed after capture")

    run_configuration = manifest.get("run_configuration")
    if not isinstance(run_configuration, dict) or not valid_sha256(
        run_configuration.get("sha256")
    ):
        errors.append(f"{prefix} effective run configuration hash is invalid")
    elif hashlib.sha256(
        json.dumps(
            run_configuration.get("value"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest() != run_configuration["sha256"]:
        errors.append(f"{prefix} effective run configuration was altered")
    return errors


def verify_validation_provenance(
    repo_root: Path,
    result: ValidationResult,
    current_definition: dict[str, Any],
    metadata: dict[str, Any],
) -> list[str]:
    prefix = f"{result.id} validation provenance"
    manifest = result.provenance
    if not isinstance(manifest, dict) or int(manifest.get("schema_version") or 0) < 2:
        return [f"{prefix} does not bind eval inputs"]
    errors: list[str] = []
    expected_fields = {
        "base_id": current_definition["base_id"],
        "language": current_definition["language"],
        "service": current_definition["service"],
        "eval_kind": current_definition["eval_kind"],
        "sanity_check_count": current_definition["sanity_check_count"],
        "rubric_check_count": current_definition["rubric_check_count"],
        "runtime_check_count": current_definition["runtime_check_count"],
    }
    for field, expected in expected_fields.items():
        if getattr(result, field) != expected:
            errors.append(
                f"{prefix} {field} differs from the current eval definition"
            )
    if Path(result.definition_path).resolve() != Path(current_definition["path"]).resolve():
        errors.append(f"{prefix} definition path differs from the current eval definition")
    if Path(result.fixture_dir).resolve() != Path(current_definition["fixture_path"]).resolve():
        errors.append(f"{prefix} fixture path differs from the current eval definition")
    case = manifest.get("case")
    if not isinstance(case, dict) or case.get("id") != result.id:
        errors.append(f"{prefix} case id does not match")
    else:
        if case.get("task_sha256") != current_definition["task_sha256"]:
            errors.append(f"{prefix} task differs from the current eval definition")
        if (
            case.get("contract_sha256")
            != current_definition["contract_sha256"]
        ):
            errors.append(
                f"{prefix} case contract differs from the current eval definition"
            )
    if not authenticated_file_matches(
        manifest.get("definition"),
        Path(current_definition["path"]),
        current_definition["sha256"],
        required=True,
    ):
        errors.append(f"{prefix} eval definition changed after validation")
    if not authenticated_current_file(manifest.get("config"), repo_root):
        errors.append(f"{prefix} eval config changed after validation")
    if not authenticated_current_tree(
        manifest.get("fixture"),
        Path(current_definition["fixture_path"]),
    ):
        errors.append(f"{prefix} fixture tree changed after validation")
    if not authenticated_current_tree(
        manifest.get("skill"),
        Path(result.skill_path),
    ):
        errors.append(f"{prefix} skill tree changed after validation")
    errors.extend(
        verify_companion_skills(
            manifest.get("companion_skills"),
            result.skill,
            Path(result.skill_path),
            prefix,
            staged=None,
        )
    )
    shared_references = repo_root / "skills/references"
    if not authenticated_current_tree(
        manifest.get("shared_references"),
        shared_references,
        optional=not shared_references.is_dir(),
    ):
        errors.append(f"{prefix} shared references changed after validation")
    harness_source = Path(__file__).resolve().parent
    if not authenticated_current_tree(manifest.get("harness"), harness_source):
        errors.append(f"{prefix} eval harness or grader source changed after validation")
    run_configuration = manifest.get("run_configuration")
    if not isinstance(run_configuration, dict) or not valid_sha256(
        run_configuration.get("sha256")
    ):
        errors.append(f"{prefix} effective run configuration hash is invalid")
    else:
        value = run_configuration.get("value")
        digest = hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        if digest != run_configuration["sha256"]:
            errors.append(f"{prefix} effective run configuration was altered")
        if value != metadata:
            errors.append(f"{prefix} metadata differs from captured run configuration")
    return errors


def validation_provenance_errors(
    repo_root: Path,
    skill: str,
    results: list[ValidationResult],
    metadata: dict[str, Any],
) -> list[str]:
    contracts, discovery_errors = expected_prompt_contracts(
        repo_root, skill, "validation"
    )
    errors = list(discovery_errors)
    if contracts is None:
        return errors
    identity_sets: dict[str, set[tuple[object, object]]] = {
        "skill": set(),
        "shared_references": set(),
        "harness": set(),
    }
    config_identities: set[tuple[object, object, object]] = set()
    companion_skill_identities: set[tuple[object, ...]] = set()
    for result in results:
        if result.skill != skill:
            errors.append(
                f"{result.id} validation result skill differs from report skill {skill}"
            )
        current = contracts.get(result.id)
        if current is None:
            continue
        errors.extend(
            verify_validation_provenance(repo_root, result, current, metadata)
        )
        provenance = result.provenance
        companion_skill_identities.add(
            companion_skill_identity(
                provenance.get("companion_skills")
                if isinstance(provenance, dict)
                else None
            )
        )
        for name in identity_sets:
            record = provenance.get(name) if isinstance(provenance, dict) else None
            if isinstance(record, dict):
                identity_sets[name].add(
                    (record.get("path"), record.get("tree_sha256"))
                )
        config = provenance.get("config") if isinstance(provenance, dict) else None
        if isinstance(config, dict):
            config_identities.add(
                (config.get("path"), config.get("exists"), config.get("sha256"))
            )
    labels = {
        "skill": "selected skill",
        "shared_references": "shared-reference",
        "harness": "eval harness",
    }
    for name, identities in identity_sets.items():
        if len(identities) > 1:
            errors.append(
                f"validation results used different {labels[name]} paths or tree bytes"
            )
    if len(config_identities) > 1:
        errors.append("validation results used different eval config files or bytes")
    if len(companion_skill_identities) > 1:
        errors.append(
            "validation results used different companion skill paths or tree bytes"
        )
    return errors


def companion_skill_identity(records: object) -> tuple[object, ...]:
    if not isinstance(records, list):
        return (None,)
    return tuple(
        (
            record.get("name"),
            record.get("path"),
            record.get("tree_sha256"),
        )
        if isinstance(record, dict)
        else (None, None, None)
        for record in records
    )


def verify_companion_skills(
    records: object,
    selected_skill: str,
    selected_path: Path | None,
    prefix: str,
    *,
    staged: bool | None,
) -> list[str]:
    expected_names = SKILL_COMPANIONS.get(selected_skill, ())
    if not expected_names and records is None:
        return []
    if not isinstance(records, list):
        return [f"{prefix} companion_skills must be an array"]
    if len(records) != len(expected_names):
        return [f"{prefix} companion skill set does not match {selected_skill}"]

    errors: list[str] = []
    for record, name in zip(records, expected_names, strict=True):
        expected_path = (
            selected_path.parent / name if selected_path is not None else None
        )
        if not isinstance(record, dict) or record.get("name") != name:
            errors.append(f"{prefix} companion skill order or name is invalid")
            continue
        if expected_path is None or not authenticated_current_tree(
            record, expected_path
        ):
            errors.append(
                f"{prefix} companion skill {name} changed after capture"
            )
        staged_path = record.get("staged_path")
        if staged is False and staged_path is not None:
            errors.append(
                f"{prefix} baseline unexpectedly staged companion skill {name}"
            )
        elif staged is True:
            if not isinstance(staged_path, str) or not staged_path:
                errors.append(
                    f"{prefix} loaded side did not stage companion skill {name}"
                )
            else:
                candidate = Path(staged_path)
                expected_suffix = (".agents", "skills", name, "SKILL.md")
                if (
                    not candidate.is_absolute()
                    or os.path.normpath(staged_path) != staged_path
                    or tuple(candidate.parts[-4:]) != expected_suffix
                ):
                    errors.append(
                        f"{prefix} companion skill {name} staged path is invalid"
                    )
    return errors


def authenticated_file_matches(
    record: object,
    expected_path: Path,
    expected_sha256: str,
    *,
    required: bool,
) -> bool:
    if not isinstance(record, dict):
        return False
    recorded_path = record.get("path")
    if not isinstance(recorded_path, str) or not recorded_path:
        return not required and record.get("exists") is False and record.get("sha256") is None
    path = Path(recorded_path)
    if path.is_symlink() or path.resolve() != expected_path.resolve():
        return False
    return (
        record.get("exists") is True
        and record.get("sha256") == expected_sha256
        and valid_sha256(record.get("sha256"))
    )


def authenticated_current_file(record: object, repo_root: Path) -> bool:
    if not isinstance(record, dict):
        return False
    path_value = record.get("path")
    if path_value is None:
        return record.get("exists") is False and record.get("sha256") is None
    if not isinstance(path_value, str) or not path_value:
        return False
    path = Path(path_value)
    if not path.is_absolute():
        path = repo_root / path
    if path.is_symlink():
        return False
    exists = path.is_file()
    if record.get("exists") is not exists:
        return False
    if not exists:
        return record.get("sha256") is None
    recorded_sha = record.get("sha256")
    return valid_sha256(recorded_sha) and recorded_sha == hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def authenticated_current_tree(
    record: object,
    expected_path: Path | None,
    *,
    optional: bool = False,
) -> bool:
    if not isinstance(record, dict):
        return False
    path_value = record.get("path")
    if not isinstance(path_value, str) or not path_value:
        return optional and record.get("tree_sha256") is None
    recorded_path = Path(path_value)
    if recorded_path.is_symlink():
        return False
    if expected_path is not None and recorded_path.resolve() != expected_path.resolve():
        return False
    if not recorded_path.is_dir():
        return optional and record.get("tree_sha256") is None
    recorded_sha = record.get("tree_sha256")
    if not valid_sha256(recorded_sha):
        return False
    try:
        return recorded_sha == tree_sha256(recorded_path)
    except (OSError, ValueError):
        return False


def valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def render_kind_report(skill: str, benchmark: dict[str, Any]) -> str:
    kind = str(benchmark["kind"])
    template = template_for_kind(kind)
    lines = [f"# {skill} {template.summary_title.replace(' Summary', '')} Codex Eval Report"]
    lines.extend(render_environment_table(benchmark["metadata"], "Mode"))
    lines.extend(render_kind_summary_section(template, benchmark["evals"]))
    lines.extend(render_kind_failure_section(template, benchmark["failures"]))
    if template.evidence_title:
        lines.extend(["", f"## {template.evidence_title}", ""])
        lines.append("Runtime failure evidence includes the relevant Docker Compose log tail in the failure table.")
    lines.extend(["", "## Result JSON", ""])
    lines.append("File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.")
    return "\n".join(lines) + "\n"


def render_kind_summary_section(template: ReportTemplate, evals: list[dict[str, Any]]) -> list[str]:
    lines = [
        "",
        f"## {template.summary_title}",
        "",
        "Task-agent tokens measure the model carrying out the skill on the fixture; judge tokens belong only to rubric grading and are excluded from normal-use comparisons.",
        "",
        "| Mode | Eval | Service | Prompts | With Skill | With Skill Task-Agent Tokens | With Skill Judge Tokens | With Skill Time | Baseline | Baseline Task-Agent Tokens | Baseline Judge Tokens | Baseline Time |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    if not evals:
        lines.append("| - | - | - | 0 | - | - | - | - | - | - | - | - |")
        return lines
    for item in evals:
        lines.append(
            "| {mode} | {eval_id} | {service} | {prompts} | {ws} | {ws_agent_tokens} | {ws_judge_tokens} | {ws_time} | {base} | {base_agent_tokens} | {base_judge_tokens} | {base_time} |".format(
                mode=markdown_cell(item["mode"]),
                eval_id=markdown_cell(item["id"]),
                service=markdown_cell(item["case"]),
                prompts=item["prompt_count"],
                ws=format_kind_side(item.get("with_skill"), template.category),
                ws_agent_tokens=format_tokens(item.get("with_skill"), "agent_tokens"),
                ws_judge_tokens=format_tokens(item.get("with_skill"), "rubric_tokens"),
                ws_time=format_duration(item.get("with_skill")),
                base=format_kind_side(item.get("with_baseline"), template.category),
                base_agent_tokens=format_tokens(item.get("with_baseline"), "agent_tokens"),
                base_judge_tokens=format_tokens(item.get("with_baseline"), "rubric_tokens"),
                base_time=format_duration(item.get("with_baseline")),
            )
        )
    return lines


def render_kind_failure_section(template: ReportTemplate, failures: list[dict[str, str]]) -> list[str]:
    lines = ["", f"## {template.failure_title}", ""]
    if not failures:
        lines.append(template.empty_failures)
        return lines
    lines.extend(["| Mode | Service | Side | Prompt | Result | Evidence |", "|---|---|---|---|---|---|"])
    for failure in failures:
        lines.append(
            "| {mode} | {service} | {side} | {prompt} | {result} | {evidence} |".format(
                mode=markdown_cell(failure.get("mode")),
                service=markdown_cell(failure["service"]),
                side=markdown_cell(failure["side"]),
                prompt=markdown_cell(failure["prompt"]),
                result=markdown_cell(failure["result"]),
                evidence=markdown_cell(truncate(failure["evidence"], 320)),
            )
        )
    return lines


def write_report_outputs(
    repo_root: Path,
    run_root: Path,
    skill: str,
    kind: str,
    benchmark: dict[str, Any],
    report: str,
    output_dir: Path | None = None,
) -> tuple[Path, Path]:
    validate_output_component(skill, "skill")
    validate_output_component(kind, "kind")
    ensure_safe_output_directory(run_root, repo_root)
    run_root_identity = path_directory_identity(run_root)
    report_dir = run_root / kind
    ensure_safe_output_directory(report_dir, run_root)
    benchmark_path = report_dir / "benchmark.json"
    report_path = report_dir / "report.md"
    atomic_text_write(
        benchmark_path,
        json.dumps(benchmark, indent=2),
        boundary=run_root,
        expected_boundary_identity=run_root_identity,
    )
    atomic_text_write(
        report_path,
        report,
        boundary=run_root,
        expected_boundary_identity=run_root_identity,
    )

    latest_root = output_dir or repo_root / "eval-reports"
    ensure_safe_output_directory(
        latest_root,
        latest_root if output_dir is not None else repo_root,
    )
    latest_root_identity = path_directory_identity(latest_root)
    latest_dir = latest_root / skill / kind
    scope = benchmark.get("metadata", {}).get("scope", {})
    if not isinstance(scope, dict) or scope.get("status") != "full":
        validate_output_component(run_root.name, "run id")
        latest_dir = latest_dir / "scoped" / run_root.name
    ensure_safe_output_directory(latest_dir, latest_root)
    published_benchmark = sanitize_published_value(benchmark, repo_root)
    published_report = sanitize_published_text(report, repo_root)
    atomic_text_write(
        latest_dir / "report.md",
        published_report,
        boundary=latest_root,
        expected_boundary_identity=latest_root_identity,
    )
    atomic_text_write(
        latest_dir / "benchmark.json",
        json.dumps(published_benchmark, indent=2),
        boundary=latest_root,
        expected_boundary_identity=latest_root_identity,
    )
    return report_path, benchmark_path


def sanitize_published_text(value: str, repo_root: Path) -> str:
    """Remove machine-specific repository prefixes from latest reports."""

    roots = sorted(
        {str(repo_root.absolute()), str(repo_root.resolve())},
        key=len,
        reverse=True,
    )
    result = value
    for root in roots:
        result = result.replace(root + os.sep, "")
        result = result.replace(root, ".")
    return result


def sanitize_published_value(value: Any, repo_root: Path) -> Any:
    if isinstance(value, dict):
        return {
            key: sanitize_published_value(item, repo_root)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_published_value(item, repo_root) for item in value]
    if isinstance(value, str):
        return sanitize_published_text(value, repo_root)
    return value


def validate_output_component(value: str, label: str) -> None:
    if not value or value in {".", ".."} or Path(value).name != value:
        raise ValueError(f"unsafe {label} output component: {value!r}")


def ensure_safe_output_directory(path: Path, root: Path) -> None:
    """Create an output directory without traversing symlink ancestors."""

    absolute_path = path.absolute()
    absolute_root = root.absolute()
    try:
        relative = absolute_path.relative_to(absolute_root)
    except ValueError as error:
        raise ValueError(
            f"output path escapes its root: {absolute_path} not within {absolute_root}"
        ) from error
    creation_boundary = absolute_root
    while not creation_boundary.exists():
        if creation_boundary.is_symlink():
            raise ValueError(
                f"output root must not be a symlink: {creation_boundary}"
            )
        parent = creation_boundary.parent
        if parent == creation_boundary:
            raise ValueError(
                f"output directory has no existing ancestor: {absolute_root}"
            )
        creation_boundary = parent
    if creation_boundary.is_symlink():
        raise ValueError(
            f"output root must not be a symlink: {creation_boundary}"
        )
    if not creation_boundary.is_dir():
        raise ValueError(
            f"output directory path is not a directory: {creation_boundary}"
        )
    current = creation_boundary
    for component in absolute_path.relative_to(creation_boundary).parts:
        current = current / component
        if current.is_symlink():
            raise ValueError(f"output directory must not be a symlink: {current}")
        if current.exists() and not current.is_dir():
            raise ValueError(f"output directory path is not a directory: {current}")
    boundary_identity = path_directory_identity(creation_boundary)
    ensure_anchored_directory(
        absolute_path,
        boundary=creation_boundary,
        expected_boundary_identity=boundary_identity,
    )


def format_kind_side(side: dict[str, Any] | None, kind: str) -> str:
    if side is None:
        return "-"
    if kind == "rubric":
        return format_rubric(side)
    data = side.get("checks")
    if not data:
        return "-"
    total = int(data["total"])
    passed = int(data["passed"])
    skipped = int(data.get("skipped") or 0)
    if total == 0 and skipped == 0:
        return "-"
    if total == 0 and skipped:
        return f"{skipped} skipped"
    value = format_count(passed, total)
    if skipped:
        return f"{value}, {skipped} skipped"
    return value


def normalize_kind(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def write_live_result_jsons(
    repo_root: Path,
    run_root: Path,
    mode: str,
    results: list[CaseResult],
) -> dict[str, dict[str, str]]:
    paths: dict[str, dict[str, str]] = {}
    run_root_identity = path_directory_identity(run_root)
    for base_id, group in grouped_case_results(results).items():
        first = group[0]
        validate_output_component(first.language, "language")
        validate_output_component(first.service, "service")
        eval_name = eval_kind(base_id)
        validate_output_component(eval_name, "eval")
        eval_dir = run_root / "results" / first.language / first.service / eval_name
        ensure_safe_output_directory(eval_dir, run_root)

        payload = {
            "mode": mode,
            "id": base_id,
            "skill": first.skill,
            "language": first.language,
            "service": first.service,
            "prompt_count": len(group),
            "prompts": [case_result_payload(result) for result in group],
            "aggregate": aggregate_case_group(group),
        }
        eval_path = eval_dir / "eval.json"
        atomic_text_write(
            eval_path,
            json.dumps(payload, indent=2),
            boundary=run_root,
            expected_boundary_identity=run_root_identity,
        )

        side_paths = {"eval": relative_to_repo(repo_root, eval_path)}
        for side_key in SIDE_ATTRS:
            side_payload = {
                "mode": mode,
                "side": side_key,
                "id": base_id,
                "skill": first.skill,
                "language": first.language,
                "service": first.service,
                "prompt_count": len(group),
                "prompts": [side_result_payload(result, side_key) for result in group],
                "aggregate": aggregate_side(group, side_key),
            }
            side_path = eval_dir / f"{side_key}.json"
            atomic_text_write(
                side_path,
                json.dumps(side_payload, indent=2),
                boundary=run_root,
                expected_boundary_identity=run_root_identity,
            )
            side_paths[side_key] = relative_to_repo(repo_root, side_path)
        paths[base_id] = side_paths
    return paths


def case_result_payload(result: CaseResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "base_id": result.base_id,
        "prompt_id": result.prompt_id,
        "case": f"{result.language}/{result.service}",
        "with_skill": side_summary(result.with_skill),
        "with_baseline": side_summary(result.baseline),
    }


def side_result_payload(result: CaseResult, side_key: str) -> dict[str, Any]:
    side = side_for_key(result, side_key)
    return {
        "id": result.id,
        "base_id": result.base_id,
        "prompt_id": result.prompt_id,
        "case": f"{result.language}/{result.service}",
        "result": side_summary(side),
    }


def side_summary(side: SideResult | None) -> dict[str, Any] | None:
    if side is None:
        return None
    return {
        "exit_code": side.exit_code,
        "sanity": check_summary(side, "sanity"),
        "runtime": check_summary(side, "runtime"),
        "rubric": load_rubric_grade(side),
        "command_count": side.command_count,
        "duration_seconds": side.duration_seconds,
        "agent_duration_seconds": side.agent_duration_seconds,
        "rubric_duration_seconds": side.rubric_duration_seconds,
        "tokens": side.tokens,
        "agent_tokens": side.agent_tokens,
        "rubric_tokens": side.rubric_tokens,
        "errors": side.errors,
        "trace_path": side.trace_path,
        "final_message_path": side.final_message_path,
        "rubric_grade_path": side.rubric_grade_path,
        "rubric_trace_path": side.rubric_trace_path,
    }


def check_summary(side: SideResult, category: str) -> dict[str, Any]:
    checks = checks_for_category(side, category)
    total = sum(1 for check in checks if not check.skipped)
    passed = sum(1 for check in checks if check.passed and not check.skipped)
    skipped = sum(1 for check in checks if check.skipped)
    return {
        "pass_rate": 1.0 if total == 0 else passed / total,
        "passed": passed,
        "total": total,
        "skipped": skipped,
        "checks": [check.model_dump(mode="json") for check in checks],
    }


def checks_for_category(side: SideResult, category: str) -> list[GradeCheckResult]:
    return [check for check in side.grade.checks if check.category == category]


def aggregate_check_category(sides: list[SideResult], category: str) -> dict[str, Any]:
    checks = [check for side in sides for check in checks_for_category(side, category)]
    return {
        "passed": sum(1 for check in checks if check.passed and not check.skipped),
        "total": sum(1 for check in checks if not check.skipped),
        "skipped": sum(1 for check in checks if check.skipped),
    }


def aggregate_case_group(group: list[CaseResult]) -> dict[str, Any]:
    first = group[0]
    return {
        "id": first.base_id,
        "case": f"{first.language}/{first.service}",
        "language": first.language,
        "service": first.service,
        "prompt_count": len(group),
        "prompts": [result.prompt_id for result in group],
        "with_skill": aggregate_side(group, "with_skill"),
        "with_baseline": aggregate_side(group, "with_baseline"),
    }


def aggregate_side(results: list[CaseResult], side_key: str) -> dict[str, Any] | None:
    sides = [side for result in results if (side := side_for_key(result, side_key)) is not None]
    if not sides:
        return None

    rubric = [grade for side in sides if (grade := load_rubric_grade(side)) is not None]
    rubric_total = sum(int(grade["total"]) for grade in rubric)
    rubric_passed = sum(int(grade["passed"]) for grade in rubric)
    scores = [int(grade["score"]) for grade in rubric if isinstance(grade.get("score"), int)]
    return {
        "prompt_count": len(sides),
        "sanity": aggregate_check_category(sides, "sanity"),
        "runtime": aggregate_check_category(sides, "runtime"),
        "rubric": None
        if not rubric
        else {
            "passed": rubric_passed,
            "total": rubric_total,
            "average_score": average(scores) if scores else None,
        },
        "command_count": sum(side.command_count for side in sides),
        "duration_seconds": round(sum(side.duration_seconds for side in sides), 3),
        "agent_duration_seconds": round(sum(side.agent_duration_seconds for side in sides), 3),
        "rubric_duration_seconds": round(sum(side.rubric_duration_seconds for side in sides), 3),
        "tokens": sum(side.tokens for side in sides),
        "agent_tokens": sum(side.agent_tokens for side in sides),
        "rubric_tokens": sum(side.rubric_tokens for side in sides),
        "error_count": sum(len(side.errors) for side in sides),
    }


def collect_failures(results: list[CaseResult]) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for result in sorted(results, key=lambda item: (item.language, item.service, item.base_id, item.prompt_id)):
        service = f"{result.language}/{result.service}"
        for side_key in SIDE_ATTRS:
            side = side_for_key(result, side_key)
            if side is None:
                continue
            for check in side.grade.checks:
                if check.passed or check.skipped:
                    continue
                category = check.category
                failures.append(
                    {
                        "service": service,
                        "side": side_key,
                        "prompt": result.prompt_id,
                        "category": category,
                        "result": f"{category}:{check.id} FAIL",
                        "evidence": check.evidence,
                    }
                )
            rubric = load_rubric_grade(side)
            if rubric is None:
                continue
            rubric_failures = 0
            for check in rubric.get("checks", []):
                if bool(check.get("pass")):
                    continue
                rubric_failures += 1
                failures.append(
                    {
                        "service": service,
                        "side": side_key,
                        "prompt": result.prompt_id,
                        "category": "rubric",
                        "result": f"rubric:{check.get('id', 'check')} FAIL",
                        "evidence": str(check.get("evidence") or check.get("notes") or ""),
                    }
                )
            if not rubric_failures and rubric.get("overall_pass") is False:
                failures.append(
                    {
                        "service": service,
                        "side": side_key,
                        "prompt": result.prompt_id,
                        "category": "rubric",
                        "result": "rubric:overall FAIL",
                        "evidence": str(rubric.get("notes") or "overall rubric grade failed"),
                    }
                )
    return failures


def build_validation_benchmark(
    repo_root: Path,
    skill: str,
    results: list[ValidationResult],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    evals = []
    result_ids = [result.id for result in results]
    duplicate_ids = sorted(
        {result_id for result_id in result_ids if result_ids.count(result_id) > 1}
    )
    provenance_errors = validation_provenance_errors(
        repo_root,
        skill,
        results,
        metadata,
    )
    for base_id, group in grouped_validation_results(results).items():
        first = group[0]
        evals.append(
            {
                "id": first.base_id,
                "case": f"{first.language}/{first.service}",
                "language": first.language,
                "service": first.service,
                "prompt_count": len(group),
                "prompts": [result.prompt_id for result in group],
                "definition_path": relative_to_repo(repo_root, first.definition_path),
                "eval_dir": relative_to_repo(repo_root, first.fixture_dir),
                "skill_path": relative_to_repo(repo_root, first.skill_path),
                "sanity_check_count": first.sanity_check_count,
                "rubric_check_count": first.rubric_check_count,
                "runtime_check_count": first.runtime_check_count,
            }
        )

    metadata = dict(metadata)
    metadata["scope"] = report_scope_metadata(
        repo_root,
        skill,
        "validation",
        set(result_ids),
        additional_errors=[
            f"duplicate validation result: {result_id}"
            for result_id in duplicate_ids
        ]
        + provenance_errors,
    )
    return {
        "mode": "validation",
        "skill": skill,
        "metadata": metadata,
        "evals": evals,
        "summary": {
            "eval_count": len(evals),
            "case_count": len(results),
            "prompt_count": len(results),
            "sanity_check_count": sum(result.sanity_check_count for result in results),
            "rubric_check_count": sum(result.rubric_check_count for result in results),
            "runtime_check_count": sum(result.runtime_check_count for result in results),
        },
    }


def render_validation_report(skill: str, benchmark: dict[str, Any]) -> str:
    lines = [
        f"# {skill} Codex Eval Validation Report",
        "",
        "This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.",
    ]
    lines.extend(render_environment_table(benchmark["metadata"], "Mode"))

    lines.extend(
        [
            "",
            "## Eval Summary",
            "",
            "| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |",
            "|---|---|---:|---|---:|---:|---:|",
        ]
    )
    for item in benchmark["evals"]:
        lines.append(
            "| {eval_id} | {service} | {prompts} | {path} | {det} | {qual} | {runtime} |".format(
                eval_id=markdown_cell(item["id"]),
                service=markdown_cell(item["case"]),
                prompts=item["prompt_count"],
                path=markdown_cell(item["definition_path"]),
                det=item["sanity_check_count"],
                qual=item["rubric_check_count"],
                runtime=item.get("runtime_check_count", 0),
            )
        )
    lines.append("")
    return "\n".join(lines)


def report_metadata(
    skill: str,
    mode: str,
    run_root: Path,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized = dict(metadata or {})
    normalized.setdefault("mode", mode)
    normalized.setdefault("eval_kind", "validation" if mode == "validation" else "standard")
    normalized.setdefault("skill", skill)
    normalized.setdefault("run_id", run_root.name)
    normalized.setdefault("agent_model", "-")
    normalized.setdefault("judge_model", "-")
    normalized.setdefault("rubric_enabled", "-")
    normalized.setdefault("runtime_enabled", "-")
    normalized.setdefault("workers", "-")
    normalized.setdefault("config_path", "-")
    return normalized


def render_environment_table(metadata: dict[str, Any], mode_label: str) -> list[str]:
    rows = [
        (mode_label, "mode"),
        ("Eval kind", "eval_kind"),
        ("Skill", "skill"),
        ("Run ID", "run_id"),
    ]
    if not metadata_has_eval_kind(metadata, "validation"):
        rows.append(("Agent model", "agent_model"))
    if metadata_has_eval_kind(metadata, "rubric") or truthy_metadata(metadata.get("rubric_enabled")):
        rows.extend(
            [
                ("Judge model", "judge_model"),
                ("Rubric enabled", "rubric_enabled"),
            ]
        )
    if metadata_has_eval_kind(metadata, "runtime") or truthy_metadata(metadata.get("runtime_enabled")):
        rows.append(("Runtime enabled", "runtime_enabled"))
    rows.extend(
        [
            ("Workers", "workers"),
            ("Config", "config_path"),
        ]
    )

    scope = metadata.get("scope")
    if isinstance(scope, dict):
        rows.extend(
            [
                ("Report scope", "__scope_status"),
                ("Selected prompts", "__scope_selected"),
                ("Expected prompts", "__scope_expected"),
            ]
        )

    lines = [
        "",
        "## Environment",
        "",
        "| Field | Value |",
        "|---|---|",
    ]
    for label, key in rows:
        if key == "__scope_status":
            value = scope.get("status") if isinstance(scope, dict) else None
        elif key == "__scope_selected":
            value = (
                scope.get("selected_prompt_count")
                if isinstance(scope, dict)
                else None
            )
        elif key == "__scope_expected":
            value = (
                scope.get("expected_prompt_count")
                if isinstance(scope, dict)
                else None
            )
        else:
            value = metadata.get(key)
        lines.append(f"| {label} | {markdown_cell(value)} |")
    return lines


def metadata_has_eval_kind(metadata: dict[str, Any], expected: str) -> bool:
    return expected in eval_kind_values(metadata)


def eval_kind_values(metadata: dict[str, Any]) -> list[str]:
    return [value.lower() for value in str(metadata.get("eval_kind") or "").replace(",", " ").split()]


def truthy_metadata(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def grouped_case_results(results: list[CaseResult]) -> dict[str, list[CaseResult]]:
    grouped: dict[str, list[CaseResult]] = {}
    for result in sorted(results, key=lambda item: (item.language, item.service, item.base_id, item.prompt_id)):
        grouped.setdefault(result.base_id, []).append(result)
    return grouped


def grouped_validation_results(results: list[ValidationResult]) -> dict[str, list[ValidationResult]]:
    grouped: dict[str, list[ValidationResult]] = {}
    for result in sorted(results, key=lambda item: (item.language, item.service, item.base_id, item.prompt_id)):
        grouped.setdefault(result.base_id, []).append(result)
    return grouped


def side_for_key(result: CaseResult, side_key: str) -> SideResult | None:
    return getattr(result, SIDE_ATTRS[side_key])


def load_rubric_grade(
    side: SideResult,
    run_root: Path | None = None,
    authenticated_files: dict[str, bytes] | None = None,
) -> dict[str, Any] | None:
    if not side.rubric_grade_path:
        return None
    if authenticated_files is not None:
        if run_root is None:
            return None
        try:
            relative = captured_relative_path(run_root, side.rubric_grade_path)
        except ValueError:
            return None
        captured = authenticated_files.get(relative)
        if captured is None:
            return None
        data = json.loads(captured)
    else:
        path = Path(side.rubric_grade_path)
        if path.is_symlink() or not path.is_file():
            return None
        data = json.loads(read_regular_text(path))
    checks = data.get("checks") or []
    passed = sum(1 for check in checks if bool(check.get("pass")))
    score = normalize_rubric_score(data.get("score"), passed, len(checks))
    normalized = {
        "overall_pass": data.get("overall_pass"),
        "score": score,
        "passed": passed,
        "total": len(checks),
        "checks": checks,
        "path": side.rubric_grade_path,
    }
    return normalized


def normalize_rubric_score(score: Any, passed: int, total: int) -> Any:
    if isinstance(score, int) and total > 0 and score == passed and score <= total:
        return round((passed / total) * 100)
    return score


def format_rubric(side: dict[str, Any] | None) -> str:
    if side is None or side.get("rubric") is None:
        return "-"
    rubric = side["rubric"]
    value = format_count(int(rubric["passed"]), int(rubric["total"]))
    score = rubric.get("average_score")
    if score is None:
        return value
    return f"{value}, avg score {score:.0f}"


def format_tokens(side: dict[str, Any] | None, key: str = "agent_tokens") -> str:
    if side is None:
        return "-"
    tokens = int(side.get(key) or 0)
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.1f}K"
    return str(tokens)


def format_duration(side: dict[str, Any] | None) -> str:
    if side is None:
        return "-"
    seconds = float(side.get("duration_seconds") or 0.0)
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h"
    if seconds >= 60:
        return f"{seconds / 60:.1f}m"
    return f"{seconds:.1f}s"


def format_count(passed: int, total: int) -> str:
    if total == 0:
        return "100% (0/0)"
    return f"{passed / total:.0%} ({passed}/{total})"


def average(values: list[int] | list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def eval_kind(base_id: str) -> str:
    parts = [part for part in base_id.split("/") if part]
    if len(parts) >= 4:
        return safe_name("-".join(parts[2:]))
    return safe_name(parts[-1] if parts else "eval")


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)


def truncate(value: str, limit: int) -> str:
    normalized = " ".join(str(value).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def markdown_cell(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value).replace("|", "\\|").replace("\n", " ")


def relative_to_repo(repo_root: Path, path: str | Path) -> str:
    absolute = Path(path)
    try:
        return str(absolute.relative_to(repo_root))
    except ValueError:
        return str(absolute)


def relative_to_run_root(run_root: Path, path: str | Path) -> str:
    absolute = Path(path)
    try:
        return str(absolute.relative_to(run_root))
    except ValueError:
        return str(absolute)
