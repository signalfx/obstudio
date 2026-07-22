from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .definitions import (
    EvalCase,
    EvalDefinition,
    PromptVariant,
    RubricEvalCase,
    RubricEvalDefinition,
    RuntimeEvalCase,
    RuntimeEvalDefinition,
    SanityEvalCase,
    SanityEvalDefinition,
)
from .eval_files import eval_file_layout
from .schema_resources import schema_validator


CASE_PROVENANCE_FIELDS = {
    "definition_path",
    "fixture_dir",
    "definition_sha256",
    "collected_contract_sha256",
}


def load_eval_definition(
    path: Path,
    *,
    definition_bytes: bytes | None = None,
) -> EvalDefinition:
    """Load one eval definition and bind it to the exact bytes read."""

    layout = eval_file_layout(path)
    if layout is None or layout.role is None:
        raise ValueError(
            "eval files must live under eval/sanity, eval/qual, or "
            f"eval/runtime: {path}"
        )
    source_bytes = (
        definition_bytes
        if definition_bytes is not None
        else path.read_bytes()
    )
    data = json.loads(source_bytes)
    if not isinstance(data, dict):
        raise ValueError(f"eval definition must be an object: {path}")
    normalized = with_path_defaults(path, data)
    schema_validator(schema_name_for_role(layout.role)).validate(normalized)
    definition = definition_model_for_role(layout.role).model_validate(
        normalized
    )
    definition.definition_path = path
    definition.fixture_dir = layout.fixture_dir
    definition.definition_sha256 = hashlib.sha256(source_bytes).hexdigest()
    return definition


def case_from_definition(
    definition: EvalDefinition,
    prompt: PromptVariant,
    path: Path,
) -> EvalCase:
    common = {
        "id": f"{definition.id}/{prompt.id}",
        "base_id": definition.id,
        "prompt_id": prompt.id,
        "skill": definition.skill,
        "language": definition.language,
        "service": definition.service,
        "task": prompt.task,
        "definition_path": path,
        "fixture_dir": definition.fixture_dir or eval_fixture_dir(path),
        "definition_sha256": definition.definition_sha256,
    }
    case: EvalCase
    if isinstance(definition, SanityEvalDefinition):
        case = SanityEvalCase(**common, checks=definition.checks)
    elif isinstance(definition, RubricEvalDefinition):
        case = RubricEvalCase(
            **common,
            rubric=definition.rubric,
            judge_prompt=definition.judge_prompt,
            judge_inputs=definition.judge_inputs,
        )
    elif isinstance(definition, RuntimeEvalDefinition):
        case = RuntimeEvalCase(**common, checks=definition.checks)
    else:
        raise TypeError(
            f"unsupported eval definition: {type(definition).__name__}"
        )
    case.collected_contract_sha256 = case_contract_sha256(case)
    return case


def with_path_defaults(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    layout = eval_file_layout(path)
    if layout is None:
        return dict(data)
    normalized = dict(data)
    normalized.setdefault("language", layout.language)
    normalized.setdefault("service", layout.service)
    normalized.setdefault("id", layout.default_id)
    return normalized


def eval_fixture_dir(path: Path) -> Path:
    layout = eval_file_layout(path)
    return path.parent if layout is None else layout.fixture_dir


def schema_name_for_role(role: str) -> str:
    if role == "sanity":
        return "sanity.schema.json"
    if role == "rubric":
        return "rubric.schema.json"
    if role == "runtime":
        return "runtime.schema.json"
    raise ValueError(f"unknown eval role: {role}")


def definition_model_for_role(role: str):
    if role == "sanity":
        return SanityEvalDefinition
    if role == "rubric":
        return RubricEvalDefinition
    if role == "runtime":
        return RuntimeEvalDefinition
    raise ValueError(f"unknown eval role: {role}")


def case_contract_payload(case: EvalCase) -> dict[str, object]:
    return case.model_dump(
        mode="json",
        exclude=CASE_PROVENANCE_FIELDS,
    )


def case_contract_sha256(case: EvalCase) -> str:
    return canonical_sha256(case_contract_payload(case))


def case_task_sha256(case: EvalCase) -> str:
    return hashlib.sha256(case.task.encode("utf-8")).hexdigest()


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
