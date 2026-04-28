from __future__ import annotations

import subprocess
from pathlib import Path

from pytest_codex_evals.definitions import GradeCheckResult, GradeResult, SanityCheck, SanityEvalCase
from pytest_codex_evals.trace import TraceSummary

from .shared import contains, guard_checks, missing_values


def grade_sanity(case: SanityEvalCase, run_dir: Path, final_message: str, trace: TraceSummary, side: str) -> GradeResult:
    service_dir = run_dir / "service"
    results = guard_checks(run_dir, final_message, trace, side, case.skill)
    for check in case.checks:
        if check.applies_to not in ("both", side):
            continue
        results.append(run_check(check, service_dir, final_message))
    return GradeResult(checks=results)


def run_check(check: SanityCheck, service_dir: Path, final_message: str) -> GradeCheckResult:
    kind = check.kind
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
            return result(check, not missing, "Missing: " + ", ".join(missing) if missing else f"All values present in {path}")
        passed = any(contains(text, value) for value in check.values)
        return result(check, passed, f"At least one value present in {path}" if passed else "None present: " + ", ".join(check.values))

    if kind in {
        "command_succeeds",
        "command_stdout_contains_all",
        "command_stdout_contains_any",
        "command_stdout_contains_none",
    }:
        return run_command_check(check, service_dir)

    return result(check, False, f"Unknown sanity check kind: {kind}")


def run_command_check(check: SanityCheck, service_dir: Path) -> GradeCheckResult:
    if not check.command:
        return result(check, False, "Command check requires command")
    cwd = service_dir / check.cwd if check.cwd else service_dir
    if not cwd.exists():
        return result(check, False, f"Command cwd missing: {cwd}")
    try:
        completed = subprocess.run(check.command, cwd=cwd, capture_output=True, text=True, timeout=check.timeout_seconds)
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


def result(check: SanityCheck, passed: bool, evidence: str, skipped: bool = False) -> GradeCheckResult:
    return GradeCheckResult(
        id=check.id,
        description=check.description,
        passed=passed,
        evidence=evidence,
        category="sanity",
        skipped=skipped,
    )


def command_label(command: list[str]) -> str:
    return " ".join(command)


def command_evidence(command: list[str], returncode: int, output: str) -> str:
    snippet = " ".join(output.split())[:500]
    if snippet:
        return f"{command_label(command)} exited {returncode}: {snippet}"
    return f"{command_label(command)} exited {returncode}"


def required_path(check: SanityCheck) -> str:
    if not check.path:
        raise ValueError(f"check {check.id} requires path")
    return check.path
