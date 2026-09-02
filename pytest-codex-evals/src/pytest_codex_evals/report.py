from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from .definitions import (
    CaseResult,
    GradeCheckResult,
    SideResult,
    TokenUsage,
    ValidationResult,
)
from .eval_files import (
    eval_file_layout,
    fixture_eval_input_sources,
    iter_eval_files,
    regular_source_file,
    runtime_definition_asset_files,
    runtime_repository_source_files,
    shared_runtime_source_files,
    shared_skill_reference_source_files,
    staged_fixture_source_files,
    staged_skill_source_files,
    source_tree_files,
)
from .reports import ReportTemplate, template_for_kind


LIVE_MODES = {"with_skill", "with_baseline", "ab"}
SIDE_ATTRS = {
    "with_skill": "with_skill",
    "with_baseline": "baseline",
}
RAW_RUNS_DIR = "runs"
TOKEN_USAGE_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_creation_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "provider_total_tokens",
    "derived_total_tokens",
)
SOURCE_MANIFEST_DIGEST_VERSION = 2


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
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
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "run.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


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
    manifest_path = run_root / "run.json"
    payload_paths: list[Path]
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload_paths = [run_root / path for path in manifest.get("runs", [])]
    else:
        payload_paths = sorted((run_root / RAW_RUNS_DIR).glob("*.json"))
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in payload_paths if path.is_file()]
    return payloads


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
    validation_results = [
        ValidationResult.model_validate(item)
        for payload in payloads
        if payload.get("mode") == "validation"
        for item in payload.get("results", [])
        if item.get("eval_kind") == kind
    ]
    return build_kind_benchmark(repo_root, run_root, skill, kind, live_payloads, validation_results)


def build_kind_benchmark(
    repo_root: Path,
    run_root: Path,
    skill: str,
    kind: str,
    live_payloads: list[dict[str, Any]],
    validation_results: list[ValidationResult] | None = None,
) -> dict[str, Any]:
    evals = []
    failures = []
    metadata_sources = []
    live_selection_keys: set[tuple[str, str, str]] = set()
    for payload in sorted(live_payloads, key=lambda item: str(item.get("mode", ""))):
        mode = str(payload["mode"])
        metadata_sources.append(payload.get("metadata", {}))
        results = [CaseResult.model_validate(item) for item in payload.get("results", [])]
        live_selection_keys.update(
            (result.id, result.base_id, result.prompt_id) for result in results
        )
        result_paths = payload.get("result_paths", {})
        for base_id, group in grouped_case_results(results).items():
            item = aggregate_kind_case_group(kind, group)
            item["mode"] = mode
            item["result_paths"] = result_paths.get(base_id, {})
            evals.append(item)
        failures.extend(collect_kind_failures(results, kind, mode))

    metadata = kind_report_metadata(skill, run_root, kind, metadata_sources)
    benchmark = {
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
    provenance_results = validation_results or []
    if provenance_results:
        validation_selection_keys = {
            (result.id, result.base_id, result.prompt_id)
            for result in provenance_results
        }
        if validation_selection_keys != live_selection_keys:
            raise ValueError(
                "live report results do not match validation provenance selections"
            )
    provenance = source_provenance(repo_root, provenance_results)
    if provenance:
        benchmark["source"] = provenance
    return benchmark


def source_input_digests(
    repo_root: Path,
    skill: str,
    kind: str,
    skill_path: Path,
    config_path: Path | None = None,
    *,
    definition_path: Path | None = None,
    fixture_dir: Path | None = None,
    prompt_id: str | None = None,
    eval_inputs: list[str] | None = None,
) -> dict[str, str]:
    root = repo_root.resolve()
    resolved_skill = skill_path.resolve()
    try:
        resolved_skill.relative_to(root)
    except ValueError:
        return {}

    paths = staged_skill_source_files(resolved_skill)
    paths.extend(shared_skill_reference_source_files(root))
    eval_roles = {
        "rubric": {"rubric"},
        "sanity": {"sanity"},
        "runtime": {"runtime"},
        "validation": {"rubric", "runtime", "sanity"},
    }.get(kind, set())
    eval_root = root / "evals"
    has_runtime_definition = False
    if definition_path is not None:
        if fixture_dir is None or prompt_id is None:
            raise ValueError(
                "selected eval provenance requires a fixture directory and prompt ID"
            )
        selected_paths, has_runtime_definition = selected_eval_source_files(
            root,
            skill,
            eval_roles,
            definition_path,
            fixture_dir,
            prompt_id,
            eval_inputs,
        )
        paths.extend(selected_paths)
    elif fixture_dir is not None or prompt_id is not None or eval_inputs is not None:
        raise ValueError("selected eval provenance requires a definition path")
    elif eval_roles and eval_root.is_dir():
        for path in iter_eval_files(eval_root):
            layout = eval_file_layout(path)
            if layout is None or layout.role not in eval_roles:
                continue
            try:
                definition = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"cannot read eval definition: {path}: {exc}") from exc
            if not isinstance(definition, dict):
                raise ValueError(f"eval definition must be an object: {path}")
            if definition.get("skill") == skill:
                paths.append(path)
                paths.extend(staged_fixture_source_files(layout.fixture_dir))
                prompts = definition.get("prompts", [])
                if not isinstance(prompts, list):
                    raise ValueError(f"eval definition prompts must be a list: {path}")
                for prompt in prompts:
                    if not isinstance(prompt, dict):
                        raise ValueError(
                            f"eval definition prompt must be an object: {path}"
                        )
                    eval_inputs = prompt.get("eval_inputs")
                    if eval_inputs is not None and (
                        not isinstance(eval_inputs, list)
                        or any(not isinstance(value, str) for value in eval_inputs)
                    ):
                        raise ValueError(
                            f"eval definition eval_inputs must be a string list: {path}"
                        )
                    paths.extend(
                        source
                        for _relative, source in fixture_eval_input_sources(
                            layout.fixture_dir,
                            eval_inputs,
                        )
                    )
                if layout.role == "runtime":
                    has_runtime_definition = True
                    paths.extend(runtime_definition_asset_files(path))
    if has_runtime_definition:
        paths.extend(shared_runtime_source_files(eval_root))
        paths.extend(runtime_repository_source_files(root))

    harness_root = root / "pytest-codex-evals"
    harness_package_root = harness_root / "src" / "pytest_codex_evals"
    if harness_package_root.is_dir():
        paths.extend(
            source_tree_files(
                harness_package_root,
                ("__pycache__", ".pytest_cache", ".DS_Store", "*.pyc"),
            )
        )
    for name in ("pyproject.toml", "uv.lock"):
        harness_metadata = harness_root / name
        if source := regular_source_file(harness_metadata):
            paths.append(source)
    if config_path is not None:
        config_source = regular_source_file(config_path)
        if config_source is None:
            raise ValueError(f"eval config input is missing: {config_path}")
        try:
            config_source.resolve().relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"eval config input must stay within the repository: {config_path}"
            ) from exc
        paths.append(config_source)
    elif eval_root.is_dir():
        for path in sorted(eval_root.glob("codex-evals*.toml")):
            if source := regular_source_file(path):
                paths.append(source)
    if eval_root.is_dir():
        for name in ("pyproject.toml", "uv.lock"):
            eval_metadata = eval_root / name
            if source := regular_source_file(eval_metadata):
                paths.append(source)

    digests: dict[str, str] = {}
    for path in sorted(set(paths)):
        relative = path.resolve().relative_to(root).as_posix()
        digests[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def selected_eval_source_files(
    repo_root: Path,
    skill: str,
    eval_roles: set[str],
    definition_path: Path,
    fixture_dir: Path,
    prompt_id: str,
    eval_inputs: list[str] | None,
) -> tuple[list[Path], bool]:
    definition_source = regular_source_file(definition_path)
    if definition_source is None:
        raise ValueError(f"selected eval definition is missing: {definition_path}")
    try:
        definition_source.resolve().relative_to(repo_root)
        resolved_fixture = fixture_dir.resolve()
        resolved_fixture.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError("selected eval source must stay within the repository") from exc

    layout = eval_file_layout(definition_source)
    if layout is None or layout.role not in eval_roles:
        raise ValueError(
            f"selected eval definition does not match {sorted(eval_roles)}: "
            f"{definition_path}"
        )
    if layout.fixture_dir.resolve() != resolved_fixture:
        raise ValueError(
            f"selected eval fixture does not match its definition: {fixture_dir}"
        )
    try:
        definition = json.loads(definition_source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"cannot read eval definition: {definition_source}: {exc}"
        ) from exc
    if not isinstance(definition, dict):
        raise ValueError(f"eval definition must be an object: {definition_source}")
    if definition.get("skill") != skill:
        raise ValueError(
            f"selected eval definition does not target skill {skill}: "
            f"{definition_source}"
        )
    prompts = definition.get("prompts", [])
    if not isinstance(prompts, list):
        raise ValueError(f"eval definition prompts must be a list: {definition_source}")
    matching_prompts = [
        prompt
        for prompt in prompts
        if isinstance(prompt, dict) and prompt.get("id") == prompt_id
    ]
    if len(matching_prompts) != 1:
        raise ValueError(
            f"selected eval prompt {prompt_id!r} is missing or duplicated: "
            f"{definition_source}"
        )
    selected_inputs = matching_prompts[0].get("eval_inputs")
    if selected_inputs is None:
        selected_inputs = []
    if (
        not isinstance(selected_inputs, list)
        or any(not isinstance(value, str) for value in selected_inputs)
    ):
        raise ValueError(
            f"eval definition eval_inputs must be a string list: {definition_source}"
        )
    recorded_inputs = list(eval_inputs or [])
    if selected_inputs != recorded_inputs:
        raise ValueError(
            f"selected eval inputs do not match prompt {prompt_id!r}: "
            f"{definition_source}"
        )

    paths = [definition_source, *staged_fixture_source_files(resolved_fixture)]
    paths.extend(
        source
        for _relative, source in fixture_eval_input_sources(
            resolved_fixture,
            recorded_inputs,
        )
    )
    is_runtime = layout.role == "runtime"
    if is_runtime:
        paths.extend(runtime_definition_asset_files(definition_source))
    return paths, is_runtime


def source_input_digests_for_kinds(
    repo_root: Path,
    skill: str,
    kinds: list[str],
    skill_path: Path,
    config_path: Path | None = None,
) -> dict[str, str]:
    files: dict[str, str] = {}
    for kind in sorted(set(kinds)):
        for path, digest in source_input_digests(
            repo_root,
            skill,
            kind,
            skill_path,
            config_path,
        ).items():
            existing = files.get(path)
            if existing is not None and existing != digest:
                raise ValueError(f"source input changed while building manifest: {path}")
            files[path] = digest
    return files


def source_input_digests_for_selections(
    repo_root: Path,
    skill: str,
    selections: list[dict[str, Any]],
    skill_path: Path,
    config_path: Path | None = None,
) -> dict[str, str]:
    files: dict[str, str] = {}
    for selection in selections:
        manifest = source_input_digests(
            repo_root,
            skill,
            selection["eval_kind"],
            skill_path,
            config_path,
            definition_path=repo_root / selection["definition_path"],
            fixture_dir=repo_root / selection["fixture_dir"],
            prompt_id=selection["prompt_id"],
            eval_inputs=selection["eval_inputs"],
        )
        for path, digest in manifest.items():
            existing = files.get(path)
            if existing is not None and existing != digest:
                raise ValueError(f"source input changed while building manifest: {path}")
            files[path] = digest
    return files


def source_provenance(
    repo_root: Path,
    results: list[ValidationResult],
    *,
    selection_scope: str | None = None,
) -> dict[str, Any] | None:
    manifest_results = [result for result in results if result.source_files]
    manifests = [result.source_files for result in manifest_results]
    if not manifests:
        return None
    files: dict[str, str] = {}
    for manifest in manifests:
        for path, digest in manifest.items():
            existing = files.get(path)
            if existing is not None and existing != digest:
                raise ValueError(f"source input changed during eval run: {path}")
            files[path] = digest
    skill_paths = {
        Path(result.skill_path).resolve().relative_to(repo_root.resolve()).as_posix()
        for result in results
        if result.source_files
    }
    if len(skill_paths) != 1:
        raise ValueError("eval run contains inconsistent skill source paths")
    config_paths = {
        Path(result.config_path)
        .resolve()
        .relative_to(repo_root.resolve())
        .as_posix()
        for result in results
        if result.source_files and result.config_path
    }
    if len(config_paths) > 1:
        raise ValueError("eval run contains inconsistent config source paths")
    eval_kinds = sorted({result.eval_kind for result in results if result.source_files})
    selections: list[dict[str, Any]] | None = None
    if manifest_results and all(
        result.selected_eval_inputs is not None for result in manifest_results
    ):
        selections_by_key: dict[
            tuple[str, str, str, str, tuple[str, ...]], dict[str, Any]
        ] = {}
        root = repo_root.resolve()
        for result in manifest_results:
            try:
                definition_path = (
                    Path(result.definition_path).resolve().relative_to(root).as_posix()
                )
                fixture_dir = (
                    Path(result.fixture_dir).resolve().relative_to(root).as_posix()
                )
            except ValueError as exc:
                raise ValueError(
                    "selected eval source path escapes the repository"
                ) from exc
            selected_inputs = tuple(result.selected_eval_inputs or [])
            key = (
                definition_path,
                fixture_dir,
                result.prompt_id,
                result.eval_kind,
                selected_inputs,
            )
            selections_by_key[key] = {
                "definition_path": definition_path,
                "fixture_dir": fixture_dir,
                "prompt_id": result.prompt_id,
                "eval_kind": result.eval_kind,
                "eval_inputs": list(selected_inputs),
            }
        selections = [selections_by_key[key] for key in sorted(selections_by_key)]
    skill_path = skill_paths.pop()
    source_config_path = config_paths.pop() if config_paths else None
    provenance: dict[str, Any] = {
        "digest_version": SOURCE_MANIFEST_DIGEST_VERSION,
        "digest": source_manifest_digest(
            files,
            digest_version=SOURCE_MANIFEST_DIGEST_VERSION,
            eval_kinds=eval_kinds,
            skill_path=skill_path,
            config_path=source_config_path,
            selections=selections,
            selection_scope=selection_scope,
        ),
        "eval_kinds": eval_kinds,
        "files": files,
        "skill_path": skill_path,
    }
    if selections is not None:
        provenance["selections"] = selections
    if source_config_path is not None:
        provenance["config_path"] = source_config_path
    if selection_scope is not None:
        provenance["selection_scope"] = selection_scope
    return provenance


def source_manifest_digest(
    files: dict[str, str],
    *,
    digest_version: int,
    eval_kinds: list[str] | None = None,
    skill_path: str | None = None,
    config_path: str | None = None,
    selections: list[dict[str, Any]] | None = None,
    selection_scope: str | None = None,
) -> str:
    digest = hashlib.sha256()
    if digest_version == 1:
        for path, file_digest in sorted(files.items()):
            digest.update(path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(file_digest.encode("ascii"))
            digest.update(b"\n")
        return digest.hexdigest()
    if digest_version != SOURCE_MANIFEST_DIGEST_VERSION:
        raise ValueError(f"unsupported source manifest digest version: {digest_version}")
    if eval_kinds is None or skill_path is None:
        raise ValueError("source manifest v2 requires eval kinds and a skill path")
    identity: dict[str, Any] = {
        "digest_version": digest_version,
        "eval_kinds": sorted(set(eval_kinds)),
        "files": {path: files[path] for path in sorted(files)},
        "skill_path": skill_path,
    }
    if config_path is not None:
        identity["config_path"] = config_path
    if selections is not None:
        identity["selections"] = sorted(
            selections,
            key=lambda selection: (
                selection["definition_path"],
                selection["fixture_dir"],
                selection["prompt_id"],
                selection["eval_kind"],
                tuple(selection["eval_inputs"]),
            ),
        )
    if selection_scope is not None:
        identity["selection_scope"] = selection_scope
    digest.update(b"obstudio-source-manifest\0")
    digest.update(
        json.dumps(
            identity,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    return digest.hexdigest()


def source_selection_key(
    selection: dict[str, Any],
) -> tuple[str, str, str, str, tuple[str, ...]]:
    return (
        selection["definition_path"],
        selection["fixture_dir"],
        selection["prompt_id"],
        selection["eval_kind"],
        tuple(selection["eval_inputs"]),
    )


def full_validation_source_selections(
    repo_root: Path,
    skill: str,
) -> list[dict[str, Any]]:
    root = repo_root.resolve()
    eval_root = root / "evals" if (root / "evals").is_dir() else root
    selections: list[dict[str, Any]] = []
    for path in iter_eval_files(eval_root):
        layout = eval_file_layout(path)
        if layout is None or layout.role is None:
            continue
        try:
            definition = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read eval definition: {path}: {exc}") from exc
        if not isinstance(definition, dict):
            raise ValueError(f"eval definition must be an object: {path}")
        if definition.get("skill") != skill:
            continue
        prompts = definition.get("prompts")
        if not isinstance(prompts, list):
            raise ValueError(f"eval definition prompts must be a list: {path}")
        for prompt in prompts:
            if not isinstance(prompt, dict):
                raise ValueError(f"eval definition prompt must be an object: {path}")
            prompt_id = prompt.get("id")
            eval_inputs = prompt.get("eval_inputs", [])
            if (
                not isinstance(prompt_id, str)
                or not prompt_id
                or not isinstance(eval_inputs, list)
                or any(not isinstance(value, str) for value in eval_inputs)
            ):
                raise ValueError(f"eval definition prompt selection is malformed: {path}")
            selections.append(
                {
                    "definition_path": path.resolve().relative_to(root).as_posix(),
                    "fixture_dir": layout.fixture_dir.resolve().relative_to(root).as_posix(),
                    "prompt_id": prompt_id,
                    "eval_kind": layout.role,
                    "eval_inputs": eval_inputs,
                }
            )
    return sorted(selections, key=source_selection_key)


def source_manifest_selections(
    source: dict[str, Any],
    benchmark_path: Path,
) -> list[dict[str, Any]] | None:
    raw_selections = source.get("selections")
    if raw_selections is None:
        return None
    if not isinstance(raw_selections, list) or not raw_selections:
        raise ValueError(f"{benchmark_path}: source selections are malformed")

    selections: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, tuple[str, ...]]] = set()
    for raw in raw_selections:
        if not isinstance(raw, dict):
            raise ValueError(f"{benchmark_path}: source selections are malformed")
        definition_path = raw.get("definition_path")
        fixture_dir = raw.get("fixture_dir")
        prompt_id = raw.get("prompt_id")
        eval_kind = raw.get("eval_kind")
        eval_inputs = raw.get("eval_inputs")
        if (
            not isinstance(definition_path, str)
            or not isinstance(fixture_dir, str)
            or not isinstance(prompt_id, str)
            or not prompt_id
            or not isinstance(eval_kind, str)
            or eval_kind not in {"rubric", "runtime", "sanity"}
            or not isinstance(eval_inputs, list)
            or any(not isinstance(value, str) for value in eval_inputs)
        ):
            raise ValueError(f"{benchmark_path}: source selections are malformed")
        for relative in (definition_path, fixture_dir):
            path = Path(relative)
            if (
                not relative
                or path.is_absolute()
                or path.as_posix() != relative
                or any(part in {"", ".", ".."} for part in path.parts)
            ):
                raise ValueError(
                    f"{benchmark_path}: source selection path is malformed"
                )
        key = source_selection_key(raw)
        if key in seen:
            raise ValueError(f"{benchmark_path}: source selections are duplicated")
        seen.add(key)
        selections.append(
            {
                "definition_path": definition_path,
                "fixture_dir": fixture_dir,
                "prompt_id": prompt_id,
                "eval_kind": eval_kind,
                "eval_inputs": eval_inputs,
            }
        )
    return selections


def verify_published_report_sources(repo_root: Path) -> list[Path]:
    verified: list[Path] = []
    root = repo_root.resolve()
    benchmark_paths = sorted((root / "eval-reports").glob("*/*/benchmark.json"))
    provenance_skills = {
        path.parent.parent.name
        for path in benchmark_paths
        if isinstance(json.loads(path.read_text(encoding="utf-8")).get("source"), dict)
    }
    for benchmark_path in benchmark_paths:
        benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
        source = benchmark.get("source")
        if not isinstance(source, dict):
            if benchmark_path.parent.parent.name in provenance_skills:
                raise ValueError(f"{benchmark_path}: source manifest is missing; rerun the owning eval")
            continue
        files = source.get("files")
        if not isinstance(files, dict) or not files:
            raise ValueError(f"{benchmark_path}: source manifest is empty")
        raw_digest_version = source.get("digest_version")
        if raw_digest_version is None:
            digest_version = 1
        elif (
            type(raw_digest_version) is not int
            or raw_digest_version != SOURCE_MANIFEST_DIGEST_VERSION
        ):
            raise ValueError(
                f"{benchmark_path}: source manifest digest version is malformed"
            )
        else:
            digest_version = raw_digest_version
        skill = benchmark.get("skill")
        kind = benchmark.get("kind")
        skill_path = source.get("skill_path")
        if not isinstance(skill, str) or not isinstance(kind, str) or not isinstance(skill_path, str):
            raise ValueError(f"{benchmark_path}: source identity is malformed")
        eval_kinds = source.get("eval_kinds")
        if eval_kinds is None:
            if digest_version == SOURCE_MANIFEST_DIGEST_VERSION:
                raise ValueError(f"{benchmark_path}: source eval kinds are malformed")
            eval_kinds = [kind]
        if (
            not isinstance(eval_kinds, list)
            or not eval_kinds
            or any(
                not isinstance(eval_kind, str)
                or eval_kind not in {"rubric", "runtime", "sanity"}
                for eval_kind in eval_kinds
            )
        ):
            raise ValueError(f"{benchmark_path}: source eval kinds are malformed")
        declared_eval_kinds = sorted(set(eval_kinds))
        if kind != "validation" and declared_eval_kinds != [kind]:
            raise ValueError(f"{benchmark_path}: source eval kinds do not match report kind")
        selections = source_manifest_selections(source, benchmark_path)
        if selections is not None and sorted(
            {selection["eval_kind"] for selection in selections}
        ) != declared_eval_kinds:
            raise ValueError(
                f"{benchmark_path}: source selections do not match eval kinds"
            )
        selection_scope = None
        reconstruction_eval_kinds = declared_eval_kinds
        if kind == "validation":
            selection_scope = source.get("selection_scope")
            if selection_scope == "full":
                reconstruction_eval_kinds = ["rubric", "runtime", "sanity"]
            elif selection_scope != "filtered":
                raise ValueError(f"{benchmark_path}: validation source selection scope is malformed")
        elif source.get("selection_scope") is not None:
            raise ValueError(f"{benchmark_path}: source selection scope is malformed")
        if (
            digest_version == SOURCE_MANIFEST_DIGEST_VERSION
            and kind == "validation"
            and selection_scope == "full"
        ):
            if selections is None:
                raise ValueError(
                    f"{benchmark_path}: full validation source selections are missing"
                )
            try:
                expected_selections = full_validation_source_selections(root, skill)
            except (OSError, ValueError) as exc:
                raise ValueError(
                    f"{benchmark_path}: eval report inputs are stale; rerun the owning eval"
                ) from exc
            if sorted(selections, key=source_selection_key) != expected_selections:
                raise ValueError(
                    f"{benchmark_path}: eval report inputs are stale; rerun the owning eval"
                )
        resolved_skill_path = (root / skill_path).resolve()
        try:
            resolved_skill_path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"{benchmark_path}: skill path escapes the repository: {skill_path}") from exc
        source_config_path = source.get("config_path")
        resolved_config_path = None
        if source_config_path is not None:
            if not isinstance(source_config_path, str) or not source_config_path:
                raise ValueError(f"{benchmark_path}: source config path is malformed")
            resolved_config_path = root / source_config_path
            try:
                resolved_config_path.resolve().relative_to(root)
            except ValueError as exc:
                raise ValueError(
                    f"{benchmark_path}: config path escapes the repository: {source_config_path}"
                ) from exc
            metadata = benchmark.get("metadata")
            if (
                not isinstance(metadata, dict)
                or metadata.get("config_path") != source_config_path
            ):
                raise ValueError(
                    f"{benchmark_path}: source config path does not match report metadata"
                )
        try:
            if selections is not None and selection_scope != "full":
                current = source_input_digests_for_selections(
                    root,
                    skill,
                    selections,
                    resolved_skill_path,
                    resolved_config_path,
                )
            else:
                current = source_input_digests_for_kinds(
                    root,
                    skill,
                    reconstruction_eval_kinds,
                    resolved_skill_path,
                    resolved_config_path,
                )
        except ValueError as exc:
            raise ValueError(
                f"{benchmark_path}: eval report inputs are stale; rerun the owning eval"
            ) from exc
        for relative, expected in files.items():
            if not isinstance(relative, str) or not isinstance(expected, str):
                raise ValueError(f"{benchmark_path}: source manifest is malformed")
            path = (root / relative).resolve()
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"{benchmark_path}: source path escapes the repository: {relative}") from exc
            if not path.is_file():
                raise ValueError(f"{benchmark_path}: source input is missing: {relative}")
        expected_digest = source.get("digest")
        current_digest = source_manifest_digest(
            current,
            digest_version=digest_version,
            eval_kinds=declared_eval_kinds,
            skill_path=skill_path,
            config_path=source_config_path,
            selections=selections,
            selection_scope=selection_scope,
        )
        if current != files or current_digest != expected_digest:
            raise ValueError(f"{benchmark_path}: eval report inputs are stale; rerun the owning eval")
        verified.append(benchmark_path)
    return verified


def aggregate_kind_case_group(kind: str, group: list[CaseResult]) -> dict[str, Any]:
    first = group[0]
    return {
        "id": first.base_id,
        "case": f"{first.language}/{first.service}",
        "language": first.language,
        "service": first.service,
        "prompt_count": len(group),
        "prompts": [result.prompt_id for result in group],
        "with_skill": aggregate_kind_side(kind, group, "with_skill"),
        "with_baseline": aggregate_kind_side(kind, group, "with_baseline"),
    }


def aggregate_kind_side(kind: str, results: list[CaseResult], side_key: str) -> dict[str, Any] | None:
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
        "agent_usage": aggregate_usage(
            [side.agent_usage for side in sides], expected_records=len(sides)
        ),
    }
    if kind == "rubric":
        rubric = [grade for side in sides if (grade := load_rubric_grade(side)) is not None]
        rubric_total = sum(int(grade["total"]) for grade in rubric)
        rubric_passed = sum(int(grade["passed"]) for grade in rubric)
        scores = [int(grade["score"]) for grade in rubric if isinstance(grade.get("score"), int)]
        summary["rubric"] = None if not rubric else {"passed": rubric_passed, "total": rubric_total, "average_score": average(scores) if scores else None}
        summary["rubric_tokens"] = sum(side.rubric_tokens for side in sides)
        summary["rubric_duration_seconds"] = round(sum(side.rubric_duration_seconds for side in sides), 3)
        summary["rubric_usage"] = aggregate_usage(
            [side.rubric_usage for side in sides], expected_records=len(sides)
        )
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
        "agent_usage": aggregate_usage(
            [side.get("agent_usage") for side in sides],
            expected_records=sum(int(side["prompt_count"]) for side in sides),
        ),
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
        summary["rubric_usage"] = aggregate_usage(
            [side.get("rubric_usage") for side in sides],
            expected_records=sum(int(side["prompt_count"]) for side in sides),
        )
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


def render_kind_report(skill: str, benchmark: dict[str, Any]) -> str:
    kind = str(benchmark["kind"])
    template = template_for_kind(kind)
    lines = [f"# {skill} {template.summary_title.replace(' Summary', '')} Codex Eval Report"]
    lines.extend(render_environment_table(benchmark["metadata"], "Mode"))
    lines.extend(render_kind_summary_section(template, benchmark["evals"]))
    lines.extend(render_kind_usage_sections(kind, benchmark["evals"]))
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
        "| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    if not evals:
        lines.append("| - | - | - | 0 | - | - | - | - | - | - |")
        return lines
    for item in evals:
        lines.append(
            "| {mode} | {eval_id} | {service} | {prompts} | {ws} | {ws_tokens} | {ws_time} | {base} | {base_tokens} | {base_time} |".format(
                mode=markdown_cell(item["mode"]),
                eval_id=markdown_cell(item["id"]),
                service=markdown_cell(item["case"]),
                prompts=item["prompt_count"],
                ws=format_kind_side(item.get("with_skill"), template.category),
                ws_tokens=format_tokens(item.get("with_skill")),
                ws_time=format_duration(item.get("with_skill")),
                base=format_kind_side(item.get("with_baseline"), template.category),
                base_tokens=format_tokens(item.get("with_baseline")),
                base_time=format_duration(item.get("with_baseline")),
            )
        )
    return lines


def render_kind_usage_sections(kind: str, evals: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    agent_rows = usage_rows(evals, "agent_usage")
    if agent_rows:
        lines.extend(render_usage_table("Agent Token Usage", agent_rows))
    if kind == "rubric":
        judge_rows = usage_rows(evals, "rubric_usage")
        if judge_rows:
            lines.extend(render_usage_table("Judge Token Usage", judge_rows))
    return lines


def render_usage_table(title: str, rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "",
        f"## {title}",
        "",
        "| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |",
        "|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {mode} | {eval_id} | {service} | {side} | {provider} | {source} | {status} | {coverage} | {input} | {cached} | {creation} | {output} | {reasoning} | {provider_total} | {derived_total} |".format(
                mode=markdown_cell(row["mode"]),
                eval_id=markdown_cell(row["eval_id"]),
                service=markdown_cell(row["service"]),
                side=markdown_cell(row["side"]),
                provider=markdown_cell(row["provider"]),
                source=markdown_cell(row["source"]),
                status=markdown_cell(row["status"]),
                coverage=markdown_cell(row["coverage"]),
                input=markdown_cell(row["input_tokens"]),
                cached=markdown_cell(row["cached_input_tokens"]),
                creation=markdown_cell(row["cache_creation_input_tokens"]),
                output=markdown_cell(row["output_tokens"]),
                reasoning=markdown_cell(row["reasoning_output_tokens"]),
                provider_total=markdown_cell(row["provider_total_tokens"]),
                derived_total=markdown_cell(row["derived_total_tokens"]),
            )
        )
    return lines


def usage_rows(evals: list[dict[str, Any]], usage_key: str) -> list[dict[str, Any]]:
    if not any(
        side.get(usage_key) is not None
        for item in evals
        for side_key in ("with_skill", "with_baseline")
        if (side := item.get(side_key)) is not None
    ):
        return []

    rows: list[dict[str, Any]] = []
    for item in evals:
        for side_key in ("with_skill", "with_baseline"):
            side = item.get(side_key)
            if side is None:
                continue
            usage = side.get(usage_key)
            rows.append(
                {
                    "mode": item.get("mode"),
                    "eval_id": item.get("id"),
                    "service": item.get("case"),
                    "side": side_key,
                    "provider": usage.get("provider", "unknown") if usage else "unknown",
                    "source": usage.get("source", "unknown") if usage else "unknown",
                    "status": usage_status(usage, int(side.get("prompt_count") or 0)),
                    "coverage": usage_coverage(usage, int(side.get("prompt_count") or 0)),
                    **{
                        field: usage_value(usage, field, int(side.get("prompt_count") or 0))
                        for field in TOKEN_USAGE_FIELDS
                    },
                }
            )
    return rows


def usage_payload(value: TokenUsage | dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, TokenUsage):
        payload = value.model_dump(mode="json")
        payload["effective_total_tokens"] = value.total_tokens
        return payload
    payload = dict(value)
    if "effective_total_tokens" not in payload:
        payload["effective_total_tokens"] = preferred_usage_total(payload)
    return payload


def preferred_usage_total(payload: dict[str, Any]) -> int | None:
    coverage = payload.get("coverage")
    if isinstance(coverage, dict):
        records = int(coverage.get("record_count") or 0)
        preferred_count = int(coverage.get("preferred_total_count") or 0)
        if records == 0 or preferred_count != records:
            return None
        field_counts = coverage.get("field_counts") or {}
        provider_count = int(field_counts.get("provider_total_tokens") or 0)
        if (
            provider_count == records
            and payload.get("provider_total_tokens") is not None
        ):
            return int(payload["provider_total_tokens"])
        derived_count = int(field_counts.get("derived_total_tokens") or 0)
        if (
            provider_count == 0
            and derived_count == records
            and payload.get("derived_total_tokens") is not None
        ):
            return int(payload["derived_total_tokens"])
        return None
    provider_total = payload.get("provider_total_tokens")
    if provider_total is not None:
        return int(provider_total)
    derived_total = payload.get("derived_total_tokens")
    if derived_total is not None:
        return int(derived_total)
    return None


def aggregate_usage(
    usages: list[TokenUsage | dict[str, Any] | None],
    *,
    expected_records: int | None = None,
) -> dict[str, Any] | None:
    payloads = [usage_payload(usage) for usage in usages]
    modeled = [payload for payload in payloads if payload is not None]
    if not modeled:
        return None

    field_counts = {field: 0 for field in TOKEN_USAGE_FIELDS}
    field_values = {field: 0 for field in TOKEN_USAGE_FIELDS}
    providers: list[str] = []
    sources: list[str] = []
    record_count = 0
    modeled_count = 0
    observed_count = 0
    recognized_count = 0
    usage_record_count = 0
    selected_record_count = 0
    preferred_total_count = 0
    effective_total = 0
    effective_total_count = 0

    for payload in modeled:
        coverage = payload.get("coverage")
        if isinstance(coverage, dict):
            child_records = int(coverage.get("record_count") or 0)
            child_modeled = int(coverage.get("modeled_count") or 0)
            child_observed = int(coverage.get("observed_count") or 0)
            child_recognized = int(coverage.get("recognized_count") or 0)
            child_field_counts = coverage.get("field_counts") or {}
            child_preferred_count = coverage.get("preferred_total_count")
            if child_preferred_count is None:
                provider_count = int(
                    child_field_counts.get("provider_total_tokens") or 0
                )
                derived_count = int(
                    child_field_counts.get("derived_total_tokens") or 0
                )
                if (
                    provider_count == child_records
                    and payload.get("provider_total_tokens") is not None
                ):
                    child_preferred_count = child_records
                elif (
                    provider_count == 0
                    and derived_count == child_records
                    and payload.get("derived_total_tokens") is not None
                ):
                    child_preferred_count = child_records
                else:
                    child_preferred_count = 0
        else:
            child_records = 1
            child_modeled = 1
            child_observed = int(bool(payload.get("observed")))
            child_recognized = int(
                payload.get("effective_total_tokens") is not None
                or any(payload.get(field) is not None for field in TOKEN_USAGE_FIELDS)
            )
            child_field_counts = {
                field: int(payload.get(field) is not None)
                for field in TOKEN_USAGE_FIELDS
            }
            child_preferred_count = int(
                payload.get("effective_total_tokens") is not None
            )

        record_count += child_records
        modeled_count += child_modeled
        observed_count += child_observed
        recognized_count += child_recognized
        usage_record_count += int(payload.get("usage_record_count") or 0)
        selected_record_count += int(payload.get("selected_record_count") or 0)
        preferred_total_count += int(child_preferred_count or 0)
        child_effective_total = payload.get("effective_total_tokens")
        if child_effective_total is not None and int(child_preferred_count or 0) > 0:
            effective_total += int(child_effective_total)
            effective_total_count += int(child_preferred_count or 0)
        providers.append(str(payload.get("provider") or "unknown"))
        sources.append(str(payload.get("source") or "unknown"))

        for field in TOKEN_USAGE_FIELDS:
            count = int(child_field_counts.get(field) or 0)
            field_counts[field] += count
            if count and payload.get(field) is not None:
                field_values[field] += int(payload[field])

    record_count = max(record_count, expected_records or len(usages))
    result: dict[str, Any] = {
        "provider": combined_label(providers),
        "source": combined_label(sources),
        "observed": observed_count > 0,
        "usage_record_count": usage_record_count,
        "selected_record_count": selected_record_count,
        **{
            field: field_values[field] if field_counts[field] else None
            for field in TOKEN_USAGE_FIELDS
        },
        "effective_total_tokens": (
            effective_total if effective_total_count else None
        ),
        "coverage": {
            "record_count": record_count,
            "modeled_count": modeled_count,
            "observed_count": observed_count,
            "recognized_count": recognized_count,
            "preferred_total_count": preferred_total_count,
            "field_counts": field_counts,
        },
    }
    return result


def combined_label(values: list[str]) -> str:
    unique = sorted(set(value or "unknown" for value in values))
    if not unique:
        return "unknown"
    if len(unique) == 1:
        return unique[0]
    return "mixed"


def usage_status(usage: dict[str, Any] | None, expected_records: int) -> str:
    if usage is None:
        return "legacy"
    coverage = usage.get("coverage") or {}
    records = int(coverage.get("record_count") or expected_records or 1)
    modeled = int(coverage.get("modeled_count") or 0)
    observed = int(coverage.get("observed_count") or 0)
    recognized = int(coverage.get("recognized_count") or 0)
    if modeled == 0:
        return "legacy"
    if observed == 0:
        return "absent"
    if recognized == 0:
        return "unrecognized"
    preferred_totals = int(coverage.get("preferred_total_count") or 0)
    if recognized < records or preferred_totals < records:
        return "partial"
    return "measured"


def usage_coverage(usage: dict[str, Any] | None, expected_records: int) -> str:
    if usage is None:
        return f"0/{expected_records} modeled"
    coverage = usage.get("coverage") or {}
    records = int(coverage.get("record_count") or expected_records or 1)
    modeled = int(coverage.get("modeled_count") or 0)
    observed = int(coverage.get("observed_count") or 0)
    recognized = int(coverage.get("recognized_count") or 0)
    parts = [f"{recognized}/{records} recognized"]
    if observed != records or observed != recognized:
        parts.append(f"{observed}/{records} observed")
    if modeled != records:
        parts.append(f"{modeled}/{records} modeled")
    return "; ".join(parts)


def usage_value(
    usage: dict[str, Any] | None, field: str, expected_records: int
) -> str:
    if usage is None:
        return "unknown"
    coverage = usage.get("coverage") or {}
    records = int(coverage.get("record_count") or expected_records or 1)
    field_counts = coverage.get("field_counts") or {}
    count = int(field_counts.get(field) or 0)
    value = usage.get(field)
    if count == 0 or value is None:
        return "unknown"
    if count < records:
        return f"{int(value)} ({count}/{records})"
    return str(int(value))


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
    report_dir = run_root / kind
    report_dir.mkdir(parents=True, exist_ok=True)
    benchmark_path = report_dir / "benchmark.json"
    report_path = report_dir / "report.md"
    benchmark_path.write_text(json.dumps(benchmark, indent=2), encoding="utf-8")
    report_path.write_text(report, encoding="utf-8")

    latest_root = output_dir or repo_root / "eval-reports"
    latest_dir = latest_root / skill / kind
    latest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(report_path, latest_dir / "report.md")
    shutil.copyfile(benchmark_path, latest_dir / "benchmark.json")
    return report_path, benchmark_path


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
    for base_id, group in grouped_case_results(results).items():
        first = group[0]
        eval_dir = run_root / "results" / first.language / first.service / eval_kind(base_id)
        eval_dir.mkdir(parents=True, exist_ok=True)

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
        eval_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

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
            side_path.write_text(json.dumps(side_payload, indent=2), encoding="utf-8")
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
        "agent_usage": usage_payload(side.agent_usage),
        "rubric_usage": usage_payload(side.rubric_usage),
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
        "agent_usage": aggregate_usage(
            [side.agent_usage for side in sides], expected_records=len(sides)
        ),
        "rubric_usage": aggregate_usage(
            [side.rubric_usage for side in sides], expected_records=len(sides)
        ),
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

    benchmark = {
        "schema_version": 1,
        "kind": "validation",
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
    selection_scope = metadata.get("validation_scope")
    if selection_scope not in {"filtered", "full"}:
        raise ValueError("validation report metadata is missing its selection scope")
    provenance = source_provenance(repo_root, results, selection_scope=selection_scope)
    if provenance:
        benchmark["source"] = provenance
    return benchmark


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
    # Raw run manifests need the repository root to locate artifacts, but the
    # published benchmark is portable and must not expose a developer's local
    # account name or workspace layout.
    normalized.pop("repo_root", None)
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

    lines = [
        "",
        "## Environment",
        "",
        "| Field | Value |",
        "|---|---|",
    ]
    for label, key in rows:
        lines.append(f"| {label} | {markdown_cell(metadata.get(key))} |")
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


def load_rubric_grade(side: SideResult) -> dict[str, Any] | None:
    if not side.rubric_grade_path:
        return None
    path = Path(side.rubric_grade_path)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
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


def format_tokens(side: dict[str, Any] | None) -> str:
    if side is None:
        return "-"
    usage = side.get("agent_usage")
    if usage is not None:
        tokens = complete_usage_total(usage)
        if tokens is None:
            coverage = usage.get("coverage") or {}
            records = int(coverage.get("record_count") or 1)
            preferred_count = int(coverage.get("preferred_total_count") or 0)
            if preferred_count != records or "agent_tokens" not in side:
                return "unknown"
            tokens = int(side.get("agent_tokens") or 0)
        return compact_token_count(tokens)
    combined_tokens = int(side.get("tokens") or 0)
    agent_tokens = int(side.get("agent_tokens") or 0)
    rubric_tokens = int(side.get("rubric_tokens") or 0)
    if agent_tokens != 0 or rubric_tokens != 0 or combined_tokens == 0:
        tokens = agent_tokens
    else:
        tokens = combined_tokens
    return compact_token_count(tokens)


def complete_usage_total(usage: dict[str, Any]) -> int | None:
    coverage = usage.get("coverage") or {}
    records = int(coverage.get("record_count") or 1)
    preferred_count = int(coverage.get("preferred_total_count") or 0)
    if "effective_total_tokens" in usage:
        if (
            preferred_count == records
            and usage.get("effective_total_tokens") is not None
        ):
            return int(usage["effective_total_tokens"])
        return None
    field_counts = coverage.get("field_counts") or {}
    provider_count = int(field_counts.get("provider_total_tokens") or 0)
    if provider_count == records and usage.get("provider_total_tokens") is not None:
        return int(usage["provider_total_tokens"])
    if provider_count > 0:
        return None
    derived_count = int(field_counts.get("derived_total_tokens") or 0)
    if derived_count == records and usage.get("derived_total_tokens") is not None:
        return int(usage["derived_total_tokens"])
    return None


def compact_token_count(tokens: int) -> str:
    if tokens >= 1_000_000:
        return compact_scaled_token_count(tokens, 1_000_000, "M")
    if tokens >= 1_000:
        return compact_scaled_token_count(tokens, 1_000, "K")
    return str(tokens)


def compact_scaled_token_count(tokens: int, scale: int, suffix: str) -> str:
    tenths, remainder = divmod(tokens * 10, scale)
    if remainder * 2 > scale or (remainder * 2 == scale and tenths % 2 == 1):
        tenths += 1
    whole, decimal = divmod(tenths, 10)
    return f"{whole}.{decimal}{suffix}"


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
