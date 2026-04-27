from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CodexEvalSettings:
    live_ab: bool = False
    qualitative_enabled: bool = True
    agent_model: str | None = None
    judge_model: str | None = None


def load_settings(path: Path | None) -> CodexEvalSettings:
    if path is None or not path.exists():
        return CodexEvalSettings()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    run = table(data, "run")
    qualitative = table(data, "qualitative")
    models = table(data, "models")
    return CodexEvalSettings(
        live_ab=bool(run.get("live_ab", False)),
        qualitative_enabled=bool(qualitative.get("enabled", True)),
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
