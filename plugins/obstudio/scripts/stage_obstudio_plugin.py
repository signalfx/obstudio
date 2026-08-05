#!/usr/bin/env python3
"""Stage a self-contained Obstudio Codex plugin package."""

from __future__ import annotations

import argparse
import os
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = ROOT / "plugins" / "obstudio"
CANONICAL_SKILLS_ROOT = ROOT / "skills"
DEFAULT_OUTPUT = ROOT / ".release" / "plugins" / "obstudio"
DEFAULT_ARCHIVE = ROOT / ".release" / "plugins" / "obstudio.zip"

PLUGIN_PATHS = (
    ".codex-plugin",
    ".mcp.json",
    "README.md",
    "assets",
    "hooks",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="staged plugin directory")
    parser.add_argument("--archive", type=Path, default=None, help="optional zip archive to write")
    parser.add_argument("--check", action="store_true", help="verify the staged plugin and exit")
    args = parser.parse_args()

    output = args.output.expanduser().resolve()
    if args.check:
        verify_staged_plugin(output)
        return 0

    stage_plugin(output)
    if args.archive is not None:
        write_archive(output, args.archive.expanduser().resolve())
    return 0


def stage_plugin(output: Path) -> None:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    for relative in PLUGIN_PATHS:
        copy_path(PLUGIN_ROOT / relative, output / relative)

    skills_output = output / "skills"
    skills_output.mkdir()
    for entry in sorted((PLUGIN_ROOT / "skills").iterdir()):
        target = entry.resolve()
        if target.is_relative_to(CANONICAL_SKILLS_ROOT) or target.is_relative_to(PLUGIN_ROOT / "skills"):
            copy_path(target, skills_output / entry.name)
            continue
        raise RuntimeError(f"refusing to stage skill outside trusted roots: {entry} -> {target}")

    verify_staged_plugin(output)


def copy_path(source: Path, destination: Path) -> None:
    if source.is_symlink():
        source = source.resolve()
    if source.is_dir():
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
        shutil.copytree(source, destination, symlinks=False, ignore=ignore)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination, follow_symlinks=True)


def verify_staged_plugin(output: Path) -> None:
    manifest = output / ".codex-plugin" / "plugin.json"
    skills = output / "skills"
    if not manifest.is_file():
        raise RuntimeError(f"missing plugin manifest: {manifest}")
    if not skills.is_dir():
        raise RuntimeError(f"missing staged skills directory: {skills}")
    symlinks = [path for path in output.rglob("*") if path.is_symlink()]
    if symlinks:
        rendered = "\n".join(str(path.relative_to(output)) for path in symlinks)
        raise RuntimeError(f"staged plugin must not contain symlinks:\n{rendered}")


def write_archive(source: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source.rglob("*")):
            if path.is_dir():
                continue
            arcname = Path(source.name) / path.relative_to(source)
            zf.write(path, arcname.as_posix())


if __name__ == "__main__":
    raise SystemExit(main())
