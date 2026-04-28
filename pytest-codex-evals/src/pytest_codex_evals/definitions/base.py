from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


EvalRole = Literal["sanity", "rubric", "runtime"]
CheckCategory = Literal["sanity", "runtime"]


class PromptVariant(BaseModel):
    id: str
    task: str


class BaseEvalDefinition(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    skill: str
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
    language: str
    service: str
    task: str
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
    eval_kind: EvalRole
    sanity_check_count: int = 0
    rubric_check_count: int = 0
    runtime_check_count: int = 0
