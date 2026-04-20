"""Performance eval tests -- token budgets and context limits."""

import pytest

from conftest import (
    LANGUAGE_REF_BUDGET,
    MAX_SINGLE_SKILL_CONTEXT,
    REFERENCE_TOKEN_BUDGETS,
    REFS_DIR,
    SKILL_TOKEN_BUDGETS,
    SKILLS_DIR,
    estimate_tokens,
)

SKILL_IDS = list(SKILL_TOKEN_BUDGETS.keys())
REF_IDS = list(REFERENCE_TOKEN_BUDGETS.keys())


class TestSkillTokenBudgets:
    """Each skill must stay within its token budget."""

    @pytest.mark.parametrize("skill_name", SKILL_IDS)
    def test_skill_within_budget(self, skill_name):
        budget = SKILL_TOKEN_BUDGETS[skill_name]
        skill_file = SKILLS_DIR / skill_name / "SKILL.md"
        assert skill_file.exists(), f"Skill file not found: {skill_file}"

        tokens = estimate_tokens(skill_file.read_text())
        assert tokens <= budget, (
            f"{skill_name}: {tokens}/{budget} tokens "
            f"({tokens / budget * 100:.0f}%) — OVER BUDGET"
        )


class TestReferenceTokenBudgets:
    """Shared references must stay within their token budgets."""

    @pytest.mark.parametrize("ref_name", REF_IDS)
    def test_reference_within_budget(self, ref_name):
        budget = REFERENCE_TOKEN_BUDGETS[ref_name]
        ref_file = REFS_DIR / ref_name
        assert ref_file.exists(), f"Reference file not found: {ref_file}"

        tokens = estimate_tokens(ref_file.read_text())
        assert tokens <= budget, (
            f"{ref_name}: {tokens}/{budget} tokens "
            f"({tokens / budget * 100:.0f}%) — OVER BUDGET"
        )

    def test_language_refs_within_budget(self):
        lang_dir = REFS_DIR / "languages"
        if not lang_dir.is_dir():
            pytest.skip("No languages/ directory")

        over = []
        for f in sorted(lang_dir.glob("*.md")):
            tokens = estimate_tokens(f.read_text())
            if tokens > LANGUAGE_REF_BUDGET:
                over.append(f"{f.name}: {tokens}/{LANGUAGE_REF_BUDGET}")
        assert not over, f"Language refs over budget: {over}"


class TestCombinedContext:
    """Skill + largest reference + largest language ref must fit in context."""

    @pytest.mark.parametrize("skill_name", SKILL_IDS)
    def test_combined_fits_context(self, skill_name):
        skill_file = SKILLS_DIR / skill_name / "SKILL.md"
        if not skill_file.exists():
            pytest.skip(f"Skill not found: {skill_name}")

        skill_tokens = estimate_tokens(skill_file.read_text())

        max_ref = 0
        for ref_name in REFERENCE_TOKEN_BUDGETS:
            ref_file = REFS_DIR / ref_name
            if ref_file.exists():
                max_ref = max(max_ref, estimate_tokens(ref_file.read_text()))

        max_lang = 0
        lang_dir = REFS_DIR / "languages"
        if lang_dir.is_dir():
            for f in lang_dir.glob("*.md"):
                max_lang = max(max_lang, estimate_tokens(f.read_text()))

        combined = skill_tokens + max_ref + max_lang
        assert combined <= MAX_SINGLE_SKILL_CONTEXT, (
            f"{skill_name}: {combined}/{MAX_SINGLE_SKILL_CONTEXT} tokens "
            f"(skill={skill_tokens} + ref={max_ref} + lang={max_lang}) "
            f"— EXCEEDS CONTEXT SLICE"
        )
