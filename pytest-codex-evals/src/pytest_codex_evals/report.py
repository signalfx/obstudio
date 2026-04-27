from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .models import CaseResult, SideResult, ValidationResult


LIVE_MODES = {"with_skill", "with_baseline", "ab"}
SIDE_ATTRS = {
    "with_skill": "with_skill",
    "with_baseline": "baseline",
}


def write_side_reports(
    repo_root: Path,
    run_root: Path,
    skill: str,
    mode: str,
    results: list[CaseResult],
    metadata: dict[str, Any] | None = None,
) -> None:
    write_live_reports(repo_root, run_root, skill, mode, results, metadata)


def write_ab_reports(
    repo_root: Path,
    run_root: Path,
    skill: str,
    results: list[CaseResult],
    metadata: dict[str, Any] | None = None,
) -> None:
    write_live_reports(repo_root, run_root, skill, "ab", results, metadata)


def write_live_reports(
    repo_root: Path,
    run_root: Path,
    skill: str,
    mode: str,
    results: list[CaseResult],
    metadata: dict[str, Any] | None = None,
) -> None:
    if mode not in LIVE_MODES:
        raise ValueError(f"{mode} is not a live report mode")

    normalized_metadata = report_metadata(skill, mode, run_root, metadata)
    result_paths = write_live_result_jsons(repo_root, run_root, mode, results)
    benchmark = build_live_benchmark(skill, mode, results, normalized_metadata, result_paths)
    report = render_live_report(skill, benchmark)

    prefix = mode
    benchmark_path = run_root / f"{prefix}-benchmark.json"
    report_path = run_root / f"{prefix}-report.md"
    benchmark_path.parent.mkdir(parents=True, exist_ok=True)
    benchmark_path.write_text(json.dumps(benchmark, indent=2), encoding="utf-8")
    report_path.write_text(report, encoding="utf-8")

    shutil.copyfile(report_path, run_root / "report.md")
    shutil.copyfile(benchmark_path, run_root / "benchmark.json")

    latest_dir = repo_root / "eval-reports" / skill
    latest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(report_path, latest_dir / f"{prefix.upper()}_REPORT.md")
    shutil.copyfile(benchmark_path, latest_dir / f"{prefix}-benchmark.json")
    shutil.copyfile(report_path, latest_dir / "REPORT.md")
    shutil.copyfile(benchmark_path, latest_dir / "benchmark.json")


def write_validation_reports(
    repo_root: Path,
    run_root: Path,
    skill: str,
    results: list[ValidationResult],
    metadata: dict[str, Any] | None = None,
) -> None:
    normalized_metadata = report_metadata(skill, "validation", run_root, metadata)
    benchmark = build_validation_benchmark(repo_root, skill, results, normalized_metadata)
    benchmark_path = run_root / "validation-benchmark.json"
    benchmark_path.parent.mkdir(parents=True, exist_ok=True)
    benchmark_path.write_text(json.dumps(benchmark, indent=2), encoding="utf-8")

    report = render_validation_report(skill, benchmark)
    report_path = run_root / "validation-report.md"
    report_path.write_text(report, encoding="utf-8")

    latest_dir = repo_root / "eval-reports" / skill
    latest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(report_path, latest_dir / "VALIDATION_REPORT.md")
    shutil.copyfile(benchmark_path, latest_dir / "validation-benchmark.json")


def write_live_result_jsons(
    repo_root: Path,
    run_root: Path,
    mode: str,
    results: list[CaseResult],
) -> dict[str, dict[str, str]]:
    paths: dict[str, dict[str, str]] = {}
    for base_id, group in grouped_case_results(results).items():
        first = group[0]
        eval_dir = run_root / "results" / first.language / first.service / eval_kind(base_id)
        eval_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "mode": mode,
            "id": base_id,
            "skill": first.skill,
            "language": first.language,
            "service": first.service,
            "prompt_count": len(group),
            "prompts": [case_result_payload(result) for result in group],
            "aggregate": aggregate_case_group(group),
        }
        eval_path = eval_dir / "eval.json"
        eval_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        side_paths = {"eval": relative_to_repo(repo_root, eval_path)}
        for side_key in SIDE_ATTRS:
            side_payload = {
                "mode": mode,
                "side": side_key,
                "id": base_id,
                "skill": first.skill,
                "language": first.language,
                "service": first.service,
                "prompt_count": len(group),
                "prompts": [side_result_payload(result, side_key) for result in group],
                "aggregate": aggregate_side(group, side_key),
            }
            side_path = eval_dir / f"{side_key}.json"
            side_path.write_text(json.dumps(side_payload, indent=2), encoding="utf-8")
            side_paths[side_key] = relative_to_repo(repo_root, side_path)
        paths[base_id] = side_paths
    return paths


def case_result_payload(result: CaseResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "base_id": result.base_id,
        "prompt_id": result.prompt_id,
        "case": f"{result.language}/{result.service}",
        "with_skill": side_summary(result.with_skill),
        "with_baseline": side_summary(result.baseline),
    }


def side_result_payload(result: CaseResult, side_key: str) -> dict[str, Any]:
    side = side_for_key(result, side_key)
    return {
        "id": result.id,
        "base_id": result.base_id,
        "prompt_id": result.prompt_id,
        "case": f"{result.language}/{result.service}",
        "result": side_summary(side),
    }


def side_summary(side: SideResult | None) -> dict[str, Any] | None:
    if side is None:
        return None
    return {
        "exit_code": side.exit_code,
        "deterministic": {
            "pass_rate": side.deterministic_grade.pass_rate,
            "passed": side.deterministic_grade.passed,
            "total": side.deterministic_grade.total,
            "checks": [check.model_dump(mode="json") for check in side.deterministic_grade.checks],
        },
        "qualitative": load_qualitative_grade(side),
        "command_count": side.command_count,
        "tokens": side.tokens,
        "errors": side.errors,
        "trace_path": side.trace_path,
        "final_message_path": side.final_message_path,
        "qualitative_grade_path": side.qualitative_grade_path,
    }


def build_live_benchmark(
    skill: str,
    mode: str,
    results: list[CaseResult],
    metadata: dict[str, Any],
    result_paths: dict[str, dict[str, str]],
) -> dict[str, Any]:
    evals = []
    for base_id, group in grouped_case_results(results).items():
        aggregate = aggregate_case_group(group)
        aggregate["result_paths"] = result_paths.get(base_id, {})
        evals.append(aggregate)

    failures = collect_failures(results)
    return {
        "mode": mode,
        "skill": skill,
        "metadata": metadata,
        "evals": evals,
        "failures": failures,
        "summary": {
            "eval_count": len(evals),
            "case_count": len(results),
            "prompt_count": len(results),
            "failure_count": len(failures),
            "with_skill": aggregate_side(results, "with_skill"),
            "with_baseline": aggregate_side(results, "with_baseline"),
        },
    }


def aggregate_case_group(group: list[CaseResult]) -> dict[str, Any]:
    first = group[0]
    return {
        "id": first.base_id,
        "case": f"{first.language}/{first.service}",
        "language": first.language,
        "service": first.service,
        "prompt_count": len(group),
        "prompts": [result.prompt_id for result in group],
        "with_skill": aggregate_side(group, "with_skill"),
        "with_baseline": aggregate_side(group, "with_baseline"),
    }


def aggregate_side(results: list[CaseResult], side_key: str) -> dict[str, Any] | None:
    sides = [side for result in results if (side := side_for_key(result, side_key)) is not None]
    if not sides:
        return None

    qualitative = [grade for side in sides if (grade := load_qualitative_grade(side)) is not None]
    qualitative_total = sum(int(grade["total"]) for grade in qualitative)
    qualitative_passed = sum(int(grade["passed"]) for grade in qualitative)
    scores = [int(grade["score"]) for grade in qualitative if isinstance(grade.get("score"), int)]
    return {
        "prompt_count": len(sides),
        "deterministic": {
            "passed": sum(side.deterministic_grade.passed for side in sides),
            "total": sum(side.deterministic_grade.total for side in sides),
        },
        "qualitative": None
        if not qualitative
        else {
            "passed": qualitative_passed,
            "total": qualitative_total,
            "average_score": average(scores) if scores else None,
        },
        "command_count": sum(side.command_count for side in sides),
        "tokens": sum(side.tokens for side in sides),
        "error_count": sum(len(side.errors) for side in sides),
    }


def collect_failures(results: list[CaseResult]) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for result in sorted(results, key=lambda item: (item.language, item.service, item.base_id, item.prompt_id)):
        service = f"{result.language}/{result.service}"
        for side_key in SIDE_ATTRS:
            side = side_for_key(result, side_key)
            if side is None:
                continue
            for check in side.deterministic_grade.checks:
                if check.passed:
                    continue
                failures.append(
                    {
                        "service": service,
                        "side": side_key,
                        "prompt": result.prompt_id,
                        "result": f"deterministic:{check.id} FAIL",
                        "evidence": check.evidence,
                    }
                )
            qualitative = load_qualitative_grade(side)
            if qualitative is None:
                continue
            qualitative_failures = 0
            for check in qualitative.get("checks", []):
                if bool(check.get("pass")):
                    continue
                qualitative_failures += 1
                failures.append(
                    {
                        "service": service,
                        "side": side_key,
                        "prompt": result.prompt_id,
                        "result": f"qualitative:{check.get('id', 'check')} FAIL",
                        "evidence": str(check.get("evidence") or check.get("notes") or ""),
                    }
                )
            if not qualitative_failures and qualitative.get("overall_pass") is False:
                failures.append(
                    {
                        "service": service,
                        "side": side_key,
                        "prompt": result.prompt_id,
                        "result": "qualitative:overall FAIL",
                        "evidence": str(qualitative.get("notes") or "overall qualitative grade failed"),
                    }
                )
    return failures


def render_live_report(skill: str, benchmark: dict[str, Any]) -> str:
    lines = [
        f"# {skill} Codex Eval Report",
        "",
        "## Environment",
        "",
        "| Field | Value |",
        "|---|---|",
    ]
    for label, key in (
        ("Mode", "mode"),
        ("Skill", "skill"),
        ("Run ID", "run_id"),
        ("Agent model", "agent_model"),
        ("Judge model", "judge_model"),
        ("Qualitative enabled", "qualitative_enabled"),
        ("Workers", "workers"),
        ("Config", "config_path"),
    ):
        value = benchmark["metadata"].get(key)
        if key == "judge_model" and not benchmark["metadata"].get("qualitative_enabled"):
            value = "-"
        lines.append(f"| {label} | {markdown_cell(value)} |")

    lines.extend(
        [
            "",
            "## Eval Summary",
            "",
            "| Eval | Service | Prompts | With Skill Deterministic | With Skill Qualitative | With Baseline Deterministic | With Baseline Qualitative |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for item in benchmark["evals"]:
        lines.append(
            "| {eval_id} | {service} | {prompts} | {ws_det} | {ws_qual} | {base_det} | {base_qual} |".format(
                eval_id=markdown_cell(item["id"]),
                service=markdown_cell(item["case"]),
                prompts=item["prompt_count"],
                ws_det=format_deterministic(item.get("with_skill")),
                ws_qual=format_qualitative(item.get("with_skill")),
                base_det=format_deterministic(item.get("with_baseline")),
                base_qual=format_qualitative(item.get("with_baseline")),
            )
        )

    lines.extend(["", "## Failure Cases", ""])
    failures = benchmark["failures"]
    if not failures:
        lines.append("No deterministic or qualitative failures.")
    else:
        lines.extend(["| Service | Side | Prompt | Result | Evidence |", "|---|---|---|---|---|"])
        for failure in failures:
            lines.append(
                "| {service} | {side} | {prompt} | {result} | {evidence} |".format(
                    service=markdown_cell(failure["service"]),
                    side=markdown_cell(failure["side"]),
                    prompt=markdown_cell(failure["prompt"]),
                    result=markdown_cell(failure["result"]),
                    evidence=markdown_cell(truncate(failure["evidence"], 320)),
                )
            )

    lines.extend(["", "## Result JSON", ""])
    lines.append("File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.")
    return "\n".join(lines) + "\n"


def build_validation_benchmark(
    repo_root: Path,
    skill: str,
    results: list[ValidationResult],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    evals = []
    for base_id, group in grouped_validation_results(results).items():
        first = group[0]
        evals.append(
            {
                "id": first.base_id,
                "case": f"{first.language}/{first.service}",
                "language": first.language,
                "service": first.service,
                "prompt_count": len(group),
                "prompts": [result.prompt_id for result in group],
                "definition_path": relative_to_repo(repo_root, first.definition_path),
                "eval_dir": relative_to_repo(repo_root, first.fixture_dir),
                "skill_path": relative_to_repo(repo_root, first.skill_path),
                "deterministic_check_count": first.deterministic_check_count,
                "qualitative_check_count": first.qualitative_check_count,
            }
        )

    return {
        "mode": "validation",
        "skill": skill,
        "metadata": metadata,
        "evals": evals,
        "summary": {
            "eval_count": len(evals),
            "case_count": len(results),
            "prompt_count": len(results),
            "deterministic_check_count": sum(result.deterministic_check_count for result in results),
            "qualitative_check_count": sum(result.qualitative_check_count for result in results),
        },
    }


def render_validation_report(skill: str, benchmark: dict[str, Any]) -> str:
    lines = [
        f"# {skill} Codex Eval Validation Report",
        "",
        "This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.",
        "",
        "## Environment",
        "",
        "| Field | Value |",
        "|---|---|",
    ]
    for label, key in (
        ("Mode", "mode"),
        ("Skill", "skill"),
        ("Run ID", "run_id"),
        ("Config", "config_path"),
    ):
        lines.append(f"| {label} | {markdown_cell(benchmark['metadata'].get(key))} |")

    lines.extend(
        [
            "",
            "## Eval Summary",
            "",
            "| Eval | Service | Prompts | Eval File | Deterministic Checks | Qualitative Checks |",
            "|---|---|---:|---|---:|---:|",
        ]
    )
    for item in benchmark["evals"]:
        lines.append(
            "| {eval_id} | {service} | {prompts} | {path} | {det} | {qual} |".format(
                eval_id=markdown_cell(item["id"]),
                service=markdown_cell(item["case"]),
                prompts=item["prompt_count"],
                path=markdown_cell(item["definition_path"]),
                det=item["deterministic_check_count"],
                qual=item["qualitative_check_count"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def report_metadata(
    skill: str,
    mode: str,
    run_root: Path,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized = dict(metadata or {})
    normalized.setdefault("mode", mode)
    normalized.setdefault("skill", skill)
    normalized.setdefault("run_id", run_root.name)
    normalized.setdefault("agent_model", "-")
    normalized.setdefault("judge_model", "-")
    normalized.setdefault("qualitative_enabled", "-")
    normalized.setdefault("workers", "-")
    normalized.setdefault("config_path", "-")
    return normalized


def grouped_case_results(results: list[CaseResult]) -> dict[str, list[CaseResult]]:
    grouped: dict[str, list[CaseResult]] = {}
    for result in sorted(results, key=lambda item: (item.language, item.service, item.base_id, item.prompt_id)):
        grouped.setdefault(result.base_id, []).append(result)
    return grouped


def grouped_validation_results(results: list[ValidationResult]) -> dict[str, list[ValidationResult]]:
    grouped: dict[str, list[ValidationResult]] = {}
    for result in sorted(results, key=lambda item: (item.language, item.service, item.base_id, item.prompt_id)):
        grouped.setdefault(result.base_id, []).append(result)
    return grouped


def side_for_key(result: CaseResult, side_key: str) -> SideResult | None:
    return getattr(result, SIDE_ATTRS[side_key])


def load_qualitative_grade(side: SideResult) -> dict[str, Any] | None:
    if not side.qualitative_grade_path:
        return None
    path = Path(side.qualitative_grade_path)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    checks = data.get("checks") or []
    passed = sum(1 for check in checks if bool(check.get("pass")))
    normalized = {
        "overall_pass": data.get("overall_pass"),
        "score": data.get("score"),
        "passed": passed,
        "total": len(checks),
        "checks": checks,
        "path": side.qualitative_grade_path,
    }
    return normalized


def format_deterministic(side: dict[str, Any] | None) -> str:
    if side is None:
        return "-"
    deterministic = side["deterministic"]
    return format_count(int(deterministic["passed"]), int(deterministic["total"]))


def format_qualitative(side: dict[str, Any] | None) -> str:
    if side is None or side.get("qualitative") is None:
        return "-"
    qualitative = side["qualitative"]
    value = format_count(int(qualitative["passed"]), int(qualitative["total"]))
    score = qualitative.get("average_score")
    if score is None:
        return value
    return f"{value}, avg score {score:.0f}"


def format_count(passed: int, total: int) -> str:
    if total == 0:
        return "100% (0/0)"
    return f"{passed / total:.0%} ({passed}/{total})"


def average(values: list[int]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def eval_kind(base_id: str) -> str:
    return safe_name(base_id.rsplit("/", 1)[-1] or "eval")


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)


def truncate(value: str, limit: int) -> str:
    normalized = " ".join(str(value).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def markdown_cell(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value).replace("|", "\\|").replace("\n", " ")


def relative_to_repo(repo_root: Path, path: str | Path) -> str:
    absolute = Path(path)
    try:
        return str(absolute.relative_to(repo_root))
    except ValueError:
        return str(absolute)
