from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock


REPO_ROOT = Path(__file__).parents[3]
SCANNER = REPO_ROOT / "skills" / "references" / "scripts" / "inspect_otel_project.py"


def load_scanner_module():
    spec = importlib.util.spec_from_file_location("inspect_otel_project_tested", SCANNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SCANNER_MODULE = load_scanner_module()


class InspectOtelProjectTest(unittest.TestCase):
    def inspect(self, root: Path, *args: str) -> dict[str, Any]:
        result = subprocess.run(
            [sys.executable, str(SCANNER), str(root), *args],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_go_fixture_finds_manifest_entrypoint_routes_runtime_and_tests(self) -> None:
        root = REPO_ROOT / "evals" / "go" / "kvstore"

        result = self.inspect(root)

        self.assertEqual(result["schema_version"], 1)
        self.assertIn(
            {"path": "go.mod", "language": "go", "kind": "go-module"},
            result["manifests"],
        )
        self.assertIn(
            "cmd/kvstore-server/main.go",
            {item["path"] for item in result["entrypoints"]},
        )
        self.assertEqual(
            {item["route"] for item in result["routes"]},
            {"/kv/", "/search"},
        )
        self.assertIn("go", {item["ecosystem"] for item in result["runtime_candidates"]})
        self.assertIn("kvstore/http_test.go", result["tests"])
        self.assertEqual(result["summary"]["otel_findings"], 0)
        self.assertIn("Candidates only", result["proof_boundary"])
        self.assertTrue(result["complete"])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(
            result["section_counts"]["routes"],
            {"total": 2, "returned": 2, "truncated": 0},
        )

    def test_cross_language_route_candidates_are_detected(self) -> None:
        cases = {
            REPO_ROOT / "evals" / "python" / "fastapi-celery": {"GET", "POST", "DELETE"},
            REPO_ROOT / "evals" / "node" / "express-basic": {"GET", "POST"},
        }
        for root, expected_methods in cases.items():
            with self.subTest(root=root):
                result = self.inspect(root)
                methods = {item["method"] for item in result["routes"]}
                self.assertTrue(expected_methods.issubset(methods))

    def test_common_router_receiver_names_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "routes.py").write_text(
                'api.get("/api", handler)\n'
                'engine.post("/engine", handler)\n'
                'v1.delete("/v1/items/{id}", handler)\n',
                encoding="utf-8",
            )

            result = self.inspect(root)

        self.assertEqual(
            {(item["method"], item["route"]) for item in result["routes"]},
            {("GET", "/api"), ("POST", "/engine"), ("DELETE", "/v1/items/{id}")},
        )

    def test_otel_findings_are_categorized_and_excluded_directories_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                '[project]\nrequires-python = ">=3.11"\n'
                'dependencies = ["opentelemetry-sdk"]\n',
                encoding="utf-8",
            )
            (root / "app.py").write_text(
                "from opentelemetry.sdk.trace import TracerProvider\n"
                "from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter\n"
                "provider = TracerProvider()\n"
                "trace.set_tracer_provider(provider)\n"
                "with tracer.start_as_current_span('work'):\n"
                "    pass\n"
                "provider.force_flush()\n",
                encoding="utf-8",
            )
            (root / ".env").write_text("OTEL_SERVICE_NAME=checkout\n", encoding="utf-8")
            (root / ".env.local").write_text(
                "OTEL_EXPORTER_OTLP_HEADERS=Authorization=secret-value\n",
                encoding="utf-8",
            )
            (root / "collector.yaml").write_text(
                "headers: secret-value\n",
                encoding="utf-8",
            )
            ignored = root / ".venv"
            ignored.mkdir()
            (ignored / "ignored.py").write_text("LoggerProvider()\n", encoding="utf-8")
            agent_skills = root / ".agents" / "skills" / "otel-audit"
            agent_skills.mkdir(parents=True)
            (agent_skills / "SKILL.md").write_text(
                "opentelemetry instrumentation instructions\n",
                encoding="utf-8",
            )

            result = self.inspect(root)

        findings = result["otel_findings"]
        self.assertGreaterEqual(len(findings["dependency_or_import"]), 2)
        self.assertEqual(findings["provider_construction"][0]["path"], "app.py")
        self.assertEqual(findings["provider_registration"][0]["line"], 4)
        self.assertEqual(findings["exporter"][0]["path"], "app.py")
        self.assertEqual(findings["custom_span"][0]["line"], 5)
        self.assertEqual(findings["runtime_configuration"][0]["path"], ".env")
        runtime_text = {item["path"]: item["text"] for item in findings["runtime_configuration"]}
        self.assertEqual(runtime_text[".env"], "OTEL_SERVICE_NAME=<redacted>")
        self.assertEqual(
            runtime_text[".env.local"],
            "OTEL_EXPORTER_OTLP_HEADERS=<redacted>",
        )
        self.assertNotIn("secret-value", json.dumps(result))
        self.assertFalse(any(item["path"].startswith(".venv/") for values in findings.values() for item in values))
        self.assertFalse(any(item["path"].startswith(".agents/") for values in findings.values() for item in values))

    def test_output_is_deterministic_and_bounded(self) -> None:
        root = REPO_ROOT / "evals" / "go" / "chi-basic"
        first = self.inspect(root, "--max-items", "2")
        second = self.inspect(root, "--max-items", "2")

        self.assertEqual(first, second)
        self.assertTrue(all(len(items) <= 2 for items in first["otel_findings"].values()))
        self.assertLessEqual(len(first["routes"]), 2)

    def test_stat_then_symlink_swap_cannot_escape_project_read(self) -> None:
        if not SCANNER_MODULE.descriptor_operations_supported():
            self.skipTest("requires descriptor-relative no-follow operations")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "project"
            root.mkdir()
            source = root / "app.py"
            source.write_text("print('safe')\n", encoding="utf-8")
            outside = base / "outside.py"
            secret = "EXTERNAL_PRIVATE_VALUE_314159"
            outside.write_text(secret + "\n", encoding="utf-8")
            moved = root / "app.original.py"
            real_open = os.open
            swapped = False

            def swap_before_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal swapped
                if path == "app.py" and dir_fd is not None and not swapped:
                    source.rename(moved)
                    source.symlink_to(outside)
                    swapped = True
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with (
                mock.patch.object(
                    SCANNER_MODULE,
                    "descriptor_operations_supported",
                    return_value=True,
                ),
                mock.patch.object(
                    SCANNER_MODULE.os, "open", side_effect=swap_before_open
                ),
            ):
                result = SCANNER_MODULE.collect_scan_input(
                    root, max_files=10, max_total_bytes=10_000
                )

            self.assertTrue(swapped)
            self.assertNotIn(
                secret,
                "\n".join(
                    line for lines in result.lines.values() for line in lines
                ),
            )
            self.assertEqual(result.skipped["read_errors"], 1)

    def test_directory_component_swap_cannot_escape_project_read(self) -> None:
        if not SCANNER_MODULE.descriptor_operations_supported():
            self.skipTest("requires descriptor-relative no-follow operations")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "project"
            nested = root / "nested"
            nested.mkdir(parents=True)
            (nested / "safe.py").write_text("print('safe')\n", encoding="utf-8")
            outside = base / "outside"
            outside.mkdir()
            secret = "EXTERNAL_DIRECTORY_VALUE_271828"
            (outside / "outside.py").write_text(secret + "\n", encoding="utf-8")
            moved = root / "nested-original"
            real_open = os.open
            swapped = False

            def swap_directory_before_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal swapped
                if path == "nested" and dir_fd is not None and not swapped:
                    nested.rename(moved)
                    nested.symlink_to(outside, target_is_directory=True)
                    swapped = True
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with (
                mock.patch.object(
                    SCANNER_MODULE,
                    "descriptor_operations_supported",
                    return_value=True,
                ),
                mock.patch.object(
                    SCANNER_MODULE.os,
                    "open",
                    side_effect=swap_directory_before_open,
                ),
            ):
                result = SCANNER_MODULE.collect_scan_input(
                    root, max_files=10, max_total_bytes=10_000
                )

            self.assertTrue(swapped)
            self.assertNotIn(
                secret,
                "\n".join(
                    line for lines in result.lines.values() for line in lines
                ),
            )
            self.assertGreaterEqual(result.skipped["walk_errors"], 1)

    def test_entry_and_depth_budgets_bound_both_walkers(self) -> None:
        walkers = [
            (
                "portable",
                SCANNER_MODULE.collect_scan_input_portable,
            )
        ]
        if SCANNER_MODULE.descriptor_operations_supported():
            walkers.append(
                (
                    "descriptor",
                    SCANNER_MODULE.collect_scan_input_descriptor,
                )
            )

        for walker_name, walker in walkers:
            with self.subTest(walker=walker_name):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    first = root / "a"
                    first.mkdir()
                    (root / "b").mkdir()
                    for index in range(4):
                        (first / f"unsupported-{index}.bin").write_bytes(b"")

                    entry_limited = walker(
                        root,
                        max_files=10,
                        max_total_bytes=10_000,
                        max_entries=3,
                        max_depth=10,
                    )

                self.assertFalse(entry_limited.complete)
                self.assertEqual(entry_limited.skipped["entry_limit"], 1)
                self.assertEqual(entry_limited.files, [])
                self.assertTrue(
                    any(
                        "directory entries" in warning
                        for warning in entry_limited.warnings
                    )
                )

            with self.subTest(walker=walker_name, limit="depth"):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    nested = root / "level-1" / "level-2"
                    nested.mkdir(parents=True)
                    (nested / "app.py").write_text(
                        "print('too deep')\n", encoding="utf-8"
                    )

                    depth_limited = walker(
                        root,
                        max_files=10,
                        max_total_bytes=10_000,
                        max_entries=100,
                        max_depth=1,
                    )

                self.assertFalse(depth_limited.complete)
                self.assertEqual(depth_limited.skipped["depth_limit"], 1)
                self.assertEqual(depth_limited.files, [])
                self.assertTrue(
                    any(
                        "beyond depth 1" in warning
                        for warning in depth_limited.warnings
                    )
                )

    def test_entry_budget_stops_enumeration_at_one_over_limit(self) -> None:
        class FakeEntry:
            def __init__(self, name: str) -> None:
                self.name = name

        class EndlessScandir:
            def __init__(self, maximum_yields: int) -> None:
                self.maximum_yields = maximum_yields
                self.yielded = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def __iter__(self):
                return self

            def __next__(self) -> FakeEntry:
                if self.yielded >= self.maximum_yields:
                    raise AssertionError("directory enumeration exceeded budget + 1")
                self.yielded += 1
                return FakeEntry(f"entry-{self.yielded}")

        walkers = [
            ("portable", SCANNER_MODULE.collect_scan_input_portable)
        ]
        if SCANNER_MODULE.descriptor_operations_supported():
            walkers.append(
                ("descriptor", SCANNER_MODULE.collect_scan_input_descriptor)
            )

        max_entries = 3
        for walker_name, walker in walkers:
            with self.subTest(walker=walker_name):
                enumerations: list[EndlessScandir] = []

                def scandir(_directory):
                    enumeration = EndlessScandir(max_entries + 1)
                    enumerations.append(enumeration)
                    return enumeration

                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    with mock.patch.object(
                        SCANNER_MODULE.os,
                        "scandir",
                        side_effect=scandir,
                    ):
                        result = walker(
                            root,
                            max_files=10,
                            max_total_bytes=10_000,
                            max_entries=max_entries,
                            max_depth=10,
                        )

                self.assertEqual(len(enumerations), 1)
                self.assertEqual(enumerations[0].yielded, max_entries + 1)
                self.assertFalse(result.complete)
                self.assertEqual(result.skipped["entry_limit"], 1)
                self.assertEqual(result.files, [])

    def test_truncation_counts_preserve_total_findings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text(
                "\n".join(
                    f"provider_{index} = TracerProvider()" for index in range(5)
                )
                + "\n",
                encoding="utf-8",
            )

            result = self.inspect(root, "--max-items", "2")

        self.assertEqual(result["summary"]["otel_findings_by_category"]["provider_construction"], 5)
        self.assertEqual(len(result["otel_findings"]["provider_construction"]), 2)
        self.assertEqual(
            result["summary"]["otel_findings_truncated_by_category"]["provider_construction"],
            3,
        )
        self.assertEqual(
            result["otel_finding_counts"]["provider_construction"],
            {"total": 5, "returned": 2, "truncated": 3},
        )
        self.assertFalse(result["complete"])
        self.assertTrue(
            any("otel_findings" in warning for warning in result["warnings"])
        )

    def test_non_otel_sections_report_truncation_and_incomplete_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text(
                "\n".join(
                    f'app.get("/route-{index}", handler)' for index in range(5)
                )
                + "\n",
                encoding="utf-8",
            )

            result = self.inspect(root, "--max-items", "2")

        self.assertEqual(len(result["routes"]), 2)
        self.assertEqual(
            result["section_counts"]["routes"],
            {"total": 5, "returned": 2, "truncated": 3},
        )
        self.assertFalse(result["complete"])
        self.assertTrue(
            any("routes" in warning for warning in result["warnings"])
        )

    def test_file_and_byte_limits_bound_scan_and_report_skips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.py").write_text("print('a')\n", encoding="utf-8")
            (root / "b.py").write_text("print('b')\n", encoding="utf-8")

            file_limited = self.inspect(root, "--max-files", "1")
            byte_limited = self.inspect(root, "--max-total-bytes", "5")

        self.assertFalse(file_limited["complete"])
        self.assertEqual(file_limited["summary"]["text_files_scanned"], 1)
        self.assertEqual(file_limited["skipped"]["file_limit"], 1)
        self.assertGreaterEqual(file_limited["skipped_count"], 1)
        self.assertFalse(byte_limited["complete"])
        self.assertEqual(byte_limited["summary"]["text_files_scanned"], 0)
        self.assertEqual(byte_limited["skipped"]["byte_limit"], 1)

    def test_sensitive_route_text_and_package_script_definition_are_redacted(self) -> None:
        secret = "sentinel-hard-coded-secret"
        compound_secret = "opaque-route-value"
        aws_secret = "opaque-aws-route-value"
        route_signature = "opaque-route-signature"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text(
                'app.get("/health?token='
                + secret
                + '", headers="Authorization: '
                + secret
                + '")\n'
                + 'app.get("/compound?SPLUNK_ACCESS_TOKEN='
                + compound_secret
                + '", handler)\n'
                + 'app.get("/aws?AWS_SECRET_ACCESS_KEY='
                + aws_secret
                + '", handler)\n'
                + 'app.get("/signed?X-Amz-Signature='
                + route_signature
                + '", handler)\n',
                encoding="utf-8",
            )
            (root / "package.json").write_text(
                json.dumps(
                    {
                        "scripts": {
                            "probe": f"curl -H 'Authorization: {secret}' /health"
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = self.inspect(root)

        serialized = json.dumps(result)
        self.assertNotIn(secret, serialized)
        self.assertNotIn(compound_secret, serialized)
        self.assertNotIn(aws_secret, serialized)
        self.assertNotIn(route_signature, serialized)
        self.assertTrue(
            all(
                "redacted" in route["text"]
                for route in result["routes"]
            )
        )
        self.assertEqual(
            {route["route"] for route in result["routes"]},
            {
                "/health?token=<redacted>",
                "/compound?SPLUNK_ACCESS_TOKEN=<redacted>",
                "/aws?AWS_SECRET_ACCESS_KEY=<redacted>",
                "/signed?X-Amz-Signature=<redacted>",
            },
        )
        self.assertEqual(
            result["project_commands"][0]["definition"],
            "<redacted sensitive configuration>",
        )

    def test_url_bearer_and_opaque_credentials_are_redacted_from_inventory_text(
        self,
    ) -> None:
        url_credential = "ci-user:s3cr3t"
        bearer_credential = "bearer-s3cr3t"
        opaque_credential = "ghp_0123456789abcdefghijklmnop"
        signed_url_credential = "signed-s3cr3t-value"
        aws_signature = "opaqueawssignature123"
        gcs_signature = "opaquegcssignature123"
        quoted_key_credential = "plain-opaque-value"
        python_key_credential = "python-opaque-value"
        cli_credential = "cli-opaque-value"
        quoted_cli_credential = "quoted opaque value"
        compound_credential = "opaquecompoundvalue123"
        aws_credential = "opaqueawsvalue123"
        auth_token_credential = "opaqueauthvalue123"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text(
                "with tracer.start_as_current_span('work'):  "
                f"# https://{url_credential}@registry.example.com/path\n"
                f"meter.create_counter('requests')  # {opaque_credential}\n"
                'meter.create_histogram("http.server.request.duration")\n'
                'meter.create_histogram("gen_ai.usage.input_tokens")\n'
                'meter.create_histogram("gen_ai.usage.output_tokens")\n'
                'meter.create_histogram("gen_ai.client.token.usage").record('
                '1, {"gen_ai.token.type": "input"})\n'
                f'meter.create_counter("quoted-key", {{"token": "{quoted_key_credential}"}})\n'
                f"meter.create_counter('python-key', {{'api_key': '{python_key_credential}'}})\n"
                f"SPLUNK_ACCESS_TOKEN={compound_credential} opentelemetry-instrument python app.py\n"
                f'AWS_SECRET_ACCESS_KEY={aws_credential} meter.create_counter("aws")\n'
                f'meter.create_counter("auth", {{"authToken": "{auth_token_credential}"}})\n'
                'module = "go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"\n',
                encoding="utf-8",
            )
            (root / "package.json").write_text(
                json.dumps(
                    {
                        "scripts": {
                            "registry": (
                                "curl "
                                f"https://{url_credential}@registry.example.com/health"
                            ),
                            "auth": (
                                "curl -H 'X-Auth: Bearer "
                                f"{bearer_credential}' /health"
                            ),
                            "signed": (
                                "curl 'https://storage.example/blob?sv=1&sig="
                                f"{signed_url_credential}'"
                            ),
                            "aws-signed": (
                                "curl 'https://storage.example/blob?"
                                f"X-Amz-Signature={aws_signature}'"
                            ),
                            "gcs-signed": (
                                "curl 'https://storage.example/blob?"
                                f"X-Goog-Signature={gcs_signature}'"
                            ),
                            "test": "go test ./internal/observability",
                            "database": (
                                "psql postgresql://ci-user:s3cr3t@"
                                "db.example/app"
                            ),
                            "basic": (
                                "curl -u ci-user:s3cr3t "
                                "https://registry.example/health"
                            ),
                            "basic-attached": (
                                "curl -uci-user:s3cr3t "
                                "https://registry.example/health"
                            ),
                            "basic-equals": (
                                "curl --user=ci-user:s3cr3t "
                                "https://registry.example/health"
                            ),
                            "token-flag": (
                                f"tool --token {cli_credential} run"
                            ),
                            "password-flag": (
                                "tool --password '"
                                f"{quoted_cli_credential}' run"
                            ),
                            "compound-env": (
                                f"SPLUNK_ACCESS_TOKEN={compound_credential} "
                                "opentelemetry-instrument python app.py"
                            ),
                            "aws-env": (
                                f"AWS_SECRET_ACCESS_KEY={aws_credential} "
                                "opentelemetry-instrument python app.py"
                            ),
                            "auth-token-flag": (
                                f"tool --auth-token {auth_token_credential} run"
                            ),
                            "prefixed-token-flag": (
                                "tool --splunk-access-token "
                                f"{compound_credential} run"
                            ),
                            "boolean-before-token": (
                                "tool --verbose --splunk-access-token "
                                f"{compound_credential} run"
                            ),
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = self.inspect(root)

        serialized = json.dumps(result)
        for credential in (
            url_credential,
            bearer_credential,
            opaque_credential,
            signed_url_credential,
            aws_signature,
            gcs_signature,
            quoted_key_credential,
            python_key_credential,
            cli_credential,
            quoted_cli_credential,
            compound_credential,
            aws_credential,
            auth_token_credential,
        ):
            self.assertNotIn(credential, serialized)
        definitions = {
            item["name"]: item["definition"]
            for item in result["project_commands"]
        }
        self.assertIn("https://<redacted>@registry.example.com/health", definitions["registry"])
        self.assertIn("Bearer <redacted>", definitions["auth"])
        self.assertEqual(
            definitions["signed"],
            "curl 'https://storage.example/blob?sv=1&sig=<redacted>'",
        )
        self.assertEqual(
            definitions["aws-signed"],
            "curl 'https://storage.example/blob?X-Amz-Signature=<redacted>'",
        )
        self.assertEqual(
            definitions["gcs-signed"],
            "curl 'https://storage.example/blob?X-Goog-Signature=<redacted>'",
        )
        self.assertEqual(definitions["test"], "go test ./internal/observability")
        self.assertEqual(
            definitions["database"],
            "psql postgresql://<redacted>@db.example/app",
        )
        self.assertEqual(
            definitions["basic"],
            "curl -u <redacted> https://registry.example/health",
        )
        self.assertEqual(
            definitions["basic-attached"],
            "curl -u<redacted> https://registry.example/health",
        )
        self.assertEqual(
            definitions["basic-equals"],
            "curl --user=<redacted> https://registry.example/health",
        )
        self.assertEqual(
            definitions["token-flag"],
            "tool --token <redacted> run",
        )
        self.assertEqual(
            definitions["password-flag"],
            "tool --password <redacted> run",
        )
        self.assertEqual(
            definitions["compound-env"],
            "<redacted sensitive configuration>",
        )
        self.assertEqual(
            definitions["aws-env"],
            "<redacted sensitive configuration>",
        )
        self.assertEqual(
            definitions["auth-token-flag"],
            "tool --auth-token <redacted> run",
        )
        self.assertEqual(
            definitions["prefixed-token-flag"],
            "tool --splunk-access-token <redacted> run",
        )
        self.assertEqual(
            definitions["boolean-before-token"],
            "tool --verbose --splunk-access-token <redacted> run",
        )
        finding_text = " ".join(
            item["text"]
            for values in result["otel_findings"].values()
            for item in values
        )
        self.assertIn("https://<redacted>@registry.example.com/path", finding_text)
        self.assertIn("<redacted>", finding_text)
        self.assertIn("http.server.request.duration", finding_text)
        self.assertIn("gen_ai.usage.input_tokens", finding_text)
        self.assertIn("gen_ai.usage.output_tokens", finding_text)
        self.assertIn("gen_ai.client.token.usage", finding_text)
        self.assertIn("gen_ai.token.type", finding_text)
        self.assertIn(
            "go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp",
            finding_text,
        )
        for ordinary in (
            "http.server.request.duration",
            "gen_ai.usage.input_tokens",
            "gen_ai.usage.output_tokens",
            "gen_ai.client.token.usage",
            "gen_ai.token.type",
            "go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp",
            "/srv/checkout/config/runtime.yaml",
            "--config=./config/runtime.yaml",
        ):
            self.assertEqual(
                SCANNER_MODULE.redact_line(Path("app.py"), ordinary),
                ordinary,
            )

    def test_malformed_package_json_does_not_abort_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text("{not-json", encoding="utf-8")
            (root / "app.js").write_text('app.get("/health", handler);\n', encoding="utf-8")

            result = self.inspect(root)

        self.assertIn(
            {"path": "package.json", "language": "node", "kind": "node-package"},
            result["manifests"],
        )
        self.assertEqual(result["project_commands"], [])
        self.assertEqual(result["routes"][0]["route"], "/health")

    def test_non_object_package_json_does_not_abort_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text("[]", encoding="utf-8")
            (root / "app.js").write_text(
                'app.get("/health", handler);\n', encoding="utf-8"
            )

            result = self.inspect(root)

        self.assertEqual(result["project_commands"], [])
        self.assertEqual(result["routes"][0]["route"], "/health")

    def test_requirements_suffix_is_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "requirements.TXT").write_text(
                "opentelemetry-api\n", encoding="utf-8"
            )

            result = self.inspect(root)

        self.assertIn(
            {
                "path": "requirements.TXT",
                "language": "python",
                "kind": "python-requirements",
            },
            result["manifests"],
        )

    def test_excludes_eval_docs_and_lockfiles_from_otel_evidence(self) -> None:
        root = REPO_ROOT / "evals" / "go" / "chi-partial"
        source_lines = (root / "main.go").read_text(encoding="utf-8").splitlines()
        provider_line = next(
            index
            for index, line in enumerate(source_lines, start=1)
            if "sdktrace.NewTracerProvider(" in line
        )
        resource_line = next(
            index
            for index, line in enumerate(source_lines, start=1)
            if "resource.New(ctx)" in line
        )

        result = self.inspect(root)

        paths = {
            item["path"]
            for values in result["otel_findings"].values()
            for item in values
        }
        self.assertFalse(any(path.startswith("eval/") for path in paths))
        self.assertNotIn("go.sum", paths)
        self.assertIn("main.go", paths)
        self.assertEqual(
            result["otel_findings"]["provider_construction"][0]["line"],
            provider_line,
        )
        self.assertIn(
            "otlptracehttp.New",
            result["otel_findings"]["exporter"][-1]["text"],
        )
        self.assertEqual(
            result["otel_findings"]["resource"][0]["line"], resource_line
        )

    def test_excludes_repository_level_evals_directory_from_otel_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "provider = TracerProvider()\n", encoding="utf-8"
            )
            evals = root / "evals" / "fixture"
            evals.mkdir(parents=True)
            (evals / "service.py").write_text(
                "provider = MeterProvider()\n", encoding="utf-8"
            )

            result = self.inspect(root)

        paths = {
            item["path"]
            for values in result["otel_findings"].values()
            for item in values
        }
        self.assertIn("service.py", paths)
        self.assertFalse(any(path.startswith("evals/") for path in paths))

    def test_nested_eval_package_is_source_but_top_level_eval_is_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "src" / "eval"
            source.mkdir(parents=True)
            (source / "runtime.py").write_text(
                "provider = TracerProvider()\n", encoding="utf-8"
            )
            fixture = root / "eval" / "runtime"
            fixture.mkdir(parents=True)
            (fixture / "fixture.py").write_text(
                "provider = MeterProvider()\n", encoding="utf-8"
            )

            result = self.inspect(root)

        paths = {
            item["path"]
            for values in result["otel_findings"].values()
            for item in values
        }
        self.assertIn("src/eval/runtime.py", paths)
        self.assertFalse(any(path.startswith("eval/") for path in paths))

    def test_nested_module_runtime_uses_module_cwd_and_local_lockfile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            module = root / "services" / "api"
            module.mkdir(parents=True)
            (module / "pyproject.toml").write_text(
                '[project]\nrequires-python = ">=3.12"\n',
                encoding="utf-8",
            )
            (module / "uv.lock").write_text("version = 1\n", encoding="utf-8")
            (module / ".python-version").write_text("3.12\n", encoding="utf-8")

            result = self.inspect(root)

        self.assertEqual(
            result["runtime_candidates"],
            [
                {
                    "ecosystem": "python",
                    "cwd": "services/api",
                    "evidence": "services/api/pyproject.toml + services/api/uv.lock",
                    "runner": "uv run --locked",
                    "probe": "uv run --locked python --version",
                }
            ],
        )
        self.assertEqual(result["lockfiles"], ["services/api/uv.lock"])
        self.assertEqual(result["version_files"], ["services/api/.python-version"])

    def test_windows_virtualenv_uses_one_exact_runner_and_probe_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                "[project]\nname = 'windows-venv'\n",
                encoding="utf-8",
            )
            interpreter = root / ".venv" / "Scripts" / "python.exe"
            interpreter.parent.mkdir(parents=True)
            interpreter.write_bytes(b"")

            result = self.inspect(root)

        candidate = result["runtime_candidates"][0]
        self.assertEqual(candidate["runner"], ".venv/Scripts/python.exe")
        self.assertEqual(
            candidate["probe"],
            f"{candidate['runner']} --version",
        )

    def test_output_writes_full_inventory_and_prints_summary(self) -> None:
        root = REPO_ROOT / "evals" / "node" / "express-basic"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory).resolve() / "inventory.json"
            completed = subprocess.run(
                [sys.executable, str(SCANNER), str(root), "--output", str(output)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads(completed.stdout)
            full = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(summary["output"], str(output.resolve()))
        self.assertEqual(summary["summary"], full["summary"])
        self.assertEqual(summary["complete"], full["complete"])
        self.assertEqual(summary["warnings"], full["warnings"])
        self.assertEqual(summary["skipped_count"], full["skipped_count"])
        self.assertIn("otel_findings", full)

    def test_relative_output_is_project_anchored_and_replaces_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root = base / "project"
            root.mkdir()
            (root / "service.py").write_text(
                "provider = TracerProvider()\n", encoding="utf-8"
            )
            output = root / ".observe" / "inventory.json"
            output.parent.mkdir()
            output.write_text("old\n", encoding="utf-8")
            unrelated_cwd = base / "cwd"
            unrelated_cwd.mkdir()

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCANNER),
                    str(root),
                    "--output",
                    ".observe/inventory.json",
                ],
                cwd=unrelated_cwd,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads(completed.stdout)
            self.assertEqual(summary["output"], str(output))
            self.assertEqual(json.loads(output.read_text())["root"], ".")
            self.assertFalse((unrelated_cwd / ".observe").exists())

    def test_relative_output_rejects_project_local_symlink_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root = base / "project"
            root.mkdir()
            outside = base / "outside"
            outside.mkdir()
            (root / ".observe").symlink_to(outside, target_is_directory=True)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCANNER),
                    str(root),
                    "--output",
                    ".observe/inventory.json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("symlink", completed.stderr.lower())
            self.assertFalse((outside / "inventory.json").exists())

    def test_output_rejects_symlink_target_and_project_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root = base / "project"
            root.mkdir()
            outside = base / "outside.json"
            outside.write_text("must survive\n", encoding="utf-8")
            target = root / "inventory.json"
            target.symlink_to(outside)

            target_result = subprocess.run(
                [
                    sys.executable,
                    str(SCANNER),
                    str(root),
                    "--output",
                    "inventory.json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            project_link = base / "project-link"
            project_link.symlink_to(root, target_is_directory=True)
            project_result = subprocess.run(
                [sys.executable, str(SCANNER), str(project_link)],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(target_result.returncode, 0)
            self.assertIn("symlink", target_result.stderr.lower())
            self.assertEqual(outside.read_text(encoding="utf-8"), "must survive\n")
            self.assertNotEqual(project_result.returncode, 0)
            self.assertIn("symlink", project_result.stderr.lower())

    def test_make_special_targets_are_not_commands(self) -> None:
        result = self.inspect(REPO_ROOT / "evals" / "go" / "kvstore")
        names = {item["name"] for item in result["project_commands"]}
        self.assertNotIn(".PHONY", names)
        self.assertIn("test", names)

    def test_rejects_invalid_root_and_limit(self) -> None:
        missing = subprocess.run(
            [sys.executable, str(SCANNER), "/definitely/missing"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("not a directory", missing.stderr)

        invalid_limit = subprocess.run(
            [sys.executable, str(SCANNER), str(REPO_ROOT), "--max-items", "0"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(invalid_limit.returncode, 0)
        self.assertIn("at least 1", invalid_limit.stderr)

        invalid_files = subprocess.run(
            [
                sys.executable,
                str(SCANNER),
                str(REPO_ROOT),
                "--max-files",
                "0",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(invalid_files.returncode, 0)
        self.assertIn("--max-files must be at least 1", invalid_files.stderr)

        invalid_bytes = subprocess.run(
            [
                sys.executable,
                str(SCANNER),
                str(REPO_ROOT),
                "--max-total-bytes",
                "0",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(invalid_bytes.returncode, 0)
        self.assertIn("--max-total-bytes must be at least 1", invalid_bytes.stderr)

        invalid_entries = subprocess.run(
            [
                sys.executable,
                str(SCANNER),
                str(REPO_ROOT),
                "--max-entries",
                "0",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(invalid_entries.returncode, 0)
        self.assertIn("--max-entries must be at least 1", invalid_entries.stderr)

        invalid_depth = subprocess.run(
            [
                sys.executable,
                str(SCANNER),
                str(REPO_ROOT),
                "--max-depth",
                "-1",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(invalid_depth.returncode, 0)
        self.assertIn("--max-depth must be at least 0", invalid_depth.stderr)


if __name__ == "__main__":
    unittest.main()
