#!/usr/bin/env python3
"""Resolve and validate a local Java agent without downloading anything.

The resolver turns an available JAR into an explicit verification pin: absolute
path, implementation version, premain class, and SHA-256.  It deliberately
keeps that fact separate from production-version parity, which cannot be
claimed unless the caller supplies a source-derived expected version.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree


SCHEMA_VERSION = 1
MAX_CONFIG_FILES = 4_000
MAX_CONFIG_BYTES = 2_000_000
MAX_CANDIDATES = 256
MAX_MANIFEST_BYTES = 256_000

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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    ):
        return "splunk"
    if (
        "opentelemetry" in implementation_vendor
        or "/io/opentelemetry/javaagent/opentelemetry-javaagent/"
        in coordinate_path
        or "/io.opentelemetry.javaagent/opentelemetry-javaagent/"
        in coordinate_path
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


def validate_candidate(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except (FileNotFoundError, OSError) as error:
        return None, f"not-readable: {error}"
    if not resolved.is_file():
        return None, "not-a-regular-file"
    before = resolved.stat()
    try:
        with zipfile.ZipFile(resolved) as archive:
            manifest_names = [
                name
                for name in archive.namelist()
                if name.upper() == "META-INF/MANIFEST.MF"
            ]
            if len(manifest_names) != 1:
                return None, "missing-or-duplicate-META-INF/MANIFEST.MF"
            manifest_info = archive.getinfo(manifest_names[0])
            if manifest_info.file_size > MAX_MANIFEST_BYTES:
                return None, "manifest-too-large"
            manifest = parse_manifest(archive.read(manifest_names[0]))
    except KeyError:
        return None, "missing-META-INF/MANIFEST.MF"
    except (OSError, zipfile.BadZipFile) as error:
        return None, f"invalid-jar: {error}"
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
    digest = sha256_file(resolved)
    after = resolved.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        return None, "jar-changed-during-validation"
    coordinate = (
        "com.splunk:splunk-otel-javaagent"
        if family == "splunk"
        else "io.opentelemetry.javaagent:opentelemetry-javaagent"
    )
    return (
        {
            "path": str(resolved),
            "coordinate": coordinate,
            "sha256": digest,
            "size_bytes": after.st_size,
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


def iter_config_files(project: Path) -> Iterable[Path]:
    seen = 0
    for directory, names, filenames in os.walk(project):
        relative = Path(directory).relative_to(project)
        names[:] = sorted(
            name
            for name in names
            if name not in SKIP_DIRECTORIES
            and not (relative == Path(".observe") and name == "evidence")
        )
        for filename in sorted(filenames):
            path = Path(directory) / filename
            if not is_config_file(path):
                continue
            seen += 1
            if seen > MAX_CONFIG_FILES:
                return
            try:
                if path.stat().st_size <= MAX_CONFIG_BYTES:
                    yield path
            except OSError:
                continue


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


def configured_candidates(project: Path) -> list[tuple[Path, str, str]]:
    candidates: list[tuple[Path, str, str]] = []
    for variable in ENV_AGENT_PATHS:
        value = os.environ.get(variable)
        if not value:
            continue
        for path in expand_path(value, (project,)):
            candidates.append((path, "environment", variable))
    for variable in ENV_AGENT_OPTIONS:
        value = os.environ.get(variable, "")
        for match in AGENT_PATH_PATTERN.finditer(value):
            raw = next(group for group in match.groups() if group is not None)
            for path in expand_path(raw, (project,)):
                candidates.append((path, "environment", variable))

    for config_path in iter_config_files(project):
        try:
            text = config_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        source_kind = source_kind_for_config(config_path, project)
        for match in AGENT_PATH_PATTERN.finditer(text):
            raw = next(group for group in match.groups() if group is not None)
            line = text.count("\n", 0, match.start()) + 1
            evidence = f"{config_path.relative_to(project)}:{line}"
            for path in expand_path(raw, (config_path.parent, project)):
                candidates.append((path, source_kind, evidence))
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
    roots: Iterable[Path], patterns: Iterable[str], source: str
) -> list[tuple[Path, str, str]]:
    result: list[tuple[Path, str, str]] = []
    for root in roots:
        for pattern in patterns:
            try:
                for path in sorted(root.glob(pattern)):
                    result.append((path, source, str(root)))
                    if len(result) >= MAX_CANDIDATES:
                        return result
            except OSError:
                continue
    return result


def project_local_candidates(project: Path) -> list[tuple[Path, str, str]]:
    result: list[tuple[Path, str, str]] = []
    roots = [project / name for name in ("lib", "libs", "tools", ".observe/cache")]
    for root in roots:
        if not root.is_dir():
            continue
        for pattern in ("*javaagent*.jar", "**/*javaagent*.jar"):
            try:
                for path in sorted(root.glob(pattern)):
                    result.append((path, "project_local", str(root.relative_to(project))))
                    if len(result) >= MAX_CANDIDATES:
                        return result
            except OSError:
                continue
    return result


SOURCE_RANK = {
    "explicit": 7,
    "environment": 6,
    "project_config": 5,
    "prior_verification": 4,
    "project_local": 3,
    "maven_cache": 2,
    "gradle_cache": 2,
}


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
    if "splunk" in lowered:
        return "splunk"
    if (
        "io/opentelemetry/javaagent" in lowered
        or re.search(r"opentelemetry-javaagent-\d", path.name.lower())
    ):
        return "opentelemetry"
    return None


def repository_family_hints(project: Path) -> tuple[list[str], list[str]]:
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
    for config_path in iter_config_files(project):
        try:
            text = config_path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
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
    raw_candidates: list[tuple[Path, str, str]],
    project: Path,
) -> dict[str, Any]:
    config_candidates = [
        (path, source, evidence)
        for path, source, evidence in raw_candidates
        if source in {"environment", "project_config"}
    ]
    family_hints = sorted(
        {
            family
            for path, _, _ in config_candidates
            if (family := family_from_path(path)) is not None
        }
    )
    repository_families, repository_evidence = repository_family_hints(project)
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
    if family is None and len(family_hints) == 1:
        family = family_hints[0]
        source = "repository_config"
    if version is None and len(version_hints) == 1:
        version = version_hints[0]
        source = "repository_config"
    return {
        "family": family,
        "version": version,
        "source": source,
        "evidence": sorted(
            {evidence for _, _, evidence in config_candidates}
            | set(repository_evidence)
        ),
        "conflicts": conflicts,
        "unresolved_conflicts": unresolved_conflicts,
    }


def resolve(args: argparse.Namespace) -> dict[str, Any]:
    project = args.project.expanduser().resolve()
    raw_candidates: list[tuple[Path, str, str]] = []
    raw_candidates.extend(
        (Path(value), "explicit", f"--candidate={value}")
        for value in args.candidate
    )
    raw_candidates.extend(configured_candidates(project))
    raw_candidates.extend(project_local_candidates(project))

    maven = maven_roots(args.maven_repo)
    raw_candidates.extend(
        cache_candidates(
            maven,
            (
                "com/splunk/splunk-otel-javaagent/*/splunk-otel-javaagent-*.jar",
                "io/opentelemetry/javaagent/opentelemetry-javaagent/*/opentelemetry-javaagent-*.jar",
            ),
            "maven_cache",
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
        )
    )
    expected = expected_contract(args, raw_candidates, project)

    valid_by_path: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, str]] = []
    for path, source, evidence in raw_candidates[:MAX_CANDIDATES]:
        candidate, reason = validate_candidate(path)
        if candidate is None:
            rejected.append(
                {
                    "path": str(path.expanduser()),
                    "source": source,
                    "source_evidence": evidence,
                    "reason": reason or "invalid",
                }
            )
            continue
        candidate.update(
            {
                "source": source,
                "source_evidence": [evidence],
            }
        )
        existing = valid_by_path.get(candidate["path"])
        if existing is None:
            valid_by_path[candidate["path"]] = candidate
            continue
        existing["source_evidence"] = sorted(
            set(existing["source_evidence"] + [evidence])
        )
        if SOURCE_RANK.get(source, 0) > SOURCE_RANK.get(existing["source"], 0):
            existing["source"] = source

    valid = sorted(valid_by_path.values(), key=lambda item: item["path"])
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "java-agent-resolution",
        "project": str(project),
        "status": "unresolved",
        "complete": True,
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
            "production_parity": "not_proven",
        },
        "production_parity": {
            "status": "not_proven",
            "reason": (
                "This local resolver does not inspect the deployed production "
                "runtime artifact."
            ),
        },
        "searched": {
            "explicit_candidates": len(args.candidate),
            "maven_roots": [str(path) for path in maven],
            "gradle_roots": [str(path) for path in gradle],
            "raw_candidates": len(raw_candidates),
            "valid_candidates": len(valid),
        },
        "rejected": rejected,
        "message": (
            "No valid Java agent was found after deterministic local resolution; "
            "record the exact missing coordinate or source-configured artifact before "
            "requesting external input."
        ),
    }
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
    elif len({candidate["family"] for candidate in eligible}) > 1:
        result["status"] = "ambiguous"
        result["message"] = (
            "Valid Splunk and upstream OpenTelemetry Java agents were both found, "
            "but source did not select a provider family."
        )
        return result

    if expected_version is not None:
        exact_version_candidates = [
            candidate
            for candidate in eligible
            if candidate.get("artifact_version") == expected_version
        ]
        if exact_version_candidates:
            eligible = exact_version_candidates

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
    result["status"] = "resolved"
    result["selected"] = selected
    result["claims"]["local_candidate_validated"] = True
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
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.project.expanduser().is_dir():
        print(f"Project directory does not exist: {args.project}", file=sys.stderr)
        return 2
    payload = json.dumps(resolve(args), indent=2, sort_keys=True) + "\n"
    if args.output is None:
        sys.stdout.write(payload)
    else:
        output = args.output.expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
