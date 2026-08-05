#!/usr/bin/env python3
"""Bootstrap Obstudio the first time a Codex session loads the plugin."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import socket
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import zipfile
from datetime import datetime, timezone
from pathlib import Path


RELEASE_BASE_URL = os.environ.get(
    "OBSTUDIO_RELEASE_BASE_URL",
    "https://github.com/signalfx/obstudio/releases/latest/download",
)
OBSTUDIO_HEALTH_URL = os.environ.get(
    "OBSTUDIO_HEALTH_URL",
    "http://127.0.0.1:3000/api/health",
)
BOOTSTRAP_STATE_FILE = "bootstrap-state.json"
CODEX_MANAGED_BLOCK = "# BEGIN OBSTUDIO MCP CONFIG"
DOWNLOAD_TIMEOUT_SECONDS = 30
DOWNLOAD_ATTEMPTS = 3
HEALTH_CHECK_ATTEMPTS = 20
HEALTH_CHECK_SLEEP_SECONDS = 0.5
CHECKSUM_LINE_PATTERNS = (
    re.compile(r"^(?P<hash>[0-9a-fA-F]{64})\s+\*?(?P<name>.+)$"),
    re.compile(r"^SHA256 \((?P<name>.+)\) = (?P<hash>[0-9a-fA-F]{64})$"),
)
VERSION_PATTERN = re.compile(r"\b\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?\b")
HELP_SKILL_HINT = "Use $obstudio-help to list available commands."


def main() -> int:
    plugin_root = resolve_plugin_root()
    plugin_data = resolve_plugin_data()
    plugin_version = read_plugin_version(plugin_root)
    state_path = plugin_data / BOOTSTRAP_STATE_FILE
    codex_config_path = Path.home() / ".codex" / "config.toml"
    codex_skills_path = Path.home() / ".codex" / "skills" / "obstudio"

    if is_bootstrapped(state_path, plugin_version, codex_config_path, codex_skills_path):
        emit_context(
            "Obstudio is already bootstrapped for Codex. "
            f"{HELP_SKILL_HINT} Use $otel-audit, $otel-instrument, and $otel-verify as needed."
        )
        return 0

    try:
        artifact_suffix = resolve_release_artifact()
        release_dir = plugin_data / "release" / artifact_suffix.removesuffix(".zip")
        release_dir.mkdir(parents=True, exist_ok=True)
        checksums_path = release_dir / "checksums.txt"
        resolved_artifact, expected_checksum = fetch_expected_checksum(artifact_suffix, checksums_path)
        release_version = resolve_release_version(resolved_artifact, artifact_suffix)

        obstudio_binary = locate_existing_obstudio(release_version)
        install_source = "existing"
        if obstudio_binary is None:
            obstudio_binary = download_obstudio(plugin_data, artifact_suffix, resolved_artifact, expected_checksum)
            install_source = "downloaded"

        run_install(obstudio_binary)
        local_obstudio_requested = codex_config_requests_local_obstudio(codex_config_path)
        pid = ""
        live_pid = ""
        log_path = None
        process_started = False
        if local_obstudio_requested:
            if probe_obstudio_health(OBSTUDIO_HEALTH_URL):
                live_pid = find_pid_listening_on_url(OBSTUDIO_HEALTH_URL)
                pid = live_pid
            else:
                if is_tcp_port_open(OBSTUDIO_HEALTH_URL):
                    raise RuntimeError(
                        f"local Observer port is already occupied at {OBSTUDIO_HEALTH_URL} "
                        "but the health endpoint is not reporting Obstudio; stop the existing process or clear the stale shared-observer state"
                    )
                process, log_path = start_obstudio_background(obstudio_binary, plugin_data)
                try:
                    verify_local_obstudio_health()
                    ensure_process_running(process)
                    configure_codex_mcp_url(codex_config_path, derive_obstudio_mcp_url(OBSTUDIO_HEALTH_URL))
                except Exception:
                    terminate_process(process)
                    raise
                pid = str(process.pid)
                process_started = True
        observer_state = observer_state_fields(
            state_path,
            local_requested=local_obstudio_requested,
            process_started=process_started,
            live_pid=live_pid,
            pid=pid,
            log_path=log_path,
        )
        write_state(
            state_path,
            {
                "pluginVersion": plugin_version,
                "installSource": install_source,
                "obstudioBinary": str(obstudio_binary),
                "bootstrappedAt": datetime.now(timezone.utc).isoformat(),
                **observer_state,
            },
        )
        if process_started:
            emit_context(
                "Obstudio bootstrap complete. Codex now has the bundled skills, "
                "the local Observer MCP config, and a background Observer process "
                "was started for the bundled HTTP MCP endpoint. "
                f"{HELP_SKILL_HINT}"
            )
        elif observer_state["mode"] == "managed":
            emit_context(
                "Obstudio bootstrap complete. Codex now has the bundled skills, "
                "the local Observer MCP config, and the managed background Observer "
                "is healthy. "
                f"{HELP_SKILL_HINT}"
            )
        else:
            emit_context(
                "Obstudio bootstrap complete. Codex now has the bundled skills "
                "and the MCP config points at a shared Observer. "
                f"{HELP_SKILL_HINT}"
            )
        return 0
    except Exception as exc:  # pragma: no cover - defensive hook boundary
        emit_error(
            "Obstudio bootstrap could not complete automatically. "
            "The plugin bundle is present, but the release installer failed."
        )
        print(f"bootstrap error: {exc}", file=sys.stderr)
        return 2


def resolve_plugin_root() -> Path:
    for env_name in ("PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT"):
        value = os.environ.get(env_name, "").strip()
        if value:
            return Path(value).expanduser().resolve()
    raise RuntimeError("PLUGIN_ROOT is not set")


def resolve_plugin_data() -> Path:
    for env_name in ("PLUGIN_DATA", "CLAUDE_PLUGIN_DATA"):
        value = os.environ.get(env_name, "").strip()
        if value:
            data = Path(value).expanduser().resolve()
            data.mkdir(parents=True, exist_ok=True)
            return data
    raise RuntimeError("PLUGIN_DATA is not set")


def read_plugin_version(plugin_root: Path) -> str:
    manifest_path = plugin_root / ".codex-plugin" / "plugin.json"
    with manifest_path.open("r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    version = manifest.get("version", "").strip()
    if not version:
        raise RuntimeError("plugin manifest is missing a version")
    return version


def codex_config_requests_local_obstudio(config_path: Path) -> bool:
    try:
        config = config_path.read_text(encoding="utf-8")
    except OSError:
        return False

    start = config.find(CODEX_MANAGED_BLOCK)
    if start == -1:
        return False
    end = config.find("# END OBSTUDIO MCP CONFIG", start)
    if end == -1:
        return False
    block = config[start:end]
    return "command =" in block and "url =" not in block


def is_bootstrapped(
    state_path: Path,
    plugin_version: str,
    codex_config_path: Path,
    codex_skills_path: Path,
) -> bool:
    if not codex_skills_path.is_dir() or not codex_config_path.is_file():
        return False

    try:
        config = codex_config_path.read_text(encoding="utf-8")
    except OSError:
        return False

    if CODEX_MANAGED_BLOCK not in config:
        return False

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except OSError:
        return False
    except json.JSONDecodeError:
        return False

    if state.get("pluginVersion") != plugin_version:
        return False

    health_url = codex_obstudio_health_url(codex_config_path)
    if health_url is None:
        return False
    return probe_obstudio_health(health_url)


def locate_existing_obstudio(expected_version: str) -> Path | None:
    candidates = [
        shutil.which("obstudio"),
        Path.home() / ".codex" / "skills" / "obstudio" / "obstudio",
        Path.home() / ".codex" / "skills" / "obstudio" / "obstudio.exe",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser().resolve()
        if path.is_file() and existing_binary_matches_release(path, expected_version):
            return path
    return None


def download_obstudio(
    plugin_data: Path,
    artifact_suffix: str,
    resolved_artifact: str,
    expected_checksum: str,
) -> Path:
    release_dir = plugin_data / "release" / artifact_suffix.removesuffix(".zip")
    release_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir = release_dir / "extracted"
    binary_name = "obstudio.exe" if is_windows() else "obstudio"
    binary_path = extracted_dir / binary_name

    archive_path = release_dir / resolved_artifact
    if archive_is_valid(archive_path, expected_checksum) and binary_path.is_file():
        if extracted_binary_matches_archive(archive_path, binary_path, binary_name):
            ensure_executable(binary_path)
            return binary_path

    if archive_path.exists() or extracted_dir.exists():
        if archive_path.exists() and not archive_is_valid(archive_path, expected_checksum):
            archive_path.unlink(missing_ok=True)
        if extracted_dir.exists():
            shutil.rmtree(extracted_dir)

    download_url = f"{RELEASE_BASE_URL}/{resolved_artifact}"
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(download_url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response, archive_path.open("wb") as output:
                shutil.copyfileobj(response, output)
            break
        except Exception as exc:  # pragma: no cover - network boundary
            archive_path.unlink(missing_ok=True)
            if attempt == DOWNLOAD_ATTEMPTS:
                raise RuntimeError(f"failed to download {resolved_artifact} after {DOWNLOAD_ATTEMPTS} attempts") from exc
            time.sleep(attempt)

    if extracted_dir.exists():
        shutil.rmtree(extracted_dir)
    extracted_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(archive_path) as zf:
            validate_zip_entries(zf, extracted_dir)
        verify_checksum(archive_path, expected_checksum)
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(extracted_dir)
    except (zipfile.BadZipFile, RuntimeError) as exc:
        archive_path.unlink(missing_ok=True)
        if extracted_dir.exists():
            shutil.rmtree(extracted_dir)
        raise RuntimeError(f"downloaded archive {resolved_artifact} is corrupt") from exc
    binary_path = find_binary(extracted_dir, binary_name)
    if binary_path is None:
        raise RuntimeError(f"could not find {binary_name} in {resolved_artifact}")

    ensure_executable(binary_path)
    return binary_path


def fetch_expected_checksum(
    artifact_suffix: str,
    checksums_path: Path,
) -> tuple[str, str]:
    checksums_path.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for download_url in (f"{RELEASE_BASE_URL}/checksums.txt",):
        try:
            with urllib.request.urlopen(download_url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
                text = response.read().decode("utf-8")
            result = parse_checksum(text, artifact_suffix)
            try:
                checksums_path.write_text(text, encoding="utf-8")
                cache_versioned_checksums(
                    checksums_path,
                    resolve_release_version(result[0], artifact_suffix),
                    text,
                )
            except OSError:
                pass
            return result
        except Exception as exc:  # pragma: no cover - network boundary
            last_error = exc

    release_version = None
    try:
        release_version = resolve_latest_release_version()
    except Exception as exc:  # pragma: no cover - network boundary
        last_error = exc
    if release_version:
        versioned_checksums_path = versioned_checksum_cache_path(checksums_path, release_version)
        if versioned_checksums_path.is_file():
            try:
                return parse_checksum(versioned_checksums_path.read_text(encoding="utf-8"), artifact_suffix)
            except OSError:
                pass
        versioned_download_url = f"{RELEASE_BASE_URL}/obstudio_{release_version}_checksums.txt"
        try:
            with urllib.request.urlopen(versioned_download_url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
                text = response.read().decode("utf-8")
            result = parse_checksum(text, artifact_suffix)
            try:
                checksums_path.write_text(text, encoding="utf-8")
                cache_versioned_checksums(checksums_path, release_version, text)
            except OSError:
                pass
            return result
        except Exception as exc:  # pragma: no cover - network boundary
            last_error = exc

    cached_result = newest_cached_checksum(checksums_path, artifact_suffix)
    if cached_result is not None:
        return cached_result
    raise RuntimeError("failed to download release checksum manifest") from last_error


def parse_checksum(checksums_text: str, artifact_suffix: str) -> tuple[str, str]:
    target_name = re.compile(
        rf"^obstudio_\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?_{re.escape(artifact_suffix)}$"
    )
    for raw_line in checksums_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for pattern in CHECKSUM_LINE_PATTERNS:
            match = pattern.fullmatch(line)
            if match:
                name = match.group("name")
                if target_name.fullmatch(Path(name).name):
                    return Path(name).name, match.group("hash").lower()
    raise RuntimeError(f"checksum for {artifact_suffix} not found in checksums.txt")


def newest_cached_checksum(checksums_path: Path, artifact_suffix: str) -> tuple[str, str] | None:
    cached_paths = []
    for cached_path in checksums_path.parent.glob("checksums-*.txt"):
        release_version = cached_checksum_version(cached_path)
        if release_version is not None:
            cached_paths.append((release_version, cached_path))
    cached_paths.sort(key=lambda item: semver_sort_key(item[0]), reverse=True)
    for _, cached_path in cached_paths:
        try:
            return parse_checksum(cached_path.read_text(encoding="utf-8"), artifact_suffix)
        except (OSError, RuntimeError):
            continue
    return None


def cached_checksum_version(path: Path) -> str | None:
    match = re.fullmatch(rf"checksums-({VERSION_PATTERN.pattern}).txt", path.name)
    if not match:
        return None
    return match.group(1)


def semver_sort_key(version: str) -> tuple[int, int, int, int, tuple[tuple[int, int | str], ...]]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?", version)
    if not match:
        return (0, 0, 0, 0, ((1, version),))
    major, minor, patch = (int(match.group(index)) for index in (1, 2, 3))
    prerelease = match.group(4)
    stable_rank = 1 if prerelease is None else 0
    return (major, minor, patch, stable_rank, semver_prerelease_key(prerelease or ""))


def semver_prerelease_key(prerelease: str) -> tuple[tuple[int, int | str], ...]:
    key = []
    for part in prerelease.split("."):
        if re.fullmatch(r"\d+", part):
            key.append((0, int(part)))
            continue
        match = re.fullmatch(r"([A-Za-z-]+)(\d+)", part)
        if match:
            key.append((1, match.group(1)))
            key.append((0, int(match.group(2))))
            continue
        key.append((1, part))
    return tuple(key)


def archive_is_valid(archive_path: Path, expected_checksum: str) -> bool:
    if not archive_path.is_file():
        return False
    try:
        return sha256_file(archive_path) == expected_checksum
    except OSError:
        return False


def extracted_binary_matches_archive(archive_path: Path, binary_path: Path, binary_name: str) -> bool:
    try:
        with zipfile.ZipFile(archive_path) as zf:
            member_name = find_zip_member(zf, binary_name)
            if member_name is None:
                return False
            return sha256_file(binary_path) == sha256_zip_member(zf, member_name)
    except (OSError, zipfile.BadZipFile):
        return False


def verify_checksum(archive_path: Path, expected_checksum: str) -> None:
    actual = sha256_file(archive_path)
    if actual != expected_checksum:
        raise RuntimeError(
            f"checksum mismatch for {archive_path.name}: expected {expected_checksum}, got {actual}"
        )


def validate_zip_entries(zf: zipfile.ZipFile, extract_root: Path) -> None:
    root = extract_root.resolve()
    for info in zf.infolist():
        if not info.filename:
            raise RuntimeError("downloaded archive contains an empty entry name")
        target = (root / info.filename).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f"archive contains unsafe path: {info.filename}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_release_artifact() -> str:
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Darwin":
        if machine in {"arm64", "aarch64"}:
            return "darwin_arm64.zip"
        if machine in {"x86_64", "amd64"}:
            return "darwin_amd64.zip"
    elif system == "Linux":
        if machine in {"x86_64", "amd64"}:
            return "linux_amd64.zip"
    elif system == "Windows":
        if machine in {"x86_64", "amd64"}:
            return "windows_amd64.zip"
    raise RuntimeError(
        f"unsupported platform: {system}/{machine}. "
        "Obstudio releases currently ship Linux amd64, macOS arm64/amd64, and Windows amd64 assets; "
        "install Obstudio manually from https://github.com/signalfx/obstudio/releases if your platform is not listed."
    )


def resolve_latest_release_version() -> str:
    download_url = "https://api.github.com/repos/signalfx/obstudio/releases/latest"
    try:
        with urllib.request.urlopen(download_url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except Exception as exc:  # pragma: no cover - network boundary
        raise RuntimeError("failed to determine latest Obstudio release version") from exc
    tag_name = str(payload.get("tag_name", "")).strip()
    if not tag_name:
        raise RuntimeError("latest Obstudio release is missing a tag name")
    release_version = tag_name.removeprefix("v").strip()
    if not release_version:
        raise RuntimeError(f"could not parse release version from tag {tag_name}")
    return release_version


def resolve_release_version(resolved_artifact: str, artifact_suffix: str) -> str:
    expected_suffix = f"_{artifact_suffix}"
    if not resolved_artifact.endswith(expected_suffix):
        raise RuntimeError(
            f"could not parse release version from {resolved_artifact}: expected suffix {expected_suffix}"
        )
    prefix = resolved_artifact.removesuffix(expected_suffix)
    if not prefix.startswith("obstudio_"):
        raise RuntimeError(f"could not parse release version from {resolved_artifact}")
    release_version = prefix.removeprefix("obstudio_")
    if not release_version:
        raise RuntimeError(f"could not parse release version from {resolved_artifact}")
    return release_version


def ensure_process_running(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        raise RuntimeError("Observer process exited before becoming healthy")


def existing_binary_matches_release(obstudio_binary: Path, expected_version: str) -> bool:
    try:
        result = subprocess.run(
            [str(obstudio_binary), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return False
    if result.returncode != 0:
        return False
    reported_version = parse_obstudio_version(result.stdout, result.stderr)
    return reported_version == expected_version


def parse_obstudio_version(stdout: str, stderr: str) -> str | None:
    text = "\n".join(part for part in (stdout, stderr) if part)
    matches = VERSION_PATTERN.findall(text)
    if not matches:
        return None
    return matches[-1]


def is_windows() -> bool:
    return platform.system() == "Windows"


def find_binary(root: Path, binary_name: str) -> Path | None:
    direct = root / binary_name
    if direct.is_file():
        return direct
    for candidate in root.rglob(binary_name):
        if candidate.is_file():
            return candidate
    return None


def ensure_executable(path: Path) -> None:
    if is_windows():
        return
    mode = path.stat().st_mode
    path.chmod(mode | 0o111)


def versioned_checksum_cache_path(checksums_path: Path, release_version: str) -> Path:
    return checksums_path.with_name(f"checksums-{release_version}.txt")


def cache_versioned_checksums(checksums_path: Path, release_version: str, text: str) -> None:
    versioned_checksums_path = versioned_checksum_cache_path(checksums_path, release_version)
    try:
        versioned_checksums_path.write_text(text, encoding="utf-8")
    except OSError:
        pass


def find_zip_member(zf: zipfile.ZipFile, binary_name: str) -> str | None:
    for name in zf.namelist():
        if Path(name).name == binary_name:
            return name
    return None


def sha256_zip_member(zf: zipfile.ZipFile, member_name: str) -> str:
    digest = hashlib.sha256()
    with zf.open(member_name) as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_install(obstudio_binary: Path) -> None:
    command = [str(obstudio_binary), "install", "--target=codex"]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "obstudio install failed:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


def start_obstudio_background(obstudio_binary: Path, plugin_data: Path) -> tuple[subprocess.Popen[str], Path]:
    log_dir = plugin_data / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "obstudio.log"
    env = os.environ.copy()
    env["OBSTUDIO_OWNER"] = "codex-plugin"
    env["OBSTUDIO_MODE"] = "managed"
    with log_path.open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [str(obstudio_binary)],
            stdout=log_file,
            stderr=log_file,
            env=env,
            start_new_session=True,
        )
    return process, log_path


def terminate_process(process: subprocess.Popen[str]) -> None:
    try:
        process.terminate()
        process.wait(timeout=5)
    except Exception:
        try:
            process.kill()
            process.wait(timeout=5)
        except Exception:
            pass


def verify_local_obstudio_health() -> None:
    last_error: Exception | None = None
    for _ in range(HEALTH_CHECK_ATTEMPTS):
        try:
            with urllib.request.urlopen(OBSTUDIO_HEALTH_URL, timeout=2) as response:
                if response.status != 200:
                    raise RuntimeError(f"unexpected health status: {response.status}")
                payload = json.load(response)
                if (
                    isinstance(payload, dict)
                    and payload.get("kind") == "obstudio"
                    and payload.get("apiVersion") == "v1"
                ):
                    return
        except Exception as exc:  # pragma: no cover - health boundary
            last_error = exc
        time.sleep(HEALTH_CHECK_SLEEP_SECONDS)
    raise RuntimeError(
        f"local Observer did not become healthy at {OBSTUDIO_HEALTH_URL}"
    ) from last_error


def probe_obstudio_health(health_url: str) -> bool:
    try:
        with urllib.request.urlopen(health_url, timeout=2) as response:
            if response.status != 200:
                return False
            payload = json.load(response)
            return (
                isinstance(payload, dict)
                and payload.get("kind") == "obstudio"
                and payload.get("apiVersion") == "v1"
            )
    except Exception:
        return False


def codex_obstudio_health_url(config_path: Path) -> str | None:
    try:
        config = config_path.read_text(encoding="utf-8")
    except OSError:
        return None

    start = config.find(CODEX_MANAGED_BLOCK)
    if start == -1:
        return None
    end = config.find("# END OBSTUDIO MCP CONFIG", start)
    if end == -1:
        return None
    block = config[start:end]
    url_match = re.search(r'(?m)^\s*url\s*=\s*"([^"]+)"\s*$', block)
    if url_match:
        return derive_health_url(url_match.group(1))
    if re.search(r'(?m)^\s*command\s*=\s*"([^"]+)"\s*$', block):
        return OBSTUDIO_HEALTH_URL
    return None


def derive_health_url(mcp_url: str) -> str:
    parsed = urllib.parse.urlparse(mcp_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/mcp"):
        path = path[: -len("/mcp")] + "/api/health"
    elif path:
        path = path.rstrip("/") + "/api/health"
    else:
        path = "/api/health"
    return parsed._replace(path=path).geturl()


def derive_obstudio_mcp_url(health_url: str) -> str:
    parsed = urllib.parse.urlparse(health_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/api/health"):
        path = path[: -len("/api/health")] + "/mcp"
    elif path:
        path = path.rstrip("/") + "/mcp"
    else:
        path = "/mcp"
    return parsed._replace(path=path).geturl()


def configure_codex_mcp_url(config_path: Path, mcp_url: str) -> None:
    try:
        config = config_path.read_text(encoding="utf-8")
    except OSError:
        config = ""

    block = "\n".join(
        [
            CODEX_MANAGED_BLOCK,
            "[mcp_servers.obstudio]",
            "enabled = true",
            f'url = "{mcp_url}"',
            "# END OBSTUDIO MCP CONFIG",
            "",
        ]
    )
    start = config.find(CODEX_MANAGED_BLOCK)
    if start != -1:
        end = config.find("# END OBSTUDIO MCP CONFIG", start)
        if end != -1:
            end += len("# END OBSTUDIO MCP CONFIG")
            config = config[:start].rstrip() + "\n\n" + block + config[end:].lstrip("\n")
        else:
            config = config.rstrip() + "\n\n" + block
    else:
        config = config.rstrip()
        if config:
            config += "\n\n"
        config += block

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config, encoding="utf-8")


def is_tcp_port_open(url_text: str) -> bool:
    parsed = urllib.parse.urlparse(url_text)
    host = parsed.hostname
    port = parsed.port
    if not host or port is None:
        return False
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def read_bootstrap_state_pid(state_path: Path) -> str:
    state = read_bootstrap_state(state_path)
    pid = state.get("pid")
    if isinstance(pid, str):
        return pid.strip()
    if isinstance(pid, int):
        return str(pid)
    return ""


def read_bootstrap_state(state_path: Path) -> dict[str, object]:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(state, dict):
        return state
    return {}


def bootstrap_state_proves_managed_owner(state_path: Path, live_pid: str) -> bool:
    if not live_pid:
        return False
    state = read_bootstrap_state(state_path)
    return (
        state.get("owner") == "codex-plugin"
        and state.get("mode") == "managed"
        and read_bootstrap_state_pid(state_path) == live_pid
    )


def observer_state_fields(
    state_path: Path,
    *,
    local_requested: bool,
    process_started: bool,
    live_pid: str,
    pid: str,
    log_path: Path | None,
) -> dict[str, str]:
    if not local_requested:
        return {
            "owner": "shared-observer",
            "mode": "shared",
            "healthUrl": "",
            "mcpUrl": "",
            "pid": "",
            "logPath": "",
        }
    if process_started or bootstrap_state_proves_managed_owner(state_path, live_pid):
        owner = "codex-plugin"
        mode = "managed"
    else:
        owner = "external-observer"
        mode = "external"
    return {
        "owner": owner,
        "mode": mode,
        "healthUrl": OBSTUDIO_HEALTH_URL,
        "mcpUrl": derive_obstudio_mcp_url(OBSTUDIO_HEALTH_URL),
        "pid": pid,
        "logPath": str(log_path) if log_path is not None else "",
    }


def find_pid_listening_on_url(health_url: str) -> str:
    parsed = urllib.parse.urlparse(health_url)
    port = parsed.port
    if port is None:
        return ""
    try:
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    for line in result.stdout.splitlines():
        pid = line.strip()
        if pid.isdigit():
            return pid
    return ""


def write_state(path: Path, payload: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")


def emit_context(message: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": message,
            }
        },
        sys.stdout,
    )
    sys.stdout.write("\n")


def emit_error(message: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": message,
                "isError": True,
            }
        },
        sys.stdout,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
