from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_configure_output.py"
SKILL = Path(__file__).parents[1] / "SKILL.md"
SPEC = importlib.util.spec_from_file_location("validate_configure_output", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

DASHBOARD_TESTS = (
    Path(__file__).parents[2]
    / "splunk-dashboard"
    / "tests"
    / "test_validate_dashboard_output.py"
)
DASHBOARD_SPEC = importlib.util.spec_from_file_location(
    "dashboard_test_helpers_for_configure", DASHBOARD_TESTS
)
assert DASHBOARD_SPEC and DASHBOARD_SPEC.loader
DASHBOARD_HELPERS = importlib.util.module_from_spec(DASHBOARD_SPEC)
sys.modules[DASHBOARD_SPEC.name] = DASHBOARD_HELPERS
DASHBOARD_SPEC.loader.exec_module(DASHBOARD_HELPERS)

METRIC = "http.server.request.duration"


def write_validation_fixture(
    root: Path,
    *,
    detector_metric: str = METRIC,
    verified_metric: str = METRIC,
) -> argparse.Namespace:
    terraform_dir = root / "terraform"
    terraform_dir.mkdir()
    (terraform_dir / "detectors.tf").write_text(
        f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{detector_metric}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
        encoding="utf-8",
    )
    (terraform_dir / "variables.tf").write_text(
        '''variable "api_token" {
  type      = string
  sensitive = true
}

variable "realm" {
  type = string
}

variable "service_name" {
  type = string
}
''',
        encoding="utf-8",
    )
    (terraform_dir / "terraform.tfvars.example").write_text(
        'api_token   = ""\nrealm      = "us0"\nservice_name = "checkout"\n',
        encoding="utf-8",
    )
    (terraform_dir / ".gitignore").write_text(
        ".terraform/\n*.tfstate\n*.tfstate.*\nterraform.tfvars\n",
        encoding="utf-8",
    )
    detectors_report = root / "detectors.md"
    detectors_report.write_text(
        f"# Detectors\n\n**Result:** Pass\n\nGenerated `{detector_metric}` detector.\n",
        encoding="utf-8",
    )
    configure_verify_report = root / "splunk-configure-verify.md"
    configure_verify_report.write_text(
        """# Splunk Configure Verification

**Result:** Pass

## Executive Summary
Validation passed.

## What Was Added
One detector.

## Tested And Working
| Check | Result | Evidence |
|---|---|---|
| Authenticated detector SignalFlow compile | Pass | Authenticated `terraform plan -refresh=false -input=false` accepted all generated detectors through `/v2/detector/validate`. |

## Not Yet Proven
None.

## Validation Notes
Publishing/applying was not run because it is not required for configure verification.

## Next Steps
Apply with credentials.
""",
        encoding="utf-8",
    )
    verify_report = root / "otel-verify.md"
    verify_report.write_text(
        f"""## Tested And Working
| OTel item | Type | Added or modified | Working status | How it was tested | Evidence |
|---|---|---|---|---|---|
| `{verified_metric}` | Metric | Exporter | Working | OTLP | collector |
""",
        encoding="utf-8",
    )
    return argparse.Namespace(
        terraform_dir=terraform_dir,
        detectors_report=detectors_report,
        configure_verify_report=configure_verify_report,
        verify_report=verify_report,
        allow_source_only_metric=[],
    )


def write_canonical_reader_report(args: argparse.Namespace) -> None:
    root = args.terraform_dir.parent
    instrumentation = json.loads(
        (root / "otel-instrumentation.json").read_text(encoding="utf-8")
    )
    verification = json.loads(
        (root / "otel-verify.json").read_text(encoding="utf-8")
    )
    proofs = {
        item["id"]: item
        for finding in verification["findings"]
        for item in finding["item_results"]
    }
    status_labels = {
        "working": "Working",
        "not_working": "Not working",
        "not_proven": "Not proven",
        "not_configured": "Not configured",
        "blocked": "Not proven",
    }
    rows = []
    non_working = []
    for finding in instrumentation["findings"]:
        for source in finding["telemetry_changes"]:
            proof = proofs[source["id"]]
            status = status_labels[proof["status"]]
            if status != "Working":
                non_working.append(source["id"])
            rows.append(
                "| {id} | {name} | {type} | {change} | {status} | {tested} | "
                "{product} | {evidence} |".format(
                    id=source["id"],
                    name=source["name"],
                    type=source["type"],
                    change=source["change"],
                    status=status,
                    tested="; ".join(proof["observed_telemetry"]),
                    product="; ".join(proof["product_validation"]),
                    evidence="; ".join(proof["evidence"]),
                )
            )
    working = len(rows) - len(non_working)
    gaps = "None." if not non_working else "\n".join(f"- {item}" for item in non_working)
    args.verify_report.write_text(
        f"""# OpenTelemetry Verification Report

**Result:** {verification['meta']['result']}

## What Changed
Canonical verification results were projected for readers.

## Tested And Working
**Individual result:** {working}/{len(rows)} working: metrics {working}/{len(rows)}.

| Item ID | OTel item | Type | Added or modified | Working status | How it was tested | Product result / visibility | Evidence |
|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

## Not Working Or Not Proven
{gaps}

## Proof
Canonical JSON contains the bound commands and evidence.
""",
        encoding="utf-8",
    )


def write_canonical_configure_flow(args: argparse.Namespace) -> None:
    root = args.terraform_dir.parent
    DASHBOARD_HELPERS.write_bound_flow(root, root / "otel-verify.json")
    write_canonical_reader_report(args)


def add_scenario_only_metric_to_canonical_flow(
    args: argparse.Namespace, metric: str
) -> None:
    root = args.terraform_dir.parent
    report_module = DASHBOARD_HELPERS.REPORT_MODULE
    audit = json.loads((root / "otel-audit.json").read_text(encoding="utf-8"))
    audit["findings"][0]["expected_telemetry"].append(
        {
            "type": "metric",
            "name": metric,
            "attributes": ["service.name"],
            "product_view": "Request size chart",
        }
    )
    audit = report_module.normalize_audit_report(audit)
    audit_digest = report_module.audit_digest(audit)

    selection = json.loads(
        (root / "otel-selection.json").read_text(encoding="utf-8")
    )
    selection["audit_sha256"] = audit_digest
    selection = report_module.normalize_selection(selection, audit)

    instrumentation = json.loads(
        (root / "otel-instrumentation.json").read_text(encoding="utf-8")
    )
    instrumentation["audit_sha256"] = audit_digest
    instrumentation["selection_sha256"] = report_module.selection_digest(selection)
    instrumentation = report_module.normalize_instrumentation(
        instrumentation, audit, selection
    )

    verification = json.loads(
        (root / "otel-verify.json").read_text(encoding="utf-8")
    )
    verification["audit_sha256"] = audit_digest
    verification["instrumentation_sha256"] = report_module.instrumentation_digest(
        instrumentation
    )
    verification["findings"][0]["scenarios"][0]["observed_telemetry"].append(
        f"Metric {metric} emitted with service.name=checkout"
    )
    verification = report_module.normalize_verify(
        verification, audit, selection, instrumentation
    )

    (root / "otel-audit.json").write_text(json.dumps(audit), encoding="utf-8")
    (root / "otel-selection.json").write_text(
        json.dumps(selection), encoding="utf-8"
    )
    (root / "otel-instrumentation.json").write_text(
        json.dumps(instrumentation), encoding="utf-8"
    )
    (root / "otel-verify.json").write_text(
        json.dumps(verification), encoding="utf-8"
    )
    write_canonical_reader_report(args)


def write_dashboard_fixture(
    args: argparse.Namespace,
    *,
    result: str = "Pass",
    observer_result: str = "Pass",
    live_value_result: str = "Pass",
) -> None:
    (args.terraform_dir / "dashboards.tf").write_text(
        '''resource "signalfx_time_chart" "latency" {
  # telemetry-item: OTEL-001.http-duration
  name = "P99 Latency"
  program_text = <<-EOF
    data('http.server.request.duration', filter=filter('service.name', 'checkout')).percentile(pct=99).publish(label='P99 Latency')
  EOF
}

resource "signalfx_dashboard_group" "overview" {
  name = "Checkout Overview"
}

resource "signalfx_dashboard" "red" {
  name            = "Checkout RED"
  dashboard_group = signalfx_dashboard_group.overview.id
  chart {
    chart_id = signalfx_time_chart.latency.id
    column   = 0
    row      = 0
    width    = 6
    height   = 3
  }
}
''',
        encoding="utf-8",
    )
    (args.terraform_dir.parent / "dashboards.preview.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "groups": [
                    {
                        "name": "Checkout Overview",
                        "dashboards": [
                            {
                                "name": "Checkout RED",
                                "charts": [
                                    {
                                        "label": "latency",
                                        "title": "P99 Latency",
                                        "chartType": "time_series",
                                        "telemetryItemId": "OTEL-001.http-duration",
                                        "productAction": "Add the verified latency metric to the RED dashboard.",
                                        "programText": "data('http.server.request.duration', filter=filter('service.name', 'checkout')).percentile(pct=99).publish(label='P99 Latency')",
                                        "text": None,
                                        "layout": {
                                            "column": 0,
                                            "row": 0,
                                            "width": 6,
                                            "height": 3,
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (args.terraform_dir.parent / "dashboards.md").write_text(
        f"""# Dashboards Report: checkout

**Result:** {result}
**Preview:** `.observe/dashboards.preview.json`

## Panels

| # | Telemetry Item ID | Panel | Metric | Chart Type | Grid (col,row,w,h) | Product action / rationale |
|---|---|---|---|---|---|---|
| 1 | OTEL-001.http-duration | P99 Latency | http.server.request.duration | time_series | 0,0,6,3 | Add the verified latency metric to the RED dashboard. |

## Preview And Validation

| Check | Result | What it proves | Evidence / next step |
|---|---|---|---|
| Verified metric item mapping | Pass | Every chart maps to a working telemetry item | `OTEL-001.http-duration` and verification evidence |
| Terraform ↔ preview parity | Pass | HCL and sidecar agree | `validate_dashboard_output.py` validator passed for 1 chart |
| Observer render | {observer_result} | Observer accepted and rendered the sidecar | local Observer render witness for 1 chart |
| Live value sanity | {live_value_result} | Query returned plausible values and dimensions | saved recent-window query evidence for `http.server.request.duration` |
| Publish/apply | Not run | Review remains local | publish only after human approval |
""",
        encoding="utf-8",
    )
    write_canonical_configure_flow(args)


class WorkingMetricsTest(unittest.TestCase):
    def test_reads_working_metric_on_python_39_compatible_path(self) -> None:
        report = """## Tested And Working
| OTel item | Type | Added or modified | Working status | How it was tested | Evidence |
|---|---|---|---|---|---|
| `http.server.request.duration` | Metric | Exporter | Working | OTLP | collector |
| `http.server.active_requests` | Metric | Exporter | Not proven | OTLP | absent |
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "otel-verify.md"
            path.write_text(report, encoding="utf-8")
            self.assertEqual(
                MODULE.working_metrics(path),
                {"http.server.request.duration"},
            )

    def test_skill_documents_structured_authenticated_plan_evidence(self) -> None:
        text = SKILL.read_text(encoding="utf-8")

        self.assertIn("| Check | Result | Evidence |", text)
        self.assertIn("| Authenticated detector SignalFlow compile | Pass |", text)
        self.assertIn("`/v2/detector/validate`", text)


class ValidateConfigureOutputTest(unittest.TestCase):
    def test_accepts_verified_detector_and_secure_provider_wiring(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = MODULE.validate(write_validation_fixture(Path(directory)))

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 1)
        self.assertEqual(result["detector_metrics"], [METRIC])
        self.assertEqual(result["reported_status"], "Pass")

    def test_accepts_detector_authorized_by_bound_canonical_flow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_validation_fixture(Path(directory))
            write_canonical_configure_flow(args)
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["working_metric_count"], 2)

    def test_rejects_instrumentation_bound_to_a_stale_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_validation_fixture(Path(directory))
            write_canonical_configure_flow(args)
            path = args.terraform_dir.parent / "otel-instrumentation.json"
            instrumentation = json.loads(path.read_text(encoding="utf-8"))
            instrumentation["selection_sha256"] = "sha256:" + "f" * 64
            path.write_text(json.dumps(instrumentation), encoding="utf-8")

            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any(
                "canonical verification flow validation failed" in error
                for error in result["errors"]
            ),
            result["errors"],
        )

    def test_rejects_metric_authorized_only_by_same_named_span_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_validation_fixture(Path(directory))
            write_canonical_configure_flow(args)
            verify_path = args.terraform_dir.parent / "otel-verify.json"
            verification = json.loads(verify_path.read_text(encoding="utf-8"))
            wrong_kind = (
                "The generated trace captured span "
                "http.server.request.duration with service.name=checkout."
            )
            finding = verification["findings"][0]
            finding["scenarios"][0]["observed_telemetry"] = [wrong_kind]
            finding["item_results"][0]["observed_telemetry"] = [wrong_kind]
            verify_path.write_text(json.dumps(verification), encoding="utf-8")
            write_canonical_reader_report(args)

            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any(
                "canonical verification flow validation failed" in error
                for error in result["errors"]
            ),
            result["errors"],
        )

    def test_rejects_markdown_metric_not_authorized_by_canonical_json(self) -> None:
        detector_metric = "custom.unverified.metric"
        with tempfile.TemporaryDirectory() as directory:
            args = write_validation_fixture(
                Path(directory),
                detector_metric=detector_metric,
                verified_metric=detector_metric,
            )
            write_canonical_configure_flow(args)
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            f"latency: metric {detector_metric!r} is not a Working verified metric",
            result["errors"],
        )

    def test_uses_the_exact_canonical_snapshot_that_was_validated(self) -> None:
        detector_metric = "custom.post-validation.metric"
        with tempfile.TemporaryDirectory() as directory:
            args = write_validation_fixture(
                Path(directory), detector_metric=detector_metric
            )
            write_canonical_configure_flow(args)
            original_validator = MODULE.run_checked_validator
            validator_calls = 0

            def mutate_after_validation(command, label, errors):
                nonlocal validator_calls
                result = original_validator(command, label, errors)
                validator_calls += 1
                if validator_calls == 2:
                    path = args.terraform_dir.parent / "otel-instrumentation.json"
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    payload["findings"][0]["telemetry_changes"][0]["name"] = (
                        detector_metric
                    )
                    path.write_text(json.dumps(payload), encoding="utf-8")
                return result

            with mock.patch.object(
                MODULE, "run_checked_validator", side_effect=mutate_after_validation
            ):
                result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            f"latency: metric {detector_metric!r} is not a Working verified metric",
            result["errors"],
        )

    def test_rejects_scenario_only_metric_without_working_item_result(self) -> None:
        scenario_only_metric = "http.server.request.size"
        with tempfile.TemporaryDirectory() as directory:
            args = write_validation_fixture(
                Path(directory), detector_metric=scenario_only_metric
            )
            write_canonical_configure_flow(args)
            add_scenario_only_metric_to_canonical_flow(args, scenario_only_metric)
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            f"latency: metric {scenario_only_metric!r} is not a Working verified metric",
            result["errors"],
        )

    def test_rejects_markdown_that_disagrees_with_canonical_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_validation_fixture(Path(directory))
            write_canonical_configure_flow(args)
            args.verify_report.write_text(
                args.verify_report.read_text(encoding="utf-8").replace(
                    METRIC, "custom.forged.metric", 1
                ),
                encoding="utf-8",
            )
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any(
                "verify Markdown projection validation failed" in error
                for error in result["errors"]
            ),
            result["errors"],
        )

    def test_rejects_pass_with_substantive_not_yet_proven_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_validation_fixture(Path(directory))
            report = args.configure_verify_report.read_text(encoding="utf-8").replace(
                "## Not Yet Proven\nNone.",
                "## Not Yet Proven\nRemote SignalFlow compilation was not run.",
            )
            args.configure_verify_report.write_text(report, encoding="utf-8")
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "configure verification report: Result Pass conflicts with substantive "
            "## Not Yet Proven content",
            result["errors"],
        )

    def test_rejects_pass_without_authenticated_detector_compile_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_validation_fixture(Path(directory))
            report = args.configure_verify_report.read_text(encoding="utf-8").replace(
                "| Authenticated detector SignalFlow compile | Pass | Authenticated `terraform plan -refresh=false -input=false` accepted all generated detectors through `/v2/detector/validate`. |",
                "| Local Terraform validation | Pass | `terraform validate -json` returned valid. |",
            )
            args.configure_verify_report.write_text(report, encoding="utf-8")
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "configure verification report: Result Pass requires a successful authenticated "
            "terraform plan / SignalFlow compile row covering every generated detector",
            result["errors"],
        )

    def test_rejects_authenticated_plan_row_with_negative_or_uncertain_evidence(self) -> None:
        contradictions = (
            "Authenticated terraform plan failed; SignalFlow compile returned no "
            "validation result for all 1 generated detector.",
            "Authenticated terraform plan may have succeeded; SignalFlow validation "
            "is pending for all 1 generated detector.",
        )
        for contradictory in contradictions:
            with self.subTest(contradictory=contradictory), tempfile.TemporaryDirectory() as directory:
                args = write_validation_fixture(Path(directory))
                report = args.configure_verify_report.read_text(encoding="utf-8")
                report = re.sub(
                    r"Authenticated `terraform plan[^|]+",
                    contradictory + " ",
                    report,
                )
                args.configure_verify_report.write_text(report, encoding="utf-8")
                result = MODULE.validate(args)

            self.assertEqual(result["result"], "FAIL")
            self.assertIn(
                "configure verification report: Result Pass requires a successful authenticated "
                "terraform plan / SignalFlow compile row covering every generated detector",
                result["errors"],
            )

    def test_accepts_dashboard_proof_with_publish_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_validation_fixture(Path(directory))
            write_dashboard_fixture(args)
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["dashboard_chart_count"], 1)
        self.assertEqual(result["preview_chart_count"], 1)

    def test_accepts_inherited_partial_when_dashboard_checks_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_validation_fixture(Path(directory))
            write_dashboard_fixture(args, result="Partial")
            args.detectors_report.write_text(
                args.detectors_report.read_text(encoding="utf-8").replace(
                    "**Result:** Pass", "**Result:** Partial"
                ),
                encoding="utf-8",
            )
            args.configure_verify_report.write_text(
                args.configure_verify_report.read_text(encoding="utf-8").replace(
                    "**Result:** Pass", "**Result:** Partial"
                ),
                encoding="utf-8",
            )
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["reported_status"], "Partial")

    def test_delegates_explicit_source_metric_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_validation_fixture(Path(directory))
            write_dashboard_fixture(args)
            source_id = "SOURCE-METRIC.http.server.request.duration"
            dashboards_tf = args.terraform_dir / "dashboards.tf"
            dashboards_tf.write_text(
                dashboards_tf.read_text(encoding="utf-8").replace(
                    "OTEL-001.http-duration", source_id
                ),
                encoding="utf-8",
            )
            preview = args.terraform_dir.parent / "dashboards.preview.json"
            preview.write_text(
                preview.read_text(encoding="utf-8").replace(
                    "OTEL-001.http-duration", source_id
                ),
                encoding="utf-8",
            )
            report = args.terraform_dir.parent / "dashboards.md"
            report.write_text(
                report.read_text(encoding="utf-8").replace(
                    "OTEL-001.http-duration", source_id
                ),
                encoding="utf-8",
            )
            args.allow_source_only_item = [source_id]
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "PASS", result["errors"])

    def test_rejects_dashboard_terraform_without_report_and_preview(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_validation_fixture(Path(directory))
            (args.terraform_dir / "dashboards.tf").write_text(
                'resource "signalfx_time_chart" "latency" {}\n',
                encoding="utf-8",
            )
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any(error.startswith("missing dashboards report:") for error in result["errors"]),
            result["errors"],
        )
        self.assertTrue(
            any(error.startswith("missing dashboard preview:") for error in result["errors"]),
            result["errors"],
        )

    def test_rejects_dashboard_pass_without_render_and_live_value_proof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = write_validation_fixture(Path(directory))
            write_dashboard_fixture(args, observer_result="Not run", live_value_result="Blocked")
            result = MODULE.validate(args)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "dashboard validator: report: Result Pass requires Observer render and "
            "Live value sanity to be Pass",
            result["errors"],
        )

    def test_rejects_detector_without_working_metric_evidence(self) -> None:
        detector_metric = "custom.unverified.metric"
        with tempfile.TemporaryDirectory() as directory:
            result = MODULE.validate(
                write_validation_fixture(Path(directory), detector_metric=detector_metric)
            )

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            f"latency: metric {detector_metric!r} is not a Working verified metric",
            result["errors"],
        )

    def test_accepts_merged_route_group_detectors_on_same_metric_different_filter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}

resource "signalfx_detector" "error" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name) and filter('error.type', '*'))
    signal.publish('Error rate')
  EOF

  rule {{
    detect_label = "Error rate"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 2)

    def test_rejects_two_detectors_on_same_metric_with_identical_filters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}

resource "signalfx_detector" "latency_dup" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency again')
  EOF

  rule {{
    detect_label = "High latency again"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "two detectors read the same metric with the same aggregation and attribute "
            "filters (true duplicate; a route-group merge must use a distinct aggregation "
            "or filter on distinct attributes)",
            result["errors"],
        )

    def test_accepts_latency_and_throughput_detectors_on_same_metric_different_aggregation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).percentile(pct=99)
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}

resource "signalfx_detector" "throughput" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name), rollup='count').sum()
    signal.publish('Low throughput')
  EOF

  rule {{
    detect_label = "Low throughput"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 2)

    def test_rejects_two_detectors_with_identical_percentile_argument(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "p99" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).percentile(pct=99)
    signal.publish('P99 latency')
  EOF

  rule {{
    detect_label = "P99 latency"
  }}
}}

resource "signalfx_detector" "p50" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).percentile(pct=99)
    signal.publish('P50 latency')
  EOF

  rule {{
    detect_label = "P50 latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "two detectors read the same metric with the same aggregation and attribute "
            "filters (true duplicate; a route-group merge must use a distinct aggregation "
            "or filter on distinct attributes)",
            result["errors"],
        )

    def test_accepts_two_detectors_on_same_metric_with_different_percentile_argument(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "p99" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).percentile(pct=99)
    signal.publish('P99 latency')
  EOF

  rule {{
    detect_label = "P99 latency"
  }}
}}

resource "signalfx_detector" "p50" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).percentile(pct=50)
    signal.publish('P50 latency')
  EOF

  rule {{
    detect_label = "P50 latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 2)

    def test_accepts_two_detectors_on_same_metric_with_different_by_grouping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "error" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name) and filter('error.type', '*')).count(by=['error.type'])
    signal.publish('Error rate')
  EOF

  rule {{
    detect_label = "Error rate"
  }}
}}

resource "signalfx_detector" "throughput" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name) and filter('error.type', '*')).count(by=['http.route'])
    signal.publish('Throughput')
  EOF

  rule {{
    detect_label = "Throughput"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 2)

    def test_accepts_two_detectors_differing_only_in_and_or_filter_structure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "and_filter" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name) and filter('error.type', '*'))
    signal.publish('And filter')
  EOF

  rule {{
    detect_label = "And filter"
  }}
}}

resource "signalfx_detector" "or_filter" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name) or filter('error.type', '*'))
    signal.publish('Or filter')
  EOF

  rule {{
    detect_label = "Or filter"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 2)

    def test_rejects_two_detectors_differing_only_in_compact_boolean_operator_spacing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "spaced" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name) and filter('error.type', '*'))
    signal.publish('Error rate')
  EOF

  rule {{
    detect_label = "Error rate"
  }}
}}

resource "signalfx_detector" "compact" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)and filter('error.type', '*'))
    signal.publish('Error rate again')
  EOF

  rule {{
    detect_label = "Error rate again"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "two detectors read the same metric with the same aggregation and attribute "
            "filters (true duplicate; a route-group merge must use a distinct aggregation "
            "or filter on distinct attributes)",
            result["errors"],
        )

    def test_rejects_two_detectors_differing_only_in_punctuation_whitespace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "spaced" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter = filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}

resource "signalfx_detector" "unspaced" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency again')
  EOF

  rule {{
    detect_label = "High latency again"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "two detectors read the same metric with the same aggregation and attribute "
            "filters (true duplicate; a route-group merge must use a distinct aggregation "
            "or filter on distinct attributes)",
            result["errors"],
        )

    def test_preserves_whitespace_inside_quoted_filter_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "one_space" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', 'checkout api'))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}

resource "signalfx_detector" "two_space" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', 'checkout  api'))
    signal.publish('High latency again')
  EOF

  rule {{
    detect_label = "High latency again"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 2)

    def test_ignores_filter_looking_text_outside_the_data_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    # was filter('error.type', '*') before the route-group merge
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish("was filter('error.type', '*')")
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}

resource "signalfx_detector" "latency_dup" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency again')
  EOF

  rule {{
    detect_label = "High latency again"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "two detectors read the same metric with the same aggregation and attribute "
            "filters (true duplicate; a route-group merge must use a distinct aggregation "
            "or filter on distinct attributes)",
            result["errors"],
        )


    def test_ignores_decoy_data_call_inside_a_comment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    # previously used data('custom.unverified.metric', filter=filter('x', 'y'))
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}

resource "signalfx_detector" "latency_dup" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency again')
  EOF

  rule {{
    detect_label = "High latency again"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "two detectors read the same metric with the same aggregation and attribute "
            "filters (true duplicate; a route-group merge must use a distinct aggregation "
            "or filter on distinct attributes)",
            result["errors"],
        )
        self.assertNotIn(
            f"latency: metric {METRIC!r} is not a Working verified metric",
            result["errors"],
        )

    def test_ignores_decoy_data_call_inside_a_trailing_comment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))  # old data('custom.unverified.metric', filter=filter('x', 'y'))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}

resource "signalfx_detector" "latency_dup" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency again')
  EOF

  rule {{
    detect_label = "High latency again"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "two detectors read the same metric with the same aggregation and attribute "
            "filters (true duplicate; a route-group merge must use a distinct aggregation "
            "or filter on distinct attributes)",
            result["errors"],
        )
        self.assertNotIn(
            f"latency: metric {METRIC!r} is not a Working verified metric",
            result["errors"],
        )

    def test_ignores_decoy_data_call_with_unbalanced_paren_inside_a_trailing_comment(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))  # old data('custom.metric'
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS")

    def test_ignores_decoy_paren_inside_a_comment_within_a_multiline_data_call(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}',   # note filter( with an unbalanced paren
        filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}

resource "signalfx_detector" "latency_dup" {{
  program_text = <<-EOF
    signal = data('{METRIC}',
        filter=filter('service.name', var.service_name))
    signal.publish('High latency again')
  EOF

  rule {{
    detect_label = "High latency again"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "two detectors read the same metric with the same aggregation and attribute "
            "filters (true duplicate; a route-group merge must use a distinct aggregation "
            "or filter on distinct attributes)",
            result["errors"],
        )
        self.assertNotIn(
            f"latency: metric {METRIC!r} is not a Working verified metric",
            result["errors"],
        )

    def test_ignores_decoy_brace_inside_a_comment_within_a_program_text_heredoc(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    # closing brace decoy }}
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 1)

    def test_ignores_decoy_resource_block_hidden_inside_a_comment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

# resource "signalfx_detector" "ghost" {{
resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 1)

    def test_ignores_decoy_resource_header_inside_a_program_text_heredoc(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    note = 'resource "signalfx_detector" "ghost" {{'
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 1)

    def test_ignores_decoy_provider_block_inside_a_program_text_heredoc(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    note = 'provider "signalfx" {{ auth_token = "leak" }}'
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 1)

    def test_ignores_decoy_detect_label_inside_a_program_text_heredoc(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    note = 'detect_label = "Ghost label"'
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 1)

    def test_ignores_decoy_resource_header_and_brace_inside_a_description_heredoc(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  description = <<-EOT
    historical: resource "signalfx_detector" "ghost" {{ stray brace }}
  EOT
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 1)

    def test_ignores_decoy_brace_inside_a_quoted_description_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  description = "closing brace }} and detect_label = decoy"
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 1)

    def test_scans_real_program_text_not_a_decoy_inside_a_quoted_description(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  description = "see program_text = <<EOF data('decoy.metric') EOF"
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_metrics"], [METRIC])

    def test_scans_real_program_text_not_a_decoy_inside_a_description_heredoc(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  description = <<-EOT
    program_text = <<EOF
    data('decoy.metric')
    EOF
  EOT
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_metrics"], [METRIC])

    def test_rejects_a_provider_auth_token_wrapped_in_a_boolean_expression(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token == "x"
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn("signalfx provider must use var.api_token", result["errors"])

    def test_rejects_a_provider_api_url_wrapped_in_a_boolean_expression(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com" != ""
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn("signalfx provider api_url must derive from var.realm", result["errors"])

    def test_accepts_a_provider_auth_token_with_a_trailing_comment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token # required credential
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])

    def test_rejects_a_provider_whose_auth_token_only_appears_in_a_string_value(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  alias      = "auth_token = var.api_token"
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn("signalfx provider must use var.api_token", result["errors"])

    def test_ignores_decoy_auth_token_inside_a_comment_in_the_provider_block(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  # auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn("signalfx provider must use var.api_token", result["errors"])

    def test_rejects_two_detectors_differing_only_in_quote_style(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "single_quote" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', 'checkout'))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}

resource "signalfx_detector" "double_quote" {{
  program_text = <<-EOF
    signal = data("{METRIC}", filter=filter("service.name", "checkout"))
    signal.publish('High latency again')
  EOF

  rule {{
    detect_label = "High latency again"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "two detectors read the same metric with the same aggregation and attribute "
            "filters (true duplicate; a route-group merge must use a distinct aggregation "
            "or filter on distinct attributes)",
            result["errors"],
        )

    def test_rejects_two_detectors_differing_only_in_aggregation_quote_style(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "single_quote" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).count(by=['error.type'])
    signal.publish('Error rate')
  EOF

  rule {{
    detect_label = "Error rate"
  }}
}}

resource "signalfx_detector" "double_quote" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).count(by=["error.type"])
    signal.publish('Error rate again')
  EOF

  rule {{
    detect_label = "Error rate again"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "two detectors read the same metric with the same aggregation and attribute "
            "filters (true duplicate; a route-group merge must use a distinct aggregation "
            "or filter on distinct attributes)",
            result["errors"],
        )

    def test_ignores_decoy_checks_hidden_inside_comments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    # filter('service.name', var.service_name)
    # signal.publish('Decoy label')
    # detect_label = "Decoy label"
    # uses var.ghost_undeclared for context
    # session_id used to live here
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])

    def test_rejects_detector_missing_service_name_filter_behind_a_decoy_comment(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    # filter('service.name', var.service_name)
    signal = data('{METRIC}')
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn("latency: missing service.name filter", result["errors"])

    def test_rejects_detector_whose_published_label_is_only_a_decoy_comment(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    # signal.publish('High latency')
    signal.publish('Something else')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "latency: detect_label 'High latency' is not published by SignalFlow",
            result["errors"],
        )

    def test_ignores_decoy_auth_token_inside_a_double_slash_comment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  // auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn("signalfx provider must use var.api_token", result["errors"])

    def test_ignores_decoy_resource_block_hidden_inside_a_block_comment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

/* resource "signalfx_detector" "ghost" {{ */
resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 1)

    def test_ignores_decoy_brace_inside_a_block_comment_within_a_program_text_heredoc(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    /* block comment with decoy resource "signalfx_detector" "ghost" {{ */
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 1)

    def test_accepts_two_detectors_with_escaped_newline_vs_literal_n_filter_value(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "newline" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name) and filter('log.delimiter', '\\n'))
    signal.publish('Newline delimiter')
  EOF

  rule {{
    detect_label = "Newline delimiter"
  }}
}}

resource "signalfx_detector" "letter_n" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name) and filter('log.delimiter', 'n'))
    signal.publish('Letter n delimiter')
  EOF

  rule {{
    detect_label = "Letter n delimiter"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 2)

    def test_rejects_two_detectors_differing_only_in_and_operand_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "forward" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name) and filter('error.type', '*'))
    signal.publish('Error rate')
  EOF

  rule {{
    detect_label = "Error rate"
  }}
}}

resource "signalfx_detector" "reversed" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('error.type', '*') and filter('service.name', var.service_name))
    signal.publish('Error rate again')
  EOF

  rule {{
    detect_label = "Error rate again"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "two detectors read the same metric with the same aggregation and attribute "
            "filters (true duplicate; a route-group merge must use a distinct aggregation "
            "or filter on distinct attributes)",
            result["errors"],
        )

    def test_rejects_two_detectors_differing_only_in_keyword_argument_order(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "filter_then_rollup" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name), rollup='count').sum()
    signal.publish('Throughput')
  EOF

  rule {{
    detect_label = "Throughput"
  }}
}}

resource "signalfx_detector" "rollup_then_filter" {{
  program_text = <<-EOF
    signal = data('{METRIC}', rollup='count', filter=filter('service.name', var.service_name)).sum()
    signal.publish('Throughput again')
  EOF

  rule {{
    detect_label = "Throughput again"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "two detectors read the same metric with the same aggregation and attribute "
            "filters (true duplicate; a route-group merge must use a distinct aggregation "
            "or filter on distinct attributes)",
            result["errors"],
        )

    def test_ignores_data_call_looking_text_inside_a_description_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  description = "Replaces the old data('legacy.metric') detector"

  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_metrics"], [METRIC])

    def test_rejects_two_data_calls_inside_the_same_program_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    a = data('{METRIC}', filter=filter('service.name', var.service_name))
    b = data('other.metric', filter=filter('service.name', var.service_name))
    a.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "latency: expected exactly one data(...) metric, found 2",
            result["errors"],
        )

    def test_ignores_a_data_call_looking_label_inside_publish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    note = "old detector called data('legacy.metric') directly"
    A = data('{METRIC}', filter=filter('service.name', var.service_name))
    A.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_metrics"], [METRIC])

    def test_rejects_an_unbalanced_data_call_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    A = data('{METRIC}', filter=filter('service.name', var.service_name)
    A.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any("latency: malformed data(...) call" in error for error in result["errors"]),
            result["errors"],
        )

    def test_rejects_an_unbalanced_publish_call_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    A = data('{METRIC}', filter=filter('service.name', var.service_name))
    A.publish('High latency'
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any("latency: malformed .publish(...) call" in error for error in result["errors"]),
            result["errors"],
        )
        # The shared paren matcher must not describe a .publish(...) failure as
        # an "unbalanced data(...) call".
        self.assertFalse(
            any("data(...) call" in error for error in result["errors"]),
            result["errors"],
        )

    def test_rejects_an_unbalanced_aggregation_call_without_reporting_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    A = data('{METRIC}', filter=filter('service.name', var.service_name)).percentile(pct=99
    A.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any("latency: malformed aggregation call" in error for error in result["errors"]),
            result["errors"],
        )

    def test_rejects_a_chained_aggregation_method_missing_its_argument_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    A = data('{METRIC}', filter=filter('service.name', var.service_name)).percentile
    A.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any("latency: malformed aggregation call" in error for error in result["errors"]),
            result["errors"],
        )

    def test_accepts_a_keyword_form_publish_label(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    A = data('{METRIC}', filter=filter('service.name', var.service_name)).percentile(pct=99).publish(label='High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_metrics"], [METRIC])

    def test_rejects_a_mismatched_bracket_in_the_data_call_without_reporting_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    A = data('{METRIC}', filter=filter('service.name', var.service_name)).count(by=['http.route')).publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any("latency: malformed aggregation call" in error for error in result["errors"]),
            result["errors"],
        )

    def test_rejects_forbidden_content_hidden_in_a_description_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  description = "captures raw_prompt text for debugging"

  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "latency: unsafe raw prompt/content appears in detector program",
            result["errors"],
        )

    def test_ignores_data_call_looking_text_inside_a_plain_string_program_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  description = "Replaces the old data('legacy.metric') detector"
  program_text = "signal = data('{METRIC}', filter=filter('service.name', var.service_name)); signal.publish('High latency')"

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_metrics"], [METRIC])

    def test_rejects_program_text_heredoc_with_no_closing_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "latency: expected exactly one data(...) metric, found 0",
            result["errors"],
        )

    def test_does_not_truncate_a_non_dash_heredoc_at_an_indented_lookalike_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<EOF
signal = data('{METRIC}', filter=filter('service.name', var.service_name))
  EOF
signal.publish('High latency')
EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_metrics"], [METRIC])

    def test_parses_a_program_text_heredoc_with_crlf_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            detectors = fixture.terraform_dir.joinpath("detectors.tf")
            detectors.write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
'''.replace("\n", "\r\n"),
                encoding="utf-8",
                newline="",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_metrics"], [METRIC])

    def test_ignores_decoy_variable_and_detect_label_hidden_in_a_description_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  description = "was based on var.undeclared_var and detect_label = \\"Fake Label\\""

  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_metrics"], [METRIC])

    def test_rejects_two_detectors_differing_only_in_aggregation_keyword_order(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "pct_over" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).percentile(pct=99, over='5m')
    signal.publish('P99 latency')
  EOF

  rule {{
    detect_label = "P99 latency"
  }}
}}

resource "signalfx_detector" "over_pct" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).percentile(over='5m', pct=99)
    signal.publish('P99 latency again')
  EOF

  rule {{
    detect_label = "P99 latency again"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "two detectors read the same metric with the same aggregation and attribute "
            "filters (true duplicate; a route-group merge must use a distinct aggregation "
            "or filter on distinct attributes)",
            result["errors"],
        )

    def test_accepts_two_detectors_differing_only_in_between_positional_argument_order(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "low_ten_high_twenty" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).between(10, 20)
    signal.publish('Between 10 and 20')
  EOF

  rule {{
    detect_label = "Between 10 and 20"
  }}
}}

resource "signalfx_detector" "low_twenty_high_ten" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).between(20, 10)
    signal.publish('Between 20 and 10')
  EOF

  rule {{
    detect_label = "Between 20 and 10"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])

    def test_decodes_escaped_newline_in_a_plain_string_program_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = "signal = data('{METRIC}', filter=filter('service.name', var.service_name))\\nsignal.publish('High latency')"

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_metrics"], [METRIC])

    def test_rejects_a_data_call_missing_service_name_filter_despite_a_decoy_elsewhere(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    note = "old detector used filter('service.name', var.service_name)"
    A = data('{METRIC}')
    A.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn("latency: missing service.name filter", result["errors"])

    def test_rejects_a_service_name_filter_that_only_appears_inside_a_string_argument(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    A = data('{METRIC}', filter=filter('env', "filter('service.name', x)"))
    A.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn("latency: missing service.name filter", result["errors"])

    def test_rejects_a_publish_label_mismatch_despite_a_decoy_label_elsewhere(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    note = ".publish('High latency')"
    A = data('{METRIC}', filter=filter('service.name', var.service_name))
    A.publish('Some other label')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "latency: detect_label 'High latency' is not published by SignalFlow",
            result["errors"],
        )

    def test_rejects_a_second_data_call_with_a_non_literal_metric_argument(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    a = data(dynamic_metric, filter=filter('service.name', var.service_name))
    b = data('{METRIC}', filter=filter('service.name', var.service_name))
    b.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any("latency: malformed data(...) call" in error for error in result["errors"]),
            result["errors"],
        )

    def test_rejects_two_detectors_differing_only_in_associative_paren_grouping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "left_grouped" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=(filter('service.name', var.service_name) and filter('error.type', '*')) and filter('http.route', '/checkout'))
    signal.publish('Error rate')
  EOF

  rule {{
    detect_label = "Error rate"
  }}
}}

resource "signalfx_detector" "right_grouped" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name) and (filter('error.type', '*') and filter('http.route', '/checkout')))
    signal.publish('Error rate again')
  EOF

  rule {{
    detect_label = "Error rate again"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "two detectors read the same metric with the same aggregation and attribute "
            "filters (true duplicate; a route-group merge must use a distinct aggregation "
            "or filter on distinct attributes)",
            result["errors"],
        )

    def test_rejects_two_detectors_differing_only_in_newline_before_aggregation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "inline" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).percentile(pct=99)
    signal.publish('P99')
  EOF

  rule {{
    detect_label = "P99"
  }}
}}

resource "signalfx_detector" "wrapped" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
      .percentile(pct=99)
    signal.publish('P99 again')
  EOF

  rule {{
    detect_label = "P99 again"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "two detectors read the same metric with the same aggregation and attribute "
            "filters (true duplicate; a route-group merge must use a distinct aggregation "
            "or filter on distinct attributes)",
            result["errors"],
        )

    def test_distinguishes_aggregations_with_deeply_nested_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "nested_a" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).mean(over=max(percentile(pct=99)))
    signal.publish('Nested A')
  EOF

  rule {{
    detect_label = "Nested A"
  }}
}}

resource "signalfx_detector" "nested_b" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).mean(over=max(percentile(pct=50)))
    signal.publish('Nested B')
  EOF

  rule {{
    detect_label = "Nested B"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 2)

    def test_rejects_an_unbalanced_detector_block_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any("malformed signalfx_detector block" in error for error in result["errors"]),
            result["errors"],
        )

    def test_rejects_two_detectors_differing_only_in_redundant_outer_filter_parens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "wrapped" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=(filter('service.name', var.service_name) and filter('error.type', '*')))
    signal.publish('Error rate')
  EOF

  rule {{
    detect_label = "Error rate"
  }}
}}

resource "signalfx_detector" "bare" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name) and filter('error.type', '*'))
    signal.publish('Error rate again')
  EOF

  rule {{
    detect_label = "Error rate again"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "two detectors read the same metric with the same aggregation and attribute "
            "filters (true duplicate; a route-group merge must use a distinct aggregation "
            "or filter on distinct attributes)",
            result["errors"],
        )

    def test_rejects_two_detectors_differing_only_in_by_grouping_key_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "route_then_error" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).count(by=['http.route', 'error.type'])
    signal.publish('Error rate')
  EOF

  rule {{
    detect_label = "Error rate"
  }}
}}

resource "signalfx_detector" "error_then_route" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).count(by=['error.type', 'http.route'])
    signal.publish('Error rate again')
  EOF

  rule {{
    detect_label = "Error rate again"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "two detectors read the same metric with the same aggregation and attribute "
            "filters (true duplicate; a route-group merge must use a distinct aggregation "
            "or filter on distinct attributes)",
            result["errors"],
        )

    def test_accepts_two_detectors_with_distinct_by_grouping_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "by_route" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).count(by=['http.route'])
    signal.publish('By route')
  EOF

  rule {{
    detect_label = "By route"
  }}
}}

resource "signalfx_detector" "by_route_and_error" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).count(by=['http.route', 'error.type'])
    signal.publish('By route and error')
  EOF

  rule {{
    detect_label = "By route and error"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])

    def test_rejects_two_detectors_differing_only_in_scalar_versus_singleton_list_group_by(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "scalar_by" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).count(by='http.route')
    signal.publish('Scalar by')
  EOF

  rule {{
    detect_label = "Scalar by"
  }}
}}

resource "signalfx_detector" "singleton_list_by" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).count(by=['http.route'])
    signal.publish('Singleton list by')
  EOF

  rule {{
    detect_label = "Singleton list by"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "two detectors read the same metric with the same aggregation and attribute "
            "filters (true duplicate; a route-group merge must use a distinct aggregation "
            "or filter on distinct attributes)",
            result["errors"],
        )

    def test_rejects_two_detectors_differing_only_in_numeric_literal_form(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "integer_pct" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).percentile(pct=99)
    signal.publish('Integer pct')
  EOF

  rule {{
    detect_label = "Integer pct"
  }}
}}

resource "signalfx_detector" "float_pct" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).percentile(pct=99.0)
    signal.publish('Float pct')
  EOF

  rule {{
    detect_label = "Float pct"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "two detectors read the same metric with the same aggregation and attribute "
            "filters (true duplicate; a route-group merge must use a distinct aggregation "
            "or filter on distinct attributes)",
            result["errors"],
        )

    def test_rejects_two_detectors_differing_only_in_redundant_precedence_parens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "explicit_precedence" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=(filter('service.name', var.service_name) and filter('error.type', '*')) or filter('http.route', '/checkout'))
    signal.publish('Explicit precedence')
  EOF

  rule {{
    detect_label = "Explicit precedence"
  }}
}}

resource "signalfx_detector" "implicit_precedence" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name) and filter('error.type', '*') or filter('http.route', '/checkout'))
    signal.publish('Implicit precedence')
  EOF

  rule {{
    detect_label = "Implicit precedence"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "two detectors read the same metric with the same aggregation and attribute "
            "filters (true duplicate; a route-group merge must use a distinct aggregation "
            "or filter on distinct attributes)",
            result["errors"],
        )

    def test_distinguishes_detectors_whose_precedence_parens_change_the_grouping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "or_grouped" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=(filter('service.name', var.service_name) or filter('error.type', '*')) and filter('http.route', '/checkout'))
    signal.publish('Or grouped')
  EOF

  rule {{
    detect_label = "Or grouped"
  }}
}}

resource "signalfx_detector" "natural_precedence" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name) or filter('error.type', '*') and filter('http.route', '/checkout'))
    signal.publish('Natural precedence')
  EOF

  rule {{
    detect_label = "Natural precedence"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 2)

    def test_rejects_api_token_whose_sensitive_flag_only_appears_in_a_description(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("variables.tf").write_text(
                '''variable "api_token" {
  type        = string
  description = "Set sensitive = true to hide this token"
}

variable "realm" {
  type = string
}

variable "service_name" {
  type = string
}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn("api_token variable is not marked sensitive", result["errors"])

    def test_rejects_a_metric_whose_only_report_mention_is_a_longer_metric_name(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            # The detector reads `http.server.request.duration`, but the report
            # only mentions the different, longer `http.server.request.duration.p99`.
            # A bare substring test would treat the metric as present; a bounded
            # match must flag it as absent.
            fixture.detectors_report.write_text(
                f"# Detectors\n\n**Result:** Pass\n\nGenerated `{METRIC}.p99` detector.\n",
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            f"latency: metric {METRIC!r} is absent from detectors report",
            result["errors"],
        )

    def test_accepts_a_var_reference_that_only_appears_inside_a_publish_label(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('legacy used var.legacy_threshold before this rewrite')
  EOF

  rule {{
    detect_label = "legacy used var.legacy_threshold before this rewrite"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertNotIn(
            "latency: referenced variable 'legacy_threshold' is not declared",
            result["errors"],
        )

    def test_accepts_a_var_mention_that_is_only_prose_in_a_description_heredoc(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            # `var.legacy_threshold` here is documentation prose inside a
            # description heredoc, not a real reference. Scoping the reference
            # scan to the program body must keep it from being flagged as an
            # undeclared variable.
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOF

  description = <<-EOT
    This detector replaces the old var.legacy_threshold approach.
  EOT

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertNotIn(
            "latency: referenced variable 'legacy_threshold' is not declared",
            result["errors"],
        )

    def test_rejects_a_resource_whose_only_data_call_lives_in_a_description_heredoc(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            # No real program_text: the data(...)/publish(...) SignalFlow lives
            # only inside a description heredoc. The zero-metric check must
            # reject it rather than scanning that free text as a program body.
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  name        = "Latency"
  description = <<-EOT
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  EOT

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "latency: expected exactly one data(...) metric, found 0",
            result["errors"],
        )

    def test_accepts_a_program_text_heredoc_with_a_hyphenated_delimiter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            # HCL delimiters permit hyphens: `<<-SIGNAL-FLOW` is a valid marker
            # and its body must be recognized as the real program_text.
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-SIGNAL-FLOW
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  SIGNAL-FLOW

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_metrics"], [METRIC])

    def test_ignores_a_decoy_resource_brace_in_a_hyphenated_delimiter_heredoc(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            # A resource-shaped decoy inside a hyphenated-delimiter heredoc body
            # must be masked, not mistaken for a second real resource block.
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-SIGNAL-FLOW
    note = "resource signalfx_detector decoy {{ oops }}"
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish('High latency')
  SIGNAL-FLOW

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 1)

    def test_rejects_a_typo_in_an_interpolated_var_reference_inside_a_filter_value(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            # `'${var.service_nam}'` is a real interpolated reference to an
            # undeclared variable; blanking the whole string would hide the typo.
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', '${{var.service_nam}}'))
    signal.publish('High latency')
  EOF

  rule {{
    detect_label = "High latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "latency: referenced variable 'service_nam' is not declared",
            result["errors"],
        )

    def test_rejects_an_api_token_whose_block_lacks_sensitive_despite_a_later_sensitive_var(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            # The api_token block closes with an indented brace and has no
            # `sensitive = true`; a later variable does. The brace matcher must
            # bound the block so the later flag cannot satisfy the check.
            fixture.terraform_dir.joinpath("variables.tf").write_text(
                '''variable "api_token" {
  type = string
  }

variable "realm" {
  type = string
}

variable "service_name" {
  type      = string
  sensitive = true
}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn("api_token variable is not marked sensitive", result["errors"])

    def test_accepts_a_double_quoted_publish_label_containing_an_apostrophe(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            # A double-quoted label with an apostrophe must not be truncated at
            # the apostrophe, so it still matches its detect_label.
            fixture.terraform_dir.joinpath("detectors.tf").write_text(
                f'''provider "signalfx" {{
  auth_token = var.api_token
  api_url    = "https://api.${{var.realm}}.signalfx.com"
}}

resource "signalfx_detector" "latency" {{
  program_text = <<-EOF
    signal = data('{METRIC}', filter=filter('service.name', var.service_name))
    signal.publish("API's latency")
  EOF

  rule {{
    detect_label = "API's latency"
  }}
}}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 1)

    def test_rejects_a_realm_declaration_that_is_only_commented_out(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_validation_fixture(root)
            fixture.terraform_dir.joinpath("variables.tf").write_text(
                '''variable "api_token" {
  type      = string
  sensitive = true
}

# variable "realm" {
#   type = string
# }

variable "service_name" {
  type = string
}
''',
                encoding="utf-8",
            )
            result = MODULE.validate(fixture)

        self.assertEqual(result["result"], "FAIL")
        self.assertIn("variables.tf does not declare realm", result["errors"])


if __name__ == "__main__":
    unittest.main()
