#!/usr/bin/env python3
"""Validate deterministic repository policy contracts for coding agents."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path


REQUIRED_HEADINGS = (
    "Coding Agent Definition of Done",
    "Reviewer Routing",
    "Code Review Rules",
    "Confluence Document Updates",
)
PROTECTED_SECTION_TITLES = REQUIRED_HEADINGS + ("Available Skills",)
REQUIRED_RULE_IDS = (
    "OBS-SCOPE",
    "OBS-TEST",
    "OBS-SKILL",
    "OBS-PRESERVE",
    "OBS-UI",
    "OBS-PLUGIN",
    "OBS-INTEGRATION",
)
ROUTED_AGENT_GUIDES = (
    "observer/AGENTS.md",
    "observer/client/AGENTS.md",
    "extension/AGENTS.md",
    "skills/AGENTS.md",
    "evals/AGENTS.md",
    "pytest-codex-evals/AGENTS.md",
)
ROUTED_AGENT_GUIDE_DESCRIPTIONS = {
    "observer/AGENTS.md": "Go collector, OTLP, REST, MCP, storage, and serving.",
    "observer/client/AGENTS.md": "React Telemetry Explorer.",
    "extension/AGENTS.md": (
        "VS Code-compatible editor extension and packaging."
    ),
    "skills/AGENTS.md": "canonical skill sources and skill-level tests.",
    "evals/AGENTS.md": "eval fixtures, checks, configs, and reports.",
    "pytest-codex-evals/AGENTS.md": (
        "reusable pytest plugin and compatibility."
    ),
}
ROUTED_AGENT_GUIDE_PREAMBLES = {
    "observer/AGENTS.md": (
        "This file adds Go backend guidance to the repository-root `AGENTS.md`."
    ),
    "observer/client/AGENTS.md": (
        "This file adds React client guidance to the applicable parent instructions."
    ),
    "extension/AGENTS.md": (
        "This file adds editor-extension guidance to the repository-root `AGENTS.md`."
    ),
    "skills/AGENTS.md": (
        "This file adds skill-maintenance guidance to the repository-root `AGENTS.md`."
    ),
    "evals/AGENTS.md": (
        "This file adds eval-harness and fixture guidance to the repository-root "
        "`AGENTS.md`."
    ),
    "pytest-codex-evals/AGENTS.md": (
        "This file adds reusable-plugin guidance to the repository-root `AGENTS.md`."
    ),
}
ROUTED_AGENT_GUIDE_TITLES = {
    "observer/AGENTS.md": "Observer Instructions",
    "observer/client/AGENTS.md": "Observer Client Instructions",
    "extension/AGENTS.md": "Extension Instructions",
    "skills/AGENTS.md": "Skill Source Instructions",
    "evals/AGENTS.md": "Eval Instructions",
    "pytest-codex-evals/AGENTS.md": "Pytest Plugin Instructions",
}
COPILOT_ADAPTER_CONTRACT = """# Repository Instructions

`/AGENTS.md` is the canonical instruction source for this repository. Read and
follow it before coding or reviewing, together with every nested `AGENTS.md`
that applies to a changed path.

For pull request reviews, follow `/AGENTS.md` sections **Reviewer Routing** and
**Code Review Rules**. Identify a finding with its stable `OBS-*` rule ID when
one applies; do not force ordinary correctness, security, or reliability bugs
into an unrelated repository-specific rule. Use `/CONTRIBUTING.md` for the
development and pull request workflow. Do not duplicate or redefine those
policies here.
"""
PR_TEMPLATE_REQUIRED_FIELDS = {
    "Validation evidence": (
        "Exact commands and results:",
        "Skill eval file(s), when shipped skill content changed:",
        "Local rubric command and result for each added or modified skill; for a "
        "complete retirement, record agent-policy and eval-harness cleanup results:",
        "Affected UI interaction/accessibility evidence; smallest supported or "
        "narrowest tested IDE/container dimensions, normal and live-resize behavior, "
        "and relevant theme/zoom or text-scaling visual evidence:",
        "Plugin/integration and shared UI host compatibility evidence; capability "
        "and isolated-failure evidence when discovery, shared state, lifecycle, "
        "execution, orchestration, or host APIs changed:",
        "Checks skipped and why:",
    ),
    "Risk and review": ("Residual risks or unverified assumptions:",),
}
RUBRIC_DIRECTORY_NAMES = {"qual", "rubric"}
EVAL_DEFINITION_DIRECTORY_NAMES = RUBRIC_DIRECTORY_NAMES | {"runtime", "sanity"}
SHARED_CONSUMER_MAP = Path("skills/references/consumers.json")

MAKE_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*[?+:!]?=")
MAKE_TARGET_RE = re.compile(r"^([^\s:#=][^:#=]*):(?!=)")
AVAILABLE_SKILLS_HEADER_RE = re.compile(
    r"^\|[ \t]*Skill[ \t]*\|[ \t]*Purpose[ \t]*\|[ \t]*$"
)
AVAILABLE_SKILLS_DELIMITER_RE = re.compile(
    r"^\|[ \t]*:?-{3,}:?[ \t]*\|"
    r"[ \t]*:?-{3,}:?[ \t]*\|[ \t]*$"
)
SKILL_TABLE_ROW_RE = re.compile(
    r"^\|[ \t]*`\$([^`]+)`[ \t]*\|.+\|[ \t]*$"
)
FENCE_RE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})(.*)$")
ATX_HEADING_RE = re.compile(r"^(#{1,6})(?!#)(?:[ \t]+(.*?))?[ \t]*$")
INDENTED_ATX_HEADING_RE = re.compile(
    r"^[ ]{1,3}(#{1,6})(?!#)(?:[ \t]+(.*?))?[ \t]*$"
)
SETEXT_UNDERLINE_RE = re.compile(r"^[ ]{0,3}(?P<marker>=+|-+)[ \t]*$")
THEMATIC_BREAK_RE = re.compile(
    r"^[ ]{0,3}(?:\*[ \t]*){3,}$|"
    r"^[ ]{0,3}(?:_[ \t]*){3,}$|"
    r"^[ ]{0,3}(?:-[ \t]*){3,}$"
)
CONTAINER_BLOCK_RE = re.compile(
    r"^[ ]{0,3}(?:>|[*+-](?:[ \t]+|$)|[0-9]{1,9}[.)](?:[ \t]+|$))"
)
BLOCK_QUOTE_PREFIX_RE = re.compile(r"^[ ]{0,3}>[ \t]?")
LIST_PREFIX_RE = re.compile(
    r"^[ ]{0,3}(?:[*+-]|[0-9]{1,9}[.)])(?P<spacing>[ \t]+)(?P<content>.*)$"
)
INDENTED_CONTENT_RE = re.compile(r"^(?: {4}| {0,3}\t)")
LINK_REFERENCE_BLOCK_RE = re.compile(
    r"(?m)^[ ]{0,3}\["
    r"(?:\\[^\r\n]|[^\[\]\\\r\n]|(?:\r\n|\r|\n)[ ]{0,3}(?=[^\r\n])){1,999}"
    r"\]:"
)
GFM_TABLE_DELIMITER_RE = re.compile(
    r"^[ \t]*(?=[^\r\n]*\|)\|?[ \t]*:?-+:?[ \t]*"
    r"(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$"
)
PLAIN_SECTION_HEADING_RE = re.compile(r"^## [A-Za-z0-9][A-Za-z0-9 ]*$")
EXACT_RULE_HEADING_RE = re.compile(
    r"^###[ \t]+(?P<id>OBS-[A-Z][A-Z0-9-]*)[ \t]+--[ \t]+(?P<title>.+?)"
    r"[ \t]*$"
)
FORBIDDEN_RULE_TITLE_MARKUP = frozenset("\\`*_[]<>#&~$")
RAW_HTML_RE = re.compile(
    r"<(?:!--|\?|!\[CDATA\[|![A-Za-z]|"
    r"/?[A-Za-z][A-Za-z0-9-]*(?=[ \t\v\f\r\n/>]|$))",
    re.IGNORECASE,
)
PARENT_INSTRUCTION_NEGATION_RE = re.compile(
    r"\b(?:ignore|disregard|override|supersede|do not follow|don't follow)\b"
    r"[^\r\n.]{0,120}\b(?:repository(?:-root| root)?|parent)\b|"
    r"\b(?:repository(?:-root| root)?|parent)\b[^\r\n.]{0,120}"
    r"\b(?:do not apply|does not apply|are not applicable|must not be followed)\b",
    re.IGNORECASE,
)


def _commonmark_lines(markdown: str) -> list[str]:
    return [
        match.group(0)
        for match in re.finditer(r"[^\r\n]*(?:\r\n|\r|\n|$)", markdown)
        if match.group(0)
    ]


def _is_markdown_blank(text: str) -> bool:
    return not text or all(character in " \t" for character in text)


def _read(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"{path}: cannot read file: {exc}")
        return ""


def _read_policy_file(path: Path, root: Path, errors: list[str]) -> str:
    if path.is_symlink():
        errors.append(
            f"{path.relative_to(root)}: policy entrypoint must not be a symbolic link"
        )
        return ""
    return _read(path, errors)


def _mask_fenced_blocks(markdown: str) -> str:
    masked: list[str] = []
    fence: tuple[str, int] | None = None
    for raw_line in _commonmark_lines(markdown):
        line = raw_line.rstrip("\r\n")
        marker = FENCE_RE.match(line)
        if fence is not None:
            if marker:
                token, suffix = marker.groups()
                if (
                    token[0] == fence[0]
                    and len(token) >= fence[1]
                    and _is_markdown_blank(suffix)
                ):
                    fence = None
            masked.append("".join(char if char in "\r\n" else " " for char in raw_line))
            continue

        if (
            marker
            and line.startswith(marker.group(1)[0])
            and _is_valid_fence_opener(marker)
        ):
            token = marker.group(1)
            fence = (token[0], len(token))
            masked.append("".join(char if char in "\r\n" else " " for char in raw_line))
            continue
        masked.append(raw_line)
    return "".join(masked)


def _character_is_escaped(markdown: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and markdown[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def _mask_code_spans(markdown: str) -> str:
    masked = list(markdown)
    index = 0
    while index < len(markdown):
        if markdown[index] != "`" or _character_is_escaped(markdown, index):
            index += 1
            continue

        opener_end = index
        while opener_end < len(markdown) and markdown[opener_end] == "`":
            opener_end += 1
        delimiter_length = opener_end - index
        search_at = opener_end
        line_end = len(markdown)
        for separator in ("\r", "\n"):
            separator_at = markdown.find(separator, opener_end)
            if separator_at >= 0:
                line_end = min(line_end, separator_at)
        closer_end: int | None = None
        while search_at < line_end:
            closer_start = markdown.find("`", search_at)
            if closer_start < 0 or closer_start >= line_end:
                break
            candidate_end = closer_start
            while candidate_end < len(markdown) and markdown[candidate_end] == "`":
                candidate_end += 1
            if candidate_end - closer_start == delimiter_length:
                closer_end = candidate_end
                break
            search_at = candidate_end

        if closer_end is None:
            index = opener_end
            continue
        for position in range(index, closer_end):
            if masked[position] not in "\r\n":
                masked[position] = " "
        masked[index] = "x"
        index = closer_end
    return "".join(masked)


def _mask_html_comments(markdown: str) -> str:
    visible_markdown = _mask_code_spans(markdown)
    masked = list(markdown)
    cursor = 0
    while cursor < len(markdown):
        start = visible_markdown.find("<!--", cursor)
        if start < 0:
            break
        if _character_is_escaped(visible_markdown, start):
            cursor = start + 4
            continue
        close = visible_markdown.find("-->", start + 4)
        end = len(markdown) if close < 0 else close + 3
        for position in range(start, end):
            if masked[position] not in "\r\n":
                masked[position] = " "
        cursor = end
    return "".join(masked)


def _active_markdown(markdown: str) -> str:
    return _mask_html_comments(_mask_fenced_blocks(markdown))


def _check_nested_fences(markdown: str, source: str, errors: list[str]) -> None:
    active_markdown = _active_markdown(markdown)
    for raw_line in _commonmark_lines(active_markdown):
        line = raw_line.rstrip("\r\n")
        marker = FENCE_RE.match(_without_container_prefixes(line))
        if marker and _is_valid_fence_opener(marker):
            errors.append(
                f"{source}: nested or indented fenced blocks are not supported"
            )
            return


def _check_active_raw_html(markdown: str, source: str, errors: list[str]) -> None:
    visible_markdown = _mask_code_spans(_active_markdown(markdown))
    for raw_line in _commonmark_lines(visible_markdown):
        line = raw_line.rstrip("\r\n")
        if any(
            not _character_is_escaped(line, match.start())
            for match in RAW_HTML_RE.finditer(line)
        ):
            errors.append(f"{source}: raw HTML is not supported in active directives")
            return


def _without_container_prefixes(line: str) -> str:
    content = line
    while True:
        content = content.lstrip(" \t")
        if SETEXT_UNDERLINE_RE.match(content) or THEMATIC_BREAK_RE.match(content):
            return content
        quote = BLOCK_QUOTE_PREFIX_RE.match(content)
        if quote:
            content = content[quote.end() :]
            continue
        item = LIST_PREFIX_RE.match(content)
        if item:
            content = item.group("content")
            continue
        return content


def _is_valid_fence_opener(marker: re.Match[str]) -> bool:
    token, suffix = marker.groups()
    return token[0] == "~" or "`" not in suffix


def _policy_atx_headings(
    markdown: str,
) -> list[tuple[int, str, int, int]]:
    headings: list[tuple[int, str, int, int]] = []
    fence: tuple[str, int] | None = None
    offset = 0
    for raw_line in _commonmark_lines(markdown):
        line = raw_line.rstrip("\r\n")
        if fence is not None:
            marker = FENCE_RE.match(line)
            if marker:
                token, suffix = marker.groups()
                if (
                    token[0] == fence[0]
                    and len(token) >= fence[1]
                    and _is_markdown_blank(suffix)
                ):
                    fence = None
            offset += len(raw_line)
            continue

        marker = FENCE_RE.match(line)
        if (
            marker
            and line.startswith(marker.group(1)[0])
            and _is_valid_fence_opener(marker)
        ):
            token = marker.group(1)
            fence = (token[0], len(token))
            offset += len(raw_line)
            continue

        heading = ATX_HEADING_RE.match(line)
        if heading:
            hashes, raw_title = heading.groups()
            title_without_closer = re.sub(
                r"[ \t]+#+[ \t]*$", "", raw_title or ""
            )
            title = title_without_closer.strip(" \t")
            headings.append((len(hashes), title, offset, offset + len(raw_line)))
        offset += len(raw_line)
    return headings


def _source_line(markdown: str, start: int) -> str:
    end = start
    while end < len(markdown) and markdown[end] not in "\r\n":
        end += 1
    return markdown[start:end]


def _normalized_section_title(title: str) -> str:
    return " ".join(html.unescape(title).split()).casefold()


def _matching_section_headings(
    markdown: str, title: str
) -> list[tuple[str, str]]:
    expected = _normalized_section_title(title)
    return [
        (heading_title, _source_line(markdown, start).rstrip(" \t"))
        for level, heading_title, start, _end in _policy_atx_headings(markdown)
        if _normalized_section_title(heading_title) == expected
    ]


def _check_policy_markdown_ambiguity(markdown: str, errors: list[str]) -> None:
    unfenced_markdown = _mask_fenced_blocks(markdown)
    visible_markdown = _mask_code_spans(unfenced_markdown)
    for raw_line in _commonmark_lines(visible_markdown):
        line = raw_line.rstrip("\r\n")
        if any(
            character == "`" and not _character_is_escaped(line, index)
            for index, character in enumerate(line)
        ):
            errors.append(
                "AGENTS.md: inline code spans must open and close on the same "
                f"physical line: {line!r}"
            )
        if any(
            not _character_is_escaped(line, match.start())
            for match in RAW_HTML_RE.finditer(line)
        ):
            errors.append(
                "AGENTS.md: column-leading raw HTML syntax and inline raw HTML "
                f"syntax are not supported in the policy document: {line!r}"
            )

    fence: tuple[str, int] | None = None
    for raw_line in _commonmark_lines(markdown):
        line = raw_line.rstrip("\r\n")
        marker = FENCE_RE.match(line)
        if fence is not None:
            if marker:
                token, suffix = marker.groups()
                if (
                    token[0] == fence[0]
                    and len(token) >= fence[1]
                    and _is_markdown_blank(suffix)
                ):
                    fence = None
            continue

        if marker and _is_valid_fence_opener(marker):
            token = marker.group(1)
            if line.startswith(token[0]):
                fence = (token[0], len(token))
            else:
                errors.append(
                    "AGENTS.md: indented fenced blocks are ambiguous in the policy "
                    f"document; use a column-1 fence: {line!r}"
                )
            continue

        source_content = line.lstrip(" \t")
        container_content = _without_container_prefixes(line)
        structural_content = container_content.lstrip(" \t")
        nested_heading = ATX_HEADING_RE.match(structural_content)
        if structural_content != line and nested_heading:
            errors.append(
                "AGENTS.md: structural policy headings must use column-1 ATX "
                f"headings: {line!r}"
            )
        if (
            SETEXT_UNDERLINE_RE.match(source_content)
            or THEMATIC_BREAK_RE.match(source_content)
            or SETEXT_UNDERLINE_RE.match(structural_content)
            or THEMATIC_BREAK_RE.match(structural_content)
        ):
            errors.append(
                "AGENTS.md: setext headings and thematic breaks are not supported "
                "in the policy document"
            )

    if fence is not None:
        errors.append("AGENTS.md: unclosed fenced code block")

    headings = _policy_atx_headings(markdown)
    h1_sources = [
        _source_line(markdown, start).rstrip(" \t")
        for level, _title, start, _end in headings
        if level == 1
    ]
    if h1_sources != ["# AGENTS.md"]:
        errors.append(
            "AGENTS.md: expected exactly one literal '# AGENTS.md' document heading"
        )

    normalized_h2_titles: list[str] = []
    for level, title, start, _end in headings:
        if level >= 4:
            errors.append(
                "AGENTS.md: H4-H6 headings are not supported; use a plain paragraph"
            )
        if level != 2:
            continue
        source = _source_line(markdown, start).rstrip(" \t")
        normalized_h2_titles.append(_normalized_section_title(title))
        if PLAIN_SECTION_HEADING_RE.fullmatch(source) is None:
            errors.append(
                "AGENTS.md: top-level policy sections must use literal, plain-text "
                f"H2 headings: {source!r}"
            )
    for title in sorted(set(normalized_h2_titles)):
        if normalized_h2_titles.count(title) > 1:
            errors.append(
                "AGENTS.md: top-level policy section headings must be unique; "
                f"found {normalized_h2_titles.count(title)} headings named {title!r}"
            )


def _section_bounds_all(markdown: str, title: str) -> list[tuple[int, int]]:
    headings = _policy_atx_headings(markdown)
    sections: list[tuple[int, int]] = []
    for index, (level, heading_title, _start, content_start) in enumerate(headings):
        source = _source_line(markdown, _start).rstrip(" \t")
        if level != 2 or heading_title != title or source != f"## {title}":
            continue
        content_end = len(markdown)
        for next_level, _next_title, next_start, _next_end in headings[index + 1 :]:
            if next_level <= level:
                content_end = next_start
                break
        sections.append((content_start, content_end))
    return sections


def _section_bounds(markdown: str, title: str) -> tuple[int, int] | None:
    sections = _section_bounds_all(markdown, title)
    return sections[0] if sections else None


def _section(markdown: str, title: str) -> str | None:
    bounds = _section_bounds(markdown, title)
    if bounds is None:
        return None
    return markdown[bounds[0] : bounds[1]]


def _routing_entry_is_canonical(routing: str, guide: str) -> bool:
    entries = [
        raw_line.rstrip("\r\n")
        for raw_line in _commonmark_lines(routing)
        if re.match(
            rf"^[ ]{{0,3}}[-*+][ \t]+`{re.escape(guide)}`(?:[ \t]|$)",
            raw_line,
        )
    ]
    expected = f"- `{guide}` -- {ROUTED_AGENT_GUIDE_DESCRIPTIONS[guide]}"
    return entries == [expected]


def _available_skill_table_names(
    available: str, errors: list[str]
) -> set[str]:
    lines = [line.rstrip("\r\n") for line in _commonmark_lines(available)]
    header_indexes = [
        index
        for index, line in enumerate(lines)
        if AVAILABLE_SKILLS_HEADER_RE.fullmatch(line)
    ]
    if len(header_indexes) != 1:
        errors.append(
            "AGENTS.md Available Skills: expected exactly one literal "
            "'| Skill | Purpose |' table header"
        )
        return set()

    header_index = header_indexes[0]
    if header_index > 0 and not _is_markdown_blank(lines[header_index - 1]):
        errors.append(
            "AGENTS.md Available Skills: table header must begin a new Markdown block"
        )
        return set()
    if header_index + 1 >= len(lines) or AVAILABLE_SKILLS_DELIMITER_RE.fullmatch(
        lines[header_index + 1]
    ) is None:
        errors.append(
            "AGENTS.md Available Skills: table header must be followed by a "
            "two-column GFM delimiter row"
        )
        return set()

    names: list[str] = []
    for line in lines[header_index + 2 :]:
        if _is_markdown_blank(line) or not line.lstrip(" ").startswith("|"):
            break
        row = SKILL_TABLE_ROW_RE.fullmatch(line)
        if row is None:
            errors.append(
                "AGENTS.md Available Skills: every table row must use "
                "'| `$skill-name` | Purpose |'"
            )
            continue
        names.append(row.group(1))

    duplicates = sorted(name for name in set(names) if names.count(name) > 1)
    if duplicates:
        errors.append(
            "AGENTS.md Available Skills: duplicate skill rows: "
            + ", ".join(duplicates)
        )
    return set(names)


def _top_level_list_items(markdown: str) -> list[str]:
    items: list[str] = []
    current: list[str] | None = None
    for raw_line in _commonmark_lines(markdown):
        line = raw_line.rstrip("\r\n")
        item = re.match(r"^[-*+][ \t]+(.+)$", line)
        if item:
            if current is not None:
                items.append(" ".join(current))
            current = [item.group(1).strip()]
            continue
        if current is not None and re.match(r"^(?: {2,}|\t)\S", line):
            current.append(line.strip())
            continue
        if current is not None:
            items.append(" ".join(current))
            current = None
    if current is not None:
        items.append(" ".join(current))
    return items


def _review_section_source_bounds(markdown: str) -> list[tuple[int, int]]:
    return _section_bounds_all(markdown, "Code Review Rules")


def _check_review_rule_contract(markdown: str, errors: list[str]) -> None:
    sections = _review_section_source_bounds(markdown)
    review_headings = _matching_section_headings(markdown, "Code Review Rules")
    if len(sections) != 1 or len(review_headings) != 1:
        errors.append(
            "AGENTS.md Code Review Rules: expected one literal, top-level "
            "'## Code Review Rules' section, found "
            f"{len(review_headings)} matching top-level headings"
        )
    elif review_headings[0][1] != "## Code Review Rules":
        errors.append(
            "AGENTS.md Code Review Rules: the top-level heading must use the "
            "literal spelling '## Code Review Rules'"
        )

    for level, _title, heading_start, _end in _policy_atx_headings(markdown):
        if level != 3:
            continue
        if not any(start <= heading_start < end for start, end in sections):
            errors.append(
                "AGENTS.md: H3 headings are reserved for literal OBS rules inside "
                f"the Code Review Rules section: {_source_line(markdown, heading_start)!r}"
            )

    defined_rule_ids: list[str] = []
    for start, end in sections:
        section_text = markdown[start:end]
        structural_section = _mask_code_spans(section_text)
        if LINK_REFERENCE_BLOCK_RE.search(structural_section):
            errors.append(
                "AGENTS.md Code Review Rules: link-reference and table blocks "
                "are not allowed"
            )
        source_lines = _commonmark_lines(section_text)
        structural_lines = _commonmark_lines(structural_section)
        for raw_line, source_raw_line in zip(structural_lines, source_lines, strict=True):
            line = raw_line.rstrip("\r\n")
            source_line = source_raw_line.rstrip("\r\n")
            fence = FENCE_RE.match(line)
            if fence and _is_valid_fence_opener(fence):
                errors.append(
                    "AGENTS.md Code Review Rules: fenced blocks are not allowed; "
                    "keep rule definitions in literal top-level headings"
                )
                continue
            if SETEXT_UNDERLINE_RE.match(line) or THEMATIC_BREAK_RE.match(line):
                errors.append(
                    "AGENTS.md Code Review Rules: setext headings and thematic "
                    "breaks are not allowed"
                )
                continue
            if GFM_TABLE_DELIMITER_RE.match(line):
                errors.append(
                    "AGENTS.md Code Review Rules: link-reference and table blocks "
                    "are not allowed"
                )
                continue
            if CONTAINER_BLOCK_RE.match(line):
                errors.append(
                    "AGENTS.md Code Review Rules: block quotes and lists are not "
                    "allowed; keep rule definitions at the document root"
                )
                continue
            if not _is_markdown_blank(line) and INDENTED_CONTENT_RE.match(line):
                errors.append(
                    "AGENTS.md Code Review Rules: indented code blocks are not "
                    "allowed"
                )
                continue
            indented_heading = INDENTED_ATX_HEADING_RE.match(line)
            heading = ATX_HEADING_RE.match(line)
            if not indented_heading and not heading:
                continue
            if indented_heading:
                errors.append(
                    "AGENTS.md Code Review Rules: structural headings must start "
                    f"at column 1: {line!r}"
                )
                continue

            level = len(heading.group(1))
            exact = EXACT_RULE_HEADING_RE.fullmatch(source_line)
            if level != 3 or exact is None:
                errors.append(
                    "AGENTS.md Code Review Rules: every structural heading must "
                    f"match '### OBS-ID -- <plain title>': {source_line!r}"
                )
                continue

            title = exact.group("title").strip(" \t")
            if (
                not any(character.isascii() and character.isalnum() for character in title)
                or any(not 0x20 <= ord(character) <= 0x7E for character in title)
                or any(character in FORBIDDEN_RULE_TITLE_MARKUP for character in title)
            ):
                errors.append(
                    "AGENTS.md Code Review Rules: rule titles must contain plain, "
                    f"visible text without Markdown or HTML markup: {source_line!r}"
                )
                continue
            defined_rule_ids.append(exact.group("id"))

    unknown_rule_ids = set(defined_rule_ids) - set(REQUIRED_RULE_IDS)
    if unknown_rule_ids:
        errors.append(
            "AGENTS.md Code Review Rules: unknown exact rule headings: "
            + ", ".join(sorted(unknown_rule_ids))
        )
    for rule_id in REQUIRED_RULE_IDS:
        count = defined_rule_ids.count(rule_id)
        if count == 0:
            errors.append(
                "AGENTS.md Code Review Rules: missing exact rule heading "
                f"'### {rule_id} -- <plain title>'"
            )
        elif count > 1:
            errors.append(
                "AGENTS.md Code Review Rules: duplicate exact rule heading for "
                f"{rule_id}"
            )


def _canonical_skills(root: Path, errors: list[str]) -> set[str]:
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        errors.append("skills/: canonical skill directory is missing")
        return set()
    if skills_dir.is_symlink():
        errors.append("skills/: canonical skill root must not be a symbolic link")
        return set()

    names: set[str] = set()
    for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
        name = skill_file.parent.name
        names.add(name)
        skill_root = skill_file.parent
        resolved_skill_root = skill_root.resolve()
        if skill_root.is_symlink():
            errors.append(
                f"{skill_root.relative_to(root)}: canonical skill directory must not "
                "be a symbolic link"
            )
            continue
        unsafe_symlink = False
        for relative_path in _remaining_tree_paths(
            root, skill_root.relative_to(root), errors
        ):
            path = root / relative_path
            if not path.is_symlink():
                continue
            try:
                resolved = path.resolve(strict=True)
            except OSError as exc:
                errors.append(f"{path.relative_to(root)}: broken canonical symlink: {exc}")
                unsafe_symlink = True
                continue
            if not resolved.is_relative_to(resolved_skill_root):
                errors.append(
                    f"{path.relative_to(root)}: canonical skill symlink must stay "
                    f"inside {skill_root.relative_to(root)}"
                )
                unsafe_symlink = True
        if unsafe_symlink:
            continue
        text = _read(skill_file, errors)
        lines = _commonmark_lines(text)
        frontmatter_end: int | None = None
        if lines and lines[0].rstrip("\r\n") == "---":
            for index, raw_line in enumerate(lines[1:], start=1):
                if raw_line.rstrip("\r\n") == "---":
                    frontmatter_end = index
                    break
        frontmatter = "" if frontmatter_end is None else "".join(lines[1:frontmatter_end])
        frontmatter_names = re.findall(
            r"^name:[ \t]*([^\s]+)[ \t]*$", frontmatter, re.MULTILINE
        )
        if len(frontmatter_names) != 1:
            errors.append(
                f"{skill_file.relative_to(root)}: leading YAML frontmatter must "
                "contain exactly one name"
            )
        elif frontmatter_names[0] != name:
            errors.append(
                f"{skill_file.relative_to(root)}: frontmatter name "
                f"{frontmatter_names[0]!r} must match directory {name!r}"
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
    _check_policy_markdown_ambiguity(agents_text, errors)
    _check_nested_fences(agents_text, "AGENTS.md", errors)
    active_agents_text = _active_markdown(agents_text)
    for heading in PROTECTED_SECTION_TITLES:
        sections = _section_bounds_all(agents_text, heading)
        matching_headings = _matching_section_headings(agents_text, heading)
        if not sections:
            errors.append(f"AGENTS.md: missing required '## {heading}' section")
        elif len(sections) != 1 or len(matching_headings) != 1:
            errors.append(
                f"AGENTS.md: expected exactly one literal '## {heading}' section; "
                f"found {len(matching_headings)} matching top-level headings"
            )

    for reference in ("CONTRIBUTING.md", "skills/", ".agents/skills/"):
        if reference not in active_agents_text:
            errors.append(f"AGENTS.md: missing required reference to {reference}")

    routing = _section(active_agents_text, "Reviewer Routing") or ""
    literal_routing_directive = (
        "Apply this file and every more-specific instruction file that covers the\n"
        "changed path:"
    )
    if not routing.lstrip("\r\n").startswith(literal_routing_directive):
        errors.append(
            "AGENTS.md Reviewer Routing: missing the canonical positive routing "
            "directive"
        )
    for guide in ROUTED_AGENT_GUIDES:
        if not _routing_entry_is_canonical(routing, guide):
            errors.append(
                "AGENTS.md Reviewer Routing: expected exactly one canonical entry "
                f"for {guide}"
            )
        guide_path = root / guide
        if guide_path.is_symlink():
            errors.append(f"{guide}: policy entrypoint must not be a symbolic link")
            continue
        if not guide_path.is_file():
            errors.append(f"{guide}: routed instruction file is missing")
            continue
        guide_text = _read_policy_file(guide_path, root, errors)
        _check_nested_fences(guide_text, guide, errors)
        _check_active_raw_html(guide_text, guide, errors)
        if any(
            not _is_markdown_blank(raw.rstrip("\r\n"))
            and INDENTED_CONTENT_RE.match(raw.rstrip("\r\n"))
            for raw in _commonmark_lines(_mask_fenced_blocks(guide_text))
        ):
            errors.append(f"{guide}: indented code blocks are not supported")
        active_guide = _active_markdown(guide_text)
        guide_lines = _commonmark_lines(active_guide)
        first_index = next(
            (
                index
                for index, raw in enumerate(guide_lines)
                if not _is_markdown_blank(raw.rstrip("\r\n"))
            ),
            None,
        )
        expected_title = f"# {ROUTED_AGENT_GUIDE_TITLES[guide]}"
        first_line = (
            "" if first_index is None else guide_lines[first_index].rstrip("\r\n")
        )
        preamble_lines: list[str] = []
        if first_index is not None:
            for raw in guide_lines[first_index + 1 :]:
                line = raw.rstrip("\r\n")
                if not preamble_lines and _is_markdown_blank(line):
                    continue
                if _is_markdown_blank(line):
                    break
                preamble_lines.append(line)
        preamble = " ".join(" ".join(preamble_lines).split())
        if (
            first_line != expected_title
            or any(line.startswith((" ", "\t")) for line in preamble_lines)
            or not preamble.startswith(ROUTED_AGENT_GUIDE_PREAMBLES[guide])
        ):
            errors.append(
                f"{guide}: missing canonical positive parent-inheritance preamble"
            )
        normalized_guide_prose = " ".join(
            _mask_code_spans(active_guide).split()
        )
        if PARENT_INSTRUCTION_NEGATION_RE.search(normalized_guide_prose):
            errors.append(
                f"{guide}: active directives conflict with parent instructions"
            )

    _check_review_rule_contract(agents_text, errors)

    available = _section(active_agents_text, "Available Skills")
    if available is None:
        errors.append("AGENTS.md: missing required '## Available Skills' section")
    else:
        table_names = _available_skill_table_names(available, errors)
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
    adapter = _read_policy_file(adapter_path, root, errors)
    _check_nested_fences(adapter, adapter_path.as_posix(), errors)
    _check_active_raw_html(adapter, adapter_path.as_posix(), errors)
    if any(
        not _is_markdown_blank(raw_line.rstrip("\r\n"))
        and INDENTED_CONTENT_RE.match(raw_line.rstrip("\r\n"))
        for raw_line in _commonmark_lines(_mask_fenced_blocks(adapter))
    ):
        errors.append(
            ".github/copilot-instructions.md: indented code blocks are not "
            "supported in the routing adapter"
        )
    if not adapter.strip():
        errors.append(
            ".github/copilot-instructions.md: missing active Copilot routing directives"
        )
    else:
        normalized_adapter = " ".join(adapter.split())
        expected_adapter = " ".join(COPILOT_ADAPTER_CONTRACT.split())
        if normalized_adapter != expected_adapter:
            errors.append(
                ".github/copilot-instructions.md: active content must match the "
                "canonical positive routing adapter"
            )


def _check_pr_template(root: Path, errors: list[str]) -> None:
    path = root / ".github" / "PULL_REQUEST_TEMPLATE.md"
    template = _read_policy_file(path, root, errors)
    _check_nested_fences(template, path.as_posix(), errors)
    _check_active_raw_html(template, path.as_posix(), errors)
    active_template = _active_markdown(template)
    normalized_h2_titles: list[str] = []
    for level, title, start, _end in _policy_atx_headings(active_template):
        source = _source_line(active_template, start).rstrip(" \t")
        literal_heading = re.compile(
            rf"^{'#' * level} [A-Za-z0-9][A-Za-z0-9 ]*$"
        )
        if literal_heading.fullmatch(source) is None:
            errors.append(
                ".github/PULL_REQUEST_TEMPLATE.md: headings must be literal "
                f"plain text: {source!r}"
            )
        if level != 2:
            continue
        normalized_h2_titles.append(_normalized_section_title(title))
    for title in set(normalized_h2_titles):
        if normalized_h2_titles.count(title) > 1:
            errors.append(
                ".github/PULL_REQUEST_TEMPLATE.md: H2 headings must be unique; "
                f"found duplicate {title!r}"
            )
    sections_by_title: dict[str, str] = {}
    for heading in ("Summary", "Scope", "Validation evidence", "Risk and review"):
        sections = _section_bounds_all(active_template, heading)
        matching_headings = _matching_section_headings(active_template, heading)
        if not sections:
            errors.append(f".github/PULL_REQUEST_TEMPLATE.md: missing '## {heading}'")
        elif len(sections) != 1 or len(matching_headings) != 1:
            errors.append(
                ".github/PULL_REQUEST_TEMPLATE.md: expected exactly one literal "
                f"'## {heading}' heading"
            )
        if len(sections) == 1:
            sections_by_title[heading] = active_template[sections[0][0] : sections[0][1]]
    for section_title, fields in PR_TEMPLATE_REQUIRED_FIELDS.items():
        list_items = [
            " ".join(item.split()).casefold()
            for item in _top_level_list_items(sections_by_title.get(section_title, ""))
        ]
        for evidence in fields:
            count = list_items.count(" ".join(evidence.split()).casefold())
            if count == 0:
                errors.append(
                    ".github/PULL_REQUEST_TEMPLATE.md: missing evidence field "
                    f"{evidence!r} from '## {section_title}'"
                )
            elif count > 1:
                errors.append(
                    f".github/PULL_REQUEST_TEMPLATE.md: duplicate evidence field {evidence!r}"
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


def _default_base_ref(root: Path) -> str | None:
    candidates: list[str] = []
    try:
        symbolic = subprocess.run(
            ["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if symbolic.returncode == 0 and symbolic.stdout.strip():
        candidates.append(symbolic.stdout.strip())
    candidates.extend(("origin/main", "origin/master", "main", "master"))
    for candidate in candidates:
        resolved = subprocess.run(
            ["git", "rev-parse", "--verify", f"{candidate}^{{commit}}"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if resolved.returncode == 0:
            return candidate
    return None


def _repo_path(raw_path: str, errors: list[str]) -> Path | None:
    path = Path(raw_path)
    if path.is_absolute() or ".." in path.parts:
        errors.append(f"git diff path escapes repository: {raw_path!r}")
        return None
    return path


def _git_changed_files(
    root: Path, base_ref: str, errors: list[str]
) -> tuple[list[tuple[str, Path]], str | None]:
    if base_ref.startswith("-") or re.fullmatch(r"[A-Za-z0-9._/@{}^~:+-]+", base_ref) is None:
        errors.append(f"invalid agent-policy base ref: {base_ref!r}")
        return [], None

    try:
        merge_base = subprocess.run(
            ["git", "merge-base", base_ref, "HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        errors.append(f"cannot resolve agent-policy base {base_ref!r}: {exc}")
        return [], None
    if merge_base.returncode != 0 or not merge_base.stdout.strip():
        detail = merge_base.stderr.strip() or merge_base.stdout.strip() or "git merge-base failed"
        errors.append(f"cannot resolve agent-policy base {base_ref!r}: {detail}")
        return [], None
    base_tree = merge_base.stdout.strip()

    try:
        completed = subprocess.run(
            ["git", "diff", "--name-status", "-z", "--find-renames", base_tree, "--"],
            cwd=root,
            check=False,
            capture_output=True,
            timeout=30,
        )
        untracked = subprocess.run(
            ["git", "ls-files", "-z", "--others", "--exclude-standard", "--"],
            cwd=root,
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        errors.append(f"cannot inspect changed files from {base_ref!r}: {exc}")
        return [], base_tree
    if completed.returncode != 0:
        detail = (
            completed.stderr.decode("utf-8", "replace").strip()
            or completed.stdout.decode("utf-8", "replace").strip()
            or "git diff failed"
        )
        errors.append(f"cannot inspect changed files from {base_ref!r}: {detail}")
        return [], base_tree
    if untracked.returncode != 0:
        detail = (
            untracked.stderr.decode("utf-8", "replace").strip()
            or untracked.stdout.decode("utf-8", "replace").strip()
            or "git ls-files failed"
        )
        errors.append(f"cannot inspect untracked files: {detail}")
        return [], base_tree

    changes: list[tuple[str, Path]] = []
    seen: set[tuple[str, Path]] = set()

    def add(status: str, raw_path: str) -> None:
        path = _repo_path(raw_path, errors)
        item = (status, path) if path is not None else None
        if item is not None and item not in seen:
            seen.add(item)
            changes.append(item)

    def nul_fields(output: bytes, source: str) -> list[bytes]:
        if not output:
            return []
        if not output.endswith(b"\0"):
            errors.append(f"cannot parse {source}: missing NUL terminator")
            return []
        return output[:-1].split(b"\0")

    diff_fields = nul_fields(completed.stdout, "git diff output")
    index = 0
    while index < len(diff_fields):
        status = os.fsdecode(diff_fields[index])
        index += 1
        path_count = 2 if status.startswith(("R", "C")) else 1
        if index + path_count > len(diff_fields):
            errors.append(f"cannot parse git diff entry for status {status!r}")
            break
        paths = [os.fsdecode(value) for value in diff_fields[index : index + path_count]]
        index += path_count
        if status.startswith("R"):
            add("D", paths[0])
            add("A", paths[1])
        elif status.startswith("C"):
            add("A", paths[1])
        else:
            add(status, paths[0])

    for raw_path in nul_fields(untracked.stdout, "git ls-files output"):
        add("A", os.fsdecode(raw_path))
    return changes, base_tree


def _git_file_text(root: Path, tree: str, path: Path) -> str | None:
    completed = subprocess.run(
        ["git", "show", f"{tree}:{path.as_posix()}"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.stdout if completed.returncode == 0 else None


def _parse_shared_consumer_map(
    text: str,
    source: str,
    errors: list[str],
    canonical: set[str] | None = None,
) -> dict[str, set[str]]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        errors.append(f"{source}: invalid JSON: {exc}")
        return {}
    if not isinstance(raw, dict):
        errors.append(f"{source}: expected an object mapping shared files to skills")
        return {}

    mapping: dict[str, set[str]] = {}
    for reference, consumers in raw.items():
        if not isinstance(reference, str) or not reference or Path(reference).is_absolute():
            errors.append(f"{source}: invalid shared reference key {reference!r}")
            continue
        if ".." in Path(reference).parts:
            errors.append(f"{source}: shared reference key escapes its directory: {reference!r}")
            continue
        if not isinstance(consumers, list) or not consumers:
            errors.append(f"{source}: {reference!r} must name at least one consuming skill")
            continue
        if not all(isinstance(item, str) and item for item in consumers):
            errors.append(f"{source}: {reference!r} has an invalid consumer list")
            continue
        consumer_set = set(consumers)
        if len(consumer_set) != len(consumers):
            errors.append(f"{source}: {reference!r} repeats a consuming skill")
        if canonical is not None:
            unknown = consumer_set - canonical
            if unknown:
                errors.append(
                    f"{source}: {reference!r} names unknown skills: "
                    + ", ".join(sorted(unknown))
                )
        mapping[reference] = consumer_set
    return mapping


def _load_shared_consumers(
    root: Path, errors: list[str], canonical: set[str] | None = None
) -> dict[str, set[str]]:
    return _parse_shared_consumer_map(
        _read(root / SHARED_CONSUMER_MAP, errors),
        SHARED_CONSUMER_MAP.as_posix(),
        errors,
        canonical,
    )


def _shared_consumers_at_ref(
    root: Path, tree: str | None, errors: list[str]
) -> dict[str, set[str]]:
    if tree is None:
        return {}
    text = _git_file_text(root, tree, SHARED_CONSUMER_MAP)
    if text is None:
        return {}
    return _parse_shared_consumer_map(
        text,
        f"{SHARED_CONSUMER_MAP.as_posix()} at {tree}",
        errors,
    )


def _contains_reference_name(content: str, name: str) -> bool:
    return (
        re.search(
            rf"(?<![A-Za-z0-9_.-]){re.escape(name)}"
            r"(?![A-Za-z0-9_-])(?!\.[A-Za-z0-9_-])",
            content,
        )
        is not None
    )


def _check_shared_reference_consumers(
    root: Path, canonical: set[str], errors: list[str]
) -> dict[str, set[str]]:
    shared_root = root / "skills" / "references"
    if shared_root.is_symlink():
        errors.append(
            f"{shared_root.relative_to(root)}: shared reference root must not be a "
            "symbolic link"
        )
        return {}
    if not shared_root.is_dir():
        errors.append(f"{shared_root.relative_to(root)}: shared reference root is missing")
        return {}
    mapping = _load_shared_consumers(root, errors, canonical)
    resolved_shared_root = shared_root.resolve()
    shared_paths: dict[str, Path] = {}
    for path in shared_root.rglob("*"):
        if path.is_symlink():
            try:
                resolved = path.resolve(strict=True)
            except OSError as exc:
                errors.append(f"{path.relative_to(root)}: broken shared symlink: {exc}")
                continue
            if not resolved.is_relative_to(resolved_shared_root):
                errors.append(
                    f"{path.relative_to(root)}: shared reference symlink must stay "
                    f"inside {shared_root.relative_to(root)}"
                )
                continue
        if not path.is_file():
            continue
        relative = path.relative_to(shared_root)
        if (
            relative.as_posix() == "consumers.json"
            or "tests" in relative.parts
            or "__pycache__" in relative.parts
        ):
            continue
        shared_paths[relative.as_posix()] = path
    expected = set(shared_paths)
    missing = expected - set(mapping)
    extra = set(mapping) - expected
    if missing:
        errors.append(
            f"{SHARED_CONSUMER_MAP}: missing shared references: "
            + ", ".join(sorted(missing))
        )
    if extra:
        errors.append(
            f"{SHARED_CONSUMER_MAP}: unknown shared references: "
            + ", ".join(sorted(extra))
        )

    references_by_name: dict[str, list[str]] = {}
    for reference in expected:
        references_by_name.setdefault(Path(reference).name, []).append(reference)
    unique_references_by_name: dict[str, str] = {}
    for name, references in sorted(references_by_name.items()):
        if len(references) > 1:
            errors.append(
                f"{SHARED_CONSUMER_MAP}: shared filename {name!r} is ambiguous across: "
                + ", ".join(sorted(references))
            )
        else:
            unique_references_by_name[name] = references[0]

    direct_consumers = {reference: set() for reference in expected}
    for consumer in sorted(canonical):
        consumer_root = root / "skills" / consumer
        for path in consumer_root.rglob("*"):
            relative = path.relative_to(consumer_root)
            if (
                not path.is_file()
                or "tests" in relative.parts
                or "__pycache__" in relative.parts
            ):
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            for marker, reference in unique_references_by_name.items():
                if _contains_reference_name(content, marker):
                    direct_consumers[reference].add(consumer)

    dependencies = {reference: set() for reference in expected}
    for source, path in shared_paths.items():
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for marker, target in unique_references_by_name.items():
            if target != source and _contains_reference_name(content, marker):
                dependencies[source].add(target)

    effective_consumers = {
        reference: set(consumers) for reference, consumers in direct_consumers.items()
    }
    changed = True
    while changed:
        changed = False
        for source, targets in dependencies.items():
            for target in targets:
                added = effective_consumers[source] - effective_consumers[target]
                if added:
                    effective_consumers[target].update(added)
                    changed = True

    for reference, consumers in mapping.items():
        discovered = effective_consumers.get(reference, set())
        omitted = discovered - consumers
        stale = consumers - discovered
        if omitted:
            errors.append(
                f"{SHARED_CONSUMER_MAP}: {reference!r} omits consuming skills: "
                + ", ".join(sorted(omitted))
            )
        if stale:
            errors.append(
                f"{SHARED_CONSUMER_MAP}: {reference!r} names skills that do not reference it: "
                + ", ".join(sorted(stale))
            )
    return mapping


def _eval_definition_case(
    path: Path, directory_names: set[str]
) -> str | None:
    parts = path.parts
    if (
        len(parts) != 6
        or path.suffix != ".json"
        or parts[0] != "evals"
        or parts[3] != "eval"
        or parts[4] not in directory_names
    ):
        return None
    return f"{parts[1]}/{parts[2]}"


def _json_equivalent(left: object, right: object) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        if not isinstance(right, dict):
            return False
        return left.keys() == right.keys() and all(
            _json_equivalent(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        if not isinstance(right, list):
            return False
        return len(left) == len(right) and all(
            _json_equivalent(left_item, right_item)
            for left_item, right_item in zip(left, right)
        )
    return left == right


def _json_sort_key(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _effective_rubric_definition(
    definition: object, path: Path, path_case: str
) -> tuple[object, str]:
    if not isinstance(definition, dict):
        return definition, path_case

    normalized = dict(definition)
    normalized.pop("id", None)
    normalized["language"] = path.parts[1]
    normalized["service"] = path.parts[2]
    normalized.setdefault("judge_prompt", None)
    if not normalized.get("judge_inputs"):
        normalized["judge_inputs"] = []

    prompts = normalized.get("prompts")
    if isinstance(prompts, list):
        normalized_prompts: list[object] = []
        for prompt in prompts:
            if not isinstance(prompt, dict):
                normalized_prompts.append(prompt)
                continue
            normalized_prompt = dict(prompt)
            normalized_prompt.pop("id", None)
            if not normalized_prompt.get("eval_inputs"):
                normalized_prompt["eval_inputs"] = []
            elif isinstance(normalized_prompt["eval_inputs"], list):
                normalized_prompt["eval_inputs"] = sorted(
                    normalized_prompt["eval_inputs"],
                    key=_json_sort_key,
                )
            normalized_prompts.append(normalized_prompt)
        normalized["prompts"] = sorted(
            normalized_prompts,
            key=_json_sort_key,
        )

    return normalized, path_case


def _git_tree_paths(
    root: Path, tree: str, prefix: Path, errors: list[str]
) -> list[Path] | None:
    try:
        completed = subprocess.run(
            [
                "git",
                "ls-tree",
                "-r",
                "-z",
                "--name-only",
                tree,
                "--",
                prefix.as_posix(),
            ],
            cwd=root,
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        errors.append(f"cannot inspect {prefix} at base tree {tree}: {exc}")
        return None
    if completed.returncode != 0:
        detail = (
            completed.stderr.decode("utf-8", "replace").strip()
            or completed.stdout.decode("utf-8", "replace").strip()
            or "git ls-tree failed"
        )
        errors.append(f"cannot inspect {prefix} at base tree {tree}: {detail}")
        return None
    if completed.stdout and not completed.stdout.endswith(b"\0"):
        errors.append(
            f"cannot inspect {prefix} at base tree {tree}: missing NUL terminator"
        )
        return None

    paths: list[Path] = []
    for raw_path in completed.stdout.rstrip(b"\0").split(b"\0"):
        if not raw_path:
            continue
        path = _repo_path(os.fsdecode(raw_path), errors)
        if path is not None:
            paths.append(path)
    return paths


def _base_rubric_definitions(
    root: Path, base_tree: str, errors: list[str]
) -> dict[str, list[object]] | None:
    paths = _git_tree_paths(root, base_tree, Path("evals"), errors)
    if paths is None:
        return None

    definitions: dict[str, list[object]] = {}
    for path in paths:
        path_case = _eval_definition_case(path, RUBRIC_DIRECTORY_NAMES)
        if path_case is None:
            continue
        text = _git_file_text(root, base_tree, path)
        if text is None:
            errors.append(f"cannot read {path} at base tree {base_tree}")
            return None
        try:
            definition = json.loads(text)
        except json.JSONDecodeError as exc:
            errors.append(f"{path} at base tree {base_tree}: invalid JSON: {exc}")
            return None
        definition, case = _effective_rubric_definition(
            definition, path, path_case
        )
        definitions.setdefault(case, []).append(definition)
    return definitions


def _changed_rubric_evals(
    root: Path,
    changes: list[tuple[str, Path]],
    errors: list[str],
    base_tree: str | None = None,
) -> tuple[
    dict[str, list[tuple[Path, str]]],
    dict[str, list[tuple[Path, str]]],
]:
    by_skill: dict[str, list[tuple[Path, str]]] = {}
    candidates: list[tuple[Path, str, str, object]] = []
    for status, path in changes:
        path_case = _eval_definition_case(path, RUBRIC_DIRECTORY_NAMES)
        if path_case is None:
            continue
        if status.startswith("D"):
            continue
        text = _read(root / path, errors)
        try:
            definition = json.loads(text)
        except json.JSONDecodeError as exc:
            errors.append(f"{path}: changed rubric eval is invalid JSON: {exc}")
            continue
        skill = definition.get("skill") if isinstance(definition, dict) else None
        if not isinstance(skill, str) or not skill.strip():
            errors.append(f"{path}: changed rubric eval must have a non-empty top-level skill")
            continue
        definition, case = _effective_rubric_definition(
            definition, path, path_case
        )
        candidates.append((path, case, skill, definition))

    base_definitions: dict[str, list[object]] = {}
    if candidates and base_tree is not None:
        loaded = _base_rubric_definitions(root, base_tree, errors)
        if loaded is None:
            return {}, {}
        base_definitions = loaded

    unchanged_by_skill: dict[str, list[tuple[Path, str]]] = {}
    for path, case, skill, definition in candidates:
        if base_tree is not None and any(
            _json_equivalent(definition, base_definition)
            for base_definition in base_definitions.get(case, [])
        ):
            unchanged_by_skill.setdefault(skill, []).append((path, case))
            continue
        by_skill.setdefault(skill, []).append((path, case))
    return by_skill, unchanged_by_skill


def _physical_tree_paths(root: Path, relative_root: Path) -> list[Path]:
    tree_root = root / relative_root
    if tree_root.is_file() or tree_root.is_symlink():
        return [tree_root.relative_to(root)]
    if not tree_root.exists():
        return []
    return sorted(
        path.relative_to(root)
        for path in tree_root.rglob("*")
        if path.is_file() or path.is_symlink()
    )


def _remaining_tree_paths(
    root: Path, relative_root: Path, errors: list[str]
) -> list[Path]:
    if not (root / ".git").exists():
        return _physical_tree_paths(root, relative_root)
    try:
        completed = subprocess.run(
            [
                "git",
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                relative_root.as_posix(),
            ],
            cwd=root,
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        errors.append(f"cannot inspect remaining paths under {relative_root}: {exc}")
        return _physical_tree_paths(root, relative_root)
    if completed.returncode != 0:
        detail = (
            completed.stderr.decode("utf-8", "replace").strip()
            or completed.stdout.decode("utf-8", "replace").strip()
            or "git ls-files failed"
        )
        errors.append(f"cannot inspect remaining paths under {relative_root}: {detail}")
        return _physical_tree_paths(root, relative_root)
    if completed.stdout and not completed.stdout.endswith(b"\0"):
        errors.append(
            f"cannot inspect remaining paths under {relative_root}: "
            "missing NUL terminator"
        )
        return _physical_tree_paths(root, relative_root)

    paths: list[Path] = []
    for raw_path in completed.stdout.rstrip(b"\0").split(b"\0"):
        if not raw_path:
            continue
        path = _repo_path(os.fsdecode(raw_path), errors)
        if path is None:
            continue
        absolute_path = root / path
        if absolute_path.exists() or absolute_path.is_symlink():
            paths.append(path)
    return sorted(set(paths))


def _current_eval_definitions_for_skills(
    root: Path, skills: set[str], errors: list[str]
) -> dict[str, list[Path]]:
    by_skill = {skill: [] for skill in skills}
    if not skills:
        return by_skill
    for relative_path in _remaining_tree_paths(root, Path("evals"), errors):
        if (
            _eval_definition_case(relative_path, EVAL_DEFINITION_DIRECTORY_NAMES)
            is None
        ):
            continue
        text = _read(root / relative_path, errors)
        try:
            definition = json.loads(text)
        except json.JSONDecodeError as exc:
            errors.append(
                f"{relative_path}: cannot validate removed skill eval cleanup: {exc}"
            )
            continue
        skill = definition.get("skill") if isinstance(definition, dict) else None
        if skill in by_skill:
            by_skill[skill].append(relative_path)
    return by_skill


def _missing_rubric_message(
    skill: str,
    unchanged_rubrics: dict[str, list[tuple[Path, str]]],
) -> str:
    unchanged = unchanged_rubrics.get(skill, [])
    if unchanged:
        paths = ", ".join(str(path) for path, _case in unchanged)
        return (
            f"skills/{skill}/: shipped skill content changed, but its matching rubric "
            f"changes are effectively equivalent to the base tree after normalizing "
            f"identity and default metadata ({paths}); semantically update a rubric eval "
            "that exercises the changed behavior and run "
            f"make eval-rubric SKILL=skills/{skill} CASE=<language>/<service>"
        )
    return (
        f"skills/{skill}/: shipped skill content changed without a changed matching "
        "rubric eval under evals/<language>/<service>/eval/qual/ (or "
        f"eval/rubric/) with skill={skill!r}; add or update one and run "
        f"make eval-rubric SKILL=skills/{skill} CASE=<language>/<service>"
    )


def _check_skill_eval_diff(
    root: Path,
    changes: list[tuple[str, Path]],
    errors: list[str],
    shared_consumers: dict[str, set[str]] | None = None,
    base_shared_consumers: dict[str, set[str]] | None = None,
    base_tree: str | None = None,
) -> None:
    changed_skills: set[str] = set()
    deleted_skill_manifests: set[str] = set()
    changed_shared_references: set[str] = set()
    for status, path in changes:
        parts = path.parts
        if len(parts) < 3 or parts[0] != "skills":
            continue
        if "tests" in parts[2:] or "__pycache__" in parts[2:]:
            continue
        if parts[1] == "references":
            reference = Path(*parts[2:]).as_posix()
            if reference != "consumers.json":
                changed_shared_references.add(reference)
            continue
        changed_skills.add(parts[1])
        if (
            status.startswith("D")
            and len(parts) == 3
            and parts[2] == "SKILL.md"
        ):
            deleted_skill_manifests.add(parts[1])

    removed_skills = {
        skill
        for skill in deleted_skill_manifests
        if not (root / "skills" / skill / "SKILL.md").is_file()
    }
    removed_eval_definitions = _current_eval_definitions_for_skills(
        root, removed_skills, errors
    )
    for skill in sorted(removed_skills):
        remaining_paths = _remaining_tree_paths(
            root, Path("skills") / skill, errors
        )
        if remaining_paths:
            errors.append(
                f"skills/{skill}/: complete skill removal leaves repository-visible "
                "canonical files: "
                + ", ".join(str(path) for path in remaining_paths)
            )
        remaining_reports = _remaining_tree_paths(
            root, Path("eval-reports") / skill, errors
        )
        if remaining_reports:
            errors.append(
                f"skills/{skill}/: complete skill removal leaves tracked latest eval "
                "reports: " + ", ".join(str(path) for path in remaining_reports)
            )
        stale_evals = removed_eval_definitions.get(skill, [])
        if stale_evals:
            errors.append(
                f"skills/{skill}/: complete skill removal leaves eval definitions naming "
                f"the removed skill: {', '.join(str(path) for path in stale_evals)}; "
                "delete them or migrate their top-level skill field"
            )

    changed_rubrics, unchanged_rubrics = _changed_rubric_evals(
        root, changes, errors, base_tree
    )
    for skill in sorted(changed_skills):
        if skill in removed_skills or skill in changed_rubrics:
            continue
        errors.append(_missing_rubric_message(skill, unchanged_rubrics))

    if shared_consumers is None:
        shared_consumers = _load_shared_consumers(root, errors)
    if base_shared_consumers is None:
        base_shared_consumers = {}
    for reference in sorted(changed_shared_references):
        consumers = set(shared_consumers.get(reference, set()))
        consumers.update(base_shared_consumers.get(reference, set()))
        if not consumers:
            errors.append(
                f"skills/references/{reference}: no affected skills are declared in "
                f"{SHARED_CONSUMER_MAP} in the current or base tree"
            )
            continue
        for skill in sorted(consumers):
            if skill in removed_skills or skill in changed_rubrics:
                continue
            unchanged = unchanged_rubrics.get(skill, [])
            if unchanged:
                paths = ", ".join(str(path) for path, _case in unchanged)
                errors.append(
                    f"skills/references/{reference}: affected skill {skill!r} has only "
                    f"effectively equivalent matching rubric changes after normalizing "
                    f"identity and default metadata ({paths}); semantically update its "
                    "eval and run "
                    f"make eval-rubric SKILL=skills/{skill} CASE=<language>/<service>"
                )
                continue
            errors.append(
                f"skills/references/{reference}: affected skill {skill!r} has no changed "
                "matching rubric eval; update its eval and run "
                f"make eval-rubric SKILL=skills/{skill} CASE=<language>/<service>"
            )


def _markdown_snippets(text: str) -> list[tuple[int, str]]:
    snippets: list[tuple[int, str]] = []
    fence: tuple[str, int] | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        marker = re.match(r"^[ ]{0,3}(`{3,}|~{3,})(.*)$", line)
        if fence is not None:
            if marker:
                token, suffix = marker.groups()
                if (
                    token[0] == fence[0]
                    and len(token) >= fence[1]
                    and _is_markdown_blank(suffix)
                ):
                    fence = None
                    continue
            snippets.append((line_number, line))
            continue

        if marker and _is_valid_fence_opener(marker):
            token = marker.group(1)
            fence = (token[0], len(token))
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


def check_repository(root: Path, base_ref: str | None = None) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    agents_path = root / "AGENTS.md"
    contributing_path = root / "CONTRIBUTING.md"
    agents_text = _read_policy_file(agents_path, root, errors)
    contributing_text = _read_policy_file(contributing_path, root, errors)

    canonical = _canonical_skills(root, errors)
    _check_skill_discovery(root, canonical, errors)
    shared_consumers = _check_shared_reference_consumers(root, canonical, errors)
    _check_instruction_structure(root, agents_text, canonical, errors)
    _check_cross_document_claims(agents_text, contributing_text, errors)
    _check_pr_template(root, errors)
    if base_ref:
        changes, base_tree = _git_changed_files(root, base_ref, errors)
        if changes:
            base_shared_consumers = _shared_consumers_at_ref(root, base_tree, errors)
            _check_skill_eval_diff(
                root,
                changes,
                errors,
                shared_consumers=shared_consumers,
                base_shared_consumers=base_shared_consumers,
                base_tree=base_tree,
            )
    policy_documents = tuple(
        path
        for path in (
            agents_path,
            contributing_path,
            *(root / guide for guide in ROUTED_AGENT_GUIDES),
        )
        if not path.is_symlink()
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
    parser.add_argument(
        "--base-ref",
        default=os.environ.get("AGENT_POLICY_BASE"),
        help=(
            "git base ref used to enforce changed skill/rubric pairing "
            "(defaults to AGENT_POLICY_BASE, then the repository default branch)"
        ),
    )
    args = parser.parse_args(argv)
    base_ref = args.base_ref
    if base_ref and re.fullmatch(r"0+", base_ref):
        base_ref = None
    if not base_ref:
        base_ref = _default_base_ref(args.root.resolve())
    if not base_ref:
        print(
            "Agent policy check failed:\n"
            "  - cannot determine a git base ref; pass --base-ref or set "
            "AGENT_POLICY_BASE",
            file=sys.stderr,
        )
        return 1
    errors = check_repository(args.root, base_ref)
    if errors:
        print("Agent policy check failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("Agent policy check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
