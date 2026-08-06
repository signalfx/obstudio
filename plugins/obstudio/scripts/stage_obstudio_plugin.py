#!/usr/bin/env python3
"""Stage a self-contained Obstudio Codex plugin package."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = ROOT / "plugins" / "obstudio"
CANONICAL_SKILLS_ROOT = ROOT / "skills"
DEFAULT_OUTPUT = ROOT / ".release" / "plugins" / "obstudio"
DEFAULT_ARCHIVE = ROOT / ".release" / "plugins" / "obstudio.zip"
PLUGIN_SKILLS_DIR = "skills"
PLUGIN_LOCAL_SKILL_ENTRIES = (
    "obstudio-help",
    "observer-control/observer-open",
    "observer-control/observer-restart",
    "observer-control/observer-status",
    "observer-control/observer-stop",
)
PLUGIN_SHARED_SKILL_ENTRIES = (
    "otel-audit",
    "otel-instrument",
    "otel-verify",
    "references",
    "splunk-configure",
    "splunk-dashboard",
    "splunk-dashboard-publish",
    "splunk-dashboard-sync",
    "splunk-detector-publish",
    "splunk-sync",
)
PLUGIN_SKILL_ENTRIES = (*PLUGIN_LOCAL_SKILL_ENTRIES, *PLUGIN_SHARED_SKILL_ENTRIES)

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
    parser.add_argument("--sync-plugin-skills", action="store_true", help="refresh the committed plugin skills copy")
    parser.add_argument("--check-plugin-skills", action="store_true", help="verify committed plugin skills are synced")
    args = parser.parse_args()

    if args.sync_plugin_skills:
        sync_plugin_skills()
        return 0
    if args.check_plugin_skills:
        verify_plugin_skills_synced()
        return 0

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

    skills_output = output / PLUGIN_SKILLS_DIR
    stage_skills(skills_output)

    verify_staged_plugin(output)


def stage_skills(skills_output: Path) -> None:
    if skills_output.exists():
        shutil.rmtree(skills_output)
    skills_output.mkdir(parents=True)
    copy_shared_skills(skills_output)
    copy_local_skills(skills_output)


def sync_plugin_skills() -> None:
    skills_output = PLUGIN_ROOT / PLUGIN_SKILLS_DIR
    skills_output.mkdir(parents=True, exist_ok=True)
    copy_shared_skills(skills_output)
    verify_local_plugin_skills(skills_output)


def copy_shared_skills(skills_output: Path) -> None:
    for relative in PLUGIN_SHARED_SKILL_ENTRIES:
        source = CANONICAL_SKILLS_ROOT / relative
        if not source.exists():
            raise RuntimeError(f"missing canonical skill entry: {source}")
        destination = skills_output / relative
        remove_path(destination)
        copy_path(source, destination)


def copy_local_skills(skills_output: Path) -> None:
    source_root = PLUGIN_ROOT / PLUGIN_SKILLS_DIR
    for relative in PLUGIN_LOCAL_SKILL_ENTRIES:
        source = source_root / relative
        if not source.exists():
            raise RuntimeError(f"missing plugin-local skill entry: {source}")
        destination = skills_output / relative
        if source.resolve() == destination.resolve():
            continue
        remove_path(destination)
        copy_path(source, destination)


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


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
    skills = output / PLUGIN_SKILLS_DIR
    if not manifest.is_file():
        raise RuntimeError(f"missing plugin manifest: {manifest}")
    if not skills.is_dir():
        raise RuntimeError(f"missing staged skills directory: {skills}")
    symlinks = [path for path in output.rglob("*") if path.is_symlink()]
    if symlinks:
        rendered = "\n".join(str(path.relative_to(output)) for path in symlinks)
        raise RuntimeError(f"staged plugin must not contain symlinks:\n{rendered}")


def verify_plugin_skills_synced() -> None:
    skills_root = PLUGIN_ROOT / PLUGIN_SKILLS_DIR
    verify_local_plugin_skills(skills_root)

    expected = sorted(flatten_expected_skill_files())
    actual = sorted(flatten_files(PLUGIN_ROOT / PLUGIN_SKILLS_DIR))
    if expected != actual:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        details = []
        if missing:
            details.append("missing:\n" + "\n".join(str(path) for path in missing))
        if extra:
            details.append("extra:\n" + "\n".join(str(path) for path in extra))
        raise RuntimeError("plugin skills are not synced with canonical skills\n" + "\n".join(details))

    for relative in expected:
        source = source_for_shared_plugin_skill_file(relative)
        if source is None:
            continue
        destination = PLUGIN_ROOT / PLUGIN_SKILLS_DIR / relative
        if destination.is_symlink():
            raise RuntimeError(f"plugin skill copy must not contain symlinks: {destination}")
        source_hash = file_sha256(source)
        destination_hash = file_sha256(destination)
        if source_hash != destination_hash:
            raise RuntimeError(
                "plugin skill copy differs from canonical source: "
                f"{relative} ({source_hash} != {destination_hash})"
            )


def verify_local_plugin_skills(skills_root: Path) -> None:
    for relative in PLUGIN_LOCAL_SKILL_ENTRIES:
        path = skills_root / relative
        if not path.exists():
            raise RuntimeError(f"missing plugin-local skill: {path}")
        if path.is_symlink():
            raise RuntimeError(f"plugin-local skill must not be a symlink: {path}")
        if not (path / "SKILL.md").is_file():
            raise RuntimeError(f"missing plugin-local SKILL.md: {path / 'SKILL.md'}")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def flatten_expected_skill_files() -> set[Path]:
    files: set[Path] = set()
    for relative in PLUGIN_SHARED_SKILL_ENTRIES:
        source = CANONICAL_SKILLS_ROOT / relative
        if source.is_file():
            files.add(Path(relative))
            continue
        for path in source.rglob("*"):
            if path.is_file() and not should_ignore(path):
                files.add(Path(relative) / path.relative_to(source))
    for relative in PLUGIN_LOCAL_SKILL_ENTRIES:
        source = PLUGIN_ROOT / PLUGIN_SKILLS_DIR / relative
        for path in source.rglob("*"):
            if path.is_file() and not should_ignore(path):
                files.add(Path(relative) / path.relative_to(source))
    return files


def source_for_shared_plugin_skill_file(relative: Path) -> Path | None:
    for entry in sorted(PLUGIN_SHARED_SKILL_ENTRIES, key=len, reverse=True):
        entry_path = Path(entry)
        if relative == entry_path or entry_path in relative.parents:
            return CANONICAL_SKILLS_ROOT / relative
    return None


def flatten_files(root: Path) -> set[Path]:
    files: set[Path] = set()
    for path in root.rglob("*"):
        if path.is_file() and not should_ignore(path):
            files.add(path.relative_to(root))
    return files


def should_ignore(path: Path) -> bool:
    return any(part == "__pycache__" for part in path.parts) or path.name in {".DS_Store"} or path.suffix == ".pyc"


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
