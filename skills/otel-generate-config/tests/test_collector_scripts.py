from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
GENERATE = SKILL_DIR / "scripts" / "generate_collector.py"
VALIDATE = SKILL_DIR / "scripts" / "validate_collector.py"


class BundleScriptsTest(unittest.TestCase):
    def generate(
        self,
        output: Path,
        *extra: str,
        expect_success: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(GENERATE),
            "--output",
            str(output),
            "--realm",
            "us1",
            "--cluster-name",
            "checkout-prod",
            "--environment",
            "production",
            "--namespace",
            "observability",
            "--release-name",
            "splunk-otel",
            "--topology",
            "agent-service",
            "--distribution",
            "eks",
            "--collector-version",
            "0.155.0",
            *extra,
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if expect_success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def validate(
        self,
        output: Path,
        expect_success: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(VALIDATE), str(output)],
            capture_output=True,
            text=True,
        )
        if expect_success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def add_legacy_helm_output(self, output: Path) -> None:
        chart = output / "helm" / "Chart.yaml"
        values = output / "helm" / "values.yaml"
        secret = output / "helm" / "examples" / "splunk-secret.yaml"
        lock = output / "helm" / "Chart.lock"
        archive = (
            output
            / "helm"
            / "charts"
            / "splunk-otel-collector-0.155.0.tgz"
        )
        for path in (chart, values, secret, lock, archive):
            path.parent.mkdir(parents=True, exist_ok=True)
        chart.write_text("apiVersion: v2\nname: old\n", encoding="utf-8")
        values.write_text("collector: {}\n", encoding="utf-8")
        secret.write_text("apiVersion: v1\nkind: Secret\n", encoding="utf-8")
        lock.write_text("stale lock\n", encoding="utf-8")
        archive.write_bytes(b"stale archive")

    def test_generates_token_free_kubernetes_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "deploy" / "otel-collector"
            result = self.generate(output)

            self.assertIn("No access token was read or written.", result.stdout)
            self.validate(output)

            collector = (output / "collector-config.yaml").read_text()
            manifest = (output / "kubernetes" / "collector.yaml").read_text()
            secret = (
                output / "kubernetes" / "splunk-secret.example.yaml"
            ).read_text()
            deployment = (output / "DEPLOYMENT.md").read_text()

            self.assertFalse((output / "helm").exists())
            self.assertFalse((output / "kubernetes" / "helm-rendered.yaml").exists())
            self.assertIn("${env:SPLUNK_ACCESS_TOKEN}", collector)
            self.assertIn("kind: Service", manifest)
            self.assertIn("kind: Deployment", manifest)
            self.assertIn("name: splunk-otel-collector-agent", manifest)
            self.assertIn(
                "image: \"quay.io/signalfx/splunk-otel-collector:0.155.0\"",
                manifest,
            )
            self.assertIn("name: splunk-otel-secret", manifest)
            self.assertIn("key: splunk_observability_access_token", manifest)
            self.assertIn(
                "splunk_observability_access_token: REPLACE_AT_DEPLOY_TIME",
                secret,
            )
            self.assertIn("kubernetes/collector.yaml", deployment)
            self.assertNotIn("helm-rendered", deployment)
            self.assertNotIn("helm/", deployment)

    def test_gateway_mode_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output, "--gateway")
            manifest = (output / "kubernetes" / "collector.yaml").read_text()
            deployment = (output / "DEPLOYMENT.md").read_text()
            self.assertIn("name: splunk-otel-collector", manifest)
            self.assertIn("gateway using image", deployment)

    def test_standard_route_inputs_default_to_gateway(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            command = [
                sys.executable,
                str(GENERATE),
                "--output",
                str(output),
                "--realm",
                "us0",
                "--cluster-name",
                "checkout-prod",
                "--environment",
                "production",
                "--collector-version",
                "0.157.0",
            ]
            result = subprocess.run(command, capture_output=True, text=True)

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = (output / "kubernetes" / "collector.yaml").read_text()
            self.assertIn("name: splunk-otel-collector", manifest)
            self.assertIn('value: "us0"', manifest)
            self.assertIn("name: splunk-otel-secret", manifest)
            self.assertFalse((output / "helm").exists())

    def test_existing_secret_alias_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            result = self.generate(
                output,
                "--existing-secret",
                "splunk-otel-token",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = (output / "kubernetes" / "collector.yaml").read_text()
            secret = (
                output / "kubernetes" / "splunk-secret.example.yaml"
            ).read_text()
            self.assertIn("name: splunk-otel-token", manifest)
            self.assertIn("name: splunk-otel-token", secret)

    def test_refuses_overwrite_without_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            result = self.generate(output, expect_success=False)
            self.assertIn("use --overwrite", result.stderr)
            self.generate(output, "--overwrite")

    def test_overwrite_removes_stale_rendered_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            rendered = output / "kubernetes" / "helm-rendered.yaml"
            rendered.write_text("apiVersion: v1\nkind: ConfigMap\n")

            result = self.generate(output, "--overwrite")

            self.assertFalse(rendered.exists())
            self.assertIn("Removed stale generated artifact", result.stdout)
            self.validate(output)

    def test_legacy_render_provenance_requires_overwrite_and_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            provenance = (
                output
                / "kubernetes"
                / "helm-rendered.provenance.json"
            )
            provenance.parent.mkdir(parents=True)
            provenance.write_text("stale provenance\n", encoding="utf-8")

            refused = self.generate(output, expect_success=False)
            self.assertIn("helm-rendered.provenance.json", refused.stderr)
            self.assertEqual(provenance.read_text(), "stale provenance\n")

            replaced = self.generate(output, "--overwrite")
            self.assertFalse(provenance.exists())
            self.assertIn("Removed stale generated artifact", replaced.stdout)

    def test_legacy_helm_output_requires_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.add_legacy_helm_output(output)

            result = self.generate(output, expect_success=False)

            self.assertIn("use --overwrite", result.stderr)
            self.assertTrue((output / "helm" / "values.yaml").exists())

    def test_overwrite_removes_legacy_helm_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.add_legacy_helm_output(output)

            self.generate(output, "--overwrite")

            self.assertFalse((output / "helm").exists())
            self.validate(output)

    def test_empty_legacy_helm_directory_requires_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            (output / "helm").mkdir(parents=True)

            result = self.generate(output, expect_success=False)

            self.assertIn("use --overwrite", result.stderr)
            self.generate(output, "--overwrite")
            self.assertFalse((output / "helm").exists())
            self.validate(output)

    def test_overwrite_preflights_managed_destinations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            output.mkdir()
            (output / "collector-config.yaml").mkdir()
            rendered = output / "kubernetes" / "helm-rendered.yaml"
            rendered.parent.mkdir()
            rendered.write_text("apiVersion: v1\nkind: ConfigMap\n")

            result = self.generate(
                output,
                "--overwrite",
                expect_success=False,
            )

            self.assertIn("managed output is not a regular file", result.stderr)
            self.assertTrue(rendered.exists())
            self.assertFalse((output / "DEPLOYMENT.md").exists())

    def test_rejects_symlinked_managed_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            output = root / "bundle"
            output.mkdir()
            outside = root / "outside"
            outside.mkdir()
            (output / "helm").symlink_to(outside, target_is_directory=True)
            result = self.generate(output, expect_success=False)
            self.assertIn("must not be a symlink", result.stderr)

    def test_rejects_symlinked_output_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            project = root / "project"
            project.mkdir()
            outside = root / "outside"
            outside.mkdir()
            (project / "deploy").symlink_to(outside, target_is_directory=True)

            result = self.generate(
                project / "deploy" / "otel-collector",
                expect_success=False,
            )

            self.assertIn("symlink component", result.stderr)
            self.assertEqual(list(outside.iterdir()), [])

    def test_accepts_release_name_at_safe_kubernetes_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            result = self.generate(output, "--release-name", "a" * 47)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_release_name_longer_than_safe_kubernetes_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            result = self.generate(
                output,
                "--release-name",
                "a" * 48,
                expect_success=False,
            )
            self.assertIn("must not exceed 47 characters", result.stderr)

    def test_token_arguments_are_rejected_without_echoing_value(self) -> None:
        sentinel = "SENTINEL_COLLECTOR_TOKEN_MUST_NOT_LEAK"
        forms = (("--token", sentinel), (f"--token={sentinel}",))
        for form in forms:
            with self.subTest(form=form), tempfile.TemporaryDirectory() as temp_dir:
                output = Path(temp_dir).resolve() / "bundle"
                result = self.generate(output, *form, expect_success=False)
                combined = result.stdout + result.stderr
                self.assertIn("--token is forbidden", combined)
                self.assertNotIn(sentinel, combined)
                self.assertFalse(output.exists())

    def test_secret_name_errors_never_echo_supplied_value(self) -> None:
        sentinel = "SENTINEL_COLLECTOR_SECRET_MUST_NOT_LEAK"
        forms = (
            ("--secret-name", sentinel),
            (f"--secret-name={sentinel}",),
            ("--existing-secret", sentinel),
            (f"--existing-secret={sentinel}",),
            ("--secret-name", f"--{sentinel}"),
            ("--existing-secret", f"--{sentinel}"),
        )
        for form in forms:
            with self.subTest(form=form), tempfile.TemporaryDirectory() as temp_dir:
                output = Path(temp_dir).resolve() / "bundle"
                result = self.generate(output, *form, expect_success=False)
                combined = result.stdout + result.stderr
                self.assertIn("invalid Kubernetes Secret name", combined)
                self.assertNotIn(sentinel, combined)
                self.assertFalse(output.exists())

    def test_rejects_invalid_collector_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            result = self.generate(
                output,
                "--collector-version",
                "latest",
                expect_success=False,
            )
            self.assertIn("invalid collector version", result.stderr)

    def test_rejects_realm_with_trailing_hyphen(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            result = self.generate(
                output,
                "--realm",
                "us1-",
                expect_success=False,
            )
            self.assertIn("invalid realm", result.stderr)

    def test_validator_rejects_inline_access_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            config_path = output / "collector-config.yaml"
            config_path.write_text(
                config_path.read_text() + "\naccessToken: plaintext-token\n"
            )
            result = self.validate(output, expect_success=False)
            self.assertIn("non-empty inline accessToken", result.stderr)

    def test_validator_rejects_quoted_inline_access_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            config_path = output / "collector-config.yaml"
            config_path.write_text(
                config_path.read_text() + '\n"accessToken": plaintext-token\n'
            )
            result = self.validate(output, expect_success=False)
            self.assertIn("non-empty inline accessToken", result.stderr)

    def test_validator_rejects_duplicate_top_level_collector_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            config_path = output / "collector-config.yaml"
            config_path.write_text(
                config_path.read_text(encoding="utf-8")
                + "\nreceivers:\n  otlp: {}\n",
                encoding="utf-8",
            )

            result = self.validate(output, expect_success=False)

            self.assertIn("duplicate YAML mapping key 'receivers'", result.stderr)

    def test_validator_rejects_literal_x_sf_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            config_path = output / "collector-config.yaml"
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    'X-SF-Token: "${env:SPLUNK_ACCESS_TOKEN}"',
                    'X-SF-Token: "plaintext-token"',
                ),
                encoding="utf-8",
            )

            result = self.validate(output, expect_success=False)

            self.assertIn("contains a literal X-SF-Token value", result.stderr)

    def test_validator_rejects_example_token_outside_secret_example(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            config_path = output / "collector-config.yaml"
            config_path.write_text(
                config_path.read_text(encoding="utf-8")
                + "\nexample: REPLACE_AT_DEPLOY_TIME\n",
                encoding="utf-8",
            )

            result = self.validate(output, expect_success=False)

            self.assertIn("contains an example token value", result.stderr)

    def test_validator_rejects_legacy_rendered_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            rendered = output / "kubernetes" / "helm-rendered.yaml"
            rendered.write_text("apiVersion: v1\nkind: ConfigMap\n")

            result = self.validate(output, expect_success=False)

            self.assertIn("helm-rendered.yaml is no longer generated", result.stderr)

    def test_validator_rejects_legacy_helm_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            (output / "helm").mkdir()

            result = self.validate(output, expect_success=False)

            self.assertIn("helm/ is no longer generated", result.stderr)

    def test_validator_rejects_invalid_image_tag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            manifest_path = output / "kubernetes" / "collector.yaml"
            manifest_path.write_text(
                manifest_path.read_text(encoding="utf-8").replace(
                    "quay.io/signalfx/splunk-otel-collector:0.155.0",
                    "quay.io/signalfx/splunk-otel-collector:latest",
                ),
                encoding="utf-8",
            )

            result = self.validate(output, expect_success=False)

            self.assertIn("must pin exactly one Splunk Collector image tag", result.stderr)

    def test_validator_rejects_manifest_secret_name_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            manifest_path = output / "kubernetes" / "collector.yaml"
            manifest_path.write_text(
                manifest_path.read_text(encoding="utf-8").replace(
                    "name: splunk-otel-secret",
                    "name: other-secret",
                    1,
                ),
                encoding="utf-8",
            )

            result = self.validate(output, expect_success=False)

            self.assertIn("Collector Secret reference name differs", result.stderr)

    def test_validator_rejects_duplicate_service_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            manifest_path = output / "kubernetes" / "collector.yaml"
            service_start = manifest_path.read_text(encoding="utf-8").index(
                "apiVersion: v1\nkind: Service"
            )
            service_end = manifest_path.read_text(encoding="utf-8").index(
                "---\napiVersion: apps/v1"
            )
            service = manifest_path.read_text(encoding="utf-8")[
                service_start:service_end
            ]
            manifest_path.write_text(
                manifest_path.read_text(encoding="utf-8") + "\n---\n" + service,
                encoding="utf-8",
            )

            result = self.validate(output, expect_success=False)

            self.assertIn("must contain exactly one Service", result.stderr)

    def test_validator_rejects_duplicate_token_example_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            secret = output / "kubernetes" / "splunk-secret.example.yaml"
            secret.write_text(
                secret.read_text(encoding="utf-8")
                + "\n  splunk_observability_access_token: REPLACE_AT_DEPLOY_TIME\n",
                encoding="utf-8",
            )

            result = self.validate(output, expect_success=False)

            self.assertIn("duplicate YAML mapping key", result.stderr)
            self.assertIn("must contain exactly one access-token key", result.stderr)


if __name__ == "__main__":
    unittest.main()
