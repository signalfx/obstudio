from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .base import BaseEvalCase, BaseEvalDefinition


# ---------------------------------------------------------------------------
# Generic endpoint expectation (domain-agnostic)
# ---------------------------------------------------------------------------


class EndpointExpectation(BaseModel):
    id: str
    url: str = ""
    method: str = "GET"
    contains_all: list[str] = Field(default_factory=list)
    contains_any: list[str] = Field(default_factory=list)
    field_checks: dict[str, list[str]] = Field(default_factory=dict)
    detail_path_template: str | None = None
    detail_id_field: str | None = None
    detail_contains_all: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Runtime expectations
# ---------------------------------------------------------------------------


class RuntimeExpectations(BaseModel):
    service_name: str = "observer"
    service_port: int = 3000
    health_path: str = "/api/health"
    clear_path: str | None = "/api/data"
    clear_method: str = "DELETE"
    endpoints: list[EndpointExpectation] = Field(default_factory=list)

    def has_expectations(self) -> bool:
        return bool(self.endpoints)


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
