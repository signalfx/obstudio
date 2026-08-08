#!/usr/bin/env python3
"""Validate deterministic repository policy contracts for coding agents."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import sys
from pathlib import Path


REQUIRED_HEADINGS = (
    "Coding Agent Definition of Done",
    "Reviewer Routing",
    "Code Review Rules",
    "Confluence Document Updates",
)
REQUIRED_RULE_IDS = ("OBS-SCOPE", "OBS-TEST", "OBS-SKILL", "OBS-PRESERVE")
ROUTED_AGENT_GUIDES = (
    "observer/AGENTS.md",
    "observer/client/AGENTS.md",
    "extension/AGENTS.md",
    "skills/AGENTS.md",
    "evals/AGENTS.md",
)
REQUIRED_CODEOWNER_PATTERNS = (
    "AGENTS.md",
    "/CONTRIBUTING.md",
    "/Makefile",
    "/.github/CODEOWNERS",
    "/.github/copilot-instructions.md",
    "/.github/PULL_REQUEST_TEMPLATE.md",
    "/.github/workflows/",
    "/evals/agent-guidelines/",
    "/evals/Makefile",
    "/evals/test_agent_guideline_contracts.py",
    "/scripts/check_agent_policy.py",
    "/tests/test_agent_policy.py",
)

MAKE_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*[?+:!]?=")
MAKE_TARGET_RE = re.compile(r"^([^\s:#=][^:#=]*):(?!=)")
SKILL_TABLE_ROW_RE = re.compile(r"^\|\s*`\$([^`]+)`\s*\|", re.MULTILINE)


def _read(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"{path}: cannot read file: {exc}")
        return ""


def _section(markdown: str, title: str) -> str | None:
    match = re.search(rf"^##\s+{re.escape(title)}\s*$", markdown, re.MULTILINE)
    if not match:
        return None
    end = re.search(r"^##\s+", markdown[match.end() :], re.MULTILINE)
    if end:
        return markdown[match.end() : match.end() + end.start()]
    return markdown[match.end() :]


def _canonical_skills(root: Path, errors: list[str]) -> set[str]:
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        errors.append("skills/: canonical skill directory is missing")
        return set()

    names: set[str] = set()
    for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
        name = skill_file.parent.name
        names.add(name)
        text = _read(skill_file, errors)
        frontmatter_name = re.search(r"^name:\s*([^\s]+)\s*$", text, re.MULTILINE)
        if not frontmatter_name:
            errors.append(f"{skill_file.relative_to(root)}: missing frontmatter name")
        elif frontmatter_name.group(1) != name:
            errors.append(
                f"{skill_file.relative_to(root)}: frontmatter name "
                f"{frontmatter_name.group(1)!r} must match directory {name!r}"
            )
    if not names:
        errors.append("skills/: no canonical */SKILL.md files found")
    return names


def _check_skill_discovery(root: Path, canonical: set[str], errors: list[str]) -> None:
    discovery_dir = root / ".agents" / "skills"
    if not discovery_dir.is_dir():
        errors.append(".agents/skills/: discovery directory is missing")
        return

    discovered = {entry.name for entry in discovery_dir.iterdir()}
    missing = canonical - discovered
    extra = discovered - canonical
    if missing:
        errors.append(
            ".agents/skills/: missing canonical skill links: " + ", ".join(sorted(missing))
        )
    if extra:
        errors.append(
            ".agents/skills/: entries without canonical skills: " + ", ".join(sorted(extra))
        )

    for name in sorted(canonical & discovered):
        link = discovery_dir / name
        if not link.is_symlink():
            errors.append(f"{link.relative_to(root)}: must be a symbolic link")
            continue
        raw_target = os.readlink(link)
        if Path(raw_target).is_absolute():
            errors.append(f"{link.relative_to(root)}: link target must be relative")
            continue
        expected_target = Path("..") / ".." / "skills" / name
        if Path(raw_target) != expected_target:
            errors.append(
                f"{link.relative_to(root)}: link target must be {expected_target}, "
                f"found {raw_target}"
            )
        try:
            resolved = link.resolve(strict=True)
        except OSError as exc:
            errors.append(f"{link.relative_to(root)}: broken skill link: {exc}")
            continue
        expected = (root / "skills" / name).resolve(strict=True)
        if resolved != expected:
            errors.append(
                f"{link.relative_to(root)}: resolves to {resolved}, expected {expected}"
            )


def _check_instruction_structure(
    root: Path, agents_text: str, canonical: set[str], errors: list[str]
) -> None:
    for heading in REQUIRED_HEADINGS:
        if _section(agents_text, heading) is None:
            errors.append(f"AGENTS.md: missing required '## {heading}' section")

    for reference in ("CONTRIBUTING.md", "skills/", ".agents/skills/"):
        if reference not in agents_text:
            errors.append(f"AGENTS.md: missing required reference to {reference}")

    routing = _section(agents_text, "Reviewer Routing") or ""
    for guide in ROUTED_AGENT_GUIDES:
        if guide not in routing:
            errors.append(f"AGENTS.md Reviewer Routing: missing {guide}")
        if not (root / guide).is_file():
            errors.append(f"{guide}: routed instruction file is missing")

    review_rules = _section(agents_text, "Code Review Rules") or ""
    for rule_id in REQUIRED_RULE_IDS:
        if rule_id not in review_rules:
            errors.append(f"AGENTS.md Code Review Rules: missing {rule_id}")

    available = _section(agents_text, "Available Skills")
    if available is None:
        errors.append("AGENTS.md: missing required '## Available Skills' section")
    else:
        table_names = set(SKILL_TABLE_ROW_RE.findall(available))
        missing = canonical - table_names
        extra = table_names - canonical
        if missing:
            errors.append(
                "AGENTS.md Available Skills: missing canonical skills: "
                + ", ".join(sorted(missing))
            )
        if extra:
            errors.append(
                "AGENTS.md Available Skills: unknown skills: " + ", ".join(sorted(extra))
            )

    adapter_path = root / ".github" / "copilot-instructions.md"
    adapter = _read(adapter_path, errors)
    if adapter:
        if "/AGENTS.md" not in adapter and "`AGENTS.md`" not in adapter:
            errors.append(
                ".github/copilot-instructions.md: must route to the canonical root AGENTS.md"
            )
        for heading in ("Reviewer Routing", "Code Review Rules"):
            if heading not in adapter:
                errors.append(
                    f".github/copilot-instructions.md: missing routing reference to {heading}"
                )


def _check_pr_template(root: Path, errors: list[str]) -> None:
    path = root / ".github" / "PULL_REQUEST_TEMPLATE.md"
    template = _read(path, errors)
    for heading in ("Summary", "Scope", "Validation evidence", "Risk and review"):
        if re.search(rf"^##\s+{re.escape(heading)}\s*$", template, re.MULTILINE) is None:
            errors.append(f".github/PULL_REQUEST_TEMPLATE.md: missing '## {heading}'")
    for evidence in ("Exact commands and results", "Checks skipped", "Residual risks"):
        if evidence.casefold() not in template.casefold():
            errors.append(
                f".github/PULL_REQUEST_TEMPLATE.md: missing evidence field {evidence!r}"
            )


def _check_cross_document_claims(
    agents_text: str, contributing_text: str, errors: list[str]
) -> None:
    coverage_pointer = re.search(
        r"(?:see|follow)\s+`?AGENTS\.md`?[^.\n]*coverage",
        contributing_text,
        re.IGNORECASE,
    )
    if coverage_pointer and "coverage" not in agents_text.lower():
        errors.append(
            "CONTRIBUTING.md: coverage guidance points to AGENTS.md, but AGENTS.md "
            "contains no coverage guidance"
        )


def _codeowner_patterns(text: str, errors: list[str]) -> dict[str, tuple[str, ...]]:
    patterns: dict[str, tuple[str, ...]] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            fields = shlex.split(stripped, comments=True)
        except ValueError as exc:
            errors.append(f".github/CODEOWNERS:{line_number}: invalid entry: {exc}")
            continue
        if len(fields) < 2 or not all(owner.startswith("@") for owner in fields[1:]):
            errors.append(
                f".github/CODEOWNERS:{line_number}: expected a path and at least one @owner"
            )
            continue
        patterns[fields[0]] = tuple(fields[1:])
    return patterns


def _check_codeowners(root: Path, errors: list[str]) -> None:
    path = root / ".github" / "CODEOWNERS"
    patterns = _codeowner_patterns(_read(path, errors), errors)
    missing = set(REQUIRED_CODEOWNER_PATTERNS) - set(patterns)
    if missing:
        errors.append(
            ".github/CODEOWNERS: missing protected policy paths: "
            + ", ".join(sorted(missing))
        )
    single_owner = [
        pattern
        for pattern in REQUIRED_CODEOWNER_PATTERNS
        if pattern in patterns and len(set(patterns[pattern])) < 2
    ]
    if single_owner:
        errors.append(
            ".github/CODEOWNERS: policy paths need at least two independent owners: "
            + ", ".join(single_owner)
        )


def _markdown_snippets(text: str) -> list[tuple[int, str]]:
    snippets: list[tuple[int, str]] = []
    fence: str | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token[0]
            elif token[0] == fence:
                fence = None
            continue
        if fence is not None:
            snippets.append((line_number, line))
            continue
        for inline in re.findall(r"`([^`\n]+)`", line):
            snippets.append((line_number, inline))
    return snippets


def _shell_segments(command: str) -> list[tuple[list[str], str | None]]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = "#"
        tokens = list(lexer)
    except ValueError:
        return []

    segments: list[tuple[list[str], str | None]] = []
    current: list[str] = []
    for token in tokens:
        if token and all(char in ";&|" for char in token):
            if current:
                segments.append((current, token))
                current = []
        else:
            current.append(token)
    if current:
        segments.append((current, None))
    return segments


def _make_arguments(args: list[str]) -> tuple[Path, list[str]]:
    directory = Path(".")
    targets: list[str] = []
    options_with_values = {
        "-f",
        "--file",
        "--makefile",
        "-I",
        "--include-dir",
        "-j",
        "--jobs",
        "-l",
        "--load-average",
        "-o",
        "--old-file",
        "--assume-old",
        "-W",
        "--what-if",
        "--eval",
    }
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in ("-C", "--directory"):
            if index + 1 < len(args):
                directory /= args[index + 1]
                index += 2
                continue
            break
        if arg.startswith("--directory="):
            directory /= arg.split("=", 1)[1]
        elif arg.startswith("-C") and len(arg) > 2:
            directory /= arg[2:]
        elif arg in options_with_values:
            index += 2
            continue
        elif arg.startswith("-") or MAKE_ASSIGNMENT_RE.match(arg):
            pass
        elif "$" not in arg:
            targets.append(arg)
        index += 1
    return directory, targets


def _make_references(text: str) -> list[tuple[int, Path, str]]:
    references: list[tuple[int, Path, str]] = []
    for line_number, snippet in _markdown_snippets(text):
        working_dir = Path(".")
        for segment, connector in _shell_segments(snippet):
            if segment and segment[0] == "$":
                segment = segment[1:]
            if len(segment) == 2 and segment[0] == "cd":
                working_dir /= segment[1]
                continue
            try:
                make_index = segment.index("make")
            except ValueError:
                continue
            make_dir, targets = _make_arguments(segment[make_index + 1 :])
            for target in targets:
                references.append((line_number, working_dir / make_dir, target))
            if connector not in ("&&", ";"):
                working_dir = Path(".")
    return references


def _makefile_targets(path: Path, errors: list[str]) -> set[str]:
    text = _read(path, errors)
    targets: set[str] = set()
    for line in text.splitlines():
        match = MAKE_TARGET_RE.match(line)
        if not match:
            continue
        for target in match.group(1).split():
            if not target.startswith(".") and "$" not in target and "%" not in target:
                targets.add(target)
    return targets


def _check_make_references(root: Path, documents: tuple[Path, ...], errors: list[str]) -> None:
    target_cache: dict[Path, set[str]] = {}
    for document in documents:
        text = _read(document, errors)
        for line_number, relative_dir, target in _make_references(text):
            makefile = (root / relative_dir / "Makefile").resolve()
            try:
                makefile.relative_to(root.resolve())
            except ValueError:
                errors.append(
                    f"{document.relative_to(root)}:{line_number}: make directory escapes repository"
                )
                continue
            if not makefile.is_file():
                errors.append(
                    f"{document.relative_to(root)}:{line_number}: make {target} has no "
                    f"Makefile in {relative_dir}"
                )
                continue
            targets = target_cache.setdefault(makefile, _makefile_targets(makefile, errors))
            if target not in targets:
                errors.append(
                    f"{document.relative_to(root)}:{line_number}: unknown make target "
                    f"{target!r} in {makefile.relative_to(root)}"
                )


def check_repository(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    agents_path = root / "AGENTS.md"
    contributing_path = root / "CONTRIBUTING.md"
    agents_text = _read(agents_path, errors)
    contributing_text = _read(contributing_path, errors)

    canonical = _canonical_skills(root, errors)
    _check_skill_discovery(root, canonical, errors)
    _check_instruction_structure(root, agents_text, canonical, errors)
    _check_cross_document_claims(agents_text, contributing_text, errors)
    _check_pr_template(root, errors)
    _check_codeowners(root, errors)
    policy_documents = (
        agents_path,
        contributing_path,
        *(root / guide for guide in ROUTED_AGENT_GUIDES),
    )
    _check_make_references(root, policy_documents, errors)
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to this script's parent repository)",
    )
    args = parser.parse_args(argv)
    errors = check_repository(args.root)
    if errors:
        print("Agent policy check failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("Agent policy check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
