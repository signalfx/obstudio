#!/usr/bin/env python3
"""Fail if any SKILL.md description exceeds the platform's 1,536 character cap.

Checks both the canonical skills/ tree and plugins/obstudio/skills/ (which
also contains plugin-local skills, e.g. observer-control/*, with no
canonical counterpart).

Parses just enough YAML to resolve the `description` frontmatter field (plain
scalar or `|`/`>` block scalar, with any chomping indicator) without adding a
PyYAML dependency to the repo.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DESCRIPTION_CAP = 1536

_KEY_RE = re.compile(r"^description:[ \t]*(.*)$")
_BLOCK_HEADER_RE = re.compile(r"^([|>])([+-]?)[ \t]*$")
_TOP_LEVEL_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+:")


def _extract_frontmatter(text: str) -> str | None:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None
    for index, raw_line in enumerate(lines[1:], start=1):
        if raw_line.rstrip("\r\n") == "---":
            return "".join(lines[1:index])
    return None


def _block_scalar_value(lines: list[str], indicator: str, chomping: str) -> str:
    content_lines: list[str] = []
    indent: int | None = None
    for raw_line in lines:
        stripped = raw_line.rstrip("\r\n")
        if stripped.strip() == "":
            content_lines.append("")
            continue
        line_indent = len(stripped) - len(stripped.lstrip(" "))
        if indent is None:
            indent = line_indent
        elif line_indent < indent:
            break
        content_lines.append(stripped[indent:])

    if indicator == "|":
        value = "\n".join(content_lines)
    else:
        paragraphs: list[list[str]] = [[]]
        for line in content_lines:
            if line == "":
                paragraphs.append([])
            else:
                paragraphs[-1].append(line)
        value = "\n".join(" ".join(p) for p in paragraphs if p or len(paragraphs) == 1)

    if chomping == "-":
        return value.rstrip("\n")
    if chomping == "+":
        return value
    return value.rstrip("\n") + "\n" if value else value


def _description_from_frontmatter(frontmatter: str) -> str | None:
    lines = frontmatter.splitlines()
    for line_index, line in enumerate(lines):
        match = _KEY_RE.match(line)
        if not match:
            continue
        remainder = match.group(1).strip()
        block_match = _BLOCK_HEADER_RE.match(remainder) if remainder else None
        if block_match:
            body_lines = []
            for later in lines[line_index + 1 :]:
                if later.strip() and _TOP_LEVEL_KEY_RE.match(later) and not later.startswith((" ", "\t")):
                    break
                body_lines.append(later)
            return _block_scalar_value(
                body_lines, block_match.group(1), block_match.group(2)
            )
        if remainder.startswith('"') and remainder.endswith('"') and len(remainder) >= 2:
            return remainder[1:-1]
        if remainder.startswith("'") and remainder.endswith("'") and len(remainder) >= 2:
            return remainder[1:-1]
        return remainder
    return None


def _find_skill_files(root: Path) -> list[Path]:
    seen: dict[Path, Path] = {}
    for skills_dir, pattern in (
        (root / "skills", "*/SKILL.md"),
        (root / "plugins" / "obstudio" / "skills", "**/SKILL.md"),
    ):
        for skill_file in sorted(skills_dir.glob(pattern)):
            seen.setdefault(skill_file.resolve(), skill_file)
    return sorted(seen.values(), key=lambda path: path.relative_to(root))


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    errors: list[str] = []

    skill_files = _find_skill_files(root)
    if not skill_files:
        print(f"{root}: no SKILL.md files found under skills/ or plugins/obstudio/skills/", file=sys.stderr)
        return 1

    for skill_file in skill_files:
        rel = skill_file.relative_to(root)
        text = skill_file.read_text(encoding="utf-8")
        frontmatter = _extract_frontmatter(text)
        if frontmatter is None:
            errors.append(f"{rel}: missing leading YAML frontmatter")
            continue
        description = _description_from_frontmatter(frontmatter)
        if description is None:
            errors.append(f"{rel}: frontmatter has no description field")
            continue
        length = len(description)
        if length > DESCRIPTION_CAP:
            errors.append(
                f"{rel}: description is {length} characters, exceeds the "
                f"{DESCRIPTION_CAP} character cap"
            )

    if errors:
        print("Skill description length check failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"Checked {len(skill_files)} skill description(s), all within the {DESCRIPTION_CAP} character cap.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
