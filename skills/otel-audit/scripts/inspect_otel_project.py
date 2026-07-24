#!/usr/bin/env python3
"""Run the shared, read-only OpenTelemetry project inventory."""

import runpy
import sys
from pathlib import Path


def shared_scanner_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "references"
        / "scripts"
        / "inspect_otel_project.py"
    )


def main() -> int:
    shared_scanner = shared_scanner_path()
    if not shared_scanner.is_file():
        print(
            "OpenTelemetry project inventory helper is missing: "
            f"{shared_scanner}. Install or copy the complete Obstudio skill bundle, "
            "or perform repository discovery manually.",
            file=sys.stderr,
        )
        return 2
    runpy.run_path(str(shared_scanner), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
