from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = SKILL_ROOT / "scripts" / "generate_application.py"
VALIDATOR = SKILL_ROOT / "scripts" / "validate_application.py"
GENERATOR_SPEC = importlib.util.spec_from_file_location(
    "otel_generate_application_test_module", GENERATOR
)
assert GENERATOR_SPEC and GENERATOR_SPEC.loader
GENERATOR_MODULE = importlib.util.module_from_spec(GENERATOR_SPEC)
GENERATOR_SPEC.loader.exec_module(GENERATOR_MODULE)


DEPLOYMENT = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: checkout
  namespace: checkout
spec:
  selector:
    matchLabels:
      app: checkout
  template:
    metadata:
      labels:
        app: checkout
    spec:
      containers:
        - name: checkout
          image: example.invalid/checkout:1
          env:
            - name: KEEP_ME
              value: present
"""


class ConnectionScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.app = self.workspace / "checkout"
        self.base = self.app / "kubernetes" / "deployment.yaml"
        self.base.parent.mkdir(parents=True)
        self.base.write_text(DEPLOYMENT, encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    @property
    def output(self) -> Path:
        return self.app / "deploy" / "otel-config"

    def arguments(self, *, include_app: bool = True) -> list[str]:
        args = [
            "--workspace-root",
            str(self.workspace),
        ]
        if include_app:
            args.extend(("--app", str(self.app)))
        args.extend(
            (
                "--realm",
                "us0",
                "--collector-namespace",
                "observability",
                "--collector-release",
                "splunk-otel",
                "--topology",
                "gateway",
                "--secret-name",
                "splunk-otel-token",
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
            )
        )
        return args

    def run_generator(
        self,
        *extra: str,
        include_app: bool = True,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(GENERATOR), *self.arguments(include_app=include_app), *extra],
            cwd=cwd or self.workspace,
            text=True,
            capture_output=True,
            check=False,
        )

    def run_validator(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), str(self.output)],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_explicit_app_generates_contract_and_targeted_overlay(self) -> None:
        original = self.base.read_bytes()
        result = self.run_generator()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.base.read_bytes(), original)

        contract = (self.output / "otel-connection.yaml").read_text()
        overlay = (self.output / "kubernetes/otel-env-patch.yaml").read_text()
        kustomization = (self.output / "kubernetes/kustomization.yaml").read_text()
        endpoint = "http://splunk-otel-collector.observability.svc.cluster.local:4318"
        self.assertIn(f'endpoint: "{endpoint}"', contract)
        self.assertIn(f'tracesEndpoint: "{endpoint}/v1/traces"', contract)
        self.assertIn('serviceResolution: "release-topology-default"', contract)
        self.assertIn(f'value: "{endpoint}"', overlay)
        self.assertIn('name: "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"', overlay)
        self.assertIn('name: "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"', overlay)
        self.assertIn('name: "checkout"', overlay)
        self.assertIn('namespace: "checkout"', overlay)
        self.assertIn('path: "otel-env-patch.yaml"', kustomization)
        for forbidden in (
            "splunk-otel-token",
            "splunk_observability_access_token",
            "SPLUNK_ACCESS_TOKEN",
            "X-SF-Token",
            'realm: "us0"',
        ):
            self.assertNotIn(forbidden, overlay)
        self.assertIn("No access token was read or written.", result.stdout)
        self.assertIn("Next commands:", result.stdout)
        self.assertIn("Add the generated component", result.stdout)
        self.assertIn("components:", result.stdout)
        self.assertIn('  - "deploy/otel-config/kubernetes"', result.stdout)
        self.assertIn("adjust this app-root-relative path", result.stdout)
        self.assertNotIn("kubectl kustomize", result.stdout)
        self.assertNotIn("kubectl apply -k", result.stdout)
        self.assertEqual(self.run_validator().returncode, 0)

    def test_missing_base_generates_reviewable_workload_scaffold(self) -> None:
        args = self.arguments()
        base_index = args.index("--base")
        del args[base_index : base_index + 2]
        result = subprocess.run(
            [
                sys.executable,
                str(GENERATOR),
                *args,
                "--image",
                "example.invalid/checkout:1",
                "--container-port",
                "8080",
            ],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        contract = (self.output / "otel-connection.yaml").read_text()
        kustomization = (
            self.output / "kubernetes/kustomization.yaml"
        ).read_text()
        overlay = (self.output / "kubernetes/otel-env-patch.yaml").read_text()
        scaffold = (self.output / "kubernetes/workload.yaml").read_text()
        self.assertIn('overlayMode: "scaffold"', contract)
        self.assertIn('base: "deploy/otel-config/kubernetes/workload.yaml"', contract)
        self.assertIn('resources:\n  - "workload.yaml"', kustomization)
        self.assertIn('path: "otel-env-patch.yaml"', kustomization)
        self.assertIn('"obstudio.splunk.com/scaffold": "true"', scaffold)
        self.assertIn('image: "example.invalid/checkout:1"', scaffold)
        self.assertIn("containerPort: 8080", scaffold)
        self.assertIn('name: "OTEL_EXPORTER_OTLP_ENDPOINT"', overlay)
        self.assertNotIn("splunk-otel-token", overlay)
        self.assertNotIn("SPLUNK_ACCESS_TOKEN", scaffold)
        self.assertIn("Next commands:", result.stdout)
        self.assertIn("Review the workload scaffold", result.stdout)
        self.assertIn("Replace the image, resources, probes", result.stdout)
        self.assertIn("kubectl apply -k", result.stdout)
        self.assertEqual(self.run_validator().returncode, 0)

    def test_omitted_app_uses_original_current_directory(self) -> None:
        result = self.run_generator(include_app=False, cwd=self.app)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.output / "otel-connection.yaml").is_file())
        self.assertIn(f"configuration: {self.app.resolve()}", result.stdout)

    def test_collector_route_inputs_default_to_standard_gateway(self) -> None:
        args = self.arguments()
        for flag in (
            "--collector-namespace",
            "--collector-release",
            "--topology",
        ):
            index = args.index(flag)
            del args[index : index + 2]

        result = subprocess.run(
            [sys.executable, str(GENERATOR), *args],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        contract = (self.output / "otel-connection.yaml").read_text()
        endpoint = "http://splunk-otel-collector.observability.svc.cluster.local:4318"
        self.assertIn('namespace: "observability"', contract)
        self.assertIn('release: "splunk-otel"', contract)
        self.assertIn('topology: "gateway"', contract)
        self.assertIn(f'endpoint: "{endpoint}"', contract)

    def test_existing_secret_alias_is_accepted(self) -> None:
        args = self.arguments()
        index = args.index("--secret-name")
        args[index] = "--existing-secret"

        result = subprocess.run(
            [sys.executable, str(GENERATOR), *args],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        contract = (self.output / "otel-connection.yaml").read_text()
        self.assertIn('name: "splunk-otel-token"', contract)

    def test_dns_subdomain_secret_name_is_accepted(self) -> None:
        args = self.arguments()
        args[args.index("--secret-name") + 1] = "team.splunk-otel-token"

        result = subprocess.run(
            [sys.executable, str(GENERATOR), *args],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        contract = (self.output / "otel-connection.yaml").read_text()
        self.assertIn('name: "team.splunk-otel-token"', contract)
        validated = self.run_validator()
        self.assertEqual(validated.returncode, 0, validated.stderr)

    def test_dns_subdomain_workload_name_is_accepted(self) -> None:
        self.base.write_text(
            DEPLOYMENT.replace(
                "  name: checkout\n  namespace: checkout",
                "  name: checkout.api\n  namespace: checkout",
                1,
            ),
            encoding="utf-8",
        )
        args = self.arguments()
        args[args.index("--workload-name") + 1] = "checkout.api"

        result = subprocess.run(
            [sys.executable, str(GENERATOR), *args],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        contract = (self.output / "otel-connection.yaml").read_text()
        overlay = (self.output / "kubernetes/otel-env-patch.yaml").read_text()
        kustomization = (self.output / "kubernetes/kustomization.yaml").read_text()
        self.assertIn('name: "checkout.api"', contract)
        self.assertIn('name: "checkout.api"', kustomization)
        self.assertIn('value: "checkout.api"', overlay)
        validated = self.run_validator()
        self.assertEqual(validated.returncode, 0, validated.stderr)

    def test_agent_service_and_grpc_are_bound_together(self) -> None:
        args = self.arguments()
        args[args.index("gateway")] = "agent-service"
        result = subprocess.run(
            [sys.executable, str(GENERATOR), *args, "--protocol", "grpc"],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        contract = (self.output / "otel-connection.yaml").read_text()
        expected = "http://splunk-otel-collector-agent.observability.svc.cluster.local:4317"
        self.assertIn(f'endpoint: "{expected}"', contract)
        self.assertIn(f'tracesEndpoint: "{expected}"', contract)
        self.assertIn('portName: "otlp"', contract)

    def test_custom_service_and_cluster_domain(self) -> None:
        result = self.run_generator(
            "--collector-service",
            "custom-gateway",
            "--cluster-domain",
            "cluster.internal",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        contract = (self.output / "otel-connection.yaml").read_text()
        self.assertIn(
            'endpoint: "http://custom-gateway.observability.svc.cluster.internal:4318"',
            contract,
        )
        self.assertIn('serviceResolution: "explicit"', contract)
        self.assertEqual(self.run_validator().returncode, 0)

    def test_collector_evidence_is_recorded_without_absolute_app_path(self) -> None:
        evidence = self.app / "collector.yaml"
        evidence.write_text(
            """\
apiVersion: v1
kind: Service
metadata:
  name: splunk-otel-collector
  namespace: observability
spec:
  ports:
    - name: otlp-http
      port: 4318
""",
            encoding="utf-8",
        )
        result = self.run_generator("--collector-evidence", str(evidence))
        self.assertEqual(result.returncode, 0, result.stderr)
        contract = (self.output / "otel-connection.yaml").read_text()
        self.assertIn('serviceResolution: "generated-collector-yaml"', contract)
        self.assertIn('source: "collector.yaml"', contract)
        self.assertRegex(contract, r'sha256: "[0-9a-f]{64}"')
        self.assertNotIn(str(self.app), contract)

    def test_collector_evidence_must_prove_selected_service_and_port(self) -> None:
        evidence = self.app / "collector.yaml"
        evidence.write_text(
            """\
apiVersion: v1
kind: Service
metadata:
  name: wrong-service
  namespace: observability
spec:
  ports:
    - name: otlp-http
      port: 9999
""",
            encoding="utf-8",
        )
        result = self.run_generator("--collector-evidence", str(evidence))
        self.assertEqual(result.returncode, 2)
        self.assertIn("exactly one selected Service route", result.stderr)
        self.assertFalse(self.output.exists())

    def test_duplicate_collector_evidence_routes_are_rejected(self) -> None:
        service = """\
apiVersion: v1
kind: Service
metadata:
  name: splunk-otel-collector
  namespace: observability
spec:
  ports:
    - name: otlp-http
      port: 4318
"""
        evidence = self.app / "collector.yaml"
        evidence.write_text(f"{service}---\n{service}", encoding="utf-8")
        result = self.run_generator("--collector-evidence", str(evidence))
        self.assertEqual(result.returncode, 2)
        self.assertIn("exactly one selected Service route", result.stderr)
        self.assertFalse(self.output.exists())

    def test_identical_rerun_is_idempotent(self) -> None:
        first = self.run_generator()
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.run_generator()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("Unchanged OTel application configuration", second.stdout)

    def test_changed_managed_files_require_explicit_overwrite(self) -> None:
        self.assertEqual(self.run_generator().returncode, 0)
        changed = self.arguments()
        changed[changed.index("us0")] = "us1"
        refused = subprocess.run(
            [sys.executable, str(GENERATOR), *changed],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(refused.returncode, 2)
        self.assertIn("use --overwrite", refused.stderr)
        replaced = subprocess.run(
            [sys.executable, str(GENERATOR), *changed, "--overwrite"],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(replaced.returncode, 0, replaced.stderr)
        self.assertIn('realm: "us1"', (self.output / "otel-connection.yaml").read_text())

    def test_overwrite_from_scaffold_to_base_removes_stale_workload(self) -> None:
        scaffold_args = self.arguments()
        base_index = scaffold_args.index("--base")
        del scaffold_args[base_index : base_index + 2]
        scaffold = subprocess.run(
            [
                sys.executable,
                str(GENERATOR),
                *scaffold_args,
                "--image",
                "example.invalid/checkout:1",
                "--container-port",
                "8080",
            ],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(scaffold.returncode, 0, scaffold.stderr)
        workload = self.output / "kubernetes/workload.yaml"
        self.assertTrue(workload.is_file())

        replaced = self.run_generator("--overwrite")
        self.assertEqual(replaced.returncode, 0, replaced.stderr)
        self.assertFalse(workload.exists())
        contract = (self.output / "otel-connection.yaml").read_text()
        self.assertIn('overlayMode: "component"', contract)
        self.assertEqual(self.run_validator().returncode, 0)

    def test_legacy_managed_files_can_be_overwritten_after_rename(self) -> None:
        self.assertEqual(self.run_generator().returncode, 0)
        for path in self.output.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            path.write_text(
                text.replace(
                    "otel-generate-app-collector-config",
                    "otel-generate-config",
                ),
                encoding="utf-8",
            )

        self.assertEqual(self.run_validator().returncode, 0)
        replaced = self.run_generator("--overwrite")

        self.assertEqual(replaced.returncode, 0, replaced.stderr)
        contract = (self.output / "otel-connection.yaml").read_text()
        self.assertIn(
            "# Generated by otel-generate-app-collector-config. Do not edit.",
            contract,
        )
        self.assertIn('name: "otel-generate-app-collector-config"', contract)

    def test_hand_authored_managed_path_is_never_overwritten(self) -> None:
        destination = self.output / "otel-connection.yaml"
        destination.parent.mkdir(parents=True)
        destination.write_text("hand authored\n", encoding="utf-8")
        result = self.run_generator("--overwrite")
        self.assertEqual(result.returncode, 2)
        self.assertIn("hand-authored", result.stderr)
        self.assertEqual(destination.read_text(), "hand authored\n")

    def test_app_and_base_must_remain_in_workspace_boundary(self) -> None:
        outside = Path(self.temp.name).parent / f"{Path(self.temp.name).name}-outside"
        outside.mkdir()
        self.addCleanup(shutil.rmtree, outside, True)
        result = subprocess.run(
            [
                sys.executable,
                str(GENERATOR),
                *self.arguments()[:2],
                "--app",
                str(outside),
                *self.arguments()[4:],
            ],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("escapes workspace root", result.stderr)
        self.assertFalse((outside / "deploy/otel-config").exists())

    def test_invalid_identifiers_fail_before_writes(self) -> None:
        cases = (
            ("--realm", "https://us0.example"),
            ("--collector-namespace", "Observability"),
            ("--collector-release", "bad_release"),
            ("--secret-name", "../secret"),
            ("--application-namespace", "bad namespace"),
            ("--workload-name", "Checkout"),
            ("--container", "checkout/app"),
        )
        for flag, invalid in cases:
            with self.subTest(flag=flag):
                args = self.arguments()
                args[args.index(flag) + 1] = invalid
                result = subprocess.run(
                    [sys.executable, str(GENERATOR), *args],
                    cwd=self.workspace,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertFalse(self.output.exists())

    def test_accepts_collector_release_at_safe_kubernetes_limit(self) -> None:
        release_name = "a" * 47
        result = self.run_generator(
            "--collector-release", release_name
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            f'release: "{release_name}"',
            (self.output / "otel-connection.yaml").read_text(),
        )

    def test_rejects_collector_release_longer_than_safe_kubernetes_limit(self) -> None:
        result = self.run_generator(
            "--collector-release", "a" * 48
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("must not exceed 47 characters", result.stderr)
        self.assertFalse(self.output.exists())

    def test_token_arguments_are_rejected_without_echoing_value(self) -> None:
        sentinel = "SENTINEL_APPLICATION_TOKEN_MUST_NOT_LEAK"
        forms = (("--token", sentinel), (f"--token={sentinel}",))
        for form in forms:
            with self.subTest(form=form):
                result = self.run_generator(*form)
                combined = result.stdout + result.stderr
                self.assertEqual(result.returncode, 2)
                self.assertIn("--token is forbidden", combined)
                self.assertNotIn(sentinel, combined)
                self.assertFalse(self.output.exists())

    def test_secret_name_errors_never_echo_supplied_value(self) -> None:
        sentinel = "SENTINEL_APPLICATION_SECRET_MUST_NOT_LEAK"
        forms = (
            ("--secret-name", sentinel),
            (f"--secret-name={sentinel}",),
            ("--existing-secret", sentinel),
            (f"--existing-secret={sentinel}",),
            ("--secret-name", f"--{sentinel}"),
            ("--existing-secret", f"--{sentinel}"),
        )
        for form in forms:
            with self.subTest(form=form):
                result = self.run_generator(*form)
                combined = result.stdout + result.stderr
                self.assertEqual(result.returncode, 2)
                self.assertIn("invalid Kubernetes Secret name", combined)
                self.assertNotIn(sentinel, combined)
                self.assertFalse(self.output.exists())

    def test_selected_workload_must_exist_exactly_once(self) -> None:
        cases = {
            "missing": DEPLOYMENT.replace(
                "name: checkout\n", "name: other\n", 1
            ),
            "duplicate": f"{DEPLOYMENT}---\n{DEPLOYMENT}",
        }
        for case, manifest in cases.items():
            with self.subTest(case=case):
                self.base.write_text(manifest, encoding="utf-8")
                result = self.run_generator()
                self.assertEqual(result.returncode, 2)
                self.assertIn("exactly one selected workload", result.stderr)
                self.assertFalse(self.output.exists())

    def test_selected_container_must_exist_exactly_once(self) -> None:
        cases = {
            "missing": DEPLOYMENT.replace(
                "name: checkout\n          image",
                "name: worker\n          image",
            ),
            "duplicate": DEPLOYMENT.replace(
                "      containers:\n",
                "      containers:\n"
                "        - name: checkout\n"
                "          image: example.invalid/checkout:2\n",
            ),
        }
        for case, manifest in cases.items():
            with self.subTest(case=case):
                self.base.write_text(manifest, encoding="utf-8")
                result = self.run_generator()
                self.assertEqual(result.returncode, 2)
                self.assertIn("exactly one target container", result.stderr)
                self.assertFalse(self.output.exists())

    def test_identical_generated_environment_values_are_allowed(self) -> None:
        endpoint = "http://splunk-otel-collector.observability.svc.cluster.local:4318"
        self.base.write_text(
            DEPLOYMENT.replace(
                "            - name: KEEP_ME\n"
                "              value: present\n",
                "            - name: KEEP_ME\n"
                "              value: present\n"
                "            - name: OTEL_SERVICE_NAME\n"
                "              value: checkout\n"
                "            - name: OTEL_EXPORTER_OTLP_ENDPOINT\n"
                f"              value: {endpoint}\n",
            ),
            encoding="utf-8",
        )

        result = self.run_generator()

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_conflicting_otel_environment_is_rejected_without_echo(self) -> None:
        sentinel = "SENTINEL_OTEL_ENV_VALUE_MUST_NOT_LEAK"
        cases = {
            "different-literal": (
                "            - name: OTEL_EXPORTER_OTLP_ENDPOINT\n"
                f"              value: {sentinel}\n"
            ),
            "duplicate": (
                "            - name: OTEL_SERVICE_NAME\n"
                "              value: checkout\n"
                "            - name: OTEL_SERVICE_NAME\n"
                "              value: checkout\n"
            ),
            "value-from": (
                "            - name: OTEL_EXPORTER_OTLP_ENDPOINT\n"
                "              valueFrom:\n"
                "                secretKeyRef:\n"
                f"                  name: {sentinel}\n"
                "                  key: token\n"
            ),
            "dynamic-literal": (
                "            - name: OTEL_SERVICE_NAME\n"
                f"              value: $({sentinel})\n"
            ),
            "unmanaged-exporter-setting": (
                "            - name: OTEL_EXPORTER_OTLP_HEADERS\n"
                f"              value: {sentinel}\n"
            ),
            "splunk-application-setting": (
                "            - name: SPLUNK_ACCESS_TOKEN\n"
                f"              value: {sentinel}\n"
            ),
            "flow-style-splunk-setting": (
                "            - {name: SPLUNK_ACCESS_TOKEN, "
                f"value: {sentinel}}}\n"
            ),
        }
        marker = (
            "            - name: KEEP_ME\n"
            "              value: present\n"
        )
        for case, conflicting_env in cases.items():
            with self.subTest(case=case):
                self.base.write_text(
                    DEPLOYMENT.replace(marker, marker + conflicting_env),
                    encoding="utf-8",
                )

                result = self.run_generator()
                combined = result.stdout + result.stderr

                self.assertEqual(result.returncode, 2)
                self.assertIn(
                    "conflicting OpenTelemetry environment configuration",
                    combined,
                )
                self.assertNotIn(sentinel, combined)
                self.assertFalse(self.output.exists())

    def test_omitted_workload_namespace_matches_default(self) -> None:
        self.base.write_text(
            DEPLOYMENT.replace("  namespace: checkout\n", "", 1),
            encoding="utf-8",
        )
        result = self.run_generator(
            "--application-namespace", "default"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            'namespace: "default"',
            (self.output / "otel-connection.yaml").read_text(),
        )

    def test_remote_kustomization_resource_is_rejected_without_echo(self) -> None:
        sentinel = "SENTINEL_REMOTE_QUERY_MUST_NOT_LEAK"
        (self.base.parent / "kustomization.yaml").write_text(
            """\
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - https://example.invalid/remote.yaml?token="""
            + sentinel
            + "\n",
            encoding="utf-8",
        )
        result = self.run_generator("--base", "kubernetes")
        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 2)
        self.assertIn("remote Kustomization resources", combined)
        self.assertNotIn(sentinel, combined)
        self.assertFalse(self.output.exists())

    def test_nested_remote_kustomization_resource_is_rejected(self) -> None:
        nested = self.base.parent / "nested"
        nested.mkdir()
        (self.base.parent / "kustomization.yaml").write_text(
            """\
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - nested
""",
            encoding="utf-8",
        )
        (nested / "kustomization.yaml").write_text(
            """\
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - git::https://example.invalid/repository.git
""",
            encoding="utf-8",
        )
        result = self.run_generator("--base", "kubernetes")
        self.assertEqual(result.returncode, 2)
        self.assertIn("remote Kustomization resources", result.stderr)
        self.assertFalse(self.output.exists())

    def test_kustomization_timeout_uses_constant_non_secret_error(self) -> None:
        (self.base.parent / "kustomization.yaml").write_text(
            """\
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
""",
            encoding="utf-8",
        )
        sentinel = "SENTINEL_TIMEOUT_OUTPUT_MUST_NOT_LEAK"
        expired = subprocess.TimeoutExpired(
            ["kubectl", "kustomize", sentinel],
            60,
            output=sentinel,
            stderr=sentinel,
        )
        with mock.patch.object(
            GENERATOR_MODULE.shutil,
            "which",
            return_value="/fake/kubectl",
        ), mock.patch.object(
            GENERATOR_MODULE.subprocess,
            "run",
            side_effect=expired,
        ):
            with self.assertRaisesRegex(
                ValueError, "timed out after 60 seconds"
            ) as raised:
                GENERATOR_MODULE.base_manifest(
                    self.base.parent,
                    allowed_root=self.app.resolve(),
                )
        self.assertNotIn(sentinel, str(raised.exception))
        self.assertFalse(self.output.exists())

    def test_output_symlink_is_rejected(self) -> None:
        real_output = self.app / "real-output"
        real_output.mkdir()
        output_parent = self.app / "deploy"
        output_parent.mkdir()
        (output_parent / "otel-config").symlink_to(real_output, target_is_directory=True)
        result = self.run_generator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("symlink", result.stderr)

    def test_explicit_output_symlink_is_rejected(self) -> None:
        real_output = self.app / "real-output"
        real_output.mkdir()
        linked_output = self.app / "linked-output"
        linked_output.symlink_to(real_output, target_is_directory=True)
        result = self.run_generator("--output", str(linked_output))
        self.assertEqual(result.returncode, 2)
        self.assertIn("symlink", result.stderr)

    def test_managed_subdirectory_symlink_is_rejected(self) -> None:
        self.output.mkdir(parents=True)
        outside = self.workspace / "outside-kubernetes"
        outside.mkdir()
        (self.output / "kubernetes").symlink_to(
            outside,
            target_is_directory=True,
        )
        result = self.run_generator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("symlink", result.stderr)
        self.assertFalse((outside / "otel-env-patch.yaml").exists())

    def test_validator_rejects_overlay_secret_and_cross_file_drift(self) -> None:
        self.assertEqual(self.run_generator().returncode, 0)
        overlay_path = self.output / "kubernetes/otel-env-patch.yaml"
        overlay = overlay_path.read_text()
        overlay_path.write_text(overlay + "# X-SF-Token\n", encoding="utf-8")
        secret_result = self.run_validator()
        self.assertEqual(secret_result.returncode, 1)
        self.assertIn("forbidden value", secret_result.stderr)

        overlay_path.write_text(overlay.replace("4318", "9999", 1), encoding="utf-8")
        drift_result = self.run_validator()
        self.assertEqual(drift_result.returncode, 1)
        self.assertIn("inconsistent OTEL_EXPORTER_OTLP_ENDPOINT", drift_result.stderr)

    def test_validator_rejects_dynamic_secret_realm_and_port_drift(self) -> None:
        args = self.arguments()
        args[args.index("splunk-otel-token")] = "collector-private-ref"
        args[args.index("us0")] = "us7"
        generated = subprocess.run(
            [sys.executable, str(GENERATOR), *args],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(generated.returncode, 0, generated.stderr)
        overlay_path = self.output / "kubernetes/otel-env-patch.yaml"
        overlay = overlay_path.read_text()
        overlay_path.write_text(
            overlay
            + """\
            -
              name: "OTEL_TEST_SECRET"
              value: "collector-private-ref"
            -
              name: "OTEL_TEST_REALM"
              value: "us7"
""",
            encoding="utf-8",
        )
        leaked = self.run_validator()
        self.assertEqual(leaked.returncode, 1)
        self.assertIn("forbidden collector Secret name", leaked.stderr)
        self.assertIn("forbidden realm", leaked.stderr)

        overlay_path.write_text(overlay, encoding="utf-8")
        contract_path = self.output / "otel-connection.yaml"
        contract_path.write_text(
            contract_path.read_text().replace("port: 4318", "port: 9999"),
            encoding="utf-8",
        )
        drifted = self.run_validator()
        self.assertEqual(drifted.returncode, 1)
        self.assertIn("port does not match", drifted.stderr)

    def test_realm_substring_in_route_is_not_a_false_positive(self) -> None:
        result = self.run_generator(
            "--collector-service", "otel-us0-gateway"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        validated = self.run_validator()
        self.assertEqual(validated.returncode, 0, validated.stderr)

    def test_validator_rejects_invalid_overlay_mode(self) -> None:
        self.assertEqual(self.run_generator().returncode, 0)
        contract_path = self.output / "otel-connection.yaml"
        contract_path.write_text(
            contract_path.read_text(encoding="utf-8").replace(
                'overlayMode: "component"',
                'overlayMode: "invalid"',
            ),
            encoding="utf-8",
        )

        result = self.run_validator()

        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid application overlayMode", result.stderr)

    def test_validator_rejects_overlay_mode_kustomization_kind_drift(self) -> None:
        self.assertEqual(self.run_generator().returncode, 0)
        contract_path = self.output / "otel-connection.yaml"
        contract_path.write_text(
            contract_path.read_text(encoding="utf-8").replace(
                'overlayMode: "component"',
                'overlayMode: "standalone"',
            ),
            encoding="utf-8",
        )

        result = self.run_validator()

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "standalone overlayMode requires a Kustomization",
            result.stderr,
        )

    @unittest.skipUnless(shutil.which("kubectl"), "kubectl is not installed")
    def test_rendered_kustomization_env_conflict_is_rejected_without_echo(
        self,
    ) -> None:
        sentinel = "SENTINEL_KUSTOMIZE_SECRET_MUST_NOT_LEAK"
        (self.base.parent / "kustomization.yaml").write_text(
            """\
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
patches:
  - path: otel-conflict.yaml
""",
            encoding="utf-8",
        )
        (self.base.parent / "otel-conflict.yaml").write_text(
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
          env:
            - name: OTEL_EXPORTER_OTLP_ENDPOINT
              valueFrom:
                secretKeyRef:
                  name: """
            + sentinel
            + """
                  key: token
""",
            encoding="utf-8",
        )

        result = self.run_generator("--base", "kubernetes")
        combined = result.stdout + result.stderr

        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "conflicting OpenTelemetry environment configuration",
            combined,
        )
        self.assertNotIn(sentinel, combined)
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(shutil.which("kubectl"), "kubectl is not installed")
    def test_generated_kustomization_builds_offline(self) -> None:
        (self.base.parent / "kustomization.yaml").write_text(
            """\
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
""",
            encoding="utf-8",
        )
        (self.base.parent / "unreferenced-duplicate.yaml").write_text(
            DEPLOYMENT,
            encoding="utf-8",
        )
        generated = self.run_generator("--base", "kubernetes")
        self.assertEqual(generated.returncode, 0, generated.stderr)
        result = subprocess.run(
            ["kubectl", "kustomize", str(self.output / "kubernetes")],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OTEL_EXPORTER_OTLP_ENDPOINT", result.stdout)
        self.assertIn("KEEP_ME", result.stdout)

        rendered = self.app / "kubernetes" / "rendered-otel-overlay.yaml"
        rendered.write_text(result.stdout, encoding="utf-8")
        rechecked = self.run_generator(
            "--base",
            str(rendered),
            "--output",
            str(self.app / "deploy" / "otel-config-recheck"),
        )
        self.assertEqual(rechecked.returncode, 0, rechecked.stderr)


if __name__ == "__main__":
    unittest.main()
