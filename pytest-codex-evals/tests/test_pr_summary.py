from __future__ import annotations

import json
from pathlib import Path

from pytest_codex_evals.pr_summary import (
    END_MARKER,
    START_MARKER,
    extract_rubric_summary,
    render_rubric_pr_summary,
    replace_rubric_summary_section,
)


def test_render_rubric_pr_summary_uses_report_sections(tmp_path: Path):
    write_skill(tmp_path, "otel-audit")
    write_eval(tmp_path, "python/example/eval/qual/audit.json", "otel-audit")
    base_reports = tmp_path / ".baseline-eval-reports"
    write_report(base_reports, "otel-audit", "90% (9/10), avg score 86")
    write_report(tmp_path / "eval-reports", "otel-audit", "100% (10/10), avg score 92")

    summary = render_rubric_pr_summary(
        tmp_path,
        ["otel-audit"],
        base_report_root=base_reports,
        base_label="origin/main",
        after_label="this PR",
    )

    assert START_MARKER in summary
    assert END_MARKER in summary
    assert "## Skill Rubric Summary" in summary
    assert "Before is copied from the base branch" in summary
    assert "After is generated from this PR's live rubric eval report." in summary
    assert "#### Before (origin/main)" in summary
    assert "90% (9/10), avg score 86" in summary
    assert "#### After (this PR)" in summary
    assert "100% (10/10), avg score 92" in summary
    assert "Rubric Failures" not in summary


def test_render_rubric_pr_summary_marks_missing_after_report(tmp_path: Path):
    write_skill(tmp_path, "otel-instrument")
    write_eval(tmp_path, "java/example/eval/qual/instrument.json", "otel-instrument")

    summary = render_rubric_pr_summary(
        tmp_path,
        ["otel-instrument"],
        missing_after_note="not run: OPENAI_API_KEY not configured",
    )

    assert "_No base rubric report was found._" in summary
    assert "_not run: OPENAI_API_KEY not configured_" in summary


def test_extract_rubric_summary_returns_only_the_summary_table():
    report = """# Report

## Environment

env

## Rubric Summary

| A | B |
|---|---|
| 1 | 2 |

## Rubric Failures

failures
"""

    assert extract_rubric_summary(report) == "| A | B |\n|---|---|\n| 1 | 2 |"


def test_replace_rubric_summary_section_updates_existing_markers():
    old = f"Intro\n\n{START_MARKER}\nold summary\n{END_MARKER}\n\nOutro\n"
    new = f"{START_MARKER}\nnew summary\n{END_MARKER}\n"

    updated = replace_rubric_summary_section(old, new)

    assert "Intro" in updated
    assert "Outro" in updated
    assert "new summary" in updated
    assert "old summary" not in updated


def write_skill(root: Path, skill: str) -> None:
    skill_dir = root / "skills" / skill
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {skill}\n---\n", encoding="utf-8")


def write_eval(root: Path, rel: str, skill: str) -> None:
    path = root / "evals" / rel
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"skill": skill, "prompts": [{"id": "direct", "task": "Run."}]}), encoding="utf-8")


def write_report(root: Path, skill: str, result: str) -> None:
    path = root / skill / "rubric" / "report.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        f"""# {skill} Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/example/qual/audit | python/example | 2 | {result} | 10K | 1.0m | - | - | - |

## Rubric Failures

No rubric failures.
""",
        encoding="utf-8",
    )
