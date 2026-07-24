#!/usr/bin/env python3
"""Resolve and validate a local Java agent without downloading anything.

The resolver turns an available JAR into an explicit verification pin: absolute
path, implementation version, premain class, and SHA-256.  It deliberately
keeps that fact separate from production-version parity, which cannot be
claimed unless the caller supplies a source-derived expected version.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import stat
import struct
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from secure_output import (
    SecureOutputError,
    authenticate_directory,
    descriptor_operations_supported,
    path_is_link_or_reparse,
    require_same_directory,
    write_text,
)


SCHEMA_VERSION = 1
MAX_CONFIG_FILES = 4_000
MAX_CONFIG_BYTES = 2_000_000
MAX_CONFIG_ENTRY_VISITS = MAX_CONFIG_FILES * 16
MAX_CONFIG_DIRECTORY_DEPTH = 128
MAX_CANDIDATES = 256
MAX_CANDIDATE_VISITS = MAX_CANDIDATES * 4
MAX_MANIFEST_BYTES = 256_000
MAX_AGENT_BYTES = 512_000_000
MAX_ZIP_ENTRIES = 40_000
MAX_ZIP_CENTRAL_DIRECTORY_BYTES = 64_000_000
ZIP_EOCD_MIN_BYTES = 22
ZIP_MAX_COMMENT_BYTES = 65_535
ZIP_EOCD_SIGNATURE = b"PK\x05\x06"
ZIP_CENTRAL_HEADER_BYTES = 46
ZIP_CENTRAL_SIGNATURE = b"PK\x01\x02"

SKIP_DIRECTORIES = {
    ".git",
    ".gradle",
    ".idea",
    ".terraform",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
    "vendor",
}
CONFIG_NAMES = {
    ".gitlab-ci.yml",
    "Dockerfile",
    "Jenkinsfile",
    "Makefile",
    "Taskfile.yml",
    "build.gradle",
    "build.gradle.kts",
    "docker-compose.yml",
    "docker-compose.yaml",
    "gradle.properties",
    "justfile",
    "pom.xml",
}
CONFIG_SUFFIXES = {
    ".conf",
    ".env",
    ".json",
    ".kts",
    ".properties",
    ".sh",
    ".toml",
    ".xml",
    ".yaml",
    ".yml",
}
AGENT_PATH_PATTERN = re.compile(
    r"-javaagent:(?:\"(?P<double>[^\"]+?\.jar)\"|"
    r"'(?P<single>[^']+?\.jar)'|(?P<plain>[^\s\"']+?\.jar))",
    re.IGNORECASE,
)
SEMVER_IDENTIFIER = r"[0-9A-Za-z-]+"
SEMVER_PATTERN_TEXT = (
    r"(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    rf"(?:-(?P<prerelease>{SEMVER_IDENTIFIER}(?:\.{SEMVER_IDENTIFIER})*))?"
    rf"(?:\+(?P<build>{SEMVER_IDENTIFIER}(?:\.{SEMVER_IDENTIFIER})*))?"
)
VERSION_PATTERN = re.compile(
    rf"(?<!\d)(?P<version>{SEMVER_PATTERN_TEXT})(?![0-9A-Za-z.+-])"
)
FULL_VERSION_PATTERN = re.compile(rf"^(?P<version>{SEMVER_PATTERN_TEXT})$")
RECOGNIZED_PREMAIN_CLASSES = {
    "splunk": "com.splunk.opentelemetry.javaagent.SplunkAgent",
    "opentelemetry": "io.opentelemetry.javaagent.OpenTelemetryAgent",
}
PREMAIN_CLASS_FAMILIES = {
    premain_class: family
    for family, premain_class in RECOGNIZED_PREMAIN_CLASSES.items()
}
ENV_AGENT_OPTIONS = (
    "JAVA_TOOL_OPTIONS",
    "JDK_JAVA_OPTIONS",
    "MAVEN_OPTS",
    "GRADLE_OPTS",
)
ENV_AGENT_PATHS = (
    "OTEL_JAVAAGENT_PATH",
    "OTEL_JAVA_AGENT_PATH",
    "SPLUNK_OTEL_AGENT",
    "JAVAAGENT_PATH",
)
ZIP_CANDIDATE_ERRORS = (
    EOFError,
    NotImplementedError,
    OSError,
    RuntimeError,
    ValueError,
    zipfile.BadZipFile,
    zipfile.LargeZipFile,
)


@dataclass(frozen=True)
class RootedCandidateAuthority:
    """Identity chain binding a discovered leaf to one authenticated root."""

    root: Path
    root_identity: tuple[int, int]
    parent_parts: tuple[str, ...]
    parent_identities: tuple[tuple[int, int], ...]
    leaf_name: str
    leaf_stability: tuple[int, int, int, int, int]


@dataclass(frozen=True)
class CandidateReference:
    path: Path
    source: str
    evidence: str
    authority: RootedCandidateAuthority | None = None

    def __iter__(self):
        # Preserve the historical three-value interface used by callers/tests.
        yield self.path
        yield self.source
        yield self.evidence

    def __getitem__(self, index: int):
        return (self.path, self.source, self.evidence)[index]


@dataclass(frozen=True)
class CoalescedCandidate:
    path: Path
    source: str
    evidence: list[str]
    authority: RootedCandidateAuthority | None = None


@dataclass(frozen=True)
class AuthenticatedScanRoot:
    path: Path
    identity: tuple[int, int]
    evidence: str


@dataclass(frozen=True)
class DirectoryCursor:
    parts: tuple[str, ...] = ()
    identities: tuple[tuple[int, int], ...] = ()


def parse_manifest(payload: bytes) -> dict[str, str]:
    """Parse the manifest's main section, including continuation lines."""

    attributes: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in payload.decode("utf-8", errors="replace").splitlines():
        if not raw_line:
            break
        if raw_line.startswith(" ") and current_key is not None:
            attributes[current_key] += raw_line[1:]
            continue
        if ":" not in raw_line:
            current_key = None
            continue
        key, value = raw_line.split(":", 1)
        current_key = key.strip()
        attributes[current_key] = value.lstrip()
    return attributes


def manifest_value(attributes: dict[str, str], name: str) -> str:
    expected = name.lower()
    return next(
        (value for key, value in attributes.items() if key.lower() == expected),
        "",
    )


def file_identity(status: os.stat_result) -> tuple[int, int]:
    return status.st_dev, status.st_ino


def file_stability(status: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        status.st_dev,
        status.st_ino,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def candidate_directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def open_rooted_directory_descriptor(
    authority: RootedCandidateAuthority,
) -> int:
    """Reopen an authenticated candidate parent without following components."""

    descriptor = os.open(authority.root, candidate_directory_flags())
    try:
        if file_identity(os.fstat(descriptor)) != authority.root_identity:
            raise OSError("candidate discovery root changed")
        for component, expected_identity in zip(
            authority.parent_parts,
            authority.parent_identities,
            strict=True,
        ):
            child = os.open(
                component,
                candidate_directory_flags(),
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
            if file_identity(os.fstat(descriptor)) != expected_identity:
                raise OSError("candidate parent changed after discovery")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def rooted_candidate_namespace_matches(
    authority: RootedCandidateAuthority,
    expected_file: os.stat_result,
) -> bool:
    """Confirm the discovered root-to-leaf namespace still names this file."""

    if descriptor_operations_supported():
        descriptor: int | None = None
        try:
            descriptor = open_rooted_directory_descriptor(authority)
            current = os.stat(
                authority.leaf_name,
                dir_fd=descriptor,
                follow_symlinks=False,
            )
            return (
                not path_is_link_or_reparse(current)
                and stat.S_ISREG(current.st_mode)
                and file_identity(current) == file_identity(expected_file)
                and file_stability(current) == authority.leaf_stability
            )
        except OSError:
            return False
        finally:
            if descriptor is not None:
                os.close(descriptor)

    current = authority.root
    try:
        root_status = os.lstat(current)
        if (
            path_is_link_or_reparse(root_status)
            or not stat.S_ISDIR(root_status.st_mode)
            or file_identity(root_status) != authority.root_identity
        ):
            return False
        for component, expected_identity in zip(
            authority.parent_parts,
            authority.parent_identities,
            strict=True,
        ):
            current = current / component
            details = os.lstat(current)
            if (
                path_is_link_or_reparse(details)
                or not stat.S_ISDIR(details.st_mode)
                or file_identity(details) != expected_identity
            ):
                return False
        leaf = os.lstat(current / authority.leaf_name)
        return (
            not path_is_link_or_reparse(leaf)
            and stat.S_ISREG(leaf.st_mode)
            and file_identity(leaf) == file_identity(expected_file)
            and file_stability(leaf) == authority.leaf_stability
        )
    except OSError:
        return False


def open_rooted_candidate_descriptor(
    authority: RootedCandidateAuthority,
) -> tuple[Path, int]:
    """Open exactly the leaf authenticated during rooted discovery."""

    resolved = authority.root.joinpath(
        *authority.parent_parts,
        authority.leaf_name,
    )
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    if descriptor_operations_supported():
        parent = open_rooted_directory_descriptor(authority)
        try:
            current = os.stat(
                authority.leaf_name,
                dir_fd=parent,
                follow_symlinks=False,
            )
            if (
                path_is_link_or_reparse(current)
                or not stat.S_ISREG(current.st_mode)
                or file_stability(current) != authority.leaf_stability
            ):
                raise OSError("candidate leaf changed after discovery")
            descriptor = os.open(authority.leaf_name, flags, dir_fd=parent)
        finally:
            os.close(parent)
        opened = os.fstat(descriptor)
        if file_stability(opened) != authority.leaf_stability:
            os.close(descriptor)
            raise OSError("candidate leaf changed while opening")
        return resolved, descriptor

    if not rooted_candidate_namespace_matches(
        authority,
        _status_from_stability(authority.leaf_stability),
    ):
        raise OSError("candidate namespace changed after discovery")
    before = os.lstat(resolved)
    descriptor = os.open(resolved, flags)
    opened = os.fstat(descriptor)
    if (
        file_stability(before) != authority.leaf_stability
        or file_stability(opened) != authority.leaf_stability
        or not rooted_candidate_namespace_matches(authority, opened)
    ):
        os.close(descriptor)
        raise OSError("candidate leaf changed while opening")
    return resolved, descriptor


def _status_from_stability(
    stability: tuple[int, int, int, int, int],
) -> Any:
    """Provide the identity fields used by the portable namespace predicate."""

    class ExpectedStatus:
        st_dev, st_ino, st_size, st_mtime_ns, st_ctime_ns = stability

    return ExpectedStatus()


def open_candidate_descriptor(
    path: Path,
    authority: RootedCandidateAuthority | None = None,
) -> tuple[
    Path,
    int,
    list[tuple[Path, tuple[int, int]]],
    RootedCandidateAuthority | None,
]:
    """Open one canonical candidate without following its final pathname."""

    if authority is not None:
        resolved, descriptor = open_rooted_candidate_descriptor(authority)
        return resolved, descriptor, [], authority

    resolved = path.expanduser().resolve(strict=True)
    parent_identities: list[tuple[Path, tuple[int, int]]] = []
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    if descriptor_operations_supported():
        anchor = Path(resolved.anchor)
        parent_descriptor = os.open(anchor, candidate_directory_flags())
        try:
            current = anchor
            parent_identities.append(
                (current, file_identity(os.fstat(parent_descriptor)))
            )
            for component in resolved.parent.relative_to(anchor).parts:
                child = os.open(
                    component,
                    candidate_directory_flags(),
                    dir_fd=parent_descriptor,
                )
                os.close(parent_descriptor)
                parent_descriptor = child
                current = current / component
                parent_identities.append(
                    (current, file_identity(os.fstat(parent_descriptor)))
                )
            descriptor = os.open(
                resolved.name, file_flags, dir_fd=parent_descriptor
            )
        finally:
            os.close(parent_descriptor)
        return resolved, descriptor, parent_identities, None

    current = Path(resolved.anchor)
    for component in (None, *resolved.parent.relative_to(current).parts):
        if component is not None:
            current = current / component
        status = os.lstat(current)
        if path_is_link_or_reparse(status) or not stat.S_ISDIR(status.st_mode):
            raise OSError(f"candidate parent is a link or reparse point: {current}")
        parent_identities.append((current, file_identity(status)))
    status = os.lstat(resolved)
    if path_is_link_or_reparse(status) or not stat.S_ISREG(status.st_mode):
        raise OSError("candidate is not a real regular file")
    descriptor = os.open(resolved, file_flags)
    if file_identity(os.fstat(descriptor)) != file_identity(status):
        os.close(descriptor)
        raise OSError("candidate changed before it was opened")
    return resolved, descriptor, parent_identities, None


def candidate_namespace_matches(
    path: Path,
    expected_file: os.stat_result,
    parents: list[tuple[Path, tuple[int, int]]],
) -> bool:
    for parent, identity in parents:
        try:
            status = os.lstat(parent)
        except OSError:
            return False
        if (
            path_is_link_or_reparse(status)
            or not stat.S_ISDIR(status.st_mode)
            or file_identity(status) != identity
        ):
            return False
    try:
        current = os.lstat(path)
    except OSError:
        return False
    return (
        not path_is_link_or_reparse(current)
        and stat.S_ISREG(current.st_mode)
        and file_identity(current) == file_identity(expected_file)
    )


def parse_semver(
    value: str,
) -> tuple[int, int, int, tuple[str, ...], tuple[str, ...]] | None:
    match = FULL_VERSION_PATTERN.fullmatch(value)
    if match is None:
        return None
    prerelease = tuple((match.group("prerelease") or "").split("."))
    if prerelease == ("",):
        prerelease = ()
    if any(
        identifier.isdigit()
        and len(identifier) > 1
        and identifier.startswith("0")
        for identifier in prerelease
    ):
        return None
    build = tuple((match.group("build") or "").split("."))
    if build == ("",):
        build = ()
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        prerelease,
        build,
    )


def parse_sha256(value: str) -> str:
    normalized = value.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise argparse.ArgumentTypeError("expected SHA-256 must be 64 hexadecimal characters")
    return normalized


def version_from_text(value: str) -> str | None:
    searchable = value[:-4] if value.lower().endswith(".jar") else value
    for match in VERSION_PATTERN.finditer(searchable):
        version = match.group("version")
        if parse_semver(version) is not None:
            return version
    return None


def artifact_version_from_manifest(value: str, family: str) -> str | None:
    if family == "splunk":
        lowered = value.lower()
        marker = lowered.rfind("-otel-")
        if lowered.startswith("splunk-") and marker > len("splunk-"):
            distribution_version = value[len("splunk-") : marker]
            if parse_semver(distribution_version) is not None:
                return distribution_version
    return version_from_text(value)


def version_key(value: str | None) -> tuple[Any, ...]:
    if value is None:
        return (-1, -1, -1, -1, ())
    parsed = parse_semver(value)
    if parsed is None:
        return (-1, -1, -1, -1, ((1, value),))
    major, minor, patch, prerelease, _ = parsed
    stable = 1 if not prerelease else 0
    prerelease_key = tuple(
        (0, int(identifier)) if identifier.isdigit() else (1, identifier)
        for identifier in prerelease
    )
    return (
        major,
        minor,
        patch,
        stable,
        prerelease_key,
    )


def artifact_family_hint(path: Path, manifest: dict[str, str]) -> str | None:
    coordinate_path = path.as_posix().lower()
    filename = path.name.lower()
    implementation_vendor = manifest_value(
        manifest, "Implementation-Vendor"
    ).lower()
    implementation_version = manifest_value(
        manifest, "Implementation-Version"
    ).lower()
    if (
        "splunk" in implementation_vendor
        or implementation_version.startswith("splunk-")
        or "/com/splunk/splunk-otel-javaagent/" in coordinate_path
        or "/com.splunk/splunk-otel-javaagent/" in coordinate_path
        or "splunk-otel-javaagent" in filename
    ):
        return "splunk"
    if (
        "opentelemetry" in implementation_vendor
        or "/io/opentelemetry/javaagent/opentelemetry-javaagent/"
        in coordinate_path
        or "/io.opentelemetry.javaagent/opentelemetry-javaagent/"
        in coordinate_path
        or re.search(r"opentelemetry-javaagent-\d", filename)
    ):
        return "opentelemetry"
    return None


def artifact_family(
    path: Path, manifest: dict[str, str], premain_class: str
) -> tuple[str | None, str | None]:
    premain_family = PREMAIN_CLASS_FAMILIES.get(premain_class)
    if premain_family is None:
        return None, "unrecognized-Premain-Class"
    hinted_family = artifact_family_hint(path, manifest)
    if hinted_family is not None and hinted_family != premain_family:
        return (
            None,
            f"Premain-Class-does-not-match-{hinted_family}-agent-family",
        )
    return premain_family, None


def validate_zip_directory_budget(snapshot: Any) -> None:
    """Reject ZIP directories that would make stdlib metadata unbounded."""

    snapshot.seek(0, os.SEEK_END)
    archive_size = snapshot.tell()
    tail_size = min(
        archive_size,
        ZIP_EOCD_MIN_BYTES + ZIP_MAX_COMMENT_BYTES,
    )
    snapshot.seek(archive_size - tail_size)
    tail = snapshot.read(tail_size)
    position = tail.rfind(ZIP_EOCD_SIGNATURE)
    if position < 0 or position + ZIP_EOCD_MIN_BYTES > len(tail):
        raise zipfile.BadZipFile("missing end-of-central-directory record")
    (
        _,
        disk_number,
        central_disk,
        disk_entries,
        total_entries,
        central_size,
        central_offset,
        comment_size,
    ) = struct.unpack_from("<4s4H2LH", tail, position)
    if position + ZIP_EOCD_MIN_BYTES + comment_size != len(tail):
        raise zipfile.BadZipFile("invalid end-of-central-directory length")
    if disk_number or central_disk or disk_entries != total_entries:
        raise zipfile.BadZipFile("multi-disk ZIP archives are not supported")
    if (
        total_entries == 0xFFFF
        or central_size == 0xFFFFFFFF
        or central_offset == 0xFFFFFFFF
    ):
        raise zipfile.LargeZipFile("ZIP64 Java-agent candidates are not supported")
    if total_entries > MAX_ZIP_ENTRIES:
        raise zipfile.LargeZipFile(
            f"ZIP entry count {total_entries} exceeds {MAX_ZIP_ENTRIES}"
        )
    if central_size > MAX_ZIP_CENTRAL_DIRECTORY_BYTES:
        raise zipfile.LargeZipFile(
            "ZIP central directory exceeds "
            f"{MAX_ZIP_CENTRAL_DIRECTORY_BYTES} bytes"
        )
    if central_offset + central_size > archive_size:
        raise zipfile.BadZipFile("central directory escapes candidate bytes")
    eocd_offset = archive_size - tail_size + position
    central_start = eocd_offset - central_size
    if central_start < central_offset:
        raise zipfile.BadZipFile("central directory offset is inconsistent")

    snapshot.seek(central_start)
    remaining = central_size
    actual_entries = 0
    while remaining:
        if remaining < ZIP_CENTRAL_HEADER_BYTES:
            raise zipfile.BadZipFile("truncated central directory record")
        header = snapshot.read(ZIP_CENTRAL_HEADER_BYTES)
        if (
            len(header) != ZIP_CENTRAL_HEADER_BYTES
            or header[:4] != ZIP_CENTRAL_SIGNATURE
        ):
            raise zipfile.BadZipFile("invalid central directory record")
        filename_size, extra_size, entry_comment_size = struct.unpack_from(
            "<3H", header, 28
        )
        record_size = (
            ZIP_CENTRAL_HEADER_BYTES
            + filename_size
            + extra_size
            + entry_comment_size
        )
        if record_size > remaining:
            raise zipfile.BadZipFile("central directory record escapes its budget")
        actual_entries += 1
        if actual_entries > MAX_ZIP_ENTRIES:
            raise zipfile.LargeZipFile(
                f"ZIP entry count exceeds {MAX_ZIP_ENTRIES}"
            )
        snapshot.seek(record_size - ZIP_CENTRAL_HEADER_BYTES, os.SEEK_CUR)
        remaining -= record_size
    if actual_entries != total_entries:
        raise zipfile.BadZipFile(
            "central directory entry count does not match end-of-directory record"
        )
    snapshot.seek(0)


def validate_candidate(
    path: Path,
    authority: RootedCandidateAuthority | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    descriptor: int | None = None
    try:
        resolved, descriptor, parent_identities, rooted_authority = (
            open_candidate_descriptor(path, authority)
        )
    except (FileNotFoundError, OSError) as error:
        return None, f"not-readable: {error}"
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            return None, "not-a-regular-file"
        if before.st_size > MAX_AGENT_BYTES:
            return None, "agent-jar-too-large"
        digest = hashlib.sha256()
        with tempfile.TemporaryFile() as snapshot:
            total = 0
            while chunk := os.read(descriptor, 1024 * 1024):
                total += len(chunk)
                if total > MAX_AGENT_BYTES:
                    return None, "agent-jar-too-large"
                digest.update(chunk)
                snapshot.write(chunk)
            after = os.fstat(descriptor)
            if file_stability(before) != file_stability(after):
                return None, "jar-changed-during-validation"
            namespace_matches = (
                rooted_candidate_namespace_matches(rooted_authority, before)
                if rooted_authority is not None
                else candidate_namespace_matches(
                    resolved, before, parent_identities
                )
            )
            if not namespace_matches:
                return None, "jar-path-changed-during-validation"
            snapshot.seek(0)
            try:
                validate_zip_directory_budget(snapshot)
                with zipfile.ZipFile(snapshot) as archive:
                    manifest_infos = [
                        info
                        for info in archive.infolist()
                        if info.filename.upper() == "META-INF/MANIFEST.MF"
                    ]
                    if len(manifest_infos) != 1:
                        return None, "missing-or-duplicate-META-INF/MANIFEST.MF"
                    manifest_info = manifest_infos[0]
                    if manifest_info.file_size > MAX_MANIFEST_BYTES:
                        return None, "manifest-too-large"
                    manifest = parse_manifest(archive.read(manifest_info))
            except KeyError:
                return None, "missing-META-INF/MANIFEST.MF"
            except ZIP_CANDIDATE_ERRORS as error:
                return None, f"invalid-jar: {error}"
    finally:
        if descriptor is not None:
            os.close(descriptor)
    premain_class = manifest_value(manifest, "Premain-Class").strip()
    if not premain_class:
        return None, "missing-Premain-Class"
    family, family_error = artifact_family(resolved, manifest, premain_class)
    if family is None:
        return None, family_error or "unrecognized-Java-agent-family"
    implementation_version = manifest_value(
        manifest, "Implementation-Version"
    ).strip()
    artifact_version = artifact_version_from_manifest(
        implementation_version, family
    )
    version_source = "manifest" if artifact_version is not None else "filename"
    if artifact_version is None:
        artifact_version = version_from_text(resolved.name)
    namespace_matches = (
        rooted_candidate_namespace_matches(rooted_authority, before)
        if rooted_authority is not None
        else candidate_namespace_matches(resolved, before, parent_identities)
    )
    if not namespace_matches:
        return None, "jar-path-changed-during-validation"
    coordinate = (
        "com.splunk:splunk-otel-javaagent"
        if family == "splunk"
        else "io.opentelemetry.javaagent:opentelemetry-javaagent"
    )
    return (
        {
            "path": str(resolved),
            "coordinate": coordinate,
            "sha256": digest.hexdigest(),
            "size_bytes": before.st_size,
            "artifact_identity": {
                "device": before.st_dev,
                "inode": before.st_ino,
            },
            "premain_class": premain_class,
            "implementation_vendor": manifest_value(
                manifest, "Implementation-Vendor"
            ).strip(),
            "implementation_version": implementation_version or None,
            "artifact_version": artifact_version,
            "version_source": version_source,
            "family": family,
            "javaagent_argv": [f"-javaagent:{resolved}"],
        },
        None,
    )


def is_config_file(path: Path) -> bool:
    name = path.name
    return (
        name in CONFIG_NAMES
        or name.startswith("Dockerfile.")
        or name.startswith(".env")
        or path.suffix.lower() in CONFIG_SUFFIXES
    )


@dataclass(frozen=True)
class ConfigSnapshot:
    path: Path
    text: str


@dataclass
class BoundedOmission:
    reason: str
    omitted_count: int
    omitted_unit: str
    count_is_lower_bound: bool
    limit: int
    limit_unit: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "omitted_count": self.omitted_count,
            "omitted_unit": self.omitted_unit,
            "count_is_lower_bound": self.count_is_lower_bound,
            "limit": self.limit,
            "limit_unit": self.limit_unit,
        }


def record_bounded_omission(
    omissions: list[BoundedOmission] | None,
    *,
    reason: str,
    omitted_count: int = 1,
    omitted_unit: str,
    count_is_lower_bound: bool,
    limit: int,
    limit_unit: str,
) -> None:
    if omissions is None or omitted_count <= 0:
        return
    for existing in omissions:
        if (
            existing.reason == reason
            and existing.omitted_unit == omitted_unit
            and existing.limit == limit
            and existing.limit_unit == limit_unit
        ):
            existing.omitted_count += omitted_count
            existing.count_is_lower_bound = (
                existing.count_is_lower_bound or count_is_lower_bound
            )
            return
    omissions.append(
        BoundedOmission(
            reason=reason,
            omitted_count=omitted_count,
            omitted_unit=omitted_unit,
            count_is_lower_bound=count_is_lower_bound,
            limit=limit,
            limit_unit=limit_unit,
        )
    )


def authenticate_scan_root(
    root: Path,
    source: str,
    omissions: list[BoundedOmission] | None,
    *,
    allow_link_root: bool,
) -> AuthenticatedScanRoot | None:
    """Bind discovery to one canonical directory or make incompleteness explicit."""

    raw = Path(os.path.abspath(root.expanduser()))
    try:
        raw_status = os.lstat(raw)
    except FileNotFoundError:
        return None
    except (OSError, RuntimeError):
        record_bounded_omission(
            omissions,
            reason=f"{source}_root_authentication_error",
            omitted_unit="roots",
            count_is_lower_bound=False,
            limit=1,
            limit_unit="root",
        )
        return None
    if path_is_link_or_reparse(raw_status) and not allow_link_root:
        record_bounded_omission(
            omissions,
            reason=f"{source}_linked_root",
            omitted_unit="roots",
            count_is_lower_bound=False,
            limit=1,
            limit_unit="root",
        )
        return None
    try:
        canonical = raw.resolve(strict=True)
        canonical_status = os.lstat(canonical)
        if (
            path_is_link_or_reparse(canonical_status)
            or not stat.S_ISDIR(canonical_status.st_mode)
        ):
            raise OSError("resolved discovery root is not a real directory")
        if descriptor_operations_supported():
            descriptor = os.open(canonical, candidate_directory_flags())
            try:
                opened = os.fstat(descriptor)
                if (
                    not stat.S_ISDIR(opened.st_mode)
                    or file_identity(opened) != file_identity(canonical_status)
                ):
                    raise OSError("discovery root changed while opening")
            finally:
                os.close(descriptor)
    except (OSError, RuntimeError):
        record_bounded_omission(
            omissions,
            reason=f"{source}_root_authentication_error",
            omitted_unit="roots",
            count_is_lower_bound=False,
            limit=1,
            limit_unit="root",
        )
        return None
    return AuthenticatedScanRoot(
        path=canonical,
        identity=file_identity(canonical_status),
        evidence=str(raw),
    )


def portable_cursor_matches(
    root: AuthenticatedScanRoot,
    cursor: DirectoryCursor,
) -> bool:
    current = root.path
    try:
        details = os.lstat(current)
        if (
            path_is_link_or_reparse(details)
            or not stat.S_ISDIR(details.st_mode)
            or file_identity(details) != root.identity
        ):
            return False
        for component, expected in zip(
            cursor.parts,
            cursor.identities,
            strict=True,
        ):
            current = current / component
            details = os.lstat(current)
            if (
                path_is_link_or_reparse(details)
                or not stat.S_ISDIR(details.st_mode)
                or file_identity(details) != expected
            ):
                return False
        return True
    except OSError:
        return False


def open_scan_cursor(
    root: AuthenticatedScanRoot,
    cursor: DirectoryCursor,
) -> tuple[int | None, Path]:
    path = root.path.joinpath(*cursor.parts)
    if descriptor_operations_supported() and os.scandir in os.supports_fd:
        descriptor = os.open(root.path, candidate_directory_flags())
        try:
            if file_identity(os.fstat(descriptor)) != root.identity:
                raise OSError("discovery root changed")
            for component, expected in zip(
                cursor.parts,
                cursor.identities,
                strict=True,
            ):
                child = os.open(
                    component,
                    candidate_directory_flags(),
                    dir_fd=descriptor,
                )
                os.close(descriptor)
                descriptor = child
                if file_identity(os.fstat(descriptor)) != expected:
                    raise OSError("queued directory changed")
            return descriptor, path
        except BaseException:
            os.close(descriptor)
            raise
    if not portable_cursor_matches(root, cursor):
        raise OSError("queued directory changed")
    return None, path


def bounded_sorted_names(
    target: int | Path,
    remaining_visits: int,
) -> list[str] | None:
    """Return a deterministic directory inventory without retaining an overflow."""

    names: list[str] = []
    with os.scandir(target) as entries:
        for entry in entries:
            names.append(entry.name)
            if len(names) > remaining_visits:
                return None
    return sorted(names)


def cursor_entry_status(
    descriptor: int | None,
    directory: Path,
    name: str,
) -> os.stat_result:
    if descriptor is not None:
        return os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    return os.lstat(directory / name)


def rooted_authority(
    root: AuthenticatedScanRoot,
    cursor: DirectoryCursor,
    name: str,
    details: os.stat_result,
) -> RootedCandidateAuthority:
    return RootedCandidateAuthority(
        root=root.path,
        root_identity=root.identity,
        parent_parts=cursor.parts,
        parent_identities=cursor.identities,
        leaf_name=name,
        leaf_stability=file_stability(details),
    )


def read_bounded_descriptor(descriptor: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while total <= maximum:
        chunk = os.read(
            descriptor,
            min(1024 * 1024, maximum + 1 - total),
        )
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def record_config_omission(
    omissions: list[BoundedOmission] | None,
    reason: str,
) -> None:
    """Record a failed config scope whose hidden contents are not enumerable."""

    record_bounded_omission(
        omissions,
        reason=reason,
        omitted_unit="config scopes",
        count_is_lower_bound=True,
        limit=MAX_CONFIG_FILES,
        limit_unit="config files",
    )


def record_config_entry_limit(
    omissions: list[BoundedOmission] | None,
) -> None:
    record_bounded_omission(
        omissions,
        reason="config_entry_visit_limit",
        omitted_unit="entries",
        count_is_lower_bound=True,
        limit=MAX_CONFIG_ENTRY_VISITS,
        limit_unit="entries",
    )


def descriptor_config_snapshots(
    project: Path,
    root_descriptor: int,
    root_identity: tuple[int, int] | None,
    bounded_omissions: list[BoundedOmission] | None = None,
) -> list[ConfigSnapshot]:
    """Read config bytes through one retained, no-follow directory tree."""

    snapshots: list[ConfigSnapshot] = []
    seen = 0
    entry_visits = 0
    directory_flags = candidate_directory_flags()
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.dup(root_descriptor)
        root_status = os.fstat(descriptor)
    except OSError:
        record_config_omission(
            bounded_omissions,
            "config_identity_chain_error",
        )
        return snapshots
    if root_identity is not None and file_identity(root_status) != root_identity:
        os.close(descriptor)
        record_config_omission(
            bounded_omissions,
            "config_identity_chain_error",
        )
        return snapshots

    def visit(
        directory_descriptor: int,
        relative: Path,
        depth: int = 0,
    ) -> bool:
        nonlocal seen, entry_visits
        if depth > MAX_CONFIG_DIRECTORY_DEPTH:
            record_bounded_omission(
                bounded_omissions,
                reason="config_directory_depth_limit",
                omitted_unit="directories",
                count_is_lower_bound=True,
                limit=MAX_CONFIG_DIRECTORY_DEPTH,
                limit_unit="directory levels",
            )
            return True
        try:
            names = bounded_sorted_names(
                directory_descriptor,
                MAX_CONFIG_ENTRY_VISITS - entry_visits,
            )
        except OSError:
            record_config_omission(
                bounded_omissions,
                "config_directory_list_error",
            )
            return True
        if names is None:
            record_config_entry_limit(bounded_omissions)
            return True
        entry_visits += len(names)

        directories: list[tuple[str, os.stat_result]] = []
        files: list[tuple[str, os.stat_result]] = []
        for name in names:
            try:
                details = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except OSError:
                record_config_omission(
                    bounded_omissions,
                    "config_entry_stat_error",
                )
                return True
            if path_is_link_or_reparse(details):
                if name in SKIP_DIRECTORIES or (
                    relative == Path(".observe") and name == "evidence"
                ):
                    continue
                record_config_omission(
                    bounded_omissions,
                    "config_child_directory_error",
                )
                return True
            if stat.S_ISDIR(details.st_mode):
                directories.append((name, details))
            else:
                files.append((name, details))

        for name, details in files:
            relative_path = relative / name
            path = project / relative_path
            if not is_config_file(path):
                continue
            seen += 1
            if seen > MAX_CONFIG_FILES:
                record_bounded_omission(
                    bounded_omissions,
                    reason="config_file_count_limit",
                    omitted_unit="files",
                    count_is_lower_bound=True,
                    limit=MAX_CONFIG_FILES,
                    limit_unit="files",
                )
                return True
            if path_is_link_or_reparse(details) or not stat.S_ISREG(
                details.st_mode
            ):
                record_config_omission(
                    bounded_omissions,
                    "config_file_identity_error",
                )
                return True
            if details.st_size > MAX_CONFIG_BYTES:
                record_bounded_omission(
                    bounded_omissions,
                    reason="config_file_size_limit",
                    omitted_unit="files",
                    count_is_lower_bound=False,
                    limit=MAX_CONFIG_BYTES,
                    limit_unit="bytes",
                )
                continue
            file_descriptor: int | None = None
            try:
                file_descriptor = os.open(
                    name,
                    file_flags,
                    dir_fd=directory_descriptor,
                )
                opened = os.fstat(file_descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or file_identity(opened) != file_identity(details)
                ):
                    record_config_omission(
                        bounded_omissions,
                        "config_file_identity_error",
                    )
                    return True
                try:
                    payload = read_bounded_descriptor(
                        file_descriptor,
                        MAX_CONFIG_BYTES,
                    )
                except OSError:
                    record_config_omission(
                        bounded_omissions,
                        "config_file_read_error",
                    )
                    return True
                after = os.fstat(file_descriptor)
                current = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                if len(payload) > MAX_CONFIG_BYTES:
                    record_bounded_omission(
                        bounded_omissions,
                        reason="config_file_size_limit",
                        omitted_unit="files",
                        count_is_lower_bound=False,
                        limit=MAX_CONFIG_BYTES,
                        limit_unit="bytes",
                    )
                    continue
                if (
                    file_stability(opened) != file_stability(after)
                    or path_is_link_or_reparse(current)
                    or not stat.S_ISREG(current.st_mode)
                    or file_identity(current) != file_identity(opened)
                ):
                    record_config_omission(
                        bounded_omissions,
                        "config_file_identity_error",
                    )
                    return True
            except OSError:
                record_config_omission(
                    bounded_omissions,
                    "config_file_open_error",
                )
                return True
            finally:
                if file_descriptor is not None:
                    os.close(file_descriptor)
            snapshots.append(
                ConfigSnapshot(
                    path=path,
                    text=payload.decode("utf-8", errors="replace"),
                )
            )

        for name, details in directories:
            if name in SKIP_DIRECTORIES or (
                relative == Path(".observe") and name == "evidence"
            ):
                continue
            if path_is_link_or_reparse(details):
                record_config_omission(
                    bounded_omissions,
                    "config_child_directory_error",
                )
                return True
            child: int | None = None
            try:
                child = os.open(
                    name,
                    directory_flags,
                    dir_fd=directory_descriptor,
                )
                opened = os.fstat(child)
                if (
                    not stat.S_ISDIR(opened.st_mode)
                    or file_identity(opened) != file_identity(details)
                ):
                    record_config_omission(
                        bounded_omissions,
                        "config_identity_chain_error",
                    )
                    return True
                if visit(child, relative / name, depth + 1):
                    return True
            except OSError:
                record_config_omission(
                    bounded_omissions,
                    "config_child_directory_error",
                )
                return True
            finally:
                if child is not None:
                    os.close(child)
        return False

    try:
        try:
            root_status = os.fstat(descriptor)
        except OSError:
            record_config_omission(
                bounded_omissions,
                "config_identity_chain_error",
            )
        else:
            if stat.S_ISDIR(root_status.st_mode):
                visit(descriptor, Path())
            else:
                record_config_omission(
                    bounded_omissions,
                    "config_identity_chain_error",
                )
    finally:
        os.close(descriptor)
    return snapshots


def portable_config_chain(
    project: Path,
    parent: Path,
    root_identity: tuple[int, int] | None,
) -> list[tuple[Path, tuple[int, int]]]:
    try:
        relative = parent.relative_to(project)
    except ValueError as error:
        raise OSError(f"config path escapes project root: {parent}") from error
    identities: list[tuple[Path, tuple[int, int]]] = []
    current = project
    for component in (None, *relative.parts):
        if component is not None:
            current = current / component
        details = os.lstat(current)
        if path_is_link_or_reparse(details) or not stat.S_ISDIR(details.st_mode):
            raise OSError(f"config parent is a link or reparse point: {current}")
        identity = file_identity(details)
        if not identities and root_identity is not None and identity != root_identity:
            raise OSError("project root changed during config discovery")
        identities.append((current, identity))
    return identities


def portable_config_chain_matches(
    identities: list[tuple[Path, tuple[int, int]]],
) -> bool:
    for path, expected in identities:
        try:
            details = os.lstat(path)
        except OSError:
            return False
        if (
            path_is_link_or_reparse(details)
            or not stat.S_ISDIR(details.st_mode)
            or file_identity(details) != expected
        ):
            return False
    return True


def portable_config_snapshot(
    project: Path,
    path: Path,
    expected: os.stat_result,
    root_identity: tuple[int, int] | None,
    bounded_omissions: list[BoundedOmission] | None = None,
) -> ConfigSnapshot | None:
    try:
        parents = portable_config_chain(project, path.parent, root_identity)
    except OSError:
        record_config_omission(
            bounded_omissions,
            "config_identity_chain_error",
        )
        return None
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError:
        record_config_omission(
            bounded_omissions,
            "config_file_open_error",
        )
        return None
    try:
        try:
            opened = os.fstat(descriptor)
            current = os.lstat(path)
        except OSError:
            record_config_omission(
                bounded_omissions,
                "config_entry_stat_error",
            )
            return None
        if (
            not stat.S_ISREG(opened.st_mode)
            or file_identity(opened) != file_identity(expected)
            or path_is_link_or_reparse(current)
            or file_identity(current) != file_identity(opened)
            or not portable_config_chain_matches(parents)
        ):
            record_config_omission(
                bounded_omissions,
                "config_file_identity_error",
            )
            return None
        try:
            payload = read_bounded_descriptor(descriptor, MAX_CONFIG_BYTES)
        except OSError:
            record_config_omission(
                bounded_omissions,
                "config_file_read_error",
            )
            return None
        try:
            after = os.fstat(descriptor)
            current = os.lstat(path)
        except OSError:
            record_config_omission(
                bounded_omissions,
                "config_entry_stat_error",
            )
            return None
        if len(payload) > MAX_CONFIG_BYTES:
            record_bounded_omission(
                bounded_omissions,
                reason="config_file_size_limit",
                omitted_unit="files",
                count_is_lower_bound=False,
                limit=MAX_CONFIG_BYTES,
                limit_unit="bytes",
            )
            return None
        if (
            file_stability(opened) != file_stability(after)
            or path_is_link_or_reparse(current)
            or file_identity(current) != file_identity(opened)
            or not portable_config_chain_matches(parents)
        ):
            record_config_omission(
                bounded_omissions,
                "config_file_identity_error",
            )
            return None
        return ConfigSnapshot(
            path=path,
            text=payload.decode("utf-8", errors="replace"),
        )
    except OSError:
        record_config_omission(
            bounded_omissions,
            "config_file_read_error",
        )
        return None
    finally:
        os.close(descriptor)


def portable_config_snapshots(
    project: Path,
    root_identity: tuple[int, int] | None,
    bounded_omissions: list[BoundedOmission] | None = None,
) -> list[ConfigSnapshot]:
    snapshots: list[ConfigSnapshot] = []
    seen = 0
    entry_visits = 0
    pending = [(project, 0)]
    while pending:
        current, depth = pending.pop()
        if depth > MAX_CONFIG_DIRECTORY_DEPTH:
            record_bounded_omission(
                bounded_omissions,
                reason="config_directory_depth_limit",
                omitted_unit="directories",
                count_is_lower_bound=True,
                limit=MAX_CONFIG_DIRECTORY_DEPTH,
                limit_unit="directory levels",
            )
            return snapshots
        try:
            portable_config_chain(project, current, root_identity)
        except OSError:
            record_config_omission(
                bounded_omissions,
                "config_identity_chain_error",
            )
            return snapshots
        try:
            names = bounded_sorted_names(
                current,
                MAX_CONFIG_ENTRY_VISITS - entry_visits,
            )
        except OSError:
            record_config_omission(
                bounded_omissions,
                "config_walk_error",
            )
            return snapshots
        if names is None:
            record_config_entry_limit(bounded_omissions)
            return snapshots
        entry_visits += len(names)

        relative = current.relative_to(project)
        directories: list[tuple[Path, int]] = []
        for name in names:
            path = current / name
            try:
                details = os.lstat(path)
            except OSError:
                record_config_omission(
                    bounded_omissions,
                    "config_entry_stat_error",
                )
                return snapshots
            if path_is_link_or_reparse(details):
                if name in SKIP_DIRECTORIES or (
                    relative == Path(".observe") and name == "evidence"
                ):
                    continue
                record_config_omission(
                    bounded_omissions,
                    "config_child_directory_error",
                )
                return snapshots
            if stat.S_ISDIR(details.st_mode):
                if name in SKIP_DIRECTORIES or (
                    relative == Path(".observe") and name == "evidence"
                ):
                    continue
                directories.append((path, depth + 1))
                continue
            if not is_config_file(path):
                continue
            seen += 1
            if seen > MAX_CONFIG_FILES:
                record_bounded_omission(
                    bounded_omissions,
                    reason="config_file_count_limit",
                    omitted_unit="files",
                    count_is_lower_bound=True,
                    limit=MAX_CONFIG_FILES,
                    limit_unit="files",
                )
                return snapshots
            if not stat.S_ISREG(details.st_mode):
                record_config_omission(
                    bounded_omissions,
                    "config_file_identity_error",
                )
                return snapshots
            if details.st_size > MAX_CONFIG_BYTES:
                record_bounded_omission(
                    bounded_omissions,
                    reason="config_file_size_limit",
                    omitted_unit="files",
                    count_is_lower_bound=False,
                    limit=MAX_CONFIG_BYTES,
                    limit_unit="bytes",
                )
                return snapshots
            snapshot = portable_config_snapshot(
                project,
                path,
                details,
                root_identity,
                bounded_omissions,
            )
            if snapshot is None:
                return snapshots
            snapshots.append(snapshot)
        pending.extend(
            sorted(directories, key=lambda item: item[0], reverse=True)
        )
    return snapshots


def collect_config_snapshots(
    project: Path,
    *,
    root_descriptor: int | None = None,
    root_identity: tuple[int, int] | None = None,
    bounded_omissions: list[BoundedOmission] | None = None,
) -> list[ConfigSnapshot]:
    if (
        descriptor_operations_supported()
        and os.scandir in os.supports_fd
        and root_descriptor is not None
    ):
        return descriptor_config_snapshots(
            project,
            root_descriptor,
            root_identity,
            bounded_omissions,
        )
    return portable_config_snapshots(
        project,
        root_identity,
        bounded_omissions,
    )


def expand_path(raw: str, bases: Iterable[Path]) -> list[Path]:
    expanded = os.path.expandvars(os.path.expanduser(raw.strip()))
    if "$" in expanded:
        # Keep unresolved configured paths as non-readable candidates so their
        # provider and version constraints still participate in resolution.
        return [Path(expanded)]
    candidate = Path(expanded)
    if candidate.is_absolute():
        return [candidate]
    return [base / candidate for base in bases]


def source_kind_for_config(path: Path, project: Path) -> str:
    try:
        relative = path.relative_to(project)
    except ValueError:
        return "project_config"
    if relative.parts and relative.parts[0] == ".observe":
        return "prior_verification"
    return "project_config"


def configured_candidates(
    project: Path,
    config_snapshots: list[ConfigSnapshot],
    bounded_omissions: list[BoundedOmission] | None = None,
) -> list[CandidateReference]:
    candidates: list[CandidateReference] = []
    seen: set[tuple[str, str]] = set()
    visits = 0

    def retain(path: Path, source: str, evidence: str) -> bool:
        nonlocal visits
        visits += 1
        if visits > MAX_CANDIDATE_VISITS:
            record_bounded_omission(
                bounded_omissions,
                reason="configured_candidate_visit_limit",
                omitted_unit="candidate visits",
                count_is_lower_bound=True,
                limit=MAX_CANDIDATE_VISITS,
                limit_unit="candidate visits",
            )
            return False
        key = (str(path.expanduser().absolute()), source)
        if key in seen:
            return True
        if len(candidates) >= MAX_CANDIDATES:
            record_bounded_omission(
                bounded_omissions,
                reason="configured_candidate_limit",
                omitted_unit="candidates",
                count_is_lower_bound=True,
                limit=MAX_CANDIDATES,
                limit_unit="candidates",
            )
            return False
        seen.add(key)
        candidates.append(CandidateReference(path, source, evidence))
        return True

    for variable in ENV_AGENT_PATHS:
        value = os.environ.get(variable)
        if not value:
            continue
        for path in expand_path(value, (project,)):
            if not retain(path, "environment", variable):
                return candidates
    for variable in ENV_AGENT_OPTIONS:
        value = os.environ.get(variable, "")
        for match in AGENT_PATH_PATTERN.finditer(value):
            raw = next(group for group in match.groups() if group is not None)
            for path in expand_path(raw, (project,)):
                if not retain(path, "environment", variable):
                    return candidates

    for snapshot in config_snapshots:
        config_path = snapshot.path
        text = snapshot.text
        source_kind = source_kind_for_config(config_path, project)
        for match in AGENT_PATH_PATTERN.finditer(text):
            raw = next(group for group in match.groups() if group is not None)
            line = text.count("\n", 0, match.start()) + 1
            evidence = f"{config_path.relative_to(project)}:{line}"
            for path in expand_path(raw, (config_path.parent, project)):
                if not retain(path, source_kind, evidence):
                    return candidates
    return candidates


def maven_roots(explicit: list[Path]) -> list[Path]:
    if explicit:
        return unique_paths(explicit)
    roots: list[Path] = []
    for variable in ("MAVEN_REPO_LOCAL", "M2_REPO"):
        value = os.environ.get(variable)
        if value:
            roots.append(Path(value))
    settings_path = Path.home() / ".m2" / "settings.xml"
    if settings_path.is_file():
        try:
            root = ElementTree.parse(settings_path).getroot()
            local_repo = next(
                (
                    element.text
                    for element in root.iter()
                    if element.tag.rsplit("}", 1)[-1] == "localRepository"
                    and element.text
                ),
                None,
            )
            if local_repo:
                roots.append(Path(os.path.expandvars(local_repo)).expanduser())
        except (ElementTree.ParseError, OSError):
            pass
    roots.append(Path.home() / ".m2" / "repository")
    return unique_paths(roots)


def gradle_roots(explicit: list[Path]) -> list[Path]:
    if explicit:
        return unique_paths(explicit)
    roots: list[Path] = []
    gradle_home = os.environ.get("GRADLE_USER_HOME")
    if gradle_home:
        roots.append(Path(gradle_home) / "caches" / "modules-2" / "files-2.1")
    roots.append(Path.home() / ".gradle" / "caches" / "modules-2" / "files-2.1")
    return unique_paths(roots)


def unique_paths(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        value = str(path.expanduser().absolute())
        if value not in seen:
            seen.add(value)
            result.append(Path(value))
    return result


def cache_candidates(
    roots: Iterable[Path],
    patterns: Iterable[str],
    source: str,
    bounded_omissions: list[BoundedOmission] | None = None,
) -> list[CandidateReference]:
    result: list[CandidateReference] = []
    seen: set[str] = set()
    visits = 0
    for root in roots:
        authenticated = authenticate_scan_root(
            root,
            source,
            bounded_omissions,
            allow_link_root=True,
        )
        if authenticated is None:
            continue
        for pattern in sorted(patterns):
            parts = Path(pattern).parts
            if not parts or "**" in parts:
                continue
            pending: list[tuple[DirectoryCursor, int]] = [
                (DirectoryCursor(), 0)
            ]
            while pending:
                cursor, index = pending.pop()
                segment = parts[index]
                descriptor: int | None = None
                try:
                    descriptor, directory = open_scan_cursor(
                        authenticated,
                        cursor,
                    )
                    names = bounded_sorted_names(
                        descriptor if descriptor is not None else directory,
                        MAX_CANDIDATE_VISITS - visits,
                    )
                except OSError:
                    record_bounded_omission(
                        bounded_omissions,
                        reason=f"{source}_traversal_error",
                        omitted_unit="directories",
                        count_is_lower_bound=True,
                        limit=MAX_CANDIDATE_VISITS,
                        limit_unit="entries",
                    )
                    return sorted(result, key=lambda item: str(item.path))
                finally:
                    if descriptor is not None:
                        os.close(descriptor)
                if names is None:
                    record_bounded_omission(
                        bounded_omissions,
                        reason=f"{source}_entry_visit_limit",
                        omitted_unit="entries",
                        count_is_lower_bound=True,
                        limit=MAX_CANDIDATE_VISITS,
                        limit_unit="entries",
                    )
                    return sorted(result, key=lambda item: str(item.path))

                descriptor = None
                local_children: list[tuple[DirectoryCursor, int]] = []
                local_candidates: list[CandidateReference] = []
                try:
                    descriptor, directory = open_scan_cursor(
                        authenticated,
                        cursor,
                    )
                    for name in names:
                        visits += 1
                        if (
                            name.startswith(".")
                            and not segment.startswith(".")
                        ) or not fnmatch.fnmatchcase(name, segment):
                            continue
                        details = cursor_entry_status(
                            descriptor,
                            directory,
                            name,
                        )
                        if path_is_link_or_reparse(details):
                            raise OSError(
                                "linked cache entry prevents authenticated traversal"
                            )
                        path = Path(authenticated.evidence).joinpath(
                            *cursor.parts,
                            name,
                        )
                        if index + 1 < len(parts):
                            if stat.S_ISDIR(details.st_mode):
                                local_children.append(
                                    (
                                        DirectoryCursor(
                                            cursor.parts + (name,),
                                            cursor.identities
                                            + (file_identity(details),),
                                        ),
                                        index + 1,
                                    )
                                )
                            continue
                        if not stat.S_ISREG(details.st_mode):
                            continue
                        key = str(path)
                        if key in seen:
                            continue
                        if len(result) + len(local_candidates) >= MAX_CANDIDATES:
                            record_bounded_omission(
                                bounded_omissions,
                                reason=f"{source}_candidate_limit",
                                omitted_unit="candidates",
                                count_is_lower_bound=True,
                                limit=MAX_CANDIDATES,
                                limit_unit="candidates",
                            )
                            return sorted(result + local_candidates, key=lambda item: str(item.path))
                        seen.add(key)
                        local_candidates.append(
                            CandidateReference(
                                path=path,
                                source=source,
                                evidence=authenticated.evidence,
                                authority=rooted_authority(
                                    authenticated,
                                    cursor,
                                    name,
                                    details,
                                ),
                            )
                        )
                    if descriptor is None and not portable_cursor_matches(
                        authenticated,
                        cursor,
                    ):
                        raise OSError("queued directory changed during scan")
                except OSError:
                    record_bounded_omission(
                        bounded_omissions,
                        reason=f"{source}_traversal_error",
                        omitted_unit="directories",
                        count_is_lower_bound=True,
                        limit=MAX_CANDIDATE_VISITS,
                        limit_unit="entries",
                    )
                    return sorted(result, key=lambda item: str(item.path))
                finally:
                    if descriptor is not None:
                        os.close(descriptor)
                result.extend(local_candidates)
                pending.extend(
                    sorted(
                        local_children,
                        key=lambda item: item[0].parts,
                        reverse=True,
                    )
                )
    return sorted(result, key=lambda item: str(item[0]))


def project_local_candidates(
    project: Path,
    bounded_omissions: list[BoundedOmission] | None = None,
) -> list[CandidateReference]:
    result: list[CandidateReference] = []
    seen: set[str] = set()
    visits = 0
    roots = [project / name for name in ("lib", "libs", "tools", ".observe/cache")]
    for root in roots:
        authenticated = authenticate_scan_root(
            root,
            "project_local",
            bounded_omissions,
            allow_link_root=False,
        )
        if authenticated is None:
            continue
        pending = [DirectoryCursor()]
        evidence = str(root.relative_to(project))
        while pending:
            cursor = pending.pop()
            descriptor: int | None = None
            try:
                descriptor, directory = open_scan_cursor(authenticated, cursor)
                names = bounded_sorted_names(
                    descriptor if descriptor is not None else directory,
                    MAX_CANDIDATE_VISITS - visits,
                )
            except OSError:
                record_bounded_omission(
                    bounded_omissions,
                    reason="project_local_traversal_error",
                    omitted_unit="directories",
                    count_is_lower_bound=True,
                    limit=MAX_CANDIDATE_VISITS,
                    limit_unit="entries",
                )
                return sorted(result, key=lambda item: str(item.path))
            finally:
                if descriptor is not None:
                    os.close(descriptor)
            if names is None:
                record_bounded_omission(
                    bounded_omissions,
                    reason="project_local_entry_visit_limit",
                    omitted_unit="entries",
                    count_is_lower_bound=True,
                    limit=MAX_CANDIDATE_VISITS,
                    limit_unit="entries",
                )
                return sorted(result, key=lambda item: str(item.path))

            descriptor = None
            local_children: list[DirectoryCursor] = []
            local_candidates: list[CandidateReference] = []
            try:
                descriptor, directory = open_scan_cursor(authenticated, cursor)
                for name in names:
                    visits += 1
                    details = cursor_entry_status(descriptor, directory, name)
                    if path_is_link_or_reparse(details):
                        raise OSError(
                            "linked project-local entry prevents authenticated traversal"
                        )
                    path = root.joinpath(*cursor.parts, name)
                    if stat.S_ISDIR(details.st_mode):
                        local_children.append(
                            DirectoryCursor(
                                cursor.parts + (name,),
                                cursor.identities + (file_identity(details),),
                            )
                        )
                        continue
                    lowered = name.lower()
                    if (
                        not stat.S_ISREG(details.st_mode)
                        or "javaagent" not in lowered
                        or not lowered.endswith(".jar")
                    ):
                        continue
                    key = str(path)
                    if key in seen:
                        continue
                    if len(result) + len(local_candidates) >= MAX_CANDIDATES:
                        record_bounded_omission(
                            bounded_omissions,
                            reason="project_local_candidate_limit",
                            omitted_unit="candidates",
                            count_is_lower_bound=True,
                            limit=MAX_CANDIDATES,
                            limit_unit="candidates",
                        )
                        return sorted(result + local_candidates, key=lambda item: str(item.path))
                    seen.add(key)
                    local_candidates.append(
                        CandidateReference(
                            path=path,
                            source="project_local",
                            evidence=evidence,
                            authority=rooted_authority(
                                authenticated,
                                cursor,
                                name,
                                details,
                            ),
                        )
                    )
                if descriptor is None and not portable_cursor_matches(
                    authenticated,
                    cursor,
                ):
                    raise OSError("queued directory changed during scan")
            except OSError:
                record_bounded_omission(
                    bounded_omissions,
                    reason="project_local_traversal_error",
                    omitted_unit="directories",
                    count_is_lower_bound=True,
                    limit=MAX_CANDIDATE_VISITS,
                    limit_unit="entries",
                )
                return sorted(result, key=lambda item: str(item.path))
            finally:
                if descriptor is not None:
                    os.close(descriptor)
            result.extend(local_candidates)
            pending.extend(sorted(local_children, key=lambda item: item.parts, reverse=True))
    return sorted(result, key=lambda item: str(item.path))


SOURCE_RANK = {
    "explicit": 7,
    "environment": 6,
    "project_config": 5,
    "prior_verification": 4,
    "project_local": 3,
    "maven_cache": 2,
    "gradle_cache": 2,
}


def coalesce_candidates(
    candidates: Iterable[CandidateReference],
) -> list[CoalescedCandidate]:
    result: list[CoalescedCandidate] = []
    index_by_path: dict[str, int] = {}
    for candidate in candidates:
        path = candidate.path
        source = candidate.source
        evidence = candidate.evidence
        key = str(path.expanduser().absolute())
        index = index_by_path.get(key)
        if index is None:
            index_by_path[key] = len(result)
            result.append(
                CoalescedCandidate(
                    path,
                    source,
                    [evidence],
                    candidate.authority,
                )
            )
            continue
        existing = result[index]
        existing_path = existing.path
        existing_source = existing.source
        existing_evidence = list(existing.evidence)
        existing_authority = existing.authority
        if evidence not in existing_evidence:
            existing_evidence.append(evidence)
        if SOURCE_RANK.get(source, 0) > SOURCE_RANK.get(existing_source, 0):
            existing_source = source
            existing_authority = candidate.authority
        result[index] = CoalescedCandidate(
            existing_path,
            existing_source,
            existing_evidence,
            existing_authority,
        )
    return result


def select_candidate(
    candidates: list[dict[str, Any]], expected_version: str | None
) -> dict[str, Any]:
    def score(candidate: dict[str, Any]) -> tuple[Any, ...]:
        exact_version = int(
            expected_version is not None
            and candidate.get("artifact_version") == expected_version
        )
        return (
            SOURCE_RANK.get(candidate["source"], 0),
            exact_version,
            version_key(candidate.get("artifact_version")),
            candidate["path"],
        )

    return max(candidates, key=score)


def family_from_path(path: Path) -> str | None:
    lowered = path.as_posix().lower()
    name = path.name.lower()
    if (
        "com/splunk/splunk-otel-javaagent" in lowered
        or "com.splunk/splunk-otel-javaagent" in lowered
    ):
        return "splunk"
    if (
        "io/opentelemetry/javaagent" in lowered
        or "io.opentelemetry.javaagent/opentelemetry-javaagent" in lowered
        or re.search(r"opentelemetry-javaagent-\d", name)
    ):
        return "opentelemetry"
    if "splunk-otel-javaagent" in name:
        return "splunk"
    return None


def repository_family_hints(
    project: Path,
    config_snapshots: list[ConfigSnapshot],
) -> tuple[list[str], list[str]]:
    families: set[str] = set()
    evidence: set[str] = set()
    splunk_markers = (
        "com.splunk:splunk-otel-javaagent",
        "splunk-otel-javaagent",
        "signalfx-base",
        "splunkdev.net/observability",
    )
    upstream_markers = (
        "io.opentelemetry.javaagent:opentelemetry-javaagent",
        "io/opentelemetry/javaagent/opentelemetry-javaagent",
    )
    for snapshot in config_snapshots:
        config_path = snapshot.path
        text = snapshot.text.lower()
        relative = str(config_path.relative_to(project))
        if any(marker in text for marker in splunk_markers):
            families.add("splunk")
            evidence.add(relative)
        if any(marker in text for marker in upstream_markers):
            families.add("opentelemetry")
            evidence.add(relative)
    return sorted(families), sorted(evidence)


def expected_contract(
    args: argparse.Namespace,
    raw_candidates: list[CandidateReference],
    project: Path,
    config_snapshots: list[ConfigSnapshot],
) -> dict[str, Any]:
    config_candidates = [
        (candidate.path, candidate.source, candidate.evidence)
        for candidate in raw_candidates
        if candidate.source in {"environment", "project_config"}
    ]
    family_hints = sorted(
        {
            family
            for path, _, _ in config_candidates
            if (family := family_from_path(path)) is not None
        }
    )
    repository_families, repository_evidence = repository_family_hints(
        project,
        config_snapshots,
    )
    family_hints = sorted(set(family_hints + repository_families))
    version_hints = sorted(
        {
            version
            for path, _, _ in config_candidates
            if (version := version_from_text(path.name)) is not None
        },
        key=version_key,
    )
    conflicts: list[str] = []
    unresolved_conflicts: list[str] = []
    if len(family_hints) > 1:
        conflict = "repository runtime configuration names multiple agent families"
        conflicts.append(conflict)
        if args.expected_family is None:
            unresolved_conflicts.append(conflict)
    if len(version_hints) > 1:
        conflict = "repository runtime configuration names multiple agent versions"
        conflicts.append(conflict)
        if args.expected_version is None:
            unresolved_conflicts.append(conflict)
    family = args.expected_family
    version = (
        version_from_text(args.expected_version) or args.expected_version
        if args.expected_version
        else None
    )
    source = "cli" if family or version else "none"
    if args.expected_sha256 is not None:
        source = "cli"
    if family is None and len(family_hints) == 1:
        family = family_hints[0]
        source = "repository_config"
    if version is None and len(version_hints) == 1:
        version = version_hints[0]
        source = "repository_config"
    return {
        "family": family,
        "version": version,
        "sha256": args.expected_sha256,
        "source": source,
        "evidence": sorted(
            {evidence for _, _, evidence in config_candidates}
            | set(repository_evidence)
        ),
        "conflicts": conflicts,
        "unresolved_conflicts": unresolved_conflicts,
    }


def resolve(args: argparse.Namespace) -> dict[str, Any]:
    project_boundary = authenticate_directory(args.project)
    project = project_boundary.path
    exact_candidate_only = bool(
        getattr(args, "exact_candidate_only", False)
    )
    if exact_candidate_only and (
        len(args.candidate) != 1
        or args.expected_family is None
        or args.expected_sha256 is None
    ):
        raise ValueError(
            "exact-candidate-only resolution requires one --candidate, "
            "--expected-family, and --expected-sha256"
        )
    bounded_omissions: list[BoundedOmission] = []
    config_snapshots = (
        []
        if exact_candidate_only
        else collect_config_snapshots(
            project,
            root_descriptor=project_boundary.descriptor,
            root_identity=project_boundary.identity,
            bounded_omissions=bounded_omissions,
        )
    )
    raw_candidates: list[CandidateReference] = []
    raw_candidates.extend(
        CandidateReference(
            Path(value),
            "explicit",
            f"--candidate={value}",
        )
        for value in args.candidate
    )
    if exact_candidate_only:
        maven: list[Path] = []
        gradle: list[Path] = []
    else:
        raw_candidates.extend(
            configured_candidates(
                project,
                config_snapshots,
                bounded_omissions,
            )
        )
        raw_candidates.extend(
            project_local_candidates(project, bounded_omissions)
        )
        maven = maven_roots(args.maven_repo)
        raw_candidates.extend(
            cache_candidates(
                maven,
                (
                    "com/splunk/splunk-otel-javaagent/*/splunk-otel-javaagent-*.jar",
                    "io/opentelemetry/javaagent/opentelemetry-javaagent/*/opentelemetry-javaagent-*.jar",
                ),
                "maven_cache",
                bounded_omissions,
            )
        )
        gradle = gradle_roots(args.gradle_cache)
        raw_candidates.extend(
            cache_candidates(
                gradle,
                (
                    "com.splunk/splunk-otel-javaagent/*/*/splunk-otel-javaagent-*.jar",
                    "io.opentelemetry.javaagent/opentelemetry-javaagent/*/*/opentelemetry-javaagent-*.jar",
                ),
                "gradle_cache",
                bounded_omissions,
            )
        )
    candidate_inputs = coalesce_candidates(raw_candidates)
    if len(candidate_inputs) > MAX_CANDIDATES:
        record_bounded_omission(
            bounded_omissions,
            reason="candidate_validation_limit",
            omitted_count=len(candidate_inputs) - MAX_CANDIDATES,
            omitted_unit="candidates",
            count_is_lower_bound=False,
            limit=MAX_CANDIDATES,
            limit_unit="candidates",
        )
    expected = expected_contract(
        args,
        raw_candidates,
        project,
        config_snapshots,
    )

    valid_by_path: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, str]] = []
    candidates_to_validate = candidate_inputs[:MAX_CANDIDATES]
    for candidate_input in candidates_to_validate:
        path = candidate_input.path
        source = candidate_input.source
        evidence = candidate_input.evidence
        candidate, reason = validate_candidate(
            path,
            candidate_input.authority,
        )
        if candidate is None:
            rejected.append(
                {
                    "path": str(path.expanduser()),
                    "source": source,
                    "source_evidence": "; ".join(evidence),
                    "reason": reason or "invalid",
                }
            )
            continue
        candidate.update(
            {
                "source": source,
                "source_evidence": evidence,
            }
        )
        existing = valid_by_path.get(candidate["path"])
        if existing is None:
            valid_by_path[candidate["path"]] = candidate
            continue
        existing["source_evidence"] = sorted(
            set(existing["source_evidence"] + evidence)
        )
        if SOURCE_RANK.get(source, 0) > SOURCE_RANK.get(existing["source"], 0):
            existing["source"] = source

    valid = sorted(valid_by_path.values(), key=lambda item: item["path"])
    bounded_omission_rows = [
        omission.as_dict()
        for omission in sorted(
            bounded_omissions,
            key=lambda item: (
                item.reason,
                item.limit_unit,
                item.limit,
            ),
        )
    ]
    discovery_complete = not bounded_omission_rows
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "java-agent-resolution",
        "project": str(project),
        "status": "unresolved" if discovery_complete else "incomplete",
        "complete": discovery_complete,
        "candidate_only": True,
        "proof_boundary": (
            "Local artifact validation is not Java-agent execution or deployed "
            "production proof."
        ),
        "expected": expected,
        "selected": None,
        "claims": {
            "local_candidate_validated": False,
            "verification_execution": "not_run",
            "repository_configuration_match": "none",
            "verification_pin_match": "none",
            "production_parity": "not_proven",
        },
        "production_parity": {
            "status": "not_proven",
            "reason": (
                "This local resolver does not inspect the deployed production "
                "runtime artifact."
            ),
        },
        "bounded_discovery": {
            "complete": discovery_complete,
            "omissions": bounded_omission_rows,
        },
        "searched": {
            "explicit_candidates": len(args.candidate),
            "maven_roots": [str(path) for path in maven],
            "gradle_roots": [str(path) for path in gradle],
            "config_files_read": len(config_snapshots),
            "raw_candidates": len(raw_candidates),
            "unique_candidates": len(candidate_inputs),
            "candidates_validated": len(candidates_to_validate),
            "valid_candidates": len(valid),
        },
        "rejected": rejected,
        "message": (
            "No valid Java agent was found after deterministic local resolution; "
            "record the exact missing coordinate or source-configured artifact before "
            "requesting external input."
            if discovery_complete
            else "Java-agent resolution is incomplete because bounded discovery "
            "omitted eligible configuration or candidates; no agent was selected."
        ),
    }
    if not discovery_complete:
        return result
    if expected["unresolved_conflicts"]:
        result["status"] = "ambiguous"
        result["message"] = (
            "Java-agent runtime configuration is contradictory; pass the exact "
            "source-supported --expected-family and/or --expected-version needed "
            "to disambiguate it. Conflicts: "
            + "; ".join(expected["unresolved_conflicts"])
        )
        return result
    if not valid:
        return result

    eligible = valid
    expected_family = expected["family"]
    expected_version = expected["version"]
    if expected_family is not None:
        eligible = [
            candidate
            for candidate in eligible
            if candidate["family"] == expected_family
        ]
        if not eligible:
            result["message"] = (
                f"No valid {expected_family} Java agent was found after deterministic "
                "local resolution."
            )
            result["claims"]["repository_configuration_match"] = "mismatch"
            return result

    if expected_version is not None:
        exact_version_candidates = [
            candidate
            for candidate in eligible
            if candidate.get("artifact_version") == expected_version
        ]
        if not exact_version_candidates:
            result["message"] = (
                "No validated Java agent matches the required repository version "
                f"{expected_version}; verification must not substitute another release."
            )
            result["claims"]["repository_configuration_match"] = "mismatch"
            return result
        eligible = exact_version_candidates

    expected_sha256 = expected["sha256"]
    if expected_sha256 is not None:
        exact_digest_candidates = [
            candidate
            for candidate in eligible
            if candidate["sha256"] == expected_sha256
        ]
        if not exact_digest_candidates:
            result["message"] = (
                "No validated Java agent matches the required SHA-256 verification pin; "
                "the candidate changed or the wrong artifact was selected."
            )
            result["claims"]["verification_pin_match"] = "mismatch"
            return result
        eligible = exact_digest_candidates

    if (
        expected_family is None
        and len({candidate["family"] for candidate in eligible}) > 1
    ):
        highest_source_rank = max(
            SOURCE_RANK.get(candidate["source"], 0)
            for candidate in eligible
        )
        highest_authority = [
            candidate
            for candidate in eligible
            if SOURCE_RANK.get(candidate["source"], 0) == highest_source_rank
        ]
        authoritative_families = {
            candidate["family"] for candidate in highest_authority
        }
        if len(authoritative_families) > 1:
            result["status"] = "ambiguous"
            result["message"] = (
                "Equally authoritative Java-agent candidates name both Splunk and "
                "upstream OpenTelemetry families; select one exact source path."
            )
            return result
        authoritative_family = next(iter(authoritative_families))
        eligible = [
            candidate
            for candidate in eligible
            if candidate["family"] == authoritative_family
        ]

    selected = select_candidate(eligible, expected_version)
    same_pin = [
        candidate
        for candidate in eligible
        if candidate["coordinate"] == selected["coordinate"]
        and candidate.get("artifact_version") == selected.get("artifact_version")
    ]
    if len({candidate["sha256"] for candidate in same_pin}) > 1:
        result["status"] = "ambiguous"
        result["message"] = (
            "The same Java-agent coordinate and version resolved to different "
            "artifact bytes; select an exact path or digest."
        )
        return result

    exact_expected_version = (
        expected_version is not None
        and selected.get("artifact_version") == expected_version
    )
    family_matches = (
        expected_family is not None and selected["family"] == expected_family
    )
    if selected["source"] in {"explicit", "environment", "project_config"}:
        selection_reason = "exact_config_path"
    elif exact_expected_version:
        selection_reason = "exact_config_pin"
    elif family_matches:
        selection_reason = "same_family_fallback"
    else:
        selection_reason = "cache_only_fallback"
    selected["selection_reason"] = selection_reason
    recheck_argv = [
        sys.executable,
        "-I",
        str(Path(__file__).resolve()),
        "--project",
        str(project),
        "--candidate",
        selected["path"],
        "--exact-candidate-only",
        "--expected-family",
        selected["family"],
        "--expected-sha256",
        selected["sha256"],
    ]
    if selected.get("artifact_version") is not None:
        recheck_argv.extend(
            ["--expected-version", selected["artifact_version"]]
        )
    selected["verification_pin"] = {
        "path": selected["path"],
        "sha256": selected["sha256"],
        "size_bytes": selected["size_bytes"],
        "artifact_identity": selected["artifact_identity"],
    }
    selected["pre_attach_recheck_argv"] = recheck_argv
    result["status"] = "resolved"
    result["selected"] = selected
    result["claims"]["local_candidate_validated"] = True
    result["claims"]["verification_pin_match"] = (
        "exact" if expected_sha256 is not None else "recorded"
    )
    if expected_version is not None:
        result["claims"]["repository_configuration_match"] = (
            "exact" if exact_expected_version else "mismatch"
        )
    elif expected_family is not None:
        result["claims"]["repository_configuration_match"] = "family_only"
    result["message"] = (
        "Resolved and validated a concrete Java agent for verification; no "
        "user-supplied agent is required."
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve a valid local OpenTelemetry-compatible Java agent without "
            "downloading or executing it."
        )
    )
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--candidate", action="append", default=[])
    parser.add_argument(
        "--exact-candidate-only",
        action="store_true",
        help=(
            "Revalidate one previously selected path and exact pin without "
            "rescanning project configuration or local dependency caches."
        ),
    )
    parser.add_argument("--maven-repo", action="append", type=Path, default=[])
    parser.add_argument("--gradle-cache", action="append", type=Path, default=[])
    parser.add_argument(
        "--expected-family",
        "--prefer-family",
        dest="expected_family",
        choices=("splunk", "opentelemetry"),
        help=(
            "Source-derived provider family constraint. --prefer-family is a "
            "backward-compatible alias."
        ),
    )
    parser.add_argument("--expected-version")
    parser.add_argument(
        "--expected-sha256",
        type=parse_sha256,
        help=(
            "Required verification-pin digest. Re-run with the selected path and "
            "digest immediately before attaching the Java agent."
        ),
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.exact_candidate_only and (
        len(args.candidate) != 1
        or args.expected_family is None
        or args.expected_sha256 is None
    ):
        print(
            "--exact-candidate-only requires one --candidate, "
            "--expected-family, and --expected-sha256",
            file=sys.stderr,
        )
        return 2
    try:
        project = authenticate_directory(args.project)
    except SecureOutputError as error:
        print(f"Project directory is not safe: {error}", file=sys.stderr)
        return 2
    args.project = project.path
    payload = json.dumps(resolve(args), indent=2, sort_keys=True) + "\n"
    try:
        require_same_directory(project)
    except SecureOutputError as error:
        print(f"Project directory changed during resolution: {error}", file=sys.stderr)
        return 2
    if args.output is None:
        sys.stdout.write(payload)
    else:
        try:
            output = write_text(project, args.output, payload)
        except SecureOutputError as error:
            print(f"Refusing unsafe Java-agent output: {error}", file=sys.stderr)
            return 2
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
