#!/usr/bin/env python3
"""Resolve cache-backed, Go-compatible OpenTelemetry dependency pins.

This helper never invokes a shell or edits project manifests. It inspects
go.mod files already in the module cache, fingerprints one selected Go
executable with an exact ``go version`` probe, and emits a candidate command.
When ``--output`` is supplied, it writes the complete deterministic plan there
and prints only a compact, digest-bound branch summary. A plan is complete only
when the file proxy can serve the recursively selected dependency closure and
every selected module supports the project's Go version. When only the exact
direct bundle is ready, the additive ``bootstrap_probe`` field can expose a
bounded, fingerprinted candidate closure for an isolated executable
import-reachability probe. Missing artifacts in the conservative metadata
closure remain absent from that private proxy; the probe decides whether any
of them are actually required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 2
MAX_GO_MOD_BYTES = 1_000_000
MAX_WARNINGS = 32
MAX_CANDIDATE_REJECTIONS = 32
MAX_CLOSURE_MODULES = 256
MAX_CLOSURE_STEPS = 1024
MAX_REQUIREMENTS_PER_GO_MOD = 512
MAX_CACHE_DIRECTORY_ENTRIES = 4_096
MAX_GO_EXECUTABLE_BYTES = 512_000_000
MAX_GO_VERSION_OUTPUT_BYTES = 4_096
MAX_PROXY_ARTIFACT_BYTES = 512_000_000
MAX_PROBE_PROXY_FILES = 1_024
MAX_PROBE_PROXY_BYTES = 1_073_741_824
PROXY_ARTIFACT_SUFFIXES = ("mod", "info", "zip", "ziphash")
PLAN_OUTPUT_DIRECTORY = Path(".observe") / "tmp"
PLAN_OUTPUT_NAME = "go-otel-version-plan.json"
PLAN_OUTPUT_PATH = PLAN_OUTPUT_DIRECTORY / PLAN_OUTPUT_NAME

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
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
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


class Warnings:
    def __init__(self) -> None:
        self.items: list[str] = []
        self.omitted = 0

    def add(self, message: str) -> None:
        if len(self.items) < MAX_WARNINGS:
            self.items.append(message)
        else:
            self.omitted += 1


def _drain_probe_stream(
    stream: Any, state: dict[str, Any], capture_limit: int
) -> None:
    hasher = hashlib.sha256()
    count = 0
    captured = bytearray()
    while True:
        chunk = stream.read(65_536)
        if not chunk:
            break
        count += len(chunk)
        hasher.update(chunk)
        if len(captured) < capture_limit:
            captured.extend(chunk[: capture_limit - len(captured)])
    state.update(
        {
            "bytes": count,
            "sha256": hasher.hexdigest(),
            "captured": bytes(captured),
            "complete": count <= capture_limit,
        }
    )


def bound_go_environment(bound: dict[str, str]) -> dict[str, str]:
    """Apply one exact, scrubbed Go environment to a child process."""

    environment = {
        key: value for key, value in os.environ.items() if key not in GO_ENV_TO_SCRUB
    }
    environment.update(bound)
    return environment


def probe_go_version(
    executable: Path, *, cwd: Path, environment: dict[str, str]
) -> str:
    """Return bounded normalized version output for one canonical executable."""

    process = subprocess.Popen(
        [str(executable), "version"],
        cwd=cwd,
        env=bound_go_environment(environment),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout_state: dict[str, Any] = {}
    stderr_state: dict[str, Any] = {}
    assert process.stdout is not None and process.stderr is not None
    threads = [
        threading.Thread(
            target=_drain_probe_stream,
            args=(process.stdout, stdout_state, MAX_GO_VERSION_OUTPUT_BYTES),
        ),
        threading.Thread(
            target=_drain_probe_stream,
            args=(process.stderr, stderr_state, MAX_GO_VERSION_OUTPUT_BYTES),
        ),
    ]
    for thread in threads:
        thread.start()
    try:
        return_code = process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise ValueError("selected Go executable version probe timed out") from None
    finally:
        for thread in threads:
            thread.join()
        process.stdout.close()
        process.stderr.close()
    if return_code != 0:
        raise ValueError(
            "selected Go executable version probe failed "
            f"(exit {return_code}, stdout {stdout_state.get('bytes', 0)} bytes/"
            f"{stdout_state.get('sha256')}, stderr {stderr_state.get('bytes', 0)} "
            f"bytes/{stderr_state.get('sha256')})"
        )
    if not stdout_state.get("complete") or stderr_state.get("bytes"):
        raise ValueError("selected Go executable returned invalid bounded version output")
    try:
        version = stdout_state["captured"].decode("utf-8").strip()
    except UnicodeError as error:
        raise ValueError("selected Go executable version is not UTF-8") from error
    if not re.fullmatch(r"go version go\S+ \S+/\S+", version):
        raise ValueError("selected Go executable returned an unexpected version")
    return version


def go_runtime_fingerprint(
    requested: Path | None, *, cwd: Path, environment: dict[str, str]
) -> dict[str, Any]:
    """Bind one regular executable by canonical path, bytes, and version."""

    selected = str(requested.expanduser()) if requested is not None else shutil.which("go")
    if not selected:
        raise ValueError("no selected Go executable is available")
    path = Path(selected)
    if not path.is_absolute():
        located = shutil.which(selected)
        if not located:
            raise ValueError(f"selected Go executable is unavailable: {selected}")
        path = Path(located)
    path = path.resolve(strict=True)
    before = os.stat(path, follow_symlinks=False)
    if status_is_link_or_reparse(before) or not stat.S_ISREG(before.st_mode):
        raise ValueError("selected Go executable must be a regular file")
    if not os.access(path, os.X_OK):
        raise ValueError("selected Go executable is not executable")
    if before.st_size > MAX_GO_EXECUTABLE_BYTES:
        raise ValueError("selected Go executable exceeds the fingerprint limit")
    hasher = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1_048_576)
            if not chunk:
                break
            count += len(chunk)
            if count > MAX_GO_EXECUTABLE_BYTES:
                raise ValueError("selected Go executable exceeds the fingerprint limit")
            hasher.update(chunk)
    after = os.stat(path, follow_symlinks=False)
    if file_identity(before) != file_identity(after) or (
        before.st_size,
        before.st_mtime_ns,
    ) != (after.st_size, after.st_mtime_ns):
        raise ValueError("selected Go executable changed during fingerprinting")
    version = probe_go_version(path, cwd=cwd, environment=environment)
    return {
        "path": str(path),
        "size_bytes": count,
        "sha256": hasher.hexdigest(),
        "version": version,
        "effective_toolchain": version.split()[2],
    }


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


def module_path_major(module: str) -> tuple[str, bool]:
    """Return the Go semantic-import-version suffix and its validity."""

    if module.startswith("gopkg.in/"):
        stable_path = (
            module[: -len("-unstable")]
            if module.endswith("-unstable")
            else module
        )
        match = re.search(r"\.v(?P<major>0|[1-9]\d*)$", stable_path)
        if match is None:
            return "", False
        return f".v{match.group('major')}", True

    match = re.search(r"/v(?P<major>[0-9.]+)$", module)
    if match is None:
        return "", True
    major_text = match.group("major")
    if (
        "." in major_text
        or major_text.startswith("0")
        or major_text == "1"
    ):
        return "", False
    return f"/v{major_text}", True


def module_version_path_compatible(module: str, version: str) -> bool:
    """Match Go's module path-major, v0/v1, and +incompatible rules."""

    version_match = SEMVER.fullmatch(version)
    if version_match is None:
        return False
    path_major, path_valid = module_path_major(module)
    if not path_valid:
        return False
    version_major = f"v{version_match.group('major')}"
    if path_major == "":
        return version_major in {"v0", "v1"} or (
            version_match.group("build") == "incompatible"
        )
    if path_major == ".v1" and version.startswith("v0.0.0-"):
        return True
    return version_major == path_major[1:]


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


def ensure_no_link_components(root: Path, target: Path) -> None:
    """Reject links/reparse points in an expected cache artifact path."""

    try:
        relative = target.relative_to(root)
    except ValueError as error:
        raise ValueError("proxy artifact escapes the canonical module cache") from error
    current = root
    root_status = os.lstat(current)
    if status_is_link_or_reparse(root_status) or not stat.S_ISDIR(root_status.st_mode):
        raise ValueError("canonical module cache is not a regular directory")
    for part in relative.parts[:-1]:
        current = current / part
        status = os.lstat(current)
        if status_is_link_or_reparse(status) or not stat.S_ISDIR(status.st_mode):
            raise ValueError(f"proxy artifact parent is not link-safe: {current}")


def proxy_artifact_fingerprint(
    cache: Path, path: Path, label: str
) -> dict[str, Any]:
    """Bind one proxy artifact by namespace identity, bounded bytes, and SHA-256."""

    ensure_no_link_components(cache, path)
    before = os.lstat(path)
    if status_is_link_or_reparse(before) or not stat.S_ISREG(before.st_mode):
        raise ValueError(f"{label} is not a link-safe regular file")
    if before.st_size <= 0 or before.st_size > MAX_PROXY_ARTIFACT_BYTES:
        raise ValueError(f"{label} has an invalid bounded size")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            status_is_link_or_reparse(opened)
            or not stat.S_ISREG(opened.st_mode)
            or file_identity(opened) != file_identity(before)
        ):
            raise ValueError(f"{label} identity changed before hashing")
        hasher = hashlib.sha256()
        count = 0
        while True:
            chunk = os.read(descriptor, 1_048_576)
            if not chunk:
                break
            count += len(chunk)
            if count > MAX_PROXY_ARTIFACT_BYTES:
                raise ValueError(f"{label} exceeds the bounded size")
            hasher.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    named_after = os.lstat(path)
    if (
        count != before.st_size
        or file_identity(before) != file_identity(after)
        or file_identity(before) != file_identity(named_after)
        or (before.st_size, before.st_mtime_ns)
        != (after.st_size, after.st_mtime_ns)
        or (before.st_size, before.st_mtime_ns)
        != (named_after.st_size, named_after.st_mtime_ns)
    ):
        raise ValueError(f"{label} changed during hashing")
    return {
        "path": str(path),
        "size_bytes": count,
        "sha256": hasher.hexdigest(),
        "device": before.st_dev,
        "inode": before.st_ino,
        "mode": stat.S_IMODE(before.st_mode),
        "link_safe": True,
        "regular": True,
    }


def proxy_artifacts(
    cache: Path, module: str, version: str
) -> tuple[dict[str, dict[str, Any]], list[str], list[str]]:
    artifacts: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    unsafe: list[str] = []
    for suffix in PROXY_ARTIFACT_SUFFIXES:
        path = download_artifact(cache, module, version, suffix)
        try:
            artifacts[suffix] = proxy_artifact_fingerprint(
                cache, path, f"{module}@{version}.{suffix}"
            )
        except FileNotFoundError:
            missing.append(suffix)
        except (OSError, ValueError):
            unsafe.append(suffix)
    return artifacts, missing, unsafe


def bounded_cache_entries(
    directory: Path, max_entries: int
) -> tuple[list[Path], bool]:
    """Return sorted entries only when the whole directory fits the bound."""

    if max_entries < 1:
        raise ValueError("max_entries must be at least 1")
    entries: list[Path] = []
    with os.scandir(directory) as iterator:
        for entry in iterator:
            if len(entries) >= max_entries:
                return [], True
            entries.append(directory / entry.name)
    return sorted(entries, key=lambda path: path.name), False


def discover_otelhttp_sources(
    cache: Path,
    warnings: Warnings,
    max_entries: int | None = None,
) -> tuple[dict[str, list[tuple[Path, str]]], bool, int, int]:
    sources: dict[str, list[tuple[Path, str]]] = {}
    scan_failed = False
    directories_truncated = 0
    entries_omitted_at_least = 0
    entry_limit = (
        MAX_CACHE_DIRECTORY_ENTRIES if max_entries is None else max_entries
    )

    parts = OTELHTTP_MODULE.split("/")
    extracted_parent = cache.joinpath(*parts[:-1])
    extracted_prefix = f"{parts[-1]}@"
    if extracted_parent.is_dir():
        try:
            entries, truncated = bounded_cache_entries(
                extracted_parent, entry_limit
            )
        except OSError as error:
            warnings.add(f"could not scan cached otelhttp modules: {error}")
            scan_failed = True
        else:
            if truncated:
                warnings.add(
                    "cached otelhttp module directory exceeded the "
                    f"{entry_limit}-entry scan limit"
                )
                scan_failed = True
                directories_truncated += 1
                entries_omitted_at_least += 1
            else:
                for entry in entries:
                    if not entry.name.startswith(extracted_prefix):
                        continue
                    version = entry.name[len(extracted_prefix) :]
                    go_mod = entry / "go.mod"
                    if go_mod.is_file():
                        sources.setdefault(version, []).append(
                            (go_mod, "extracted")
                        )

    download_dir = (
        cache
        / "cache"
        / "download"
        / Path(*parts)
        / "@v"
    )
    if download_dir.is_dir():
        try:
            entries, truncated = bounded_cache_entries(
                download_dir, entry_limit
            )
        except OSError as error:
            warnings.add(f"could not scan downloaded otelhttp metadata: {error}")
            scan_failed = True
        else:
            if truncated:
                warnings.add(
                    "downloaded otelhttp metadata directory exceeded the "
                    f"{entry_limit}-entry scan limit"
                )
                scan_failed = True
                directories_truncated += 1
                entries_omitted_at_least += 1
            else:
                for entry in entries:
                    if not entry.name.endswith(".mod") or not entry.is_file():
                        continue
                    version = entry.name[: -len(".mod")]
                    existing = sources.setdefault(version, [])
                    if not any(source == "download" for _, source in existing):
                        existing.append((entry, "download"))

    return (
        sources,
        scan_failed,
        directories_truncated,
        entries_omitted_at_least,
    )


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


def base_result(
    project: Path,
    go_mod: Path,
    cache: Path,
    source: str,
    go_runtime: dict[str, Any] | None,
) -> dict[str, Any]:
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
            "go_mod_sha256": None,
            "go_sum": {"present": False, "sha256": None},
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
        "go_runtime": go_runtime,
        "scan": {
            "cache_entry_limit": MAX_CACHE_DIRECTORY_ENTRIES,
            "cache_directories_truncated": 0,
            "cache_entries_omitted_at_least": 0,
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
            "import_closure_complete": False,
            "candidate_closure_inspected": False,
            "closure_modules": 0,
            "available_artifact_count": 0,
            "available_artifact_bytes": 0,
            "candidate": None,
            "modules": [],
            "verification": [],
            "graph_metadata": [],
            "reasons": [],
        },
        "verification": [],
        "graph_metadata": [],
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
    artifacts, missing_artifacts, unsafe_artifacts = proxy_artifacts(
        cache, module, version
    )
    issues: list[str] = []
    if not module_version_path_compatible(module, version):
        issues.append("module-path-major-version-mismatch")
    if missing_artifacts:
        issues.append("missing-file-proxy-artifacts")
    if unsafe_artifacts:
        issues.append("unsafe-file-proxy-artifacts")

    item: dict[str, Any] = {
        "module": module,
        "version": version,
        "source": "download",
        "status": "not-ready",
        "issues": issues,
        "file_proxy_complete": not missing_artifacts,
        "artifacts": artifacts,
        "missing_artifacts": missing_artifacts,
        "unsafe_artifacts": unsafe_artifacts,
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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], int]:
    """Verify selected MVS versions and retain every encountered graph edge."""

    proposed = {
        **{
            module: candidate["core_version"]
            for module in COMPANION_MODULES
        },
        OTELHTTP_MODULE: candidate["version"],
    }
    selected: dict[str, str] = {}
    selected_keys: dict[str, tuple[Any, ...]] = {}
    pending: set[tuple[str, str]] = set()
    verification: dict[tuple[str, str], dict[str, Any]] = {}
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
        identity = (module, version)
        if identity not in verification:
            pending.add(identity)
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

    for requirement in project_requirements:
        add_requirement(requirement["module"], requirement["version"])
    for module, version in proposed.items():
        add_requirement(module, version)

    while pending and not closure_issues:
        module, version = min(pending)
        pending.remove((module, version))
        if (module, version) in verification:
            continue
        steps += 1
        if steps > MAX_CLOSURE_STEPS:
            closure_issues.append(
                f"dependency-closure-step-limit:{MAX_CLOSURE_STEPS}"
            )
            break
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
        verification[(module, version)] = item
        # Go's MVS graph loader may need the go.mod for a lower version even
        # after a higher version is selected. Retain that exact metadata row,
        # but only expand requirements from the currently selected version;
        # recursively expanding every superseded graph would inventory the
        # whole cache rather than the candidate's bounded MVS closure.
        if selected.get(module) != version:
            continue
        if "mod" not in item["artifacts"] or item["requirement_parse_issues"]:
            continue
        for requirement in item["requirements"]:
            add_requirement(requirement["module"], requirement["version"])

    for module, expected_version in proposed.items():
        selected_version = selected.get(module)
        if selected_version == expected_version:
            continue
        item = verification.get((module, selected_version or expected_version))
        if item is not None:
            item["issues"].append("proposed-version-not-selected")
            item["status"] = "not-ready"
            item["proposed_version"] = expected_version
        issue = (
            f"proposed-version-not-selected:{module}@{expected_version}"
            f":selected={selected_version}"
        )
        closure_issues.append(issue)

    selected_rows = [
        verification[(module, version)]
        for module, version in sorted(selected.items())
        if (module, version) in verification
    ]
    selected_identities = set(selected.items())
    graph_metadata: list[dict[str, Any]] = []
    for identity in sorted(verification):
        if identity in selected_identities:
            continue
        row = verification[identity]
        artifacts = {
            suffix: row["artifacts"][suffix]
            for suffix in ("mod", "info")
            if suffix in row["artifacts"]
        }
        missing = [
            suffix for suffix in PROXY_ARTIFACT_SUFFIXES if suffix not in artifacts
        ]
        graph_metadata.append(
            {
                **row,
                "status": "not-ready",
                "file_proxy_complete": False,
                "artifacts": artifacts,
                "missing_artifacts": missing,
                "unsafe_artifacts": [
                    suffix
                    for suffix in row["unsafe_artifacts"]
                    if suffix in {"mod", "info"}
                ],
                "binding_scope": "graph-metadata",
            }
        )
    return selected_rows, graph_metadata, closure_issues, steps


def probe_artifact_bounds(
    verification: list[dict[str, Any]],
) -> tuple[int, int, bool]:
    """Return the bounded available-artifact inventory for one probe plan."""

    artifact_count = 0
    artifact_bytes = 0
    for row in verification:
        artifacts = row.get("artifacts")
        if not isinstance(artifacts, dict):
            return 0, 0, False
        artifact_count += len(artifacts)
        for artifact in artifacts.values():
            if not isinstance(artifact, dict):
                return 0, 0, False
            size = artifact.get("size_bytes")
            if type(size) is not int or size <= 0:
                return 0, 0, False
            artifact_bytes += size
    return (
        artifact_count,
        artifact_bytes,
        artifact_count <= MAX_PROBE_PROXY_FILES
        and artifact_bytes <= MAX_PROBE_PROXY_BYTES,
    )


def direct_bundle_ready(
    candidate: dict[str, Any], verification: list[dict[str, Any]]
) -> bool:
    """Require complete safe artifacts for every fixed direct OTel pin."""

    direct = {
        pin.rsplit("@", 1)[0]: pin.rsplit("@", 1)[1]
        for pin in candidate_modules(candidate)
    }
    rows = {
        (row.get("module"), row.get("version")): row
        for row in verification
        if isinstance(row, dict)
    }
    return all(
        (
            (row := rows.get((module, version))) is not None
            and row.get("status") == "ready"
            and row.get("file_proxy_complete") is True
            and row.get("missing_artifacts") == []
            and row.get("unsafe_artifacts") == []
        )
        for module, version in direct.items()
    )


def execution_env(
    project: Path,
    cache: Path,
    runtime: dict[str, Any] | None = None,
) -> dict[str, str]:
    local_cache = project / ".observe" / "tmp" / "go-otel-resolver"
    proxy = (cache / "cache" / "download").resolve().as_uri()
    environment = {
        # Disabling CGO removes inherited compiler/linker selection from the
        # dependency edit and its deterministic validation gate. Projects that
        # require CGO fail this gate explicitly instead of silently using an
        # unbound host compiler.
        "CGO_ENABLED": "0",
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
        "GOTELEMETRY": "off",
        "GOTOOLCHAIN": "local",
        "GOVCS": "*:off",
        "GOWORK": "off",
        "HOME": str(local_cache / "home"),
    }
    if runtime is not None:
        version = runtime.get("version")
        if not isinstance(version, str) or not version.startswith("go version "):
            raise ValueError("selected Go runtime version binding is invalid")
        platform = version.rsplit(" ", 1)[-1]
        if platform.count("/") != 1:
            raise ValueError("selected Go runtime platform binding is invalid")
        goos, goarch = platform.split("/", 1)
        if not goos or not goarch:
            raise ValueError("selected Go runtime platform binding is invalid")
        environment.update({"GOOS": goos, "GOARCH": goarch})
    return environment


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


def resolve(
    project_arg: Path,
    gomodcache_arg: Path | None,
    go_executable_arg: Path | None = None,
) -> dict[str, Any]:
    warnings = Warnings()
    project, go_mod_path = project_go_mod(project_arg)
    cache, cache_source = default_gomodcache(gomodcache_arg)
    runtime_error: str | None = None
    try:
        with tempfile.TemporaryDirectory(
            prefix="obstudio-go-runtime-fingerprint-",
            ignore_cleanup_errors=True,
        ) as runtime_directory:
            runtime_root = Path(runtime_directory)
            runtime_environment = execution_env(project, cache)
            runtime_environment.update(
                {
                    "GOCACHE": str(runtime_root / "gocache"),
                    "GOMODCACHE": str(runtime_root / "gomodcache"),
                    "GOPATH": str(runtime_root / "gopath"),
                    "GOTELEMETRYDIR": str(runtime_root / "telemetry"),
                    "HOME": str(runtime_root / "home"),
                }
            )
            runtime = go_runtime_fingerprint(
                go_executable_arg,
                cwd=project,
                environment=runtime_environment,
            )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        runtime = None
        runtime_error = str(error)
    result = base_result(project, go_mod_path, cache, cache_source, runtime)
    if runtime_error is not None:
        result["reasons"] = ["selected-go-runtime-unavailable"]
        warnings.add(runtime_error)
        return finish(result, warnings)

    if not go_mod_path.is_file():
        result["reasons"] = ["project-go-mod-missing"]
        warnings.add(f"project go.mod is missing: {go_mod_path}")
        return finish(result, warnings)

    project_text = read_go_mod(go_mod_path, warnings, "project go.mod")
    if project_text is None:
        result["reasons"] = ["project-go-mod-unreadable"]
        return finish(result, warnings)
    result["project"]["go_mod_sha256"] = hashlib.sha256(
        project_text.encode("utf-8")
    ).hexdigest()
    go_sum_path = project / "go.sum"
    if go_sum_path.is_file():
        try:
            go_sum_payload = go_sum_path.read_bytes()
        except OSError as error:
            warnings.add(f"project go.sum is unreadable: {error}")
            result["reasons"] = ["project-go-sum-unreadable"]
            return finish(result, warnings)
        result["project"]["go_sum"] = {
            "present": True,
            "sha256": hashlib.sha256(go_sum_payload).hexdigest(),
        }
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
    incompatible_project_requirements = [
        requirement
        for requirement in project_requirements
        if semver_key(requirement["version"]) is not None
        and not module_version_path_compatible(
            requirement["module"], requirement["version"]
        )
    ]
    if incompatible_project_requirements:
        project_reasons.append("project-requirement-path-major-mismatch")
    if project_reasons:
        result["reasons"] = project_reasons
        return finish(result, warnings)

    if not cache.is_dir():
        result["reasons"] = ["gomodcache-missing"]
        warnings.add(f"Go module cache is not a directory: {cache}")
        return finish(result, warnings)

    (
        sources,
        scan_failed,
        directories_truncated,
        entries_omitted_at_least,
    ) = discover_otelhttp_sources(cache, warnings)
    result["scan"]["cache_directories_truncated"] = directories_truncated
    result["scan"]["cache_entries_omitted_at_least"] = (
        entries_omitted_at_least
    )
    result["scan"]["otelhttp_versions_seen"] = len(sources)
    if scan_failed:
        result["status"] = "incomplete"
        result["reasons"] = ["otelhttp-cache-scan-failed"]
        return finish(result, warnings)

    compatible: list[dict[str, Any]] = []
    for version, version_sources in sources.items():
        version_key = semver_key(version)
        if version_key is None or not module_version_path_compatible(
            OTELHTTP_MODULE, version
        ):
            result["scan"]["unusable_versions"] += 1
            warnings.add(
                "ignored cached otelhttp version with invalid or "
                f"path-incompatible semver: {version}"
            )
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
            if (
                semver_key(core_version) is None
                or not module_version_path_compatible(
                    "go.opentelemetry.io/otel", core_version
                )
            ):
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
    bootstrap_verification: list[dict[str, Any]] = []
    bootstrap_graph_metadata: list[dict[str, Any]] = []
    bootstrap_artifact_count = 0
    bootstrap_artifact_bytes = 0
    selected_verification: list[dict[str, Any]] = []
    selected_graph_metadata: list[dict[str, Any]] = []
    selected_closure_steps = 0
    for candidate in sorted(
        compatible,
        key=lambda item: item["semver_key"],
        reverse=True,
    ):
        if bootstrap_candidate is None:
            (
                bootstrap_closure,
                bootstrap_metadata,
                bootstrap_issues,
                _,
            ) = verify_dependency_closure(
                cache,
                candidate,
                project_requirements,
                project_module,
                project_version_key,
                warnings,
            )
            artifact_count, artifact_bytes, artifacts_bounded = (
                probe_artifact_bounds(bootstrap_closure + bootstrap_metadata)
            )
            if (
                not bootstrap_issues
                and artifacts_bounded
                and direct_bundle_ready(candidate, bootstrap_closure)
                and all(
                    not item["unsafe_artifacts"]
                    for item in bootstrap_closure + bootstrap_metadata
                )
            ):
                bootstrap_candidate = candidate
                bootstrap_verification = bootstrap_closure
                bootstrap_graph_metadata = bootstrap_metadata
                bootstrap_artifact_count = artifact_count
                bootstrap_artifact_bytes = artifact_bytes
        result["scan"]["candidates_checked"] += 1
        (
            verification,
            graph_metadata,
            closure_issues,
            closure_steps,
        ) = verify_dependency_closure(
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
        graph_not_ready = [
            item
            for item in graph_metadata
            if "mod" not in item["artifacts"] or item["unsafe_artifacts"]
        ]
        if not not_ready and not graph_not_ready and not closure_issues:
            selected = candidate
            selected_verification = verification
            selected_graph_metadata = graph_metadata
            selected_closure_steps = closure_steps
            break

        result["scan"]["non_runnable_versions"] += 1
        if any(
            item["artifacts"] and item["missing_artifacts"]
            for item in not_ready + graph_not_ready
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
                for item in not_ready + graph_not_ready
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
                "import_closure_complete": False,
                "candidate_closure_inspected": True,
                "closure_modules": len(bootstrap_verification),
                "available_artifact_count": bootstrap_artifact_count,
                "available_artifact_bytes": bootstrap_artifact_bytes,
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
                "verification": bootstrap_verification,
                "graph_metadata": bootstrap_graph_metadata,
                "reasons": [
                    "full-project-closure-not-proven",
                    "fixed-direct-bundle-file-proxy-ready",
                    "candidate-closure-available-artifacts-bound",
                ],
            }
        else:
            result["bootstrap_probe"]["reasons"] = [
                "no-file-proxy-ready-import-closure"
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
    result["graph_metadata"] = selected_graph_metadata
    result["scan"]["closure_modules"] = len(selected_verification)
    result["scan"]["closure_steps"] = selected_closure_steps
    modules = candidate_modules(selected)
    ready = not scan_failed
    if ready:
        env = execution_env(project, cache, runtime)
        result["go_get"] = {
            "ready": True,
            "cwd": str(project),
            "env": env,
            "modules": modules,
            "argv": [runtime["path"], "get", *modules],
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
            "cleanup_argv": [
                runtime["path"],
                "clean",
                "-cache",
                "-modcache",
            ],
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


def compact_summary(
    result: dict[str, Any], output: Path, plan_sha256: str
) -> dict[str, Any]:
    """Return the bounded decision surface for a persisted full plan."""

    selection = result.get("selection")
    compact_selection = None
    if isinstance(selection, dict):
        compact_selection = {
            "otelhttp_version": selection.get("version"),
            "core_version": selection.get("core_version"),
        }

    bootstrap = result.get("bootstrap_probe")
    bootstrap_candidate = (
        bootstrap.get("candidate") if isinstance(bootstrap, dict) else None
    )
    compact_bootstrap = {
        "eligible": bool(
            isinstance(bootstrap, dict) and bootstrap.get("eligible") is True
        ),
        "otelhttp_version": (
            bootstrap_candidate.get("version")
            if isinstance(bootstrap_candidate, dict)
            else None
        ),
        "core_version": (
            bootstrap_candidate.get("core_version")
            if isinstance(bootstrap_candidate, dict)
            else None
        ),
    }

    go_get = result.get("go_get")
    go_get_ready = bool(
        isinstance(go_get, dict) and go_get.get("ready") is True
    )
    if result.get("complete") is True and go_get_ready:
        next_action = "go-get"
    elif compact_bootstrap["eligible"]:
        next_action = "probe-bootstrap"
    else:
        next_action = "stop"

    warnings = result.get("warnings")
    warning_count = len(warnings) if isinstance(warnings, list) else 0
    warnings_omitted = result.get("warnings_omitted")
    if type(warnings_omitted) is int:
        warning_count += warnings_omitted

    rejections = result.get("candidate_rejections")
    rejection_count = len(rejections) if isinstance(rejections, list) else 0
    rejections_omitted = result.get("candidate_rejections_omitted")
    if type(rejections_omitted) is int:
        rejection_count += rejections_omitted

    reasons = result.get("reasons")
    return {
        "schema_version": result.get("schema_version"),
        "status": result.get("status"),
        "complete": result.get("complete") is True,
        "next_action": next_action,
        "selection": compact_selection,
        "go_get_ready": go_get_ready,
        "bootstrap_probe": compact_bootstrap,
        "reasons": reasons if isinstance(reasons, list) else [],
        "warning_count": warning_count,
        "candidate_rejection_count": rejection_count,
        "plan_path": str(output),
        "plan_sha256": plan_sha256,
    }


def bounded_output_path(
    result: dict[str, Any], requested_project: Path, requested_output: Path
) -> tuple[Path, Path]:
    """Resolve an output path without following service-tree symlinks."""

    project_info = result.get("project")
    project_value = (
        project_info.get("path") if isinstance(project_info, dict) else None
    )
    if not isinstance(project_value, str):
        raise ValueError("resolver project root is unavailable")
    project = Path(project_value)
    if not project.is_absolute() or project.resolve() != project:
        raise ValueError("resolver project root is not canonical")

    project_input = requested_project.expanduser()
    if not project_input.is_absolute():
        project_input = Path.cwd() / project_input
    project_input = Path(os.path.abspath(project_input))
    if project_input.is_file():
        project_input = project_input.parent

    output_input = requested_output.expanduser()
    if not output_input.is_absolute():
        output_input = Path.cwd() / output_input
    output_input = Path(os.path.abspath(output_input))
    expected_input = project_input / PLAN_OUTPUT_PATH
    if output_input != expected_input:
        raise ValueError(
            "resolver plan output must be the fixed path "
            f"{expected_input}; runner-owned and alternate paths are reserved"
        )
    output = project / PLAN_OUTPUT_PATH
    return project, output


def status_is_link_or_reparse(status: os.stat_result) -> bool:
    reparse_mask = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(status, "st_file_attributes", 0)
    return stat.S_ISLNK(status.st_mode) or bool(attributes & reparse_mask)


def file_identity(status: os.stat_result) -> tuple[int, int]:
    return status.st_dev, status.st_ino


def descriptor_publication_supported() -> bool:
    required_dir_fd = {os.open, os.mkdir, os.rename, os.stat, os.unlink}
    return (
        os.name == "posix"
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and required_dir_fd.issubset(os.supports_dir_fd)
        and os.stat in os.supports_follow_symlinks
    )


def require_regular_target_portable(path: Path) -> None:
    if not os.path.lexists(path):
        return
    status = os.lstat(path)
    if status_is_link_or_reparse(status) or not stat.S_ISREG(status.st_mode):
        raise OSError(f"resolver plan output must be a regular file: {path}")


def ensure_portable_parent(project: Path, output: Path) -> None:
    """Create the fixed parent while rejecting links, reparses, and non-dirs."""

    current = project
    project_status = os.lstat(current)
    if status_is_link_or_reparse(project_status) or not stat.S_ISDIR(
        project_status.st_mode
    ):
        raise OSError(f"resolver project must be a regular directory: {project}")
    for part in output.parent.relative_to(project).parts:
        current = current / part
        try:
            os.mkdir(current, mode=0o755)
        except FileExistsError:
            pass
        status = os.lstat(current)
        if status_is_link_or_reparse(status) or not stat.S_ISDIR(status.st_mode):
            raise OSError(
                "resolver plan parent contains a link, reparse point, or "
                f"non-directory: {current}"
            )


def write_plan_descriptor(project: Path, output: Path, payload: bytes) -> None:
    """Write below the project with directory-relative, no-follow operations."""

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory_fd = os.open(project, directory_flags)
    temporary_name: str | None = None
    temporary_fd: int | None = None
    try:
        relative_parent = output.parent.relative_to(project)
        for part in relative_parent.parts:
            try:
                os.mkdir(part, mode=0o755, dir_fd=directory_fd)
            except FileExistsError:
                pass
            next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd

        try:
            target = os.stat(
                output.name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            target = None
        if target is not None and (
            status_is_link_or_reparse(target)
            or not stat.S_ISREG(target.st_mode)
        ):
            raise OSError(f"resolver plan output must be a regular file: {output}")

        temporary_name = f".go-otel-plan-{os.urandom(8).hex()}.tmp"
        temporary_fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        with os.fdopen(temporary_fd, "wb") as stream:
            temporary_fd = None
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

        temporary_status = os.stat(
            temporary_name, dir_fd=directory_fd, follow_symlinks=False
        )
        if status_is_link_or_reparse(temporary_status) or not stat.S_ISREG(
            temporary_status.st_mode
        ):
            raise OSError("resolver temporary plan is not a regular file")
        temporary_identity = file_identity(temporary_status)

        try:
            target = os.stat(
                output.name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            target = None
        if target is not None and (
            status_is_link_or_reparse(target)
            or not stat.S_ISREG(target.st_mode)
        ):
            raise OSError(f"resolver plan output must be a regular file: {output}")

        os.rename(
            temporary_name,
            output.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary_name = None
        published = os.stat(
            output.name, dir_fd=directory_fd, follow_symlinks=False
        )
        if (
            status_is_link_or_reparse(published)
            or not stat.S_ISREG(published.st_mode)
            or file_identity(published) != temporary_identity
        ):
            raise OSError("resolver plan identity changed during publication")
        os.fsync(directory_fd)
    finally:
        if temporary_fd is not None:
            os.close(temporary_fd)
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)


def write_plan_portable(project: Path, output: Path, payload: bytes) -> None:
    """Portable atomic publication with explicit namespace integrity checks."""

    ensure_portable_parent(project, output)
    require_regular_target_portable(output)
    temporary = output.with_name(f".{output.name}.{os.urandom(8).hex()}.tmp")
    if os.path.lexists(temporary):
        raise OSError(f"resolver temporary plan already exists: {temporary}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor: int | None = None
    temporary_identity: tuple[int, int] | None = None
    published = False
    try:
        descriptor = os.open(temporary, flags, 0o600)
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("resolver plan write made no progress")
            offset += written
        os.fsync(descriptor)
        temporary_identity = file_identity(os.fstat(descriptor))
        named_status = os.lstat(temporary)
        if (
            status_is_link_or_reparse(named_status)
            or not stat.S_ISREG(named_status.st_mode)
            or file_identity(named_status) != temporary_identity
        ):
            raise OSError("resolver temporary plan identity changed")
        ensure_portable_parent(project, output)
        require_regular_target_portable(output)
        os.replace(temporary, output)
        published = True
        ensure_portable_parent(project, output)
        published_status = os.lstat(output)
        if (
            status_is_link_or_reparse(published_status)
            or not stat.S_ISREG(published_status.st_mode)
            or file_identity(published_status) != temporary_identity
        ):
            raise OSError("resolver plan identity changed during publication")
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


def write_plan_atomically(project: Path, output: Path, payload: bytes) -> None:
    if descriptor_publication_supported():
        write_plan_descriptor(project, output, payload)
    else:
        write_plan_portable(project, output, payload)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve cache-backed OpenTelemetry Go dependency pins without "
            "executing a shell or editing project manifests."
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
    parser.add_argument(
        "--go-executable",
        type=Path,
        help=(
            "Project-selected Go executable to fingerprint and bind. Defaults "
            "to the current PATH selection for backward compatibility."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Write the complete deterministic plan to the fixed project path "
            ".observe/tmp/go-otel-version-plan.json and print a compact, "
            "digest-bound summary. "
            "Without this option, print the complete plan for backward "
            "compatibility."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = resolve(args.project, args.gomodcache, args.go_executable)
    full_plan = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(full_plan, end="")
        return 0

    full_plan_bytes = full_plan.encode("utf-8")
    try:
        project, output = bounded_output_path(result, args.project, args.output)
        write_plan_atomically(project, output, full_plan_bytes)
    except (OSError, ValueError) as error:
        print(f"could not write resolver plan: {error}", file=sys.stderr)
        return 2

    summary = compact_summary(
        result,
        output,
        hashlib.sha256(full_plan_bytes).hexdigest(),
    )
    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
