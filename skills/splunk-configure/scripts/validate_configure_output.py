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
DATA_METRIC = re.compile(r"\bdata\(\s*['\"]([^'\"]+)['\"]")
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


def detector_blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for match in RESOURCE_START.finditer(text):
        opening = text.find("{", match.start())
        end = matching_brace(text, opening)
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
    blocks = detector_blocks(detectors_text)
    ids = [resource_id for resource_id, _ in blocks]
    if len(ids) != len(set(ids)):
        errors.append("duplicate signalfx_detector resource identifiers")

    declared = set(VARIABLE_DECLARATION.findall(variables_text))
    verified = working_metrics(args.verify_report)
    allowed = verified | set(args.allow_source_only_metric)
    detector_metrics: list[str] = []

    for resource_id, block in blocks:
        metrics = DATA_METRIC.findall(block)
        if len(metrics) != 1:
            errors.append(f"{resource_id}: expected exactly one data(...) metric, found {len(metrics)}")
            continue
        metric = metrics[0]
        detector_metrics.append(metric)
        if metric not in allowed:
            errors.append(f"{resource_id}: metric {metric!r} is not a Working verified metric")
        if metric not in report_text:
            errors.append(f"{resource_id}: metric {metric!r} is absent from detectors report")
        if not re.search(r"filter\(\s*['\"]service\.name['\"]\s*,", block):
            errors.append(f"{resource_id}: missing service.name filter")
        for variable in VARIABLE_REFERENCE.findall(block):
            if variable not in declared:
                errors.append(f"{resource_id}: referenced variable {variable!r} is not declared")
        labels = DETECT_LABEL.findall(block)
        if len(labels) != 1:
            errors.append(f"{resource_id}: expected one detect_label, found {len(labels)}")
        elif not re.search(rf"\.publish\(\s*['\"]{re.escape(labels[0])}['\"]\s*\)", block):
            errors.append(f"{resource_id}: detect_label {labels[0]!r} is not published by SignalFlow")
        for description, pattern in FORBIDDEN_PROGRAM_PATTERNS.items():
            if pattern.search(block):
                errors.append(f"{resource_id}: unsafe {description} appears in detector program")

    if len(detector_metrics) != len(set(detector_metrics)):
        errors.append("the same metric is assigned to more than one detector")
    if "api_token" not in declared:
        errors.append("variables.tf does not declare sensitive api_token")
    if "realm" not in declared:
        errors.append("variables.tf does not declare realm")
    provider_matches = list(PROVIDER_START.finditer(detectors_text))
    if len(provider_matches) != 1:
        errors.append(f"expected one signalfx provider block, found {len(provider_matches)}")
    else:
        opening = detectors_text.find("{", provider_matches[0].start())
        provider = detectors_text[provider_matches[0].start() : matching_brace(detectors_text, opening) + 1]
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
