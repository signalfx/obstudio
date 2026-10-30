"""Write, verify, and check the reviewed runtime manifest shipped inside the plugin."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


MANIFEST_SCHEMA_VERSION = 1
MANIFEST_RELATIVE_PATH = Path("hooks") / "runtime-manifest.json"
ARTIFACT_SUFFIXES = (
    "darwin_amd64.zip",
    "darwin_arm64.zip",
    "linux_amd64.zip",
    "windows_amd64.zip",
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
CHECKSUM_LINE_PATTERN = re.compile(r"^(?P<hash>[0-9a-fA-F]{64})\s+\*?(?P<name>.+)$")


def artifact_name(version: str, suffix: str) -> str:
    return f"obstudio_{version}_{suffix}"


def manifest_path(plugin_root: Path) -> Path:
    return plugin_root / MANIFEST_RELATIVE_PATH


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hashes_from_checksums_file(checksums_file: Path, version: str) -> dict[str, str]:
    lines = checksums_file.read_text(encoding="utf-8").splitlines()
    hashes: dict[str, str] = {}
    for suffix in ARTIFACT_SUFFIXES:
        name = artifact_name(version, suffix)
        found = [
            match.group("hash").lower()
            for match in (CHECKSUM_LINE_PATTERN.fullmatch(line.strip()) for line in lines)
            if match and Path(match.group("name")).name == name
        ]
        if len(found) != 1:
            raise RuntimeError(f"expected exactly one checksum for {name} in {checksums_file}")
        hashes[suffix] = found[0]
    return hashes


def hashes_from_dist(dist_dir: Path, version: str) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for suffix in ARTIFACT_SUFFIXES:
        archive = dist_dir / artifact_name(version, suffix)
        if not archive.is_file():
            raise RuntimeError(f"missing runtime archive: {archive}")
        hashes[suffix] = file_sha256(archive)
    return hashes


def render_manifest(version: str, hashes: dict[str, str]) -> str:
    manifest = {
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "version": version,
        "artifacts": {
            suffix: {"name": artifact_name(version, suffix), "sha256": hashes[suffix]}
            for suffix in ARTIFACT_SUFFIXES
        },
    }
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def write_runtime_manifest(plugin_root: Path, version: str, hashes: dict[str, str]) -> Path:
    path = manifest_path(plugin_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_manifest(version, hashes), encoding="utf-8")
    read_runtime_manifest(path)
    print(f"wrote {path} for {version}")
    return path


def read_runtime_manifest(path: Path) -> dict[str, object]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"runtime manifest is missing or invalid JSON: {path}") from exc
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != MANIFEST_SCHEMA_VERSION:
        raise RuntimeError(f"runtime manifest has an unsupported schema: {path}")
    version = manifest.get("version")
    if not isinstance(version, str) or not version:
        raise RuntimeError(f"runtime manifest is missing a version: {path}")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(ARTIFACT_SUFFIXES):
        raise RuntimeError(f"runtime manifest must list exactly {', '.join(ARTIFACT_SUFFIXES)}: {path}")
    for suffix in ARTIFACT_SUFFIXES:
        entry = artifacts[suffix]
        if not isinstance(entry, dict) or entry.get("name") != artifact_name(version, suffix):
            raise RuntimeError(f"runtime manifest artifact name for {suffix} is invalid: {path}")
        sha256 = entry.get("sha256")
        if not isinstance(sha256, str) or not SHA256_PATTERN.fullmatch(sha256):
            raise RuntimeError(f"runtime manifest sha256 for {suffix} must be 64 lowercase hex chars: {path}")
    return manifest


def check_runtime_manifest(plugin_root: Path, plugin_version: str) -> None:
    path = manifest_path(plugin_root)
    manifest = read_runtime_manifest(path)
    if manifest["version"] != plugin_version:
        raise RuntimeError(
            f"runtime manifest version {manifest['version']!r} does not match "
            f"plugin version {plugin_version!r}: {path}"
        )
    print(f"runtime manifest pins {plugin_version}")


def verify_runtime_manifest(plugin_root: Path, version: str, dist_dir: Path) -> None:
    path = manifest_path(plugin_root)
    manifest = read_runtime_manifest(path)
    if manifest["version"] != version:
        raise RuntimeError(f"runtime manifest version {manifest['version']!r} does not match release {version!r}")
    actual = hashes_from_dist(dist_dir, version)
    artifacts = manifest["artifacts"]
    assert isinstance(artifacts, dict)
    mismatches = [
        f"  {suffix}: manifest {artifacts[suffix]['sha256']} != built {actual[suffix]}"
        for suffix in ARTIFACT_SUFFIXES
        if artifacts[suffix]["sha256"] != actual[suffix]
    ]
    if mismatches:
        raise RuntimeError(
            "rebuilt runtime archives do not match the committed runtime manifest:\n" + "\n".join(mismatches)
        )
    print(f"rebuilt runtime archives match the runtime manifest for {version}")
