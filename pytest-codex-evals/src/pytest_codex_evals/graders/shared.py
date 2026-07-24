from __future__ import annotations

import difflib
import re
import shlex
from pathlib import Path
from typing import Any

from pytest_codex_evals.ab import INSTRUCTION_COMPANIONS, SKILL_COMPANIONS
from pytest_codex_evals.definitions import GradeCheckResult
from pytest_codex_evals.trace import TraceSummary


GLOBAL_SKILL_ROOT = re.compile(
    r"(?:/\.codex/(?:skills|plugins)|\$\{?codex_home\}?|/plugins/cache/)"
    r"(?=[/\s\"'`]|$)",
    re.IGNORECASE,
)
COMPANION_ARTIFACT = re.compile(
    r"(?:^|[/\s\"'`])otel-verify\.json\b", re.IGNORECASE
)
COMPANION_WORKFLOW = re.compile(
    r"(?:^|[\s\"'`])\$?otel-verify(?=$|[\s\"'`])", re.IGNORECASE
)
COMPANION_FINALIZER = re.compile(r"\bfinalize-instrumentation\b", re.IGNORECASE)
DIRECT_SKILL_READERS = {"cat", "head", "tail", "sed"}
DIRECT_SKILL_READ_METADATA = {"wc"}
SHELL_READ_WRAPPERS = {"bash", "sh", "zsh"}


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
        checks.append(check_selected_skill_source_isolation(run_dir, trace, skill))
        if skill in SKILL_COMPANIONS:
            checks.append(
                check_companion_skill_source_isolation(run_dir, trace, skill)
            )
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


def check_selected_skill_source_isolation(
    run_dir: Path,
    trace: TraceSummary,
    selected_skill: str,
) -> GradeCheckResult:
    """Prove the agent loaded the staged skill rather than another installation."""

    staged_relative = f".agents/skills/{selected_skill}/SKILL.md"
    staged_path = run_dir / staged_relative
    expected_text = (
        staged_path.read_text(encoding="utf-8", errors="strict")
        if staged_path.is_file()
        else None
    )
    skill_path = re.compile(
        rf"(?P<path>[^\s\"'`;|&()<>]*{re.escape(selected_skill)}/SKILL\.md)",
        re.IGNORECASE,
    )
    forbidden_commands: list[str] = []
    staged_outputs: list[str] = []
    for item in trace_command_items(trace):
        command = item.get("command")
        if not isinstance(command, str):
            continue
        references = skill_path.findall(command)
        if GLOBAL_SKILL_ROOT.search(command) or any(
            not is_staged_companion_reference(reference, run_dir, staged_relative)
            for reference in references
        ):
            forbidden_commands.append(command)
            continue
        if not references or not direct_skill_read(command):
            continue
        output = item.get("aggregated_output")
        exit_code = item.get("exit_code")
        status = str(item.get("status", "")).lower()
        if (
            exit_code in (None, 0)
            and status not in {"failed", "cancelled", "canceled"}
            and isinstance(output, str)
        ):
            staged_outputs.append(output)

    if forbidden_commands:
        passed = False
        evidence = "Forbidden selected-skill path: " + forbidden_commands[0]
    elif expected_text is None:
        passed = False
        evidence = f"Missing staged selected skill: {staged_path}"
    elif not outputs_cover_text(expected_text, staged_outputs):
        passed = False
        evidence = f"No complete successful read of {staged_relative}"
    else:
        passed = True
        evidence = f"Loaded the complete skill from {staged_relative}"
    return GradeCheckResult(
        id="selected-skill-source-isolation",
        description=(
            "The governing SKILL.md is loaded completely from the authenticated "
            "staged skill, never from a global or alternate installation."
        ),
        passed=passed,
        evidence=evidence,
        category="sanity",
    )


def outputs_cover_text(expected_text: str, outputs: list[str]) -> bool:
    expected_lines = expected_text.splitlines()
    if not expected_lines:
        return False
    covered: set[int] = set()
    for output in outputs:
        matcher = difflib.SequenceMatcher(
            None,
            expected_lines,
            output.splitlines(),
            autojunk=False,
        )
        for block in matcher.get_matching_blocks():
            covered.update(range(block.a, block.a + block.size))
    return len(covered) == len(expected_lines)


def check_companion_skill_source_isolation(
    run_dir: Path,
    trace: TraceSummary,
    selected_skill: str,
) -> GradeCheckResult:
    companions = SKILL_COMPANIONS.get(selected_skill, ())
    if not companions:
        return GradeCheckResult(
            id="companion-skill-source-isolation",
            description="No authenticated companion skill is required.",
            passed=True,
            evidence="No companion skill configured",
            category="sanity",
        )

    results = [
        check_one_companion_source_isolation(
            run_dir,
            trace,
            selected_skill,
            companion,
        )
        for companion in companions
    ]
    failed = next((result for result in results if not result[0]), None)
    if failed is not None:
        passed, evidence = failed
    else:
        passed = True
        evidence = "; ".join(result[1] for result in results)
    return GradeCheckResult(
        id="companion-skill-source-isolation",
        description=(
            "Companion instructions and scripts come only from authenticated "
            "staged skill trees; instruction companions are loaded exactly once "
            "when delegated."
        ),
        passed=passed,
        evidence=evidence,
        category="sanity",
    )


def check_one_companion_source_isolation(
    run_dir: Path,
    trace: TraceSummary,
    selected_skill: str,
    companion: str,
) -> tuple[bool, str]:
    staged_relative = f".agents/skills/{companion}/SKILL.md"
    staged_path = run_dir / staged_relative
    expected_text = (
        staged_path.read_text(encoding="utf-8", errors="strict")
        if staged_path.is_file()
        else None
    )
    companion_skill_path = re.compile(
        rf"(?P<path>[^\s\"'`;|&()<>]*{re.escape(companion)}/SKILL\.md)",
        re.IGNORECASE,
    )
    companion_tree_path = re.compile(
        rf"(?P<path>(?:[^\s\"'`;|&()<>]*/{re.escape(companion)}"
        rf"(?:/[^\s\"'`;|&()<>]+)?|{re.escape(companion)}/"
        r"[^\s\"'`;|&()<>]+))(?=$|[\s\"'`;|&()<>])",
        re.IGNORECASE,
    )
    instruction_companion = selected_skill in INSTRUCTION_COMPANIONS
    forbidden_commands: list[str] = []
    delegated_commands: list[str] = []
    complete_reads = 0
    for item in trace_command_items(trace):
        command = item.get("command")
        if not isinstance(command, str):
            continue
        references = companion_skill_path.findall(command)
        tree_references = companion_tree_path.findall(command)
        if GLOBAL_SKILL_ROOT.search(command) or any(
            not is_staged_companion_tree_reference(
                reference, run_dir, staged_relative
            )
            for reference in tree_references
        ):
            forbidden_commands.append(command)
            continue
        if (
            tree_references
            or (
                instruction_companion
                and (
                    COMPANION_ARTIFACT.search(command)
                    or COMPANION_WORKFLOW.search(command)
                    or COMPANION_FINALIZER.search(command)
                )
            )
        ):
            delegated_commands.append(command)
        if not references or not direct_skill_read(command):
            continue
        if not all(
            is_staged_companion_reference(reference, run_dir, staged_relative)
            for reference in references
        ):
            continue
        output = item.get("aggregated_output")
        exit_code = item.get("exit_code")
        status = str(item.get("status", "")).lower()
        succeeded = exit_code in (None, 0) and status not in {
            "failed",
            "cancelled",
            "canceled",
        }
        if (
            succeeded
            and expected_text is not None
            and isinstance(output, str)
            and expected_text.rstrip("\n") in output
        ):
            complete_reads += len(references)

    if forbidden_commands:
        return False, "Forbidden companion-skill path: " + forbidden_commands[0]
    elif expected_text is None:
        return False, f"Missing staged companion skill: {staged_path}"
    elif instruction_companion and delegated_commands and complete_reads != 1:
        return False, (
            f"Companion workflow was invoked; expected exactly one complete read "
            f"of {staged_relative}; observed {complete_reads}"
        )
    elif instruction_companion and not delegated_commands:
        return True, f"{companion}: workflow not invoked; no instruction read required"
    elif instruction_companion:
        return True, f"{companion}: loaded exactly once from {staged_relative}"
    return True, f"{companion}: authenticated staged support tree available"


def trace_command_items(trace: TraceSummary) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for event in trace.events:
        item = event.get("item")
        if item is None and isinstance(event.get("payload"), dict):
            item = event["payload"].get("item")
        if isinstance(item, dict) and item.get("type") == "command_execution":
            items.append(item)
    return items


def is_staged_companion_reference(
    reference: str,
    run_dir: Path,
    staged_relative: str,
) -> bool:
    normalized = reference.removeprefix("./")
    if normalized in {staged_relative, f"../{staged_relative}"}:
        return True
    path = Path(reference)
    return path.is_absolute() and path == run_dir / staged_relative


def is_staged_companion_tree_reference(
    reference: str,
    run_dir: Path,
    staged_relative: str,
) -> bool:
    normalized = reference.removeprefix("./")
    staged_root = str(Path(staged_relative).parent)
    service_relative_root = f"../{staged_root}"
    if (
        normalized == staged_root
        or normalized.startswith(staged_root + "/")
        or normalized == service_relative_root
        or normalized.startswith(service_relative_root + "/")
    ):
        return True
    path = Path(reference)
    absolute_root = run_dir / staged_root
    return path.is_absolute() and (
        path == absolute_root or absolute_root in path.parents
    )


def direct_skill_read(command: str) -> bool:
    """Recognize a direct, auditable full-file reader command."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if not tokens:
        return False
    executable = Path(tokens[0]).name
    if executable in SHELL_READ_WRAPPERS:
        arguments = tokens[1:]
        if executable == "bash" and arguments[:1] == ["--norc"]:
            arguments = arguments[1:]
        if not arguments or arguments[0] not in {"-c", "-lc"}:
            return False
        arguments = arguments[1:]
        if arguments[:1] == ["--"]:
            arguments = arguments[1:]
        return len(arguments) == 1 and direct_shell_skill_read(arguments[0])
    return executable in DIRECT_SKILL_READERS


def direct_shell_skill_read(command: str) -> bool:
    """Accept a bounded read sequence such as ``wc -l FILE && sed ... FILE``.

    The output still has to cover the authenticated staged file, so metadata
    commands cannot establish completeness by themselves. Reject pipes,
    redirects, backgrounding, substitutions, and executables other than the
    direct readers plus ``wc``.
    """

    if any(marker in command for marker in ("$(", "`", "\n", "\r")):
        return False
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return False

    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in {"&&", ";"}:
            if not segments[-1]:
                return False
            segments.append([])
        elif token in {"&", "|", "||", "<", ">", "<<", ">>"}:
            return False
        else:
            segments[-1].append(token)
    if not segments[-1]:
        return False

    readers = 0
    for segment in segments:
        executable = Path(segment[0]).name
        if executable in DIRECT_SKILL_READERS:
            readers += 1
        elif executable not in DIRECT_SKILL_READ_METADATA:
            return False
    return readers > 0


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
