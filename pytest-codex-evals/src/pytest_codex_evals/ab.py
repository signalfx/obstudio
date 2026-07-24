from __future__ import annotations

from .definitions import EvalCase


SKILL_COMPANIONS: dict[str, tuple[str, ...]] = {
    "otel-instrument": ("otel-verify",),
    "splunk-configure": ("splunk-dashboard",),
}

INSTRUCTION_COMPANIONS = {"otel-instrument"}


def side_prompt(case: EvalCase, side: str) -> str:
    if side == "with_skill":
        prompt = (
            f"Use the ${case.skill} skill. Before taking task actions, read its "
            "complete instructions from the authenticated staged path "
            f".agents/skills/{case.skill}/SKILL.md. Do not search CODEX_HOME, "
            "home directories, or alternate skill installations. "
            f"{case.task}"
        )
        companions = SKILL_COMPANIONS.get(case.skill, ())
        if companions:
            companion_paths = ", ".join(
                f".agents/skills/{name}/SKILL.md" for name in companions
            )
            if case.skill in INSTRUCTION_COMPANIONS:
                prompt += (
                    " When delegating to a companion skill, load it exactly once "
                    f"from the authenticated staged path {companion_paths}; do not "
                    "search CODEX_HOME, home directories, or alternate skill "
                    "installations."
                )
            else:
                prompt += (
                    " Use companion scripts only from the authenticated staged "
                    f"tree containing {companion_paths}; do not search CODEX_HOME, "
                    "home directories, or alternate skill installations."
                )
        return prompt
    if side == "baseline":
        return case.task
    raise ValueError(f"unknown eval side: {side}")
