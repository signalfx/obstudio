from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from pydantic import Field

from .base import BaseEvalCase, BaseEvalDefinition


SanityCheckKind = Literal[
    "final_contains_all",
    "final_contains_any",
    "file_exists",
    "file_exists_any",
    "no_file_exists",
    "file_contains_all",
    "file_contains_any",
    "command_succeeds",
    "command_stdout_contains_all",
    "command_stdout_contains_any",
    "command_stdout_contains_none",
]


class SanityCheck(BaseModel):
    id: str
    description: str
    kind: SanityCheckKind
    path: str | None = None
    paths: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    command: list[str] = Field(default_factory=list)
    cwd: str | None = None
    timeout_seconds: int = 30
    applies_to: Literal["both", "with_skill", "baseline"] = "with_skill"


class SanityEvalDefinition(BaseEvalDefinition):
    checks: list[SanityCheck] = Field(default_factory=list)

    @property
    def kind(self) -> Literal["sanity"]:
        return "sanity"


class SanityEvalCase(BaseEvalCase):
    checks: list[SanityCheck] = Field(default_factory=list)

    @property
    def kind(self) -> Literal["sanity"]:
        return "sanity"
