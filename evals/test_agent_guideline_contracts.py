"""Deterministic contracts for repository coding and review guidance."""

from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_POLICY = REPO_ROOT / "AGENTS.md"
CASE_ROOT = REPO_ROOT / "evals" / "agent-guidelines"
CASE_FILES = (CASE_ROOT / "coding.json", CASE_ROOT / "review.json")
EXPECTED_HEADINGS = (
    "## Coding Agent Definition of Done",
    "## Reviewer Routing",
    "## Code Review Rules",
)
EXPECTED_RULE_IDS = {
    "OBS-SCOPE",
    "OBS-TEST",
    "OBS-SKILL",
    "OBS-PRESERVE",
    "OBS-UI",
    "OBS-PLUGIN",
    "OBS-INTEGRATION",
}
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


def _rule_section(document: str, rule_id: str) -> str:
    marker = f"### {rule_id} "
    assert marker in document
    tail = document.split(marker, 1)[1]
    return tail.split("\n### ", 1)[0]


def _squash(text: str) -> str:
    return " ".join(text.casefold().split())


def _assert_any(text: str, *phrases: str) -> None:
    normalized = _squash(text)
    assert any(_squash(phrase) in normalized for phrase in phrases), (
        f"expected one of {phrases!r} in policy section"
    )


def _validate_output_contract(schema: dict, expected: dict) -> None:
    required = schema["required"]
    properties = schema["properties"]

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(required) == {"verdict", "rule_ids", "evidence", "rationale"}
    assert set(expected) == set(required)
    assert expected["verdict"] in properties["verdict"]["enum"]
    assert isinstance(expected["rule_ids"], list)
    assert len(expected["rule_ids"]) == len(set(expected["rule_ids"]))
    assert set(expected["rule_ids"]) <= set(properties["rule_ids"]["items"]["enum"])
    assert isinstance(expected["evidence"], list) and expected["evidence"]
    assert all(isinstance(item, str) and item.strip() for item in expected["evidence"])
    assert isinstance(expected["rationale"], str) and expected["rationale"].strip()


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
    policy = _read(AGENT_POLICY)
    rules = _section(policy, EXPECTED_HEADINGS[2])

    assert all(rule_id in rules for rule_id in EXPECTED_RULE_IDS)
    _assert_any(rules, "unrelated", "drive-by")
    _assert_any(rules, "behavior changes", "behavior change")
    _assert_any(rules, "skills/", "canonical skill")
    _assert_any(rules, ".agents/skills", "discovery links")
    _assert_any(rules, "eval", "coverage")
    _assert_any(rules, "revert", "overwrite", "preserve")

    skill = _rule_section(policy, "OBS-SKILL")
    _assert_any(skill, "matching rubric eval", "matching qual/rubric eval")
    _assert_any(skill, "make eval-rubric")
    _assert_any(skill, "exact result", "command and result")
    _assert_any(skill, "`eval-validation` alone", "validation alone")

    ui = _rule_section(policy, "OBS-UI")
    for marker in (
        "text fields",
        "select/drop-down",
        "keyboard",
        "focus",
        "loading",
        "empty",
        "error",
        "supported widths",
        "themes",
    ):
        assert marker in _squash(ui)
    _assert_any(ui, "semantic names/roles", "accessible names/roles")
    _assert_any(ui, "rendered screenshots", "manual visual inspection")

    plugin = _rule_section(policy, "OBS-PLUGIN")
    for marker in (
        "discovery",
        "registration",
        "cli/config defaults",
        "schemas",
        "public imports",
        "aliases",
        "caches",
        "run state",
        "versioning",
        "migration",
    ):
        assert marker in _squash(plugin)
    _assert_any(plugin, "isolated", "isolation")
    _assert_any(plugin, "backward-compatible", "compatibility")

    integration = _rule_section(policy, "OBS-INTEGRATION")
    for marker in ("claude code", "codex", "cursor", "kiro", "copilot"):
        assert marker in _squash(integration)
    _assert_any(integration, "shared schema", "target's schema")
    _assert_any(integration, "user-owned state", "unrelated settings")
    _assert_any(integration, "one automatic target failure", "later targets")
    _assert_any(integration, "core observer", "stop the core observer")
    _assert_any(integration, "middle integration fails", "mixed-target path")


def test_agent_guideline_case_matrix_is_balanced_and_schema_constrained() -> None:
    for path in CASE_FILES:
        definition = _load(path)
        cases = definition["cases"]
        schema = definition["output_schema"]

        assert definition["policy_source"] == "AGENTS.md"
        assert "safe counterexample" in _squash(definition["judge_prompt"])
        assert "unrelated clean" in _squash(definition["judge_prompt"])
        assert {case["category"] for case in cases} == EXPECTED_CATEGORIES
        assert all(
            sum(case["category"] == category for case in cases) >= 1
            for category in EXPECTED_CATEGORIES
        )
        assert len({case["id"] for case in cases}) == len(cases)

        for case in cases:
            _validate_output_contract(schema, case["expected"])
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


def test_skill_change_cases_require_matching_rubric_eval_and_exact_run() -> None:
    definition = _load(CASE_ROOT / "coding.json")
    cases = {case["id"]: case for case in definition["cases"]}
    violation = cases["skill-change-without-matching-rubric-run"]
    safe = cases["skill-change-with-matching-rubric-run"]

    violation_text = _squash(json.dumps(violation))
    safe_text = _squash(json.dumps(safe))
    assert "eval/qual" in violation_text and "eval/rubric" in violation_text
    assert "eval-validation" in violation_text
    assert "make eval-rubric" in violation_text
    assert violation["expected"]["rule_ids"] == ["OBS-SKILL"]

    assert "evals/go/chi-basic/eval/qual/audit.json" in safe_text
    assert "skill field is otel-audit" in safe_text
    assert (
        "make eval-rubric skill=skills/otel-audit case=go/chi-basic" in safe_text
    )
    assert safe["expected"]["verdict"] == "acceptable"


def test_review_cases_cover_ui_plugin_and_integration_both_ways() -> None:
    definition = _load(CASE_ROOT / "review.json")
    cases = definition["cases"]
    cases_by_id = {case["id"]: case for case in cases}
    safe_case_ids = {
        "OBS-UI": "ui-control-and-layout-with-complete-proof",
        "OBS-PLUGIN": "plugin-change-isolated-and-compatible",
        "OBS-INTEGRATION": "automatic-agent-integration-isolates-middle-failure",
    }

    for rule_id in ("OBS-UI", "OBS-PLUGIN", "OBS-INTEGRATION"):
        violations = [
            case
            for case in cases
            if case["category"] == "violation"
            and rule_id in case["expected"]["rule_ids"]
        ]
        safe_case = cases_by_id[safe_case_ids[rule_id]]
        assert len(violations) == 1
        assert safe_case["category"] == "safe-counterexample"
        assert safe_case["expected"]["verdict"] == "acceptable"


def main() -> int:
    tests = (
        test_agent_policy_exposes_coding_and_review_contracts,
        test_code_review_rules_have_stable_ids_and_semantic_markers,
        test_agent_guideline_case_matrix_is_balanced_and_schema_constrained,
        test_agent_guideline_rubrics_use_only_documented_rules,
        test_skill_change_cases_require_matching_rubric_eval_and_exact_run,
        test_review_cases_cover_ui_plugin_and_integration_both_ways,
    )
    for test in tests:
        test()
    print(f"{len(tests)} agent-guideline contract tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
