from __future__ import annotations

from pathlib import Path

from pytest_codex_evals.definitions import BaseEvalCase, GradeResult, RubricEvalCase, RuntimeEvalCase, SanityEvalCase
from pytest_codex_evals.trace import TraceSummary

from .runtime import grade_runtime
from .sanity import grade_sanity
from .shared import guard_checks


def grade_side(
    *,
    case: BaseEvalCase,
    run_dir: Path,
    final_message: str,
    trace: TraceSummary,
    side: str,
    runtime_enabled: bool = False,
    repo_root: Path | None = None,
) -> GradeResult:
    if isinstance(case, SanityEvalCase):
        return grade_sanity(case, run_dir, final_message, trace, side)
    if isinstance(case, RuntimeEvalCase):
        return grade_runtime(case, run_dir, final_message, trace, side, runtime_enabled=runtime_enabled, repo_root=repo_root)
    if isinstance(case, RubricEvalCase):
        return GradeResult(checks=guard_checks(run_dir, final_message, trace, side, case.skill))
    return GradeResult(checks=guard_checks(run_dir, final_message, trace, side, case.skill))
