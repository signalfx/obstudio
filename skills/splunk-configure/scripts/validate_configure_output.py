#!/usr/bin/env python3
"""Validate generated Splunk detector Terraform against verified metrics."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


RESOURCE_START = re.compile(r'resource\s+"signalfx_detector"\s+"([^"]+)"\s*\{')
VARIABLE_DECLARATION = re.compile(r'variable\s+"([^"]+)"\s*\{')
VARIABLE_REFERENCE = re.compile(r"\bvar\.([A-Za-z_][A-Za-z0-9_]*)")
PROGRAM_TEXT_HEREDOC = re.compile(r'\bprogram_text\s*=\s*<<(-)?\s*"?([A-Za-z_][A-Za-z0-9_]*)"?[ \t]*\n')
PROGRAM_TEXT_STRING = re.compile(r'\bprogram_text\s*=\s*"((?:\\.|[^"\\])*)"')
DECOY_FIELD = re.compile(r'\b(?:name|description)\s*=\s*"((?:\\.|[^"\\])*)"')
DATA_CALL = re.compile(r"\bdata\(")
DATA_METRIC = re.compile(r"\bdata\(\s*['\"]([^'\"]+)['\"]")
AGG_METHOD_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
DETECT_LABEL = re.compile(r'detect_label\s*=\s*"([^"]+)"')
BACKTICK = re.compile(r"`([^`]+)`")
PROVIDER_START = re.compile(r'provider\s+"signalfx"\s*\{')
REPORT_STATUS = re.compile(r"^\*\*Result:\*\*\s*(Pass|Partial|Fail|Blocked)\s*$", re.I | re.M)
CONFIGURE_VERIFY_HEADINGS = (
    "Executive Summary",
    "What Was Added",
    "Tested And Working",
    "Not Yet Proven",
    "Validation Notes",
    "Next Steps",
)
FORBIDDEN_PROGRAM_PATTERNS = {
    "raw prompt/content": re.compile(r"\b(raw[._ -]?(?:prompt|content|completion)|prompt[._ -]?text)\b", re.I),
    "request identity": re.compile(r"\b(?:request|session|user|tenant|org|trace)[._-]?(?:id|identifier)\b", re.I),
}


def markdown_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def working_metrics(report: Path) -> set[str]:
    if not report.exists():
        return set()
    lines = report.read_text(encoding="utf-8").splitlines()
    in_section = False
    header: list[str] | None = None
    metrics: set[str] = set()
    for line in lines:
        if line.startswith("## "):
            in_section = line.strip() == "## Tested And Working"
            header = None
            continue
        if not in_section or not line.lstrip().startswith("|"):
            continue
        cells = markdown_cells(line)
        if header is None and "OTel item" in cells and "Working status" in cells:
            header = cells
            continue
        if header is None or set(cells) <= {"---", "--"} or len(cells) != len(header):
            continue
        # Column counts are checked above; avoid Python 3.10-only zip(strict=...).
        row = dict(zip(header, cells))
        if row.get("Working status") != "Working" or not re.match(
            r"^metric\b", row.get("Type", ""), re.I
        ):
            continue
        item = row["OTel item"]
        tokens = BACKTICK.findall(item)
        metrics.add(tokens[0] if tokens else item.strip())
    return metrics


def matching_brace(text: str, opening: int) -> int:
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(opening, len(text)):
        char = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError("unbalanced detector resource block")


def matching_paren(text: str, opening: int) -> int:
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(opening, len(text)):
        char = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError("unbalanced data(...) call")


def _blank_comment_lines(text: str) -> str:
    """Return text with every `#` line comment, `//` line comment, and
    `/* ... */` block comment -- whether it starts the line or trails real
    code -- replaced by spaces (newlines inside a block comment are kept so
    line numbers do not shift), so a decoy `data(...)` or `resource` block
    mentioned in a comment can never be matched instead of real HCL/SignalFlow
    syntax. A comment marker inside a quoted string is left untouched since it
    is not a comment marker there. Every other character keeps its original
    index for slicing the block."""
    chars = list(text)
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(chars):
        char = chars[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in {'"', "'"}:
            quote = char
            index += 1
            continue
        if char == "#" or (char == "/" and chars[index + 1 : index + 2] == ["/"]):
            while index < len(chars) and chars[index] not in "\r\n":
                chars[index] = " "
                index += 1
            continue
        if char == "/" and chars[index + 1 : index + 2] == ["*"]:
            chars[index] = " "
            chars[index + 1] = " "
            index += 2
            while index < len(chars) and chars[index : index + 2] != ["*", "/"]:
                if chars[index] not in "\r\n":
                    chars[index] = " "
                index += 1
            if index < len(chars):
                chars[index] = " "
                chars[index + 1] = " "
                index += 2
            continue
        index += 1
    return "".join(chars)


def _blank_decoy_fields(searchable: str) -> str:
    """Return searchable (already comment-blanked) with the quoted value of
    every `name = "..."` / `description = "..."` field -- wherever it
    appears in the block, including a `description` inside `rule { ... }` --
    replaced by spaces, so a `var.foo` or `detect_label = "..."`-shaped decoy
    string placed in one of those free-text fields is never mistaken for a
    real variable reference or detect label. This does not narrow the scope
    of legitimate `var.foo` references or the real `detect_label` field
    itself, since neither of those is named `name` or `description`."""
    chars = list(searchable)
    for match in DECOY_FIELD.finditer(searchable):
        start, end = match.span(1)
        for index in range(start, end):
            chars[index] = " "
    return "".join(chars)


def _blank_quoted_content(text: str) -> str:
    """Return text with the interior of every quoted string blanked (the
    quote characters themselves are left in place), so a decoy `data(` or
    `filter(` marker that only appears inside a string literal -- for
    example a `.publish("replaces data('legacy.metric')")` label -- can
    never be mistaken by a caller scanning the result for real SignalFlow
    syntax markers. Every other character, including newlines inside the
    string, keeps its original index so positions found in this view still
    locate the real markers in the unblanked text."""
    chars = list(text)
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(chars):
        char = chars[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            elif char not in "\r\n":
                chars[index] = " "
            index += 1
            continue
        if char in {'"', "'"}:
            quote = char
        index += 1
    return "".join(chars)


def _iter_data_call_spans(searchable: str) -> list[tuple[int, int, int]]:
    """Return (start, opening, close) for every top-level `data(...)` call in
    searchable, in source order. Call markers are located in a
    quote-blanked view of searchable, so a decoy `data(`-shaped marker
    inside a string literal (e.g. a `.publish(...)` label) is never found as
    a call; each call's own closing paren is then found against the real,
    unblanked searchable text using the existing quote-aware
    `matching_paren`, so nested strings inside the call's own arguments
    (which may themselves contain parens) are handled correctly. Raises
    ValueError, via `matching_paren`, if a real call's parentheses are
    unbalanced."""
    masked = _blank_quoted_content(searchable)
    spans: list[tuple[int, int, int]] = []
    for match in DATA_CALL.finditer(masked):
        opening = match.end() - 1
        close = matching_paren(searchable, opening)
        spans.append((match.start(), opening, close))
    return spans


def program_text_body(block: str, searchable: str | None = None) -> str:
    """Return the `program_text` value of a signalfx_detector resource block
    -- the heredoc body of a `<<EOF ... EOF`/`<<-EOF ... EOF` heredoc, or the
    decoded value of a plain quoted string -- with the resource header and
    any other HCL fields (`name`, `description`, `rule { ... }`) stripped
    away, so metric/filter/label discovery scoped to this body can never
    mistake a `data(...)`- or `publish(...)`-shaped string inside an
    unrelated quoted HCL value for real SignalFlow syntax. `searchable` lets
    a caller that already has the comment-blanked view of `block` pass it in
    instead of paying for `_blank_comment_lines` again. Falls back to the
    full block only when no `program_text` field is found at all, so the
    caller still gets a normal validation error (no data(...) call found)
    rather than silently skipping the resource; a malformed heredoc (no
    closing marker) instead returns an empty body, since falling back to the
    full block there would drag the following `rule { ... }` field into
    scanned scope."""
    if searchable is None:
        searchable = _blank_comment_lines(block)
    start_match = PROGRAM_TEXT_HEREDOC.search(searchable)
    if start_match is not None:
        dash, marker = start_match.group(1), start_match.group(2)
        indent = r"[ \t]*" if dash else ""
        end_match = re.search(
            rf"^{indent}{re.escape(marker)}[ \t]*$", searchable[start_match.end() :], re.M
        )
        if end_match is None:
            return ""
        return block[start_match.end() : start_match.end() + end_match.start()]
    string_match = PROGRAM_TEXT_STRING.search(searchable)
    if string_match is not None:
        return _decode_string_escapes(string_match.group(1))
    return block


def data_call_span(block: str, searchable: str | None = None) -> tuple[int, int, str] | None:
    """Return the (opening, closing) paren indices of the first data(...)
    call in block, plus the comment-blanked view of block those indices are
    valid against, so a decoy `data(`, `filter(`, or `)` mentioned in a
    comment or inside an unrelated string literal (e.g. a `.publish(...)`
    label) -- whether before the real call or on a continuation line inside
    its own argument list -- is never mistaken for real SignalFlow syntax by
    callers that slice the returned span. `searchable` lets a caller that
    already has the comment-blanked view of `block` pass it in instead of
    paying for `_blank_comment_lines` again. Raises ValueError, via
    `_iter_data_call_spans`, if the real call's parentheses are unbalanced;
    callers scoped to one resource should catch this and report a
    resource-scoped error rather than letting it escape validation."""
    if searchable is None:
        searchable = _blank_comment_lines(block)
    spans = _iter_data_call_spans(searchable)
    if not spans:
        return None
    _, opening, close = spans[0]
    return opening, close, searchable


TOKEN = re.compile(
    r"'(?:\\.|[^'\\])*'"
    r'|"(?:\\.|[^"\\])*"'
    r"|[A-Za-z_][A-Za-z0-9_.]*"
    r"|\d+(?:\.\d+)?"
    r"|\S"
)
NUMERIC = re.compile(r"\d+(?:\.\d+)?")


def _is_wordlike(token: str) -> bool:
    return token[0].isalnum() or token[0] in "_'\""


_STRING_ESCAPE_DECODE = {
    "\\": "\\",
    "'": "'",
    '"': '"',
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


def _decode_string_escapes(body: str) -> str:
    """Decode only the recognized escape sequences in a string literal body
    (backslash, quotes, and n/r/t) to their actual character, so an escaped
    control character (e.g. `\\n`, a newline) is never conflated with the
    unescaped literal character it merely resembles (e.g. `n`, the letter).
    An unrecognized `\\x` sequence passes through with its backslash intact
    since its meaning is not known."""
    result: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char == "\\" and index + 1 < len(body):
            next_char = body[index + 1]
            if next_char in _STRING_ESCAPE_DECODE:
                result.append(_STRING_ESCAPE_DECODE[next_char])
                index += 2
                continue
            result.append(char)
            result.append(next_char)
            index += 2
            continue
        result.append(char)
        index += 1
    return "".join(result)


def _canonical_token(token: str) -> str:
    """Canonicalize a string literal's quote style to single quotes so
    `'checkout'` and `"checkout"` compare equal; a numeric literal is
    normalized to its float value so equal numbers written differently -- e.g.
    `99` versus `99.0`, or `5` versus `5.0` -- render identically; other tokens
    pass through. Escape sequences are decoded to their actual character (not
    merely stripped of their backslash) before re-escaping, so a literal
    character and its similarly-spelled escape sequence -- e.g. the letter `n`
    in `'n'` versus the newline escape in `'\\n'` -- never canonicalize to the
    same signature."""
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"":
        decoded = _decode_string_escapes(token[1:-1])
        escaped = (
            decoded.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return f"'{escaped}'"
    if NUMERIC.fullmatch(token):
        return repr(float(token))
    return token


_BRACKET_OPENERS = {"(": ")", "[": "]", "{": "}"}
_BRACKET_CLOSERS = set(_BRACKET_OPENERS.values())


def _build_group(tokens: list[str], index: int) -> tuple[list, int]:
    """Parse tokens[index:] into a nested list mirroring bracket nesting.
    Each element is a token string, or an (opener, inner) pair for a `(...)`
    paren group, a `[...]` list, or a `{...}` dict -- so a comma inside any of
    those (e.g. the elements of `by=['a','b']` or the entries of a
    `filter={'a':'x','b':'y'}` dict) is collapsed into one nested element and
    never leaks out as a top-level comma to `_split_top_level_commas`. Stops
    at (and consumes) the first unmatched closing bracket or the end of
    tokens."""
    group: list = []
    while index < len(tokens):
        token = tokens[index]
        if token in _BRACKET_OPENERS:
            inner, index = _build_group(tokens, index + 1)
            group.append((token, inner))
        elif token in _BRACKET_CLOSERS:
            return group, index + 1
        else:
            group.append(token)
            index += 1
    return group, index


def _unwrap_redundant_parens(tokens: list) -> list:
    """Strip parentheses that wrap the whole token list. A paren group around
    an entire (sub)expression never changes how that expression's own boolean
    operators group -- it has no sibling operator to bind against -- so
    `(A and B)` and `A and B` (and `((A and B))`) must render identically.
    Repeats so multiply-nested whole-expression wrappers collapse too. This is
    only safe on a complete expression; a caller must not use it on an operand
    sitting beside a different operator, where the parens are significant."""
    while len(tokens) == 1 and isinstance(tokens[0], tuple) and tokens[0][0] == "(":
        tokens = tokens[0][1]
    return tokens


def _split_top_level_operator(tokens: list, operator: str) -> list[list]:
    """Split tokens on every top-level occurrence of the `and`/`or` operator
    string. A boolean operator nested inside a `(...)`/`[...]`/`{...}` group is
    already collapsed into a single tuple element by `_build_group`, so it is
    never seen here and stays bound to its own group."""
    result: list[list] = []
    current: list = []
    for token in tokens:
        if token == operator:
            result.append(current)
            current = []
        else:
            current.append(token)
    result.append(current)
    return result


def _top_level_operators(tokens: list) -> set[str]:
    return {token for token in tokens if token in ("and", "or")}


def _collect_operands(tokens: list, operator: str) -> list[list]:
    """Split tokens on top-level `operator`, flattening a single
    parenthesized operand whose own top-level operator is the *same* into the
    parent list. This makes the associative regroupings `(a and b) and c`,
    `a and (b and c)`, and `(a and d) and (b and c)` collapse to the same flat
    operand set before the caller sorts them -- while an operand parenthesized
    around a *different* operator (e.g. `(a or b)` inside an `and` chain) is
    left intact, since its parens are semantically significant."""
    raw = _split_top_level_operator(tokens, operator)
    if len(raw) == 1:
        return raw
    operands: list[list] = []
    for operand in raw:
        if len(operand) == 1 and isinstance(operand[0], tuple) and operand[0][0] == "(":
            inner = _unwrap_redundant_parens(operand[0][1])
            if _top_level_operators(inner) == {operator}:
                operands.extend(_collect_operands(inner, operator))
                continue
        operands.append(operand)
    return operands


def _render_operand(operand: list, parent_operator: str) -> str:
    """Render one operand of an `and`/`or` chain, wrapping it in parentheses
    only when its own top-level operator binds *looser* than the parent -- an
    `or` sub-expression sitting inside an `and` chain -- since those parens are
    the only ones that change which stream is selected. An `and` operand of an
    `or` chain, or a bare primary, needs no parens because `and` already binds
    tighter than `or`; dropping its parens (`(a and b) or c` -> `a and b or c`)
    does not change the expression."""
    rendered, top_operator = _canonical_boolean(operand)
    if parent_operator == "and" and top_operator == "or":
        return f"({rendered})"
    return rendered


def _canonical_boolean(tokens: list) -> tuple[str, str | None]:
    """Canonicalize a boolean (sub)expression, honoring SignalFlow operator
    precedence (`and` binds tighter than `or`) so that redundant precedence
    parentheses are dropped while significant ones are kept, and sorting the
    commutative operands at each level so operand order never changes the
    signature. Returns (rendered, top_operator) where top_operator is 'or',
    'and', or None (a primary with no top-level boolean operator), letting a
    caller decide whether this expression needs wrapping in its own context.
    `or` is split before `and` so a mixed chain like `a and b or c` groups as
    `(a and b) or c`, matching how SignalFlow parses it."""
    tokens = _unwrap_redundant_parens(tokens)
    or_terms = _collect_operands(tokens, "or")
    if len(or_terms) > 1:
        rendered = sorted(_render_operand(term, "or") for term in or_terms)
        return " or ".join(rendered), "or"
    and_terms = _collect_operands(tokens, "and")
    if len(and_terms) > 1:
        rendered = sorted(_render_operand(term, "and") for term in and_terms)
        return " and ".join(rendered), "and"
    return _render_tokens(tokens), None


def _canonical_bracket(opener: str, inner: list) -> str:
    """Render a nested bracket group to a canonical string. A `(...)` group is
    a positional/keyword argument list or a parenthesized boolean
    sub-expression, so it is canonicalized by `_canonical_group` (first
    argument positional, the rest sorted). A `[...]` list and a `{...}` dict,
    by contrast, are order-insensitive for stream selection -- the group-by
    keys of `by=['a','b']` and the entries of a `filter={'a':'x','b':'y'}`
    dict select the same stream regardless of order -- so their
    comma-separated members are each canonicalized and then sorted, making
    `by=['a','b']` and `by=['b','a']` (and the two key orderings of a filter
    dict) render identically. A single-element `[...]` list is unwrapped to
    that bare element, since the SignalFlow `by=` group-by and the value
    argument of `filter(...)` accept a scalar or a one-element list
    interchangeably -- `by=['host']` selects the same stream as `by='host'`,
    and `filter('k',['a'])` the same as `filter('k','a')` -- so the two forms
    must render identically. A single-element `{...}` dict is left wrapped,
    since a dict is not interchangeable with its bare entry."""
    closer = _BRACKET_OPENERS[opener]
    if opener == "(":
        return f"({_canonical_group(inner)})"
    members = sorted(_canonical_argument(member) for member in _split_top_level_commas(inner))
    if opener == "[" and len(members) == 1:
        return members[0]
    return f"{opener}{','.join(members)}{closer}"


def _render_tokens(tokens: list) -> str:
    parts: list[str] = []
    previous: str | None = None
    for item in tokens:
        token = _canonical_bracket(item[0], item[1]) if isinstance(item, tuple) else _canonical_token(item)
        if previous is not None and _is_wordlike(previous) and _is_wordlike(token):
            parts.append(" ")
        parts.append(token)
        previous = token
    return "".join(parts)


def _split_top_level_commas(group: list) -> list[list]:
    """Split group on "," elements that belong to this group's own nesting
    level. Commas inside a nested paren group are untouched because that
    nested content is already collapsed into a single ("(", inner) element
    by `_build_group`, not exposed as top-level "," tokens here."""
    args: list[list] = []
    current: list = []
    for item in group:
        if item == ",":
            args.append(current)
            current = []
        else:
            current.append(item)
    args.append(current)
    return args


def _canonical_argument(tokens: list) -> str:
    """Render one data(...) argument to a canonical string. A leading
    `filter=` keyword prefix is set aside before canonicalizing the boolean
    expression, so the prefix never ends up attached to whichever operand
    happens to render first -- that association would otherwise differ between
    `filter=filter(a) and filter(b)` and the operands reversed, defeating the
    operand sort inside `_canonical_boolean`. String-literal quote style is
    normalized, and the operands of each top-level `and`/`or` level are sorted
    with precedence-redundant parentheses dropped, so two filter expressions
    that are identical except for quote style, commutative operand order, or
    redundant/associative parenthesization render to the same string."""
    prefix = ""
    if len(tokens) >= 2 and tokens[0] == "filter" and tokens[1] == "=":
        prefix, tokens = "filter=", tokens[2:]
    rendered, _ = _canonical_boolean(tokens)
    return prefix + rendered


def _canonical_group(group: list) -> str:
    """Render a parsed data(...) argument list to a canonical string by
    canonicalizing each top-level comma-separated argument independently.
    The first argument is the positional metric name and keeps its position;
    every argument after it is a `key=value` keyword argument (`filter=...`,
    `rollup=...`, etc.) and those are sorted by their canonicalized string, so
    `data(METRIC, filter=..., rollup='count')` and
    `data(METRIC, rollup='count', filter=...)` -- which select the identical
    stream -- render to the same signature regardless of keyword order."""
    rendered = [_canonical_argument(arg) for arg in _split_top_level_commas(group)]
    if len(rendered) > 1:
        rendered = [rendered[0]] + sorted(rendered[1:])
    return ",".join(rendered)


PUBLISH_CALL = re.compile(r"\.publish\(")
PUBLISH_LABEL = re.compile(r"\.publish\(\s*['\"]([^'\"]+)['\"]")


def _iter_publish_call_spans(searchable: str) -> list[tuple[int, int, int]]:
    """Return (start, opening, close) for every top-level `.publish(...)`
    call in searchable, in source order. Same quote-blanked-marker /
    unblanked-close-paren technique as `_iter_data_call_spans`, so a decoy
    `.publish(`-shaped marker inside a string literal (e.g. a `description`
    field documenting the program) is never found as a call. Raises
    ValueError, via `matching_paren`, if a real call's parentheses are
    unbalanced."""
    masked = _blank_quoted_content(searchable)
    spans: list[tuple[int, int, int]] = []
    for match in PUBLISH_CALL.finditer(masked):
        opening = match.end() - 1
        close = matching_paren(searchable, opening)
        spans.append((match.start(), opening, close))
    return spans


def published_labels(searchable: str) -> list[str]:
    """Return the label argument of every top-level `.publish(...)` call in
    searchable (already comment-blanked), found via the quote-aware
    `_iter_publish_call_spans` scanner so a decoy `.publish('label')`-shaped
    string inside a comment or an unrelated field (e.g. a `description`
    documenting the program) is never mistaken for a real publish call, the
    same way `data_call_metrics` guards against a decoy `data(...)` marker.
    Raises ValueError, via `_iter_publish_call_spans`, if a real call's
    parentheses are unbalanced."""
    labels = []
    for start, _, _ in _iter_publish_call_spans(searchable):
        label_match = PUBLISH_LABEL.match(searchable, start)
        if label_match is not None:
            labels.append(label_match.group(1))
    return labels


def data_call_metrics(searchable: str) -> list[str]:
    """Return the metric-name argument of every top-level data(...) call in
    searchable (already comment-blanked), found via the quote-aware
    `_iter_data_call_spans` scanner so a data(...)-shaped decoy that only
    appears inside a string literal -- for example a
    `.publish("replaces data('legacy.metric')")` label -- is never counted
    as a second call the way a plain `DATA_METRIC.findall` over the whole
    body would. Every discovered call is counted: one whose metric argument
    is not a quoted string literal (e.g. `data(dynamic_metric, ...)`) raises
    ValueError rather than being silently dropped, so it cannot hide behind a
    second, verified literal call and bypass the one-metric and working-metric
    evidence checks. Also raises ValueError, via `_iter_data_call_spans`, if a
    real call's parentheses are unbalanced."""
    metrics = []
    for start, _, _ in _iter_data_call_spans(searchable):
        metric_match = DATA_METRIC.match(searchable, start)
        if metric_match is None:
            raise ValueError("data(...) call's metric argument is not a quoted string literal")
        metrics.append(metric_match.group(1))
    return metrics


def data_call_signature(block: str, searchable: str | None = None) -> str | None:
    """Return the canonical argument text of the data(...) call, scoped to
    the call's own arguments so filter(...)-shaped text inside comments or
    publish() labels elsewhere in the block is never mistaken for a real
    filter. Canonicalizing (rather than extracting key/value pairs)
    preserves `and`/`or`/`not` boolean structure and any other
    stream-affecting option such as rollup, so two data(...) calls that
    select different streams never collapse to the same signature -- while
    quote style and commutative and/or operand order, which do not change
    which stream is selected, do collapse to the same signature. `searchable`
    lets a caller that already has the comment-blanked view of `block` pass
    it in instead of paying for `_blank_comment_lines` again."""
    span = data_call_span(block, searchable)
    if span is None:
        return None
    opening, close, searchable = span
    tokens = TOKEN.findall(searchable[opening + 1 : close])
    group, _ = _build_group(tokens, 0)
    return _canonical_group(group)


def _is_keyword_argument(tokens: list) -> bool:
    return len(tokens) >= 2 and tokens[1] == "=" and bool(re.match(r"^[A-Za-z_]\w*$", str(tokens[0])))


def _canonical_aggregation_call(name: str, args_text: str) -> str:
    """Render one aggregation method call's argument list to a canonical
    string. Aggregation methods can take positional arguments whose order is
    semantically significant -- e.g. `between(low_limit, high_limit)`,
    `count_above(value, ...)` -- so positional arguments keep their original
    order and are never sorted alongside each other; only the keyword
    arguments (`pct=99`, `over='5m'`, etc.), which the SignalFlow methods
    referenced here take exclusively via `key=value` and whose relative
    order does not change which values are passed, are sorted among
    themselves. Quote style is normalized the same way as a data(...)
    argument list, so two calls to the same method that differ only in
    keyword-argument order or quote style -- not positional-argument order --
    render to the same signature."""
    tokens = TOKEN.findall(args_text)
    group, _ = _build_group(tokens, 0)
    positional: list[str] = []
    keyword: list[str] = []
    for arg in _split_top_level_commas(group):
        rendered_arg = _canonical_argument(arg)
        (keyword if _is_keyword_argument(arg) else positional).append(rendered_arg)
    rendered = positional + sorted(keyword)
    return f".{name}({','.join(rendered)})"


def aggregation_signature(block: str, searchable: str | None = None) -> str:
    """Return the normalized chain of aggregation method calls, including
    their arguments, chained directly onto data(...) and before .publish(...),
    e.g. '.percentile(pct=99)' or ".count(by=['error.type'])". Including the
    arguments (not just the method name) distinguishes detectors that read
    the same metric with the same method but different aggregation
    arguments, such as different percentiles or different `by=[...]` groupings.
    Quote style and keyword-argument order inside those arguments are
    canonicalized the same way as the filter signature, so two aggregation
    chains that are identical except for quote style or keyword order, e.g.
    `.percentile(pct=99, over='5m')` vs `.percentile(over='5m', pct=99)`,
    render to the same signature and are not mistaken for a distinguishing
    difference; the order of chained methods themselves is preserved since
    that is semantically significant. The chain is walked with a quote-aware
    scanner (rather than a fixed-depth regex) so whitespace or a newline
    around the chaining dot -- `data(...).mean()` vs `data(...).\n  mean()`
    -- does not change the signature, and an argument nested more than one
    paren deep is not truncated. Scanning stops at the first `.publish(`
    (the publish call is not part of the aggregation) or at the first token
    that is not a `.method(...)` continuation. `searchable` lets a caller
    that already has the comment-blanked view of `block` pass it in instead
    of paying for `_blank_comment_lines` again."""
    span = data_call_span(block, searchable)
    if span is None:
        return ""
    _, close, searchable = span
    calls: list[str] = []
    index = close + 1
    length = len(searchable)
    while True:
        while index < length and searchable[index].isspace():
            index += 1
        if index >= length or searchable[index] != ".":
            break
        index += 1
        while index < length and searchable[index].isspace():
            index += 1
        name_match = AGG_METHOD_NAME.match(searchable, index)
        if name_match is None:
            break
        name = name_match.group(0)
        if name == "publish":
            break
        cursor = name_match.end()
        while cursor < length and searchable[cursor].isspace():
            cursor += 1
        if cursor >= length or searchable[cursor] != "(":
            break
        try:
            call_close = matching_paren(searchable, cursor)
        except ValueError:
            break
        calls.append(_canonical_aggregation_call(name, searchable[cursor + 1 : call_close]))
        index = call_close + 1
    return "".join(calls)


def detector_blocks(text: str) -> list[tuple[str, str]]:
    """Split text into (resource_id, block) pairs for every top-level
    `resource "signalfx_detector" "..." { ... }` block. Both the resource
    header and the closing brace are located against a comment-blanked view
    so a decoy `resource "signalfx_detector" "ghost" {` or a stray `{`/`}`
    inside a comment -- whether at the HCL level or inside a program_text
    heredoc -- can never be mistaken for a real block boundary; the returned
    block text is still sliced from the original, unblanked `text` since
    `_blank_comment_lines` preserves character indices."""
    searchable = _blank_comment_lines(text)
    blocks: list[tuple[str, str]] = []
    for match in RESOURCE_START.finditer(searchable):
        opening = searchable.find("{", match.start())
        end = matching_brace(searchable, opening)
        blocks.append((match.group(1), text[match.start() : end + 1]))
    return blocks


def report_status(text: str, name: str, errors: list[str]) -> str | None:
    matches = REPORT_STATUS.findall(text)
    if len(matches) != 1:
        errors.append(f"{name}: expected exactly one Result status, found {len(matches)}")
        return None
    return matches[0].title()


def validate_heading_order(text: str, name: str, errors: list[str]) -> None:
    headings = re.findall(r"^## (.+?)\s*$", text, re.M)
    positions: list[int] = []
    for expected in CONFIGURE_VERIFY_HEADINGS:
        count = headings.count(expected)
        if count == 0:
            errors.append(f"{name}: missing ## {expected}")
            continue
        if count > 1:
            errors.append(f"{name}: duplicate ## {expected}")
            continue
        positions.append(headings.index(expected))
    if len(positions) == len(CONFIGURE_VERIFY_HEADINGS) and positions != sorted(positions):
        errors.append(f"{name}: reader-first headings are out of order")


def validate(args: argparse.Namespace) -> dict[str, object]:
    terraform_dir: Path = args.terraform_dir
    required = {
        "detectors.tf": terraform_dir / "detectors.tf",
        "variables.tf": terraform_dir / "variables.tf",
        "terraform.tfvars.example": terraform_dir / "terraform.tfvars.example",
        ".gitignore": terraform_dir / ".gitignore",
        "detectors report": args.detectors_report,
        "configure verification report": args.configure_verify_report,
    }
    errors = [f"missing {name}: {path}" for name, path in required.items() if not path.is_file()]
    if errors:
        return {"result": "FAIL", "errors": errors}

    detectors_text = required["detectors.tf"].read_text(encoding="utf-8")
    variables_text = required["variables.tf"].read_text(encoding="utf-8")
    tfvars_text = required["terraform.tfvars.example"].read_text(encoding="utf-8")
    gitignore_text = required[".gitignore"].read_text(encoding="utf-8")
    report_text = required["detectors report"].read_text(encoding="utf-8")
    configure_verify_text = required["configure verification report"].read_text(encoding="utf-8")
    detector_status = report_status(report_text, "detectors report", errors)
    configure_status = report_status(configure_verify_text, "configure verification report", errors)
    if detector_status is not None and configure_status is not None and detector_status != configure_status:
        errors.append(
            "detectors report status does not match configure verification status: "
            f"{detector_status} != {configure_status}"
        )
    validate_heading_order(configure_verify_text, "configure verification report", errors)
    try:
        blocks = detector_blocks(detectors_text)
    except ValueError as error:
        errors.append(f"detectors.tf: malformed signalfx_detector block ({error})")
        return {"result": "FAIL", "errors": errors}
    ids = [resource_id for resource_id, _ in blocks]
    if len(ids) != len(set(ids)):
        errors.append("duplicate signalfx_detector resource identifiers")

    declared = set(VARIABLE_DECLARATION.findall(variables_text))
    verified = working_metrics(args.verify_report)
    allowed = verified | set(args.allow_source_only_metric)
    detector_metrics: list[str] = []
    detector_signatures: list[tuple[str, str | None, str]] = []

    for resource_id, block in blocks:
        searchable = _blank_comment_lines(block)
        decoy_blanked = _blank_decoy_fields(searchable)
        program_body = program_text_body(block, searchable)
        program_searchable = _blank_comment_lines(program_body)
        try:
            metrics = data_call_metrics(program_searchable)
        except ValueError as error:
            errors.append(f"{resource_id}: malformed data(...) call ({error})")
            continue
        if len(metrics) != 1:
            errors.append(f"{resource_id}: expected exactly one data(...) metric, found {len(metrics)}")
            continue
        metric = metrics[0]
        detector_metrics.append(metric)
        detector_signatures.append(
            (
                metric,
                data_call_signature(program_body, program_searchable),
                aggregation_signature(program_body, program_searchable),
            )
        )
        if metric not in allowed:
            errors.append(f"{resource_id}: metric {metric!r} is not a Working verified metric")
        if metric not in report_text:
            errors.append(f"{resource_id}: metric {metric!r} is absent from detectors report")
        data_span = data_call_span(program_body, program_searchable)
        data_args = program_searchable[data_span[0] : data_span[1] + 1] if data_span is not None else ""
        if not re.search(r"filter\(\s*['\"]service\.name['\"]\s*,", data_args):
            errors.append(f"{resource_id}: missing service.name filter")
        for variable in VARIABLE_REFERENCE.findall(decoy_blanked):
            if variable not in declared:
                errors.append(f"{resource_id}: referenced variable {variable!r} is not declared")
        labels = DETECT_LABEL.findall(decoy_blanked)
        if len(labels) != 1:
            errors.append(f"{resource_id}: expected one detect_label, found {len(labels)}")
        else:
            try:
                labels_published = published_labels(program_searchable)
            except ValueError as error:
                errors.append(f"{resource_id}: malformed .publish(...) call ({error})")
            else:
                if labels[0] not in labels_published:
                    errors.append(f"{resource_id}: detect_label {labels[0]!r} is not published by SignalFlow")
        for description, pattern in FORBIDDEN_PROGRAM_PATTERNS.items():
            if pattern.search(searchable):
                errors.append(f"{resource_id}: unsafe {description} appears in detector program")

    if len(detector_signatures) != len(set(detector_signatures)):
        errors.append(
            "two detectors read the same metric with the same aggregation and attribute "
            "filters (true duplicate; a route-group merge must use a distinct aggregation "
            "or filter on distinct attributes)"
        )
    if "api_token" not in declared:
        errors.append("variables.tf does not declare sensitive api_token")
    if "realm" not in declared:
        errors.append("variables.tf does not declare realm")
    searchable_detectors_text = _blank_comment_lines(detectors_text)
    provider_matches = list(PROVIDER_START.finditer(searchable_detectors_text))
    if len(provider_matches) != 1:
        errors.append(f"expected one signalfx provider block, found {len(provider_matches)}")
    else:
        opening = searchable_detectors_text.find("{", provider_matches[0].start())
        try:
            end = matching_brace(searchable_detectors_text, opening)
        except ValueError as error:
            errors.append(f"detectors.tf: malformed signalfx provider block ({error})")
            end = None
        if end is not None:
            provider = searchable_detectors_text[provider_matches[0].start() : end + 1]
            if not re.search(r"auth_token\s*=\s*var\.api_token\b", provider):
                errors.append("signalfx provider must use var.api_token")
            if not re.search(r'api_url\s*=\s*"https://api\.\$\{var\.realm\}\.(?:signalfx\.com|observability\.splunk\.com)"', provider):
                errors.append("signalfx provider api_url must derive from var.realm")
    if not re.search(r'variable\s+"api_token"\s*\{(?:(?!\n\}).)*sensitive\s*=\s*true', variables_text, re.S):
        errors.append("api_token variable is not marked sensitive")
    if not re.search(r'^\s*api_token\s*=\s*""\s*(?:#.*)?$', tfvars_text, re.M):
        errors.append("terraform.tfvars.example must leave api_token empty")
    ignore_lines = {
        line.strip() for line in gitignore_text.splitlines() if line.strip() and not line.lstrip().startswith("#")
    }
    for required_ignore in {".terraform/", "*.tfstate", "*.tfstate.*", "terraform.tfvars"}:
        if required_ignore not in ignore_lines:
            errors.append(f".gitignore does not exclude {required_ignore!r}")

    return {
        "result": "PASS" if not errors else "FAIL",
        "detector_count": len(blocks),
        "detector_metrics": sorted(detector_metrics),
        "working_metric_count": len(verified),
        "reported_status": configure_status,
        "source_only_exceptions": sorted(args.allow_source_only_metric),
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terraform-dir", type=Path, required=True)
    parser.add_argument("--detectors-report", type=Path, required=True)
    parser.add_argument("--configure-verify-report", type=Path, required=True)
    parser.add_argument("--verify-report", type=Path, required=True)
    parser.add_argument("--allow-source-only-metric", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    try:
        result = validate(parse_args())
    except (OSError, ValueError) as error:
        result = {"result": "FAIL", "errors": [str(error)]}
    print(json.dumps(result, indent=2))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
