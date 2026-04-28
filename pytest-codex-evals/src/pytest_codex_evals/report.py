from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .models import CaseResult, GradeCheckResult, SideResult, ValidationResult


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


def write_combined_session_reports(runs: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for run in runs:
        if not run.get("results"):
            continue
        key = (str(run["repo_root"]), str(run["run_root"]), run["skill"])
        grouped.setdefault(key, []).append(run)

    for run_group in grouped.values():
        first = run_group[0]
        repo_root = first["repo_root"]
        run_root = first["run_root"]
        skill = first["skill"]
        validation_results: list[ValidationResult] = []
        validation_metadata: dict[str, Any] = {}
        live_runs: list[dict[str, Any]] = []
        for run in run_group:
            if run["mode"] == "validation":
                validation_results.extend(run["results"])
                validation_metadata = run.get("metadata", validation_metadata)
            elif run["mode"] in LIVE_MODES:
                live_runs.append(run)

        benchmark = build_combined_benchmark(repo_root, run_root, skill, validation_results, validation_metadata, live_runs)
        report = render_combined_report(skill, benchmark)
        benchmark_path = run_root / "benchmark.json"
        report_path = run_root / "report.md"
        benchmark_path.parent.mkdir(parents=True, exist_ok=True)
        benchmark_path.write_text(json.dumps(benchmark, indent=2), encoding="utf-8")
        report_path.write_text(report, encoding="utf-8")

        latest_dir = repo_root / "eval-reports" / skill / report_key(benchmark)
        latest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(report_path, latest_dir / "report.md")
        shutil.copyfile(benchmark_path, latest_dir / "benchmark.json")


def build_combined_benchmark(
    repo_root: Path,
    run_root: Path,
    skill: str,
    validation_results: list[ValidationResult],
    validation_metadata: dict[str, Any],
    live_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    if not validation_metadata:
        validation_metadata = next((run.get("metadata", {}) for run in live_runs if run.get("metadata")), {})
    if not validation_metadata:
        validation_metadata = {"mode": "validation", "skill": skill, "run_id": run_root.name, "repo_root": str(repo_root)}
    validation = build_validation_benchmark(repo_root, skill, validation_results, report_metadata(skill, "validation", run_root, validation_metadata))

    live = []
    for run in sorted(live_runs, key=lambda item: item["mode"]):
        result_paths = collect_existing_result_paths(repo_root, run["run_root"], run["results"])
        live.append(
            build_live_benchmark(
                skill,
                run["mode"],
                run["results"],
                report_metadata(skill, run["mode"], run["run_root"], run.get("metadata")),
                result_paths,
            )
        )

    metadata = combined_metadata(skill, run_root, validation_metadata, live)
    return {
        "skill": skill,
        "metadata": metadata,
        "validation": validation,
        "live": live,
        "deterministic_failures": collect_combined_failures(live, "deterministic"),
        "qualitative_failures": collect_combined_failures(live, "qualitative"),
        "runtime_failures": collect_combined_failures(live, "runtime"),
    }


def collect_existing_result_paths(
    repo_root: Path,
    run_root: Path,
    results: list[CaseResult],
) -> dict[str, dict[str, str]]:
    paths: dict[str, dict[str, str]] = {}
    for base_id, group in grouped_case_results(results).items():
        first = group[0]
        eval_dir = run_root / "results" / first.language / first.service / eval_kind(base_id)
        side_paths: dict[str, str] = {}
        for name in ("eval", "with_skill", "with_baseline"):
            path = eval_dir / f"{name}.json"
            if path.is_file():
                side_paths[name] = relative_to_repo(repo_root, path)
        paths[base_id] = side_paths
    return paths


def combined_metadata(
    skill: str,
    run_root: Path,
    validation_metadata: dict[str, Any],
    live: list[dict[str, Any]],
) -> dict[str, Any]:
    live_metadata = [item.get("metadata", {}) for item in live]
    metadata_sources = live_metadata or [validation_metadata]
    modes = [item.get("mode", "validation") for item in live] or ["validation"]
    eval_kinds = sorted({str(meta.get("eval_kind") or "-") for meta in metadata_sources if meta.get("eval_kind")}) or ["validation"]
    agent_models = sorted({str(meta.get("agent_model") or "-") for meta in metadata_sources if meta.get("agent_model")}) or ["-"]
    judge_models = sorted({str(meta.get("judge_model") or "-") for meta in metadata_sources if meta.get("judge_model")}) or ["-"]
    config_paths = sorted({str(meta.get("config_path") or "-") for meta in [validation_metadata, *live_metadata] if meta.get("config_path")}) or ["-"]
    return {
        "mode": ", ".join(modes),
        "eval_kind": ", ".join(eval_kinds),
        "skill": skill,
        "run_id": run_root.name,
        "agent_model": ", ".join(agent_models),
        "judge_model": ", ".join(judge_models),
        "qualitative_enabled": any(bool(meta.get("qualitative_enabled")) for meta in metadata_sources),
        "runtime_enabled": any(bool(meta.get("runtime_enabled")) for meta in metadata_sources),
        "workers": ", ".join(sorted({str(meta.get("workers") or "-") for meta in metadata_sources if meta.get("workers")})) or "-",
        "config_path": ", ".join(config_paths),
    }


def render_combined_report(skill: str, benchmark: dict[str, Any]) -> str:
    lines = [
        f"# {skill} Codex Eval Report",
        "",
        "## Environment",
        "",
        "| Field | Value |",
        "|---|---|",
    ]
    for label, key in (
        ("Modes", "mode"),
        ("Eval kind", "eval_kind"),
        ("Skill", "skill"),
        ("Run ID", "run_id"),
        ("Agent model", "agent_model"),
        ("Judge model", "judge_model"),
        ("Qualitative enabled", "qualitative_enabled"),
        ("Runtime enabled", "runtime_enabled"),
        ("Workers", "workers"),
        ("Config", "config_path"),
    ):
        value = benchmark["metadata"].get(key)
        if key == "judge_model" and not benchmark["metadata"].get("qualitative_enabled"):
            value = "-"
        lines.append(f"| {label} | {markdown_cell(value)} |")

    lines.extend(render_validation_section(benchmark["validation"]))
    lines.extend(render_live_section("Deterministic", benchmark["live"], "deterministic", benchmark["deterministic_failures"]))
    lines.extend(render_live_section("Qualitative", benchmark["live"], "qualitative", benchmark["qualitative_failures"]))
    lines.extend(render_live_section("Runtime", benchmark["live"], "runtime", benchmark["runtime_failures"]))
    lines.extend(["", "## Result JSON", ""])
    lines.append("File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.")
    return "\n".join(lines) + "\n"


def render_validation_section(validation: dict[str, Any]) -> list[str]:
    lines = [
        "",
        "## Validation",
        "",
        "| Eval | Service | Prompts | Eval File | Deterministic Checks | Qualitative Checks | Runtime Checks |",
        "|---|---|---:|---|---:|---:|---:|",
    ]
    evals = validation.get("evals", [])
    if not evals:
        lines.append("| - | - | 0 | - | 0 | 0 | 0 |")
        return lines
    for item in evals:
        lines.append(
            "| {eval_id} | {service} | {prompts} | {path} | {det} | {qual} | {runtime} |".format(
                eval_id=markdown_cell(item["id"]),
                service=markdown_cell(item["case"]),
                prompts=item["prompt_count"],
                path=markdown_cell(item["definition_path"]),
                det=item["deterministic_check_count"],
                qual=item["qualitative_check_count"],
                runtime=item.get("runtime_check_count", 0),
            )
        )
    return lines


def render_live_section(title: str, live_runs: list[dict[str, Any]], category: str, failures: list[dict[str, str]]) -> list[str]:
    lines = [
        "",
        f"## {title}",
        "",
        "| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    rows = []
    for live in live_runs:
        for item in live.get("evals", []):
            rows.append(
                "| {mode} | {eval_id} | {service} | {prompts} | {ws} | {ws_tokens} | {ws_time} | {base} | {base_tokens} | {base_time} |".format(
                    mode=markdown_cell(live["mode"]),
                    eval_id=markdown_cell(item["id"]),
                    service=markdown_cell(item["case"]),
                    prompts=item["prompt_count"],
                    ws=format_category(item.get("with_skill"), category),
                    ws_tokens=format_tokens(item.get("with_skill")),
                    ws_time=format_duration(item.get("with_skill")),
                    base=format_category(item.get("with_baseline"), category),
                    base_tokens=format_tokens(item.get("with_baseline")),
                    base_time=format_duration(item.get("with_baseline")),
                )
            )
    if rows:
        lines.extend(rows)
    else:
        lines.append("| - | - | - | 0 | - | - | - | - | - | - |")

    lines.extend(["", f"### {title} Failures", ""])
    if not failures:
        lines.append(f"No {title.lower()} failures.")
    else:
        lines.extend(["| Mode | Service | Side | Prompt | Result | Evidence |", "|---|---|---|---|---|---|"])
        for failure in failures:
            lines.append(
                "| {mode} | {service} | {side} | {prompt} | {result} | {evidence} |".format(
                    mode=markdown_cell(failure.get("mode")),
                    service=markdown_cell(failure["service"]),
                    side=markdown_cell(failure["side"]),
                    prompt=markdown_cell(failure["prompt"]),
                    result=markdown_cell(failure["result"]),
                    evidence=markdown_cell(truncate(failure["evidence"], 320)),
                )
            )
    return lines


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
        "deterministic": check_summary(side, "deterministic"),
        "runtime": check_summary(side, "runtime"),
        "qualitative": load_qualitative_grade(side),
        "command_count": side.command_count,
        "duration_seconds": side.duration_seconds,
        "agent_duration_seconds": side.agent_duration_seconds,
        "qualitative_duration_seconds": side.qualitative_duration_seconds,
        "tokens": side.tokens,
        "agent_tokens": side.agent_tokens,
        "qualitative_tokens": side.qualitative_tokens,
        "errors": side.errors,
        "trace_path": side.trace_path,
        "final_message_path": side.final_message_path,
        "qualitative_grade_path": side.qualitative_grade_path,
    }


def check_summary(side: SideResult, category: str) -> dict[str, Any]:
    checks = checks_for_category(side, category)
    total = sum(1 for check in checks if not check.skipped)
    passed = sum(1 for check in checks if check.passed and not check.skipped)
    skipped = sum(1 for check in checks if check.skipped)
    return {
        "pass_rate": 1.0 if total == 0 else passed / total,
        "passed": passed,
        "total": total,
        "skipped": skipped,
        "checks": [check.model_dump(mode="json") for check in checks],
    }


def checks_for_category(side: SideResult, category: str) -> list[GradeCheckResult]:
    return [check for check in side.deterministic_grade.checks if check.category == category]


def aggregate_check_category(sides: list[SideResult], category: str) -> dict[str, Any]:
    checks = [check for side in sides for check in checks_for_category(side, category)]
    return {
        "passed": sum(1 for check in checks if check.passed and not check.skipped),
        "total": sum(1 for check in checks if not check.skipped),
        "skipped": sum(1 for check in checks if check.skipped),
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
        "deterministic": aggregate_check_category(sides, "deterministic"),
        "runtime": aggregate_check_category(sides, "runtime"),
        "qualitative": None
        if not qualitative
        else {
            "passed": qualitative_passed,
            "total": qualitative_total,
            "average_score": average(scores) if scores else None,
        },
        "command_count": sum(side.command_count for side in sides),
        "duration_seconds": round(sum(side.duration_seconds for side in sides), 3),
        "agent_duration_seconds": round(sum(side.agent_duration_seconds for side in sides), 3),
        "qualitative_duration_seconds": round(sum(side.qualitative_duration_seconds for side in sides), 3),
        "tokens": sum(side.tokens for side in sides),
        "agent_tokens": sum(side.agent_tokens for side in sides),
        "qualitative_tokens": sum(side.qualitative_tokens for side in sides),
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
                if check.passed or check.skipped:
                    continue
                category = check.category
                failures.append(
                    {
                        "service": service,
                        "side": side_key,
                        "prompt": result.prompt_id,
                        "category": category,
                        "result": f"{category}:{check.id} FAIL",
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
                        "category": "qualitative",
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
                        "category": "qualitative",
                        "result": "qualitative:overall FAIL",
                        "evidence": str(qualitative.get("notes") or "overall qualitative grade failed"),
                    }
                )
    return failures


def collect_combined_failures(live_runs: list[dict[str, Any]], category: str) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for live in live_runs:
        mode = live.get("mode", "")
        for failure in live.get("failures", []):
            if failure.get("category") != category:
                continue
            with_mode = dict(failure)
            with_mode["mode"] = str(mode)
            failures.append(with_mode)
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
        ("Eval kind", "eval_kind"),
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
            "| Eval | Service | Prompts | With Skill Deterministic | With Skill Qualitative | With Skill Tokens | With Skill Time | With Baseline Deterministic | With Baseline Qualitative | Baseline Tokens | Baseline Time |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in benchmark["evals"]:
        lines.append(
            "| {eval_id} | {service} | {prompts} | {ws_det} | {ws_qual} | {ws_tokens} | {ws_time} | {base_det} | {base_qual} | {base_tokens} | {base_time} |".format(
                eval_id=markdown_cell(item["id"]),
                service=markdown_cell(item["case"]),
                prompts=item["prompt_count"],
                ws_det=format_deterministic(item.get("with_skill")),
                ws_qual=format_qualitative(item.get("with_skill")),
                ws_tokens=format_tokens(item.get("with_skill")),
                ws_time=format_duration(item.get("with_skill")),
                base_det=format_deterministic(item.get("with_baseline")),
                base_qual=format_qualitative(item.get("with_baseline")),
                base_tokens=format_tokens(item.get("with_baseline")),
                base_time=format_duration(item.get("with_baseline")),
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
                "runtime_check_count": first.runtime_check_count,
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
            "runtime_check_count": sum(result.runtime_check_count for result in results),
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
        ("Eval kind", "eval_kind"),
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
            "| Eval | Service | Prompts | Eval File | Deterministic Checks | Qualitative Checks | Runtime Checks |",
            "|---|---|---:|---|---:|---:|---:|",
        ]
    )
    for item in benchmark["evals"]:
        lines.append(
            "| {eval_id} | {service} | {prompts} | {path} | {det} | {qual} | {runtime} |".format(
                eval_id=markdown_cell(item["id"]),
                service=markdown_cell(item["case"]),
                prompts=item["prompt_count"],
                path=markdown_cell(item["definition_path"]),
                det=item["deterministic_check_count"],
                qual=item["qualitative_check_count"],
                runtime=item.get("runtime_check_count", 0),
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
    normalized.setdefault("eval_kind", "validation" if mode == "validation" else "standard")
    normalized.setdefault("skill", skill)
    normalized.setdefault("run_id", run_root.name)
    normalized.setdefault("agent_model", "-")
    normalized.setdefault("judge_model", "-")
    normalized.setdefault("qualitative_enabled", "-")
    normalized.setdefault("runtime_enabled", "-")
    normalized.setdefault("workers", "-")
    normalized.setdefault("config_path", "-")
    return normalized


def report_key(benchmark: dict[str, Any]) -> str:
    metadata = benchmark.get("metadata", {})
    value = str(metadata.get("eval_kind") or "").strip().lower()
    if value and "," not in value:
        return safe_name(value)
    mode = str(metadata.get("mode") or "validation").strip().lower()
    if mode == "with_skill":
        return "skill"
    if mode == "with_baseline":
        return "baseline"
    return safe_name(mode or "validation")


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


def format_category(side: dict[str, Any] | None, category: str) -> str:
    if side is None:
        return "-"
    if category == "qualitative":
        return format_qualitative(side)
    data = side.get(category)
    if not data:
        return "-"
    total = int(data["total"])
    passed = int(data["passed"])
    skipped = int(data.get("skipped") or 0)
    if total == 0 and skipped == 0:
        return "-"
    if total == 0 and skipped:
        return f"{skipped} skipped"
    value = format_count(passed, total)
    if skipped:
        return f"{value}, {skipped} skipped"
    return value


def format_qualitative(side: dict[str, Any] | None) -> str:
    if side is None or side.get("qualitative") is None:
        return "-"
    qualitative = side["qualitative"]
    value = format_count(int(qualitative["passed"]), int(qualitative["total"]))
    score = qualitative.get("average_score")
    if score is None:
        return value
    return f"{value}, avg score {score:.0f}"


def format_tokens(side: dict[str, Any] | None) -> str:
    if side is None:
        return "-"
    tokens = int(side.get("tokens") or 0)
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.1f}K"
    return str(tokens)


def format_duration(side: dict[str, Any] | None) -> str:
    if side is None:
        return "-"
    seconds = float(side.get("duration_seconds") or 0.0)
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h"
    if seconds >= 60:
        return f"{seconds / 60:.1f}m"
    return f"{seconds:.1f}s"


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
