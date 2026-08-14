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
    def test_stage_materializes_unified_plugin(self):
        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "obstudio"

            STAGE.stage_plugin(output)

            self.assertTrue((output / ".codex-plugin" / "plugin.json").is_file())
            self.assertTrue((output / ".claude-plugin" / "plugin.json").is_file())
            self.assertTrue((output / "PRIVACY.md").is_file())
            self.assertTrue((output / "SECURITY.md").is_file())
            self.assertTrue((output / "hooks" / "bootstrap_obstudio.py").is_file())
            self.assertTrue((output / "hooks" / "bootstrap_claude.cjs").is_file())
            self.assertTrue((output / "skills" / "otel-instrument" / "SKILL.md").is_file())
            self.assertTrue((output / "skills" / "references" / "report-flow-contract.md").is_file())
            self.assertFalse((output / "skills" / "otel-instrument").is_symlink())
            self.assertFalse(any(path.is_symlink() for path in output.rglob("*")))

    def test_host_stage_omits_other_host_metadata(self):
        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "obstudio-codex"

            STAGE.stage_plugin(output, host="codex")

            self.assertTrue((output / ".codex-plugin" / "plugin.json").is_file())
            self.assertFalse((output / ".claude-plugin").exists())
            self.assertTrue((output / "hooks" / "codex-hooks.json").is_file())
            self.assertFalse((output / "hooks" / "claude-hooks.json").exists())
            self.assertFalse((output / "hooks" / "bootstrap_claude.cjs").exists())

    def test_claude_stage_preserves_source_manifest_version(self):
        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "obstudio-claude"

            STAGE.stage_plugin(output, host="claude")

            manifest = json.loads((output / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["version"], "0.0.16")

    def test_release_tag_stamps_and_enforces_both_plugin_manifest_versions(self):
        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "obstudio"

            STAGE.stage_plugin(output, host="all", release_version=STAGE.release_version_from_tag("v1.2.3"))

            for manifest_path in (
                output / ".codex-plugin" / "plugin.json",
                output / ".claude-plugin" / "plugin.json",
            ):
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(manifest["version"], "1.2.3")
            STAGE.verify_staged_plugin(output, host="all", expected_version="1.2.3")

    def test_release_tag_rejects_non_semver_or_missing_v_prefix(self):
        for tag in ("1.2.3", "vlatest", "v1.2", "v01.2.3", "v1.2.3-01", "v1.2.3-rc..1"):
            with self.assertRaisesRegex(RuntimeError, "release tag must be"):
                STAGE.release_version_from_tag(tag)

    def test_release_tag_accepts_semver_prerelease_and_build_metadata(self):
        self.assertEqual(STAGE.release_version_from_tag("v1.2.3-rc.1+build.42"), "1.2.3-rc.1+build.42")

    def test_release_tag_verification_rejects_manifest_version_mismatch(self):
        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "obstudio-claude"
            STAGE.stage_plugin(output, host="claude")

            with self.assertRaisesRegex(RuntimeError, "must match release version 1.2.3"):
                STAGE.verify_staged_plugin(output, host="claude", expected_version="1.2.3")

    def test_verify_rejects_staged_symlinks(self):
        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "obstudio"
            (output / ".codex-plugin").mkdir(parents=True)
            (output / ".codex-plugin" / "plugin.json").write_text(
                json.dumps({"interface": {"defaultPrompt": []}}),
                encoding="utf-8",
            )
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
        self.assertEqual(marketplace["interface"]["displayName"], "Splunk Observability Studio")
        self.assertEqual(marketplace["plugins"][0]["name"], "obstudio")

    def test_claude_marketplace_uses_legacy_compatible_metadata(self):
        marketplace_path = Path(__file__).resolve().parents[4] / ".claude-plugin" / "marketplace.json"
        marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))

        self.assertNotIn("description", marketplace)
        self.assertEqual(marketplace["name"], "obstudio")
        self.assertEqual(marketplace["plugins"][0]["name"], "obstudio")
        self.assertEqual(marketplace["plugins"][0]["source"], "./plugins/obstudio")
        self.assertEqual(marketplace["plugins"][0]["displayName"], "Splunk Observability Studio")

    def test_plugin_manifest_uses_committed_skills(self):
        plugin_root = Path(__file__).resolve().parents[2]
        manifest_path = plugin_root / ".codex-plugin" / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        skills_path = plugin_root / manifest["skills"]

        self.assertEqual(manifest["skills"], "./skills/")
        self.assertLessEqual(
            len(manifest["interface"]["defaultPrompt"]),
            STAGE.MAX_DEFAULT_PROMPTS,
        )
        self.assertTrue((skills_path / "otel-instrument" / "SKILL.md").is_file())
        self.assertFalse(any(path.is_symlink() for path in skills_path.rglob("*")))

    def test_host_manifests_explicitly_select_hook_files(self):
        plugin_root = Path(__file__).resolve().parents[2]
        codex_manifest = json.loads((plugin_root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        claude_manifest = json.loads((plugin_root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))

        self.assertEqual(codex_manifest["hooks"], "./hooks/codex-hooks.json")
        self.assertEqual(codex_manifest["name"], "obstudio")
        self.assertEqual(codex_manifest["interface"]["displayName"], "Splunk Observability Studio")
        self.assertEqual(claude_manifest["hooks"], "./hooks/claude-hooks.json")
        self.assertEqual(claude_manifest["name"], "obstudio")
        self.assertNotIn("$schema", claude_manifest)
        self.assertEqual(claude_manifest["displayName"], "Splunk Observability Studio")
        self.assertEqual(claude_manifest["version"], "0.0.16")

        codex_hook = json.loads((plugin_root / "hooks" / "codex-hooks.json").read_text(encoding="utf-8"))
        codex_command = codex_hook["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        self.assertIn("OBSTUDIO_PLUGIN_HOST=codex", codex_command)
        self.assertEqual(
            codex_hook["hooks"]["SessionStart"][0]["hooks"][0]["statusMessage"],
            "Bootstrapping Splunk Observability Studio for Codex",
        )

        claude_hook = json.loads((plugin_root / "hooks" / "claude-hooks.json").read_text(encoding="utf-8"))
        claude_command = claude_hook["hooks"]["SessionStart"][0]["hooks"][0]
        self.assertEqual(claude_command["command"], "node")
        self.assertEqual(claude_command["args"], ["${CLAUDE_PLUGIN_ROOT}/hooks/bootstrap_claude.cjs"])
        self.assertEqual(claude_command["statusMessage"], "Bootstrapping Splunk Observability Studio for Claude Code")
        self.assertNotIn("commandWindows", claude_command)

        claude_launcher = (plugin_root / "hooks" / "bootstrap_claude.cjs").read_text(encoding="utf-8")
        self.assertLess(claude_launcher.index('["py", ["-3"]]'), claude_launcher.index('["python", []]'))

    def test_verify_rejects_too_many_default_prompts(self):
        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "obstudio"
            (output / ".codex-plugin").mkdir(parents=True)
            (output / "skills").mkdir(parents=True)
            (output / ".codex-plugin" / "plugin.json").write_text(
                json.dumps(
                    {
                        "interface": {
                            "defaultPrompt": [
                                "one",
                                "two",
                                "three",
                                "four",
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "defaultPrompt must contain at most 3 entries"):
                STAGE.verify_staged_plugin(output)

    def test_verify_rejects_unknown_manifest_skill_references(self):
        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "obstudio"
            (output / ".codex-plugin").mkdir(parents=True)
            skill_dir = output / "skills" / "observer-control" / "observer-open"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: observer-open\n---\n",
                encoding="utf-8",
            )
            (output / ".codex-plugin" / "plugin.json").write_text(
                json.dumps(
                    {
                        "interface": {
                            "longDescription": "Open with $open-observer.",
                            "defaultPrompt": [],
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, r"unknown skills: \$open-observer"):
                STAGE.verify_staged_plugin(output)

    def test_committed_plugin_skills_are_synced(self):
        STAGE.verify_plugin_skills_synced()

    def test_normalized_hash_ignores_trailing_line_whitespace(self):
        with tempfile.TemporaryDirectory() as tempdir:
            source = Path(tempdir) / "source.md"
            destination = Path(tempdir) / "destination.md"
            source.write_text("same text \nnext\t\r\nlast ", encoding="utf-8")
            destination.write_text("same text\nnext\r\nlast", encoding="utf-8")

            self.assertEqual(
                STAGE.normalized_file_sha256(source),
                STAGE.normalized_file_sha256(destination),
            )

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

    def test_plugin_local_observer_control_skills_are_not_shared(self):
        root = Path(__file__).resolve().parents[4]

        self.assertFalse((root / "skills" / "observer-control").exists())


if __name__ == "__main__":
    unittest.main()
