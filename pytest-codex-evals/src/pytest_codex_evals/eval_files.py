from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


EVAL_ROLE_DIRS = {
    "qual": "rubric",
    "rubric": "rubric",
    "runtime": "runtime",
    "sanity": "sanity",
}


@dataclass(frozen=True)
class EvalFileLayout:
    path: Path
    fixture_dir: Path
    language: str
    service: str
    eval_name: str
    role: str | None
    default_id: str


def is_eval_file(path: Path) -> bool:
    return eval_file_layout(path) is not None


def iter_eval_files(eval_root: Path) -> list[Path]:
    return sorted(path for path in eval_root.rglob("*.json") if is_eval_file(path))


def eval_file_layout(path: Path) -> EvalFileLayout | None:
    if path.suffix != ".json":
        return None
    if path.parent.parent.name == "eval" and path.parent.name in EVAL_ROLE_DIRS:
        return nested_eval_file_layout(path)
    return None


def nested_eval_file_layout(path: Path) -> EvalFileLayout:
    fixture_dir = path.parents[2]
    language = fixture_dir.parent.name
    service = fixture_dir.name
    role_dir = path.parent.name
    eval_name = path.stem
    return EvalFileLayout(
        path=path,
        fixture_dir=fixture_dir,
        language=language,
        service=service,
        eval_name=eval_name,
        role=EVAL_ROLE_DIRS[role_dir],
        default_id=f"{language}/{service}/{role_dir}/{eval_name}",
    )
