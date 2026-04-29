from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import BaseEvalCase, BaseEvalDefinition


class RubricEvalDefinition(BaseEvalDefinition):
    rubric: list[str]
    judge_prompt: str | None = None
    judge_inputs: list[str] = Field(default_factory=list)

    @property
    def kind(self) -> Literal["rubric"]:
        return "rubric"


class RubricEvalCase(BaseEvalCase):
    rubric: list[str]
    judge_prompt: str | None = None
    judge_inputs: list[str] = Field(default_factory=list)

    @property
    def kind(self) -> Literal["rubric"]:
        return "rubric"
