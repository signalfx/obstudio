from __future__ import annotations

import json
import shutil
from pathlib import Path

from .models import CaseResult, ValidationResult


def write_side_reports(repo_root: Path, run_root: Path, skill: str, mode: str, results: list[CaseResult]) -> None:
    label = "with_skill" if mode == "with_skill" else "with_baseline"
    side_name = label
    side_attr = "with_skill" if mode == "with_skill" else "baseline"

    benchmark = build_side_benchmark(skill, label, side_attr, results)
    benchmark_path = run_root / f"{label}-benchmark.json"
    benchmark_path.parent.mkdir(parents=True, exist_ok=True)
    benchmark_path.write_text(json.dumps(benchmark, indent=2), encoding="utf-8")

    report = render_side_report(skill, label, side_name, side_attr, results)
    report_path = run_root / f"{label}-report.md"
    report_path.write_text(report, encoding="utf-8")

    latest_dir = repo_root / "eval-reports" / skill
    latest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(report_path, latest_dir / f"{label.upper()}_REPORT.md")
    shutil.copyfile(benchmark_path, latest_dir / f"{label}-benchmark.json")


def write_ab_reports(repo_root: Path, run_root: Path, skill: str, results: list[CaseResult]) -> None:
    benchmark = build_benchmark(skill, results)
    benchmark_path = run_root / "ab-benchmark.json"
    benchmark_path.parent.mkdir(parents=True, exist_ok=True)
    benchmark_path.write_text(json.dumps(benchmark, indent=2), encoding="utf-8")

    report = render_report(skill, results)
    report_path = run_root / "ab-report.md"
    report_path.write_text(report, encoding="utf-8")

    shutil.copyfile(report_path, run_root / "report.md")
    shutil.copyfile(benchmark_path, run_root / "benchmark.json")

    latest_dir = repo_root / "eval-reports" / skill
    latest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(report_path, latest_dir / "AB_REPORT.md")
    shutil.copyfile(benchmark_path, latest_dir / "ab-benchmark.json")
    shutil.copyfile(report_path, latest_dir / "REPORT.md")
    shutil.copyfile(benchmark_path, latest_dir / "benchmark.json")


def write_validation_reports(repo_root: Path, run_root: Path, skill: str, results: list[ValidationResult]) -> None:
    benchmark = build_validation_benchmark(repo_root, skill, results)
    benchmark_path = run_root / "validation-benchmark.json"
    benchmark_path.parent.mkdir(parents=True, exist_ok=True)
    benchmark_path.write_text(json.dumps(benchmark, indent=2), encoding="utf-8")

    report = render_validation_report(repo_root, skill, results)
    report_path = run_root / "validation-report.md"
    report_path.write_text(report, encoding="utf-8")

    latest_dir = repo_root / "eval-reports" / skill
    latest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(report_path, latest_dir / "VALIDATION_REPORT.md")
    shutil.copyfile(benchmark_path, latest_dir / "validation-benchmark.json")


def build_benchmark(skill: str, results: list[CaseResult]) -> dict:
    rows = []
    for result in results:
        rows.append(
            {
                "id": result.id,
                "base_id": result.base_id,
                "case": f"{result.language}/{result.service}",
                "prompt_id": result.prompt_id,
                "with_skill": side_summary(required_side(result, "with_skill")),
                "baseline": side_summary(required_side(result, "baseline")),
            }
        )
    return {
        "mode": "ab",
        "skill": skill,
        "runs": rows,
        "summary": {
            "case_count": len(results),
            "with_skill_avg": average([required_side(r, "with_skill").deterministic_grade.pass_rate for r in results]),
            "baseline_guard_avg": average([required_side(r, "baseline").deterministic_grade.pass_rate for r in results]),
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
        f"# {skill} Codex A/B Eval Report",
        "",
        "| Case | Prompt | With Skill Checks | Baseline Guards | Commands (ws/base) | Tokens (ws/base) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for result in results:
        ws = required_side(result, "with_skill")
        base = required_side(result, "baseline")
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
        if side is None:
            continue
        for check in side.deterministic_grade.checks:
            status = "PASS" if check.passed else "FAIL"
            evidence = check.evidence.replace("\n", " ")[:240]
            lines.append(f"| {side_name} | {check.id} | {status} | {evidence} |")
    lines.append("")
    return lines


def build_side_benchmark(skill: str, mode: str, side_attr: str, results: list[CaseResult]) -> dict:
    rows = []
    for result in results:
        side = required_side(result, side_attr)
        rows.append(
            {
                "id": result.id,
                "base_id": result.base_id,
                "case": f"{result.language}/{result.service}",
                "prompt_id": result.prompt_id,
                side_attr: side_summary(side),
            }
        )
    return {
        "mode": mode,
        "skill": skill,
        "runs": rows,
        "summary": {
            "case_count": len(results),
            "pass_rate_avg": average([required_side(r, side_attr).deterministic_grade.pass_rate for r in results]),
        },
    }


def render_side_report(skill: str, mode: str, side_name: str, side_attr: str, results: list[CaseResult]) -> str:
    title = "With Skill" if mode == "with_skill" else "With Baseline"
    lines = [
        f"# {skill} Codex Eval Report - {title}",
        "",
        f"| Case | Prompt | {side_name} Checks | Commands | Tokens |",
        "|---|---|---:|---:|---:|",
    ]
    for result in results:
        side = required_side(result, side_attr)
        lines.append(
            "| {case} | {prompt} | {rate:.0%} ({passed}/{total}) | {commands} | {tokens} |".format(
                case=f"{result.language}/{result.service}",
                prompt=result.prompt_id,
                rate=side.deterministic_grade.pass_rate,
                passed=side.deterministic_grade.passed,
                total=side.deterministic_grade.total,
                commands=side.command_count,
                tokens=side.tokens,
            )
        )
    lines.extend(["", "## Deterministic Checks", ""])
    for result in results:
        lines.extend(render_case_checks(result))
    return "\n".join(lines) + "\n"


def required_side(result: CaseResult, side_attr: str):
    side = getattr(result, side_attr)
    if side is None:
        raise ValueError(f"{result.id}: missing {side_attr} result")
    return side


def build_validation_benchmark(repo_root: Path, skill: str, results: list[ValidationResult]) -> dict:
    rows = []
    for result in results:
        rows.append(
            {
                "id": result.id,
                "base_id": result.base_id,
                "case": f"{result.language}/{result.service}",
                "prompt_id": result.prompt_id,
                "definition_path": relative_to_repo(repo_root, result.definition_path),
                "eval_dir": relative_to_repo(repo_root, result.fixture_dir),
                "skill_path": relative_to_repo(repo_root, result.skill_path),
                "deterministic_check_count": result.deterministic_check_count,
                "qualitative_check_count": result.qualitative_check_count,
            }
        )
    return {
        "mode": "validation",
        "skill": skill,
        "runs": rows,
        "summary": {
            "case_count": len(results),
            "deterministic_check_count": sum(result.deterministic_check_count for result in results),
            "qualitative_check_count": sum(result.qualitative_check_count for result in results),
        },
    }


def render_validation_report(repo_root: Path, skill: str, results: list[ValidationResult]) -> str:
    lines = [
        f"# {skill} Codex Eval Validation Report",
        "",
        "This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex A/B execution.",
        "",
        "| Case | Prompt | Eval File | Deterministic Checks | Qualitative Checks |",
        "|---|---|---|---:|---:|",
    ]
    for result in results:
        lines.append(
            "| {case} | {prompt} | {path} | {det} | {qual} |".format(
                case=f"{result.language}/{result.service}",
                prompt=result.prompt_id,
                path=relative_to_repo(repo_root, result.definition_path),
                det=result.deterministic_check_count,
                qual=result.qualitative_check_count,
            )
        )
    lines.append("")
    return "\n".join(lines)


def relative_to_repo(repo_root: Path, path: str) -> str:
    absolute = Path(path)
    try:
        return str(absolute.relative_to(repo_root))
    except ValueError:
        return str(absolute)
