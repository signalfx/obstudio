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
            ):
                self.assertEqual(BOOTSTRAP.main(), 2)

        emit_error.assert_called_once_with(
            "Splunk Observability Studio bootstrap could not complete automatically. "
            "The plugin bundle is present, but the managed runtime could not be prepared."
        )


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

    def test_uses_claude_manifest_version_and_owner(self):
        root = Path(__file__).resolve().parents[4]
        prior = os.environ.get("OBSTUDIO_PLUGIN_HOST")
        os.environ["OBSTUDIO_PLUGIN_HOST"] = "claude"
        try:
            self.assertEqual(BOOTSTRAP.plugin_owner(), "claude-plugin")
            self.assertEqual(BOOTSTRAP.plugin_display_name(), "Splunk Observability Studio")
            self.assertEqual(BOOTSTRAP.skill_command("observer-open"), "/obstudio:observer-open")
            self.assertEqual(BOOTSTRAP.read_plugin_version(root / "plugins" / "obstudio"), "0.0.16")
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

    def test_malformed_exact_versioned_cache_falls_back_to_remote_manifest(self):
        class FakeResponse(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        remote_text = (
            b"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd *obstudio_0.0.14_linux_amd64.zip\n"
        )
        with tempfile.TemporaryDirectory() as tempdir:
            checksums_path = Path(tempdir) / "checksums.txt"
            versioned_cache = BOOTSTRAP.versioned_checksum_cache_path(checksums_path, "0.0.14")
            versioned_cache.write_text("truncated\n", encoding="utf-8")

            def fake_urlopen(url, timeout=0):
                if url.endswith("/checksums.txt"):
                    raise RuntimeError("stable checksum alias missing")
                if url.endswith("/releases/latest"):
                    return FakeResponse(json.dumps({"tag_name": "v0.0.14"}).encode("utf-8"))
                if url.endswith("/obstudio_0.0.14_checksums.txt"):
                    return FakeResponse(remote_text)
                raise AssertionError(f"unexpected URL: {url}")

            with mock.patch.object(BOOTSTRAP.urllib.request, "urlopen", side_effect=fake_urlopen):
                name, checksum = BOOTSTRAP.fetch_expected_checksum("linux_amd64.zip", checksums_path)

            self.assertEqual(versioned_cache.read_text(encoding="utf-8"), remote_text.decode("utf-8"))
            self.assertFalse(list(Path(tempdir).glob(".*.tmp-*")))

        self.assertEqual(name, "obstudio_0.0.14_linux_amd64.zip")
        self.assertEqual(checksum, "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd")

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

    def test_write_text_atomic_replaces_with_complete_text(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "checksums.txt"
            path.write_text("old\n", encoding="utf-8")

            BOOTSTRAP.write_text_atomic(path, "new\n")

            self.assertEqual(path.read_text(encoding="utf-8"), "new\n")
            self.assertFalse(list(Path(tempdir).glob(".*.tmp-*")))


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

    def test_managed_state_requires_matching_release_version(self):
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
            state_path.write_text(
                json.dumps(
                    {
                        "pluginVersion": "0.1.0",
                        "releaseVersion": "0.1.0",
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
                "version": "0.0.9",
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
                    "fetch_expected_checksum",
                    return_value=("obstudio_0.2.0_linux_amd64.zip", "checksum"),
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
                mock.patch.object(BOOTSTRAP, "fetch_expected_checksum") as fetch_expected_checksum,
                mock.patch.object(BOOTSTRAP, "start_obstudio_background") as start_obstudio_background,
                mock.patch.object(BOOTSTRAP, "emit_context") as emit_context,
            ):
                self.assertEqual(BOOTSTRAP.main(), 0)

            fetch_expected_checksum.assert_not_called()
            start_obstudio_background.assert_not_called()
            emit_context.assert_called_once_with(
                "Splunk Observability Studio MCP is explicitly disabled in Codex config. The plugin hook "
                "left the managed Observer stopped, did not start or restart the "
                "plugin-managed Observer, and bundled Splunk Observability Studio skills remain available."
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
                mock.patch.object(BOOTSTRAP, "fetch_expected_checksum") as fetch_expected_checksum,
                mock.patch.object(BOOTSTRAP, "start_obstudio_background") as start_obstudio_background,
                mock.patch.object(BOOTSTRAP, "emit_context") as emit_context,
            ):
                self.assertEqual(BOOTSTRAP.main(), 0)

            fetch_expected_checksum.assert_not_called()
            start_obstudio_background.assert_not_called()
            emit_context.assert_called_once_with(
                "Custom Splunk Observability Studio MCP endpoint detected in Codex config. The plugin hook "
                "left the configured endpoint unchanged (http://127.0.0.1:4111/mcp), "
                "did not start or restart the plugin-managed Observer, and bundled "
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
                    "fetch_expected_checksum",
                    return_value=("obstudio_0.1.0_linux_amd64.zip", "checksum"),
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
            )
            start_obstudio_background.assert_called_once_with(verified_binary, plugin_data)
            state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["obstudioBinary"], str(verified_binary))


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
                        "OTLP_PORT": "9998",
                        "OTLP_HTTP_PORT": "9997",
                        "OTLP_GRPC_PORT": "9996",
                    },
                ),
                mock.patch.object(BOOTSTRAP.subprocess, "Popen", side_effect=fake_popen),
            ):
                process, log_path = BOOTSTRAP.start_obstudio_background(binary, Path(tempdir))

        self.assertEqual(process.pid, 1234)
        self.assertEqual(captured["command"], [str(binary)])
        self.assertEqual(captured["kwargs"]["env"]["HOST"], "127.0.0.1")
        self.assertEqual(captured["kwargs"]["env"]["PORT"], "3000")
        self.assertNotIn("OTLP_PORT", captured["kwargs"]["env"])
        self.assertEqual(captured["kwargs"]["env"]["OTLP_HTTP_PORT"], "4318")
        self.assertEqual(captured["kwargs"]["env"]["OTLP_GRPC_PORT"], "4317")
        self.assertEqual(captured["kwargs"]["env"]["OBSTUDIO_OWNER"], "codex-plugin")
        self.assertEqual(captured["kwargs"]["env"]["OBSTUDIO_MODE"], "managed")
        self.assertEqual(log_path.name, "obstudio.log")


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
                mock.patch.object(BOOTSTRAP, "fetch_expected_checksum", return_value=("obstudio_0.1.0_linux_amd64.zip", "checksum")),
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
                        'url = "http://127.0.0.1:3000/mcp"',
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
                    "fetch_expected_checksum",
                    return_value=("obstudio_0.2.0_linux_amd64.zip", "checksum"),
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

            terminate_managed_process.assert_called_once_with("4321", "http://127.0.0.1:3000/api/health")
            start_obstudio_background.assert_called_once_with(binary, plugin_data)
            state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["pluginVersion"], "0.2.0")
        self.assertEqual(state["releaseVersion"], "0.2.0")
        self.assertEqual(state["owner"], "codex-plugin")
        self.assertEqual(state["mode"], "managed")
        self.assertEqual(state["pid"], "5555")


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
