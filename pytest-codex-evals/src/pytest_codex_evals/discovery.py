from __future__ import annotations

from pathlib import Path

from .definitions import EvalCase
from .eval_files import iter_eval_files
from .plugin import case_from_definition, load_eval_definition


def discover_cases(
    repo_root: Path,
    skill: str | None = None,
    case_id: str | None = None,
    prompt_id: str | None = None,
) -> list[EvalCase]:
    eval_root = repo_root / "evals" if (repo_root / "evals").is_dir() else repo_root
    cases: list[EvalCase] = []
    for path in iter_eval_files(eval_root):
        definition = load_eval_definition(path)
        if skill and definition.skill != skill:
            continue
        if case_id and definition.case_key != case_id:
            continue
        for prompt in definition.prompts:
            if prompt_id and prompt.id != prompt_id:
                continue
            cases.append(case_from_definition(definition, prompt, path))
    return cases
