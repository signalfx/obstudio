#!/usr/bin/env python3
"""Generate a human-readable markdown report from skill eval benchmark JSONs.

Usage:
    uv run python generate_report.py                          # from latest workspace runs
    uv run python generate_report.py --dir tests/reports/2026-04-20  # from saved reports
    uv run python generate_report.py --output tests/reports/2026-04-20/REPORT.md
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = REPO_ROOT / "skill-eval-workspace"


def load_benchmarks(source_dir: Path | None = None) -> list[dict]:
    """Load benchmark JSONs from either a reports dir or workspace latest links."""
    benchmarks = []

    if source_dir:
        for f in sorted(source_dir.glob("*.json")):
            benchmarks.append(json.loads(f.read_text()))
    else:
        for latest in sorted(WORKSPACE_ROOT.glob("*/latest")):
            benchmark_file = latest / "benchmark.json"
            if benchmark_file.exists():
                benchmarks.append(json.loads(benchmark_file.read_text()))

    return benchmarks


def format_report(benchmarks: list[dict]) -> str:
    """Generate a markdown report from benchmark data."""
    lines = []

    # Header
    ts = benchmarks[0]["metadata"]["timestamp"] if benchmarks else ""
    run_date = ts[:10] if ts else datetime.now().strftime("%Y-%m-%d")
    lines.append(f"# Skill Eval Report — {run_date}")
    lines.append("")

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| Skill | With Skill | Baseline | Delta | Avg Time | Avg Tokens |")
    lines.append("|-------|-----------|----------|-------|----------|------------|")

    for b in benchmarks:
        name = b["metadata"]["skill_name"]
        ws = b["run_summary"]["with_skill"]
        wo = b["run_summary"]["without_skill"]
        delta = b["run_summary"]["delta"]

        ws_pct = f"{ws['pass_rate']['mean']*100:.0f}%"
        wo_pct = f"{wo['pass_rate']['mean']*100:.0f}%"
        delta_str = delta["pass_rate"]
        time_str = f"{ws['time_seconds']['mean']:.0f}s"
        tokens_str = f"{ws['tokens']['mean']:,.0f}"

        lines.append(f"| {name} | {ws_pct} | {wo_pct} | {delta_str} | {time_str} | {tokens_str} |")

    lines.append("")

    # Per-skill detail
    lines.append("## Detail by Skill")
    lines.append("")

    for b in benchmarks:
        name = b["metadata"]["skill_name"]
        lines.append(f"### {name}")
        lines.append("")

        # Group runs by eval
        evals: dict[int, dict] = {}
        for run in b["runs"]:
            eid = run["eval_id"]
            if eid not in evals:
                evals[eid] = {"name": run["eval_name"], "with_skill": None, "without_skill": None}
            evals[eid][run["configuration"]] = run

        for eid in sorted(evals.keys()):
            ev = evals[eid]
            lines.append(f"#### Eval {eid}: {ev['name']}")
            lines.append("")

            # Results row
            ws_run = ev.get("with_skill")
            wo_run = ev.get("without_skill")

            if ws_run and wo_run:
                ws_r = ws_run["result"]
                wo_r = wo_run["result"]
                lines.append(f"| | With Skill | Baseline |")
                lines.append(f"|---|---|---|")
                lines.append(f"| Pass rate | {ws_r['passed']}/{ws_r['total']} ({ws_r['pass_rate']*100:.0f}%) | {wo_r['passed']}/{wo_r['total']} ({wo_r['pass_rate']*100:.0f}%) |")
                lines.append(f"| Time | {ws_r['time_seconds']:.0f}s | {wo_r['time_seconds']:.0f}s |")
                lines.append(f"| Tokens | {ws_r['tokens']:,} | {wo_r['tokens']:,} |")
                lines.append("")

            # Assertions detail (with_skill)
            if ws_run and "expectations" in ws_run:
                lines.append("**Assertions (with skill):**")
                lines.append("")
                for exp in ws_run["expectations"]:
                    icon = "PASS" if exp["passed"] else "FAIL"
                    lines.append(f"- [{icon}] {exp['text']}")
                    if not exp["passed"]:
                        lines.append(f"  - Evidence: {exp['evidence']}")
                lines.append("")

            # Show failures from baseline if any
            if wo_run and "expectations" in wo_run:
                failures = [e for e in wo_run["expectations"] if not e["passed"]]
                if failures:
                    lines.append("**Baseline failures:**")
                    lines.append("")
                    for exp in failures:
                        lines.append(f"- [FAIL] {exp['text']}")
                        lines.append(f"  - Evidence: {exp['evidence']}")
                    lines.append("")

        lines.append("---")
        lines.append("")

    # Footer
    total_evals = sum(len(b["metadata"]["evals_run"]) for b in benchmarks)
    total_runs = sum(len(b["runs"]) for b in benchmarks)
    lines.append(f"*{len(benchmarks)} skills, {total_evals} evals, {total_runs} total runs.*")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate skill eval report")
    parser.add_argument("--dir", type=Path, help="Directory with benchmark JSON files")
    parser.add_argument("--output", "-o", type=Path, help="Output file (default: stdout)")
    args = parser.parse_args()

    benchmarks = load_benchmarks(args.dir)
    if not benchmarks:
        print("No benchmark data found.", file=sys.stderr)
        sys.exit(1)

    report = format_report(benchmarks)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report)
        print(f"Report written to {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
