from __future__ import annotations

import json
import shutil
from pathlib import Path

from .models import CaseResult


def write_reports(repo_root: Path, run_root: Path, skill: str, results: list[CaseResult]) -> None:
    benchmark = build_benchmark(skill, results)
    benchmark_path = run_root / "benchmark.json"
    benchmark_path.write_text(json.dumps(benchmark, indent=2), encoding="utf-8")

    report = render_report(skill, results)
    report_path = run_root / "report.md"
    report_path.write_text(report, encoding="utf-8")

    latest_dir = repo_root / "eval-reports" / skill
    latest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(report_path, latest_dir / "REPORT.md")
    shutil.copyfile(benchmark_path, latest_dir / "benchmark.json")


def build_benchmark(skill: str, results: list[CaseResult]) -> dict:
    rows = []
    for result in results:
        rows.append(
            {
                "id": result.id,
                "base_id": result.base_id,
                "case": f"{result.language}/{result.service}",
                "prompt_id": result.prompt_id,
                "with_skill": side_summary(result.with_skill),
                "baseline": side_summary(result.baseline),
            }
        )
    return {
        "skill": skill,
        "runs": rows,
        "summary": {
            "case_count": len(results),
            "with_skill_avg": average([r.with_skill.deterministic_grade.pass_rate for r in results]),
            "baseline_guard_avg": average([r.baseline.deterministic_grade.pass_rate for r in results]),
        },
    }


def side_summary(side) -> dict:
    return {
        "exit_code": side.exit_code,
        "pass_rate": side.deterministic_grade.pass_rate,
        "passed": side.deterministic_grade.passed,
        "total": side.deterministic_grade.total,
        "command_count": side.command_count,
        "tokens": side.tokens,
        "errors": side.errors,
        "trace_path": side.trace_path,
        "final_message_path": side.final_message_path,
        "qualitative_grade_path": side.qualitative_grade_path,
    }


def average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def render_report(skill: str, results: list[CaseResult]) -> str:
    lines = [
        f"# {skill} Codex Eval Report",
        "",
        "| Case | Prompt | With Skill Checks | Baseline Guards | Commands (ws/base) | Tokens (ws/base) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for result in results:
        ws = result.with_skill
        base = result.baseline
        lines.append(
            "| {case} | {prompt} | {ws:.0%} ({wsp}/{wst}) | {base:.0%} ({bp}/{bt}) | {wc}/{bc} | {wt}/{btok} |".format(
                case=f"{result.language}/{result.service}",
                prompt=result.prompt_id,
                ws=ws.deterministic_grade.pass_rate,
                wsp=ws.deterministic_grade.passed,
                wst=ws.deterministic_grade.total,
                base=base.deterministic_grade.pass_rate,
                bp=base.deterministic_grade.passed,
                bt=base.deterministic_grade.total,
                wc=ws.command_count,
                bc=base.command_count,
                wt=ws.tokens,
                btok=base.tokens,
            )
        )
    lines.extend(["", "## Deterministic Checks", ""])
    for result in results:
        lines.extend(render_case_checks(result))
    return "\n".join(lines) + "\n"


def render_case_checks(result: CaseResult) -> list[str]:
    lines = [
        f"### {result.language}/{result.service} ({result.prompt_id})",
        "",
        "| Side | Check | Result | Evidence |",
        "|---|---|---|---|",
    ]
    for side_name, side in (("with_skill", result.with_skill), ("baseline", result.baseline)):
        for check in side.deterministic_grade.checks:
            status = "PASS" if check.passed else "FAIL"
            evidence = check.evidence.replace("\n", " ")[:240]
            lines.append(f"| {side_name} | {check.id} | {status} | {evidence} |")
    lines.append("")
    return lines
