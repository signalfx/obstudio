from __future__ import annotations

import argparse
from pathlib import Path

from .discovery import discover_cases
from .pr_summary import (
    available_kinds,
    discover_changed_skills,
    render_rubric_pr_summary,
    replace_rubric_summary_section,
)
from .report import load_raw_run_payloads, normalize_kind, render_reports_for_run_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex-eval-harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List discovered eval cases")
    list_parser.add_argument("--root", default=".", help="Repository root")
    list_parser.add_argument("--skill", default="", help="Optional skill directory path filter")

    report_parser = subparsers.add_parser("report", help="Render Markdown and benchmark JSON from raw eval results")
    report_parser.add_argument("--repo-root", default=".", help="Repository root; defaults to current directory or nearest parent with skills/")
    report_parser.add_argument("--run-root", default="", help="Specific .workspace/codex-evals/<skill>/<run-id> directory")
    report_parser.add_argument("--kind", required=True, choices=("validation", "sanity", "rubric", "runtime"), help="Report kind to render")
    report_parser.add_argument("--skill", default="", help="Skill directory path or skill name; optional with --run-root")
    report_parser.add_argument("--output-dir", default="", help="Directory for latest report copies; defaults to <repo-root>/eval-reports")

    changed_parser = subparsers.add_parser("changed-skills", help="List changed skill names for a PR diff")
    changed_parser.add_argument("--repo-root", default=".", help="Repository root")
    changed_parser.add_argument("--base", required=True, help="Base git revision")
    changed_parser.add_argument("--head", required=True, help="Head git revision")

    kinds_parser = subparsers.add_parser("eval-kinds", help="List available eval kinds for a skill")
    kinds_parser.add_argument("--repo-root", default=".", help="Repository root")
    kinds_parser.add_argument("--skill", required=True, help="Skill name or skills/<name> path")

    summary_parser = subparsers.add_parser("pr-rubric-summary", help="Render or insert PR-body before/after rubric summaries")
    summary_parser.add_argument("--repo-root", default=".", help="Repository root")
    summary_parser.add_argument("--skill", action="append", default=[], help="Skill name or skills/<name> path; repeatable")
    summary_parser.add_argument("--skills-file", default="", help="Newline-delimited skill names")
    summary_parser.add_argument("--body-file", default="", help="Existing PR body to update")
    summary_parser.add_argument("--output", default="", help="Output file; defaults to stdout")
    summary_parser.add_argument("--base-report-root", default="", help="Directory containing base eval-reports copies")
    summary_parser.add_argument("--base-label", default="base", help="Label for the before report")
    summary_parser.add_argument("--after-label", default="this PR", help="Label for the after report")
    summary_parser.add_argument("--missing-after-note", default="not run", help="Text for missing after rubric report")

    args = parser.parse_args(argv)
    if args.command == "list":
        repo_root = infer_repo_root(Path(args.root).resolve())
        skill = Path(args.skill).expanduser().resolve().name if args.skill else None
        cases = discover_cases(
            repo_root,
            skill=skill,
        )
        for case in cases:
            print(f"{case.skill:16} {case.language}/{case.service:24} {case.prompt_id:18} {case.id}")
        print(f"{len(cases)} eval case(s)")
        return 0
    if args.command == "report":
        repo_root = infer_repo_root(Path(args.repo_root).expanduser().resolve())
        skill = skill_name(args.skill)
        output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else None
        run_roots = [Path(args.run_root).expanduser().resolve()] if args.run_root else latest_run_roots(repo_root, skill, args.kind)
        if not run_roots:
            target = f" for {skill}" if skill else ""
            parser.error(f"no raw {args.kind} eval runs found{target}")
        for run_root in run_roots:
            report_path, benchmark_path = render_reports_for_run_root(run_root, args.kind, skill=skill, output_dir=output_dir)
            print(f"wrote {report_path}")
            print(f"wrote {benchmark_path}")
        return 0
    if args.command == "changed-skills":
        repo_root = infer_repo_root(Path(args.repo_root).expanduser().resolve())
        for skill in discover_changed_skills(repo_root, args.base, args.head):
            print(skill)
        return 0
    if args.command == "eval-kinds":
        repo_root = infer_repo_root(Path(args.repo_root).expanduser().resolve())
        for kind in available_kinds(repo_root, skill_name(args.skill) or args.skill):
            print(kind)
        return 0
    if args.command == "pr-rubric-summary":
        repo_root = infer_repo_root(Path(args.repo_root).expanduser().resolve())
        skills = [skill_name(skill) or skill for skill in args.skill]
        if args.skills_file:
            skills_path = Path(args.skills_file).expanduser()
            skills.extend(
                skill_name(line.strip()) or line.strip()
                for line in skills_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        base_report_root = Path(args.base_report_root).expanduser().resolve() if args.base_report_root else None
        section = render_rubric_pr_summary(
            repo_root,
            skills,
            base_report_root=base_report_root,
            base_label=args.base_label,
            after_label=args.after_label,
            missing_after_note=args.missing_after_note,
        )
        output = section
        if args.body_file:
            body = Path(args.body_file).expanduser().read_text(encoding="utf-8")
            output = replace_rubric_summary_section(body, section)
        if args.output:
            Path(args.output).expanduser().write_text(output, encoding="utf-8")
        else:
            print(output, end="")
        return 0
    return 1


def skill_name(value: str) -> str | None:
    if not value:
        return None
    return Path(value.rstrip("/")).expanduser().name


def infer_repo_root(start: Path) -> Path:
    current = start if start.is_dir() else start.parent
    for candidate in (current, *current.parents):
        if (candidate / "skills").is_dir():
            return candidate
    return start


def latest_run_roots(repo_root: Path, skill: str | None, kind: str) -> list[Path]:
    root = repo_root / ".workspace" / "codex-evals"
    if not root.is_dir():
        return []
    skill_dirs = [root / skill] if skill else [path for path in sorted(root.iterdir()) if path.is_dir() and not path.name.startswith("_")]
    run_roots = []
    for skill_dir in skill_dirs:
        if not skill_dir.is_dir():
            continue
        for candidate in sorted((path for path in skill_dir.iterdir() if path.is_dir()), reverse=True):
            if run_root_has_kind(candidate, kind):
                run_roots.append(candidate)
                break
    return run_roots


def run_root_has_kind(run_root: Path, kind: str) -> bool:
    try:
        payloads = load_raw_run_payloads(run_root)
    except Exception:
        return False
    for payload in payloads:
        mode = payload.get("mode")
        if kind == "validation" and mode == "validation":
            return True
        if mode != "validation" and normalize_kind(str(payload.get("eval_kind", ""))) == kind:
            return True
    return False
