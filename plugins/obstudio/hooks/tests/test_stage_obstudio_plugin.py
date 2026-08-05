import importlib.util
import json
import tempfile
import unittest
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
            self.assertTrue((output / "skills" / "otel-instrument" / "SKILL.md").is_file())
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

    def test_marketplace_installs_from_staged_plugin_tree(self):
        marketplace_path = Path(__file__).resolve().parents[4] / ".agents" / "plugins" / "marketplace.json"
        marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))

        self.assertEqual(
            marketplace["plugins"][0]["source"]["path"],
            "./.release/plugins/obstudio",
        )


if __name__ == "__main__":
    unittest.main()
