"""Normalization and validation core for the structured OTel report workflow."""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any


OVERLAY_SCHEMA_VERSION = 1
DECISION_SELECTION_SCHEMA_VERSION = 2
CURRENT_SELECTION_SCHEMA_VERSION = 3
SUPPORTED_SELECTION_SCHEMA_VERSIONS = {1, 2, CURRENT_SELECTION_SCHEMA_VERSION}
CURRENT_AUDIT_SCHEMA_VERSION = 2
SUPPORTED_AUDIT_SCHEMA_VERSIONS = {1, CURRENT_AUDIT_SCHEMA_VERSION}
STABLE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
STATUSES = {"Pass", "Partial", "Blocked"}
RESULT_STATUSES = STATUSES | {"Fail", "Not run"}
INSTRUMENTATION_RESULT_STATUSES = STATUSES | {"Fail"}
FINDING_STATUSES = {"proposed", "approved", "in_progress", "done", "rejected", "deferred"}
UNRESOLVED_FINDING_STATUSES = {"proposed", "approved", "in_progress"}
SEVERITIES = {"critical", "high", "medium", "low", "info"}
PRIORITY_ORDER = ("required", "recommended", "deferred")
PRIORITIES = set(PRIORITY_ORDER)
PRIORITY_RANK = {priority: index for index, priority in enumerate(PRIORITY_ORDER)}
EFFORTS = {"small", "medium", "large", "decision"}
INSTRUMENT_MODES = {"default", "fix all", "manual decision", "external follow-up"}
EXECUTABLE_MODES = {"default", "fix all"}
PROOF_LEVELS = {"focused call-site", "full runtime", "either"}
PROOF_LEVEL_ALIASES = {
    "focused": "focused call-site",
    "call-site": "focused call-site",
    "call site": "focused call-site",
    "callsite": "focused call-site",
    "focused call site": "focused call-site",
    "focused call-site": "focused call-site",
    "unit": "focused call-site",
    "unit test": "focused call-site",
    "unit-tested": "focused call-site",
    "runtime": "full runtime",
    "full": "full runtime",
    "full-runtime": "full runtime",
    "full runtime": "full runtime",
    "unit plus runtime": "full runtime",
    "unit and runtime": "full runtime",
    "focused plus runtime": "full runtime",
    "focused and runtime": "full runtime",
    "either": "either",
}
SIGNAL_TYPES = {"span", "metric", "log", "resource", "configuration"}
FINDING_GROUPS = {"splunk-agent-observability"}
AO_TARGET_SCOPES = {"resource-routing"}
AO_TARGET_LEGACY_CONFIGURATION_NAMES = {
    "agent-observability.project",
    "agent-observability.agent-stream",
    "agent-observability.project-resource",
    "agent-observability.agent-stream-resource",
    "agent-observability.runtime-routing",
    "agent-observability.splunk-ao-routing",
}
INCIDENT_READINESS_STATUSES = {"covered", "partial", "missing", "owner-mapped"}
GENAI_READINESS_STATUSES = {"covered", "partial", "missing", "owner-mapped"}
SCAN_BLOCKER_CHECKS = {
    "manifest",
    "entry-point",
    "route-source",
    "runtime-startup",
    "dependency-scan",
    "genai-ownership",
    "source-scan",
}
OWNER_PLACEHOLDER = re.compile(r"^(?:tbd|unknown|owner|someone|team|n/?a)$", re.IGNORECASE)
EXTERNAL_OWNER_CATEGORY = re.compile(
    r"(?:external|provider|platform|vendor|third[- ]party|managed[- ]service)"
    r"(?:\s*/\s*(?:external|provider|platform|vendor|third[- ]party|"
    r"managed[- ]service))?(?:[- ]owned|\s+owner)?",
    re.IGNORECASE,
)
GENERIC_EXTERNAL_OWNER_DETAIL = re.compile(
    r"(?:(?:external|provider|platform|vendor|third[- ]party|managed[- ]service)"
    r"(?:[- ]owned)?(?:\s+(?:owner|team))?|owner|team)",
    re.IGNORECASE,
)
DECISION_CHOICE = re.compile(r"\b(?:which|whether|should|choose|select)\b", re.IGNORECASE)
EXTERNAL_ACTION = re.compile(
    r"\b(?:emit|export|configure|provide|supply|expose|prove|verify)(?:s|d|ed|ing)?\b",
    re.IGNORECASE,
)
CLOSURE_STATUSES = {"working", "not_working", "not_proven", "not_configured", "deferred"}
SCENARIO_STATUSES = {"working", "not_working", "not_proven", "not_configured", "blocked"}
CHANGE_KINDS = {"added", "modified", "removed"}
CONSUMER_COMPATIBILITY_STATUSES = {"compatible", "breaking", "requires_review"}
PROOF_MODES = {"app_test", "unit", "unit+otlp", "full_runtime", "contract_only", "static", "not_run"}
ITEM_DIRECT_PROOF_MODES = {"app_test", "unit", "unit+otlp", "full_runtime"}
VISIBILITY_STATES = {
    "explorer_visible",
    "otlp_accepted",
    "not_explorer_visible",
    "not_proven",
    "not_applicable",
}
EPHEMERAL_ARTIFACT_PREFIXES = (
    "/tmp",
    "/private/tmp",
    "/var/folders",
    "/private/var/folders",
)
FLOW_MARKER = re.compile(r"\[(SOURCE-COVERED|GAP:\s*([^\]]+))\]")
FLOW_BRACKET = re.compile(r"\[[^\]]+\]")
AUDIT_VERIFY_NEXT_STEP = re.compile(
    r"(?:\b(?:run|rerun|re-run|use|invoke|execute|launch|start)\s+"
    r"(?:the\s+)?(?:\$?otel[- ]verify|verification(?:\s+workflow)?)\b|"
    r"\b\$?otel[- ]verify\b)",
    re.IGNORECASE,
)
SEVERITY_BY_PRIORITY = {
    "required": "high",
    "recommended": "medium",
    "deferred": "low",
}
MODE_GUIDANCE = {
    "default": {
        "selection": "Select",
        "guidance": "Safe app-owned work. Select it for instrumentation.",
    },
    "fix all": {
        "selection": "Select",
        "guidance": "Broader safe work. Select it only when the broader scope is wanted.",
    },
    "manual decision": {
        "selection": None,
        "guidance": "Choose one named OpenTelemetry outcome. The decision itself never enters instrumentation scope; compatible executable work becomes selectable.",
    },
    "external follow-up": {
        "selection": None,
        "guidance": "Track this with the named external owner. This item cannot enter the instrumentation selection.",
    },
}


class ReportError(ValueError):
    """Raised for schema or reference errors in report JSON."""


def fail(message: str) -> None:
    raise ReportError(message)


def has_exact_external_owner(value: str) -> bool:
    """Require a category-prefixed owner with a concrete named source."""

    category, separator, detail = value.partition(":")
    detail = detail.strip()
    return bool(
        separator
        and EXTERNAL_OWNER_CATEGORY.fullmatch(category.strip())
        and detail
        and not OWNER_PLACEHOLDER.fullmatch(detail)
        and not GENERIC_EXTERNAL_OWNER_DETAIL.fullmatch(detail)
    )


def as_object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{path} must be an object")
    return value


def as_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        fail(f"{path} must be a list")
    return value


def text(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        fail(f"{path} must be a string")
    if not allow_empty and not value.strip():
        fail(f"{path} must not be empty")
    return value


def optional_text(value: Any, path: str) -> str | None:
    if value is None:
        return None
    return text(value, path)


def stable_id(value: Any, path: str) -> str:
    result = text(value, path)
    if not STABLE_ID.fullmatch(result):
        fail(f"{path} must be a stable ID")
    return result


def string_list(value: Any, path: str) -> list[str]:
    return [text(item, f"{path}[{index}]") for index, item in enumerate(as_list(value, path))]


def durable_artifact_text(value: str, path: str) -> str:
    """Reject non-portable temporary artifact paths in durable report fields."""
    normalized = value.strip().replace("\\", "/")
    if any(
        normalized == prefix or normalized.startswith(prefix + "/")
        for prefix in EPHEMERAL_ARTIFACT_PREFIXES
    ):
        fail(
            f"{path} references an ephemeral absolute path; copy durable proof under "
            ".observe/evidence/<run>/ and store the repository-relative path"
        )
    return value


def durable_artifact_list(value: Any, path: str) -> list[str]:
    return [
        durable_artifact_text(item, f"{path}[{index}]")
        for index, item in enumerate(string_list(value, path))
    ]


def non_empty_string_list(value: Any, path: str) -> list[str]:
    result = string_list(value, path)
    if not result:
        fail(f"{path} must contain at least one item")
    return result


def object_list(value: Any, path: str) -> list[dict[str, Any]]:
    return [
        as_object(item, f"{path}[{index}]")
        for index, item in enumerate(as_list(value, path))
    ]


def normalized_words(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^a-z0-9._/]+", " ", normalized).split())


def validate_audit_review_next_step(value: str, path: str) -> None:
    if AUDIT_VERIFY_NEXT_STEP.search(value):
        fail(
            f"{path} must not present $otel-verify or generic verification as "
            "the audit next step; direct reviewers to select/save audit scope "
            "and run $otel-instrument, or state standalone verification as a "
            "separate explicit request"
        )


def normalize_evidence_row(row: dict[str, Any], path: str) -> dict[str, str]:
    return {
        "check": text(row.get("check"), f"{path}.check"),
        "finding": text(row.get("finding"), f"{path}.finding"),
        "source": text(row.get("source"), f"{path}.source"),
    }


def normalize_scan_blockers(value: Any) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    blocker_ids: set[str] = set()
    for index, row in enumerate(object_list(value, "scan_blockers")):
        path = f"scan_blockers[{index}]"
        blocker_id = stable_id(row.get("id"), f"{path}.id")
        if blocker_id in blocker_ids:
            fail(f"duplicate scan blocker ID: {blocker_id}")
        blocker_ids.add(blocker_id)
        check = text(row.get("check"), f"{path}.check")
        if check not in SCAN_BLOCKER_CHECKS:
            fail(f"{path}.check must be one of {sorted(SCAN_BLOCKER_CHECKS)}")
        blockers.append(
            {
                "id": blocker_id,
                "check": check,
                "blocked_scope": non_empty_string_list(
                    row.get("blocked_scope", []), f"{path}.blocked_scope"
                ),
                "prerequisite": text(row.get("prerequisite"), f"{path}.prerequisite"),
                "evidence": non_empty_string_list(
                    row.get("evidence", []), f"{path}.evidence"
                ),
                "required_action": text(
                    row.get("required_action"), f"{path}.required_action"
                ),
            }
        )
    return blockers


def normalize_routes(value: Any) -> list[dict[str, str]]:
    routes = []
    for index, row in enumerate(object_list(value, "routes")):
        routes.append(
            {
                "method": text(row.get("method"), f"routes[{index}].method"),
                "path": text(row.get("path"), f"routes[{index}].path"),
            }
        )
    return routes


def compact_row_text(value: Any, path: str) -> str:
    """Accept compact table-cell values while preserving scalar validation.

    LLM-authored readiness rows sometimes produce a short list or keyed object
    for cells that are rendered as plain text. Coerce those cells
    deterministically instead of failing finalization, but still reject missing
    or empty values.
    """

    if isinstance(value, str):
        return text(value, path)
    if isinstance(value, bool) or isinstance(value, int) or isinstance(value, float):
        return text(str(value), path)
    if isinstance(value, list):
        parts = [
            compact_row_text(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
        return text("; ".join(part for part in parts if part), path)
    if isinstance(value, dict):
        parts = [
            f"{text(str(key), f'{path}.{key}.key')}: {compact_row_text(item, f'{path}.{key}')}"
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        ]
        return text("; ".join(part for part in parts if part), path)
    return text(value, path)


def normalize_json_field(value: Any, path: str) -> Any:
    if isinstance(value, str):
        return text(value, path)
    if isinstance(value, bool) or isinstance(value, int) or isinstance(value, float):
        return value
    if isinstance(value, list):
        return [
            normalize_json_field(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        return {
            text(str(key), f"{path}.{key}.key"): normalize_json_field(
                item, f"{path}.{key}"
            )
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    fail(f"{path} must be a JSON scalar, list, or object")


def normalize_signal_rows(
    value: Any,
    path: str,
    fields: tuple[str, ...],
    *,
    preserve_extra: bool = False,
) -> list[dict[str, Any]]:
    rows = []
    for index, row in enumerate(object_list(value, path)):
        normalized = {
            field: compact_row_text(row.get(field), f"{path}[{index}].{field}")
            for field in fields
        }
        if preserve_extra:
            for key, item in sorted(row.items(), key=lambda pair: str(pair[0])):
                key_text = text(str(key), f"{path}[{index}].{key}.key")
                if key_text in normalized:
                    continue
                normalized[key_text] = normalize_json_field(
                    item, f"{path}[{index}].{key_text}"
                )
        rows.append(normalized)
    return rows


def normalize_proof_level(value: Any, path: str, scenario_id: str) -> str:
    raw = text(value, path)
    normalized = re.sub(r"\s+", " ", raw.strip().lower().replace("_", " ").replace("-", " "))
    proof_level = PROOF_LEVEL_ALIASES.get(normalized, raw)
    if proof_level not in PROOF_LEVELS:
        fail(f"invalid proof level for {scenario_id}: {raw}")
    return proof_level


def normalize_verification(value: Any) -> dict[str, Any]:
    verification = as_object(value, "verification")
    environments = []
    environment_ids = set()
    for index, row in enumerate(object_list(verification.get("environments", []), "verification.environments")):
        environment_id = stable_id(row.get("id"), f"verification.environments[{index}].id")
        if environment_id in environment_ids:
            fail(f"duplicate verification environment ID: {environment_id}")
        environment_ids.add(environment_id)
        environments.append(
            {
                "id": environment_id,
                "surface": text(row.get("surface"), f"verification.environments[{index}].surface"),
                "config_evidence": text(
                    row.get("config_evidence"),
                    f"verification.environments[{index}].config_evidence",
                ),
                "runner": text(row.get("runner"), f"verification.environments[{index}].runner"),
                "scope": text(row.get("scope"), f"verification.environments[{index}].scope"),
                "prerequisites": text(
                    row.get("prerequisites"),
                    f"verification.environments[{index}].prerequisites",
                ),
            }
        )

    scenarios = []
    scenario_ids = set()
    for index, row in enumerate(object_list(verification.get("scenarios", []), "verification.scenarios")):
        scenario_id = stable_id(row.get("id"), f"verification.scenarios[{index}].id")
        if scenario_id in scenario_ids:
            fail(f"duplicate verification scenario ID: {scenario_id}")
        scenario_ids.add(scenario_id)
        proof_level = normalize_proof_level(
            row.get("proof_level"),
            f"verification.scenarios[{index}].proof_level",
            scenario_id,
        )
        environments_for_scenario = [
            stable_id(item, f"verification.scenarios[{index}].environments[{env_index}]")
            for env_index, item in enumerate(as_list(row.get("environments"), f"verification.scenarios[{index}].environments"))
        ]
        unknown = sorted(set(environments_for_scenario) - environment_ids)
        if unknown:
            fail(f"scenario {scenario_id} references undefined environments: {unknown}")
        scenarios.append(
            {
                "id": scenario_id,
                "trigger": text(row.get("trigger"), f"verification.scenarios[{index}].trigger"),
                "entrypoint": text(row.get("entrypoint"), f"verification.scenarios[{index}].entrypoint"),
                "expected_signals": text(
                    row.get("expected_signals"),
                    f"verification.scenarios[{index}].expected_signals",
                ),
                "proof_level": proof_level,
                "acceptance_criteria": text(
                    row.get("acceptance_criteria"),
                    f"verification.scenarios[{index}].acceptance_criteria",
                ),
                "environments": environments_for_scenario,
            }
        )
    return {"environments": environments, "scenarios": scenarios}


def normalize_finding(
    row: dict[str, Any],
    path: str,
    audit_schema_version: int,
) -> dict[str, Any]:
    priority = text(row.get("priority"), f"{path}.priority")
    if priority not in PRIORITIES:
        fail(f"{path}.priority must be one of {sorted(PRIORITIES)}")
    severity = text(row.get("severity", SEVERITY_BY_PRIORITY[priority]), f"{path}.severity")
    if severity not in SEVERITIES:
        fail(f"{path}.severity must be one of {sorted(SEVERITIES)}")
    status = text(row.get("status", "proposed"), f"{path}.status")
    if status not in FINDING_STATUSES:
        fail(f"{path}.status must be one of {sorted(FINDING_STATUSES)}")
    mode = text(row.get("instrument_mode"), f"{path}.instrument_mode")
    if mode not in INSTRUMENT_MODES:
        fail(f"{path}.instrument_mode must be one of {sorted(INSTRUMENT_MODES)}")
    effort = text(row.get("effort"), f"{path}.effort")
    if effort not in EFFORTS:
        fail(f"{path}.effort must be one of {sorted(EFFORTS)}")
    finding_group = optional_text(row.get("finding_group"), f"{path}.finding_group")
    if finding_group is not None and finding_group not in FINDING_GROUPS:
        fail(f"{path}.finding_group must be one of {sorted(FINDING_GROUPS)}")
    telemetry = []
    for index, item in enumerate(object_list(row.get("expected_telemetry", []), f"{path}.expected_telemetry")):
        item_path = f"{path}.expected_telemetry[{index}]"
        signal_type = text(item.get("type"), f"{item_path}.type")
        if signal_type not in SIGNAL_TYPES:
            fail(f"{item_path}.type must be one of {sorted(SIGNAL_TYPES)}")
        telemetry_item = {
            "type": signal_type,
            "name": text(item.get("name"), f"{item_path}.name"),
            "attributes": string_list(item.get("attributes", []), f"{item_path}.attributes"),
            "product_view": text(item.get("product_view"), f"{item_path}.product_view"),
        }
        telemetry.append(telemetry_item)
    if not telemetry:
        fail(f"{path}.expected_telemetry must contain at least one item")
    ao_target_scope = None
    if "ao_target_scope" in row:
        ao_target_scope = text(row["ao_target_scope"], f"{path}.ao_target_scope")
        if ao_target_scope not in AO_TARGET_SCOPES:
            fail(f"{path}.ao_target_scope must be one of {sorted(AO_TARGET_SCOPES)}")
        if finding_group != "splunk-agent-observability" or not any(
            item["type"] == "configuration" for item in telemetry
        ):
            fail(f"{path}.ao_target_scope requires an Agent Observability configuration finding")
    decision_owner = optional_text(row.get("decision_owner"), f"{path}.decision_owner")
    decision_question = optional_text(
        row.get("decision_question"), f"{path}.decision_question"
    )
    explicit_decision_options = "decision_options" in row
    decision_options: list[dict[str, Any]] = []
    if explicit_decision_options:
        option_rows = object_list(row.get("decision_options"), f"{path}.decision_options")
        if not 2 <= len(option_rows) <= 3:
            fail(f"{path}.decision_options must contain 2 or 3 mutually exclusive options")
        option_ids: set[str] = set()
        for index, option_row in enumerate(option_rows):
            option_path = f"{path}.decision_options[{index}]"
            option_id = stable_id(option_row.get("id"), f"{option_path}.id")
            if option_id in option_ids:
                fail(f"{path}.decision_options must use unique option IDs")
            option_ids.add(option_id)
            unlocks = [
                stable_id(item, f"{option_path}.unlocks[{unlock_index}]")
                for unlock_index, item in enumerate(
                    as_list(option_row.get("unlocks", []), f"{option_path}.unlocks")
                )
            ]
            if len(unlocks) != len(set(unlocks)):
                fail(f"{option_path}.unlocks must not contain duplicates")
            decision_options.append(
                {
                    "id": option_id,
                    "label": text(option_row.get("label"), f"{option_path}.label"),
                    "outcome": text(option_row.get("outcome"), f"{option_path}.outcome"),
                    "unlocks": unlocks,
                }
            )
    external_owner = optional_text(row.get("external_owner"), f"{path}.external_owner")
    external_requirement = optional_text(
        row.get("external_requirement"), f"{path}.external_requirement"
    )
    if explicit_decision_options and mode != "manual decision":
        fail(f"{path}.decision_options is valid only for manual decision findings")
    if audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION:
        if mode == "manual decision":
            if not decision_owner or not decision_question:
                fail(
                    f"{path}.manual decision requires decision_owner and an exact "
                    "telemetry-specific decision_question"
                )
            if OWNER_PLACEHOLDER.fullmatch(decision_owner.strip()):
                fail(f"{path}.decision_owner must name a concrete responsible owner")
            if not decision_question.rstrip().endswith("?") or not DECISION_CHOICE.search(
                decision_question
            ):
                fail(
                    f"{path}.decision_question must be an exact telemetry choice "
                    "using which/whether/should/choose/select and a question mark"
                )
        elif decision_owner is not None or decision_question is not None:
            fail(
                f"{path}.decision_owner and decision_question are valid only for "
                "manual decision findings"
            )
        if mode == "external follow-up":
            if not external_owner or not external_requirement:
                fail(
                    f"{path}.external follow-up requires a known external_owner and "
                    "exact external_requirement for OTel telemetry or proof"
                )
            if OWNER_PLACEHOLDER.fullmatch(external_owner.strip()):
                fail(f"{path}.external_owner must name a concrete external owner")
            if not EXTERNAL_ACTION.search(external_requirement):
                fail(
                    f"{path}.external_requirement must say what the external owner "
                    "will emit, export, configure, provide, supply, expose, prove, or verify"
                )
        elif external_owner is not None or external_requirement is not None:
            fail(
                f"{path}.external_owner and external_requirement are valid only for "
                "external follow-up findings"
            )
    report = {
        "id": stable_id(row.get("id"), f"{path}.id"),
        "title": text(row.get("title"), f"{path}.title"),
        "severity": severity,
        "priority": priority,
        "effort": effort,
        "status": status,
        "area": text(row.get("area"), f"{path}.area"),
        "gap": text(row.get("gap"), f"{path}.gap"),
        "impact": text(row.get("impact"), f"{path}.impact"),
        "product_outcome": optional_text(
            row.get("product_outcome"), f"{path}.product_outcome"
        )
        or telemetry[0]["product_view"],
        "required_fix": text(row.get("required_fix"), f"{path}.required_fix"),
        "instrument_mode": mode,
        "verification_scenarios": [
            stable_id(item, f"{path}.verification_scenarios[{index}]")
            for index, item in enumerate(as_list(row.get("verification_scenarios", []), f"{path}.verification_scenarios"))
        ],
        "dependencies": [
            stable_id(item, f"{path}.dependencies[{index}]")
            for index, item in enumerate(as_list(row.get("dependencies", []), f"{path}.dependencies"))
        ],
        "evidence": non_empty_string_list(row.get("evidence", []), f"{path}.evidence"),
        "acceptance_criteria": non_empty_string_list(
            row.get("acceptance_criteria", []), f"{path}.acceptance_criteria"
        ),
        "constraints": string_list(row.get("constraints", []), f"{path}.constraints"),
        "expected_telemetry": telemetry,
        "follow_up_actions": non_empty_string_list(
            row.get("follow_up_actions", []), f"{path}.follow_up_actions"
        ),
        "resolution": optional_text(row.get("resolution"), f"{path}.resolution"),
        "resolved_commit": optional_text(row.get("resolved_commit"), f"{path}.resolved_commit"),
    }
    if decision_owner is not None:
        report["decision_owner"] = decision_owner
    if decision_question is not None:
        report["decision_question"] = decision_question
    if explicit_decision_options:
        report["decision_options"] = decision_options
    if external_owner is not None:
        report["external_owner"] = external_owner
    if external_requirement is not None:
        report["external_requirement"] = external_requirement
        if (
            audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION
            and normalized_words(external_requirement)
            != normalized_words(report["required_fix"])
        ):
            fail(
                f"{path}.required_fix must contain the exact external_requirement "
                "and no hidden service implementation handoff"
            )
    if finding_group is not None:
        report["finding_group"] = finding_group
    if ao_target_scope is not None:
        report["ao_target_scope"] = ao_target_scope
    if audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION:
        for index, value in enumerate(report["follow_up_actions"]):
            validate_audit_review_next_step(
                value, f"{path}.follow_up_actions[{index}]"
            )
    return report


def normalize_audit_report(data: dict[str, Any]) -> dict[str, Any]:
    audit_schema_version = data.get("schema_version")
    if audit_schema_version not in SUPPORTED_AUDIT_SCHEMA_VERSIONS:
        fail(
            "audit schema_version must be one of "
            f"{sorted(SUPPORTED_AUDIT_SCHEMA_VERSIONS)}"
        )
    if data.get("kind") != "otel-audit":
        fail("kind must be otel-audit")

    meta = as_object(data.get("meta"), "meta")
    status = text(meta.get("status"), "meta.status")
    if status not in STATUSES:
        fail(f"meta.status must be one of {sorted(STATUSES)}")
    scan_blockers = (
        normalize_scan_blockers(data.get("scan_blockers", []))
        if audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION
        else []
    )
    if (
        audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION
        and status == "Blocked"
        and not scan_blockers
    ):
        fail("meta.status Blocked requires at least one structured scan_blocker")
    if (
        audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION
        and status != "Blocked"
        and scan_blockers
    ):
        fail("scan_blockers are valid only when meta.status is Blocked")
    genai_detected = meta.get("genai_ownership_detected")
    if not isinstance(genai_detected, bool):
        fail("meta.genai_ownership_detected must be a boolean")

    current = as_object(data.get("current_instrumentation", {}), "current_instrumentation")
    verification = normalize_verification(data.get("verification", {}))

    findings = []
    finding_ids = set()
    for index, row in enumerate(object_list(data.get("findings", []), "findings")):
        finding = normalize_finding(
            row,
            f"findings[{index}]",
            audit_schema_version,
        )
        if finding["id"] in finding_ids:
            fail(f"duplicate finding ID: {finding['id']}")
        finding_ids.add(finding["id"])
        findings.append(finding)

    if status == "Pass" and findings:
        fail("meta.status Pass requires zero source-visible findings")
    if status == "Partial" and not findings:
        fail("meta.status Partial requires at least one source-visible finding")

    scenarios_by_id = {row["id"]: row for row in verification["scenarios"]}
    scenario_ids = set(scenarios_by_id)
    for finding in findings:
        if len(finding["verification_scenarios"]) != len(
            set(finding["verification_scenarios"])
        ):
            fail(
                f"finding {finding['id']} verification_scenarios must not "
                "contain duplicates"
            )
        unknown_scenarios = sorted(set(finding["verification_scenarios"]) - scenario_ids)
        if unknown_scenarios:
            fail(f"finding {finding['id']} references undefined scenarios: {unknown_scenarios}")
        unknown_dependencies = sorted(set(finding["dependencies"]) - finding_ids)
        if unknown_dependencies:
            fail(f"finding {finding['id']} references undefined dependencies: {unknown_dependencies}")

    findings_by_id = {finding["id"]: finding for finding in findings}
    for decision in findings:
        if "decision_options" not in decision:
            continue
        decision_id = decision["id"]
        direct_dependents = [
            finding
            for finding in findings
            if decision_id in finding["dependencies"]
            and finding["instrument_mode"] in EXECUTABLE_MODES
        ]
        unlocked_ids: set[str] = set()
        unlocking_option_by_id: dict[str, str] = {}
        for option_index, option in enumerate(decision["decision_options"]):
            for target_id in option["unlocks"]:
                target = findings_by_id.get(target_id)
                option_path = (
                    f"finding {decision_id} decision_options[{option_index}].unlocks"
                )
                if target is None:
                    fail(f"{option_path} references undefined finding {target_id}")
                if target["instrument_mode"] not in EXECUTABLE_MODES:
                    fail(f"{option_path} target {target_id} must be executable")
                if decision_id not in target["dependencies"]:
                    fail(
                        f"{option_path} target {target_id} must directly depend on "
                        f"decision {decision_id}"
                    )
                previous_option = unlocking_option_by_id.get(target_id)
                if previous_option is not None:
                    fail(
                        f"finding {decision_id} decision_options unlock sets must be "
                        f"pairwise disjoint; executable finding {target_id} is unlocked "
                        f"by both {previous_option} and {option['id']}"
                    )
                unlocking_option_by_id[target_id] = option["id"]
                unlocked_ids.add(target_id)
        missing_unlocks = [
            finding["id"]
            for finding in direct_dependents
            if finding["id"] not in unlocked_ids
        ]
        if missing_unlocks:
            fail(
                f"finding {decision_id} decision_options must unlock every direct "
                f"executable dependent; missing {missing_unlocks}"
            )

    genai_readiness = normalize_signal_rows(
        data.get("genai_readiness", []),
        "genai_readiness",
        ("surface", "status", "evidence", "required_signals", "owner", "acceptance_criteria", "impact"),
    )
    if genai_detected and not genai_readiness:
        fail("meta.genai_ownership_detected is true but genai_readiness is empty")
    if not genai_detected and genai_readiness:
        fail("meta.genai_ownership_detected is false but genai_readiness is not empty")
    genai_surfaces: set[str] = set()
    if audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION:
        for index, row in enumerate(genai_readiness):
            if row["status"] not in GENAI_READINESS_STATUSES:
                fail(
                    f"genai_readiness[{index}].status must be one of "
                    f"{sorted(GENAI_READINESS_STATUSES)}"
                )
            if row["surface"] in genai_surfaces:
                fail(f"duplicate GenAI readiness surface: {row['surface']}")
            genai_surfaces.add(row["surface"])
            if row["status"] == "owner-mapped" and not has_exact_external_owner(
                row["owner"]
            ):
                fail(
                    f"genai_readiness[{index}].owner must name an exact external, "
                    "provider, or platform owner for owner-mapped status"
                )
        if status == "Pass" and any(
            row["status"] not in {"covered", "owner-mapped"}
            for row in genai_readiness
        ):
            fail(
                "meta.status Pass requires every GenAI readiness surface to be "
                "covered or owner-mapped"
            )

    incident_readiness = normalize_signal_rows(
        current.get("incident_readiness", []),
        "current_instrumentation.incident_readiness",
        ("area", "status", "evidence", "required_signals", "impact"),
    )
    readiness_areas: set[str] = set()
    if audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION:
        for index, row in enumerate(incident_readiness):
            if row["status"] not in INCIDENT_READINESS_STATUSES:
                fail(
                    "current_instrumentation.incident_readiness"
                    f"[{index}].status must be one of {sorted(INCIDENT_READINESS_STATUSES)}"
                )
            if row["area"] in readiness_areas:
                fail(f"duplicate incident readiness area: {row['area']}")
            readiness_areas.add(row["area"])

    report = {
        "schema_version": audit_schema_version,
        "kind": "otel-audit",
        "meta": {
            "audit_id": stable_id(meta.get("audit_id"), "meta.audit_id"),
            "service_name": text(meta.get("service_name"), "meta.service_name"),
            "commit": text(meta.get("commit"), "meta.commit"),
            "language": text(meta.get("language"), "meta.language"),
            "framework": text(meta.get("framework"), "meta.framework"),
            "date": text(meta.get("date"), "meta.date"),
            "status": status,
            "genai_ownership_detected": genai_detected,
        },
        "summary": non_empty_string_list(data.get("summary", []), "summary"),
        "flow": text(
            data.get(
                "flow",
                "audit -> select -> instrument -> verify -> configure/dashboard -> publish",
            ),
            "flow",
        ),
        "evidence": [
            normalize_evidence_row(row, f"evidence[{index}]")
            for index, row in enumerate(object_list(data.get("evidence", []), "evidence"))
        ],
        "routes": normalize_routes(data.get("routes", [])),
        "signal_flow": {
            "component_flow_map": text(
                as_object(data.get("signal_flow", {}), "signal_flow").get("component_flow_map"),
                "signal_flow.component_flow_map",
            )
        },
        "current_instrumentation": {
            "spans": normalize_signal_rows(
                current.get("spans", []),
                "current_instrumentation.spans",
                ("name", "source", "type"),
                preserve_extra=True,
            ),
            "metrics": normalize_signal_rows(
                current.get("metrics", []),
                "current_instrumentation.metrics",
                ("name", "source", "type"),
                preserve_extra=True,
            ),
            "logs": normalize_signal_rows(
                current.get("logs", []),
                "current_instrumentation.logs",
                ("integration", "source", "detail"),
                preserve_extra=True,
            ),
            "incident_readiness": incident_readiness,
        },
        "genai_readiness": genai_readiness,
        "findings": findings,
        "verification": verification,
        "anti_patterns": string_list(data.get("anti_patterns", []), "anti_patterns"),
        "recommendation": string_list(data.get("recommendation", []), "recommendation"),
    }
    if audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION:
        report["scan_blockers"] = scan_blockers
        for index, value in enumerate(report["recommendation"]):
            validate_audit_review_next_step(
                value,
                f"recommendation[{index}]",
            )
    evidence_checks = {row["check"] for row in report["evidence"]}
    required_evidence_checks = {
        "Manifest",
        "Entry point",
        "Route source",
        "Runtime/startup",
        "GenAI ownership",
    }
    missing_evidence_checks = sorted(required_evidence_checks - evidence_checks)
    if missing_evidence_checks:
        fail(f"evidence is missing required checks: {missing_evidence_checks}")
    ownership_rows = [row for row in report["evidence"] if row["check"] == "GenAI ownership"]
    expected_ownership = "Yes" if genai_detected else "No"
    if len(ownership_rows) != 1 or ownership_rows[0]["finding"] != expected_ownership:
        fail("evidence must contain one GenAI ownership row matching meta")

    dependencies_by_id = {finding["id"]: finding["dependencies"] for finding in findings}
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(finding_id: str) -> None:
        if finding_id in visited:
            return
        if finding_id in visiting:
            fail(f"finding dependency cycle includes {finding_id}")
        visiting.add(finding_id)
        for dependency in dependencies_by_id[finding_id]:
            visit(dependency)
        visiting.remove(finding_id)
        visited.add(finding_id)

    for finding_id in dependencies_by_id:
        visit(finding_id)

    if audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION:
        transitively_required: set[str] = set()

        def mark_required_dependencies(finding_id: str) -> None:
            for dependency_id in dependencies_by_id[finding_id]:
                if dependency_id in transitively_required:
                    continue
                transitively_required.add(dependency_id)
                mark_required_dependencies(dependency_id)

        for finding in findings:
            if finding["instrument_mode"] in EXECUTABLE_MODES:
                mark_required_dependencies(finding["id"])

        orphan_non_executable_ids = [
            finding["id"]
            for finding in findings
            if finding["instrument_mode"] not in EXECUTABLE_MODES
            and finding["id"] not in transitively_required
        ]
        if orphan_non_executable_ids:
            fail(
                "schema v2 non-executable findings must be transitively required "
                "by an executable finding; orphan IDs: "
                f"{orphan_non_executable_ids}"
            )

    areas = [finding["area"] for finding in findings]
    duplicate_areas = sorted({area for area in areas if areas.count(area) > 1})
    if duplicate_areas:
        fail(f"finding areas must be unique: {duplicate_areas}")
    incomplete_readiness_areas = {
        row["area"]
        for row in report["current_instrumentation"]["incident_readiness"]
        if row["status"] in {"partial", "missing", "owner-mapped"}
    }
    unresolved_findings_by_area = {
        finding["area"]: finding
        for finding in findings
        if finding["status"] in UNRESOLVED_FINDING_STATUSES
    }
    unmapped_readiness = sorted(
        incomplete_readiness_areas - set(unresolved_findings_by_area)
    )
    if audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION and unmapped_readiness:
        fail(
            "partial, missing, or owner-mapped incident readiness areas require identical "
            "unresolved finding areas: "
            f"{unmapped_readiness}"
        )
    readiness_without_scenarios = sorted(
        area
        for area in incomplete_readiness_areas
        if area in unresolved_findings_by_area
        and not unresolved_findings_by_area[area]["verification_scenarios"]
    )
    if audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION and readiness_without_scenarios:
        fail(
            "partial, missing, or owner-mapped incident readiness findings require verification "
            f"scenarios: {readiness_without_scenarios}"
        )
    incomplete_genai_surfaces = {
        row["surface"]
        for row in report["genai_readiness"]
        if row["status"] in {"partial", "missing"}
    }
    unmapped_genai_readiness = sorted(
        incomplete_genai_surfaces - set(unresolved_findings_by_area)
    )
    if audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION and unmapped_genai_readiness:
        fail(
            "partial or missing GenAI readiness surfaces require identical "
            "unresolved finding areas: "
            f"{unmapped_genai_readiness}"
        )
    genai_without_scenarios = sorted(
        surface
        for surface in incomplete_genai_surfaces
        if surface in unresolved_findings_by_area
        and not unresolved_findings_by_area[surface]["verification_scenarios"]
    )
    if audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION and genai_without_scenarios:
        fail(
            "partial or missing GenAI readiness findings require verification "
            f"scenarios: {genai_without_scenarios}"
        )
    complete_genai_with_unresolved_findings = sorted(
        {
            row["surface"]
            for row in report["genai_readiness"]
            if row["status"] in {"covered", "owner-mapped"}
        }
        & set(unresolved_findings_by_area)
    )
    if (
        audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION
        and complete_genai_with_unresolved_findings
    ):
        fail(
            "covered or owner-mapped GenAI readiness surfaces must not have "
            "unresolved findings: "
            f"{complete_genai_with_unresolved_findings}"
        )
    complete_with_unresolved_findings = sorted(
        {
            row["area"]
            for row in report["current_instrumentation"]["incident_readiness"]
            if row["status"] == "covered"
        }
        & set(unresolved_findings_by_area)
    )
    if (
        audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION
        and complete_with_unresolved_findings
    ):
        fail(
            "covered incident readiness areas must not have "
            "unresolved findings: "
            f"{complete_with_unresolved_findings}"
        )
    raw_flow = report["signal_flow"]["component_flow_map"]
    invalid_markers = sorted(
        marker for marker in FLOW_BRACKET.findall(raw_flow) if not FLOW_MARKER.fullmatch(marker)
    )
    if invalid_markers:
        fail(f"signal_flow contains unsupported markers: {invalid_markers}")
    flow_gap_areas = {
        match.group(2).strip()
        for match in FLOW_MARKER.finditer(raw_flow)
        if match.group(2)
    }
    unknown_flow_gaps = sorted(flow_gap_areas - set(areas))
    if unknown_flow_gaps:
        fail(f"signal_flow gap markers reference undefined finding areas: {unknown_flow_gaps}")
    unmapped_findings = sorted(set(areas) - flow_gap_areas)
    if unmapped_findings:
        fail(f"findings are not associated with a component-flow gap marker: {unmapped_findings}")
    return report


def audit_digest(report: dict[str, Any]) -> str:
    payload = json.dumps(
        report,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def instrumentation_digest(instrumentation: dict[str, Any]) -> str:
    """Bind verification to the exact normalized instrumentation overlay."""
    payload = json.dumps(
        instrumentation,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def selection_digest(selection: dict[str, Any]) -> str:
    """Bind instrumentation to the exact normalized reviewer selection."""
    payload = json.dumps(
        selection,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def script_json(value: Any) -> str:
    """Serialize JSON for inline script data without raw HTML tag starts."""
    return json.dumps(value, separators=(",", ":")).replace("<", "\\u003c")


def decision_answer_map(
    decision_answers: list[dict[str, str]] | dict[str, str] | None,
) -> dict[str, str]:
    if decision_answers is None:
        return {}
    if isinstance(decision_answers, dict):
        return dict(decision_answers)
    return {
        answer["finding_id"]: answer["option_id"]
        for answer in decision_answers
    }


def selected_decision_option(
    finding: dict[str, Any], option_id: str | None
) -> dict[str, Any] | None:
    if option_id is None:
        return None
    return next(
        (
            option
            for option in finding.get("decision_options", [])
            if option["id"] == option_id
        ),
        None,
    )


def selection_blockers(
    report: dict[str, Any],
    finding_id: str,
    decision_answers: list[dict[str, str]] | dict[str, str] | None = None,
) -> list[str]:
    """Return unresolved non-executable prerequisites in canonical audit order."""
    by_id = {finding["id"]: finding for finding in report["findings"]}
    if finding_id not in by_id:
        fail(f"selection references undefined finding: {finding_id}")
    answers = decision_answer_map(decision_answers)
    blocked: set[str] = set()
    visiting: set[str] = {finding_id}

    def visit(dependency_id: str, dependent_id: str) -> None:
        if dependency_id in visiting:
            fail(f"finding dependency cycle includes {dependency_id}")
        dependency = by_id[dependency_id]
        mode = dependency["instrument_mode"]
        if mode in EXECUTABLE_MODES and dependency["status"] == "done":
            return
        if (
            mode in EXECUTABLE_MODES
            and dependency["status"] in {"rejected", "deferred"}
        ):
            blocked.add(dependency_id)
            return
        if mode == "manual decision":
            option = selected_decision_option(
                dependency, answers.get(dependency_id)
            )
            if option is None or dependent_id not in option["unlocks"]:
                blocked.add(dependency_id)
                return
            visiting.add(dependency_id)
            for nested_id in dependency["dependencies"]:
                visit(nested_id, dependency_id)
            visiting.remove(dependency_id)
            return
        if mode not in EXECUTABLE_MODES:
            blocked.add(dependency_id)
            return
        visiting.add(dependency_id)
        for nested_id in dependency["dependencies"]:
            visit(nested_id, dependency_id)
        visiting.remove(dependency_id)

    for dependency_id in by_id[finding_id]["dependencies"]:
        visit(dependency_id, finding_id)
    return [
        finding["id"]
        for finding in report["findings"]
        if finding["id"] in blocked
    ]


def finding_selection_eligibility(
    report: dict[str, Any],
    finding_id: str,
    decision_answers: list[dict[str, str]] | dict[str, str] | None = None,
) -> dict[str, Any]:
    finding = next(
        (item for item in report["findings"] if item["id"] == finding_id),
        None,
    )
    if finding is None:
        fail(f"selection references undefined finding: {finding_id}")
    mode = finding["instrument_mode"]
    answers = decision_answer_map(decision_answers)
    blockers = selection_blockers(report, finding_id, answers)
    if mode == "manual decision":
        answer = selected_decision_option(finding, answers.get(finding_id))
        return {
            "selectable": False,
            "blockers": [],
            "reason": (
                "Decision recorded"
                if answer is not None
                else "Choose an answer"
                if finding.get("decision_options")
                else "Resolve decision first"
            ),
        }
    if mode == "external follow-up":
        return {
            "selectable": False,
            "blockers": [],
            "reason": "Not selectable for instrumentation",
        }
    if finding["status"] in {"done", "rejected", "deferred"}:
        return {
            "selectable": False,
            "blockers": [],
            "reason": f"Finding is {finding['status']}",
        }
    if blockers:
        return {
            "selectable": False,
            "blockers": blockers,
            "reason": f"Blocked by {', '.join(blockers)}",
        }
    return {"selectable": True, "blockers": [], "reason": ""}


def report_selection_eligibility(
    report: dict[str, Any],
    decision_answers: list[dict[str, str]] | dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    return {
        finding["id"]: finding_selection_eligibility(
            report, finding["id"], decision_answers
        )
        for finding in report["findings"]
    }


def dependency_closure(
    report: dict[str, Any],
    requested_ids: list[str],
    decision_answers: list[dict[str, str]] | dict[str, str] | None = None,
) -> list[str]:
    by_id = {finding["id"]: finding for finding in report["findings"]}
    unknown = sorted(set(requested_ids) - set(by_id))
    if unknown:
        fail(f"selection references undefined findings: {unknown}")
    selected: set[str] = set()
    visiting: set[str] = set()

    def include_dependency(finding_id: str) -> None:
        finding = by_id[finding_id]
        if finding["instrument_mode"] in EXECUTABLE_MODES:
            if finding["status"] == "done":
                return
            include(finding_id)
            return
        if finding["instrument_mode"] != "manual decision":
            return
        if finding_id in visiting:
            fail(f"finding dependency cycle includes {finding_id}")
        visiting.add(finding_id)
        for dependency in finding["dependencies"]:
            include_dependency(dependency)
        visiting.remove(finding_id)

    def include(finding_id: str) -> None:
        if finding_id in selected:
            return
        if finding_id in visiting:
            fail(f"finding dependency cycle includes {finding_id}")
        finding = by_id[finding_id]
        eligibility = finding_selection_eligibility(
            report, finding_id, decision_answers
        )
        if not eligibility["selectable"]:
            fail(
                f"finding {finding_id} cannot be selected for instrumentation: "
                f"{eligibility['reason']}"
            )
        visiting.add(finding_id)
        for dependency in finding["dependencies"]:
            include_dependency(dependency)
        visiting.remove(finding_id)
        selected.add(finding_id)

    for finding_id in requested_ids:
        include(finding_id)
    return [finding["id"] for finding in report["findings"] if finding["id"] in selected]


def decision_unlocks_executable_work(
    report: dict[str, Any],
    finding: dict[str, Any],
) -> bool:
    by_id = {item["id"]: item for item in report["findings"]}
    for option in finding.get("decision_options", []):
        for unlocked_id in option.get("unlocks", []):
            unlocked = by_id.get(unlocked_id)
            if (
                unlocked
                and unlocked["instrument_mode"] in EXECUTABLE_MODES
                and unlocked["status"] not in {"done", "rejected", "deferred"}
            ):
                return True
    return False


def unresolved_select_all_decisions(
    report: dict[str, Any],
    decision_answers: list[dict[str, str]] | dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    answers = decision_answer_map(decision_answers)
    return [
        finding
        for finding in report["findings"]
        if finding["instrument_mode"] == "manual decision"
        and selected_decision_option(finding, answers.get(finding["id"])) is None
        and decision_unlocks_executable_work(report, finding)
    ]


def select_all_decision_prompt(
    decisions: list[dict[str, Any]],
) -> str:
    lines = [
        "select --all requires manual decision answers before selecting all "
        "instrumentation. Choose one option for each decision and rerun with "
        "repeatable --decision FINDING_ID=OPTION_ID:",
    ]
    for decision in decisions:
        lines.append("")
        lines.append(f"{decision['id']}: {decision.get('decision_question', 'Choose one telemetry option')}")
        for option in decision.get("decision_options", []):
            unlocks = ", ".join(option.get("unlocks", [])) or "no executable work"
            lines.append(
                f"  --decision {decision['id']}={option['id']}  "
                f"{option['label']} — {option['outcome']} "
                f"(unlocks: {unlocks})"
            )
    return "\n".join(lines)


def select_all_requested_ids(
    report: dict[str, Any],
    decision_answers: list[dict[str, str]] | dict[str, str] | None = None,
) -> list[str]:
    pending_decisions = unresolved_select_all_decisions(report, decision_answers)
    if pending_decisions:
        fail(select_all_decision_prompt(pending_decisions))
    eligibility = report_selection_eligibility(report, decision_answers)
    return [
        finding["id"]
        for finding in report["findings"]
        if finding["instrument_mode"] in EXECUTABLE_MODES
        and eligibility[finding["id"]]["selectable"]
    ]


def select_all_selection(
    report: dict[str, Any],
    decision_answers: list[dict[str, str]] | dict[str, str] | None = None,
    approved_by: str | None = None,
    approved_at: str | None = None,
    ao_target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_answers = normalize_decision_answers(
        decision_answers or [],
        report,
        "selection.decision_answers",
    )
    requested_ids = select_all_requested_ids(report, normalized_answers)
    if not requested_ids:
        fail(
            "select --all found no selectable executable findings. "
            "Answer-only selections authorize no instrumentation code edits."
        )
    return normalize_selection(
        {
            "schema_version": (
                CURRENT_SELECTION_SCHEMA_VERSION
                if ao_target is not None
                else DECISION_SELECTION_SCHEMA_VERSION
                if normalized_answers
                else OVERLAY_SCHEMA_VERSION
            ),
            "kind": "otel-selection",
            "audit_id": report["meta"]["audit_id"],
            "audit_sha256": audit_digest(report),
            "requested_ids": requested_ids,
            "decision_answers": normalized_answers,
            "approved_by": approved_by,
            "approved_at": approved_at,
            **({"ao_target": ao_target} if ao_target is not None else {}),
        },
        report,
    )


def normalize_decision_answers(
    value: Any,
    report: dict[str, Any],
    path: str,
) -> list[dict[str, str]]:
    by_id = {finding["id"]: finding for finding in report["findings"]}
    answers_by_id: dict[str, str] = {}
    for index, row in enumerate(object_list(value, path)):
        answer_path = f"{path}[{index}]"
        finding_id = stable_id(row.get("finding_id"), f"{answer_path}.finding_id")
        option_id = stable_id(row.get("option_id"), f"{answer_path}.option_id")
        if finding_id in answers_by_id:
            fail(f"{path} must not contain duplicate finding IDs")
        finding = by_id.get(finding_id)
        if finding is None:
            fail(f"{answer_path}.finding_id references undefined finding {finding_id}")
        if finding["instrument_mode"] != "manual decision":
            fail(f"{answer_path}.finding_id {finding_id} is not a manual decision")
        options = finding.get("decision_options", [])
        if not options:
            fail(
                f"{answer_path}.finding_id {finding_id} has no selectable "
                "decision_options"
            )
        if selected_decision_option(finding, option_id) is None:
            fail(
                f"{answer_path}.option_id {option_id} is not defined for "
                f"decision {finding_id}"
            )
        answers_by_id[finding_id] = option_id
    return [
        {"finding_id": finding["id"], "option_id": answers_by_id[finding["id"]]}
        for finding in report["findings"]
        if finding["id"] in answers_by_id
    ]


def is_ao_target_configuration(finding: dict[str, Any]) -> bool:
    if finding.get("finding_group") != "splunk-agent-observability":
        return False
    configurations = [
        item for item in finding.get("expected_telemetry", [])
        if item["type"] == "configuration"
    ]
    return bool(configurations) and (
        finding.get("ao_target_scope") == "resource-routing"
        or any(item["name"] in AO_TARGET_LEGACY_CONFIGURATION_NAMES for item in configurations)
    )


def ao_target_eligible_finding_ids(report: dict[str, Any]) -> list[str]:
    return [finding["id"] for finding in report["findings"] if is_ao_target_configuration(finding)]


def has_selected_ao_configuration(report: dict[str, Any], approved_ids: list[str]) -> bool:
    return any(finding_id in approved_ids for finding_id in ao_target_eligible_finding_ids(report))


def normalize_ao_target(value: Any, path: str) -> dict[str, Any]:
    target = as_object(value, path)
    selectors = ("project_name", "project_id", "agent_stream_name", "agent_stream_id")
    unknown = set(target) - {*selectors, "create_if_missing"}
    if unknown:
        fail(f"{path} contains unsupported fields: {sorted(unknown)}")
    create_if_missing = target.get("create_if_missing", True)
    if not isinstance(create_if_missing, bool):
        fail(f"{path}.create_if_missing must be a boolean")
    if not any(key in target for key in selectors) and create_if_missing is False:
        return {"create_if_missing": False}
    normalized: dict[str, Any] = {}
    for resource in ("project", "agent_stream"):
        supplied = [key for key in (f"{resource}_name", f"{resource}_id") if key in target]
        if len(supplied) != 1:
            fail(f"{path} requires exactly one {resource}_name or {resource}_id selector")
        key = supplied[0]
        raw_value = text(target[key], f"{path}.{key}")
        value = raw_value.strip()
        if len(value) > 512 or any(unicodedata.category(char).startswith("C") for char in raw_value):
            fail(f"{path}.{key} must be at most 512 characters without control characters")
        normalized[key] = value
    normalized["create_if_missing"] = create_if_missing
    return normalized


def normalize_selection(data: dict[str, Any], report: dict[str, Any], path: str = "selection") -> dict[str, Any]:
    schema_version = data.get("schema_version")
    if schema_version not in SUPPORTED_SELECTION_SCHEMA_VERSIONS:
        fail(
            f"{path}.schema_version must be one of "
            f"{sorted(SUPPORTED_SELECTION_SCHEMA_VERSIONS)}"
        )
    if data.get("kind") != "otel-selection":
        fail(f"{path}.kind must be otel-selection")
    audit_id = stable_id(data.get("audit_id"), f"{path}.audit_id")
    if audit_id != report["meta"]["audit_id"]:
        fail(f"{path}.audit_id does not match audit")
    digest = text(data.get("audit_sha256"), f"{path}.audit_sha256")
    expected_digest = audit_digest(report)
    if digest != expected_digest:
        fail(f"{path}.audit_sha256 does not match audit")
    if schema_version >= DECISION_SELECTION_SCHEMA_VERSION and "requested_ids" not in data:
        fail(f"{path}.requested_ids is required for schema_version {schema_version}")
    requested_source = (
        data.get("requested_ids")
        if "requested_ids" in data
        else data.get("approved_ids", [])
    )
    requested_ids = [
        stable_id(item, f"{path}.requested_ids[{index}]")
        for index, item in enumerate(as_list(requested_source, f"{path}.requested_ids"))
    ]
    if len(requested_ids) != len(set(requested_ids)):
        fail(f"{path}.requested_ids must not contain duplicates")
    decision_answers = normalize_decision_answers(
        data.get("decision_answers", []),
        report,
        f"{path}.decision_answers",
    )
    if schema_version == 1 and decision_answers:
        fail(
            f"{path}.schema_version must be at least {DECISION_SELECTION_SCHEMA_VERSION} "
            "when decision_answers are present"
        )
    if not requested_ids and not decision_answers:
        fail(
            f"{path} must contain at least one requested finding ID or "
            "decision answer"
        )
    approved_ids = dependency_closure(report, requested_ids, decision_answers)
    supplied_approved = [
        stable_id(item, f"{path}.approved_ids[{index}]")
        for index, item in enumerate(as_list(data.get("approved_ids", approved_ids), f"{path}.approved_ids"))
    ]
    if supplied_approved != approved_ids:
        fail(f"{path}.approved_ids must equal the dependency-closed audit order {approved_ids}")
    normalized = {
        "schema_version": schema_version,
        "kind": "otel-selection",
        "audit_id": audit_id,
        "audit_sha256": expected_digest,
        "requested_ids": [item for item in requested_ids if item in approved_ids],
        "approved_ids": approved_ids,
        "approved_by": optional_text(data.get("approved_by"), f"{path}.approved_by"),
        "approved_at": optional_text(data.get("approved_at"), f"{path}.approved_at"),
    }
    if schema_version >= DECISION_SELECTION_SCHEMA_VERSION:
        normalized["decision_answers"] = decision_answers
    if "ao_target" in data:
        if schema_version < CURRENT_SELECTION_SCHEMA_VERSION:
            fail(f"{path}.schema_version must be {CURRENT_SELECTION_SCHEMA_VERSION} when ao_target is present")
        if not has_selected_ao_configuration(report, approved_ids):
            fail(f"{path}.ao_target requires a selected Agent Observability resource or routing finding")
        normalized["ao_target"] = normalize_ao_target(data["ao_target"], f"{path}.ao_target")
    return normalized


def normalize_telemetry_change(
    row: dict[str, Any],
    path: str,
    finding_id: str,
    expected_scenarios: list[str],
) -> dict[str, Any]:
    item_id = stable_id(row.get("id"), f"{path}.id")
    if not item_id.startswith(f"{finding_id}."):
        fail(f"{path}.id must start with {finding_id}.")
    change_kind = text(row.get("change_kind"), f"{path}.change_kind")
    if change_kind not in CHANGE_KINDS:
        fail(f"{path}.change_kind must be one of {sorted(CHANGE_KINDS)}")
    signal_type = text(row.get("type"), f"{path}.type")
    if signal_type not in SIGNAL_TYPES:
        fail(f"{path}.type must be one of {sorted(SIGNAL_TYPES)}")
    signal_name = text(row.get("name"), f"{path}.name")
    added_attributes = string_list(row.get("added_attributes", []), f"{path}.added_attributes")
    follow_up_actions = non_empty_string_list(row.get("follow_up_actions", []), f"{path}.follow_up_actions")
    scenarios = [
        stable_id(item, f"{path}.verification_scenarios[{index}]")
        for index, item in enumerate(
            as_list(row.get("verification_scenarios", []), f"{path}.verification_scenarios")
        )
    ]
    unknown_scenarios = sorted(set(scenarios) - set(expected_scenarios))
    if unknown_scenarios:
        fail(f"{path}.verification_scenarios contains unknown scenarios: {unknown_scenarios}")
    if expected_scenarios and not scenarios:
        fail(f"{path}.verification_scenarios must map the telemetry item to audit scenarios")
    source = durable_artifact_text(text(row.get("source"), f"{path}.source"), f"{path}.source")
    change = text(row.get("change"), f"{path}.change")
    normalized = {
        "id": item_id,
        "change_kind": change_kind,
        "change": change,
        "type": signal_type,
        "name": signal_name,
        "source": source,
        "added_attributes": added_attributes,
        "product_view": text(row.get("product_view"), f"{path}.product_view"),
        "follow_up_actions": follow_up_actions,
        "verification_scenarios": scenarios,
    }
    compatibility = normalize_consumer_compatibility(
        row,
        f"{path}.consumer_compatibility",
    )
    if compatibility is not None:
        normalized["consumer_compatibility"] = compatibility
    return normalized


def normalize_consumer_compatibility(
    row: dict[str, Any],
    path: str,
) -> dict[str, Any] | None:
    if "consumer_compatibility" not in row:
        return None
    compatibility = as_object(row.get("consumer_compatibility"), path)
    status = text(compatibility.get("status"), f"{path}.status")
    if status not in CONSUMER_COMPATIBILITY_STATUSES:
        fail(
            f"{path}.status must be one of "
            f"{sorted(CONSUMER_COMPATIBILITY_STATUSES)}"
        )
    migration = string_list(compatibility.get("migration", []), f"{path}.migration")
    if status == "breaking" and not migration:
        fail(f"{path}.migration must name the required consumer migration")
    return {
        "status": status,
        "existing_contract": non_empty_string_list(
            compatibility.get("existing_contract", []),
            f"{path}.existing_contract",
        ),
        "instrumentation_action": text(
            compatibility.get("instrumentation_action"),
            f"{path}.instrumentation_action",
        ),
        "user_impact": text(
            compatibility.get("user_impact"),
            f"{path}.user_impact",
        ),
        "migration": migration,
    }


def normalize_instrumentation(data: dict[str, Any], report: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
    if data.get("schema_version") != OVERLAY_SCHEMA_VERSION or data.get("kind") != "otel-instrumentation":
        fail("instrumentation must have schema_version 1 and kind otel-instrumentation")
    meta = as_object(data.get("meta"), "instrumentation.meta")
    result = text(meta.get("result"), "instrumentation.meta.result")
    if result not in INSTRUMENTATION_RESULT_STATUSES:
        fail(
            "instrumentation.meta.result must be one of "
            f"{sorted(INSTRUMENTATION_RESULT_STATUSES)}"
        )
    if stable_id(data.get("audit_id"), "instrumentation.audit_id") != report["meta"]["audit_id"]:
        fail("instrumentation.audit_id does not match audit")
    if text(data.get("audit_sha256"), "instrumentation.audit_sha256") != audit_digest(report):
        fail("instrumentation.audit_sha256 does not match audit")
    supplied_selection_digest = optional_text(
        data.get("selection_sha256"), "instrumentation.selection_sha256"
    )
    expected_selection_digest = selection_digest(selection)
    if supplied_selection_digest is None:
        fail(
            "instrumentation.selection_sha256 is required to bind implementation "
            "to the exact normalized selection"
        )
    if supplied_selection_digest != expected_selection_digest:
        fail("instrumentation.selection_sha256 does not match selection")
    rows = []
    seen = set()
    telemetry_ids: set[str] = set()
    audit_findings = {finding["id"]: finding for finding in report["findings"]}
    for index, row in enumerate(object_list(data.get("findings", []), "instrumentation.findings")):
        row_path = f"instrumentation.findings[{index}]"
        finding_id = stable_id(row.get("id"), f"{row_path}.id")
        if finding_id in seen:
            fail(f"duplicate instrumentation finding ID: {finding_id}")
        seen.add(finding_id)
        status = text(row.get("status"), f"{row_path}.status")
        if status not in CLOSURE_STATUSES:
            fail(f"{row_path}.status must be one of {sorted(CLOSURE_STATUSES)}")
        changes = string_list(row.get("changes", []), f"{row_path}.changes")
        tests = string_list(row.get("tests", []), f"{row_path}.tests")
        evidence = durable_artifact_list(row.get("evidence", []), f"{row_path}.evidence")
        if not changes:
            fail(
                f"{row_path}.changes must record the concrete correction or explain "
                "why the selected row is proof-only"
            )
        if status == "working" and (not changes or not tests or not evidence):
            fail(f"working instrumentation row {finding_id} requires changes, tests, and evidence")
        telemetry_changes = [
            normalize_telemetry_change(
                item,
                f"{row_path}.telemetry_changes[{item_index}]",
                finding_id,
                audit_findings.get(finding_id, {}).get("verification_scenarios", []),
            )
            for item_index, item in enumerate(
                object_list(row.get("telemetry_changes", []), f"{row_path}.telemetry_changes")
            )
        ]
        local_telemetry_ids = [item["id"] for item in telemetry_changes]
        duplicate_telemetry_ids = sorted(
            {
                item_id
                for item_id in local_telemetry_ids
                if local_telemetry_ids.count(item_id) > 1 or item_id in telemetry_ids
            }
        )
        if duplicate_telemetry_ids:
            fail(f"duplicate instrumentation telemetry item IDs: {duplicate_telemetry_ids}")
        telemetry_ids.update(local_telemetry_ids)
        rows.append(
            {
                "id": finding_id,
                "status": status,
                "changes": changes,
                "telemetry_changes": telemetry_changes,
                "tests": tests,
                "evidence": evidence,
                "follow_up_actions": non_empty_string_list(
                    row.get("follow_up_actions", []), f"{row_path}.follow_up_actions"
                ),
                "resolved_commit": optional_text(row.get("resolved_commit"), f"{row_path}.resolved_commit"),
            }
        )
    approved = selection["approved_ids"]
    if [row["id"] for row in rows] != approved:
        fail(f"instrumentation finding IDs must exactly match dependency-closed selected audit order {approved}")
    failed_rows = [row for row in rows if row["status"] == "not_working"]
    if failed_rows and result != "Fail":
        fail(
            "instrumentation.meta.result must be Fail when any selected finding "
            "is not_working"
        )
    if result == "Fail" and not failed_rows:
        fail(
            "instrumentation.meta.result Fail requires at least one not_working "
            "finding"
        )
    if result == "Pass" and not rows:
        fail(
            "instrumentation.meta.result Pass requires at least one selected "
            "instrumentation finding"
        )
    selected_complete = all(row["status"] == "working" for row in rows)
    if result == "Pass" and not selected_complete:
        fail(
            "instrumentation.meta.result Pass requires every selected finding to "
            "be working"
        )
    if rows and selected_complete and result != "Pass":
        fail(
            "instrumentation.meta.result must be Pass when every selected finding "
            "is working"
        )
    normalized = {
        "schema_version": OVERLAY_SCHEMA_VERSION,
        "kind": "otel-instrumentation",
        "audit_id": report["meta"]["audit_id"],
        "audit_sha256": audit_digest(report),
        "selection_sha256": supplied_selection_digest,
        "meta": {
            "service_name": text(meta.get("service_name"), "instrumentation.meta.service_name"),
            "date": text(meta.get("date"), "instrumentation.meta.date"),
            "result": result,
        },
        "findings": rows,
        "next_steps": string_list(data.get("next_steps", []), "instrumentation.next_steps"),
    }
    return normalized


def item_source_denies_delivery(source_item: dict[str, Any]) -> bool:
    product_view = " ".join(str(source_item.get("product_view", "")).lower().split())
    if not product_view:
        return False
    no_delivery_phrases = (
        "no otlp",
        "no export path",
        "no exporter",
        "not exported",
        "local only",
        "source only",
        "not product-visible",
    )
    return any(phrase in product_view for phrase in no_delivery_phrases)


def normalize_verify(
    data: dict[str, Any],
    report: dict[str, Any],
    selection: dict[str, Any],
    instrumentation: dict[str, Any],
) -> dict[str, Any]:
    if data.get("schema_version") != OVERLAY_SCHEMA_VERSION or data.get("kind") != "otel-verify":
        fail("verify must have schema_version 1 and kind otel-verify")
    meta = as_object(data.get("meta"), "verify.meta")
    result = text(meta.get("result"), "verify.meta.result")
    if result not in RESULT_STATUSES:
        fail(f"verify.meta.result must be one of {sorted(RESULT_STATUSES)}")
    if stable_id(data.get("audit_id"), "verify.audit_id") != report["meta"]["audit_id"]:
        fail("verify.audit_id does not match audit")
    if text(data.get("audit_sha256"), "verify.audit_sha256") != audit_digest(report):
        fail("verify.audit_sha256 does not match audit")
    supplied_instrumentation_digest = optional_text(
        data.get("instrumentation_sha256"), "verify.instrumentation_sha256"
    )
    expected_instrumentation_digest = instrumentation_digest(instrumentation)
    if supplied_instrumentation_digest is None:
        fail(
            "verify.instrumentation_sha256 is required to bind proof to the exact "
            "normalized instrumentation overlay"
        )
    if supplied_instrumentation_digest != expected_instrumentation_digest:
        fail("verify.instrumentation_sha256 does not match instrumentation")
    audit_findings_by_id = {
        finding["id"]: finding for finding in report["findings"]
    }
    expected_by_finding = {
        finding_id: finding["verification_scenarios"]
        for finding_id, finding in audit_findings_by_id.items()
    }
    expected_items_by_finding = {
        finding["id"]: [item["id"] for item in finding["telemetry_changes"]]
        for finding in instrumentation["findings"]
    }
    instrumentation_items_by_id = {
        item["id"]: item
        for finding in instrumentation["findings"]
        for item in finding["telemetry_changes"]
    }
    rows = []
    seen = set()
    for index, row in enumerate(object_list(data.get("findings", []), "verify.findings")):
        row_path = f"verify.findings[{index}]"
        finding_id = stable_id(row.get("id"), f"{row_path}.id")
        if finding_id not in audit_findings_by_id:
            fail(f"{row_path}.id {finding_id} is not present in the bound audit")
        if finding_id not in expected_items_by_finding:
            fail(
                f"{row_path}.id {finding_id} is not present in the bound "
                "instrumentation overlay"
            )
        if finding_id in seen:
            fail(f"duplicate verify finding ID: {finding_id}")
        seen.add(finding_id)
        status = text(row.get("status"), f"{row_path}.status")
        if status not in CLOSURE_STATUSES:
            fail(f"{row_path}.status must be one of {sorted(CLOSURE_STATUSES)}")
        scenarios = []
        scenario_seen = set()
        for scenario_index, scenario in enumerate(object_list(row.get("scenarios", []), f"{row_path}.scenarios")):
            scenario_path = f"{row_path}.scenarios[{scenario_index}]"
            scenario_id = stable_id(scenario.get("id"), f"{scenario_path}.id")
            if scenario_id in scenario_seen:
                fail(f"duplicate scenario {scenario_id} for {finding_id}")
            scenario_seen.add(scenario_id)
            scenario_status = text(scenario.get("status"), f"{scenario_path}.status")
            if scenario_status not in SCENARIO_STATUSES:
                fail(f"{scenario_path}.status must be one of {sorted(SCENARIO_STATUSES)}")
            blocking_reason = optional_text(
                scenario.get("blocking_reason"), f"{scenario_path}.blocking_reason"
            )
            unobserved_outcome = optional_text(
                scenario.get("unobserved_outcome"),
                f"{scenario_path}.unobserved_outcome",
            )
            commands = string_list(
                scenario.get("commands", []), f"{scenario_path}.commands"
            )
            evidence = durable_artifact_list(
                scenario.get("evidence", []), f"{scenario_path}.evidence"
            )
            observed_telemetry = string_list(
                scenario.get("observed_telemetry", []), f"{scenario_path}.observed_telemetry"
            )
            product_validation = string_list(
                scenario.get("product_validation", []), f"{scenario_path}.product_validation"
            )
            proof_mode = text(scenario.get("proof_mode"), f"{scenario_path}.proof_mode")
            if proof_mode not in PROOF_MODES:
                fail(f"{scenario_path}.proof_mode must be one of {sorted(PROOF_MODES)}")
            visibility = text(scenario.get("visibility"), f"{scenario_path}.visibility")
            if visibility not in VISIBILITY_STATES:
                fail(f"{scenario_path}.visibility must be one of {sorted(VISIBILITY_STATES)}")
            if scenario_status == "blocked":
                if blocking_reason is None or unobserved_outcome is None:
                    fail(
                        f"blocked scenario {scenario_id} requires blocking_reason and "
                        "unobserved_outcome"
                    )
                if not commands or not evidence:
                    fail(
                        f"blocked scenario {scenario_id} requires the command and durable "
                        "evidence that support its blocking_reason"
                    )
                if proof_mode != "not_run" or visibility != "not_proven":
                    fail(
                        f"blocked scenario {scenario_id} must use proof_mode not_run and "
                        "visibility not_proven"
                    )
            elif blocking_reason is not None or unobserved_outcome is not None:
                fail(
                    f"{scenario_path}.blocking_reason and unobserved_outcome are valid "
                    "only when status is blocked"
                )
            if scenario_status == "working" and (
                not evidence
                or not observed_telemetry
                or not product_validation
                or proof_mode == "not_run"
                or visibility == "not_proven"
            ):
                fail(
                    f"working scenario {scenario_id} requires evidence, observed telemetry, "
                    "product validation, an executed proof mode, and a known visibility state"
                )
            if scenario_status == "not_working" and (
                not evidence
                or not observed_telemetry
                or not product_validation
                or proof_mode == "not_run"
            ):
                fail(
                    f"not_working scenario {scenario_id} requires executed proof, "
                    "direct evidence, observed failure behavior, and a product result"
                )
            if visibility in {"otlp_accepted", "explorer_visible"} and (
                not evidence
                or not observed_telemetry
                or not product_validation
                or proof_mode == "not_run"
            ):
                fail(
                    f"{scenario_path}.visibility {visibility} requires executed proof, "
                    "direct evidence, observed telemetry, and product validation"
                )
            normalized_scenario = {
                "id": scenario_id,
                "status": scenario_status,
                "commands": commands,
                "evidence": evidence,
                "observed_telemetry": observed_telemetry,
                "trace_ids": string_list(
                    scenario.get("trace_ids", []), f"{scenario_path}.trace_ids"
                ),
                "product_validation": product_validation,
                "proof_mode": proof_mode,
                "visibility": visibility,
            }
            if blocking_reason is not None and unobserved_outcome is not None:
                normalized_scenario["blocking_reason"] = blocking_reason
                normalized_scenario["unobserved_outcome"] = unobserved_outcome
            scenarios.append(normalized_scenario)
        expected_scenarios = expected_by_finding.get(finding_id, [])
        actual_scenarios = [scenario["id"] for scenario in scenarios]
        if actual_scenarios != expected_scenarios:
            fail(f"verify row {finding_id} must cover scenarios {expected_scenarios} in audit order")
        remaining = string_list(row.get("remaining", []), f"{row_path}.remaining")
        item_results = []
        item_seen: set[str] = set()
        for item_index, item in enumerate(object_list(row.get("item_results", []), f"{row_path}.item_results")):
            item_path = f"{row_path}.item_results[{item_index}]"
            item_id = stable_id(item.get("id"), f"{item_path}.id")
            if item_id in item_seen:
                fail(f"duplicate verify item result ID: {item_id}")
            item_seen.add(item_id)
            item_status = text(item.get("status"), f"{item_path}.status")
            if item_status not in SCENARIO_STATUSES:
                fail(f"{item_path}.status must be one of {sorted(SCENARIO_STATUSES)}")
            direct_assertion_passed = item.get("direct_assertion_passed")
            if not isinstance(direct_assertion_passed, bool):
                fail(f"{item_path}.direct_assertion_passed must be a boolean")
            if direct_assertion_passed != (item_status == "working"):
                fail(
                    f"{item_path}.direct_assertion_passed must be true exactly when "
                    "the item status is working; finding or scenario coverage cannot "
                    "downgrade a passed item assertion"
                )
            proof_mode = text(item.get("proof_mode"), f"{item_path}.proof_mode")
            if proof_mode not in PROOF_MODES:
                fail(f"{item_path}.proof_mode must be one of {sorted(PROOF_MODES)}")
            visibility = text(item.get("visibility"), f"{item_path}.visibility")
            if visibility not in VISIBILITY_STATES:
                fail(f"{item_path}.visibility must be one of {sorted(VISIBILITY_STATES)}")
            item_scenarios = [
                stable_id(value, f"{item_path}.scenarios[{scenario_index}]")
                for scenario_index, value in enumerate(
                    as_list(item.get("scenarios", []), f"{item_path}.scenarios")
                )
            ]
            if len(item_scenarios) != len(set(item_scenarios)):
                fail(f"{item_path}.scenarios must not contain duplicates")
            source_item = instrumentation_items_by_id.get(item_id)
            if source_item is None:
                fail(f"{item_path}.id is not defined by the instrumentation overlay")
            mapped_item_scenarios = set(source_item["verification_scenarios"])
            unknown_item_scenarios = sorted(
                set(item_scenarios) - mapped_item_scenarios
            )
            if unknown_item_scenarios:
                fail(
                    f"{item_path}.scenarios contains scenarios not mapped to the "
                    f"telemetry item: {unknown_item_scenarios}"
                )
            item_evidence = durable_artifact_list(
                item.get("evidence", []), f"{item_path}.evidence"
            )
            item_observed = string_list(
                item.get("observed_telemetry", []), f"{item_path}.observed_telemetry"
            )
            item_product = string_list(
                item.get("product_validation", []), f"{item_path}.product_validation"
            )
            removal_proof: dict[str, Any] | None = None
            if source_item["change_kind"] == "removed":
                raw_removal_proof = item.get("removal_proof")
                if raw_removal_proof is not None:
                    proof = as_object(raw_removal_proof, f"{item_path}.removal_proof")
                    removed_signal = text(
                        proof.get("removed_signal"),
                        f"{item_path}.removal_proof.removed_signal",
                    )
                    replacement_signal = text(
                        proof.get("replacement_signal"),
                        f"{item_path}.removal_proof.replacement_signal",
                    )
                    absence_assertion_passed = proof.get(
                        "absence_assertion_passed"
                    )
                    replacement_assertion_passed = proof.get(
                        "replacement_assertion_passed"
                    )
                    if removed_signal != source_item["name"]:
                        fail(
                            f"{item_path}.removal_proof.removed_signal must exactly "
                            "match the removed telemetry item name"
                        )
                    if replacement_signal == removed_signal:
                        fail(
                            f"{item_path}.removal_proof.replacement_signal must name "
                            "the distinct intended replacement owner"
                        )
                    if not isinstance(absence_assertion_passed, bool):
                        fail(
                            f"{item_path}.removal_proof.absence_assertion_passed "
                            "must be a boolean"
                        )
                    if not isinstance(replacement_assertion_passed, bool):
                        fail(
                            f"{item_path}.removal_proof.replacement_assertion_passed "
                            "must be a boolean"
                        )
                    removal_proof = {
                        "removed_signal": removed_signal,
                        "replacement_signal": replacement_signal,
                        "absence_assertion_passed": absence_assertion_passed,
                        "replacement_assertion_passed": replacement_assertion_passed,
                    }
                if item_status == "working" and (
                    removal_proof is None
                    or not removal_proof["absence_assertion_passed"]
                    or not removal_proof["replacement_assertion_passed"]
                ):
                    fail(
                        f"working removed item {item_id} requires structured proof "
                        "that the removed signal is absent and its intended "
                        "replacement owner is present"
                    )
            if item_status == "working" and (
                not item_scenarios
                or not item_evidence
                or not item_observed
                or not item_product
                or proof_mode not in ITEM_DIRECT_PROOF_MODES
                or visibility == "not_proven"
            ):
                fail(
                    f"working item result {item_id} requires scenarios, direct evidence, observed telemetry, "
                    "product validation, a direct unit/application/runtime proof mode, "
                    "and a known visibility state"
                )
            if item_status == "not_working" and (
                not item_scenarios
                or not item_evidence
                or not item_observed
                or not item_product
                or proof_mode == "not_run"
            ):
                fail(
                    f"not_working item result {item_id} requires mapped scenarios, "
                    "executed proof, direct evidence, observed failure behavior, and "
                    "a product result"
                )
            if visibility in {"otlp_accepted", "explorer_visible"} and (
                not item_scenarios
                or not item_evidence
                or not item_observed
                or not item_product
                or proof_mode == "not_run"
            ):
                fail(
                    f"{item_path}.visibility {visibility} requires mapped scenarios, "
                    "executed proof, direct evidence, observed telemetry, and product validation"
                )
            if visibility in {"otlp_accepted", "explorer_visible"} and item_source_denies_delivery(source_item):
                fail(
                    f"{item_path}.visibility {visibility} conflicts with "
                    "the instrumentation item product_view delivery capability"
                )
            normalized_item = {
                "id": item_id,
                "status": item_status,
                "direct_assertion_passed": direct_assertion_passed,
                "scenarios": item_scenarios,
                "proof_mode": proof_mode,
                "visibility": visibility,
                "evidence": item_evidence,
                "observed_telemetry": item_observed,
                "product_validation": item_product,
            }
            if removal_proof is not None:
                normalized_item["removal_proof"] = removal_proof
            item_results.append(normalized_item)
        expected_items = expected_items_by_finding.get(finding_id, [])
        if [item["id"] for item in item_results] != expected_items:
            fail(f"verify row {finding_id} item_results must exactly cover {expected_items} in instrumentation order")
        if status == "working":
            if not scenarios and not item_results:
                fail(
                    f"working verify row {finding_id} requires at least one "
                    "scenario or telemetry-item proof"
                )
            if any(scenario["status"] != "working" for scenario in scenarios):
                fail(f"working verify row {finding_id} requires every scenario to be working")
            if remaining:
                fail(f"working verify row {finding_id} must not have remaining work")
            if any(item["status"] != "working" for item in item_results):
                fail(f"working verify row {finding_id} requires every telemetry item to be working")
        nested_failure = any(
            scenario["status"] == "not_working" for scenario in scenarios
        ) or any(item["status"] == "not_working" for item in item_results)
        if status == "not_working" and not nested_failure:
            fail(
                f"not_working verify row {finding_id} requires at least one "
                "executed not_working scenario or telemetry item"
            )
        all_nested_working = all(
            scenario["status"] == "working" for scenario in scenarios
        ) and all(item["status"] == "working" for item in item_results)
        if all_nested_working and not remaining and status != "working":
            fail(
                f"verify row {finding_id} must be working when every mapped scenario "
                "and telemetry item is working and no work remains"
            )
        if status != "working" and not remaining:
            fail(f"unresolved verify row {finding_id} requires concrete remaining work")
        rows.append(
            {
                "id": finding_id,
                "status": status,
                "scenarios": scenarios,
                "item_results": item_results,
                "remaining": remaining,
            }
        )
    approved = selection["approved_ids"]
    if [row["id"] for row in rows] != approved:
        fail(f"verify finding IDs must exactly match dependency-closed selected audit order {approved}")
    next_steps = string_list(data.get("next_steps", []), "verify.next_steps")
    nested_failures = [
        row["id"]
        for row in rows
        if any(scenario["status"] == "not_working" for scenario in row["scenarios"])
        or any(item["status"] == "not_working" for item in row["item_results"])
    ]
    for row in rows:
        if row["id"] in nested_failures and row["status"] != "not_working":
            fail(
                f"verify row {row['id']} must be not_working when an executed "
                "scenario or telemetry item is not_working"
            )
    failed_rows = [row for row in rows if row["status"] == "not_working"]
    if failed_rows and result != "Fail":
        fail("verify.meta.result must be Fail when any finding is not_working")
    if result == "Fail" and not failed_rows:
        fail("verify.meta.result Fail requires at least one not_working finding")
    if result == "Pass" and any(row["status"] != "working" for row in rows):
        fail("verify.meta.result Pass requires every finding to be working")
    if rows and all(row["status"] == "working" for row in rows) and result != "Pass":
        fail("verify.meta.result must be Pass when every finding is working")
    meaningful_proof = any(
        scenario["proof_mode"] != "not_run"
        for row in rows
        for scenario in row["scenarios"]
    ) or any(
        item["proof_mode"] != "not_run"
        for row in rows
        for item in row["item_results"]
    )
    has_blocker = any(
        scenario["status"] == "blocked"
        for row in rows
        for scenario in row["scenarios"]
    )
    if failed_rows:
        expected_result = "Fail"
    elif rows and all(row["status"] == "working" for row in rows):
        expected_result = "Pass"
    elif meaningful_proof:
        expected_result = "Partial"
    elif has_blocker:
        expected_result = "Blocked"
    else:
        expected_result = "Not run"
    if result != expected_result:
        fail(
            f"verify.meta.result must be {expected_result} for the recorded "
            "scenario and telemetry-item proof"
        )
    normalized = {
        "schema_version": OVERLAY_SCHEMA_VERSION,
        "kind": "otel-verify",
        "audit_id": report["meta"]["audit_id"],
        "audit_sha256": audit_digest(report),
        "instrumentation_sha256": supplied_instrumentation_digest,
        "meta": {
            "service_name": text(meta.get("service_name"), "verify.meta.service_name"),
            "date": text(meta.get("date"), "verify.meta.date"),
            "result": result,
        },
        "findings": rows,
        "next_steps": next_steps,
    }
    return normalized


def load_json(path: Path) -> dict[str, Any]:
    try:
        return as_object(json.loads(path.read_text(encoding="utf-8")), str(path))
    except (UnicodeError, json.JSONDecodeError) as exc:
        fail(f"{path} is not valid JSON: {exc}")


def empty_selection(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": OVERLAY_SCHEMA_VERSION,
        "kind": "otel-selection",
        "audit_id": report["meta"]["audit_id"],
        "audit_sha256": audit_digest(report),
        "requested_ids": [],
        "approved_ids": [],
        "approved_by": None,
        "approved_at": None,
    }


def load_selection(
    path: Path | None,
    report: dict[str, Any],
    audit_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if path is not None:
        return normalize_selection(load_json(path), report, str(path))
    if isinstance(audit_data, dict) and isinstance(
        audit_data.get("review_selection"), dict
    ):
        return normalize_selection(
            audit_data["review_selection"],
            report,
            "audit.review_selection",
        )
    return empty_selection(report)


def selection_candidate_paths(
    audit_json: Path,
    output: Path,
    explicit_candidates: list[Path],
    search_directories: list[Path],
) -> list[tuple[int, Path]]:
    candidates: dict[str, tuple[int, Path]] = {}

    def add(path: Path, trust_tier: int) -> None:
        key = os.path.abspath(path)
        existing = candidates.get(key)
        if existing is None or trust_tier < existing[0]:
            candidates[key] = (trust_tier, path)

    for candidate in explicit_candidates:
        add(candidate, 0)

    directory_tiers = [
        (audit_json.parent, 1),
        (output.parent, 1),
        *((directory, 2) for directory in search_directories),
        (Path.home() / "Downloads", 3),
    ]
    for directory, trust_tier in directory_tiers:
        if not directory.is_dir():
            continue
        for pattern in ("otel-selection*.json", "otel-audit*.json"):
            for candidate in sorted(directory.glob(pattern)):
                add(candidate, trust_tier)
    return list(candidates.values())


def try_load_bound_selection(path: Path, report: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = load_json(path)
    except (OSError, ReportError) as exc:
        return None, str(exc)
    if data.get("kind") == "otel-audit":
        if not isinstance(data.get("review_selection"), dict):
            return None, "audit report has no review_selection"
        try:
            candidate_report = normalize_audit_report(data)
        except ReportError as exc:
            return None, f"saved audit is invalid: {exc}"
        if candidate_report["meta"]["audit_id"] != report["meta"]["audit_id"]:
            return None, "saved audit_id does not match"
        if audit_digest(candidate_report) != audit_digest(report):
            return None, "saved audit_sha256 does not match"
        try:
            return (
                normalize_selection(
                    data["review_selection"],
                    report,
                    f"{path}.review_selection",
                ),
                None,
            )
        except ReportError as exc:
            return None, str(exc)
    if data.get("kind") != "otel-selection":
        return None, "kind is not otel-selection or otel-audit with review_selection"
    if data.get("audit_id") != report["meta"]["audit_id"]:
        return None, "audit_id does not match"
    if data.get("audit_sha256") != audit_digest(report):
        return None, "audit_sha256 does not match"
    try:
        return normalize_selection(data, report, str(path)), None
    except ReportError as exc:
        return None, str(exc)
