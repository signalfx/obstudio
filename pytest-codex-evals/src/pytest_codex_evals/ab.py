from __future__ import annotations

from .models import EvalCase


def side_prompt(case: EvalCase, side: str) -> str:
    if side == "with_skill":
        return f"Use the ${case.skill} skill. {case.task}"
    if side == "baseline":
        return case.task
    raise ValueError(f"unknown eval side: {side}")
