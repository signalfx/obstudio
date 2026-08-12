#!/usr/bin/env python3
"""Shared bootstrap runtime for host-scoped Obstudio plugins."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform
import re
import socket
import shutil
import signal
import subprocess
import sys
import time
import tomllib
import urllib.request
import urllib.parse
import zipfile
from datetime import datetime, timezone
from pathlib import Path


RELEASE_BASE_URL = "https://github.com/signalfx/obstudio/releases/latest/download"
OBSTUDIO_HEALTH_URL = os.environ.get(
    "OBSTUDIO_HEALTH_URL",
    "http://127.0.0.1:3000/api/health",
)
BOOTSTRAP_STATE_FILE = "bootstrap-state.json"
BOOTSTRAP_LOCK_FILE = "bootstrap.lock"
BOOTSTRAP_STATUS_STOPPED = "stopped"
CODEX_MANAGED_BLOCK = "# BEGIN OBSTUDIO MCP CONFIG"
DOWNLOAD_TIMEOUT_SECONDS = 30
DOWNLOAD_ATTEMPTS = 3
HEALTH_CHECK_ATTEMPTS = 20
HEALTH_CHECK_SLEEP_SECONDS = 0.5
HOOK_EXECUTION_DEADLINE_SECONDS = 120
LOCK_DEADLINE_SAFETY_SECONDS = 2
LOCK_POLL_SECONDS = 0.25
CHECKSUM_LINE_PATTERNS = (
    re.compile(r"^(?P<hash>[0-9a-fA-F]{64})\s+\*?(?P<name>.+)$"),
    re.compile(r"^SHA256 \((?P<name>.+)\) = (?P<hash>[0-9a-fA-F]{64})$"),
)
VERSION_PATTERN = re.compile(r"\b\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?\b")


def plugin_host() -> str:
    configured = os.environ.get("OBSTUDIO_PLUGIN_HOST", "").strip().lower()
    if configured:
        return configured
    return "claude" if os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip() else "codex"


def host_name() -> str:
    return "Claude Code" if plugin_host() == "claude" else "Codex"


def plugin_owner() -> str:
    return f"{plugin_host()}-plugin"


def skill_command(name: str) -> str:
    return f"/obstudio:{name}" if plugin_host() == "claude" else f"${name}"


def help_skill_hint() -> str:
    return f"Use {skill_command('obstudio-help')} to list available commands."


HELP_SKILL_HINT = help_skill_hint()


class BootstrapLockTimeout(RuntimeError):
    pass


@contextlib.contextmanager
def bootstrap_lock(lock_path: Path):
    lock_deadline = time.monotonic() + max(0.0, hook_execution_deadline_seconds() - LOCK_DEADLINE_SAFETY_SECONDS)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        if is_windows():
            acquire_windows_lock(lock_file, lock_deadline)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if is_windows():
                import msvcrt

                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def hook_execution_deadline_seconds() -> float:
    raw = os.environ.get("OBSTUDIO_HOOK_EXECUTION_DEADLINE_SECONDS", "")
    if not raw:
        return HOOK_EXECUTION_DEADLINE_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return HOOK_EXECUTION_DEADLINE_SECONDS
    return max(0.0, value)


def acquire_windows_lock(lock_file, deadline: float) -> None:
    import msvcrt

    while True:
        lock_file.seek(0)
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            return
        except OSError as exc:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BootstrapLockTimeout("timed out waiting for Obstudio bootstrap lock") from exc
            time.sleep(min(LOCK_POLL_SECONDS, remaining))


def main() -> int:
    try:
        plugin_root = resolve_plugin_root()
        plugin_data = resolve_plugin_data()
        plugin_version = read_plugin_version(plugin_root)
        state_path = plugin_data / BOOTSTRAP_STATE_FILE
        codex_config_path = Path.home() / ".codex" / "config.toml"
        codex_skills_path = Path.home() / ".codex" / "skills" / "obstudio"
        plugin_mcp_path = plugin_root / ".mcp.json"

        with bootstrap_lock(plugin_data / BOOTSTRAP_LOCK_FILE):
            return bootstrap_locked(
                plugin_data,
                plugin_version,
                state_path,
                codex_config_path,
                codex_skills_path,
                plugin_mcp_path,
            )
    except Exception as exc:  # pragma: no cover - defensive hook boundary
        emit_error(
            "Obstudio bootstrap could not complete automatically. "
            "The plugin bundle is present, but the managed runtime could not be prepared."
        )
        print(f"bootstrap error: {exc}", file=sys.stderr)
        return 2


def bootstrap_locked(
    plugin_data: Path,
    plugin_version: str,
    state_path: Path,
    codex_config_path: Path,
    codex_skills_path: Path,
    plugin_mcp_path: Path,
) -> int:
    stopped_state = read_bootstrap_state(state_path) if bootstrap_state_requests_stop(state_path) else {}
    if stopped_state.get("pluginVersion") == plugin_version:
        emit_context(
            "Obstudio Observer is intentionally stopped for this plugin. "
            f"{help_skill_hint()} Use {skill_command('observer-restart')} to start the managed Observer again."
        )
        return 0
    if stopped_state:
        write_state(
            state_path,
            stopped_observer_state(
                stopped_state,
                plugin_version=plugin_version,
                install_source=string_state_value(stopped_state, "installSource"),
                obstudio_binary=string_state_value(stopped_state, "obstudioBinary"),
            ),
        )
        emit_context(
            "Obstudio plugin files were updated, and the managed Observer "
            "remains intentionally stopped. "
            f"{help_skill_hint()} Use {skill_command('observer-restart')} to start it again."
        )
        return 0

    plugin_mcp_url = read_plugin_obstudio_mcp_url(plugin_mcp_path)
    plugin_health_url = derive_health_url(plugin_mcp_url) if plugin_mcp_url else OBSTUDIO_HEALTH_URL
    mcp_policy = codex_obstudio_mcp_policy(codex_config_path, plugin_mcp_url)
    if mcp_policy == "disabled":
        write_state(
            state_path,
            plugin_policy_state(plugin_version, owner="user-configured", mode="disabled"),
        )
        emit_context(
            "Obstudio MCP is explicitly disabled in Codex config. The plugin hook "
            "left the managed Observer stopped, did not start or restart the "
            "plugin-managed Observer, and bundled Obstudio skills remain available. "
            f"{help_skill_hint()}"
        )
        return 0
    if mcp_policy == "custom":
        write_state(
            state_path,
            plugin_policy_state(plugin_version, owner="external-observer", mode="custom"),
        )
        emit_context(
            "Custom Obstudio MCP endpoint detected in Codex config. The plugin hook "
            f"left the configured endpoint unchanged ({codex_obstudio_mcp_url(codex_config_path)}), "
            "did not start or restart the plugin-managed Observer, and bundled "
            f"Obstudio skills remain available. {help_skill_hint()}"
        )
        return 0

    if is_bootstrapped(state_path, plugin_version, codex_config_path, codex_skills_path, plugin_mcp_path):
        emit_context(
            f"Obstudio is already bootstrapped for {host_name()}. "
            f"{help_skill_hint()} Use {skill_command('otel-audit')}, "
            f"{skill_command('otel-instrument')}, and {skill_command('otel-verify')} as needed."
        )
        return 0

    try:
        artifact_suffix = resolve_release_artifact()
        release_dir = plugin_data / "release" / artifact_suffix.removesuffix(".zip")
        release_dir.mkdir(parents=True, exist_ok=True)
        checksums_path = release_dir / "checksums.txt"
        resolved_artifact, expected_checksum = fetch_expected_checksum(artifact_suffix, checksums_path)
        release_version = resolve_release_version(resolved_artifact, artifact_suffix)

        obstudio_binary = download_obstudio(plugin_data, artifact_suffix, resolved_artifact, expected_checksum)
        install_source = "downloaded"

        prior_managed_pid = read_managed_bootstrap_state_pid(state_path)
        local_obstudio_requested = mcp_policy == "plugin-local" or bool(prior_managed_pid)
        pid = ""
        live_pid = ""
        live_health = None
        log_path = None
        process_started = False
        if local_obstudio_requested:
            live_health = fetch_obstudio_health(plugin_health_url)
            if live_health is not None:
                live_pid = find_pid_listening_on_url(plugin_health_url)
                pid = live_pid
                managed_owner = bool(prior_managed_pid) and bootstrap_state_proves_managed_owner(
                    state_path,
                    live_pid,
                    live_health,
                )
                if managed_owner and not health_payload_version_matches_release(live_health, release_version):
                    terminate_managed_process(live_pid or prior_managed_pid, plugin_health_url)
                    process, log_path = start_obstudio_background(obstudio_binary, plugin_data)
                    try:
                        live_health = verify_local_obstudio_health(plugin_health_url)
                        ensure_process_running(process)
                    except Exception:
                        terminate_process(process)
                        raise
                    pid = str(process.pid)
                    live_pid = ""
                    process_started = True
            else:
                if is_tcp_port_open(plugin_health_url):
                    raise RuntimeError(
                        f"local Observer port is already occupied at {plugin_health_url} "
                        "but the health endpoint is not reporting Obstudio; stop the existing process or clear the stale shared-observer state"
                    )
                process, log_path = start_obstudio_background(obstudio_binary, plugin_data)
                try:
                    live_health = verify_local_obstudio_health(plugin_health_url)
                    ensure_process_running(process)
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
            health_payload=live_health,
            log_path=log_path,
            expected_version=release_version,
            health_url=plugin_health_url,
            mcp_url=plugin_mcp_url,
        )
        write_state(
            state_path,
            {
                "pluginVersion": plugin_version,
                "releaseVersion": release_version,
                "installSource": install_source,
                "obstudioBinary": str(obstudio_binary),
                "bootstrappedAt": datetime.now(timezone.utc).isoformat(),
                **observer_state,
            },
        )
        if process_started:
            emit_context(
                f"Obstudio bootstrap complete. {host_name()} now has the bundled skills, "
                "the local Observer MCP config, and a background Observer process "
                "was started for the bundled HTTP MCP endpoint. "
                f"{help_skill_hint()}"
            )
        elif observer_state["mode"] == "managed":
            emit_context(
                f"Obstudio bootstrap complete. {host_name()} now has the bundled skills, "
                "the local Observer MCP config, and the managed background Observer "
                "is healthy. "
                f"{help_skill_hint()}"
            )
        else:
            emit_context(
                f"Obstudio bootstrap complete. {host_name()} now has the bundled skills "
                "and the MCP config points at a shared Observer. "
                f"{help_skill_hint()}"
            )
        return 0
    except Exception as exc:  # pragma: no cover - defensive hook boundary
        emit_error(
            "Obstudio bootstrap could not complete automatically. "
            "The plugin bundle is present, but the managed runtime could not be prepared."
        )
        print(f"bootstrap error: {exc}", file=sys.stderr)
        return 2


def resolve_plugin_root() -> Path:
    env_names = ("CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT") if plugin_host() == "claude" else ("PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT")
    for env_name in env_names:
        value = os.environ.get(env_name, "").strip()
        if value:
            return Path(value).expanduser().resolve()
    raise RuntimeError("PLUGIN_ROOT is not set")


def resolve_plugin_data() -> Path:
    env_names = ("CLAUDE_PLUGIN_DATA", "PLUGIN_DATA") if plugin_host() == "claude" else ("PLUGIN_DATA", "CLAUDE_PLUGIN_DATA")
    for env_name in env_names:
        value = os.environ.get(env_name, "").strip()
        if value:
            data = Path(value).expanduser().resolve()
            data.mkdir(parents=True, exist_ok=True)
            return data
    raise RuntimeError("PLUGIN_DATA is not set")


def read_plugin_version(plugin_root: Path) -> str:
    manifest_dir = ".claude-plugin" if plugin_host() == "claude" else ".codex-plugin"
    manifest_path = plugin_root / manifest_dir / "plugin.json"
    with manifest_path.open("r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    version = manifest.get("version", "").strip()
    if not version:
        raise RuntimeError("plugin manifest is missing a version")
    return version


def read_plugin_obstudio_mcp_url(mcp_path: Path) -> str:
    try:
        payload = json.loads(mcp_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return derive_obstudio_mcp_url(OBSTUDIO_HEALTH_URL)
    if not isinstance(payload, dict):
        return derive_obstudio_mcp_url(OBSTUDIO_HEALTH_URL)
    servers = payload.get("mcpServers")
    if not isinstance(servers, dict):
        return derive_obstudio_mcp_url(OBSTUDIO_HEALTH_URL)
    obstudio = servers.get("obstudio")
    if not isinstance(obstudio, dict):
        return derive_obstudio_mcp_url(OBSTUDIO_HEALTH_URL)
    url = obstudio.get("url")
    if isinstance(url, str) and url.strip():
        return url.strip()
    return derive_obstudio_mcp_url(OBSTUDIO_HEALTH_URL)


def plugin_policy_state(plugin_version: str, *, owner: str, mode: str) -> dict[str, str]:
    return {
        "pluginVersion": plugin_version,
        "releaseVersion": "",
        "installSource": "",
        "obstudioBinary": "",
        "bootstrappedAt": datetime.now(timezone.utc).isoformat(),
        "owner": owner,
        "mode": mode,
        "healthUrl": "",
        "mcpUrl": "",
        "pid": "",
        "observerStartedAt": "",
        "logPath": "",
    }


def codex_obstudio_mcp_policy(config_path: Path, plugin_mcp_url: str) -> str:
    if plugin_host() != "codex":
        return "plugin-local"
    try:
        config = config_path.read_text(encoding="utf-8")
    except OSError:
        return "plugin-local"

    server = read_codex_obstudio_server(config)
    if server is None:
        return "plugin-local"
    if server.get("enabled") is False:
        return "disabled"
    url = server.get("url")
    if isinstance(url, str) and url.strip():
        return "plugin-local" if normalize_mcp_url(url) == normalize_mcp_url(plugin_mcp_url) else "custom"
    command = server.get("command")
    if isinstance(command, str) and command.strip():
        return "plugin-local" if CODEX_MANAGED_BLOCK in config else "custom"
    return "plugin-local"


def codex_obstudio_mcp_url(config_path: Path) -> str:
    try:
        config = config_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    server = read_codex_obstudio_server(config)
    if server is None:
        return ""
    url = server.get("url")
    if isinstance(url, str):
        return url.strip()
    return ""


def read_codex_obstudio_server(config: str) -> dict[str, object] | None:
    try:
        payload = tomllib.loads(config)
    except tomllib.TOMLDecodeError:
        return read_codex_obstudio_server_fallback(config)
    mcp_servers = payload.get("mcp_servers")
    if not isinstance(mcp_servers, dict):
        return None
    obstudio = mcp_servers.get("obstudio")
    if isinstance(obstudio, dict):
        return obstudio
    return None


def read_codex_obstudio_server_fallback(config: str) -> dict[str, object] | None:
    match = re.search(r"(?ms)^\s*\[mcp_servers\.obstudio\]\s*$(.*?)(?=^\s*\[|\Z)", config)
    if not match:
        return None
    block = match.group(1)
    server: dict[str, object] = {}
    enabled_match = re.search(r"(?m)^\s*enabled\s*=\s*(true|false)\s*$", block)
    if enabled_match:
        server["enabled"] = enabled_match.group(1) == "true"
    url_match = re.search(r'(?m)^\s*url\s*=\s*"([^"]+)"\s*$', block)
    if url_match:
        server["url"] = url_match.group(1)
    command_match = re.search(r'(?m)^\s*command\s*=\s*"([^"]+)"\s*$', block)
    if command_match:
        server["command"] = command_match.group(1)
    return server


def normalize_mcp_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    path = parsed.path.rstrip("/") or "/mcp"
    if not path.endswith("/mcp"):
        path = path + "/mcp"
    return parsed._replace(path=path).geturl()


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
    plugin_mcp_path: Path | None = None,
) -> bool:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except OSError:
        return False
    except json.JSONDecodeError:
        return False

    if state.get("pluginVersion") != plugin_version:
        return False

    plugin_mcp_url = read_plugin_obstudio_mcp_url(plugin_mcp_path) if plugin_mcp_path is not None else derive_obstudio_mcp_url(OBSTUDIO_HEALTH_URL)
    policy = codex_obstudio_mcp_policy(codex_config_path, plugin_mcp_url)
    if policy in {"disabled", "custom"}:
        return True
    health_url = string_state_value(state, "healthUrl") or derive_health_url(plugin_mcp_url)
    health_payload = fetch_obstudio_health(health_url)
    if health_payload is None:
        return False
    if state.get("owner") == plugin_owner() and state.get("mode") == "managed":
        live_pid = find_pid_listening_on_url(health_url)
        expected_version = string_state_value(state, "releaseVersion")
        return bootstrap_state_proves_managed_owner(state_path, live_pid, health_payload, expected_version)
    return True


def download_obstudio(
    plugin_data: Path,
    artifact_suffix: str,
    resolved_artifact: str,
    expected_checksum: str,
) -> Path:
    release_dir = plugin_data / "release" / resolved_artifact.removesuffix(".zip")
    release_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir = release_dir / "extracted"
    binary_name = "obstudio.exe" if is_windows() else "obstudio"

    archive_path = release_dir / resolved_artifact
    if archive_is_valid(archive_path, expected_checksum):
        binary_path = find_extracted_binary_matching_archive(archive_path, extracted_dir, binary_name)
        if binary_path is not None:
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
                write_text_atomic(checksums_path, text)
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
            cached_result = parse_cached_checksum(versioned_checksums_path, artifact_suffix)
            if cached_result is not None:
                return cached_result
        versioned_download_url = f"{RELEASE_BASE_URL}/obstudio_{release_version}_checksums.txt"
        try:
            with urllib.request.urlopen(versioned_download_url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
                text = response.read().decode("utf-8")
            result = parse_checksum(text, artifact_suffix)
            try:
                write_text_atomic(checksums_path, text)
                cache_versioned_checksums(checksums_path, release_version, text)
            except OSError:
                pass
            return result
        except Exception as exc:  # pragma: no cover - network boundary
            last_error = exc

    cached_result = newest_cached_checksum(checksums_path, artifact_suffix)
    if cached_result is not None:
        return cached_result
    cached_result = parse_cached_checksum(checksums_path, artifact_suffix)
    if cached_result is not None:
        return cached_result
    raise RuntimeError("failed to download release checksum manifest") from last_error


def parse_checksum(checksums_text: str, artifact_suffix: str) -> tuple[str, str]:
    target_name = re.compile(
        rf"^obstudio_\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?_{re.escape(artifact_suffix)}$"
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
        cached_result = parse_cached_checksum(cached_path, artifact_suffix)
        if cached_result is not None:
            return cached_result
    return None


def parse_cached_checksum(path: Path, artifact_suffix: str) -> tuple[str, str] | None:
    try:
        return parse_checksum(path.read_text(encoding="utf-8"), artifact_suffix)
    except OSError:
        return None
    except RuntimeError:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
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


def find_extracted_binary_matching_archive(archive_path: Path, extracted_dir: Path, binary_name: str) -> Path | None:
    try:
        root = extracted_dir.resolve()
        with zipfile.ZipFile(archive_path) as zf:
            for member_name in find_zip_members(zf, binary_name):
                candidate = (root / member_name).resolve()
                try:
                    candidate.relative_to(root)
                except ValueError:
                    continue
                if candidate.is_file() and sha256_file(candidate) == sha256_zip_member(zf, member_name):
                    return candidate
    except (OSError, zipfile.BadZipFile):
        return None
    return None


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


def parse_obstudio_version(stdout: str, stderr: str) -> str | None:
    text = "\n".join(part for part in (stdout, stderr) if part)
    matches = VERSION_PATTERN.findall(text)
    if not matches:
        return None
    return matches[-1]


def normalize_obstudio_version(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    without_prefix = text.removeprefix("v")
    if re.fullmatch(VERSION_PATTERN, without_prefix):
        return without_prefix
    matches = VERSION_PATTERN.findall(text)
    if not matches:
        return ""
    return matches[-1]


def health_payload_version_matches_release(health_payload: dict[str, object] | None, release_version: str) -> bool:
    if health_payload is None:
        return False
    return normalize_obstudio_version(health_payload.get("version")) == normalize_obstudio_version(release_version)


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
        write_text_atomic(versioned_checksums_path, text)
    except OSError:
        pass


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temp_path.write_text(text, encoding="utf-8")
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def find_zip_member(zf: zipfile.ZipFile, binary_name: str) -> str | None:
    return next(iter(find_zip_members(zf, binary_name)), None)


def find_zip_members(zf: zipfile.ZipFile, binary_name: str) -> list[str]:
    return [name for name in zf.namelist() if Path(name).name == binary_name]


def sha256_zip_member(zf: zipfile.ZipFile, member_name: str) -> str:
    digest = hashlib.sha256()
    with zf.open(member_name) as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def start_obstudio_background(obstudio_binary: Path, plugin_data: Path) -> tuple[subprocess.Popen[str], Path]:
    log_dir = plugin_data / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "obstudio.log"
    env = os.environ.copy()
    for key in ("HOST", "PORT", "OTLP_PORT", "OTLP_HTTP_PORT", "OTLP_GRPC_PORT"):
        env.pop(key, None)
    env["HOST"] = "127.0.0.1"
    env["PORT"] = "3000"
    env["OTLP_HTTP_PORT"] = "4318"
    env["OTLP_GRPC_PORT"] = "4317"
    env["OBSTUDIO_OWNER"] = plugin_owner()
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


def terminate_managed_process(pid: str, health_url: str = OBSTUDIO_HEALTH_URL) -> None:
    pid = pid.strip()
    if not pid.isdigit():
        raise RuntimeError("could not determine managed Observer process pid")
    if is_windows():
        subprocess.run(["taskkill", "/PID", pid, "/T"], check=False, capture_output=True, text=True, timeout=5)
    else:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except ProcessLookupError:
            return
    if wait_for_managed_process_exit(pid, health_url):
        return
    if is_windows():
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], check=False, capture_output=True, text=True, timeout=5)
    else:
        try:
            os.kill(int(pid), signal.SIGKILL)
        except ProcessLookupError:
            return
    wait_for_managed_process_exit(pid, health_url)


def wait_for_managed_process_exit(pid: str, health_url: str = OBSTUDIO_HEALTH_URL) -> bool:
    for _ in range(20):
        if find_pid_listening_on_url(health_url) != pid:
            return True
        time.sleep(0.25)
    return False


def verify_local_obstudio_health(health_url: str = OBSTUDIO_HEALTH_URL) -> dict[str, object]:
    last_error: Exception | None = None
    for _ in range(HEALTH_CHECK_ATTEMPTS):
        try:
            payload = fetch_obstudio_health(health_url)
            if payload is not None:
                return payload
        except Exception as exc:  # pragma: no cover - health boundary
            last_error = exc
        time.sleep(HEALTH_CHECK_SLEEP_SECONDS)
    raise RuntimeError(
        f"local Observer did not become healthy at {health_url}"
    ) from last_error


def fetch_obstudio_health(health_url: str) -> dict[str, object] | None:
    try:
        with urllib.request.urlopen(health_url, timeout=2) as response:
            if response.status != 200:
                return None
            payload = json.load(response)
            if (
                isinstance(payload, dict)
                and payload.get("kind") == "obstudio"
                and payload.get("apiVersion") == "v1"
            ):
                return payload
    except Exception:
        return None
    return None


def probe_obstudio_health(health_url: str) -> bool:
    return fetch_obstudio_health(health_url) is not None


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


def read_managed_bootstrap_state_pid(state_path: Path) -> str:
    state = read_bootstrap_state(state_path)
    if state.get("owner") != plugin_owner() or state.get("mode") != "managed":
        return ""
    return read_bootstrap_state_pid(state_path)


def read_bootstrap_state(state_path: Path) -> dict[str, object]:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(state, dict):
        return state
    return {}


def bootstrap_state_requests_stop(state_path: Path) -> bool:
    state = read_bootstrap_state(state_path)
    return state.get("status") == BOOTSTRAP_STATUS_STOPPED or state.get("disabled") is True


def stopped_observer_state(
    prior_state: dict[str, object],
    *,
    plugin_version: str,
    install_source: str,
    obstudio_binary: Path | str,
) -> dict[str, str]:
    return {
        "pluginVersion": plugin_version,
        "installSource": install_source,
        "obstudioBinary": str(obstudio_binary),
        "bootstrappedAt": datetime.now(timezone.utc).isoformat(),
        "status": BOOTSTRAP_STATUS_STOPPED,
        "owner": string_state_value(prior_state, "owner"),
        "mode": string_state_value(prior_state, "mode"),
        "healthUrl": string_state_value(prior_state, "healthUrl"),
        "mcpUrl": string_state_value(prior_state, "mcpUrl"),
        "pid": string_state_value(prior_state, "pid"),
        "observerStartedAt": string_state_value(prior_state, "observerStartedAt"),
        "logPath": string_state_value(prior_state, "logPath"),
    }


def string_state_value(state: dict[str, object], key: str) -> str:
    value = state.get(key)
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    return ""


def bootstrap_state_proves_managed_owner(
    state_path: Path,
    live_pid: str,
    health_payload: dict[str, object] | None,
    expected_version: str = "",
) -> bool:
    if not health_payload_reports_managed(health_payload):
        return False
    if expected_version and not health_payload_version_matches_release(health_payload, expected_version):
        return False
    state = read_bootstrap_state(state_path)
    if state.get("owner") != plugin_owner() or state.get("mode") != "managed":
        return False

    saved_pid = read_bootstrap_state_pid(state_path)
    if live_pid and saved_pid and saved_pid != live_pid:
        return False

    saved_started_at = state.get("observerStartedAt")
    live_started_at = health_payload.get("startedAt")
    if saved_started_at and live_started_at and str(saved_started_at) != str(live_started_at):
        return False
    return True


def health_payload_reports_managed(health_payload: dict[str, object] | None) -> bool:
    return (
        health_payload is not None
        and health_payload.get("owner") == plugin_owner()
        and health_payload.get("mode") == "managed"
    )


def observer_state_fields(
    state_path: Path,
    *,
    local_requested: bool,
    process_started: bool,
    live_pid: str,
    pid: str,
    health_payload: dict[str, object] | None,
    log_path: Path | None,
    expected_version: str = "",
    health_url: str = OBSTUDIO_HEALTH_URL,
    mcp_url: str = "",
) -> dict[str, str]:
    if not local_requested:
        return {
            "owner": "shared-observer",
            "mode": "shared",
            "healthUrl": "",
            "mcpUrl": "",
            "pid": "",
            "observerStartedAt": "",
            "logPath": "",
        }
    if (process_started and health_payload_reports_managed(health_payload)) or bootstrap_state_proves_managed_owner(
        state_path,
        live_pid,
        health_payload,
        expected_version,
    ):
        owner = plugin_owner()
        mode = "managed"
    else:
        owner = "external-observer"
        mode = "external"
    observer_started_at = ""
    if health_payload is not None and isinstance(health_payload.get("startedAt"), str):
        observer_started_at = str(health_payload["startedAt"])
    return {
        "owner": owner,
        "mode": mode,
        "healthUrl": health_url,
        "mcpUrl": mcp_url or derive_obstudio_mcp_url(health_url),
        "pid": pid,
        "observerStartedAt": observer_started_at,
        "logPath": str(log_path) if log_path is not None else "",
    }


def find_pid_listening_on_url(health_url: str) -> str:
    parsed = urllib.parse.urlparse(health_url)
    port = parsed.port
    if port is None:
        return ""
    if is_windows():
        return find_windows_pid_listening_on_port(port)
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


def find_windows_pid_listening_on_port(port: int) -> str:
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        f"(Get-NetTCPConnection -LocalPort {port} -State Listen | Select-Object -First 1 -ExpandProperty OwningProcess)",
    ]
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=5)
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
