#!/usr/bin/env python3
"""Validate, scope, and render the structured OTel report workflow."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import unicodedata
from pathlib import Path, PurePath
from typing import Any
from urllib.parse import quote


OVERLAY_SCHEMA_VERSION = 1
CURRENT_SELECTION_SCHEMA_VERSION = 2
SUPPORTED_SELECTION_SCHEMA_VERSIONS = {1, CURRENT_SELECTION_SCHEMA_VERSION}
CURRENT_AUDIT_SCHEMA_VERSION = 2
SUPPORTED_AUDIT_SCHEMA_VERSIONS = {1, CURRENT_AUDIT_SCHEMA_VERSION}
STABLE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
STATUSES = {"Pass", "Partial", "Blocked"}
RESULT_STATUSES = STATUSES | {"Fail", "Not run"}
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
CANONICAL_OWNER_TERMS = (
    "app-owned",
    "service-owned",
    "framework-owned",
    "bridge-owned",
    "agent-owned",
    "runtime-owned",
    "sdk-owned",
    "callback",
    "provider sdk",
    "opentelemetry java agent",
    "otel java agent",
    "java agent",
    "opentelemetry agent",
    "otel agent",
    "auto-instrumentation",
    "auto instrumentation",
    "framework instrumentation",
    "micronaut",
    "spring",
)
SIGNAL_TYPES = {"span", "metric", "log", "resource", "configuration"}
CONFIGURATION_SCOPES = {
    "otel-sdk",
    "otel-resource",
    "otel-exporter",
    "otel-sampling",
    "otel-propagation",
    "otel-instrumentation",
    "otel-collector",
}
OTEL_CONCERN_ORDER = (
    "signal-emission",
    "context-propagation",
    "trace-log-correlation",
    "semantic-attributes",
    "cardinality-safety",
    "otel-configuration",
    "telemetry-proof",
)
OTEL_CONCERNS = set(OTEL_CONCERN_ORDER)
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
PROHIBITED_CLOSURE_RULES = (
    (
        "API or OpenAPI contract work",
        re.compile(r"\b(?:add|author|update|publish|generate|lint|validate|approve|sync|enforce|version)(?:s|ed|ing)?\b"),
        re.compile(r"\b(?:openapi|swagger|api contract|client contract|contract schema|generated (?:sdk|client))\b"),
    ),
    (
        "documentation or runbook work",
        re.compile(r"\b(?:add|create|write|update|publish|fix|validate|link|maintain)(?:s|ed|ing)?\b"),
        re.compile(r"\b(?:documentation|runbook|playbook|readme|wiki|confluence|owner(?:ship)? link|chat link|slack link)\b"),
    ),
    (
        "behavior-only testing",
        re.compile(r"\b(?:add|create|write|fix|enable|enforce|update)(?:s|ed|ing)?\b"),
        re.compile(r"\b(?:behavior only (?:test|check)|contract lint|docs? lint|link lint|ci (?:job|workflow|check)|coverage threshold|(?:unit|integration|e2e) test)\b"),
    ),
    (
        "product behavior or policy work",
        re.compile(r"\b(?:implement|change|define|choose|decide|select|govern|apply|adopt|approve|enforce|tune|set|enable|disable|increase|decrease|fix)(?:s|d|ed|ing)?\b"),
        re.compile(
            r"\b(?:retry (?:policy|behavior)|backoff (?:policy|behavior)|circuit breaker (?:policy|behavior)|"
            r"timeout (?:policy|value)|deadline (?:policy|value)|cache (?:policy|ttl|invalidation)|"
            r"fallback (?:policy|target|behavior)|rate limit|quota|product limit|page (?:size|limit)|"
            r"request limit|rejection (?:policy|response)|liveness semantics|readiness semantics|"
            r"health semantics|deployment policy|release policy|rollout policy|auth(?:entication|orization)? policy|security policy)\b"
            r"|\bapproval policy\b"
        ),
    ),
    (
        "ownership administration",
        re.compile(r"\b(?:create|update|publish|maintain|assign|discover)(?:s|ed|ing)?\b"),
        re.compile(r"\b(?:owner map|ownership map|ownership link|contact list|escalation policy|on call rotation)\b"),
    ),
    (
        "general service configuration",
        re.compile(r"\b(?:change|configure|set|update)(?:s|d|ed|ing)?\b"),
        re.compile(r"\b(?:feature flag|application config|service config|helm values|kubernetes manifest|docker config|deployment manifest|environment variable)\b"),
    ),
)
PROHIBITED_TELEMETRY_OUTPUT = re.compile(
    r"\b(?:runbook|documentation|owner link|contract lint|contract drift|"
    r"contract approval|ci status|lint result|test result|policy approval)\b"
)
PROHIBITED_AUDIT_SECTION_OUTPUT = re.compile(
    r"\b(?:openapi|swagger|api contract|runbook|playbook|documentation|"
    r"owner(?:ship)? link|owner discovery|behavior only test|contract lint|"
    r"link validation)\b"
)
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
GENAI_CLOSURE_STATUSES = CLOSURE_STATUSES | {"partial", "owner_mapped"}
GENAI_PASS_STATUSES = {"working", "deferred", "owner_mapped"}
NEGATIVE_OR_UNCERTAIN_INSTRUMENTATION_PROOF = re.compile(
    r"(?:^\s*(?:none|unproven|blocked|pending|skipped|unknown|n/?a)\b|"
    r"\b(?:not proven|not configured|not run|not tested|unsuccessful|"
    r"failed|failure|errored?|rejected|denied|unavailable|uncertain)\b|"
    r"\b(?:could|did)\s+not\b|\bno\s+(?:evidence|result|output|proof)\b|"
    r"\btests?\s+(?:are\s+)?blocked\b)",
    re.IGNORECASE,
)
AFFIRMATIVE_IMPLEMENTATION_PROOF = re.compile(
    r"\b(?:pass(?:ed)?|success(?:ful(?:ly)?)?|succeed(?:ed)?|completed|executed|"
    r"accepted|captured|observed|emitted|exported|recorded|assert(?:ed|ion)?|"
    r"implemented|instrumented|configured|added|go\s+test|pytest|cargo\s+test|"
    r"npm(?:\s+run)?\s+test)\b",
    re.IGNORECASE,
)
AFFIRMATIVE_EXECUTED_INSTRUMENTATION_PROOF = re.compile(
    r"\b(?:pass(?:ed)?|success(?:ful(?:ly)?)?|succeed(?:ed)?|completed|executed|"
    r"accepted|captured|observed|emitted|exported|recorded|assert(?:ed|ion)?|"
    r"go\s+test|pytest|cargo\s+test|npm(?:\s+run)?\s+test)\b",
    re.IGNORECASE,
)
POSITIVE_INSTRUMENTATION_EVIDENCE = re.compile(
    r"(?:^|/)\.observe/evidence/|"
    r"(?:^|[\s/])[A-Za-z0-9_.-]+\.(?:jsonl?|txt|log|xml|html?|md|out|"
    r"tap|junit|otlp|pb)(?=$|[\s,;:])|"
    r"\b(?:pass(?:ed)?|succeed(?:ed)?|accepted|captured|observed|emitted|"
    r"exported|recorded|assertion)\b",
    re.IGNORECASE,
)
DURABLE_INSTRUMENTATION_ARTIFACT_REFERENCE = re.compile(
    r"(?:^|[\s;`])(?:\.?[A-Za-z0-9_.-]+[/\\])*[A-Za-z0-9_.-]+\."
    r"(?:jsonl?|txt|log|xml|html?|md|out|tap|junit|otlp|pb)(?=$|[\s,;:`])",
    re.IGNORECASE,
)
NON_PROOF_INSTRUMENTATION_ARTIFACT_LABEL = re.compile(
    r"\b(?:none|unproven|not\s+(?:proven|configured|run|tested)|blocked|"
    r"pending|skipped|unknown)\b",
    re.IGNORECASE,
)
SCENARIO_STATUSES = {"working", "not_working", "not_proven", "not_configured", "blocked"}
CHANGE_KINDS = {"added", "modified", "removed"}
PROOF_MODES = {"app_test", "unit", "unit+otlp", "full_runtime", "contract_only", "static", "not_run"}
ITEM_DIRECT_PROOF_MODES = {"app_test", "unit", "unit+otlp", "full_runtime"}
VISIBILITY_STATES = {
    "explorer_visible",
    "otlp_accepted",
    "not_explorer_visible",
    "not_proven",
    "not_applicable",
}
VERIFY_WORKFLOW_MODES = {"standalone", "instrumentation_child"}
VERIFY_LIFECYCLES = {"intermediate", "final"}
STOP_BOUNDARY_KINDS = {
    "unselected_work",
    "material_decision",
    "new_authority",
    "external_prerequisite",
}
IMPERATIVE_STOP_BOUNDARY_REASON = re.compile(
    r"^(?:run|rerun|provide|supply|install|restore|refresh|start|configure|"
    r"obtain|use|record|execute|exercise|capture|inspect|verify|prove|repair|"
    r"fix|change|remove|add|choose|decide|approve|authorize)\b",
    re.IGNORECASE,
)
EPHEMERAL_ARTIFACT_PREFIXES = (
    "/tmp",
    "/private/tmp",
    "/var/folders",
    "/private/var/folders",
)
FLOW_MARKER = re.compile(r"\[(SOURCE-COVERED|GAP:\s*([^\]]+))\]")
FLOW_BRACKET = re.compile(r"\[[^\]]+\]")
METRIC_PRODUCT_ACTION = re.compile(r"\b(chart|dashboard|detector|alert|monitor)\b", re.IGNORECASE)
DIMENSION_PRODUCT_ACTION = re.compile(r"\b(filter|slice|group(?:-?by)?|breakdown)\b", re.IGNORECASE)
GENERIC_TELEMETRY_CHANGE = re.compile(
    r"\b(?:for|to satisfy) the selected bounded telemetry contract\b",
    re.IGNORECASE,
)
DENIES_OTLP_DELIVERY = re.compile(
    r"\bno\b.{0,40}\botlp\b.{0,40}\b(?:pipeline|export(?:er| path)?)\b",
    re.IGNORECASE,
)
CLOUD_PRODUCT_EVIDENCE = re.compile(
    r"\b(?:Splunk Observability Cloud|Splunk O11y Cloud)\b", re.IGNORECASE
)
NO_FURTHER_ACTION = re.compile(
    r"\b(?:no|nothing)\s+(?:further|remaining|else|more)?\s*"
    r"(?:action|work|proof|verification|change)s?\s+(?:is|are)\s+required\b",
    re.IGNORECASE,
)
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


def normalized_action_words(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", normalized).split())


def validate_otel_closure_text(
    value: str,
    path: str,
    *,
    telemetry_output: bool = False,
    audit_section: bool = False,
) -> None:
    clauses = [
        normalized_words(clause)
        for clause in re.split(r"[;\n]|(?<=[.!?])\s+", value)
        if clause.strip()
    ]
    for clause in clauses:
        audit_match = (
            PROHIBITED_AUDIT_SECTION_OUTPUT.search(clause)
            if audit_section
            else None
        )
        allowed_openapi_route_signal = bool(
            audit_match
            and audit_match.group(0) in {"openapi", "swagger"}
            and re.search(r"/(?:openapi|swagger)(?:\.json)?(?:\b|$)", clause)
            and re.search(
                r"\b(?:span|metric|trace|otel|opentelemetry|telemetry|attribute)\b",
                clause,
            )
        )
        if audit_match and not allowed_openapi_route_signal:
            fail(
                f"{path} contains prohibited non-OpenTelemetry audit content in "
                f"clause {clause!r}; move this fact to evidence/constraints or remove it"
            )
        if telemetry_output and PROHIBITED_TELEMETRY_OUTPUT.search(clause):
            fail(
                f"{path} contains prohibited non-OpenTelemetry output in clause "
                f"{clause!r}; move this fact to evidence/constraints or remove it"
            )
        for category, action_pattern, object_pattern in PROHIBITED_CLOSURE_RULES:
            if not action_pattern.search(clause) or not object_pattern.search(clause):
                continue
            if category == "behavior-only testing" and re.search(
                r"\b(?:span|metric|trace|otel|opentelemetry|exporter|collector|"
                r"telemetry|parentage|attribute|context)\b",
                clause,
            ):
                continue
            if category == "general service configuration" and re.search(
                r"\b(?:otel|opentelemetry|collector|exporter|provider)\b|otel_",
                clause,
            ):
                continue
            fail(
                f"{path} contains prohibited non-OpenTelemetry closure work "
                f"({category}) in clause {clause!r}; move this fact to "
                "evidence/constraints or remove it"
            )


def validate_audit_review_next_step(value: str, path: str) -> None:
    if AUDIT_VERIFY_NEXT_STEP.search(value):
        fail(
            f"{path} must not present $otel-verify or generic verification as "
            "the audit next step; direct reviewers to select/save audit scope "
            "and run $otel-instrument, or state standalone verification as a "
            "separate explicit request"
        )


def expected_telemetry_reference_terms(telemetry: list[dict[str, Any]]) -> set[str]:
    generic = {
        "attribute",
        "configuration",
        "error",
        "metric",
        "name",
        "otel",
        "opentelemetry",
        "outcome",
        "owner",
        "resource",
        "service",
        "signal",
        "span",
        "status",
        "telemetry",
        "type",
    }
    terms: set[str] = set()
    for item in telemetry:
        values = [item["name"], *item["attributes"]]
        scope = item.get("configuration_scope")
        if scope:
            values.append(scope)
        for value in values:
            normalized = normalized_words(value)
            if len(normalized) >= 4:
                terms.add(normalized)
            segments = re.sub(r"[^a-z0-9]+", " ", value.casefold()).split()
            terms.update(
                word
                for word in segments
                if len(word) >= 5 and word not in generic
            )
    return terms


def require_expected_telemetry_reference(
    value: str,
    path: str,
    telemetry: list[dict[str, Any]],
) -> None:
    normalized = normalized_words(value)
    terms = expected_telemetry_reference_terms(telemetry)
    if not any(term in normalized for term in terms):
        fail(
            f"{path} must reference an expected OTel signal name, attribute, "
            "or configuration scope"
        )


AFFIRMATIVE_TELEMETRY_PROOF = re.compile(
    r"\b(?:observed|emitted|recorded|exported|received|accepted|captured)\b|"
    r"\b(?:is|was|were|are)\s+(?:present|available|visible)\b|"
    r"\b(?:trace|capture|receiver|collector|exporter|result|payload|response|"
    r"batch|telemetry|span|metric|log|event|sample|recording)\b"
    r"[^.!?;\n]{0,160}\b(?:has|had|contains?|contained|included)\b",
    re.IGNORECASE,
)
ASPIRATIONAL_OR_UNCERTAIN_TELEMETRY_PROOF = re.compile(
    r"\b(?:should|would|could|can|may|might|must|will|perhaps|possibly|"
    r"maybe|pending|unknown|uncertain|apparently|expected|supposed)\b|"
    r"\b(?:appears?|seems?)\s+to\b|"
    r"\b(?:not|never)\s+(?:confirmed|verified|proven|validated|asserted)\b|"
    r"\b(?:unconfirmed|unverified|unproven)\b|"
    r"\b(?:planned|intended)\s+to\b|"
    r"\b(?:contract|configuration|documentation|specification)\s+"
    r"(?:says?|states?|describes?|expects?|requires?)\b",
    re.IGNORECASE,
)
STATIC_OR_DECLARATIVE_TELEMETRY_CONTEXT = re.compile(
    r"\b(?:source\s+(?:code|file|scan)|config(?:uration)?\s+file|"
    r"configuration\s+(?:contains?|records?|asserts?|states?|declares?|"
    r"shows?|lists?|includes?)|(?:unit\s+|integration\s+|focused\s+|"
    r"application\s+|app\s+)?test\s+(?:source|code|case|definition|"
    r"description|fixture|plan|assertion)|code\s+search|static\s+"
    r"(?:scan|check|analysis)|comment|documentation|readme|contract|"
    r"specification|schema|manifest|grep|(?:string|literal)\s+"
    r"(?:contains?|records?|asserts?|shows?|includes?))\b",
    re.IGNORECASE,
)
TELEMETRY_PROOF_CLAUSE_BOUNDARY = re.compile(
    r"(?:[.!?](?:\s+|$)|;\s*|\n+)"
)
TELEMETRY_PROOF_ASSERTION_BOUNDARY = re.compile(
    r"(?:"
    r"[.!?](?:\s+|$)|;\s*|\n+|"
    r"(?:,|\(|\[)\s*(?=(?:(?:but|and)\s+)?(?:not|no|never|without)\b|"
    r"(?:whereas|while|rather\s+than|instead\s+of)\b)|"
    r"\s+(?=(?:and\s+(?:not|no|never|without)|"
    r"but|whereas|while|rather\s+than|instead\s+of)\b)|"
    r"(?:,\s*|\s+)(?:and|while)\s+"
    r"(?=(?:(?:an?|the|another)\s+)?(?:span|trace|metric|counter|"
    r"histogram|gauge|measurement|time[ -]?series|log(?:\s+record)?)\b)"
    r")",
    re.IGNORECASE,
)

ZERO_OR_NO_TELEMETRY_PROOF = re.compile(
    r"\b(?:zero|0)\s+(?:matching\s+)?(?:spans?|traces?|metrics?|counters?|"
    r"histograms?|gauges?|measurements?|time[ -]?series|logs?|log\s+records?|"
    r"telemetry\s+items?|data\s+points?|samples?|records?)\b|"
    r"\bno\s+(?:matching\s+)?(?:spans?|traces?|metrics?|counters?|"
    r"histograms?|gauges?|measurements?|time[ -]?series|logs?|log\s+records?|"
    r"telemetry(?:\s+items?)?|data\s+points?|samples?|records?)\b|"
    r"\brecorded\s+as\s+(?:missing|absent|unobserved)\b",
    re.IGNORECASE,
)

SIGNAL_KIND_PROOF = {
    "span": re.compile(r"\b(?:span|trace)\b", re.IGNORECASE),
    "metric": re.compile(
        r"\b(?:metric|counter|histogram|gauge|measurement|time[ -]?series)\b",
        re.IGNORECASE,
    ),
    "log": re.compile(r"\b(?:log|log record)\b", re.IGNORECASE),
    "resource": re.compile(r"\bresource\b", re.IGNORECASE),
    "configuration": re.compile(
        r"\b(?:configuration|config)\b", re.IGNORECASE
    ),
}


def exact_telemetry_item_is_referenced(
    value: str,
    telemetry_item: dict[str, Any],
    attribute_field: str = "attributes",
    reference_outcome: str = "positive",
) -> bool:
    """Require exact signal tokens with proof polarity appropriate to the result."""
    if reference_outcome not in {"positive", "negative", "any"}:
        raise ValueError(f"unsupported telemetry reference outcome: {reference_outcome}")

    def exact_token_matches(source: str, token: str) -> list[re.Match[str]]:
        parts = token.strip().split()
        if not parts:
            return []
        body = r"\s+".join(re.escape(part) for part in parts)
        identifier = r"A-Za-z0-9_"
        separators = r"._:/-"
        pattern = re.compile(
            rf"(?<![{identifier}])(?<![{identifier}][{separators}])"
            rf"{body}(?![{identifier}])(?!(?:[{separators}][{identifier}]))",
            re.IGNORECASE,
        )
        return list(pattern.finditer(source))

    def exact_token_polarities(source: str, token: str) -> list[bool]:
        return [
            telemetry_mention_is_negated(source, match)
            for match in exact_token_matches(source, token)
        ]

    def kind_matches_for_type(
        source: str, signal_type: str | None
    ) -> list[re.Match[str]]:
        pattern = SIGNAL_KIND_PROOF.get(signal_type)
        if pattern is None:
            return []
        protected_matches = [
            match
            for token in (
                telemetry_item["name"],
                *telemetry_item.get(attribute_field, []),
            )
            for match in exact_token_matches(source, token)
        ]
        return [
            match
            for match in pattern.finditer(source)
            if not any(
                match.start() < protected.end() and protected.start() < match.end()
                for protected in protected_matches
            )
        ]

    def signal_kind_matches(source: str) -> list[re.Match[str]]:
        return kind_matches_for_type(source, telemetry_item.get("type"))

    def signal_kind_polarities(source: str) -> list[bool]:
        return [
            telemetry_mention_is_negated(source, match)
            for match in signal_kind_matches(source)
        ]

    def has_competing_signal_kind(source: str) -> bool:
        signal_type = telemetry_item.get("type")
        if signal_type not in {"span", "metric", "log"}:
            return False
        return any(
            other_type != signal_type and kind_matches_for_type(source, other_type)
            for other_type in SIGNAL_KIND_PROOF
            if other_type in {"span", "metric", "log"}
        )

    def has_competing_signal_correction(source: str) -> bool:
        signal_type = telemetry_item.get("type")
        if signal_type not in {"span", "metric", "log"}:
            return False
        competing = {
            "span": r"span|trace",
            "metric": r"metric|counter|histogram|gauge|measurement|time[ -]?series",
            "log": r"log|log\s+record",
        }
        other_kinds = "|".join(
            pattern
            for kind, pattern in competing.items()
            if kind != signal_type
        )
        return bool(
            re.search(
                rf"\b(?:it|this|that|the\s+(?:signal|item))\s+"
                rf"(?:is|was|were|are)\s+(?:actually\s+|instead\s+)?"
                rf"(?:an?\s+)?(?:{other_kinds})\b",
                source,
                re.IGNORECASE,
            )
        )

    def bound_signal_kind_matches(
        source: str, *, require_positive: bool
    ) -> list[re.Match[str]]:
        """Return type words that describe the exact named signal."""
        name_matches = exact_token_matches(source, telemetry_item["name"])
        kind_matches = signal_kind_matches(source)
        if not name_matches or not kind_matches or has_competing_signal_kind(source):
            return []
        filler = re.compile(
            r"^[\s,:()\[\]-]*(?:(?:a|an|the|one|single|server|client|consumer|"
            r"producer|internal|recording|named|signal)\s+){0,4}"
            r"[\s,:()\[\]-]*$",
            re.IGNORECASE,
        )
        container = re.compile(
            r"^[^.!?;\n]{0,120}\b(?:contains?|contained|includes?|included|"
            r"has|had)\s+(?:(?:a|an|the|one|single|no)\s+)?$",
            re.IGNORECASE,
        )
        emitted_as = re.compile(
            r"^[^.!?;\n]{0,80}\b(?:is|was|were|are)\s+"
            r"(?:emitted|recorded|exported|received|captured)\s+as\s+"
            r"(?:(?:a|an|the|one|single)\s+)?$",
            re.IGNORECASE,
        )
        bound: list[re.Match[str]] = []
        for kind_match in kind_matches:
            for name_match in name_matches:
                if kind_match.end() <= name_match.start():
                    between = source[kind_match.end() : name_match.start()]
                    is_bound = bool(
                        filler.fullmatch(between) or container.fullmatch(between)
                    )
                elif name_match.end() <= kind_match.start():
                    between = source[name_match.end() : kind_match.start()]
                    is_bound = bool(
                        filler.fullmatch(between) or emitted_as.fullmatch(between)
                    )
                else:
                    is_bound = True
                if not is_bound:
                    continue
                if require_positive and (
                    telemetry_mention_is_negated(source, kind_match)
                    or telemetry_mention_is_negated(source, name_match)
                ):
                    continue
                bound.append(kind_match)
                break
        return bound

    def attributes_are_bound_to_signal(
        source: str,
        attributes: set[str],
        bound_kinds: list[re.Match[str]],
    ) -> bool:
        """Keep every required attribute on the same typed signal assertion."""
        if not attributes:
            return True
        if not bound_kinds:
            return False
        all_kinds = signal_kind_matches(source)

        def distance(first: re.Match[str], second: re.Match[str]) -> int:
            if first.end() <= second.start():
                return second.start() - first.end()
            if second.end() <= first.start():
                return first.start() - second.end()
            return 0

        for attribute in attributes:
            attribute_matches = exact_token_matches(source, attribute)
            if not attribute_matches:
                return False
            bound = False
            for attribute_match in attribute_matches:
                nearest = min(
                    distance(kind_match, attribute_match)
                    for kind_match in all_kinds
                )
                if any(
                    distance(kind_match, attribute_match) == nearest
                    for kind_match in bound_kinds
                ):
                    bound = True
                    break
            if not bound:
                return False
        return True

    required_attributes = {
        attribute.strip()
        for attribute in telemetry_item.get(attribute_field, [])
    }
    tokens = [telemetry_item["name"], *sorted(required_attributes)]
    requires_signal_kind = telemetry_item.get("type") in SIGNAL_KIND_PROOF
    if reference_outcome == "negative" and not requires_signal_kind:
        token_polarities = [exact_token_polarities(value, token) for token in tokens]
        return bool(
            all(token_polarities)
            and any(
                negated
                for polarities in token_polarities
                for negated in polarities
            )
        )
    positive_match = False
    negative_match = False
    any_match = False
    for assertion in TELEMETRY_PROOF_ASSERTION_BOUNDARY.split(value):
        if not assertion.strip():
            continue
        token_polarities = [
            exact_token_polarities(assertion, token) for token in tokens
        ]
        if any(not polarities for polarities in token_polarities):
            continue
        kind_polarities = signal_kind_polarities(assertion)
        if requires_signal_kind and not kind_polarities:
            continue
        bound_kinds = (
            bound_signal_kind_matches(assertion, require_positive=False)
            if requires_signal_kind
            else []
        )
        if requires_signal_kind and not bound_kinds:
            continue
        if requires_signal_kind and not attributes_are_bound_to_signal(
            assertion, required_attributes, bound_kinds
        ):
            continue
        any_match = True
        if reference_outcome == "any":
            continue
        assertion_is_negative = bool(
            ZERO_OR_NO_TELEMETRY_PROOF.search(assertion)
            or any(
                negated
                for polarities in token_polarities
                for negated in polarities
            )
            or (requires_signal_kind and any(kind_polarities))
        )
        if assertion_is_negative:
            negative_match = True
            continue
        if (
            AFFIRMATIVE_TELEMETRY_PROOF.search(assertion)
            and not ASPIRATIONAL_OR_UNCERTAIN_TELEMETRY_PROOF.search(assertion)
            and not STATIC_OR_DECLARATIVE_TELEMETRY_CONTEXT.search(assertion)
            and (not requires_signal_kind or any(not value for value in kind_polarities))
            and all(
                any(not negated for negated in polarities)
                for polarities in token_polarities
            )
        ):
            positive_match = True
    if reference_outcome == "any":
        return any_match
    if positive_match and has_competing_signal_correction(value):
        return False
    if positive_match and negative_match:
        return False
    return positive_match if reference_outcome == "positive" else negative_match


TELEMETRY_NEGATION_BEFORE = re.compile(
    r"(?:"
    r"\b(?:no|not|never|without|rather\s+than|instead\s+of)\s+"
    r"(?:(?:an?|the)\s+)?|"
    r"\b(?:missing|absent|unobserved)\s+|"
    r"\bno\s+(?:evidence|data|sign|record)\s+(?:of|for)\s+|"
    r"\b(?:did|does|do|could|can)\s+(?:not|never)\s+"
    r"(?:find|see|observe|record|capture|receive)\s+|"
    r"\bnever\s+(?:found|saw|observed|recorded|captured|received)\s+|"
    r"\bunable\s+to\s+(?:find|see|observe|record|capture|receive)\s+|"
    r"\b(?:not|never)\s+(?:emit(?:ted)?|observ(?:e|ed)|record(?:ed)?|"
    r"export(?:ed)?|captur(?:e|ed)|receiv(?:e|ed)|contain(?:ed)?|produc(?:e|ed))\s+|"
    r"\b(?:did|does|do|could|can|was|were|is|are|has|have|had|would|should)\s+"
    r"not\s+(?:(?:be\s+)?(?:found|seen)|emit|observe|record|export|capture|receive|contain|produce)\s+|"
    r"\b(?:didn|doesn|couldn|wasn|weren|isn|aren|hasn|haven|hadn|wouldn|shouldn)"
    r"['’]t\s+(?:(?:be\s+)?(?:found|seen)|emit|observe|record|export|capture|receive|contain|produce)\s+|"
    r"\bfailed\s+to\s+(?:find|see|emit|observe|record|export|capture|receive|contain|produce)\s+"
    r")$",
    re.IGNORECASE,
)
TELEMETRY_NEGATION_AFTER = re.compile(
    r"^[\s,:;()\[\]-]*(?:"
    r"(?:is|was|were|are|remains?|remained)\s+"
    r"(?:missing|absent|unobserved|unavailable)\b|"
    r"(?:is|was|were|are|remains?|remained)\s+(?:not|never)\s+"
    r"(?:present|available|found|seen|observed|recorded|captured|received)\b|"
    r"(?:could|can|was|were|is|are|has|have|had|would|should)\s+"
    r"(?:not|never)\s+(?:be\s+)?(?:found|seen|observed|recorded|captured|received)\b|"
    r"(?:couldn|wasn|weren|isn|aren|hasn|haven|hadn|wouldn|shouldn)"
    r"['’]t\s+(?:be\s+)?(?:found|seen|observed|recorded|captured|received)\b|"
    r"(?:is|was|were|are|did|does|do|could|can|has|have|had|would|should)\s+"
    r"(?:not|never)\s+(?:emit(?:ted)?|observ(?:e|ed)|record(?:ed)?|export(?:ed)?|"
    r"captur(?:e|ed)|receiv(?:e|ed)|contain(?:ed)?|produc(?:e|ed))|"
    r"(?:isn|wasn|weren|aren|didn|doesn|couldn|hasn|haven|hadn|wouldn|shouldn)"
    r"['’]t\s+(?:emit|observe|record|export|capture|receive|contain|produce)|"
    r"(?:not|never)\s+(?:emit(?:ted)?|observ(?:e|ed)|record(?:ed)?|export(?:ed)?|"
    r"captur(?:e|ed)|receiv(?:e|ed)|contain(?:ed)?|produc(?:e|ed))|"
    r"failed\s+to\s+(?:find|see|emit|observe|record|export|capture|receive|contain|produce)|"
    r"(?:yielded|returned|produced|contained|had|has)\s+no\s+"
    r"(?:data|evidence|samples?|points?|records?)\b|"
    r"missing\b|absent\b|unobserved\b)",
    re.IGNORECASE,
)


def telemetry_mention_is_negated(value: str, match: re.Match[str]) -> bool:
    """Detect negation in the same prose clause as an exact telemetry mention."""
    before = value[: match.start()]
    after = value[match.end() :]
    boundary_matches = list(re.finditer(r"(?:[.!?;]\s+|\n+)", before))
    clause_start = boundary_matches[-1].end() if boundary_matches else 0
    clause_prefix = before[clause_start:]
    clause_end_match = re.search(r"(?:[.!?;]\s+|\n+)", after)
    clause_suffix = after[: clause_end_match.start()] if clause_end_match else after
    selector = re.match(r"^\s*\{[^{}\n]{0,256}\}", clause_suffix)
    if selector is not None:
        clause_suffix = clause_suffix[selector.end() :]
    return bool(
        TELEMETRY_NEGATION_BEFORE.search(clause_prefix)
        or TELEMETRY_NEGATION_AFTER.search(clause_suffix)
    )


def require_exact_telemetry_item_reference(
    value: str,
    path: str,
    telemetry_item: dict[str, Any],
    attribute_field: str = "attributes",
    reference_outcome: str = "positive",
) -> None:
    if not exact_telemetry_item_is_referenced(
        value, telemetry_item, attribute_field, reference_outcome
    ):
        fail(
            f"{path} must reference the exact telemetry item "
            f"{telemetry_item.get('type', 'signal')} {telemetry_item['name']} and "
            "all of its required attribute keys and authored values "
            f"with {reference_outcome} proof semantics"
        )


def require_exact_expected_telemetry_reference(
    value: str,
    path: str,
    telemetry: list[dict[str, Any]],
    reference_outcome: str,
) -> None:
    if not any(
        exact_telemetry_item_is_referenced(
            value, item, reference_outcome=reference_outcome
        )
        for item in telemetry
    ):
        expected = [f"{item['type']} {item['name']}" for item in telemetry]
        fail(
            f"{path} must reference at least one exact expected telemetry item "
            f"with {reference_outcome} proof semantics: {expected}"
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


def normalize_signal_rows(value: Any, path: str, fields: tuple[str, ...]) -> list[dict[str, str]]:
    rows = []
    for index, row in enumerate(object_list(value, path)):
        rows.append({field: compact_row_text(row.get(field), f"{path}[{index}].{field}") for field in fields})
    return rows


def normalize_proof_level(value: Any, path: str, scenario_id: str) -> str:
    raw = text(value, path)
    normalized = re.sub(r"\s+", " ", raw.strip().lower().replace("_", " ").replace("-", " "))
    proof_level = PROOF_LEVEL_ALIASES.get(normalized, raw)
    if proof_level not in PROOF_LEVELS:
        fail(f"invalid proof level for {scenario_id}: {raw}")
    return proof_level


def names_canonical_telemetry_owner(value: str) -> bool:
    lowered = re.sub(r"\s+", " ", value.lower())
    spaced = re.sub(r"[\s_-]+", " ", value.lower()).strip()
    return any(
        term in lowered or re.sub(r"[\s_-]+", " ", term).strip() in spaced
        for term in CANONICAL_OWNER_TERMS
    )


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
    explicit_otel_concerns = "otel_concerns" in row
    otel_concerns = (
        string_list(row.get("otel_concerns", []), f"{path}.otel_concerns")
        if explicit_otel_concerns
        else []
    )
    if audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION and not explicit_otel_concerns:
        fail(
            f"{path}.otel_concerns is required by audit schema "
            f"v{CURRENT_AUDIT_SCHEMA_VERSION}"
        )
    if audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION:
        if not otel_concerns:
            fail(f"{path}.otel_concerns must contain at least one item when provided")
        invalid_concerns = sorted(set(otel_concerns) - OTEL_CONCERNS)
        if invalid_concerns:
            fail(
                f"{path}.otel_concerns contains unsupported OpenTelemetry concerns: "
                f"{invalid_concerns}; expected only {sorted(OTEL_CONCERNS)}"
            )
        if len(otel_concerns) != len(set(otel_concerns)):
            fail(f"{path}.otel_concerns must not contain duplicates")
    telemetry = []
    for index, item in enumerate(object_list(row.get("expected_telemetry", []), f"{path}.expected_telemetry")):
        item_path = f"{path}.expected_telemetry[{index}]"
        signal_type = text(item.get("type"), f"{item_path}.type")
        if signal_type not in SIGNAL_TYPES:
            fail(f"{item_path}.type must be one of {sorted(SIGNAL_TYPES)}")
        configuration_scope = None
        if signal_type == "configuration":
            if "configuration_scope" in item:
                configuration_scope = text(
                    item.get("configuration_scope"),
                    f"{item_path}.configuration_scope",
                )
                if configuration_scope not in CONFIGURATION_SCOPES:
                    fail(
                        f"{item_path}.configuration_scope must be one of "
                        f"{sorted(CONFIGURATION_SCOPES)}"
                    )
            else:
                fail(
                    f"{item_path}.configuration_scope is required for "
                    "OpenTelemetry configuration"
                )
        elif "configuration_scope" in item:
            fail(
                f"{item_path}.configuration_scope is only valid when type is "
                "configuration"
            )
        telemetry_item = {
            "type": signal_type,
            "name": text(item.get("name"), f"{item_path}.name"),
            "attributes": string_list(item.get("attributes", []), f"{item_path}.attributes"),
            "product_view": text(item.get("product_view"), f"{item_path}.product_view"),
        }
        if configuration_scope is not None:
            telemetry_item["configuration_scope"] = configuration_scope
        telemetry.append(telemetry_item)
    if not telemetry:
        fail(f"{path}.expected_telemetry must contain at least one item")
    if not any(
        item["type"] in {"span", "metric", "log", "resource"} for item in telemetry
    ):
        fail(
            f"{path}.expected_telemetry must include a span, metric, log, or "
            "resource outcome; scoped configuration alone is insufficient for "
            "an OpenTelemetry finding"
        )
    if audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION:
        for index, item in enumerate(telemetry):
            item_path = f"{path}.expected_telemetry[{index}]"
            validate_otel_closure_text(
                item["name"], f"{item_path}.name", telemetry_output=True
            )
            validate_otel_closure_text(
                item["product_view"],
                f"{item_path}.product_view",
                telemetry_output=True,
            )
            for attribute_index, attribute in enumerate(item["attributes"]):
                validate_otel_closure_text(
                    attribute,
                    f"{item_path}.attributes[{attribute_index}]",
                    telemetry_output=True,
                )
    signal_types = {item["type"] for item in telemetry}
    has_configuration = "configuration" in signal_types
    if audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION:
        otel_concerns = [
            concern for concern in OTEL_CONCERN_ORDER if concern in set(otel_concerns)
        ]
    if (
        audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION
        and has_configuration
        and "otel-configuration" not in otel_concerns
    ):
        fail(
            f"{path}.otel_concerns must include otel-configuration when "
            "expected_telemetry contains configuration"
        )
    if (
        audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION
        and "otel-configuration" in otel_concerns
        and not has_configuration
    ):
        fail(
            f"{path}.otel_concerns includes otel-configuration but "
            "expected_telemetry has no configuration item"
        )
    if (
        audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION
        and "context-propagation" in otel_concerns
        and "span" not in signal_types
    ):
        fail(f"{path}.context-propagation closure requires a span outcome")
    if (
        audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION
        and "trace-log-correlation" in otel_concerns
        and "log" not in signal_types
    ):
        fail(f"{path}.trace-log-correlation closure requires a log outcome")
    if (
        audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION
        and {"semantic-attributes", "cardinality-safety"} & set(otel_concerns)
        and not any(item["attributes"] for item in telemetry)
    ):
        fail(
            f"{path}.semantic/cardinality closure requires at least one "
            "expected telemetry attribute"
        )
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
            require_expected_telemetry_reference(
                decision_question,
                f"{path}.decision_question",
                telemetry,
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
            require_expected_telemetry_reference(
                external_requirement,
                f"{path}.external_requirement",
                telemetry,
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
    if audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION and mode == "default":
        duplicate_contract = " ".join(
            (report["area"], report["gap"], report["required_fix"])
        ).lower()
        if any(term in duplicate_contract for term in ("duplicate", "overlap")) and not names_canonical_telemetry_owner(report["required_fix"]):
            fail(
                f"{path}.required_fix must name the canonical telemetry owner "
                "for default duplicate remediation or use manual decision"
            )
    if explicit_otel_concerns:
        report["otel_concerns"] = otel_concerns
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
    closure_values: list[tuple[str, str]] = [
        ("title", report["title"]),
        ("area", report["area"]),
        ("gap", report["gap"]),
        ("product_outcome", report["product_outcome"]),
        ("required_fix", report["required_fix"]),
    ]
    closure_values.extend(
        (f"acceptance_criteria[{index}]", value)
        for index, value in enumerate(report["acceptance_criteria"])
    )
    closure_values.extend(
        (f"follow_up_actions[{index}]", value)
        for index, value in enumerate(report["follow_up_actions"])
    )
    if decision_question is not None:
        closure_values.append(("decision_question", decision_question))
    for option_index, option in enumerate(decision_options):
        closure_values.append(
            (f"decision_options[{option_index}].outcome", option["outcome"])
        )
    if external_requirement is not None:
        closure_values.append(("external_requirement", external_requirement))
    if audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION:
        for field, value in closure_values:
            validate_otel_closure_text(
                value,
                f"{path}.{field}",
                audit_section=True,
            )
            if field.startswith("follow_up_actions["):
                validate_audit_review_next_step(value, f"{path}.{field}")
    if (
        audit_schema_version == CURRENT_AUDIT_SCHEMA_VERSION
        and "telemetry-proof" in otel_concerns
        and not report["verification_scenarios"]
    ):
        fail(f"{path}.telemetry-proof closure requires a verification scenario")
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

    signal_flow = as_object(data.get("signal_flow", {}), "signal_flow")
    component_flow_map = text(
        signal_flow.get("component_flow_map", ""),
        "signal_flow.component_flow_map",
        allow_empty=True,
    )
    if not component_flow_map.strip():
        component_flow_map = ""

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
            "component_flow_map": component_flow_map,
        },
        "current_instrumentation": {
            "spans": normalize_signal_rows(current.get("spans", []), "current_instrumentation.spans", ("name", "source", "type")),
            "metrics": normalize_signal_rows(current.get("metrics", []), "current_instrumentation.metrics", ("name", "source", "type")),
            "logs": normalize_signal_rows(current.get("logs", []), "current_instrumentation.logs", ("integration", "source", "detail")),
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
    if raw_flow:
        invalid_markers = sorted(
            marker
            for marker in FLOW_BRACKET.findall(raw_flow)
            if not FLOW_MARKER.fullmatch(marker)
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
            fail(
                "signal_flow gap markers reference undefined finding areas: "
                f"{unknown_flow_gaps}"
            )
        unmapped_findings = sorted(set(areas) - flow_gap_areas)
        if unmapped_findings:
            fail(
                "findings are not associated with a component-flow gap marker: "
                f"{unmapped_findings}"
            )
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
    if schema_version == CURRENT_SELECTION_SCHEMA_VERSION and "requested_ids" not in data:
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
            f"{path}.schema_version must be {CURRENT_SELECTION_SCHEMA_VERSION} "
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
    if schema_version == CURRENT_SELECTION_SCHEMA_VERSION:
        normalized["decision_answers"] = decision_answers
    return normalized


def normalize_telemetry_change(
    row: dict[str, Any],
    path: str,
    finding_id: str,
    expected_scenarios: list[str],
    expected_telemetry: list[dict[str, Any]],
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
    if change_kind in {"added", "modified"}:
        matching_expected = [
            item
            for item in expected_telemetry
            if item["type"] == signal_type and item["name"] == signal_name
        ]
        if not matching_expected:
            expected = [
                f"{item['type']} {item['name']}" for item in expected_telemetry
            ]
            fail(
                f"{path} must change an exact expected telemetry item from the "
                f"audit finding; expected one of {expected}"
            )
        expected_attributes = {
            attribute.strip()
            for item in matching_expected
            for attribute in item["attributes"]
        }
        actual_attributes = {
            attribute.strip()
            for attribute in added_attributes
        }
        unexpected_attributes = sorted(actual_attributes - expected_attributes)
        if unexpected_attributes:
            fail(
                f"{path}.added_attributes contains attributes not promised by "
                f"the audit finding: {unexpected_attributes}"
            )
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
    if signal_type == "metric" and not any(METRIC_PRODUCT_ACTION.search(action) for action in follow_up_actions):
        fail(f"{path}.follow_up_actions must name a chart, dashboard, detector, alert, or monitor")
    if added_attributes and not any(
        DIMENSION_PRODUCT_ACTION.search(action) for action in follow_up_actions
    ):
        fail(f"{path}.follow_up_actions must name the filter, slice, group-by, or breakdown enabled by added attributes")
    source = durable_artifact_text(text(row.get("source"), f"{path}.source"), f"{path}.source")
    change = text(row.get("change"), f"{path}.change")
    if GENERIC_TELEMETRY_CHANGE.search(change):
        fail(
            f"{path}.change must describe the concrete code/config behavior and "
            "telemetry correction; generic selected-contract wording is not allowed"
        )
    return {
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


def normalize_context_handoff(
    row: dict[str, Any],
    path: str,
    finding_id: str,
    expected_scenarios: list[str],
) -> dict[str, Any]:
    handoff_id = stable_id(row.get("id"), f"{path}.id")
    if not handoff_id.startswith(f"{finding_id}."):
        fail(f"{path}.id must start with {finding_id}.")
    producer = text(row.get("producer"), f"{path}.producer")
    consumer = text(row.get("consumer"), f"{path}.consumer")
    if normalized_words(producer) == normalized_words(consumer):
        fail(f"{path}.consumer must name a downstream component distinct from producer")
    keys = string_list(row.get("keys", []), f"{path}.keys")
    if len(keys) != len(set(keys)):
        fail(f"{path}.keys must not contain duplicates")
    verification_scenario = stable_id(
        row.get("verification_scenario"), f"{path}.verification_scenario"
    )
    if verification_scenario not in expected_scenarios:
        fail(
            f"{path}.verification_scenario must reference one of the finding's "
            f"audit scenarios: {expected_scenarios}"
        )
    return {
        "id": handoff_id,
        "producer": producer,
        "producer_source": durable_artifact_text(
            text(row.get("producer_source"), f"{path}.producer_source"),
            f"{path}.producer_source",
        ),
        "carrier": text(row.get("carrier"), f"{path}.carrier"),
        "keys": keys,
        "consumer": consumer,
        "consumer_source": durable_artifact_text(
            text(row.get("consumer_source"), f"{path}.consumer_source"),
            f"{path}.consumer_source",
        ),
        "verification_scenario": verification_scenario,
    }


def normalize_genai_closure(
    value: Any,
    report: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = object_list(value, "instrumentation.genai_closure")
    expected_rows = report["genai_readiness"]
    if not expected_rows:
        if rows:
            fail(
                "instrumentation.genai_closure is valid only when the audit "
                "declares GenAI ownership"
            )
        return []
    if len(rows) != len(expected_rows):
        fail(
            "instrumentation.genai_closure must contain exactly one row for every "
            "audit GenAI readiness surface"
        )

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, (row, expected) in enumerate(zip(rows, expected_rows, strict=True)):
        path = f"instrumentation.genai_closure[{index}]"
        surface = text(row.get("surface"), f"{path}.surface")
        if surface in seen:
            fail(f"duplicate instrumentation GenAI closure surface: {surface}")
        seen.add(surface)
        if surface != expected["surface"]:
            fail(
                "instrumentation.genai_closure surfaces must match the audit in "
                f"source order; expected {expected['surface']}, got {surface}"
            )
        required_signals = text(
            row.get("required_signals"), f"{path}.required_signals"
        )
        if required_signals != expected["required_signals"]:
            fail(f"{path}.required_signals must exactly match the audit surface")
        owner = text(row.get("owner"), f"{path}.owner")
        if owner != expected["owner"]:
            fail(f"{path}.owner must exactly match the audit surface owner")
        status = text(row.get("status"), f"{path}.status")
        if status not in GENAI_CLOSURE_STATUSES:
            fail(
                f"{path}.status must be one of "
                f"{sorted(GENAI_CLOSURE_STATUSES)}"
            )
        implemented_proven = string_list(
            row.get("implemented_proven", []), f"{path}.implemented_proven"
        )
        tests = string_list(row.get("tests", []), f"{path}.tests")
        evidence = durable_artifact_list(
            row.get("evidence", []), f"{path}.evidence"
        )
        remaining_signals = string_list(
            row.get("remaining_signals", []), f"{path}.remaining_signals"
        )
        if status == "working" and (
            not implemented_proven
            or not tests
            or not evidence
            or remaining_signals
        ):
            fail(
                f"working GenAI closure surface {surface} requires implemented/proven "
                "signals, executed tests, durable evidence, and no remaining signals"
            )
        if status != "working" and not remaining_signals:
            fail(
                f"non-working GenAI closure surface {surface} must name remaining "
                "signals or its exact owner/prerequisite"
            )
        normalized.append(
            {
                "surface": surface,
                "required_signals": required_signals,
                "owner": owner,
                "implemented_proven": implemented_proven,
                "tests": tests,
                "evidence": evidence,
                "remaining_signals": remaining_signals,
                "status": status,
            }
        )
    return normalized


def normalize_instrumentation(data: dict[str, Any], report: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
    if data.get("schema_version") != OVERLAY_SCHEMA_VERSION or data.get("kind") != "otel-instrumentation":
        fail("instrumentation must have schema_version 1 and kind otel-instrumentation")
    meta = as_object(data.get("meta"), "instrumentation.meta")
    result = text(meta.get("result"), "instrumentation.meta.result")
    if result not in RESULT_STATUSES:
        fail(f"instrumentation.meta.result must be one of {sorted(RESULT_STATUSES)}")
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
        audit_finding = audit_findings.get(finding_id, {})
        expected_scenarios = audit_finding.get("verification_scenarios", [])
        telemetry_changes = [
            normalize_telemetry_change(
                item,
                f"{row_path}.telemetry_changes[{item_index}]",
                finding_id,
                expected_scenarios,
                audit_finding.get("expected_telemetry", []),
            )
            for item_index, item in enumerate(
                object_list(row.get("telemetry_changes", []), f"{row_path}.telemetry_changes")
            )
        ]
        context_handoffs = [
            normalize_context_handoff(
                item,
                f"{row_path}.context_handoffs[{handoff_index}]",
                finding_id,
                expected_scenarios,
            )
            for handoff_index, item in enumerate(
                object_list(
                    row.get("context_handoffs", []),
                    f"{row_path}.context_handoffs",
                )
            )
        ]
        handoff_ids = [item["id"] for item in context_handoffs]
        if len(handoff_ids) != len(set(handoff_ids)):
            fail(f"{row_path}.context_handoffs must not contain duplicate IDs")
        requires_context_handoffs = (
            "context-propagation" in audit_finding.get("otel_concerns", [])
        )
        if requires_context_handoffs and not context_handoffs:
            fail(
                f"{row_path}.context_handoffs must inventory every source "
                "producer-to-consumer edge for a context-propagation finding"
            )
        if context_handoffs and not requires_context_handoffs:
            fail(
                f"{row_path}.context_handoffs is valid only when the audit "
                "finding declares context-propagation"
            )
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
        normalized_row = {
            "id": finding_id,
            "status": status,
            "changes": changes,
            "telemetry_changes": telemetry_changes,
            "tests": tests,
            "evidence": evidence,
            "follow_up_actions": non_empty_string_list(
                row.get("follow_up_actions", []), f"{row_path}.follow_up_actions"
            ),
            "resolved_commit": optional_text(
                row.get("resolved_commit"), f"{row_path}.resolved_commit"
            ),
        }
        if context_handoffs:
            normalized_row["context_handoffs"] = context_handoffs
        rows.append(normalized_row)
    approved = selection["approved_ids"]
    if [row["id"] for row in rows] != approved:
        fail(f"instrumentation finding IDs must exactly match dependency-closed selected audit order {approved}")
    genai_closure = normalize_genai_closure(
        data.get("genai_closure", []), report
    )
    failed_rows = [row for row in rows if row["status"] == "not_working"]
    failed_genai = [
        row for row in genai_closure if row["status"] == "not_working"
    ]
    if (failed_rows or failed_genai) and result != "Fail":
        fail(
            "instrumentation.meta.result must be Fail when any selected finding "
            "or GenAI closure surface is not_working"
        )
    if result == "Fail" and not (failed_rows or failed_genai):
        fail(
            "instrumentation.meta.result Fail requires at least one not_working "
            "finding or GenAI closure surface"
        )
    selected_complete = all(row["status"] == "working" for row in rows)
    genai_complete = all(
        row["status"] in GENAI_PASS_STATUSES for row in genai_closure
    )
    has_scope = bool(rows or genai_closure)
    if result == "Pass" and not (selected_complete and genai_complete):
        fail(
            "instrumentation.meta.result Pass requires every selected finding to "
            "be working and every GenAI closure surface to be working, deferred, "
            "or owner_mapped"
        )
    if has_scope and selected_complete and genai_complete and result != "Pass":
        fail(
            "instrumentation.meta.result must be Pass when every selected finding "
            "and GenAI closure surface is complete"
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
    if report["meta"]["genai_ownership_detected"]:
        normalized["genai_closure"] = genai_closure
    return normalized


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
    workflow_mode = text(
        meta.get("workflow_mode", "standalone"), "verify.meta.workflow_mode"
    )
    if workflow_mode not in VERIFY_WORKFLOW_MODES:
        fail(
            f"verify.meta.workflow_mode must be one of "
            f"{sorted(VERIFY_WORKFLOW_MODES)}"
        )
    lifecycle = text(meta.get("lifecycle", "final"), "verify.meta.lifecycle")
    if lifecycle not in VERIFY_LIFECYCLES:
        fail(
            f"verify.meta.lifecycle must be one of {sorted(VERIFY_LIFECYCLES)}"
        )
    raw_stop_boundaries = object_list(
        data.get("stop_boundaries", []), "verify.stop_boundaries"
    )
    if raw_stop_boundaries and not (
        workflow_mode == "instrumentation_child"
        and result == "Fail"
        and lifecycle == "intermediate"
    ):
        fail(
            "verify.stop_boundaries is allowed only for an instrumentation_child "
            "overlay with result Fail and lifecycle intermediate"
        )
    if raw_stop_boundaries and instrumentation["meta"]["result"] != "Fail":
        fail(
            "verify.stop_boundaries requires the bound instrumentation "
            "meta.result to be Fail"
        )
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
    expected_context_handoffs_by_finding = {
        finding["id"]: finding.get("context_handoffs", [])
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
        expected_context_handoffs = expected_context_handoffs_by_finding.get(
            finding_id, []
        )
        context_handoffs_by_id = {
            handoff["id"]: handoff for handoff in expected_context_handoffs
        }
        seen_context_handoff_ids: set[str] = set()
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
            context_propagation_proof = []
            for proof_index, proof in enumerate(
                object_list(
                    scenario.get("context_propagation_proof", []),
                    f"{scenario_path}.context_propagation_proof",
                )
            ):
                proof_path = (
                    f"{scenario_path}.context_propagation_proof[{proof_index}]"
                )
                handoff_id = stable_id(
                    proof.get("handoff_id"), f"{proof_path}.handoff_id"
                )
                expected_handoff = context_handoffs_by_id.get(handoff_id)
                if expected_handoff is None:
                    fail(
                        f"{proof_path}.handoff_id {handoff_id} is not present in "
                        "the bound instrumentation context_handoffs"
                    )
                if handoff_id in seen_context_handoff_ids:
                    fail(
                        f"context handoff {handoff_id} must be proven at most "
                        "once per finding"
                    )
                if expected_handoff["verification_scenario"] != scenario_id:
                    fail(
                        f"{proof_path}.handoff_id {handoff_id} must be proven by "
                        f"scenario {expected_handoff['verification_scenario']}"
                    )
                seen_context_handoff_ids.add(handoff_id)
                same_trace_assertion_passed = proof.get(
                    "same_trace_assertion_passed"
                )
                relationship_assertion_passed = proof.get(
                    "relationship_assertion_passed"
                )
                if not isinstance(same_trace_assertion_passed, bool):
                    fail(
                        f"{proof_path}.same_trace_assertion_passed must be a boolean"
                    )
                if not isinstance(relationship_assertion_passed, bool):
                    fail(
                        f"{proof_path}.relationship_assertion_passed must be a boolean"
                    )
                context_propagation_proof.append(
                    {
                        "handoff_id": handoff_id,
                        "same_trace_assertion_passed": (
                            same_trace_assertion_passed
                        ),
                        "relationship_assertion_passed": (
                            relationship_assertion_passed
                        ),
                    }
                )
            if context_propagation_proof and proof_mode not in ITEM_DIRECT_PROOF_MODES:
                fail(
                    f"{scenario_path}.context_propagation_proof requires a direct "
                    f"execution proof mode: {sorted(ITEM_DIRECT_PROOF_MODES)}"
                )
            failed_context_proof = any(
                not proof["same_trace_assertion_passed"]
                or not proof["relationship_assertion_passed"]
                for proof in context_propagation_proof
            )
            if failed_context_proof and scenario_status != "not_working":
                fail(
                    f"{scenario_path}.status must be not_working when a context "
                    "propagation relationship assertion failed"
                )
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
            expected_scenario_handoff_ids = [
                handoff["id"]
                for handoff in expected_context_handoffs
                if handoff["verification_scenario"] == scenario_id
            ]
            actual_scenario_handoff_ids = [
                proof["handoff_id"] for proof in context_propagation_proof
            ]
            if (
                scenario_status == "working"
                and actual_scenario_handoff_ids != expected_scenario_handoff_ids
            ):
                fail(
                    f"working scenario {scenario_id} must prove mapped context "
                    f"handoffs in instrumentation order: "
                    f"{expected_scenario_handoff_ids}"
                )
            if scenario_status in {"working", "not_working"}:
                require_exact_expected_telemetry_reference(
                    "\n".join(observed_telemetry),
                    f"{scenario_path}.observed_telemetry",
                    audit_findings_by_id[finding_id]["expected_telemetry"],
                    "positive" if scenario_status == "working" else "negative",
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
            if context_propagation_proof:
                normalized_scenario["context_propagation_proof"] = (
                    context_propagation_proof
                )
            scenarios.append(normalized_scenario)
        if status == "working":
            expected_context_handoff_ids = [
                handoff["id"] for handoff in expected_context_handoffs
            ]
            if seen_context_handoff_ids != set(expected_context_handoff_ids):
                missing_context_handoff_ids = [
                    handoff_id
                    for handoff_id in expected_context_handoff_ids
                    if handoff_id not in seen_context_handoff_ids
                ]
                if missing_context_handoff_ids:
                    fail(
                        f"working verify finding {finding_id} is missing context "
                        f"handoff proof for {missing_context_handoff_ids}"
                    )
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
    if lifecycle == "intermediate" and result != "Fail":
        fail(
            "verify.meta.lifecycle intermediate is reserved for a failed child "
            "repair packet"
        )
    if (
        workflow_mode == "instrumentation_child"
        and result == "Fail"
        and lifecycle != "intermediate"
    ):
        fail(
            "failed instrumentation-child verification must be intermediate; "
            "the parent repair loop cannot finalize it"
        )
    failed_id_order = {row["id"]: index for index, row in enumerate(failed_rows)}
    stop_boundaries: list[dict[str, Any]] = []
    for boundary_index, boundary in enumerate(raw_stop_boundaries):
        boundary_path = f"verify.stop_boundaries[{boundary_index}]"
        finding_ids = [
            stable_id(
                value,
                f"{boundary_path}.finding_ids[{finding_index}]",
            )
            for finding_index, value in enumerate(
                as_list(
                    boundary.get("finding_ids"),
                    f"{boundary_path}.finding_ids",
                )
            )
        ]
        if not finding_ids:
            fail(f"{boundary_path}.finding_ids must not be empty")
        if len(finding_ids) != len(set(finding_ids)):
            fail(f"{boundary_path}.finding_ids must not contain duplicates")
        unknown_failed_ids = [
            finding_id
            for finding_id in finding_ids
            if finding_id not in failed_id_order
        ]
        if unknown_failed_ids:
            fail(
                f"{boundary_path}.finding_ids must reference only failed "
                f"verify findings: {unknown_failed_ids}"
            )
        kind = text(boundary.get("kind"), f"{boundary_path}.kind")
        if kind not in STOP_BOUNDARY_KINDS:
            fail(
                f"{boundary_path}.kind must be one of "
                f"{sorted(STOP_BOUNDARY_KINDS)}"
            )
        reason = text(boundary.get("reason"), f"{boundary_path}.reason").strip()
        if IMPERATIVE_STOP_BOUNDARY_REASON.match(reason):
            fail(
                f"{boundary_path}.reason must state the observed boundary "
                "declaratively, not as an action"
            )
        required_action = text(
            boundary.get("required_action"), f"{boundary_path}.required_action"
        ).strip()
        evidence = durable_artifact_list(
            boundary.get("evidence", []), f"{boundary_path}.evidence"
        )
        if not evidence:
            fail(f"{boundary_path}.evidence must contain durable evidence")
        stop_boundaries.append(
            {
                "finding_ids": sorted(
                    finding_ids, key=failed_id_order.__getitem__
                ),
                "kind": kind,
                "reason": reason,
                "required_action": required_action,
                "evidence": evidence,
            }
        )
    if stop_boundaries:
        instrumentation_findings_by_id = {
            row["id"]: row for row in instrumentation["findings"]
        }
        non_failed_instrumentation_ids = sorted(
            {
                finding_id
                for boundary in stop_boundaries
                for finding_id in boundary["finding_ids"]
                if instrumentation_findings_by_id[finding_id]["status"]
                != "not_working"
            },
            key=failed_id_order.__getitem__,
        )
        if non_failed_instrumentation_ids:
            fail(
                "verify.stop_boundaries finding_ids require matching bound "
                "instrumentation findings with status not_working: "
                f"{non_failed_instrumentation_ids}"
            )
        covered_failed_ids = {
            finding_id
            for boundary in stop_boundaries
            for finding_id in boundary["finding_ids"]
        }
        missing_failed_ids = [
            row["id"] for row in failed_rows if row["id"] not in covered_failed_ids
        ]
        if missing_failed_ids:
            fail(
                "verify.stop_boundaries must identify every failed finding when a "
                f"stopped child boundary is recorded: {missing_failed_ids}"
            )
        rows_by_id = {row["id"]: row for row in rows}
        for boundary_index, boundary in enumerate(stop_boundaries):
            normalized_required_action = normalized_action_words(
                boundary["required_action"]
            )
            duplicated_locations: list[str] = []
            for finding_id in boundary["finding_ids"]:
                for remaining_index, action in enumerate(
                    rows_by_id[finding_id]["remaining"]
                ):
                    normalized_action = normalized_action_words(action)
                    if (
                        f" {normalized_required_action} "
                        in f" {normalized_action} "
                        or f" {normalized_action} "
                        in f" {normalized_required_action} "
                    ):
                        duplicated_locations.append(
                            f"verify.findings[{finding_id}].remaining"
                            f"[{remaining_index}]"
                        )
            for next_step_index, action in enumerate(next_steps):
                normalized_action = normalized_action_words(action)
                if (
                    f" {normalized_required_action} "
                    in f" {normalized_action} "
                    or f" {normalized_action} "
                    in f" {normalized_required_action} "
                ):
                    duplicated_locations.append(
                        f"verify.next_steps[{next_step_index}]"
                    )
            if duplicated_locations:
                fail(
                    f"verify.stop_boundaries[{boundary_index}].required_action "
                    "must remain only in stop_boundaries and cannot be duplicated "
                    "as an application code/config repair in "
                    f"{duplicated_locations}"
                )
        stop_boundaries.sort(
            key=lambda boundary: (
                min(
                    failed_id_order[finding_id]
                    for finding_id in boundary["finding_ids"]
                ),
                boundary["kind"],
                boundary["reason"],
            )
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
            "workflow_mode": workflow_mode,
            "lifecycle": lifecycle,
        },
        "findings": rows,
        "next_steps": next_steps,
    }
    if stop_boundaries:
        normalized["stop_boundaries"] = stop_boundaries
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


def md_cell(value: Any) -> str:
    if isinstance(value, list):
        value = "<br>".join(str(item) for item in value)
    return str(value).replace("|", r"\|").replace("\n", "<br>")


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    lines.extend("| " + " | ".join(md_cell(cell) for cell in row) + " |" for row in rows)
    return "\n".join(lines)


def md_bullets(items: list[str], empty: str = "None.") -> str:
    return "\n".join(f"- {item}" for item in items) if items else empty


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


def render_telemetry_proof_table(
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
            f'<th scope="row">{esc(telemetry_change_reader_label(item))}</th>'
            f'<td>{esc(observed)}</td>'
            f'<td><strong class="proof-status proof-status-{esc(result["status"])}">'
            f'{esc(status)}</strong></td>'
            "</tr>"
        )
    if not rows:
        return (
            '<p class="muted">No application telemetry change was created for this '
            "selected issue.</p>"
        )
    return (
        '<div class="telemetry-proof-table"><table>'
        '<caption class="sr-only">Proof status for telemetry changes</caption>'
        '<thead><tr><th>Telemetry change</th><th>What was observed</th><th>Status</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
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
    item_table = render_telemetry_proof_table(implementation, proof)
    coverage = render_coverage_details(proof, audit_scenarios)
    return (
        '<section class="finding-proof">'
        f'<h4>{esc(heading)}</h4>'
        f'{summary_html}{blocked_summary}'
        f'{item_table}{coverage}'
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
    elif counts["items_otlp_accepted"]:
        delivery_sentence = (
            "Local OTLP delivery was checked; Splunk Observability Cloud was not checked."
        )
    else:
        delivery_sentence = (
            "Local OTLP delivery and Splunk Observability Cloud were not checked."
        )
    return (
        f'<h2 id="instrumentation-status-heading" class="status-heading">{esc(heading)}</h2>'
        f'<p><strong>Overall result: {esc(aggregate_result)}.</strong> '
        f'{esc(proof_sentence)} {esc(delivery_sentence)}</p>'
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
                '<tr>'
                f'<td><code>{esc(item["id"])}</code></td>'
                f'<td><strong>{esc(human_item_proof_status(item))}</strong><br>'
                f'<span class="muted">{esc(human_proof_mode(item["proof_mode"]))} · '
                f'{esc(human_visibility(item["visibility"]))}</span></td>'
                f'<td>{esc(observed or "None observed")}</td>'
                f'<td>{esc(reader_prose("; ".join(item["product_validation"])) or "No product validation")}</td>'
                f'<td>{evidence}</td>'
                '</tr>'
            )
    return (
        '<details><summary>Scenario proof</summary><div class="table-wrap"><table><thead><tr>'
        '<th>Finding / scenario</th><th>Status</th><th>Observed telemetry</th><th>Product check</th><th>Evidence</th>'
        f'</tr></thead><tbody>{"".join(scenario_rows)}</tbody></table></div></details>'
        '<details><summary>Item-level proof</summary><div class="table-wrap"><table><thead><tr>'
        '<th>Telemetry item</th><th>Status</th><th>Observed telemetry</th><th>Product check</th><th>Evidence</th>'
        f'</tr></thead><tbody>{"".join(item_rows)}</tbody></table></div></details>'
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


def render_stop_boundaries(verify: dict[str, Any] | None) -> str:
    if verify is None or not verify.get("stop_boundaries"):
        return ""
    kind_labels = {
        "unselected_work": "Unselected work",
        "material_decision": "Material decision",
        "new_authority": "New authority",
        "external_prerequisite": "External prerequisite",
    }
    rows = []
    for boundary in verify["stop_boundaries"]:
        affected = ", ".join(
            f'<a class="finding-jump" href="#selected-{esc(finding_id)}">'
            f'<code>{esc(finding_id)}</code></a>'
            for finding_id in boundary["finding_ids"]
        )
        rows.append(
            '<article class="stop-boundary">'
            f'<h3>{esc(kind_labels[boundary["kind"]])}</h3>'
            f'<p><strong>Affected failed findings:</strong> {affected}</p>'
            f'<p><strong>Why instrumentation stopped:</strong> '
            f'{esc(reader_prose(boundary["reason"]))}</p>'
            '<p><strong>Required action outside the instrumentation repair '
            f'scope:</strong> {esc(reader_prose(boundary["required_action"]))}</p>'
            '<div><strong>Durable evidence:</strong>'
            f'{render_list(boundary["evidence"])}</div>'
            '</article>'
        )
    return (
        '<section class="panel stop-boundaries" '
        'aria-labelledby="stop-boundaries-heading">'
        '<h2 id="stop-boundaries-heading">Why the repair loop stopped</h2>'
        '<p class="review-note">The executed verification failures remain recorded. '
        'Instrumentation cannot safely continue until the boundary action below is '
        'completed; it is not another application code/config repair.</p>'
        f'<div class="stop-boundary-list">{"".join(rows)}</div>'
        '</section>'
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
    stop_boundaries = render_stop_boundaries(verify)
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
    verify_link = '<a href="otel-verify.json">Verification JSON</a>' if verify else '<span>Verification not run</span>'
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
.finding-proof {{ background:#fff; border:1px solid var(--line); border-radius:7px; display:grid; gap:8px; grid-template-columns:1fr 1fr; margin-top:10px; padding:10px; }}
.finding-proof > h4 {{ color:var(--muted); font-size:12px; grid-column:1/-1; letter-spacing:.06em; margin:0; text-transform:uppercase; }}
.proof-summary,.blocked-proof-summary,.telemetry-proof-table,.coverage-details {{ grid-column:1/-1; }}
.proof-summary {{ margin:0; }}
.blocked-proof-summary {{ background:#fff9ec; border-left:3px solid #b7791f; border-radius:4px; display:grid; gap:6px; padding:9px 11px; }}
.blocked-proof-summary > strong,.blocked-proof-summary div > strong {{ display:block; margin-bottom:3px; }}
.blocked-proof-summary ul {{ margin:3px 0 0; }}
.telemetry-proof-table {{ overflow-x:auto; }}
.telemetry-proof-table th[scope="row"] {{ color:var(--ink); font-size:13px; min-width:180px; }}
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
@media (max-width:760px) {{ .selected-issue-grid,.finding-proof,.coverage-detail-body {{ grid-template-columns:1fr; }} .finding-proof > h4,.proof-summary,.telemetry-proof-table,.coverage-details {{ grid-column:1; }} }}
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
    <a href="otel-instrumentation.json">Instrumentation JSON</a>
    {verify_link}
  </nav>
</div></header>
<main class="wrap">
  <section class="summary" aria-labelledby="instrumentation-status-heading">{summary}</section>
  {stop_boundaries}
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
    payload = json.dumps(
        {
            "report": report,
            "selection": selection,
            "selection_eligibility": selection_eligibility,
            "display_finding_ids": display_finding_ids(report),
            "source_references": source_references,
        },
        separators=(",", ":"),
    ).replace("</", "<\\/")
    mode_guidance_payload = json.dumps(MODE_GUIDANCE, separators=(",", ":"))
    title = esc(report["meta"]["service_name"])
    findings = report["findings"]
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
    readiness_sections: list[str] = []
    incident_readiness = report["current_instrumentation"]["incident_readiness"]
    if incident_readiness:
        incident_table = html_table(
            ["Area", "Status", "Evidence", "Required signals / gap", "Detection / localization impact"],
            [
                [row["area"], row["status"], row["evidence"], row["required_signals"], row["impact"]]
                for row in incident_readiness
            ],
            source_columns={2},
            source_references=source_references,
        )
        readiness_sections.append(
            '<section class="panel readiness-panel" aria-labelledby="incident-readiness-heading">'
            '<h2 id="incident-readiness-heading">Incident telemetry readiness</h2>'
            f"{incident_table}</section>"
        )
    if report["genai_readiness"]:
        genai_table = html_table(
            ["Surface", "Status", "Evidence", "Required signals", "Owner / source", "Acceptance", "Detection / localization impact"],
            [
                [
                    row["surface"],
                    row["status"],
                    row["evidence"],
                    row["required_signals"],
                    row["owner"],
                    row["acceptance_criteria"],
                    row["impact"],
                ]
                for row in report["genai_readiness"]
            ],
            source_columns={2, 4},
            source_references=source_references,
        )
        readiness_sections.append(
            '<section class="panel readiness-panel" aria-labelledby="genai-readiness-heading">'
            '<h2 id="genai-readiness-heading">GenAI telemetry readiness</h2>'
            f"{genai_table}</section>"
        )
    readiness_html = "".join(readiness_sections)
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
h3 {{ margin: 0 0 6px; font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .1em; }}
p {{ margin: 0 0 12px; }}
ul {{ margin: 0; padding-left: 18px; }}
code, pre {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
.source-link {{ color: var(--accent); text-decoration: none; overflow-wrap: anywhere; }}
.source-link:hover, .source-link:focus {{ text-decoration: underline; }}
.source-link code {{ color: inherit; }}
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
.tray-bar {{ display: grid; grid-template-columns: minmax(230px, 1fr) minmax(280px, 1.2fr) max-content; gap: 18px; align-items: center; padding-top: 12px; padding-bottom: 12px; }}
.tray-summary {{ min-width: 0; }}
.tray-summary strong {{ display: block; font-size: 14px; line-height: 1.35; }}
.tray-hint {{ display: block; color: #d3d9e2; font-size: 11px; line-height: 1.4; margin-top: 3px; }}
.tray-hint code {{ color: #91f0b8; }}
.tray-command {{ min-width: 0; }}
.instrument-command {{ display: block; margin-top: 4px; max-width: 100%; overflow-x: auto; white-space: nowrap; background: #0b111a; border: 1px solid #253143; border-radius: 6px; color: #91f0b8; padding: 7px 9px; user-select: all; }}
.tray button {{ border-radius: 6px; padding: 9px 13px; font-weight: 700; cursor: pointer; }}
.tray button.primary {{ background: var(--ok); color: #fff; border: 1px solid var(--ok); }}
.tray button:hover {{ filter: brightness(1.08); }}
.tray button:disabled {{ cursor: not-allowed; filter: none; opacity: .5; }}
.sr-only {{ position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }}
@media (max-width: 760px) {{
  body {{ padding-bottom: 124px; }}
  .context-grid {{ grid-template-columns: 1fr; }}
  .tray-bar {{ grid-template-columns: 1fr; gap: 9px; }}
  .tray-summary {{ width: 100%; }}
  .tray-bar > button {{ width: 100%; }}
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
    <nav class="report-nav" aria-label="Report data">
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
  </section>
{readiness_html}
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
    <div class="tray-summary">
      <strong id="planSummary"></strong>
      <span class="tray-hint" id="saveSelectionHint">Save a selected audit copy as <code>.observe/otel-audit.selected.json</code> before running <code>$otel-instrument</code>. The canonical audit remains unchanged. If your browser downloads the copy instead, <code>$otel-instrument</code> can adopt it after validation when no repository selection already exists.</span>
    </div>
    <div class="tray-command" aria-labelledby="instrumentCommandLabel">
      <span class="tray-hint" id="instrumentCommandLabel">Copy/paste terminal fallback when saving is unreliable:</span>
      <code class="instrument-command" id="instrumentCommand"></code>
    </div>
    <button id="saveSelection" class="primary" type="button" aria-describedby="saveSelectionHint">Save selection</button>
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
  return parts.map(part => part.href
    ? `<a class="source-link" href="${{esc(part.href)}}" target="_blank" rel="noopener" title="Open local source file"><code>${{esc(part.text)}}</code><span class="source-open" aria-hidden="true">↗</span></a>`
    : esc(part.text)
  ).join("");
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
      ? "Review the executable work unlocked by this answer and select the work you want to save."
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
    return "This finding is selected. Save the selection, then run $otel-instrument.";
  }}
  if (selected.has(finding.id)) {{
    return "This finding is included because selected work depends on it. Save the selection, then run $otel-instrument.";
  }}
  return "Select this finding, then save the selection before running $otel-instrument.";
}}

function renderCards() {{
  document.getElementById("cards").innerHTML = DISPLAY_FINDINGS.map(f => {{
    const lifecycle = lifecycleStatus(f);
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
          <section><h3>Gap</h3><p>${{esc(f.gap)}}</p></section>
          <section><h3>Why it matters</h3><p>${{esc(f.impact)}}</p></section>
          <section><h3>${{esc(primaryActionLabel)}}</h3><p>${{esc(requiredAction)}}</p></section>
          <section><h3>Next step</h3><p data-finding-next-step="${{esc(f.id)}}">${{esc(findingNextStep(f))}}</p></section>
        </div>
        <details class="finding-technical-details">
          <summary><span>Technical details</span> <span class="detail-counts">${{esc(contractCounts)}}</span></summary>
          <div class="technical-details-body">
            <section><h3>Expected telemetry</h3>${{telemetry ? `<ul>${{telemetry}}</ul>` : `<p class="muted">None recorded.</p>`}}</section>
            <section><h3>Acceptance criteria</h3><ul>${{acceptance}}</ul></section>
            ${{constraints ? `<section><h3>Implementation guardrails</h3><ul>${{constraints}}</ul></section>` : ""}}
            <section><h3>Evidence</h3>${{evidence ? `<ul>${{evidence}}</ul>` : `<p class="muted">None recorded.</p>`}}</section>
          </div>
        </details>
      </div>
    </article>`;
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

function plural(count, singular, pluralForm) {{
  return count === 1 ? singular : (pluralForm || singular + "s");
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
  return "<service-root>";
}}

function terminalInstrumentCommand() {{
  const ids = orderedRequested();
  if (!ids.length) {{
    return "Select at least one executable finding to generate an instrumentation command.";
  }}
  const parts = ["$otel-instrument", "--ids", ids.join(",")];
  for (const answer of orderedDecisionAnswers()) {{
    parts.push("--decision", `${{answer.finding_id}}=${{answer.option_id}}`);
  }}
  parts.push(serviceRootFromLocation());
  return parts.map((part, index) => index === 0 ? part : commandPart(part)).join(" ");
}}

function renderInstrumentCommand() {{
  const node = document.getElementById("instrumentCommand");
  if (node) node.textContent = terminalInstrumentCommand();
}}

function renderTray() {{
  const requestedIds = orderedRequested();
  const inPlanIds = orderedSelection();
  const autoAddedIds = inPlanIds.filter(id => !requested.has(id));
  const hasSelection = requestedIds.length > 0 || decisionAnswers.size > 0;
  const tray = document.getElementById("tray");
  tray.hidden = !hasSelection;
  tray.toggleAttribute("inert", !hasSelection);
  tray.setAttribute("aria-hidden", String(!hasSelection));
  const summaryParts = [inPlanIds.length + " in selection"];
  if (autoAddedIds.length) {{
    summaryParts.push(autoAddedIds.length + " auto-added " + plural(autoAddedIds.length, "dependency", "dependencies"));
  }}
  if (decisionAnswers.size) {{
    summaryParts.push(decisionAnswers.size + " " + plural(decisionAnswers.size, "decision answer", "decision answers"));
  }}
  document.getElementById("planSummary").textContent = hasSelection ? summaryParts.join(" · ") : "";
  document.getElementById("saveSelection").disabled = !hasSelection;
  renderInstrumentCommand();
}}

function selectionDocument() {{
  const answers = orderedDecisionAnswers();
  const document = {{schema_version: answers.length ? 2 : 1, kind: "otel-selection", audit_id: REPORT.meta.audit_id, audit_sha256: DATA.selection.audit_sha256, requested_ids: orderedRequested(), approved_ids: orderedSelection(), approved_by: null, approved_at: null}};
  if (answers.length) document.decision_answers = answers;
  return document;
}}

function auditReviewDocument() {{
  const document = JSON.parse(JSON.stringify(REPORT));
  document.review_selection = selectionDocument();
  return document;
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
  const decisionInput = event.target.closest("input[data-decision-id][data-option-id]");
  if (decisionInput) {{
    applyDecisionAnswer(decisionInput.dataset.decisionId, decisionInput.dataset.optionId);
    return;
  }}
  const input = event.target.closest("input[data-id]");
  if (!input) return;
  applySelectionInput(input);
}});

async function saveSelectionOverlay() {{
  const contents = JSON.stringify(auditReviewDocument(), null, 2) + "\\n";
  const dependencyCount = orderedSelection().filter(id => !requested.has(id)).length;
  const dependencyMessage = dependencyCount
    ? ` It includes ${{dependencyCount}} auto-added ${{plural(dependencyCount, "dependency", "dependencies")}}.`
    : "";
  if (window.showSaveFilePicker) {{
    try {{
      const handle = await window.showSaveFilePicker({{
        suggestedName: "otel-audit.selected.json",
        types: [{{description: "OpenTelemetry audit JSON with saved selection", accept: {{"application/json": [".json"]}}}}],
      }});
      if (handle.name === "otel-audit.json") {{
        announceSelection("The canonical otel-audit.json is immutable. Choose otel-audit.selected.json or another new selected-audit filename.");
        return;
      }}
      const existingFile = await handle.getFile();
      if (existingFile.size) {{
        let existingDocument;
        try {{
          existingDocument = JSON.parse(await existingFile.text());
        }} catch (error) {{
          announceSelection("The chosen file already exists and is not a valid selected audit. Choose a new otel-audit.selected.json file.");
          return;
        }}
        const existingSelection = existingDocument?.review_selection;
        const sameAudit = existingDocument?.kind === "otel-audit"
          && existingDocument?.meta?.audit_id === REPORT.meta.audit_id
          && existingSelection?.audit_sha256 === DATA.selection.audit_sha256;
        if (!sameAudit) {{
          announceSelection("The chosen file belongs to a different or newer audit. Choose a new otel-audit.selected.json file.");
          return;
        }}
      }}
      const writable = await handle.createWritable();
      await writable.write(contents);
      await writable.close();
      announceSelection("Selected audit copy saved." + dependencyMessage + " Keep it in .observe before running $otel-instrument.");
      return;
    }} catch (error) {{
      if (error && error.name === "AbortError") {{
        announceSelection("Audit selection save cancelled.");
        return;
      }}
      console.warn("Direct audit-state save failed; falling back to browser download.", error);
    }}
  }}
  const blob = new Blob([contents], {{type:"application/json"}});
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "otel-audit.selected.json";
  link.hidden = true;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 0);
  announceSelection("Selected audit download fallback started." + dependencyMessage + " $otel-instrument can adopt it after validation when no repository selection already exists.");
}}

document.getElementById("saveSelection").addEventListener("click", () => {{
  saveSelectionOverlay();
}});

syncDependencyClosure();
renderCards();
renderTray();
revealCurrentHash();
window.addEventListener("hashchange", revealCurrentHash);
</script>
</body>
</html>
"""


def directory_identity(descriptor: int) -> tuple[int, int]:
    status = os.fstat(descriptor)
    return status.st_dev, status.st_ino


def output_directory_matches(
    boundary: Path,
    relative_parts: tuple[str, ...],
    boundary_identity: tuple[int, int],
    parent_identity: tuple[int, int],
) -> bool:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(boundary, flags)
    except OSError:
        return False
    try:
        if directory_identity(descriptor) != boundary_identity:
            return False
        for component in relative_parts:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return directory_identity(descriptor) == parent_identity
    except OSError:
        return False
    finally:
        os.close(descriptor)


def open_output_parent(
    path: Path,
) -> tuple[int, Path, tuple[str, ...], tuple[int, int], tuple[int, int]]:
    path = Path(os.path.abspath(path))
    parent = path.parent
    boundary = parent
    while not os.path.lexists(boundary):
        next_boundary = boundary.parent
        if next_boundary == boundary:
            fail(f"could not find an existing output boundary for {path}")
        boundary = next_boundary
    relative_parts = parent.relative_to(boundary).parts
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(boundary, flags)
    boundary_identity = directory_identity(descriptor)
    try:
        for component in relative_parts:
            try:
                next_descriptor = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                try:
                    os.mkdir(component, mode=0o755, dir_fd=descriptor)
                except FileExistsError:
                    pass
                next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return (
            descriptor,
            boundary,
            relative_parts,
            boundary_identity,
            directory_identity(descriptor),
        )
    except BaseException:
        os.close(descriptor)
        raise


def descriptor_atomic_writes_supported() -> bool:
    # CPython does not advertise os.replace in supports_dir_fd on every POSIX
    # platform where its signature happens to accept dir_fd. Use the
    # equivalently atomic POSIX rename operation and gate that exact primitive.
    required_dir_fd = {os.open, os.stat, os.mkdir, os.unlink, os.rename}
    required_follow_symlinks = {os.stat}
    return (
        os.name == "posix"
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and required_dir_fd.issubset(os.supports_dir_fd)
        and required_follow_symlinks.issubset(os.supports_follow_symlinks)
    )


def path_is_link_or_reparse(status: os.stat_result) -> bool:
    reparse_mask = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(status, "st_file_attributes", 0)
    return stat.S_ISLNK(status.st_mode) or bool(attributes & reparse_mask)


def portable_parent_chain(parent: Path) -> list[tuple[Path, tuple[int, int]]]:
    lineage: list[Path] = []
    current = parent
    while True:
        lineage.append(current)
        if current.parent == current:
            break
        current = current.parent
    identities: list[tuple[Path, tuple[int, int]]] = []
    for directory in reversed(lineage):
        if identities and not portable_parent_chain_matches(identities):
            fail(
                "output ancestor changed during portable parent creation; this "
                "platform lacks descriptor-relative filesystem operations"
            )
        if not os.path.lexists(directory):
            try:
                directory.mkdir()
            except FileExistsError:
                pass
            if identities and not portable_parent_chain_matches(identities):
                fail(
                    "output ancestor changed while creating a portable parent; "
                    "this platform lacks descriptor-relative filesystem operations"
                )
        status = os.lstat(directory)
        if path_is_link_or_reparse(status) or not stat.S_ISDIR(status.st_mode):
            fail(
                "portable output parent must contain only real directories, "
                f"not symlinks or reparse points: {directory}"
            )
        identities.append((directory, (status.st_dev, status.st_ino)))
    return identities


def portable_parent_chain_matches(
    identities: list[tuple[Path, tuple[int, int]]],
) -> bool:
    for directory, expected in identities:
        try:
            status = os.lstat(directory)
        except OSError:
            return False
        if (
            path_is_link_or_reparse(status)
            or not stat.S_ISDIR(status.st_mode)
            or (status.st_dev, status.st_ino) != expected
        ):
            return False
    return True


def require_portable_regular_target(path: Path) -> None:
    if not os.path.lexists(path):
        return
    status = os.lstat(path)
    if path_is_link_or_reparse(status) or not stat.S_ISREG(status.st_mode):
        fail(
            "portable output target must be a regular file, not a symlink, "
            f"reparse point, or directory: {path}"
        )


def write_text_portable(path: Path, value: str) -> None:
    """Atomic fallback for platforms without descriptor-relative APIs.

    Python on Windows cannot bind path operations to a retained directory
    handle. Reparse checks plus before/after directory identity checks detect
    namespace replacement, but cannot eliminate the narrow check/use window
    between validation and a path-based open or replace.
    """

    identities = portable_parent_chain(path.parent)
    require_portable_regular_target(path)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(12)}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        payload = value.encode("utf-8")
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        if not portable_parent_chain_matches(identities):
            fail(
                "output parent changed before portable atomic replace; this "
                "platform lacks descriptor-relative filesystem operations"
            )
        require_portable_regular_target(path)
        os.replace(temporary, path)
        if not portable_parent_chain_matches(identities):
            fail(
                "output parent changed during portable atomic replace; this "
                "platform lacks descriptor-relative filesystem operations"
            )
    finally:
        if descriptor is not None:
            os.close(descriptor)
        # A failed path-based write may have observed a replaced namespace.
        # Leave the mode-0600 random temporary entry rather than risk unlinking
        # an entry substituted by another process.


def write_text_descriptor(path: Path, value: str) -> None:
    path = Path(os.path.abspath(path))
    (
        parent_descriptor,
        boundary,
        relative_parts,
        boundary_identity,
        parent_identity,
    ) = open_output_parent(path)
    temporary_name = f".{path.name}.{secrets.token_hex(12)}.tmp"
    descriptor: int | None = None
    try:
        try:
            target_status = os.stat(
                path.name, dir_fd=parent_descriptor, follow_symlinks=False
            )
        except FileNotFoundError:
            target_status = None
        if target_status is not None and not stat.S_ISREG(target_status.st_mode):
            fail(f"output target must be a regular file, not a symlink or directory: {path}")
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_descriptor,
        )
        payload = value.encode("utf-8")
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.rename(
            temporary_name,
            path.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        os.fsync(parent_descriptor)
        if not output_directory_matches(
            boundary,
            relative_parts,
            boundary_identity,
            parent_identity,
        ):
            fail(f"output directory namespace changed during write: {path.parent}")
    finally:
        if descriptor is not None:
            os.close(descriptor)
        # Do not unlink a failed temporary name: even under the retained parent
        # fd, another process could have exchanged that directory entry.
        os.close(parent_descriptor)


def write_text(path: Path, value: str) -> None:
    path = Path(os.path.abspath(path))
    if not path.name:
        fail(f"output path must name a file: {path}")
    if descriptor_atomic_writes_supported():
        write_text_descriptor(path, value)
    else:
        write_text_portable(path, value)


def write_json(path: Path, data: dict[str, Any]) -> None:
    write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def write_compact_json(path: Path, data: dict[str, Any]) -> None:
    write_text(
        path,
        json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n",
    )


def load_flow(
    report: dict[str, Any],
    selection_path: Path | None,
    instrumentation_path: Path | None,
    verify_path: Path | None,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    selection = load_selection(selection_path, report)
    instrumentation = (
        normalize_instrumentation(load_json(instrumentation_path), report, selection)
        if instrumentation_path
        else None
    )
    if verify_path and instrumentation is None:
        fail("--verify-json requires --instrumentation-json")
    verify = (
        normalize_verify(load_json(verify_path), report, selection, instrumentation)
        if verify_path and instrumentation is not None
        else None
    )
    return selection, instrumentation, verify


def scoped_report(report: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
    approved = set(selection["approved_ids"])
    findings = [finding for finding in report["findings"] if finding["id"] in approved]
    scenario_ids = {scenario for finding in findings for scenario in finding["verification_scenarios"]}
    scenarios = [scenario for scenario in report["verification"]["scenarios"] if scenario["id"] in scenario_ids]
    environment_ids = {environment for scenario in scenarios for environment in scenario["environments"]}
    environments = [environment for environment in report["verification"]["environments"] if environment["id"] in environment_ids]
    answers_by_id = decision_answer_map(selection.get("decision_answers", []))
    decision_answers = []
    for finding in report["findings"]:
        option = selected_decision_option(finding, answers_by_id.get(finding["id"]))
        if option is None:
            continue
        decision_answers.append(
            {
                "finding_id": finding["id"],
                "option_id": option["id"],
                "label": option["label"],
                "outcome": option["outcome"],
            }
        )
    scoped = {
        "schema_version": OVERLAY_SCHEMA_VERSION,
        "kind": "otel-audit-scope",
        "audit_id": report["meta"]["audit_id"],
        "audit_sha256": audit_digest(report),
        "meta": report["meta"],
        "current_instrumentation": report["current_instrumentation"],
        "genai_readiness": report["genai_readiness"],
        "approved_ids": selection["approved_ids"],
        "findings": findings,
        "verification": {"environments": environments, "scenarios": scenarios},
    }
    if decision_answers:
        scoped["decision_answers"] = decision_answers
    return scoped


def cmd_validate(args: argparse.Namespace) -> int:
    report = normalize_audit_report(load_json(args.audit_json))
    print(
        f"PASS: {args.audit_json} ({len(report['findings'])} findings, "
        f"{len(report['verification']['scenarios'])} scenarios)"
    )
    return 0


def load_canonical_audit_for_selection(audit_json: Path) -> dict[str, Any]:
    try:
        return normalize_audit_report(load_json(audit_json))
    except ReportError as exc:
        fail(
            "canonical audit is invalid; the selection cannot be used until "
            f"$otel-audit is rerun or the audit JSON is repaired: {exc}"
        )


def cmd_select(args: argparse.Namespace) -> int:
    report = load_canonical_audit_for_selection(args.audit_json)
    raw_answers: list[dict[str, str]] = []
    for value in args.decision:
        finding_id, separator, option_id = value.partition("=")
        if not separator or not finding_id.strip() or not option_id.strip():
            fail("--decision must use FINDING_ID=OPTION_ID")
        raw_answers.append(
            {"finding_id": finding_id.strip(), "option_id": option_id.strip()}
        )
    if args.all and args.ids.strip():
        fail("select --all cannot be combined with --ids")
    if args.all:
        raw_ids = select_all_requested_ids(report, raw_answers)
        if not raw_ids:
            fail(
                "select --all found no selectable executable findings. "
                "Answer-only selections authorize no instrumentation code edits."
            )
    else:
        raw_ids = [item.strip() for item in args.ids.split(",") if item.strip()]
    if not raw_ids and not raw_answers:
        fail("select requires --ids, --all, and/or at least one --decision answer")
    selection = normalize_selection(
        {
            "schema_version": (
                CURRENT_SELECTION_SCHEMA_VERSION
                if raw_answers
                else OVERLAY_SCHEMA_VERSION
            ),
            "kind": "otel-selection",
            "audit_id": report["meta"]["audit_id"],
            "audit_sha256": audit_digest(report),
            "requested_ids": raw_ids,
            "decision_answers": raw_answers,
            "approved_by": args.approved_by,
            "approved_at": args.approved_at,
        },
        report,
    )
    approved_ids = selection["approved_ids"]
    write_json(args.output, selection)
    if args.scoped_out:
        write_compact_json(args.scoped_out, scoped_report(report, selection))
    added = [finding_id for finding_id in approved_ids if finding_id not in raw_ids]
    print(
        f"wrote {args.output} ({len(approved_ids)} findings in scope"
        + (", selected all eligible executable findings" if args.all else "")
        + (f", auto-included dependencies: {','.join(added)}" if added else "")
        + ")"
    )
    return 0


def cmd_adopt_selection(args: argparse.Namespace) -> int:
    report = load_canonical_audit_for_selection(args.audit_json)
    if not args.output.parent.is_dir():
        fail(f"selection output parent is not a directory: {args.output.parent}")

    matches: list[tuple[int, int, str, Path, dict[str, Any]]] = []
    rejected: list[str] = []
    for trust_tier, candidate in selection_candidate_paths(
        args.audit_json,
        args.output,
        args.candidate,
        args.search_dir,
    ):
        if not candidate.is_file():
            continue
        selection, reason = try_load_bound_selection(candidate, report)
        if selection is None:
            if reason and candidate.name.startswith(("otel-selection", "otel-audit")):
                rejected.append(f"{candidate}: {reason}")
            continue
        try:
            modified = candidate.stat().st_mtime_ns
        except OSError:
            modified = 0
        matches.append(
            (trust_tier, modified, os.path.abspath(candidate), candidate, selection)
        )

    if not matches:
        details = ("\nRejected candidates:\n- " + "\n- ".join(rejected[:10])) if rejected else ""
        fail(
            "no saved audit selection matching the canonical audit was found. "
            "Save a selected audit copy from .observe/otel.html or run select "
            "with explicit IDs."
            + details
        )

    matches.sort(key=lambda item: (item[0], -item[1], item[2]))
    _trust_tier, _modified, _path_key, source, selection = matches[0]
    selected_all_from_empty = False
    if args.all_if_empty and not selection["approved_ids"]:
        selection = select_all_selection(
            report,
            selection.get("decision_answers", []),
            selection.get("approved_by"),
            selection.get("approved_at"),
        )
        selected_all_from_empty = True
    write_json(args.output, selection)
    if args.scoped_out:
        write_compact_json(args.scoped_out, scoped_report(report, selection))
    auto_added = [
        finding_id
        for finding_id in selection["approved_ids"]
        if finding_id not in selection["requested_ids"]
    ]
    print(
        f"wrote {args.output} from {source} "
        f"({len(selection['approved_ids'])} findings in scope"
        + (
            ", selected all eligible executable findings"
            if selected_all_from_empty
            else ""
        )
        + (
            f", auto-included dependencies: {','.join(auto_added)}"
            if auto_added
            else ""
        )
        + ")"
    )
    return 0


def infer_source_root(audit_json: Path) -> Path:
    audit_parent = audit_json.resolve().parent
    return audit_parent.parent if audit_parent.name == ".observe" else audit_parent


def cmd_render_html(args: argparse.Namespace) -> int:
    audit_data = load_json(args.audit_json)
    report = normalize_audit_report(audit_data)
    if args.instrumentation_json or args.verify_json:
        fail(
            "audit HTML does not render instrumentation or verification overlays; "
            "use render-instrumentation-html"
        )
    selection = load_selection(args.selection_json, report, audit_data)
    source_root = (args.repo_root or infer_source_root(args.audit_json)).resolve()
    if not source_root.is_dir():
        fail(f"source repository root is not a directory: {source_root}")
    html_text = render_html(
        report,
        selection,
        source_root,
        args.output.resolve().parent,
    )
    write_text(args.output, html_text)
    print(f"wrote {args.output} ({len(report['findings'])} findings)")
    return 0


def audit_finalization_preflight_errors(data: Any) -> list[str]:
    """Return common independent authoring errors in one bounded response."""

    if not isinstance(data, dict):
        return []
    errors: list[str] = []

    row_contracts: tuple[tuple[str, Any, tuple[str, ...]], ...] = (
        (
            "genai_readiness",
            data.get("genai_readiness"),
            (
                "surface",
                "status",
                "evidence",
                "required_signals",
                "owner",
                "acceptance_criteria",
                "impact",
            ),
        ),
        (
            "current_instrumentation.incident_readiness",
            (
                data.get("current_instrumentation", {}).get("incident_readiness")
                if isinstance(data.get("current_instrumentation"), dict)
                else None
            ),
            ("area", "status", "evidence", "required_signals", "impact"),
        ),
    )
    for path, rows, fields in row_contracts:
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            for field in fields:
                value = row.get(field)
                try:
                    compact_row_text(value, f"{path}[{index}].{field}")
                except ReportError:
                    errors.append(f"{path}[{index}].{field} must be a string")

    return errors[:50]


def markdown_local_file_link(label: str, path: PurePath) -> str:
    """Return a CommonMark-safe link to one absolute local path."""

    escaped_label = (
        label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    )
    destination = quote(
        path.as_posix(),
        safe="/: ._~!$&'()*+,;=@-",
    )
    return f"[{escaped_label}](<{destination}>)"


def cmd_finalize_audit(args: argparse.Namespace) -> int:
    """Validate the canonical audit once and render its human HTML view."""

    raw_report = load_json(args.audit_json)
    preflight_errors = audit_finalization_preflight_errors(raw_report)
    if preflight_errors:
        fail(
            f"audit finalization found {len(preflight_errors)} independent authoring "
            "errors:\n- "
            + "\n- ".join(preflight_errors)
        )
    report = normalize_audit_report(raw_report)
    source_root = (args.repo_root or infer_source_root(args.audit_json)).resolve()
    if not source_root.is_dir():
        fail(f"source repository root is not a directory: {source_root}")
    write_text(
        args.html,
        render_html(
            report,
            load_selection(None, report),
            source_root,
            args.html.resolve().parent,
        ),
    )
    print(
        json.dumps(
            {
                "result": "PASS",
                "audit_sha256": audit_digest(report),
                "findings": len(report["findings"]),
                "scenarios": len(report["verification"]["scenarios"]),
                "audit": str(args.audit_json.resolve()),
                "html": str(args.html.resolve()),
                "links": {
                    "review_report": markdown_local_file_link(
                        "otel.html", args.html.resolve()
                    ),
                    "machine_report": markdown_local_file_link(
                        "otel-audit.json", args.audit_json.resolve()
                    ),
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def cmd_render_instrumentation_html(args: argparse.Namespace) -> int:
    report = normalize_audit_report(load_json(args.audit_json))
    selection, instrumentation, verify = load_flow(
        report, args.selection_json, args.instrumentation_json, args.verify_json
    )
    if instrumentation is None:
        fail("render-instrumentation-html requires --instrumentation-json")
    source_root = (args.repo_root or infer_source_root(args.audit_json)).resolve()
    if not source_root.is_dir():
        fail(f"source repository root is not a directory: {source_root}")
    html_text = render_instrumentation_html(
        report,
        selection,
        instrumentation,
        verify,
        source_root,
        args.output.resolve().parent,
    )
    write_text(args.output, html_text)
    print(
        f"wrote {args.output} ({len(instrumentation['findings'])} findings in scope, "
        f"verification {verify['meta']['result'] if verify else 'Not run'})"
    )
    return 0


def cmd_validate_flow(args: argparse.Namespace) -> int:
    report = load_canonical_audit_for_selection(args.audit_json)
    selection, instrumentation, verify = load_flow(
        report, args.selection_json, args.instrumentation_json, args.verify_json
    )
    stages = ["audit", "selection"]
    if instrumentation:
        stages.append("instrumentation")
    if verify:
        stages.append("verify")
    print(
        f"PASS: {' -> '.join(stages)} ({len(selection['approved_ids'])} findings in scope, "
        f"audit {report['meta']['audit_id']})"
    )
    return 0


def cmd_instrumentation_digest(args: argparse.Namespace) -> int:
    """Print the canonical digest for one bound instrumentation overlay."""
    report = normalize_audit_report(load_json(args.audit_json))
    _selection, instrumentation, _verify = load_flow(
        report,
        args.selection_json,
        args.instrumentation_json,
        None,
    )
    if instrumentation is None:
        fail("instrumentation-digest requires instrumentation JSON")
    print(instrumentation_digest(instrumentation))
    return 0


def instrumentation_final_gate_result(
    report: dict[str, Any],
    selection: dict[str, Any],
    instrumentation: dict[str, Any],
    verify: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Evaluate the shared final gate against an already-normalized flow."""
    if verify["meta"]["workflow_mode"] != "instrumentation_child":
        fail(
            "instrumentation-final-gate requires verify.meta.workflow_mode "
            "instrumentation_child"
        )
    failed_findings = [
        finding["id"]
        for finding in verify["findings"]
        if finding["status"] == "not_working"
    ]
    failed_scenarios = [
        scenario["id"]
        for finding in verify["findings"]
        for scenario in finding["scenarios"]
        if scenario["status"] == "not_working"
    ]
    failed_items = [
        item["id"]
        for finding in verify["findings"]
        for item in finding["item_results"]
        if item["status"] == "not_working"
    ]
    passed = (
        verify["meta"]["lifecycle"] == "final"
        and not failed_findings
        and instrumentation["meta"]["result"] != "Fail"
    )
    pending = [
        finding["id"]
        for finding in verify["findings"]
        if finding["status"] not in {"working", "not_working"}
    ]
    return (
        {
            "schema_version": OVERLAY_SCHEMA_VERSION,
            "kind": "otel-instrumentation-final-gate",
            "audit_id": report["meta"]["audit_id"],
            "audit_sha256": audit_digest(report),
            "selection_sha256": selection_digest(selection),
            "instrumentation_sha256": instrumentation_digest(instrumentation),
            "passed": passed,
            "verification_result": verify["meta"]["result"],
            "verification_lifecycle": verify["meta"]["lifecycle"],
            "failed_findings": failed_findings,
            "failed_scenarios": failed_scenarios,
            "failed_items": failed_items,
            "proof_pending_findings": pending,
        },
        pending,
    )


def print_instrumentation_final_gate(
    result: dict[str, Any],
    verify: dict[str, Any],
    pending: list[str],
) -> int:
    if not result["passed"]:
        failed_findings = result["failed_findings"]
        print(
            "REPAIR REQUIRED: instrumentation cannot finalize with an intermediate "
            "or failed child verification result"
            + (f"; findings={','.join(failed_findings)}" if failed_findings else "")
        )
        return 2
    print(
        "PASS: instrumentation final gate "
        f"({len(verify['findings']) - len(pending)}/{len(verify['findings'])} "
        "findings at required proof; no executed verification failures)"
    )
    return 0


def cmd_instrumentation_final_gate(args: argparse.Namespace) -> int:
    """Prevent an active instrumentation workflow from handing off stale failures."""
    report = normalize_audit_report(load_json(args.audit_json))
    raw_verify = load_json(args.verify_json)
    if not raw_verify.get("instrumentation_sha256"):
        fail(
            "final instrumentation verification must include instrumentation_sha256 "
            "bound to the exact normalized instrumentation overlay"
        )
    selection, instrumentation, verify = load_flow(
        report, args.selection_json, args.instrumentation_json, args.verify_json
    )
    if instrumentation is None or verify is None:
        fail("instrumentation-final-gate requires instrumentation and verification JSON")
    result, pending = instrumentation_final_gate_result(
        report, selection, instrumentation, verify
    )
    if args.output:
        write_json(args.output, result)
    return print_instrumentation_final_gate(result, verify, pending)


def run_projection_validator(label: str, command: list[str]) -> str:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode == 0:
        return completed.stdout.strip()
    detail = (completed.stderr or completed.stdout).strip()
    fail(
        f"{label} failed"
        + (f": {detail}" if detail else f" with exit code {completed.returncode}")
    )


def run_go_validation_freshness(command: list[str]) -> dict[str, Any]:
    """Run and parse one digest-only fixed-Go freshness check."""

    output = run_projection_validator("fixed Go validation freshness", command)
    try:
        result = json.loads(output)
    except (json.JSONDecodeError, UnicodeError) as exc:
        fail(f"fixed Go validation freshness returned invalid JSON: {exc}")
    if not isinstance(result, dict) or result.get("status") != "passed":
        fail("fixed Go validation freshness returned an invalid success result")
    for key in (
        "accepted_plan_sha256",
        "evidence_sha256",
        "proxy_bundle_sha256",
        "resolver_plan_sha256",
        "runtime_sha256",
        "source_sha256",
    ):
        value = result.get(key)
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            fail(f"fixed Go validation freshness omitted valid {key}")
    return result


def stale_parent_verification_actions(
    instrumentation: dict[str, Any],
) -> list[str]:
    """Locate parent CTAs that still ask for the already-present child run."""
    locations: list[str] = []
    candidates = [
        (f"instrumentation.next_steps[{index}]", action)
        for index, action in enumerate(instrumentation["next_steps"])
    ]
    for finding_index, finding in enumerate(instrumentation["findings"]):
        candidates.extend(
            (
                f"instrumentation.findings[{finding_index}].follow_up_actions[{index}]",
                action,
            )
            for index, action in enumerate(finding["follow_up_actions"])
        )
        for item_index, item in enumerate(finding["telemetry_changes"]):
            candidates.extend(
                (
                    "instrumentation.findings"
                    f"[{finding_index}].telemetry_changes[{item_index}]"
                    f".follow_up_actions[{index}]",
                    action,
                )
                for index, action in enumerate(item["follow_up_actions"])
            )
    for location, action in candidates:
        if is_stale_parent_verification_action(action):
            locations.append(location)
    return locations


def cmd_finalize_instrumentation(args: argparse.Namespace) -> int:
    """Validate, atomically render, and gate one bound instrumentation flow."""
    report = normalize_audit_report(load_json(args.audit_json))

    # This is intentionally first: a stale proof overlay must not invoke other
    # tools or replace any reader/gate artifacts.
    selection, instrumentation, verify = load_flow(
        report, args.selection_json, args.instrumentation_json, args.verify_json
    )
    if instrumentation is None or verify is None:
        fail("finalize-instrumentation requires instrumentation and verification JSON")
    if verify["meta"]["workflow_mode"] != "instrumentation_child":
        fail(
            "finalize-instrumentation requires verify.meta.workflow_mode "
            "instrumentation_child"
        )
    stale_actions = stale_parent_verification_actions(instrumentation)
    if stale_actions:
        fail(
            "finalize-instrumentation found stale parent actions that ask to run "
            "the already-present child verification: "
            + ", ".join(stale_actions)
            + "; replace them with durable implementation/product actions and "
            "rerun the child so its digest binds the corrected instrumentation overlay"
        )

    skills_root = Path(__file__).resolve().parents[2]
    reader_validator = (
        skills_root / "otel-verify" / "scripts" / "validate_reader_report.py"
    )
    gap_validator = (
        skills_root / "otel-instrument" / "scripts" / "validate_gap_closure.py"
    )
    for label, validator in (
        ("verify reader validator", reader_validator),
        ("instrumentation gap-closure validator", gap_validator),
    ):
        if not validator.is_file():
            fail(f"{label} is missing from the active skill bundle: {validator}")

    source_root = (args.repo_root or infer_source_root(args.audit_json)).resolve()
    if not source_root.is_dir():
        fail(f"source repository root is not a directory: {source_root}")

    go_runner = (
        skills_root / "otel-instrument" / "scripts" / "run_go_otel_command.py"
    )
    go_ledger = (
        source_root
        / ".observe"
        / "tmp"
        / "go-otel-resolver"
        / "accepted-plan.json"
    )
    go_evidence = source_root / ".observe" / "evidence" / "go-otel-validation.json"
    if go_ledger.exists() != go_evidence.exists():
        fail(
            "fixed Go validation freshness is incomplete: accepted-plan ledger "
            "and validation evidence must both exist before finalization"
        )
    go_check_command: list[str] | None = None
    first_go_freshness: dict[str, Any] | None = None
    if go_ledger.exists():
        if not go_runner.is_file():
            fail(f"fixed Go validation runner is missing: {go_runner}")
        raw_go_evidence = load_json(go_evidence)
        resolver_plan = raw_go_evidence.get("resolver_plan")
        if not isinstance(resolver_plan, dict):
            fail("fixed Go validation evidence has no resolver-plan binding")
        plan_path = resolver_plan.get("path")
        plan_sha256 = resolver_plan.get("sha256")
        expected_plan = source_root / ".observe" / "tmp" / "go-otel-version-plan.json"
        if plan_path != str(expected_plan) or not isinstance(plan_sha256, str):
            fail("fixed Go validation evidence resolver-plan binding is invalid")
        go_check_command = [
            sys.executable,
            "-I",
            str(go_runner),
            "--project",
            str(source_root),
            "--plan",
            plan_path,
            "--plan-sha256",
            plan_sha256,
            "--action",
            "check-validation",
        ]
        first_go_freshness = run_go_validation_freshness(go_check_command)

    instrumentation_markdown = (
        args.instrumentation_markdown
        or args.instrumentation_json.with_suffix(".md")
    )
    verify_markdown = args.verify_markdown or args.verify_json.with_suffix(".md")

    run_projection_validator(
        "verify reader projection",
        [
            sys.executable,
            "-I",
            str(reader_validator),
            str(verify_markdown),
            "--instrumentation-json",
            str(args.instrumentation_json),
            "--verify-json",
            str(args.verify_json),
            "--audit-json",
            str(args.audit_json),
            "--selection-json",
            str(args.selection_json),
        ],
    )
    run_projection_validator(
        "instrumentation gap closure",
        [
            sys.executable,
            "-I",
            str(gap_validator),
            str(instrumentation_markdown),
            "--audit-json",
            str(args.audit_json),
            "--selection-json",
            str(args.selection_json),
            "--instrumentation-json",
            str(args.instrumentation_json),
            "--verify-json",
            str(args.verify_json),
        ],
    )

    html_text = render_instrumentation_html(
        report,
        selection,
        instrumentation,
        verify,
        source_root,
        args.output.resolve().parent,
    )
    if go_check_command is not None and first_go_freshness is not None:
        final_go_freshness = run_go_validation_freshness(go_check_command)
        if final_go_freshness != first_go_freshness:
            fail(
                "fixed Go validation freshness changed between the initial check "
                "and HTML publication"
            )
    write_text(args.output, html_text)
    result, pending = instrumentation_final_gate_result(
        report, selection, instrumentation, verify
    )
    if args.gate_output:
        write_json(args.gate_output, result)
    return print_instrumentation_final_gate(result, verify, pending)


def cmd_gate(args: argparse.Namespace) -> int:
    report = normalize_audit_report(load_json(args.audit_json))
    included_priorities = {
        "none": set(),
        "required": {"required"},
        "recommended": {"required", "recommended"},
        "any": PRIORITIES,
    }[args.fail_on]
    unresolved = [
        finding
        for finding in report["findings"]
        if finding["priority"] in included_priorities
        and finding["status"] in {"proposed", "approved", "in_progress"}
    ]
    audit_incomplete = (
        report["schema_version"] == CURRENT_AUDIT_SCHEMA_VERSION
        and report["meta"]["status"] == "Blocked"
    )
    result = {
        "schema_version": OVERLAY_SCHEMA_VERSION,
        "kind": "otel-audit-gate",
        "audit_id": report["meta"]["audit_id"],
        "audit_sha256": audit_digest(report),
        "fail_on": args.fail_on,
        "audit_status": report["meta"]["status"],
        "policy_evaluated": not audit_incomplete,
        "passed": not unresolved and not audit_incomplete,
        "blocking_ids": [finding["id"] for finding in unresolved],
    }
    if audit_incomplete:
        result["scan_blockers"] = [
            blocker["id"] for blocker in report["scan_blockers"]
        ]
    if args.output:
        write_json(args.output, result)
    if audit_incomplete:
        print(
            "BLOCKED: audit scan is incomplete: "
            + "; ".join(
                f"{blocker['id']} {blocker['prerequisite']}"
                for blocker in report["scan_blockers"]
            )
        )
        return 0 if args.fail_on == "none" else 2
    if unresolved:
        print(
            "GAP: unresolved findings matched the CI policy: "
            + ",".join(finding["id"] for finding in unresolved)
        )
        return 2
    print(f"PASS: audit gate ({args.fail_on})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate canonical OTel audit JSON")
    validate.add_argument("audit_json", type=Path)
    validate.set_defaults(func=cmd_validate)

    select = subparsers.add_parser("select", help="validate IDs and write a bound selection")
    select.add_argument("audit_json", type=Path)
    select.add_argument(
        "--ids",
        default="",
        help="comma-separated executable finding IDs",
    )
    select.add_argument(
        "--all",
        action="store_true",
        help=(
            "select every currently eligible executable finding; stops with "
            "manual-decision options when a choice is required"
        ),
    )
    select.add_argument("-o", "--output", type=Path, required=True)
    select.add_argument("--scoped-out", type=Path)
    select.add_argument("--approved-by")
    select.add_argument("--approved-at")
    select.add_argument(
        "--decision",
        action="append",
        default=[],
        metavar="FINDING_ID=OPTION_ID",
        help="record a manual decision answer; repeat for multiple decisions",
    )
    select.set_defaults(func=cmd_select)

    adopt = subparsers.add_parser(
        "adopt-selection",
        help=(
            "copy the highest-trust saved otel-selection*.json or "
            "otel-audit*.json review_selection bound to the audit into "
            ".observe/otel-selection.json"
        ),
    )
    adopt.add_argument("audit_json", type=Path)
    adopt.add_argument("-o", "--output", type=Path, required=True)
    adopt.add_argument("--scoped-out", type=Path)
    adopt.add_argument(
        "--candidate",
        action="append",
        default=[],
        type=Path,
        help="explicit selection JSON candidate; repeat for multiple files",
    )
    adopt.add_argument(
        "--search-dir",
        action="append",
        default=[],
        type=Path,
        help=(
            "directory to search for otel-selection*.json or saved "
            "otel-audit*.json; repeat as needed"
        ),
    )
    adopt.add_argument(
        "--all-if-empty",
        action="store_true",
        help=(
            "when the adopted selection has only decision answers, select every "
            "eligible executable finding using those answers"
        ),
    )
    adopt.set_defaults(func=cmd_adopt_selection)

    render = subparsers.add_parser("render-html", help="render self-contained audit and scope-planning HTML")
    render.add_argument("audit_json", type=Path)
    render.add_argument("-o", "--output", type=Path, required=True)
    render.add_argument("--selection-json", type=Path)
    render.add_argument("--instrumentation-json", type=Path)
    render.add_argument("--verify-json", type=Path)
    render.add_argument(
        "--repo-root",
        type=Path,
        help="source repository root for portable local-file links (inferred from .observe by default)",
    )
    render.set_defaults(func=cmd_render_html)

    finalize_audit = subparsers.add_parser(
        "finalize-audit",
        help="validate canonical audit and render self-contained HTML",
    )
    finalize_audit.add_argument("audit_json", type=Path)
    finalize_audit.add_argument("--html", type=Path, required=True)
    finalize_audit.add_argument(
        "--repo-root",
        type=Path,
        help="source repository root for portable local-file links (inferred from .observe by default)",
    )
    finalize_audit.set_defaults(func=cmd_finalize_audit)

    instrumentation_html = subparsers.add_parser(
        "render-instrumentation-html",
        help="render self-contained instrumentation, product-impact, and proof HTML",
    )
    instrumentation_html.add_argument("audit_json", type=Path)
    instrumentation_html.add_argument("-o", "--output", type=Path, required=True)
    instrumentation_html.add_argument("--selection-json", type=Path, required=True)
    instrumentation_html.add_argument("--instrumentation-json", type=Path, required=True)
    instrumentation_html.add_argument("--verify-json", type=Path)
    instrumentation_html.add_argument(
        "--repo-root",
        type=Path,
        help="source repository root for portable local-file links (inferred from .observe by default)",
    )
    instrumentation_html.set_defaults(func=cmd_render_instrumentation_html)

    flow = subparsers.add_parser("validate-flow", help="validate bound workflow overlays")
    flow.add_argument("audit_json", type=Path)
    flow.add_argument("--selection-json", type=Path, required=True)
    flow.add_argument("--instrumentation-json", type=Path)
    flow.add_argument("--verify-json", type=Path)
    flow.set_defaults(func=cmd_validate_flow)

    instrumentation_digest_command = subparsers.add_parser(
        "instrumentation-digest",
        help="print the canonical digest of a bound instrumentation overlay",
    )
    instrumentation_digest_command.add_argument("audit_json", type=Path)
    instrumentation_digest_command.add_argument(
        "--selection-json", type=Path, required=True
    )
    instrumentation_digest_command.add_argument(
        "--instrumentation-json", type=Path, required=True
    )
    instrumentation_digest_command.set_defaults(func=cmd_instrumentation_digest)

    instrumentation_gate = subparsers.add_parser(
        "instrumentation-final-gate",
        help="block final instrumentation handoff while child verification needs repair",
    )
    instrumentation_gate.add_argument("audit_json", type=Path)
    instrumentation_gate.add_argument("--selection-json", type=Path, required=True)
    instrumentation_gate.add_argument("--instrumentation-json", type=Path, required=True)
    instrumentation_gate.add_argument("--verify-json", type=Path, required=True)
    instrumentation_gate.add_argument("--output", type=Path)
    instrumentation_gate.set_defaults(func=cmd_instrumentation_final_gate)

    finalize_instrumentation = subparsers.add_parser(
        "finalize-instrumentation",
        help=(
            "validate reader projections, atomically render instrumentation HTML, "
            "and apply the final child-verification gate"
        ),
    )
    finalize_instrumentation.add_argument("audit_json", type=Path)
    finalize_instrumentation.add_argument(
        "--selection-json", type=Path, required=True
    )
    finalize_instrumentation.add_argument(
        "--instrumentation-json", type=Path, required=True
    )
    finalize_instrumentation.add_argument("--verify-json", type=Path, required=True)
    finalize_instrumentation.add_argument("--instrumentation-markdown", type=Path)
    finalize_instrumentation.add_argument("--verify-markdown", type=Path)
    finalize_instrumentation.add_argument(
        "-o", "--output", "--html-output", type=Path, required=True
    )
    finalize_instrumentation.add_argument(
        "--repo-root",
        type=Path,
        help=(
            "source repository root for portable local-file links "
            "(inferred from .observe by default)"
        ),
    )
    finalize_instrumentation.add_argument("--gate-output", type=Path)
    finalize_instrumentation.set_defaults(func=cmd_finalize_instrumentation)

    gate = subparsers.add_parser("gate", help="apply a deterministic CI finding policy")
    gate.add_argument("audit_json", type=Path)
    gate.add_argument("--fail-on", choices=("none", "required", "recommended", "any"), default="required")
    gate.add_argument("--output", type=Path)
    gate.set_defaults(func=cmd_gate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (OSError, ReportError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
