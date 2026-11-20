from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .base import BaseEvalCase, BaseEvalDefinition
from ..rubric_base import validate_rubric_dimensions


class RubricDimension(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    criteria: list[str] = Field(min_length=1)


def _validate_dimensions(rubric: list[str], dimensions: list[RubricDimension], strict: bool) -> None:
    validate_rubric_dimensions(rubric, [dimension.model_dump() for dimension in dimensions], strict)


class RubricEvalDefinition(BaseEvalDefinition):
    rubric: list[str]
    judge_prompt: str | None = None
    judge_inputs: list[str] = Field(default_factory=list)
    strict_rubric_output: bool = False
    rubric_dimensions: list[RubricDimension] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_dimensions(self) -> Self:
        _validate_dimensions(self.rubric, self.rubric_dimensions, self.strict_rubric_output)
        return self

    @property
    def kind(self) -> Literal["rubric"]:
        return "rubric"


class RubricEvalCase(BaseEvalCase):
    rubric: list[str]
    judge_prompt: str | None = None
    judge_inputs: list[str] = Field(default_factory=list)
    strict_rubric_output: bool = False
    rubric_dimensions: list[RubricDimension] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_dimensions(self) -> Self:
        _validate_dimensions(self.rubric, self.rubric_dimensions, self.strict_rubric_output)
        return self

    @property
    def kind(self) -> Literal["rubric"]:
        return "rubric"
