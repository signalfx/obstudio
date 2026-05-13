from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Iterable


START_MARKER = "<!-- obstudio-rubric-summary:start -->"
END_MARKER = "<!-- obstudio-rubric-summary:end -->"

KIND_ORDER = ("validation", "sanity", "rubric", "runtime")
ROLE_TO_KIND = {
    "sanity": "sanity",
    "qual": "rubric",
    "runtime": "runtime",
}


def discover_changed_skills(repo_root: Path, base: str, head: str) -> list[str]:
    """Return skill names affected by a PR diff."""
    paths = changed_paths(repo_root, base, head)
    direct_skills: set[str] = set()
    include_all_eval_skills = False

    for path in paths:
        parts = Path(path).parts
        if len(parts) >= 2 and parts[0] == "skills":
            direct_skills.add(parts[1])
            continue
        if parts and parts[0] in {"evals", "pytest-codex-evals"}:
            include_all_eval_skills = True
            continue
        if path == ".github/workflows/skill-rubric-pr-summary.yml":
            include_all_eval_skills = True

    skills = set(skills_with_evals(repo_root)) if include_all_eval_skills else set()
    skills.update(direct_skills)
    return sorted(skill for skill in skills if skill_exists(repo_root, skill))


def changed_paths(repo_root: Path, base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", base, head],
        cwd=repo_root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def skill_exists(repo_root: Path, skill: str) -> bool:
    return (repo_root / "skills" / skill / "SKILL.md").is_file()


def skills_with_evals(repo_root: Path) -> list[str]:
    return sorted({skill for skill, _ in eval_skill_kinds(repo_root)})


def available_kinds(repo_root: Path, skill: str) -> list[str]:
    kinds = {kind for eval_skill, kind in eval_skill_kinds(repo_root) if eval_skill == skill}
    if kinds:
        kinds.add("validation")
    return [kind for kind in KIND_ORDER if kind in kinds]


def eval_skill_kinds(repo_root: Path) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    evals_root = repo_root / "evals"
    if not evals_root.is_dir():
        return pairs

    for path in sorted(evals_root.rglob("*.json")):
        kind = ROLE_TO_KIND.get(path.parent.name)
        if kind is None:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        skill = payload.get("skill")
        if isinstance(skill, str) and skill:
            pairs.add((skill, kind))
    return pairs


def render_rubric_pr_summary(
    repo_root: Path,
    skills: Iterable[str],
    *,
    base_report_root: Path | None = None,
    base_label: str = "base",
    after_label: str = "this PR",
    missing_after_note: str = "not run",
) -> str:
    skill_list = [skill for skill in skills if skill_exists(repo_root, skill)]
    sections = [
        render_skill_rubric_summary(repo_root, skill, base_report_root, base_label, after_label, missing_after_note)
        for skill in skill_list
    ]
    if not sections:
        sections.append("_No changed skills with rubric evals were detected._")

    lines = [
        START_MARKER,
        "## Skill Rubric Summary",
        "",
        "Before is copied from the base branch `eval-reports/<skill>/rubric/report.md#rubric-summary` section. "
        "After is generated from this PR's live rubric eval report.",
        "",
        *sections,
        END_MARKER,
    ]
    return "\n".join(lines) + "\n"


def render_skill_rubric_summary(
    repo_root: Path,
    skill: str,
    base_report_root: Path | None,
    base_label: str,
    after_label: str,
    missing_after_note: str,
) -> str:
    if "rubric" not in available_kinds(repo_root, skill):
        return f"### `{skill}`\n\n_No rubric eval definition found for this skill._\n"

    base_report = load_report(base_report_root or repo_root / "eval-reports", skill)
    after_report = load_report(repo_root / "eval-reports", skill)
    base_summary = extract_rubric_summary(base_report) if base_report else None
    after_summary = extract_rubric_summary(after_report) if after_report else None

    lines = [
        f"### `{skill}`",
        "",
        f"#### Before ({base_label})",
        "",
        format_summary_or_note(base_summary, "No base rubric report was found."),
        "",
        f"#### After ({after_label})",
        "",
        format_summary_or_note(after_summary, missing_after_note),
        "",
    ]
    return "\n".join(lines)


def load_report(root: Path, skill: str) -> str | None:
    path = root / skill / "rubric" / "report.md"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def extract_rubric_summary(markdown: str) -> str | None:
    lines = markdown.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == "## Rubric Summary":
            start = index + 1
            break
    if start is None:
        return None

    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break

    section = "\n".join(lines[start:end]).strip()
    return section or None


def format_summary_or_note(summary: str | None, note: str) -> str:
    if summary:
        return summary
    return f"_{note}_"


def replace_rubric_summary_section(body: str, section: str) -> str:
    start = body.find(START_MARKER)
    end = body.find(END_MARKER)
    if start != -1 and end != -1 and start < end:
        end += len(END_MARKER)
        return body[:start].rstrip() + "\n\n" + section.strip() + "\n\n" + body[end:].lstrip()
    if not body.strip():
        return section
    return body.rstrip() + "\n\n" + section
