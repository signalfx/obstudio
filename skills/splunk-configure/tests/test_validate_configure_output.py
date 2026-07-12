from __future__ import annotations

import argparse
import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_configure_output.py"
SPEC = importlib.util.spec_from_file_location("validate_configure_output", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

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
Local validation.

## Not Yet Proven
Remote apply.

## Validation Notes
Fixture evidence.

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


class ValidateConfigureOutputTest(unittest.TestCase):
    def test_accepts_verified_detector_and_secure_provider_wiring(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = MODULE.validate(write_validation_fixture(Path(directory)))

        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["detector_count"], 1)
        self.assertEqual(result["detector_metrics"], [METRIC])
        self.assertEqual(result["reported_status"], "Pass")

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


if __name__ == "__main__":
    unittest.main()
