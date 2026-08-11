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
            "--chart-version",
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

    def add_locked_dependency(self, output: Path) -> None:
        (output / "helm" / "Chart.lock").write_text(
            "dependencies:\n"
            "- name: splunk-otel-collector\n"
            "  repository: "
            "https://signalfx.github.io/splunk-otel-collector-chart\n"
            "  version: 0.155.0\n"
            "digest: sha256:placeholder\n"
            "generated: now\n",
            encoding="utf-8",
        )
        archive = (
            output
            / "helm"
            / "charts"
            / "splunk-otel-collector-0.155.0.tgz"
        )
        archive.parent.mkdir()
        archive.write_bytes(b"chart archive")

    def test_generates_token_free_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "deploy" / "otel-collector"
            result = self.generate(output)

            self.assertIn("No access token was read or written.", result.stdout)
            self.validate(output)

            collector = (output / "collector-config.yaml").read_text()
            chart = (output / "helm" / "Chart.yaml").read_text()
            values = (output / "helm" / "values.yaml").read_text()
            manifest = (output / "kubernetes" / "collector.yaml").read_text()
            secret = (
                output / "kubernetes" / "splunk-secret.example.yaml"
            ).read_text()
            deployment = (output / "DEPLOYMENT.md").read_text()

            self.assertIn("${env:SPLUNK_ACCESS_TOKEN}", collector)
            self.assertIn('version: "0.155.0"', chart)
            self.assertIn('realm: "us1"', values)
            self.assertIn("enabled: false", values)
            self.assertNotIn("accessToken:", values)
            self.assertNotIn("tokenPassthrough:", values)
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
            self.assertIn(
                "kubernetes/collector.yaml",
                deployment,
            )
            self.assertNotIn("helm-rendered", deployment)

    def test_gateway_mode_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output, "--gateway")
            values = (output / "helm" / "values.yaml").read_text()
            deployment = (output / "DEPLOYMENT.md").read_text()
            self.assertIn("gateway:\n    enabled: true", values)
            self.assertIn("centralized OTLP gateway", deployment)

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
                "--chart-version",
                "0.157.0",
            ]
            result = subprocess.run(command, capture_output=True, text=True)

            self.assertEqual(result.returncode, 0, result.stderr)
            values = (output / "helm" / "values.yaml").read_text()
            manifest = (output / "kubernetes" / "collector.yaml").read_text()
            self.assertIn('clusterName: "checkout-prod"', values)
            self.assertIn("gateway:\n    enabled: true", values)
            self.assertIn("tokenPassthrough: false", values)
            self.assertIn("name: splunk-otel-collector", manifest)
            self.assertIn(
                'name: "splunk-otel-secret"',
                values,
            )

    def test_existing_secret_alias_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            result = self.generate(
                output,
                "--existing-secret",
                "splunk-otel-token",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            values = (output / "helm" / "values.yaml").read_text()
            manifest = (output / "kubernetes" / "collector.yaml").read_text()
            self.assertIn('name: "splunk-otel-token"', values)
            self.assertIn("name: splunk-otel-token", manifest)

    def test_chart_0156_omits_unsupported_gateway_token_passthrough(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(
                output,
                "--chart-version",
                "0.156.0",
                "--gateway",
            )
            values = (output / "helm" / "values.yaml").read_text()
            self.assertNotIn("tokenPassthrough:", values)

    def test_newer_chart_disables_gateway_token_passthrough(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(
                output,
                "--chart-version",
                "0.157.0",
                "--gateway",
            )
            values = (output / "helm" / "values.yaml").read_text()
            self.assertIn("tokenPassthrough: false", values)
            self.validate(output)

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
            self.assertIn(
                "helm-rendered.provenance.json", refused.stderr
            )
            self.assertEqual(provenance.read_text(), "stale provenance\n")

            replaced = self.generate(output, "--overwrite")
            self.assertFalse(provenance.exists())
            self.assertIn(
                "Removed stale generated artifact", replaced.stdout
            )

    def test_overwrite_removes_stale_helm_dependency_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            chart_lock = output / "helm" / "Chart.lock"
            chart_lock.write_text("stale lock\n")
            chart_archive = (
                output
                / "helm"
                / "charts"
                / "splunk-otel-collector-0.155.0.tgz"
            )
            chart_archive.parent.mkdir()
            chart_archive.write_bytes(b"stale archive")

            self.generate(
                output,
                "--overwrite",
                "--chart-version",
                "0.156.0",
            )

            self.assertFalse(chart_lock.exists())
            self.assertFalse(chart_archive.exists())
            self.assertIn(
                'version: "0.156.0"',
                (output / "helm" / "Chart.yaml").read_text(),
            )
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

            self.assertIn(
                "managed output is not a regular file",
                result.stderr,
            )
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
            (project / "deploy").symlink_to(
                outside,
                target_is_directory=True,
            )

            result = self.generate(
                project / "deploy" / "otel-collector",
                expect_success=False,
            )

            self.assertIn("symlink component", result.stderr)
            self.assertEqual(list(outside.iterdir()), [])

    def test_accepts_release_name_at_safe_helm_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            result = self.generate(
                output,
                "--release-name",
                "a" * 47,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_release_name_longer_than_safe_helm_limit(self) -> None:
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

    def test_rejects_invalid_chart_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            result = self.generate(
                output,
                "--chart-version",
                "latest",
                expect_success=False,
            )
            self.assertIn("invalid chart version", result.stderr)

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
            values_path = output / "helm" / "values.yaml"
            values_path.write_text(
                values_path.read_text() + "\n    accessToken: plaintext-token\n"
            )
            result = self.validate(output, expect_success=False)
            self.assertIn("non-empty inline accessToken", result.stderr)

    def test_validator_rejects_quoted_inline_access_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            values_path = output / "helm" / "values.yaml"
            values_path.write_text(
                values_path.read_text()
                + '\n    "accessToken": plaintext-token\n'
            )
            result = self.validate(output, expect_success=False)
            self.assertIn("non-empty inline accessToken", result.stderr)

    def test_validator_rejects_duplicate_enabled_token_passthrough(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(
                output,
                "--chart-version",
                "0.157.0",
                "--gateway",
            )
            values_path = output / "helm" / "values.yaml"
            values_path.write_text(
                values_path.read_text()
                + '\n    "tokenPassthrough": true\n'
            )
            result = self.validate(output, expect_success=False)
            self.assertIn(
                "duplicate gateway tokenPassthrough",
                result.stderr,
            )
            self.assertIn(
                "enables gateway token passthrough",
                result.stderr,
            )

    def test_validator_rejects_duplicate_top_level_collector_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            values_path = output / "helm" / "values.yaml"
            values_path.write_text(
                values_path.read_text(encoding="utf-8")
                + "\ncollector:\n  gateway:\n    enabled: false\n",
                encoding="utf-8",
            )

            result = self.validate(output, expect_success=False)

            self.assertIn("duplicate YAML mapping key 'collector'", result.stderr)

    def test_validator_rejects_false_setting_despite_comment_decoy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            values_path = output / "helm" / "values.yaml"
            values_path.write_text(
                values_path.read_text(encoding="utf-8").replace(
                    "    metricsEnabled: true",
                    "    metricsEnabled: false\n    # metricsEnabled: true",
                ),
                encoding="utf-8",
            )

            result = self.validate(output, expect_success=False)

            self.assertIn(
                "collector.splunkObservability.metricsEnabled=true",
                result.stderr,
            )

    def test_validator_rejects_realm_with_trailing_hyphen_after_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            values_path = output / "helm" / "values.yaml"
            values_path.write_text(
                values_path.read_text(encoding="utf-8").replace(
                    'realm: "us1"',
                    'realm: "us1-"',
                ),
                encoding="utf-8",
            )

            result = self.validate(output, expect_success=False)

            self.assertIn("invalid Collector realm", result.stderr)

    def test_validator_checks_the_dependency_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            chart_path = output / "helm" / "Chart.yaml"
            chart_path.write_text(
                chart_path.read_text().replace(
                    'version: "0.155.0"',
                    'version: "latest"',
                )
            )
            result = self.validate(output, expect_success=False)
            self.assertIn("dependency version is not exact semver", result.stderr)

    def test_validator_rejects_stale_chart_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            (output / "helm" / "Chart.lock").write_text(
                "dependencies:\n"
                "- name: splunk-otel-collector\n"
                "  repository: "
                "https://signalfx.github.io/splunk-otel-collector-chart\n"
                "  version: 0.154.0\n"
                "digest: sha256:placeholder\n"
                "generated: now\n"
            )
            result = self.validate(output, expect_success=False)
            self.assertIn("Chart.lock is stale", result.stderr)

    def test_validator_rejects_wrong_chart_lock_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            (output / "helm" / "Chart.lock").write_text(
                "dependencies:\n"
                "- name: splunk-otel-collector\n"
                "  repository: https://example.invalid\n"
                "  version: 0.155.0\n"
                "digest: sha256:placeholder\n"
                "generated: now\n"
            )
            result = self.validate(output, expect_success=False)
            self.assertIn(
                "Chart.lock does not use the official chart repository",
                result.stderr,
            )

    def test_validator_allows_only_the_expected_locked_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            self.add_locked_dependency(output)

            self.validate(output)

    def test_validator_rejects_unexpected_helm_inputs(self) -> None:
        cases = {
            "templates/backdoor.yaml": "apiVersion: v1\nkind: ConfigMap\n",
            "crds/backdoor.yaml": "apiVersion: v1\nkind: ConfigMap\n",
            ".helmignore": "templates/\n",
            "values.schema.json": "{}\n",
            "charts/unpacked/Chart.yaml": "apiVersion: v2\nname: unpacked\n",
        }
        for relative, content in cases.items():
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temp_dir:
                output = Path(temp_dir).resolve() / "bundle"
                self.generate(output)
                unexpected = output / "helm" / relative
                unexpected.parent.mkdir(parents=True, exist_ok=True)
                unexpected.write_text(content, encoding="utf-8")

                result = self.validate(output, expect_success=False)

                self.assertIn("unexpected Helm input", result.stderr)
                self.assertIn(f"helm/{relative}", result.stderr)

    def test_validator_rejects_duplicate_literal_example_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            secret_path = (
                output / "kubernetes" / "splunk-secret.example.yaml"
            )
            secret_path.write_text(
                secret_path.read_text()
                + "\n  splunk_observability_access_token: literal-token\n"
            )
            result = self.validate(output, expect_success=False)
            self.assertIn(
                "must contain exactly one access-token key",
                result.stderr,
            )

    def test_validator_rejects_quoted_duplicate_example_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            secret_path = (
                output / "helm" / "examples" / "splunk-secret.yaml"
            )
            secret_path.write_text(
                secret_path.read_text()
                + '\n  "splunk_observability_access_token": literal-token\n'
            )
            result = self.validate(output, expect_success=False)
            self.assertIn(
                "must contain exactly one access-token key",
                result.stderr,
            )

    def test_validator_scans_additional_yaml_for_literal_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            extra = output / "extra-values.yaml"
            extra.write_text("headers:\n  X-SF-Token: literal-token\n")
            result = self.validate(output, expect_success=False)
            self.assertIn("literal X-SF-Token value", result.stderr)

    def test_validator_rejects_base64_token_secret_outside_examples(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            secret = output / "kubernetes" / "splunk-secret.yaml"
            encoded_token = "U0VOVElORUxfQUNDRVNTX1RPS0VO"
            secret.write_text(
                "apiVersion: v1\n"
                "kind: Secret\n"
                "metadata:\n"
                "  name: splunk-otel-token\n"
                "  namespace: observability\n"
                "type: Opaque\n"
                "data:\n"
                "  splunk_observability_access_token: "
                f"{encoded_token}\n",
                encoding="utf-8",
            )

            result = self.validate(output, expect_success=False)
            combined = result.stdout + result.stderr

            self.assertIn(
                "Collector access-token key outside an approved example Secret",
                combined,
            )
            self.assertNotIn(encoded_token, combined)

    def test_validator_rejects_hooks_in_generated_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            manifest = output / "kubernetes" / "collector.yaml"
            manifest.write_text(
                manifest.read_text()
                + "\n# helm.sh/hook: pre-install\n",
                encoding="utf-8",
            )
            result = self.validate(output, expect_success=False)
            self.assertIn("contains Helm hooks", result.stderr)

    def test_validator_rejects_missing_otlp_http_service_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            manifest = output / "kubernetes" / "collector.yaml"
            manifest.write_text(
                manifest.read_text(encoding="utf-8").replace(
                    "      port: 4318\n",
                    "      port: 14318\n",
                    count=1,
                ),
                encoding="utf-8",
            )

            result = self.validate(output, expect_success=False)

            self.assertIn(
                "OTLP/HTTP Service route: port 'otlp-http'=4318",
                result.stderr,
            )

    def test_validator_rejects_duplicate_otlp_http_service_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            manifest = output / "kubernetes" / "collector.yaml"
            service_port = (
                "    - name: otlp-http\n"
                "      port: 4318\n"
                "      targetPort: otlp-http\n"
                "      protocol: TCP\n"
            )
            manifest.write_text(
                manifest.read_text(encoding="utf-8").replace(
                    service_port,
                    service_port + service_port,
                    count=1,
                ),
                encoding="utf-8",
            )

            result = self.validate(output, expect_success=False)

            self.assertIn(
                "OTLP/HTTP Service route: port 'otlp-http'=4318",
                result.stderr,
            )


if __name__ == "__main__":
    unittest.main()
