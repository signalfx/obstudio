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
    signal = data('{METRIC}', filter=filter('service.name', var.service_name)).count()
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


if __name__ == "__main__":
    unittest.main()
