from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EvalRole = Literal["sanity", "rubric", "runtime"]
CheckCategory = Literal["sanity", "runtime"]


def validate_eval_input_paths(values: list[str] | None) -> list[str] | None:
    """Require fixture-root-relative file paths below eval/inputs."""

    if values is None:
        return None
    seen: set[str] = set()
    for value in values:
        candidate = Path(value)
        if (
            not value
            or "\\" in value
            or candidate.is_absolute()
            or candidate.parts[:2] != ("eval", "inputs")
            or len(candidate.parts) < 3
            or any(part in {"", ".", ".."} for part in candidate.parts)
            or candidate.as_posix() != value
        ):
            raise ValueError(
                "eval_inputs entries must be safe relative file paths under "
                "eval/inputs"
            )
        if value in seen:
            raise ValueError("eval_inputs entries must be unique")
        seen.add(value)
    return values


class PromptVariant(BaseModel):
    id: str
    task: str
    eval_inputs: list[str] | None = None

    _validate_eval_inputs = field_validator("eval_inputs")(
        validate_eval_input_paths
    )


class BaseEvalDefinition(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    skill: str
    skill_source: str | None = None
    language: str
    service: str
    prompts: list[PromptVariant]
    definition_path: Path | None = None
    fixture_dir: Path | None = None

    @property
    def kind(self) -> EvalRole:
        raise NotImplementedError

    @property
    def case_key(self) -> str:
        return f"{self.language}/{self.service}"

    @property
    def case_id(self) -> str:
        return self.case_key


class BaseEvalCase(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    base_id: str
    prompt_id: str
    skill: str
    skill_source: str | None = None
    language: str
    service: str
    task: str
    eval_inputs: list[str] | None = None
    definition_path: Path | None = None
    fixture_dir: Path | None = None

    _validate_eval_inputs = field_validator("eval_inputs")(
        validate_eval_input_paths
    )

    @property
    def kind(self) -> EvalRole:
        raise NotImplementedError

    @property
    def case_key(self) -> str:
        return f"{self.language}/{self.service}"

    @property
    def case_id(self) -> str:
        return self.case_key


def resolve_skill_source(
    repo_root: Path,
    skill: str,
    skill_source: str | None = None,
    selected_skill_dir: Path | None = None,
) -> Path:
    """Resolve a selected or definition-declared skill source inside the repo."""
    if selected_skill_dir is not None:
        return selected_skill_dir
    relative = Path(skill_source or f"skills/{skill}")
    if relative.is_absolute():
        raise ValueError("skill_source must be relative to the repository root")
    resolved_root = repo_root.resolve()
    resolved = (resolved_root / relative).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("skill_source must stay within the repository root") from exc
    return resolved


class GradeCheckResult(BaseModel):
    id: str
    description: str
    passed: bool
    evidence: str = ""
    category: CheckCategory = "sanity"
    skipped: bool = False


class GradeResult(BaseModel):
    checks: list[GradeCheckResult] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(1 for check in self.checks if not check.skipped)

    @property
    def passed(self) -> int:
        return sum(1 for check in self.checks if check.passed and not check.skipped)

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 1.0
        return self.passed / self.total


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["codex", "claude", "unknown"] = "unknown"
    source: Literal["cumulative", "incremental", "unknown"] = "unknown"
    observed: bool = False
    usage_record_count: int = Field(default=0, ge=0)
    selected_record_count: int = Field(default=0, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    cache_creation_input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reasoning_output_tokens: int | None = Field(default=None, ge=0)
    provider_total_tokens: int | None = Field(default=None, ge=0)
    derived_total_tokens: int | None = Field(default=None, ge=0)
    effective_total_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="before")
    @classmethod
    def populate_missing_effective_total(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "effective_total_tokens" in value:
            return value
        normalized = dict(value)
        effective_total = normalized.get("provider_total_tokens")
        if effective_total is None:
            effective_total = normalized.get("derived_total_tokens")
        normalized["effective_total_tokens"] = effective_total
        return normalized

    @property
    def recognized(self) -> bool:
        return self.effective_total_tokens is not None or any(
            value is not None
            for value in (
                self.input_tokens,
                self.cached_input_tokens,
                self.cache_creation_input_tokens,
                self.output_tokens,
                self.reasoning_output_tokens,
                self.provider_total_tokens,
                self.derived_total_tokens,
            )
        )

    @property
    def total_tokens(self) -> int | None:
        return self.effective_total_tokens


class SideResult(BaseModel):
    side: Literal["with_skill", "baseline"]
    exit_code: int
    trace_path: str
    final_message_path: str
    grade: GradeResult
    rubric_grade_path: str | None = None
    rubric_trace_path: str | None = None
    command_count: int = 0
    duration_seconds: float = 0.0
    agent_duration_seconds: float = 0.0
    rubric_duration_seconds: float = 0.0
    tokens: int = 0
    agent_tokens: int = 0
    rubric_tokens: int = 0
    agent_usage: TokenUsage | None = None
    rubric_usage: TokenUsage | None = None
    errors: list[str] = Field(default_factory=list)


class CaseResult(BaseModel):
    id: str
    base_id: str
    prompt_id: str
    skill: str
    language: str
    service: str
    with_skill: SideResult | None = None
    baseline: SideResult | None = None


class ValidationResult(BaseModel):
    id: str
    base_id: str
    prompt_id: str
    skill: str
    language: str
    service: str
    definition_path: str
    fixture_dir: str
    skill_path: str
    config_path: str = ""
    eval_kind: EvalRole
    selected_eval_inputs: list[str] | None = None
    sanity_check_count: int = 0
    rubric_check_count: int = 0
    runtime_check_count: int = 0
    source_files: dict[str, str] = Field(default_factory=dict)

    _validate_selected_eval_inputs = field_validator("selected_eval_inputs")(
        validate_eval_input_paths
    )
