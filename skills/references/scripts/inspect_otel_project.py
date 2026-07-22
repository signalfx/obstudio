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
from dataclasses import dataclass, field
from pathlib import Path


SCHEMA_VERSION = 1
MAX_FILE_BYTES = 2_000_000
DEFAULT_MAX_ITEMS = 80
DEFAULT_MAX_FILES = 5_000
DEFAULT_MAX_TOTAL_BYTES = 50_000_000
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
    "warnings_omitted",
)

SKIP_DIRS = {
    ".cache",
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
    r"(?i)(?P<prefix>\b(?:authorization|headers?|password|passwd|secret|token|"
    r"api[_-]?key|client[_-]?secret)\b\s*[:=]\s*)(?P<value>[^,\s}\]]+)"
)
SENSITIVE_NAME = re.compile(
    r"(?i)(?:authorization|credential|headers?|password|passwd|secret|token|"
    r"api[_-]?key|client[_-]?secret)"
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
    is_requirements = path.name.startswith("requirements") and path.suffix.lower() == ".txt"
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


def relative_label(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def collect_scan_input(
    root: Path, *, max_files: int, max_total_bytes: int
) -> ScanInput:
    scan = ScanInput()

    def walk_error(error: OSError) -> None:
        scan.skipped["walk_errors"] += 1
        scan.warn(f"directory walk failed: {error}")

    stop = False
    for current, dirnames, filenames in os.walk(root, onerror=walk_error):
        current_path = Path(current)
        retained_dirs = []
        for name in sorted(dirnames):
            path = current_path / name
            if name in SKIP_DIRS:
                scan.skipped["configured_directories"] += 1
                continue
            if path.is_symlink():
                scan.skipped["symlink_directories"] += 1
                scan.warn(f"skipped symlink directory: {relative_label(root, path)}")
                continue
            retained_dirs.append(name)
        dirnames[:] = retained_dirs

        for name in sorted(filenames):
            path = current_path / name
            if not is_supported_text(path):
                continue
            if path.is_symlink():
                scan.skipped["symlink_files"] += 1
                scan.warn(f"skipped symlink file: {relative_label(root, path)}")
                continue
            if len(scan.files) >= max_files:
                scan.skipped["file_limit"] += 1
                scan.warn(
                    f"stopped after {max_files} text files; additional files were not scanned"
                )
                stop = True
                break
            try:
                size = path.stat().st_size
            except OSError as error:
                scan.skipped["stat_errors"] += 1
                scan.warn(
                    f"could not stat {relative_label(root, path)}: {error}"
                )
                continue
            if size > MAX_FILE_BYTES:
                scan.skipped["oversized_files"] += 1
                scan.warn(
                    f"skipped oversized file {relative_label(root, path)} "
                    f"({size} bytes; limit {MAX_FILE_BYTES})"
                )
                continue
            if scan.bytes_scanned + size > max_total_bytes:
                scan.skipped["byte_limit"] += 1
                scan.warn(
                    f"stopped before {relative_label(root, path)} because the "
                    f"{max_total_bytes}-byte scan limit was reached"
                )
                stop = True
                break
            try:
                lines = tuple(
                    path.read_text(encoding="utf-8", errors="replace").splitlines()
                )
            except OSError as error:
                scan.skipped["read_errors"] += 1
                scan.warn(
                    f"could not read {relative_label(root, path)}: {error}"
                )
                continue
            scan.files.append(path)
            scan.lines[path] = lines
            scan.bytes_scanned += size
        if stop:
            break

    return scan


def file_role(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    lowered_parts = {part.lower() for part in relative.parts}
    name = path.name.lower()
    if lowered_parts & {"eval", "evals"}:
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


def redact_line(path: Path, text: str) -> str:
    stripped = text.strip()
    if path.name == ".env" or path.name.startswith(".env."):
        match = ENV_ASSIGNMENT.match(stripped)
        return f"{match.group('key')}=<redacted>" if match else "<redacted env line>"
    if SENSITIVE_NAME.search(stripped):
        return "<redacted sensitive configuration>"
    return SENSITIVE_ASSIGNMENT.sub(r"\g<prefix><redacted>", stripped)[:240]


def redact_route(route: str) -> str:
    if SENSITIVE_NAME.search(route):
        return "<redacted sensitive route>"
    return route[:240]


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
        elif path.name.startswith("requirements") and path.suffix == ".txt":
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
            elif (module_root / ".venv" / "bin" / "python").exists():
                add(
                    "python",
                    cwd,
                    manifest["path"] + " + .venv",
                    ".venv/bin/python",
                    ".venv/bin/python --version",
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
) -> dict[str, object]:
    scan = collect_scan_input(
        root,
        max_files=max_files,
        max_total_bytes=max_total_bytes,
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
        "--output",
        type=Path,
        help="Write the full JSON inventory to this path and print only its summary.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit(f"project root is not a directory: {root}")
    if args.max_items < 1:
        raise SystemExit("--max-items must be at least 1")
    if args.max_files < 1:
        raise SystemExit("--max-files must be at least 1")
    if args.max_total_bytes < 1:
        raise SystemExit("--max-total-bytes must be at least 1")
    result = inspect(
        root,
        args.max_items,
        max_files=args.max_files,
        max_total_bytes=args.max_total_bytes,
    )
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
