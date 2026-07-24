#!/usr/bin/env python3
"""Resolve and execute allowlisted Go OTel commands without a shell."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from types import ModuleType
from typing import Any, NamedTuple
from urllib.parse import unquote, urlparse


RUNNER = Path(__file__).resolve()
RESOLVER = RUNNER.with_name("resolve_go_otel_versions.py")
ALLOWED_GO_SUBCOMMANDS = {"build", "list", "run", "test"}
BOOTSTRAP_FOLLOWUP_SUBCOMMANDS = {"build", "list", "run", "test"}
FORBIDDEN_EXTERNAL_TOOL_FLAGS = {"exec", "toolexec", "vettool"}
FORBIDDEN_BOOTSTRAP_FLAGS = {"mod", "modfile", "overlay"}
LEDGER_SCHEMA_VERSION = 5
LEDGER_KIND = "go-otel-bootstrap-accepted-plan"
OWNED_DIRECTORY = Path(".observe") / "tmp" / "go-otel-resolver"
PERSISTED_PLAN = Path(".observe") / "tmp" / "go-otel-version-plan.json"
STAGE_DIRECTORY = "bootstrap-stage"
LEDGER_NAME = "accepted-plan.json"
RETIRED_DIRECTORY_PREFIX = f".{OWNED_DIRECTORY.name}.retired."
VALIDATION_EVIDENCE = Path(".observe") / "evidence" / "go-otel-validation.json"
VALIDATION_BUILD_OUTPUT_DIRECTORY = "build-output"
VALIDATION_BUILD_OUTPUT_BINDING = "$INVOCATION/build-output"
MAX_PROJECT_FILE_BYTES = 8_000_000
MAX_GO_EXECUTABLE_BYTES = 512_000_000
MAX_PROJECT_INPUT_FILES = 50_000
MAX_PROJECT_INPUT_BYTES = 512_000_000
MAX_STAGED_PROXY_BYTES = 1_073_741_824
MAX_STAGED_PROXY_FILES = 1_024
MAX_VALIDATION_ARGS = 32
MAX_VALIDATION_ARG_BYTES = 1_024
MAX_BLOCKER_DETAIL = 240
MAX_DIAGNOSTIC_CAPTURE_BYTES = 8_192
MAX_DIAGNOSTIC_EXCERPT_CHARS = 320
VALIDATION_EVIDENCE_SCHEMA_VERSION = 4
SOURCE_DIGEST_ALGORITHM = "go-project-input-tree-v2"
SOURCE_EXCLUDED_DIRECTORIES = {
    ".git",
    ".observe",
    "gocache",
    "gomodcache",
    "node_modules",
}
PROBE_PROOF_BOUNDARY = (
    "The staged tidy proves only import-reachable dependency resolution for "
    "the fixed bootstrap imports. It does not prove application "
    "instrumentation, compilation, tests, export, or runtime telemetry."
)
FULL_PLAN_PROOF_BOUNDARY = (
    "The resolver proved a compatible file-proxy dependency closure. It does "
    "not prove application instrumentation, compilation, tests, export, or "
    "runtime telemetry."
)
PROBE_IMPORTS = (
    "go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp",
    "go.opentelemetry.io/otel",
    "go.opentelemetry.io/otel/sdk/metric",
    "go.opentelemetry.io/otel/sdk/trace",
    "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp",
    "go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp",
)
GO_ENV_TO_SCRUB = {
    "AR",
    "CC",
    "CC_FOR_TARGET",
    "CGO_CFLAGS",
    "CGO_CFLAGS_ALLOW",
    "CGO_CFLAGS_DISALLOW",
    "CGO_CPPFLAGS",
    "CGO_CPPFLAGS_ALLOW",
    "CGO_CPPFLAGS_DISALLOW",
    "CGO_CXXFLAGS",
    "CGO_CXXFLAGS_ALLOW",
    "CGO_CXXFLAGS_DISALLOW",
    "CGO_ENABLED",
    "CGO_FFLAGS",
    "CGO_FFLAGS_ALLOW",
    "CGO_FFLAGS_DISALLOW",
    "CGO_LDFLAGS",
    "CGO_LDFLAGS_ALLOW",
    "CGO_LDFLAGS_DISALLOW",
    "CXX",
    "CXX_FOR_TARGET",
    "GO111MODULE",
    "GO386",
    "GOAMD64",
    "GOARCH",
    "GOARM",
    "GOARM64",
    "GOBIN",
    "GOCACHE",
    "GOENV",
    "GOEXE",
    "GOEXPERIMENT",
    "GOFLAGS",
    "GOHOSTARCH",
    "GOHOSTOS",
    "GOMIPS",
    "GOMIPS64",
    "GOINSECURE",
    "GOMOD",
    "GOMODCACHE",
    "GONOPROXY",
    "GONOSUMDB",
    "GOOS",
    "GOPPC64",
    "GOPATH",
    "GOPRIVATE",
    "GOPROXY",
    "GOROOT",
    "GORISCV64",
    "GOSUMDB",
    "GOTELEMETRY",
    "GOTELEMETRYDIR",
    "GOTMPDIR",
    "GOTOOLCHAIN",
    "GOTOOLDIR",
    "GOVCS",
    "GOVERSION",
    "GOWASM",
    "GOWORK",
    "PKG_CONFIG",
}

MATERIAL_GO_ENV_KEYS = tuple(sorted(GO_ENV_TO_SCRUB))

ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
DIAGNOSTIC_LOCATION = re.compile(
    r"^(?P<path>.+?\.go):(?P<line>[1-9][0-9]{0,8})"
    r"(?::(?P<column>[1-9][0-9]{0,8}))?:\s*(?P<message>.+)$"
)
FAILED_TEST = re.compile(r"^--- FAIL: (?P<name>[A-Za-z0-9_./-]+)(?:\s|$)")
SENSITIVE_DIAGNOSTIC = re.compile(
    r"(?i)(?:authorization|credential|headers?|password|passwd|secret|token|"
    r"api[_-]?key|client[_-]?secret)"
)
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(?P<prefix>\b(?:authorization|credential|headers?|password|passwd|"
    r"secret|token|api[_-]?key|client[_-]?secret)\b\s*[:=]\s*)"
    r"(?P<value>[^,\s}\]]+)"
)
URL_USERINFO = re.compile(r"(?i)(?P<scheme>https?://)[^/@\s]+@")
BEARER_VALUE = re.compile(r"(?i)(?P<prefix>\bbearer\s+)[^,\s}\]]+")
OPAQUE_VALUE = re.compile(r"\b(?=[A-Za-z0-9_.:/+=@-]{20,}\b)(?=[^\s]*[-_./+=@])[^\s,}\]]+")


class CommandError(ValueError):
    pass


class LedgerSnapshot(NamedTuple):
    payload: bytes
    value: dict[str, Any]
    sha256: str
    identity: tuple[int, int]
    mode: int


def status_is_link_or_reparse(status: os.stat_result) -> bool:
    reparse_mask = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(status, "st_file_attributes", 0)
    return stat.S_ISLNK(status.st_mode) or bool(attributes & reparse_mask)


def path_is_link_or_reparse(path: Path) -> bool:
    try:
        status = os.lstat(path)
    except OSError:
        return False
    return status_is_link_or_reparse(status)


def _detect_descriptor_cleanup_support() -> bool:
    required_dir_fd = {os.open, os.mkdir, os.rename, os.stat}
    return (
        os.name == "posix"
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and required_dir_fd.issubset(os.supports_dir_fd)
        and os.stat in os.supports_follow_symlinks
    )


_DESCRIPTOR_CLEANUP_SUPPORTED = _detect_descriptor_cleanup_support()


def _detect_descriptor_publication_support() -> bool:
    required_dir_fd = {os.open, os.rename, os.stat, os.unlink}
    return (
        os.name == "posix"
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and required_dir_fd.issubset(os.supports_dir_fd)
        and os.stat in os.supports_follow_symlinks
    )


_DESCRIPTOR_PUBLICATION_SUPPORTED = _detect_descriptor_publication_support()


def descriptor_cleanup_supported() -> bool:
    return _DESCRIPTOR_CLEANUP_SUPPORTED


def descriptor_publication_supported() -> bool:
    return _DESCRIPTOR_PUBLICATION_SUPPORTED


def descriptor_mode_supported() -> bool:
    return hasattr(os, "fchmod")


def load_resolver() -> ModuleType:
    if RESOLVER.is_symlink():
        raise CommandError(f"resolver must be a trusted regular sibling: {RESOLVER}")
    spec = importlib.util.spec_from_file_location("otel_go_resolver", RESOLVER)
    if spec is None or spec.loader is None:
        raise CommandError(f"could not load resolver: {RESOLVER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require_dict(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CommandError(f"resolver {name} must be an object")
    return value


def require_argv(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item and "\x00" not in item for item in value
    ):
        raise CommandError(f"resolver {name} must be a non-empty string list")
    return list(value)


def ensure_no_symlink_components(project: Path, target: Path, label: str) -> None:
    try:
        relative = target.relative_to(project)
    except ValueError as error:
        raise CommandError(f"{label} escapes the project") from error
    current = project
    for part in relative.parts:
        current = current / part
        if path_is_link_or_reparse(current):
            raise CommandError(
                f"{label} contains symlink component or reparse point: {current}"
            )


def ensure_no_symlink_ancestors(path: Path, label: str) -> None:
    """Reject a link/reparse point at every existing namespace component."""

    absolute = Path(os.path.abspath(path))
    parts = absolute.parts
    if not parts:
        raise CommandError(f"{label} path is empty")
    current = Path(parts[0])
    for part in parts[1:]:
        current = current / part
        try:
            status = os.lstat(current)
        except FileNotFoundError:
            break
        except OSError as error:
            raise CommandError(f"could not inspect {label} ancestor: {error}") from error
        if status_is_link_or_reparse(status):
            raise CommandError(
                f"{label} contains symlink ancestor or reparse point: {current}"
            )


def validate_check_bound_paths(
    plan: dict[str, object], resolver: ModuleType
) -> None:
    """Fail closed on links in every path consumed by check-validation."""

    project = plan.get("project")
    cache = plan.get("cache")
    runtime = plan.get("runtime")
    artifacts = plan.get("proxy_artifacts")
    if (
        not isinstance(project, Path)
        or not isinstance(cache, Path)
        or not isinstance(runtime, dict)
        or not isinstance(artifacts, list)
    ):
        raise CommandError("check-validation bound path state is invalid")
    paths: list[tuple[Path, str]] = [
        (project, "project root"),
        (project / "go.mod", "project go.mod"),
        (project / PERSISTED_PLAN, "persisted resolver plan"),
        (ledger_path(project), "accepted-plan ledger"),
        (project / VALIDATION_EVIDENCE, "Go validation evidence"),
        (cache, "source module cache"),
    ]
    if (project / "go.sum").exists() or (project / "go.sum").is_symlink():
        paths.append((project / "go.sum", "project go.sum"))
    runtime_path = runtime.get("path")
    if not isinstance(runtime_path, str):
        raise CommandError("check-validation runtime path is invalid")
    paths.append((Path(runtime_path), "bound Go runtime"))
    environment = require_dict(plan.get("env"), "check-validation env")
    for key, value in environment.items():
        if not isinstance(value, str):
            raise CommandError("check-validation environment path is invalid")
        if key == "GOPROXY":
            parsed = urlparse(value)
            if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
                raise CommandError("check-validation GOPROXY path is invalid")
            paths.append((Path(unquote(parsed.path)), "bound GOPROXY"))
        elif key in {"GOCACHE", "GOMODCACHE", "GOPATH", "HOME"}:
            paths.append((Path(value), f"bound {key}"))
    for row in artifacts:
        bound = require_dict(row, "check-validation proxy row")
        module = bound.get("module")
        version = bound.get("version")
        if not isinstance(module, str) or not isinstance(version, str):
            raise CommandError("check-validation proxy identity is invalid")
        bound_artifacts = require_dict(
            bound.get("artifacts"), "check-validation proxy artifacts"
        )
        for suffix in resolver.PROXY_ARTIFACT_SUFFIXES:
            if suffix not in bound_artifacts:
                continue
            paths.append(
                (
                    resolver.download_artifact(cache, module, version, suffix),
                    f"bound proxy artifact {module}@{version}.{suffix}",
                )
            )
    for path, label in paths:
        ensure_no_symlink_ancestors(path, label)


def validate_project(result: dict[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    if type(result.get("schema_version")) is not int or result["schema_version"] != 2:
        raise CommandError("resolver returned an unsupported schema")
    if result.get("candidate_only") is not True:
        raise CommandError("resolver omitted the candidate-only proof boundary")
    project_info = require_dict(result.get("project"), "project")
    project_text = project_info.get("path")
    go_mod_text = project_info.get("go_mod")
    if not isinstance(project_text, str) or not isinstance(go_mod_text, str):
        raise CommandError("resolver project paths are invalid")
    project = Path(project_text)
    go_mod = Path(go_mod_text)
    if not project.is_absolute() or project.resolve() != project:
        raise CommandError("resolver project path is not canonical")
    if go_mod != project / "go.mod" or not go_mod.is_file():
        raise CommandError("resolver project go.mod is invalid")
    if go_mod.is_symlink():
        raise CommandError("project go.mod must not be a symlink")
    cache_info = require_dict(result.get("gomodcache"), "gomodcache")
    cache_text = cache_info.get("path")
    if not isinstance(cache_text, str):
        raise CommandError("resolver module cache path is invalid")
    cache = Path(cache_text)
    if not cache.is_absolute() or cache.resolve() != cache:
        raise CommandError("resolver module cache path is not canonical")
    owned = project / OWNED_DIRECTORY
    proxy = (cache / "cache" / "download").resolve()
    overlapping = (cache, proxy)
    if any(
        source == owned
        or source.is_relative_to(owned)
        or owned.is_relative_to(source)
        for source in overlapping
    ):
        raise CommandError(
            "source module cache or file proxy overlaps the runner-owned directory"
        )
    return project, cache, project_info


def runtime_platform(runtime: dict[str, Any]) -> tuple[str, str]:
    version = runtime.get("version")
    if not isinstance(version, str) or not version.startswith("go version "):
        raise CommandError("bound Go runtime version is invalid")
    platform = version.rsplit(" ", 1)[-1]
    if platform.count("/") != 1:
        raise CommandError("bound Go runtime platform is invalid")
    goos, goarch = platform.split("/", 1)
    if not goos or not goarch:
        raise CommandError("bound Go runtime platform is invalid")
    return goos, goarch


def validate_environment(
    project: Path,
    env: object,
    runtime: dict[str, Any] | None = None,
) -> dict[str, str]:
    environment = require_dict(env, "go_commands.env")
    if not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in environment.items()
    ):
        raise CommandError("resolver environment is invalid")
    local = project / OWNED_DIRECTORY
    expected_paths = {
        "GOCACHE": local / "gocache",
        "GOMODCACHE": local / "gomodcache",
        "GOPATH": local / "gopath",
        "HOME": local / "home",
    }
    for key, expected in expected_paths.items():
        if environment.get(key) != str(expected):
            raise CommandError(f"resolver {key} is outside the owned directory")
        ensure_no_symlink_components(project, expected, key)
    if environment.get("GOTOOLCHAIN") != "local":
        raise CommandError("resolver must disable toolchain downloads")
    if environment.get("GOVCS") != "*:off":
        raise CommandError("resolver must disable VCS fallback")
    if environment.get("GOSUMDB") != "off":
        raise CommandError("resolver must disable checksum database access")
    if environment.get("GOTELEMETRY") != "off":
        raise CommandError("resolver must disable local Go telemetry state")
    if environment.get("CGO_ENABLED") != "0":
        raise CommandError("resolver must disable unbound CGO tool execution")
    if runtime is not None:
        goos, goarch = runtime_platform(runtime)
        if environment.get("GOOS") != goos or environment.get("GOARCH") != goarch:
            raise CommandError("resolver GOOS/GOARCH differ from the bound Go runtime")
    proxy = environment.get("GOPROXY", "")
    if not proxy.startswith("file://") or "," in proxy or "|" in proxy:
        raise CommandError("resolver must use one file-only Go proxy")
    return dict(environment)


def validate_proxy_bindings(
    resolver: ModuleType,
    cache: Path,
    value: object,
    *,
    required_modules: list[str],
    label: str,
    reverify_current: bool = False,
    allow_partial: bool = False,
) -> list[dict[str, object]]:
    """Validate every persisted selected proxy artifact against current bytes."""

    if not isinstance(value, list) or not value:
        raise CommandError(f"{label} proxy verification is unavailable")
    bindings: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    required = {tuple(pin.rsplit("@", 1)) for pin in required_modules}
    for index, raw in enumerate(value):
        row = require_dict(raw, f"{label}.verification[{index}]")
        module = row.get("module")
        version = row.get("version")
        if not isinstance(module, str) or not isinstance(version, str):
            raise CommandError(f"{label} proxy module identity is invalid")
        identity = (module, version)
        if identity in seen:
            raise CommandError(f"{label} proxy module identity is duplicated")
        seen.add(identity)
        missing = row.get("missing_artifacts")
        unsafe = row.get("unsafe_artifacts")
        artifacts = require_dict(row.get("artifacts"), f"{label}.artifacts")
        suffixes = set(resolver.PROXY_ARTIFACT_SUFFIXES)
        if allow_partial:
            if (
                not isinstance(missing, list)
                or missing
                != [suffix for suffix in resolver.PROXY_ARTIFACT_SUFFIXES if suffix not in artifacts]
                or unsafe != []
                or not set(artifacts).issubset(suffixes)
                or row.get("file_proxy_complete") != (not missing)
                or row.get("status") not in {"ready", "not-ready"}
            ):
                raise CommandError(f"{label} partial proxy binding is invalid")
            if identity in required and (
                row.get("status") != "ready"
                or row.get("file_proxy_complete") is not True
                or missing
            ):
                raise CommandError(
                    f"{label} selected direct proxy module is not fully bound"
                )
        elif (
            row.get("status") != "ready"
            or row.get("file_proxy_complete") is not True
            or missing != []
            or unsafe != []
            or set(artifacts) != suffixes
        ):
            raise CommandError(f"{label} proxy module is not fully bound")
        canonical: dict[str, object] = {}
        for suffix in resolver.PROXY_ARTIFACT_SUFFIXES:
            if suffix not in artifacts:
                continue
            expected_path = resolver.download_artifact(cache, module, version, suffix)
            expected = require_dict(
                artifacts.get(suffix), f"{label}.{module}@{version}.{suffix}"
            )
            if expected.get("path") != str(expected_path):
                raise CommandError(f"{label} proxy artifact path drift")
            size = expected.get("size_bytes")
            artifact_digest = expected.get("sha256")
            device = expected.get("device")
            inode = expected.get("inode")
            mode = expected.get("mode")
            if (
                set(expected)
                != {
                    "path",
                    "size_bytes",
                    "sha256",
                    "device",
                    "inode",
                    "mode",
                    "link_safe",
                    "regular",
                }
                or type(size) is not int
                or size <= 0
                or size > resolver.MAX_PROXY_ARTIFACT_BYTES
                or not isinstance(artifact_digest, str)
                or len(artifact_digest) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in artifact_digest
                )
                or type(device) is not int
                or device < 0
                or type(inode) is not int
                or inode < 0
                or type(mode) is not int
                or mode < 0
                or mode > 0o7777
                or expected.get("link_safe") is not True
                or expected.get("regular") is not True
            ):
                raise CommandError(f"{label} proxy artifact binding is invalid")
            if reverify_current:
                try:
                    current = resolver.proxy_artifact_fingerprint(
                        cache, expected_path, f"{module}@{version}.{suffix}"
                    )
                except (OSError, ValueError) as error:
                    raise CommandError(
                        f"{label} proxy artifact is unavailable: "
                        f"{module}@{version}.{suffix}: {error}"
                    ) from error
                if current != expected:
                    raise CommandError(
                        f"{label} proxy artifact fingerprint drift: "
                        f"{module}@{version}.{suffix}"
                    )
            canonical[suffix] = dict(expected)
        bindings.append(
            {
                "module": module,
                "version": version,
                "status": row.get("status"),
                "file_proxy_complete": row.get("file_proxy_complete"),
                "missing_artifacts": list(missing),
                "unsafe_artifacts": [],
                "artifacts": canonical,
            }
        )

    if not required.issubset(seen):
        raise CommandError(f"{label} proxy bindings omit a selected direct module")
    return bindings


def reverify_proxy_bindings(
    plan: dict[str, object], resolver: ModuleType
) -> None:
    cache = plan.get("cache")
    bindings = plan.get("proxy_artifacts")
    modules = plan.get("modules")
    if not isinstance(cache, Path) or not isinstance(modules, list):
        raise CommandError("proxy artifact validation state is invalid")
    validate_proxy_bindings(
        resolver,
        cache,
        bindings,
        required_modules=modules,
        label="selected",
        reverify_current=True,
        allow_partial=plan.get("allow_partial_proxy") is True,
    )


def cleanup_contract(
    project: Path,
    commands: dict[str, Any],
    env: dict[str, str],
    executable: str,
) -> dict[str, object]:
    cleanup_argv = require_argv(commands.get("cleanup_argv"), "cleanup_argv")
    if cleanup_argv != [executable, "clean", "-cache", "-modcache"]:
        raise CommandError("resolver cleanup argv is not bounded")
    owned = commands.get("owned_cache_paths")
    if owned != [env["GOCACHE"], env["GOMODCACHE"]]:
        raise CommandError("resolver owned cache paths are invalid")
    allowed = commands.get("cleanup_allowed_files")
    expected_allowed = [
        str(Path(env["GOCACHE"]) / "README"),
        str(Path(env["GOCACHE"]) / "trim.txt"),
    ]
    if allowed != expected_allowed:
        raise CommandError("resolver cleanup allowlist is invalid")
    return {
        "cleanup": cleanup_argv,
        "owned": list(owned),
        "allowed": list(allowed),
    }


def isolate_runtime_paths(
    plan: dict[str, object], runtime_root: Path
) -> dict[str, object]:
    """Move executable Go state out of the repository for this invocation."""

    environment = dict(require_dict(plan.get("env"), "runtime env"))
    environment.update(
        {
            "GOCACHE": str(runtime_root / "gocache"),
            "GOMODCACHE": str(runtime_root / "gomodcache"),
            "GOPATH": str(runtime_root / "gopath"),
            "HOME": str(runtime_root / "home"),
        }
    )
    isolated = {**plan, "env": environment, "runtime_root": runtime_root}
    if "owned" in isolated:
        isolated["owned"] = [environment["GOCACHE"], environment["GOMODCACHE"]]
        isolated["allowed"] = [
            str(Path(environment["GOCACHE"]) / "README"),
            str(Path(environment["GOCACHE"]) / "trim.txt"),
        ]
    return isolated


def proxy_content_digest(bindings: list[dict[str, object]]) -> str:
    """Bind proxy contents without invocation-specific paths or inode numbers."""

    content: list[dict[str, object]] = []
    for row in bindings:
        artifacts = require_dict(row.get("artifacts"), "proxy content artifacts")
        content.append(
            {
                "module": row.get("module"),
                "version": row.get("version"),
                "artifacts": {
                    suffix: {
                        "size_bytes": require_dict(
                            artifacts.get(suffix), f"proxy content {suffix}"
                        ).get("size_bytes"),
                        "sha256": require_dict(
                            artifacts.get(suffix), f"proxy content {suffix}"
                        ).get("sha256"),
                    }
                    for suffix in sorted(artifacts)
                },
            }
        )
    payload = json.dumps(content, separators=(",", ":"), sort_keys=True).encode()
    return digest(payload)


def copy_bound_proxy_artifact(
    resolver: ModuleType,
    source_cache: Path,
    source: Path,
    expected: dict[str, Any],
    destination: Path,
    label: str,
) -> None:
    """Copy one exact bound artifact without a source check/use window."""

    resolver.ensure_no_link_components(source_cache, source)
    before = os.lstat(source)
    if (
        status_is_link_or_reparse(before)
        or not stat.S_ISREG(before.st_mode)
        or expected.get("device") != before.st_dev
        or expected.get("inode") != before.st_ino
        or expected.get("mode") != stat.S_IMODE(before.st_mode)
        or expected.get("size_bytes") != before.st_size
    ):
        raise CommandError(f"{label} source identity drift before staging")
    source_descriptor = os.open(
        source,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0),
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination_descriptor: int | None = None
    try:
        opened = os.fstat(source_descriptor)
        if file_identity(opened) != file_identity(before):
            raise CommandError(f"{label} source identity drift while staging")
        destination_descriptor = os.open(
            destination,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_BINARY", 0),
            0o400,
        )
        hasher = hashlib.sha256()
        count = 0
        while True:
            chunk = os.read(source_descriptor, 1_048_576)
            if not chunk:
                break
            count += len(chunk)
            if count > resolver.MAX_PROXY_ARTIFACT_BYTES:
                raise CommandError(f"{label} exceeds the per-file staging bound")
            hasher.update(chunk)
            write_all(destination_descriptor, chunk)
        os.fsync(destination_descriptor)
        if descriptor_mode_supported():
            os.fchmod(destination_descriptor, 0o400)
        after = os.fstat(source_descriptor)
        named_after = os.lstat(source)
        if (
            file_identity(before) != file_identity(after)
            or file_identity(before) != file_identity(named_after)
            or (before.st_size, before.st_mtime_ns)
            != (after.st_size, after.st_mtime_ns)
            or (before.st_size, before.st_mtime_ns)
            != (named_after.st_size, named_after.st_mtime_ns)
            or count != expected.get("size_bytes")
            or hasher.hexdigest() != expected.get("sha256")
        ):
            raise CommandError(f"{label} source content drift while staging")
    finally:
        if destination_descriptor is not None:
            os.close(destination_descriptor)
        os.close(source_descriptor)


def stage_proxy_artifacts(
    plan: dict[str, object], resolver: ModuleType, runtime_root: Path
) -> dict[str, object]:
    """Create one bounded, read-only file proxy owned by this invocation."""

    source_cache = plan.get("cache")
    bindings = plan.get("proxy_artifacts")
    if not isinstance(source_cache, Path) or not isinstance(bindings, list):
        raise CommandError("proxy staging state is invalid")
    artifact_count = sum(
        len(require_dict(row.get("artifacts"), "proxy staging artifacts"))
        for row in bindings
    )
    if artifact_count > MAX_STAGED_PROXY_FILES:
        raise CommandError("selected proxy artifact count exceeds the staging bound")
    total_bytes = 0
    for row in bindings:
        artifacts = require_dict(row.get("artifacts"), "proxy staging artifacts")
        for suffix in resolver.PROXY_ARTIFACT_SUFFIXES:
            if suffix not in artifacts:
                continue
            size = require_dict(artifacts.get(suffix), f"proxy staging {suffix}").get(
                "size_bytes"
            )
            if type(size) is not int or size <= 0:
                raise CommandError("selected proxy artifact size binding is invalid")
            total_bytes += size
            if total_bytes > MAX_STAGED_PROXY_BYTES:
                raise CommandError("selected proxy artifacts exceed the staging byte bound")

    stage_cache = runtime_root / "staged-proxy-cache"
    stage_proxy = stage_cache / "cache" / "download"
    stage_proxy.mkdir(parents=True, exist_ok=False)
    staged_rows: list[dict[str, object]] = []
    for row in bindings:
        module = row.get("module")
        version = row.get("version")
        if not isinstance(module, str) or not isinstance(version, str):
            raise CommandError("selected proxy module binding is invalid")
        source_artifacts = require_dict(row.get("artifacts"), "proxy artifacts")
        for suffix in resolver.PROXY_ARTIFACT_SUFFIXES:
            if suffix not in source_artifacts:
                continue
            expected = require_dict(
                source_artifacts.get(suffix), f"{module}@{version}.{suffix}"
            )
            source = resolver.download_artifact(source_cache, module, version, suffix)
            destination = resolver.download_artifact(
                stage_cache, module, version, suffix
            )
            copy_bound_proxy_artifact(
                resolver,
                source_cache,
                source,
                expected,
                destination,
                f"{module}@{version}.{suffix}",
            )
        staged_rows.append(
            {
                "module": module,
                "version": version,
                "status": row.get("status"),
                "file_proxy_complete": row.get("file_proxy_complete"),
                "missing_artifacts": list(
                    row.get("missing_artifacts")
                    if isinstance(row.get("missing_artifacts"), list)
                    else []
                ),
                "unsafe_artifacts": [],
                "artifacts": {
                    suffix: resolver.proxy_artifact_fingerprint(
                        stage_cache,
                        resolver.download_artifact(
                            stage_cache, module, version, suffix
                        ),
                        f"staged {module}@{version}.{suffix}",
                    )
                    for suffix in resolver.PROXY_ARTIFACT_SUFFIXES
                    if suffix in source_artifacts
                },
            }
        )

    source_digest = proxy_content_digest(bindings)
    staged_digest = proxy_content_digest(staged_rows)
    if staged_digest != source_digest:
        raise CommandError("staged proxy content binding drift")
    for directory, subdirectories, files in os.walk(stage_cache, topdown=False):
        for name in files:
            os.chmod(Path(directory) / name, 0o400)
        for name in subdirectories:
            os.chmod(Path(directory) / name, 0o500)
    os.chmod(stage_cache, 0o500)

    environment = dict(require_dict(plan.get("env"), "staged proxy env"))
    environment["GOPROXY"] = stage_proxy.as_uri()
    return {
        **plan,
        "source_cache": source_cache,
        "source_proxy_artifacts": bindings,
        "cache": stage_cache,
        "proxy_artifacts": staged_rows,
        "proxy_bundle_sha256": staged_digest,
        "proxy_artifact_count": artifact_count,
        "proxy_total_bytes": total_bytes,
        "env": environment,
    }


def prepare_invocation(
    plan: dict[str, object], resolver: ModuleType, runtime_root: Path
) -> dict[str, object]:
    isolated = isolate_runtime_paths(plan, runtime_root)
    return stage_proxy_artifacts(isolated, resolver, runtime_root)


def validate_resolved_plan(
    result: object, resolver: ModuleType
) -> dict[str, object]:
    plan = require_dict(result, "plan")
    project, cache, _ = validate_project(plan)
    if plan.get("status") != "complete" or plan.get("complete") is not True:
        reasons = plan.get("reasons")
        raise CommandError(f"resolver did not produce a complete plan: {reasons}")
    go_get = require_dict(plan.get("go_get"), "go_get")
    commands = require_dict(plan.get("go_commands"), "go_commands")
    if go_get.get("ready") is not True or commands.get("ready") is not True:
        raise CommandError("resolver command plan is not ready")
    if go_get.get("cwd") != str(project) or commands.get("cwd") != str(project):
        raise CommandError("resolver command cwd does not match the project")
    persisted_runtime = require_dict(plan.get("go_runtime"), "go_runtime")
    env = validate_environment(project, commands.get("env"), persisted_runtime)
    runtime = runtime_fingerprint(
        plan, resolver, cwd=project, environment=env
    )
    executable = runtime["path"]
    if go_get.get("env") != env:
        raise CommandError("resolver environments differ")
    go_get_argv = require_argv(go_get.get("argv"), "go_get.argv")
    if go_get_argv[:2] != [executable, "get"]:
        raise CommandError("resolver go_get argv is invalid")
    candidate = candidate_identity(plan.get("selection"))
    modules = go_get_argv[2:]
    if modules != resolver.candidate_modules(candidate):
        raise CommandError("resolver go_get modules do not match the selection")
    proxy_artifacts = validate_proxy_bindings(
        resolver,
        cache,
        plan.get("verification"),
        required_modules=modules,
        label="complete plan",
    )
    graph_metadata = plan.get("graph_metadata")
    if not isinstance(graph_metadata, list):
        raise CommandError("complete plan graph metadata is invalid")
    canonical_graph_metadata: list[dict[str, object]] = []
    if graph_metadata:
        canonical_graph_metadata = validate_proxy_bindings(
            resolver,
            cache,
            graph_metadata,
            required_modules=[],
            label="complete plan graph metadata",
            allow_partial=True,
        )
        proxy_artifacts.extend(canonical_graph_metadata)
    contract = cleanup_contract(project, commands, env, executable)
    return {
        "source": "complete",
        "project": project,
        "cache": cache,
        "env": env,
        "go_get": go_get_argv,
        "selection": candidate,
        "candidate": candidate,
        "modules": modules,
        "runtime": runtime,
        "proxy_artifacts": proxy_artifacts,
        "graph_metadata_modules": [
            f"{row['module']}@{row['version']}" for row in canonical_graph_metadata
        ],
        **contract,
    }


def candidate_identity(candidate: object) -> dict[str, str | None]:
    item = require_dict(candidate, "bootstrap_probe.candidate")
    values: dict[str, str | None] = {}
    for key in ("module", "version", "core_version", "go_version"):
        value = item.get(key)
        if value is not None and not isinstance(value, str):
            raise CommandError(f"bootstrap candidate {key} is invalid")
        values[key] = value
    if not all(values[key] for key in ("module", "version", "core_version")):
        raise CommandError("bootstrap candidate is incomplete")
    if values["module"] != (
        "go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
    ):
        raise CommandError("bootstrap candidate module is invalid")
    return values


def validate_bootstrap_plan(
    result: object, resolver: ModuleType
) -> dict[str, object]:
    plan = require_dict(result, "plan")
    project, cache, project_info = validate_project(plan)
    if plan.get("complete") is True or plan.get("status") == "complete":
        raise CommandError("bootstrap probe is not allowed when a complete plan exists")
    existing = project_info.get("existing_otel_requirements")
    if not isinstance(existing, list) or existing:
        raise CommandError(
            "bootstrap probe requires a project with no OTel requirements"
        )
    probe = require_dict(plan.get("bootstrap_probe"), "bootstrap_probe")
    probe_verification = probe.get("verification")
    if (
        probe.get("eligible") is not True
        or probe.get("import_closure_complete") is not False
        or probe.get("candidate_closure_inspected") is not True
        or not isinstance(probe_verification, list)
        or probe.get("closure_modules") != len(probe_verification)
    ):
        raise CommandError(f"bootstrap probe is not eligible: {probe.get('reasons')}")
    candidate = candidate_identity(probe.get("candidate"))
    modules = require_argv(probe.get("modules"), "bootstrap_probe.modules")
    expected_modules = resolver.candidate_modules(candidate)
    if modules != expected_modules:
        raise CommandError("bootstrap direct bundle does not match the candidate")
    persisted_runtime = require_dict(plan.get("go_runtime"), "go_runtime")
    env = validate_environment(
        project,
        resolver.execution_env(project, cache, persisted_runtime),
        persisted_runtime,
    )
    runtime = runtime_fingerprint(
        plan, resolver, cwd=project, environment=env
    )
    proxy_artifacts = validate_proxy_bindings(
        resolver,
        cache,
        probe_verification,
        required_modules=modules,
        label="bootstrap plan",
        allow_partial=True,
    )
    graph_metadata = probe.get("graph_metadata")
    if not isinstance(graph_metadata, list):
        raise CommandError("bootstrap graph metadata is invalid")
    canonical_graph_metadata: list[dict[str, object]] = []
    if graph_metadata:
        canonical_graph_metadata = validate_proxy_bindings(
            resolver,
            cache,
            graph_metadata,
            required_modules=[],
            label="bootstrap graph metadata",
            allow_partial=True,
        )
        proxy_artifacts.extend(canonical_graph_metadata)
    artifact_count = sum(
        len(require_dict(row.get("artifacts"), "bootstrap artifacts"))
        for row in proxy_artifacts
    )
    artifact_bytes = sum(
        require_dict(artifact, "bootstrap artifact").get("size_bytes", 0)
        for row in proxy_artifacts
        for artifact in require_dict(row.get("artifacts"), "bootstrap artifacts").values()
    )
    if (
        artifact_count != probe.get("available_artifact_count")
        or artifact_bytes != probe.get("available_artifact_bytes")
        or artifact_count > MAX_STAGED_PROXY_FILES
        or artifact_bytes > MAX_STAGED_PROXY_BYTES
    ):
        raise CommandError("bootstrap available-artifact bounds drift")
    return {
        "source": "bootstrap",
        "project": project,
        "cache": cache,
        "env": env,
        "go_get": [runtime["path"], "get", *modules],
        "selection": candidate,
        "modules": modules,
        "candidate": candidate,
        "runtime": runtime,
        "proxy_artifacts": proxy_artifacts,
        "graph_metadata_modules": [
            f"{row['module']}@{row['version']}" for row in canonical_graph_metadata
        ],
        "allow_partial_proxy": True,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve and execute an allowlisted OTel Go dependency or validation "
            "command without shell interpolation."
        )
    )
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--gomodcache", type=Path)
    parser.add_argument(
        "--plan",
        required=True,
        type=Path,
        help=(
            "Exact persisted resolver plan at "
            "<project>/.observe/tmp/go-otel-version-plan.json."
        ),
    )
    parser.add_argument(
        "--plan-sha256",
        required=True,
        help="SHA-256 printed by the resolver for the persisted plan.",
    )
    parser.add_argument(
        "--action",
        choices=(
            "go-get",
            "validate",
            "check-validation",
            "cleanup",
            "probe-bootstrap",
        ),
    )
    parser.add_argument(
        "--build-arg",
        action="append",
        default=[],
        help="Bounded project build flag or package selector for --action validate.",
    )
    parser.add_argument(
        "--test-arg",
        action="append",
        default=[],
        help="Bounded project test flag or package selector for --action validate.",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser.parse_args()


def select_argv(
    args: argparse.Namespace, plan: dict[str, object]
) -> tuple[str, list[str]]:
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if args.action and command:
        raise CommandError("use either --action or a command after --, not both")
    if (args.build_arg or args.test_arg) and args.action != "validate":
        raise CommandError(
            "build/test argument overrides are allowed only with --action validate"
        )
    if args.action == "go-get":
        return "go-get", list(plan["go_get"])
    if args.action == "validate":
        return "validate", []
    if args.action == "check-validation":
        return "check-validation", []
    if args.action == "cleanup":
        cleanup = plan.get("cleanup")
        if not isinstance(cleanup, list):
            raise CommandError("cleanup is unavailable for this plan")
        return "cleanup", list(cleanup)
    if args.action == "probe-bootstrap":
        return "probe-bootstrap", ["go", "mod", "tidy"]
    if not command or command[0] != "go" or len(command) < 2:
        raise CommandError("provide one explicit allowed Go command after --")
    if command[1] == "mod":
        if len(command) < 3 or command[2] != "tidy":
            raise CommandError("only `go mod tidy` is allowed for go mod")
    elif command[1] not in ALLOWED_GO_SUBCOMMANDS:
        raise CommandError(f"unsupported Go subcommand: {command[1]}")
    if any(not item or "\x00" in item for item in command):
        raise CommandError("command arguments must be non-empty and NUL-free")
    forbidden = [
        item
        for item in command[2:]
        if go_flag_name(item) in FORBIDDEN_EXTERNAL_TOOL_FLAGS
    ]
    if forbidden:
        raise CommandError(
            "external Go tool execution flags are not allowed: "
            + ", ".join(forbidden)
        )
    runtime = require_dict(plan.get("runtime"), "runtime")
    executable = runtime.get("path")
    if not isinstance(executable, str):
        raise CommandError("bound Go runtime path is invalid")
    return command[1], [executable, *command[1:]]


def go_flag_name(argument: str) -> str | None:
    """Normalize the one- and two-dash spellings accepted by Go's flag parser."""

    token = argument.split("=", 1)[0]
    if token.startswith("--"):
        return token[2:]
    if token.startswith("-"):
        return token[1:]
    return None


def bounded_validation_args(kind: str, values: list[str]) -> list[str]:
    """Accept only inert Go flags and relative package selectors."""

    if len(values) > MAX_VALIDATION_ARGS:
        raise CommandError(f"{kind} argument count exceeds {MAX_VALIDATION_ARGS}")
    allowed_boolean = {
        "build": {"race", "trimpath"},
        "test": {"race", "short", "failfast", "trimpath"},
    }[kind]
    allowed_values = {
        "build": {"tags", "buildvcs"},
        "test": {"tags", "buildvcs", "run", "count", "timeout", "parallel"},
    }[kind]
    result: list[str] = []
    for value in values or ["./..."]:
        if (
            not value
            or "\x00" in value
            or len(value.encode("utf-8")) > MAX_VALIDATION_ARG_BYTES
        ):
            raise CommandError(f"{kind} argument is empty, oversized, or NUL-bearing")
        flag = go_flag_name(value)
        if flag is not None:
            name = flag.split("=", 1)[0]
            if name not in allowed_boolean | allowed_values:
                raise CommandError(f"unsafe {kind} validation flag: {value}")
            if name in allowed_values and "=" not in value:
                raise CommandError(
                    f"{kind} validation flag must use one argv-bound value: {value}"
                )
        else:
            candidate = Path(value)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise CommandError(f"unsafe {kind} package selector: {value}")
            if not (value == "." or value.startswith("./")):
                raise CommandError(f"unsafe {kind} package selector: {value}")
        result.append(value)
    return result


def validation_commands(
    args: argparse.Namespace,
    runtime: dict[str, Any],
    runtime_root: Path,
) -> tuple[tuple[str, list[str]], ...]:
    executable = runtime.get("path")
    if not isinstance(executable, str):
        raise CommandError("bound Go runtime path is unavailable")
    return (
        ("tidy", [executable, "mod", "tidy"]),
        (
            "build",
            [
                executable,
                "build",
                f"-o={runtime_root / VALIDATION_BUILD_OUTPUT_DIRECTORY}",
                *bounded_validation_args("build", args.build_arg),
            ],
        ),
        ("test", [executable, "test", *bounded_validation_args("test", args.test_arg)]),
    )


def validation_command_binding(
    name: str, argv: list[str], runtime_root: Path
) -> list[str]:
    """Normalize the invocation-owned build output in durable evidence."""

    if name != "build":
        return list(argv)
    expected = f"-o={runtime_root / VALIDATION_BUILD_OUTPUT_DIRECTORY}"
    if len(argv) < 3 or argv[2] != expected:
        raise CommandError("validation build output binding is invalid")
    return [*argv[:2], f"-o={VALIDATION_BUILD_OUTPUT_BINDING}", *argv[3:]]


def command_environment(plan_env: dict[str, str]) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in GO_ENV_TO_SCRUB
    }
    environment.update(plan_env)
    return environment


def environment_binding(
    plan: dict[str, object], environment: dict[str, str]
) -> dict[str, str | None]:
    """Record the exact material Go environment with stable temp placeholders."""

    runtime_root = plan.get("runtime_root")
    proxy_digest = plan.get("proxy_bundle_sha256")
    if not isinstance(runtime_root, Path) or not isinstance(proxy_digest, str):
        raise CommandError("material Go environment binding is unavailable")
    binding: dict[str, str | None] = {}
    for key in MATERIAL_GO_ENV_KEYS:
        value = environment.get(key)
        if value is not None and key in {"GOCACHE", "GOMODCACHE", "GOPATH", "HOME"}:
            path = Path(value)
            try:
                relative = path.relative_to(runtime_root)
            except ValueError as error:
                raise CommandError(f"bound {key} escapes the invocation runtime") from error
            value = f"$INVOCATION/{relative.as_posix()}"
        elif value is not None and key == "GOPROXY":
            expected = (runtime_root / "staged-proxy-cache" / "cache" / "download").as_uri()
            if value != expected:
                raise CommandError("bound GOPROXY is not the invocation-owned proxy")
            value = f"file://$INVOCATION/staged-proxy-cache/cache/download#{proxy_digest}"
        binding[key] = value
    return binding


def reverify_consuming_action(
    plan: dict[str, object],
    resolver: ModuleType,
    *,
    cwd: Path,
    environment: dict[str, str] | None = None,
) -> None:
    """Recheck selected proxy bytes and effective toolchain before consumption."""

    reverify_proxy_bindings(plan, resolver)
    runtime = require_dict(plan.get("runtime"), "runtime")
    bound_environment = environment or command_environment(
        require_dict(plan.get("env"), "runtime env")
    )
    current = runtime_fingerprint(
        {"go_runtime": runtime},
        resolver,
        cwd=cwd,
        environment=bound_environment,
    )
    if current != runtime:
        raise CommandError("bound Go runtime effective toolchain drift")


def read_bounded(path: Path, label: str) -> bytes:
    try:
        status = os.lstat(path)
    except OSError as error:
        raise CommandError(f"could not stat {label}: {error}") from error
    if status_is_link_or_reparse(status) or not stat.S_ISREG(status.st_mode):
        raise CommandError(f"{label} must be a regular file, not a link")
    if status.st_size > MAX_PROJECT_FILE_BYTES:
        raise CommandError(f"{label} exceeds {MAX_PROJECT_FILE_BYTES} bytes")
    try:
        return path.read_bytes()
    except OSError as error:
        raise CommandError(f"could not read {label}: {error}") from error


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def runtime_fingerprint(
    resolved: dict[str, Any],
    resolver: ModuleType,
    *,
    cwd: Path,
    environment: dict[str, str],
) -> dict[str, Any]:
    expected = require_dict(resolved.get("go_runtime"), "go_runtime")
    path = expected.get("path")
    if not isinstance(path, str):
        raise CommandError("persisted plan Go runtime path is invalid")
    try:
        with tempfile.TemporaryDirectory(
            prefix="obstudio-go-runtime-fingerprint-",
            ignore_cleanup_errors=True,
        ) as runtime_directory:
            runtime_root = Path(runtime_directory)
            probe_environment = dict(environment)
            probe_environment.update(
                {
                    "GOCACHE": str(runtime_root / "gocache"),
                    "GOMODCACHE": str(runtime_root / "gomodcache"),
                    "GOPATH": str(runtime_root / "gopath"),
                    "GOTELEMETRYDIR": str(runtime_root / "telemetry"),
                    "HOME": str(runtime_root / "home"),
                }
            )
            current = resolver.go_runtime_fingerprint(
                Path(path), cwd=cwd, environment=probe_environment
            )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise CommandError(f"bound Go runtime is unavailable: {error}") from error
    if current != expected:
        raise CommandError("bound Go runtime fingerprint drift")
    return dict(expected)


def load_persisted_plan(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], dict[str, str]]:
    project_input = args.project.expanduser()
    if not project_input.is_absolute():
        project_input = Path.cwd() / project_input
    project = project_input.resolve()
    if not project.is_dir():
        raise CommandError(f"project directory is unavailable: {project}")

    plan_input = args.plan.expanduser()
    if not plan_input.is_absolute():
        plan_input = Path.cwd() / plan_input
    plan = Path(os.path.abspath(plan_input))
    expected = project / PERSISTED_PLAN
    if plan != expected:
        raise CommandError(f"persisted plan must use the fixed path: {expected}")
    ensure_no_symlink_components(project, plan, "persisted resolver plan")

    expected_sha256 = args.plan_sha256
    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise CommandError("persisted plan SHA-256 must be 64 lowercase hex digits")
    payload = read_bounded(plan, "persisted resolver plan")
    actual_sha256 = digest(payload)
    if actual_sha256 != expected_sha256:
        raise CommandError("persisted resolver plan SHA-256 drift")
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise CommandError(f"persisted resolver plan is invalid: {error}") from error
    resolved = require_dict(value, "persisted plan")
    planned_project, planned_cache, _ = validate_project(resolved)
    if planned_project != project:
        raise CommandError("persisted resolver plan project drift")
    if args.gomodcache is not None:
        requested_cache = args.gomodcache.expanduser().resolve()
        if requested_cache != planned_cache:
            raise CommandError("persisted resolver plan module-cache drift")
    return resolved, {
        "plan_path": str(plan),
        "plan_sha256": actual_sha256,
    }


def optional_file_state(path: Path, label: str) -> dict[str, object]:
    if not path.exists() and not path.is_symlink():
        return {"present": False, "sha256": None}
    payload = read_bounded(path, label)
    return {"present": True, "sha256": digest(payload)}


def directive_state(resolver: ModuleType, go_mod: bytes) -> dict[str, object]:
    try:
        text = go_mod.decode("utf-8")
    except UnicodeError as error:
        raise CommandError(f"project go.mod is not UTF-8: {error}") from error
    module = resolver.module_directive(text)
    go_version, go_status = resolver.go_directive_details(text)
    if module is None or go_status != "valid" or go_version is None:
        raise CommandError("project module/go directives are no longer valid")
    toolchain: list[str] = []
    for raw_line in text.splitlines():
        code, _ = resolver.split_go_mod_comment(raw_line)
        stripped = code.strip()
        if stripped == "toolchain" or stripped.startswith("toolchain "):
            toolchain.append(stripped)
    return {"module": module, "go": go_version, "toolchain": toolchain}


def project_state(project: Path, resolver: ModuleType) -> dict[str, object]:
    go_mod = read_bounded(project / "go.mod", "project go.mod")
    return {
        "go_mod_sha256": digest(go_mod),
        "go_sum": optional_file_state(project / "go.sum", "project go.sum"),
        "directives": directive_state(resolver, go_mod),
    }


def go_source_tree_state(project: Path) -> dict[str, object]:
    """Hash all bounded regular project build/test inputs without links."""

    entries: list[tuple[str, Path, int, int]] = []
    stack = [project]
    while stack:
        directory = stack.pop()
        try:
            children = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as error:
            raise CommandError(f"could not scan Go source tree: {error}") from error
        for child in children:
            path = Path(child.path)
            relative = path.relative_to(project)
            try:
                status = child.stat(follow_symlinks=False)
            except OSError as error:
                raise CommandError(f"could not stat Go source input {relative}: {error}") from error
            if status_is_link_or_reparse(status):
                if child.name not in SOURCE_EXCLUDED_DIRECTORIES:
                    raise CommandError(f"relevant Go project input is a link: {relative}")
                continue
            if stat.S_ISDIR(status.st_mode):
                if child.name not in SOURCE_EXCLUDED_DIRECTORIES:
                    stack.append(path)
                continue
            if not stat.S_ISREG(status.st_mode):
                raise CommandError(
                    f"Go project input is not a regular file: {relative}"
                )
            entries.append(
                (
                    relative.as_posix(),
                    path,
                    status.st_size,
                    stat.S_IMODE(status.st_mode),
                )
            )
            if len(entries) > MAX_PROJECT_INPUT_FILES:
                raise CommandError(
                    "Go project input file count exceeds the deterministic limit"
                )

    hasher = hashlib.sha256()
    total_bytes = 0
    for relative, path, expected_size, expected_mode in sorted(entries):
        relative_payload = relative.encode("utf-8")
        hasher.update(len(relative_payload).to_bytes(8, "big"))
        hasher.update(relative_payload)
        hasher.update(expected_size.to_bytes(8, "big"))
        hasher.update(expected_mode.to_bytes(4, "big"))
        before = os.lstat(path)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                status_is_link_or_reparse(opened)
                or not stat.S_ISREG(opened.st_mode)
                or file_identity(opened) != file_identity(before)
            ):
                raise CommandError(
                    f"Go project input identity changed before digest: {relative}"
                )
            count = 0
            while True:
                chunk = os.read(descriptor, 1_048_576)
                if not chunk:
                    break
                count += len(chunk)
                total_bytes += len(chunk)
                if total_bytes > MAX_PROJECT_INPUT_BYTES:
                    raise CommandError(
                        "Go project input bytes exceed the deterministic limit"
                    )
                hasher.update(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        named_after = os.lstat(path)
        if count != expected_size or file_identity(before) != file_identity(after) or (
            before.st_size,
            before.st_mtime_ns,
            stat.S_IMODE(before.st_mode),
        ) != (
            after.st_size,
            after.st_mtime_ns,
            stat.S_IMODE(after.st_mode),
        ) or file_identity(before) != file_identity(named_after) or (
            before.st_size,
            before.st_mtime_ns,
            stat.S_IMODE(before.st_mode),
        ) != (
            named_after.st_size,
            named_after.st_mtime_ns,
            stat.S_IMODE(named_after.st_mode),
        ):
            raise CommandError(f"Go project input changed during digest: {relative}")
    return {
        "algorithm": SOURCE_DIGEST_ALGORITHM,
        "complete": True,
        "file_count": len(entries),
        "byte_count": total_bytes,
        "sha256": hasher.hexdigest(),
    }


def validate_persisted_project_state(
    resolved: dict[str, Any], project: Path, resolver: ModuleType
) -> None:
    project_info = require_dict(resolved.get("project"), "project")
    current = project_state(project, resolver)
    if project_info.get("go_mod_sha256") != current["go_mod_sha256"]:
        raise CommandError("persisted resolver plan project go.mod drift")
    if project_info.get("go_sum") != current["go_sum"]:
        raise CommandError("persisted resolver plan project go.sum drift")


def snapshot_project(project: Path) -> dict[str, tuple[bool, bytes, int | None]]:
    snapshot: dict[str, tuple[bool, bytes, int | None]] = {}
    for name in ("go.mod", "go.sum"):
        path = project / name
        if not path.exists() and not path.is_symlink():
            snapshot[name] = (False, b"", None)
            continue
        payload = read_bounded(path, f"project {name}")
        snapshot[name] = (True, payload, stat.S_IMODE(path.stat().st_mode))
    return snapshot


def file_identity(status: os.stat_result) -> tuple[int, int]:
    return status.st_dev, status.st_ino


def require_regular_target_descriptor(parent: int, name: str) -> None:
    try:
        status = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    if status_is_link_or_reparse(status) or not stat.S_ISREG(status.st_mode):
        raise CommandError(
            f"atomic-write target must be a regular file, not a link: {name}"
        )


def require_regular_target_portable(path: Path) -> None:
    if not os.path.lexists(path):
        return
    status = os.lstat(path)
    if status_is_link_or_reparse(status) or not stat.S_ISREG(status.st_mode):
        raise CommandError(
            f"atomic-write target must be a regular file, not a link: {path}"
        )


def write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("atomic write made no progress")
        offset += written


def atomic_write_descriptor(path: Path, payload: bytes, mode: int) -> None:
    parent = os.open(
        path.parent,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    temporary_name = f".{path.name}.{os.getpid()}.tmp"
    descriptor: int | None = None
    temporary_identity: tuple[int, int] | None = None
    published = False
    try:
        require_regular_target_descriptor(parent, path.name)
        try:
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                mode,
                dir_fd=parent,
            )
        except FileExistsError:
            raise CommandError(
                f"temporary path already exists: {path.parent / temporary_name}"
            ) from None
        if descriptor_mode_supported():
            os.fchmod(descriptor, mode)
        write_all(descriptor, payload)
        os.fsync(descriptor)
        temporary_identity = file_identity(os.fstat(descriptor))
        named_status = os.stat(
            temporary_name, dir_fd=parent, follow_symlinks=False
        )
        if (
            status_is_link_or_reparse(named_status)
            or not stat.S_ISREG(named_status.st_mode)
            or file_identity(named_status) != temporary_identity
        ):
            raise CommandError("temporary file identity changed before publication")
        require_regular_target_descriptor(parent, path.name)
        os.rename(
            temporary_name,
            path.name,
            src_dir_fd=parent,
            dst_dir_fd=parent,
        )
        published = True
        published_status = os.stat(
            path.name, dir_fd=parent, follow_symlinks=False
        )
        if (
            status_is_link_or_reparse(published_status)
            or not stat.S_ISREG(published_status.st_mode)
            or file_identity(published_status) != temporary_identity
        ):
            raise CommandError("published file identity changed during publication")
        os.fsync(parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if not published and temporary_identity is not None:
            try:
                current = os.stat(
                    temporary_name, dir_fd=parent, follow_symlinks=False
                )
            except FileNotFoundError:
                pass
            else:
                if file_identity(current) == temporary_identity:
                    os.unlink(temporary_name, dir_fd=parent)
        os.close(parent)


def atomic_write_portable(path: Path, payload: bytes, mode: int) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if os.path.lexists(temporary):
        raise CommandError(f"temporary path already exists: {temporary}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor: int | None = None
    temporary_identity: tuple[int, int] | None = None
    published = False
    try:
        descriptor = os.open(temporary, flags, mode)
        if descriptor_mode_supported():
            os.fchmod(descriptor, mode)
        write_all(descriptor, payload)
        os.fsync(descriptor)
        temporary_identity = file_identity(os.fstat(descriptor))
        named_status = os.lstat(temporary)
        if (
            status_is_link_or_reparse(named_status)
            or not stat.S_ISREG(named_status.st_mode)
            or file_identity(named_status) != temporary_identity
        ):
            raise CommandError("temporary file identity changed before publication")
        require_regular_target_portable(path)
        os.replace(temporary, path)
        published = True
        published_status = os.lstat(path)
        if (
            status_is_link_or_reparse(published_status)
            or not stat.S_ISREG(published_status.st_mode)
            or file_identity(published_status) != temporary_identity
        ):
            raise CommandError("published file identity changed during publication")
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if not published and temporary_identity is not None:
            try:
                current = os.lstat(temporary)
            except FileNotFoundError:
                pass
            else:
                if file_identity(current) == temporary_identity:
                    temporary.unlink()


def atomic_write(path: Path, payload: bytes, mode: int = 0o600) -> None:
    if descriptor_publication_supported():
        atomic_write_descriptor(path, payload, mode)
    else:
        atomic_write_portable(path, payload, mode)


def restore_project(
    project: Path, snapshot: dict[str, tuple[bool, bytes, int | None]]
) -> None:
    failures: list[str] = []
    for name, (present, payload, mode) in snapshot.items():
        path = project / name
        try:
            if path.is_symlink():
                path.unlink()
            if present:
                atomic_write(path, payload, mode or 0o644)
            elif path.exists():
                path.unlink()
        except (CommandError, OSError) as error:
            failures.append(f"{name}:{error}")
    if failures:
        raise CommandError("project rollback failed: " + "; ".join(failures[:2]))


def rollback_project(
    project: Path, snapshot: dict[str, tuple[bool, bytes, int | None]]
) -> tuple[str, str | None]:
    """Restore manifests exactly and return both drift and rollback evidence."""

    try:
        changed = snapshot_project(project) != snapshot
    except (CommandError, OSError):
        changed = True
    try:
        restore_project(project, snapshot)
        if snapshot_project(project) != snapshot:
            raise CommandError("project rollback verification failed")
    except (CommandError, OSError) as error:
        return "attempted", str(error)
    return ("restored" if changed else "verified-unchanged"), None


def exact_pins_present(
    project: Path, resolver: ModuleType, modules: list[str]
) -> bool:
    payload = read_bounded(project / "go.mod", "project go.mod")
    try:
        parsed = resolver.parse_requirements(payload.decode("utf-8"))
    except UnicodeError as error:
        raise CommandError(f"project go.mod is not UTF-8: {error}") from error
    if parsed["issues"] or parsed["has_replace"] or parsed["has_exclude"]:
        return False
    requirements: dict[str, list[str]] = {}
    for item in parsed["requirements"]:
        requirements.setdefault(item["module"], []).append(item["version"])
    for pin in modules:
        module, version = pin.rsplit("@", 1)
        if requirements.get(module) != [version]:
            return False
    return True


def probe_resolved_modules(
    stage: Path, resolver: ModuleType, direct_modules: list[str]
) -> list[str]:
    """Derive the exact module set selected by the successful fixed-import tidy."""

    payload = read_bounded(stage / "go.mod", "bootstrap go.mod")
    try:
        parsed = resolver.parse_requirements(payload.decode("utf-8"))
    except UnicodeError as error:
        raise CommandError(f"bootstrap go.mod is not UTF-8: {error}") from error
    if parsed["issues"] or parsed["has_replace"] or parsed["has_exclude"]:
        raise CommandError("bootstrap resolved module closure is not canonical")
    selected: dict[str, str] = {}
    for requirement in parsed["requirements"]:
        module = requirement["module"]
        version = requirement["version"]
        if (
            module in selected
            or resolver.semver_key(version) is None
            or not resolver.module_version_path_compatible(module, version)
        ):
            raise CommandError("bootstrap resolved module closure is invalid")
        selected[module] = version
    resolved = [f"{module}@{selected[module]}" for module in sorted(selected)]
    if not set(direct_modules).issubset(resolved):
        raise CommandError("bootstrap resolved closure omitted a fixed direct pin")
    return resolved


def select_proxy_bindings(
    bindings: list[dict[str, object]], modules: list[str], label: str
) -> list[dict[str, object]]:
    """Select an exact plan-bound module subset without copying new cache state."""

    indexed = {
        (row.get("module"), row.get("version")): row
        for row in bindings
    }
    selected: list[dict[str, object]] = []
    for pin in modules:
        identity = tuple(pin.rsplit("@", 1))
        row = indexed.get(identity)
        if row is None:
            raise CommandError(f"{label} resolved module is outside the bound proxy")
        selected.append(row)
    return selected


def proxy_binding_modules(
    bindings: list[dict[str, object]], label: str
) -> list[str]:
    """Return a deterministic, duplicate-free identity list for bound rows."""

    identities: set[tuple[str, str]] = set()
    for row in bindings:
        module = row.get("module")
        version = row.get("version")
        if not isinstance(module, str) or not isinstance(version, str):
            raise CommandError(f"{label} proxy module identity is invalid")
        identity = (module, version)
        if identity in identities:
            raise CommandError(f"{label} proxy module identity is duplicated")
        identities.add(identity)
    return [f"{module}@{version}" for module, version in sorted(identities)]


def verify_post_edit(
    project: Path,
    resolver: ModuleType,
    ledger: dict[str, Any],
) -> dict[str, object]:
    current = project_state(project, resolver)
    if current["directives"] != ledger["directives"]:
        raise CommandError("go/toolchain/module directives changed")
    if not exact_pins_present(project, resolver, ledger["modules"]):
        raise CommandError("exact intended OTel pins are not present")
    return current


def ledger_path(project: Path) -> Path:
    return project / OWNED_DIRECTORY / LEDGER_NAME


def write_ledger(project: Path, ledger: dict[str, Any]) -> None:
    path = ledger_path(project)
    ensure_no_symlink_components(project, path, "accepted-plan ledger")
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_no_symlink_components(project, path, "accepted-plan ledger")
    payload = (
        json.dumps(ledger, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    atomic_write(path, payload)


def read_ledger_snapshot(project: Path) -> LedgerSnapshot | None:
    path = ledger_path(project)
    ensure_no_symlink_components(project, path, "accepted-plan ledger")
    if not path.exists():
        return None
    status = os.lstat(path)
    payload = read_bounded(path, "accepted-plan ledger")
    after = os.lstat(path)
    if file_identity(status) != file_identity(after) or (
        status.st_size,
        status.st_mtime_ns,
    ) != (after.st_size, after.st_mtime_ns):
        raise CommandError("accepted-plan ledger changed while being read")
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise CommandError(f"accepted-plan ledger is invalid: {error}") from error
    ledger = require_dict(value, "accepted-plan ledger")
    if (
        ledger.get("schema_version") != LEDGER_SCHEMA_VERSION
        or ledger.get("kind") != LEDGER_KIND
    ):
        raise CommandError("accepted-plan ledger schema is invalid")
    if ledger.get("state") not in {"probed", "applied"}:
        raise CommandError("accepted-plan ledger state is invalid")
    proof_boundaries = {
        "bootstrap-probe": PROBE_PROOF_BOUNDARY,
        "resolver-full-closure": FULL_PLAN_PROOF_BOUNDARY,
    }
    proof_source = ledger.get("proof_source")
    if (
        proof_source not in proof_boundaries
        or ledger.get("proof_boundary") != proof_boundaries[proof_source]
    ):
        raise CommandError("accepted-plan proof boundary is invalid")
    return LedgerSnapshot(
        payload=payload,
        value=ledger,
        sha256=digest(payload),
        identity=file_identity(after),
        mode=stat.S_IMODE(after.st_mode),
    )


def create_ledger(
    plan: dict[str, object],
    resolver: ModuleType,
    state: str,
    *,
    proof_source: str = "bootstrap-probe",
    probe_modules: list[str] | None = None,
    probe_bound_modules: list[str] | None = None,
    probe_graph_modules: list[str] | None = None,
    probe_proxy_sha256: str | None = None,
) -> dict[str, Any]:
    project = plan["project"]
    if not isinstance(project, Path):
        raise CommandError("bootstrap project is invalid")
    project_details = project_state(project, resolver)
    cache = plan.get("source_cache", plan.get("cache"))
    if not isinstance(cache, Path):
        raise CommandError("bootstrap module cache is invalid")
    proof_boundaries = {
        "bootstrap-probe": PROBE_PROOF_BOUNDARY,
        "resolver-full-closure": FULL_PLAN_PROOF_BOUNDARY,
    }
    if proof_source not in proof_boundaries:
        raise CommandError("accepted-plan proof source is invalid")
    plan_path = plan.get("plan_path")
    plan_sha256 = plan.get("plan_sha256")
    if not isinstance(plan_path, str) or not isinstance(plan_sha256, str):
        raise CommandError("accepted-plan resolver binding is invalid")
    ledger = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "kind": LEDGER_KIND,
        "state": state,
        "project": str(project),
        "gomodcache": str(cache),
        "plan_path": plan_path,
        "plan_sha256": plan_sha256,
        "candidate": plan["candidate"],
        "modules": plan["modules"],
        "runtime": plan["runtime"],
        "directives": project_details["directives"],
        "go_mod_sha256": project_details["go_mod_sha256"],
        "go_sum": project_details["go_sum"],
        "proof_source": proof_source,
        "proof_boundary": proof_boundaries[proof_source],
    }
    if proof_source == "bootstrap-probe":
        if (
            not isinstance(probe_modules, list)
            or not probe_modules
            or not isinstance(probe_bound_modules, list)
            or not probe_bound_modules
            or not isinstance(probe_graph_modules, list)
            or not isinstance(probe_proxy_sha256, str)
            or len(probe_proxy_sha256) != 64
        ):
            raise CommandError("bootstrap probe closure binding is unavailable")
        ledger["probe_resolved_modules"] = probe_modules
        ledger["probe_bound_modules"] = probe_bound_modules
        ledger["probe_graph_metadata_modules"] = probe_graph_modules
        ledger["probe_proxy_sha256"] = probe_proxy_sha256
    return ledger


def read_ledger(project: Path) -> dict[str, Any] | None:
    snapshot = read_ledger_snapshot(project)
    return snapshot.value if snapshot is not None else None


def validate_ledger(
    ledger: dict[str, Any],
    project: Path,
    cache: Path,
    resolver: ModuleType,
    *,
    state: str,
    plan_binding: dict[str, str],
    expected_plan: dict[str, object],
) -> dict[str, object]:
    if ledger.get("state") != state:
        raise CommandError(f"accepted-plan ledger must be in {state} state")
    if ledger.get("project") != str(project) or ledger.get("gomodcache") != str(cache):
        raise CommandError("accepted-plan project or module-cache drift")
    if (
        ledger.get("plan_path") != plan_binding.get("plan_path")
        or ledger.get("plan_sha256") != plan_binding.get("plan_sha256")
    ):
        raise CommandError("accepted-plan persisted resolver plan drift")
    candidate = candidate_identity(ledger.get("candidate"))
    modules = require_argv(ledger.get("modules"), "accepted-plan modules")
    if modules != resolver.candidate_modules(candidate):
        raise CommandError("accepted-plan candidate/module drift")
    if (
        candidate != expected_plan.get("candidate")
        or modules != expected_plan.get("modules")
    ):
        raise CommandError("accepted-plan resolver candidate drift")
    runtime = require_dict(ledger.get("runtime"), "accepted-plan runtime")
    env = validate_environment(
        project,
        resolver.execution_env(project, cache, runtime),
        runtime,
    )
    planned_runtime = runtime_fingerprint(
        {
            "go_runtime": runtime,
        },
        resolver,
        cwd=project,
        environment=env,
    )
    if planned_runtime != expected_plan.get("runtime"):
        raise CommandError("accepted-plan Go runtime drift")
    proxy_artifacts = expected_plan.get("proxy_artifacts")
    if not isinstance(proxy_artifacts, list):
        raise CommandError("accepted-plan resolver proxy bindings are invalid")
    allow_partial_proxy = False
    if ledger.get("proof_source") == "bootstrap-probe":
        probe_modules = require_argv(
            ledger.get("probe_resolved_modules"),
            "accepted-plan probe_resolved_modules",
        )
        if (
            probe_modules
            != sorted(probe_modules, key=lambda pin: pin.rsplit("@", 1)[0])
            or not set(modules).issubset(probe_modules)
            or any(pin.count("@") != 1 for pin in probe_modules)
        ):
            raise CommandError("accepted-plan probe module closure is invalid")
        proxy_artifacts = select_proxy_bindings(
            proxy_artifacts,
            probe_modules,
            "accepted-plan",
        )
        if any(
            row.get("file_proxy_complete") is not True
            or row.get("missing_artifacts") != []
            for row in proxy_artifacts
        ):
            raise CommandError(
                "accepted-plan resolved module proxy binding is incomplete"
            )
        bound_modules = require_argv(
            ledger.get("probe_bound_modules"),
            "accepted-plan probe_bound_modules",
        )
        expected_bound_modules = proxy_binding_modules(
            expected_plan["proxy_artifacts"],
            "accepted-plan resolver",
        )
        if bound_modules != expected_bound_modules:
            raise CommandError("accepted-plan bound proxy closure drift")
        bound_artifacts = select_proxy_bindings(
            expected_plan["proxy_artifacts"],
            bound_modules,
            "accepted-plan bound proxy",
        )
        graph_modules_value = ledger.get("probe_graph_metadata_modules")
        expected_graph_modules = expected_plan.get("graph_metadata_modules")
        if (
            not isinstance(graph_modules_value, list)
            or graph_modules_value != expected_graph_modules
        ):
            raise CommandError("accepted-plan graph metadata closure drift")
        if proxy_content_digest(bound_artifacts) != ledger.get(
            "probe_proxy_sha256"
        ):
            raise CommandError("accepted-plan probe proxy closure drift")
        proxy_artifacts = bound_artifacts
        allow_partial_proxy = True
    current = project_state(project, resolver)
    if current["go_mod_sha256"] != ledger.get("go_mod_sha256"):
        raise CommandError("accepted-plan go.mod SHA drift")
    if current["go_sum"] != ledger.get("go_sum"):
        raise CommandError("accepted-plan go.sum drift")
    if current["directives"] != ledger.get("directives"):
        raise CommandError("accepted-plan directive drift")
    if state == "applied" and not exact_pins_present(project, resolver, modules):
        raise CommandError("accepted-plan exact OTel pins drift")
    return {
        "source": "ledger",
        "project": project,
        "cache": cache,
        "env": env,
        "go_get": [planned_runtime["path"], "get", *modules],
        "selection": candidate,
        "candidate": candidate,
        "modules": modules,
        "runtime": planned_runtime,
        "proxy_artifacts": proxy_artifacts,
        "allow_partial_proxy": allow_partial_proxy,
        "ledger": ledger,
        **plan_binding,
    }


def compact_detail(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="replace")
    compact = " ".join(text.split())
    if len(compact) > MAX_BLOCKER_DETAIL:
        return compact[: MAX_BLOCKER_DETAIL - 1] + "…"
    return compact


def terminal_blocker(reason: str, **details: object) -> None:
    payload = {"action": "probe-bootstrap", "status": "blocked", "reason": reason}
    payload.update(details)
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True), file=sys.stderr)


def remove_bookkeeping(project: Path) -> tuple[int, list[str]]:
    """Deactivate the exact accepted-plan ledger by tombstoning its directory.

    Executable caches and probe staging live in a fresh external temporary
    directory. Repository contents are deliberately never traversed here:
    unexpected entries block cleanup and remain untouched. The accepted-plan
    directory is moved intact into a fresh quarantine directory, so even an
    exact-ledger substitution between validation and rename is never unlinked.
    """

    if not descriptor_cleanup_supported():
        return remove_bookkeeping_portable(project)

    root = project / OWNED_DIRECTORY
    errors: list[str] = []
    error_count = 0

    def record(path: Path, error: OSError) -> None:
        nonlocal error_count
        error_count += 1
        if len(errors) < 3:
            errors.append(f"{path.name}:{error.strerror or error}")

    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )

    descriptor: int | None = None
    parent_descriptor: int | None = None
    root_descriptor: int | None = None
    quarantine_descriptor: int | None = None
    ancestor_identities: list[tuple[str | None, tuple[int, int]]] = []

    def identity(open_descriptor: int) -> tuple[int, int]:
        status = os.fstat(open_descriptor)
        return status.st_dev, status.st_ino

    def canonical_ancestors_match() -> bool:
        if not ancestor_identities:
            return False
        reopened: int | None = None
        try:
            reopened = os.open(project, flags)
            if identity(reopened) != ancestor_identities[0][1]:
                return False
            for component, expected in ancestor_identities[1:]:
                if component is None:
                    return False
                next_descriptor = os.open(component, flags, dir_fd=reopened)
                os.close(reopened)
                reopened = next_descriptor
                if identity(reopened) != expected:
                    return False
            return True
        except OSError:
            return False
        finally:
            if reopened is not None:
                os.close(reopened)

    try:
        descriptor = os.open(project, flags)
        ancestor_identities.append((None, identity(descriptor)))
        current_path = project
        for index, component in enumerate(OWNED_DIRECTORY.parts):
            child_path = current_path / component
            try:
                child_descriptor = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                return 0, []
            except OSError as error:
                record(child_path, error)
                return error_count, errors
            if index == len(OWNED_DIRECTORY.parts) - 1:
                parent_descriptor = descriptor
                descriptor = None
                root_descriptor = child_descriptor
                break
            ancestor_identities.append((component, identity(child_descriptor)))
            os.close(descriptor)
            descriptor = child_descriptor
            current_path = child_path

        if parent_descriptor is None or root_descriptor is None:
            return 0, []
        root_status = os.fstat(root_descriptor)
        root_identity = (root_status.st_dev, root_status.st_ino)
        root_name = OWNED_DIRECTORY.name
        try:
            names = os.listdir(root_descriptor)
        except OSError as error:
            record(root, error)
            return error_count, errors
        unexpected = sorted(name for name in names if name != LEDGER_NAME)
        if unexpected:
            error_count += 1
            errors.append(
                f"{root.name}:unexpected entries block non-recursive cleanup: "
                + ", ".join(unexpected[:3])
            )
            return error_count, errors
        if LEDGER_NAME in names:
            try:
                ledger_status = os.stat(
                    LEDGER_NAME,
                    dir_fd=root_descriptor,
                    follow_symlinks=False,
                )
            except OSError as error:
                record(root / LEDGER_NAME, error)
                return error_count, errors
            if not stat.S_ISREG(ledger_status.st_mode):
                error_count += 1
                errors.append(
                    f"{LEDGER_NAME}:accepted-plan ledger is not a regular file"
                )
                return error_count, errors
        quarantine_name = f"{RETIRED_DIRECTORY_PREFIX}{secrets.token_hex(12)}"
        try:
            os.mkdir(quarantine_name, mode=0o700, dir_fd=parent_descriptor)
            quarantine_descriptor = os.open(
                quarantine_name, flags, dir_fd=parent_descriptor
            )
            os.rename(
                root_name,
                "retired",
                src_dir_fd=parent_descriptor,
                dst_dir_fd=quarantine_descriptor,
            )
        except OSError as error:
            record(root, error)
            return error_count, errors
        try:
            retired = os.stat(
                "retired",
                dir_fd=quarantine_descriptor,
                follow_symlinks=False,
            )
        except OSError as error:
            record(root, error)
            return error_count, errors
        if not stat.S_ISDIR(retired.st_mode) or (
            retired.st_dev,
            retired.st_ino,
        ) != root_identity:
            error_count += 1
            errors.append(f"{root.name}:directory namespace changed during cleanup")
        if not canonical_ancestors_match():
            error_count += 1
            if len(errors) < 3:
                errors.append(
                    f"{root.name}:canonical ancestor namespace changed during cleanup"
                )
    finally:
        if quarantine_descriptor is not None:
            os.close(quarantine_descriptor)
        if root_descriptor is not None:
            os.close(root_descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)
        if descriptor is not None:
            os.close(descriptor)
    return error_count, errors


def portable_directory_identity(path: Path) -> tuple[int, int]:
    status = os.lstat(path)
    if path_is_link_or_reparse(path) or not stat.S_ISDIR(status.st_mode):
        raise OSError(f"expected a real directory: {path}")
    return status.st_dev, status.st_ino


def remove_bookkeeping_portable(project: Path) -> tuple[int, list[str]]:
    """Tombstone exact bookkeeping without Unix directory descriptors.

    Identity and reparse checks fail closed around the atomic directory move.
    Windows cannot eliminate the narrow path check/use window without native
    directory handles, but the helper never recursively deletes repository
    content or follows a caller-controlled reparse point.
    """

    root = project / OWNED_DIRECTORY
    parent = root.parent
    try:
        ensure_no_symlink_components(project, root, "accepted-plan directory")
        if not os.path.lexists(root):
            return 0, []
        project_identity = portable_directory_identity(project)
        parent_identity = portable_directory_identity(parent)
        root_identity = portable_directory_identity(root)
        names = sorted(entry.name for entry in os.scandir(root))
        unexpected = [name for name in names if name != LEDGER_NAME]
        if unexpected:
            return 1, [
                f"{root.name}:unexpected entries block non-recursive cleanup: "
                + ", ".join(unexpected[:3])
            ]
        if LEDGER_NAME in names:
            ledger = root / LEDGER_NAME
            ledger_status = os.lstat(ledger)
            if path_is_link_or_reparse(ledger) or not stat.S_ISREG(
                ledger_status.st_mode
            ):
                return 1, [
                    f"{LEDGER_NAME}:accepted-plan ledger is not a regular file"
                ]
        quarantine = parent / (
            f"{RETIRED_DIRECTORY_PREFIX}{secrets.token_hex(12)}"
        )
        quarantine.mkdir(mode=0o700)
        quarantine_identity = portable_directory_identity(quarantine)
        if (
            portable_directory_identity(project) != project_identity
            or portable_directory_identity(parent) != parent_identity
            or portable_directory_identity(root) != root_identity
        ):
            return 1, [f"{root.name}:directory namespace changed during cleanup"]
        retired = quarantine / "retired"
        os.replace(root, retired)
        if (
            portable_directory_identity(project) != project_identity
            or portable_directory_identity(parent) != parent_identity
            or portable_directory_identity(quarantine) != quarantine_identity
            or portable_directory_identity(retired) != root_identity
        ):
            return 1, [f"{root.name}:directory namespace changed during cleanup"]
        return 0, []
    except OSError as error:
        return 1, [f"{root.name}:{error.strerror or error}"]


def retired_bookkeeping_exists(project: Path) -> bool:
    """Recognize an intentional prior tombstone without traversing it."""

    parent = project / OWNED_DIRECTORY.parent
    ensure_no_symlink_components(project, parent, "retired bookkeeping parent")
    if not parent.is_dir():
        return False
    return any(
        path.name.startswith(RETIRED_DIRECTORY_PREFIX)
        and not path_is_link_or_reparse(path)
        and path.is_dir()
        for path in parent.iterdir()
    )


def stage_probe(plan: dict[str, object], resolver: ModuleType) -> int:
    project = plan["project"]
    if not isinstance(project, Path):
        raise CommandError("bootstrap project is invalid")
    runtime_root = plan.get("runtime_root")
    if not isinstance(runtime_root, Path):
        raise CommandError("bootstrap runtime root is invalid")
    stage = runtime_root / STAGE_DIRECTORY
    try:
        stage.mkdir(exist_ok=False)
        modules = plan["modules"]
        if not isinstance(modules, list):
            raise CommandError("bootstrap modules are invalid")
        selection = plan["selection"]
        if not isinstance(selection, dict):
            raise CommandError("bootstrap candidate is invalid")
        go_version = project_state(project, resolver)["directives"]["go"]
        go_mod = "\n".join(
            [
                "module otel.bootstrap.probe",
                "",
                f"go {go_version}",
                "",
                "require (",
                *(
                    f"\t{pin.rsplit('@', 1)[0]} {pin.rsplit('@', 1)[1]}"
                    for pin in modules
                ),
                ")",
                "",
            ]
        ).encode("utf-8")
        imports = "\n".join(
            f'\t_ "{module}"' for module in PROBE_IMPORTS
        )
        source = (
            "package main\n\nimport (\n"
            + imports
            + "\n)\n\nfunc main() {}\n"
        ).encode("utf-8")
        atomic_write(stage / "go.mod", go_mod, 0o600)
        atomic_write(stage / "main.go", source, 0o600)
        runtime = require_dict(plan.get("runtime"), "bootstrap runtime")
        probe_environment = command_environment(plan["env"])
        reverify_consuming_action(
            plan, resolver, cwd=stage, environment=probe_environment
        )
        command_code, command_stdout, command_stderr = digest_command(
            [str(runtime["path"]), "mod", "tidy"],
            plan,
            probe_environment,
            cwd=stage,
        )
    except (CommandError, OSError) as error:
        terminal_blocker(
            "probe-stage-or-tidy-unavailable",
            detail=str(error)[:MAX_BLOCKER_DETAIL],
        )
        return 126
    post_tidy_error: CommandError | None = None
    resolved_modules: list[str] = []
    resolved_bindings: list[dict[str, object]] = []
    bound_modules: list[str] = []
    graph_modules: list[str] = []
    ledger_bindings: list[dict[str, object]] = []
    if command_code == 0:
        try:
            staged = project_state(stage, resolver)
            expected_directives = {
                "module": "otel.bootstrap.probe",
                "go": go_version,
                "toolchain": [],
            }
            if staged["directives"] != expected_directives:
                raise CommandError("staged go/module/toolchain directives changed")
            if read_bounded(stage / "main.go", "bootstrap source") != source:
                raise CommandError("fixed bootstrap source changed")
            if not exact_pins_present(stage, resolver, modules):
                raise CommandError("staged exact intended OTel pins changed")
            resolved_modules = probe_resolved_modules(stage, resolver, modules)
            source_bindings = plan.get("source_proxy_artifacts")
            if not isinstance(source_bindings, list):
                raise CommandError("bootstrap source proxy binding is unavailable")
            bound_modules = proxy_binding_modules(
                source_bindings, "bootstrap bound"
            )
            resolved_bindings = select_proxy_bindings(
                source_bindings,
                resolved_modules,
                "bootstrap",
            )
            if any(
                row.get("file_proxy_complete") is not True
                or row.get("missing_artifacts") != []
                for row in resolved_bindings
            ):
                raise CommandError(
                    "bootstrap resolved module lacks a complete proxy artifact set"
                )
            graph_value = plan.get("graph_metadata_modules")
            if not isinstance(graph_value, list):
                raise CommandError("bootstrap graph metadata binding is unavailable")
            graph_modules = require_argv(
                graph_value, "bootstrap graph_metadata_modules"
            ) if graph_value else []
            ledger_bindings = select_proxy_bindings(
                source_bindings,
                bound_modules,
                "bootstrap bound",
            )
        except CommandError as error:
            post_tidy_error = error
    if command_code != 0:
        terminal_blocker(
            "go-mod-tidy-failed",
            exit_code=command_code,
            stdout=command_stdout,
            stderr=command_stderr,
        )
        return command_code if command_code > 0 else 1
    if post_tidy_error is not None:
        terminal_blocker(
            "probe-post-tidy-invariant-failed",
            detail=str(post_tidy_error)[:MAX_BLOCKER_DETAIL],
        )
        return 4
    try:
        ledger = create_ledger(
            plan,
            resolver,
            "probed",
            probe_modules=resolved_modules,
            probe_bound_modules=bound_modules,
            probe_graph_modules=graph_modules,
            probe_proxy_sha256=proxy_content_digest(ledger_bindings),
        )
        write_ledger(project, ledger)
    except (CommandError, OSError) as error:
        terminal_blocker(
            "accepted-plan-ledger-write-failed",
            detail=str(error)[:MAX_BLOCKER_DETAIL],
        )
        return 3
    print(
        json.dumps(
            {
                "action": "probe-bootstrap",
                "status": "accepted",
                "state": "probed",
                "candidate": selection,
                "modules": modules,
                "resolved_module_count": len(resolved_modules),
                "ledger": str(ledger_path(project)),
                "proof_boundary": PROBE_PROOF_BOUNDARY,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


def verify_cleanup(plan: dict[str, object]) -> list[str]:
    runtime_root = plan.get("runtime_root")
    if not isinstance(runtime_root, Path):
        raise CommandError("cleanup runtime root is invalid")
    allowed = {Path(path) for path in plan["allowed"]}
    unexpected: list[str] = []
    for cache_text in plan["owned"]:
        cache = Path(cache_text)
        ensure_no_symlink_components(runtime_root, cache, "owned runtime cache")
        if not cache.exists():
            continue
        allowed_directories = {
            parent
            for path in allowed
            if path.is_relative_to(cache)
            for parent in path.parents
            if parent == cache or parent.is_relative_to(cache)
        }
        for path in cache.rglob("*"):
            if path.is_symlink():
                unexpected.append(f"symlink:{path}")
            elif path.is_file() and path not in allowed:
                unexpected.append(str(path))
            elif path.is_dir() and path not in allowed_directories:
                unexpected.append(f"directory:{path}")
            elif not path.is_file() and not path.is_dir():
                unexpected.append(f"special:{path}")
    return sorted(unexpected)


def compact_notice(action: str, argv: list[str], plan: dict[str, object]) -> str:
    selection = plan.get("selection")
    selected = selection if isinstance(selection, dict) else None
    return json.dumps(
        {
            "action": action,
            "argv": argv,
            "cwd": str(plan["project"]),
            "selection": selected,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def drain_stream_digest(
    stream: Any,
    state: dict[str, object],
    capture_diagnostic: bool = False,
) -> None:
    hasher = hashlib.sha256()
    count = 0
    head = bytearray()
    tail = bytearray()
    while True:
        chunk = stream.read(65_536)
        if not chunk:
            break
        count += len(chunk)
        hasher.update(chunk)
        if capture_diagnostic:
            remaining = MAX_DIAGNOSTIC_CAPTURE_BYTES - len(head)
            if remaining > 0:
                head.extend(chunk[:remaining])
            tail.extend(chunk)
            if len(tail) > MAX_DIAGNOSTIC_CAPTURE_BYTES:
                del tail[:-MAX_DIAGNOSTIC_CAPTURE_BYTES]
    state.update({"bytes": count, "sha256": hasher.hexdigest()})
    if capture_diagnostic:
        state.update(
            {
                "_diagnostic_head": bytes(head),
                "_diagnostic_tail": (
                    b"" if count <= len(head) else bytes(tail)
                ),
                "_diagnostic_truncated": count > len(head),
            }
        )


def diagnostic_stream_text(state: dict[str, object]) -> str:
    head = state.get("_diagnostic_head", b"")
    tail = state.get("_diagnostic_tail", b"")
    if not isinstance(head, bytes) or not isinstance(tail, bytes):
        return ""
    payload = head if not tail else head + b"\n" + tail
    return payload.decode("utf-8", errors="replace")


def safe_diagnostic_location(raw_path: str, project: Path) -> str | None:
    candidate = raw_path.strip()
    project_prefix = str(project) + os.sep
    if candidate.startswith(project_prefix):
        candidate = candidate[len(project_prefix) :]
    path = Path(candidate)
    if path.is_absolute() or ".." in path.parts or path.suffix != ".go":
        return None
    normalized = path.as_posix()
    if not normalized or len(normalized) > MAX_BLOCKER_DETAIL:
        return None
    return normalized


def sanitize_diagnostic_message(message: str) -> tuple[str, bool, bool]:
    cleaned = ANSI_ESCAPE.sub("", message)
    cleaned = " ".join(
        "".join(character if character.isprintable() else " " for character in cleaned).split()
    )
    if SENSITIVE_DIAGNOSTIC.search(cleaned):
        return "<redacted sensitive diagnostic>", True, False
    cleaned = URL_USERINFO.sub(r"\g<scheme><redacted>@", cleaned)
    cleaned = BEARER_VALUE.sub(r"\g<prefix><redacted>", cleaned)
    cleaned = SENSITIVE_ASSIGNMENT.sub(r"\g<prefix><redacted>", cleaned)
    redacted = OPAQUE_VALUE.sub("<redacted>", cleaned)
    was_redacted = redacted != cleaned
    if len(redacted) > MAX_DIAGNOSTIC_EXCERPT_CHARS:
        return (
            redacted[: MAX_DIAGNOSTIC_EXCERPT_CHARS - 1] + "…",
            was_redacted,
            True,
        )
    return redacted, was_redacted, False


def failure_diagnostic(
    name: str,
    project: Path,
    stdout: dict[str, object],
    stderr: dict[str, object],
) -> dict[str, object]:
    streams = (
        ("stderr", diagnostic_stream_text(stderr)),
        ("stdout", diagnostic_stream_text(stdout)),
    )
    location: dict[str, object] | None = None
    location_message: str | None = None
    location_source: str | None = None
    failed_test: str | None = None
    saw_panic = False
    saw_loopback_block = False
    saw_dependency_failure = False
    saw_manifest_update = False
    for source, text in streams:
        for raw_line in text.splitlines():
            line = ANSI_ESCAPE.sub("", raw_line).strip()
            if not line:
                continue
            if failed_test is None:
                match = FAILED_TEST.match(line)
                if match is not None:
                    failed_test = match.group("name")
            lowered = line.lower()
            saw_panic = saw_panic or lowered.startswith("panic:")
            saw_loopback_block = saw_loopback_block or (
                "operation not permitted" in lowered
                and ("listen tcp" in lowered or "failed to listen" in lowered)
            )
            saw_dependency_failure = saw_dependency_failure or any(
                marker in lowered
                for marker in (
                    "no required module provides package",
                    "module lookup disabled",
                    "cannot find module providing package",
                    "unrecognized import path",
                    "reading https://",
                )
            )
            saw_manifest_update = saw_manifest_update or (
                lowered.startswith("go: updates to go.")
                and "needed" in lowered
            )
            if location is not None:
                continue
            match = DIAGNOSTIC_LOCATION.match(line)
            if match is None:
                continue
            path = safe_diagnostic_location(match.group("path"), project)
            if path is None:
                continue
            location = {
                "path": path,
                "line": int(match.group("line")),
            }
            if match.group("column") is not None:
                location["column"] = int(match.group("column"))
            location_message = match.group("message")
            location_source = source

    diagnostic: dict[str, object]
    if saw_loopback_block:
        diagnostic = {
            "category": "environment_blocked",
            "excerpt": "loopback network binding is not permitted",
        }
    elif saw_dependency_failure:
        diagnostic = {
            "category": "dependency_resolution_failed",
            "excerpt": "the bound Go dependency set could not be resolved",
        }
    elif saw_manifest_update:
        diagnostic = {
            "category": "manifest_update_required",
            "excerpt": "the Go command requires a go.mod or go.sum update",
        }
    elif failed_test is not None or (name == "test" and saw_panic):
        diagnostic = {
            "category": "test_failure",
            "excerpt": (
                f"--- FAIL: {failed_test}"
                if failed_test is not None
                else "the test process panicked"
            ),
        }
    elif location is not None:
        diagnostic = {"category": "compile_error"}
    else:
        diagnostic = {"category": f"{name}_failed"}

    capture_truncated = any(
        stream.get("_diagnostic_truncated") is True for stream in (stdout, stderr)
    )
    if location is not None:
        diagnostic["location"] = location
        if diagnostic["category"] == "compile_error" and location_message is not None:
            message, message_redacted, message_truncated = sanitize_diagnostic_message(
                location_message
            )
            suffix = f": {message}" if message else ""
            column = (
                f":{location['column']}" if "column" in location else ""
            )
            excerpt = f"{location['path']}:{location['line']}{column}{suffix}"
            if len(excerpt) > MAX_DIAGNOSTIC_EXCERPT_CHARS:
                excerpt = excerpt[: MAX_DIAGNOSTIC_EXCERPT_CHARS - 1] + "…"
                message_truncated = True
            diagnostic["excerpt"] = excerpt
            capture_truncated = capture_truncated or message_truncated
            if message_redacted:
                diagnostic["redacted"] = True
        diagnostic["source"] = location_source
    if "excerpt" in diagnostic:
        diagnostic["truncated"] = capture_truncated
    return diagnostic


def digest_command(
    argv: list[str],
    plan: dict[str, object],
    environment: dict[str, str],
    *,
    cwd: Path | None = None,
    capture_diagnostic: bool = False,
) -> tuple[int, dict[str, object], dict[str, object]]:
    """Drain arbitrary child output and retain only count + digest."""

    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd or plan["project"],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        payload = str(error).encode("utf-8", errors="replace")
        return (
            126,
            {
                "bytes": 0,
                "sha256": digest(b""),
                **(
                    {
                        "_diagnostic_head": b"",
                        "_diagnostic_tail": b"",
                        "_diagnostic_truncated": False,
                    }
                    if capture_diagnostic
                    else {}
                ),
            },
            {
                "bytes": len(payload),
                "sha256": digest(payload),
                **(
                    {
                        "_diagnostic_head": payload[:MAX_DIAGNOSTIC_CAPTURE_BYTES],
                        "_diagnostic_tail": b"",
                        "_diagnostic_truncated": len(payload)
                        > MAX_DIAGNOSTIC_CAPTURE_BYTES,
                    }
                    if capture_diagnostic
                    else {}
                ),
            },
        )
    stdout: dict[str, object] = {}
    stderr: dict[str, object] = {}
    assert process.stdout is not None and process.stderr is not None
    threads = [
        threading.Thread(
            target=drain_stream_digest,
            args=(process.stdout, stdout, capture_diagnostic),
        ),
        threading.Thread(
            target=drain_stream_digest,
            args=(process.stderr, stderr, capture_diagnostic),
        ),
    ]
    for thread in threads:
        thread.start()
    return_code = process.wait()
    for thread in threads:
        thread.join()
    process.stdout.close()
    process.stderr.close()
    if return_code < 0:
        return_code = 128 + (-return_code)
    return return_code, stdout, stderr


def execute(
    argv: list[str],
    plan: dict[str, object],
    env: dict[str, str] | None = None,
) -> tuple[int, dict[str, object], dict[str, object]]:
    return digest_command(
        argv,
        plan,
        env or command_environment(plan["env"]),
    )


def validation_evidence_path(project: Path) -> Path:
    """Prepare the fixed project-owned validation evidence path safely."""

    path = project / VALIDATION_EVIDENCE
    ensure_no_symlink_components(project, path, "Go validation evidence")
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_no_symlink_components(project, path, "Go validation evidence")
    require_regular_target_portable(path)
    return path


def validation_command_evidence(
    name: str,
    argv: list[str],
    return_code: int,
    stdout: dict[str, object],
    stderr: dict[str, object],
    environment: dict[str, str | None],
) -> dict[str, object]:
    return {
        "name": name,
        "argv": argv,
        "status": "passed" if return_code == 0 else "failed",
        "exit_code": return_code,
        "stdout_bytes": stdout["bytes"],
        "stdout_sha256": stdout["sha256"],
        "stderr_bytes": stderr["bytes"],
        "stderr_sha256": stderr["sha256"],
        "environment": environment,
    }


def restore_ledger(project: Path, payload: bytes) -> None:
    path = ledger_path(project)
    ensure_no_symlink_components(project, path.parent, "accepted-plan ledger parent")
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_no_symlink_components(project, path.parent, "accepted-plan ledger parent")
    if path_is_link_or_reparse(path):
        path.unlink()
    atomic_write(path, payload)


def require_ledger_snapshot(
    project: Path,
    accepted: LedgerSnapshot,
    *,
    restore_on_drift: bool,
) -> None:
    """Reject byte or identity replacement, including semantic equivalents."""

    drift = False
    try:
        status = os.lstat(ledger_path(project))
        payload = read_bounded(ledger_path(project), "accepted-plan ledger")
        after = os.lstat(ledger_path(project))
        drift = (
            file_identity(status) != accepted.identity
            or file_identity(after) != accepted.identity
            or payload != accepted.payload
            or stat.S_IMODE(status.st_mode) != accepted.mode
            or stat.S_IMODE(after.st_mode) != accepted.mode
        )
    except (CommandError, OSError):
        drift = True
    if not drift:
        return
    if restore_on_drift:
        restore_ledger(project, accepted.payload)
    raise CommandError("accepted-plan ledger exact-byte identity drift")


def run_ledger_validation(
    plan: dict[str, object],
    resolver: ModuleType,
    commands: tuple[tuple[str, list[str]], ...],
) -> int:
    """Run the fixed Go viability gate serially in one isolated runtime."""

    project = plan["project"]
    ledger = plan.get("ledger")
    accepted = plan.get("ledger_snapshot")
    runtime = plan.get("runtime")
    if (
        not isinstance(project, Path)
        or not isinstance(ledger, dict)
        or not isinstance(accepted, LedgerSnapshot)
        or not isinstance(runtime, dict)
    ):
        raise CommandError("accepted-plan validation state is invalid")
    runtime_root = plan.get("runtime_root")
    if not isinstance(runtime_root, Path):
        raise CommandError("accepted-plan validation runtime is invalid")
    build_output = runtime_root / VALIDATION_BUILD_OUTPUT_DIRECTORY
    build_output.mkdir(exist_ok=False)
    evidence_path = validation_evidence_path(project)
    require_ledger_snapshot(project, accepted, restore_on_drift=False)
    ledger_before = accepted.payload
    project_before = project_state(project, resolver)
    source_before = go_source_tree_state(project)
    environment = command_environment(plan["env"])
    results: list[dict[str, object]] = []
    runner_error: str | None = None
    failed_command: str | None = None
    return_code = 0

    current_accepted = accepted
    for name, argv in commands:
        snapshot = snapshot_project(project)
        require_ledger_snapshot(project, current_accepted, restore_on_drift=False)
        command_env = dict(environment)
        if name != "tidy":
            command_env["GOFLAGS"] = "-mod=readonly"
        reverify_consuming_action(
            plan, resolver, cwd=project, environment=command_env
        )
        command_code, stdout, stderr = digest_command(
            list(argv),
            plan,
            command_env,
            capture_diagnostic=True,
        )
        child_exit_code = command_code
        result = validation_command_evidence(
            name,
            validation_command_binding(name, list(argv), runtime_root),
            command_code,
            stdout,
            stderr,
            environment_binding(plan, command_env),
        )
        result["child_exit_code"] = child_exit_code
        if child_exit_code != 0:
            result["diagnostic"] = failure_diagnostic(
                name,
                project,
                stdout,
                stderr,
            )
        results.append(result)

        integrity_error: str | None = None
        try:
            require_ledger_snapshot(
                project, current_accepted, restore_on_drift=True
            )
        except (CommandError, OSError) as error:
            integrity_error = str(error)
            runner_error = integrity_error
            result["status"] = "failed"
            result["runner_error"] = integrity_error
            if child_exit_code == 0:
                result["exit_code"] = 2
                command_code = 2

        if command_code == 0 and name == "tidy":
            try:
                updated = verify_post_edit(project, resolver, ledger)
                updated_ledger = dict(ledger)
                updated_ledger.update(updated)
                updated_ledger["validation_commands"] = {
                    command_name: validation_command_binding(
                        command_name, command_argv, runtime_root
                    )
                    for command_name, command_argv in commands
                }
                write_ledger(project, updated_ledger)
                updated_snapshot = read_ledger_snapshot(project)
                if updated_snapshot is None:
                    raise CommandError("updated accepted-plan ledger is unavailable")
                ledger = updated_ledger
                current_accepted = updated_snapshot
                plan["ledger"] = updated_ledger
                plan["ledger_snapshot"] = updated_snapshot
                source_before = go_source_tree_state(project)
            except (CommandError, OSError) as error:
                runner_error = str(error)
                result["status"] = "failed"
                result["exit_code"] = 2
                result["runner_error"] = runner_error
                command_code = 2
                try:
                    restore_ledger(project, ledger_before)
                except (CommandError, OSError) as rollback_error:
                    result["ledger_rollback_error"] = str(rollback_error)
                    runner_error += f"; ledger rollback failed: {rollback_error}"

        if command_code != 0:
            rollback_status, rollback_error = rollback_project(project, snapshot)
            result["manifest_rollback"] = rollback_status
            if rollback_error is not None:
                result["rollback_error"] = rollback_error
                if runner_error:
                    runner_error += f"; {rollback_error}"
                else:
                    runner_error = rollback_error
            if integrity_error is not None and child_exit_code != 0:
                result["exit_code"] = child_exit_code
                command_code = child_exit_code
        elif name != "tidy":
            current = project_state(project, resolver)
            if (
                current["go_mod_sha256"] != ledger.get("go_mod_sha256")
                or current["go_sum"] != ledger.get("go_sum")
            ):
                rollback_status, rollback_error = rollback_project(project, snapshot)
                runner_error = f"{name} changed go.mod or go.sum"
                result["status"] = "failed"
                result["exit_code"] = 2
                result["runner_error"] = runner_error
                result["manifest_rollback"] = rollback_status
                if rollback_error is not None:
                    result["rollback_error"] = rollback_error
                    runner_error += f"; {rollback_error}"
                command_code = 2

        if command_code != 0:
            failed_command = name
            return_code = command_code
            break

    try:
        require_ledger_snapshot(project, current_accepted, restore_on_drift=True)
        source_after = go_source_tree_state(project)
        if source_after != source_before:
            raise CommandError("Go source tree changed during serial validation")
        current_runtime = runtime_fingerprint(
            {"go_runtime": runtime},
            resolver,
            cwd=project,
            environment=environment,
        )
        if current_runtime != runtime:
            raise CommandError("bound Go runtime changed during serial validation")
    except (CommandError, OSError) as error:
        final_error = str(error)
        runner_error = (
            f"{runner_error}; {final_error}" if runner_error else final_error
        )
        if return_code == 0:
            return_code = 2
            failed_command = "integrity"
        try:
            source_after = go_source_tree_state(project)
        except (CommandError, OSError) as source_error:
            source_after = {
                "algorithm": SOURCE_DIGEST_ALGORITHM,
                "complete": False,
                "file_count": 0,
                "byte_count": 0,
                "sha256": None,
                "error": str(source_error),
            }

    ledger_after = current_accepted.payload
    project_after = project_state(project, resolver)
    status = "passed" if return_code == 0 else "failed"
    evidence = {
        "schema_version": VALIDATION_EVIDENCE_SCHEMA_VERSION,
        "kind": "go-otel-serial-validation",
        "action": "validate",
        "status": status,
        "project": str(project),
        "selection": plan.get("selection"),
        "resolver_plan": {
            "path": plan.get("plan_path"),
            "sha256": plan.get("plan_sha256"),
        },
        "accepted_plan": {
            "state": ledger.get("state"),
            "proof_source": ledger.get("proof_source"),
            "proof_boundary": ledger.get("proof_boundary"),
            "sha256_before": digest(ledger_before),
            "sha256_after": digest(ledger_after),
            "bytes_before": len(ledger_before),
            "bytes_after": len(ledger_after),
        },
        "runtime": {
            "isolation": "one runner invocation with one cache and module cache",
            "go_mod_tidy_before_build_and_test": True,
            "parallel_state_changing_commands": False,
            "fingerprint": runtime,
            "environment": environment_binding(plan, environment),
            "proxy_bundle_sha256": plan.get("proxy_bundle_sha256"),
            "proxy_artifact_count": plan.get("proxy_artifact_count"),
            "proxy_total_bytes": plan.get("proxy_total_bytes"),
            "build_output": VALIDATION_BUILD_OUTPUT_BINDING,
        },
        "source_tree_before": source_before,
        "source_tree_after": source_after,
        "project_state_before": project_before,
        "project_state_after": project_after,
        "commands": results,
        "failed_command": failed_command,
        "runner_error": runner_error,
    }
    evidence_payload = (
        json.dumps(evidence, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    atomic_write(evidence_path, evidence_payload)
    summary = {
        "action": "validate",
        "status": status,
        "commands_completed": len(results),
        "evidence": VALIDATION_EVIDENCE.as_posix(),
        "evidence_sha256": digest(evidence_payload),
        "accepted_plan_sha256": digest(ledger_after),
        "source_sha256": source_after.get("sha256"),
    }
    if failed_command is not None:
        summary["failed_command"] = failed_command
        summary["exit_code"] = return_code
        failed_rows = [
            row for row in results if row.get("name") == failed_command
        ]
        if failed_rows and isinstance(failed_rows[-1].get("diagnostic"), dict):
            summary["diagnostic"] = failed_rows[-1]["diagnostic"]
    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
    return return_code


def check_ledger_validation(
    plan: dict[str, object], resolver: ModuleType
) -> int:
    """Read-only freshness check for one successful fixed Go validation."""

    project = plan.get("project")
    ledger = plan.get("ledger")
    accepted = plan.get("ledger_snapshot")
    runtime = plan.get("runtime")
    if (
        not isinstance(project, Path)
        or not isinstance(ledger, dict)
        or not isinstance(accepted, LedgerSnapshot)
        or not isinstance(runtime, dict)
    ):
        raise CommandError("accepted-plan validation state is invalid")
    require_ledger_snapshot(project, accepted, restore_on_drift=False)
    reverify_consuming_action(
        plan,
        resolver,
        cwd=project,
        environment=command_environment(plan["env"]),
    )

    commands = require_dict(
        ledger.get("validation_commands"), "accepted-plan validation_commands"
    )
    expected_names = ("tidy", "build", "test")
    if set(commands) != set(expected_names):
        raise CommandError("accepted-plan validation command binding is invalid")
    expected_commands = [
        (name, require_argv(commands.get(name), f"validation_commands.{name}"))
        for name in expected_names
    ]
    if expected_commands[0][1] != [runtime["path"], "mod", "tidy"]:
        raise CommandError("accepted-plan tidy command binding is invalid")
    if (
        len(expected_commands[1][1]) < 3
        or expected_commands[1][1][2]
        != f"-o={VALIDATION_BUILD_OUTPUT_BINDING}"
    ):
        raise CommandError("accepted-plan build output binding is invalid")
    for name, argv in expected_commands[1:]:
        if argv[:2] != [runtime["path"], name]:
            raise CommandError(f"accepted-plan {name} command binding is invalid")

    evidence_path = project / VALIDATION_EVIDENCE
    payload = read_bounded(evidence_path, "Go validation evidence")
    try:
        evidence = require_dict(json.loads(payload), "Go validation evidence")
    except (json.JSONDecodeError, UnicodeError) as error:
        raise CommandError(f"Go validation evidence is invalid: {error}") from error
    if (
        evidence.get("schema_version") != VALIDATION_EVIDENCE_SCHEMA_VERSION
        or evidence.get("kind") != "go-otel-serial-validation"
        or evidence.get("action") != "validate"
        or evidence.get("status") != "passed"
        or evidence.get("failed_command") is not None
        or evidence.get("runner_error") is not None
    ):
        raise CommandError("Go validation evidence is not a successful final gate")
    if evidence.get("project") != str(project):
        raise CommandError("Go validation evidence project drift")
    resolver_plan = require_dict(evidence.get("resolver_plan"), "resolver_plan")
    if resolver_plan != {
        "path": plan.get("plan_path"),
        "sha256": plan.get("plan_sha256"),
    }:
        raise CommandError("Go validation evidence resolver-plan drift")
    accepted_evidence = require_dict(evidence.get("accepted_plan"), "accepted_plan")
    if (
        accepted_evidence.get("sha256_after") != accepted.sha256
        or accepted_evidence.get("bytes_after") != len(accepted.payload)
    ):
        raise CommandError("Go validation evidence accepted-ledger drift")
    runtime_evidence = require_dict(evidence.get("runtime"), "runtime")
    if runtime_evidence.get("fingerprint") != runtime:
        raise CommandError("Go validation evidence runtime drift")
    if runtime_evidence.get("build_output") != VALIDATION_BUILD_OUTPUT_BINDING:
        raise CommandError("Go validation evidence build output drift")
    base_environment = command_environment(require_dict(plan.get("env"), "runtime env"))
    if runtime_evidence.get("environment") != environment_binding(
        plan, base_environment
    ):
        raise CommandError("Go validation evidence material environment drift")
    if (
        runtime_evidence.get("proxy_bundle_sha256")
        != plan.get("proxy_bundle_sha256")
        or runtime_evidence.get("proxy_artifact_count")
        != plan.get("proxy_artifact_count")
        or runtime_evidence.get("proxy_total_bytes")
        != plan.get("proxy_total_bytes")
    ):
        raise CommandError("Go validation evidence staged-proxy drift")
    if evidence.get("project_state_after") != project_state(project, resolver):
        raise CommandError("Go validation evidence go.mod/go.sum drift")
    source = go_source_tree_state(project)
    if (
        evidence.get("source_tree_before") != source
        or evidence.get("source_tree_after") != source
    ):
        raise CommandError("Go validation evidence source-tree drift")
    command_evidence = evidence.get("commands")
    if not isinstance(command_evidence, list) or len(command_evidence) != 3:
        raise CommandError("Go validation command evidence is incomplete")
    for item, (name, argv) in zip(command_evidence, expected_commands, strict=True):
        row = require_dict(item, f"commands.{name}")
        if row.get("name") != name or row.get("argv") != argv:
            raise CommandError(f"Go validation {name} command drift")
        if row.get("status") != "passed" or row.get("exit_code") != 0:
            raise CommandError(f"Go validation {name} did not pass")
        command_environment_value = dict(base_environment)
        if name != "tidy":
            command_environment_value["GOFLAGS"] = "-mod=readonly"
        if row.get("environment") != environment_binding(
            plan, command_environment_value
        ):
            raise CommandError(f"Go validation {name} environment drift")
        if "stdout" in row or "stderr" in row:
            raise CommandError("Go validation evidence contains forbidden plaintext output")
        for stream in ("stdout", "stderr"):
            count = row.get(f"{stream}_bytes")
            stream_digest = row.get(f"{stream}_sha256")
            if type(count) is not int or count < 0:
                raise CommandError(f"Go validation {name} {stream} count is invalid")
            if (
                not isinstance(stream_digest, str)
                or len(stream_digest) != 64
                or any(character not in "0123456789abcdef" for character in stream_digest)
            ):
                raise CommandError(f"Go validation {name} {stream} digest is invalid")

    summary = {
        "action": "check-validation",
        "status": "passed",
        "evidence": VALIDATION_EVIDENCE.as_posix(),
        "evidence_sha256": digest(payload),
        "accepted_plan_sha256": accepted.sha256,
        "source_sha256": source["sha256"],
        "runtime_sha256": runtime["sha256"],
        "resolver_plan_sha256": plan.get("plan_sha256"),
        "proxy_bundle_sha256": plan.get("proxy_bundle_sha256"),
    }
    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
    return 0


def run_ledger_go_get(
    argv: list[str], plan: dict[str, object], resolver: ModuleType
) -> int:
    project = plan["project"]
    if not isinstance(project, Path):
        raise CommandError("accepted-plan project is invalid")
    accepted = plan.get("ledger_snapshot")
    if not isinstance(accepted, LedgerSnapshot):
        raise CommandError("accepted-plan exact-byte snapshot is invalid")
    snapshot = snapshot_project(project)
    require_ledger_snapshot(project, accepted, restore_on_drift=False)
    try:
        action_environment = command_environment(plan["env"])
        reverify_consuming_action(
            plan, resolver, cwd=project, environment=action_environment
        )
        return_code, stdout, stderr = execute(argv, plan, action_environment)
        require_ledger_snapshot(project, accepted, restore_on_drift=True)
    except BaseException:
        restore_project(project, snapshot)
        raise
    ledger = plan["ledger"]
    if not isinstance(ledger, dict):
        raise CommandError("accepted-plan ledger is invalid")
    if return_code != 0:
        rollback_status, rollback_error = rollback_project(project, snapshot)
        result: dict[str, object] = {
            "action": "go-get",
            "status": "failed",
            "exit_code": return_code,
            "child_exit_code": return_code,
            "stdout": stdout,
            "stderr": stderr,
            "manifest_rollback": rollback_status,
        }
        if rollback_error is not None:
            result["rollback_error"] = rollback_error
        print(
            json.dumps(result, separators=(",", ":"), sort_keys=True)
        )
        return return_code
    try:
        updated = verify_post_edit(project, resolver, ledger)
    except CommandError:
        restore_project(project, snapshot)
        raise
    ledger = dict(ledger)
    ledger.update(updated)
    ledger["state"] = "applied"
    try:
        write_ledger(project, ledger)
    except (CommandError, OSError):
        restore_project(project, snapshot)
        restore_ledger(project, accepted.payload)
        raise
    print(
        json.dumps(
            {
                "action": "go-get",
                "status": "passed",
                "selection": plan.get("selection"),
                "stdout": stdout,
                "stderr": stderr,
                "accepted_plan_sha256": digest(
                    read_bounded(ledger_path(project), "accepted-plan ledger")
                ),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


def run_ledger_followup(
    action: str,
    argv: list[str],
    plan: dict[str, object],
    resolver: ModuleType,
) -> int:
    project = plan["project"]
    if not isinstance(project, Path):
        raise CommandError("accepted-plan project is invalid")
    accepted = plan.get("ledger_snapshot")
    if not isinstance(accepted, LedgerSnapshot):
        raise CommandError("accepted-plan exact-byte snapshot is invalid")
    if action != "mod" and action not in BOOTSTRAP_FOLLOWUP_SUBCOMMANDS:
        raise CommandError(f"{action} is not allowed by an accepted bootstrap plan")
    runtime = require_dict(plan.get("runtime"), "runtime")
    if action == "mod" and argv != [runtime.get("path"), "mod", "tidy"]:
        raise CommandError("accepted bootstrap plan allows only exact `go mod tidy`")
    forbidden = [
        item
        for item in argv[2:]
        if go_flag_name(item) in FORBIDDEN_BOOTSTRAP_FLAGS
    ]
    if forbidden:
        raise CommandError(
            "dependency-mutating Go flags are not allowed: " + ", ".join(forbidden)
        )
    snapshot = snapshot_project(project)
    environment = command_environment(plan["env"])
    if action != "mod":
        environment["GOFLAGS"] = "-mod=readonly"
    require_ledger_snapshot(project, accepted, restore_on_drift=False)
    try:
        reverify_consuming_action(
            plan, resolver, cwd=project, environment=environment
        )
        return_code, stdout, stderr = execute(argv, plan, environment)
        require_ledger_snapshot(project, accepted, restore_on_drift=True)
    except BaseException:
        restore_project(project, snapshot)
        raise
    ledger = plan["ledger"]
    if not isinstance(ledger, dict):
        raise CommandError("accepted-plan ledger is invalid")
    if action == "mod" and return_code != 0:
        restore_project(project, snapshot)
        print(
            json.dumps(
                {
                    "action": action,
                    "status": "failed",
                    "exit_code": return_code,
                    "stdout": stdout,
                    "stderr": stderr,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return return_code
    if action == "mod" and return_code == 0:
        try:
            updated = verify_post_edit(project, resolver, ledger)
        except CommandError:
            restore_project(project, snapshot)
            raise
        ledger = dict(ledger)
        ledger.update(updated)
        try:
            write_ledger(project, ledger)
        except (CommandError, OSError):
            restore_project(project, snapshot)
            restore_ledger(project, accepted.payload)
            raise
    else:
        current = project_state(project, resolver)
        if (
            current["go_mod_sha256"] != ledger["go_mod_sha256"]
            or current["go_sum"] != ledger["go_sum"]
        ):
            restore_project(project, snapshot)
            raise CommandError(f"{action} changed go.mod or go.sum")
    print(
        json.dumps(
            {
                "action": action,
                "status": "passed" if return_code == 0 else "failed",
                "exit_code": return_code,
                "stdout": stdout,
                "stderr": stderr,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return return_code


def run(args: argparse.Namespace, runtime_root: Path) -> int:
    try:
        resolver = load_resolver()
        resolved, plan_binding = load_persisted_plan(args)
        project, cache, _ = validate_project(resolved)
        bookkeeping_root = project / OWNED_DIRECTORY
        if args.action == "cleanup" and (
            bookkeeping_root.exists() or bookkeeping_root.is_symlink()
        ):
            count, errors = remove_bookkeeping(project)
            if count:
                print(
                    json.dumps(
                        {
                            "action": "cleanup",
                            "status": "blocked",
                            "count": count,
                            "errors": errors,
                        },
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    file=sys.stderr,
                )
                return 3
            print(
                json.dumps(
                    {"action": "cleanup", "status": "complete"},
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0
        if args.action == "cleanup" and retired_bookkeeping_exists(project):
            print(
                json.dumps(
                    {"action": "cleanup", "status": "complete"},
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0
        ledger_snapshot = read_ledger_snapshot(project)
        ledger = ledger_snapshot.value if ledger_snapshot is not None else None
        if ledger is None:
            validate_persisted_project_state(resolved, project, resolver)
        if args.action == "probe-bootstrap":
            plan = validate_bootstrap_plan(resolved, resolver)
            plan.update(plan_binding)
            plan = prepare_invocation(plan, resolver, runtime_root)
            return stage_probe(plan, resolver)

        if ledger is not None:
            if ledger.get("proof_source") == "bootstrap-probe":
                expected = validate_bootstrap_plan(resolved, resolver)
            else:
                expected = validate_resolved_plan(resolved, resolver)
            if ledger.get("state") == "probed":
                plan = validate_ledger(
                    ledger,
                    project,
                    cache,
                    resolver,
                    state="probed",
                    plan_binding=plan_binding,
                    expected_plan=expected,
                )
                plan["ledger_snapshot"] = ledger_snapshot
                if args.action != "go-get":
                    raise CommandError(
                        "run the exact pinned go-get before follow-up commands"
                    )
            else:
                plan = validate_ledger(
                    ledger,
                    project,
                    cache,
                    resolver,
                    state="applied",
                    plan_binding=plan_binding,
                    expected_plan=expected,
                )
                plan["ledger_snapshot"] = ledger_snapshot
                if args.action == "go-get":
                    raise CommandError(
                        "the exact pinned dependency edit is already applied"
                    )
            action, argv = select_argv(args, plan)
            if action == "check-validation":
                validate_check_bound_paths(plan, resolver)
            plan = prepare_invocation(plan, resolver, runtime_root)
            if action == "go-get":
                return run_ledger_go_get(argv, plan, resolver)
            if action == "validate":
                return run_ledger_validation(
                    plan,
                    resolver,
                    validation_commands(
                        args,
                        require_dict(plan.get("runtime"), "runtime"),
                        runtime_root,
                    ),
                )
            if action == "check-validation":
                return check_ledger_validation(plan, resolver)
            return run_ledger_followup(action, argv, plan, resolver)

        plan = validate_resolved_plan(resolved, resolver)
        plan.update(plan_binding)
        action, argv = select_argv(args, plan)
        if action == "go-get":
            ledger = create_ledger(
                plan,
                resolver,
                "probed",
                proof_source="resolver-full-closure",
            )
            write_ledger(project, ledger)
            plan = {**plan, "ledger": ledger}
            created_snapshot = read_ledger_snapshot(project)
            if created_snapshot is None:
                raise CommandError("accepted-plan ledger publication failed")
            plan["ledger_snapshot"] = created_snapshot
            plan = prepare_invocation(plan, resolver, runtime_root)
            return run_ledger_go_get(argv, plan, resolver)
        if action != "cleanup":
            raise CommandError(
                "run the exact pinned go-get before follow-up commands"
            )
        plan = isolate_runtime_paths(plan, runtime_root)
    except (CommandError, OSError) as error:
        if args.action == "probe-bootstrap":
            terminal_blocker(
                "probe-not-eligible", detail=str(error)[:MAX_BLOCKER_DETAIL]
            )
        else:
            print(f"cannot execute Go OTel command: {error}", file=sys.stderr)
        return 2

    return_code, stdout, stderr = execute(argv, plan)
    if return_code != 0:
        print(
            json.dumps(
                {
                    "action": action,
                    "status": "failed",
                    "exit_code": return_code,
                    "stdout": stdout,
                    "stderr": stderr,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return return_code
    if action == "cleanup":
        unexpected = verify_cleanup(plan)
        if unexpected:
            print(
                "resolver cleanup left unexpected cache payloads: "
                + json.dumps(unexpected),
                file=sys.stderr,
            )
            return 3
    print(
        json.dumps(
            {
                "action": action,
                "status": "passed",
                "stdout": stdout,
                "stderr": stderr,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    args = parse_args()
    with tempfile.TemporaryDirectory(
        prefix="obstudio-go-otel-", ignore_cleanup_errors=True
    ) as runtime_text:
        return run(args, Path(runtime_text).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
