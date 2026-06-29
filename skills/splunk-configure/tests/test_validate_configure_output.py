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


if __name__ == "__main__":
    unittest.main()
