from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.check_agent_policy import (
    REQUIRED_CODEOWNER_PATTERNS,
    ROUTED_AGENT_GUIDES,
    _make_references,
    check_repository,
)


class AgentPolicyCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self._write("skills/example/SKILL.md", "---\nname: example\n---\n")
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

Review the merge-base diff under OBS-SCOPE, OBS-TEST, OBS-SKILL, and
OBS-PRESERVE.

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
            ".github/CODEOWNERS",
            "\n".join(
                f"{pattern} @maintainer @backup" for pattern in REQUIRED_CODEOWNER_PATTERNS
            )
            + "\n",
        )
        self._write(
            ".github/PULL_REQUEST_TEMPLATE.md",
            """## Summary

## Scope

## Validation evidence

- Exact commands and results:
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
        self._write("AGENTS.md", agents.replace("OBS-PRESERVE", "OBS-REMOVED"))
        self._write(".github/PULL_REQUEST_TEMPLATE.md", "## Summary\n")
        errors = check_repository(self.root)
        self.assertTrue(any("missing OBS-PRESERVE" in error for error in errors))
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

    def test_requires_policy_codeowners(self) -> None:
        self._write(".github/CODEOWNERS", "AGENTS.md @maintainer\n")
        errors = check_repository(self.root)
        self.assertTrue(any("missing protected policy paths" in error for error in errors))

    def test_requires_two_independent_policy_owners(self) -> None:
        self._write(
            ".github/CODEOWNERS",
            "\n".join(
                f"{pattern} @maintainer" for pattern in REQUIRED_CODEOWNER_PATTERNS
            )
            + "\n",
        )
        errors = check_repository(self.root)
        self.assertTrue(any("at least two independent owners" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
