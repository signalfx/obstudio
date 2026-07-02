from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from pytest_codex_evals.backends import AgentBackend, CodexBackend
from pytest_codex_evals.definitions import RubricEvalCase
from pytest_codex_evals.schema_resources import schema_path as packaged_schema_path


def run_rubric_grade(
    *,
    case: RubricEvalCase,
    side_dir: Path,
    schema_path: Path | None = None,
    model: str | None,
    backend: AgentBackend | None = None,
    timeout: int = 900,
) -> Path:
    if backend is None:
        backend = CodexBackend()
    if schema_path is None:
        with packaged_schema_path("rubric_grade.schema.json") as path:
            return _run_rubric_grade(case=case, side_dir=side_dir, schema_path=path, model=model, backend=backend, timeout=timeout)
    return _run_rubric_grade(case=case, side_dir=side_dir, schema_path=schema_path, model=model, backend=backend, timeout=timeout)


def _run_rubric_grade(
    *,
    case: RubricEvalCase,
    side_dir: Path,
    schema_path: Path,
    model: str | None,
    backend: AgentBackend,
    timeout: int,
) -> Path:
    result = backend.run_judge(
        prompt=rubric_prompt(case),
        exec_dir=side_dir,
        model=model,
        schema_path=schema_path,
        timeout=timeout,
    )
    output_path = result.final_message_path
    validate_rubric_output(output_path, schema_path)
    return output_path


def rubric_prompt(case: RubricEvalCase) -> str:
    if case.judge_prompt:
        return case.judge_prompt.format(
            case_id=case.base_id,
            prompt_id=case.prompt_id,
            task=case.task,
            rubric=rubric_text(case),
            inputs=judge_inputs_text(case),
        )
    inputs = judge_inputs_text(case)
    input_section = f"\nSuggested inputs:\n{inputs}\n" if inputs else ""
    return f"""Evaluate the completed eval run in this directory.

Case: {case.base_id}
Prompt variant: {case.prompt_id}
Task: {case.task}
{input_section}
Return only JSON matching the provided schema. Grade against this rubric:
{rubric_text(case)}

Set `score` to a 0-100 percentage-style quality score. Do not put the number
of passed checks in `score`.
Use check ids derived from the rubric order, such as rubric-1, rubric-2, etc.
"""


def rubric_text(case: RubricEvalCase) -> str:
    return "\n".join(f"- {item}" for item in case.rubric)


def judge_inputs_text(case: RubricEvalCase) -> str:
    return "\n".join(f"- {item}" for item in case.judge_inputs)


def validate_rubric_output(output_path: Path, schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    data = json.loads(output_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(data)
