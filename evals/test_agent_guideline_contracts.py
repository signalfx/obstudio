"""Deterministic contracts for repository coding and review guidance."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_POLICY = REPO_ROOT / "AGENTS.md"
CASE_ROOT = REPO_ROOT / "evals" / "agent-guidelines"
CASE_FILES = (CASE_ROOT / "coding.json", CASE_ROOT / "review.json")
EXPECTED_HEADINGS = (
    "## Coding Agent Definition of Done",
    "## Reviewer Routing",
    "## Code Review Rules",
)
EXPECTED_RULE_IDS = {"OBS-SCOPE", "OBS-TEST", "OBS-SKILL", "OBS-PRESERVE"}
EXPECTED_CATEGORIES = {"violation", "safe-counterexample", "unrelated-clean"}


def _read(path: Path) -> str:
    assert path.is_file(), f"expected file not found: {path}"
    return path.read_text(encoding="utf-8")


def _load(path: Path) -> dict:
    return json.loads(_read(path))


def _section(document: str, heading: str) -> str:
    assert heading in document
    tail = document.split(heading, 1)[1]
    return tail.split("\n## ", 1)[0]


def _squash(text: str) -> str:
    return " ".join(text.casefold().split())


def _assert_any(text: str, *phrases: str) -> None:
    normalized = _squash(text)
    assert any(_squash(phrase) in normalized for phrase in phrases), (
        f"expected one of {phrases!r} in policy section"
    )


def test_agent_policy_exposes_coding_and_review_contracts() -> None:
    policy = _read(AGENT_POLICY)
    positions = [policy.index(heading) for heading in EXPECTED_HEADINGS]

    assert positions == sorted(positions)

    coding = _section(policy, EXPECTED_HEADINGS[0])
    _assert_any(
        coding,
        "focused diff",
        "focused change",
        "requested scope",
        "remove unrelated edits",
    )
    _assert_any(coding, "behavior changes", "behavior change")
    _assert_any(coding, "narrowest relevant test", "narrowest useful test")
    _assert_any(coding, "exact commands", "exact validation commands", "commands run")
    _assert_any(coding, "skipped", "not run")
    _assert_any(coding, "residual risk", "remaining risk")

    reviewer = _section(policy, EXPECTED_HEADINGS[1])
    _assert_any(reviewer, "merge-base diff", "merge base diff")
    _assert_any(reviewer, "read-only", "do not edit")
    _assert_any(reviewer, "correctness", "regression")
    _assert_any(reviewer, "file and line", "file/line", "changed line")
    _assert_any(reviewer, "missing tests", "missing proof", "test coverage")


def test_code_review_rules_have_stable_ids_and_semantic_markers() -> None:
    rules = _section(_read(AGENT_POLICY), EXPECTED_HEADINGS[2])

    assert all(rule_id in rules for rule_id in EXPECTED_RULE_IDS)
    _assert_any(rules, "unrelated", "drive-by")
    _assert_any(rules, "behavior changes", "behavior change")
    _assert_any(rules, "skills/", "canonical skill")
    _assert_any(rules, ".agents/skills", "discovery links")
    _assert_any(rules, "eval", "coverage")
    _assert_any(rules, "revert", "overwrite", "preserve")


def test_agent_guideline_case_matrix_is_balanced_and_schema_constrained() -> None:
    for path in CASE_FILES:
        definition = _load(path)
        cases = definition["cases"]
        schema = definition["output_schema"]

        Draft202012Validator.check_schema(schema)
        assert definition["policy_source"] == "AGENTS.md"
        assert "safe counterexample" in _squash(definition["judge_prompt"])
        assert "unrelated clean" in _squash(definition["judge_prompt"])
        assert {case["category"] for case in cases} == EXPECTED_CATEGORIES
        assert len(cases) == len(EXPECTED_CATEGORIES)
        assert len({case["id"] for case in cases}) == len(cases)

        for case in cases:
            Draft202012Validator(schema).validate(case["expected"])
            if case["category"] == "violation":
                assert case["expected"]["verdict"] == "changes-required"
                assert case["expected"]["rule_ids"]
            else:
                assert case["expected"]["verdict"] == "acceptable"
                assert case["expected"]["rule_ids"] == []


def test_agent_guideline_rubrics_use_only_documented_rules() -> None:
    exercised_violations: set[str] = set()

    for path in CASE_FILES:
        definition = _load(path)
        rubric_ids = [item["id"] for item in definition["rubric"]]

        assert len(rubric_ids) == len(set(rubric_ids))
        assert set(rubric_ids) <= EXPECTED_RULE_IDS
        for item in definition["rubric"]:
            assert item["criterion"].strip()
        for case in definition["cases"]:
            assert set(case["expected"]["rule_ids"]) <= set(rubric_ids)
            if case["category"] == "violation":
                exercised_violations.update(case["expected"]["rule_ids"])

    assert exercised_violations == EXPECTED_RULE_IDS
