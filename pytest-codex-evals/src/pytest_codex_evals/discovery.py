from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from .models import EvalCase, EvalDefinition
from .schema_resources import load_schema


def discover_cases(
    repo_root: Path,
    skill: str | None = None,
    case_id: str | None = None,
    prompt_id: str | None = None,
) -> list[EvalCase]:
    eval_root = repo_root / "evals" if (repo_root / "evals").is_dir() else repo_root
    schema = load_schema("eval.schema.json")
    validator = Draft202012Validator(schema)
    cases: list[EvalCase] = []
    for path in sorted(eval_root.rglob("*_eval.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        kind = path.name.removesuffix("_eval.json")
        data.setdefault("language", path.parent.parent.name)
        data.setdefault("service", path.parent.name)
        data.setdefault("id", f"{data['language']}/{data['service']}/{kind}")
        validator.validate(data)
        definition = EvalDefinition.model_validate(data)
        if skill and definition.skill != skill:
            continue
        if case_id and definition.case_key != case_id:
            continue
        for prompt in definition.prompts:
            if prompt_id and prompt.id != prompt_id:
                continue
            cases.append(
                EvalCase(
                    id=f"{definition.id}/{prompt.id}",
                    base_id=definition.id,
                    prompt_id=prompt.id,
                    skill=definition.skill,
                    language=definition.language,
                    service=definition.service,
                    task=prompt.task,
                    deterministic_checks=definition.deterministic_checks,
                    qualitative_checks=definition.qualitative_checks,
                    definition_path=path,
                    fixture_dir=path.parent,
                )
            )
    return cases
