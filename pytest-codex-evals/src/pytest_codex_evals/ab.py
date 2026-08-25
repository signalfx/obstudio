from __future__ import annotations

from .definitions import EvalCase


def side_prompt(case: EvalCase, side: str) -> str:
    if side == "with_skill":
        return (
            f"Use the ${case.skill} skill. Before doing or saying anything else, run "
            f"exactly this one read-only command and wait for it to complete: cat "
            f".agents/skills/{case.skill}/SKILL.md. Do not combine that read with pwd "
            f"or any other command, and do not emit commentary before or during the "
            f"read. Then follow the skill. {case.task}"
        )
    if side == "baseline":
        return case.task
    raise ValueError(f"unknown eval side: {side}")
