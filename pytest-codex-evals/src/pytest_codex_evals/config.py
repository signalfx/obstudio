from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CodexEvalSettings:
    run_mode: str = "validation"
    eval_kind: str = "validation"
    rubric_enabled: bool = True
    runtime_enabled: bool = False
    agent_model: str | None = None
    judge_model: str | None = None
    agent_backend: str = "codex"
    agent_command: str | None = None
    agent_extra_args: tuple[str, ...] = ()
    agent_timeout: int = 1200
    judge_timeout: int = 900


def load_settings(path: Path | None) -> CodexEvalSettings:
    if path is None or not path.exists():
        return CodexEvalSettings()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    run = table(data, "run")
    rubric = table(data, "rubric")
    runtime = table(data, "runtime")
    models = table(data, "models")
    agent = table(data, "agent")
    return CodexEvalSettings(
        run_mode=run_mode(run),
        eval_kind=eval_kind(run),
        rubric_enabled=bool(rubric.get("enabled", True)),
        runtime_enabled=bool(runtime.get("enabled", False)),
        agent_model=optional_string(models.get("agent")),
        judge_model=optional_string(models.get("judge")),
        agent_backend=agent_backend(agent),
        agent_command=optional_string(agent.get("command")),
        agent_extra_args=agent_extra_args(agent),
        agent_timeout=int(agent.get("timeout", 1200)),
        judge_timeout=int(agent.get("judge_timeout", 900)),
    )


def table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"[{key}] must be a table")
    return value


def optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("model values must be strings")
    stripped = value.strip()
    return stripped or None


def run_mode(run: dict[str, Any]) -> str:
    value = run.get("mode")
    if value is None:
        return "ab" if bool(run.get("live_ab", False)) else "validation"
    if not isinstance(value, str):
        raise ValueError("[run].mode must be a string")
    normalized = value.strip().lower().replace("-", "_")
    aliases = {
        "skill": "with_skill",
        "baseline": "with_baseline",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"validation", "with_skill", "with_baseline", "ab"}:
        raise ValueError("[run].mode must be one of: validation, with_skill, with_baseline, ab")
    return normalized


def eval_kind(run: dict[str, Any]) -> str:
    value = run.get("eval_kind", run.get("kind"))
    if value is None:
        return "validation" if run_mode(run) == "validation" else "standard"
    if not isinstance(value, str):
        raise ValueError("[run].eval_kind must be a string")
    normalized = value.strip().lower().replace("-", "_")
    aliases = {
        "sanity": "sanity",
        "rubric": "rubric",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"validation", "standard", "sanity", "rubric", "runtime"}:
        raise ValueError("[run].eval_kind must be one of: validation, standard, sanity, rubric, runtime")
    return normalized


def agent_backend(agent: dict[str, Any]) -> str:
    value = agent.get("backend", "codex")
    if not isinstance(value, str):
        raise ValueError("[agent].backend must be a string")
    normalized = value.strip().lower()
    if normalized not in {"codex", "cursor", "claude"}:
        raise ValueError("[agent].backend must be one of: codex, cursor, claude")
    return normalized


def agent_extra_args(agent: dict[str, Any]) -> tuple[str, ...]:
    value = agent.get("extra_args", [])
    if not isinstance(value, list):
        raise ValueError("[agent].extra_args must be a list of strings")
    return tuple(str(arg) for arg in value)
