from __future__ import annotations

from .definitions import EvalCase


def is_bare_skill_task(task: object, skill: str) -> bool:
    return isinstance(task, str) and task in {f"${skill}", f"${skill} ./service"}


def side_prompt(case: EvalCase, side: str, *, native_skill_invocation: bool = False,
                comparison: bool = False) -> str:
    if comparison and side in {"with_skill", "baseline"}:
        return case.task
    if side == "with_skill":
        if native_skill_invocation and is_bare_skill_task(case.task, case.skill):
            return case.task
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
