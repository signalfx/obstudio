from __future__ import annotations

import json
import os
import secrets
import stat
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .trace import TraceSummary, parse_trace


@dataclass
class AgentResult:
    returncode: int
    trace_path: Path
    final_message_path: Path
    stderr_path: Path


class AgentBackend(Protocol):
    """Protocol for pluggable agent execution backends."""

    @property
    def name(self) -> str: ...

    def run_agent(
        self,
        *,
        prompt: str,
        exec_dir: Path,
        model: str | None = None,
        timeout: int = 1200,
    ) -> AgentResult: ...

    def run_judge(
        self,
        *,
        prompt: str,
        exec_dir: Path,
        model: str | None = None,
        schema_path: Path | None = None,
        timeout: int = 900,
    ) -> AgentResult: ...

    def parse_trace(self, trace_path: Path) -> TraceSummary: ...


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


@dataclass
class StreamedCommandResult:
    returncode: int
    stdout: str
    stderr: str


def run_streamed_command(
    cmd: list[str],
    *,
    stdout_path: Path,
    stderr_path: Path,
    timeout: int,
    env: dict[str, str] | None = None,
) -> StreamedCommandResult:
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    if Path(os.path.abspath(stdout_path.parent)) != Path(
        os.path.abspath(stderr_path.parent)
    ):
        raise ValueError("streamed stdout and stderr must share an output directory")
    output_boundary_identity = path_directory_identity(stdout_path.parent)
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        bufsize=1,
    )
    stdout_thread = threading.Thread(
        target=_pump_stream,
        args=(process.stdout, stdout_chunks),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_pump_stream,
        args=(process.stderr, stderr_chunks),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        process.kill()
        process.wait()
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        communicated_stdout: str | bytes | None = None
        communicated_stderr: str | bytes | None = None
        if not stdout_thread.is_alive() and not stderr_thread.is_alive():
            communicated_stdout, communicated_stderr = process.communicate()
        stdout = _merge_stream_observations(
            error.stdout,
            "".join(stdout_chunks),
            communicated_stdout,
            encoding=getattr(process.stdout, "encoding", None),
        )
        stderr = _merge_stream_observations(
            error.stderr,
            "".join(stderr_chunks),
            communicated_stderr,
            encoding=getattr(process.stderr, "encoding", None),
        )
        _write_streamed_artifacts(
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            stdout=stdout,
            stderr=stderr,
            output_boundary_identity=output_boundary_identity,
        )
        raise
    stdout_thread.join()
    stderr_thread.join()
    stdout = "".join(stdout_chunks)
    stderr = "".join(stderr_chunks)
    _write_streamed_artifacts(
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        stdout=stdout,
        stderr=stderr,
        output_boundary_identity=output_boundary_identity,
    )
    return StreamedCommandResult(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _write_streamed_artifacts(
    *,
    stdout_path: Path,
    stderr_path: Path,
    stdout: str,
    stderr: str,
    output_boundary_identity: tuple[int, int],
) -> None:
    atomic_text_write(
        stdout_path,
        stdout,
        boundary=stdout_path.parent,
        expected_boundary_identity=output_boundary_identity,
    )
    atomic_text_write(
        stderr_path,
        stderr,
        boundary=stderr_path.parent,
        expected_boundary_identity=output_boundary_identity,
    )


def _merge_stream_observations(
    *values: str | bytes | None,
    encoding: str | None,
) -> str:
    merged = ""
    for value in values:
        fragment = _stream_text(value, encoding=encoding)
        if not fragment:
            continue
        if fragment.startswith(merged):
            merged = fragment
            continue
        if merged.startswith(fragment) or fragment in merged:
            continue
        overlap = min(len(merged), len(fragment))
        while overlap and merged[-overlap:] != fragment[:overlap]:
            overlap -= 1
        merged += fragment[overlap:]
    return merged


def _stream_text(value: str | bytes | None, *, encoding: str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(encoding or "utf-8", errors="replace")
    return value


def _pump_stream(pipe: Any, chunks: list[str]) -> None:
    if pipe is None:
        return
    for line in pipe:
        chunks.append(line)


@dataclass(frozen=True)
class AnchoredDirectory:
    descriptor: int | None
    boundary: Path
    relative_parts: tuple[str, ...]
    boundary_identity: tuple[int, int]
    parent_identity: tuple[int, int]
    path: Path


def path_is_link_or_reparse(status: os.stat_result) -> bool:
    reparse_mask = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(status, "st_file_attributes", 0)
    return stat.S_ISLNK(status.st_mode) or bool(attributes & reparse_mask)


def _detect_descriptor_operations() -> bool:
    required_dir_fd = {os.open, os.mkdir, os.stat, os.rename, os.unlink}
    return (
        os.name == "posix"
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and required_dir_fd.issubset(os.supports_dir_fd)
        and os.stat in os.supports_follow_symlinks
    )


_DESCRIPTOR_OPERATIONS_SUPPORTED = _detect_descriptor_operations()


def descriptor_operations_supported() -> bool:
    return _DESCRIPTOR_OPERATIONS_SUPPORTED


def close_anchored_directory(anchor: AnchoredDirectory) -> None:
    if anchor.descriptor is not None:
        os.close(anchor.descriptor)


def _portable_directory_identity(path: Path) -> tuple[int, int]:
    status = os.lstat(path)
    if path_is_link_or_reparse(status) or not stat.S_ISDIR(status.st_mode):
        raise ValueError(f"expected a real directory: {path}")
    return status.st_dev, status.st_ino


def _portable_chain(
    parent: Path,
    boundary: Path,
    *,
    create: bool,
) -> tuple[tuple[str, ...], tuple[int, int], tuple[int, int]]:
    try:
        relative = parent.relative_to(boundary)
    except ValueError as error:
        raise ValueError(
            f"output parent {parent} is outside anchored boundary {boundary}"
        ) from error
    boundary_identity = _portable_directory_identity(boundary)
    current = boundary
    for component in relative.parts:
        if _portable_directory_identity(boundary) != boundary_identity:
            raise ValueError(f"directory boundary changed during setup: {boundary}")
        current = current / component
        if not os.path.lexists(current):
            if not create:
                raise FileNotFoundError(current)
            try:
                current.mkdir()
            except FileExistsError:
                pass
        _portable_directory_identity(current)
    return relative.parts, boundary_identity, _portable_directory_identity(parent)


def directory_identity(descriptor: int) -> tuple[int, int]:
    status = os.fstat(descriptor)
    return status.st_dev, status.st_ino


def open_anchored_directory(
    parent: Path,
    boundary: Path,
    *,
    create: bool = False,
) -> AnchoredDirectory:
    parent = Path(os.path.abspath(parent))
    boundary = Path(os.path.abspath(boundary))
    try:
        relative = parent.relative_to(boundary)
    except ValueError as error:
        raise ValueError(
            f"output parent {parent} is outside anchored boundary {boundary}"
        ) from error
    if not descriptor_operations_supported():
        relative_parts, boundary_identity, parent_identity = _portable_chain(
            parent, boundary, create=create
        )
        return AnchoredDirectory(
            descriptor=None,
            boundary=boundary,
            relative_parts=relative_parts,
            boundary_identity=boundary_identity,
            parent_identity=parent_identity,
            path=parent,
        )
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(boundary, flags)
    boundary_identity = directory_identity(descriptor)
    try:
        for component in relative.parts:
            try:
                next_descriptor = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(component, mode=0o755, dir_fd=descriptor)
                except FileExistsError:
                    # Another worker may have created the same shared output
                    # directory after our failed open. Opening it below with
                    # O_DIRECTORY | O_NOFOLLOW authenticates the winner.
                    pass
                next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return AnchoredDirectory(
            descriptor=descriptor,
            boundary=boundary,
            relative_parts=relative.parts,
            boundary_identity=boundary_identity,
            parent_identity=directory_identity(descriptor),
            path=parent,
        )
    except BaseException:
        os.close(descriptor)
        raise


def ensure_anchored_directory(
    path: Path,
    *,
    boundary: Path,
    expected_boundary_identity: tuple[int, int] | None = None,
) -> tuple[int, int]:
    """Create/open a directory beneath a retained no-follow boundary fd."""

    anchor = open_anchored_directory(path, boundary, create=True)
    try:
        if (
            expected_boundary_identity is not None
            and anchor.boundary_identity != expected_boundary_identity
        ):
            raise ValueError(
                f"directory boundary was replaced before creation: {anchor.boundary}"
            )
        if not anchored_namespace_matches(anchor):
            raise ValueError(
                f"directory namespace changed during creation: {path}"
            )
        return anchor.parent_identity
    finally:
        close_anchored_directory(anchor)


def path_directory_identity(path: Path) -> tuple[int, int]:
    path = Path(os.path.abspath(path))
    if not descriptor_operations_supported():
        return _portable_directory_identity(path)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags)
    try:
        return directory_identity(descriptor)
    finally:
        os.close(descriptor)


def anchored_namespace_matches(anchor: AnchoredDirectory) -> bool:
    if anchor.descriptor is None:
        try:
            if _portable_directory_identity(anchor.boundary) != anchor.boundary_identity:
                return False
            current = anchor.boundary
            for component in anchor.relative_parts:
                current = current / component
                _portable_directory_identity(current)
            return _portable_directory_identity(current) == anchor.parent_identity
        except (OSError, ValueError):
            return False
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(anchor.boundary, flags)
    except OSError:
        return False
    try:
        if directory_identity(descriptor) != anchor.boundary_identity:
            return False
        for component in anchor.relative_parts:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return directory_identity(descriptor) == anchor.parent_identity
    except OSError:
        return False
    finally:
        os.close(descriptor)


def atomic_text_write(
    path: Path,
    value: str,
    *,
    boundary: Path | None = None,
    expected_boundary_identity: tuple[int, int] | None = None,
) -> None:
    """Atomically write text using the strongest available filesystem API."""

    path = Path(os.path.abspath(path))
    anchor = open_anchored_directory(path.parent, boundary or path.parent)
    if (
        expected_boundary_identity is not None
        and anchor.boundary_identity != expected_boundary_identity
    ):
        close_anchored_directory(anchor)
        raise ValueError(
            f"output boundary was replaced before write: {anchor.boundary}"
        )
    if anchor.descriptor is None:
        _atomic_text_write_portable(path, value, anchor)
        return
    temporary_name = f".{path.name}.{secrets.token_hex(12)}.tmp"
    descriptor: int | None = None
    replaced = False
    try:
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=anchor.descriptor,
        )
        encoded = value.encode("utf-8")
        offset = 0
        while offset < len(encoded):
            offset += os.write(descriptor, encoded[offset:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(
            temporary_name,
            path.name,
            src_dir_fd=anchor.descriptor,
            dst_dir_fd=anchor.descriptor,
        )
        replaced = True
        os.fsync(anchor.descriptor)
        if not anchored_namespace_matches(anchor):
            os.unlink(path.name, dir_fd=anchor.descriptor)
            replaced = False
            raise ValueError(
                f"output directory namespace changed during write: {path.parent}"
            )
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if not replaced:
            try:
                os.unlink(temporary_name, dir_fd=anchor.descriptor)
            except FileNotFoundError:
                pass
        os.close(anchor.descriptor)


def _require_portable_regular_file(path: Path) -> None:
    if not os.path.lexists(path):
        return
    status = os.lstat(path)
    if path_is_link_or_reparse(status) or not stat.S_ISREG(status.st_mode):
        raise ValueError(
            f"output target must be a regular file, not a link or directory: {path}"
        )


def _atomic_text_write_portable(
    path: Path,
    value: str,
    anchor: AnchoredDirectory,
) -> None:
    """Best available atomic write where directory-relative APIs are absent.

    Reparse and identity checks detect namespace replacement, but Windows
    cannot eliminate the narrow path check/use window without native handles.
    """

    _require_portable_regular_file(path)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(12)}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        encoded = value.encode("utf-8")
        offset = 0
        while offset < len(encoded):
            offset += os.write(descriptor, encoded[offset:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        if not anchored_namespace_matches(anchor):
            raise ValueError(f"output directory changed before write: {path.parent}")
        _require_portable_regular_file(path)
        os.replace(temporary, path)
        if not anchored_namespace_matches(anchor):
            raise ValueError(f"output directory changed during write: {path.parent}")
    finally:
        if descriptor is not None:
            os.close(descriptor)
        close_anchored_directory(anchor)


def read_anchored_regular_bytes(
    path: Path,
    *,
    boundary: Path,
    expected_boundary_identity: tuple[int, int] | None = None,
) -> bytes:
    """Read one regular file through a retained, no-follow directory fd."""

    path = Path(os.path.abspath(path))
    anchor = open_anchored_directory(path.parent, boundary)
    if (
        expected_boundary_identity is not None
        and anchor.boundary_identity != expected_boundary_identity
    ):
        close_anchored_directory(anchor)
        raise ValueError(
            f"input boundary was replaced before read: {anchor.boundary}"
        )
    if anchor.descriptor is None:
        try:
            status = os.lstat(path)
            if path_is_link_or_reparse(status) or not stat.S_ISREG(status.st_mode):
                raise ValueError(f"input must be a regular file: {path}")
            descriptor = os.open(
                path, os.O_RDONLY | getattr(os, "O_BINARY", 0)
            )
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise ValueError(f"input must be a regular file: {path}")
                chunks: list[bytes] = []
                while chunk := os.read(descriptor, 1024 * 1024):
                    chunks.append(chunk)
            finally:
                os.close(descriptor)
            if not anchored_namespace_matches(anchor):
                raise ValueError(
                    f"input directory namespace changed during read: {path.parent}"
                )
            return b"".join(chunks)
        finally:
            close_anchored_directory(anchor)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=anchor.descriptor,
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"input must be a regular file: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        if not anchored_namespace_matches(anchor):
            raise ValueError(
                f"input directory namespace changed during read: {path.parent}"
            )
        return b"".join(chunks)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(anchor.descriptor)


def temporary_output_path(parent: Path, label: str) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=label, suffix=".tmp", dir=parent)
    os.close(descriptor)
    return Path(name)


def read_regular_text(path: Path) -> str:
    try:
        status = os.lstat(path)
    except OSError as error:
        raise ValueError(f"backend output must be a regular file: {path}") from error
    if path_is_link_or_reparse(status) or not stat.S_ISREG(status.st_mode):
        raise ValueError(f"backend output must be a regular file: {path}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "r", encoding="utf-8", errors="replace") as source:
        return source.read()


def rubric_failure_payload(returncode: int, stderr: str) -> str:
    return json.dumps(
        {
            "overall_pass": False,
            "score": 0,
            "checks": [
                {
                    "id": "rubric-run",
                    "pass": False,
                    "notes": f"Agent rubric grader exited with {returncode}",
                    "evidence": stderr[-1000:],
                }
            ],
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# Codex backend
# ---------------------------------------------------------------------------


def _codex_subprocess_env(exec_dir: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    clean_package_config = env.get("CODEX_EVAL_CLEAN_PACKAGE_CONFIG", "1").strip().lower()
    if clean_package_config in {"1", "true", "yes", "on"}:
        default_index = env.get("UV_DEFAULT_INDEX") or env.get("PIP_INDEX_URL") or "https://pypi.org/simple"
        env["UV_NO_CONFIG"] = "1"
        env["UV_DEFAULT_INDEX"] = default_index
        env["PIP_CONFIG_FILE"] = os.devnull
        env["PIP_INDEX_URL"] = default_index
        env.pop("PIP_EXTRA_INDEX_URL", None)
    if exec_dir is not None:
        env["UV_CACHE_DIR"] = str(exec_dir / ".uv-cache")
        env["PIP_CACHE_DIR"] = str(exec_dir / ".pip-cache")
    return env


@dataclass
class CodexBackend:
    command: str = "codex"
    extra_args: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "codex"

    def run_agent(
        self,
        *,
        prompt: str,
        exec_dir: Path,
        model: str | None = None,
        timeout: int = 1200,
    ) -> AgentResult:
        exec_dir_identity = path_directory_identity(exec_dir)
        trace_path = exec_dir / "trace.jsonl"
        final_path = exec_dir / "last_message.md"
        stderr_path = exec_dir / "stderr.txt"
        raw_final_path = temporary_output_path(exec_dir, ".codex-final-")

        cmd = [
            self.command,
            "exec",
            "--json",
            "--full-auto",
            "--skip-git-repo-check",
            "--cd",
            str(exec_dir),
            "--output-last-message",
            str(raw_final_path),
            *self.extra_args,
        ]
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)

        try:
            completed = run_streamed_command(
                cmd,
                stdout_path=trace_path,
                stderr_path=stderr_path,
                timeout=timeout,
                env=_codex_subprocess_env(exec_dir),
            )
            final_value = read_regular_text(raw_final_path)
            atomic_text_write(
                final_path,
                final_value,
                boundary=exec_dir,
                expected_boundary_identity=exec_dir_identity,
            )
        finally:
            raw_final_path.unlink(missing_ok=True)

        return AgentResult(
            returncode=completed.returncode,
            trace_path=trace_path,
            final_message_path=final_path,
            stderr_path=stderr_path,
        )

    def run_judge(
        self,
        *,
        prompt: str,
        exec_dir: Path,
        model: str | None = None,
        schema_path: Path | None = None,
        timeout: int = 900,
    ) -> AgentResult:
        exec_dir_identity = path_directory_identity(exec_dir)
        output_path = exec_dir / "rubric_grade.json"
        raw_output_path = temporary_output_path(exec_dir, ".codex-rubric-")
        trace_path = exec_dir / "rubric_trace.jsonl"
        stderr_path = exec_dir / "rubric_stderr.txt"

        cmd = [
            self.command,
            "exec",
            "--json",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--cd",
            str(exec_dir),
        ]
        if schema_path:
            cmd.extend(["--output-schema", str(schema_path)])
        cmd.extend(["--output-last-message", str(raw_output_path), *self.extra_args])
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)

        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            atomic_text_write(
                trace_path,
                completed.stdout,
                boundary=exec_dir,
                expected_boundary_identity=exec_dir_identity,
            )
            atomic_text_write(
                stderr_path,
                completed.stderr,
                boundary=exec_dir,
                expected_boundary_identity=exec_dir_identity,
            )
            output = read_regular_text(raw_output_path)
            if completed.returncode != 0 and not output.strip():
                output = rubric_failure_payload(
                    completed.returncode, completed.stderr
                )
            atomic_text_write(
                output_path,
                output,
                boundary=exec_dir,
                expected_boundary_identity=exec_dir_identity,
            )
        finally:
            raw_output_path.unlink(missing_ok=True)

        return AgentResult(
            returncode=completed.returncode,
            trace_path=trace_path,
            final_message_path=output_path,
            stderr_path=stderr_path,
        )

    def parse_trace(self, trace_path: Path) -> TraceSummary:
        return parse_trace(trace_path)


# ---------------------------------------------------------------------------
# Cursor backend
# ---------------------------------------------------------------------------


@dataclass
class CursorBackend:
    command: str = "cursor"
    extra_args: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "cursor"

    def run_agent(
        self,
        *,
        prompt: str,
        exec_dir: Path,
        model: str | None = None,
        timeout: int = 1200,
    ) -> AgentResult:
        exec_dir_identity = path_directory_identity(exec_dir)
        trace_path = exec_dir / "trace.jsonl"
        final_path = exec_dir / "last_message.md"
        stderr_path = exec_dir / "stderr.txt"
        raw_final_path = temporary_output_path(exec_dir, ".cursor-final-")

        cmd = [
            self.command,
            "--cli",
            "agent",
            "--full-auto",
            "--skip-git-repo-check",
            "--cd",
            str(exec_dir),
            "--output-last-message",
            str(raw_final_path),
            *self.extra_args,
        ]
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)

        try:
            completed = run_streamed_command(
                cmd,
                stdout_path=trace_path,
                stderr_path=stderr_path,
                timeout=timeout,
            )
            atomic_text_write(
                final_path,
                read_regular_text(raw_final_path),
                boundary=exec_dir,
                expected_boundary_identity=exec_dir_identity,
            )
        finally:
            raw_final_path.unlink(missing_ok=True)

        return AgentResult(
            returncode=completed.returncode,
            trace_path=trace_path,
            final_message_path=final_path,
            stderr_path=stderr_path,
        )

    def run_judge(
        self,
        *,
        prompt: str,
        exec_dir: Path,
        model: str | None = None,
        schema_path: Path | None = None,
        timeout: int = 900,
    ) -> AgentResult:
        exec_dir_identity = path_directory_identity(exec_dir)
        output_path = exec_dir / "rubric_grade.json"
        raw_output_path = temporary_output_path(exec_dir, ".cursor-rubric-")
        trace_path = exec_dir / "rubric_trace.jsonl"
        stderr_path = exec_dir / "rubric_stderr.txt"

        cmd = [
            self.command,
            "--cli",
            "agent",
            "--full-auto",
            "--skip-git-repo-check",
            "--cd",
            str(exec_dir),
        ]
        if schema_path:
            cmd.extend(["--output-schema", str(schema_path)])
        cmd.extend(["--output-last-message", str(raw_output_path), *self.extra_args])
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)

        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            atomic_text_write(
                trace_path,
                completed.stdout,
                boundary=exec_dir,
                expected_boundary_identity=exec_dir_identity,
            )
            atomic_text_write(
                stderr_path,
                completed.stderr,
                boundary=exec_dir,
                expected_boundary_identity=exec_dir_identity,
            )
            output = read_regular_text(raw_output_path)
            if completed.returncode != 0 and not output.strip():
                output = rubric_failure_payload(
                    completed.returncode, completed.stderr
                )
            atomic_text_write(
                output_path,
                output,
                boundary=exec_dir,
                expected_boundary_identity=exec_dir_identity,
            )
        finally:
            raw_output_path.unlink(missing_ok=True)

        return AgentResult(
            returncode=completed.returncode,
            trace_path=trace_path,
            final_message_path=output_path,
            stderr_path=stderr_path,
        )

    def parse_trace(self, trace_path: Path) -> TraceSummary:
        return parse_trace(trace_path)


# ---------------------------------------------------------------------------
# Claude Code backend
# ---------------------------------------------------------------------------


@dataclass
class ClaudeBackend:
    command: str = "claude"
    extra_args: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "claude"

    def run_agent(
        self,
        *,
        prompt: str,
        exec_dir: Path,
        model: str | None = None,
        timeout: int = 1200,
    ) -> AgentResult:
        exec_dir_identity = path_directory_identity(exec_dir)
        trace_path = exec_dir / "trace.jsonl"
        final_path = exec_dir / "last_message.md"
        stderr_path = exec_dir / "stderr.txt"

        cmd = [
            self.command,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--max-turns",
            "50",
            *self.extra_args,
        ]
        if model:
            cmd.extend(["--model", model])

        completed = run_streamed_command(
            cmd,
            stdout_path=trace_path,
            stderr_path=stderr_path,
            timeout=timeout,
            env=_claude_subprocess_env(exec_dir),
        )
        _extract_claude_final_message(
            trace_path, final_path, exec_dir_identity=exec_dir_identity
        )

        return AgentResult(
            returncode=completed.returncode,
            trace_path=trace_path,
            final_message_path=final_path,
            stderr_path=stderr_path,
        )

    def run_judge(
        self,
        *,
        prompt: str,
        exec_dir: Path,
        model: str | None = None,
        schema_path: Path | None = None,
        timeout: int = 900,
    ) -> AgentResult:
        exec_dir_identity = path_directory_identity(exec_dir)
        output_path = exec_dir / "rubric_grade.json"
        trace_path = exec_dir / "rubric_trace.jsonl"
        stderr_path = exec_dir / "rubric_stderr.txt"

        judge_prompt = prompt
        if schema_path:
            schema_text = schema_path.read_text(encoding="utf-8")
            judge_prompt = f"{prompt}\n\nOutput must conform to this JSON schema:\n{schema_text}"

        cmd = [
            self.command,
            "-p",
            judge_prompt,
            "--output-format",
            "json",
            "--max-turns",
            "5",
            *self.extra_args,
        ]
        if model:
            cmd.extend(["--model", model])

        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=exec_dir,
        )
        atomic_text_write(
            trace_path,
            completed.stdout,
            boundary=exec_dir,
            expected_boundary_identity=exec_dir_identity,
        )
        atomic_text_write(
            stderr_path,
            completed.stderr,
            boundary=exec_dir,
            expected_boundary_identity=exec_dir_identity,
        )

        _extract_claude_final_message(
            trace_path, output_path, exec_dir_identity=exec_dir_identity
        )

        if completed.returncode != 0 and not read_regular_text(output_path).strip():
            atomic_text_write(
                output_path,
                rubric_failure_payload(completed.returncode, completed.stderr),
                boundary=exec_dir,
                expected_boundary_identity=exec_dir_identity,
            )

        return AgentResult(
            returncode=completed.returncode,
            trace_path=trace_path,
            final_message_path=output_path,
            stderr_path=stderr_path,
        )

    def parse_trace(self, trace_path: Path) -> TraceSummary:
        return _parse_claude_trace(trace_path)


def _claude_subprocess_env(exec_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["CLAUDE_CWD"] = str(exec_dir)
    return env


def _extract_claude_final_message(
    trace_path: Path,
    output_path: Path,
    *,
    exec_dir_identity: tuple[int, int] | None = None,
) -> None:
    """Extract the last assistant text from Claude JSON output."""
    try:
        raw = read_regular_text(trace_path)
        data = json.loads(raw) if raw.strip() else {}
        result_text = ""
        if isinstance(data, dict):
            result_text = data.get("result", "") or ""
        elif isinstance(data, list) and data:
            last = data[-1]
            if isinstance(last, dict):
                result_text = last.get("content", "") or last.get("result", "") or ""
        atomic_text_write(
            output_path,
            result_text,
            boundary=output_path.parent,
            expected_boundary_identity=exec_dir_identity,
        )
    except (json.JSONDecodeError, OSError, ValueError):
        atomic_text_write(
            output_path,
            "",
            boundary=output_path.parent,
            expected_boundary_identity=exec_dir_identity,
        )


def _parse_claude_trace(trace_path: Path) -> TraceSummary:
    """Parse Claude Code JSON output into TraceSummary (best-effort)."""
    from .trace import CommandEvent, TraceSummary, TraceUsage

    raw = trace_path.read_text(encoding="utf-8", errors="replace")
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return TraceSummary([], raw)

    events: list[dict[str, Any]] = []
    if isinstance(data, dict):
        events = [data]
    elif isinstance(data, list):
        events = data

    commands: list[CommandEvent] = []
    usage = TraceUsage()
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("type") == "tool_use" and event.get("name") in {"bash", "execute_command"}:
            cmd_text = ""
            inp = event.get("input", {})
            if isinstance(inp, dict):
                cmd_text = inp.get("command", "")
            if cmd_text:
                commands.append(CommandEvent(command=cmd_text))
        u = event.get("usage")
        if isinstance(u, dict):
            usage.input_tokens += int(u.get("input_tokens") or 0)
            usage.output_tokens += int(u.get("output_tokens") or 0)

    if usage.total_tokens == 0:
        usage.total_tokens = usage.input_tokens + usage.output_tokens
    summary = TraceSummary(events, raw)
    summary.commands = commands
    summary.usage = usage
    return summary


# ---------------------------------------------------------------------------
# Backend registry
# ---------------------------------------------------------------------------

BACKEND_REGISTRY: dict[str, type] = {
    "codex": CodexBackend,
    "cursor": CursorBackend,
    "claude": ClaudeBackend,
}


def create_backend(
    name: str = "codex",
    command: str | None = None,
    extra_args: list[str] | None = None,
) -> AgentBackend:
    cls = BACKEND_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"unknown agent backend: {name!r}; available: {', '.join(BACKEND_REGISTRY)}")
    kwargs: dict[str, Any] = {}
    if command is not None:
        kwargs["command"] = command
    if extra_args is not None:
        kwargs["extra_args"] = extra_args
    return cls(**kwargs)
