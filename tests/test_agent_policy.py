from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.check_agent_policy import (
    REQUIRED_RULE_IDS,
    ROUTED_AGENT_GUIDES,
    _check_shared_reference_consumers,
    _check_skill_eval_diff,
    _default_base_ref,
    _git_changed_files,
    _make_references,
    check_repository,
)


class AgentPolicyCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self._write("skills/example/SKILL.md", "---\nname: example\n---\n")
        self._write("skills/references/consumers.json", "{}\n")
        (self.root / ".agents/skills").mkdir(parents=True)
        (self.root / ".agents/skills/example").symlink_to("../../skills/example")
        self._write(
            "AGENTS.md",
            """# AGENTS.md

Read `CONTRIBUTING.md`. Canonical sources live in `skills/`; discovery links
live in `.agents/skills/`.

## Coding Agent Definition of Done

Run focused tests.

## Reviewer Routing

"""
            + "\n".join(f"- `{guide}`" for guide in ROUTED_AGENT_GUIDES)
            + """

## Code Review Rules

Review the merge-base diff under OBS-SCOPE, OBS-TEST, OBS-SKILL,
OBS-PRESERVE, OBS-UI, OBS-PLUGIN, and OBS-INTEGRATION.

## Confluence Document Updates

Use structural API updates and validate the published document.

## Available Skills

| Skill | Purpose |
|---|---|
| `$example` | Example |

```sh
make test MODE=fast
make -C evals verify CASE=one
```
""",
        )
        self._write("CONTRIBUTING.md", "Run `make --jobs 2 test`.\n")
        for guide in ROUTED_AGENT_GUIDES:
            self._write(guide, "# Scoped instructions\n")
        self._write(
            ".github/copilot-instructions.md",
            "Follow `/AGENTS.md` Reviewer Routing and Code Review Rules.\n",
        )
        self._write(
            ".github/PULL_REQUEST_TEMPLATE.md",
            """## Summary

## Scope

## Validation evidence

- Exact commands and results:
- Skill eval file(s):
- Local rubric command and result:
- UI interaction/accessibility evidence:
- Plugin/integration compatibility evidence:
- Checks skipped and why:

## Risk and review

- Residual risks:
""",
        )
        self._write("Makefile", "test:\n\t@true\n")
        self._write("evals/Makefile", "verify:\n\t@true\n")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write(self, relative_path: str, content: str) -> None:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_accepts_consistent_policy_contract(self) -> None:
        self.assertEqual(check_repository(self.root), [])

    def test_rejects_absolute_and_misdirected_skill_links(self) -> None:
        link = self.root / ".agents/skills/example"
        link.unlink()
        link.symlink_to(self.root / "skills/example")
        errors = check_repository(self.root)
        self.assertTrue(any("link target must be relative" in error for error in errors))

        link.unlink()
        self._write("skills/other/SKILL.md", "---\nname: other\n---\n")
        link.symlink_to("../../skills/other")
        errors = check_repository(self.root)
        self.assertTrue(any("expected" in error for error in errors))

    def test_requires_canonical_relative_skill_link_spelling(self) -> None:
        link = self.root / ".agents/skills/example"
        link.unlink()
        link.symlink_to("../../../" + self.root.name + "/skills/example")
        errors = check_repository(self.root)
        self.assertTrue(any("link target must be ../../skills/example" in error for error in errors))

    def test_requires_exact_skill_table_and_discovery_parity(self) -> None:
        self._write("skills/second/SKILL.md", "---\nname: second\n---\n")
        errors = check_repository(self.root)
        self.assertTrue(any("missing canonical skill links: second" in error for error in errors))
        self.assertTrue(any("missing canonical skills: second" in error for error in errors))

    def test_requires_routed_guides_and_copilot_adapter(self) -> None:
        (self.root / "observer/client/AGENTS.md").unlink()
        self._write(".github/copilot-instructions.md", "Standalone instructions.\n")
        errors = check_repository(self.root)
        self.assertTrue(any("routed instruction file is missing" in error for error in errors))
        self.assertTrue(any("canonical root AGENTS.md" in error for error in errors))

    def test_requires_stable_review_ids_and_pr_evidence(self) -> None:
        agents = self.root.joinpath("AGENTS.md").read_text(encoding="utf-8")
        for rule_id in REQUIRED_RULE_IDS:
            with self.subTest(rule_id=rule_id):
                self._write("AGENTS.md", agents.replace(rule_id, "OBS-REMOVED"))
                errors = check_repository(self.root)
                self.assertTrue(any(f"missing {rule_id}" in error for error in errors))

        self._write("AGENTS.md", agents)
        self._write(".github/PULL_REQUEST_TEMPLATE.md", "## Summary\n")
        errors = check_repository(self.root)
        self.assertTrue(any("missing '## Validation evidence'" in error for error in errors))

    def test_make_parser_ignores_options_assignments_and_plain_prose(self) -> None:
        text = """Do not treat make imaginary as a command.

Use `make --jobs 2 test MODE=fast`.

```sh
cd evals && make -j4 verify CASE=one
make -C evals --directory=. verify
```
"""
        self.assertEqual(
            _make_references(text),
            [
                (3, Path("."), "test"),
                (6, Path("evals"), "verify"),
                (7, Path("evals"), "verify"),
            ],
        )

    def test_rejects_unknown_documented_make_target(self) -> None:
        self._write("CONTRIBUTING.md", "Run `make missing-target`.\n")
        errors = check_repository(self.root)
        self.assertTrue(any("unknown make target 'missing-target'" in error for error in errors))

    def test_rejects_stale_coverage_cross_reference(self) -> None:
        self._write(
            "CONTRIBUTING.md",
            "See `AGENTS.md` for how agents should incorporate coverage analysis.\n",
        )
        errors = check_repository(self.root)
        self.assertTrue(any("contains no coverage guidance" in error for error in errors))

    def test_changed_skill_requires_a_matching_changed_rubric_eval(self) -> None:
        for status in ("M", "D"):
            with self.subTest(status=status):
                errors: list[str] = []
                _check_skill_eval_diff(
                    self.root,
                    [(status, Path("skills/example/SKILL.md"))],
                    errors,
                )
                self.assertTrue(
                    any("shipped skill content changed" in error for error in errors)
                )

        skill_change = ("M", Path("skills/example/SKILL.md"))
        rubric_path = Path("evals/go/example/eval/qual/audit.json")
        self._write(rubric_path.as_posix(), '{"skill": "other"}\n')
        errors = []
        _check_skill_eval_diff(self.root, [skill_change, ("M", rubric_path)], errors)
        self.assertTrue(any("skill='example'" in error for error in errors))

        self._write(rubric_path.as_posix(), '{"skill": "example"}\n')
        errors = []
        _check_skill_eval_diff(self.root, [skill_change, ("M", rubric_path)], errors)
        self.assertEqual(errors, [])

    def test_deleted_rubric_does_not_satisfy_skill_pairing(self) -> None:
        skill_change = ("M", Path("skills/example/SKILL.md"))
        rubric_path = Path("evals/go/example/eval/qual/audit.json")
        errors: list[str] = []
        _check_skill_eval_diff(
            self.root,
            [skill_change, ("D", rubric_path)],
            errors,
        )
        self.assertTrue(any("shipped skill content changed" in error for error in errors))

    def test_sanity_or_runtime_eval_does_not_satisfy_skill_rubric_pairing(self) -> None:
        skill_change = ("M", Path("skills/example/references/contract.md"))
        sanity_path = Path("evals/go/example/eval/sanity/audit.json")
        runtime_path = Path("evals/go/example/eval/runtime/audit.json")
        self._write(sanity_path.as_posix(), '{"skill": "example"}\n')
        self._write(runtime_path.as_posix(), '{"skill": "example"}\n')
        errors: list[str] = []
        _check_skill_eval_diff(
            self.root,
            [skill_change, ("M", sanity_path), ("M", runtime_path)],
            errors,
        )
        self.assertTrue(any("shipped skill content changed" in error for error in errors))

    def test_test_only_skill_changes_do_not_require_a_rubric_pair(self) -> None:
        errors: list[str] = []
        _check_skill_eval_diff(
            self.root,
            [("M", Path("skills/example/tests/test_contract.py"))],
            errors,
        )
        self.assertEqual(errors, [])

    def test_shared_skill_reference_requires_at_least_one_changed_rubric(self) -> None:
        shared_change = ("M", Path("skills/references/shared-contract.md"))
        self._write(
            "skills/references/consumers.json",
            '{"shared-contract.md": ["example"]}\n',
        )
        errors: list[str] = []
        _check_skill_eval_diff(self.root, [shared_change], errors)
        self.assertTrue(any("affected skill 'example'" in error for error in errors))

        rubric_path = Path("evals/go/example/eval/qual/audit.json")
        self._write(rubric_path.as_posix(), '{"skill": "example"}\n')
        errors = []
        _check_skill_eval_diff(self.root, [shared_change, ("A", rubric_path)], errors)
        self.assertEqual(errors, [])

    def test_shared_reference_map_matches_files_and_declared_consumers(self) -> None:
        self._write("skills/references/shared-contract.md", "# Shared\n")
        errors = check_repository(self.root)
        self.assertTrue(any("missing shared references" in error for error in errors))

        self._write(
            "skills/references/consumers.json",
            '{"shared-contract.md": ["example"]}\n',
        )
        errors = check_repository(self.root)
        self.assertTrue(
            any("names skills that do not reference it: example" in error for error in errors)
        )

        self._write(
            "skills/example/SKILL.md",
            "---\nname: example\n---\nRead ../references/shared-contract.md.\n",
        )
        self.assertEqual(check_repository(self.root), [])

    def test_shared_reference_map_cannot_omit_a_real_consumer(self) -> None:
        self._write("skills/references/shared-contract.md", "# Shared\n")
        self._write(
            "skills/references/consumers.json",
            '{"shared-contract.md": ["example"]}\n',
        )
        self._write(
            "skills/example/SKILL.md",
            "---\nname: example\n---\nRead ../references/shared-contract.md.\n",
        )
        self._write(
            "skills/second/SKILL.md",
            "---\nname: second\n---\nRead ../references/shared-contract.md.\n",
        )
        errors: list[str] = []
        _check_shared_reference_consumers(
            self.root,
            {"example", "second"},
            errors,
        )
        self.assertTrue(any("omits consuming skills: second" in error for error in errors))

    def test_git_diff_includes_worktree_index_untracked_and_both_rename_sides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    ["git", *args],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=True,
                )

            git("init", "-b", "main")
            git("config", "user.name", "Agent Policy Test")
            git("config", "user.email", "agent-policy@example.invalid")
            self._write_at(root, "skills/example/SKILL.md", "---\nname: example\n---\n")
            self._write_at(root, "skills/example/reference.md", "move me\n")
            git("add", ".")
            git("commit", "-m", "baseline")

            self._write_at(
                root,
                "skills/example/SKILL.md",
                "---\nname: example\n---\nChanged.\n",
            )
            self._write_at(
                root,
                "evals/go/example/eval/qual/audit.json",
                '{"skill": "example"}\n',
            )
            git("add", "evals/go/example/eval/qual/audit.json")
            self._write_at(root, "notes.txt", "untracked\n")
            (root / "skills/example/reference.md").rename(root / "moved-reference.md")
            git(
                "add",
                "-A",
                "--",
                "skills/example/reference.md",
                "moved-reference.md",
            )

            default_base = _default_base_ref(root)
            self.assertIsNotNone(default_base)
            errors: list[str] = []
            changes, base_tree = _git_changed_files(root, default_base or "HEAD", errors)

            self.assertEqual(errors, [])
            self.assertTrue(base_tree)
            self.assertIn(("M", Path("skills/example/SKILL.md")), changes)
            self.assertIn(("A", Path("evals/go/example/eval/qual/audit.json")), changes)
            self.assertIn(("A", Path("notes.txt")), changes)
            self.assertIn(("D", Path("skills/example/reference.md")), changes)
            self.assertIn(("A", Path("moved-reference.md")), changes)

    @staticmethod
    def _write_at(root: Path, relative_path: str, content: str) -> None:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
