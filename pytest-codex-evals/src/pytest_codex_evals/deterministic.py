from __future__ import annotations

import subprocess
from pathlib import Path

from .models import DeterministicCheck, GradeCheckResult, GradeResult, EvalCase
from .runtime import run_observer_docker_runtime
from .trace import TraceSummary


def grade_deterministic(
    case: EvalCase,
    run_dir: Path,
    final_message: str,
    trace: TraceSummary,
    side: str,
    runtime_enabled: bool = False,
) -> GradeResult:
    service_dir = run_dir / "service"
    results: list[GradeCheckResult] = []

    results.append(
        GradeCheckResult(
            id="final-message-present",
            description="Run produced a non-empty final response.",
            passed=bool(final_message.strip()),
            evidence="Final message present" if final_message.strip() else "Final message was empty",
        )
    )

    if side == "with_skill":
        results.append(check_repo_skills_loaded(run_dir, case.skill))
    elif side == "baseline":
        results.append(check_repo_skills_absent(run_dir))
        contaminated = trace_contains_skill_reference(trace, case.skill)
        results.append(
            GradeCheckResult(
                id="baseline-skill-isolation",
                description="Baseline trace does not show repo skill visibility or invocation.",
                passed=not contaminated,
                evidence="No repo skill references found" if not contaminated else "Skill reference found in trace",
            )
        )

    for check in case.deterministic_checks:
        if check.applies_to not in ("both", side):
            continue
        results.append(run_check(check, service_dir, final_message, trace, runtime_enabled))

    return GradeResult(checks=results)


def check_repo_skills_loaded(run_dir: Path, target_skill: str) -> GradeCheckResult:
    skills_dir = run_dir / ".agents" / "skills"
    loaded = loaded_skill_names(skills_dir)
    target_text = ""
    target_path = skill_file(skills_dir, target_skill)
    if target_path.exists():
        target_text = target_path.read_text(encoding="utf-8", errors="replace")
    target_declared = f"name: {target_skill}" in target_text
    passed = target_path.exists() and target_declared
    evidence_parts = []
    if not target_path.exists():
        evidence_parts.append(f"Missing target skill: {target_skill}")
    if not target_declared:
        evidence_parts.append(f"{target_skill} SKILL.md does not declare name: {target_skill}")
    if not evidence_parts:
        evidence_parts.append(f"Loaded skills: {', '.join(loaded)}")
    return GradeCheckResult(
        id="skills-loaded",
        description="A/B loaded side exposes repo skill entries through .agents/skills.",
        passed=passed,
        evidence="; ".join(evidence_parts),
    )


def check_repo_skills_absent(run_dir: Path) -> GradeCheckResult:
    skills_dir = run_dir / ".agents" / "skills"
    present = loaded_skill_names(skills_dir)
    return GradeCheckResult(
        id="skills-not-loaded",
        description="A/B not-loaded side does not expose repo skill entries.",
        passed=not present,
        evidence="No repo skill files present" if not present else "Present: " + ", ".join(present),
    )


def skill_file(skills_dir: Path, skill: str) -> Path:
    return skills_dir / skill / "SKILL.md"


def loaded_skill_names(skills_dir: Path) -> list[str]:
    if not skills_dir.exists():
        return []
    return sorted(path.parent.name for path in skills_dir.glob("*/SKILL.md"))


def run_check(
    check: DeterministicCheck,
    service_dir: Path,
    final_message: str,
    trace: TraceSummary,
    runtime_enabled: bool = False,
) -> GradeCheckResult:
    kind = check.kind
    evidence = ""

    if kind == "final_contains_all":
        missing = missing_values(final_message, check.values)
        return result(check, not missing, "Missing: " + ", ".join(missing) if missing else "All values present")

    if kind == "final_contains_any":
        passed = any(contains(final_message, value) for value in check.values)
        return result(check, passed, "At least one value present" if passed else "None present: " + ", ".join(check.values))

    if kind == "file_exists":
        path = service_dir / required_path(check)
        return result(check, path.exists(), str(path))

    if kind == "file_exists_any":
        paths = [service_dir / p for p in check.paths]
        existing = [str(p) for p in paths if p.exists()]
        return result(check, bool(existing), "Existing: " + ", ".join(existing) if existing else "No candidate files found")

    if kind == "no_file_exists":
        path = service_dir / required_path(check)
        return result(check, not path.exists(), str(path))

    if kind in ("file_contains_all", "file_contains_any"):
        path = service_dir / required_path(check)
        if not path.exists():
            return result(check, False, f"File missing: {path}")
        text = path.read_text(encoding="utf-8", errors="replace")
        if kind == "file_contains_all":
            missing = missing_values(text, check.values)
            evidence = "Missing: " + ", ".join(missing) if missing else f"All values present in {path}"
            return result(check, not missing, evidence)
        passed = any(contains(text, value) for value in check.values)
        evidence = f"At least one value present in {path}" if passed else "None present: " + ", ".join(check.values)
        return result(check, passed, evidence)

    if kind == "trace_command_contains":
        haystack = "\n".join(command.command for command in trace.commands)
        missing = missing_values(haystack, check.values)
        return result(check, not missing, "Missing commands: " + ", ".join(missing) if missing else "Command evidence found")

    if kind in {
        "command_succeeds",
        "command_stdout_contains_all",
        "command_stdout_contains_any",
        "command_stdout_contains_none",
    }:
        return run_command_check(check, service_dir)

    if kind == "observer_docker_runtime":
        if not runtime_enabled:
            return result(
                check,
                True,
                "Runtime check skipped; enable [runtime].enabled = true or pass --codex-runtime.",
                category="runtime",
                skipped=True,
            )
        return run_observer_docker_runtime(check, service_dir)

    return result(check, False, f"Unknown check kind: {kind}")


def run_command_check(check: DeterministicCheck, service_dir: Path) -> GradeCheckResult:
    if not check.command:
        return result(check, False, "Command check requires command")
    cwd = service_dir / check.cwd if check.cwd else service_dir
    if not cwd.exists():
        return result(check, False, f"Command cwd missing: {cwd}")
    try:
        completed = subprocess.run(
            check.command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=check.timeout_seconds,
        )
    except FileNotFoundError as exc:
        return result(check, False, f"Command executable not found: {exc.filename}")
    except subprocess.TimeoutExpired as exc:
        return result(check, False, f"Command timed out after {exc.timeout}s: {command_label(check.command)}")

    stdout = completed.stdout or ""
    combined_output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    evidence = command_evidence(check.command, completed.returncode, combined_output)
    if check.kind == "command_succeeds":
        return result(check, completed.returncode == 0, evidence)

    if completed.returncode != 0:
        return result(check, False, evidence)

    if check.kind == "command_stdout_contains_all":
        missing = missing_values(stdout, check.values)
        return result(check, not missing, evidence if not missing else evidence + "; missing: " + ", ".join(missing))

    if check.kind == "command_stdout_contains_any":
        passed = any(contains(stdout, value) for value in check.values)
        return result(check, passed, evidence if passed else evidence + "; none present: " + ", ".join(check.values))

    if check.kind == "command_stdout_contains_none":
        present = [value for value in check.values if contains(stdout, value)]
        return result(check, not present, evidence if not present else evidence + "; unexpected: " + ", ".join(present))

    return result(check, False, f"Unsupported command check kind: {check.kind}")


def command_label(command: list[str]) -> str:
    return " ".join(command)


def command_evidence(command: list[str], returncode: int, output: str) -> str:
    snippet = " ".join(output.split())[:500]
    if snippet:
        return f"{command_label(command)} exited {returncode}: {snippet}"
    return f"{command_label(command)} exited {returncode}"


def trace_contains_skill_reference(trace: TraceSummary, skill: str) -> bool:
    text = trace.raw_text.lower()
    skill = skill.lower()
    markers = (
        f"${skill}",
        f".agents/skills/{skill}",
        f"skills/{skill}",
    )
    return any(marker in text for marker in markers)


def result(
    check: DeterministicCheck,
    passed: bool,
    evidence: str,
    category: str = "deterministic",
    skipped: bool = False,
) -> GradeCheckResult:
    return GradeCheckResult(
        id=check.id,
        description=check.description,
        passed=passed,
        evidence=evidence,
        category=category,  # type: ignore[arg-type]
        skipped=skipped,
    )


def missing_values(text: str, values: list[str]) -> list[str]:
    return [value for value in values if not contains(text, value)]


def contains(text: str, value: str) -> bool:
    return value.lower() in text.lower()


def required_path(check: DeterministicCheck) -> str:
    if not check.path:
        raise ValueError(f"check {check.id} requires path")
    return check.path
