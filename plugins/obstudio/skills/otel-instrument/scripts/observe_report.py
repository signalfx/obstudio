#!/usr/bin/env python3
"""Run the shared OTel report flow validator and HTML renderer."""

import runpy
import sys
from pathlib import Path


def shared_tool_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "references"
        / "scripts"
        / "observe_report.py"
    )


def main() -> int:
    shared_tool = shared_tool_path()
    if not shared_tool.is_file():
        print(
            "OpenTelemetry report helper is missing: "
            f"{shared_tool}. Install or copy the complete Obstudio skill bundle.",
            file=sys.stderr,
        )
        return 1
    runpy.run_path(str(shared_tool), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
