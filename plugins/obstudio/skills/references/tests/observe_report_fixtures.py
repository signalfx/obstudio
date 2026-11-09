from __future__ import annotations

import copy
import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "observe_report.py"
SPEC = importlib.util.spec_from_file_location("observe_report", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def sample_report() -> dict[str, object]:
    return {
        "schema_version": 2,
        "kind": "otel-audit",
        "meta": {
            "audit_id": "checkout-20260717",
            "service_name": "checkout",
            "commit": "abc1234",
            "language": "go",
            "framework": "chi",
            "date": "2026-07-17",
            "status": "Partial",
            "genai_ownership_detected": False,
        },
        "summary": ["Checkout telemetry needs route-level latency coverage."],
        "flow": "audit -> instrument -> verify -> configure",
        "evidence": [
            {"check": "Manifest", "finding": "Go module", "source": "go.mod"},
            {"check": "Entry point", "finding": "HTTP API", "source": "main.go"},
            {"check": "Route source", "finding": "GET /checkout", "source": "main.go:42"},
            {"check": "Runtime/startup", "finding": "go run", "source": "Makefile"},
            {"check": "GenAI ownership", "finding": "No", "source": "bounded repository scan"},
        ],
        "routes": [{"method": "GET", "path": "/checkout"}],
        "signal_flow": {
            "component_flow_map": (
                "Request path\n"
                "main.go [SOURCE-COVERED] -> checkout [GAP: Checkout latency]\n\n"
                "Dependency path\n"
                "checkout [SOURCE-COVERED] -> payment provider [GAP: Payment dependency]"
            )
        },
        "current_instrumentation": {
            "spans": [],
            "metrics": [],
            "logs": [],
            "incident_readiness": [],
        },
        "genai_readiness": [],
        "findings": [
            {
                "id": "OTEL-001",
                "title": "Checkout latency is not measured",
                "priority": "required",
                "effort": "small",
                "area": "Checkout latency",
                "gap": "No route-level latency metric or span timing exists.",
                "impact": "Operators cannot isolate slow checkout requests.",
                "product_outcome": "Each checkout request has one route-named trace that can be filtered in the waterfall.",
                "required_fix": "Add HTTP server instrumentation and route span attributes.",
                "instrument_mode": "default",
                "verification_scenarios": ["http.checkout.success"],
                "evidence": ["main.go:42"],
                "acceptance_criteria": ["A request emits one server span with http.route."],
                "constraints": ["Keep route values low cardinality."],
                "expected_telemetry": [
                    {
                        "type": "span",
                        "name": "GET /checkout",
                        "attributes": ["http.route"],
                        "product_view": "Trace waterfall and route filtering",
                    }
                ],
                "follow_up_actions": ["Verify the span in ObStudio before merge."],
            },
            {
                "id": "OTEL-002",
                "title": "Payment provider dimension is missing",
                "severity": "medium",
                "priority": "recommended",
                "effort": "medium",
                "area": "Payment dependency",
                "gap": "Provider calls are not distinguishable.",
                "impact": "Operators cannot compare provider-specific latency.",
                "product_outcome": "Traces can be filtered by a bounded payment-provider name.",
                "required_fix": "Add a low-cardinality payment.provider span attribute.",
                "instrument_mode": "fix all",
                "verification_scenarios": ["http.checkout.success"],
                "dependencies": ["OTEL-001"],
                "evidence": ["payments.go:18"],
                "acceptance_criteria": ["Provider is filterable without raw provider IDs."],
                "constraints": ["Use a bounded provider name."],
                "expected_telemetry": [
                    {
                        "type": "span",
                        "name": "payment.authorize",
                        "attributes": ["payment.provider"],
                        "product_view": "Provider-specific trace filtering",
                    }
                ],
                "follow_up_actions": ["Slice the trace view by payment.provider."],
            },
        ],
        "verification": {
            "environments": [
                {
                    "id": "go.local",
                    "surface": "checkout service",
                    "config_evidence": "go.mod",
                    "runner": "go test ./...",
                    "scope": "module",
                    "prerequisites": "none",
                }
            ],
            "scenarios": [
                {
                    "id": "http.checkout.success",
                    "trigger": "GET /checkout",
                    "entrypoint": "main.go:42",
                    "expected_signals": "GET /checkout span and payment.request.duration metric",
                    "proof_level": "full runtime",
                    "acceptance_criteria": "span is emitted with route attribute",
                    "environments": ["go.local"],
                }
            ],
        },
        "anti_patterns": [],
        "recommendation": ["Run $otel-instrument for OTEL-001."],
    }


def sample_splunk_agent_observability_report() -> dict[str, object]:
    data = sample_report()
    data["findings"].extend(  # type: ignore[union-attr]
        [
            {
                "id": "AO-001",
                "finding_group": "splunk-agent-observability",
                "title": "Agent Observability project is not configured",
                "severity": "high",
                "priority": "required",
                "effort": "small",
                "status": "proposed",
                "area": "Agent Observability project",
                "gap": "No source-backed project configuration is present.",
                "impact": "Agent traces cannot be assigned to the intended project.",
                "product_outcome": "The application has a durable Agent Observability project target.",
                "required_fix": "Create or configure the Agent Observability project through a checked-in deployment path.",
                "instrument_mode": "default",
                "verification_scenarios": ["http.checkout.success"],
                "dependencies": [],
                "evidence": ["Makefile"],
                "acceptance_criteria": ["The configured project can be resolved without Obstudio at runtime."],
                "constraints": ["Do not put access tokens in tracked files."],
                "expected_telemetry": [
                    {
                        "type": "configuration",
                        "name": "agent-observability.project",
                        "attributes": [],
                        "product_view": "Agent Observability project routing",
                    }
                ],
                "follow_up_actions": ["Confirm the project target before instrumentation."],
            },
            {
                "id": "AO-002",
                "finding_group": "splunk-agent-observability",
                "title": "Dedicated Agent Stream is not configured",
                "severity": "high",
                "priority": "required",
                "effort": "small",
                "status": "proposed",
                "area": "Dedicated Agent Stream",
                "gap": "No source-backed Agent Stream configuration is present.",
                "impact": "Agent traces remain unassigned or mix with unrelated applications.",
                "product_outcome": "The application routes traces to its dedicated Agent Stream.",
                "required_fix": "Create the Agent Stream and persist direct application export routing.",
                "instrument_mode": "default",
                "verification_scenarios": ["http.checkout.success"],
                "dependencies": ["AO-001", "OTEL-001"],
                "evidence": ["Makefile"],
                "acceptance_criteria": ["A fresh application trace appears in the dedicated Agent Stream."],
                "constraints": ["The deployed application must not require Obstudio in the data path."],
                "expected_telemetry": [
                    {
                        "type": "configuration",
                        "name": "agent-observability.agent-stream",
                        "attributes": [],
                        "product_view": "Dedicated Agent Stream",
                    }
                ],
                "follow_up_actions": ["Confirm routing with a fresh application trace."],
            },
        ]
    )
    data["signal_flow"]["component_flow_map"] += (  # type: ignore[index]
        "\n\nAgent Observability configuration\n"
        "deployment [GAP: Agent Observability project] -> "
        "Agent Stream [GAP: Dedicated Agent Stream]"
    )
    return data


def make_manual_decision(finding: dict[str, object]) -> None:
    finding["instrument_mode"] = "manual decision"
    finding["decision_owner"] = "service telemetry owner"
    telemetry = finding["expected_telemetry"]
    signal_name = telemetry[0]["name"]  # type: ignore[index]
    finding["decision_question"] = (
        f"Which owner and bounded attributes should the OTel signal {signal_name} use?"
    )
    finding.pop("external_owner", None)
    finding.pop("external_requirement", None)


def sample_decision_branch_report() -> dict[str, object]:
    data = sample_report()
    decision = data["findings"][0]  # type: ignore[index]
    make_manual_decision(decision)
    decision.update(
        {
            "title": "Choose the checkout span owner",
            "effort": "decision",
            "area": "Checkout tracing owner",
            "gap": "The source does not define which OpenTelemetry owner emits the GET /checkout span.",
            "impact": "Two competing span owners can duplicate or suppress the checkout trace.",
            "product_outcome": "Each checkout request has one canonical GET /checkout span in the trace waterfall.",
            "required_fix": "Choose which OpenTelemetry path emits the GET /checkout span.",
            "follow_up_actions": [
                "Select the GET /checkout span emission path before instrumentation."
            ],
            "dependencies": [],
            "decision_options": [
                {
                    "id": "application-owned",
                    "label": "Application-owned span",
                    "outcome": "Emit the GET /checkout span from application-owned OpenTelemetry instrumentation.",
                    "unlocks": ["OTEL-002"],
                },
                {
                    "id": "runtime-owned",
                    "label": "Runtime-owned span",
                    "outcome": "Emit the GET /checkout span from OpenTelemetry runtime auto-instrumentation.",
                    "unlocks": ["OTEL-003"],
                },
            ],
        }
    )

    application_branch = data["findings"][1]  # type: ignore[index]
    application_branch.update(
        {
            "title": "Implement application-owned checkout tracing",
            "priority": "required",
            "effort": "small",
            "area": "Application checkout tracing",
            "gap": "The application does not emit the canonical GET /checkout span.",
            "impact": "Checkout requests have no application-owned trace waterfall.",
            "product_outcome": "The trace waterfall shows one application-owned GET /checkout span.",
            "required_fix": "Emit the GET /checkout span from application OpenTelemetry instrumentation.",
            "instrument_mode": "default",
            "dependencies": ["OTEL-001"],
            "expected_telemetry": copy.deepcopy(decision["expected_telemetry"]),
            "acceptance_criteria": [
                "Application instrumentation emits one GET /checkout span with http.route."
            ],
            "follow_up_actions": [
                "Verify the application-owned GET /checkout span before merge."
            ],
        }
    )

    runtime_branch = copy.deepcopy(application_branch)
    runtime_branch.update(
        {
            "id": "OTEL-003",
            "title": "Configure runtime-owned checkout tracing",
            "priority": "recommended",
            "area": "Runtime checkout tracing",
            "gap": "Runtime auto-instrumentation does not emit the canonical GET /checkout span.",
            "impact": "Checkout requests have no runtime-owned trace waterfall.",
            "product_outcome": "The trace waterfall shows one runtime-owned GET /checkout span.",
            "required_fix": "Emit the GET /checkout span from OpenTelemetry runtime auto-instrumentation.",
            "instrument_mode": "fix all",
            "acceptance_criteria": [
                "Runtime auto-instrumentation emits one GET /checkout span with http.route."
            ],
            "follow_up_actions": [
                "Verify the runtime-owned GET /checkout span before merge."
            ],
        }
    )
    data["findings"].append(runtime_branch)  # type: ignore[index]
    data["signal_flow"]["component_flow_map"] = (  # type: ignore[index]
        "main.go [GAP: Checkout tracing owner]\n"
        "checkout handler [GAP: Application checkout tracing]\n"
        "runtime bootstrap [GAP: Runtime checkout tracing]"
    )
    return data


def make_external_follow_up(finding: dict[str, object]) -> None:
    finding["instrument_mode"] = "external follow-up"
    finding["external_owner"] = "telemetry platform team"
    telemetry = finding["expected_telemetry"]
    signal_name = telemetry[0]["name"]  # type: ignore[index]
    requirement = f"Supply the platform-owned OTel signal {signal_name} and saved telemetry proof."
    finding["external_requirement"] = requirement
    finding["required_fix"] = requirement
    finding.pop("decision_owner", None)
    finding.pop("decision_question", None)


def sample_instrumentation(
    report: dict[str, object],
    digest: str,
    selection: dict[str, object] | None = None,
) -> dict[str, object]:
    if selection is None:
        selection = MODULE.normalize_selection(
            {
                "schema_version": 1,
                "kind": "otel-selection",
                "audit_id": report["meta"]["audit_id"],  # type: ignore[index]
                "audit_sha256": digest,
                "requested_ids": ["OTEL-001"],
                "approved_ids": ["OTEL-001"],
            },
            report,
        )
    return {
        "schema_version": 1,
        "kind": "otel-instrumentation",
        "audit_id": report["meta"]["audit_id"],  # type: ignore[index]
        "audit_sha256": digest,
        "selection_sha256": MODULE.selection_digest(selection),
        "meta": {"service_name": "checkout", "date": "2026-07-17", "result": "Partial"},
        "findings": [
            {
                "id": "OTEL-001",
                "status": "not_proven",
                "changes": ["Wrapped the handler."],
                "telemetry_changes": [
                    {
                        "id": "OTEL-001.http-server-span",
                        "change_kind": "modified",
                        "change": "Wrapped the server handler with route-aware tracing.",
                        "type": "span",
                        "name": "GET /checkout",
                        "source": "main.go:42",
                        "added_attributes": ["http.route"],
                        "product_view": "Route trace waterfall",
                        "follow_up_actions": ["Filter the trace waterfall by http.route."],
                        "verification_scenarios": ["http.checkout.success"],
                    }
                ],
                "tests": ["go test ./..."],
                "evidence": ["main.go:42"],
                "follow_up_actions": ["Run verification, then review the route trace."],
            }
        ],
        "next_steps": ["Run verification."],
    }


def sample_verify(
    report: dict[str, object],
    digest: str,
    instrumentation_sha256: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "otel-verify",
        "audit_id": report["meta"]["audit_id"],  # type: ignore[index]
        "audit_sha256": digest,
        "instrumentation_sha256": instrumentation_sha256,
        "meta": {"service_name": "checkout", "date": "2026-07-20", "result": "Partial"},
        "findings": [
            {
                "id": "OTEL-001",
                "status": "not_proven",
                "scenarios": [
                    {
                        "id": "http.checkout.success",
                        "status": "not_proven",
                        "commands": ["go test ./..."],
                        "evidence": [".observe/evidence/run/test.txt"],
                        "observed_telemetry": [],
                        "trace_ids": [],
                        "product_validation": ["Target-product query was not run."],
                        "proof_mode": "app_test",
                        "visibility": "not_explorer_visible",
                    }
                ],
                "item_results": [
                    {
                        "id": "OTEL-001.http-server-span",
                        "status": "not_proven",
                        "direct_assertion_passed": False,
                        "scenarios": ["http.checkout.success"],
                        "proof_mode": "app_test",
                        "visibility": "not_explorer_visible",
                        "evidence": [".observe/evidence/run/test.txt"],
                        "observed_telemetry": [],
                        "product_validation": ["Target-product query was not run."],
                    }
                ],
                "remaining": ["Capture the remaining route topology proof."],
            }
        ],
        "next_steps": ["Capture the remaining route topology proof."],
    }
