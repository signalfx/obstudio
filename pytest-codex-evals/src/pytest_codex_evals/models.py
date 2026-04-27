from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


CheckKind = Literal[
    "final_contains_all",
    "final_contains_any",
    "file_exists",
    "file_exists_any",
    "no_file_exists",
    "file_contains_all",
    "file_contains_any",
    "trace_command_contains",
]


class DeterministicCheck(BaseModel):
    id: str
    description: str
    kind: CheckKind
    path: str | None = None
    paths: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    applies_to: Literal["both", "with_skill", "baseline"] = "with_skill"


class PromptVariant(BaseModel):
    id: str
    task: str


class EvalDefinition(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    skill: str
    language: str
    service: str
    prompts: list[PromptVariant]
    deterministic_checks: list[DeterministicCheck] = Field(default_factory=list)
    qualitative_checks: list[str] = Field(default_factory=list)
    definition_path: Path | None = None
    fixture_dir: Path | None = None

    @property
    def case_key(self) -> str:
        return f"{self.language}/{self.service}"

    @property
    def case_id(self) -> str:
        return self.case_key


class EvalCase(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    base_id: str
    prompt_id: str
    skill: str
    language: str
    service: str
    task: str
    deterministic_checks: list[DeterministicCheck] = Field(default_factory=list)
    qualitative_checks: list[str] = Field(default_factory=list)
    definition_path: Path | None = None
    fixture_dir: Path | None = None

    @property
    def case_key(self) -> str:
        return f"{self.language}/{self.service}"

    @property
    def case_id(self) -> str:
        return self.case_key


class CommandEvent(BaseModel):
    command: str
    status: str = ""


class TraceUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class GradeCheckResult(BaseModel):
    id: str
    description: str
    passed: bool
    evidence: str = ""


class GradeResult(BaseModel):
    checks: list[GradeCheckResult] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def passed(self) -> int:
        return sum(1 for check in self.checks if check.passed)

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
    deterministic_grade: GradeResult
    qualitative_grade_path: str | None = None
    command_count: int = 0
    tokens: int = 0
    errors: list[str] = Field(default_factory=list)


class CaseResult(BaseModel):
    id: str
    base_id: str
    prompt_id: str
    skill: str
    language: str
    service: str
    with_skill: SideResult
    baseline: SideResult


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
    deterministic_check_count: int = 0
    qualitative_check_count: int = 0
