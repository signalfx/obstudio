#!/usr/bin/env python3
"""Validate the reader-facing structure and per-OTel coverage of a verify report."""

from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType


REQUIRED_SECTIONS = (
    "What Changed",
    "Tested And Working",
    "Not Working Or Not Proven",
    "Proof",
)
EXPECTED_HEADER = (
    "Item ID",
    "OTel item",
    "Type",
    "Added or modified",
    "Working status",
    "How it was tested",
    "Product result / visibility",
    "Evidence",
)
ALLOWED_STATUSES = {"Working", "Not working", "Not proven", "Not configured"}
PLACEHOLDERS = {"", "n/a", "none", "tested", "verified", "unknown", "-"}
EMPTY_INVENTORY_MARKER = (
    "No telemetry items. Selected findings are proof-first verification scope."
)
JSON_STATUS_LABELS = {
    "working": "Working",
    "not_working": "Not working",
    "not_proven": "Not proven",
    "not_configured": "Not configured",
    "blocked": "Not proven",
}
PROOF_MODES = {
    "app_test",
    "unit",
    "unit+otlp",
    "full_runtime",
    "contract_only",
    "static",
    "not_run",
}
VISIBILITY_STATES = {
    "explorer_visible",
    "otlp_accepted",
    "not_explorer_visible",
    "not_proven",
    "not_applicable",
}


def normalize_item(value: str) -> str:
    """Compare item identities independently of reader-facing Markdown code style."""
    return re.sub(r"\s+", " ", value.replace("`", "")).strip()


def normalize_projection_cell(value: str) -> str:
    return normalize_item(re.sub(r"<br\s*/?>", "; ", value, flags=re.IGNORECASE))


def section_bounds(text: str, heading: str) -> tuple[int, int]:
    match = re.search(rf"^## {re.escape(heading)}\s*$", text, re.MULTILINE)
    if not match:
        raise ValueError(f"missing required section: ## {heading}")
    next_heading = re.search(r"^## ", text[match.end() :], re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(text)
    return match.start(), end


def split_row(line: str) -> tuple[str, ...]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith(r"\|"):
        text = text[:-1]
    return tuple(
        cell.replace(r"\|", "|").strip()
        for cell in re.split(r"(?<!\\)\|", text)
    )


def parse_signal_table(
    section: str, *, allow_empty_inventory: bool = False
) -> list[tuple[str, ...]]:
    lines = section.splitlines()
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        header = split_row(line)
        if header != EXPECTED_HEADER:
            continue
        separator = split_row(lines[index + 1]) if index + 1 < len(lines) else ()
        if len(separator) != len(EXPECTED_HEADER) or not all(
            re.fullmatch(r":?-+:?", cell.replace(" ", "")) for cell in separator
        ):
            raise ValueError("per-OTel table is missing its separator row")
        rows: list[tuple[str, ...]] = []
        for row_line in lines[index + 2 :]:
            if not row_line.lstrip().startswith("|"):
                break
            row = split_row(row_line)
            if len(row) != len(EXPECTED_HEADER):
                raise ValueError(
                    f"per-OTel row has {len(row)} columns, expected {len(EXPECTED_HEADER)}: {row_line}"
                )
            rows.append(row)
        if not rows and not (
            allow_empty_inventory
            and re.search(
                rf"^{re.escape(EMPTY_INVENTORY_MARKER)}$", section, re.MULTILINE
            )
        ):
            raise ValueError("per-OTel table has no item rows")
        return rows
    raise ValueError(
        "missing per-OTel table with header: " + " | ".join(EXPECTED_HEADER)
    )


def parse_gap_items(section: str) -> list[tuple[str, str]]:
    """Return exact item-ID and state cells from the reader-facing gap table."""
    lines = section.splitlines()
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        header = split_row(line)
        item_columns = [
            column_index
            for column_index, cell in enumerate(header)
            if cell in {"Item", "Item ID"}
        ]
        state_columns = [
            column_index
            for column_index, cell in enumerate(header)
            if cell == "State"
        ]
        if len(item_columns) != 1 or len(state_columns) != 1:
            continue
        separator = split_row(lines[index + 1]) if index + 1 < len(lines) else ()
        if len(separator) != len(header) or not all(
            re.fullmatch(r":?-+:?", cell.replace(" ", "")) for cell in separator
        ):
            continue
        item_column = item_columns[0]
        state_column = state_columns[0]
        items: list[tuple[str, str]] = []
        for row_line in lines[index + 2 :]:
            if not row_line.lstrip().startswith("|"):
                break
            row = split_row(row_line)
            if len(row) == len(header) and row[item_column]:
                items.append(
                    (
                        normalize_item(row[item_column]),
                        normalize_item(row[state_column]),
                    )
                )
        return items
    return []


def tested_projection(proof: dict) -> str:
    proof_mode = proof.get("proof_mode")
    if proof_mode not in PROOF_MODES:
        raise ValueError(
            f"{proof.get('id')}: verify proof_mode must be one of "
            f"{sorted(PROOF_MODES)}"
        )
    scenarios = proof.get("scenarios", [])
    if not isinstance(scenarios, list) or any(
        not isinstance(value, str) or not value.strip() for value in scenarios
    ):
        raise ValueError(f"{proof.get('id')}: verify scenarios must be string IDs")
    scenario_projection = ", ".join(scenarios) if scenarios else "none"
    return f"proof_mode={proof_mode}; scenarios={scenario_projection}"


def product_projection(proof: dict) -> str:
    visibility = proof.get("visibility")
    if visibility not in VISIBILITY_STATES:
        raise ValueError(
            f"{proof.get('id')}: verify visibility must be one of "
            f"{sorted(VISIBILITY_STATES)}"
        )
    product_validation = proof.get("product_validation", [])
    if not isinstance(product_validation, list) or any(
        not isinstance(value, str) or not value.strip()
        for value in product_validation
    ):
        raise ValueError(
            f"{proof.get('id')}: verify product_validation must be strings"
        )
    values = [*product_validation]
    values.append(f"visibility={visibility}")
    return "; ".join(values)


def load_expected_items(path: Path) -> set[str]:
    return {
        normalize_item(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def instrumentation_items(data: dict) -> list[dict]:
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != 1
        or data.get("kind") != "otel-instrumentation"
    ):
        raise ValueError(
            "instrumentation JSON must have schema_version 1 and kind otel-instrumentation"
        )
    selection_sha256 = data.get("selection_sha256")
    if not isinstance(selection_sha256, str) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", selection_sha256
    ):
        raise ValueError(
            "instrumentation selection_sha256 must be a canonical "
            "sha256:<64 lowercase hex> digest"
        )
    findings = data.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError("instrumentation findings must be a list")
    items: list[dict] = []
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("instrumentation findings must be objects")
        telemetry_changes = finding.get("telemetry_changes", [])
        if not isinstance(telemetry_changes, list):
            raise ValueError("instrumentation telemetry_changes must be a list")
        for item in telemetry_changes:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
                raise ValueError("every instrumentation telemetry change must have a nonempty id")
            items.append(item)
    item_ids = [item["id"].strip() for item in items]
    duplicates = sorted({item_id for item_id in item_ids if item_ids.count(item_id) > 1})
    if duplicates:
        raise ValueError("duplicate instrumentation telemetry item IDs: " + ", ".join(duplicates))
    return items


def load_instrumentation_items(path: Path) -> tuple[dict, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data, instrumentation_items(data)


def verify_items(data: dict) -> list[dict]:
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != 1
        or data.get("kind") != "otel-verify"
    ):
        raise ValueError("verify JSON must have schema_version 1 and kind otel-verify")
    findings = data.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError("verify findings must be a list")
    items: list[dict] = []
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("verify findings must be objects")
        item_results = finding.get("item_results", [])
        if not isinstance(item_results, list):
            raise ValueError("verify item_results must be a list")
        for item in item_results:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise ValueError("every verify item result must have a nonempty id")
            items.append(item)
    return items


def load_shared_report_module() -> ModuleType:
    shared = (
        Path(__file__).resolve().parents[2]
        / "references"
        / "scripts"
        / "observe_report.py"
    )
    if not shared.is_file():
        raise ValueError(f"shared canonical flow validator is missing: {shared}")
    spec = importlib.util.spec_from_file_location(
        "otel_reader_observe_report", shared
    )
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load shared canonical flow validator: {shared}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_canonical_flow(
    audit_json_path: Path,
    selection_json_path: Path,
    instrumentation_json_path: Path,
    verify_json_path: Path,
) -> tuple[dict, list[dict], dict, list[dict]]:
    module = load_shared_report_module()
    report = module.normalize_audit_report(module.load_json(audit_json_path))
    _selection, instrumentation, verification = module.load_flow(
        report,
        selection_json_path,
        instrumentation_json_path,
        verify_json_path,
    )
    if instrumentation is None or verification is None:
        raise ValueError(
            "canonical reader validation requires instrumentation and verify overlays"
        )
    return (
        instrumentation,
        instrumentation_items(instrumentation),
        verification,
        verify_items(verification),
    )


def validate(
    report: Path,
    expected_items_path: Path | None,
    instrumentation_json_path: Path | None,
    verify_json_path: Path | None,
    audit_json_path: Path | None,
    selection_json_path: Path | None,
) -> list[str]:
    text = report.read_text(encoding="utf-8")
    positions = []
    bounds = {}
    for section in REQUIRED_SECTIONS:
        start, end = section_bounds(text, section)
        positions.append(start)
        bounds[section] = (start, end)
    if positions != sorted(positions):
        raise ValueError("required reader sections are not in the expected order")

    instrumentation_data: dict | None = None
    instrumentation_items: list[dict] = []
    verify_data: dict | None = None
    verify_item_rows: list[dict] = []
    if instrumentation_json_path and verify_json_path:
        canonical_audit = audit_json_path or instrumentation_json_path.with_name(
            "otel-audit.json"
        )
        canonical_selection = (
            selection_json_path
            or instrumentation_json_path.with_name("otel-selection.json")
        )
        missing_context = [
            str(path)
            for path in (canonical_audit, canonical_selection)
            if not path.is_file()
        ]
        if missing_context:
            raise ValueError(
                "canonical verify projection requires --audit-json and "
                "--selection-json, or sibling otel-audit.json and "
                "otel-selection.json; missing: " + ", ".join(missing_context)
            )
        (
            instrumentation_data,
            instrumentation_items,
            verify_data,
            verify_item_rows,
        ) = load_canonical_flow(
            canonical_audit,
            canonical_selection,
            instrumentation_json_path,
            verify_json_path,
        )
    elif instrumentation_json_path:
        instrumentation_data, instrumentation_items = load_instrumentation_items(
            instrumentation_json_path
        )

    tested_start, tested_end = bounds["Tested And Working"]
    tested_section = text[tested_start:tested_end]
    rows = parse_signal_table(
        tested_section,
        allow_empty_inventory=(
            instrumentation_data is not None and not instrumentation_items
        ),
    )
    item_ids: list[str] = []
    item_labels: set[str] = set()
    non_working: dict[str, str] = {}
    errors: list[str] = []

    for item_id, item, item_type, changed, status, tested, product_result, evidence in rows:
        if not item_id:
            errors.append("a per-OTel row has an empty Item ID")
            continue
        if item_id in item_ids:
            errors.append(f"duplicate OTel item ID row: {item_id}")
        item_ids.append(item_id)
        if not item:
            errors.append("a per-OTel row has an empty item")
            continue
        item_identity = normalize_item(item)
        if instrumentation_data is None and item_identity in item_labels:
            errors.append(f"duplicate OTel item row: {item}")
        item_labels.add(item_identity)
        if not item_type:
            errors.append(f"{item}: Type is empty")
        if changed.casefold() in PLACEHOLDERS:
            errors.append(f"{item}: Added or modified is not specific")
        if status not in ALLOWED_STATUSES:
            errors.append(f"{item}: invalid Working status: {status}")
        if tested.casefold() in PLACEHOLDERS:
            errors.append(f"{item}: How it was tested is not specific")
        if product_result.casefold() in PLACEHOLDERS:
            errors.append(f"{item}: Product result / visibility is not specific")
        if status == "Working" and evidence.casefold() in PLACEHOLDERS:
            errors.append(f"{item}: Working row lacks direct evidence")
        if status != "Working":
            non_working[item_id] = status

    result_match = re.search(
        r"\*\*Individual result:\*\*\s*(\d+)\s*/\s*(\d+)\s+working\b",
        tested_section,
    )
    working_count = sum(1 for row in rows if row[4] == "Working")
    if not result_match:
        errors.append("Tested And Working is missing the Individual result summary")
    else:
        reported_working, reported_total = map(int, result_match.groups())
        if reported_working != working_count or reported_total != len(rows):
            errors.append(
                "Individual result count does not match the per-OTel table: "
                f"reported {reported_working}/{reported_total}, "
                f"actual {working_count}/{len(rows)}"
            )

    gaps_start, gaps_end = bounds["Not Working Or Not Proven"]
    gaps_section = text[gaps_start:gaps_end]
    gap_items = parse_gap_items(gaps_section)
    gap_item_ids = [item_id for item_id, _state in gap_items]
    expected_gap_states = {
        normalize_item(item_id): status for item_id, status in non_working.items()
    }
    expected_gap_ids = list(expected_gap_states)
    actual_gap_counts = Counter(gap_item_ids)
    missing_gap_ids = sorted(
        item for item in set(expected_gap_ids) if actual_gap_counts[item] == 0
    )
    duplicate_gap_ids = sorted(
        item for item, count in actual_gap_counts.items() if count > 1
    )
    unexpected_gap_ids = sorted(set(gap_item_ids) - set(expected_gap_ids))
    if non_working:
        for item in missing_gap_ids:
            errors.append(f"{item}: non-working item ID is missing from gap section")
    elif not re.search(r"\bNone\b", gaps_section):
        errors.append("all rows are Working but the gap section does not say None")
    if duplicate_gap_ids:
        errors.append(
            "duplicate item IDs in Not Working Or Not Proven: "
            + ", ".join(duplicate_gap_ids)
        )
    if unexpected_gap_ids:
        errors.append(
            "unexpected item IDs in Not Working Or Not Proven: "
            + ", ".join(unexpected_gap_ids)
        )
    for item_id, state in gap_items:
        expected_state = expected_gap_states.get(item_id)
        if expected_state is not None and state != expected_state:
            errors.append(
                f"{item_id}: gap State {state!r} does not match "
                f"Working status {expected_state!r}"
            )

    if expected_items_path:
        expected_items = load_expected_items(expected_items_path)
        missing = sorted(expected_items - item_labels)
        unexpected = sorted(item_labels - expected_items)
        if missing:
            errors.append("missing expected OTel items: " + ", ".join(missing))
        if unexpected:
            errors.append("unexpected OTel items: " + ", ".join(unexpected))

    if instrumentation_json_path:
        expected_item_ids = [item["id"].strip() for item in instrumentation_items]
        if item_ids != expected_item_ids:
            missing = [item_id for item_id in expected_item_ids if item_id not in item_ids]
            unexpected = [item_id for item_id in item_ids if item_id not in expected_item_ids]
            if missing:
                errors.append("missing instrumentation item IDs: " + ", ".join(missing))
            if unexpected:
                errors.append("unexpected instrumentation item IDs: " + ", ".join(unexpected))
            if not missing and not unexpected:
                errors.append("per-OTel item IDs are not in instrumentation order")

    if verify_json_path:
        if instrumentation_data is None:
            errors.append("--verify-json requires --instrumentation-json")
        else:
            if verify_data is None:
                errors.append(
                    "canonical verify projection could not load the bound flow"
                )
                verify_data = {}
            verify_items = verify_item_rows
            if verify_data.get("audit_id") != instrumentation_data.get("audit_id"):
                errors.append("verify audit_id does not match instrumentation JSON")
            if verify_data.get("audit_sha256") != instrumentation_data.get("audit_sha256"):
                errors.append("verify audit_sha256 does not match instrumentation JSON")
            verify_ids = [item.get("id") for item in verify_items]
            instrumentation_ids = [item.get("id") for item in instrumentation_items]
            if verify_ids != instrumentation_ids:
                errors.append(
                    "verify item IDs/order do not match instrumentation telemetry changes"
                )
            result_match = re.search(
                r"^\*\*Result:\*\*\s*(Pass|Partial|Fail|Blocked|Not run)\s*$",
                text,
                re.MULTILINE,
            )
            verify_meta = verify_data.get("meta")
            if not isinstance(verify_meta, dict):
                errors.append("verify meta must be an object")
                verify_result = None
            else:
                verify_result = verify_meta.get("result")
            if result_match is None or result_match.group(1) != verify_result:
                errors.append(
                    "reader Result does not match verify JSON: "
                    f"markdown={result_match.group(1) if result_match else 'missing'}, "
                    f"verify={verify_result}"
                )
            if len(rows) == len(instrumentation_items) == len(verify_items):
                for row, source, proof in zip(
                    rows, instrumentation_items, verify_items, strict=True
                ):
                    status = JSON_STATUS_LABELS.get(proof.get("status"))
                    if status is None:
                        errors.append(
                            f"{proof.get('id')}: unsupported verify status {proof.get('status')}"
                        )
                        continue
                    expected_row = (
                        source.get("id", ""),
                        source.get("name", ""),
                        source.get("type", ""),
                        source.get("change", ""),
                        status,
                        tested_projection(proof),
                        product_projection(proof),
                        "; ".join(proof.get("evidence", [])),
                    )
                    if tuple(map(normalize_projection_cell, row)) != tuple(
                        map(normalize_projection_cell, expected_row)
                    ):
                        errors.append(
                            f"{source.get('id')}: reader row disagrees with bound "
                            "instrumentation/verify JSON projection"
                        )

    if errors:
        raise ValueError("\n".join(errors))
    return item_ids


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--expected-items-file", type=Path)
    parser.add_argument("--instrumentation-json", type=Path)
    parser.add_argument("--verify-json", type=Path)
    parser.add_argument("--audit-json", type=Path)
    parser.add_argument("--selection-json", type=Path)
    args = parser.parse_args()
    try:
        items = validate(
            args.report,
            args.expected_items_file,
            args.instrumentation_json,
            args.verify_json,
            args.audit_json,
            args.selection_json,
        )
    except (OSError, ValueError) as error:
        print(f"reader report validation failed:\n{error}", file=sys.stderr)
        return 1
    print(f"reader report validation passed: {len(items)} individual OTel items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
