from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, model_validator

from .base import BaseEvalCase, BaseEvalDefinition


# ---------------------------------------------------------------------------
# Generic endpoint expectation (domain-agnostic)
# ---------------------------------------------------------------------------


class JSONRecordExpectation(BaseModel):
    """Structured assertions over records returned by a JSON-list endpoint."""

    model_config = ConfigDict(extra="forbid")

    id: str
    match: dict[str, Any] = Field(default_factory=dict)
    match_contains: dict[str, str] = Field(default_factory=dict)
    field_equals: dict[str, Any] = Field(default_factory=dict)
    field_contains: dict[str, str] = Field(default_factory=dict)
    non_empty: list[str] = Field(default_factory=list)
    exact_count: int | None = Field(default=None, ge=0)
    unique_by: list[str] = Field(default_factory=list)
    correlates_with_trace: bool = False


class EndpointExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    url: str = ""
    method: str = "GET"
    contains_all: list[str] = Field(default_factory=list)
    contains_any: list[str] = Field(default_factory=list)
    field_checks: dict[str, list[str]] = Field(default_factory=dict)
    detail_path_template: str | None = None
    detail_id_field: str | None = None
    detail_contains_all: list[str] = Field(default_factory=list)
    record_checks: list[JSONRecordExpectation] = Field(default_factory=list)


class ServiceLogExpectation(BaseModel):
    """Assertions over a Compose service's preserved stdout/stderr output."""

    model_config = ConfigDict(extra="forbid")

    id: str
    service_name: str = "app"
    contains_all: list[str] = Field(default_factory=list)
    occurrences: dict[str, NonNegativeInt] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_assertion(self) -> Self:
        values = [*self.contains_all, *self.occurrences]
        if not values:
            raise ValueError("service log expectation must include contains_all or occurrences")
        if any(not value.strip() for value in values):
            raise ValueError("service log expectation values must not be empty")
        return self


# ---------------------------------------------------------------------------
# Runtime expectations
# ---------------------------------------------------------------------------


class RuntimeExpectations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_name: str = "observer"
    service_port: int = 3000
    health_path: str = "/api/health"
    clear_path: str | None = "/api/data"
    clear_method: str = "DELETE"
    endpoints: list[EndpointExpectation] = Field(default_factory=list)
    service_logs: list[ServiceLogExpectation] = Field(default_factory=list)

    def has_expectations(self) -> bool:
        return bool(self.endpoints or self.service_logs)

    @model_validator(mode="after")
    def require_expectation(self) -> Self:
        if not self.has_expectations():
            raise ValueError("runtime expect must include endpoints or service_logs")
        return self


class RuntimeCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    description: str
    compose_file: str
    expect: RuntimeExpectations
    timeout_seconds: int = 300
    settle_seconds: float = 5
    environment: dict[str, str] = Field(default_factory=dict)
    stop_services_before_validation: list[Literal["app"]] = Field(
        default_factory=list,
        max_length=1,
    )
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
