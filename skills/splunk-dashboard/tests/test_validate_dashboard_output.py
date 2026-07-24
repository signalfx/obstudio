from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_dashboard_output.py"
SPEC = importlib.util.spec_from_file_location("validate_dashboard_output", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

SHARED_TESTS = Path(__file__).parents[2] / "references" / "tests" / "test_observe_report.py"
SHARED_SPEC = importlib.util.spec_from_file_location(
    "observe_report_test_helpers_for_dashboard", SHARED_TESTS
)
assert SHARED_SPEC and SHARED_SPEC.loader
SHARED = importlib.util.module_from_spec(SHARED_SPEC)
sys.modules[SHARED_SPEC.name] = SHARED
SHARED_SPEC.loader.exec_module(SHARED)
REPORT_MODULE = SHARED.MODULE


def write_bound_flow(root: Path, verification: Path) -> None:
    raw_audit = copy.deepcopy(SHARED.sample_report())
    metrics = (
        ("http.server.request.duration", "Route latency chart"),
        ("http.server.errors.total", "Route error chart"),
    )
    for finding, (name, product_view) in zip(
        raw_audit["findings"], metrics, strict=True
    ):
        finding["expected_telemetry"] = [
            {
                "type": "metric",
                "name": name,
                "attributes": ["service.name"],
                "product_view": product_view,
            }
        ]
    raw_audit["verification"]["scenarios"][0]["expected_signals"] = (
        "http.server.request.duration and http.server.errors.total with service.name"
    )
    audit = REPORT_MODULE.normalize_audit_report(raw_audit)
    audit_sha256 = REPORT_MODULE.audit_digest(audit)
    selection = REPORT_MODULE.normalize_selection(
        {
            "schema_version": 1,
            "kind": "otel-selection",
            "audit_id": audit["meta"]["audit_id"],
            "audit_sha256": audit_sha256,
            "requested_ids": ["OTEL-002"],
            "approved_ids": ["OTEL-001", "OTEL-002"],
        },
        audit,
    )
    instrumentation_rows = []
    item_specs = (
        ("OTEL-001", "OTEL-001.http-duration", metrics[0]),
        ("OTEL-002", "OTEL-002.http-errors", metrics[1]),
    )
    for finding_id, item_id, (name, product_view) in item_specs:
        instrumentation_rows.append(
            {
                "id": finding_id,
                "status": "working",
                "changes": [f"Added the bounded {name} metric recording path."],
                "telemetry_changes": [
                    {
                        "id": item_id,
                        "change_kind": "added",
                        "change": f"Records {name} once per bounded HTTP outcome.",
                        "type": "metric",
                        "name": name,
                        "source": "main.go:42",
                        "added_attributes": ["service.name"],
                        "product_view": product_view,
                        "follow_up_actions": [
                            f"Add {name} to the generated RED dashboard and filter it by service.name."
                        ],
                        "verification_scenarios": ["http.checkout.success"],
                    }
                ],
                "tests": ["go test ./..."],
                "evidence": [".observe/evidence/dashboard-runtime.json"],
                "follow_up_actions": ["Validate the generated dashboard query."],
            }
        )
    instrumentation = REPORT_MODULE.normalize_instrumentation(
        {
            "schema_version": 1,
            "kind": "otel-instrumentation",
            "audit_id": audit["meta"]["audit_id"],
            "audit_sha256": audit_sha256,
            "selection_sha256": REPORT_MODULE.selection_digest(selection),
            "meta": {
                "service_name": "checkout",
                "date": "2026-07-17",
                "result": "Pass",
            },
            "findings": instrumentation_rows,
            "next_steps": ["Generate the RED dashboard."],
        },
        audit,
        selection,
    )
    verify_rows = []
    for finding_id, item_id, (name, product_view) in item_specs:
        verify_rows.append(
            {
                "id": finding_id,
                "status": "working",
                "scenarios": [
                    {
                        "id": "http.checkout.success",
                        "status": "working",
                        "commands": ["go test ./..."],
                        "evidence": [".observe/evidence/dashboard-runtime.json"],
                        "observed_telemetry": [
                            f"Metric {name} emitted with service.name=checkout"
                        ],
                        "trace_ids": [],
                        "product_validation": [product_view],
                        "proof_mode": "full_runtime",
                        "visibility": "explorer_visible",
                    }
                ],
                "item_results": [
                    {
                        "id": item_id,
                        "status": "working",
                        "direct_assertion_passed": True,
                        "scenarios": ["http.checkout.success"],
                        "proof_mode": "full_runtime",
                        "visibility": "explorer_visible",
                        "evidence": [".observe/evidence/dashboard-runtime.json"],
                        "observed_telemetry": [
                            f"Metric {name} emitted with service.name=checkout"
                        ],
                        "product_validation": [product_view],
                    }
                ],
                "remaining": [],
            }
        )
    verify = REPORT_MODULE.normalize_verify(
        {
            "schema_version": 1,
            "kind": "otel-verify",
            "audit_id": audit["meta"]["audit_id"],
            "audit_sha256": audit_sha256,
            "instrumentation_sha256": REPORT_MODULE.instrumentation_digest(
                instrumentation
            ),
            "meta": {
                "service_name": "checkout",
                "date": "2026-07-17",
                "result": "Pass",
                "workflow_mode": "standalone",
                "lifecycle": "final",
            },
            "findings": verify_rows,
            "next_steps": ["Generate the RED dashboard."],
        },
        audit,
        selection,
        instrumentation,
    )
    (root / "otel-audit.json").write_text(json.dumps(audit), encoding="utf-8")
    (root / "otel-selection.json").write_text(
        json.dumps(selection), encoding="utf-8"
    )
    (root / "otel-instrumentation.json").write_text(
        json.dumps(instrumentation), encoding="utf-8"
    )
    verification.write_text(json.dumps(verify, indent=2), encoding="utf-8")


def write_fixture(root: Path) -> argparse.Namespace:
    terraform_dir = root / "terraform"
    terraform_dir.mkdir()
    terraform = terraform_dir / "dashboards.tf"
    terraform.write_text(
        '''resource "signalfx_time_chart" "p99_latency" {
  # telemetry-item: OTEL-001.http-duration
  name = "P99 Latency"
  program_text = <<-EOF
    A = data('http.server.request.duration', filter=filter('service.name', '${var.service_name}')).percentile(pct=99).publish(label='P99 Latency')
  EOF
}

resource "signalfx_time_chart" "error_rate" {
  # telemetry-item: OTEL-002.http-errors
  name = "Error Rate"
  program_text = <<-EOF
    A = data('http.server.errors.total', filter=filter('service.name', '${var.service_name}')).sum().publish(label='Error Rate')
  EOF
}

resource "signalfx_dashboard_group" "overview" {
  name = "${var.service_name} Overview"
}

resource "signalfx_dashboard" "red" {
  name            = "${var.service_name} RED"
  dashboard_group = signalfx_dashboard_group.overview.id

  chart {
    chart_id = signalfx_time_chart.p99_latency.id
    column = 0
    row = 0
    width = 6
    height = 3
  }

  chart {
    chart_id = signalfx_time_chart.error_rate.id
    column = 6
    row = 0
    width = 6
    height = 3
  }
}
''',
        encoding="utf-8",
    )
    variables = terraform_dir / "variables.tf"
    variables.write_text(
        '''variable "service_name" {
  type = string
  default = "checkout"
}

variable "api_token" {
  type      = string
  sensitive = true
}
''',
        encoding="utf-8",
    )
    preview = root / "dashboards.preview.json"
    preview.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "generatedAt": "2026-07-17T00:00:00Z",
                "groups": [
                    {
                        "name": "checkout Overview",
                        "description": "RED dashboard",
                        "dashboards": [
                            {
                                "name": "checkout RED",
                                "description": "Rate, errors, duration",
                                "charts": [
                                    {
                                        "label": "p99_latency",
                                        "title": "P99 Latency",
                                        "chartType": "time_series",
                                        "telemetryItemId": "OTEL-001.http-duration",
                                        "productAction": "Add the verified latency metric to the RED dashboard.",
                                        "programText": "A = data('http.server.request.duration', filter=filter('service.name', 'checkout')).percentile(pct=99).publish(label='P99 Latency')",
                                        "text": None,
                                        "layout": {"column": 0, "row": 0, "width": 6, "height": 3},
                                    },
                                    {
                                        "label": "error_rate",
                                        "title": "Error Rate",
                                        "chartType": "time_series",
                                        "telemetryItemId": "OTEL-002.http-errors",
                                        "productAction": "Add the verified error metric to the RED dashboard.",
                                        "programText": "A = data('http.server.errors.total', filter=filter('service.name', 'checkout')).sum().publish(label='Error Rate')",
                                        "text": None,
                                        "layout": {"column": 6, "row": 0, "width": 6, "height": 3},
                                    },
                                ],
                            }
                        ],
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    report = root / "dashboards.md"
    report.write_text(
        """# Dashboards Report: checkout

**Result:** Partial
**Preview:** `.observe/dashboards.preview.json`

## Panels

| # | Telemetry Item ID | Panel | Metric | Chart Type | Grid (col,row,w,h) | Product action / rationale |
|---|-------------------|-------|--------|------------|--------------------|----------------------------|
| 1 | OTEL-001.http-duration | P99 Latency | http.server.request.duration | time_series | 0,0,6,3 | Add the verified latency metric to the RED dashboard. |
| 2 | OTEL-002.http-errors | Error Rate | http.server.errors.total | time_series | 6,0,6,3 | Add the verified error metric to the RED dashboard. |

## Preview And Validation

| Check | Result | What it proves | Evidence / next step |
|-------|--------|----------------|----------------------|
| Verified metric item mapping | Pass | Exact item provenance | verification item IDs |
| Terraform ↔ preview parity | Pass | Same panels | validator output |
| Observer render | Not run | Local UI render | Open the Dashboards tab |
| Live value sanity | Not run | Query values | Start the Observer and emit traffic |
| Publish/apply | Not run | No live write | Human approval required |
""",
        encoding="utf-8",
    )
    verification = root / "otel-verify.json"
    write_bound_flow(root, verification)
    return argparse.Namespace(
        terraform=terraform,
        preview=preview,
        report=report,
        variables=variables,
        tfvars=None,
        verification=verification,
        legacy_audit=None,
        allow_source_only_item=[],
    )


def edit_preview(path: Path, edit) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data["groups"][0]["dashboards"][0]["charts"])
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def edit_verification(path: Path, edit) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class ValidateDashboardOutputTest(unittest.TestCase):
    def test_accepts_exact_hcl_preview_and_partial_report_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = MODULE.validate(write_fixture(Path(directory)))

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["chart_count"], 2)
        self.assertEqual(result["preview_chart_count"], 2)
        self.assertEqual(result["working_verification_item_count"], 2)
        self.assertEqual(result["reported_status"], "Partial")

    def test_rejects_boolean_schema_version_and_layout_integer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            data = json.loads(args.preview.read_text(encoding="utf-8"))
            data["schemaVersion"] = True
            args.preview.write_text(json.dumps(data), encoding="utf-8")
            result = MODULE.validate(args)
        self.assertEqual(result["result"], "FAIL")
        self.assertIn("preview: schemaVersion must equal 1", result["errors"])

        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            args.terraform.write_text(
                args.terraform.read_text(encoding="utf-8").replace(
                    "chart_id = signalfx_time_chart.p99_latency.id\n    column = 0\n    row = 0",
                    "chart_id = signalfx_time_chart.p99_latency.id\n    column = 0\n    row = 1",
                ),
                encoding="utf-8",
            )
            data = json.loads(args.preview.read_text(encoding="utf-8"))
            data["groups"][0]["dashboards"][0]["charts"][0]["layout"]["row"] = True
            args.preview.write_text(json.dumps(data), encoding="utf-8")
            args.report.write_text(
                args.report.read_text(encoding="utf-8").replace(
                    "time_series | 0,0,6,3 |", "time_series | 0,1,6,3 |"
                ),
                encoding="utf-8",
            )
            result = MODULE.validate(args)
        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any("layout must contain integer" in error for error in result["errors"]),
            result["errors"],
        )

    def test_rejects_layout_outside_observer_signed_int_range_despite_parity(self) -> None:
        for row in (1 << 63, -(1 << 63) - 1):
            with self.subTest(row=row), tempfile.TemporaryDirectory() as directory:
                args = write_fixture(Path(directory))
                args.terraform.write_text(
                    args.terraform.read_text(encoding="utf-8").replace(
                        "chart_id = signalfx_time_chart.p99_latency.id\n    column = 0\n    row = 0",
                        "chart_id = signalfx_time_chart.p99_latency.id\n"
                        f"    column = 0\n    row = {row}",
                    ),
                    encoding="utf-8",
                )
                data = json.loads(args.preview.read_text(encoding="utf-8"))
                data["groups"][0]["dashboards"][0]["charts"][0]["layout"][
                    "row"
                ] = row
                args.preview.write_text(json.dumps(data), encoding="utf-8")
                args.report.write_text(
                    args.report.read_text(encoding="utf-8").replace(
                        "time_series | 0,0,6,3 |",
                        f"time_series | 0,{row},6,3 |",
                    ),
                    encoding="utf-8",
                )

                result = MODULE.validate(args)

            self.assertEqual(result["result"], "FAIL")
            self.assertTrue(
                any(
                    "row must fit the signed 64-bit Observer int range" in error
                    for error in result["errors"]
                ),
                result["errors"],
            )

    def test_observer_int_range_applies_to_every_layout_coordinate(self) -> None:
        for index, name in enumerate(("column", "row", "width", "height")):
            with self.subTest(name=name):
                layout = [0, 0, 1, 1]
                layout[index] = 1 << 63
                errors: list[str] = []

                MODULE.validate_layout(
                    "chart", tuple(layout), "preview dashboard 'service'", errors
                )

                self.assertTrue(
                    any(
                        f"{name} must fit the signed 64-bit Observer int range"
                        in error
                        for error in errors
                    ),
                    errors,
                )

    def test_topology_parity_includes_unused_groups_and_empty_dashboards(self) -> None:
        extra_hcl = '''
resource "signalfx_dashboard_group" "empty_group" {
  name = "checkout Empty Group"
}

resource "signalfx_dashboard" "empty_dashboard" {
  name            = "checkout Empty Dashboard"
  dashboard_group = signalfx_dashboard_group.empty_group.id
}
'''
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            args.terraform.write_text(
                args.terraform.read_text(encoding="utf-8") + extra_hcl,
                encoding="utf-8",
            )
            data = json.loads(args.preview.read_text(encoding="utf-8"))
            data["groups"].append(
                {
                    "name": "checkout Empty Group",
                    "dashboards": [
                        {"name": "checkout Empty Dashboard", "charts": []}
                    ],
                }
            )
            args.preview.write_text(json.dumps(data), encoding="utf-8")
            accepted = MODULE.validate(args)
            self.assertEqual(accepted["result"], "PASS", accepted["errors"])

            data["groups"][1]["dashboards"] = []
            args.preview.write_text(json.dumps(data), encoding="utf-8")
            missing_dashboard = MODULE.validate(args)
        self.assertEqual(missing_dashboard["result"], "FAIL")
        self.assertTrue(
            any("Terraform dashboard" in error and "missing from preview" in error for error in missing_dashboard["errors"]),
            missing_dashboard["errors"],
        )

    def test_accepts_explicit_legacy_working_metric_without_source_only_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            for name in (
                "otel-audit.json",
                "otel-selection.json",
                "otel-instrumentation.json",
                "otel-verify.json",
            ):
                (args.preview.parent / name).unlink()
            replacements = {
                "OTEL-001.http-duration": "SOURCE-METRIC.http.server.request.duration",
                "OTEL-002.http-errors": "SOURCE-METRIC.http.server.errors.total",
            }
            for path in (args.terraform, args.preview, args.report):
                text = path.read_text(encoding="utf-8")
                for old, new in replacements.items():
                    text = text.replace(old, new)
                path.write_text(text, encoding="utf-8")
            legacy = args.preview.parent / "legacy-otel-verify.md"
            legacy.write_text(
                """# OTel Verification Report: checkout

**Result:** Pass

## Tested And Working
| Item ID | OTel item | Type | Added or modified | Working status | How it was tested | Product result / visibility | Evidence |
|---|---|---|---|---|---|---|---|
| SOURCE-METRIC.http.server.request.duration | `http.server.request.duration` | Metric | Existing route duration metric | Working | proof_mode=full_runtime; scenarios=http.success | Route latency data accepted; visibility=otlp_accepted | .observe/evidence/http-duration.json |
| SOURCE-METRIC.http.server.errors.total | `http.server.errors.total` | Metric | Existing route error metric | Working | proof_mode=unit+otlp; scenarios=http.failure | Route error data accepted; visibility=otlp_accepted | .observe/evidence/http-errors.json |
""",
                encoding="utf-8",
            )
            args.verification = None
            args.legacy_verification = legacy
            args.allow_source_only_item = []
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["working_verification_item_count"], 2)

    def test_rejects_bare_legacy_working_labels_as_metric_proof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            for name in (
                "otel-audit.json",
                "otel-selection.json",
                "otel-instrumentation.json",
                "otel-verify.json",
            ):
                (args.preview.parent / name).unlink()
            for path in (args.terraform, args.preview, args.report):
                path.write_text(
                    path.read_text(encoding="utf-8")
                    .replace(
                        "OTEL-001.http-duration",
                        "SOURCE-METRIC.http.server.request.duration",
                    )
                    .replace(
                        "OTEL-002.http-errors",
                        "SOURCE-METRIC.http.server.errors.total",
                    ),
                    encoding="utf-8",
                )
            legacy = args.preview.parent / "legacy-otel-verify.md"
            legacy.write_text(
                """# OTel Verification Report: checkout

**Result:** Pass

## Tested And Working
| OTel item | Type | Working status |
|---|---|---|
| `http.server.request.duration` | Metric | Working |
| `http.server.errors.total` | Metric | Working |
""",
                encoding="utf-8",
            )
            args.verification = None
            args.legacy_verification = legacy
            args.allow_source_only_item = []

            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any("must contain the full" in error for error in result["errors"]),
            result["errors"],
        )

    def test_legacy_working_metric_requires_direct_durable_proof(self) -> None:
        template = """# OTel Verification Report: checkout

**Result:** {result}

## Tested And Working
| Item ID | OTel item | Type | Added or modified | Working status | How it was tested | Product result / visibility | Evidence |
|---|---|---|---|---|---|---|---|
| SOURCE-METRIC.http.server.request.duration | http.server.request.duration | Metric | Existing route metric | Working | {tested} | {product} | {evidence} |
"""
        cases = {
            "not-run proof": {
                "result": "Pass",
                "tested": "proof_mode=not_run; scenarios=none",
                "product": "Route latency; visibility=not_proven",
                "evidence": "main.go:12",
                "expected": "executed proof mode",
            },
            "source-only evidence": {
                "result": "Pass",
                "tested": "proof_mode=full_runtime; scenarios=http.success",
                "product": "Route latency; visibility=otlp_accepted",
                "evidence": "main.go:12",
                "expected": "positive durable evidence",
            },
            "unproven artifact label": {
                "result": "Pass",
                "tested": "proof_mode=full_runtime; scenarios=http.success",
                "product": "Route latency; visibility=otlp_accepted",
                "evidence": ".observe/evidence/not-proven.log",
                "expected": "positive durable evidence",
            },
            "missing product outcome": {
                "result": "Pass",
                "tested": "proof_mode=full_runtime; scenarios=http.success",
                "product": "visibility=otlp_accepted",
                "evidence": ".observe/evidence/http-duration.json",
                "expected": "must name the observed outcome",
            },
            "blocked overall result": {
                "result": "Blocked",
                "tested": "proof_mode=full_runtime; scenarios=http.success",
                "product": "Route latency; visibility=otlp_accepted",
                "evidence": ".observe/evidence/http-duration.json",
                "expected": "cannot contain directly proven Working metrics",
            },
        }
        for name, case in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "otel-verify.md"
                path.write_text(template.format(**case), encoding="utf-8")
                errors: list[str] = []

                metrics = MODULE.legacy_working_metrics(path, errors)

                self.assertEqual(metrics, set())
                self.assertTrue(
                    any(case["expected"] in error for error in errors), errors
                )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "otel-verify.md"
            path.write_text(
                template.format(
                    result="Pass",
                    tested="proof_mode=full_runtime; scenarios=http.failure",
                    product="Failure-path telemetry accepted; visibility=otlp_accepted",
                    evidence=".observe/evidence/http-failure.json",
                ),
                encoding="utf-8",
            )
            errors = []

            metrics = MODULE.legacy_working_metrics(path, errors)

            self.assertEqual(metrics, {"http.server.request.duration"}, errors)
            self.assertEqual(errors, [])

    def test_legacy_working_metric_requires_item_id_for_exact_metric(self) -> None:
        template = """# OTel Verification Report: checkout

**Result:** Pass

## Tested And Working
| Item ID | OTel item | Type | Added or modified | Working status | How it was tested | Product result / visibility | Evidence |
|---|---|---|---|---|---|---|---|
| {item_id} | http.server.request.duration | Metric | Existing route metric | Working | proof_mode=full_runtime; scenarios=http.success | Route latency accepted; visibility=otlp_accepted | .observe/evidence/http-duration.json |
"""
        for item_id in (
            "SOURCE-METRIC.http.server.errors.total",
            "OTEL-001.http-duration",
        ):
            with self.subTest(item_id=item_id), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "otel-verify.md"
                path.write_text(template.format(item_id=item_id), encoding="utf-8")
                errors: list[str] = []

                metrics = MODULE.legacy_working_metrics(path, errors)

                self.assertEqual(metrics, set())
                self.assertTrue(
                    any(
                        "Item ID must equal "
                        "'SOURCE-METRIC.http.server.request.duration'" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_legacy_proof_rejects_duplicate_last_wins_status_header(self) -> None:
        report = """# OTel Verification Report: checkout

**Result:** Pass

## Tested And Working
| Item ID | OTel item | Type | Added or modified | Working status | How it was tested | Product result / visibility | Evidence | Working status |
|---|---|---|---|---|---|---|---|---|
| SOURCE-METRIC.http.server.request.duration | http.server.request.duration | Metric | Existing route metric | Not working | proof_mode=full_runtime; scenarios=http.success | Route latency accepted; visibility=otlp_accepted | .observe/evidence/http-duration.json | Working |
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "otel-verify.md"
            path.write_text(report, encoding="utf-8")
            errors: list[str] = []

            metrics = MODULE.legacy_working_metrics(path, errors)

        self.assertEqual(metrics, set())
        self.assertTrue(
            any("exact item-proof header" in error for error in errors), errors
        )

    def test_canonical_audit_never_falls_back_to_legacy_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            args.verification.unlink()
            legacy = args.preview.parent / "legacy-otel-verify.md"
            legacy.write_text(
                """## Tested And Working
| OTel item | Type | Working status |
|---|---|---|
| `http.server.request.duration` | Metric | Working |
""",
                encoding="utf-8",
            )
            args.verification = None
            args.legacy_verification = legacy
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any("legacy Markdown must not supplement" in error for error in result["errors"]),
            result["errors"],
        )

    def test_rejects_non_bijective_or_mismatched_chart_contracts(self) -> None:
        mutations = {
            "one-to-one": lambda charts: charts.pop(),
            "query": lambda charts: charts[0].__setitem__(
                "programText", charts[0]["programText"].replace("request.duration", "request.wrong")
            ),
            "type": lambda charts: charts[0].__setitem__("chartType", "single_value"),
            "layout": lambda charts: charts[0]["layout"].__setitem__("row", 4),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                args = write_fixture(Path(directory))
                edit_preview(args.preview, mutation)
                result = MODULE.validate(args)
                self.assertEqual(result["result"], "FAIL")
                self.assertTrue(
                    any("parity" in error.lower() for error in result["errors"]),
                    result["errors"],
                )

    def test_rejects_dashboard_or_group_hierarchy_drift(self) -> None:
        mutations = {
            "dashboard": lambda data: data["groups"][0]["dashboards"][0].__setitem__(
                "name", "checkout Wrong"
            ),
            "group": lambda data: data["groups"][0].__setitem__(
                "name", "checkout Wrong"
            ),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                args = write_fixture(Path(directory))
                data = json.loads(args.preview.read_text(encoding="utf-8"))
                mutation(data)
                args.preview.write_text(json.dumps(data, indent=2), encoding="utf-8")
                result = MODULE.validate(args)

            self.assertEqual(result["result"], "FAIL")
            self.assertTrue(
                any(f"{name} name differs" in error for error in result["errors"]),
                result["errors"],
            )

    def test_resource_discovery_ignores_commented_and_string_decoys(self) -> None:
        wrappers = {
            "block comment": lambda source: f"/*\n{source}\n*/\n",
            "heredoc string": lambda source: (
                "locals {\n  decoy = <<-HCL\n"
                f"{source}\n"
                "HCL\n}\n"
            ),
        }
        for name, wrap in wrappers.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                args = write_fixture(Path(directory))
                source = args.terraform.read_text(encoding="utf-8")
                args.terraform.write_text(wrap(source), encoding="utf-8")

                result = MODULE.validate(args)

            self.assertEqual(result["result"], "FAIL")
            self.assertTrue(
                any(
                    "no supported signalfx_*_chart resources found" in error
                    for error in result["errors"]
                ),
                result["errors"],
            )

        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            source = args.terraform.read_text(encoding="utf-8")
            original_mask = MODULE.hcl_structure_mask
            with mock.patch.object(
                MODULE,
                "hcl_structure_mask",
                wraps=original_mask,
            ) as mask:
                blocks = MODULE.resource_blocks(source, MODULE.CHART_RESOURCE)

        self.assertEqual(len(blocks), 2)
        self.assertEqual(
            mask.call_count,
            1,
            "resource brace matching must reuse the precomputed HCL mask",
        )

    def test_rejects_missing_sensitive_api_token_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            args.variables.write_text(
                args.variables.read_text(encoding="utf-8").replace(
                    "sensitive = true", "sensitive = false"
                ),
                encoding="utf-8",
            )
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "Terraform variables: api_token must set sensitive = true",
            result["errors"],
        )

    def test_rejects_stale_or_noncanonical_verification_contracts(self) -> None:
        mutations = {
            "binding": lambda data: data.pop("instrumentation_sha256"),
            "direct assertion": lambda data: data["findings"][0]["item_results"][0].pop(
                "direct_assertion_passed"
            ),
            "static proof": lambda data: data["findings"][0]["item_results"][0].__setitem__(
                "proof_mode", "static"
            ),
            "finding join": lambda data: data["findings"][0]["item_results"][0].__setitem__(
                "id", "OTEL-999.http-duration"
            ),
        }
        expected = {
            "binding": "instrumentation_sha256 must be a canonical sha256:<64 lowercase hex> digest",
            "direct assertion": "direct_assertion_passed must be a boolean",
            "static proof": "working item needs a direct executed proof_mode",
            "finding join": "id must belong to finding OTEL-001",
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                args = write_fixture(Path(directory))
                edit_verification(args.verification, mutation)
                result = MODULE.validate(args)

            self.assertEqual(result["result"], "FAIL")
            self.assertTrue(
                any(expected[name] in error for error in result["errors"]),
                result["errors"],
            )

    def test_invalid_verification_json_and_kind_fail_without_crashing(self) -> None:
        payloads = ("{", json.dumps({"schema_version": 1, "kind": "wrong"}))
        for payload in payloads:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory:
                args = write_fixture(Path(directory))
                args.verification.write_text(payload, encoding="utf-8")
                result = MODULE.validate(args)

            self.assertEqual(result["result"], "FAIL")
            self.assertTrue(result["errors"])

    def test_rejects_verification_that_fails_canonical_flow_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            for filename in (
                "otel-audit.json",
                "otel-selection.json",
                "otel-instrumentation.json",
            ):
                (args.preview.parent / filename).write_text("{}", encoding="utf-8")
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any(
                "canonical audit/selection/instrumentation binding validation failed" in error
                for error in result["errors"]
            ),
            result["errors"],
        )

    def test_rejects_instrumentation_bound_to_a_stale_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            path = args.preview.parent / "otel-instrumentation.json"
            instrumentation = json.loads(path.read_text(encoding="utf-8"))
            instrumentation["selection_sha256"] = "sha256:" + "f" * 64
            path.write_text(json.dumps(instrumentation), encoding="utf-8")

            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any(
                "canonical audit/selection/instrumentation binding validation failed"
                in error
                for error in result["errors"]
            ),
            result["errors"],
        )

    def test_uses_the_exact_bound_flow_snapshot_that_was_validated(self) -> None:
        original_metric = "http.server.request.duration"
        forged_metric = "custom.post-validation.metric"
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            for path in (args.terraform, args.preview, args.report):
                path.write_text(
                    path.read_text(encoding="utf-8").replace(
                        original_metric, forged_metric
                    ),
                    encoding="utf-8",
                )
            original_run = MODULE.subprocess.run

            def mutate_after_validation(*command_args, **command_kwargs):
                completed = original_run(*command_args, **command_kwargs)
                instrumentation_path = (
                    args.preview.parent / "otel-instrumentation.json"
                )
                instrumentation = json.loads(
                    instrumentation_path.read_text(encoding="utf-8")
                )
                instrumentation["findings"][0]["telemetry_changes"][0][
                    "name"
                ] = forged_metric
                instrumentation_path.write_text(
                    json.dumps(instrumentation), encoding="utf-8"
                )
                verification = json.loads(
                    args.verification.read_text(encoding="utf-8")
                )
                verification["findings"][0]["scenarios"][0][
                    "observed_telemetry"
                ] = [f"{forged_metric} emitted with service.name=checkout"]
                verification["findings"][0]["item_results"][0][
                    "observed_telemetry"
                ] = [f"{forged_metric} emitted with service.name=checkout"]
                args.verification.write_text(
                    json.dumps(verification), encoding="utf-8"
                )
                return completed

            with mock.patch.object(
                MODULE.subprocess, "run", side_effect=mutate_after_validation
            ):
                result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any(
                "does not exactly match bound instrumentation item name" in error
                or "is absent from working item" in error
                for error in result["errors"]
            ),
            result["errors"],
        )

    def test_rejects_missing_or_incorrect_panel_metric(self) -> None:
        replacements = {
            "missing column": ("| Metric |", "| Signal |"),
            "wrong value": ("| http.server.request.duration |", "| wrong.metric |"),
        }
        for name, (old, new) in replacements.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                args = write_fixture(Path(directory))
                args.report.write_text(
                    args.report.read_text(encoding="utf-8").replace(old, new),
                    encoding="utf-8",
                )
                result = MODULE.validate(args)

            self.assertEqual(result["result"], "FAIL")
            self.assertTrue(
                any("Panels" in error for error in result["errors"]),
                result["errors"],
            )

    def test_hcl_heredoc_preserves_plain_and_dedents_indented_forms(self) -> None:
        plain = "program_text = <<EOF\n    A = data('metric')\nEOF"
        indented = "program_text = <<-EOF\n    A = data('metric')\n  EOF"

        self.assertEqual(MODULE.hcl_heredoc(plain, "program_text"), "    A = data('metric')")
        self.assertEqual(MODULE.hcl_heredoc(indented, "program_text"), "A = data('metric')")

    def test_rejects_unresolved_preview_variables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            edit_preview(
                args.preview,
                lambda charts: charts[0].__setitem__(
                    "programText", charts[0]["programText"].replace("checkout", "${var.service_name}")
                ),
            )
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(any("unresolved Terraform variable" in error for error in result["errors"]))

    def test_rejects_overlap_even_when_hcl_and_preview_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            source = args.terraform.read_text(encoding="utf-8").replace(
                "chart_id = signalfx_time_chart.error_rate.id\n    column = 6",
                "chart_id = signalfx_time_chart.error_rate.id\n    column = 5",
            )
            args.terraform.write_text(source, encoding="utf-8")
            edit_preview(args.preview, lambda charts: charts[1]["layout"].__setitem__("column", 5))
            args.report.write_text(
                args.report.read_text(encoding="utf-8").replace("| 2 | OTEL-002.http-errors | Error Rate | http.server.errors.total | time_series | 6,0,6,3 |", "| 2 | OTEL-002.http-errors | Error Rate | http.server.errors.total | time_series | 5,0,6,3 |"),
                encoding="utf-8",
            )
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(any("overlap" in error for error in result["errors"]), result["errors"])

    def test_rejects_out_of_bounds_grid_even_when_hcl_and_preview_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            source = args.terraform.read_text(encoding="utf-8").replace(
                "chart_id = signalfx_time_chart.error_rate.id\n    column = 6",
                "chart_id = signalfx_time_chart.error_rate.id\n    column = 7",
            )
            args.terraform.write_text(source, encoding="utf-8")
            edit_preview(args.preview, lambda charts: charts[1]["layout"].__setitem__("column", 7))
            args.report.write_text(
                args.report.read_text(encoding="utf-8").replace(
                    "| 2 | OTEL-002.http-errors | Error Rate | http.server.errors.total | time_series | 6,0,6,3 |",
                    "| 2 | OTEL-002.http-errors | Error Rate | http.server.errors.total | time_series | 7,0,6,3 |",
                ),
                encoding="utf-8",
            )
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertGreaterEqual(
            sum("width must fit within the 12-column grid" in error for error in result["errors"]),
            2,
            result["errors"],
        )

    def test_rejects_query_without_service_filter_even_when_parity_matches(self) -> None:
        replacement = "A = data('http.server.request.duration').percentile(pct=99).publish(label='P99 Latency')"
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            source = args.terraform.read_text(encoding="utf-8")
            source = source.replace(
                "A = data('http.server.request.duration', filter=filter('service.name', '${var.service_name}')).percentile(pct=99).publish(label='P99 Latency')",
                replacement,
            )
            args.terraform.write_text(source, encoding="utf-8")
            edit_preview(args.preview, lambda charts: charts[0].__setitem__("programText", replacement))
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertGreaterEqual(
            sum("missing service.name or sf_service filter" in error for error in result["errors"]),
            2,
        )

    def test_rejects_unstable_telemetry_item_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            args.terraform.write_text(
                args.terraform.read_text(encoding="utf-8").replace(
                    "# telemetry-item: OTEL-001.http-duration",
                    "# telemetry-item: http-duration",
                ),
                encoding="utf-8",
            )
            edit_preview(
                args.preview,
                lambda charts: charts[0].__setitem__("telemetryItemId", "http-duration"),
            )
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(any("OTEL-###" in error for error in result["errors"]), result["errors"])

    def test_rejects_stable_but_invented_item_not_in_working_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            args.terraform.write_text(
                args.terraform.read_text(encoding="utf-8").replace(
                    "OTEL-001.http-duration", "OTEL-999.invented-metric"
                ),
                encoding="utf-8",
            )
            edit_preview(
                args.preview,
                lambda charts: charts[0].__setitem__(
                    "telemetryItemId", "OTEL-999.invented-metric"
                ),
            )
            args.report.write_text(
                args.report.read_text(encoding="utf-8").replace(
                    "OTEL-001.http-duration", "OTEL-999.invented-metric"
                ),
                encoding="utf-8",
            )
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "provenance: chart item 'OTEL-999.invented-metric' is not a Working verification item",
            result["errors"],
        )

    def test_rejects_working_span_item_as_dashboard_metric_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            errors: list[str] = []
            preview = MODULE.parse_preview(args.preview, errors)
            instrumentation = json.loads(
                (args.preview.parent / "otel-instrumentation.json").read_text(
                    encoding="utf-8"
                )
            )
            items = {
                item["id"]: item
                for finding in instrumentation["findings"]
                for item in finding["telemetry_changes"]
            }
            items["OTEL-001.http-duration"] = {
                **items["OTEL-001.http-duration"],
                "type": "span",
            }
            MODULE.validate_item_provenance(
                preview, args.verification, items, set(), set(), errors
            )

        self.assertTrue(
            any("instrumentation type 'span', expected 'metric'" in error for error in errors),
            errors,
        )

    def test_text_chart_still_requires_bound_metric_item(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            errors: list[str] = []
            parsed = MODULE.parse_preview(args.preview, errors)
            chart = parsed["p99_latency"]
            preview = {
                "p99_latency": MODULE.PreviewChart(
                    chart.label,
                    chart.title,
                    "text",
                    None,
                    "Bound metric explanation",
                    chart.telemetry_item_id,
                    chart.product_action,
                    chart.layout,
                    chart.dashboard,
                    chart.group,
                )
            }
            instrumentation = json.loads(
                (args.preview.parent / "otel-instrumentation.json").read_text(
                    encoding="utf-8"
                )
            )
            items = {
                item["id"]: item
                for finding in instrumentation["findings"]
                for item in finding["telemetry_changes"]
            }
            items[chart.telemetry_item_id] = {
                **items[chart.telemetry_item_id],
                "type": "span",
            }
            MODULE.validate_item_provenance(
                preview, args.verification, items, set(), set(), errors
            )

        self.assertTrue(
            any("instrumentation type 'span', expected 'metric'" in error for error in errors),
            errors,
        )

    def test_rejects_isolated_verify_without_canonical_companions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            for name in (
                "otel-audit.json",
                "otel-selection.json",
                "otel-instrumentation.json",
            ):
                (args.preview.parent / name).unlink()
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any("canonical verification companions are incomplete" in error for error in result["errors"]),
            result["errors"],
        )

    def test_rejects_working_item_without_direct_proof_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            data = json.loads(args.verification.read_text(encoding="utf-8"))
            data["findings"][0]["item_results"][0] = {
                "id": "OTEL-001.http-duration",
                "status": "working",
            }
            args.verification.write_text(json.dumps(data), encoding="utf-8")
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any("working item needs non-empty evidence" in error for error in result["errors"]),
            result["errors"],
        )

    def test_rejects_chart_metric_absent_from_working_item_observation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            data = json.loads(args.verification.read_text(encoding="utf-8"))
            data["findings"][0]["item_results"][0]["observed_telemetry"] = [
                "some.other.metric emitted"
            ]
            args.verification.write_text(json.dumps(data), encoding="utf-8")
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any(
                "absent from working item" in error
                or "must reference the exact telemetry item" in error
                for error in result["errors"]
            ),
            result["errors"],
        )

    def test_rejects_prefix_collision_and_negated_metric_observation(self) -> None:
        observations = (
            "http.server.request.duration.total emitted",
            "did not observe http.server.request.duration",
            "http.server.request.duration did not emit",
            "http.server.request.duration was absent",
            "http.server.request.duration is missing",
            "http.server.request.duration could not be found",
            "could not find http.server.request.duration",
            "did not find http.server.request.duration",
            "never found http.server.request.duration",
            "unable to find http.server.request.duration",
            "no evidence of http.server.request.duration",
            "http.server.request.duration was not present",
            "http.server.request.duration was unavailable",
            "http.server.request.duration could not be observed",
            "http.server.request.duration yielded no data",
        )
        for observation in observations:
            with self.subTest(observation=observation), tempfile.TemporaryDirectory() as directory:
                args = write_fixture(Path(directory))
                data = json.loads(args.verification.read_text(encoding="utf-8"))
                data["findings"][0]["item_results"][0]["observed_telemetry"] = [
                    observation
                ]
                args.verification.write_text(json.dumps(data), encoding="utf-8")
                result = MODULE.validate(args)

            self.assertEqual(result["result"], "FAIL")
            self.assertTrue(
                any(
                    "absent from working item" in error
                    or "must reference the exact telemetry item" in error
                    for error in result["errors"]
                ),
                result["errors"],
            )

    def test_exact_metric_observation_accepts_clause_and_selector_forms(self) -> None:
        metric = "http.server.request.duration"
        self.assertTrue(
            MODULE.exact_metric_observed(
                metric,
                "No errors occurred. http.server.request.duration emitted",
            )
        )
        self.assertTrue(
            MODULE.exact_metric_observed(
                metric,
                "http.server.request.duration{service.name=checkout} emitted",
            )
        )

    def test_accepts_audit_only_source_metric_and_rejects_partial_downstream(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            item_id = "SOURCE-METRIC.http.server.request.duration"
            args.terraform.write_text(
                args.terraform.read_text(encoding="utf-8")
                .replace("OTEL-001.http-duration", item_id)
                .replace(
                    "resource \"signalfx_time_chart\" \"error_rate\" {",
                    "# removed second chart for this source-only fixture\n"
                    "resource \"signalfx_time_chart\" \"error_rate_removed\" {",
                ),
                encoding="utf-8",
            )
            source = args.terraform.read_text(encoding="utf-8")
            start = source.index('resource "signalfx_time_chart" "error_rate_removed"')
            end = source.index('resource "signalfx_dashboard_group" "overview"')
            source = source[:start] + source[end:]
            chart_start = source.index("  chart {", source.index('resource "signalfx_dashboard"'))
            second_start = source.index("  chart {", chart_start + 1)
            second_end = source.index("  }", second_start) + len("  }\n")
            args.terraform.write_text(source[:second_start] + source[second_end:], encoding="utf-8")
            edit_preview(
                args.preview,
                lambda charts: (
                    charts[0].__setitem__("telemetryItemId", item_id),
                    charts.pop(),
                ),
            )
            report = args.report.read_text(encoding="utf-8")
            report = report.replace("OTEL-001.http-duration", item_id)
            report = "\n".join(
                line for line in report.splitlines() if "OTEL-002.http-errors" not in line
            ) + "\n"
            args.report.write_text(report, encoding="utf-8")
            for name in (
                "otel-selection.json",
                "otel-instrumentation.json",
                "otel-verify.json",
            ):
                (args.preview.parent / name).unlink()
            args.verification = None
            args.allow_source_only_item = [item_id]
            missing_source = MODULE.validate(args)

            audit_path = args.preview.parent / "otel-audit.json"
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            audit["current_instrumentation"]["metrics"] = [
                {
                    "name": "http.server.request.duration",
                    "source": "metrics.go:12",
                    "type": "histogram",
                }
            ]
            audit_path.write_text(json.dumps(audit), encoding="utf-8")
            result = MODULE.validate(args)

            legacy = args.preview.parent / "legacy-otel-verify.md"
            legacy.write_text("legacy proof must not be read\n", encoding="utf-8")
            args.legacy_verification = legacy
            audit_with_legacy = MODULE.validate(args)
            args.legacy_verification = None

            legacy_audit = args.preview.parent / "otel.md"
            legacy_audit.write_text(
                """# Observability Report: checkout

### Metrics

| Name | Source | Type |
|---|---|---|
| http.server.request.duration | metrics.go:12 | histogram |

## Instrumentation
""",
                encoding="utf-8",
            )
            canonical_audit = audit_path.read_text(encoding="utf-8")
            args.legacy_audit = legacy_audit
            canonical_with_legacy_audit = MODULE.validate(args)
            audit_path.unlink()
            legacy_source_only = MODULE.validate(args)
            args.legacy_audit = None
            audit_path.write_text(canonical_audit, encoding="utf-8")

            (args.preview.parent / "otel-selection.json").write_text(
                "{}", encoding="utf-8"
            )
            partial_downstream = MODULE.validate(args)

        self.assertEqual(missing_source["result"], "FAIL")
        self.assertTrue(
            any(
                "exact metric is absent from audit current_instrumentation.metrics"
                in error
                for error in missing_source["errors"]
            ),
            missing_source["errors"],
        )
        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(audit_with_legacy["result"], "FAIL")
        self.assertTrue(
            any(
                "legacy Markdown must not supplement" in error
                for error in audit_with_legacy["errors"]
            ),
            audit_with_legacy["errors"],
        )
        self.assertEqual(canonical_with_legacy_audit["result"], "FAIL")
        self.assertTrue(
            any(
                "legacy audit Markdown must not supplement" in error
                for error in canonical_with_legacy_audit["errors"]
            ),
            canonical_with_legacy_audit["errors"],
        )
        self.assertEqual(legacy_source_only["result"], "PASS", legacy_source_only["errors"])
        self.assertEqual(partial_downstream["result"], "FAIL")
        self.assertTrue(
            any(
                "canonical otel-verify.json is required" in error
                for error in partial_downstream["errors"]
            ),
            partial_downstream["errors"],
        )

    def test_legacy_audit_source_metric_inventory_is_exact_and_unambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "otel.md"
            path.write_text(
                """# Observability Report: checkout

### Metrics

| Name | Source | Type |
|---|---|---|
| http.server.request.duration | otelhttp | auto |
| checkout.payment.errors | metrics.go:42 | custom |

## Instrumentation
""",
                encoding="utf-8",
            )
            errors: list[str] = []
            item_ids = MODULE.legacy_audit_source_metric_ids(path, errors)

            duplicate = path.read_text(encoding="utf-8").replace(
                "| checkout.payment.errors | metrics.go:42 | custom |",
                "| checkout.payment.errors | metrics.go:42 | custom |\n"
                "| http.server.request.duration | duplicate | auto |",
            )
            path.write_text(duplicate, encoding="utf-8")
            duplicate_errors: list[str] = []
            MODULE.legacy_audit_source_metric_ids(path, duplicate_errors)

            path.write_text(
                duplicate.replace("### Metrics", "## Metrics"), encoding="utf-8"
            )
            heading_errors: list[str] = []
            MODULE.legacy_audit_source_metric_ids(path, heading_errors)

        self.assertEqual(errors, [])
        self.assertEqual(
            item_ids,
            {
                "SOURCE-METRIC.http.server.request.duration",
                "SOURCE-METRIC.checkout.payment.errors",
            },
        )
        self.assertTrue(
            any("duplicate legacy metric" in error for error in duplicate_errors),
            duplicate_errors,
        )
        self.assertTrue(
            any("exactly one Metrics heading" in error for error in heading_errors),
            heading_errors,
        )

    def test_rejects_source_metric_id_that_does_not_match_data_metric(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            item_id = "SOURCE-METRIC.wrong.metric"
            args.terraform.write_text(
                args.terraform.read_text(encoding="utf-8").replace(
                    "OTEL-001.http-duration", item_id
                ),
                encoding="utf-8",
            )
            edit_preview(
                args.preview,
                lambda charts: charts[0].__setitem__("telemetryItemId", item_id),
            )
            args.report.write_text(
                args.report.read_text(encoding="utf-8").replace(
                    "OTEL-001.http-duration", item_id
                ),
                encoding="utf-8",
            )
            args.allow_source_only_item = [item_id]
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any("SOURCE-METRIC.<exact data() metric>" in error for error in result["errors"]),
            result["errors"],
        )

    def test_rejects_pass_report_without_render_and_live_value_proof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            args.report.write_text(
                args.report.read_text(encoding="utf-8").replace(
                    "**Result:** Partial", "**Result:** Pass"
                ),
                encoding="utf-8",
            )
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "report: Result Pass requires Observer render and Live value sanity to be Pass",
            result["errors"],
        )

    def test_all_direct_evidence_rows_reject_negative_pass_claims(self) -> None:
        contradictions = {
            "Verified metric item mapping": (
                "verification item IDs",
                "without verification item IDs",
            ),
            "Terraform ↔ preview parity": (
                "validator output",
                "validator not-run for dashboards.tf",
            ),
            "Observer render": (
                "saved Observer screenshot render witness",
                "missing Observer screenshot render witness",
            ),
            "Live value sanity": (
                "saved recent-window query series evidence",
                "absent query series evidence for recent-window",
            ),
        }
        for row_name, (valid, contradictory) in contradictions.items():
            with self.subTest(row=row_name), tempfile.TemporaryDirectory() as directory:
                args = write_fixture(Path(directory))
                report = args.report.read_text(encoding="utf-8")
                report = report.replace("**Result:** Partial", "**Result:** Pass")
                report = report.replace(
                    "| Observer render | Not run | Local UI render | Open the Dashboards tab |",
                    "| Observer render | Pass | Local UI render | saved Observer screenshot render witness |",
                )
                report = report.replace(
                    "| Live value sanity | Not run | Query values | Start the Observer and emit traffic |",
                    "| Live value sanity | Pass | Query values | saved recent-window query series evidence |",
                )
                report = report.replace(valid, contradictory, 1)
                args.report.write_text(report, encoding="utf-8")

                result = MODULE.validate(args)

            self.assertEqual(result["result"], "FAIL")
            self.assertIn(
                f"report: {row_name} Pass row contradicts its negative or uncertain evidence",
                result["errors"],
            )

    def test_accepts_pass_report_with_direct_render_and_value_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            report = args.report.read_text(encoding="utf-8")
            report = report.replace("**Result:** Partial", "**Result:** Pass")
            report = report.replace(
                "| Observer render | Not run | Local UI render | Open the Dashboards tab |",
                "| Observer render | Pass | Local UI render | saved Observer screenshot render witness |",
            )
            report = report.replace(
                "| Live value sanity | Not run | Query values | Start the Observer and emit traffic |",
                "| Live value sanity | Pass | Query values | saved recent-window query series evidence |",
            )
            args.report.write_text(report, encoding="utf-8")
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "PASS", result["errors"])

    def test_rejects_pass_rows_with_negative_or_uncertain_direct_evidence(self) -> None:
        mutations = {
            "Observer render": (
                "saved Observer screenshot render witness",
                "Observer screenshot could not be captured; no render witness is available",
            ),
            "Live value sanity": (
                "saved recent-window query series evidence",
                "recent-window query may have returned series; result remains pending",
            ),
        }
        for check, (positive, contradictory) in mutations.items():
            with self.subTest(check=check), tempfile.TemporaryDirectory() as directory:
                args = write_fixture(Path(directory))
                report = args.report.read_text(encoding="utf-8")
                report = report.replace("**Result:** Partial", "**Result:** Pass")
                report = report.replace(
                    "| Observer render | Not run | Local UI render | Open the Dashboards tab |",
                    "| Observer render | Pass | Local UI render | saved Observer screenshot render witness |",
                )
                report = report.replace(
                    "| Live value sanity | Not run | Query values | Start the Observer and emit traffic |",
                    "| Live value sanity | Pass | Query values | saved recent-window query series evidence |",
                )
                report = report.replace(positive, contradictory)
                args.report.write_text(report, encoding="utf-8")
                result = MODULE.validate(args)

            self.assertEqual(result["result"], "FAIL")
            self.assertIn(
                f"report: {check} Pass row contradicts its negative or uncertain evidence",
                result["errors"],
            )

    def test_rejects_all_checks_pass_partial_without_parent_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            report = args.report.read_text(encoding="utf-8")
            report = report.replace(
                "| Observer render | Not run | Local UI render | Open the Dashboards tab |",
                "| Observer render | Pass | Local UI render | saved Observer screenshot render witness |",
            )
            report = report.replace(
                "| Live value sanity | Not run | Query values | Start the Observer and emit traffic |",
                "| Live value sanity | Pass | Query values | saved recent-window query series evidence |",
            )
            args.report.write_text(report, encoding="utf-8")
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "report: Result Partial is inconsistent when all required preview checks pass",
            result["errors"],
        )

    def test_rejects_pass_rows_without_direct_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            report = args.report.read_text(encoding="utf-8")
            report = report.replace("**Result:** Partial", "**Result:** Pass")
            report = report.replace("Observer render | Not run", "Observer render | Pass")
            report = report.replace("Live value sanity | Not run", "Live value sanity | Pass")
            args.report.write_text(report, encoding="utf-8")
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn("report: Observer render Pass row lacks direct evidence", result["errors"])
        self.assertIn("report: Live value sanity Pass row lacks direct evidence", result["errors"])

    def test_rejects_report_that_claims_failed_deterministic_parity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_fixture(Path(directory))
            args.report.write_text(
                args.report.read_text(encoding="utf-8").replace(
                    "| Terraform ↔ preview parity | Pass |",
                    "| Terraform ↔ preview parity | Fail |",
                ),
                encoding="utf-8",
            )
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "report: Terraform ↔ preview parity must be Pass after deterministic validation",
            result["errors"],
        )


if __name__ == "__main__":
    unittest.main()
