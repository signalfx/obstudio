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


if __name__ == "__main__":
    unittest.main()
