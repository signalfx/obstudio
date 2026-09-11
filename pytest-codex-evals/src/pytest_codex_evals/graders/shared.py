from __future__ import annotations

import re
import shlex
from pathlib import Path

from pytest_codex_evals.definitions import GradeCheckResult
from pytest_codex_evals.trace import ActionEvent, TraceSummary


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
        checks.append(check_skill_instructions_read(run_dir, trace, skill))
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


def check_skill_instructions_read(
    run_dir: Path,
    trace: TraceSummary,
    target_skill: str,
) -> GradeCheckResult:
    target_path = (run_dir / ".agents" / "skills" / target_skill / "SKILL.md").resolve()
    inspected = reads_complete_skill_before_other_actions(trace.actions, run_dir, target_path)
    return GradeCheckResult(
        id="skill-instructions-read",
        description="Loaded side completely reads the target SKILL.md before any other task action.",
        passed=inspected,
        evidence=(
            f"Initial actions completely read {target_skill}/SKILL.md"
            if inspected
            else f"Did not successfully read all of {target_skill}/SKILL.md before another action"
        ),
        category="sanity",
    )


def reads_complete_skill_before_other_actions(
    actions: list[ActionEvent],
    run_dir: Path,
    target_path: Path,
) -> bool:
    try:
        target_lines = target_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    except OSError:
        return False
    if not target_lines:
        return False

    covered_through = 0
    for index, action in enumerate(actions):
        segment = skill_read_segment(action, run_dir, target_path, target_lines)
        if segment is None:
            return False
        if index + 1 < len(actions) and not completes_before_action(action, actions[index + 1]):
            return False
        start_line, end_line = segment
        if start_line > covered_through + 1:
            return False
        covered_through = max(covered_through, end_line)
        if covered_through >= len(target_lines):
            return True
    return False


def skill_read_segment(
    action: ActionEvent,
    run_dir: Path,
    target_path: Path,
    target_lines: list[str],
) -> tuple[int, int] | None:
    if action.status.lower() != "completed" or action.exit_code not in {None, 0}:
        return None
    if action.name.lower() in {"read", "read_file"}:
        return native_read_segment(action, run_dir, target_path, target_lines)
    if action.kind != "command":
        return None
    command = action.input.get("command")
    if not isinstance(command, str):
        return None
    tokens = simple_command_tokens(command)
    if tokens is None or not tokens:
        return None
    reader = Path(tokens[0]).name
    arguments = tokens[1:]
    if reader == "cat":
        if arguments[:1] == ["--"]:
            arguments = arguments[1:]
        if len(arguments) != 1 or not resolves_to(arguments[0], run_dir, target_path):
            return None
        start_line, end_line = 1, len(target_lines)
    elif reader == "sed":
        parsed = sed_read_segment(arguments, run_dir, target_path, len(target_lines))
        if parsed is None:
            return None
        start_line, end_line = parsed
    else:
        return None
    expected = "".join(target_lines[start_line - 1:end_line])
    if action.output.rstrip("\n") != expected.rstrip("\n"):
        return None
    return start_line, end_line


def sed_read_segment(
    arguments: list[str],
    run_dir: Path,
    target_path: Path,
    total_lines: int,
) -> tuple[int, int] | None:
    if len(arguments) == 3 and arguments[0] == "-n":
        expression, path = arguments[1:]
    elif len(arguments) == 4 and arguments[:2] == ["-n", "-e"]:
        expression, path = arguments[2:]
    else:
        return None
    if not resolves_to(path, run_dir, target_path):
        return None
    match = re.fullmatch(r"([1-9][0-9]*)(?:,([1-9][0-9]*|\$))?p", expression)
    if match is None:
        return None
    start_line = int(match.group(1))
    raw_end = match.group(2)
    end_line = start_line if raw_end is None else total_lines if raw_end == "$" else int(raw_end)
    end_line = min(end_line, total_lines)
    if start_line > total_lines or end_line < start_line:
        return None
    return start_line, end_line


def native_read_segment(
    action: ActionEvent,
    run_dir: Path,
    target_path: Path,
    target_lines: list[str],
) -> tuple[int, int] | None:
    total_target_lines = len(target_lines)
    raw_path = action.input.get("file_path") or action.input.get("path")
    if not isinstance(raw_path, str) or not resolves_to(raw_path, run_dir, target_path):
        return None
    result = action.result
    if isinstance(result, dict) and isinstance(result.get("file"), dict):
        file_result = result["file"]
        start_line = file_result.get("startLine")
        line_count = file_result.get("numLines")
        total_lines = file_result.get("totalLines")
        if all(isinstance(value, int) for value in (start_line, line_count, total_lines)):
            normalized_start = 1 if start_line == 0 else start_line
            if normalized_start < 1 or line_count < 1 or total_lines != total_target_lines:
                return None
            return normalized_start, min(total_target_lines, normalized_start + line_count - 1)

    raw_start = action.input.get("offset", 1)
    raw_limit = action.input.get("limit")
    if not isinstance(raw_start, int) or raw_start < 1:
        return None
    if raw_limit is None:
        end_line = total_target_lines
    elif isinstance(raw_limit, int) and raw_limit > 0:
        end_line = min(total_target_lines, raw_start + raw_limit - 1)
    else:
        return None
    if raw_start > total_target_lines:
        return None
    expected = "".join(target_lines[raw_start - 1 : end_line])
    if action.output.rstrip("\n") != expected.rstrip("\n"):
        return None
    return raw_start, end_line


def completes_before_action(action: ActionEvent, next_action: ActionEvent) -> bool:
    return action.completion_order is not None and action.completion_order < next_action.start_order


def simple_command_tokens(command: str) -> list[str] | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if (
        len(tokens) == 3
        and Path(tokens[0]).name in {"bash", "dash", "ksh", "sh", "zsh"}
        and tokens[1] in {"-c", "-lc"}
    ):
        try:
            tokens = shlex.split(tokens[2])
        except ValueError:
            return None
    shell_operators = {"&", "&&", ";", "|", "||", "<", ">", ">>", "2>", "2>>"}
    if any(
        token in shell_operators
        or any(operator in token for operator in (";", "|", "&", ">", "<", "`", "$("))
        for token in tokens
    ):
        return None
    return tokens


def resolves_to(value: str, run_dir: Path, target_path: Path) -> bool:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = run_dir / candidate
    return candidate.resolve() == target_path


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
