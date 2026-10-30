import importlib.util
import io
import json
import os
import sys
import unittest
from pathlib import Path
import tempfile
import zipfile
from unittest import mock


def load_bootstrap_module():
    script_path = Path(__file__).resolve().parents[1] / "bootstrap_obstudio.py"
    spec = importlib.util.spec_from_file_location("bootstrap_obstudio", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BOOTSTRAP = load_bootstrap_module()


RUNTIME_SHA256 = "a" * 64


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def write_runtime_manifest(path, version="1.2.3", suffix="linux_amd64.zip", name=None, sha256=RUNTIME_SHA256, **overrides):
    manifest = {
        "schemaVersion": 1,
        "version": version,
        "artifacts": {suffix: {"name": name or f"obstudio_{version}_{suffix}", "sha256": sha256}},
    }
    manifest.update(overrides)
    path.write_text(json.dumps(manifest), encoding="utf-8")


class DummyProcess:
    def __init__(self, poll_result):
        self._poll_result = poll_result

    def poll(self):
        return self._poll_result


class BootstrapLockTest(unittest.TestCase):
    def test_windows_lock_retries_with_nonblocking_lock(self):
        class FakeMsvcrt:
            LK_NBLCK = 1
            LK_UNLCK = 2
            attempts = 0
            modes = []

            @classmethod
            def locking(cls, _fileno, mode, _length):
                cls.modes.append(mode)
                if mode == cls.LK_NBLCK:
                    cls.attempts += 1
                    if cls.attempts < 3:
                        raise OSError("busy")

        with tempfile.TemporaryDirectory() as tempdir:
            lock_path = Path(tempdir) / "bootstrap.lock"
            with (
                mock.patch.object(BOOTSTRAP, "is_windows", return_value=True),
                mock.patch.dict(sys.modules, {"msvcrt": FakeMsvcrt}),
                mock.patch.object(BOOTSTRAP.time, "monotonic", side_effect=[0.0, 1.0, 2.0]),
                mock.patch.object(BOOTSTRAP.time, "sleep") as sleep,
            ):
                with BOOTSTRAP.bootstrap_lock(lock_path):
                    pass

        self.assertEqual(FakeMsvcrt.modes, [FakeMsvcrt.LK_NBLCK, FakeMsvcrt.LK_NBLCK, FakeMsvcrt.LK_NBLCK, FakeMsvcrt.LK_UNLCK])
        self.assertEqual(sleep.call_count, 2)

    def test_main_reports_lock_failure_through_hook_error_boundary(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plugin_root = Path(tempdir) / "plugin"
            plugin_data = Path(tempdir) / "data"
            (plugin_root / ".codex-plugin").mkdir(parents=True)
            plugin_data.mkdir()
            (plugin_root / ".codex-plugin" / "plugin.json").write_text(
                json.dumps({"version": "0.1.0"}),
                encoding="utf-8",
            )
            with (
                mock.patch.object(BOOTSTRAP, "resolve_plugin_root", return_value=plugin_root),
                mock.patch.object(BOOTSTRAP, "resolve_plugin_data", return_value=plugin_data),
                mock.patch.object(BOOTSTRAP.Path, "home", return_value=Path(tempdir) / "home"),
                mock.patch.object(BOOTSTRAP, "bootstrap_lock", side_effect=BOOTSTRAP.BootstrapLockTimeout("busy")),
                mock.patch.object(BOOTSTRAP, "emit_error") as emit_error,
                mock.patch.object(BOOTSTRAP, "read_hook_payload", return_value={"session_id": "session-1"}),
                mock.patch.object(BOOTSTRAP, "emit_repository_correlation") as emit_correlation,
            ):
                self.assertEqual(BOOTSTRAP.main(), 2)

        emit_error.assert_called_once_with(
            "Splunk Observability Studio bootstrap could not complete automatically. "
            "The plugin bundle is present, but the managed runtime could not be prepared."
        )
        emit_correlation.assert_called_once_with({"session_id": "session-1"})


class ClaudeBootstrapTest(unittest.TestCase):
    def test_fallback_detects_codex_when_compatibility_root_variables_are_present(self):
        with mock.patch.dict(
            os.environ,
            {
                "CLAUDE_PLUGIN_ROOT": "/tmp/claude-plugin",
                "PLUGIN_ROOT": "/tmp/codex-plugin",
            },
            clear=True,
        ):
            self.assertEqual(BOOTSTRAP.plugin_host(), "codex")

    def test_codex_host_is_explicit_when_both_host_root_variables_are_present(self):
        with mock.patch.dict(
            os.environ,
            {
                "OBSTUDIO_PLUGIN_HOST": "codex",
                "CLAUDE_PLUGIN_ROOT": "/tmp/claude-plugin",
                "PLUGIN_ROOT": "/tmp/codex-plugin",
            },
            clear=True,
        ):
            self.assertEqual(BOOTSTRAP.plugin_host(), "codex")

    def test_prefers_codex_paths_when_both_host_environments_are_present(self):
        with tempfile.TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            claude_root = tempdir_path / "claude-plugin"
            codex_root = tempdir_path / "codex-plugin"
            claude_data = tempdir_path / "claude-data"
            codex_data = tempdir_path / "codex-data"
            claude_root.mkdir()
            codex_root.mkdir()
            with mock.patch.dict(
                os.environ,
                {
                    "OBSTUDIO_PLUGIN_HOST": "codex",
                    "CLAUDE_PLUGIN_ROOT": str(claude_root),
                    "PLUGIN_ROOT": str(codex_root),
                    "CLAUDE_PLUGIN_DATA": str(claude_data),
                    "PLUGIN_DATA": str(codex_data),
                },
            ):
                self.assertEqual(BOOTSTRAP.resolve_plugin_root(), codex_root.resolve())
                self.assertEqual(BOOTSTRAP.resolve_plugin_data(), codex_data.resolve())
                self.assertTrue(codex_data.is_dir())
                self.assertFalse(claude_data.exists())

    def test_prefers_claude_paths_when_both_host_environments_are_present(self):
        with tempfile.TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            claude_root = tempdir_path / "claude-plugin"
            codex_root = tempdir_path / "codex-plugin"
            claude_data = tempdir_path / "claude-data"
            codex_data = tempdir_path / "codex-data"
            claude_root.mkdir()
            codex_root.mkdir()
            with mock.patch.dict(
                os.environ,
                {
                    "OBSTUDIO_PLUGIN_HOST": "claude",
                    "CLAUDE_PLUGIN_ROOT": str(claude_root),
                    "PLUGIN_ROOT": str(codex_root),
                    "CLAUDE_PLUGIN_DATA": str(claude_data),
                    "PLUGIN_DATA": str(codex_data),
                },
            ):
                self.assertEqual(BOOTSTRAP.resolve_plugin_root(), claude_root.resolve())
                self.assertEqual(BOOTSTRAP.resolve_plugin_data(), claude_data.resolve())
                self.assertTrue(claude_data.is_dir())
                self.assertFalse(codex_data.exists())

    def test_claude_data_falls_back_under_config_directory(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config_dir = Path(tempdir) / "claude-config"
            with mock.patch.dict(
                os.environ,
                {
                    "OBSTUDIO_PLUGIN_HOST": "claude",
                    "CLAUDE_CONFIG_DIR": str(config_dir),
                },
                clear=True,
            ):
                data = BOOTSTRAP.resolve_plugin_data()

            self.assertEqual(data, (config_dir / "plugins" / "data" / "obstudio").resolve())
            self.assertTrue(data.is_dir())

    def test_codex_data_still_requires_host_provided_directory(self):
        with mock.patch.dict(os.environ, {"OBSTUDIO_PLUGIN_HOST": "codex"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "PLUGIN_DATA is not set"):
                BOOTSTRAP.resolve_plugin_data()

    def test_uses_claude_manifest_version_and_owner(self):
        prior = os.environ.get("OBSTUDIO_PLUGIN_HOST")
        os.environ["OBSTUDIO_PLUGIN_HOST"] = "claude"
        try:
            self.assertEqual(BOOTSTRAP.plugin_owner(), "claude-plugin")
            self.assertEqual(BOOTSTRAP.plugin_display_name(), "Splunk Observability Studio")
            self.assertEqual(BOOTSTRAP.skill_command("observer-open"), "/obstudio:observer-open")
            self.assertEqual(
                BOOTSTRAP.codex_obstudio_mcp_policy(Path("ignored"), "http://127.0.0.1:3000/mcp"),
                "plugin-local",
            )
            state = BOOTSTRAP.observer_state_fields(
                Path("missing-state.json"),
                local_requested=True,
                process_started=True,
                live_pid="",
                pid="1234",
                health_payload={"owner": "claude-plugin", "mode": "managed"},
                log_path=None,
            )
            self.assertEqual(state["owner"], "claude-plugin")
            self.assertEqual(state["mode"], "managed")
        finally:
            if prior is None:
                os.environ.pop("OBSTUDIO_PLUGIN_HOST", None)
            else:
                os.environ["OBSTUDIO_PLUGIN_HOST"] = prior

    def test_read_plugin_version_uses_selected_host_manifest(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / ".claude-plugin").mkdir()
            (root / ".codex-plugin").mkdir()
            (root / ".claude-plugin" / "plugin.json").write_text(
                '{"version": "0.0.0-claude-test"}',
                encoding="utf-8",
            )
            (root / ".codex-plugin" / "plugin.json").write_text(
                '{"version": "0.0.0-codex-test"}',
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {"OBSTUDIO_PLUGIN_HOST": "claude"}, clear=True):
                self.assertEqual(
                    BOOTSTRAP.read_plugin_version(root),
                    "0.0.0-claude-test",
                )

            with mock.patch.dict(os.environ, {"OBSTUDIO_PLUGIN_HOST": "codex"}, clear=True):
                self.assertEqual(
                    BOOTSTRAP.read_plugin_version(root),
                    "0.0.0-codex-test",
                )


class RepositoryCorrelationTest(unittest.TestCase):
    def test_reads_only_object_hook_payloads(self):
        self.assertEqual(
            BOOTSTRAP.read_hook_payload(io.StringIO('{"session_id":"session-1"}')),
            {"session_id": "session-1"},
        )
        self.assertEqual(BOOTSTRAP.read_hook_payload(io.StringIO("[1,2,3]")), {})
        self.assertEqual(BOOTSTRAP.read_hook_payload(io.StringIO("{")), {})

    def test_reads_opt_in_repository_correlation_without_requiring_provider_ownership(self):
        with tempfile.TemporaryDirectory() as tempdir:
            state_path = Path(tempdir) / "token-telemetry.json"
            state_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "repositoryCorrelation": {
                            "claude-code": {
                                "mode": "path",
                                "endpoint": "http://127.0.0.1:4318/v1/logs",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.dict(
                os.environ,
                {
                    "OBSTUDIO_PLUGIN_HOST": "claude",
                    "OBSTUDIO_TOKEN_TELEMETRY_STATE_PATH": str(state_path),
                },
                clear=True,
            ):
                self.assertEqual(
                    BOOTSTRAP.read_repository_correlation_config(),
                    {"mode": "path", "endpoint": "http://127.0.0.1:4318/v1/logs"},
                )

    def test_resolves_relative_repository_correlation_state_from_user_home(self):
        with tempfile.TemporaryDirectory() as tempdir:
            home = Path(tempdir)
            state_path = home / "state" / "token-telemetry.json"
            state_path.parent.mkdir()
            state_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "repositoryCorrelation": {
                            "codex": {
                                "mode": "name",
                                "endpoint": "http://localhost:4318/v1/logs",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "OBSTUDIO_PLUGIN_HOST": "codex",
                        "OBSTUDIO_TOKEN_TELEMETRY_STATE_PATH": "state/token-telemetry.json",
                    },
                    clear=True,
                ),
                mock.patch.object(BOOTSTRAP.Path, "home", return_value=home),
            ):
                self.assertEqual(
                    BOOTSTRAP.read_repository_correlation_config(),
                    {"mode": "name", "endpoint": "http://localhost:4318/v1/logs"},
                )

    def test_rejects_remote_path_correlation_endpoint(self):
        with tempfile.TemporaryDirectory() as tempdir:
            state_path = Path(tempdir) / "token-telemetry.json"
            state_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "repositoryCorrelation": {
                            "codex": {
                                "mode": "path",
                                "endpoint": "https://telemetry.example/v1/logs",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.dict(
                os.environ,
                {
                    "OBSTUDIO_PLUGIN_HOST": "codex",
                    "OBSTUDIO_TOKEN_TELEMETRY_STATE_PATH": str(state_path),
                },
                clear=True,
            ):
                self.assertIsNone(BOOTSTRAP.read_repository_correlation_config())

    def test_builds_content_free_claude_repository_event(self):
        with tempfile.TemporaryDirectory() as tempdir:
            repository = Path(tempdir) / "entity-model-service"
            workspace = repository / "internal" / "entity"
            (repository / ".git").mkdir(parents=True)
            workspace.mkdir(parents=True)
            payload = {
                "session_id": "session-1",
                "cwd": str(workspace),
                "hook_event_name": "SessionStart",
                "prompt": "must not be exported",
            }
            with mock.patch.dict(os.environ, {"OBSTUDIO_PLUGIN_HOST": "claude"}, clear=True):
                event = BOOTSTRAP.build_repository_correlation_event(
                    payload,
                    {"mode": "path", "endpoint": "http://127.0.0.1:4318/v1/logs"},
                )

        self.assertIsNotNone(event)
        encoded = json.dumps(event)
        self.assertNotIn("must not be exported", encoded)
        record = event["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        attributes = {
            item["key"]: item["value"]["stringValue"]
            for item in record["attributes"]
        }
        self.assertEqual(attributes["gen_ai.provider.name"], "claude")
        self.assertEqual(attributes["conversation.id"], "session-1")
        self.assertEqual(attributes["repository.name"], "entity-model-service")
        self.assertEqual(attributes["repository.path"], str(repository.resolve()))
        self.assertEqual(attributes["workspace.path"], str(repository.resolve()))

    def test_name_mode_does_not_export_paths(self):
        with tempfile.TemporaryDirectory() as tempdir:
            repository = Path(tempdir) / "entity-model-service"
            (repository / ".git").mkdir(parents=True)
            with mock.patch.dict(os.environ, {"OBSTUDIO_PLUGIN_HOST": "codex"}, clear=True):
                event = BOOTSTRAP.build_repository_correlation_event(
                    {"session_id": "thread-1", "cwd": str(repository)},
                    {"mode": "name", "endpoint": "http://localhost:4318/v1/logs"},
                )

        encoded = json.dumps(event)
        self.assertIn("entity-model-service", encoded)
        self.assertNotIn(str(repository), encoded)
        self.assertNotIn("repository.path", encoded)
        self.assertNotIn("workspace.path", encoded)

    def test_emits_repository_event_to_configured_local_otlp_endpoint(self):
        class FakeResponse(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        with tempfile.TemporaryDirectory() as tempdir:
            repository = Path(tempdir) / "service"
            (repository / ".git").mkdir(parents=True)
            config = {"mode": "path", "endpoint": "http://127.0.0.1:4318/v1/logs"}
            opener = mock.Mock()
            opener.open.return_value = FakeResponse()
            with (
                mock.patch.dict(os.environ, {"OBSTUDIO_PLUGIN_HOST": "claude"}, clear=True),
                mock.patch.object(BOOTSTRAP, "read_repository_correlation_config", return_value=config),
                mock.patch.object(BOOTSTRAP.urllib.request, "build_opener", return_value=opener),
            ):
                emitted = BOOTSTRAP.emit_repository_correlation(
                    {"session_id": "session-1", "cwd": str(repository), "hook_event_name": "SessionStart"}
                )

        self.assertTrue(emitted)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, config["endpoint"])
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(
            json.loads(request.data)["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["body"]["stringValue"],
            BOOTSTRAP.REPOSITORY_CORRELATION_EVENT,
        )

    def test_repository_event_bypasses_inherited_proxies(self):
        class FakeResponse(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        opener = mock.Mock()
        opener.open.return_value = FakeResponse()
        with tempfile.TemporaryDirectory() as tempdir:
            repository = Path(tempdir) / "service"
            (repository / ".git").mkdir(parents=True)
            config = {"mode": "path", "endpoint": "http://127.0.0.1:4318/v1/logs"}
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "OBSTUDIO_PLUGIN_HOST": "claude",
                        "HTTP_PROXY": "http://proxy.invalid:9876",
                        "HTTPS_PROXY": "http://proxy.invalid:9876",
                        "NO_PROXY": "",
                        "no_proxy": "",
                    },
                    clear=True,
                ),
                mock.patch.object(BOOTSTRAP, "read_repository_correlation_config", return_value=config),
                mock.patch.object(BOOTSTRAP.urllib.request, "build_opener", return_value=opener) as build_opener,
                mock.patch.object(BOOTSTRAP.urllib.request, "urlopen") as urlopen,
            ):
                emitted = BOOTSTRAP.emit_repository_correlation(
                    {"session_id": "session-1", "cwd": str(repository), "hook_event_name": "SessionStart"}
                )

        self.assertTrue(emitted)
        urlopen.assert_not_called()
        proxy_handler = build_opener.call_args.args[0]
        self.assertIsInstance(proxy_handler, BOOTSTRAP.urllib.request.ProxyHandler)
        self.assertEqual(proxy_handler.proxies, {})
        opener.open.assert_called_once()


class EnsureProcessRunningTest(unittest.TestCase):
    def test_accepts_running_child(self):
        BOOTSTRAP.ensure_process_running(DummyProcess(None))

    def test_rejects_exited_child(self):
        with self.assertRaisesRegex(RuntimeError, "exited before becoming healthy"):
            BOOTSTRAP.ensure_process_running(DummyProcess(1))


class ExtractedBinaryMatchesArchiveTest(unittest.TestCase):
    def test_accepts_matching_extracted_binary(self):
        with tempfile.TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            archive_path = tempdir_path / "obstudio_0.0.14_linux_amd64.zip"
            binary_name = "obstudio"
            extracted_binary = tempdir_path / binary_name
            extracted_binary.write_bytes(b"hello-obstudio")

            with zipfile.ZipFile(archive_path, "w") as zf:
                zf.writestr(f"obstudio_0.0.14_linux_amd64/{binary_name}", b"hello-obstudio")

            self.assertTrue(BOOTSTRAP.extracted_binary_matches_archive(archive_path, extracted_binary, binary_name))

    def test_rejects_mismatched_extracted_binary(self):
        with tempfile.TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            archive_path = tempdir_path / "obstudio_0.0.14_linux_amd64.zip"
            binary_name = "obstudio"
            extracted_binary = tempdir_path / binary_name
            extracted_binary.write_bytes(b"hello-obstudio")

            with zipfile.ZipFile(archive_path, "w") as zf:
                zf.writestr(f"obstudio_0.0.14_linux_amd64/{binary_name}", b"different-bytes")

            self.assertFalse(BOOTSTRAP.extracted_binary_matches_archive(archive_path, extracted_binary, binary_name))


class DownloadObstudioTest(unittest.TestCase):
    def test_reuses_wrapped_extracted_binary_from_valid_cache(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plugin_data = Path(tempdir)
            release_dir = plugin_data / "release" / "obstudio_0.0.14_linux_amd64"
            extracted_binary = release_dir / "extracted" / "obstudio_0.0.14_linux_amd64" / "obstudio"
            archive_path = release_dir / "obstudio_0.0.14_linux_amd64.zip"
            extracted_binary.parent.mkdir(parents=True)
            extracted_binary.write_bytes(b"hello-obstudio")
            with zipfile.ZipFile(archive_path, "w") as zf:
                zf.writestr("obstudio_0.0.14_linux_amd64/obstudio", b"hello-obstudio")
            expected_checksum = BOOTSTRAP.sha256_file(archive_path)

            with mock.patch.object(BOOTSTRAP.urllib.request, "urlopen") as urlopen:
                got = BOOTSTRAP.download_obstudio(
                    plugin_data,
                    "linux_amd64.zip",
                    "obstudio_0.0.14_linux_amd64.zip",
                    expected_checksum,
                    "0.0.14",
                )

            self.assertEqual(got, extracted_binary.resolve())
            urlopen.assert_not_called()

    def test_downloads_new_release_without_removing_old_extracted_release(self):
        class FakeResponse(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        with tempfile.TemporaryDirectory() as tempdir:
            plugin_data = Path(tempdir)
            old_binary = (
                plugin_data
                / "release"
                / "obstudio_0.0.13_linux_amd64"
                / "extracted"
                / "obstudio_0.0.13_linux_amd64"
                / "obstudio"
            )
            old_binary.parent.mkdir(parents=True)
            old_binary.write_bytes(b"old-running-obstudio")

            archive_buffer = io.BytesIO()
            with zipfile.ZipFile(archive_buffer, "w") as zf:
                zf.writestr("obstudio_0.0.14_linux_amd64/obstudio", b"new-obstudio")
            archive_bytes = archive_buffer.getvalue()
            expected_checksum = BOOTSTRAP.hashlib.sha256(archive_bytes).hexdigest()

            with mock.patch.object(
                BOOTSTRAP.urllib.request,
                "urlopen",
                return_value=FakeResponse(archive_bytes),
            ):
                got = BOOTSTRAP.download_obstudio(
                    plugin_data,
                    "linux_amd64.zip",
                    "obstudio_0.0.14_linux_amd64.zip",
                    expected_checksum,
                    "0.0.14",
                )

            self.assertTrue(old_binary.is_file())
            self.assertEqual(got.name, "obstudio")
            self.assertEqual(got.read_bytes(), b"new-obstudio")
            self.assertIn("obstudio_0.0.14_linux_amd64", str(got))


class ValidateZipEntriesTest(unittest.TestCase):
    def test_accepts_normal_nested_entry(self):
        with tempfile.TemporaryDirectory() as tempdir:
            archive_path = Path(tempdir) / "safe.zip"
            with zipfile.ZipFile(archive_path, "w") as zf:
                zf.writestr("obstudio_0.0.14/obstudio", b"binary")

            with zipfile.ZipFile(archive_path) as zf:
                BOOTSTRAP.validate_zip_entries(zf, Path(tempdir) / "extract")

    def test_rejects_parent_traversal_entry(self):
        with tempfile.TemporaryDirectory() as tempdir:
            archive_path = Path(tempdir) / "traversal.zip"
            with zipfile.ZipFile(archive_path, "w") as zf:
                zf.writestr("../outside", b"bad")

            with zipfile.ZipFile(archive_path) as zf:
                with self.assertRaisesRegex(RuntimeError, "unsafe path"):
                    BOOTSTRAP.validate_zip_entries(zf, Path(tempdir) / "extract")

    def test_rejects_absolute_entry(self):
        with tempfile.TemporaryDirectory() as tempdir:
            archive_path = Path(tempdir) / "absolute.zip"
            absolute_entry = str(Path(Path(tempdir).anchor or "/") / "outside")
            with zipfile.ZipFile(archive_path, "w") as zf:
                zf.writestr(absolute_entry, b"bad")

            with zipfile.ZipFile(archive_path) as zf:
                with self.assertRaisesRegex(RuntimeError, "unsafe path"):
                    BOOTSTRAP.validate_zip_entries(zf, Path(tempdir) / "extract")


class LoadRuntimeManifestTest(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self.manifest_path = Path(self._tempdir.name) / "runtime-manifest.json"
        patcher = mock.patch.object(BOOTSTRAP, "RUNTIME_MANIFEST_PATH", self.manifest_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_returns_pinned_runtime_for_matching_plugin_version(self):
        write_runtime_manifest(self.manifest_path)

        got = BOOTSTRAP.load_runtime_manifest("linux_amd64.zip", "1.2.3")

        self.assertEqual(got, ("1.2.3", "obstudio_1.2.3_linux_amd64.zip", RUNTIME_SHA256))

    def test_absolute_path_plugin_version_accepts_manifest_version(self):
        write_runtime_manifest(self.manifest_path)
        plugin_root_key = str(Path(self._tempdir.name).resolve())

        got = BOOTSTRAP.load_runtime_manifest("linux_amd64.zip", plugin_root_key)

        self.assertEqual(got[0], "1.2.3")

    def test_missing_manifest_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "missing or unreadable"):
            BOOTSTRAP.load_runtime_manifest("linux_amd64.zip", "1.2.3")

    def test_malformed_json_fails_closed(self):
        self.manifest_path.write_text("{not json", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "missing or unreadable"):
            BOOTSTRAP.load_runtime_manifest("linux_amd64.zip", "1.2.3")

    def test_wrong_schema_version_is_rejected(self):
        write_runtime_manifest(self.manifest_path, schemaVersion=2)

        with self.assertRaisesRegex(RuntimeError, "unsupported schema"):
            BOOTSTRAP.load_runtime_manifest("linux_amd64.zip", "1.2.3")

    def test_non_semver_manifest_version_is_rejected(self):
        write_runtime_manifest(self.manifest_path, version="latest")

        with self.assertRaisesRegex(RuntimeError, "invalid version"):
            BOOTSTRAP.load_runtime_manifest("linux_amd64.zip", "latest")

    def test_plugin_version_mismatch_is_rejected(self):
        write_runtime_manifest(self.manifest_path)

        with self.assertRaisesRegex(RuntimeError, "pins 1.2.3 but the plugin is 1.2.4"):
            BOOTSTRAP.load_runtime_manifest("linux_amd64.zip", "1.2.4")

    def test_platform_without_pinned_runtime_is_rejected(self):
        write_runtime_manifest(self.manifest_path)

        with self.assertRaisesRegex(RuntimeError, "no pinned runtime for darwin_arm64.zip"):
            BOOTSTRAP.load_runtime_manifest("darwin_arm64.zip", "1.2.3")

    def test_artifact_name_mismatch_is_rejected(self):
        write_runtime_manifest(self.manifest_path, name="obstudio_1.2.3_darwin_arm64.zip")

        with self.assertRaisesRegex(RuntimeError, "artifact name for linux_amd64.zip is invalid"):
            BOOTSTRAP.load_runtime_manifest("linux_amd64.zip", "1.2.3")

    def test_invalid_sha256_is_rejected(self):
        for bad in (RUNTIME_SHA256.upper(), "abc123", "", None):
            with self.subTest(sha256=bad):
                write_runtime_manifest(self.manifest_path, sha256=bad)

                with self.assertRaisesRegex(RuntimeError, "checksum for linux_amd64.zip is invalid"):
                    BOOTSTRAP.load_runtime_manifest("linux_amd64.zip", "1.2.3")


class ResolveRuntimeReleaseTest(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self.plugin_data = Path(self._tempdir.name) / "data"
        self.plugin_data.mkdir()
        self.manifest_path = Path(self._tempdir.name) / "runtime-manifest.json"
        write_runtime_manifest(self.manifest_path)
        patcher = mock.patch.object(BOOTSTRAP, "RUNTIME_MANIFEST_PATH", self.manifest_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_downloads_the_manifest_pinned_archive_for_each_host(self):
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                binary = self.plugin_data / "obstudio"
                with (
                    mock.patch.dict(os.environ, {"OBSTUDIO_PLUGIN_HOST": host}, clear=True),
                    mock.patch.object(BOOTSTRAP, "download_obstudio", return_value=binary) as download,
                ):
                    got = BOOTSTRAP.resolve_runtime_release(self.plugin_data, "linux_amd64.zip", "1.2.3")

                self.assertEqual(got, (binary, "obstudio_1.2.3_linux_amd64.zip", RUNTIME_SHA256, "1.2.3"))
                download.assert_called_once_with(
                    self.plugin_data, "linux_amd64.zip", "obstudio_1.2.3_linux_amd64.zip", RUNTIME_SHA256, "1.2.3"
                )

    def test_missing_pinned_archive_does_not_fall_back(self):
        not_found = BOOTSTRAP.urllib.error.HTTPError("url", 404, "Not Found", {}, None)
        with mock.patch.object(BOOTSTRAP, "download_obstudio", side_effect=not_found) as download:
            with self.assertRaises(BOOTSTRAP.urllib.error.HTTPError):
                BOOTSTRAP.resolve_runtime_release(self.plugin_data, "linux_amd64.zip", "1.2.3")

        download.assert_called_once()

    def test_invalid_manifest_never_downloads(self):
        self.manifest_path.write_text("{}", encoding="utf-8")
        with mock.patch.object(BOOTSTRAP, "download_obstudio") as download:
            with self.assertRaisesRegex(RuntimeError, "unsupported schema"):
                BOOTSTRAP.resolve_runtime_release(self.plugin_data, "linux_amd64.zip", "1.2.3")

        download.assert_not_called()

    def test_removes_legacy_checksum_caches_after_install(self):
        release_dir = self.plugin_data / "release" / "linux_amd64"
        release_dir.mkdir(parents=True)
        (release_dir / "checksums.txt").write_text("old\n", encoding="utf-8")
        (release_dir / "checksums-1.2.2.txt").write_text("old\n", encoding="utf-8")
        with mock.patch.object(BOOTSTRAP, "download_obstudio", return_value=self.plugin_data / "obstudio"):
            BOOTSTRAP.resolve_runtime_release(self.plugin_data, "linux_amd64.zip", "1.2.3")

        self.assertEqual(list(release_dir.glob("checksums*.txt")), [])


class RemoveLegacyChecksumCachesTest(unittest.TestCase):
    def test_removes_only_checksum_files(self):
        with tempfile.TemporaryDirectory() as tempdir:
            release_dir = Path(tempdir) / "release" / "obstudio_1.2.3_linux_amd64"
            release_dir.mkdir(parents=True)
            (release_dir / "checksums.txt").write_text("x", encoding="utf-8")
            (release_dir / "checksums-1.2.3.txt").write_text("x", encoding="utf-8")
            keep = release_dir / "obstudio_1.2.3_linux_amd64.zip"
            keep.write_bytes(b"zip")

            BOOTSTRAP.remove_legacy_checksum_caches(Path(tempdir))

            self.assertEqual(sorted(path.name for path in release_dir.iterdir()), [keep.name])

    def test_tolerates_missing_release_directory(self):
        with tempfile.TemporaryDirectory() as tempdir:
            BOOTSTRAP.remove_legacy_checksum_caches(Path(tempdir))


class DownloadPinnedReleaseTest(unittest.TestCase):
    def archive_bytes(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("obstudio_1.2.3_linux_amd64/obstudio", b"pinned-obstudio")
        return buffer.getvalue()

    def test_only_requests_the_exact_release_tag_archive(self):
        archive = self.archive_bytes()
        urls = []

        def fake_urlopen(url, timeout=None):
            urls.append(url)
            return FakeResponse(archive)

        with tempfile.TemporaryDirectory() as tempdir:
            with mock.patch.object(BOOTSTRAP.urllib.request, "urlopen", side_effect=fake_urlopen):
                BOOTSTRAP.download_obstudio(
                    Path(tempdir),
                    "linux_amd64.zip",
                    "obstudio_1.2.3_linux_amd64.zip",
                    BOOTSTRAP.hashlib.sha256(archive).hexdigest(),
                    "1.2.3",
                )

        self.assertEqual(
            urls,
            ["https://github.com/signalfx/obstudio/releases/download/v1.2.3/obstudio_1.2.3_linux_amd64.zip"],
        )
        self.assertFalse([url for url in urls if "latest" in url])

    def test_not_found_raises_without_trying_another_url(self):
        not_found = BOOTSTRAP.urllib.error.HTTPError("url", 404, "Not Found", {}, None)
        with tempfile.TemporaryDirectory() as tempdir:
            with mock.patch.object(BOOTSTRAP.urllib.request, "urlopen", side_effect=not_found) as urlopen:
                with self.assertRaises(BOOTSTRAP.urllib.error.HTTPError):
                    BOOTSTRAP.download_obstudio(
                        Path(tempdir),
                        "linux_amd64.zip",
                        "obstudio_1.2.3_linux_amd64.zip",
                        RUNTIME_SHA256,
                        "1.2.3",
                    )

            archive_path = (
                Path(tempdir) / "release" / "obstudio_1.2.3_linux_amd64" / "obstudio_1.2.3_linux_amd64.zip"
            )
            self.assertFalse(archive_path.exists())

        urlopen.assert_called_once()
        self.assertNotIn("latest", urlopen.call_args.args[0])

    def test_checksum_mismatch_deletes_archive_and_never_extracts_or_runs(self):
        archive = self.archive_bytes()
        with tempfile.TemporaryDirectory() as tempdir:
            release_dir = Path(tempdir) / "release" / "obstudio_1.2.3_linux_amd64"
            with (
                mock.patch.object(BOOTSTRAP.urllib.request, "urlopen", return_value=FakeResponse(archive)),
                mock.patch.object(BOOTSTRAP.subprocess, "Popen") as popen,
                mock.patch.object(BOOTSTRAP.subprocess, "run") as run,
            ):
                with self.assertRaisesRegex(RuntimeError, "is corrupt"):
                    BOOTSTRAP.download_obstudio(
                        Path(tempdir),
                        "linux_amd64.zip",
                        "obstudio_1.2.3_linux_amd64.zip",
                        RUNTIME_SHA256,
                        "1.2.3",
                    )

            self.assertFalse((release_dir / "obstudio_1.2.3_linux_amd64.zip").exists())
            self.assertFalse((release_dir / "extracted").exists())
            self.assertEqual([path for path in Path(tempdir).rglob("obstudio") if path.is_file()], [])
        popen.assert_not_called()
        run.assert_not_called()


class HookSourceTest(unittest.TestCase):
    def test_hook_source_has_no_latest_release_path(self):
        source = (Path(__file__).resolve().parents[1] / "bootstrap_obstudio.py").read_text(encoding="utf-8")

        self.assertNotIn("releases/latest", source)
        self.assertNotIn("fetch_expected_checksum", source)


class RuntimeVersionWarningTest(unittest.TestCase):
    def test_warns_when_claude_reuses_shared_mismatched_runtime(self):
        with tempfile.TemporaryDirectory() as tempdir:
            state_path = Path(tempdir) / "bootstrap-state.json"
            state_path.write_text(json.dumps({"mode": "shared"}), encoding="utf-8")
            with (
                mock.patch.dict(os.environ, {"OBSTUDIO_PLUGIN_HOST": "claude"}, clear=True),
                mock.patch.object(BOOTSTRAP, "fetch_obstudio_health", return_value={"version": "1.2.4"}),
                mock.patch.object(BOOTSTRAP, "emit_context") as emit_context,
            ):
                BOOTSTRAP.warn_if_shared_runtime_version_mismatch(state_path, "1.2.3")

        emit_context.assert_called_once_with(
            "Claude Code plugin version 1.2.3 is using an already-running Observer version 1.2.4; "
            "the existing runtime was left running."
        )

    def test_warns_when_codex_reuses_shared_mismatched_runtime(self):
        with tempfile.TemporaryDirectory() as tempdir:
            state_path = Path(tempdir) / "bootstrap-state.json"
            state_path.write_text(json.dumps({"mode": "shared"}), encoding="utf-8")
            with (
                mock.patch.dict(os.environ, {"OBSTUDIO_PLUGIN_HOST": "codex"}, clear=True),
                mock.patch.object(BOOTSTRAP, "fetch_obstudio_health", return_value={"version": "1.2.4"}),
                mock.patch.object(BOOTSTRAP, "emit_context") as emit_context,
            ):
                BOOTSTRAP.warn_if_shared_runtime_version_mismatch(state_path, "1.2.3")

        emit_context.assert_called_once_with(
            "Codex plugin version 1.2.3 is using an already-running Observer version 1.2.4; "
            "the existing runtime was left running."
        )

    def test_does_not_probe_managed_runtime(self):
        with tempfile.TemporaryDirectory() as tempdir:
            state_path = Path(tempdir) / "bootstrap-state.json"
            state_path.write_text(json.dumps({"mode": "managed"}), encoding="utf-8")
            with mock.patch.object(BOOTSTRAP, "fetch_obstudio_health") as fetch_health:
                BOOTSTRAP.warn_if_shared_runtime_version_mismatch(state_path, "1.2.3")

        fetch_health.assert_not_called()


class ObserverStateFieldsTest(unittest.TestCase):
    def test_started_local_process_is_managed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            got = BOOTSTRAP.observer_state_fields(
                Path(tempdir) / "bootstrap-state.json",
                local_requested=True,
                process_started=True,
                live_pid="",
                pid="1234",
                health_payload={"kind": "obstudio", "apiVersion": "v1", "owner": "codex-plugin", "mode": "managed"},
                log_path=Path(tempdir) / "obstudio.log",
            )

        self.assertEqual(got["owner"], "codex-plugin")
        self.assertEqual(got["mode"], "managed")
        self.assertEqual(got["pid"], "1234")

    def test_reused_listener_without_prior_owned_pid_is_external(self):
        with tempfile.TemporaryDirectory() as tempdir:
            got = BOOTSTRAP.observer_state_fields(
                Path(tempdir) / "bootstrap-state.json",
                local_requested=True,
                process_started=False,
                live_pid="4321",
                pid="4321",
                health_payload={"kind": "obstudio", "apiVersion": "v1", "owner": "external", "mode": "standalone"},
                log_path=None,
            )

        self.assertEqual(got["owner"], "external-observer")
        self.assertEqual(got["mode"], "external")

    def test_reused_listener_with_matching_prior_owned_pid_remains_managed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            state_path = Path(tempdir) / "bootstrap-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "owner": "codex-plugin",
                        "mode": "managed",
                        "pid": "4321",
                        "observerStartedAt": "2026-08-04T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            got = BOOTSTRAP.observer_state_fields(
                state_path,
                local_requested=True,
                process_started=False,
                live_pid="4321",
                pid="4321",
                health_payload={
                    "kind": "obstudio",
                    "apiVersion": "v1",
                    "owner": "codex-plugin",
                    "mode": "managed",
                    "startedAt": "2026-08-04T00:00:00Z",
                },
                log_path=None,
            )

        self.assertEqual(got["owner"], "codex-plugin")
        self.assertEqual(got["mode"], "managed")


class BootstrapStateHealthTest(unittest.TestCase):
    def test_stopped_bootstrap_state_requests_stop(self):
        with tempfile.TemporaryDirectory() as tempdir:
            state_path = Path(tempdir) / "bootstrap-state.json"
            state_path.write_text(json.dumps({"status": "stopped"}), encoding="utf-8")

            self.assertTrue(BOOTSTRAP.bootstrap_state_requests_stop(state_path))

    def test_bootstrap_state_requires_live_health_for_shared_url(self):
        with tempfile.TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            state_path = tempdir_path / "bootstrap-state.json"
            skills_path = tempdir_path / ".codex" / "skills" / "obstudio"
            config_path = tempdir_path / ".codex" / "config.toml"
            skills_path.mkdir(parents=True, exist_ok=True)
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                "\n".join(
                    [
                        BOOTSTRAP.CODEX_MANAGED_BLOCK,
                        "[mcp_servers.obstudio]",
                        "enabled = true",
                        'url = "http://127.0.0.1:17900/mcp"',
                        BOOTSTRAP.CODEX_MANAGED_BLOCK.replace("# BEGIN", "# END"),
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            state_path.write_text(json.dumps({"pluginVersion": "0.1.0"}), encoding="utf-8")

            with mock.patch.object(BOOTSTRAP, "fetch_obstudio_health", return_value=None):
                self.assertFalse(
                    BOOTSTRAP.is_bootstrapped(
                        state_path,
                        "0.1.0",
                        config_path,
                        skills_path,
                    )
                )

            with mock.patch.object(
                BOOTSTRAP,
                "fetch_obstudio_health",
                return_value={"kind": "obstudio", "apiVersion": "v1"},
            ):
                self.assertTrue(
                    BOOTSTRAP.is_bootstrapped(
                        state_path,
                        "0.1.0",
                        config_path,
                        skills_path,
                    )
                )

    def test_managed_state_requires_matching_live_pid(self):
        with tempfile.TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            state_path = tempdir_path / "bootstrap-state.json"
            skills_path = tempdir_path / ".codex" / "skills" / "obstudio"
            config_path = tempdir_path / ".codex" / "config.toml"
            skills_path.mkdir(parents=True, exist_ok=True)
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                "\n".join(
                    [
                        BOOTSTRAP.CODEX_MANAGED_BLOCK,
                        "[mcp_servers.obstudio]",
                        "enabled = true",
                        'url = "http://127.0.0.1:17900/mcp"',
                        BOOTSTRAP.CODEX_MANAGED_BLOCK.replace("# BEGIN", "# END"),
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            health_payload = {
                "kind": "obstudio",
                "apiVersion": "v1",
                "owner": "codex-plugin",
                "mode": "managed",
                "version": "0.1.0",
                "startedAt": "2026-08-04T00:00:00Z",
            }
            state_path.write_text(
                json.dumps(
                    {
                        "pluginVersion": "0.1.0",
                        "owner": "codex-plugin",
                        "mode": "managed",
                        "pid": "1234",
                        "observerStartedAt": "2026-08-04T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.object(BOOTSTRAP, "fetch_obstudio_health", return_value=health_payload),
                mock.patch.object(BOOTSTRAP, "find_pid_listening_on_url", return_value="5678"),
            ):
                self.assertFalse(
                    BOOTSTRAP.is_bootstrapped(
                        state_path,
                        "0.1.0",
                        config_path,
                        skills_path,
                    )
                )

            with (
                mock.patch.object(BOOTSTRAP, "fetch_obstudio_health", return_value=health_payload),
                mock.patch.object(BOOTSTRAP, "find_pid_listening_on_url", return_value="1234"),
            ):
                self.assertTrue(
                    BOOTSTRAP.is_bootstrapped(
                        state_path,
                        "0.1.0",
                        config_path,
                        skills_path,
                    )
                )

    def test_managed_state_requires_pinned_plugin_version(self):
        with tempfile.TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            state_path = tempdir_path / "bootstrap-state.json"
            skills_path = tempdir_path / ".codex" / "skills" / "obstudio"
            config_path = tempdir_path / ".codex" / "config.toml"
            skills_path.mkdir(parents=True, exist_ok=True)
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                "\n".join(
                    [
                        BOOTSTRAP.CODEX_MANAGED_BLOCK,
                        "[mcp_servers.obstudio]",
                        "enabled = true",
                        'url = "http://127.0.0.1:17900/mcp"',
                        BOOTSTRAP.CODEX_MANAGED_BLOCK.replace("# BEGIN", "# END"),
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            state_path.write_text(
                json.dumps(
                    {
                        "pluginVersion": "0.1.0",
                        "releaseVersion": "0.1.1",
                        "owner": "codex-plugin",
                        "mode": "managed",
                        "pid": "1234",
                    }
                ),
                encoding="utf-8",
            )
            stale_health_payload = {
                "kind": "obstudio",
                "apiVersion": "v1",
                "owner": "codex-plugin",
                "mode": "managed",
                "version": "0.1.1",
            }
            current_health_payload = {
                "kind": "obstudio",
                "apiVersion": "v1",
                "owner": "codex-plugin",
                "mode": "managed",
                "version": "v0.1.0",
            }

            with (
                mock.patch.object(BOOTSTRAP, "fetch_obstudio_health", return_value=stale_health_payload),
                mock.patch.object(BOOTSTRAP, "find_pid_listening_on_url", return_value="1234"),
            ):
                self.assertFalse(
                    BOOTSTRAP.is_bootstrapped(
                        state_path,
                        "0.1.0",
                        config_path,
                        skills_path,
                    )
                )

            with (
                mock.patch.object(BOOTSTRAP, "fetch_obstudio_health", return_value=current_health_payload),
                mock.patch.object(BOOTSTRAP, "find_pid_listening_on_url", return_value="1234"),
            ):
                self.assertTrue(
                    BOOTSTRAP.is_bootstrapped(
                        state_path,
                        "0.1.0",
                        config_path,
                        skills_path,
                    )
                )

    def test_managed_state_accepts_missing_pid_lookup_when_health_metadata_matches(self):
        with tempfile.TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            state_path = tempdir_path / "bootstrap-state.json"
            skills_path = tempdir_path / ".codex" / "skills" / "obstudio"
            config_path = tempdir_path / ".codex" / "config.toml"
            skills_path.mkdir(parents=True, exist_ok=True)
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                "\n".join(
                    [
                        BOOTSTRAP.CODEX_MANAGED_BLOCK,
                        "[mcp_servers.obstudio]",
                        "enabled = true",
                        'url = "http://127.0.0.1:17900/mcp"',
                        BOOTSTRAP.CODEX_MANAGED_BLOCK.replace("# BEGIN", "# END"),
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            health_payload = {
                "kind": "obstudio",
                "apiVersion": "v1",
                "owner": "codex-plugin",
                "mode": "managed",
                "version": "0.1.0",
                "startedAt": "2026-08-04T00:00:00Z",
            }
            state_path.write_text(
                json.dumps(
                    {
                        "pluginVersion": "0.1.0",
                        "owner": "codex-plugin",
                        "mode": "managed",
                        "pid": "1234",
                        "observerStartedAt": "2026-08-04T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.object(BOOTSTRAP, "fetch_obstudio_health", return_value=health_payload),
                mock.patch.object(BOOTSTRAP, "find_pid_listening_on_url", return_value=""),
            ):
                self.assertTrue(
                    BOOTSTRAP.is_bootstrapped(
                        state_path,
                        "0.1.0",
                        config_path,
                        skills_path,
                    )
                )

    def test_managed_state_rejects_reused_pid_with_different_started_at(self):
        with tempfile.TemporaryDirectory() as tempdir:
            state_path = Path(tempdir) / "bootstrap-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "owner": "codex-plugin",
                        "mode": "managed",
                        "pid": "1234",
                        "observerStartedAt": "2026-08-04T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )

            self.assertFalse(
                BOOTSTRAP.bootstrap_state_proves_managed_owner(
                    state_path,
                    "1234",
                    {
                        "kind": "obstudio",
                        "apiVersion": "v1",
                        "owner": "codex-plugin",
                        "mode": "managed",
                        "startedAt": "2026-08-04T00:01:00Z",
                    },
                )
            )

    def test_managed_state_rejects_health_metadata_owner_mismatch(self):
        with tempfile.TemporaryDirectory() as tempdir:
            state_path = Path(tempdir) / "bootstrap-state.json"
            state_path.write_text(
                json.dumps({"owner": "codex-plugin", "mode": "managed", "pid": "1234"}),
                encoding="utf-8",
            )

            self.assertFalse(
                BOOTSTRAP.bootstrap_state_proves_managed_owner(
                    state_path,
                    "1234",
                    {
                        "kind": "obstudio",
                        "apiVersion": "v1",
                        "owner": "cli",
                        "mode": "standalone",
                    },
                )
            )

    def test_main_honors_stopped_state_before_install(self):
        with tempfile.TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            plugin_root = tempdir_path / "plugin"
            plugin_data = tempdir_path / "data"
            codex_home = tempdir_path / "home"
            state_path = plugin_data / BOOTSTRAP.BOOTSTRAP_STATE_FILE
            (plugin_root / ".codex-plugin").mkdir(parents=True)
            plugin_data.mkdir()
            (plugin_root / ".codex-plugin" / "plugin.json").write_text(
                json.dumps({"version": "0.1.0"}),
                encoding="utf-8",
            )
            state_path.write_text(json.dumps({"pluginVersion": "0.1.0", "status": "stopped"}), encoding="utf-8")

            with (
                mock.patch.object(BOOTSTRAP, "resolve_plugin_root", return_value=plugin_root),
                mock.patch.object(BOOTSTRAP, "resolve_plugin_data", return_value=plugin_data),
                mock.patch.object(BOOTSTRAP.Path, "home", return_value=codex_home),
                mock.patch.object(BOOTSTRAP, "emit_context"),
            ):
                self.assertEqual(BOOTSTRAP.main(), 0)

    def test_main_reinstalls_on_version_change_when_stopped_without_starting_process(self):
        with tempfile.TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            plugin_root = tempdir_path / "plugin"
            plugin_data = tempdir_path / "data"
            codex_home = tempdir_path / "home"
            binary = tempdir_path / "obstudio"
            state_path = plugin_data / BOOTSTRAP.BOOTSTRAP_STATE_FILE
            (plugin_root / ".codex-plugin").mkdir(parents=True)
            plugin_data.mkdir()
            binary.write_text("binary", encoding="utf-8")
            (plugin_root / ".codex-plugin" / "plugin.json").write_text(
                json.dumps({"version": "0.2.0"}),
                encoding="utf-8",
            )
            state_path.write_text(
                json.dumps(
                    {
                        "pluginVersion": "0.1.0",
                        "status": "stopped",
                        "owner": "codex-plugin",
                        "mode": "managed",
                        "pid": "1234",
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.object(BOOTSTRAP, "resolve_plugin_root", return_value=plugin_root),
                mock.patch.object(BOOTSTRAP, "resolve_plugin_data", return_value=plugin_data),
                mock.patch.object(BOOTSTRAP.Path, "home", return_value=codex_home),
                mock.patch.object(BOOTSTRAP, "resolve_release_artifact", return_value="linux_amd64.zip"),
                mock.patch.object(
                    BOOTSTRAP,
                    "load_runtime_manifest",
                    return_value=("0.2.0", "obstudio_0.2.0_linux_amd64.zip", "checksum"),
                ),
                mock.patch.object(BOOTSTRAP, "start_obstudio_background") as start_obstudio_background,
                mock.patch.object(BOOTSTRAP, "emit_context"),
            ):
                self.assertEqual(BOOTSTRAP.main(), 0)

            start_obstudio_background.assert_not_called()
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["pluginVersion"], "0.2.0")
            self.assertEqual(state["status"], "stopped")
            self.assertEqual(state["owner"], "codex-plugin")

    def test_main_preserves_explicit_codex_mcp_opt_out_without_installing(self):
        with tempfile.TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            plugin_root = tempdir_path / "plugin"
            plugin_data = tempdir_path / "data"
            codex_home = tempdir_path / "home"
            config_path = codex_home / ".codex" / "config.toml"
            (plugin_root / ".codex-plugin").mkdir(parents=True)
            plugin_data.mkdir()
            config_path.parent.mkdir(parents=True)
            (plugin_root / ".codex-plugin" / "plugin.json").write_text(
                json.dumps({"version": "0.1.0"}),
                encoding="utf-8",
            )
            (plugin_root / ".mcp.json").write_text(
                json.dumps({"mcpServers": {"obstudio": {"type": "http", "url": "http://127.0.0.1:3000/mcp"}}}),
                encoding="utf-8",
            )
            config_path.write_text(
                "\n".join(
                    [
                        "[mcp_servers.obstudio]",
                        "enabled = false",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.object(BOOTSTRAP, "resolve_plugin_root", return_value=plugin_root),
                mock.patch.object(BOOTSTRAP, "resolve_plugin_data", return_value=plugin_data),
                mock.patch.object(BOOTSTRAP.Path, "home", return_value=codex_home),
                mock.patch.object(BOOTSTRAP, "load_runtime_manifest") as load_runtime_manifest,
                mock.patch.object(BOOTSTRAP, "start_obstudio_background") as start_obstudio_background,
                mock.patch.object(BOOTSTRAP, "emit_context") as emit_context,
            ):
                self.assertEqual(BOOTSTRAP.main(), 0)

            load_runtime_manifest.assert_not_called()
            start_obstudio_background.assert_not_called()
            emit_context.assert_called_once_with(
                "Splunk Observability Studio MCP is explicitly disabled in Codex config. The plugin hook "
                "left managed Splunk Observability Studio stopped, did not start or restart the "
                "plugin-managed Splunk Observability Studio service, and bundled Splunk Observability Studio skills remain available."
            )
            self.assertIn("enabled = false", config_path.read_text(encoding="utf-8"))
            state = json.loads((plugin_data / BOOTSTRAP.BOOTSTRAP_STATE_FILE).read_text(encoding="utf-8"))
        self.assertEqual(state["pluginVersion"], "0.1.0")
        self.assertEqual(state["mode"], "disabled")

    def test_main_preserves_custom_codex_mcp_url_without_installing(self):
        with tempfile.TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            plugin_root = tempdir_path / "plugin"
            plugin_data = tempdir_path / "data"
            codex_home = tempdir_path / "home"
            config_path = codex_home / ".codex" / "config.toml"
            (plugin_root / ".codex-plugin").mkdir(parents=True)
            plugin_data.mkdir()
            config_path.parent.mkdir(parents=True)
            (plugin_root / ".codex-plugin" / "plugin.json").write_text(
                json.dumps({"version": "0.1.0"}),
                encoding="utf-8",
            )
            (plugin_root / ".mcp.json").write_text(
                json.dumps({"mcpServers": {"obstudio": {"type": "http", "url": "http://127.0.0.1:3000/mcp"}}}),
                encoding="utf-8",
            )
            config_path.write_text(
                "\n".join(
                    [
                        "[mcp_servers.obstudio]",
                        "enabled = true",
                        'url = "http://127.0.0.1:4111/mcp"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.object(BOOTSTRAP, "resolve_plugin_root", return_value=plugin_root),
                mock.patch.object(BOOTSTRAP, "resolve_plugin_data", return_value=plugin_data),
                mock.patch.object(BOOTSTRAP.Path, "home", return_value=codex_home),
                mock.patch.object(BOOTSTRAP, "load_runtime_manifest") as load_runtime_manifest,
                mock.patch.object(BOOTSTRAP, "start_obstudio_background") as start_obstudio_background,
                mock.patch.object(BOOTSTRAP, "emit_context") as emit_context,
            ):
                self.assertEqual(BOOTSTRAP.main(), 0)

            load_runtime_manifest.assert_not_called()
            start_obstudio_background.assert_not_called()
            emit_context.assert_called_once_with(
                "Custom Splunk Observability Studio MCP endpoint detected in Codex config. The plugin hook "
                "left the configured endpoint unchanged (http://127.0.0.1:4111/mcp), "
                "did not start or restart the plugin-managed Splunk Observability Studio service, and bundled "
                "Splunk Observability Studio skills remain available."
            )
            self.assertIn('url = "http://127.0.0.1:4111/mcp"', config_path.read_text(encoding="utf-8"))
            state = json.loads((plugin_data / BOOTSTRAP.BOOTSTRAP_STATE_FILE).read_text(encoding="utf-8"))
        self.assertEqual(state["pluginVersion"], "0.1.0")
        self.assertEqual(state["mode"], "custom")


class BootstrapHealthCheckTest(unittest.TestCase):
    def test_bootstrap_state_requires_live_health_for_local_config(self):
        with tempfile.TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            state_path = tempdir_path / "bootstrap-state.json"
            skills_path = tempdir_path / ".codex" / "skills" / "obstudio"
            config_path = tempdir_path / ".codex" / "config.toml"
            skills_path.mkdir(parents=True, exist_ok=True)
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                "\n".join(
                    [
                        BOOTSTRAP.CODEX_MANAGED_BLOCK,
                        "[mcp_servers.obstudio]",
                        "enabled = true",
                        'command = "/tmp/obstudio"',
                        BOOTSTRAP.CODEX_MANAGED_BLOCK.replace("# BEGIN", "# END"),
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            state_path.write_text(json.dumps({"pluginVersion": "0.1.0"}), encoding="utf-8")

            with mock.patch.object(BOOTSTRAP, "fetch_obstudio_health", return_value=None):
                self.assertFalse(
                    BOOTSTRAP.is_bootstrapped(
                        state_path,
                        "0.1.0",
                        config_path,
                        skills_path,
                    )
                )

            with mock.patch.object(
                BOOTSTRAP,
                "fetch_obstudio_health",
                return_value={"kind": "obstudio", "apiVersion": "v1"},
            ):
                self.assertTrue(
                    BOOTSTRAP.is_bootstrapped(
                        state_path,
                        "0.1.0",
                        config_path,
                        skills_path,
                    )
                )

    def test_find_pid_listening_on_url_prefers_live_listening_process(self):
        class FakeResult:
            returncode = 0
            stdout = "4321\n"

        with mock.patch.object(BOOTSTRAP.subprocess, "run", return_value=FakeResult()):
            self.assertEqual(
                BOOTSTRAP.find_pid_listening_on_url("http://127.0.0.1:3000/api/health"),
                "4321",
            )

    def test_find_pid_listening_on_url_uses_powershell_on_windows(self):
        class FakeResult:
            returncode = 0
            stdout = "9876\r\n"

        with (
            mock.patch.object(BOOTSTRAP, "is_windows", return_value=True),
            mock.patch.object(BOOTSTRAP.subprocess, "run", return_value=FakeResult()) as run,
        ):
            self.assertEqual(
                BOOTSTRAP.find_pid_listening_on_url("http://127.0.0.1:3000/api/health"),
                "9876",
            )

        command = run.call_args.args[0]
        self.assertEqual(command[0], "powershell")
        self.assertIn("Get-NetTCPConnection", " ".join(command))

    def test_codex_configured_health_url_derives_shared_mcp_health_endpoint(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config_path = Path(tempdir) / "config.toml"
            config_path.write_text(
                "\n".join(
                    [
                        BOOTSTRAP.CODEX_MANAGED_BLOCK,
                        "[mcp_servers.obstudio]",
                        "enabled = true",
                        'url = "http://127.0.0.1:3000/mcp"',
                        BOOTSTRAP.CODEX_MANAGED_BLOCK.replace("# BEGIN", "# END"),
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            got = BOOTSTRAP.codex_obstudio_health_url(config_path)
        self.assertEqual(got, "http://127.0.0.1:3000/api/health")


class ReleaseBinarySelectionTest(unittest.TestCase):
    def test_main_uses_verified_release_instead_of_path_candidate(self):
        class FakeProcess:
            pid = 2222

            def poll(self):
                return None

        with tempfile.TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            plugin_root = tempdir_path / "plugin"
            plugin_data = tempdir_path / "data"
            codex_home = tempdir_path / "home"
            config_path = codex_home / ".codex" / "config.toml"
            path_candidate = tempdir_path / "path" / "obstudio"
            verified_binary = tempdir_path / "verified" / "obstudio"
            state_path = plugin_data / BOOTSTRAP.BOOTSTRAP_STATE_FILE
            (plugin_root / ".codex-plugin").mkdir(parents=True)
            plugin_data.mkdir()
            path_candidate.parent.mkdir()
            verified_binary.parent.mkdir()
            path_candidate.write_text("untrusted", encoding="utf-8")
            verified_binary.write_text("verified", encoding="utf-8")
            (plugin_root / ".codex-plugin" / "plugin.json").write_text(
                json.dumps({"version": "0.1.0"}),
                encoding="utf-8",
            )
            (plugin_root / ".mcp.json").write_text(
                json.dumps({"mcpServers": {"obstudio": {"type": "http", "url": "http://127.0.0.1:3000/mcp"}}}),
                encoding="utf-8",
            )

            with (
                mock.patch.object(BOOTSTRAP, "resolve_plugin_root", return_value=plugin_root),
                mock.patch.object(BOOTSTRAP, "resolve_plugin_data", return_value=plugin_data),
                mock.patch.object(BOOTSTRAP.Path, "home", return_value=codex_home),
                mock.patch.object(BOOTSTRAP, "resolve_release_artifact", return_value="linux_amd64.zip"),
                mock.patch.object(
                    BOOTSTRAP,
                    "load_runtime_manifest",
                    return_value=("0.1.0", "obstudio_0.1.0_linux_amd64.zip", "checksum"),
                ),
                mock.patch.object(BOOTSTRAP.shutil, "which", return_value=str(path_candidate)) as which,
                mock.patch.object(BOOTSTRAP.subprocess, "run") as run,
                mock.patch.object(BOOTSTRAP, "download_obstudio", return_value=verified_binary) as download_obstudio,
                mock.patch.object(BOOTSTRAP, "fetch_obstudio_health", return_value=None),
                mock.patch.object(BOOTSTRAP, "is_tcp_port_open", return_value=False),
                mock.patch.object(
                    BOOTSTRAP,
                    "start_obstudio_background",
                    return_value=(FakeProcess(), plugin_data / "logs" / "obstudio.log"),
                ) as start_obstudio_background,
                mock.patch.object(
                    BOOTSTRAP,
                    "verify_local_obstudio_health",
                    return_value={
                        "kind": "obstudio",
                        "apiVersion": "v1",
                        "owner": "codex-plugin",
                        "mode": "managed",
                        "version": "0.1.0",
                    },
                ),
                mock.patch.object(BOOTSTRAP, "emit_context"),
            ):
                self.assertEqual(BOOTSTRAP.main(), 0)

            which.assert_not_called()
            run.assert_not_called()
            download_obstudio.assert_called_once_with(
                plugin_data,
                "linux_amd64.zip",
                "obstudio_0.1.0_linux_amd64.zip",
                "checksum",
                "0.1.0",
            )
            start_obstudio_background.assert_called_once_with(
                verified_binary, plugin_data, "http://127.0.0.1:3000/api/health"
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["obstudioBinary"], str(verified_binary))

    def test_unusable_plugin_mcp_url_falls_back_to_default_port_17900(self):
        # With no usable obstudio URL in the plugin MCP config, the hook falls
        # back to the built-in default health URL; the managed observer it
        # starts must bind the fixed default port, never the retired :3000.
        self.assertEqual(BOOTSTRAP.OBSTUDIO_HEALTH_URL, "http://127.0.0.1:17900/api/health")
        captured = {}

        class FakeProcess:
            pid = 3333

            def poll(self):
                return None

        def fake_popen(command, **kwargs):
            captured["env"] = kwargs["env"]
            return FakeProcess()

        unusable_mcp_configs = {
            "missing": None,
            "invalid-json": "{",
            "no-obstudio-server": json.dumps({"mcpServers": {}}),
            "blank-url": json.dumps({"mcpServers": {"obstudio": {"type": "http", "url": "  "}}}),
        }
        for label, mcp_text in unusable_mcp_configs.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as tempdir:
                captured.clear()
                tempdir_path = Path(tempdir)
                plugin_root = tempdir_path / "plugin"
                plugin_data = tempdir_path / "data"
                codex_home = tempdir_path / "home"
                verified_binary = tempdir_path / "verified" / "obstudio"
                (plugin_root / ".codex-plugin").mkdir(parents=True)
                plugin_data.mkdir()
                verified_binary.parent.mkdir()
                verified_binary.write_text("verified", encoding="utf-8")
                (plugin_root / ".codex-plugin" / "plugin.json").write_text(
                    json.dumps({"version": "0.1.0"}),
                    encoding="utf-8",
                )
                if mcp_text is not None:
                    (plugin_root / ".mcp.json").write_text(mcp_text, encoding="utf-8")

                with (
                    mock.patch.object(BOOTSTRAP, "resolve_plugin_root", return_value=plugin_root),
                    mock.patch.object(BOOTSTRAP, "resolve_plugin_data", return_value=plugin_data),
                    mock.patch.object(BOOTSTRAP.Path, "home", return_value=codex_home),
                    mock.patch.object(BOOTSTRAP, "resolve_release_artifact", return_value="linux_amd64.zip"),
                    mock.patch.object(
                        BOOTSTRAP,
                        "load_runtime_manifest",
                        return_value=("0.1.0", "obstudio_0.1.0_linux_amd64.zip", "checksum"),
                    ),
                    mock.patch.object(BOOTSTRAP.subprocess, "run"),
                    mock.patch.object(BOOTSTRAP.subprocess, "Popen", side_effect=fake_popen),
                    mock.patch.object(BOOTSTRAP, "download_obstudio", return_value=verified_binary),
                    mock.patch.object(BOOTSTRAP, "fetch_obstudio_health", return_value=None),
                    mock.patch.object(BOOTSTRAP, "is_tcp_port_open", return_value=False),
                    mock.patch.object(
                        BOOTSTRAP,
                        "verify_local_obstudio_health",
                        return_value={
                            "kind": "obstudio",
                            "apiVersion": "v1",
                            "owner": "codex-plugin",
                            "mode": "managed",
                            "version": "0.1.0",
                        },
                    ),
                    mock.patch.object(BOOTSTRAP, "emit_context"),
                ):
                    self.assertEqual(BOOTSTRAP.main(), 0)

                self.assertEqual(captured["env"]["OBSTUDIO_PORT"], "17900")


class ConfigureCodexMCPURLTest(unittest.TestCase):
    def test_replaces_command_config_with_url_config(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config_path = Path(tempdir) / ".codex" / "config.toml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                "\n".join(
                    [
                        'model = "gpt-5.4"',
                        "",
                        BOOTSTRAP.CODEX_MANAGED_BLOCK,
                        "[mcp_servers.obstudio]",
                        "enabled = true",
                        'command = "/tmp/obstudio"',
                        "args = []",
                        BOOTSTRAP.CODEX_MANAGED_BLOCK.replace("# BEGIN", "# END"),
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            BOOTSTRAP.configure_codex_mcp_url(config_path, "http://127.0.0.1:3000/mcp")

            got = config_path.read_text(encoding="utf-8")
            self.assertFalse(BOOTSTRAP.codex_config_requests_local_obstudio(config_path))

        self.assertIn('model = "gpt-5.4"', got)
        self.assertIn('url = "http://127.0.0.1:3000/mcp"', got)
        self.assertNotIn("command =", got)


class StartObstudioBackgroundTest(unittest.TestCase):
    def test_sets_managed_owner_environment(self):
        captured = {}

        class FakeProcess:
            pid = 1234

        def fake_popen(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            return FakeProcess()

        with tempfile.TemporaryDirectory() as tempdir:
            binary = Path(tempdir) / "obstudio"
            binary.write_text("binary", encoding="utf-8")
            with (
                mock.patch.dict(
                    BOOTSTRAP.os.environ,
                    {
                        "HOST": "0.0.0.0",
                        "PORT": "9999",
                        "OBSTUDIO_PORT": "9999",
                        "OTLP_PORT": "9998",
                        "OTLP_HTTP_PORT": "9997",
                        "OTLP_GRPC_PORT": "9996",
                        "ANTHROPIC_API_KEY": "sk-ant-secret",
                        "AWS_SECRET_ACCESS_KEY": "aws-secret",
                        "GITHUB_TOKEN": "ghp_secret",
                        "SPLUNK_REALM": "us0",
                    },
                ),
                mock.patch.object(BOOTSTRAP.subprocess, "Popen", side_effect=fake_popen),
            ):
                process, log_path = BOOTSTRAP.start_obstudio_background(
                    binary,
                    Path(tempdir),
                    "http://127.0.0.1:17900/api/health",
                )

        self.assertEqual(process.pid, 1234)
        self.assertEqual(captured["command"], [str(binary)])
        self.assertEqual(captured["kwargs"]["env"]["HOST"], "127.0.0.1")
        # Binary reads only OBSTUDIO_PORT; it is derived from the health URL the
        # caller passed (not the dead bare PORT), and an inherited OBSTUDIO_PORT
        # is scrubbed first so it cannot leak.
        self.assertEqual(captured["kwargs"]["env"]["OBSTUDIO_PORT"], "17900")
        self.assertNotIn("PORT", captured["kwargs"]["env"])
        self.assertNotIn("OTLP_PORT", captured["kwargs"]["env"])
        self.assertEqual(captured["kwargs"]["env"]["OTLP_HTTP_PORT"], "4318")
        self.assertEqual(captured["kwargs"]["env"]["OTLP_GRPC_PORT"], "4317")
        self.assertEqual(captured["kwargs"]["env"]["OBSTUDIO_OWNER"], "codex-plugin")
        self.assertEqual(captured["kwargs"]["env"]["OBSTUDIO_MODE"], "managed")
        self.assertEqual(captured["kwargs"]["env"]["SPLUNK_REALM"], "us0")
        for name in ("ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN"):
            self.assertNotIn(name, captured["kwargs"]["env"])
        self.assertEqual(log_path.name, "obstudio.log")

    def test_child_env_excludes_unrelated_credentials(self):
        parent_env = {
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "HTTPS_PROXY": "http://proxy.example:8080",
            "LC_ALL": "C",
            "SPLUNK_ACCESS_TOKEN": "splunk-token",
            "WEAVER_PATH": "/opt/weaver/bin/weaver",
            "MAX_FLOW_NODE_SPAN_LIST_SIZE": "5000",
            "ANTHROPIC_API_KEY": "sk-ant-secret",
            "AWS_SECRET_ACCESS_KEY": "aws-secret",
            "OPENAI_API_KEY": "sk-openai-secret",
            "GITHUB_TOKEN": "ghp_secret",
        }

        child_env = BOOTSTRAP.build_child_env(parent_env)

        self.assertEqual(child_env["PATH"], "/usr/bin")
        self.assertEqual(child_env["HOME"], "/home/user")
        self.assertEqual(child_env["HTTPS_PROXY"], "http://proxy.example:8080")
        self.assertEqual(child_env["LC_ALL"], "C")
        self.assertEqual(child_env["SPLUNK_ACCESS_TOKEN"], "splunk-token")
        self.assertEqual(child_env["WEAVER_PATH"], "/opt/weaver/bin/weaver")
        self.assertEqual(child_env["MAX_FLOW_NODE_SPAN_LIST_SIZE"], "5000")
        for name in ("ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY", "OPENAI_API_KEY", "GITHUB_TOKEN"):
            self.assertNotIn(name, child_env)


class MainOwnershipFlowTest(unittest.TestCase):
    def test_prior_managed_state_survives_legacy_command_config(self):
        with tempfile.TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            plugin_root = tempdir_path / "plugin"
            plugin_data = tempdir_path / "data"
            codex_home = tempdir_path / "home"
            config_path = codex_home / ".codex" / "config.toml"
            skills_path = codex_home / ".codex" / "skills" / "obstudio"
            binary = tempdir_path / "obstudio"
            state_path = plugin_data / BOOTSTRAP.BOOTSTRAP_STATE_FILE
            (plugin_root / ".codex-plugin").mkdir(parents=True)
            plugin_data.mkdir()
            skills_path.mkdir(parents=True)
            binary.write_text("binary", encoding="utf-8")
            (plugin_root / ".codex-plugin" / "plugin.json").write_text(
                json.dumps({"version": "0.1.0"}),
                encoding="utf-8",
            )
            config_path.write_text(
                "\n".join(
                    [
                        BOOTSTRAP.CODEX_MANAGED_BLOCK,
                        "[mcp_servers.obstudio]",
                        "enabled = true",
                        'command = "/tmp/obstudio"',
                        BOOTSTRAP.CODEX_MANAGED_BLOCK.replace("# BEGIN", "# END"),
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            state_path.write_text(
                json.dumps({"pluginVersion": "0.0.9", "owner": "codex-plugin", "mode": "managed", "pid": "4321"}),
                encoding="utf-8",
            )

            with (
                mock.patch.object(BOOTSTRAP, "resolve_plugin_root", return_value=plugin_root),
                mock.patch.object(BOOTSTRAP, "resolve_plugin_data", return_value=plugin_data),
                mock.patch.object(BOOTSTRAP.Path, "home", return_value=codex_home),
                mock.patch.object(BOOTSTRAP, "resolve_release_artifact", return_value="linux_amd64.zip"),
                mock.patch.object(BOOTSTRAP, "load_runtime_manifest", return_value=("0.1.0", "obstudio_0.1.0_linux_amd64.zip", "checksum")),
                mock.patch.object(BOOTSTRAP, "download_obstudio", return_value=binary),
                mock.patch.object(
                    BOOTSTRAP,
                    "fetch_obstudio_health",
                    return_value={
                        "kind": "obstudio",
                        "apiVersion": "v1",
                        "owner": "codex-plugin",
                        "mode": "managed",
                        "version": "0.1.0",
                    },
                ),
                mock.patch.object(BOOTSTRAP, "find_pid_listening_on_url", return_value="4321"),
                mock.patch.object(BOOTSTRAP, "emit_context"),
            ):
                self.assertEqual(BOOTSTRAP.main(), 0)

            state = json.loads(state_path.read_text(encoding="utf-8"))
            config = config_path.read_text(encoding="utf-8")
        self.assertEqual(state["owner"], "codex-plugin")
        self.assertEqual(state["mode"], "managed")
        self.assertIn('command = "/tmp/obstudio"', config)

    def test_stale_managed_observer_is_restarted_before_new_state_is_written(self):
        class FakeProcess:
            pid = 5555

            def poll(self):
                return None

        with tempfile.TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            plugin_root = tempdir_path / "plugin"
            plugin_data = tempdir_path / "data"
            codex_home = tempdir_path / "home"
            config_path = codex_home / ".codex" / "config.toml"
            skills_path = codex_home / ".codex" / "skills" / "obstudio"
            binary = tempdir_path / "obstudio"
            state_path = plugin_data / BOOTSTRAP.BOOTSTRAP_STATE_FILE
            (plugin_root / ".codex-plugin").mkdir(parents=True)
            plugin_data.mkdir()
            skills_path.mkdir(parents=True)
            binary.write_text("binary", encoding="utf-8")
            (plugin_root / ".codex-plugin" / "plugin.json").write_text(
                json.dumps({"version": "0.2.0"}),
                encoding="utf-8",
            )
            config_path.write_text(
                "\n".join(
                    [
                        BOOTSTRAP.CODEX_MANAGED_BLOCK,
                        "[mcp_servers.obstudio]",
                        "enabled = true",
                        'url = "http://127.0.0.1:17900/mcp"',
                        BOOTSTRAP.CODEX_MANAGED_BLOCK.replace("# BEGIN", "# END"),
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            state_path.write_text(
                json.dumps(
                    {
                        "pluginVersion": "0.1.0",
                        "releaseVersion": "0.1.0",
                        "owner": "codex-plugin",
                        "mode": "managed",
                        "pid": "4321",
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.object(BOOTSTRAP, "resolve_plugin_root", return_value=plugin_root),
                mock.patch.object(BOOTSTRAP, "resolve_plugin_data", return_value=plugin_data),
                mock.patch.object(BOOTSTRAP.Path, "home", return_value=codex_home),
                mock.patch.object(BOOTSTRAP, "resolve_release_artifact", return_value="linux_amd64.zip"),
                mock.patch.object(
                    BOOTSTRAP,
                    "load_runtime_manifest",
                    return_value=("0.2.0", "obstudio_0.2.0_linux_amd64.zip", "checksum"),
                ),
                mock.patch.object(BOOTSTRAP, "download_obstudio", return_value=binary),
                mock.patch.object(
                    BOOTSTRAP,
                    "fetch_obstudio_health",
                    return_value={
                        "kind": "obstudio",
                        "apiVersion": "v1",
                        "owner": "codex-plugin",
                        "mode": "managed",
                        "version": "0.1.0",
                    },
                ),
                mock.patch.object(BOOTSTRAP, "find_pid_listening_on_url", return_value="4321"),
                mock.patch.object(BOOTSTRAP, "terminate_managed_process") as terminate_managed_process,
                mock.patch.object(
                    BOOTSTRAP,
                    "start_obstudio_background",
                    return_value=(FakeProcess(), plugin_data / "logs" / "obstudio.log"),
                ) as start_obstudio_background,
                mock.patch.object(
                    BOOTSTRAP,
                    "verify_local_obstudio_health",
                    return_value={
                        "kind": "obstudio",
                        "apiVersion": "v1",
                        "owner": "codex-plugin",
                        "mode": "managed",
                        "version": "0.2.0",
                    },
                ),
                mock.patch.object(BOOTSTRAP, "emit_context"),
            ):
                self.assertEqual(BOOTSTRAP.main(), 0)

            terminate_managed_process.assert_called_once_with("4321", "http://127.0.0.1:17900/api/health")
            start_obstudio_background.assert_called_once_with(
                binary, plugin_data, "http://127.0.0.1:17900/api/health"
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["pluginVersion"], "0.2.0")
        self.assertEqual(state["releaseVersion"], "0.2.0")
        self.assertEqual(state["owner"], "codex-plugin")
        self.assertEqual(state["mode"], "managed")
        self.assertEqual(state["pid"], "5555")

    def test_prior_managed_observer_on_old_port_is_retired_before_new_start(self):
        # Port-cutover upgrade: prior plugin-managed observer is still healthy on
        # the OLD port (:3000, saved in bootstrap-state) while the new plugin
        # targets :17900. The hook must retire the owned old-port observer to free
        # the shared OTLP ports before starting the new one.
        class FakeProcess:
            pid = 6060

            def poll(self):
                return None

        def fake_health(url):
            if url == "http://127.0.0.1:3000/api/health":
                return {
                    "kind": "obstudio",
                    "apiVersion": "v1",
                    "owner": "codex-plugin",
                    "mode": "managed",
                    "version": "0.1.0",
                }
            return None

        def fake_pid(url):
            return "4321" if url == "http://127.0.0.1:3000/api/health" else ""

        with tempfile.TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            plugin_root = tempdir_path / "plugin"
            plugin_data = tempdir_path / "data"
            codex_home = tempdir_path / "home"
            config_path = codex_home / ".codex" / "config.toml"
            binary = tempdir_path / "obstudio"
            state_path = plugin_data / BOOTSTRAP.BOOTSTRAP_STATE_FILE
            (plugin_root / ".codex-plugin").mkdir(parents=True)
            plugin_data.mkdir()
            config_path.parent.mkdir(parents=True)
            binary.write_text("binary", encoding="utf-8")
            (plugin_root / ".codex-plugin" / "plugin.json").write_text(
                json.dumps({"version": "0.2.0"}),
                encoding="utf-8",
            )
            (plugin_root / ".mcp.json").write_text(
                json.dumps(
                    {"mcpServers": {"obstudio": {"type": "http", "url": "http://127.0.0.1:17900/mcp"}}}
                ),
                encoding="utf-8",
            )
            config_path.write_text(
                "\n".join(
                    [
                        BOOTSTRAP.CODEX_MANAGED_BLOCK,
                        "[mcp_servers.obstudio]",
                        "enabled = true",
                        'url = "http://127.0.0.1:17900/mcp"',
                        BOOTSTRAP.CODEX_MANAGED_BLOCK.replace("# BEGIN", "# END"),
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            state_path.write_text(
                json.dumps(
                    {
                        "pluginVersion": "0.1.0",
                        "releaseVersion": "0.1.0",
                        "owner": "codex-plugin",
                        "mode": "managed",
                        "pid": "4321",
                        "healthUrl": "http://127.0.0.1:3000/api/health",
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.object(BOOTSTRAP, "resolve_plugin_root", return_value=plugin_root),
                mock.patch.object(BOOTSTRAP, "resolve_plugin_data", return_value=plugin_data),
                mock.patch.object(BOOTSTRAP.Path, "home", return_value=codex_home),
                mock.patch.object(BOOTSTRAP, "resolve_release_artifact", return_value="linux_amd64.zip"),
                mock.patch.object(
                    BOOTSTRAP,
                    "load_runtime_manifest",
                    return_value=("0.2.0", "obstudio_0.2.0_linux_amd64.zip", "checksum"),
                ),
                mock.patch.object(BOOTSTRAP, "download_obstudio", return_value=binary),
                mock.patch.object(BOOTSTRAP, "fetch_obstudio_health", side_effect=fake_health),
                mock.patch.object(BOOTSTRAP, "find_pid_listening_on_url", side_effect=fake_pid),
                mock.patch.object(BOOTSTRAP, "terminate_managed_process") as terminate_managed_process,
                mock.patch.object(BOOTSTRAP, "is_tcp_port_open", return_value=False),
                mock.patch.object(
                    BOOTSTRAP,
                    "start_obstudio_background",
                    return_value=(FakeProcess(), plugin_data / "logs" / "obstudio.log"),
                ) as start_obstudio_background,
                mock.patch.object(
                    BOOTSTRAP,
                    "verify_local_obstudio_health",
                    return_value={
                        "kind": "obstudio",
                        "apiVersion": "v1",
                        "owner": "codex-plugin",
                        "mode": "managed",
                        "version": "0.2.0",
                    },
                ),
                mock.patch.object(BOOTSTRAP, "emit_context"),
            ):
                self.assertEqual(BOOTSTRAP.main(), 0)

            # Old :3000 observer retired first, new observer started on :17900.
            terminate_managed_process.assert_called_once_with("4321", "http://127.0.0.1:3000/api/health")
            start_obstudio_background.assert_called_once_with(
                binary, plugin_data, "http://127.0.0.1:17900/api/health"
            )

    def test_foreign_observer_on_old_port_raises_actionable_error(self):
        # Port-cutover upgrade where the old-port observer is NOT ours (foreign
        # owner). We must not kill it; instead fail with an actionable message
        # naming the owner, pid, and endpoint — not the generic health failure.
        import contextlib
        import io

        def fake_health(url):
            if url == "http://127.0.0.1:3000/api/health":
                return {
                    "kind": "obstudio",
                    "apiVersion": "v1",
                    "owner": "vscode-extension",
                    "mode": "managed",
                    "version": "0.1.0",
                }
            return None

        def fake_pid(url):
            return "7777" if url == "http://127.0.0.1:3000/api/health" else ""

        with tempfile.TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            plugin_root = tempdir_path / "plugin"
            plugin_data = tempdir_path / "data"
            codex_home = tempdir_path / "home"
            config_path = codex_home / ".codex" / "config.toml"
            binary = tempdir_path / "obstudio"
            state_path = plugin_data / BOOTSTRAP.BOOTSTRAP_STATE_FILE
            (plugin_root / ".codex-plugin").mkdir(parents=True)
            plugin_data.mkdir()
            config_path.parent.mkdir(parents=True)
            binary.write_text("binary", encoding="utf-8")
            (plugin_root / ".codex-plugin" / "plugin.json").write_text(
                json.dumps({"version": "0.2.0"}),
                encoding="utf-8",
            )
            (plugin_root / ".mcp.json").write_text(
                json.dumps(
                    {"mcpServers": {"obstudio": {"type": "http", "url": "http://127.0.0.1:17900/mcp"}}}
                ),
                encoding="utf-8",
            )
            config_path.write_text(
                "\n".join(
                    [
                        BOOTSTRAP.CODEX_MANAGED_BLOCK,
                        "[mcp_servers.obstudio]",
                        "enabled = true",
                        'url = "http://127.0.0.1:17900/mcp"',
                        BOOTSTRAP.CODEX_MANAGED_BLOCK.replace("# BEGIN", "# END"),
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            state_path.write_text(
                json.dumps(
                    {
                        "pluginVersion": "0.1.0",
                        "releaseVersion": "0.1.0",
                        "owner": "codex-plugin",
                        "mode": "managed",
                        "pid": "4321",
                        "healthUrl": "http://127.0.0.1:3000/api/health",
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.object(BOOTSTRAP, "resolve_plugin_root", return_value=plugin_root),
                mock.patch.object(BOOTSTRAP, "resolve_plugin_data", return_value=plugin_data),
                mock.patch.object(BOOTSTRAP.Path, "home", return_value=codex_home),
                mock.patch.object(BOOTSTRAP, "resolve_release_artifact", return_value="linux_amd64.zip"),
                mock.patch.object(
                    BOOTSTRAP,
                    "load_runtime_manifest",
                    return_value=("0.2.0", "obstudio_0.2.0_linux_amd64.zip", "checksum"),
                ),
                mock.patch.object(BOOTSTRAP, "download_obstudio", return_value=binary),
                mock.patch.object(BOOTSTRAP, "fetch_obstudio_health", side_effect=fake_health),
                mock.patch.object(BOOTSTRAP, "find_pid_listening_on_url", side_effect=fake_pid),
                mock.patch.object(BOOTSTRAP, "terminate_managed_process") as terminate_managed_process,
                mock.patch.object(BOOTSTRAP, "is_tcp_port_open", return_value=False),
                mock.patch.object(BOOTSTRAP, "start_obstudio_background") as start_obstudio_background,
                mock.patch.object(BOOTSTRAP, "emit_error"),
                mock.patch.object(BOOTSTRAP, "emit_context"),
            ):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    self.assertEqual(BOOTSTRAP.main(), 2)

            # Foreign observer is NOT retired, and no new observer is spawned.
            terminate_managed_process.assert_not_called()
            start_obstudio_background.assert_not_called()
            message = stderr.getvalue()
            self.assertIn("vscode-extension", message)
            self.assertIn("7777", message)
            self.assertIn("http://127.0.0.1:3000/api/health", message)


class ParseObstudioVersionTest(unittest.TestCase):
    def test_extracts_version_from_parenthesized_output(self):
        stdout = "obstudio version 1.2.3 (build abc)\n"
        stderr = ""
        self.assertEqual(BOOTSTRAP.parse_obstudio_version(stdout, stderr), "1.2.3")

    def test_extracts_version_from_forked_semver(self):
        stdout = "obstudio version 0.0.11-fork3\n"
        stderr = ""
        self.assertEqual(BOOTSTRAP.parse_obstudio_version(stdout, stderr), "0.0.11-fork3")


if __name__ == "__main__":
    unittest.main()
