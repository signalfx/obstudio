#!/usr/bin/env python3
"""Run the shared, bounded loopback-listener capability probe."""

import runpy
import sys
from pathlib import Path


def shared_probe_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "references"
        / "scripts"
        / "probe_loopback_bind.py"
    )


def main() -> int:
    shared_probe = shared_probe_path()
    if not shared_probe.is_file():
        print(
            "Loopback bind probe is missing: "
            f"{shared_probe}. Install or copy the complete Obstudio skill bundle, "
            "or probe the local listener prerequisite manually.",
            file=sys.stderr,
        )
        return 2
    runpy.run_path(str(shared_probe), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
