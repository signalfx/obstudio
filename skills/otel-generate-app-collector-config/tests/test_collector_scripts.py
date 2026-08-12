from __future__ import annotations

import json
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
            "0.157.0",
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
        owner = output / ".otel-generate-app-collector-config.json"
        archive = (
            output
            / "helm"
            / "charts"
            / "splunk-otel-collector-0.155.0.tgz"
        )
        for path in (chart, values, secret, lock, archive, owner):
            path.parent.mkdir(parents=True, exist_ok=True)
        chart.write_text("apiVersion: v2\nname: old\n", encoding="utf-8")
        values.write_text("collector: {}\n", encoding="utf-8")
        secret.write_text("apiVersion: v1\nkind: Secret\n", encoding="utf-8")
        lock.write_text("stale lock\n", encoding="utf-8")
        archive.write_bytes(b"stale archive")
        owner.write_text(
            json.dumps(
                {
                    "generator": "otel-generate-app-collector-config",
                    "managedFiles": [
                        ".otel-generate-app-collector-config.json",
                        "DEPLOYMENT.md",
                        "collector-config.yaml",
                        "helm/Chart.yaml",
                        "helm/examples/splunk-secret.yaml",
                        "helm/values.yaml",
                        "kubernetes/collector.yaml",
                        "kubernetes/splunk-secret.example.yaml",
                    ],
                    "version": 1,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def test_generates_token_free_kubernetes_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "deploy" / "otel-collector"
            result = self.generate(output)

            self.assertIn("No access token was read or written.", result.stdout)
            self.assertIn("Next commands:", result.stdout)
            self.assertIn(
                "--from-file=splunk_observability_access_token=/dev/stdin",
                result.stdout,
            )
            self.assertIn("read -rs SPLUNK_ACCESS_TOKEN", result.stdout)
            self.assertIn(
                f"kubectl apply -f {output / 'kubernetes' / 'collector.yaml'}",
                result.stdout,
            )
            self.assertIn(
                "rollout restart deployment/splunk-otel-collector-agent",
                result.stdout,
            )
            self.assertIn(
                "rollout status deployment/splunk-otel-collector-agent",
                result.stdout,
            )
            self.assertNotIn(
                "--from-literal=splunk_observability_access_token",
                result.stdout,
            )
            self.assertNotIn("read -rsp", result.stdout)
            self.validate(output)

            collector = (output / "collector-config.yaml").read_text()
            chart = (output / "helm" / "Chart.yaml").read_text()
            values = (output / "helm" / "values.yaml").read_text()
            helm_secret = (
                output / "helm" / "examples" / "splunk-secret.yaml"
            ).read_text()
            manifest = (output / "kubernetes" / "collector.yaml").read_text()
            secret = (
                output / "kubernetes" / "splunk-secret.example.yaml"
            ).read_text()
            deployment = (output / "DEPLOYMENT.md").read_text()
            owner = json.loads(
                (output / ".otel-generate-app-collector-config.json").read_text()
            )

            self.assertFalse((output / "kubernetes" / "helm-rendered.yaml").exists())
            self.assertEqual(
                owner["generator"],
                "otel-generate-app-collector-config",
            )
            self.assertIn("collector-config.yaml", owner["managedFiles"])
            self.assertIn("helm/values.yaml", owner["managedFiles"])
            self.assertIn("version: \"0.157.0\"", chart)
            self.assertIn(
                "repository: \"https://signalfx.github.io/splunk-otel-collector-chart\"",
                chart,
            )
            self.assertIn("realm: \"us1\"", values)
            self.assertIn("name: \"splunk-otel-secret\"", values)
            self.assertIn("enabled: false", values)
            self.assertNotIn("tokenPassthrough", values)
            self.assertIn("${env:SPLUNK_ACCESS_TOKEN}", collector)
            self.assertIn("otlphttp/splunk:", collector)
            self.assertIn("exporters: [otlphttp/splunk]", collector)
            self.assertIn("resource/identity:", collector)
            self.assertIn("key: k8s.cluster.name", collector)
            self.assertIn('value: "checkout-prod"', collector)
            self.assertIn("key: deployment.environment", collector)
            self.assertIn('value: "production"', collector)
            self.assertIn(
                "processors: [memory_limiter, resource/identity, batch]",
                collector,
            )
            self.assertNotIn("otlp_http/splunk", collector)
            self.assertIn("kind: Service", manifest)
            self.assertIn("kind: Deployment", manifest)
            self.assertIn("name: splunk-otel-collector-agent", manifest)
            self.assertIn("otlphttp/splunk:", manifest)
            self.assertIn("exporters: [otlphttp/splunk]", manifest)
            self.assertIn("resource/identity:", manifest)
            self.assertIn("key: k8s.cluster.name", manifest)
            self.assertIn('value: "checkout-prod"', manifest)
            self.assertIn("key: deployment.environment", manifest)
            self.assertIn('value: "production"', manifest)
            self.assertIn(
                "processors: [memory_limiter, resource/identity, batch]",
                manifest,
            )
            self.assertNotIn("otlp_http/splunk", manifest)
            self.assertIn(
                "image: \"quay.io/signalfx/splunk-otel-collector:0.157.0\"",
                manifest,
            )
            self.assertIn("name: splunk-otel-secret", manifest)
            self.assertIn("key: splunk_observability_access_token", manifest)
            self.assertIn(
                "splunk_observability_access_token: REPLACE_AT_DEPLOY_TIME",
                secret,
            )
            self.assertIn(
                "splunk_observability_access_token: REPLACE_AT_DEPLOY_TIME",
                helm_secret,
            )
            self.assertIn("helm/values.yaml", deployment)
            self.assertIn("kubernetes/collector.yaml", deployment)
            self.assertIn("does not require the Helm CLI", deployment)
            self.assertIn("Local kind smoke test", deployment)
            self.assertIn(
                "kubectl cluster-info --context kind-checkout-prod",
                deployment,
            )
            self.assertIn(
                "--from-file=splunk_observability_access_token=/dev/stdin",
                deployment,
            )
            self.assertIn("read -rs SPLUNK_ACCESS_TOKEN", deployment)
            self.assertNotIn("read -rsp", deployment)
            self.assertIn(
                "rollout restart daemonset/splunk-otel-collector-agent",
                deployment,
            )
            self.assertIn(
                "rollout restart deployment/splunk-otel-collector-agent",
                deployment,
            )
            self.assertIn(
                "ghcr.io/open-telemetry/opentelemetry-collector-contrib/telemetrygen:v0.157.0",
                deployment,
            )
            self.assertIn("timeserieswindow", deployment)
            self.assertIn("ingest.us1.observability.splunkcloud.com", deployment)
            self.assertIn("k8s.cluster.name=checkout-prod", deployment)
            self.assertIn("deployment.environment=production", deployment)
            self.assertIn("query token is not accepted", deployment)
            self.assertNotIn("helm-rendered", deployment)

    def test_kind_smoke_commands_use_dns_safe_demo_cluster_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            result = self.generate(
                output,
                "--cluster-name",
                "demo$(touch /tmp/pwn)",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            deployment = (output / "DEPLOYMENT.md").read_text()
            self.assertIn(
                "kind create cluster --name demo-touch-tmp-pwn",
                deployment,
            )
            self.assertIn(
                "kubectl cluster-info --context kind-demo-touch-tmp-pwn",
                deployment,
            )
            self.assertNotIn("kind create cluster --name demo$(touch", deployment)
            self.assertNotIn("--context kind-demo$(touch", deployment)

    def test_gateway_mode_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output, "--gateway")
            manifest = (output / "kubernetes" / "collector.yaml").read_text()
            values = (output / "helm" / "values.yaml").read_text()
            deployment = (output / "DEPLOYMENT.md").read_text()
            self.assertIn("name: splunk-otel-collector", manifest)
            self.assertIn("enabled: true", values)
            self.assertIn("tokenPassthrough: false", values)
            self.assertIn(
                "rollout restart deployment/splunk-otel-collector",
                deployment,
            )

    def test_rejects_agent_service_on_eks_fargate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            result = self.generate(
                output,
                "--distribution",
                "eks/fargate",
                expect_success=False,
            )

            self.assertIn("requires --topology gateway", result.stderr)
            self.assertFalse(output.exists())

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
            values = (output / "helm" / "values.yaml").read_text()
            self.assertIn("realm: \"us0\"", values)
            self.assertIn("name: \"splunk-otel-secret\"", values)
            self.assertIn("enabled: true", values)
            self.assertIn("tokenPassthrough: false", values)

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

    def test_overwrite_rejects_unowned_managed_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            hand_authored = output / "helm" / "values.yaml"
            hand_authored.parent.mkdir(parents=True)
            hand_authored.write_text("collector:\n  handAuthored: true\n")

            result = self.generate(output, "--overwrite", expect_success=False)

            self.assertIn("refuse to overwrite unowned files", result.stderr)
            self.assertEqual(
                hand_authored.read_text(),
                "collector:\n  handAuthored: true\n",
            )
            self.assertFalse((output / "collector-config.yaml").exists())

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
            self.generate(output)
            provenance = (
                output
                / "kubernetes"
                / "helm-rendered.provenance.json"
            )
            provenance.write_text("stale provenance\n", encoding="utf-8")

            refused = self.generate(output, expect_success=False)
            self.assertIn("use --overwrite", refused.stderr)
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

    def test_overwrite_removes_stale_helm_dependency_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.add_legacy_helm_output(output)

            self.generate(output, "--overwrite")

            self.assertTrue((output / "helm" / "Chart.yaml").is_file())
            self.assertTrue((output / "helm" / "values.yaml").is_file())
            self.assertTrue(
                (output / "helm" / "examples" / "splunk-secret.yaml").is_file()
            )
            self.assertFalse((output / "helm" / "Chart.lock").exists())
            self.assertFalse(
                (
                    output
                    / "helm"
                    / "charts"
                    / "splunk-otel-collector-0.155.0.tgz"
                ).exists()
            )
            chart = (output / "helm" / "Chart.yaml").read_text()
            values = (output / "helm" / "values.yaml").read_text()
            self.assertIn("version: \"0.157.0\"", chart)
            self.assertIn("clusterName: \"checkout-prod\"", values)
            self.validate(output)

    def test_generates_into_empty_helm_directory_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            (output / "helm").mkdir(parents=True)

            result = self.generate(output)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output / "helm" / "Chart.yaml").is_file())
            self.assertTrue((output / "helm" / "values.yaml").is_file())
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

    def test_rejects_malformed_chart_prerelease_versions(self) -> None:
        invalid_versions = (
            "0.157.0-..",
            "0.157.0-01",
            "0.157.0-alpha..1",
            "0.157.0-alpha.01",
        )
        for version in invalid_versions:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temp_dir:
                output = Path(temp_dir).resolve() / "bundle"
                result = self.generate(
                    output,
                    "--chart-version",
                    version,
                    expect_success=False,
                )
                self.assertIn("invalid chart version", result.stderr)
                self.assertFalse(output.exists())

    def test_accepts_valid_chart_prerelease_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            result = self.generate(
                output,
                "--chart-version",
                "0.157.0-alpha.1",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.validate(output)

    def test_rejects_chart_version_with_build_metadata_for_image_tag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            result = self.generate(
                output,
                "--chart-version",
                "0.157.0+build",
                expect_success=False,
            )
            self.assertIn("invalid collector image tag", result.stderr)
            self.assertFalse(output.exists())

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

    def test_validator_rejects_invalid_collector_exporter_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            config_path = output / "collector-config.yaml"
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    "otlphttp/splunk",
                    "otlp_http/splunk",
                ),
                encoding="utf-8",
            )
            manifest_path = output / "kubernetes" / "collector.yaml"
            manifest_path.write_text(
                manifest_path.read_text(encoding="utf-8").replace(
                    "otlphttp/splunk",
                    "otlp_http/splunk",
                ),
                encoding="utf-8",
            )

            result = self.validate(output, expect_success=False)

            self.assertIn(
                "collector-config.yaml missing required value: otlphttp/splunk:",
                result.stderr,
            )
            self.assertIn(
                "collector-config.yaml missing required value: exporters: [otlphttp/splunk]",
                result.stderr,
            )
            self.assertIn(
                "collector-config.yaml uses invalid Collector exporter type otlp_http",
                result.stderr,
            )
            self.assertIn(
                "kubernetes/collector.yaml missing required value: otlphttp/splunk:",
                result.stderr,
            )
            self.assertIn(
                "kubernetes/collector.yaml missing required value: exporters: [otlphttp/splunk]",
                result.stderr,
            )
            self.assertIn(
                "kubernetes/collector.yaml uses invalid Collector exporter type otlp_http",
                result.stderr,
            )

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

    def test_validator_rejects_unexpected_helm_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            unexpected = output / "helm" / "templates" / "configmap.yaml"
            unexpected.parent.mkdir()
            unexpected.write_text("apiVersion: v1\nkind: ConfigMap\n")

            result = self.validate(output, expect_success=False)

            self.assertIn("unexpected Helm input", result.stderr)

    def test_validator_rejects_invalid_image_tag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            manifest_path = output / "kubernetes" / "collector.yaml"
            manifest_path.write_text(
                manifest_path.read_text(encoding="utf-8").replace(
                    "quay.io/signalfx/splunk-otel-collector:0.157.0",
                    "quay.io/signalfx/splunk-otel-collector:latest",
                ),
                encoding="utf-8",
            )

            result = self.validate(output, expect_success=False)

            self.assertIn("must pin exactly one Splunk Collector image tag", result.stderr)

    def test_validator_rejects_image_tag_with_build_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir).resolve() / "bundle"
            self.generate(output)
            chart_path = output / "helm" / "Chart.yaml"
            chart_path.write_text(
                chart_path.read_text(encoding="utf-8").replace(
                    'version: "0.157.0"',
                    'version: "0.157.0+build"',
                ),
                encoding="utf-8",
            )
            manifest_path = output / "kubernetes" / "collector.yaml"
            manifest_path.write_text(
                manifest_path.read_text(encoding="utf-8").replace(
                    "quay.io/signalfx/splunk-otel-collector:0.157.0",
                    "quay.io/signalfx/splunk-otel-collector:0.157.0+build",
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
