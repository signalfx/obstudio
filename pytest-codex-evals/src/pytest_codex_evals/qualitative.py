from __future__ import annotations

import json
import subprocess
from pathlib import Path

from jsonschema import Draft202012Validator

from .models import EvalCase
from .schema_resources import schema_path as packaged_schema_path


def run_qualitative_grade(
    *,
    case: EvalCase,
    side_dir: Path,
    schema_path: Path | None = None,
    model: str | None,
) -> Path:
    if schema_path is None:
        with packaged_schema_path("qualitative_grade.schema.json") as path:
            return _run_qualitative_grade(case=case, side_dir=side_dir, schema_path=path, model=model)
    return _run_qualitative_grade(case=case, side_dir=side_dir, schema_path=schema_path, model=model)


def _run_qualitative_grade(
    *,
    case: EvalCase,
    side_dir: Path,
    schema_path: Path,
    model: str | None,
) -> Path:
    output_path = side_dir / "qualitative_grade.json"
    trace_path = side_dir / "qualitative_trace.jsonl"
    prompt = qualitative_prompt(case)
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
    cmd.append(prompt)
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    trace_path.write_text(completed.stdout, encoding="utf-8")
    (side_dir / "qualitative_stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0 and not output_path.exists():
        output_path.write_text(
            json.dumps(
                {
                    "overall_pass": False,
                    "score": 0,
                    "checks": [
                        {
                            "id": "qualitative-run",
                            "pass": False,
                            "notes": f"Codex qualitative grader exited with {completed.returncode}",
                            "evidence": completed.stderr[-1000:],
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    validate_qualitative_output(output_path, schema_path)
    return output_path


def qualitative_prompt(case: EvalCase) -> str:
    checks = "\n".join(f"- {item}" for item in case.qualitative_checks)
    return f"""Evaluate the completed eval run in this directory.

Case: {case.base_id}
Prompt variant: {case.prompt_id}
Task: {case.task}

Read:
- ./service for the resulting service files
- ./last_message.md for the agent's final response
- ./deterministic_grade.json for deterministic checks

Return only JSON matching the provided schema. Grade against these qualitative checks:
{checks}

Use check ids derived from the qualitative check order, such as qualitative-1, qualitative-2, etc.
"""


def validate_qualitative_output(output_path: Path, schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    data = json.loads(output_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(data)
