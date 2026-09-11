from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .trace import ActionEvent, CommandEvent, TraceSummary, parse_events, parse_trace


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


def _codex_subprocess_env(exec_dir: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    clean_package_config = (
        env.get("CODEX_EVAL_CLEAN_PACKAGE_CONFIG", "1").strip().lower()
    )
    if clean_package_config in {"1", "true", "yes", "on"}:
        default_index = (
            env.get("UV_DEFAULT_INDEX")
            or env.get("PIP_INDEX_URL")
            or "https://pypi.org/simple"
        )
        env["UV_NO_CONFIG"] = "1"
        env["UV_DEFAULT_INDEX"] = default_index
        env["PIP_CONFIG_FILE"] = os.devnull
        env["PIP_INDEX_URL"] = default_index
        env.pop("PIP_EXTRA_INDEX_URL", None)
    if exec_dir is not None:
        env["UV_CACHE_DIR"] = str(exec_dir / ".uv-cache")
        env["PIP_CACHE_DIR"] = str(exec_dir / ".pip-cache")
    return env


def _judge_subprocess_env(
    env: dict[str, str], *, claude: bool = False
) -> dict[str, str]:
    scoped = env.copy()
    scoped["OTEL_SDK_DISABLED"] = "true"
    scoped["OTEL_LOGS_EXPORTER"] = "none"
    scoped["OTEL_TRACES_EXPORTER"] = "none"
    scoped["OTEL_METRICS_EXPORTER"] = "none"
    if claude:
        scoped["CLAUDE_CODE_ENABLE_TELEMETRY"] = "0"
        scoped["CLAUDE_CODE_ENHANCED_TELEMETRY_BETA"] = "0"
    return scoped


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
            "--config",
            "shell_environment_policy.inherit=all",
            "--sandbox",
            "workspace-write",
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
            env=_codex_subprocess_env(exec_dir),
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
        cmd.extend(
            [
                "--config",
                'otel.exporter="none"',
                "--config",
                'otel.trace_exporter="none"',
            ]
        )
        cmd.append(prompt)

        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_judge_subprocess_env(_codex_subprocess_env(exec_dir)),
        )
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
        return parse_trace(trace_path, provider="codex")


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
        return parse_trace(trace_path, provider="unknown")


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
            "stream-json",
            "--verbose",
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
            judge_prompt = (
                f"{prompt}\n\nOutput must conform to this JSON schema:\n{schema_text}"
            )

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
            env=_judge_subprocess_env(_claude_subprocess_env(exec_dir), claude=True),
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
        events = _claude_json_events(raw)
        result_text = ""
        for event in events:
            result = event.get("result")
            if isinstance(result, str) and result:
                result_text = result
                continue
            content = event.get("content")
            if isinstance(content, str) and content:
                result_text = content
                continue
            message = event.get("message")
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            text_blocks = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            assistant_text = "\n".join(
                text for text in text_blocks if isinstance(text, str) and text
            )
            if assistant_text:
                result_text = assistant_text
        output_path.write_text(result_text, encoding="utf-8")
    except OSError:
        output_path.write_text("", encoding="utf-8")


def _claude_json_events(raw: str) -> list[dict[str, Any]]:
    return parse_events(raw)


def _parse_claude_trace(trace_path: Path) -> TraceSummary:
    """Parse Claude Code JSON output into TraceSummary (best-effort)."""
    raw = trace_path.read_text(encoding="utf-8", errors="replace")
    events = _claude_json_events(raw)

    actions: list[ActionEvent] = []
    actions_by_tool_id: dict[str, ActionEvent] = {}
    for order, event in enumerate(events):
        _append_claude_tool_use(event, actions, actions_by_tool_id, order)
        _complete_claude_tool_results(event, actions_by_tool_id, order)

    summary = TraceSummary(events, raw, provider="claude")
    summary.actions = actions
    summary.commands = [
        CommandEvent(command=command, status=action.status)
        for action in actions
        if (command := _claude_command_text(action)) is not None
    ]
    return summary


def _append_claude_tool_use(
    event: dict[str, Any],
    actions: list[ActionEvent],
    actions_by_tool_id: dict[str, ActionEvent],
    order: int,
) -> None:
    blocks: list[dict[str, Any]] = []
    if event.get("type") == "tool_use":
        blocks.append(event)
    message = event.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), list):
        blocks.extend(
            block
            for block in message["content"]
            if isinstance(block, dict) and block.get("type") == "tool_use"
        )
    for block in blocks:
        name = str(block.get("name") or "").lower()
        tool_input = block.get("input")
        normalized_input = dict(tool_input) if isinstance(tool_input, dict) else {}
        action = ActionEvent(
            kind="command" if name in {"bash", "execute_command"} else "tool",
            name=name or "unknown_tool",
            status="started",
            input=normalized_input,
            start_order=order,
        )
        actions.append(action)
        tool_id = block.get("id")
        if isinstance(tool_id, str) and tool_id:
            actions_by_tool_id[tool_id] = action


def _complete_claude_tool_results(
    event: dict[str, Any],
    actions_by_tool_id: dict[str, ActionEvent],
    order: int,
) -> None:
    blocks: list[dict[str, Any]] = []
    if event.get("type") == "tool_result":
        blocks.append(event)
    message = event.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), list):
        blocks.extend(
            block
            for block in message["content"]
            if isinstance(block, dict) and block.get("type") == "tool_result"
        )
    for block in blocks:
        tool_id = block.get("tool_use_id")
        if not isinstance(tool_id, str):
            continue
        action = actions_by_tool_id.get(tool_id)
        if action is not None:
            action.status = "failed" if block.get("is_error") is True else "completed"
            action.result = block.get("content")
            action.output = _claude_tool_result_text(action.result)
            action.completion_order = order


def _claude_command_text(action: ActionEvent) -> str | None:
    if action.name in {"bash", "execute_command"}:
        command = action.input.get("command")
        return command if isinstance(command, str) else None
    if action.name in {"read", "read_file"}:
        path = action.input.get("file_path") or action.input.get("path")
        return f"read {path}" if isinstance(path, str) else None
    return None


def _claude_tool_result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    values: list[str] = []
    for block in content:
        if isinstance(block, str):
            values.append(block)
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
            values.append(block["text"])
    return "\n".join(values)


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
        raise ValueError(
            f"unknown agent backend: {name!r}; available: {', '.join(BACKEND_REGISTRY)}"
        )
    kwargs: dict[str, Any] = {}
    if command is not None:
        kwargs["command"] = command
    if extra_args is not None:
        kwargs["extra_args"] = extra_args
    return cls(**kwargs)
