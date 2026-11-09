from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.check_eval_models import DEFAULT_CONFIG, check_repository, reasoning_effort


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_eval_models.py"


class EvalModelPolicyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write_config()

    def write_config(self, name=DEFAULT_CONFIG, *, effort="high", model="gpt-6-luna"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        arguments = ["--config", f'model_reasoning_effort="{effort}"']
        path.write_text(
            f'[models]\nagent = "{model}"\njudge = "{model}"\n'
            f'[agent]\nextra_args = {json.dumps(arguments)}\n'
        )
        return path

    def write_report(self, *, skill="sample", kind="rubric", config=DEFAULT_CONFIG):
        path = self.root / "eval-reports" / skill / kind / "benchmark.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"metadata": {"agent_model": "gpt-6-luna", "judge_model": "gpt-6-luna" if kind == "rubric" else "-",
                             "rubric_enabled": kind == "rubric", "config_path": config},
                "source": {"files": {config: hashlib.sha256((self.root / config).read_bytes()).hexdigest()}}}
        path.write_text(json.dumps(data))
        return path

    def change(self, path, key, value):
        data = json.loads(path.read_text())
        data["metadata"][key] = value
        path.write_text(json.dumps(data))

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
            cwd=self.root, text=True, stderr=subprocess.PIPE,
        ).strip()

    def test_matching_models_and_unused_judges_pass(self):
        for kind in ("sanity", "rubric", "runtime"):
            self.write_report(kind=kind)
        self.assertEqual(check_repository(self.root), [])

    def test_model_mismatches_fail(self):
        for role in ("agent", "judge"):
            for model in ("another-model", "", None):
                with self.subTest(role=role, model=model):
                    path = self.write_report()
                    self.change(path, f"{role}_model", model)
                    self.assertIn(f"{role}_model: expected", "\n".join(check_repository(self.root)))

    def test_effort_mismatches_fail(self):
        for effort in ("low", "medium", "max"):
            with self.subTest(effort=effort):
                self.write_config("evals/selected.toml", effort=effort)
                self.write_report(config="evals/selected.toml")
                self.assertIn("model_reasoning_effort: expected 'high'", "\n".join(check_repository(self.root)))
        (self.root / "evals/selected.toml").write_text('[agent]\nextra_args = []\n')
        self.write_report(config="evals/selected.toml")
        self.assertTrue(check_repository(self.root))

    def test_last_supported_effort_override_wins(self):
        for args in (["--config", 'model_reasoning_effort="high"'],
                     ["--config=model_reasoning_effort=\"high\""],
                     ["-c", 'model_reasoning_effort="high"'],
                     ['-cmodel_reasoning_effort="high"']):
            with self.subTest(args=args):
                self.assertEqual(reasoning_effort(args), "high")
                self.assertEqual(reasoning_effort(args + ["-c", 'model_reasoning_effort="low"']), "low")

    def test_reference_values_come_from_repository_defaults(self):
        self.write_config(effort="medium", model="repository-model")
        path = self.write_report()
        for role in ("agent", "judge"):
            self.change(path, f"{role}_model", "repository-model")
        self.assertEqual(check_repository(self.root), [])

    def test_missing_or_unbound_inputs_fail(self):
        path = self.write_report()
        (self.root / DEFAULT_CONFIG).write_text((self.root / DEFAULT_CONFIG).read_text() + "\n# edited\n")
        self.assertIn("config source hash differs", "\n".join(check_repository(self.root)))
        for content in ("not JSON", "{}", "[]"):
            path.write_text(content)
            self.assertTrue(check_repository(self.root))
        path.unlink()
        (path.parent / "report.md").write_text("result")
        self.assertTrue(check_repository(self.root))

    def test_selected_config_stays_inside_repository(self):
        with tempfile.TemporaryDirectory() as outside:
            config = Path(outside) / "valid.toml"
            config.write_text((self.root / DEFAULT_CONFIG).read_text())
            relative = "../" + config.parent.name + "/valid.toml"
            self.write_report(config=relative)
            self.assertIn("subpath", "\n".join(check_repository(self.root)))

    def test_changed_results_use_merge_base_and_include_untracked_files(self):
        path = self.write_report()
        self.change(path, "agent_model", "another-model")
        self.git("init", "-q")
        self.git("config", "user.name", "Eval Policy Test")
        self.git("config", "user.email", "eval-policy@example.test")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.git("branch", "comparison-base")
        self.git("checkout", "-qb", "feature")
        (self.root / "feature.txt").write_text("feature")
        self.git("add", ".")
        self.git("commit", "-qm", "feature")
        self.git("checkout", "-q", "comparison-base")
        self.change(path, "run_id", "base-only-update")
        self.git("add", ".")
        self.git("commit", "-qm", "base refresh")
        self.git("checkout", "-q", "feature")
        self.assertEqual(check_repository(self.root, "comparison-base"), [])
        self.change(path, "run_id", "feature-update")
        self.assertTrue(check_repository(self.root, "comparison-base"))
        self.git("restore", ".")
        self.write_report(skill="new")
        self.assertEqual(check_repository(self.root, "comparison-base"), [])
        self.change(self.root / "eval-reports/new/rubric/benchmark.json", "judge_model", "another-model")
        self.assertTrue(check_repository(self.root, "comparison-base"))
        self.assertTrue(check_repository(self.root, "nonexistent-ref"))

    def test_validation_is_excluded_and_cli_fails_on_mismatch(self):
        path = self.root / "eval-reports/sample/validation/benchmark.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}")
        for mismatch in (False, True):
            report = self.write_report()
            if mismatch:
                self.change(report, "agent_model", "another-model")
            result = subprocess.run([sys.executable, str(SCRIPT), "--repo-root", str(self.root)], capture_output=True, text=True)
            self.assertEqual(result.returncode, int(mismatch), result.stderr)


if __name__ == "__main__":
    unittest.main()
