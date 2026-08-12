from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
GENERATE_COLLECTOR = SKILL_DIR / "scripts" / "generate_collector.py"
GENERATE_APPLICATION = SKILL_DIR / "scripts" / "generate_application.py"
VALIDATE_CONFIG = SKILL_DIR / "scripts" / "validate_config.py"


class CoordinatedConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve()
        (self.workspace / ".git").mkdir()
        self.app = self.workspace / "checkout"
        self.base = self.app / "kubernetes" / "deployment.yaml"
        self.base.parent.mkdir(parents=True)
        self.base.write_text(
            """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: checkout
  namespace: checkout
spec:
  template:
    spec:
      containers:
        - name: checkout
          image: example.invalid/checkout:1
""",
            encoding="utf-8",
        )
        self.collector = self.workspace / "deploy" / "otel-collector"
        self.application = self.app / "deploy" / "otel-config"

    @property
    def collector_yaml(self) -> Path:
        return self.collector / "kubernetes" / "collector.yaml"

    def run_command(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=self.workspace,
            text=True,
            capture_output=True,
            check=False,
        )

    def generate(
        self,
        *,
        protocol: str = "http/protobuf",
        cluster_domain: str | None = None,
        application_output: Path | None = None,
    ) -> None:
        collector = self.run_command(
            [
                sys.executable,
                str(GENERATE_COLLECTOR),
                "--output",
                str(self.collector),
                "--realm",
                "us0",
                "--cluster-name",
                "checkout-kind",
                "--environment",
                "test",
                "--namespace",
                "observability",
                "--release-name",
                "splunk-otel",
                "--existing-secret",
                "splunk-otel-token",
                "--distribution",
                "other",
                "--collector-version",
                "0.157.0",
            ]
        )
        self.assertEqual(collector.returncode, 0, collector.stderr)
        application_command = [
            sys.executable,
            str(GENERATE_APPLICATION),
            "--app",
            str(self.app),
            "--workspace-root",
            str(self.workspace),
            "--realm",
            "us0",
            "--existing-secret",
            "splunk-otel-token",
            "--collector-evidence",
            str(self.collector_yaml),
            "--protocol",
            protocol,
            "--base",
            "kubernetes/deployment.yaml",
            "--application-namespace",
            "checkout",
            "--workload-kind",
            "Deployment",
            "--workload-name",
            "checkout",
            "--container",
            "checkout",
        ]
        if cluster_domain:
            application_command.extend(["--cluster-domain", cluster_domain])
        if application_output is not None:
            self.application = application_output
            application_command.extend(["--output", str(application_output)])
        application = self.run_command(application_command)
        self.assertEqual(application.returncode, 0, application.stderr)

    def validate(self) -> subprocess.CompletedProcess[str]:
        return self.run_command(
            [
                sys.executable,
                str(VALIDATE_CONFIG),
                "--collector",
                str(self.collector),
                "--application",
                str(self.application),
            ]
        )

    def rewrite_contract_hash(self, replacement: Path) -> None:
        contract = self.application / "otel-connection.yaml"
        text = contract.read_text(encoding="utf-8")
        digest = hashlib.sha256(replacement.read_bytes()).hexdigest()
        text = re.sub(
            r'^  sha256: "[0-9a-f]{64}"$',
            f'  sha256: "{digest}"',
            text,
            count=1,
            flags=re.MULTILINE,
        )
        contract.write_text(text, encoding="utf-8")

    def test_matching_configs_validate(self) -> None:
        self.generate()

        result = self.validate()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No resources were deployed", result.stdout)
        contract = (self.application / "otel-connection.yaml").read_text()
        self.assertIn('source: "../deploy/otel-collector/kubernetes/collector.yaml"', contract)
        self.assertIn('serviceResolution: "generated-collector-yaml"', contract)

    def test_custom_application_output_depth_validates(self) -> None:
        (self.workspace / ".git").rmdir()
        self.generate(application_output=self.app / "otel-config")

        result = self.validate()

        self.assertEqual(result.returncode, 0, result.stderr)
        contract = (self.application / "otel-connection.yaml").read_text()
        self.assertIn('root: ".."', contract)
        self.assertIn('workspaceRoot: "../.."', contract)

    def test_application_root_escape_is_rejected(self) -> None:
        self.generate()
        contract = self.application / "otel-connection.yaml"
        contract.write_text(
            contract.read_text(encoding="utf-8").replace(
                'root: "../.."',
                'root: "../../../.."',
            ),
            encoding="utf-8",
        )

        result = self.validate()

        self.assertEqual(result.returncode, 1)
        self.assertIn("application root escapes the workspace", result.stderr)

    def test_grpc_custom_domain_validate(self) -> None:
        self.generate(protocol="grpc", cluster_domain="cluster.internal")

        result = self.validate()

        self.assertEqual(result.returncode, 0, result.stderr)
        contract = (self.application / "otel-connection.yaml").read_text()
        self.assertIn(
            'endpoint: "http://splunk-otel-collector.observability.svc.cluster.internal:4317"',
            contract,
        )

    def test_collector_service_override_validates_against_evidence(self) -> None:
        collector = self.run_command(
            [
                sys.executable,
                str(GENERATE_COLLECTOR),
                "--output",
                str(self.collector),
                "--realm",
                "us0",
                "--cluster-name",
                "checkout-kind",
                "--environment",
                "test",
                "--namespace",
                "observability",
                "--release-name",
                "splunk-otel",
                "--existing-secret",
                "splunk-otel-token",
                "--distribution",
                "other",
                "--collector-version",
                "0.157.0",
            ]
        )
        self.assertEqual(collector.returncode, 0, collector.stderr)
        custom_service = "otel-us0-gateway"
        collector_text = self.collector_yaml.read_text(encoding="utf-8")
        collector_text = collector_text.replace(
            "kind: Service\nmetadata:\n  name: splunk-otel-collector\n",
            f"kind: Service\nmetadata:\n  name: {custom_service}\n",
            1,
        )
        self.collector_yaml.write_text(collector_text, encoding="utf-8")

        application = self.run_command(
            [
                sys.executable,
                str(GENERATE_APPLICATION),
                "--app",
                str(self.app),
                "--workspace-root",
                str(self.workspace),
                "--realm",
                "us0",
                "--existing-secret",
                "splunk-otel-token",
                "--collector-evidence",
                str(self.collector_yaml),
                "--collector-service",
                custom_service,
                "--base",
                "kubernetes/deployment.yaml",
                "--application-namespace",
                "checkout",
                "--workload-kind",
                "Deployment",
                "--workload-name",
                "checkout",
                "--container",
                "checkout",
            ]
        )
        self.assertEqual(application.returncode, 0, application.stderr)

        result = self.validate()

        self.assertEqual(result.returncode, 0, result.stderr)
        contract = (self.application / "otel-connection.yaml").read_text()
        self.assertIn(f'service: "{custom_service}"', contract)

    def test_realm_drift_is_rejected(self) -> None:
        self.generate()
        self.collector_yaml.write_text(
            self.collector_yaml.read_text().replace(
                'value: "us0"',
                'value: "us1"',
            )
        )
        self.rewrite_contract_hash(self.collector_yaml)

        result = self.validate()

        self.assertEqual(result.returncode, 1)
        self.assertIn("realm differs", result.stderr)

    def test_release_drift_is_rejected(self) -> None:
        self.generate()
        contract = self.application / "otel-connection.yaml"
        contract.write_text(
            contract.read_text(encoding="utf-8").replace(
                'release: "splunk-otel"',
                'release: "other-otel"',
                1,
            ),
            encoding="utf-8",
        )

        result = self.validate()

        self.assertEqual(result.returncode, 1)
        self.assertIn("Collector release differs", result.stderr)

    def test_application_patch_target_identity_drift_is_rejected(self) -> None:
        self.generate()
        patch = self.application / "kubernetes" / "otel-env-patch.yaml"
        original = patch.read_text(encoding="utf-8")
        self.addCleanup(patch.write_text, original, encoding="utf-8")
        headers = original.splitlines()[:2]
        cases = (
            (
                "apiVersion",
                'apiVersion: "apps/v1"',
                'apiVersion: "apps/v2"',
                "application patch apiVersion differs",
            ),
            (
                "kind",
                'kind: "Deployment"',
                'kind: "StatefulSet"',
                "application patch kind differs",
            ),
            (
                "workload name",
                'metadata:\n  name: "checkout"\n  namespace: "checkout"',
                'metadata:\n  name: "worker"\n  namespace: "checkout"',
                "application patch workload name differs",
            ),
            (
                "namespace",
                'metadata:\n  name: "checkout"\n  namespace: "checkout"',
                'metadata:\n  name: "checkout"\n  namespace: "worker"',
                "application patch namespace differs",
            ),
            (
                "container",
                '      containers:\n        -\n          name: "checkout"',
                '      containers:\n        -\n          name: "worker"',
                "application patch target container differs",
            ),
        )
        for label, before, after, expected_error in cases:
            with self.subTest(label=label):
                drifted = original.replace(before, after, 1)
                self.assertNotEqual(drifted, original)
                self.assertEqual(drifted.splitlines()[:2], headers)
                patch.write_text(drifted, encoding="utf-8")

                result = self.validate()

                self.assertEqual(result.returncode, 1)
                self.assertIn(expected_error, result.stderr)

    def test_kustomization_patch_target_drift_is_rejected(self) -> None:
        self.generate()
        kustomization = self.application / "kubernetes" / "kustomization.yaml"
        original = kustomization.read_text(encoding="utf-8")
        self.addCleanup(kustomization.write_text, original, encoding="utf-8")
        headers = original.splitlines()[:2]
        cases = (
            (
                "path",
                'path: "otel-env-patch.yaml"',
                'path: "worker-env-patch.yaml"',
                "does not structurally reference the generated patch",
            ),
            (
                "apiVersion",
                'group: "apps"\n      version: "v1"',
                'group: "apps"\n      version: "v2"',
                "target apiVersion differs",
            ),
            (
                "kind",
                'kind: "Deployment"',
                'kind: "StatefulSet"',
                "target kind differs",
            ),
            (
                "workload name",
                'name: "^checkout$"\n      namespace: "checkout"',
                'name: "^worker$"\n      namespace: "checkout"',
                "target name differs",
            ),
            (
                "namespace",
                'name: "^checkout$"\n      namespace: "checkout"',
                'name: "^checkout$"\n      namespace: "worker"',
                "target namespace differs",
            ),
        )
        for label, before, after, expected_error in cases:
            with self.subTest(label=label):
                drifted = original.replace(before, after, 1)
                self.assertNotEqual(drifted, original)
                self.assertEqual(drifted.splitlines()[:2], headers)
                kustomization.write_text(drifted, encoding="utf-8")

                result = self.validate()

                self.assertEqual(result.returncode, 1)
                self.assertIn(expected_error, result.stderr)

    def test_generated_collector_yaml_evidence_drift_is_rejected(self) -> None:
        self.generate()
        self.collector_yaml.write_text(
            self.collector_yaml.read_text() + "# changed after generation\n"
        )

        result = self.validate()

        self.assertEqual(result.returncode, 1)
        self.assertIn("evidence hash does not match", result.stderr)

    def test_missing_canonical_generated_yaml_is_rejected(self) -> None:
        self.generate()
        self.collector_yaml.unlink()

        result = self.validate()

        self.assertEqual(result.returncode, 1)
        self.assertIn("missing canonical generated Collector YAML", result.stderr)

    def test_evidence_path_escape_is_rejected(self) -> None:
        self.generate()
        outside_temp = tempfile.TemporaryDirectory()
        self.addCleanup(outside_temp.cleanup)
        outside = Path(outside_temp.name).resolve() / "collector.yaml"
        outside.write_bytes(self.collector_yaml.read_bytes())
        digest = hashlib.sha256(outside.read_bytes()).hexdigest()
        contract = self.application / "otel-connection.yaml"
        text = contract.read_text(encoding="utf-8")
        text = re.sub(
            r'^  source: "[^"]+"$',
            f'  source: "{outside}"',
            text,
            count=1,
            flags=re.MULTILINE,
        )
        text = re.sub(
            r'^  sha256: "[0-9a-f]{64}"$',
            f'  sha256: "{digest}"',
            text,
            count=1,
            flags=re.MULTILINE,
        )
        contract.write_text(text, encoding="utf-8")

        result = self.validate()

        self.assertEqual(result.returncode, 1)
        self.assertIn("must be relative", result.stderr)

    def test_collector_route_drift_is_rejected_after_hash_update(self) -> None:
        self.generate()
        self.collector_yaml.write_text(
            self.collector_yaml.read_text(encoding="utf-8").replace(
                "      port: 4318",
                "      port: 9999",
                1,
            ),
            encoding="utf-8",
        )
        self.rewrite_contract_hash(self.collector_yaml)

        result = self.validate()

        self.assertEqual(result.returncode, 1)
        self.assertIn("must contain exactly one application route", result.stderr)

    def test_service_resolution_drift_is_rejected(self) -> None:
        self.generate()
        contract = self.application / "otel-connection.yaml"
        contract.write_text(
            contract.read_text(encoding="utf-8").replace(
                'serviceResolution: "generated-collector-yaml"',
                'serviceResolution: "explicit"',
            ),
            encoding="utf-8",
        )

        result = self.validate()

        self.assertEqual(result.returncode, 1)
        self.assertIn("route is not bound to generated Collector YAML", result.stderr)


if __name__ == "__main__":
    unittest.main()
