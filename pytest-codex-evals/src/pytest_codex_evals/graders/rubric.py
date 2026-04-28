from __future__ import annotations

import json
import subprocess
from pathlib import Path

from jsonschema import Draft202012Validator

from pytest_codex_evals.definitions import RubricEvalCase
from pytest_codex_evals.schema_resources import schema_path as packaged_schema_path


def run_rubric_grade(
    *,
    case: RubricEvalCase,
    side_dir: Path,
    schema_path: Path | None = None,
    model: str | None,
) -> Path:
    if schema_path is None:
        with packaged_schema_path("rubric_grade.schema.json") as path:
            return _run_rubric_grade(case=case, side_dir=side_dir, schema_path=path, model=model)
    return _run_rubric_grade(case=case, side_dir=side_dir, schema_path=schema_path, model=model)


def _run_rubric_grade(
    *,
    case: RubricEvalCase,
    side_dir: Path,
    schema_path: Path,
    model: str | None,
) -> Path:
    output_path = side_dir / "rubric_grade.json"
    trace_path = side_dir / "rubric_trace.jsonl"
    cmd = [
        "codex",
        "exec",
        "--json",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--cd",
        str(side_dir),
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(output_path),
    ]
    if model:
        cmd.extend(["--model", model])
    cmd.append(rubric_prompt(case))
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    trace_path.write_text(completed.stdout, encoding="utf-8")
    (side_dir / "rubric_stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0 and not output_path.exists():
        output_path.write_text(
            json.dumps(
                {
                    "overall_pass": False,
                    "score": 0,
                    "checks": [
                        {
                            "id": "rubric-run",
                            "pass": False,
                            "notes": f"Codex rubric grader exited with {completed.returncode}",
                            "evidence": completed.stderr[-1000:],
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
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
