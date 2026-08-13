#!/usr/bin/env python3
"""Stage a self-contained Obstudio plugin bundle for Codex and Claude."""

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

PLUGIN_SHARED_PATHS = (
    ".mcp.json",
    "PRIVACY.md",
    "README.md",
    "SECURITY.md",
    "assets",
)
MAX_DEFAULT_PROMPTS = 3
PLUGIN_HOSTS = ("codex", "claude")
SKILL_REFERENCE_PATTERN = re.compile(r"\$([A-Za-z0-9_-]+)")
SEMVER_PATTERN = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?\Z")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="staged plugin directory")
    parser.add_argument("--archive", type=Path, default=None, help="optional zip archive to write")
    parser.add_argument(
        "--release-tag",
        default="",
        help="release tag (vMAJOR.MINOR.PATCH) to stamp and enforce in staged manifests",
    )
    parser.add_argument(
        "--host",
        choices=("all", *PLUGIN_HOSTS),
        default="all",
        help="host manifest to validate; defaults to both plugin hosts",
    )
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
    release_version = release_version_from_tag(args.release_tag) if args.release_tag else ""
    if args.check:
        verify_staged_plugin(output, args.host, expected_version=release_version)
        return 0

    stage_plugin(output, args.host, release_version=release_version)
    if args.archive is not None:
        write_archive(output, args.archive.expanduser().resolve())
    return 0


def stage_plugin(output: Path, host: str = "all", release_version: str = "") -> None:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    for relative in plugin_paths(host):
        copy_path(PLUGIN_ROOT / relative, output / relative)
    if release_version:
        stamp_staged_manifest_versions(output, host, release_version)
    stage_hooks(output / "hooks", host)

    skills_output = output / PLUGIN_SKILLS_DIR
    stage_skills(skills_output)

    verify_staged_plugin(output, host, expected_version=release_version)


def release_version_from_tag(release_tag: str) -> str:
    version = release_tag.strip().removeprefix("v")
    if not release_tag.strip().startswith("v") or not SEMVER_PATTERN.fullmatch(version):
        raise RuntimeError(f"release tag must be vMAJOR.MINOR.PATCH semver: {release_tag}")
    return version


def stamp_staged_manifest_versions(output: Path, host: str, version: str) -> None:
    for selected_host in PLUGIN_HOSTS if host == "all" else (host,):
        manifest_path = output / (".claude-plugin" if selected_host == "claude" else ".codex-plugin") / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = version
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

def plugin_paths(host: str) -> tuple[str, ...]:
    if host == "all":
        manifests = (".codex-plugin", ".claude-plugin")
    else:
        manifests = (".claude-plugin" if host == "claude" else ".codex-plugin",)
    return (*manifests, *PLUGIN_SHARED_PATHS)


def stage_hooks(hooks_output: Path, host: str) -> None:
    hooks_output.mkdir(parents=True, exist_ok=True)
    copy_path(PLUGIN_ROOT / "hooks" / "bootstrap_obstudio.py", hooks_output / "bootstrap_obstudio.py")
    if host in ("all", "claude"):
        copy_path(PLUGIN_ROOT / "hooks" / "bootstrap_claude.cjs", hooks_output / "bootstrap_claude.cjs")
    hook_files = ("codex-hooks.json", "claude-hooks.json") if host == "all" else (f"{host}-hooks.json",)
    for hook_file in hook_files:
        copy_path(PLUGIN_ROOT / "hooks" / hook_file, hooks_output / hook_file)


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
        if relative not in PLUGIN_LOCAL_SKILL_ENTRIES:
            normalize_text_tree(destination)


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


def normalize_text_tree(path: Path) -> None:
    if path.is_file():
        normalize_text_file(path)
        return
    if path.is_dir():
        for child in path.rglob("*"):
            if child.is_file():
                normalize_text_file(child)


def normalize_text_file(path: Path) -> None:
    data = path.read_bytes()
    normalized = normalize_text_bytes(data)
    if normalized != data:
        path.write_bytes(normalized)


def normalize_text_bytes(data: bytes) -> bytes:
    if b"\0" in data:
        return data
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    return "".join(normalize_text_line(line) for line in text.splitlines(keepends=True)).encode("utf-8")


def normalize_text_line(line: str) -> str:
    if line.endswith("\r\n"):
        return line[:-2].rstrip(" \t") + "\r\n"
    if line.endswith("\n"):
        return line[:-1].rstrip(" \t") + "\n"
    if line.endswith("\r"):
        return line[:-1].rstrip(" \t") + "\r"
    return line.rstrip(" \t")


def verify_staged_plugin(output: Path, host: str = "codex", expected_version: str = "") -> None:
    skills = output / PLUGIN_SKILLS_DIR
    if not skills.is_dir():
        raise RuntimeError(f"missing staged skills directory: {skills}")
    symlinks = [path for path in output.rglob("*") if path.is_symlink()]
    if symlinks:
        rendered = "\n".join(str(path.relative_to(output)) for path in symlinks)
        raise RuntimeError(f"staged plugin must not contain symlinks:\n{rendered}")
    for selected_host in PLUGIN_HOSTS if host == "all" else (host,):
        manifest = output / (".claude-plugin" if selected_host == "claude" else ".codex-plugin") / "plugin.json"
        if not manifest.is_file():
            raise RuntimeError(f"missing plugin manifest: {manifest}")
        verify_plugin_manifest(manifest, skills, selected_host, expected_version=expected_version)


def verify_plugin_manifest(
    manifest_path: Path,
    skills_root: Path,
    host: str = "codex",
    expected_version: str = "",
) -> None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid plugin manifest JSON: {manifest_path}") from exc
    if expected_version and manifest.get("version") != expected_version:
        raise RuntimeError(
            f"plugin manifest version must match release version {expected_version}: {manifest_path}"
        )
    if host == "claude":
        if not isinstance(manifest.get("name"), str) or not manifest["name"].strip():
            raise RuntimeError("plugin manifest must include a non-empty name")
    else:
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
        source_hash = normalized_file_sha256(source)
        destination_hash = normalized_file_sha256(destination)
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


def normalized_file_sha256(path: Path) -> str:
    return hashlib.sha256(normalize_text_bytes(path.read_bytes())).hexdigest()


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

    for relative in plugin_paths("all"):
        add_files(source / relative)
    add_files(source / "hooks")
    for relative in PLUGIN_SKILL_ENTRIES:
        add_files(source / PLUGIN_SKILLS_DIR / relative)
    for path in sorted(source.rglob("*")):
        if path.is_file() and path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


if __name__ == "__main__":
    raise SystemExit(main())
