from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .base import BaseEvalCase, BaseEvalDefinition


class ObserverExpectation(BaseModel):
    path: str | None = None
    contains_all: list[str] = Field(default_factory=list)
    contains_any: list[str] = Field(default_factory=list)
    service_names: list[str] = Field(default_factory=list)
    span_names: list[str] = Field(default_factory=list)
    metric_names: list[str] = Field(default_factory=list)


class RuntimeExpectations(BaseModel):
    traces: ObserverExpectation | None = None
    metrics: ObserverExpectation | None = None


class RuntimeCheck(BaseModel):
    id: str
    description: str
    compose_file: str
    expect: RuntimeExpectations
    timeout_seconds: int = 300
    settle_seconds: float = 5
    applies_to: Literal["both", "with_skill", "baseline"] = "with_skill"


class RuntimeEvalDefinition(BaseEvalDefinition):
    checks: list[RuntimeCheck]

    @property
    def kind(self) -> Literal["runtime"]:
        return "runtime"


class RuntimeEvalCase(BaseEvalCase):
    checks: list[RuntimeCheck]

    @property
    def kind(self) -> Literal["runtime"]:
        return "runtime"
