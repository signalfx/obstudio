#!/usr/bin/env python3
"""Resolve cache-backed, Go-compatible OpenTelemetry dependency pins.

This helper is deliberately read-only. It inspects go.mod files already in the
module cache and emits a candidate command; it never invokes Go or a shell. A
plan is complete only when the file proxy can serve the recursively selected
dependency closure and every selected module supports the project's Go version.
When only the exact direct bundle is ready, the additive ``bootstrap_probe``
field can expose that narrower candidate for an isolated executable probe.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
MAX_GO_MOD_BYTES = 1_000_000
MAX_WARNINGS = 32
MAX_CANDIDATE_REJECTIONS = 32
MAX_CLOSURE_MODULES = 256
MAX_CLOSURE_STEPS = 1024
MAX_REQUIREMENTS_PER_GO_MOD = 512
PROXY_ARTIFACT_SUFFIXES = ("mod", "info", "zip", "ziphash")

OTELHTTP_MODULE = (
    "go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
)
COMPANION_MODULES = (
    "go.opentelemetry.io/otel",
    "go.opentelemetry.io/otel/sdk",
    "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp",
    "go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp",
)

GO_DIRECTIVE_VALUE = re.compile(r"^go\s+(?P<version>\d+\.\d+(?:\.\d+)?)$")
MODULE_DIRECTIVE = re.compile(
    r"^\s*module\s+(?P<module>[^\s]+)\s*(?://.*)?$",
    re.MULTILINE,
)
SEMVER = re.compile(
    r"^v(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


class Warnings:
    def __init__(self) -> None:
        self.items: list[str] = []
        self.omitted = 0

    def add(self, message: str) -> None:
        if len(self.items) < MAX_WARNINGS:
            self.items.append(message)
        else:
            self.omitted += 1


def split_go_mod_comment(line: str) -> tuple[str, str]:
    """Split a // comment while respecting Go quoted and raw strings."""

    quote: str | None = None
    escaped = False
    for index, character in enumerate(line):
        if quote == '"':
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if quote == "`":
            if character == quote:
                quote = None
            continue
        if character in {'"', "`"}:
            quote = character
            continue
        if character == "/" and line[index : index + 2] == "//":
            return line[:index], line[index + 2 :]
    return line, ""


def parse_requirements(text: str) -> dict[str, Any]:
    """Parse the bounded go.mod surface needed for offline closure proof.

    This intentionally does not attempt to implement the entire modfile
    grammar. Unsupported requirement syntax is reported and therefore prevents
    a complete plan instead of being guessed through.
    """

    requirements: list[dict[str, Any]] = []
    issues: list[str] = []
    block: str | None = None
    has_replace = False
    has_exclude = False

    def add_requirement(payload: str, comment: str, line_number: int) -> None:
        if len(requirements) >= MAX_REQUIREMENTS_PER_GO_MOD:
            marker = f"requirement-limit-exceeded:{MAX_REQUIREMENTS_PER_GO_MOD}"
            if marker not in issues:
                issues.append(marker)
            return
        fields = payload.split()
        if len(fields) != 2 or any(
            field.startswith(('"', "`")) or field.endswith(('"', "`"))
            for field in fields
        ):
            issues.append(f"unsupported-requirement-syntax:{line_number}")
            return
        requirements.append(
            {
                "module": fields[0],
                "version": fields[1],
                "indirect": bool(
                    re.search(r"(?:^|\s)indirect(?:\s|$)", comment)
                ),
            }
        )

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        code, comment = split_go_mod_comment(raw_line)
        stripped = code.strip()
        if "/*" in stripped or "*/" in stripped:
            issues.append(f"unsupported-block-comment:{line_number}")
            continue
        if not stripped:
            continue

        if block is not None:
            if stripped == ")":
                block = None
            elif block == "require":
                add_requirement(stripped, comment, line_number)
            continue

        block_match = re.fullmatch(r"(require|replace|exclude)\s*\(", stripped)
        if block_match:
            block = block_match.group(1)
            has_replace = has_replace or block == "replace"
            has_exclude = has_exclude or block == "exclude"
            continue

        directive_match = re.match(r"^(require|replace|exclude)(?:\s+|$)", stripped)
        if directive_match is None:
            continue
        directive = directive_match.group(1)
        payload = stripped[directive_match.end() :].strip()
        if directive == "require":
            add_requirement(payload, comment, line_number)
        elif directive == "replace":
            has_replace = True
        else:
            has_exclude = True

    if block is not None:
        issues.append(f"unterminated-{block}-block")
    return {
        "requirements": requirements,
        "issues": issues,
        "has_replace": has_replace,
        "has_exclude": has_exclude,
    }


def is_otel_module(module: str) -> bool:
    return module.startswith("go.opentelemetry.io/")


def parse_go_version(value: str) -> tuple[int, int, int, int] | None:
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?", value)
    if not match:
        return None
    numeric_parts = [part for part in match.groups() if part is not None]
    if any(len(part) > 1 and part.startswith("0") for part in numeric_parts):
        return None
    try:
        major = int(match.group(1))
        minor = int(match.group(2))
    except ValueError:
        return None
    patch_text = match.group(3)
    # Go 1.21 introduced a distinction between the language version (1.21)
    # and its first release (1.21.0): 1.21 < 1.21.0. Older 1.x versions treat
    # an omitted patch as .0. Go module compatibility follows this ordering.
    release_rank = 1
    if patch_text is None and minor >= 21:
        release_rank = 0
    try:
        patch = int(patch_text or 0)
    except ValueError:
        return None
    return (
        major,
        minor,
        release_rank,
        patch,
    )


def semver_key(version: str) -> tuple[Any, ...] | None:
    match = SEMVER.fullmatch(version)
    if not match:
        return None
    prerelease = match.group("prerelease")
    prerelease_key: tuple[tuple[int, int | str], ...] = ()
    release_rank = 1
    try:
        if prerelease is not None:
            release_rank = 0
            prerelease_parts = prerelease.split(".")
            if any(
                part.isdigit() and len(part) > 1 and part.startswith("0")
                for part in prerelease_parts
            ):
                return None
            prerelease_key = tuple(
                (0, int(part)) if part.isdigit() else (1, part)
                for part in prerelease_parts
            )
        return (
            int(match.group("major")),
            int(match.group("minor")),
            int(match.group("patch")),
            release_rank,
            prerelease_key,
            version,
        )
    except ValueError:
        return None


def read_go_mod(path: Path, warnings: Warnings, label: str) -> str | None:
    try:
        size = path.stat().st_size
    except OSError as error:
        warnings.add(f"could not stat {label}: {error}")
        return None
    if size > MAX_GO_MOD_BYTES:
        warnings.add(
            f"ignored oversized {label}: {size} bytes exceeds "
            f"{MAX_GO_MOD_BYTES}"
        )
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        warnings.add(f"could not read {label}: {error}")
        return None


def go_directive_details(text: str) -> tuple[str | None, str]:
    """Return the directive value and valid/absent/malformed/duplicate state."""

    directive_lines: list[str] = []
    for raw_line in text.splitlines():
        code, _ = split_go_mod_comment(raw_line)
        stripped = code.strip()
        if re.match(r"^go(?:\s|$)", stripped):
            directive_lines.append(stripped)
    if not directive_lines:
        return None, "absent"
    if len(directive_lines) != 1:
        return None, "duplicate"
    match = GO_DIRECTIVE_VALUE.fullmatch(directive_lines[0])
    if match is None:
        return None, "malformed"
    return match.group("version"), "valid"


def module_directive(text: str) -> str | None:
    matches = MODULE_DIRECTIVE.findall(text)
    return matches[0] if len(matches) == 1 else None


def core_requirement(text: str) -> str | None:
    matches = [
        item["version"]
        for item in parse_requirements(text)["requirements"]
        if item["module"] == "go.opentelemetry.io/otel"
    ]
    return matches[0] if len(matches) == 1 else None


def escape_cache_text(value: str) -> str:
    """Apply the uppercase escaping used by Go's module download cache."""

    return "".join(
        f"!{character.lower()}" if "A" <= character <= "Z" else character
        for character in value
    )


def downloaded_go_mod(cache: Path, module: str, version: str) -> Path:
    return download_artifact(cache, module, version, "mod")


def download_artifact(
    cache: Path, module: str, version: str, suffix: str
) -> Path:
    return (
        cache
        / "cache"
        / "download"
        / Path(*(escape_cache_text(part) for part in module.split("/")))
        / "@v"
        / f"{escape_cache_text(version)}.{suffix}"
    )


def proxy_artifacts(
    cache: Path, module: str, version: str
) -> tuple[dict[str, str], list[str]]:
    artifacts: dict[str, str] = {}
    missing: list[str] = []
    for suffix in PROXY_ARTIFACT_SUFFIXES:
        path = download_artifact(cache, module, version, suffix)
        try:
            present = path.is_file() and path.stat().st_size > 0
        except OSError:
            present = False
        if present:
            artifacts[suffix] = str(path)
        else:
            missing.append(suffix)
    return artifacts, missing


def discover_otelhttp_sources(
    cache: Path, warnings: Warnings
) -> tuple[dict[str, list[tuple[Path, str]]], bool]:
    sources: dict[str, list[tuple[Path, str]]] = {}
    scan_failed = False

    parts = OTELHTTP_MODULE.split("/")
    extracted_parent = cache.joinpath(*parts[:-1])
    extracted_prefix = f"{parts[-1]}@"
    if extracted_parent.is_dir():
        try:
            entries = sorted(extracted_parent.iterdir(), key=lambda path: path.name)
        except OSError as error:
            warnings.add(f"could not scan cached otelhttp modules: {error}")
            scan_failed = True
        else:
            for entry in entries:
                if not entry.name.startswith(extracted_prefix):
                    continue
                version = entry.name[len(extracted_prefix) :]
                go_mod = entry / "go.mod"
                if go_mod.is_file():
                    sources.setdefault(version, []).append((go_mod, "extracted"))

    download_dir = (
        cache
        / "cache"
        / "download"
        / Path(*parts)
        / "@v"
    )
    if download_dir.is_dir():
        try:
            entries = sorted(download_dir.iterdir(), key=lambda path: path.name)
        except OSError as error:
            warnings.add(f"could not scan downloaded otelhttp metadata: {error}")
            scan_failed = True
        else:
            for entry in entries:
                if not entry.name.endswith(".mod") or not entry.is_file():
                    continue
                version = entry.name[: -len(".mod")]
                existing = sources.setdefault(version, [])
                if not any(source == "download" for _, source in existing):
                    existing.append((entry, "download"))

    return sources, scan_failed


def default_gomodcache(explicit: Path | None) -> tuple[Path, str]:
    if explicit is not None:
        return explicit.expanduser().resolve(), "--gomodcache"
    configured = os.environ.get("GOMODCACHE")
    if configured:
        return Path(configured).expanduser().resolve(), "GOMODCACHE"
    go_path = os.environ.get("GOPATH")
    if go_path:
        first = next((item for item in go_path.split(os.pathsep) if item), "")
        if first:
            return (Path(first).expanduser() / "pkg" / "mod").resolve(), "GOPATH"
    return (Path.home() / "go" / "pkg" / "mod").resolve(), "default"


def project_go_mod(project: Path) -> tuple[Path, Path]:
    resolved = project.expanduser().resolve()
    if resolved.is_file():
        return resolved.parent, resolved
    return resolved, resolved / "go.mod"


def base_result(project: Path, go_mod: Path, cache: Path, source: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "incomplete",
        "complete": False,
        "candidate_only": True,
        "proof_boundary": (
            "Complete file-proxy artifacts and Go-version checks for the "
            "selected dependency closure make this an offline dependency "
            "candidate, not application proof. After an authorized dependency "
            "edit, verify the go.mod/go.sum diff and run project tests."
        ),
        "project": {
            "path": str(project),
            "go_mod": str(go_mod),
            "module": None,
            "go_version": None,
            "go_directive_status": None,
            "existing_otel_requirements": [],
            "requirement_parse_issues": [],
        },
        "gomodcache": {
            "path": str(cache),
            "source": source,
        },
        "scan": {
            "otelhttp_versions_seen": 0,
            "usable_versions": 0,
            "compatible_versions": 0,
            "newer_go_versions": 0,
            "unusable_versions": 0,
            "candidates_checked": 0,
            "non_runnable_versions": 0,
            "metadata_only_versions": 0,
            "closure_modules": 0,
            "closure_steps": 0,
        },
        "selection": None,
        "bootstrap_probe": {
            "eligible": False,
            "candidate": None,
            "modules": [],
            "reasons": [],
        },
        "verification": [],
        "candidate_rejections": [],
        "candidate_rejections_omitted": 0,
        "go_get": {
            "ready": False,
            "cwd": str(project),
            "env": {},
            "modules": [],
            "argv": [],
        },
        "go_commands": {
            "ready": False,
            "cwd": str(project),
            "env": {},
            "reuse_env_for": [],
            "cleanup_argv": [],
            "owned_cache_paths": [],
            "cleanup_allowed_files": [],
        },
        "reasons": [],
        "warnings": [],
        "warnings_omitted": 0,
    }


def finish(result: dict[str, Any], warnings: Warnings) -> dict[str, Any]:
    result["warnings"] = warnings.items
    result["warnings_omitted"] = warnings.omitted
    return result


def verify_proxy_module(
    cache: Path,
    module: str,
    version: str,
    project_version_key: tuple[int, int, int, int],
    warnings: Warnings,
    *,
    expected_core_version: str | None = None,
) -> dict[str, Any]:
    artifacts, missing_artifacts = proxy_artifacts(cache, module, version)
    issues: list[str] = []
    if missing_artifacts:
        issues.append("missing-file-proxy-artifacts")

    item: dict[str, Any] = {
        "module": module,
        "version": version,
        "source": "download",
        "status": "not-ready",
        "issues": issues,
        "file_proxy_complete": not missing_artifacts,
        "artifacts": artifacts,
        "missing_artifacts": missing_artifacts,
        "go_version": None,
        "go_directive_status": None,
        "compatible": None,
        "requirements": [],
        "requirement_parse_issues": [],
    }
    mod_path = downloaded_go_mod(cache, module, version)
    if "mod" not in artifacts:
        return item

    text = read_go_mod(mod_path, warnings, f"{module}@{version} proxy go.mod")
    if text is None:
        issues.append("go-mod-unreadable")
        return item
    if module_directive(text) != module:
        issues.append("module-directive-missing-or-mismatched")

    parsed = parse_requirements(text)
    item["requirements"] = parsed["requirements"]
    item["requirement_parse_issues"] = parsed["issues"]
    if parsed["issues"]:
        issues.append("requirements-unparseable")

    module_go, module_go_status = go_directive_details(text)
    module_go_key = parse_go_version(module_go) if module_go is not None else None
    if module_go_status == "valid" and module_go_key is None:
        module_go_status = "malformed"
    item["go_version"] = module_go
    item["go_directive_status"] = module_go_status
    if module_go_status == "absent":
        item["compatible"] = True
    elif module_go_status != "valid":
        issues.append(f"go-directive-{module_go_status}")
    elif module_go_key > project_version_key:
        item["compatible"] = False
        issues.append("requires-newer-go")
    else:
        item["compatible"] = True

    if expected_core_version is not None:
        core_versions = [
            requirement["version"]
            for requirement in parsed["requirements"]
            if requirement["module"] == "go.opentelemetry.io/otel"
        ]
        proxy_core_version = (
            core_versions[0] if len(core_versions) == 1 else None
        )
        item["core_version"] = proxy_core_version
        if proxy_core_version != expected_core_version:
            issues.append("core-requirement-missing-or-mismatched")

    if not issues:
        item["status"] = "ready"
    return item


def verify_dependency_closure(
    cache: Path,
    candidate: dict[str, Any],
    project_requirements: list[dict[str, Any]],
    project_module: str,
    project_version_key: tuple[int, int, int, int],
    warnings: Warnings,
) -> tuple[list[dict[str, Any]], list[str], int]:
    """Verify a bounded, conservative MVS-style dependency closure."""

    proposed = {
        **{
            module: candidate["core_version"]
            for module in COMPANION_MODULES
        },
        OTELHTTP_MODULE: candidate["version"],
    }
    selected: dict[str, str] = {}
    selected_keys: dict[str, tuple[Any, ...]] = {}
    pending: set[str] = set()
    verification: dict[str, dict[str, Any]] = {}
    closure_issues: list[str] = []
    steps = 0

    def add_requirement(module: str, version: str) -> None:
        if module == project_module:
            issue = f"dependency-requires-main-module:{module}"
            if issue not in closure_issues:
                closure_issues.append(issue)
            return
        version_key = semver_key(version)
        if version_key is None:
            issue = f"unsupported-module-version:{module}@{version}"
            if issue not in closure_issues:
                closure_issues.append(issue)
            return
        current_key = selected_keys.get(module)
        if current_key is not None and version_key <= current_key:
            return
        if module not in selected and len(selected) >= MAX_CLOSURE_MODULES:
            issue = f"dependency-closure-module-limit:{MAX_CLOSURE_MODULES}"
            if issue not in closure_issues:
                closure_issues.append(issue)
            return
        selected[module] = version
        selected_keys[module] = version_key
        pending.add(module)

    for requirement in project_requirements:
        add_requirement(requirement["module"], requirement["version"])
    for module, version in proposed.items():
        add_requirement(module, version)

    while pending and not closure_issues:
        module = min(pending)
        pending.remove(module)
        steps += 1
        if steps > MAX_CLOSURE_STEPS:
            closure_issues.append(
                f"dependency-closure-step-limit:{MAX_CLOSURE_STEPS}"
            )
            break
        version = selected[module]
        item = verify_proxy_module(
            cache,
            module,
            version,
            project_version_key,
            warnings,
            expected_core_version=(
                candidate["core_version"]
                if module == OTELHTTP_MODULE
                and version == candidate["version"]
                else None
            ),
        )
        verification[module] = item
        if item["status"] != "ready":
            continue
        for requirement in item["requirements"]:
            add_requirement(requirement["module"], requirement["version"])

    for module, expected_version in proposed.items():
        selected_version = selected.get(module)
        if selected_version == expected_version:
            continue
        item = verification.get(module)
        if item is not None:
            item["issues"].append("proposed-version-not-selected")
            item["status"] = "not-ready"
            item["proposed_version"] = expected_version
        issue = (
            f"proposed-version-not-selected:{module}@{expected_version}"
            f":selected={selected_version}"
        )
        closure_issues.append(issue)

    ordered = [verification[module] for module in sorted(verification)]
    return ordered, closure_issues, steps


def execution_env(project: Path, cache: Path) -> dict[str, str]:
    local_cache = project / ".observe" / "tmp" / "go-otel-resolver"
    proxy = (cache / "cache" / "download").resolve().as_uri()
    return {
        "GOCACHE": str(local_cache / "gocache"),
        "GOENV": "off",
        "GOFLAGS": "",
        "GOMODCACHE": str(local_cache / "gomodcache"),
        "GONOPROXY": "none",
        "GONOSUMDB": "none",
        "GOPATH": str(local_cache / "gopath"),
        "GOPRIVATE": "",
        "GOPROXY": proxy,
        "GOSUMDB": "off",
        "GOTOOLCHAIN": "local",
        "GOVCS": "*:off",
        "GOWORK": "off",
        "HOME": str(local_cache / "home"),
    }


def candidate_modules(candidate: dict[str, Any]) -> list[str]:
    """Return the exact direct dependency bundle for a candidate."""

    core_version = candidate["core_version"]
    return [
        *(f"{module}@{core_version}" for module in COMPANION_MODULES),
        f"{OTELHTTP_MODULE}@{candidate['version']}",
    ]


def verify_direct_bundle(
    cache: Path,
    candidate: dict[str, Any],
    project_version_key: tuple[int, int, int, int],
    warnings: Warnings,
) -> list[dict[str, Any]]:
    """Verify only the fixed direct imports used by the bootstrap probe.

    This deliberately does not claim that the dependency closure is complete.
    A staged ``go mod tidy`` is the executable proof for that narrower claim.
    """

    direct = {
        **{
            module: candidate["core_version"]
            for module in COMPANION_MODULES
        },
        OTELHTTP_MODULE: candidate["version"],
    }
    return [
        verify_proxy_module(
            cache,
            module,
            version,
            project_version_key,
            warnings,
            expected_core_version=(
                candidate["core_version"]
                if module == OTELHTTP_MODULE
                else None
            ),
        )
        for module, version in sorted(direct.items())
    ]


def resolve(project_arg: Path, gomodcache_arg: Path | None) -> dict[str, Any]:
    warnings = Warnings()
    project, go_mod_path = project_go_mod(project_arg)
    cache, cache_source = default_gomodcache(gomodcache_arg)
    result = base_result(project, go_mod_path, cache, cache_source)

    if not go_mod_path.is_file():
        result["reasons"] = ["project-go-mod-missing"]
        warnings.add(f"project go.mod is missing: {go_mod_path}")
        return finish(result, warnings)

    project_text = read_go_mod(go_mod_path, warnings, "project go.mod")
    if project_text is None:
        result["reasons"] = ["project-go-mod-unreadable"]
        return finish(result, warnings)
    project_module = module_directive(project_text)
    if project_module is None:
        result["reasons"] = ["project-module-directive-missing-or-invalid"]
        warnings.add("project go.mod has no single valid module directive")
        return finish(result, warnings)
    result["project"]["module"] = project_module
    project_version, project_go_status = go_directive_details(project_text)
    project_version_key = (
        parse_go_version(project_version) if project_version is not None else None
    )
    if project_go_status != "valid" or project_version_key is None:
        result["reasons"] = ["project-go-directive-missing-or-invalid"]
        warnings.add(
            "project go.mod has no single valid go directive: "
            f"{project_go_status}"
        )
        return finish(result, warnings)
    result["project"]["go_version"] = project_version
    result["project"]["go_directive_status"] = project_go_status

    project_metadata = parse_requirements(project_text)
    result["project"]["requirement_parse_issues"] = project_metadata["issues"]
    if project_metadata["issues"]:
        result["reasons"] = ["project-requirements-unparseable"]
        return finish(result, warnings)
    project_requirements = project_metadata["requirements"]
    existing_otel_requirements = sorted(
        (
            {
                "module": requirement["module"],
                "version": requirement["version"],
                "indirect": requirement["indirect"],
            }
            for requirement in project_requirements
            if is_otel_module(requirement["module"])
        ),
        key=lambda item: (item["module"], item["version"], item["indirect"]),
    )
    result["project"]["existing_otel_requirements"] = existing_otel_requirements
    project_reasons: list[str] = []
    if existing_otel_requirements:
        project_reasons.append("existing-otel-dependencies")
    if project_metadata["has_replace"]:
        project_reasons.append("project-replace-directive-unsupported")
    if project_metadata["has_exclude"]:
        project_reasons.append("project-exclude-directive-unsupported")
    invalid_project_requirements = [
        requirement
        for requirement in project_requirements
        if semver_key(requirement["version"]) is None
    ]
    if invalid_project_requirements:
        project_reasons.append("project-requirement-version-unsupported")
    if project_reasons:
        result["reasons"] = project_reasons
        return finish(result, warnings)

    if not cache.is_dir():
        result["reasons"] = ["gomodcache-missing"]
        warnings.add(f"Go module cache is not a directory: {cache}")
        return finish(result, warnings)

    sources, scan_failed = discover_otelhttp_sources(cache, warnings)
    result["scan"]["otelhttp_versions_seen"] = len(sources)

    compatible: list[dict[str, Any]] = []
    for version, version_sources in sources.items():
        version_key = semver_key(version)
        if version_key is None:
            result["scan"]["unusable_versions"] += 1
            warnings.add(f"ignored cached otelhttp version with invalid semver: {version}")
            continue

        parsed: dict[str, Any] | None = None
        for path, source in version_sources:
            text = read_go_mod(
                path,
                warnings,
                f"{OTELHTTP_MODULE}@{version} go.mod",
            )
            if text is None:
                continue
            module_go, module_go_status = go_directive_details(text)
            module_go_key = (
                parse_go_version(module_go) if module_go is not None else None
            )
            if module_go_status == "valid" and module_go_key is None:
                module_go_status = "malformed"
            if module_go_status == "absent":
                module_go_key = (0, 0, 0, 0)
            core_version = core_requirement(text)
            if (
                module_directive(text) != OTELHTTP_MODULE
                or module_go_status not in {"valid", "absent"}
                or module_go_key is None
                or core_version is None
            ):
                continue
            if semver_key(core_version) is None:
                continue
            parsed = {
                "module": OTELHTTP_MODULE,
                "version": version,
                "go_version": module_go,
                "go_directive_status": module_go_status,
                "core_version": core_version,
                "go_mod": str(path),
                "source": source,
                "semver_key": version_key,
                "go_version_key": module_go_key,
            }
            break

        if parsed is None:
            result["scan"]["unusable_versions"] += 1
            warnings.add(
                f"ignored {OTELHTTP_MODULE}@{version}: go directive is "
                "malformed or duplicated, or the module directive or "
                "go.opentelemetry.io/otel requirement is missing or invalid"
            )
            continue

        result["scan"]["usable_versions"] += 1
        if parsed["go_version_key"] <= project_version_key:
            compatible.append(parsed)
        else:
            result["scan"]["newer_go_versions"] += 1

    result["scan"]["compatible_versions"] = len(compatible)
    if not compatible:
        result["status"] = "incomplete" if scan_failed else "no-candidate"
        result["reasons"] = (
            ["otelhttp-cache-scan-failed"]
            if scan_failed
            else ["no-compatible-cached-otelhttp"]
        )
        return finish(result, warnings)

    selected: dict[str, Any] | None = None
    bootstrap_candidate: dict[str, Any] | None = None
    selected_verification: list[dict[str, Any]] = []
    selected_closure_steps = 0
    for candidate in sorted(
        compatible,
        key=lambda item: item["semver_key"],
        reverse=True,
    ):
        if bootstrap_candidate is None:
            direct_verification = verify_direct_bundle(
                cache,
                candidate,
                project_version_key,
                warnings,
            )
            if all(
                item["status"] == "ready" for item in direct_verification
            ):
                bootstrap_candidate = candidate
        result["scan"]["candidates_checked"] += 1
        verification, closure_issues, closure_steps = verify_dependency_closure(
            cache,
            candidate,
            project_requirements,
            project_module,
            project_version_key,
            warnings,
        )
        not_ready = [
            item for item in verification if item["status"] != "ready"
        ]
        if not not_ready and not closure_issues:
            selected = candidate
            selected_verification = verification
            selected_closure_steps = closure_steps
            break

        result["scan"]["non_runnable_versions"] += 1
        if any(
            item["artifacts"] and item["missing_artifacts"]
            for item in not_ready
        ):
            result["scan"]["metadata_only_versions"] += 1
        rejection = {
            "version": candidate["version"],
            "core_version": candidate["core_version"],
            "closure_issues": closure_issues,
            "not_ready_modules": [
                {
                    "module": item["module"],
                    "issues": item["issues"],
                    "missing_artifacts": item["missing_artifacts"],
                }
                for item in not_ready
            ],
        }
        if len(result["candidate_rejections"]) < MAX_CANDIDATE_REJECTIONS:
            result["candidate_rejections"].append(rejection)
        else:
            result["candidate_rejections_omitted"] += 1

    if selected is None:
        result["status"] = "incomplete"
        result["reasons"] = ["no-runnable-cached-bundle"]
        if scan_failed:
            result["reasons"].append("otelhttp-cache-scan-failed")
        if bootstrap_candidate is not None and not scan_failed:
            result["bootstrap_probe"] = {
                "eligible": True,
                "candidate": {
                    key: bootstrap_candidate[key]
                    for key in (
                        "module",
                        "version",
                        "go_version",
                        "go_directive_status",
                        "core_version",
                        "go_mod",
                        "source",
                    )
                },
                "modules": candidate_modules(bootstrap_candidate),
                "reasons": [
                    "full-project-closure-not-proven",
                    "direct-bundle-file-proxy-ready",
                ],
            }
        else:
            result["bootstrap_probe"]["reasons"] = [
                "no-file-proxy-ready-direct-bundle"
            ]
        return finish(result, warnings)

    result["selection"] = {
        key: selected[key]
        for key in (
            "module",
            "version",
            "go_version",
            "go_directive_status",
            "core_version",
            "go_mod",
            "source",
        )
    }
    result["verification"] = selected_verification
    result["scan"]["closure_modules"] = len(selected_verification)
    result["scan"]["closure_steps"] = selected_closure_steps
    modules = candidate_modules(selected)
    ready = not scan_failed
    if ready:
        env = execution_env(project, cache)
        result["go_get"] = {
            "ready": True,
            "cwd": str(project),
            "env": env,
            "modules": modules,
            "argv": ["go", "get", *modules],
        }
        result["go_commands"] = {
            "ready": True,
            "cwd": str(project),
            "env": env,
            "reuse_env_for": [
                "go mod tidy",
                "go build",
                "go test",
                "go run",
                "go clean",
            ],
            "cleanup_argv": ["go", "clean", "-cache", "-modcache"],
            "owned_cache_paths": [env["GOCACHE"], env["GOMODCACHE"]],
            "cleanup_allowed_files": [
                str(Path(env["GOCACHE"]) / "README"),
                str(Path(env["GOCACHE"]) / "trim.txt"),
            ],
        }
    result["complete"] = ready
    result["status"] = "complete" if ready else "incomplete"
    result["bootstrap_probe"]["reasons"] = ["full-plan-available"]
    reasons: set[str] = set()
    if scan_failed:
        reasons.add("otelhttp-cache-scan-failed")
    result["reasons"] = sorted(reasons)
    return finish(result, warnings)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve cache-backed OpenTelemetry Go dependency pins without "
            "executing Go or a shell."
        )
    )
    parser.add_argument(
        "--project",
        required=True,
        type=Path,
        help="Project directory or project go.mod path.",
    )
    parser.add_argument(
        "--gomodcache",
        type=Path,
        help=(
            "Go module cache path. Defaults to GOMODCACHE, GOPATH/pkg/mod, "
            "or ~/go/pkg/mod without invoking `go env`."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(
        json.dumps(
            resolve(args.project, args.gomodcache),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
