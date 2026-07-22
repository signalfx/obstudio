from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_TOOL = ROOT / "skills" / "references" / "scripts" / "observe_report.py"


def _load_report_tool():
    spec = importlib.util.spec_from_file_location("observe_report", REPORT_TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blocked_runtime_wording_preserves_unit_proof_and_names_prerequisite() -> None:
    report_tool = _load_report_tool()
    report = {
        "verification": {
            "scenarios": [
                {
                    "id": "runtime.orchestrator.shutdown",
                    "trigger": (
                        "Record an orchestrator custom metric and terminate the "
                        "process gracefully before the next periodic interval"
                    ),
                },
                {
                    "id": "runtime.mcp.shutdown",
                    "trigger": (
                        "Record an MCP custom metric and terminate the standalone "
                        "MCP process gracefully before the next periodic interval"
                    ),
                },
            ]
        }
    }
    implementation = {
        "telemetry_changes": [
            {
                "id": "OTEL-002.metrics-provider-lifecycle",
                "type": "configuration",
                "change_kind": "modified",
                "name": "custom MeterProvider shutdown lifecycle",
            }
        ]
    }
    proof = {
        "id": "OTEL-002",
        "status": "not_proven",
        "scenarios": [
            {
                "id": "runtime.orchestrator.shutdown",
                "status": "blocked",
                "commands": ["dev-login artifactory --no-browser"],
                "evidence": [".observe/evidence/dev-login-status.txt"],
                "blocking_reason": (
                    "Exact locked dependencies could not be restored because "
                    "Artifactory authentication expired."
                ),
                "unobserved_outcome": (
                    "Final metric delivery from the real orchestrator and MCP "
                    "processes is not yet observed."
                ),
                "observed_telemetry": [],
                "trace_ids": [],
                "product_validation": [],
                "proof_mode": "not_run",
                "visibility": "not_proven",
            },
            {
                "id": "runtime.mcp.shutdown",
                "status": "blocked",
                "commands": ["dev-login artifactory --no-browser"],
                "evidence": [".observe/evidence/dev-login-status.txt"],
                "blocking_reason": (
                    "Exact locked dependencies could not be restored because "
                    "Artifactory authentication expired."
                ),
                "unobserved_outcome": (
                    "Final metric delivery from the real orchestrator and MCP "
                    "processes is not yet observed."
                ),
                "observed_telemetry": [],
                "trace_ids": [],
                "product_validation": [],
                "proof_mode": "not_run",
                "visibility": "not_proven",
            },
        ],
        "item_results": [
            {
                "id": "OTEL-002.metrics-provider-lifecycle",
                "status": "working",
                "direct_assertion_passed": True,
                "scenarios": [
                    "runtime.orchestrator.shutdown",
                    "runtime.mcp.shutdown",
                ],
                "proof_mode": "unit",
                "visibility": "not_explorer_visible",
                "evidence": ["metrics_test.py:408"],
                "observed_telemetry": [
                    "Shutdown logic called provider force_flush and shutdown exactly "
                    "once across repeated cleanup."
                ],
                "product_validation": [
                    "Final process-level OTLP delivery was not exercised."
                ],
            }
        ],
        "remaining": ["Refresh the Artifactory session and restore the lock."],
    }

    rendered = report_tool.render_named_finding_proof(
        report,
        implementation,
        proof,
    )

    assert "Runtime verification unavailable" in rendered
    assert (
        "Exact locked dependencies could not be restored because Artifactory "
        "authentication expired."
    ) in rendered
    assert "Already proven" in rendered
    assert (
        "Shutdown logic called provider force_flush and shutdown exactly once "
        "across repeated cleanup."
    ) in rendered
    assert "Still unobserved" in rendered
    assert (
        "Final metric delivery from the real orchestrator and MCP processes is "
        "not yet observed."
    ) in rendered
    assert ">Proven</strong>" in rendered
    assert "2 checks were blocked." not in rendered
    assert rendered.index("Runtime verification unavailable") < rendered.index(
        "Coverage details"
    )
