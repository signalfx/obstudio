from __future__ import annotations

from pathlib import Path

from pytest_codex_evals.definitions import GradeCheckResult
from pytest_codex_evals.trace import TraceSummary


def guard_checks(run_dir: Path, final_message: str, trace: TraceSummary, side: str, skill: str) -> list[GradeCheckResult]:
    checks = [
        GradeCheckResult(
            id="final-message-present",
            description="Run produced a non-empty final response.",
            passed=bool(final_message.strip()),
            evidence="Final message present" if final_message.strip() else "Final message was empty",
            category="sanity",
        )
    ]
    if side == "with_skill":
        checks.append(check_repo_skills_loaded(run_dir, skill))
    elif side == "baseline":
        checks.append(check_repo_skills_absent(run_dir))
        contaminated = trace_contains_skill_reference(trace, skill)
        checks.append(
            GradeCheckResult(
                id="baseline-skill-isolation",
                description="Baseline trace does not show repo skill visibility or invocation.",
                passed=not contaminated,
                evidence="No repo skill references found" if not contaminated else "Skill reference found in trace",
                category="sanity",
            )
        )
    return checks


def check_repo_skills_loaded(run_dir: Path, target_skill: str) -> GradeCheckResult:
    skills_dir = run_dir / ".agents" / "skills"
    loaded = loaded_skill_names(skills_dir)
    target_path = skills_dir / target_skill / "SKILL.md"
    target_text = target_path.read_text(encoding="utf-8", errors="replace") if target_path.exists() else ""
    target_declared = f"name: {target_skill}" in target_text
    evidence_parts = []
    if not target_path.exists():
        evidence_parts.append(f"Missing target skill: {target_skill}")
    if not target_declared:
        evidence_parts.append(f"{target_skill} SKILL.md does not declare name: {target_skill}")
    if not evidence_parts:
        evidence_parts.append(f"Loaded skills: {', '.join(loaded)}")
    return GradeCheckResult(
        id="skills-loaded",
        description="Loaded side exposes repo skill entries through .agents/skills.",
        passed=target_path.exists() and target_declared,
        evidence="; ".join(evidence_parts),
        category="sanity",
    )


def check_repo_skills_absent(run_dir: Path) -> GradeCheckResult:
    skills_dir = run_dir / ".agents" / "skills"
    present = loaded_skill_names(skills_dir)
    return GradeCheckResult(
        id="skills-not-loaded",
        description="Baseline side does not expose repo skill entries.",
        passed=not present,
        evidence="No repo skill files present" if not present else "Present: " + ", ".join(present),
        category="sanity",
    )


def loaded_skill_names(skills_dir: Path) -> list[str]:
    if not skills_dir.exists():
        return []
    return sorted(path.parent.name for path in skills_dir.glob("*/SKILL.md"))


def trace_contains_skill_reference(trace: TraceSummary, skill: str) -> bool:
    text = trace.raw_text.lower()
    skill = skill.lower()
    markers = (
        f"${skill}",
        f".agents/skills/{skill}",
        f"skills/{skill}",
    )
    return any(marker in text for marker in markers)


def missing_values(text: str, values: list[str]) -> list[str]:
    return [value for value in values if not contains(text, value)]


def contains(text: str, value: str) -> bool:
    return value.lower() in text.lower()
