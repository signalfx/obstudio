from __future__ import annotations

import json
import os
import subprocess
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
        args=(process.stdout, stdout_path, stdout_chunks),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_pump_stream,
        args=(process.stderr, stderr_path, stderr_chunks),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        raise
    stdout_thread.join()
    stderr_thread.join()
    return StreamedCommandResult(
        returncode=returncode,
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
    )


def _pump_stream(pipe: Any, output_path: Path, chunks: list[str]) -> None:
    if pipe is None:
        output_path.write_text("", encoding="utf-8")
        return
    with output_path.open("w", encoding="utf-8") as output:
        for line in pipe:
            chunks.append(line)
            output.write(line)
            output.flush()


# ---------------------------------------------------------------------------
# Codex backend
# ---------------------------------------------------------------------------


def _codex_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    clean_package_config = env.get("CODEX_EVAL_CLEAN_PACKAGE_CONFIG", "1").strip().lower()
    if clean_package_config in {"1", "true", "yes", "on"}:
        default_index = env.get("UV_DEFAULT_INDEX") or env.get("PIP_INDEX_URL") or "https://pypi.org/simple"
        env["UV_NO_CONFIG"] = "1"
        env["UV_DEFAULT_INDEX"] = default_index
        env["PIP_CONFIG_FILE"] = os.devnull
        env["PIP_INDEX_URL"] = default_index
        env.pop("PIP_EXTRA_INDEX_URL", None)
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
        trace_path = exec_dir / "trace.jsonl"
        final_path = exec_dir / "last_message.md"
        stderr_path = exec_dir / "stderr.txt"

        cmd = [
            self.command,
            "exec",
            "--json",
            "--full-auto",
            "--skip-git-repo-check",
            "--cd",
            str(exec_dir),
            "--output-last-message",
            str(final_path),
            *self.extra_args,
        ]
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)

        completed = run_streamed_command(
            cmd,
            stdout_path=trace_path,
            stderr_path=stderr_path,
            timeout=timeout,
            env=_codex_subprocess_env(),
        )
        if not final_path.exists():
            final_path.write_text("", encoding="utf-8")

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
        output_path = exec_dir / "rubric_grade.json"
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
        cmd.extend(["--output-last-message", str(output_path), *self.extra_args])
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)

        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        trace_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")

        if completed.returncode != 0 and not output_path.exists():
            output_path.write_text(
                json.dumps(
                    {
                        "overall_pass": False,
                        "score": 0,
                        "checks": [
                            {
                                "id": "rubric-run",
                                "pass": False,
                                "notes": f"Agent rubric grader exited with {completed.returncode}",
                                "evidence": completed.stderr[-1000:],
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

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
        trace_path = exec_dir / "trace.jsonl"
        final_path = exec_dir / "last_message.md"
        stderr_path = exec_dir / "stderr.txt"

        cmd = [
            self.command,
            "--cli",
            "agent",
            "--full-auto",
            "--skip-git-repo-check",
            "--cd",
            str(exec_dir),
            "--output-last-message",
            str(final_path),
            *self.extra_args,
        ]
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)

        completed = run_streamed_command(
            cmd,
            stdout_path=trace_path,
            stderr_path=stderr_path,
            timeout=timeout,
        )
        if not final_path.exists():
            final_path.write_text("", encoding="utf-8")

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
        output_path = exec_dir / "rubric_grade.json"
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
        cmd.extend(["--output-last-message", str(output_path), *self.extra_args])
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)

        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        trace_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")

        if completed.returncode != 0 and not output_path.exists():
            output_path.write_text(
                json.dumps(
                    {
                        "overall_pass": False,
                        "score": 0,
                        "checks": [
                            {
                                "id": "rubric-run",
                                "pass": False,
                                "notes": f"Agent rubric grader exited with {completed.returncode}",
                                "evidence": completed.stderr[-1000:],
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

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
        if not final_path.exists():
            _extract_claude_final_message(trace_path, final_path)

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
        trace_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")

        _extract_claude_final_message(trace_path, output_path)

        if completed.returncode != 0 and not output_path.exists():
            output_path.write_text(
                json.dumps(
                    {
                        "overall_pass": False,
                        "score": 0,
                        "checks": [
                            {
                                "id": "rubric-run",
                                "pass": False,
                                "notes": f"Agent rubric grader exited with {completed.returncode}",
                                "evidence": completed.stderr[-1000:],
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
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


def _extract_claude_final_message(trace_path: Path, output_path: Path) -> None:
    """Extract the last assistant text from Claude JSON output."""
    try:
        raw = trace_path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw) if raw.strip() else {}
        result_text = ""
        if isinstance(data, dict):
            result_text = data.get("result", "") or ""
        elif isinstance(data, list) and data:
            last = data[-1]
            if isinstance(last, dict):
                result_text = last.get("content", "") or last.get("result", "") or ""
        output_path.write_text(result_text, encoding="utf-8")
    except (json.JSONDecodeError, OSError):
        output_path.write_text("", encoding="utf-8")


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
