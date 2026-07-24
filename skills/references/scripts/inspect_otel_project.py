#!/usr/bin/env python3
"""Emit a bounded, deterministic inventory for OTel skill preflight.

The inventory contains candidates, not runtime or reachability proof. It is
shared by otel-audit, otel-instrument, and otel-verify so each workflow can
start from the same repository facts without repeating broad searches.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from secure_output import (
    SecureOutputError,
    authenticate_directory,
    descriptor_operations_supported,
    path_is_link_or_reparse,
    require_same_directory,
    write_text,
)


SCHEMA_VERSION = 1
MAX_FILE_BYTES = 2_000_000
DEFAULT_MAX_ITEMS = 80
DEFAULT_MAX_FILES = 5_000
DEFAULT_MAX_TOTAL_BYTES = 50_000_000
DEFAULT_MAX_ENTRIES = 100_000
DEFAULT_MAX_DEPTH = 64
MAX_WARNINGS = 50

SKIP_COUNT_KEYS = (
    "configured_directories",
    "symlink_directories",
    "symlink_files",
    "oversized_files",
    "stat_errors",
    "read_errors",
    "walk_errors",
    "file_limit",
    "byte_limit",
    "entry_limit",
    "depth_limit",
    "warnings_omitted",
)

SKIP_DIRS = {
    ".agents",
    ".cache",
    ".codex",
    ".git",
    ".gradle",
    ".hg",
    ".idea",
    ".mypy_cache",
    ".next",
    ".nuxt",
    ".observe",
    ".pip-cache",
    ".pytest_cache",
    ".release",
    ".ruff_cache",
    ".svn",
    ".terraform",
    ".tox",
    ".uv-cache",
    ".venv",
    ".vscode-test",
    ".workspace",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "site-packages",
    "target",
    "vendor",
}

TEXT_NAMES = {
    "Cargo.lock",
    "Cargo.toml",
    "Dockerfile",
    "Gemfile",
    "Gemfile.lock",
    "Makefile",
    "Procfile",
    "Taskfile.yml",
    "build.gradle",
    "build.gradle.kts",
    "build.sbt",
    "compose.yaml",
    "compose.yml",
    "composer.json",
    "composer.lock",
    "docker-compose.yaml",
    "docker-compose.yml",
    "go.mod",
    "go.sum",
    "global.json",
    "gradlew",
    "justfile",
    "mvnw",
    "package-lock.json",
    "package.json",
    "pnpm-lock.yaml",
    "pom.xml",
    "poetry.lock",
    "pyproject.toml",
    "requirements.txt",
    "rust-toolchain",
    "rust-toolchain.toml",
    "setup.py",
    "settings.gradle",
    "settings.gradle.kts",
    "uv.lock",
    "yarn.lock",
}

TEXT_SUFFIXES = {
    ".bash",
    ".cjs",
    ".cs",
    ".csproj",
    ".env",
    ".go",
    ".gradle",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".kts",
    ".md",
    ".mjs",
    ".php",
    ".properties",
    ".py",
    ".rb",
    ".rs",
    ".scala",
    ".sh",
    ".sln",
    ".toml",
    ".ts",
    ".tsx",
    ".xml",
    ".yaml",
    ".yml",
    ".zsh",
}

MANIFEST_KINDS = {
    "Cargo.toml": ("rust", "cargo"),
    "Gemfile": ("ruby", "bundler"),
    "build.gradle": ("java", "gradle"),
    "build.gradle.kts": ("java", "gradle"),
    "composer.json": ("php", "composer"),
    "go.mod": ("go", "go-module"),
    "package.json": ("node", "node-package"),
    "pom.xml": ("java", "maven"),
    "pyproject.toml": ("python", "python-project"),
    "requirements.txt": ("python", "python-requirements"),
    "setup.py": ("python", "python-setup"),
}

LOCKFILE_NAMES = {
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
    "go.sum",
    "package-lock.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "yarn.lock",
}

VERSION_FILE_NAMES = {
    ".java-version",
    ".node-version",
    ".nvmrc",
    ".python-version",
    ".ruby-version",
    ".sdkmanrc",
    ".tool-versions",
    "global.json",
    "mise.toml",
    "rust-toolchain",
    "rust-toolchain.toml",
}

STARTUP_NAMES = {
    ".vscode/launch.json",
    "Dockerfile",
    "Makefile",
    "Procfile",
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
    "launch.json",
    "package.json",
}

ENTRYPOINT_NAMES = {
    "app.go",
    "app.js",
    "app.py",
    "app.ts",
    "index.js",
    "index.ts",
    "main.go",
    "main.js",
    "main.py",
    "main.ts",
    "manage.py",
    "server.js",
    "server.py",
    "server.ts",
    "worker.js",
    "worker.py",
    "worker.ts",
}

MAIN_SYMBOLS = {
    ".go": re.compile(r"^\s*func\s+main\s*\(", re.MULTILINE),
    ".java": re.compile(r"\bpublic\s+static\s+void\s+main\s*\("),
    ".kt": re.compile(r"^\s*fun\s+main\s*\(", re.MULTILINE),
    ".kts": re.compile(r"^\s*fun\s+main\s*\(", re.MULTILINE),
    ".py": re.compile(r"if\s+__name__\s*==\s*['\"]__main__['\"]"),
    ".rs": re.compile(r"^\s*fn\s+main\s*\(", re.MULTILINE),
}

OTEL_PATTERNS = {
    "dependency_or_import": re.compile(
        r"(?:@opentelemetry/|go\.opentelemetry\.io|io\.opentelemetry|"
        r"opentelemetry(?:[-_.]|\b)|splunk[_-]otel)",
        re.IGNORECASE,
    ),
    "provider_construction": re.compile(
        r"\b(?:TracerProvider|MeterProvider|LoggerProvider|"
        r"SdkTracerProvider|SdkMeterProvider|SdkLoggerProvider|"
        r"NewTracerProvider|NewMeterProvider|NewLoggerProvider|"
        r"NodeSDK|WebTracerProvider|NoOp\w*Provider)\b"
    ),
    "provider_registration": re.compile(
        r"\b(?:set_(?:tracer|meter|logger)_provider|"
        r"SetTracerProvider|SetMeterProvider|SetLoggerProvider|"
        r"setGlobalTracerProvider|setGlobalMeterProvider|registerInstrumentations)\s*\("
    ),
    "exporter": re.compile(
        r"\b(?:OTLP\w*Exporter|Otlp\w*Exporter|Console\w*Exporter|"
        r"File\w*Exporter|otlptrace|otlpmetric|otlplog|"
        r"otlp(?:trace|metric|log)(?:http|grpc)\.New)\b",
        re.IGNORECASE,
    ),
    "automatic_bootstrap": re.compile(
        r"\b(?:opentelemetry-instrument|javaagent|splunk_otel|"
        r"init_splunk_otel|registerInstrumentations|otelhttp\.NewHandler)\b"
    ),
    "custom_span": re.compile(
        r"\b(?:start_as_current_span|startActiveSpan|startSpan|"
        r"tracer\.Start|Span\.current|@WithSpan)\b"
    ),
    "metric_instrument": re.compile(
        r"\b(?:create_(?:counter|histogram|observable_gauge|up_down_counter)|"
        r"create(?:Counter|Histogram|ObservableGauge|UpDownCounter)|"
        r"(?:Int64|Float64)(?:Counter|Histogram|ObservableGauge|UpDownCounter))\b"
    ),
    "log_bridge": re.compile(
        r"\b(?:LoggingInstrumentor|OpenTelemetryHandler|OTLPLogExporter|"
        r"LoggerProvider|instrumentation-(?:logging|winston|pino)|"
        r"OpenTelemetryAppender)\b",
        re.IGNORECASE,
    ),
    "resource": re.compile(
        r"\b(?:Resource\.(?:create|get_empty|GetDefault)|Resource\s*\(|resource\.New|"
        r"service\.name|service\.version|deployment\.environment\.name)\b"
    ),
    "runtime_configuration": re.compile(r"\bOTEL_[A-Z0-9_]+\b"),
    "shutdown_flush": re.compile(
        r"\b(?:force_flush|ForceFlush|shutdown|Shutdown)\s*\("
    ),
}

METHOD_ROUTE = re.compile(
    r"\b(?P<receiver>app|api|engine|router|route|routes|r|mux|server|e|group|v\d+)\."
    r"(?P<method>get|post|put|delete|patch|options|head)\s*\(\s*"
    r"[rubfRUBF]*(?P<quote>['\"`])(?P<route>[^'\"`]+)(?P=quote)",
    re.IGNORECASE,
)

SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(?P<prefix>\b(?:authorization|credentials?|headers?|password|passwd|"
    r"secret|token|api[_-]?(?:key|token)|auth[_-]?token|access[_-]?token|"
    r"refresh[_-]?token|client[_-]?secret)\b\s*[:=]\s*)"
    r"(?P<value>[^,\s}\]]+)"
)
ASSIGNMENT_KEY = re.compile(
    r"(?P<quote>['\"]?)(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)(?P=quote)\s*[:=]"
)
SENSITIVE_KEY_SUFFIXES = (
    "authorization",
    "authorization_code",
    "auth_code",
    "auth_token",
    "credential",
    "credentials",
    "header",
    "headers",
    "password",
    "passwd",
    "secret",
    "secret_key",
    "private_key",
    "secret_access_key",
    "token",
    "api_key",
    "api_token",
    "access_token",
    "refresh_token",
    "client_secret",
)
URL_USERINFO = re.compile(
    r"(?i)(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)[^/@\s]+@"
)
CURL_USERINFO = re.compile(
    r"(?i)(?P<prefix>(?:^|\s)(?:-u\s*|--user(?:\s+|=)))"
    r"(?P<quote>['\"]?)[^:\s'\"]+:[^\s'\"]+(?P=quote)"
)
CURL_COMMAND = re.compile(r"(?i)\bcurl(?:\.exe)?\b")
CURL_COOKIE_VALUE = re.compile(
    r"(?i)(?P<prefix>(?:^|\s)(?:--cookie(?:\s+|=)|-b(?:\s+|=)?))"
    r"(?P<value>'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|[^\s,}\]]+)"
)
CURL_COOKIE_HEADER = re.compile(
    r"(?i)(?P<prefix>(?:^|\s)(?:-H|--header)(?:\s+|=)"
    r"(?:set-cookie|cookie)\s*:\s*)"
    r"(?P<value>[^\s,}\]]+)"
)
QUOTED_COOKIE_HEADER = re.compile(
    r"(?i)(?P<prefix>(?P<quote>['\"])(?:set-cookie|cookie)\s*:\s*)"
    r"(?P<value>(?:\\.|(?!(?P=quote)).)*?)(?P=quote)"
)
QUOTED_COOKIE_HEADER_VALUE = re.compile(
    r"(?i)(?P<prefix>\b(?:set-cookie|cookie)['\"]?\s*:\s*)"
    r"(?P<quote>['\"])(?P<value>(?:\\.|(?!(?P=quote)).)*?)(?P=quote)"
)
COOKIE_HEADER_LINE = re.compile(
    r"(?i)(?P<prefix>^\s*(?:set-cookie|cookie)\s*:\s*)(?P<value>.*)$"
)
CLI_OPTION_EQUALS_VALUE = re.compile(
    r"(?P<prefix>(?:^|\s)--?(?P<key>[A-Za-z][A-Za-z0-9_-]*)=)"
    r"(?P<value>'[^']*'|\"[^\"]*\"|[^\s,}\]]+)"
)
CLI_OPTION_SPACE_VALUE = re.compile(
    r"(?P<prefix>(?:^|\s)--?(?P<key>[A-Za-z][A-Za-z0-9_-]*)\s+)"
    r"(?P<value>'[^']*'|\"[^\"]*\"|(?!-)[^\s,}\]]+)"
)
BEARER_VALUE = re.compile(
    r"(?i)(?P<prefix>\bbearer\s+)[^,\s}\]'\"<>]+"
)
URL_QUERY_VALUE = re.compile(
    r"(?P<prefix>[?&])(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)"
    r"(?P<equals>=)(?P<value>[^&#\s'\"<>]+)"
)
KNOWN_CREDENTIAL_VALUE = re.compile(
    r"\b(?:"
    r"gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"sk-[A-Za-z0-9_-]{20,}|"
    r"AKIA[0-9A-Z]{16}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"
    r")\b"
)
ENV_ASSIGNMENT = re.compile(r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=")
DECORATOR_ROUTE = re.compile(
    r"@(?:[A-Za-z_][A-Za-z0-9_]*\.)?"
    r"(?P<method>get|post|put|delete|patch|options|head)(?:Mapping)?\s*\(\s*"
    r"(?:value\s*=\s*|path\s*=\s*)?"
    r"(?P<quote>['\"])(?P<route>[^'\"]+)(?P=quote)",
    re.IGNORECASE,
)
GENERIC_ROUTE = re.compile(
    r"\b(?:Handle|HandleFunc|route|Route|RequestMapping)\s*\(\s*"
    r"(?:value\s*=\s*|path\s*=\s*)?"
    r"(?P<quote>['\"])(?P<route>[^'\"]+)(?P=quote)"
)


def is_supported_text(path: Path) -> bool:
    is_env = path.name == ".env" or path.name.startswith(".env.")
    is_requirements = (
        path.name.lower().startswith("requirements")
        and path.suffix.lower() == ".txt"
    )
    return (
        path.name in TEXT_NAMES
        or path.name in LOCKFILE_NAMES
        or path.name in VERSION_FILE_NAMES
        or is_env
        or is_requirements
        or path.suffix.lower() in TEXT_SUFFIXES
    )


@dataclass
class ScanInput:
    files: list[Path] = field(default_factory=list)
    lines: dict[Path, tuple[str, ...]] = field(default_factory=dict)
    bytes_scanned: int = 0
    complete: bool = True
    warnings: list[str] = field(default_factory=list)
    skipped: dict[str, int] = field(
        default_factory=lambda: {key: 0 for key in SKIP_COUNT_KEYS}
    )

    def warn(self, message: str) -> None:
        self.complete = False
        if len(self.warnings) < MAX_WARNINGS:
            self.warnings.append(message)
        else:
            self.skipped["warnings_omitted"] += 1


@dataclass
class TraversalBudget:
    max_entries: int
    max_depth: int
    entries_seen: int = 0


def bounded_directory_names(
    directory: int | Path, budget: TraversalBudget
) -> tuple[list[str], bool]:
    """Read a deterministic directory only when its entries fit the budget.

    One extra entry is enough to prove truncation. In that case the partial,
    filesystem-ordered prefix is discarded so results never depend on native
    directory enumeration order.
    """

    remaining = max(0, budget.max_entries - budget.entries_seen)
    names: list[str] = []
    with os.scandir(directory) as entries:
        for entry in entries:
            names.append(entry.name)
            if len(names) > remaining:
                return [], True
    budget.entries_seen += len(names)
    return sorted(names), False


def relative_label(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def collect_scan_input(
    root: Path,
    *,
    max_files: int,
    max_total_bytes: int,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    root_descriptor: int | None = None,
) -> ScanInput:
    if descriptor_operations_supported() and os.scandir in os.supports_fd:
        return collect_scan_input_descriptor(
            root,
            max_files=max_files,
            max_total_bytes=max_total_bytes,
            max_entries=max_entries,
            max_depth=max_depth,
            root_descriptor=root_descriptor,
        )
    return collect_scan_input_portable(
        root,
        max_files=max_files,
        max_total_bytes=max_total_bytes,
        max_entries=max_entries,
        max_depth=max_depth,
    )


def descriptor_identity(status: os.stat_result) -> tuple[int, int]:
    return status.st_dev, status.st_ino


def read_descriptor_payload(descriptor: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while total <= maximum:
        chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def collect_scan_input_descriptor(
    root: Path,
    *,
    max_files: int,
    max_total_bytes: int,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    root_descriptor: int | None = None,
) -> ScanInput:
    """Scan through retained directory descriptors without following links."""

    scan = ScanInput()
    budget = TraversalBudget(max_entries=max_entries, max_depth=max_depth)
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = (
        os.dup(root_descriptor)
        if root_descriptor is not None
        else os.open(root, directory_flags)
    )

    def visit(
        directory_descriptor: int, relative: Path, depth: int
    ) -> bool:
        try:
            names, entry_limit_reached = bounded_directory_names(
                directory_descriptor, budget
            )
        except OSError as error:
            scan.skipped["walk_errors"] += 1
            scan.warn(
                f"directory walk failed at {relative.as_posix() or '.'}: {error}"
            )
            return False

        if entry_limit_reached:
            scan.skipped["entry_limit"] += 1
            scan.warn(
                f"stopped after {max_entries} directory entries; "
                "additional entries were not inspected"
            )
            return True

        directories: list[tuple[str, os.stat_result]] = []
        files: list[tuple[str, os.stat_result]] = []
        for name in names:
            try:
                details = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except OSError as error:
                scan.skipped["stat_errors"] += 1
                scan.warn(
                    f"could not stat {(relative / name).as_posix()}: {error}"
                )
                continue
            if stat.S_ISDIR(details.st_mode):
                directories.append((name, details))
            else:
                files.append((name, details))

        for name, details in files:
            relative_path = relative / name
            path = root / relative_path
            if not is_supported_text(path):
                continue
            if path_is_link_or_reparse(details):
                scan.skipped["symlink_files"] += 1
                scan.warn(f"skipped symlink file: {relative_path.as_posix()}")
                continue
            if len(scan.files) >= max_files:
                scan.skipped["file_limit"] += 1
                scan.warn(
                    f"stopped after {max_files} text files; additional files were not scanned"
                )
                return True
            if not stat.S_ISREG(details.st_mode):
                scan.skipped["read_errors"] += 1
                scan.warn(
                    f"skipped non-regular file: {relative_path.as_posix()}"
                )
                continue
            if details.st_size > MAX_FILE_BYTES:
                scan.skipped["oversized_files"] += 1
                scan.warn(
                    f"skipped oversized file {relative_path.as_posix()} "
                    f"({details.st_size} bytes; limit {MAX_FILE_BYTES})"
                )
                continue
            if scan.bytes_scanned + details.st_size > max_total_bytes:
                scan.skipped["byte_limit"] += 1
                scan.warn(
                    f"stopped before {relative_path.as_posix()} because the "
                    f"{max_total_bytes}-byte scan limit was reached"
                )
                return True

            file_descriptor: int | None = None
            try:
                file_descriptor = os.open(
                    name, file_flags, dir_fd=directory_descriptor
                )
                opened = os.fstat(file_descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or descriptor_identity(opened) != descriptor_identity(details)
                ):
                    raise OSError("file entry changed before it was opened")
                remaining = min(
                    MAX_FILE_BYTES,
                    max_total_bytes - scan.bytes_scanned,
                )
                payload = read_descriptor_payload(file_descriptor, remaining)
                if len(payload) > MAX_FILE_BYTES:
                    scan.skipped["oversized_files"] += 1
                    scan.warn(
                        f"skipped oversized file {relative_path.as_posix()} "
                        f"(grew beyond limit {MAX_FILE_BYTES})"
                    )
                    continue
                if scan.bytes_scanned + len(payload) > max_total_bytes:
                    scan.skipped["byte_limit"] += 1
                    scan.warn(
                        f"stopped before {relative_path.as_posix()} because the "
                        f"{max_total_bytes}-byte scan limit was reached"
                    )
                    return True
            except OSError as error:
                scan.skipped["read_errors"] += 1
                scan.warn(
                    f"could not read {relative_path.as_posix()}: {error}"
                )
                continue
            finally:
                if file_descriptor is not None:
                    os.close(file_descriptor)
            scan.files.append(path)
            scan.lines[path] = tuple(
                payload.decode("utf-8", errors="replace").splitlines()
            )
            scan.bytes_scanned += len(payload)

        for name, details in directories:
            path = root / relative / name
            label = (relative / name).as_posix()
            if name in SKIP_DIRS:
                scan.skipped["configured_directories"] += 1
                continue
            if path_is_link_or_reparse(details):
                scan.skipped["symlink_directories"] += 1
                scan.warn(f"skipped symlink directory: {label}")
                continue
            if depth >= budget.max_depth:
                scan.skipped["depth_limit"] += 1
                scan.warn(
                    f"skipped directory beyond depth {max_depth}: {label}"
                )
                continue
            child: int | None = None
            try:
                child = os.open(name, directory_flags, dir_fd=directory_descriptor)
                opened = os.fstat(child)
                if (
                    not stat.S_ISDIR(opened.st_mode)
                    or descriptor_identity(opened) != descriptor_identity(details)
                ):
                    raise OSError("directory entry changed before it was opened")
                if visit(child, relative / name, depth + 1):
                    return True
            except OSError as error:
                scan.skipped["walk_errors"] += 1
                scan.warn(f"directory changed or became unsafe: {label}: {error}")
            finally:
                if child is not None:
                    os.close(child)
        return False

    try:
        root_status = os.fstat(descriptor)
        if not stat.S_ISDIR(root_status.st_mode):
            raise SecureOutputError(f"project root is not a directory: {root}")
        visit(descriptor, Path(), 0)
    finally:
        os.close(descriptor)
    return scan


def portable_directory_chain(
    root: Path, parent: Path
) -> list[tuple[Path, tuple[int, int]]]:
    try:
        relative = parent.relative_to(root)
    except ValueError as error:
        raise OSError(f"scan path escapes project root: {parent}") from error
    result: list[tuple[Path, tuple[int, int]]] = []
    current = root
    for component in (None, *relative.parts):
        if component is not None:
            current = current / component
        details = os.lstat(current)
        if path_is_link_or_reparse(details) or not stat.S_ISDIR(details.st_mode):
            raise OSError(f"directory component is a link or reparse point: {current}")
        result.append((current, descriptor_identity(details)))
    return result


def portable_chain_matches(
    identities: list[tuple[Path, tuple[int, int]]]
) -> bool:
    for path, expected in identities:
        try:
            details = os.lstat(path)
        except OSError:
            return False
        if (
            path_is_link_or_reparse(details)
            or not stat.S_ISDIR(details.st_mode)
            or descriptor_identity(details) != expected
        ):
            return False
    return True


def portable_read_payload(
    root: Path,
    path: Path,
    expected: os.stat_result,
    maximum: int,
) -> bytes:
    """Best-effort no-follow read for platforms without dir_fd support.

    Reparse and identity checks fail closed around the read. Python cannot
    eliminate the narrow path check/use window on Windows, but mismatched
    bytes are never retained after a detected namespace change.
    """

    identities = portable_directory_chain(root, path.parent)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        current = os.lstat(path)
        if (
            not stat.S_ISREG(opened.st_mode)
            or path_is_link_or_reparse(current)
            or descriptor_identity(opened) != descriptor_identity(expected)
            or descriptor_identity(current) != descriptor_identity(opened)
            or not portable_chain_matches(identities)
        ):
            raise OSError("file or parent namespace changed before portable read")
        payload = read_descriptor_payload(descriptor, maximum)
        current = os.lstat(path)
        if (
            path_is_link_or_reparse(current)
            or descriptor_identity(current) != descriptor_identity(opened)
            or not portable_chain_matches(identities)
        ):
            raise OSError("file or parent namespace changed during portable read")
        return payload
    finally:
        os.close(descriptor)


def collect_scan_input_portable(
    root: Path,
    *,
    max_files: int,
    max_total_bytes: int,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> ScanInput:
    scan = ScanInput()
    budget = TraversalBudget(max_entries=max_entries, max_depth=max_depth)

    def visit(
        current_path: Path,
        relative: Path,
        depth: int,
        expected: os.stat_result | None,
    ) -> bool:
        try:
            identities = portable_directory_chain(root, current_path)
            if (
                expected is not None
                and identities[-1][1] != descriptor_identity(expected)
            ):
                raise OSError("directory entry changed before portable walk")
            names, entry_limit_reached = bounded_directory_names(
                current_path, budget
            )
            if not portable_chain_matches(identities):
                raise OSError("directory namespace changed during portable walk")
        except OSError as error:
            scan.skipped["walk_errors"] += 1
            scan.warn(
                f"directory walk failed at {relative.as_posix() or '.'}: {error}"
            )
            return False

        if entry_limit_reached:
            scan.skipped["entry_limit"] += 1
            scan.warn(
                f"stopped after {max_entries} directory entries; "
                "additional entries were not inspected"
            )
            return True

        directories: list[tuple[str, os.stat_result]] = []
        files: list[tuple[str, os.stat_result]] = []
        for name in names:
            path = current_path / name
            try:
                details = os.lstat(path)
            except OSError as error:
                scan.skipped["stat_errors"] += 1
                scan.warn(
                    f"could not stat {relative_label(root, path)}: {error}"
                )
                continue
            if stat.S_ISDIR(details.st_mode):
                directories.append((name, details))
            else:
                files.append((name, details))

        for name, details in files:
            relative_path = relative / name
            path = current_path / name
            if not is_supported_text(path):
                continue
            if path_is_link_or_reparse(details):
                scan.skipped["symlink_files"] += 1
                scan.warn(f"skipped symlink file: {relative_path.as_posix()}")
                continue
            if len(scan.files) >= max_files:
                scan.skipped["file_limit"] += 1
                scan.warn(
                    f"stopped after {max_files} text files; additional files were not scanned"
                )
                return True
            if not stat.S_ISREG(details.st_mode):
                scan.skipped["read_errors"] += 1
                scan.warn(
                    f"skipped non-regular file: {relative_path.as_posix()}"
                )
                continue
            size = details.st_size
            if size > MAX_FILE_BYTES:
                scan.skipped["oversized_files"] += 1
                scan.warn(
                    f"skipped oversized file {relative_path.as_posix()} "
                    f"({size} bytes; limit {MAX_FILE_BYTES})"
                )
                continue
            if scan.bytes_scanned + size > max_total_bytes:
                scan.skipped["byte_limit"] += 1
                scan.warn(
                    f"stopped before {relative_path.as_posix()} because the "
                    f"{max_total_bytes}-byte scan limit was reached"
                )
                return True
            try:
                payload = portable_read_payload(
                    root,
                    path,
                    details,
                    min(MAX_FILE_BYTES, max_total_bytes - scan.bytes_scanned),
                )
            except OSError as error:
                scan.skipped["read_errors"] += 1
                scan.warn(
                    f"could not read {relative_path.as_posix()}: {error}"
                )
                continue
            if len(payload) > MAX_FILE_BYTES:
                scan.skipped["oversized_files"] += 1
                scan.warn(
                    f"skipped oversized file {relative_path.as_posix()} "
                    f"(grew beyond limit {MAX_FILE_BYTES})"
                )
                continue
            if scan.bytes_scanned + len(payload) > max_total_bytes:
                scan.skipped["byte_limit"] += 1
                scan.warn(
                    f"stopped before {relative_path.as_posix()} because the "
                    f"{max_total_bytes}-byte scan limit was reached"
                )
                return True
            scan.files.append(path)
            scan.lines[path] = tuple(
                payload.decode("utf-8", errors="replace").splitlines()
            )
            scan.bytes_scanned += len(payload)

        for name, details in directories:
            path = current_path / name
            label = (relative / name).as_posix()
            if name in SKIP_DIRS:
                scan.skipped["configured_directories"] += 1
                continue
            if path_is_link_or_reparse(details):
                scan.skipped["symlink_directories"] += 1
                scan.warn(f"skipped symlink directory: {label}")
                continue
            if depth >= budget.max_depth:
                scan.skipped["depth_limit"] += 1
                scan.warn(
                    f"skipped directory beyond depth {max_depth}: {label}"
                )
                continue
            if visit(path, relative / name, depth + 1, details):
                return True
        return False

    visit(root, Path(), 0, None)

    return scan


def file_role(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    lowered_parts = {part.lower() for part in relative.parts}
    name = path.name.lower()
    if relative.parts and relative.parts[0].lower() in {"eval", "evals"}:
        return "eval"
    if path.name in LOCKFILE_NAMES:
        return "lockfile"
    if path.name in MANIFEST_KINDS or path.suffix.lower() in {".csproj", ".sln"}:
        return "manifest"
    if path.suffix.lower() == ".md":
        return "documentation"
    if (
        "test" in lowered_parts
        or "tests" in lowered_parts
        or name.startswith("test_")
        or name.endswith("_test.go")
        or ".test." in name
        or ".spec." in name
        or name.endswith("test.java")
    ):
        return "test"
    if path.suffix.lower() in {".go", ".java", ".js", ".jsx", ".kt", ".php", ".py", ".rb", ".rs", ".ts", ".tsx"}:
        return "source"
    return "config"


def normalize_key_name(key: str) -> str:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    return re.sub(r"[-.]+", "_", separated).lower()


def is_sensitive_key_name(key: str) -> bool:
    normalized = normalize_key_name(key)
    return any(
        normalized == suffix or normalized.endswith(f"_{suffix}")
        for suffix in SENSITIVE_KEY_SUFFIXES
    )


def has_sensitive_assignment_key(text: str) -> bool:
    return any(
        is_sensitive_key_name(match.group("key"))
        for match in ASSIGNMENT_KEY.finditer(text)
    )


def redact_sensitive_cli_values(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        if not is_sensitive_key_name(match.group("key")):
            return match.group(0)
        return f"{match.group('prefix')}<redacted>"

    redacted = CLI_OPTION_EQUALS_VALUE.sub(replace, text)
    return CLI_OPTION_SPACE_VALUE.sub(replace, redacted)


def redact_sensitive_query_values(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        normalized = normalize_key_name(match.group("key"))
        if not (
            is_sensitive_key_name(match.group("key"))
            or normalized in {"auth", "code", "key", "sig", "signature"}
            or normalized.endswith(("_sig", "_signature"))
        ):
            return match.group(0)
        return (
            f"{match.group('prefix')}{match.group('key')}"
            f"{match.group('equals')}<redacted>"
        )

    return URL_QUERY_VALUE.sub(replace, text)


def redact_cookie_values(text: str) -> str:
    redacted = QUOTED_COOKIE_HEADER.sub(
        r"\g<prefix><redacted>\g<quote>",
        text,
    )
    redacted = QUOTED_COOKIE_HEADER_VALUE.sub(
        r"\g<prefix>\g<quote><redacted>\g<quote>",
        redacted,
    )
    redacted = COOKIE_HEADER_LINE.sub(r"\g<prefix><redacted>", redacted)
    if CURL_COMMAND.search(redacted):
        redacted = CURL_COOKIE_HEADER.sub(r"\g<prefix><redacted>", redacted)
        redacted = CURL_COOKIE_VALUE.sub(r"\g<prefix><redacted>", redacted)
    return redacted


def redact_line(path: Path, text: str) -> str:
    stripped = text.strip()
    if path.name == ".env" or path.name.startswith(".env."):
        match = ENV_ASSIGNMENT.match(stripped)
        return f"{match.group('key')}=<redacted>" if match else "<redacted env line>"
    if has_sensitive_assignment_key(stripped):
        return "<redacted sensitive configuration>"
    redacted = URL_USERINFO.sub(r"\g<scheme><redacted>@", stripped)
    redacted = CURL_USERINFO.sub(
        r"\g<prefix>\g<quote><redacted>\g<quote>",
        redacted,
    )
    redacted = redact_cookie_values(redacted)
    redacted = redact_sensitive_cli_values(redacted)
    redacted = redact_sensitive_query_values(redacted)
    redacted = BEARER_VALUE.sub(r"\g<prefix><redacted>", redacted)
    redacted = SENSITIVE_ASSIGNMENT.sub(r"\g<prefix><redacted>", redacted)
    return KNOWN_CREDENTIAL_VALUE.sub("<redacted>", redacted)[:240]


def redact_route(route: str) -> str:
    redacted = redact_sensitive_query_values(route)
    redacted = SENSITIVE_ASSIGNMENT.sub(r"\g<prefix><redacted>", redacted)
    redacted = KNOWN_CREDENTIAL_VALUE.sub("<redacted>", redacted)
    return redacted[:240]


def finding(root: Path, path: Path, line: int, text: str) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "line": line,
        "role": file_role(root, path),
        "text": redact_line(path, text),
    }


def append_bounded(items: list[dict[str, object]], item: dict[str, object], maximum: int) -> None:
    if len(items) < maximum:
        items.append(item)


def detect_manifests(root: Path, files: list[Path]) -> tuple[list[dict[str, str]], list[str]]:
    manifests = []
    lockfiles = []
    for path in files:
        if file_role(root, path) == "eval":
            continue
        relative = path.relative_to(root).as_posix()
        if path.name in MANIFEST_KINDS:
            language, kind = MANIFEST_KINDS[path.name]
            manifests.append({"path": relative, "language": language, "kind": kind})
        elif path.suffix.lower() in {".csproj", ".sln"}:
            manifests.append({"path": relative, "language": "dotnet", "kind": "dotnet-project"})
        elif (
            path.name.lower().startswith("requirements")
            and path.suffix.lower() == ".txt"
        ):
            manifests.append({"path": relative, "language": "python", "kind": "python-requirements"})
        if path.name in LOCKFILE_NAMES:
            lockfiles.append(relative)
    return manifests, sorted(lockfiles)


def detect_languages(root: Path, files: list[Path], manifests: list[dict[str, str]]) -> list[dict[str, object]]:
    evidence: dict[str, list[str]] = {}
    for manifest in manifests:
        evidence.setdefault(manifest["language"], []).append(manifest["path"])

    suffix_languages = {
        ".cs": "dotnet",
        ".go": "go",
        ".java": "java",
        ".js": "node",
        ".jsx": "node",
        ".kt": "java",
        ".kts": "java",
        ".php": "php",
        ".py": "python",
        ".rb": "ruby",
        ".rs": "rust",
        ".ts": "node",
        ".tsx": "node",
    }
    for path in files:
        if file_role(root, path) == "eval":
            continue
        language = suffix_languages.get(path.suffix.lower())
        if language:
            relative = path.relative_to(root).as_posix()
            candidates = evidence.setdefault(language, [])
            if relative not in candidates and len(candidates) < 5:
                candidates.append(relative)

    return [
        {"name": language, "evidence": sorted(paths)}
        for language, paths in sorted(evidence.items())
    ]


def detect_entrypoints(
    root: Path,
    files: list[Path],
    lines_by_path: dict[Path, tuple[str, ...]],
    maximum: int,
) -> tuple[list[dict[str, object]], int]:
    entries: list[dict[str, object]] = []
    seen: set[str] = set()
    total = 0
    for path in files:
        if file_role(root, path) == "eval":
            continue
        relative = path.relative_to(root).as_posix()
        reason = ""
        line_number = 1
        if path.name in ENTRYPOINT_NAMES or (path.name == "main.go" and "cmd" in path.parts):
            reason = "conventional entrypoint filename"
        else:
            pattern = MAIN_SYMBOLS.get(path.suffix.lower())
            if pattern:
                text = "\n".join(lines_by_path[path])
                match = pattern.search(text)
                if match:
                    reason = "main symbol"
                    line_number = text.count("\n", 0, match.start()) + 1
        if reason and relative not in seen:
            total += 1
            append_bounded(
                entries,
                {"path": relative, "line": line_number, "reason": reason},
                maximum,
            )
            seen.add(relative)
    return entries, total


def detect_routes(
    root: Path,
    files: list[Path],
    lines_by_path: dict[Path, tuple[str, ...]],
    maximum: int,
) -> tuple[list[dict[str, object]], int]:
    routes: list[dict[str, object]] = []
    seen: set[tuple[str, int, str, str]] = set()
    total = 0
    for path in files:
        if file_role(root, path) == "eval":
            continue
        if path.suffix.lower() not in {".go", ".java", ".js", ".jsx", ".kt", ".kts", ".py", ".ts", ".tsx"}:
            continue
        relative = path.relative_to(root).as_posix()
        for line_number, line in enumerate(lines_by_path[path], start=1):
            matches: list[tuple[str, str]] = []
            for pattern in (DECORATOR_ROUTE, METHOD_ROUTE):
                for match in pattern.finditer(line):
                    matches.append((match.group("method").upper(), match.group("route")))
            for match in GENERIC_ROUTE.finditer(line):
                matches.append(("ANY", match.group("route")))
            for method, route in matches:
                key = (relative, line_number, method, route)
                if key in seen:
                    continue
                total += 1
                append_bounded(
                    routes,
                    {
                        "method": method,
                        "route": redact_route(route),
                        "path": relative,
                        "line": line_number,
                        "text": redact_line(path, line),
                    },
                    maximum,
                )
                seen.add(key)
    return routes, total


def detect_otel_findings(
    root: Path,
    files: list[Path],
    lines_by_path: dict[Path, tuple[str, ...]],
    maximum: int,
) -> tuple[dict[str, list[dict[str, object]]], dict[str, int]]:
    findings: dict[str, list[dict[str, object]]] = {name: [] for name in OTEL_PATTERNS}
    totals = {name: 0 for name in OTEL_PATTERNS}
    for path in files:
        if file_role(root, path) in {"documentation", "eval", "lockfile"}:
            continue
        for line_number, line in enumerate(lines_by_path[path], start=1):
            for category, pattern in OTEL_PATTERNS.items():
                if pattern.search(line):
                    totals[category] += 1
                    append_bounded(
                        findings[category],
                        finding(root, path, line_number, line),
                        maximum,
                    )
    return findings, totals


def detect_tests(root: Path, files: list[Path], maximum: int) -> tuple[list[str], int]:
    tests = []
    total = 0
    for path in files:
        if file_role(root, path) == "eval":
            continue
        relative = path.relative_to(root).as_posix()
        name = path.name.lower()
        parts = {part.lower() for part in path.relative_to(root).parts}
        if (
            "test" in parts
            or "tests" in parts
            or name.startswith("test_")
            or name.endswith("_test.go")
            or ".test." in name
            or ".spec." in name
            or name.endswith("test.java")
        ):
            total += 1
            if len(tests) < maximum:
                tests.append(relative)
    return tests, total


def detect_startup_surfaces(
    root: Path, files: list[Path], maximum: int
) -> tuple[list[str], int]:
    surfaces = []
    total = 0
    for path in files:
        if file_role(root, path) == "eval":
            continue
        relative = path.relative_to(root).as_posix()
        if (
            relative in STARTUP_NAMES
            or path.name in STARTUP_NAMES
            or path.name.startswith("Dockerfile")
            or ".github/workflows" in relative
            or "kubernetes" in relative.lower()
            or "/k8s/" in f"/{relative.lower()}/"
        ):
            total += 1
            if len(surfaces) < maximum:
                surfaces.append(relative)
    return surfaces, total


def project_python_runner(module_root: Path) -> str | None:
    platform_runners = (
        ".venv/Scripts/python.exe",
        ".venv/bin/python",
    )
    if os.name != "nt":
        platform_runners = tuple(reversed(platform_runners))
    for runner in platform_runners:
        if (module_root / runner).is_file():
            return runner
    return None


def detect_runtime_candidates(
    root: Path,
    manifests: list[dict[str, str]],
    lockfiles: list[str],
) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []

    def add(ecosystem: str, cwd: Path, evidence: str, runner: str, probe: str) -> None:
        candidate = {
            "ecosystem": ecosystem,
            "cwd": cwd.as_posix() if cwd.as_posix() != "" else ".",
            "evidence": evidence,
            "runner": runner,
            "probe": probe,
        }
        if candidate not in candidates:
            candidates.append(candidate)

    lock_paths = {Path(path) for path in lockfiles}
    for manifest in manifests:
        manifest_path = Path(manifest["path"])
        cwd = manifest_path.parent
        module_locks = {path.name for path in lock_paths if path.parent == cwd}
        module_root = root / cwd
        language = manifest["language"]
        if language == "go":
            add("go", cwd, manifest["path"], "go", "go version")
        elif language == "python":
            if "uv.lock" in module_locks:
                add(
                    "python",
                    cwd,
                    manifest["path"] + " + " + str(cwd / "uv.lock"),
                    "uv run --locked",
                    "uv run --locked python --version",
                )
            elif (python_runner := project_python_runner(module_root)) is not None:
                add(
                    "python",
                    cwd,
                    manifest["path"] + " + .venv",
                    python_runner,
                    f"{python_runner} --version",
                )
            else:
                add("python", cwd, manifest["path"], "project-selected Python", "python --version")
        elif language == "node":
            if "pnpm-lock.yaml" in module_locks:
                add("node", cwd, manifest["path"] + " + pnpm-lock.yaml", "pnpm", "pnpm --version")
            elif "yarn.lock" in module_locks:
                add("node", cwd, manifest["path"] + " + yarn.lock", "yarn", "yarn --version")
            else:
                add("node", cwd, manifest["path"], "npm", "node --version && npm --version")
        elif language == "java":
            if manifest["kind"] == "maven":
                runner = "./mvnw" if (module_root / "mvnw").exists() else "mvn"
                add("java", cwd, manifest["path"], runner, f"{runner} -version")
            else:
                runner = "./gradlew" if (module_root / "gradlew").exists() else "gradle"
                add("java", cwd, manifest["path"], runner, f"{runner} --version")
        elif language == "rust":
            add("rust", cwd, manifest["path"], "cargo", "cargo --version")
        elif language == "dotnet":
            add("dotnet", cwd, manifest["path"], "dotnet", "dotnet --info")

    return sorted(
        candidates,
        key=lambda item: (item["ecosystem"], item["cwd"], item["runner"]),
    )


def detect_project_commands(
    root: Path,
    files: list[Path],
    lines_by_path: dict[Path, tuple[str, ...]],
    maximum: int,
) -> tuple[list[dict[str, str]], int]:
    commands: list[dict[str, str]] = []
    total = 0
    for path in files:
        if file_role(root, path) == "eval":
            continue
        relative = path.relative_to(root).as_posix()
        if path.name in {"Makefile", "makefile"}:
            for line in lines_by_path[path]:
                match = re.match(r"^([A-Za-z0-9_.-]+)\s*:(?![=])", line)
                if match and not match.group(1).startswith("."):
                    total += 1
                    if len(commands) < maximum:
                        commands.append(
                            {
                                "source": relative,
                                "name": match.group(1),
                                "command": f"make {match.group(1)}",
                            }
                        )
        elif path.name == "package.json":
            try:
                package = json.loads("\n".join(lines_by_path[path]))
            except json.JSONDecodeError:
                continue
            if not isinstance(package, dict):
                continue
            scripts = package.get("scripts", {})
            if isinstance(scripts, dict):
                for name, command in sorted(scripts.items()):
                    total += 1
                    if len(commands) < maximum:
                        commands.append(
                            {
                                "source": relative,
                                "name": str(name),
                                "command": f"npm run {name}",
                                "definition": redact_line(path, str(command)),
                            }
                        )
    return commands, total


def section_count(total: int, returned: int) -> dict[str, int]:
    return {
        "total": total,
        "returned": returned,
        "truncated": max(0, total - returned),
    }


def inspect(
    root: Path,
    maximum: int,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    root_descriptor: int | None = None,
) -> dict[str, object]:
    scan = collect_scan_input(
        root,
        max_files=max_files,
        max_total_bytes=max_total_bytes,
        max_entries=max_entries,
        max_depth=max_depth,
        root_descriptor=root_descriptor,
    )
    files = scan.files
    lines_by_path = scan.lines
    manifests, lockfiles = detect_manifests(root, files)
    languages = detect_languages(root, files, manifests)
    entrypoints, entrypoint_total = detect_entrypoints(
        root, files, lines_by_path, maximum
    )
    routes, route_total = detect_routes(root, files, lines_by_path, maximum)
    runtime_candidates = detect_runtime_candidates(root, manifests, lockfiles)
    project_commands, project_command_total = detect_project_commands(
        root, files, lines_by_path, maximum
    )
    startup_surfaces, startup_surface_total = detect_startup_surfaces(
        root, files, maximum
    )
    tests, test_total = detect_tests(root, files, maximum)
    otel_findings, otel_totals = detect_otel_findings(
        root, files, lines_by_path, maximum
    )
    version_files = sorted(
        path.relative_to(root).as_posix()
        for path in files
        if path.name in VERSION_FILE_NAMES
    )

    returned_languages = languages[:maximum]
    returned_manifests = manifests[:maximum]
    returned_lockfiles = lockfiles[:maximum]
    returned_version_files = version_files[:maximum]
    returned_runtime_candidates = runtime_candidates[:maximum]

    result: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "root": ".",
        "proof_boundary": (
            "Candidates only: manually verify target-process reachability, runtime availability, "
            "and emitted telemetry before making coverage claims."
        ),
        "languages": returned_languages,
        "manifests": returned_manifests,
        "lockfiles": returned_lockfiles,
        "version_files": returned_version_files,
        "entrypoints": entrypoints,
        "routes": routes,
        "runtime_candidates": returned_runtime_candidates,
        "project_commands": project_commands,
        "startup_surfaces": startup_surfaces,
        "tests": tests,
        "otel_findings": otel_findings,
    }

    section_counts = {
        "languages": section_count(len(languages), len(returned_languages)),
        "manifests": section_count(len(manifests), len(returned_manifests)),
        "lockfiles": section_count(len(lockfiles), len(returned_lockfiles)),
        "version_files": section_count(
            len(version_files), len(returned_version_files)
        ),
        "entrypoints": section_count(entrypoint_total, len(entrypoints)),
        "routes": section_count(route_total, len(routes)),
        "runtime_candidates": section_count(
            len(runtime_candidates), len(returned_runtime_candidates)
        ),
        "project_commands": section_count(
            project_command_total, len(project_commands)
        ),
        "startup_surfaces": section_count(
            startup_surface_total, len(startup_surfaces)
        ),
        "tests": section_count(test_total, len(tests)),
        "otel_findings": section_count(
            sum(otel_totals.values()),
            sum(len(items) for items in otel_findings.values()),
        ),
    }
    otel_finding_counts = {
        key: section_count(otel_totals[key], len(otel_findings[key]))
        for key in sorted(otel_findings)
    }
    truncated_sections = sorted(
        key for key, counts in section_counts.items() if counts["truncated"]
    )
    complete = scan.complete and not truncated_sections
    warnings = list(scan.warnings)
    if truncated_sections:
        message = (
            "result sections truncated by --max-items: "
            + ", ".join(truncated_sections)
        )
        if len(warnings) < MAX_WARNINGS:
            warnings.append(message)
        else:
            scan.skipped["warnings_omitted"] += 1

    skipped_count = sum(scan.skipped.values())
    result.update(
        {
            "complete": complete,
            "warnings": warnings,
            "skipped": dict(sorted(scan.skipped.items())),
            "skipped_count": skipped_count,
            "section_counts": section_counts,
            "otel_finding_counts": otel_finding_counts,
        }
    )
    result["summary"] = {
        "text_files_scanned": len(files),
        "text_bytes_scanned": scan.bytes_scanned,
        "languages": len(result["languages"]),
        "manifests": len(manifests),
        "entrypoints": len(result["entrypoints"]),
        "routes": len(result["routes"]),
        "runtime_candidates": len(result["runtime_candidates"]),
        "otel_findings": sum(otel_totals.values()),
        "otel_findings_returned": sum(len(items) for items in otel_findings.values()),
        "otel_findings_by_category": dict(
            sorted(otel_totals.items())
        ),
        "otel_findings_truncated_by_category": {
            key: max(0, otel_totals[key] - len(otel_findings[key]))
            for key in sorted(otel_findings)
        },
        "complete": complete,
        "warnings": len(warnings),
        "skipped": skipped_count,
    }
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inventory project/runtime/OTel candidates for audit, instrument, and verify preflight."
    )
    parser.add_argument("root", nargs="?", default=".", type=Path)
    parser.add_argument(
        "--max-items",
        type=int,
        default=DEFAULT_MAX_ITEMS,
        help=f"Maximum entries per list/category (default: {DEFAULT_MAX_ITEMS}).",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=DEFAULT_MAX_FILES,
        help=f"Maximum supported text files to read (default: {DEFAULT_MAX_FILES}).",
    )
    parser.add_argument(
        "--max-total-bytes",
        type=int,
        default=DEFAULT_MAX_TOTAL_BYTES,
        help=(
            "Maximum total bytes to read from supported text files "
            f"(default: {DEFAULT_MAX_TOTAL_BYTES})."
        ),
    )
    parser.add_argument(
        "--max-entries",
        type=int,
        default=DEFAULT_MAX_ENTRIES,
        help=(
            "Maximum total directory entries to inspect "
            f"(default: {DEFAULT_MAX_ENTRIES})."
        ),
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=DEFAULT_MAX_DEPTH,
        help=(
            "Maximum directory depth below the project root "
            f"(default: {DEFAULT_MAX_DEPTH})."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the full JSON inventory to this path and print only its summary.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        project = authenticate_directory(args.root)
    except SecureOutputError as error:
        raise SystemExit(f"project root is not a safe directory: {error}") from None
    root = project.path
    if args.max_items < 1:
        raise SystemExit("--max-items must be at least 1")
    if args.max_files < 1:
        raise SystemExit("--max-files must be at least 1")
    if args.max_total_bytes < 1:
        raise SystemExit("--max-total-bytes must be at least 1")
    if args.max_entries < 1:
        raise SystemExit("--max-entries must be at least 1")
    if args.max_depth < 0:
        raise SystemExit("--max-depth must be at least 0")
    result = inspect(
        root,
        args.max_items,
        max_files=args.max_files,
        max_total_bytes=args.max_total_bytes,
        max_entries=args.max_entries,
        max_depth=args.max_depth,
        root_descriptor=project.descriptor,
    )
    try:
        require_same_directory(project)
    except SecureOutputError as error:
        raise SystemExit(f"project root changed during inventory: {error}") from None
    if args.output:
        try:
            output = write_text(
                project,
                args.output,
                json.dumps(result, indent=2, sort_keys=True) + "\n",
            )
        except SecureOutputError as error:
            raise SystemExit(f"refusing unsafe inventory output: {error}") from None
        print(
            json.dumps(
                {
                    "output": str(output),
                    "complete": result["complete"],
                    "warnings": result["warnings"],
                    "skipped_count": result["skipped_count"],
                    "summary": result["summary"],
                },
                sort_keys=True,
            )
        )
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
