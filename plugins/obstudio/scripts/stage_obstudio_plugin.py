#!/usr/bin/env python3
"""Stage a self-contained Obstudio Codex plugin package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
    "observer-control/observer-status",
    "observer-control/observer-restart",
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
PLUGIN_SKILL_ENTRIES = (
    "obstudio-help",
    "observer-control/observer-open",
    "otel-audit",
    "otel-instrument",
    "otel-verify",
    "splunk-configure",
    "splunk-dashboard",
    "observer-control/observer-status",
    "observer-control/observer-restart",
    "observer-control/observer-stop",
    "splunk-detector-publish",
    "splunk-dashboard-publish",
    "splunk-sync",
    "splunk-dashboard-sync",
    "references",
)

PLUGIN_PATHS = (
    ".codex-plugin",
    ".mcp.json",
    "PRIVACY.md",
    "README.md",
    "SECURITY.md",
    "assets",
    "hooks",
)
MAX_DEFAULT_PROMPTS = 3
SKILL_REFERENCE_PATTERN = re.compile(r"\$([A-Za-z0-9_-]+)")


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
    copy_plugin_skills(skills_output)


def sync_plugin_skills() -> None:
    skills_output = PLUGIN_ROOT / PLUGIN_SKILLS_DIR
    temp_output = PLUGIN_ROOT / ".skills-sync-tmp"
    remove_path(temp_output)
    temp_output.mkdir(parents=True)
    try:
        copy_plugin_skills(temp_output, local_source_root=skills_output)
        verify_local_plugin_skills(temp_output)
        remove_path(skills_output)
        temp_output.rename(skills_output)
    finally:
        remove_path(temp_output)


def copy_plugin_skills(skills_output: Path, local_source_root: Path | None = None) -> None:
    for relative in PLUGIN_SKILL_ENTRIES:
        source = source_for_plugin_skill_entry(relative, local_source_root=local_source_root)
        if not source.exists():
            raise RuntimeError(f"missing plugin skill entry: {source}")
        destination = skills_output / relative
        remove_path(destination)
        copy_path(source, destination)


def source_for_plugin_skill_entry(relative: str, local_source_root: Path | None = None) -> Path:
    if relative in PLUGIN_LOCAL_SKILL_ENTRIES:
        return (local_source_root or PLUGIN_ROOT / PLUGIN_SKILLS_DIR) / relative
    return CANONICAL_SKILLS_ROOT / relative


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
    verify_plugin_manifest(manifest, skills)
    symlinks = [path for path in output.rglob("*") if path.is_symlink()]
    if symlinks:
        rendered = "\n".join(str(path.relative_to(output)) for path in symlinks)
        raise RuntimeError(f"staged plugin must not contain symlinks:\n{rendered}")


def verify_plugin_manifest(manifest_path: Path, skills_root: Path) -> None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid plugin manifest JSON: {manifest_path}") from exc
    interface = manifest.get("interface")
    if not isinstance(interface, dict):
        raise RuntimeError("plugin manifest must include an interface object")
    default_prompts = interface.get("defaultPrompt", [])
    if not isinstance(default_prompts, list) or any(not isinstance(prompt, str) for prompt in default_prompts):
        raise RuntimeError("plugin manifest interface.defaultPrompt must be a list of strings")
    if len(default_prompts) > MAX_DEFAULT_PROMPTS:
        raise RuntimeError(
            "plugin manifest interface.defaultPrompt must contain at most "
            f"{MAX_DEFAULT_PROMPTS} entries"
        )
    verify_manifest_skill_references(manifest, available_skill_names(skills_root))


def verify_manifest_skill_references(manifest: object, skill_names: set[str]) -> None:
    missing = sorted(
        {
            reference
            for text in iter_manifest_strings(manifest)
            for reference in SKILL_REFERENCE_PATTERN.findall(text)
            if reference not in skill_names
        }
    )
    if missing:
        rendered = ", ".join(f"${name}" for name in missing)
        raise RuntimeError(f"plugin manifest references unknown skills: {rendered}")


def iter_manifest_strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_manifest_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_manifest_strings(item)


def available_skill_names(skills_root: Path) -> set[str]:
    names: set[str] = set()
    for skill_path in skills_root.rglob("SKILL.md"):
        name = read_skill_name(skill_path)
        if name:
            names.add(name)
    return names


def read_skill_name(skill_path: Path) -> str | None:
    try:
        lines = skill_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            return None
        match = re.fullmatch(r"name:\s*([A-Za-z0-9_-]+)", stripped)
        if match:
            return match.group(1)
    return None


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
        for path in iter_archive_files(source):
            arcname = Path(source.name) / path.relative_to(source)
            zf.write(path, arcname.as_posix())


def iter_archive_files(source: Path) -> list[Path]:
    ordered: list[Path] = []
    seen: set[Path] = set()

    def add_files(root: Path) -> None:
        if root.is_file():
            files = [root]
        elif root.is_dir():
            files = sorted(path for path in root.rglob("*") if path.is_file())
        else:
            files = []
        for path in files:
            if path not in seen:
                seen.add(path)
                ordered.append(path)

    for relative in PLUGIN_PATHS:
        add_files(source / relative)
    for relative in PLUGIN_SKILL_ENTRIES:
        add_files(source / PLUGIN_SKILLS_DIR / relative)
    for path in sorted(source.rglob("*")):
        if path.is_file() and path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


if __name__ == "__main__":
    raise SystemExit(main())
