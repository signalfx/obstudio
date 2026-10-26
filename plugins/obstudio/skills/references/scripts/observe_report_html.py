"""HTML rendering for the structured OTel report workflow."""

from __future__ import annotations

import hashlib
import html
import importlib.util
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote


def _load_sibling(filename: str) -> Any:
    path = Path(__file__).resolve().with_name(filename)
    name = f"_{path.stem}_{hashlib.sha256(str(path).encode()).hexdigest()[:16]}"
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return module


_core = _load_sibling("observe_report_core.py")
EXECUTABLE_MODES = _core.EXECUTABLE_MODES
MODE_GUIDANCE = _core.MODE_GUIDANCE
PRIORITY_RANK = _core.PRIORITY_RANK
RESULT_STATUSES = _core.RESULT_STATUSES
UNRESOLVED_FINDING_STATUSES = _core.UNRESOLVED_FINDING_STATUSES
ao_target_eligible_finding_ids = _core.ao_target_eligible_finding_ids
decision_answer_map = _core.decision_answer_map
fail = _core.fail
finding_selection_eligibility = _core.finding_selection_eligibility
instrumentation_digest = _core.instrumentation_digest
report_selection_eligibility = _core.report_selection_eligibility
script_json = _core.script_json
selected_decision_option = _core.selected_decision_option
selection_blockers = _core.selection_blockers
selection_digest = _core.selection_digest


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def reader_prose(value: str) -> str:
    """Hide schema spelling and opaque correlation IDs in reader-facing HTML."""
    replacements = {
        "not_proven": "not proven",
        "not_working": "not working",
        "not_configured": "not configured",
    }
    result = value
    for token, label in replacements.items():
        result = re.sub(rf"\b{token}\b", label, result, flags=re.IGNORECASE)
    trace_id = r"[0-9a-f]{32}"
    span_id = r"[0-9a-f]{16}"
    result = re.sub(
        rf"\btraceId\s*=\s*{trace_id}\s+and\s+spanId\s*=\s*{span_id}\b",
        "the generated trace context",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(
        rf"^(?:(?:bounded|live)\s+)?trace(?:\s+id)?\s+{trace_id}\b",
        "The generated trace",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(
        rf"\bthe\s+same\s+(?:(?:bounded|live)\s+)?trace(?:\s+id)?\s+{trace_id}\b",
        "the same generated trace",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(
        rf"\b(?:(?:bounded|live)\s+)?trace(?:\s+id)?\s+{trace_id}\b",
        "the generated trace",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(
        rf"\btraceId\s*=\s*{trace_id}\b",
        "the generated trace",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(
        rf"\bspanId\s*=\s*{span_id}\b",
        "the generated span",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(
        rf"\btrace(?:[_\-.]?id)\s*[:=]\s*{trace_id}\b",
        "the generated trace",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(
        rf"\bspan(?:[_\-.]?id)\s*[:=]\s*{span_id}\b",
        "the generated span",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(rf"\s*\(\s*{span_id}\s*\)", "", result, flags=re.IGNORECASE)
    result = re.sub(
        rf"\bspan\s+{span_id}\b",
        "span",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(rf"(?<![0-9a-f]){trace_id}(?![0-9a-f])", "generated-trace", result, flags=re.IGNORECASE)
    result = re.sub(rf"(?<![0-9a-f]){span_id}(?![0-9a-f])", "generated-span", result, flags=re.IGNORECASE)
    return result


def implementation_check_text(value: str) -> str:
    value = re.sub(
        r"^(?:final verification|instrumentation-phase snapshot)\s*:\s*",
        "",
        value.strip(),
        flags=re.IGNORECASE,
    )
    return reader_prose(value)


def render_list(items: list[str]) -> str:
    if not items:
        return "<p class=\"muted\">None recorded.</p>"
    return "<ul>" + "".join(f"<li>{esc(reader_prose(item))}</li>" for item in items) + "</ul>"


def finding_product_view(finding: dict[str, Any]) -> str:
    return finding["product_outcome"]


def display_finding_ids(report: dict[str, Any]) -> list[str]:
    """Return stable display order without mutating digest-bound canonical order."""
    indexed = list(enumerate(report["findings"]))
    indexed.sort(
        key=lambda pair: (
            PRIORITY_RANK[pair[1]["priority"]],
            pair[0],
        )
    )
    return [finding["id"] for _, finding in indexed]


def decision_overview(
    report: dict[str, Any],
    decision_answers: list[dict[str, str]] | dict[str, str] | None = None,
) -> dict[str, Any]:
    findings = report["findings"]
    answers = decision_answer_map(decision_answers)
    buckets: dict[str, list[dict[str, Any]]] = {
        "fix_now": [],
        "decide_now": [],
        "consider_next": [],
        "consider_later": [],
        "decide_first": [],
        "blocked": [],
        "external_follow_up": [],
        "decision_recorded": [],
    }
    for finding in findings:
        blockers = selection_blockers(report, finding["id"], answers)
        if finding["instrument_mode"] == "external follow-up":
            bucket = "external_follow_up"
        elif finding["instrument_mode"] == "manual decision":
            bucket = (
                "decision_recorded"
                if selected_decision_option(finding, answers.get(finding["id"]))
                else "decide_now"
                if finding["priority"] == "required"
                else "decide_first"
            )
        elif blockers:
            bucket = "blocked"
        elif finding["priority"] == "required":
            bucket = "fix_now"
        elif finding["priority"] == "recommended":
            bucket = "consider_next"
        else:
            bucket = "consider_later"
        buckets[bucket].append(finding)

    return {
        "priority_counts": {
            priority: sum(finding["priority"] == priority for finding in findings)
            for priority in ("required", "recommended", "deferred")
        },
        "effort_counts": {
            effort: sum(finding["effort"] == effort for finding in findings)
            for effort in ("small", "medium", "large", "decision")
        },
        "source_counts": {
            "routes": len(report["routes"]),
            "spans": len(report["current_instrumentation"]["spans"]),
            "metrics": len(report["current_instrumentation"]["metrics"]),
            "logs": len(report["current_instrumentation"]["logs"]),
        },
        "quick_wins": [
            finding
            for finding in findings
            if finding["effort"] == "small"
            and finding_selection_eligibility(
                report, finding["id"], answers
            )["selectable"]
        ],
        "buckets": buckets,
    }


def decision_summary_bullets(report: dict[str, Any]) -> list[str]:
    overview = decision_overview(report)
    source = overview["source_counts"]
    eligibility = report_selection_eligibility(report)
    findings_by_id = {finding["id"]: finding for finding in report["findings"]}
    ordered_findings = [
        findings_by_id[finding_id] for finding_id in display_finding_ids(report)
    ]
    active_findings = [
        finding
        for finding in ordered_findings
        if finding["status"] in UNRESOLVED_FINDING_STATUSES
    ]
    lead = next(
        (
            finding
            for finding in active_findings
            if eligibility[finding["id"]]["selectable"]
        ),
        None,
    )
    bullets = [
        f"{len(report['findings'])} findings are listed in highest-priority-first order.",
        (
            "Repository evidence identifies "
            f"{source['routes']} routes, {source['spans']} span entries, "
            f"{source['metrics']} metric entries, and {source['logs']} log integrations."
        ),
    ]
    if lead is not None:
        lead_outcome = finding_product_view(lead).rstrip()
        outcome_suffix = "" if lead_outcome.endswith((".", "!", "?")) else "."
        bullets.append(
            f"Start with {lead['id']} — {lead['title']}. "
            f"Expected result: {lead_outcome}{outcome_suffix}"
        )
    if report.get("scan_blockers"):
        bullets.append(
            "Scan blocked: "
            + "; ".join(
                f"{blocker['id']} — {blocker['prerequisite']} "
                f"(next: {blocker['required_action']})"
                for blocker in report["scan_blockers"]
            )
        )
    actions: list[str] = []
    selectable = sum(
        eligibility[finding["id"]]["selectable"] for finding in active_findings
    )
    if selectable:
        actions.append(
            f"select from {selectable} executable "
            f"{'item' if selectable == 1 else 'items'}"
        )
    open_decisions = sum(
        finding["instrument_mode"] == "manual decision"
        for finding in active_findings
    )
    if open_decisions:
        actions.append(
            f"answer {open_decisions} telemetry owner "
            f"{'decision' if open_decisions == 1 else 'decisions'}"
        )
    blocked = sum(
        finding["instrument_mode"] in EXECUTABLE_MODES
        and bool(eligibility[finding["id"]]["blockers"])
        for finding in active_findings
    )
    if blocked:
        actions.append(
            f"resolve prerequisites for {blocked} blocked "
            f"{'item' if blocked == 1 else 'items'}"
        )
    external = sum(
        finding["instrument_mode"] == "external follow-up"
        for finding in active_findings
    )
    if external:
        actions.append(
            f"track {external} external "
            f"{'follow-up' if external == 1 else 'follow-ups'} outside instrumentation"
        )
    if actions:
        bullets.append("Next: " + "; ".join(actions) + ".")
    return bullets


SOURCE_LOCATION_SUFFIX = re.compile(r":\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*$")
SOURCE_NOTE_SUFFIX = re.compile(r"(?P<note>\s+\(.*\))$")
SOURCE_PATH = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")


def split_source_segments(value: str) -> list[str]:
    """Split semicolon-delimited references while preserving parenthetical notes."""
    segments: list[str] = []
    depth = 0
    start = 0
    index = 0
    while index < len(value):
        character = value[index]
        if character == "(":
            depth += 1
        elif character == ")" and depth:
            depth -= 1
        elif character == ";" and depth == 0:
            segments.append(value[start:index])
            end = index + 1
            while end < len(value) and value[end].isspace():
                end += 1
            segments.append(value[index:end])
            start = end
            index = end - 1
        index += 1
    segments.append(value[start:])
    return [segment for segment in segments if segment]


def source_reference_parts(
    value: str,
    source_root: Path,
    output_dir: Path,
) -> list[dict[str, str]] | None:
    """Resolve safe repository-relative source citations into display parts."""
    root = source_root.resolve()
    output = output_dir.resolve()
    parts: list[dict[str, str]] = []
    linked = False

    for segment in split_source_segments(value):
        if segment.startswith(";"):
            parts.append({"text": segment})
            continue

        leading = segment[: len(segment) - len(segment.lstrip())]
        trailing = segment[len(segment.rstrip()) :]
        core = segment.strip()
        if not core:
            parts.append({"text": segment})
            continue

        note = ""
        note_match = SOURCE_NOTE_SUFFIX.search(core)
        if note_match:
            note = note_match.group("note")
            core = core[: note_match.start()]

        location = ""
        location_match = SOURCE_LOCATION_SUFFIX.search(core)
        if location_match:
            location = location_match.group(0)
            path_text = core[: location_match.start()]
        else:
            path_text = core

        relative_path = Path(path_text)
        candidate: Path | None = None
        if (
            path_text
            and SOURCE_PATH.fullmatch(path_text)
            and not relative_path.is_absolute()
            and ".." not in relative_path.parts
            and "://" not in path_text
        ):
            try:
                resolved = (root / relative_path).resolve()
                resolved.relative_to(root)
            except (OSError, ValueError):
                pass
            else:
                try:
                    if resolved.is_file():
                        candidate = resolved
                except OSError:
                    pass

        if candidate is None:
            parts.append({"text": segment})
            continue

        relative_href = Path(os.path.relpath(candidate, output)).as_posix()
        href = quote(relative_href, safe="/._-~")
        if location:
            first_location = location[1:].split(",", 1)[0]
            href += "#L" + first_location.replace("-", "-L", 1)
        if leading:
            parts.append({"text": leading})
        parts.append({"text": f"{path_text}{location}", "href": href})
        if note:
            parts.append({"text": note})
        if trailing:
            parts.append({"text": trailing})
        linked = True

    return parts if linked else None


def iter_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_strings(item)


def build_source_references(
    documents: list[Any],
    source_root: Path,
    output_dir: Path,
) -> dict[str, list[dict[str, str]]]:
    references: dict[str, list[dict[str, str]]] = {}
    for document in documents:
        for value in iter_strings(document):
            if value in references:
                continue
            parts = source_reference_parts(value, source_root, output_dir)
            if parts:
                references[value] = parts
    return {value: references[value] for value in sorted(references)}


def source_reference_html(value: Any, references: dict[str, list[dict[str, str]]]) -> str:
    parts = references.get(str(value))
    if not parts:
        return esc(reader_prose(str(value)))
    return "".join(
        (
            f'<a class="source-link" href="{esc(part["href"])}" target="_blank" '
            f'rel="noopener" title="Open local source file"><code>{esc(reader_prose(part["text"]))}</code>'
            '<span class="source-open" aria-hidden="true">↗</span></a>'
            if part.get("href")
            else esc(reader_prose(part["text"]))
        )
        for part in parts
    )


def html_table(
    headers: list[str],
    rows: list[list[Any]],
    *,
    source_columns: set[int] | None = None,
    source_references: dict[str, list[dict[str, str]]] | None = None,
) -> str:
    head = "".join(f"<th>{esc(header)}</th>" for header in headers)
    source_columns = source_columns or set()
    source_references = source_references or {}
    body = "".join(
        "<tr>"
        + "".join(
            f"<td>{source_reference_html(cell, source_references) if index in source_columns else esc(reader_prose(str(cell)))}</td>"
            for index, cell in enumerate(row)
        )
        + "</tr>"
        for row in rows
    )
    if not body:
        body = f'<tr><td colspan="{len(headers)}" class="muted">None recorded.</td></tr>'
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def render_decision_overview(
    report: dict[str, Any],
    selection: dict[str, Any] | None = None,
) -> str:
    current = report["current_instrumentation"]
    baseline = (
        f"Source inventory: {len(report['routes'])} routes · "
        f"{len(current['spans'])} span entries · "
        f"{len(current['metrics'])} metric entries · "
        f"{len(current['logs'])} log integrations."
    )
    return (
        '<div class="decision-context">'
        '<section><h3>Current baseline</h3>'
        f'<p>{esc(baseline)}</p></section>'
        '</div>'
        '<p class="review-note"><strong>Review order:</strong> findings are '
        'ordered by priority, highest first. Select executable work on its '
        'card; answer a telemetry choice only where the card asks for one.</p>'
    )


def instrumentation_proof_counts(
    instrumentation: dict[str, Any],
    verify: dict[str, Any] | None,
) -> dict[str, int]:
    telemetry_items = [
        item
        for finding in instrumentation["findings"]
        for item in finding["telemetry_changes"]
    ]
    verify_findings = (verify or {}).get("findings", [])
    scenarios = [
        scenario for finding in verify_findings for scenario in finding["scenarios"]
    ]
    item_results = [
        item for finding in verify_findings for item in finding["item_results"]
    ]
    return {
        "findings": len(instrumentation["findings"]),
        "telemetry_items": len(telemetry_items),
        "items_exercised": sum(
            item["proof_mode"] != "not_run" for item in item_results
        ),
        "items_working": sum(item["status"] == "working" for item in item_results),
        "items_product_visible": sum(
            item["visibility"] == "explorer_visible" for item in item_results
        ),
        "items_otlp_accepted": sum(
            item["visibility"] == "otlp_accepted" for item in item_results
        ),
        "scenarios_product_visible": sum(
            scenario["visibility"] == "explorer_visible" for scenario in scenarios
        ),
        "scenarios_otlp_accepted": sum(
            scenario["visibility"] == "otlp_accepted" for scenario in scenarios
        ),
        "findings_working": sum(
            finding["status"] == "working" for finding in verify_findings
        ),
        "findings_failed": sum(
            finding["status"] == "not_working" for finding in verify_findings
        ),
        "scenarios": len(scenarios),
        "scenarios_working": sum(
            scenario["status"] == "working" for scenario in scenarios
        ),
        "scenarios_blocked": sum(
            scenario["status"] == "blocked" for scenario in scenarios
        ),
        "scenarios_not_proven": sum(
            scenario["status"] == "not_proven"
            and scenario["proof_mode"] != "not_run"
            for scenario in scenarios
        ),
        "scenarios_not_run": sum(
            scenario["status"] == "not_proven"
            and scenario["proof_mode"] == "not_run"
            for scenario in scenarios
        ),
        "scenarios_not_configured": sum(
            scenario["status"] == "not_configured" for scenario in scenarios
        ),
        "scenarios_failed": sum(
            scenario["status"] == "not_working" for scenario in scenarios
        ),
    }


def human_verification_label(
    verification_result: str,
    failed_findings: int,
) -> str:
    if verification_result == "Pass":
        return "verification complete"
    if verification_result == "Partial" and failed_findings == 0:
        return "verification incomplete"
    if verification_result == "Fail":
        return "verification failed"
    if verification_result == "Blocked":
        return "verification blocked"
    if verification_result == "Not run":
        return "verification not run"
    return verification_result.lower()


def human_finding_proof_status(status: str, verify_present: bool) -> str:
    if not verify_present:
        return "verification not run"
    return {
        "working": "verified",
        "not_proven": "verification incomplete",
        "not_working": "verification failed",
        "not_configured": "implementation incomplete",
        "deferred": "deferred",
    }.get(status, status.replace("_", " "))


def human_item_proof_status(item: dict[str, Any] | None) -> str:
    if item is None:
        return "verification has not produced item proof"
    status = item["status"]
    if status == "working":
        return "proven"
    if status == "not_working":
        return "executed check failed"
    if status == "blocked":
        return "blocked by prerequisite"
    if status == "not_proven" and item["proof_mode"] != "not_run":
        return "executed evidence is unresolved"
    return {
        "not_proven": "not checked",
        "not_configured": "not implemented",
        "deferred": "deferred",
    }.get(status, status.replace("_", " "))


def human_proof_mode(value: str) -> str:
    return {
        "app_test": "application test",
        "unit": "unit test",
        "unit+otlp": "unit + OTLP",
        "full_runtime": "runtime",
        "contract_only": "contract check",
        "static": "static check",
        "not_run": "not run",
    }.get(value, value.replace("_", " "))


def human_visibility(value: str) -> str:
    return {
        "explorer_visible": "confirmed in target product",
        "otlp_accepted": "accepted by the OTLP receiver",
        "not_explorer_visible": "target-product check not run",
        "not_proven": "delivery not proven",
        "not_applicable": "product check not applicable",
    }.get(value, value.replace("_", " "))


def audit_scenarios_by_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        scenario["id"]: scenario
        for scenario in report.get("verification", {}).get("scenarios", [])
    }


def scenario_reader_label(
    scenario: dict[str, Any],
    audit_scenarios: dict[str, dict[str, Any]],
) -> str:
    audit_scenario = audit_scenarios.get(scenario["id"], {})
    return audit_scenario.get("trigger") or scenario["id"].replace(".", " ").replace(
        "-", " "
    )


def telemetry_change_reader_label(item: dict[str, Any]) -> str:
    action = {
        "added": "Added",
        "modified": "Modified",
        "removed": "Removed",
    }.get(item["change_kind"], item["change_kind"].title())
    return f'{action} {item["type"]}: {item["name"]}'


def consumer_compatibility_status_label(status: str) -> str:
    return {
        "compatible": "No breaking change",
        "breaking": "Breaking change",
        "requires_review": "Needs review",
    }.get(status, status.replace("_", " ").title())


def consumer_compatibility_counts(instrumentation: dict[str, Any]) -> dict[str, int]:
    counts = {"breaking": 0, "requires_review": 0, "compatible": 0}
    for finding in instrumentation["findings"]:
        for item in finding["telemetry_changes"]:
            compatibility = item.get("consumer_compatibility")
            if compatibility:
                counts[compatibility["status"]] += 1
    return counts


def render_consumer_compatibility(implementation: dict[str, Any]) -> str:
    rows: list[str] = []
    for item in implementation["telemetry_changes"]:
        compatibility = item.get("consumer_compatibility")
        if not compatibility:
            continue
        impact_parts = [compatibility["user_impact"]]
        if compatibility["migration"]:
            impact_parts.append(
                "Migration: " + "; ".join(compatibility["migration"])
            )
        rows.append(
            "<tr>"
            f'<td><strong>{esc(telemetry_change_reader_label(item))}</strong><br>'
            f'{render_list(compatibility["existing_contract"])}</td>'
            f'<td>{esc(compatibility["instrumentation_action"])}</td>'
            f'<td><span class="consumer-compat consumer-compat-{esc(compatibility["status"])}">'
            f'{esc(consumer_compatibility_status_label(compatibility["status"]))}'
            "</span></td>"
            f'<td>{esc(" ".join(impact_parts))}</td>'
            "</tr>"
        )
    if not rows:
        return ""
    return (
        '<section class="consumer-compatibility">'
        '<h4>Consumer compatibility</h4>'
        '<div class="table-wrap"><table><thead><tr>'
        '<th>Existing consumer contract</th><th>Instrumentation action</th>'
        '<th>Breaking?</th><th>User impact</th>'
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
        '</section>'
    )


def render_named_proof_group(
    title: str,
    values: list[str],
    class_name: str,
) -> str:
    values = list(dict.fromkeys(values))
    if not values:
        return ""
    return (
        f'<div class="proof-group {esc(class_name)}">'
        f'<strong>{esc(title)}</strong>{render_list(values)}</div>'
    )


def blocked_proof_context(
    proof: dict[str, Any],
    blocked_scenarios: list[dict[str, Any]],
) -> tuple[list[str], list[str], list[str]]:
    """Return blocker, proven, and unobserved facts from canonical proof fields."""
    blocked_ids = {scenario["id"] for scenario in blocked_scenarios}
    proven_items = [
        item
        for item in proof["item_results"]
        if item["status"] == "working"
        and blocked_ids.intersection(item["scenarios"])
    ]
    blocker_reasons = list(
        dict.fromkeys(
            reader_prose(scenario["blocking_reason"])
            for scenario in blocked_scenarios
            if isinstance(scenario.get("blocking_reason"), str)
            and scenario["blocking_reason"].strip()
        )
    )
    already_proven = list(
        dict.fromkeys(
            reader_prose(value)
            for item in proven_items
            for value in item["observed_telemetry"]
            if value.strip()
        )
    )
    still_unobserved = list(
        dict.fromkeys(
            reader_prose(scenario["unobserved_outcome"])
            for scenario in blocked_scenarios
            if isinstance(scenario.get("unobserved_outcome"), str)
            and scenario["unobserved_outcome"].strip()
        )
    )
    if not already_proven:
        already_proven = ["No mapped telemetry change has direct proof yet."]
    return blocker_reasons, already_proven, still_unobserved


def render_blocked_proof_summary(
    proof: dict[str, Any],
) -> str:
    blocked_scenarios = [
        scenario for scenario in proof["scenarios"] if scenario["status"] == "blocked"
    ]
    if not blocked_scenarios:
        return ""
    blocker_reasons, already_proven, still_unobserved = blocked_proof_context(
        proof, blocked_scenarios
    )
    return (
        '<div class="blocked-proof-summary">'
        '<strong>Runtime verification unavailable</strong>'
        '<div><strong>Why runtime verification is unavailable</strong>'
        f'{render_list(blocker_reasons)}</div>'
        '<div><strong>Already proven</strong>'
        f'{render_list(already_proven)}</div>'
        '<div><strong>Still unobserved</strong>'
        f'{render_list(still_unobserved)}</div>'
        '</div>'
    )


HTTP_ROUTE_TRIGGER = re.compile(
    r"^(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+/\S+",
    re.IGNORECASE,
)


def scenario_is_route(
    scenario: dict[str, Any],
    audit_scenarios: dict[str, dict[str, Any]],
) -> bool:
    trigger = audit_scenarios.get(scenario["id"], {}).get("trigger", "")
    return bool(HTTP_ROUTE_TRIGGER.match(trigger.strip()))


def scenario_has_positive_observation(scenario: dict[str, Any]) -> bool:
    if scenario["status"] == "working":
        return True
    return (
        scenario["status"] == "not_proven"
        and scenario["proof_mode"] != "not_run"
        and scenario["visibility"] != "not_proven"
        and bool(scenario["evidence"])
        and bool(scenario["observed_telemetry"])
        and bool(scenario["product_validation"])
    )


def telemetry_item_status_label(result: dict[str, Any]) -> str:
    return {
        "working": "Proven",
        "not_working": "Failed",
        "blocked": "Blocked",
        "not_configured": "Not configured",
        "deferred": "Deferred",
        "not_proven": (
            "Not checked" if result["proof_mode"] == "not_run" else "Not proven"
        ),
    }.get(result["status"], result["status"].replace("_", " ").title())


def telemetry_item_observation(
    item: dict[str, Any], result: dict[str, Any]
) -> str:
    """Return item-specific reader text without upgrading indirect evidence."""
    observed = reader_prose(" ".join(result["observed_telemetry"]))
    if result["status"] != "not_proven":
        return observed or "No direct observation was recorded."
    if result["proof_mode"] == "not_run":
        return "This exact telemetry change was not checked."
    if result["visibility"] == "not_explorer_visible":
        return (
            f'Focused checks ran, but no saved assertion directly observed the exact '
            f'{item["type"]} {item["name"]}. This telemetry change was not observed '
            "in an OTLP receiver."
        )
    if result["visibility"] == "not_proven":
        return (
            f'No direct observation was recorded for the exact {item["type"]} '
            f'{item["name"]}.'
        )
    return observed or "Direct evidence for this exact telemetry change is incomplete."


def finding_verification_heading(proof: dict[str, Any]) -> str:
    failed = any(
        value["status"] == "not_working"
        for key in ("scenarios", "item_results")
        for value in proof[key]
    )
    if failed or proof["status"] == "not_working":
        return "Verification failed"
    return {
        "working": "Verification complete",
        "not_proven": "Verification incomplete",
        "blocked": "Verification blocked",
        "not_configured": "Verification not configured",
        "deferred": "Verification deferred",
    }.get(proof["status"], "Verification status")


def named_scenario_summary(
    scenarios: list[dict[str, Any]],
    audit_scenarios: dict[str, dict[str, Any]],
    remainder_noun: str,
) -> str:
    """Return concise human trigger text without inferring its grammar."""

    labels = list(
        dict.fromkeys(
            scenario_reader_label(scenario, audit_scenarios)
            for scenario in scenarios
        )
    )
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]}; {labels[1]}"
    if len(labels) == 3:
        return f"{labels[0]}; {labels[1]}; {labels[2]}"
    additional = len(labels) - 3
    suffix = "" if additional == 1 else "s"
    return (
        f"{labels[0]}; {labels[1]}; {labels[2]}; and {additional} other "
        f"{remainder_noun}{suffix}"
    )


def finding_verification_summary(
    proof: dict[str, Any],
    audit_scenarios: dict[str, dict[str, Any]],
) -> str:
    scenarios = proof["scenarios"]
    routes = [
        scenario
        for scenario in scenarios
        if scenario_is_route(scenario, audit_scenarios)
    ]
    other = [scenario for scenario in scenarios if scenario not in routes]
    sentences: list[str] = []
    if routes:
        runtime_routes = [
            scenario
            for scenario in routes
            if scenario["status"] == "working"
            and scenario_has_positive_observation(scenario)
            and scenario["proof_mode"] == "full_runtime"
        ]
        focused_routes = [
            scenario
            for scenario in routes
            if scenario["status"] == "working"
            and scenario_has_positive_observation(scenario)
            and scenario["proof_mode"] != "full_runtime"
        ]
        if runtime_routes:
            summary = named_scenario_summary(
                runtime_routes, audit_scenarios, "route check"
            )
            sentences.append(f"Confirmed in a running service: {summary}.")
        if focused_routes:
            summary = named_scenario_summary(
                focused_routes, audit_scenarios, "route check"
            )
            sentences.append(f"Passed focused verification: {summary}.")
    focused_working = [
        scenario
        for scenario in other
        if scenario["status"] == "working"
        and scenario_has_positive_observation(scenario)
        and scenario["proof_mode"] != "full_runtime"
    ]
    runtime_working = [
        scenario
        for scenario in other
        if scenario["status"] == "working"
        and scenario_has_positive_observation(scenario)
        and scenario["proof_mode"] == "full_runtime"
    ]
    if runtime_working:
        summary = named_scenario_summary(
            runtime_working, audit_scenarios, "lifecycle or topology check"
        )
        sentences.append(f"Confirmed in the running service: {summary}.")
    if focused_working:
        summary = named_scenario_summary(
            focused_working, audit_scenarios, "lifecycle or topology check"
        )
        sentences.append(f"Passed focused verification: {summary}.")
    incomplete_observed = [
        scenario
        for scenario in scenarios
        if scenario["status"] == "not_proven"
        and scenario_has_positive_observation(scenario)
    ]
    if incomplete_observed:
        summary = named_scenario_summary(
            incomplete_observed, audit_scenarios, "check"
        )
        sentences.append(f"Focused evidence is incomplete for: {summary}.")
    not_exercised = [
        scenario
        for scenario in scenarios
        if scenario["status"] == "not_proven" and scenario["proof_mode"] == "not_run"
    ]
    unresolved = [
        scenario
        for scenario in scenarios
        if scenario["status"] == "not_proven"
        and scenario["proof_mode"] != "not_run"
        and not scenario_has_positive_observation(scenario)
    ]
    failed = [scenario for scenario in scenarios if scenario["status"] == "not_working"]
    not_configured = [
        scenario for scenario in scenarios if scenario["status"] == "not_configured"
    ]
    if not_exercised:
        summary = named_scenario_summary(
            not_exercised, audit_scenarios, "check"
        )
        sentences.append(f"Not exercised: {summary}.")
    if unresolved:
        summary = named_scenario_summary(
            unresolved, audit_scenarios, "check"
        )
        sentences.append(f"Executed evidence is unresolved for: {summary}.")
    if not_configured:
        summary = named_scenario_summary(
            not_configured, audit_scenarios, "check"
        )
        sentences.append(f"Not configured: {summary}.")
    if failed:
        summary = named_scenario_summary(
            failed, audit_scenarios, "check"
        )
        sentences.append(f"Verification failed for: {summary}.")
    return " ".join(sentences)


def render_telemetry_proof_summary(
    implementation: dict[str, Any],
    proof: dict[str, Any],
) -> str:
    item_by_id = {item["id"]: item for item in implementation["telemetry_changes"]}
    rows: list[str] = []
    for result in proof["item_results"]:
        item = item_by_id.get(result["id"])
        if item is None:
            continue
        observed = telemetry_item_observation(item, result)
        status = telemetry_item_status_label(result)
        rows.append(
            "<tr>"
            f"<td><strong>{esc(telemetry_change_reader_label(item))}</strong></td>"
            f"<td>{esc(observed)}</td>"
            "<td>"
            f'<span class="proof-status proof-status-{esc(result["status"])}">'
            f"{esc(status)}</span>"
            "</td>"
            "</tr>"
        )
    if not rows:
        return (
            '<p class="muted">No application telemetry change was created for this '
            "selected issue.</p>"
        )
    return (
        '<div class="telemetry-proof-summary"><strong>Telemetry proof</strong>'
        '<div class="table-wrap"><table class="telemetry-proof-table">'
        "<thead><tr><th>Telemetry change</th><th>What was observed</th>"
        "<th>Status</th></tr></thead>"
        f'<tbody>{"".join(rows)}</tbody></table></div></div>'
    )


def render_coverage_details(
    proof: dict[str, Any],
    audit_scenarios: dict[str, dict[str, Any]],
) -> str:
    groups: dict[str, list[str]] = {
        "runtime": [],
        "focused": [],
        "incomplete": [],
        "not_run": [],
        "unresolved": [],
        "blocked": [],
        "failed": [],
        "not_configured": [],
    }
    for scenario in proof["scenarios"]:
        label = scenario_reader_label(scenario, audit_scenarios)
        status = scenario["status"]
        if status == "working" and scenario_has_positive_observation(scenario):
            key = "runtime" if scenario["proof_mode"] == "full_runtime" else "focused"
        elif status == "not_proven" and scenario_has_positive_observation(scenario):
            key = "incomplete"
        elif status == "not_working":
            key = "failed"
        elif status == "blocked":
            key = "blocked"
        elif status == "not_configured":
            key = "not_configured"
        elif scenario["proof_mode"] == "not_run":
            key = "not_run"
        else:
            key = "unresolved"
        groups[key].append(label)
    content = "".join(
        [
            render_named_proof_group(
                "Confirmed in a running service", groups["runtime"], "proof-runtime"
            ),
            render_named_proof_group(
                "Passed focused checks", groups["focused"], "proof-focused"
            ),
            render_named_proof_group(
                "Focused evidence obtained", groups["incomplete"], "proof-partial"
            ),
            render_named_proof_group(
                "Not exercised", groups["not_run"], "proof-not-run"
            ),
            render_named_proof_group(
                "Unresolved executed checks", groups["unresolved"], "proof-unresolved"
            ),
            render_named_proof_group(
                "Affected runtime checks", groups["blocked"], "proof-blocked"
            ),
            render_named_proof_group(
                "Failed", groups["failed"], "proof-failed"
            ),
            render_named_proof_group(
                "Not configured", groups["not_configured"], "proof-not-configured"
            ),
        ]
    )
    if not content:
        return ""
    return (
        '<details class="coverage-details"><summary>Coverage details</summary>'
        f'<div class="coverage-detail-body">{content}</div></details>'
    )


def render_named_finding_proof(
    report: dict[str, Any],
    implementation: dict[str, Any],
    proof: dict[str, Any] | None,
) -> str:
    if proof is None:
        return (
            '<section class="finding-proof">'
            '<h4>Internal verification has not completed</h4>'
            '<p class="muted">The instrumentation run has not produced item-level '
            'proof for this selected issue yet. Resolve the recorded prerequisite '
            'or repair.</p>'
            '</section>'
        )

    audit_scenarios = audit_scenarios_by_id(report)
    heading = finding_verification_heading(proof)
    summary = finding_verification_summary(proof, audit_scenarios)
    summary_html = (
        f'<p class="proof-summary">{esc(summary)}</p>' if summary else ""
    )
    blocked_summary = render_blocked_proof_summary(proof)
    item_summary = render_telemetry_proof_summary(implementation, proof)
    coverage = render_coverage_details(proof, audit_scenarios)
    return (
        '<section class="finding-proof">'
        f'<h4>{esc(heading)}</h4>'
        f'{summary_html}{blocked_summary}'
        f'{item_summary}{coverage}'
        '</section>'
    )


EXPLICIT_CHILD_VERIFY_ACTION = re.compile(
    r"\b(?:\$?otel[- ]verify|child\s+verification(?:\s+workflow)?)\b",
    re.IGNORECASE,
)
STALE_VERIFY_WORKFLOW_ACTION = re.compile(
    r"\b(?:continue|complete|finish)\s+(?:with\s+)?(?:the\s+)?"
    r"(?:\$?otel[- ]verify|child\s+verification|verification\s+workflow)\b",
    re.IGNORECASE,
)
INSTRUMENTATION_WORKFLOW_VERIFY_ACTION = re.compile(
    r"\b(?:continue|complete|finish)\s+(?:the\s+)?(?:active\s+)?"
    r"instrumentation\s+workflow\s+(?:through|to|with|into)\s+"
    r"(?:the\s+)?verification\b",
    re.IGNORECASE,
)
GENERIC_VERIFY_ACTION = re.compile(
    r"\b(?:use|run|rerun|re-run|invoke|execute|launch|start)\s+"
    r"(?:the\s+)?verification(?:\s+workflow)?\b",
    re.IGNORECASE,
)
PRODUCT_VERIFY_QUALIFIER = re.compile(
    r"(?:\b(?:product|target[- ]product)\s+verification\b|"
    r"\bverification(?:\s+workflow)?\s+"
    r"(?:in|against|within|using|via)\s+(?:the\s+)?"
    r"(?:splunk\s+observability\s+cloud|splunk\s+o11y\s+cloud|"
    r"target[- ]product|product)\b)",
    re.IGNORECASE,
)


def is_stale_parent_verification_action(action: str) -> bool:
    """Classify only actions that redundantly invoke the completed child."""
    if EXPLICIT_CHILD_VERIFY_ACTION.search(action):
        return True
    if STALE_VERIFY_WORKFLOW_ACTION.search(action):
        return True
    if INSTRUMENTATION_WORKFLOW_VERIFY_ACTION.search(action):
        return True
    return bool(
        GENERIC_VERIFY_ACTION.search(action)
        and not PRODUCT_VERIFY_QUALIFIER.search(action)
    )


def verification_failure_observations(proof: dict[str, Any]) -> list[str]:
    observations: list[str] = []
    for scenario in proof["scenarios"]:
        if scenario["status"] != "not_working":
            continue
        observations.extend(scenario["observed_telemetry"])
    return list(dict.fromkeys(observations))


def render_finding_verification_follow_up(
    report: dict[str, Any],
    proof: dict[str, Any],
) -> str:
    status = proof["status"]
    remaining = proof.get("remaining", [])
    if status in {"working", "not_proven"}:
        return ""
    if status == "not_working":
        observations = verification_failure_observations(proof)
        observed = (
            render_list(observations)
            if observations
            else '<p class="muted">The executed check failed; see Technical proof for direct evidence.</p>'
        )
        action_list = (
            render_list(remaining)
            if remaining
            else '<p class="muted">No concrete code or configuration repair was recorded.</p>'
        )
        return (
            '<section class="issue-follow-up">'
            '<h4>What verification found</h4>'
            f'{observed}'
            '<h4>Code repair required</h4>'
            '<p class="muted"><code>$otel-instrument</code> changes the application. '
            '<code>$otel-verify</code> never repairs application code.</p>'
            f'{action_list}</section>'
        )
    heading = {
        "not_configured": "Implementation still needed",
        "deferred": "Deferred work",
    }.get(status, "Next action")
    return (
        '<section class="issue-follow-up">'
        f'<h4>{esc(heading)}</h4>{render_list(remaining)}</section>'
        if remaining
        else ""
    )


def render_overlay_impact(
    instrumentation: dict[str, Any] | None,
    verify: dict[str, Any] | None,
    source_references: dict[str, list[dict[str, str]]],
) -> str:
    if instrumentation is None:
        return ""
    verify_by_finding = {
        finding["id"]: finding for finding in (verify or {}).get("findings", [])
    }
    rows: list[str] = []
    counts = instrumentation_proof_counts(instrumentation, verify)
    for finding in instrumentation["findings"]:
        item_results = {
            item["id"]: item
            for item in verify_by_finding.get(finding["id"], {}).get("item_results", [])
        }
        for item in finding["telemetry_changes"]:
            result = item_results.get(item["id"])
            proof = (
                f'<strong>{esc(human_item_proof_status(result))}</strong><br>'
                f'<span class="muted">{esc(human_proof_mode(result["proof_mode"]))} · '
                f'{esc(human_visibility(result["visibility"]))}</span>'
                if result
                else '<strong>not checked</strong><br><span class="muted">verification has not produced item proof</span>'
            )
            evidence = "<br>".join(
                source_reference_html(value, source_references)
                for value in (result or {}).get("evidence", [])
            ) or '<span class="muted">None recorded.</span>'
            observed = telemetry_item_observation(item, result) if result else ""
            product_validation = "; ".join((result or {}).get("product_validation", []))
            proof_detail = evidence
            if observed:
                proof_detail += (
                    f'<br><span class="muted">Observed:</span> '
                    f'{esc(reader_prose(observed))}'
                )
            if product_validation:
                proof_detail += (
                    f'<br><span class="muted">Product check:</span> '
                    f'{esc(reader_prose(product_validation))}'
                )
            added = ", ".join(item["added_attributes"]) or "None"
            follow_up = "<br>".join(esc(action) for action in item["follow_up_actions"])
            rows.append(
                "<tr>"
                f'<td><code>{esc(item["id"])}</code><br><span class="muted">{esc(finding["id"])}</span></td>'
                f'<td>{source_reference_html(item["source"], source_references)}<br>'
                f'<strong>{esc(item["change_kind"])}</strong> — {esc(item["change"])}</td>'
                f'<td><strong>{esc(item["type"])} {esc(item["name"])}</strong><br>'
                f'<span class="muted">Added attributes/dimensions: {esc(added)}</span></td>'
                f'<td>{esc(item["product_view"])}</td>'
                f'<td>{proof}</td><td>{proof_detail}</td><td>{follow_up}</td>'
                "</tr>"
            )
    if not rows:
        rows.append('<tr><td colspan="7" class="muted">No telemetry items were added, modified, or removed.</td></tr>')
    verification_result = verify["meta"]["result"] if verify else "Not run"
    interpretation = {
        "Pass": "Every telemetry item has a direct successful observation.",
        "Partial": (
            "No verification finding failed; some route or lifecycle coverage was not exercised."
        ),
        "Fail": "An executed check failed or observed telemetry did not match the contract.",
        "Blocked": "A concrete prerequisite prevented meaningful verification.",
        "Not run": "Item-level verification has not run.",
    }.get(verification_result, "Review the item-level proof.")
    total = counts["telemetry_items"]
    failures = counts["findings_failed"] if verify is not None else "Not run"
    if counts["items_otlp_accepted"] and not counts["items_product_visible"]:
        delivery_label = "OTLP-delivered items"
        delivery_count = counts["items_otlp_accepted"]
    else:
        delivery_label = "Product-visible items"
        delivery_count = counts["items_product_visible"]
    return (
        '<section class="impact-panel" aria-labelledby="implementation-impact-heading">'
        '<h2 id="implementation-impact-heading">Code → telemetry → product result</h2>'
        '<div class="impact-stats proof-stats">'
        f'<div><span>Telemetry items</span><strong>{total}</strong></div>'
        f'<div><span>Telemetry changes proven</span><strong>{counts["items_working"]}/{total}</strong></div>'
        f'<div><span>{delivery_label}</span><strong>{delivery_count}/{total}</strong></div>'
        f'<div><span>Failed findings</span><strong>{failures}</strong></div>'
        '</div>'
        f'<p class="review-note"><strong>Proof interpretation:</strong> {esc(interpretation)}</p>'
        f'<details class="technical-details"><summary>Show {total} telemetry-item mappings and direct proof</summary>'
        '<div class="decision-table"><table><thead><tr>'
        '<th>Item</th><th>Code/config change</th><th>Exact telemetry</th><th>Product result</th>'
        '<th>Status / proof</th><th>Direct evidence</th><th>Next product action</th>'
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div></details>'
        '</section>'
    )


def instrumentation_report_next_steps(
    instrumentation: dict[str, Any],
    verify: dict[str, Any] | None,
) -> list[str]:
    if verify is not None:
        if verify.get("next_steps"):
            steps = list(verify["next_steps"])
            durable_steps = [
                step for step in steps if not is_stale_parent_verification_action(step)
            ]
            if durable_steps:
                return durable_steps
        return {
            "Pass": ["No further verification action is required."],
            "Fail": [
                "$otel-instrument: Repair the failed in-scope instrumentation."
            ],
            "Partial": [
                "Complete the concrete proof prerequisites listed on the affected findings."
            ],
            "Blocked": [
                "Satisfy the prerequisite recorded in the verification evidence."
            ],
            "Not run": [
                "Resolve the prerequisite that prevented verification."
            ],
        }.get(verify["meta"]["result"], ["Review the item-level proof."])
    if instrumentation.get("next_steps"):
        durable_steps = [
            step
            for step in instrumentation["next_steps"]
            if not is_stale_parent_verification_action(step)
        ]
        if durable_steps:
            return durable_steps
    return [
        "Resolve any recorded prerequisite named on the selected finding cards."
    ]


def has_completed_instrumentation_scope(
    instrumentation: dict[str, Any],
) -> bool:
    """Use authored structured closure statuses without interpreting prose."""

    return any(
        finding.get("status") == "working"
        for finding in instrumentation.get("findings", [])
    )


def aggregate_instrumentation_result(
    instrumentation: dict[str, Any],
    verify: dict[str, Any] | None,
) -> str:
    """Combine the verification state with completed implementation scope."""

    if verify is None:
        return instrumentation["meta"]["result"]
    verification_result = verify["meta"]["result"]
    if verification_result not in RESULT_STATUSES:
        fail(f"unsupported verification result: {verification_result}")
    if verification_result == "Fail":
        return "Fail"
    if verification_result == "Blocked":
        return (
            "Partial"
            if has_completed_instrumentation_scope(instrumentation)
            else "Blocked"
        )
    return "Partial" if verification_result == "Not run" else verification_result


def render_instrumentation_summary(
    selection: dict[str, Any],
    instrumentation: dict[str, Any],
    verify: dict[str, Any] | None,
) -> str:
    counts = instrumentation_proof_counts(instrumentation, verify)
    compatibility_counts = consumer_compatibility_counts(instrumentation)
    verification_result = verify["meta"]["result"] if verify else "Not run"
    aggregate_result = aggregate_instrumentation_result(instrumentation, verify)
    total = counts["telemetry_items"]
    failed_findings = counts["findings_failed"]
    if verify is None:
        heading = {
            "Pass": "Instrumentation complete — verification not run",
            "Partial": "Instrumentation incomplete — verification not run",
            "Fail": "Instrumentation failed — verification not run",
            "Blocked": "Instrumentation blocked — verification not run",
            "Not run": "Instrumentation and verification not run",
        }[aggregate_result]
    elif aggregate_result == "Pass":
        heading = "Instrumentation and verification complete"
    elif aggregate_result == "Fail" and verification_result == "Fail":
        failure_word = "failure" if failed_findings == 1 else "failures"
        heading = f"Verification failed — {failed_findings} observed {failure_word}"
    elif aggregate_result == "Fail":
        heading = "Instrumentation failed"
    elif aggregate_result == "Partial" and verification_result == "Pass":
        heading = "Instrumentation incomplete — verification complete"
    elif verification_result == "Partial" and failed_findings == 0:
        heading = "Verification incomplete — no observed failures"
    elif aggregate_result == "Partial" and verification_result == "Blocked":
        heading = "Instrumentation partial — verification blocked"
    elif aggregate_result == "Blocked":
        heading = "Verification blocked"
    elif verification_result == "Not run":
        heading = "Instrumentation partial — verification not run"
    else:
        heading = aggregate_result

    if total == 0:
        proof_sentence = "No telemetry changes were recorded; this is proof-only scope."
    elif total == 1:
        proof_sentence = f'{counts["items_working"]} of 1 telemetry change is proven.'
    else:
        proof_sentence = (
            f'{counts["items_working"]} of {total} telemetry changes are proven.'
        )

    if counts["items_product_visible"]:
        delivery_sentence = (
            f'{counts["items_product_visible"]} of {total} telemetry changes were '
            "confirmed in the configured telemetry explorer."
        )
    elif counts["scenarios_product_visible"]:
        delivery_sentence = (
            "Scenario proof was confirmed in the configured telemetry explorer."
        )
    elif counts["items_otlp_accepted"]:
        delivery_sentence = (
            "Local OTLP delivery was checked; Splunk Observability Cloud was not checked."
        )
    elif counts["scenarios_otlp_accepted"]:
        delivery_sentence = (
            "Scenario proof reached local OTLP; Splunk Observability Cloud was not checked."
        )
    else:
        delivery_sentence = (
            "Local OTLP delivery and Splunk Observability Cloud were not checked."
        )
    compatibility_sentence = ""
    if compatibility_counts["breaking"]:
        count = compatibility_counts["breaking"]
        noun = "change" if count == 1 else "changes"
        compatibility_sentence = (
            f" Consumer compatibility: {count} breaking telemetry consumer {noun}."
        )
    elif compatibility_counts["requires_review"]:
        count = compatibility_counts["requires_review"]
        noun = "change" if count == 1 else "changes"
        compatibility_sentence = (
            f" Consumer compatibility: {count} telemetry consumer {noun} need review."
        )
    return (
        f'<h2 id="instrumentation-status-heading" class="status-heading">{esc(heading)}</h2>'
        f'<p><strong>Overall result: {esc(aggregate_result)}.</strong> '
        f'{esc(proof_sentence)} {esc(delivery_sentence)}'
        f'{esc(compatibility_sentence)}</p>'
    )


def render_selected_issue_changes(
    report: dict[str, Any],
    selection: dict[str, Any],
    instrumentation: dict[str, Any],
    verify: dict[str, Any] | None,
) -> str:
    audit_by_id = {row["id"]: row for row in report["findings"]}
    verify_by_id = {row["id"]: row for row in (verify or {}).get("findings", [])}
    requested_ids = set(selection.get("requested_ids", []))
    entries: list[str] = []
    for implementation in instrumentation["findings"]:
        finding = audit_by_id[implementation["id"]]
        items = implementation["telemetry_changes"]
        by_type: dict[str, int] = {}
        for item in items:
            by_type[item["type"]] = by_type.get(item["type"], 0) + 1
        telemetry_shape = ", ".join(
            f"{count} {item_type}{'' if count == 1 else 's'}"
            for item_type, count in sorted(by_type.items())
        ) or "proof-only scope; no application telemetry item"
        proof = verify_by_id.get(implementation["id"])
        canonical_status = (proof or implementation)["status"]
        status = human_finding_proof_status(canonical_status, verify is not None)
        if not items:
            proof_summary = f"{status}; proof-only verification scope"
        elif verify is None:
            proof_summary = f"{status}; verification has not run"
        else:
            proof_summary = status
        named_proof = render_named_finding_proof(
            report,
            implementation,
            proof,
        )
        selection_reason = (
            "You selected" if implementation["id"] in requested_ids else "Added as a required dependency"
        )
        implementation_state = (
            "proof-only scope" if not items else "change recorded"
        )
        if implementation["status"] == "not_working":
            implementation_state = "implementation check failed"
        changes = render_list(implementation["changes"])
        follow_up = (
            render_finding_verification_follow_up(report, proof) if proof else ""
        )
        consumer_compatibility = render_consumer_compatibility(implementation)
        entries.append(
            '<li><article class="selected-issue" '
            f'id="selected-{esc(implementation["id"])}" '
            f'data-priority="{esc(finding["priority"])}" '
            f'data-area="{esc(finding["area"])}">'
            '<div class="selected-issue-header"><div>'
            f'<span class="selection-reason">{esc(selection_reason)}</span>'
            f'<h3>{esc(finding["title"])}</h3>'
            f'<p class="muted"><code>{esc(finding["id"])}</code></p></div>'
            '<span class="issue-status-group">'
            f'<span class="issue-status">Implementation: {esc(implementation_state)}</span>'
            f'<span class="issue-status">Proof: {esc(status)}</span></span></div>'
            f'<p><strong>Selected issue:</strong> {esc(finding["gap"])}</p>'
            '<div class="selected-issue-grid">'
            f'<section><h4>What changed / was corrected</h4>{changes}</section>'
            '<section><h4>How it improves observability</h4>'
            f'<p>{esc(finding["product_outcome"])}</p>'
            '</section></div>'
            f'<p class="issue-proof"><strong>Telemetry changes:</strong> {esc(telemetry_shape)} · '
            f'<strong>Verification:</strong> {esc(proof_summary)}</p>'
            f'{consumer_compatibility}'
            f'{named_proof}'
            f'{follow_up}'
            '</article></li>'
        )
    if not entries:
        return '<p class="muted">No selected-scope changes were recorded.</p>'
    return f'<ol class="selected-issues">{"".join(entries)}</ol>'


def render_gap_closure(
    report: dict[str, Any],
    instrumentation: dict[str, Any],
    verify: dict[str, Any] | None,
    source_references: dict[str, list[dict[str, str]]],
) -> str:
    audit_by_id = {row["id"]: row for row in report["findings"]}
    verify_by_id = {row["id"]: row for row in (verify or {}).get("findings", [])}
    rows: list[str] = []
    for implementation in instrumentation["findings"]:
        finding = audit_by_id[implementation["id"]]
        proof = verify_by_id.get(implementation["id"])
        status = (proof or implementation)["status"].replace("_", " ")
        changed = "<br>".join(
            f'<code>{esc(item["id"])}</code> — {esc(item["change_kind"])}: {esc(item["change"])}'
            for item in implementation["telemetry_changes"]
        )
        if not changed:
            changed = "<br>".join(esc(item) for item in implementation["changes"])
        tested = "<br>".join(
            esc(implementation_check_text(item)) for item in implementation["tests"]
        ) or "Not recorded"
        if proof is not None:
            tested = (
                '<span class="muted">Implementation regression checks '
                '(not finding-level acceptance):</span><br>'
                + tested
            )
        evidence_values = list(implementation["evidence"])
        if proof:
            for scenario in proof["scenarios"]:
                evidence_values.extend(scenario["evidence"])
        evidence = "<br>".join(
            source_reference_html(item, source_references) for item in dict.fromkeys(evidence_values)
        ) or '<span class="muted">None recorded.</span>'
        remaining = (
            proof["remaining"]
            if proof is not None
            else implementation["follow_up_actions"]
        )
        rows.append(
            f'<tr class="closure-row" id="closure-{esc(finding["id"])}">'
            f'<td><code>{esc(finding["id"])}</code><br><strong>{esc(finding["title"])}</strong><br>'
            f'<span class="muted">{esc(finding["priority"])} · {esc(finding["area"])}</span></td>'
            f'<td>{esc(finding["impact"])}</td>'
            f'<td>{changed or "No code or configuration change recorded."}</td>'
            f'<td>{tested}</td><td><strong>{esc(status)}</strong></td><td>{evidence}</td>'
            f'<td>{esc(reader_prose("; ".join(remaining)) or "None")}</td>'
            '</tr>'
        )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        '<th>Finding in scope</th><th>Why it mattered</th><th>What changed</th>'
        '<th>Instrumentation-phase checks</th>'
        '<th>Result</th><th>Evidence</th><th>Remaining / next</th>'
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def render_verification_details(
    verify: dict[str, Any] | None,
    instrumentation: dict[str, Any],
    source_references: dict[str, list[dict[str, str]]],
) -> str:
    if verify is None:
        return (
            '<p class="muted">Internal verification has not completed. '
            'Implementation is not runtime- or product-proven yet.</p>'
        )
    scenario_rows: list[str] = []
    item_rows: list[str] = []
    implementation_items = {
        item["id"]: item
        for finding in instrumentation["findings"]
        for item in finding["telemetry_changes"]
    }
    for finding in verify["findings"]:
        for scenario in finding["scenarios"]:
            evidence = "<br>".join(
                source_reference_html(item, source_references) for item in scenario["evidence"]
            ) or '<span class="muted">None recorded.</span>'
            trace_capture = (
                '<br><span class="muted">Generated trace evidence recorded.</span>'
                if scenario["trace_ids"]
                else ""
            )
            scenario_rows.append(
                '<tr>'
                f'<td><code>{esc(finding["id"])}</code><br><code>{esc(scenario["id"])}</code></td>'
                f'<td><strong>{esc(human_item_proof_status(scenario))}</strong><br>'
                f'<span class="muted">{esc(human_proof_mode(scenario["proof_mode"]))} · '
                f'{esc(human_visibility(scenario["visibility"]))}</span></td>'
                f'<td>{esc(reader_prose("; ".join(scenario["observed_telemetry"])) or "None observed")}</td>'
                f'<td>{esc(reader_prose("; ".join(scenario["product_validation"])) or "No product validation")}</td>'
                f'<td>{evidence}{trace_capture}</td>'
                '</tr>'
            )
        for item in finding["item_results"]:
            evidence = "<br>".join(
                source_reference_html(value, source_references) for value in item["evidence"]
            ) or '<span class="muted">None recorded.</span>'
            implementation_item = implementation_items.get(item["id"])
            observed = (
                telemetry_item_observation(implementation_item, item)
                if implementation_item is not None
                else reader_prose("; ".join(item["observed_telemetry"]))
            )
            item_rows.append(
                '<li>'
                f'<code>{esc(item["id"])}</code>: '
                f'<strong>{esc(human_item_proof_status(item))}</strong> '
                f'<span class="muted">{esc(human_proof_mode(item["proof_mode"]))} · '
                f'{esc(human_visibility(item["visibility"]))}</span><br>'
                f'{esc(observed or "None observed")}<br>'
                f'<span class="muted">Product check: '
                f'{esc(reader_prose("; ".join(item["product_validation"])) or "No product validation")}</span><br>'
                f'{evidence}'
                '</li>'
            )
    item_details = (
        '<details><summary>Telemetry proof details</summary>'
        f'<ul>{"".join(item_rows)}</ul></details>'
        if item_rows
        else ""
    )
    return (
        '<details><summary>Scenario proof</summary><div class="table-wrap"><table><thead><tr>'
        '<th>Finding / scenario</th><th>Status</th><th>Observed telemetry</th><th>Product check</th><th>Evidence</th>'
        f'</tr></thead><tbody>{"".join(scenario_rows)}</tbody></table></div></details>'
        f'{item_details}'
    )


def render_unselected_findings(report: dict[str, Any], selection: dict[str, Any]) -> str:
    approved = set(selection["approved_ids"])
    rows = [finding for finding in report["findings"] if finding["id"] not in approved]
    if not rows:
        return '<p class="muted">Every audit finding was included in the instrumentation scope.</p>'
    return (
        '<div class="table-wrap"><table><thead><tr><th>Finding</th><th>Priority</th><th>Why it matters</th><th>State</th></tr></thead><tbody>'
        + "".join(
            '<tr>'
            f'<td><code>{esc(finding["id"])}</code><br><strong>{esc(finding["title"])}</strong></td>'
            f'<td>{esc(finding["priority"])}</td><td>{esc(finding["impact"])}</td>'
            '<td>Not in selected scope; no implementation claim.</td></tr>'
            for finding in rows
        )
        + '</tbody></table></div>'
    )


def render_instrumentation_html(
    report: dict[str, Any],
    selection: dict[str, Any],
    instrumentation: dict[str, Any],
    verify: dict[str, Any] | None = None,
    source_root: Path | None = None,
    output_dir: Path | None = None,
) -> str:
    title = esc(report["meta"]["service_name"])
    summary = render_instrumentation_summary(selection, instrumentation, verify)
    selected_issues = render_selected_issue_changes(report, selection, instrumentation, verify)
    instrumentation_sha = instrumentation_digest(instrumentation)
    selection_sha = selection_digest(selection)
    verify_instrumentation_sha = (
        verify.get("instrumentation_sha256") if verify is not None else None
    )
    unselected_count = len(report["findings"]) - len(selection["approved_ids"])
    unselected_suffix = "" if unselected_count == 1 else "s"
    remaining_section = (
        '<section class="panel"><h2>Outside selected scope</h2>'
        f'<p>{unselected_count} audit finding{unselected_suffix} '
        'were outside this instrumentation run. Review them in '
        '<a href="otel.html">the audit and scope report</a>.</p></section>'
        if unselected_count
        else ""
    )
    verify_status = (
        '<span>Verification included</span>'
        if verify
        else '<span>Verification not run</span>'
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="otel-audit-sha256" content="{esc(instrumentation['audit_sha256'])}">
<meta name="otel-selection-sha256" content="{esc(selection_sha)}">
<meta name="otel-instrumentation-sha256" content="{esc(instrumentation_sha)}">
<meta name="otel-verify-instrumentation-sha256" content="{esc(verify_instrumentation_sha or 'unbound')}">
<title>OTel Instrumentation - {title}</title>
<style>
:root {{ --bg:#f5f7fa; --surface:#fff; --ink:#17202a; --muted:#5f6b7a; --line:#dbe2ea; --accent:#1f5eff; --ok:#16794c; --critical:#b42318; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.5 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
header {{ background:#121821; color:#eef2f7; padding:28px 0; }}
.wrap {{ max-width:1180px; margin:0 auto; padding:0 20px; }}
.eyebrow {{ color:#9aa8ba; font-size:11px; font-weight:700; letter-spacing:.12em; text-transform:uppercase; }}
h1 {{ margin:8px 0 4px; font-size:clamp(26px,4vw,38px); line-height:1.1; }}
.meta {{ color:#b8c2cf; display:flex; flex-wrap:wrap; gap:14px; font-size:13px; }}
.meta b {{ color:#fff; }}
.report-nav {{ display:flex; flex-wrap:wrap; gap:8px 16px; margin-top:14px; }}
.report-nav a {{ color:#91b8ff; }}
main {{ padding-top:18px !important; padding-bottom:34px !important; }}
.summary,.panel {{ background:var(--surface); border:1px solid var(--line); border-radius:8px; margin:0 0 18px; padding:16px 18px; overflow-x:auto; }}
.summary h2,.panel h2 {{ color:var(--muted); font-size:14px; letter-spacing:.08em; margin:0 0 10px; text-transform:uppercase; }}
.summary h2.status-heading {{ color:var(--ink); font-size:20px; letter-spacing:0; text-transform:none; }}
.impact-stats {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin-bottom:10px; }}
.instrumentation-stats {{ grid-template-columns:repeat(6,minmax(0,1fr)); }}
.proof-stats {{ grid-template-columns:repeat(4,minmax(0,1fr)); }}
.impact-stats div {{ border:1px solid var(--line); border-radius:7px; background:#fbfcfe; padding:9px 10px; }}
.impact-stats span {{ display:block; color:var(--muted); font-size:11px; letter-spacing:.06em; text-transform:uppercase; }}
.impact-stats strong {{ display:block; font-size:18px; margin-top:2px; }}
.review-note {{ border-left:3px solid var(--accent); background:#f4f7ff; margin:13px 0; padding:8px 10px; }}
.current-next {{ border-left:3px solid var(--accent); margin:12px 0 0; padding:6px 10px; }}
.selected-issues {{ display:grid; gap:12px; list-style:none; margin:12px 0 0; padding:0; }}
.selected-issue {{ background:#fbfcfe; border:1px solid var(--line); border-radius:8px; padding:14px; }}
.selected-issue-header {{ align-items:flex-start; display:flex; gap:16px; justify-content:space-between; }}
.selected-issue h3 {{ font-size:18px; line-height:1.25; margin:3px 0 4px; }}
.selection-reason {{ color:var(--accent); font-size:11px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; }}
.issue-status-group {{ align-items:flex-end; display:flex; flex-direction:column; flex:none; gap:5px; }}
.issue-status {{ border:1px solid var(--line); border-radius:999px; color:var(--muted); font-size:11px; font-weight:700; padding:3px 8px; text-transform:uppercase; }}
.selected-issue-grid {{ display:grid; gap:14px; grid-template-columns:1fr 1fr; margin-top:12px; }}
.selected-issue-grid section {{ border-top:1px solid var(--line); padding-top:10px; }}
.selected-issue-grid h4 {{ color:var(--muted); font-size:12px; letter-spacing:.06em; margin:0 0 6px; text-transform:uppercase; }}
.issue-proof {{ background:#f4f7ff; border-radius:6px; margin:12px 0 0; padding:7px 9px; }}
.consumer-compatibility {{ background:#fff9ec; border:1px solid #f0d8a8; border-radius:7px; margin-top:10px; padding:10px; }}
.consumer-compatibility h4 {{ color:#7c4a03; font-size:12px; letter-spacing:.06em; margin:0 0 6px; text-transform:uppercase; }}
.consumer-compat {{ font-weight:700; white-space:nowrap; }}
.consumer-compat-breaking {{ color:var(--critical); }}
.consumer-compat-requires_review {{ color:#7c4a03; }}
.consumer-compat-compatible {{ color:var(--ok); }}
.finding-proof {{ background:#fff; border:1px solid var(--line); border-radius:7px; display:grid; gap:8px; grid-template-columns:1fr 1fr; margin-top:10px; padding:10px; }}
.finding-proof > h4 {{ color:var(--muted); font-size:12px; grid-column:1/-1; letter-spacing:.06em; margin:0; text-transform:uppercase; }}
.proof-summary,.blocked-proof-summary,.telemetry-proof-summary,.coverage-details {{ grid-column:1/-1; }}
.proof-summary {{ margin:0; }}
.blocked-proof-summary {{ background:#fff9ec; border-left:3px solid #b7791f; border-radius:4px; display:grid; gap:6px; padding:9px 11px; }}
.blocked-proof-summary > strong,.blocked-proof-summary div > strong {{ display:block; margin-bottom:3px; }}
.blocked-proof-summary ul {{ margin:3px 0 0; }}
.telemetry-proof-summary {{ background:#f8faff; border-radius:4px; padding:8px 10px; }}
.telemetry-proof-summary .table-wrap {{ margin-top:6px; }}
.telemetry-proof-table td:last-child {{ white-space:nowrap; }}
.proof-status-working {{ color:var(--ok); }}
.proof-status-not_working,.proof-status-not_configured {{ color:var(--critical); }}
.coverage-detail-body {{ display:grid; gap:8px; grid-template-columns:1fr 1fr; padding-top:8px; }}
.proof-group {{ border-left:3px solid var(--accent); background:#f8faff; border-radius:4px; padding:7px 9px; }}
.proof-group > strong {{ display:block; margin-bottom:3px; }}
.proof-group ul {{ margin-top:3px; }}
.proof-runtime,.proof-focused,.proof-item-working,.proof-product {{ border-left-color:var(--ok); background:#f2fbf6; }}
.proof-partial,.proof-not-run,.proof-blocked,.proof-item-partial,.proof-delivery {{ border-left-color:#b7791f; background:#fff9ec; }}
.proof-failed,.proof-not-configured {{ border-left-color:var(--critical); background:#fff5f4; }}
.proof-visibility,.proof-result {{ grid-column:1/-1; margin:0; }}
.issue-follow-up {{ border-left:3px solid #b7791f; margin-top:10px; padding:6px 10px; }}
.issue-follow-up h4 {{ font-size:12px; margin:0 0 4px; text-transform:uppercase; }}
.issue-follow-up h4:not(:first-child) {{ margin-top:10px; }}
.table-wrap,.decision-table {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ border-bottom:1px solid var(--line); padding:8px; text-align:left; vertical-align:top; }}
th {{ color:var(--muted); font-size:12px; }}
code {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
.muted {{ color:var(--muted); }}
.source-link,.finding-jump {{ color:var(--accent); text-decoration:none; overflow-wrap:anywhere; }}
.source-link:hover,.source-link:focus,.finding-jump:hover,.finding-jump:focus {{ text-decoration:underline; }}
.source-reference {{ overflow-wrap:anywhere; cursor:text; user-select:all; }}
.source-open {{ display:inline-block; font-size:10px; margin-left:3px; vertical-align:top; }}
.finding-jump {{ font:700 12px ui-monospace,SFMono-Regular,Menlo,monospace; margin-right:6px; }}
.closure-row {{ scroll-margin-top:16px; }}
details {{ border-top:1px solid var(--line); margin-top:12px; padding-top:10px; }}
details > summary {{ cursor:pointer; font-weight:700; color:var(--muted); }}
.technical-details {{ border:0; margin-top:8px; padding-top:0; }}
.sr-only {{ position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }}
ul {{ margin:0; padding-left:18px; }}
p {{ margin:0 0 12px; }}
@media (max-width:900px) {{ .instrumentation-stats,.proof-stats {{ grid-template-columns:repeat(3,minmax(0,1fr)); }} }}
@media (max-width:760px) {{ .selected-issue-grid,.finding-proof,.coverage-detail-body {{ grid-template-columns:1fr; }} .finding-proof > h4,.proof-summary,.telemetry-proof-summary,.coverage-details {{ grid-column:1; }} }}
@media (max-width:620px) {{ .impact-stats,.instrumentation-stats {{ grid-template-columns:1fr 1fr; }} }}
</style>
</head>
<body>
<header><div class="wrap">
  <div class="eyebrow">OpenTelemetry instrumentation report</div>
  <h1>{title}</h1>
  <div class="meta">
    <span>audit <b>{esc(report['meta']['audit_id'])}</b></span>
    <span>audit baseline commit <b>{esc(report['meta']['commit'])}</b></span>
    <span>date <b>{esc(instrumentation['meta']['date'])}</b></span>
  </div>
  <nav class="report-nav" aria-label="Report artifacts">
    <a href="otel.html">Audit and scope report</a>
    {verify_status}
  </nav>
</div></header>
<main class="wrap">
  <section class="summary" aria-labelledby="instrumentation-status-heading">{summary}</section>
  <section class="panel" aria-labelledby="selected-issues-heading">
    <h2 id="selected-issues-heading">Selected issues and changes</h2>
    <p class="muted">Every issue in the dependency-closed instrumentation scope is listed once.</p>
    <p class="review-note">Each issue shows what changed, how observability improves, telemetry-item proof, scenario coverage, and any remaining uncertainty.</p>
    {selected_issues}
  </section>
  {remaining_section}
</main>
</body>
</html>
"""


def render_html(
    report: dict[str, Any],
    selection: dict[str, Any],
    source_root: Path | None = None,
    output_dir: Path | None = None,
    include_service_root: bool = True,
) -> str:
    source_references = (
        build_source_references(
            [report],
            source_root,
            output_dir,
        )
        if source_root is not None and output_dir is not None
        else {}
    )
    initial_decision_answers = selection.get("decision_answers", [])
    selection_eligibility = report_selection_eligibility(
        report, initial_decision_answers
    )
    payload = script_json(
        {
            "report": report,
            "selection": selection,
            "selection_eligibility": selection_eligibility,
            "ao_target_eligible_finding_ids": ao_target_eligible_finding_ids(report),
            "display_finding_ids": display_finding_ids(report),
            "source_references": source_references,
            "service_root": (
                quote(str(source_root.resolve()), safe="")
                if include_service_root and source_root is not None
                else None
            ),
        }
    )
    mode_guidance_payload = script_json(MODE_GUIDANCE)
    title = esc(report["meta"]["service_name"])
    findings = report["findings"]
    ao_target = selection.get("ao_target", {})
    ao_controls = ""
    if ao_target_eligible_finding_ids(report):
        resource_controls = []
        for resource, label in (("project", "Project"), ("agent_stream", "Agent Stream")):
            selector = "id" if f"{resource}_id" in ao_target else "name"
            value = ao_target.get(f"{resource}_{selector}", "")
            resource_controls.append(
                f'<div class="ao-target-resource"><label for="ao-{resource}-selector">{label} selector</label>'
                f'<select id="ao-{resource}-selector" data-ao-selector="{resource}">'
                f'<option value="name"{" selected" if selector == "name" else ""}>Name</option>'
                f'<option value="id"{" selected" if selector == "id" else ""}>ID</option></select>'
                f'<label id="ao-{resource}-label" for="ao-{resource}-value">{label} {selector.upper() if selector == "id" else "name"}</label>'
                f'<input id="ao-{resource}-value" data-ao-value="{resource}" type="text" '
                f'aria-describedby="ao-target-help ao-target-error" value="{esc(value)}"></div>'
            )
        ao_controls = (
            '<fieldset id="ao-target-controls" class="ao-target-controls" hidden inert>'
            '<legend>Agent Observability destination (optional)</legend>'
            '<p id="ao-target-help">Provide both resources, or leave both blank to use the application configuration. '
            'Named resources are reused or created if missing. IDs always select existing resources. '
            'Changing these values does not select findings.</p>'
            '<div class="ao-target-grid">' + "".join(resource_controls) + '</div>'
            '<label class="ao-reuse-only" for="ao-reuse-only"><input id="ao-reuse-only" type="checkbox"'
            + (' checked' if ao_target.get("create_if_missing") is False else '')
            + '> Reuse existing resources only</label>'
            '<p id="ao-target-error" class="ao-target-error" aria-live="polite"></p></fieldset>'
        )
    decision_view = render_decision_overview(report, selection)
    technical_summary = render_list(report["summary"])
    evidence_table = html_table(
        ["Check", "Finding", "Source"],
        [[row["check"], row["finding"], row["source"]] for row in report["evidence"]],
        source_columns={2},
        source_references=source_references,
    )
    environments_table = html_table(
        ["ID", "Surface", "Config evidence", "Runner", "Scope", "Prerequisites"],
        [[row["id"], row["surface"], row["config_evidence"], row["runner"], row["scope"], row["prerequisites"]] for row in report["verification"]["environments"]],
        source_columns={2},
        source_references=source_references,
    )
    scenarios_table = html_table(
        ["ID", "Trigger", "Source entrypoint", "Expected signals", "Proof", "Acceptance"],
        [[row["id"], row["trigger"], row["entrypoint"], row["expected_signals"], row["proof_level"], row["acceptance_criteria"]] for row in report["verification"]["scenarios"]],
        source_columns={2},
        source_references=source_references,
    )
    spans_table = html_table(
        ["Span", "Source", "Type"],
        [[row["name"], row["source"], row["type"]] for row in report["current_instrumentation"]["spans"]],
        source_columns={1},
        source_references=source_references,
    )
    metrics_table = html_table(
        ["Metric", "Source", "Type"],
        [[row["name"], row["source"], row["type"]] for row in report["current_instrumentation"]["metrics"]],
        source_columns={1},
        source_references=source_references,
    )
    logs_table = html_table(
        ["Log integration", "Source", "Detail"],
        [[row["integration"], row["source"], row["detail"]] for row in report["current_instrumentation"]["logs"]],
        source_columns={1},
        source_references=source_references,
    )
    scan_blockers_section = ""
    if report.get("scan_blockers"):
        scan_blockers_table = html_table(
            ["ID", "Check", "Blocked scope", "Prerequisite", "Evidence", "Required action"],
            [
                [
                    row["id"],
                    row["check"],
                    " · ".join(row["blocked_scope"]),
                    row["prerequisite"],
                    " · ".join(row["evidence"]),
                    row["required_action"],
                ]
                for row in report["scan_blockers"]
            ],
        )
        scan_blockers_section = (
            '<section class="panel scan-blockers" aria-labelledby="scan-blockers-heading">'
            '<h2 id="scan-blockers-heading">Scan incomplete</h2>'
            '<p>The audit could not inspect all required source. Resolve these prerequisites before treating the findings as complete.</p>'
            f"{scan_blockers_table}</section>"
        )
    existing_evidence_sections: list[str] = []
    if report["current_instrumentation"]["spans"]:
        existing_evidence_sections.append(f"<h3>Span candidates / definitions</h3>{spans_table}")
    if report["current_instrumentation"]["metrics"]:
        existing_evidence_sections.append(f"<h3>Metric definitions</h3>{metrics_table}")
    if report["current_instrumentation"]["logs"]:
        existing_evidence_sections.append(f"<h3>Log integrations</h3>{logs_table}")
    existing_evidence = "".join(existing_evidence_sections) or '<p class="muted">None recorded.</p>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OTel Audit - {title}</title>
<style>
:root {{
  --bg: #f5f7fa;
  --surface: #ffffff;
  --ink: #17202a;
  --muted: #5f6b7a;
  --line: #dbe2ea;
  --accent: #1f5eff;
  --ok: #16794c;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--ink); font: 14px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding-bottom: 88px; }}
header {{ background: #121821; color: #eef2f7; padding: 28px 0; }}
.wrap {{ max-width: 1040px; margin: 0 auto; padding: 0 20px; }}
.eyebrow {{ color: #9aa8ba; font-size: 11px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }}
h1 {{ margin: 8px 0 4px; font-size: clamp(26px, 4vw, 38px); line-height: 1.1; }}
.meta {{ color: #b8c2cf; display: flex; flex-wrap: wrap; gap: 14px; font-size: 13px; }}
.meta b {{ color: #fff; }}
.report-nav {{ display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 14px; }}
.report-nav a {{ color: #91b8ff; }}
.summary {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; margin: 18px 0; padding: 16px 18px; }}
.summary h2, .panel h2 {{ font-size: 14px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin: 0 0 10px; }}
.decision-context {{ display: grid; grid-template-columns: 1fr; gap: 10px; margin-bottom: 10px; }}
.decision-context section {{ border: 1px solid var(--line); border-radius: 7px; padding: 10px 11px; background: #fbfcfe; }}
.decision-context p {{ margin-bottom: 0; }}
.decision-table-link {{ color: var(--accent); text-decoration: none; }}
.decision-table-link code {{ color: var(--muted); font-size: 11px; }}
.decision-table-link:hover strong, .decision-table-link:focus strong {{ text-decoration: underline; }}
.finding-jump {{ display: inline-block; color: var(--accent); font: 700 12px ui-monospace, SFMono-Regular, Menlo, monospace; margin: 0 5px 3px 0; text-decoration: none; }}
.finding-jump:hover, .finding-jump:focus {{ text-decoration: underline; }}
.review-note {{ border-left: 3px solid var(--accent); margin: 13px 0; padding: 8px 10px; background: #f4f7ff; }}
.decision-table {{ overflow-x: auto; }}
.summary details {{ border-top: 1px solid var(--line); margin-top: 14px; padding-top: 10px; }}
.summary details > summary {{ cursor: pointer; font-weight: 700; color: var(--muted); }}
.impact-panel {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; margin: 18px 0; padding: 16px 18px; overflow-x: auto; }}
.impact-panel h2 {{ font-size: 14px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin: 0 0 10px; }}
.impact-stats {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-bottom: 10px; }}
.impact-stats div {{ border: 1px solid var(--line); border-radius: 7px; background: #fbfcfe; padding: 9px 10px; }}
.impact-stats span {{ display: block; color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .06em; }}
.impact-stats strong {{ display: block; margin-top: 2px; font-size: 18px; }}
.impact-panel details > summary {{ cursor: pointer; font-weight: 700; margin-top: 12px; }}
.findings-section {{ margin: 18px 0; }}
.findings-section > h2 {{ color: var(--ink); font-size: 18px; margin: 0 0 12px; }}
.findings-total {{ color: var(--muted); font-size: 13px; font-weight: 600; }}
.finding-subsection + .finding-subsection {{ margin-top: 22px; }}
.finding-subsection > h3 {{ color: var(--ink); font-size: 15px; letter-spacing: normal; margin: 0 0 10px; text-transform: none; }}
.card {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; margin-bottom: 10px; overflow: hidden; }}
.card.done {{ border-color: #9bd5b7; }}
.card.done .spine {{ background: var(--ok); }}
.card.working {{ border-color: #9bd5b7; }}
.card-head {{ display: grid; grid-template-columns: minmax(0, 1fr) max-content; align-items: center; }}
.row {{ display: grid; grid-template-columns: 5px minmax(72px, auto) minmax(0, 1fr) auto; gap: 12px; align-items: center; width: 100%; text-align: left; border: 0; background: transparent; color: inherit; padding: 13px 14px 13px 0; cursor: pointer; font: inherit; }}
.spine {{ align-self: stretch; background: var(--accent); }}
.fid {{ font: 700 13px ui-monospace, SFMono-Regular, Menlo, monospace; }}
.finding-copy {{ min-width: 0; }}
.ftitle {{ display: block; font-weight: 700; }}
.fimpact {{ display: block; color: var(--muted); font-size: 12px; line-height: 1.35; margin-top: 2px; }}
.finding-meta {{ align-items: center; color: var(--muted); display: flex; flex-wrap: wrap; font-size: 11px; font-weight: 600; gap: 4px 12px; margin-top: 5px; }}
.finding-meta strong {{ color: var(--ink); }}
.finding-meta code {{ color: var(--ink); font-size: 10px; }}
.plan-select {{ display: flex; gap: 7px; align-items: center; border: 1px solid var(--line); border-radius: 6px; margin-right: 14px; padding: 5px 9px; color: var(--muted); background: #fff; }}
.plan-select.on {{ border-color: var(--ok); color: var(--ok); background: #eef8f2; }}
.plan-select.included {{ border-color: #b7791f; color: #7a4a00; background: #fff8e8; }}
.plan-unavailable {{ max-width: 220px; margin-right: 14px; color: var(--muted); font-size: 11px; font-weight: 700; line-height: 1.3; text-align: right; }}
.decision-select {{ grid-column: 1 / -1; min-width: 0; border: 0; border-top: 1px solid var(--line); margin: 0; padding: 12px 14px 14px; background: #fbfcfe; }}
.decision-select legend {{ width: 100%; color: var(--ink); font-weight: 700; padding: 0 0 8px; }}
.decision-options {{ display: grid; gap: 7px; }}
.decision-option {{ display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 2px 8px; align-items: start; border: 1px solid var(--line); border-radius: 6px; background: #fff; padding: 8px 10px; cursor: pointer; }}
.decision-option:has(input:checked) {{ border-color: var(--accent); background: #f4f7ff; }}
.decision-option input {{ margin-top: 3px; }}
.decision-option strong, .decision-option span {{ grid-column: 2; }}
.decision-option span {{ color: var(--muted); font-size: 12px; }}
.decision-clear {{ border: 0; background: transparent; color: var(--accent); cursor: pointer; font-size: 11px; margin-top: 8px; padding: 0; text-decoration: underline; }}
.ao-target-controls {{ margin: 20px 0 0; padding: 14px; border: 1px solid var(--line); border-radius: 7px; background: #fbfcfe; min-width: 0; }}
.ao-target-controls legend {{ font-weight: 700; }}
.ao-target-controls p {{ color: var(--muted); font-size: 12px; }}
.ao-target-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }}
.ao-target-resource {{ display: grid; gap: 5px; min-width: 0; }}
.ao-target-resource input,.ao-target-resource select {{ box-sizing: border-box; width: 100%; min-width: 0; border: 1px solid var(--line); border-radius: 5px; background: #fff; color: var(--ink); font: inherit; padding: 7px 8px; }}
.ao-reuse-only {{ display: flex; gap: 7px; align-items: center; margin-top: 12px; }}
.ao-target-controls .ao-target-error {{ color: #b42318; margin: 8px 0 0; }}
@media (max-width: 620px) {{ .ao-target-grid {{ grid-template-columns: 1fr; }} }}
.caret {{ color: var(--muted); font-size: 20px; }}
.card.open .caret {{ transform: rotate(90deg); }}
.body {{ display: none; border-top: 1px solid var(--line); background: #fbfcfe; padding: 16px 18px; }}
.card.open .body {{ display: block; }}
.cols {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }}
.finding-technical-details {{ border-top: 1px solid var(--line); margin-top: 4px; padding-top: 12px; }}
.finding-technical-details > summary {{ align-items: baseline; color: var(--accent); cursor: pointer; display: flex; flex-wrap: wrap; font-weight: 700; gap: 5px 10px; }}
.detail-counts {{ color: var(--muted); font-size: 12px; font-weight: 600; }}
.technical-details-body {{ margin-top: 14px; }}
.technical-details-body > section, .technical-details-body > .cols + section {{ margin-top: 14px; }}
@media (max-width: 760px) {{ .impact-stats, .decision-context {{ grid-template-columns: 1fr; }} .card-head {{ grid-template-columns: 1fr; }} .row {{ grid-template-columns: 5px auto 1fr auto; }} .plan-select, .plan-unavailable {{ justify-self: end; margin: 0 14px 12px; width: max-content; }} .decision-select {{ grid-column: 1; }} .cols {{ grid-template-columns: 1fr; }} }}
h3, .card h4 {{ margin: 0 0 6px; font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .1em; }}
p {{ margin: 0 0 12px; }}
ul {{ margin: 0; padding-left: 18px; }}
code, pre {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
.source-link {{ color: var(--accent); text-decoration: none; overflow-wrap: anywhere; }}
.source-link:hover, .source-link:focus {{ text-decoration: underline; }}
.source-link code {{ color: inherit; }}
.source-reference {{ overflow-wrap: anywhere; cursor: text; user-select: all; }}
.source-open {{ display: inline-block; margin-left: 3px; font-size: 10px; vertical-align: top; }}
pre {{ background: #111827; color: #edf2f7; border-radius: 6px; padding: 10px; overflow-x: auto; white-space: pre-wrap; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ border-bottom: 1px solid var(--line); padding: 7px 8px; text-align: left; vertical-align: top; }}
th {{ color: var(--muted); font-size: 12px; }}
.panel {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 16px 18px; margin: 18px 0; overflow-x: auto; }}
.panel details > summary {{ cursor: pointer; font-weight: 700; }}
.technical-appendix h2:not(:first-child) {{ margin-top: 22px; }}
.context-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }}
.context-grid .panel {{ margin: 0; }}
.proof {{ border-left: 3px solid var(--ok); padding-left: 12px; }}
.muted {{ color: var(--muted); }}
.tray {{ position: fixed; z-index: 20; left: 0; right: 0; bottom: 0; background: #121821; color: #fff; box-shadow: 0 -8px 24px rgba(18, 24, 33, .18); }}
.tray[hidden] {{ display: none; }}
.tray-bar {{ padding-top: 12px; padding-bottom: 12px; }}
.tray-hint {{ display: block; color: #d3d9e2; font-size: 11px; line-height: 1.4; margin-top: 3px; }}
.tray-hint code {{ color: #91f0b8; }}
.tray-command {{ min-width: 0; }}
.instrument-command {{ display: block; margin-top: 4px; width: 100%; overflow-x: auto; white-space: nowrap; background: #0b111a; border: 1px solid #253143; border-radius: 6px; color: #91f0b8; padding: 7px 9px; font: inherit; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
.sr-only {{ position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }}
@media (max-width: 760px) {{
  body {{ padding-bottom: 96px; }}
  .context-grid {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<header>
  <div class="wrap">
    <div class="eyebrow">OpenTelemetry audit report</div>
    <h1>{title}</h1>
    <div class="meta">
      <span>audit <b>{esc(report['meta']['audit_id'])}</b></span>
      <span>commit <b>{esc(report['meta']['commit'])}</b></span>
      <span>language <b>{esc(report['meta']['language'])}</b></span>
      <span>framework <b>{esc(report['meta']['framework'])}</b></span>
      <span>date <b>{esc(report['meta']['date'])}</b></span>
      <span><b>{len(findings)}</b> findings</span>
    </div>
    <nav class="report-nav" aria-label="Report formats">
      <a href="otel-audit.json">Canonical audit data (JSON)</a>
    </nav>
  </div>
</header>
<main class="wrap">
  <section class="summary">
    <h2>Executive Summary</h2>
    {decision_view}
  </section>
{scan_blockers_section}
  <section class="findings-section" aria-labelledby="findings-heading">
    <h2 id="findings-heading" tabindex="-1">Findings <span class="findings-total">· {len(findings)}</span></h2>
    <div id="cards"></div>
    {ao_controls}
  </section>
  <section class="panel technical-appendix"><details><summary>Technical appendix</summary>
    <h2>Source-visible instrumentation evidence</h2>{existing_evidence}
    <h2>Verification plan</h2>
    <h3>Test environments</h3>{environments_table}
    <h3>Acceptance scenarios</h3>{scenarios_table}
    <h2>Audit notes</h2>{technical_summary}
    <h2>Audit Evidence</h2>{evidence_table}
    <h2>Recommendation</h2>{render_list(report['recommendation'])}
  </details></section>
</main>
<div class="tray" id="tray" hidden inert aria-hidden="true" aria-label="Instrumentation selection">
  <div class="wrap tray-bar">
    <div class="tray-command" aria-labelledby="instrumentCommandLabel">
      <span class="tray-hint" id="instrumentCommandLabel">Copy this prompt and paste into AI chat</span>
      <input class="instrument-command" id="instrumentCommand" type="text" readonly aria-labelledby="instrumentCommandLabel">
    </div>
  </div>
</div>
<div id="selectionStatus" class="sr-only" aria-live="polite" aria-atomic="true"></div>
<script>
const DATA = {payload};
const REPORT = DATA.report;
const modeGuidance = {mode_guidance_payload};
const selectionEligibility = {{}};
const requested = new Set(DATA.selection?.requested_ids || DATA.selection?.approved_ids || []);
const selected = new Set(DATA.selection?.approved_ids || []);
const decisionAnswers = new Map(
  (DATA.selection?.decision_answers || []).map(answer => [answer.finding_id, answer.option_id])
);
const esc = (value) => String(value ?? "").replace(/[&<>"]/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}}[c]));
const byId = new Map(REPORT.findings.map(f => [f.id, f]));
const DISPLAY_FINDINGS = (DATA.display_finding_ids || REPORT.findings.map(f => f.id))
  .map(id => byId.get(id))
  .filter(Boolean);
const isSelectable = id => selectionEligibility[id]?.selectable === true;

function selectedDecisionOption(finding) {{
  const optionId = decisionAnswers.get(finding.id);
  return (finding.decision_options || []).find(option => option.id === optionId) || null;
}}

function selectionBlockersFor(findingId) {{
  const blocked = new Set();
  const visiting = new Set([findingId]);
  function visit(dependencyId, dependentId) {{
    if (visiting.has(dependencyId)) return;
    const dependency = byId.get(dependencyId);
    if (!dependency) return;
    if (dependency.instrument_mode === "manual decision") {{
      const option = selectedDecisionOption(dependency);
      if (!option || !(option.unlocks || []).includes(dependentId)) {{
        blocked.add(dependencyId);
        return;
      }}
      visiting.add(dependencyId);
      for (const nestedId of dependency.dependencies || []) visit(nestedId, dependencyId);
      visiting.delete(dependencyId);
      return;
    }}
    if (["default", "fix all"].includes(dependency.instrument_mode) && dependency.status === "done") {{
      return;
    }}
    if (["default", "fix all"].includes(dependency.instrument_mode) && ["rejected", "deferred"].includes(dependency.status)) {{
      blocked.add(dependencyId);
      return;
    }}
    if (!["default", "fix all"].includes(dependency.instrument_mode)) {{
      blocked.add(dependencyId);
      return;
    }}
    visiting.add(dependencyId);
    for (const nestedId of dependency.dependencies || []) visit(nestedId, dependencyId);
    visiting.delete(dependencyId);
  }}
  for (const dependencyId of byId.get(findingId)?.dependencies || []) {{
    visit(dependencyId, findingId);
  }}
  return REPORT.findings.map(finding => finding.id).filter(id => blocked.has(id));
}}

function eligibilityFor(finding) {{
  if (finding.instrument_mode === "manual decision") {{
    return {{
      selectable: false,
      blockers: [],
      reason: selectedDecisionOption(finding)
        ? "Decision recorded"
        : (finding.decision_options || []).length
          ? "Choose an answer"
          : "Resolve decision first",
    }};
  }}
  if (finding.instrument_mode === "external follow-up") {{
    return {{selectable:false, blockers:[], reason:"Not selectable for instrumentation"}};
  }}
  if (["done", "rejected", "deferred"].includes(finding.status)) {{
    return {{selectable:false, blockers:[], reason:"Finding is " + finding.status}};
  }}
  const blockers = selectionBlockersFor(finding.id);
  return blockers.length
    ? {{selectable:false, blockers, reason:"Blocked by " + blockers.join(", ")}}
    : {{selectable:true, blockers:[], reason:""}};
}}

function refreshSelectionEligibility() {{
  for (const finding of REPORT.findings) {{
    selectionEligibility[finding.id] = eligibilityFor(finding);
  }}
}}

refreshSelectionEligibility();

function sourceHtml(value) {{
  const parts = DATA.source_references?.[String(value)];
  if (!parts) return `<code>${{esc(value)}}</code>`;
  return parts.map(part => {{
    if (!part.href) return esc(part.text);
    if (location.protocol === "http:" || location.protocol === "https:") {{
      return `<span class="source-reference" title="Copy this repository-relative source path"><code>${{esc(part.text)}}</code></span>`;
    }}
    return `<a class="source-link" href="${{esc(part.href)}}" target="_blank" rel="noopener" title="Open local source file"><code>${{esc(part.text)}}</code><span class="source-open" aria-hidden="true">↗</span></a>`;
  }}).join("");
}}

function neutralizeHttpSourceLinks() {{
  if (location.protocol !== "http:" && location.protocol !== "https:") return;
  for (const link of document.querySelectorAll("a.source-link")) {{
    const replacement = document.createElement("span");
    replacement.className = "source-reference";
    replacement.title = "Copy this repository-relative source path";
    replacement.innerHTML = link.querySelector("code")?.outerHTML || esc(link.textContent);
    link.replaceWith(replacement);
  }}
}}

function lifecycleStatus(f) {{
  if (requested.has(f.id)) return "selected";
  if (selected.has(f.id)) return "included";
  return f.status;
}}

function decisionSelectionControl(finding) {{
  const options = finding.decision_options || [];
  if (finding.instrument_mode !== "manual decision" || !options.length) return "";
  const selectedOption = selectedDecisionOption(finding);
  const optionRows = options.map(option => {{
    const inputId = `decision-${{finding.id}}-${{option.id}}`;
    return `<label class="decision-option" for="${{esc(inputId)}}">
      <input id="${{esc(inputId)}}" name="decision-${{esc(finding.id)}}" type="radio"
        data-decision-id="${{esc(finding.id)}}" data-option-id="${{esc(option.id)}}"
        ${{selectedOption?.id === option.id ? "checked" : ""}}>
      <strong>${{esc(option.label)}}</strong><span>${{esc(option.outcome)}}</span>
    </label>`;
  }}).join("");
  const clear = selectedOption
    ? `<button class="decision-clear" type="button" data-clear-decision="${{esc(finding.id)}}">Clear answer</button>`
    : "";
  return `<fieldset class="decision-select" data-decision-control="${{esc(finding.id)}}">
    <legend>${{esc(finding.decision_question || "Choose one telemetry outcome")}}</legend>
    <div class="decision-options">${{optionRows}}</div>${{clear}}
  </fieldset>`;
}}

function findingSelectionPresentation(finding) {{
  const explicitlySelected = requested.has(finding.id);
  const autoIncluded = selected.has(finding.id) && !explicitlySelected;
  return {{
    explicitlySelected,
    autoIncluded,
    label: autoIncluded
      ? "Included as dependency"
      : modeGuidance[finding.instrument_mode].selection,
    ariaLabel: autoIncluded
      ? `${{finding.id}} is included as a required dependency; select it explicitly to keep it if dependent work is removed`
      : `Select ${{finding.id}} for instrumentation`,
  }};
}}

function syncFindingSelectionControl(input, finding) {{
  const presentation = findingSelectionPresentation(finding);
  input.checked = presentation.explicitlySelected;
  input.indeterminate = presentation.autoIncluded;
  input.dataset.selectionState = presentation.autoIncluded
    ? "dependency"
    : presentation.explicitlySelected
      ? "selected"
      : "available";
  input.setAttribute("aria-label", presentation.ariaLabel);
  const control = input.closest(".plan-select");
  control?.classList.toggle("on", presentation.explicitlySelected);
  control?.classList.toggle("included", presentation.autoIncluded);
  const label = control?.querySelector("[data-selection-label]");
  if (label) label.textContent = presentation.label;
}}

function findingPrimaryActionLabel(finding) {{
  if (finding.instrument_mode === "manual decision") return "Decision needed";
  if (finding.instrument_mode === "external follow-up") return "External requirement";
  if (finding.finding_group === "splunk-agent-observability") return "Agent Observability change";
  return "Instrumentation change";
}}

function telemetryShapeFor(finding) {{
  const order = ["span", "metric", "log", "resource", "configuration"];
  const counts = new Map(order.map(type => [type, 0]));
  (finding.expected_telemetry || []).forEach(item => counts.set(item.type, (counts.get(item.type) || 0) + 1));
  return order
    .filter(type => counts.get(type))
    .map(type => `${{counts.get(type)}} ${{type}}${{counts.get(type) === 1 ? "" : "s"}}`)
    .join(" · ") || "not specified";
}}

function findingNextStep(finding) {{
  const eligibility = selectionEligibility[finding.id] || {{selectable:false, blockers:[], reason:"Not selectable for instrumentation"}};
  if (finding.instrument_mode === "manual decision") {{
    const option = selectedDecisionOption(finding);
    if (!option) {{
      return `Choose one answer with ${{finding.decision_owner || "the named owner"}}, then select any unlocked executable work.`;
    }}
    return (option.unlocks || []).length
      ? "Review the executable work unlocked by this answer and select the work you want in the command."
      : "This answer unlocks no instrumentation work. Keep the decision in the audit; no selection is needed.";
  }}
  if (finding.instrument_mode === "external follow-up") {{
    const requirement = finding.external_requirement ? ` Required telemetry: ${{finding.external_requirement}}` : "";
    return `Track this with ${{finding.external_owner || "the named external owner"}}; it is not instrumentation scope for this service.${{requirement}}`;
  }}
  if ((eligibility.blockers || []).length) {{
    return `Resolve ${{eligibility.blockers.join(", ")}} first, then return to select this work.`;
  }}
  if (!eligibility.selectable) {{
    return `${{eligibility.reason || "This finding cannot enter the current instrumentation selection"}}.`;
  }}
  if (requested.has(finding.id)) {{
    return "This finding is selected. Copy the generated prompt and paste into AI chat.";
  }}
  if (selected.has(finding.id)) {{
    return "This finding is included because selected work depends on it. Copy the generated prompt and paste into AI chat.";
  }}
  return "Select this finding, then copy the generated prompt and paste into AI chat.";
}}

function renderFindingCard(f) {{
    const lifecycle = lifecycleStatus(f);
    const detailHeading = f.finding_group === "splunk-agent-observability" ? "h4" : "h3";
    const mode = modeGuidance[f.instrument_mode];
    const telemetry = (f.expected_telemetry || []).map(item => `<li><b>${{esc(item.type)}} ${{esc(item.name)}}</b> — ${{esc(item.product_view)}}${{item.attributes?.length ? ` <code>${{esc(item.attributes.join(", "))}}</code>` : ""}}</li>`).join("");
    const evidence = (f.evidence || []).map(item => `<li>${{sourceHtml(item)}}</li>`).join("");
    const acceptance = (f.acceptance_criteria || []).map(item => `<li>${{esc(item)}}</li>`).join("");
    const constraints = (f.constraints || []).map(item => `<li>${{esc(item)}}</li>`).join("");
    const countLabel = (count, singular) => `${{count}} ${{singular}}${{count === 1 ? "" : "s"}}`;
    const contractCounts = [
      countLabel((f.acceptance_criteria || []).length, "acceptance check"),
      countLabel((f.constraints || []).length, "implementation guardrail"),
      countLabel((f.evidence || []).length, "source reference"),
    ].join(" · ");
    const telemetryShape = telemetryShapeFor(f);
    const dependencyCue = (f.dependencies || []).length
      ? `<span>Plan prerequisite${{f.dependencies.length === 1 ? "" : "s"}}: <code>${{esc(f.dependencies.join(", "))}}</code></span>`
      : "";
    const primaryActionLabel = findingPrimaryActionLabel(f);
    const requiredAction = f.instrument_mode === "external follow-up"
      ? [f.required_fix, f.external_requirement ? `Required telemetry: ${{f.external_requirement}}` : "", f.external_owner ? `Owner: ${{f.external_owner}}` : ""].filter(Boolean).join(" ")
      : f.required_fix;
    const eligibility = selectionEligibility[f.id] || {{selectable:false, blockers:[], reason:"Not selectable for instrumentation"}};
    const decisionControl = decisionSelectionControl(f);
    const selectionPresentation = findingSelectionPresentation(f);
    const selectionControl = decisionControl || (eligibility.selectable
      ? (() => {{
          const selectionClasses = [
            selectionPresentation.explicitlySelected ? "on" : "",
            selectionPresentation.autoIncluded ? "included" : "",
          ].filter(Boolean).join(" ");
          return `<label class="plan-select ${{selectionClasses}}" for="plan-${{esc(f.id)}}" title="${{esc(mode.guidance)}}">
            <input id="plan-${{esc(f.id)}}" name="plan-${{esc(f.id)}}" type="checkbox" aria-label="${{esc(selectionPresentation.ariaLabel)}}" data-id="${{esc(f.id)}}" data-selection-state="${{selectionPresentation.autoIncluded ? "dependency" : selectionPresentation.explicitlySelected ? "selected" : "available"}}" ${{selectionPresentation.explicitlySelected ? "checked" : ""}}> <span data-selection-label>${{esc(selectionPresentation.label)}}</span>
          </label>`;
        }})()
      : `<div class="plan-unavailable" role="note">${{esc(eligibility.reason)}}</div>`);
    return `<article class="card ${{["done","working"].includes(lifecycle) ? lifecycle : ""}}" id="${{esc(f.id)}}">
      <div class="card-head">
        <button class="row" id="finding-toggle-${{esc(f.id)}}" type="button" aria-expanded="false" aria-controls="finding-body-${{esc(f.id)}}">
          <span class="spine" aria-hidden="true"></span>
          <span class="fid">${{esc(f.id)}}</span>
          <span class="finding-copy"><span class="ftitle">${{esc(f.title)}}</span><span class="fimpact">What you get: ${{esc(f.product_outcome)}}</span><span class="finding-meta"><span>Telemetry: <strong>${{esc(telemetryShape)}}</strong></span>${{dependencyCue}}</span></span>
          <span class="caret" aria-hidden="true">›</span>
        </button>
        ${{selectionControl}}
      </div>
      <div class="body" id="finding-body-${{esc(f.id)}}" aria-labelledby="finding-toggle-${{esc(f.id)}}" hidden>
        <div class="cols">
          <section><${{detailHeading}}>Gap</${{detailHeading}}><p>${{esc(f.gap)}}</p></section>
          <section><${{detailHeading}}>Why it matters</${{detailHeading}}><p>${{esc(f.impact)}}</p></section>
          <section><${{detailHeading}}>${{esc(primaryActionLabel)}}</${{detailHeading}}><p>${{esc(requiredAction)}}</p></section>
          <section><${{detailHeading}}>Next step</${{detailHeading}}><p data-finding-next-step="${{esc(f.id)}}">${{esc(findingNextStep(f))}}</p></section>
        </div>
        <details class="finding-technical-details">
          <summary><span>Technical details</span> <span class="detail-counts">${{esc(contractCounts)}}</span></summary>
          <div class="technical-details-body">
            <section><${{detailHeading}}>Expected telemetry</${{detailHeading}}>${{telemetry ? `<ul>${{telemetry}}</ul>` : `<p class="muted">None recorded.</p>`}}</section>
            <section><${{detailHeading}}>Acceptance criteria</${{detailHeading}}><ul>${{acceptance}}</ul></section>
            ${{constraints ? `<section><${{detailHeading}}>Implementation guardrails</${{detailHeading}}><ul>${{constraints}}</ul></section>` : ""}}
            <section><${{detailHeading}}>Evidence</${{detailHeading}}>${{evidence ? `<ul>${{evidence}}</ul>` : `<p class="muted">None recorded.</p>`}}</section>
          </div>
        </details>
      </div>
    </article>`;
}}

function renderCards() {{
  const rendered = DISPLAY_FINDINGS.map(f => ({{finding: f, html: renderFindingCard(f)}}));
  const bands = [];
  for (const row of rendered) {{
    const last = bands[bands.length - 1];
    if (last && last.priority === row.finding.priority) last.rows.push(row);
    else bands.push({{priority: row.finding.priority, rows: [row]}});
  }}
  const subsection = (id, label, rows) => rows.length
    ? `<section class="finding-subsection" aria-labelledby="${{esc(id)}}"><h3 id="${{esc(id)}}">${{esc(label)}} <span class="findings-total">· ${{rows.length}}</span></h3>${{rows.map(row => row.html).join("")}}</section>`
    : "";
  document.getElementById("cards").innerHTML = bands.map(band => {{
    const openTelemetry = band.rows.filter(row => row.finding.finding_group !== "splunk-agent-observability");
    const agentObservability = band.rows.filter(row => row.finding.finding_group === "splunk-agent-observability");
    return openTelemetry.map(row => row.html).join("")
      + subsection(`splunk-agent-observability-${{band.priority}}-findings-heading`, "Splunk Agent Observability findings", agentObservability);
  }}).join("");
  syncFindingSelectionState();
}}

function orderedSelection() {{
  return REPORT.findings.map(f => f.id).filter(id => selected.has(id) && isSelectable(id));
}}

function orderedRequested() {{
  return REPORT.findings.map(f => f.id).filter(id => requested.has(id) && selected.has(id) && isSelectable(id));
}}

function orderedDecisionAnswers() {{
  return REPORT.findings
    .filter(finding => decisionAnswers.has(finding.id))
    .map(finding => ({{finding_id:finding.id, option_id:decisionAnswers.get(finding.id)}}));
}}

function announceSelection(message) {{
  document.getElementById("selectionStatus").textContent = message;
}}

function shellQuote(value) {{
  return "'" + String(value).replaceAll("'", "'\\\"'\\\"'") + "'";
}}

function commandPart(value) {{
  const text = String(value);
  return /^--[A-Za-z0-9][A-Za-z0-9_-]*$/.test(text) || /^[A-Za-z0-9_,.=:-]+$/.test(text)
    ? text
    : shellQuote(text);
}}

function serviceRootFromLocation() {{
  if (DATA.service_root) return decodeURIComponent(DATA.service_root);
  if (location.protocol === "file:") {{
    let path = decodeURIComponent(location.pathname || "");
    if (location.hostname) {{
      path = `//${{location.hostname}}${{path}}`;
    }} else if (/^\\/[A-Za-z]:\\//.test(path)) {{
      path = path.slice(1);
    }}
    const marker = "/.observe/";
    const index = path.lastIndexOf(marker);
    if (index > 0) return path.slice(0, index);
  }}
  return "";
}}

function terminalInstrumentCommand() {{
  const ids = orderedRequested();
  if (!ids.length) {{
    return "Select at least one executable finding to generate an instrumentation command.";
  }}
  const serviceRoot = serviceRootFromLocation();
  if (!serviceRoot) {{
    return "Regenerate this report with its validated service root before instrumenting.";
  }}
  const parts = ["$otel-instrument", "--ids", ids.join(",")];
  for (const answer of orderedDecisionAnswers()) {{
    parts.push("--decision", `${{answer.finding_id}}=${{answer.option_id}}`);
  }}
  const target = aoTargetArguments();
  if (target.error) return target.error;
  parts.push(...target.parts);
  parts.push(serviceRoot);
  return parts.map((part, index) => index === 0 ? part : commandPart(part)).join(" ");
}}

function renderInstrumentCommand() {{
  const node = document.getElementById("instrumentCommand");
  if (node) node.value = terminalInstrumentCommand();
}}

function renderTray() {{
  const requestedIds = orderedRequested();
  const hasSelection = requestedIds.length > 0 || decisionAnswers.size > 0;
  const tray = document.getElementById("tray");
  tray.hidden = !hasSelection;
  tray.toggleAttribute("inert", !hasSelection);
  tray.setAttribute("aria-hidden", String(!hasSelection));
  const aoControls = document.getElementById("ao-target-controls");
  if (aoControls) {{
    const hasAo = hasSelectedAoConfiguration();
    aoControls.hidden = !hasAo;
    aoControls.toggleAttribute("inert", !hasAo);
  }}
  renderInstrumentCommand();
}}

function hasSelectedAoConfiguration() {{
  return (DATA.ao_target_eligible_finding_ids || []).some(id => selected.has(id));
}}

function aoTargetArguments() {{
  if (!hasSelectedAoConfiguration()) return {{parts: [], error: ""}};
  const resources = ["project", "agent_stream"].map(resource => ({{
    resource,
    selector: document.getElementById(`ao-${{resource}}-selector`)?.value || "name",
    rawValue: document.getElementById(`ao-${{resource}}-value`)?.value || "",
    value: (document.getElementById(`ao-${{resource}}-value`)?.value || "").trim(),
  }}));
  const hasValue = resources.some(resource => resource.value);
  const reuseOnly = document.getElementById("ao-reuse-only")?.checked || false;
  const invalidResources = resources.filter(resource => Array.from(resource.value).length > 512 || /\\p{{C}}/u.test(resource.rawValue));
  const invalid = invalidResources.length > 0;
  const error = invalid ? "Resource selectors must be at most 512 characters and contain no control characters."
    : hasValue && resources.some(resource => !resource.value)
      ? "Provide both the Project and Agent Stream, or clear both fields to use application configuration."
      : "";
  const errorNode = document.getElementById("ao-target-error");
  if (errorNode) errorNode.textContent = error;
  for (const resource of resources) {{
    document.getElementById(`ao-${{resource.resource}}-value`)?.setAttribute("aria-invalid",
      String(invalidResources.includes(resource) || (hasValue && !resource.value)));
  }}
  if (error || !hasValue) return {{parts: !error && reuseOnly ? ["--ao-reuse-only"] : [], error}};
  const parts = [];
  for (const resource of resources) {{
    const flag = (resource.resource === "project" ? "--ao-project" : "--ao-agent-stream")
      + (resource.selector === "id" ? "-id" : "");
    if (resource.value.startsWith("-")) parts.push(flag + "=" + resource.value);
    else parts.push(flag, resource.value);
  }}
  if (reuseOnly) parts.push("--ao-reuse-only");
  return {{parts, error: ""}};
}}

function updateAoTargetInput(resource, selectorChanged = false) {{
  const selector = document.getElementById(`ao-${{resource}}-selector`);
  const input = document.getElementById(`ao-${{resource}}-value`);
  const label = document.getElementById(`ao-${{resource}}-label`);
  if (selectorChanged && input) input.value = "";
  if (label) label.textContent = (resource === "project" ? "Project" : "Agent Stream")
    + (selector?.value === "id" ? " ID" : " name");
  renderInstrumentCommand();
}}

function syncDependencyClosure() {{
  const closed = new Set();
  const visiting = new Set();
  function include(id) {{
    const finding = byId.get(id);
    if (!finding || closed.has(id) || visiting.has(id)) return;
    if (["default", "fix all"].includes(finding.instrument_mode) && finding.status === "done") return;
    const selectable = isSelectable(id);
    if (!selectable && finding.instrument_mode !== "manual decision") return;
    visiting.add(id);
    for (const dependency of finding.dependencies || []) include(dependency);
    visiting.delete(id);
    if (selectable) closed.add(id);
  }}
  for (const finding of REPORT.findings) {{
    if (requested.has(finding.id) && isSelectable(finding.id)) include(finding.id);
  }}
  selected.clear();
  for (const id of closed) selected.add(id);
}}

function pruneIncompatibleSelections() {{
  const removed = [];
  for (const finding of REPORT.findings) {{
    if (requested.has(finding.id) && !isSelectable(finding.id)) {{
      requested.delete(finding.id);
      removed.push(finding.id);
    }}
  }}
  return removed;
}}

function applyDecisionAnswer(decisionId, optionId) {{
  const finding = byId.get(decisionId);
  if (!finding || finding.instrument_mode !== "manual decision") return;
  const previous = decisionAnswers.get(decisionId);
  if (optionId) decisionAnswers.set(decisionId, optionId);
  else decisionAnswers.delete(decisionId);
  refreshSelectionEligibility();
  const removed = pruneIncompatibleSelections();
  syncDependencyClosure();
  renderCards();
  renderTray();
  const focusId = optionId ? `decision-${{decisionId}}-${{optionId}}` : `finding-toggle-${{decisionId}}`;
  document.getElementById(focusId)?.focus({{preventScroll:true}});
  const option = selectedDecisionOption(finding);
  let message = option
    ? `${{decisionId}} answer recorded: ${{option.label}}. Matching executable work is now available but has not been selected.`
    : `${{decisionId}} answer cleared. Dependent work is blocked again.`;
  if (previous && previous !== optionId) message = `${{decisionId}} answer changed to ${{option?.label || "unanswered"}}.`;
  if (removed.length) message += " Removed incompatible selected work: " + removed.join(", ") + ".";
  announceSelection(message);
}}

function syncFindingSelectionState() {{
  for (const finding of REPORT.findings) {{
    const card = document.getElementById(finding.id);
    if (!card) continue;
    const input = document.getElementById("plan-" + finding.id);
    if (input) {{
      syncFindingSelectionControl(input, finding);
    }}
    const nextStep = card.querySelector("[data-finding-next-step]");
    if (nextStep) nextStep.textContent = findingNextStep(finding);
  }}
}}

function applySelectionInput(input) {{
  const id = input.dataset.id;
  if (!isSelectable(id)) return;
  const before = new Set(selected);
  if (input.checked) requested.add(id);
  else requested.delete(id);
  syncDependencyClosure();
  syncFindingSelectionState();
  renderTray();

  const added = REPORT.findings.map(finding => finding.id)
    .filter(findingId => selected.has(findingId) && !before.has(findingId));
  const removed = REPORT.findings.map(finding => finding.id)
    .filter(findingId => before.has(findingId) && !selected.has(findingId));
  let message;
  if (input.checked) {{
    const dependencies = added.filter(findingId => findingId !== id);
    message = id + " selected.";
    if (dependencies.length) message += " Auto-added dependencies: " + dependencies.join(", ") + ".";
  }} else if (selected.has(id)) {{
    message = id + " remains included because another selected item requires it.";
  }} else {{
    message = id + " deselected.";
    const related = removed.filter(findingId => findingId !== id);
    if (related.length) message += " Removed no-longer-needed dependencies: " + related.join(", ") + ".";
  }}
  announceSelection(message);
}}

function setFindingOpen(card, open) {{
  const disclosure = card.querySelector(".row");
  const body = disclosure ? document.getElementById(disclosure.getAttribute("aria-controls")) : null;
  card.classList.toggle("open", open);
  disclosure?.setAttribute("aria-expanded", String(open));
  if (body) body.hidden = !open;
  return disclosure;
}}

function openFindingTarget(target) {{
  const disclosure = setFindingOpen(target, true);
  target.scrollIntoView({{behavior: "smooth", block: "start"}});
  disclosure?.focus({{preventScroll: true}});
}}

function targetFromHash(hash) {{
  if (!hash?.startsWith("#")) return null;
  try {{ return document.getElementById(decodeURIComponent(hash.slice(1))); }} catch (_) {{ return null; }}
}}

function revealCurrentHash() {{
  if (!location.hash) return;
  const target = targetFromHash(location.hash);
  if (target?.matches(".card")) openFindingTarget(target);
}}

document.addEventListener("click", event => {{
  const clearDecision = event.target.closest("[data-clear-decision]");
  if (clearDecision) {{
    applyDecisionAnswer(clearDecision.dataset.clearDecision, null);
    return;
  }}
  const findingJump = event.target.closest("[data-finding-jump][href]");
  if (findingJump) {{
    event.preventDefault();
    const target = targetFromHash(findingJump.getAttribute("href"));
    if (!target) return;
    openFindingTarget(target);
    history.replaceState(null, "", findingJump.getAttribute("href"));
    return;
  }}
  const row = event.target.closest(".row");
  if (!row) return;
  const card = row.closest(".card");
  setFindingOpen(card, !card.classList.contains("open"));
}});

document.addEventListener("change", event => {{
  const aoSelector = event.target.closest("select[data-ao-selector]");
  if (aoSelector) {{
    updateAoTargetInput(aoSelector.dataset.aoSelector, true);
    return;
  }}
  if (event.target.id === "ao-reuse-only") {{
    renderInstrumentCommand();
    return;
  }}
  const decisionInput = event.target.closest("input[data-decision-id][data-option-id]");
  if (decisionInput) {{
    applyDecisionAnswer(decisionInput.dataset.decisionId, decisionInput.dataset.optionId);
    return;
  }}
  const input = event.target.closest("input[data-id]");
  if (!input) return;
  applySelectionInput(input);
}});

document.addEventListener("input", event => {{
  const aoInput = event.target.closest("input[data-ao-value]");
  if (aoInput) updateAoTargetInput(aoInput.dataset.aoValue);
}});

syncDependencyClosure();
renderCards();
neutralizeHttpSourceLinks();
renderTray();
revealCurrentHash();
window.addEventListener("hashchange", revealCurrentHash);
</script>
</body>
</html>
"""
