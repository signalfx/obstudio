import importlib.util
import io
import json
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


class DummyProcess:
    def __init__(self, poll_result):
        self._poll_result = poll_result

    def poll(self):
        return self._poll_result


class ResolveReleaseVersionTest(unittest.TestCase):
    def test_parses_version_from_release_artifact_name(self):
        got = BOOTSTRAP.resolve_release_version("obstudio_0.0.14_linux_amd64.zip", "linux_amd64.zip")
        self.assertEqual(got, "0.0.14")

    def test_rejects_artifacts_without_expected_suffix(self):
        with self.assertRaisesRegex(RuntimeError, "could not parse release version"):
            BOOTSTRAP.resolve_release_version("obstudio_0.0.14_windows_amd64.zip", "linux_amd64.zip")

    def test_resolve_latest_release_version_uses_latest_tag(self):
        class FakeResponse(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        payload = json.dumps({"tag_name": "v0.0.14"}).encode("utf-8")
        with mock.patch.object(
            BOOTSTRAP.urllib.request,
            "urlopen",
            return_value=FakeResponse(payload),
        ):
            got = BOOTSTRAP.resolve_latest_release_version()
        self.assertEqual(got, "0.0.14")


class ParseChecksumTest(unittest.TestCase):
    def test_matches_exact_release_artifact_name(self):
        checksums_text = (
            "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef *evil/linux_amd64.zip\n"
            "feedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedface *obstudio_0.0.14_linux_amd64.zip\n"
        )

        name, checksum = BOOTSTRAP.parse_checksum(checksums_text, "linux_amd64.zip")
        self.assertEqual(name, "obstudio_0.0.14_linux_amd64.zip")
        self.assertEqual(
            checksum,
            "feedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedface",
        )

    def test_matches_release_artifact_with_prerelease_and_build_metadata(self):
        checksums_text = (
            "feedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedface "
            "*obstudio_1.2.3-rc.1+build.2_linux_amd64.zip\n"
        )

        name, checksum = BOOTSTRAP.parse_checksum(checksums_text, "linux_amd64.zip")
        self.assertEqual(name, "obstudio_1.2.3-rc.1+build.2_linux_amd64.zip")
        self.assertEqual(
            checksum,
            "feedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedface",
        )


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


class FetchExpectedChecksumTest(unittest.TestCase):
    def test_falls_back_to_versioned_checksum_manifest(self):
        class FakeResponse(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def fake_urlopen(url, timeout=0):
            if url.endswith("/checksums.txt"):
                raise RuntimeError("stable checksum alias missing")
            if url.endswith("/releases/latest"):
                return FakeResponse(json.dumps({"tag_name": "v0.0.14"}).encode("utf-8"))
            if url.endswith("/obstudio_0.0.14_checksums.txt"):
                return FakeResponse(
                    b"deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef *obstudio_0.0.14_linux_amd64.zip\n"
                )
            raise AssertionError(f"unexpected URL: {url}")

        with tempfile.TemporaryDirectory() as tempdir:
            checksums_path = Path(tempdir) / "checksums.txt"
            with mock.patch.object(BOOTSTRAP.urllib.request, "urlopen", side_effect=fake_urlopen):
                name, checksum = BOOTSTRAP.fetch_expected_checksum("linux_amd64.zip", checksums_path)

        self.assertEqual(name, "obstudio_0.0.14_linux_amd64.zip")
        self.assertEqual(checksum, "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef")

    def test_creates_checksum_cache_parent_before_writing(self):
        class FakeResponse(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        checksums_text = (
            b"deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef *obstudio_0.0.14_linux_amd64.zip\n"
        )
        with tempfile.TemporaryDirectory() as tempdir:
            checksums_path = Path(tempdir) / "missing" / "checksums.txt"
            with mock.patch.object(BOOTSTRAP.urllib.request, "urlopen", return_value=FakeResponse(checksums_text)):
                BOOTSTRAP.fetch_expected_checksum("linux_amd64.zip", checksums_path)

            self.assertTrue(checksums_path.is_file())
            self.assertTrue(BOOTSTRAP.versioned_checksum_cache_path(checksums_path, "0.0.14").is_file())

    def test_prefers_exact_versioned_cache_after_resolving_latest(self):
        class FakeResponse(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        with tempfile.TemporaryDirectory() as tempdir:
            checksums_path = Path(tempdir) / "checksums.txt"
            BOOTSTRAP.versioned_checksum_cache_path(checksums_path, "0.0.13").write_text(
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa *obstudio_0.0.13_linux_amd64.zip\n",
                encoding="utf-8",
            )
            BOOTSTRAP.versioned_checksum_cache_path(checksums_path, "0.0.14").write_text(
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb *obstudio_0.0.14_linux_amd64.zip\n",
                encoding="utf-8",
            )

            def fake_urlopen(url, timeout=0):
                if url.endswith("/checksums.txt"):
                    raise RuntimeError("stable checksum alias missing")
                if url.endswith("/releases/latest"):
                    return FakeResponse(json.dumps({"tag_name": "v0.0.14"}).encode("utf-8"))
                raise AssertionError(f"unexpected URL: {url}")

            with mock.patch.object(BOOTSTRAP.urllib.request, "urlopen", side_effect=fake_urlopen):
                name, checksum = BOOTSTRAP.fetch_expected_checksum("linux_amd64.zip", checksums_path)

        self.assertEqual(name, "obstudio_0.0.14_linux_amd64.zip")
        self.assertEqual(checksum, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")

    def test_fully_offline_cache_fallback_uses_semver_order(self):
        with tempfile.TemporaryDirectory() as tempdir:
            checksums_path = Path(tempdir) / "checksums.txt"
            BOOTSTRAP.versioned_checksum_cache_path(checksums_path, "0.0.8").write_text(
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa *obstudio_0.0.8_linux_amd64.zip\n",
                encoding="utf-8",
            )
            BOOTSTRAP.versioned_checksum_cache_path(checksums_path, "0.0.9").write_text(
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb *obstudio_0.0.9_linux_amd64.zip\n",
                encoding="utf-8",
            )

            def fake_urlopen(url, timeout=0):
                raise RuntimeError(f"network unavailable: {url}")

            with mock.patch.object(BOOTSTRAP.urllib.request, "urlopen", side_effect=fake_urlopen):
                name, checksum = BOOTSTRAP.fetch_expected_checksum("linux_amd64.zip", checksums_path)

        self.assertEqual(name, "obstudio_0.0.9_linux_amd64.zip")
        self.assertEqual(checksum, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")

    def test_fully_offline_cache_fallback_reads_plain_checksum_cache(self):
        with tempfile.TemporaryDirectory() as tempdir:
            checksums_path = Path(tempdir) / "checksums.txt"
            checksums_path.write_text(
                "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc *obstudio_0.0.14_linux_amd64.zip\n",
                encoding="utf-8",
            )

            def fake_urlopen(url, timeout=0):
                raise RuntimeError(f"network unavailable: {url}")

            with mock.patch.object(BOOTSTRAP.urllib.request, "urlopen", side_effect=fake_urlopen):
                name, checksum = BOOTSTRAP.fetch_expected_checksum("linux_amd64.zip", checksums_path)

        self.assertEqual(name, "obstudio_0.0.14_linux_amd64.zip")
        self.assertEqual(checksum, "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc")

    def test_fully_offline_cache_fallback_sorts_prerelease_numbers(self):
        with tempfile.TemporaryDirectory() as tempdir:
            checksums_path = Path(tempdir) / "checksums.txt"
            BOOTSTRAP.versioned_checksum_cache_path(checksums_path, "0.0.11-fork9").write_text(
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa *obstudio_0.0.11-fork9_linux_amd64.zip\n",
                encoding="utf-8",
            )
            BOOTSTRAP.versioned_checksum_cache_path(checksums_path, "0.0.11-fork10").write_text(
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb *obstudio_0.0.11-fork10_linux_amd64.zip\n",
                encoding="utf-8",
            )

            def fake_urlopen(url, timeout=0):
                raise RuntimeError(f"network unavailable: {url}")

            with mock.patch.object(BOOTSTRAP.urllib.request, "urlopen", side_effect=fake_urlopen):
                name, checksum = BOOTSTRAP.fetch_expected_checksum("linux_amd64.zip", checksums_path)

        self.assertEqual(name, "obstudio_0.0.11-fork10_linux_amd64.zip")
        self.assertEqual(checksum, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")

    def test_semver_sort_ignores_build_metadata(self):
        self.assertEqual(
            BOOTSTRAP.semver_sort_key("0.0.11-fork10+build2"),
            BOOTSTRAP.semver_sort_key("0.0.11-fork10+build1"),
        )

    def test_uses_versioned_checksum_cache_when_stable_alias_is_missing(self):
        with tempfile.TemporaryDirectory() as tempdir:
            checksums_path = Path(tempdir) / "checksums.txt"
            versioned_cache = BOOTSTRAP.versioned_checksum_cache_path(checksums_path, "0.0.14")
            checksums_path.write_text(
                "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff *obstudio_0.0.13_linux_amd64.zip\n",
                encoding="utf-8",
            )
            versioned_cache.write_text(
                "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef *obstudio_0.0.14_linux_amd64.zip\n",
                encoding="utf-8",
            )

            def fake_urlopen(url, timeout=0):
                raise RuntimeError(f"network unavailable: {url}")

            with mock.patch.object(BOOTSTRAP.urllib.request, "urlopen", side_effect=fake_urlopen):
                name, checksum = BOOTSTRAP.fetch_expected_checksum("linux_amd64.zip", checksums_path)

        self.assertEqual(name, "obstudio_0.0.14_linux_amd64.zip")
        self.assertEqual(checksum, "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef")


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
                        'url = "http://127.0.0.1:3000/mcp"',
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
                        'url = "http://127.0.0.1:3000/mcp"',
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
                        'url = "http://127.0.0.1:3000/mcp"',
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
                mock.patch.object(BOOTSTRAP, "run_install") as run_install,
                mock.patch.object(BOOTSTRAP, "emit_context"),
            ):
                self.assertEqual(BOOTSTRAP.main(), 0)

            run_install.assert_not_called()

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
                    "fetch_expected_checksum",
                    return_value=("obstudio_0.2.0_linux_amd64.zip", "checksum"),
                ),
                mock.patch.object(BOOTSTRAP, "locate_existing_obstudio", return_value=binary),
                mock.patch.object(BOOTSTRAP, "run_install") as run_install,
                mock.patch.object(BOOTSTRAP, "start_obstudio_background") as start_obstudio_background,
                mock.patch.object(BOOTSTRAP, "emit_context"),
            ):
                self.assertEqual(BOOTSTRAP.main(), 0)

            run_install.assert_called_once_with(binary)
            start_obstudio_background.assert_not_called()
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["pluginVersion"], "0.2.0")
            self.assertEqual(state["status"], "stopped")
            self.assertEqual(state["owner"], "codex-plugin")


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


class LocateExistingObstudioTest(unittest.TestCase):
    def test_does_not_reuse_installed_destination_binary_as_source(self):
        with tempfile.TemporaryDirectory() as tempdir:
            home = Path(tempdir) / "home"
            installed = home / ".codex" / "skills" / "obstudio" / "obstudio"
            installed.parent.mkdir(parents=True)
            installed.write_text("binary", encoding="utf-8")

            with (
                mock.patch.object(BOOTSTRAP.Path, "home", return_value=home),
                mock.patch.object(BOOTSTRAP.shutil, "which", return_value=None),
                mock.patch.object(BOOTSTRAP, "existing_binary_matches_release", return_value=True),
            ):
                self.assertIsNone(BOOTSTRAP.locate_existing_obstudio("0.1.0"))


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
            with mock.patch.object(BOOTSTRAP.subprocess, "Popen", side_effect=fake_popen):
                process, log_path = BOOTSTRAP.start_obstudio_background(binary, Path(tempdir))

        self.assertEqual(process.pid, 1234)
        self.assertEqual(captured["command"], [str(binary)])
        self.assertEqual(captured["kwargs"]["env"]["OBSTUDIO_OWNER"], "codex-plugin")
        self.assertEqual(captured["kwargs"]["env"]["OBSTUDIO_MODE"], "managed")
        self.assertEqual(log_path.name, "obstudio.log")


class MainOwnershipFlowTest(unittest.TestCase):
    def test_prior_managed_state_survives_installer_url_detection(self):
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

            def fake_run_install(_binary):
                BOOTSTRAP.configure_codex_mcp_url(config_path, "http://127.0.0.1:3000/mcp")

            with (
                mock.patch.object(BOOTSTRAP, "resolve_plugin_root", return_value=plugin_root),
                mock.patch.object(BOOTSTRAP, "resolve_plugin_data", return_value=plugin_data),
                mock.patch.object(BOOTSTRAP.Path, "home", return_value=codex_home),
                mock.patch.object(BOOTSTRAP, "resolve_release_artifact", return_value="linux_amd64.zip"),
                mock.patch.object(BOOTSTRAP, "fetch_expected_checksum", return_value=("obstudio_0.1.0_linux_amd64.zip", "checksum")),
                mock.patch.object(BOOTSTRAP, "locate_existing_obstudio", return_value=binary),
                mock.patch.object(BOOTSTRAP, "run_install", side_effect=fake_run_install),
                mock.patch.object(
                    BOOTSTRAP,
                    "fetch_obstudio_health",
                    return_value={
                        "kind": "obstudio",
                        "apiVersion": "v1",
                        "owner": "codex-plugin",
                        "mode": "managed",
                    },
                ),
                mock.patch.object(BOOTSTRAP, "find_pid_listening_on_url", return_value="4321"),
                mock.patch.object(BOOTSTRAP, "emit_context"),
            ):
                self.assertEqual(BOOTSTRAP.main(), 0)

            state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["owner"], "codex-plugin")
        self.assertEqual(state["mode"], "managed")


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
