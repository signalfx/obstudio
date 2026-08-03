#!/usr/bin/env python3
"""Bootstrap Obstudio the first time a Codex session loads the plugin."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.request
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
        checksums_path = release_dir / "checksums.txt"
        resolved_artifact, expected_checksum = fetch_expected_checksum(artifact_suffix, checksums_path)
        release_version = resolve_release_version(resolved_artifact, artifact_suffix)

        obstudio_binary = locate_existing_obstudio(release_version)
        install_source = "existing"
        if obstudio_binary is None:
            obstudio_binary = download_obstudio(plugin_data, artifact_suffix, resolved_artifact, expected_checksum)
            install_source = "downloaded"

        run_install(obstudio_binary)
        pid = None
        log_path = None
        if codex_config_requests_local_obstudio(codex_config_path):
            process, log_path = start_obstudio_background(obstudio_binary, plugin_data)
            try:
                verify_local_obstudio_health()
                ensure_process_running(process)
            except Exception:
                terminate_process(process)
                raise
            pid = process.pid
        write_state(
            state_path,
            {
                "pluginVersion": plugin_version,
                "installSource": install_source,
                "obstudioBinary": str(obstudio_binary),
                "bootstrappedAt": datetime.now(timezone.utc).isoformat(),
                "pid": str(pid) if pid is not None else "",
                "logPath": str(log_path) if log_path is not None else "",
            },
        )
        if pid is not None:
            emit_context(
                "Obstudio bootstrap complete. Codex now has the bundled skills, "
                "the local Observer MCP config, and a background Observer process "
                "was started for the bundled HTTP MCP endpoint. "
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

    return state.get("pluginVersion") == plugin_version


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
            if not archive_path.is_file():
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
    except zipfile.BadZipFile as exc:
        archive_path.unlink(missing_ok=True)
        raise RuntimeError(f"downloaded archive {resolved_artifact} is corrupt") from exc
    binary_path = find_binary(extracted_dir, binary_name)
    if binary_path is None:
        raise RuntimeError(f"could not find {binary_name} in {resolved_artifact}")

    ensure_executable(binary_path)
    return binary_path


def fetch_expected_checksum(artifact_suffix: str, checksums_path: Path) -> tuple[str, str]:
    download_url = f"{RELEASE_BASE_URL}/checksums.txt"
    cached_text = None
    if checksums_path.is_file():
        try:
            cached_text = checksums_path.read_text(encoding="utf-8")
        except OSError:
            cached_text = None
    try:
        with urllib.request.urlopen(download_url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            text = response.read().decode("utf-8")
        try:
            result = parse_checksum(text, artifact_suffix)
        except Exception:
            if cached_text is not None:
                return parse_checksum(cached_text, artifact_suffix)
            raise
        try:
            checksums_path.write_text(text, encoding="utf-8")
        except OSError:
            pass
        return result
    except Exception as exc:  # pragma: no cover - network boundary
        if cached_text is not None:
            return parse_checksum(cached_text, artifact_suffix)
        raise RuntimeError("failed to download release checksum manifest") from exc


def parse_checksum(checksums_text: str, artifact_suffix: str) -> tuple[str, str]:
    target_name = artifact_suffix
    for raw_line in checksums_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for pattern in CHECKSUM_LINE_PATTERNS:
            match = pattern.fullmatch(line)
            if match:
                name = match.group("name")
                if name == target_name or name.endswith(target_name):
                    return name, match.group("hash").lower()
    raise RuntimeError(f"checksum for {artifact_suffix} not found in checksums.txt")


def archive_is_valid(archive_path: Path, expected_checksum: str) -> bool:
    if not archive_path.is_file():
        return False
    try:
        return sha256_file(archive_path) == expected_checksum
    except OSError:
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
    raise RuntimeError(f"unsupported platform: {system}/{machine}")


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
    for line in reversed([line.strip() for line in text.splitlines() if line.strip()]):
        tokens = line.split()
        for token in reversed(tokens):
            if token == "version":
                continue
            if token:
                return token
    return None


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
    with log_path.open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [str(obstudio_binary)],
            stdout=log_file,
            stderr=log_file,
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
            }
        },
        sys.stdout,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
