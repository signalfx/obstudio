#!/usr/bin/env python3
"""Find Python OpenTelemetry provider/exporter topology candidates."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SKIP_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "node_modules",
    "site-packages",
    "target",
    "dist",
    "build",
}
TEXT_NAMES = {"Makefile", "Dockerfile", "Procfile"}
TEXT_SUFFIXES = {".py", ".sh", ".bash", ".zsh", ".env", ".toml", ".yaml", ".yml", ".json"}
PATTERNS = {
    "provider_construction": re.compile(r"\b(TracerProvider|MeterProvider|LoggerProvider|NoOpMeterProvider)\b"),
    "provider_registration": re.compile(r"\bset_(tracer|meter|logger)_provider\b"),
    "exporter": re.compile(r"\b(?:OTLP\w*Exporter|Console\w*Exporter|File\w*Exporter)\b"),
    "resource": re.compile(r"\bResource\.(?:create|get_empty)|\bResource\s*\("),
    "automatic_bootstrap": re.compile(r"\b(?:opentelemetry-instrument|splunk_otel|init_splunk_otel)\b"),
    "runtime_configuration": re.compile(
        r"\b(?:OTEL_[A-Z0-9_]+|NO_OP_OTEL|EXPORT_METRICS_TO_FILE|METRICS_FILE_PATH)\b"
    ),
    "shutdown_flush": re.compile(r"\b(?:force_flush|shutdown)\s*\("),
}


def candidates(root: Path) -> list[Path]:
    files = []
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        is_env_file = path.name == ".env" or path.name.startswith(".env.")
        if path.is_file() and (
            path.name in TEXT_NAMES or is_env_file or path.suffix in TEXT_SUFFIXES
        ):
            files.append(path)
    return sorted(files)


def scan(root: Path) -> dict[str, list[dict[str, object]]]:
    findings: dict[str, list[dict[str, object]]] = {name: [] for name in PATTERNS}
    for path in candidates(root):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        relative = str(path.relative_to(root))
        for line_number, line in enumerate(lines, start=1):
            for category, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings[category].append(
                        {"path": relative, "line": line_number, "text": line.strip()[:240]}
                    )
    return findings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find OTel provider/exporter candidates; manually verify target-process reachability."
    )
    parser.add_argument("root", nargs="?", default=".", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    result = {"root": str(root), "reachability_proven": False, "findings": scan(root)}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
