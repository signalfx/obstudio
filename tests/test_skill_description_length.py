from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.check_skill_description_length import (
    DESCRIPTION_CAP,
    _description_from_frontmatter,
    _extract_frontmatter,
    _find_skill_files,
)


class SkillDescriptionLengthTest(unittest.TestCase):
    def test_folded_block_scalar_joins_lines_with_spaces(self):
        frontmatter = (
            "name: example\n"
            "description: >-\n"
            "  Line one of the\n"
            "  description.\n"
        )
        self.assertEqual(
            _description_from_frontmatter(frontmatter), "Line one of the description."
        )

    def test_folded_block_scalar_preserves_paragraph_breaks(self):
        frontmatter = (
            "name: example\n"
            "description: >-\n"
            "  First paragraph\n"
            "  continues here.\n"
            "\n"
            "  Second paragraph.\n"
        )
        self.assertEqual(
            _description_from_frontmatter(frontmatter),
            "First paragraph continues here.\nSecond paragraph.",
        )

    def test_literal_block_scalar_preserves_newlines(self):
        frontmatter = "name: example\ndescription: |-\n  line one\n  line two\n"
        self.assertEqual(_description_from_frontmatter(frontmatter), "line one\nline two")

    def test_plain_scalar_description(self):
        frontmatter = "name: example\ndescription: A short description.\n"
        self.assertEqual(_description_from_frontmatter(frontmatter), "A short description.")

    def test_missing_description_returns_none(self):
        frontmatter = "name: example\n"
        self.assertIsNone(_description_from_frontmatter(frontmatter))

    def test_extract_frontmatter_requires_leading_delimiter(self):
        self.assertIsNone(_extract_frontmatter("no frontmatter here\n"))

    def test_extract_frontmatter_returns_block_between_delimiters(self):
        text = "---\nname: example\ndescription: hi\n---\nbody\n"
        self.assertEqual(_extract_frontmatter(text), "name: example\ndescription: hi\n")

    def test_find_skill_files_includes_canonical_and_plugin_skills(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "skills" / "example").mkdir(parents=True)
            (root / "skills" / "example" / "SKILL.md").write_text(
                "---\nname: example\ndescription: hi\n---\n", encoding="utf-8"
            )
            (root / "plugins" / "obstudio" / "skills" / "observer-control" / "observer-open").mkdir(
                parents=True
            )
            (
                root
                / "plugins"
                / "obstudio"
                / "skills"
                / "observer-control"
                / "observer-open"
                / "SKILL.md"
            ).write_text("---\nname: observer-open\ndescription: hi\n---\n", encoding="utf-8")

            found = _find_skill_files(root)

            self.assertEqual(
                {path.relative_to(root) for path in found},
                {
                    Path("skills/example/SKILL.md"),
                    Path("plugins/obstudio/skills/observer-control/observer-open/SKILL.md"),
                },
            )

    def test_find_skill_files_deduplicates_identical_resolved_paths(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "skills" / "example").mkdir(parents=True)
            (root / "skills" / "example" / "SKILL.md").write_text(
                "---\nname: example\ndescription: hi\n---\n", encoding="utf-8"
            )
            plugin_skills = root / "plugins" / "obstudio" / "skills"
            plugin_skills.mkdir(parents=True)
            (plugin_skills / "example").symlink_to(root / "skills" / "example")

            found = _find_skill_files(root)

            self.assertEqual(len(found), 1)

    def test_canonical_and_plugin_skill_descriptions_stay_within_cap(self):
        root = Path(__file__).resolve().parent.parent
        skill_files = _find_skill_files(root)
        self.assertTrue(skill_files, "expected SKILL.md files under skills/ and plugins/obstudio/skills/")
        for skill_file in skill_files:
            frontmatter = _extract_frontmatter(skill_file.read_text(encoding="utf-8"))
            description = _description_from_frontmatter(frontmatter or "")
            self.assertIsNotNone(description, f"{skill_file}: missing description")
            self.assertLessEqual(
                len(description),
                DESCRIPTION_CAP,
                f"{skill_file}: description exceeds {DESCRIPTION_CAP} characters",
            )

    def test_main_fails_when_description_exceeds_cap(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            skill_dir = root / "skills" / "too-long"
            skill_dir.mkdir(parents=True)
            oversized = "x " * (DESCRIPTION_CAP // 2 + 10)
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: too-long\ndescription: >-\n  {oversized}\n---\n",
                encoding="utf-8",
            )

            import scripts.check_skill_description_length as module

            original_file = module.__file__
            module.__file__ = str(root / "scripts" / "check_skill_description_length.py")
            try:
                self.assertEqual(module.main(), 1)
            finally:
                module.__file__ = original_file


if __name__ == "__main__":
    unittest.main()
