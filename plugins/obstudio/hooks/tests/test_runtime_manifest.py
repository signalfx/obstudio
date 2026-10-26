import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def load_module(name="runtime_manifest"):
    script_path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RM = load_module()
STAGE = load_module("stage_obstudio_plugin")
VERSION = "1.2.3"


def make_hashes(seed: str = "a") -> dict[str, str]:
    return {suffix: seed * 64 for suffix in RM.ARTIFACT_SUFFIXES}


def make_dist(dist: Path, content: bytes = b"zip") -> dict[str, str]:
    dist.mkdir(parents=True, exist_ok=True)
    for suffix in RM.ARTIFACT_SUFFIXES:
        (dist / RM.artifact_name(VERSION, suffix)).write_bytes(content + suffix.encode())
    return RM.hashes_from_dist(dist, VERSION)


class RuntimeManifestTest(unittest.TestCase):
    def test_write_then_read_round_trips(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            path = RM.write_runtime_manifest(root, VERSION, make_hashes())
            manifest = RM.read_runtime_manifest(path)
            self.assertEqual(manifest["version"], VERSION)
            self.assertEqual(set(manifest["artifacts"]), set(RM.ARTIFACT_SUFFIXES))
            self.assertTrue(path.read_text(encoding="utf-8").endswith("}\n"))

    def test_write_is_deterministic(self):
        self.assertEqual(RM.render_manifest(VERSION, make_hashes()), RM.render_manifest(VERSION, make_hashes()))

    def test_read_rejects_invalid_manifests(self):
        good = json.loads(RM.render_manifest(VERSION, make_hashes()))
        broken = {
            "schema": {**good, "schemaVersion": 2},
            "missing suffix": {**good, "artifacts": {k: v for k, v in list(good["artifacts"].items())[1:]}},
            "name mismatch": {
                **good,
                "artifacts": {**good["artifacts"], "linux_amd64.zip": {"name": "evil.zip", "sha256": "a" * 64}},
            },
            "uppercase sha": {
                **good,
                "artifacts": {**good["artifacts"], "linux_amd64.zip": {
                    "name": RM.artifact_name(VERSION, "linux_amd64.zip"), "sha256": "A" * 64}},
            },
            "short sha": {
                **good,
                "artifacts": {**good["artifacts"], "linux_amd64.zip": {
                    "name": RM.artifact_name(VERSION, "linux_amd64.zip"), "sha256": "abc"}},
            },
        }
        for label, manifest in broken.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as tempdir:
                path = Path(tempdir) / "runtime-manifest.json"
                path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    RM.read_runtime_manifest(path)

    def test_read_rejects_missing_and_malformed_files(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "runtime-manifest.json"
            with self.assertRaises(RuntimeError):
                RM.read_runtime_manifest(path)
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                RM.read_runtime_manifest(path)

    def test_check_requires_matching_plugin_version(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            RM.write_runtime_manifest(root, VERSION, make_hashes())
            RM.check_runtime_manifest(root, VERSION)
            with self.assertRaises(RuntimeError):
                RM.check_runtime_manifest(root, "9.9.9")

    def test_hashes_from_checksums_file(self):
        with tempfile.TemporaryDirectory() as tempdir:
            checksums = Path(tempdir) / "checksums.txt"
            lines = [f"{'b' * 64}  {RM.artifact_name(VERSION, s)}" for s in RM.ARTIFACT_SUFFIXES]
            checksums.write_text("\n".join(lines + [f"{'c' * 64}  other.vsix"]) + "\n", encoding="utf-8")
            self.assertEqual(RM.hashes_from_checksums_file(checksums, VERSION), make_hashes("b"))
            checksums.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                RM.hashes_from_checksums_file(checksums, VERSION)

    def test_verify_accepts_matching_dist_and_reports_tampered_hash(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir) / "plugin"
            dist = Path(tempdir) / "dist"
            RM.write_runtime_manifest(root, VERSION, make_dist(dist))
            RM.verify_runtime_manifest(root, VERSION, dist)

            (dist / RM.artifact_name(VERSION, "linux_amd64.zip")).write_bytes(b"tampered")
            with self.assertRaises(RuntimeError) as ctx:
                RM.verify_runtime_manifest(root, VERSION, dist)
            self.assertIn("linux_amd64.zip", str(ctx.exception))
            self.assertNotIn("darwin_arm64.zip", str(ctx.exception))

    def test_verify_rejects_missing_archive_and_version_mismatch(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir) / "plugin"
            dist = Path(tempdir) / "dist"
            RM.write_runtime_manifest(root, VERSION, make_dist(dist))
            with self.assertRaises(RuntimeError):
                RM.verify_runtime_manifest(root, "9.9.9", dist)
            (dist / RM.artifact_name(VERSION, "windows_amd64.zip")).unlink()
            with self.assertRaises(RuntimeError):
                RM.verify_runtime_manifest(root, VERSION, dist)


class CommittedRuntimeManifestTest(unittest.TestCase):
    def test_committed_manifest_is_valid_and_matches_plugin_version(self):
        plugin_root = Path(__file__).resolve().parents[2]
        claude = json.loads((plugin_root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        RM.check_runtime_manifest(plugin_root, claude["version"])


class StagedRuntimeManifestTest(unittest.TestCase):
    def test_stage_plugin_ships_the_runtime_manifest(self):
        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "obstudio"
            STAGE.stage_plugin(output)
            staged = output / "hooks" / "runtime-manifest.json"
            self.assertEqual(
                staged.read_bytes(),
                (STAGE.PLUGIN_ROOT / "hooks" / "runtime-manifest.json").read_bytes(),
            )

    def test_verify_staged_plugin_requires_the_runtime_manifest(self):
        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "obstudio"
            STAGE.stage_plugin(output)
            (output / "hooks" / "runtime-manifest.json").unlink()
            with self.assertRaisesRegex(RuntimeError, "runtime manifest"):
                STAGE.verify_staged_plugin(output)

    def test_check_committed_runtime_manifest_rejects_version_and_tag_mismatch(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plugin_root = Path(tempdir)
            (plugin_root / ".claude-plugin").mkdir()
            (plugin_root / ".claude-plugin" / "plugin.json").write_text('{"version": "1.2.3"}', encoding="utf-8")
            RM.write_runtime_manifest(plugin_root, "1.2.3", make_hashes())
            STAGE.check_committed_runtime_manifest("v1.2.3", plugin_root)
            with self.assertRaises(RuntimeError):
                STAGE.check_committed_runtime_manifest("v1.2.4", plugin_root)
            (plugin_root / ".claude-plugin" / "plugin.json").write_text('{"version": "1.2.4"}', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                STAGE.check_committed_runtime_manifest("", plugin_root)

    def test_cli_write_and_verify_round_trip(self):
        with tempfile.TemporaryDirectory() as tempdir:
            dist = Path(tempdir) / "dist"
            make_dist(dist)
            with mock.patch.object(STAGE, "PLUGIN_ROOT", Path(tempdir) / "plugin"), mock.patch(
                "sys.argv",
                ["stage", "--write-runtime-manifest", "--release-tag", "v1.2.3", "--dist-dir", str(dist)],
            ):
                self.assertEqual(STAGE.main(), 0)
            with mock.patch.object(STAGE, "PLUGIN_ROOT", Path(tempdir) / "plugin"), mock.patch(
                "sys.argv",
                ["stage", "--verify-runtime-manifest", "--release-tag", "v1.2.3", "--dist-dir", str(dist)],
            ):
                self.assertEqual(STAGE.main(), 0)


if __name__ == "__main__":
    unittest.main()
