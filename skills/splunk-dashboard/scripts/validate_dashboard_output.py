#!/usr/bin/env python3
"""Validate dashboard Terraform, Observer preview JSON, and reader report parity."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import textwrap
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CHART_TYPES = {
    "signalfx_time_chart": "time_series",
    "signalfx_single_value_chart": "single_value",
    "signalfx_list_chart": "list",
    "signalfx_heatmap_chart": "heatmap",
    "signalfx_text_chart": "text",
    "signalfx_table_chart": "table",
}
CHART_RESOURCE = re.compile(
    r'resource\s+"(' + "|".join(map(re.escape, CHART_TYPES)) + r')"\s+"([^"]+)"\s*\{'
)
DASHBOARD_RESOURCE = re.compile(r'resource\s+"signalfx_dashboard"\s+"([^"]+)"\s*\{')
DASHBOARD_GROUP_RESOURCE = re.compile(
    r'resource\s+"signalfx_dashboard_group"\s+"([^"]+)"\s*\{'
)
VARIABLE_RESOURCE = re.compile(r'variable\s+"([A-Za-z_][A-Za-z0-9_]*)"\s*\{')
VARIABLE_INTERPOLATION = re.compile(r"\$\{\s*var\.([A-Za-z_][A-Za-z0-9_]*)\s*\}")
UNRESOLVED_VARIABLE = re.compile(
    r"\$\{\s*var\.[A-Za-z_][A-Za-z0-9_]*\s*\}|(?<![A-Za-z0-9_.])var\.[A-Za-z_][A-Za-z0-9_]*"
)
HCL_HEREDOC_START = re.compile(
    r'<<(-?)\s*"?([A-Za-z_][A-Za-z0-9_-]*)"?[ \t]*\r?\n'
)
SERVICE_FILTER = re.compile(
    r"filter\s*\(\s*['\"](?:service\.name|sf_service)['\"]\s*,",
    re.I,
)
DATA_METRIC = re.compile(r"\bdata\(\s*['\"]([^'\"]+)['\"]")
OTEL_ITEM_ID = re.compile(r"^OTEL-\d{3}\.[A-Za-z0-9][A-Za-z0-9._-]*$")
OTEL_FINDING_ID = re.compile(r"^OTEL-\d{3}$")
SOURCE_METRIC_ID = re.compile(r"^SOURCE-METRIC\.[A-Za-z0-9][A-Za-z0-9._/-]*$")
TELEMETRY_ITEM_ID = re.compile(
    r"^(?:OTEL-\d{3}|SOURCE-METRIC)\.[A-Za-z0-9][A-Za-z0-9._/-]*$"
)
REPORT_RESULT = re.compile(r"^\*\*Result:\*\*\s*(Pass|Partial|Blocked)\s*$", re.I | re.M)
LEGACY_VERIFY_RESULT = re.compile(
    r"^\*\*Result:\*\*\s*(Pass|Partial|Fail|Blocked|Not run)\s*$",
    re.I | re.M,
)
LEGACY_VERIFY_HEADERS = (
    "Item ID",
    "OTel item",
    "Type",
    "Added or modified",
    "Working status",
    "How it was tested",
    "Product result / visibility",
    "Evidence",
)
LEGACY_WORKING_STATUSES = {
    "working",
    "not working",
    "not proven",
    "not configured",
}
LEGACY_TEST_PROJECTION = re.compile(
    r"^proof_mode=(app_test|unit|unit\+otlp|full_runtime|contract_only|static|not_run); "
    r"scenarios=(.+)$"
)
LEGACY_SCENARIO_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
LEGACY_VISIBILITY_PROJECTION = re.compile(
    r"(?:^|;\s*)visibility=(explorer_visible|otlp_accepted|"
    r"not_explorer_visible|not_proven|not_applicable)\s*$"
)
LEGACY_DURABLE_EVIDENCE = re.compile(
    r"(?:^|[\s;`])(?:\.?[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\."
    r"(?:jsonl?|txt|log|xml|html?|md|out|tap|junit|otlp|pb)(?=$|[\s,;:`])|"
    r"\b(?:saved\s+(?:collector\s+)?(?:capture|response)|"
    r"assertion\s+(?:output|report)|test\s+report)\b",
    re.I,
)
LEGACY_DURABLE_ARTIFACT_REFERENCE = re.compile(
    r"(?:^|[\s;`])(?:\.?[A-Za-z0-9_.-]+[/\\])*[A-Za-z0-9_.-]+\."
    r"(?:jsonl?|txt|log|xml|html?|md|out|tap|junit|otlp|pb)(?=$|[\s,;:`])",
    re.I,
)
NON_PROOF_LEGACY_ARTIFACT_LABEL = re.compile(
    r"\b(?:none|unproven|not\s+(?:proven|configured|run|tested)|blocked|"
    r"pending|skipped|unknown)\b",
    re.I,
)
VALIDATION_ROWS = (
    "Verified metric item mapping",
    "Terraform ↔ preview parity",
    "Observer render",
    "Live value sanity",
    "Publish/apply",
)
PROOF_MODES = {
    "app_test",
    "unit",
    "unit+otlp",
    "full_runtime",
    "contract_only",
    "static",
    "not_run",
}
ITEM_DIRECT_PROOF_MODES = {"app_test", "unit", "unit+otlp", "full_runtime"}
VISIBILITY_STATES = {
    "explorer_visible",
    "otlp_accepted",
    "not_explorer_visible",
    "not_proven",
    "not_applicable",
}
VERIFY_RESULTS = {"Pass", "Partial", "Fail", "Blocked", "Not run"}
VERIFY_WORKFLOW_MODES = {"standalone", "instrumentation_child"}
VERIFY_LIFECYCLES = {"intermediate", "final"}
VERIFY_ITEM_STATUSES = {"working", "not_working", "not_proven", "not_configured", "blocked"}
VERIFY_FINDING_STATUSES = {
    "working",
    "not_working",
    "not_proven",
    "not_configured",
    "deferred",
}
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
# Every released Observer binary targets amd64 or arm64, and SpecLayout uses Go
# int fields. Keep generated HCL and preview coordinates inside that shared
# signed 64-bit representation so Python's arbitrary-precision integers cannot
# validate a sidecar that encoding/json will reject in the Observer.
OBSERVER_INT_MIN = -(1 << 63)
OBSERVER_INT_MAX = (1 << 63) - 1
NEGATIVE_OR_UNCERTAIN_DIRECT_EVIDENCE = re.compile(
    r"\b(?:could\s+not|did\s+not|never|unable|unavailable|"
    r"(?:couldn|didn|wasn|weren|isn|aren|hasn|haven|hadn)['’]t|"
    r"fail(?:ed|ure)?|errored|(?:returned|raised|encountered|produced|with)"
    r"\s+(?:an?\s+)?errors?(?=\s*(?:[.,;:]|$))|errors?\s+(?:occurred|"
    r"returned|reported|raised|blocked|prevented)|blocked|pending|unknown|uncertain|"
    r"unproven|perhaps|possibly|maybe|(?:might|may)\s+(?:have|be|"
    r"render(?:ed)?|return(?:ed)?|show(?:n)?|contain(?:ed)?|work(?:ed)?)|"
    r"appears?\s+to|seems?\s+to|not\s+(?:run|executed|captured|saved|rendered|observed|"
    r"returned|available|proven|visible)|no\s+(?:screenshot|render|"
    r"witness|query|series|data|values?|evidence|result))\b",
    re.I,
)
NEGATED_DIRECT_PROOF = re.compile(
    r"\b(?:without|missing|absent|no)\s+"
    r"(?:(?:direct|observer|recent[- ]window)\s+)*(?:verification|"
    r"validator|mapping|parity|screenshot|render(?:\s+witness)?|witness|"
    r"query|series|data|values?|evidence|result|proof)\b",
    re.I,
)
METRIC_NEGATION_BEFORE = re.compile(
    r"(?:\b(?:no|without|missing|absent|unobserved)\s+|"
    r"\bno\s+(?:evidence|data|sign|record)\s+(?:of|for)\s+|"
    r"\b(?:did|does|do|could|can)\s+(?:not|never)\s+(?:find|see|observe|record|capture|receive)\s+|"
    r"\bnever\s+(?:found|saw|observed|recorded|captured|received)\s+|"
    r"\bunable\s+to\s+(?:find|see|observe|record|capture|receive)\s+|"
    r"\b(?:not|never)\s+(?:emit(?:ted)?|observ(?:e|ed)|record(?:ed)?|export(?:ed)?|captur(?:e|ed)|receiv(?:e|ed))\s+|"
    r"\b(?:did|does|do|could|can|was|were|is|are|has|have|had|would|should)\s+not\s+(?:(?:be\s+)?(?:found|seen)|emit|observe|record|export|capture|receive)\s+|"
    r"\b(?:didn|doesn|couldn|wasn|weren|isn|aren|hasn|haven|hadn|wouldn|shouldn)['’]t\s+(?:(?:be\s+)?(?:found|seen)|emit|observe|record|export|capture|receive)\s+|"
    r"\bfailed\s+to\s+(?:find|see|emit|observe|record|export|capture|receive)\s+)$",
    re.I,
)
METRIC_NEGATION_AFTER = re.compile(
    r"^[\s,:;()\[\]-]*(?:(?:is|was|were|are|remains?|remained)\s+(?:missing|absent|unobserved|unavailable)\b|"
    r"(?:is|was|were|are|remains?|remained)\s+(?:not|never)\s+(?:present|available|found|seen|observed|recorded|captured|received)\b|"
    r"(?:could|can|was|were|is|are|has|have|had|would|should)\s+(?:not|never)\s+(?:be\s+)?(?:found|seen|observed|recorded|captured|received)\b|"
    r"(?:couldn|wasn|weren|isn|aren|hasn|haven|hadn|wouldn|shouldn)['’]t\s+(?:be\s+)?(?:found|seen|observed|recorded|captured|received)\b|"
    r"(?:is|was|were|are|did|does|do|could|can|has|have|had|would|should)\s+(?:not|never)\s+(?:emit(?:ted)?|observ(?:e|ed)|record(?:ed)?|export(?:ed)?|captur(?:e|ed)|receiv(?:e|ed))|"
    r"(?:isn|wasn|weren|aren|didn|doesn|couldn|hasn|haven|hadn|wouldn|shouldn)['’]t\s+(?:emit|observe|record|export|capture|receive)|"
    r"(?:not|never)\s+(?:emit(?:ted)?|observ(?:e|ed)|record(?:ed)?|export(?:ed)?|captur(?:e|ed)|receiv(?:e|ed))|"
    r"failed\s+to\s+(?:find|see|emit|observe|record|export|capture|receive)|"
    r"(?:yielded|returned|produced|contained|had|has)\s+no\s+(?:data|evidence|samples?|points?|records?)\b|"
    r"missing\b|absent\b|unobserved\b|unavailable\b)",
    re.I,
)


@dataclass(frozen=True)
class Chart:
    label: str
    title: str
    resource_type: str
    chart_type: str
    program_text: str | None
    text: str | None
    telemetry_item_id: str


@dataclass(frozen=True)
class PreviewChart:
    label: str
    title: str
    chart_type: str
    program_text: str | None
    text: str | None
    telemetry_item_id: str
    product_action: str
    layout: tuple[int, int, int, int]
    dashboard: str
    group: str


@dataclass(frozen=True)
class DashboardPlacement:
    layout: tuple[int, int, int, int]
    dashboard: str
    group: str


@dataclass(frozen=True)
class DashboardTopology:
    groups: tuple[str, ...]
    dashboards: tuple[tuple[str, str], ...]


def hcl_structure_mask(source: str) -> list[bool]:
    """Mark HCL structure while excluding comments and every string body."""

    structural = [True] * len(source)
    index = 0
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if char == "#" or (char == "/" and next_char == "/"):
            end = index
            while end < len(source) and source[end] not in "\r\n":
                structural[end] = False
                end += 1
            index = end
            continue
        if char == "/" and next_char == "*":
            end = index
            while end < len(source):
                structural[end] = False
                if end > index and source[end - 1 : end + 1] == "*/":
                    end += 1
                    break
                end += 1
            index = end
            continue
        heredoc = HCL_HEREDOC_START.match(source, index)
        if heredoc is not None:
            indented, marker = heredoc.groups()
            indent = r"[ \t]*" if indented else ""
            closing = re.search(
                rf"^{indent}{re.escape(marker)}[ \t]*\r?$",
                source[heredoc.end() :],
                re.M,
            )
            body_end = (
                heredoc.end() + closing.end()
                if closing is not None
                else len(source)
            )
            for offset in range(heredoc.end(), body_end):
                structural[offset] = False
            index = body_end
            continue
        if char in {'"', "'"}:
            quote = char
            escaped = False
            structural[index] = False
            index += 1
            while index < len(source):
                structural[index] = False
                if escaped:
                    escaped = False
                elif source[index] == "\\":
                    escaped = True
                elif source[index] == quote:
                    index += 1
                    break
                index += 1
            continue
        index += 1
    return structural


def matching_brace(
    source: str,
    opening: int,
    structural: list[bool] | None = None,
) -> int:
    """Return the matching structural brace, ignoring comments and strings."""

    if structural is None:
        structural = hcl_structure_mask(source)
    depth = 0
    for index in range(opening, len(source)):
        if not structural[index]:
            continue
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError("unbalanced HCL resource block")


def resource_blocks(source: str, pattern: re.Pattern[str]) -> list[tuple[tuple[str, ...], str]]:
    blocks: list[tuple[tuple[str, ...], str]] = []
    structural = hcl_structure_mask(source)
    for match in pattern.finditer(source):
        if not structural[match.start()]:
            continue
        opening = source.find("{", match.start(), match.end())
        closing = matching_brace(source, opening, structural)
        blocks.append((match.groups(), source[opening + 1 : closing]))
    return blocks


def hcl_string(body: str, attribute: str) -> str | None:
    match = re.search(
        rf'^\s*{re.escape(attribute)}\s*=\s*"((?:\\.|[^"\\])*)"\s*(?:#.*)?$',
        body,
        re.M,
    )
    if match is None:
        return None
    return (
        match.group(1)
        .replace(r"\\", "\\")
        .replace(r'\"', '"')
        .replace(r"\n", "\n")
        .replace(r"\t", "\t")
    )


def hcl_heredoc(body: str, attribute: str) -> str | None:
    match = re.search(
        rf'^\s*{re.escape(attribute)}\s*=\s*<<(-?)([A-Za-z_][A-Za-z0-9_]*)\s*\r?\n'
        rf'(.*?)^([ \t]*)\2[ \t]*\r?$',
        body,
        re.M | re.S,
    )
    if match is None:
        return None
    indented, _, value, closing_indent = match.groups()
    if not indented and closing_indent:
        return None
    if indented:
        return textwrap.dedent(value).strip()
    return value.strip("\r\n")


def parse_scalar(value: str) -> str | int | float | bool | None:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, str) else None
    if value in {"true", "false"}:
        return value == "true"
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return None


def variable_values(variables_path: Path | None, tfvars_path: Path | None) -> dict[str, object]:
    values: dict[str, object] = {}
    if variables_path is not None and variables_path.is_file():
        source = variables_path.read_text(encoding="utf-8")
        for groups, body in resource_blocks(source, VARIABLE_RESOURCE):
            match = re.search(r"^\s*default\s*=\s*([^#\r\n]+)", body, re.M)
            if match is not None:
                parsed = parse_scalar(match.group(1))
                if parsed is not None:
                    values[groups[0]] = parsed
    if tfvars_path is not None and tfvars_path.is_file():
        for match in re.finditer(
            r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^#\r\n]+)",
            tfvars_path.read_text(encoding="utf-8"),
            re.M,
        ):
            parsed = parse_scalar(match.group(2))
            if parsed not in {None, ""}:
                values[match.group(1)] = parsed
    return values


def validate_sensitive_variables(
    variables_path: Path | None,
    tfvars_path: Path | None,
    errors: list[str],
) -> None:
    if variables_path is None or not variables_path.is_file():
        errors.append("Terraform: variables.tf is required")
        return
    source = variables_path.read_text(encoding="utf-8")
    declarations = {
        groups[0]: body for groups, body in resource_blocks(source, VARIABLE_RESOURCE)
    }
    api_token = declarations.get("api_token")
    if api_token is None:
        errors.append("Terraform variables: api_token must be declared")
    elif re.search(r"^\s*sensitive\s*=\s*true\s*(?:#.*)?$", api_token, re.M) is None:
        errors.append("Terraform variables: api_token must set sensitive = true")
    if tfvars_path is not None and tfvars_path.is_file() and re.search(
        r"^\s*api_token\s*=", tfvars_path.read_text(encoding="utf-8"), re.M
    ):
        errors.append("Terraform tfvars: --tfvars must not contain api_token")


def resolve_variables(value: str, variables: dict[str, object], context: str, errors: list[str]) -> str:
    missing: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            missing.add(name)
            return match.group(0)
        return str(variables[name])

    resolved = VARIABLE_INTERPOLATION.sub(replace, value)
    if missing:
        errors.append(f"{context}: unresolved Terraform variables: {', '.join(sorted(missing))}")
    if UNRESOLVED_VARIABLE.search(resolved) and not missing:
        errors.append(f"{context}: contains an unresolved Terraform variable")
    return resolved


def parse_charts(source: str, variables: dict[str, object], errors: list[str]) -> dict[str, Chart]:
    charts: dict[str, Chart] = {}
    for groups, body in resource_blocks(source, CHART_RESOURCE):
        resource_type, label = groups
        if label in charts:
            errors.append(f"Terraform: duplicate chart label {label!r}")
            continue
        title = hcl_string(body, "name")
        if title is None:
            errors.append(f"Terraform chart {label!r}: missing literal name")
            title = ""
        title = resolve_variables(title, variables, f"Terraform chart {label!r} name", errors)
        item_match = re.search(r"^\s*#\s*telemetry-item:\s*(\S+)\s*$", body, re.M)
        item_id = item_match.group(1) if item_match else ""
        if not TELEMETRY_ITEM_ID.fullmatch(item_id):
            errors.append(
                f"Terraform chart {label!r}: missing stable '# telemetry-item: "
                "OTEL-###.<item> or SOURCE-METRIC.<exact-name>' provenance"
            )
        chart_type = CHART_TYPES[resource_type]
        if chart_type == "text":
            program_text = hcl_heredoc(body, "program_text") or hcl_string(body, "program_text")
            text = hcl_heredoc(body, "markdown") or hcl_string(body, "markdown")
            if program_text is not None:
                errors.append(f"Terraform text chart {label!r}: must not declare program_text")
            if text is None:
                errors.append(f"Terraform text chart {label!r}: missing markdown")
                text = ""
            text = resolve_variables(text, variables, f"Terraform text chart {label!r}", errors)
        else:
            program_text = hcl_heredoc(body, "program_text") or hcl_string(body, "program_text")
            text = None
            if program_text is None:
                errors.append(f"Terraform chart {label!r}: missing program_text")
                program_text = ""
            program_text = resolve_variables(
                program_text, variables, f"Terraform chart {label!r} program_text", errors
            )
            if not SERVICE_FILTER.search(program_text):
                errors.append(f"Terraform chart {label!r}: missing service.name or sf_service filter")
        charts[label] = Chart(label, title, resource_type, chart_type, program_text, text, item_id)
    if not charts:
        errors.append("Terraform: no supported signalfx_*_chart resources found")
    return charts


def hcl_integer(body: str, attribute: str) -> int | None:
    match = re.search(rf"^\s*{re.escape(attribute)}\s*=\s*(-?\d+)\s*$", body, re.M)
    return int(match.group(1)) if match is not None else None


def validate_layout(
    label: str,
    layout: tuple[int, int, int, int],
    context: str,
    errors: list[str],
) -> None:
    column, row, width, height = layout
    for name, value in zip(("column", "row", "width", "height"), layout):
        if value < OBSERVER_INT_MIN or value > OBSERVER_INT_MAX:
            errors.append(
                f"{context} chart {label!r}: {name} must fit the signed 64-bit "
                "Observer int range"
            )
    if column < 0 or column > 11:
        errors.append(f"{context} chart {label!r}: column must be between 0 and 11")
    if row < 0:
        errors.append(f"{context} chart {label!r}: row must be non-negative")
    if width < 1 or width > 12 or column + width > 12:
        errors.append(f"{context} chart {label!r}: width must fit within the 12-column grid")
    if height < 1:
        errors.append(f"{context} chart {label!r}: height must be positive")


def overlaps(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> bool:
    lc, lr, lw, lh = left
    rc, rr, rw, rh = right
    return lc < rc + rw and rc < lc + lw and lr < rr + rh and rr < lr + lh


def parse_placement_model(
    source: str,
    charts: dict[str, Chart],
    variables: dict[str, object],
    errors: list[str],
) -> tuple[dict[str, DashboardPlacement], DashboardTopology]:
    dashboard_groups: dict[str, str] = {}
    for resource_groups, group_body in resource_blocks(source, DASHBOARD_GROUP_RESOURCE):
        group_id = resource_groups[0]
        if group_id in dashboard_groups:
            errors.append(f"Terraform: duplicate dashboard group label {group_id!r}")
            continue
        group_name = hcl_string(group_body, "name")
        if group_name is None:
            errors.append(f"Terraform dashboard group {group_id!r}: missing literal name")
            group_name = ""
        dashboard_groups[group_id] = resolve_variables(
            group_name,
            variables,
            f"Terraform dashboard group {group_id!r} name",
            errors,
        )
    if not dashboard_groups:
        errors.append("Terraform: no signalfx_dashboard_group resource found")

    placements: dict[str, DashboardPlacement] = {}
    dashboards: list[tuple[str, str]] = []
    for resource_groups, dashboard_body in resource_blocks(source, DASHBOARD_RESOURCE):
        dashboard_id = resource_groups[0]
        dashboard_name = hcl_string(dashboard_body, "name")
        if dashboard_name is None:
            errors.append(f"Terraform dashboard {dashboard_id!r}: missing literal name")
            dashboard_name = ""
        dashboard_name = resolve_variables(
            dashboard_name,
            variables,
            f"Terraform dashboard {dashboard_id!r} name",
            errors,
        )
        group_reference = re.search(
            r"^\s*dashboard_group\s*=\s*signalfx_dashboard_group\.([A-Za-z0-9_]+)\.id\s*$",
            dashboard_body,
            re.M,
        )
        if group_reference is None:
            errors.append(
                f"Terraform dashboard {dashboard_id!r}: missing valid dashboard_group reference"
            )
            group_name = ""
        else:
            group_id = group_reference.group(1)
            group_name = dashboard_groups.get(group_id, "")
            if group_id not in dashboard_groups:
                errors.append(
                    f"Terraform dashboard {dashboard_id!r}: references unknown dashboard group {group_id!r}"
                )
        dashboards.append((group_name, dashboard_name))
        in_dashboard: list[tuple[str, tuple[int, int, int, int]]] = []
        dashboard_structure = hcl_structure_mask(dashboard_body)
        for chart_match in re.finditer(r"^\s*chart\s*\{", dashboard_body, re.M):
            if not dashboard_structure[chart_match.start()]:
                continue
            opening = dashboard_body.find("{", chart_match.start(), chart_match.end())
            closing = matching_brace(
                dashboard_body,
                opening,
                dashboard_structure,
            )
            body = dashboard_body[opening + 1 : closing]
            reference = re.search(
                r"^\s*chart_id\s*=\s*(signalfx_[A-Za-z0-9_]+_chart)\.([A-Za-z0-9_]+)\.id\s*$",
                body,
                re.M,
            )
            if reference is None:
                errors.append(f"Terraform dashboard {dashboard_id!r}: chart block has invalid chart_id")
                continue
            resource_type, label = reference.groups()
            if label not in charts:
                errors.append(f"Terraform dashboard {dashboard_id!r}: references unknown chart {label!r}")
            elif charts[label].resource_type != resource_type:
                errors.append(
                    f"Terraform dashboard {dashboard_id!r}: chart {label!r} references {resource_type}, expected {charts[label].resource_type}"
                )
            values = tuple(hcl_integer(body, name) for name in ("column", "row", "width", "height"))
            if any(value is None for value in values):
                errors.append(f"Terraform dashboard {dashboard_id!r} chart {label!r}: incomplete grid layout")
                continue
            layout = (values[0], values[1], values[2], values[3])
            if label in placements:
                errors.append(f"Terraform chart {label!r}: placed more than once")
                continue
            placements[label] = DashboardPlacement(
                layout=layout,
                dashboard=dashboard_name,
                group=group_name,
            )
            validate_layout(label, layout, f"Terraform dashboard {dashboard_id!r}", errors)
            for other_label, other_layout in in_dashboard:
                if overlaps(layout, other_layout):
                    errors.append(
                        f"Terraform dashboard {dashboard_id!r}: charts {other_label!r} and {label!r} overlap"
                    )
            in_dashboard.append((label, layout))
    for label in sorted(set(charts) - set(placements)):
        errors.append(f"Terraform chart {label!r}: not placed in a dashboard")
    return placements, DashboardTopology(
        groups=tuple(dashboard_groups.values()),
        dashboards=tuple(dashboards),
    )


def parse_placements(
    source: str,
    charts: dict[str, Chart],
    variables: dict[str, object],
    errors: list[str],
) -> dict[str, DashboardPlacement]:
    """Compatibility wrapper for callers that only need chart placements."""

    return parse_placement_model(source, charts, variables, errors)[0]


def required_string(row: dict[str, Any], key: str, context: str, errors: list[str]) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{context}: {key} must be a non-empty string")
        return ""
    return value.strip()


def parse_preview_model(
    path: Path, errors: list[str]
) -> tuple[dict[str, PreviewChart], DashboardTopology]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        errors.append(f"preview: invalid JSON: {error.msg}")
        return {}, DashboardTopology((), ())
    if (
        not isinstance(data, dict)
        or type(data.get("schemaVersion")) is not int
        or data.get("schemaVersion") != 1
    ):
        errors.append("preview: schemaVersion must equal 1")
        return {}, DashboardTopology((), ())
    groups = data.get("groups")
    if not isinstance(groups, list) or not groups:
        errors.append("preview: groups must be a non-empty array")
        return {}, DashboardTopology((), ())
    charts: dict[str, PreviewChart] = {}
    group_names: list[str] = []
    dashboard_names: list[tuple[str, str]] = []
    for group_index, group in enumerate(groups):
        if not isinstance(group, dict):
            errors.append(f"preview groups[{group_index}]: must be an object")
            continue
        group_context = f"preview groups[{group_index}]"
        group_name = required_string(group, "name", group_context, errors)
        group_names.append(group_name)
        dashboards = group.get("dashboards")
        if not isinstance(dashboards, list):
            errors.append(f"{group_context}: dashboards must be an array")
            continue
        for dashboard_index, dashboard in enumerate(dashboards):
            context = f"preview groups[{group_index}].dashboards[{dashboard_index}]"
            if not isinstance(dashboard, dict):
                errors.append(f"{context}: must be an object")
                continue
            dashboard_name = required_string(dashboard, "name", context, errors)
            dashboard_names.append((group_name, dashboard_name))
            rows = dashboard.get("charts")
            if not isinstance(rows, list):
                errors.append(f"{context}: charts must be an array")
                continue
            in_dashboard: list[tuple[str, tuple[int, int, int, int]]] = []
            for chart_index, row in enumerate(rows):
                chart_context = f"{context}.charts[{chart_index}]"
                if not isinstance(row, dict):
                    errors.append(f"{chart_context}: must be an object")
                    continue
                label = required_string(row, "label", chart_context, errors)
                title = required_string(row, "title", chart_context, errors)
                chart_type = required_string(row, "chartType", chart_context, errors)
                if chart_type not in set(CHART_TYPES.values()):
                    errors.append(f"{chart_context}: unsupported chartType {chart_type!r}")
                item_id = required_string(row, "telemetryItemId", chart_context, errors)
                if not TELEMETRY_ITEM_ID.fullmatch(item_id):
                    errors.append(
                        f"{chart_context}: telemetryItemId must be OTEL-###.<item> "
                        "or SOURCE-METRIC.<exact-name>"
                    )
                product_action = required_string(row, "productAction", chart_context, errors)
                program_text = row.get("programText")
                text = row.get("text")
                if chart_type == "text":
                    if program_text is not None:
                        errors.append(f"{chart_context}: text chart programText must be null")
                    if not isinstance(text, str) or not text.strip():
                        errors.append(f"{chart_context}: text chart text must be non-empty")
                        text = ""
                    else:
                        text = text.strip()
                else:
                    if not isinstance(program_text, str) or not program_text.strip():
                        errors.append(f"{chart_context}: programText must be a non-empty string")
                        program_text = ""
                    else:
                        program_text = program_text.strip("\r\n")
                    text = None
                    if UNRESOLVED_VARIABLE.search(program_text):
                        errors.append(f"{chart_context}: programText contains an unresolved Terraform variable")
                    if not SERVICE_FILTER.search(program_text):
                        errors.append(f"{chart_context}: missing service.name or sf_service filter")
                layout_row = row.get("layout")
                if not isinstance(layout_row, dict) or any(
                    type(layout_row.get(name)) is not int
                    for name in ("column", "row", "width", "height")
                ):
                    errors.append(f"{chart_context}: layout must contain integer column, row, width, and height")
                    layout = (0, 0, 0, 0)
                else:
                    layout = tuple(layout_row[name] for name in ("column", "row", "width", "height"))
                    validate_layout(label, layout, f"preview dashboard {dashboard_name!r}", errors)
                    for other_label, other_layout in in_dashboard:
                        if overlaps(layout, other_layout):
                            errors.append(
                                f"preview dashboard {dashboard_name!r}: charts {other_label!r} and {label!r} overlap"
                            )
                    in_dashboard.append((label, layout))
                if label in charts:
                    errors.append(f"preview: duplicate chart label {label!r}")
                    continue
                charts[label] = PreviewChart(
                    label,
                    title,
                    chart_type,
                    program_text,
                    text,
                    item_id,
                    product_action,
                    layout,
                    dashboard_name,
                    group_name,
                )
    return charts, DashboardTopology(
        groups=tuple(group_names),
        dashboards=tuple(dashboard_names),
    )


def parse_preview(path: Path, errors: list[str]) -> dict[str, PreviewChart]:
    """Compatibility wrapper for callers that only need preview charts."""

    return parse_preview_model(path, errors)[0]


def working_items(path: Path, errors: list[str]) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        errors.append(f"verification: invalid JSON: {error.msg}")
        return {}
    return working_items_data(data, errors)


def legacy_working_metrics(path: Path, errors: list[str]) -> set[str]:
    """Read directly proven Working metrics from a strict legacy reader report."""

    if not path.is_file():
        errors.append(f"legacy verification: missing Markdown report: {path}")
        return set()
    source = path.read_text(encoding="utf-8")
    results = LEGACY_VERIFY_RESULT.findall(source)
    if len(results) != 1:
        errors.append(
            "legacy verification: expected exactly one Result status, found "
            f"{len(results)}"
        )
        return set()
    report_result = results[0].lower()
    section = markdown_section(source, "Tested And Working")
    if section is None:
        errors.append("legacy verification: missing ## Tested And Working")
        return set()
    rows = exact_markdown_table(section, LEGACY_VERIFY_HEADERS, errors)
    if rows is None:
        errors.append(
            "legacy verification: ## Tested And Working must contain the full "
            "Item ID / OTel item / Type / Added or modified / Working status / "
            "How it was tested / Product result / visibility / Evidence contract"
        )
        return set()
    if not rows:
        errors.append("legacy verification: Tested And Working has no item rows")
        return set()

    metrics: set[str] = set()
    statuses: list[str] = []
    for index, row in enumerate(rows):
        context = f"legacy verification row {index + 1}"
        status = " ".join(row.get("Working status", "").lower().split())
        statuses.append(status)
        if status not in LEGACY_WORKING_STATUSES:
            errors.append(f"{context}: unsupported Working status {status!r}")
            continue
        if status != "working":
            continue
        row_errors = len(errors)
        if row.get("Type", "").strip().lower() != "metric":
            errors.append(f"{context}: Working dashboard proof must have Type metric")
        metric = row.get("OTel item", "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", metric):
            errors.append(f"{context}: OTel item must be one exact metric name")
        item_id = row.get("Item ID", "").strip()
        if not TELEMETRY_ITEM_ID.fullmatch(item_id):
            errors.append(f"{context}: Item ID must be a stable telemetry item ID")
        elif item_id != f"SOURCE-METRIC.{metric}":
            errors.append(
                f"{context}: Item ID must equal "
                f"'SOURCE-METRIC.{metric}' for the exact OTel item"
            )
        if not row.get("Added or modified", "").strip():
            errors.append(f"{context}: Added or modified must describe the item")

        tested = row.get("How it was tested", "").strip()
        tested_match = LEGACY_TEST_PROJECTION.fullmatch(tested)
        if tested_match is None:
            errors.append(
                f"{context}: How it was tested must be the exact proof_mode/scenarios projection"
            )
        else:
            proof_mode, scenario_text = tested_match.groups()
            scenarios = [value.strip() for value in scenario_text.split(",")]
            if proof_mode not in ITEM_DIRECT_PROOF_MODES:
                errors.append(f"{context}: Working metric needs an executed proof mode")
            if (
                not scenarios
                or scenarios == ["none"]
                or any(not LEGACY_SCENARIO_ID.fullmatch(value) for value in scenarios)
            ):
                errors.append(f"{context}: Working metric needs exact executed scenario IDs")

        product = row.get("Product result / visibility", "").strip()
        visibility_match = LEGACY_VISIBILITY_PROJECTION.search(product)
        if visibility_match is None:
            errors.append(f"{context}: product result must end with an explicit visibility state")
        else:
            product_result = product[: visibility_match.start()].strip(" ;")
            if not product_result:
                errors.append(f"{context}: product result must name the observed outcome")
            if visibility_match.group(1) == "not_proven":
                errors.append(f"{context}: Working metric cannot have visibility=not_proven")

        evidence = row.get("Evidence", "").strip()
        artifact_refs = list(LEGACY_DURABLE_ARTIFACT_REFERENCE.finditer(evidence))
        non_proof_artifact = any(
            NON_PROOF_LEGACY_ARTIFACT_LABEL.search(
                re.sub(r"[._/\\-]+", " ", match.group(0))
            )
            for match in artifact_refs
        )
        outcome_prose = LEGACY_DURABLE_ARTIFACT_REFERENCE.sub(" ", evidence)
        if (
            not evidence
            or non_proof_artifact
            or NEGATIVE_OR_UNCERTAIN_DIRECT_EVIDENCE.search(outcome_prose)
            or not LEGACY_DURABLE_EVIDENCE.search(evidence)
        ):
            errors.append(
                f"{context}: Working metric needs positive durable evidence, not source-only prose"
            )
        if len(errors) == row_errors:
            if metric in metrics:
                errors.append(f"{context}: duplicate Working metric {metric!r}")
            else:
                metrics.add(metric)

    if report_result in {"blocked", "not run"} and metrics:
        errors.append(
            f"legacy verification: Result {results[0]} cannot contain directly proven Working metrics"
        )
        metrics.clear()
    if report_result == "pass" and any(status != "working" for status in statuses):
        errors.append(
            "legacy verification: Result Pass requires every telemetry item row to be Working"
        )
    return metrics


def working_items_data(
    data: Any, errors: list[str]
) -> dict[str, dict[str, Any]]:
    if not isinstance(data, dict):
        errors.append("verification: root must be an object")
        return {}
    if data.get("schema_version") != 1:
        errors.append("verification: schema_version must equal 1")
    if data.get("kind") != "otel-verify":
        errors.append("verification: expected canonical kind otel-verify JSON")
    audit_id = data.get("audit_id")
    if not isinstance(audit_id, str) or not audit_id.strip():
        errors.append("verification: audit_id must be a non-empty string")
    for field in ("audit_sha256", "instrumentation_sha256"):
        value = data.get(field)
        if not isinstance(value, str) or not SHA256.fullmatch(value):
            errors.append(
                f"verification: {field} must be a canonical sha256:<64 lowercase hex> digest"
            )
    meta = data.get("meta")
    if not isinstance(meta, dict):
        errors.append("verification: meta must be an object")
    else:
        for field in ("service_name", "date"):
            value = meta.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"verification: meta.{field} must be a non-empty string")
        if meta.get("result") not in VERIFY_RESULTS:
            errors.append(f"verification: meta.result must be one of {sorted(VERIFY_RESULTS)}")
        if meta.get("workflow_mode") not in VERIFY_WORKFLOW_MODES:
            errors.append(
                "verification: meta.workflow_mode must be standalone or instrumentation_child"
            )
        if meta.get("lifecycle") not in VERIFY_LIFECYCLES:
            errors.append("verification: meta.lifecycle must be intermediate or final")
    findings = data.get("findings")
    if not isinstance(findings, list):
        errors.append("verification: findings must be an array")
        return {}
    working: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    finding_seen: set[str] = set()
    for finding_index, finding in enumerate(findings):
        finding_context = f"verification findings[{finding_index}]"
        if not isinstance(finding, dict):
            errors.append(f"{finding_context}: must be an object")
            continue
        finding_id = finding.get("id")
        if not isinstance(finding_id, str) or not OTEL_FINDING_ID.fullmatch(finding_id):
            errors.append(f"{finding_context}: id must be OTEL-###")
            finding_id = ""
        elif finding_id in finding_seen:
            errors.append(f"verification: duplicate finding ID {finding_id!r}")
        else:
            finding_seen.add(finding_id)
        if finding.get("status") not in VERIFY_FINDING_STATUSES:
            errors.append(
                f"{finding_context}: status must be one of {sorted(VERIFY_FINDING_STATUSES)}"
            )
        scenarios = finding.get("scenarios")
        scenario_ids: set[str] = set()
        if not isinstance(scenarios, list):
            errors.append(f"{finding_context}: scenarios must be an array")
        else:
            for scenario_index, scenario in enumerate(scenarios):
                scenario_context = f"{finding_context}.scenarios[{scenario_index}]"
                if not isinstance(scenario, dict):
                    errors.append(f"{scenario_context}: must be an object")
                    continue
                scenario_id = scenario.get("id")
                if not isinstance(scenario_id, str) or not scenario_id.strip():
                    errors.append(f"{scenario_context}: id must be a non-empty string")
                elif scenario_id in scenario_ids:
                    errors.append(f"{finding_context}: duplicate scenario ID {scenario_id!r}")
                else:
                    scenario_ids.add(scenario_id)
                if scenario.get("status") not in VERIFY_ITEM_STATUSES:
                    errors.append(
                        f"{scenario_context}: status must be one of {sorted(VERIFY_ITEM_STATUSES)}"
                    )
                if scenario.get("proof_mode") not in PROOF_MODES:
                    errors.append(f"{scenario_context}: proof_mode is not canonical")
                if scenario.get("visibility") not in VISIBILITY_STATES:
                    errors.append(f"{scenario_context}: visibility is not canonical")
        item_results = finding.get("item_results")
        if not isinstance(item_results, list):
            errors.append(f"{finding_context}: item_results must be an array")
            continue
        for item_index, item in enumerate(item_results):
            context = f"verification findings[{finding_index}].item_results[{item_index}]"
            if not isinstance(item, dict):
                errors.append(f"{context}: must be an object")
                continue
            item_errors = len(errors)
            item_id = item.get("id")
            if not isinstance(item_id, str) or not OTEL_ITEM_ID.fullmatch(item_id):
                errors.append(f"{context}: id must be OTEL-###.<item>")
                continue
            if finding_id and not item_id.startswith(f"{finding_id}."):
                errors.append(f"{context}: id must belong to finding {finding_id}")
            if item_id in seen:
                errors.append(f"verification: duplicate telemetry item ID {item_id!r}")
                continue
            seen.add(item_id)
            status = item.get("status")
            if status not in VERIFY_ITEM_STATUSES:
                errors.append(f"{context}: status must be one of {sorted(VERIFY_ITEM_STATUSES)}")
            direct_assertion = item.get("direct_assertion_passed")
            if not isinstance(direct_assertion, bool):
                errors.append(f"{context}: direct_assertion_passed must be a boolean")
            elif direct_assertion != (status == "working"):
                errors.append(
                    f"{context}: direct_assertion_passed must be true exactly when status is working"
                )
            proof_mode = item.get("proof_mode")
            visibility = item.get("visibility")
            if proof_mode not in PROOF_MODES:
                errors.append(f"{context}: proof_mode is not canonical")
            if visibility not in VISIBILITY_STATES:
                errors.append(f"{context}: visibility is not canonical")
            item_scenarios = item.get("scenarios")
            if not isinstance(item_scenarios, list) or not item_scenarios or not all(
                isinstance(entry, str) and entry.strip() for entry in item_scenarios
            ):
                errors.append(f"{context}: scenarios must be a non-empty string array")
            else:
                unknown_scenarios = sorted(set(item_scenarios) - scenario_ids)
                if unknown_scenarios:
                    errors.append(
                        f"{context}: scenarios contain unknown finding scenarios: {unknown_scenarios}"
                    )
            if status == "working":
                required_lists = {
                    "evidence": item.get("evidence"),
                    "observed_telemetry": item.get("observed_telemetry"),
                    "product_validation": item.get("product_validation"),
                }
                if proof_mode not in ITEM_DIRECT_PROOF_MODES:
                    errors.append(f"{context}: working item needs a direct executed proof_mode")
                if visibility == "not_proven":
                    errors.append(f"{context}: working item needs a known visibility state")
                for field, value in required_lists.items():
                    if not isinstance(value, list) or not value or not all(
                        isinstance(entry, str) and entry.strip() for entry in value
                    ):
                        errors.append(f"{context}: working item needs non-empty {field}")
                if len(errors) == item_errors:
                    working[item_id] = item
    return working


def validate_item_provenance(
    preview: dict[str, PreviewChart],
    verification_path: Path | None,
    instrumentation_items: dict[str, dict[str, Any]],
    allowed_source_only: set[str],
    source_metric_ids: set[str],
    errors: list[str],
    prevalidated_working: dict[str, dict[str, Any]] | None = None,
    legacy_working: set[str] | None = None,
) -> int:
    for item_id in sorted(allowed_source_only):
        if not SOURCE_METRIC_ID.fullmatch(item_id):
            errors.append(
                f"source-only item {item_id!r}: must be SOURCE-METRIC.<exact-metric-name>"
            )
        elif item_id not in source_metric_ids:
            errors.append(
                f"source-only item {item_id!r}: exact metric is absent from audit "
                "current_instrumentation.metrics"
            )
    working: dict[str, dict[str, Any]] = {}
    legacy_working = legacy_working or set()
    legacy_item_ids = {
        f"SOURCE-METRIC.{metric}" for metric in legacy_working
    }
    if verification_path is not None and verification_path.is_file():
        working = (
            prevalidated_working
            if prevalidated_working is not None
            else working_items(verification_path, errors)
        )
    elif not allowed_source_only and not legacy_working:
        errors.append(
            "verification: canonical otel-verify.json or explicit legacy Markdown "
            "Working metric proof is required unless every chart item is explicitly "
            "allowed with --allow-source-only-item"
        )
    chart_items = {chart.telemetry_item_id for chart in preview.values() if chart.telemetry_item_id}
    for chart in preview.values():
        if not SOURCE_METRIC_ID.fullmatch(chart.telemetry_item_id):
            continue
        metrics = DATA_METRIC.findall(chart.program_text or "")
        if chart.telemetry_item_id in legacy_item_ids:
            if metrics and (
                len(metrics) != 1
                or chart.telemetry_item_id != f"SOURCE-METRIC.{metrics[0]}"
            ):
                errors.append(
                    f"provenance: legacy-proven chart {chart.label!r} must use "
                    "SOURCE-METRIC.<exact data() metric>"
                )
            continue
        expected = f"SOURCE-METRIC.{metrics[0]}" if len(metrics) == 1 else ""
        if chart.telemetry_item_id != expected:
            errors.append(
                f"provenance: source-only chart {chart.label!r} must use "
                "SOURCE-METRIC.<exact data() metric>"
            )
    unknown = sorted(
        chart_items - set(working) - legacy_item_ids - allowed_source_only
    )
    for item_id in unknown:
        errors.append(f"provenance: chart item {item_id!r} is not a Working verification item")
    for chart in preview.values():
        item = working.get(chart.telemetry_item_id)
        if item is None:
            continue
        source_item = instrumentation_items.get(chart.telemetry_item_id)
        if source_item is None:
            errors.append(
                f"provenance: chart {chart.label!r} item {chart.telemetry_item_id!r} "
                "is absent from the bound instrumentation overlay"
            )
            continue
        if source_item.get("type") != "metric":
            errors.append(
                f"provenance: chart {chart.label!r} item {chart.telemetry_item_id!r} "
                f"has instrumentation type {source_item.get('type')!r}, expected 'metric'"
            )
        if chart.program_text is None:
            continue
        observed = " ".join(item.get("observed_telemetry", []))
        for metric in DATA_METRIC.findall(chart.program_text):
            if source_item.get("name") != metric:
                errors.append(
                    f"provenance: chart {chart.label!r} data() metric {metric!r} "
                    "does not exactly match bound instrumentation item name "
                    f"{source_item.get('name')!r}"
                )
            if not exact_metric_observed(metric, observed):
                errors.append(
                    f"provenance: chart {chart.label!r} metric {metric!r} is absent from "
                    f"working item {chart.telemetry_item_id!r} observed_telemetry"
                )
    unused_exceptions = sorted(allowed_source_only - chart_items)
    for item_id in unused_exceptions:
        errors.append(f"provenance: source-only exception {item_id!r} is not used by a chart")
    return len(working) + len(legacy_working)


def audit_source_metric_ids(path: Path, errors: list[str]) -> set[str]:
    """Return stable IDs for metrics explicitly observed in the canonical audit."""

    if not path.is_file():
        errors.append(
            "source-only provenance: canonical otel-audit.json is required for "
            "--allow-source-only-item"
        )
        return set()
    try:
        audit = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        errors.append(f"source-only provenance: cannot read canonical audit: {error}")
        return set()
    if not isinstance(audit, dict):
        errors.append("source-only provenance: canonical audit must be an object")
        return set()
    current = audit.get("current_instrumentation")
    if not isinstance(current, dict):
        errors.append(
            "source-only provenance: audit current_instrumentation must be an object"
        )
        return set()
    metrics = current.get("metrics")
    if not isinstance(metrics, list):
        errors.append(
            "source-only provenance: audit current_instrumentation.metrics must be a list"
        )
        return set()
    result: set[str] = set()
    for index, row in enumerate(metrics):
        if not isinstance(row, dict):
            errors.append(
                "source-only provenance: audit metric row "
                f"{index + 1} must be an object"
            )
            continue
        name = row.get("name")
        source = row.get("source")
        metric_type = row.get("type")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (name, source, metric_type)
        ):
            errors.append(
                "source-only provenance: every audit metric needs non-empty "
                "name, source, and type"
            )
            continue
        result.add(f"SOURCE-METRIC.{name}")
    return result


def exact_metric_observed(metric: str, observed: str) -> bool:
    """Require an exact, positive metric identifier in working proof prose."""
    identifier = r"A-Za-z0-9_"
    separators = r"._:/-"
    pattern = re.compile(
        rf"(?<![{identifier}])(?<![{identifier}][{separators}])"
        rf"{re.escape(metric)}(?![{identifier}])(?!(?:[{separators}][{identifier}]))",
        re.I,
    )
    for match in pattern.finditer(observed):
        if metric_mention_is_negated(observed, match):
            continue
        return True
    return False


def metric_mention_is_negated(observed: str, match: re.Match[str]) -> bool:
    before = observed[: match.start()]
    after = observed[match.end() :]
    boundary_matches = list(re.finditer(r"(?:[.!?;]\s+|\n+)", before))
    clause_start = boundary_matches[-1].end() if boundary_matches else 0
    clause_prefix = before[clause_start:]
    clause_end_match = re.search(r"(?:[.!?;]\s+|\n+)", after)
    clause_suffix = after[: clause_end_match.start()] if clause_end_match else after
    selector = re.match(r"^\s*\{[^{}\n]{0,256}\}", clause_suffix)
    if selector is not None:
        clause_suffix = clause_suffix[selector.end() :]
    return bool(
        METRIC_NEGATION_BEFORE.search(clause_prefix)
        or METRIC_NEGATION_AFTER.search(clause_suffix)
    )


def validate_bound_verification_flow(
    preview_path: Path,
    verification_path: Path | None,
    args: argparse.Namespace,
    errors: list[str],
    require_canonical: bool,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if verification_path is None or not verification_path.is_file():
        if require_canonical:
            errors.append(
                "verification flow: canonical otel-verify.json is required when "
                "canonical JSON input exists or a chart uses OTEL item provenance"
            )
        return {}, {}
    paths: dict[str, Path | None] = {}
    for name, filename in (
        ("audit", "otel-audit.json"),
        ("selection", "otel-selection.json"),
        ("instrumentation", "otel-instrumentation.json"),
    ):
        explicit = getattr(args, name, None)
        candidate = preview_path.parent / filename
        paths[name] = (
            explicit
            if explicit is not None
            else (candidate if candidate.is_file() else None)
        )
    missing = [name for name, path in paths.items() if path is None or not path.is_file()]
    if missing:
        if require_canonical or any(paths.values()):
            errors.append(
                "verification flow: canonical verification companions are incomplete; missing "
                + ", ".join(missing)
            )
        return {}, {}
    script = Path(__file__).parents[2] / "references" / "scripts" / "observe_report.py"
    if not script.is_file():
        errors.append(f"verification flow: missing shared validator {script}")
        return {}, {}
    try:
        source_paths = {**paths, "verification": verification_path}
        snapshots = {
            name: path.read_bytes()
            for name, path in source_paths.items()
            if path is not None
        }
    except OSError as error:
        errors.append(f"verification flow: cannot capture canonical overlays: {error}")
        return {}, {}

    try:
        instrumentation = json.loads(snapshots["instrumentation"])
        verification = json.loads(snapshots["verification"])
    except json.JSONDecodeError as error:
        errors.append(f"verification flow: cannot read canonical overlays: {error}")
        return {}, {}
    working = working_items_data(verification, errors)

    with tempfile.TemporaryDirectory(prefix="dashboard-flow-") as directory:
        snapshot_root = Path(directory)
        snapshot_paths = {
            name: snapshot_root / f"{name}.json" for name in snapshots
        }
        for name, value in snapshots.items():
            snapshot_paths[name].write_bytes(value)
        completed = subprocess.run(
            [
                sys.executable,
                str(script),
                "validate-flow",
                str(snapshot_paths["audit"]),
                "--selection-json",
                str(snapshot_paths["selection"]),
                "--instrumentation-json",
                str(snapshot_paths["instrumentation"]),
                "--verify-json",
                str(snapshot_paths["verification"]),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            errors.append(
                "verification flow: canonical audit/selection/instrumentation binding validation "
                f"failed{': ' + detail if detail else ''}"
            )
            return {}, {}
    items: dict[str, dict[str, Any]] = {}
    for finding in instrumentation.get("findings", []):
        for item in finding.get("telemetry_changes", []):
            item_id = item.get("id")
            if isinstance(item_id, str):
                items[item_id] = item
    return items, working


def markdown_cells(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith(r"\|"):
        text = text[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in text:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            cells.append("".join(current).strip().strip("`*"))
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    cells.append("".join(current).strip().strip("`*"))
    return cells


def markdown_section(source: str, heading: str) -> str | None:
    match = re.search(
        rf"^## {re.escape(heading)}\s*$\n(.*?)(?=^## |\Z)",
        source,
        re.M | re.S,
    )
    return match.group(1) if match is not None else None


def markdown_table(section: str, required_headers: tuple[str, ...]) -> list[dict[str, str]] | None:
    lines = [line for line in section.splitlines() if line.lstrip().startswith("|")]
    for index, line in enumerate(lines):
        header = markdown_cells(line)
        if all(name in header for name in required_headers):
            rows: list[dict[str, str]] = []
            for candidate in lines[index + 1 :]:
                cells = markdown_cells(candidate)
                if len(cells) != len(header):
                    continue
                if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                    continue
                rows.append(dict(zip(header, cells)))
            return rows
    return None


def exact_markdown_table(
    section: str,
    expected_header: tuple[str, ...],
    errors: list[str],
) -> list[dict[str, str]] | None:
    """Parse one contiguous table with an exact, unambiguous header."""

    lines = section.splitlines()
    table_indexes = [
        index
        for index, line in enumerate(lines)
        if line.lstrip().startswith("|")
        and (index == 0 or not lines[index - 1].lstrip().startswith("|"))
    ]
    if (
        len(table_indexes) != 1
        or tuple(markdown_cells(lines[table_indexes[0]])) != expected_header
    ):
        errors.append(
            "legacy verification: expected exactly one table with the exact "
            "item-proof header in the documented order"
        )
        return None
    index = table_indexes[0]
    if index + 1 >= len(lines):
        errors.append("legacy verification: item-proof table is missing its separator")
        return None
    separator = markdown_cells(lines[index + 1])
    if len(separator) != len(expected_header) or not all(
        re.fullmatch(r":?-{3,}:?", cell) for cell in separator
    ):
        errors.append("legacy verification: item-proof table has an invalid separator")
        return None

    rows: list[dict[str, str]] = []
    for candidate in lines[index + 2 :]:
        if not candidate.lstrip().startswith("|"):
            break
        cells = markdown_cells(candidate)
        if len(cells) != len(expected_header):
            errors.append(
                "legacy verification: item-proof row column count does not match "
                "the exact header"
            )
            return None
        rows.append(dict(zip(expected_header, cells)))
    return rows


def normalized_result(value: str) -> str:
    return " ".join(value.lower().replace("not-run", "not run").split())


def chart_metric_inventory(chart: PreviewChart) -> str:
    metrics = list(dict.fromkeys(DATA_METRIC.findall(chart.program_text or "")))
    return ", ".join(metrics) if metrics else "N/A"


def validate_report(
    source: str,
    preview: dict[str, PreviewChart],
    errors: list[str],
    *,
    allow_inherited_partial: bool = False,
) -> str | None:
    results = REPORT_RESULT.findall(source)
    if len(results) != 1:
        errors.append(f"report: expected exactly one Result status, found {len(results)}")
        result = None
    else:
        result = results[0].title()
    if not re.search(r"^\*\*Preview:\*\*.*\.observe/dashboards\.preview\.json", source, re.M):
        errors.append("report: Preview must name .observe/dashboards.preview.json")

    validation_section = markdown_section(source, "Preview And Validation")
    validation_rows: dict[str, dict[str, str]] = {}
    if validation_section is None:
        errors.append("report: missing ## Preview And Validation")
    else:
        rows = markdown_table(
            validation_section,
            ("Check", "Result", "What it proves", "Evidence / next step"),
        )
        if rows is None:
            errors.append(
                "report: Preview And Validation must contain the canonical proof table"
            )
        else:
            for row in rows:
                check = row.get("Check", "")
                if check in validation_rows:
                    errors.append(f"report: duplicate Preview And Validation row {check!r}")
                validation_rows[check] = row
                for field in ("What it proves", "Evidence / next step"):
                    value = row.get(field, "").strip()
                    if not value or normalized_result(value) in {"-", "none", "n/a", "todo"}:
                        errors.append(f"report: {check or '<unnamed>'} needs concrete {field}")
            for name in VALIDATION_ROWS:
                if name not in validation_rows:
                    errors.append(f"report: missing Preview And Validation row {name!r}")
    row_results = {
        name: normalized_result(row.get("Result", ""))
        for name, row in validation_rows.items()
    }
    direct_evidence = {
        "Verified metric item mapping": ("otel-", "source-metric.", "verification"),
        "Terraform ↔ preview parity": ("validator", "dashboards.tf", "dashboards.preview.json"),
        "Observer render": ("screenshot", "render witness", "/api/dashboards/preview"),
        "Live value sanity": ("query", "series", "recent window", "recent-window"),
    }
    for name, tokens in direct_evidence.items():
        row = validation_rows.get(name)
        if row is None or row_results.get(name) != "pass":
            continue
        evidence = normalized_result(row.get("Evidence / next step", ""))
        if not any(token in evidence for token in tokens):
            errors.append(f"report: {name} Pass row lacks direct evidence")
        row_text = normalized_result(" ".join(row.values()))
        if (
            NEGATIVE_OR_UNCERTAIN_DIRECT_EVIDENCE.search(row_text)
            or NEGATED_DIRECT_PROOF.search(row_text)
        ):
            errors.append(
                f"report: {name} Pass row contradicts its negative or uncertain evidence"
            )
    for name in VALIDATION_ROWS[:2]:
        if row_results.get(name) != "pass":
            errors.append(f"report: {name} must be Pass after deterministic validation")
    observer = row_results.get("Observer render")
    live_values = row_results.get("Live value sanity")
    for name, state in (("Observer render", observer), ("Live value sanity", live_values)):
        if state is not None and state not in {"pass", "not run", "blocked"}:
            errors.append(f"report: {name} must be Pass, Not run, or Blocked")
    if row_results.get("Publish/apply") != "not run":
        errors.append("report: Publish/apply must remain Not run for a local preview")
    if result == "Pass" and (observer != "pass" or live_values != "pass"):
        errors.append("report: Result Pass requires Observer render and Live value sanity to be Pass")
    if (
        result == "Partial"
        and observer == "pass"
        and live_values == "pass"
        and not allow_inherited_partial
    ):
        errors.append("report: Result Partial is inconsistent when all required preview checks pass")
    if result == "Blocked":
        errors.append("report: Result Blocked is inconsistent with validated Terraform/preview artifacts")

    panels_section = markdown_section(source, "Panels")
    if panels_section is None:
        errors.append("report: missing ## Panels")
        return result
    panel_rows = markdown_table(
        panels_section,
        (
            "Telemetry Item ID",
            "Panel",
            "Metric",
            "Chart Type",
            "Grid (col,row,w,h)",
            "Product action / rationale",
        ),
    )
    if panel_rows is None:
        errors.append("report: Panels must contain the canonical provenance table")
        return result
    expected: list[tuple[str, str, str, str, str, str]] = []
    for chart in preview.values():
        expected.append(
            (
                chart.telemetry_item_id,
                chart.title,
                chart_metric_inventory(chart),
                chart.chart_type,
                ",".join(str(value) for value in chart.layout),
                chart.product_action,
            )
        )
    actual = [
        (
            row.get("Telemetry Item ID", ""),
            row.get("Panel", ""),
            row.get("Metric", ""),
            row.get("Chart Type", ""),
            row.get("Grid (col,row,w,h)", "").replace(" ", ""),
            row.get("Product action / rationale", ""),
        )
        for row in panel_rows
    ]
    if sorted(actual) != sorted(expected):
        errors.append(
            "report: Panels rows do not exactly match preview "
            "item/title/metric/type/layout/product-action mappings"
        )
    return result


def compare_artifacts(
    terraform: dict[str, Chart],
    placements: dict[str, DashboardPlacement],
    terraform_topology: DashboardTopology,
    preview: dict[str, PreviewChart],
    preview_topology: DashboardTopology,
    errors: list[str],
) -> None:
    for label, left, right in (
        ("dashboard group", terraform_topology.groups, preview_topology.groups),
        ("dashboard", terraform_topology.dashboards, preview_topology.dashboards),
    ):
        left_counts = Counter(left)
        right_counts = Counter(right)
        for value, count in (left_counts - right_counts).items():
            errors.append(
                f"parity: Terraform {label} {value!r} is missing from preview "
                f"({count} unmatched)"
            )
        for value, count in (right_counts - left_counts).items():
            errors.append(
                f"parity: preview {label} {value!r} has no Terraform resource "
                f"({count} unmatched)"
            )
    terraform_labels = set(terraform)
    preview_labels = set(preview)
    for label in sorted(terraform_labels - preview_labels):
        errors.append(f"parity: Terraform chart {label!r} is missing from preview")
    for label in sorted(preview_labels - terraform_labels):
        errors.append(f"parity: preview chart {label!r} has no Terraform resource")
    for label in sorted(terraform_labels & preview_labels):
        hcl = terraform[label]
        sidecar = preview[label]
        if hcl.title != sidecar.title:
            errors.append(f"parity chart {label!r}: title differs")
        if hcl.chart_type != sidecar.chart_type:
            errors.append(f"parity chart {label!r}: chart type differs")
        if hcl.program_text != sidecar.program_text:
            errors.append(f"parity chart {label!r}: resolved query differs")
        if hcl.text != sidecar.text:
            errors.append(f"parity chart {label!r}: text content differs")
        if hcl.telemetry_item_id != sidecar.telemetry_item_id:
            errors.append(f"parity chart {label!r}: telemetry item provenance differs")
        placement = placements.get(label)
        if placement is None or placement.layout != sidecar.layout:
            errors.append(f"parity chart {label!r}: grid layout differs")
        if placement is not None and placement.dashboard != sidecar.dashboard:
            errors.append(f"parity chart {label!r}: dashboard name differs")
        if placement is not None and placement.group != sidecar.group:
            errors.append(f"parity chart {label!r}: dashboard group name differs")


def validate(args: argparse.Namespace) -> dict[str, object]:
    errors: list[str] = []
    terraform_path: Path = args.terraform
    preview_path: Path = args.preview
    report_path: Path = args.report
    for label, path in (
        ("Terraform", terraform_path),
        ("preview", preview_path),
        ("report", report_path),
    ):
        if not path.is_file():
            errors.append(f"missing {label}: {path}")
    if errors:
        return {"result": "FAIL", "errors": errors}
    variables_path: Path | None = getattr(args, "variables", None)
    if variables_path is None:
        candidate = terraform_path.parent / "variables.tf"
        variables_path = candidate if candidate.is_file() else None
    tfvars_path: Path | None = getattr(args, "tfvars", None)
    validate_sensitive_variables(variables_path, tfvars_path, errors)
    variables = variable_values(variables_path, tfvars_path)
    source = terraform_path.read_text(encoding="utf-8")
    terraform = parse_charts(source, variables, errors)
    placements, terraform_topology = parse_placement_model(
        source, terraform, variables, errors
    )
    preview, preview_topology = parse_preview_model(preview_path, errors)
    compare_artifacts(
        terraform,
        placements,
        terraform_topology,
        preview,
        preview_topology,
        errors,
    )
    verification_path: Path | None = getattr(args, "verification", None)
    if verification_path is None:
        candidate = preview_path.parent / "otel-verify.json"
        verification_path = candidate if candidate.is_file() else None
    canonical_candidates: dict[str, Path] = {}
    canonical_explicit = getattr(args, "verification", None) is not None
    downstream_explicit = getattr(args, "verification", None) is not None
    for name, filename in (
        ("audit", "otel-audit.json"),
        ("selection", "otel-selection.json"),
        ("instrumentation", "otel-instrumentation.json"),
    ):
        explicit = getattr(args, name, None)
        canonical_explicit = canonical_explicit or explicit is not None
        canonical_candidates[name] = explicit or preview_path.parent / filename
        if name in {"selection", "instrumentation"} and explicit is not None:
            downstream_explicit = True
    downstream_present = downstream_explicit or verification_path is not None or any(
        canonical_candidates[name].is_file()
        for name in ("selection", "instrumentation")
    )
    uses_otel_items = any(
        chart.telemetry_item_id
        and not SOURCE_METRIC_ID.fullmatch(chart.telemetry_item_id)
        for chart in preview.values()
    )
    require_canonical = downstream_present or uses_otel_items
    canonical_json_mode = (
        canonical_explicit
        or verification_path is not None
        or any(path.is_file() for path in canonical_candidates.values())
    )
    legacy_verification: Path | None = getattr(args, "legacy_verification", None)
    legacy_metrics: set[str] = set()
    if legacy_verification is not None:
        if canonical_json_mode:
            errors.append(
                "verification: legacy Markdown must not supplement or replace a "
                "canonical JSON flow"
            )
        else:
            legacy_metrics = legacy_working_metrics(legacy_verification, errors)
    source_only_items = set(getattr(args, "allow_source_only_item", []))
    source_metric_ids = (
        audit_source_metric_ids(canonical_candidates["audit"], errors)
        if source_only_items
        else set()
    )
    instrumentation_items, prevalidated_working = validate_bound_verification_flow(
        preview_path,
        verification_path,
        args,
        errors,
        require_canonical,
    )
    working_count = validate_item_provenance(
        preview,
        verification_path,
        instrumentation_items,
        source_only_items,
        source_metric_ids,
        errors,
        prevalidated_working,
        legacy_metrics,
    )
    reported_status = validate_report(
        report_path.read_text(encoding="utf-8"),
        preview,
        errors,
        allow_inherited_partial=getattr(args, "allow_inherited_partial", False),
    )
    return {
        "result": "PASS" if not errors else "FAIL",
        "chart_count": len(terraform),
        "preview_chart_count": len(preview),
        "working_verification_item_count": working_count,
        "reported_status": reported_status,
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate dashboard HCL, Observer preview JSON, and report parity."
    )
    parser.add_argument("--terraform", type=Path, required=True)
    parser.add_argument("--preview", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--variables", type=Path)
    parser.add_argument("--tfvars", type=Path)
    parser.add_argument("--verification", type=Path)
    parser.add_argument(
        "--legacy-verification",
        type=Path,
        help="explicit legacy otel-verify.md; valid only when no canonical JSON artifact exists",
    )
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--instrumentation", type=Path)
    parser.add_argument("--allow-source-only-item", action="append", default=[])
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
