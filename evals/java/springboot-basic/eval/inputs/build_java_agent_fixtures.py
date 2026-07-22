#!/usr/bin/env python3
"""Build deterministic local Java-agent resolver fixtures with the stdlib."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path


UPSTREAM = "io.opentelemetry.javaagent.OpenTelemetryAgent"


def write_agent(path: Path, version: str, premain: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = (
        "Manifest-Version: 1.0\r\n"
        f"Implementation-Version: {version}\r\n"
        f"Premain-Class: {premain}\r\n\r\n"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", manifest)


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
