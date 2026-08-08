import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


def load_stage_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "stage_obstudio_plugin.py"
    spec = importlib.util.spec_from_file_location("stage_obstudio_plugin", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STAGE = load_stage_module()


class StageObstudioPluginTest(unittest.TestCase):
    def test_stage_materializes_symlinked_skill_trees(self):
        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "obstudio"

            STAGE.stage_plugin(output)

            self.assertTrue((output / ".codex-plugin" / "plugin.json").is_file())
            self.assertTrue((output / "PRIVACY.md").is_file())
            self.assertTrue((output / "SECURITY.md").is_file())
            self.assertTrue((output / "skills" / "otel-instrument" / "SKILL.md").is_file())
            self.assertTrue((output / "skills" / "references" / "report-flow-contract.md").is_file())
            self.assertFalse((output / "skills" / "otel-instrument").is_symlink())
            self.assertFalse(any(path.is_symlink() for path in output.rglob("*")))

    def test_verify_rejects_staged_symlinks(self):
        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "obstudio"
            (output / ".codex-plugin").mkdir(parents=True)
            (output / ".codex-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
            (output / "skills").mkdir()
            (output / "target").write_text("target", encoding="utf-8")
            (output / "skills" / "linked").symlink_to(output / "target")

            with self.assertRaisesRegex(RuntimeError, "must not contain symlinks"):
                STAGE.verify_staged_plugin(output)

    def test_marketplace_installs_from_committed_plugin_tree(self):
        marketplace_path = Path(__file__).resolve().parents[4] / ".agents" / "plugins" / "marketplace.json"
        marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))

        self.assertEqual(
            marketplace["plugins"][0]["source"]["path"],
            "./plugins/obstudio",
        )

    def test_plugin_manifest_uses_committed_skills(self):
        plugin_root = Path(__file__).resolve().parents[2]
        manifest_path = plugin_root / ".codex-plugin" / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        skills_path = plugin_root / manifest["skills"]

        self.assertEqual(manifest["skills"], "./skills/")
        self.assertTrue((skills_path / "otel-instrument" / "SKILL.md").is_file())
        self.assertFalse(any(path.is_symlink() for path in skills_path.rglob("*")))

    def test_committed_plugin_skills_are_synced(self):
        STAGE.verify_plugin_skills_synced()

    def test_archive_orders_skills_by_trust_group(self):
        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "obstudio"
            archive = Path(tempdir) / "obstudio.zip"

            STAGE.stage_plugin(output)
            STAGE.write_archive(output, archive)

            with zipfile.ZipFile(archive) as zf:
                skill_dirs = []
                seen = set()
                for name in zf.namelist():
                    parts = name.split("/")
                    if len(parts) < 3 or parts[0] != "obstudio" or parts[1] != "skills":
                        continue
                    if parts[2] == "observer-control" and len(parts) >= 4:
                        skill = "/".join(parts[2:4])
                    else:
                        skill = parts[2]
                    if skill not in seen:
                        seen.add(skill)
                        skill_dirs.append(skill)

            self.assertEqual(skill_dirs[:14], list(STAGE.PLUGIN_SKILL_ENTRIES[:14]))

    def test_plugin_local_command_skills_are_not_shared(self):
        root = Path(__file__).resolve().parents[4]

        self.assertFalse((root / "skills" / "obstudio-help").exists())
        self.assertFalse((root / "skills" / "observer-control").exists())


if __name__ == "__main__":
    unittest.main()
