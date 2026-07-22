#!/usr/bin/env python3
"""Build deterministic local Java-agent resolver fixtures with the stdlib."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path


UPSTREAM = "io.opentelemetry.javaagent.OpenTelemetryAgent"
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
FIXED_FILE_MODE = 0o100644


def write_agent(path: Path, version: str, premain: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = (
        "Manifest-Version: 1.0\r\n"
        f"Implementation-Version: {version}\r\n"
        f"Premain-Class: {premain}\r\n\r\n"
    )
    entry = zipfile.ZipInfo("META-INF/MANIFEST.MF", FIXED_ZIP_TIMESTAMP)
    entry.create_system = 3
    entry.create_version = 20
    entry.extract_version = 20
    entry.external_attr = FIXED_FILE_MODE << 16
    entry.compress_type = zipfile.ZIP_STORED
    entry.extra = b""
    entry.comment = b""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(entry, manifest.encode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.output.resolve()
    candidates = {
        "valid": root / "opentelemetry-javaagent-2.1.0+build.7.jar",
        "prerelease": root / "opentelemetry-javaagent-2.1.0-beta.2.jar",
        "malicious": root / "opentelemetry-javaagent-9.0.0.jar",
        "wrong_family": root / "splunk-otel-javaagent-8.0.0.jar",
    }
    write_agent(candidates["valid"], "2.1.0+build.7", UPSTREAM)
    write_agent(candidates["prerelease"], "2.1.0-beta.2", UPSTREAM)
    write_agent(candidates["malicious"], "9.0.0", "example.malicious.Agent")
    write_agent(candidates["wrong_family"], "8.0.0", UPSTREAM)
    print(json.dumps({key: str(path) for key, path in candidates.items()}, indent=2))


if __name__ == "__main__":
    main()
