#!/usr/bin/env python3
"""Run the shared, read-only Java-agent resolver."""

import runpy
import sys
from pathlib import Path


def shared_resolver_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "references"
        / "scripts"
        / "resolve_java_agent.py"
    )


def main() -> int:
    shared_resolver = shared_resolver_path()
    if not shared_resolver.is_file():
        print(
            "Java-agent resolver is missing: "
            f"{shared_resolver}. Install or copy the complete Obstudio skill bundle.",
            file=sys.stderr,
        )
        return 2
    runpy.run_path(str(shared_resolver), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
