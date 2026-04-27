from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CodexEvalSettings:
    run_mode: str = "validation"
    qualitative_enabled: bool = True
    runtime_enabled: bool = False
    agent_model: str | None = None
    judge_model: str | None = None


def load_settings(path: Path | None) -> CodexEvalSettings:
    if path is None or not path.exists():
        return CodexEvalSettings()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    run = table(data, "run")
    qualitative = table(data, "qualitative")
    runtime = table(data, "runtime")
    models = table(data, "models")
    return CodexEvalSettings(
        run_mode=run_mode(run),
        qualitative_enabled=bool(qualitative.get("enabled", True)),
        runtime_enabled=bool(runtime.get("enabled", False)),
        agent_model=optional_string(models.get("agent")),
        judge_model=optional_string(models.get("judge")),
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
