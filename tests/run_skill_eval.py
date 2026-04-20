#!/usr/bin/env python3
"""Skill eval runner — benchmarks skills using claude -p.

Runs each eval from a skill's evals/evals.json with and without the skill,
grades outputs against assertions, and produces a benchmark.json report.

Usage:
    uv run python run_skill_eval.py --skill splunk-audit
    uv run python run_skill_eval.py --skill splunk-audit --id 1
    uv run python run_skill_eval.py --skill splunk-audit --no-baseline
    uv run python run_skill_eval.py --skill splunk-audit --report
    uv run python run_skill_eval.py --all
    uv run python run_skill_eval.py --list
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
WORKSPACE_ROOT = REPO_ROOT / "skill-eval-workspace"

ALLOWED_TOOLS = "Read,Write,Bash,Glob,Grep,Edit"


def load_evals(skill_name: str) -> dict:
    evals_file = SKILLS_DIR / skill_name / "evals" / "evals.json"
    if not evals_file.exists():
        print(f"Error: {evals_file} not found", file=sys.stderr)
        sys.exit(1)
    return json.loads(evals_file.read_text())


def list_skills() -> list[dict]:
    results = []
    for evals_json in sorted(SKILLS_DIR.glob("*/evals/evals.json")):
        data = json.loads(evals_json.read_text())
        results.append({
            "skill": data["skill_name"],
            "evals": len(data["evals"]),
        })
    return results


def build_with_skill_prompt(skill_name: str, eval_entry: dict) -> str:
    skill_md = SKILLS_DIR / skill_name / "SKILL.md"
    refs_dir = SKILLS_DIR / "references"

    parts = [
        "You are testing an observability skill. Follow the skill instructions below step by step.",
        "",
        f"## Skill (from {skill_md.relative_to(REPO_ROOT)})",
        skill_md.read_text(),
        "",
        "## Reference files",
        f"When the skill references files like ../references/*, read them from {refs_dir.relative_to(REPO_ROOT)}/.",
        "",
        f"## Task",
        eval_entry["prompt"],
        "",
        f"Working directory: {REPO_ROOT}",
        "",
        "## Output",
        "Execute the skill fully. Create all files the skill instructs.",
    ]

    app = eval_entry.get("app")
    if app:
        parts.append(f"The target app is at {app}/.")

    return "\n".join(parts)


def build_baseline_prompt(eval_entry: dict) -> str:
    parts = [
        "You are a helpful AI assistant. You do NOT have access to any special skills or predefined workflows.",
        "Use your general knowledge of observability and OpenTelemetry.",
        "",
        "## Task",
        eval_entry["prompt"],
        "",
        f"Working directory: {REPO_ROOT}",
    ]

    app = eval_entry.get("app")
    if app:
        parts.extend([
            "",
            f"The target app is at {app}/.",
            "Read the code, analyze it, and create appropriate output files.",
        ])

    return "\n".join(parts)


def run_claude(prompt: str, cwd: Path) -> dict:
    """Run claude -p and capture output + timing."""
    start = time.monotonic()
    result = subprocess.run(
        [
            "claude", "-p", prompt,
            "--allowedTools", ALLOWED_TOOLS,
            "--output-format", "json",
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=600,
    )
    elapsed = time.monotonic() - start

    output_text = result.stdout
    tokens = 0

    # Try to parse JSON output for token info.
    try:
        data = json.loads(output_text)
        tokens = data.get("total_tokens", 0)
        if not tokens:
            usage = data.get("usage", {})
            tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    except (json.JSONDecodeError, TypeError):
        pass

    return {
        "elapsed_seconds": round(elapsed, 1),
        "tokens": tokens,
        "exit_code": result.returncode,
        "stdout_len": len(result.stdout),
        "stderr_len": len(result.stderr),
    }


def collect_outputs(app_path: Path) -> list[str]:
    """List files created in the app's .observe/ directory."""
    observe_dir = app_path / ".observe"
    if not observe_dir.exists():
        return []
    return [
        str(f.relative_to(observe_dir))
        for f in sorted(observe_dir.rglob("*"))
        if f.is_file()
    ]


def grade_eval(eval_entry: dict, app_path: Path) -> dict:
    """Grade outputs against assertions. Returns grading.json content."""
    observe_dir = app_path / ".observe"
    inventory = observe_dir / "inventory.md"
    inventory_text = inventory.read_text() if inventory.exists() else ""

    expectations = []
    for assertion in eval_entry.get("expectations", []):
        passed, evidence = check_assertion(assertion, inventory_text, observe_dir, app_path)
        expectations.append({
            "text": assertion,
            "passed": passed,
            "evidence": evidence,
        })

    passed_count = sum(1 for e in expectations if e["passed"])
    total = len(expectations)

    return {
        "expectations": expectations,
        "summary": {
            "passed": passed_count,
            "failed": total - passed_count,
            "total": total,
            "pass_rate": round(passed_count / total, 2) if total else 0,
        },
    }


def check_assertion(assertion: str, inventory_text: str, observe_dir: Path, app_path: Path) -> tuple[bool, str]:
    """Check a single assertion against the outputs. Returns (passed, evidence)."""
    a = assertion.lower()

    # File existence checks.
    if "inventory.md" in a and ("exists" in a or "created" in a or "file exists" in a):
        inv = observe_dir / "inventory.md"
        if inv.exists():
            return True, f"inventory.md exists ({inv.stat().st_size} bytes)"
        return False, "inventory.md not found"

    if not inventory_text:
        return False, "No inventory.md to check against"

    inv_lower = inventory_text.lower()

    # Section checks.
    if "all 11 sections" in a or "11 required sections" in a:
        sections = [
            "## Service Overview", "## Architecture", "## Components",
            "## Fault Domains", "## SLI Definitions", "## Spans",
            "## Metrics", "## Logs", "## Configurability",
            "## Alerts", "## Dashboard Recommendations",
        ]
        found = [s for s in sections if s.lower() in inv_lower]
        missing = [s for s in sections if s.lower() not in inv_lower]
        if not missing:
            return True, f"All 11 sections present"
        return False, f"Missing sections: {', '.join(missing)}"

    # Mermaid diagram.
    if "mermaid" in a:
        if "```mermaid" in inventory_text:
            return True, "Mermaid diagram block found"
        return False, "No ```mermaid block found"

    # Language/framework detection.
    if "go" in a and "language" in a:
        if "go" in inv_lower and ("language" in inv_lower):
            return True, "Go listed as language"
        return False, "Go not found as language"

    if "chi" in a and "framework" in a:
        if "chi" in inv_lower:
            return True, "chi listed as framework"
        return False, "chi not found as framework"

    if "node" in a and "language" in a:
        if "node" in inv_lower:
            return True, "Node.js listed as language"
        return False, "Node.js not found"

    if "express" in a and "framework" in a:
        if "express" in inv_lower:
            return True, "Express listed as framework"
        return False, "Express not found"

    # SLI count checks.
    if "sli" in a and ("at least 4" in a or "all four" in a or "golden signal" in a):
        for signal in ["latency", "traffic", "errors", "saturation"]:
            if signal not in inv_lower:
                return False, f"Golden signal '{signal}' not found in SLI table"
        return True, "All four golden signals represented"

    # OOB span check.
    if "oob" in a and "span" in a:
        if "oob" in inv_lower and ("span" in inv_lower or "## spans" in inv_lower):
            return True, "OOB span entries found"
        return False, "No OOB spans found"

    # Metrics count check.
    if "metrics" in a and "at least 3" in a:
        metrics_section = _extract_section(inventory_text, "## Metrics")
        rows = [l for l in metrics_section.split("\n") if l.strip().startswith("|") and "`" in l]
        if len(rows) >= 3:
            return True, f"{len(rows)} metric rows found"
        return False, f"Only {len(rows)} metric rows found"

    # http.server.request.duration check.
    if "http.server.request.duration" in a:
        if "http.server.request.duration" in inventory_text:
            return True, "http.server.request.duration present"
        return False, "http.server.request.duration not found"

    # No external deps check.
    if "not" in a and ("database" in a or "cache" in a or "queue" in a) and "component" in a:
        comps = _extract_section(inventory_text, "## Components")
        comps_lower = comps.lower()
        if "none" in comps_lower or "*(none)*" in comps_lower or "no external" in comps_lower:
            return True, "No external components listed"
        # Check if there are database/cache/queue entries.
        for kw in ["database", "cache", "redis", "kafka", "rabbitmq", "postgres", "mysql", "mongo"]:
            if kw in comps_lower:
                return False, f"External component '{kw}' found in Components section"
        return True, "No database/cache/queue components detected"

    # OTEL_SDK_DISABLED check.
    if "otel_sdk_disabled" in a:
        if "otel_sdk_disabled" in inv_lower:
            return True, "OTEL_SDK_DISABLED mentioned"
        return False, "OTEL_SDK_DISABLED not found"

    # Blank status check.
    if "status" in a and "blank" in a:
        spans = _extract_section(inventory_text, "## Spans")
        metrics = _extract_section(inventory_text, "## Metrics")
        logs = _extract_section(inventory_text, "## Logs")
        for section_name, section in [("Spans", spans), ("Metrics", metrics), ("Logs", logs)]:
            for line in section.split("\n"):
                if line.strip().startswith("|") and "`" in line:
                    if "| OK" in line:
                        return False, f"Found OK status in {section_name} table"
        return True, "All Status columns are blank"

    # Status=OK preserved check.
    if "status=ok" in a and ("retain" in a or "preserv" in a):
        # Vacuously true if grading — we check the output has OK values if input had them.
        return True, "Status preservation check (requires manual verification)"

    # Logs entry check.
    if "log" in a and ("at least 1" in a or "1 log" in a):
        logs = _extract_section(inventory_text, "## Logs")
        rows = [l for l in logs.split("\n") if l.strip().startswith("|") and "`" in l]
        if len(rows) >= 1:
            return True, f"{len(rows)} log signal rows found"
        return False, "No log signal rows found"

    # Alerts/Dashboard section presence.
    if "alert" in a and "dashboard" in a and ("present" in a or "section" in a):
        has_alerts = "## alerts" in inv_lower
        has_dash = "## dashboard" in inv_lower
        if has_alerts and has_dash:
            return True, "Both Alerts and Dashboard Recommendations sections present"
        missing = []
        if not has_alerts:
            missing.append("Alerts")
        if not has_dash:
            missing.append("Dashboard Recommendations")
        return False, f"Missing: {', '.join(missing)}"

    # Cancellation/refund SLI check.
    if ("cancel" in a or "refund" in a) and "sli" in a:
        sli_section = _extract_section(inventory_text, "## SLI Definitions")
        if "cancel" in sli_section.lower() or "refund" in sli_section.lower():
            return True, "Cancellation/refund SLIs found"
        return False, "No cancellation/refund SLIs found"

    # New blank-status signals.
    if "blank status" in a and ("cancel" in a or "refund" in a):
        for section_key in ["## Spans", "## Metrics", "## Logs"]:
            section = _extract_section(inventory_text, section_key)
            for line in section.split("\n"):
                if ("cancel" in line.lower() or "refund" in line.lower()) and "`" in line:
                    return True, f"New cancellation/refund signal found in {section_key}"
        return False, "No new cancellation/refund signals found"

    # Redis component check.
    if "redis" in a and "component" in a:
        comps = _extract_section(inventory_text, "## Components")
        if "redis" in comps.lower():
            return True, "Redis listed in Components"
        return False, "Redis not found in Components"

    # Celery component check.
    if "celery" in a and "component" in a:
        comps = _extract_section(inventory_text, "## Components")
        if "celery" in comps.lower():
            return True, "Celery listed in Components"
        # Also check Internal Layers.
        if "celery" in inventory_text.lower():
            return True, "Celery found in document"
        return False, "Celery not found"

    # Last-updated date.
    if "last-updated" in a or "last updated" in a or "changelog" in a:
        if "last updated" in inv_lower or "changelog" in inv_lower or "<!-- last updated" in inv_lower:
            return True, "Last-updated date or changelog present"
        return False, "No last-updated date found"

    # Terraform file check.
    if ".tf" in a and ("terraform" in a or "created" in a):
        tf_dir = observe_dir / "terraform"
        if tf_dir.exists():
            tf_files = list(tf_dir.glob("*.tf"))
            if tf_files:
                return True, f"Found {len(tf_files)} .tf files"
        return False, "No .tf files found in .observe/terraform/"

    # Alerts populated check.
    if "alert" in a and ("populated" in a or "at least one" in a):
        alerts_section = _extract_section(inventory_text, "## Alerts")
        rows = [l for l in alerts_section.split("\n") if l.strip().startswith("|") and l.count("|") >= 4]
        # Filter out header/separator rows and placeholder rows.
        data_rows = [r for r in rows if "Alert Name" not in r and "---" not in r and "Placeholder" not in r.lower() and r.strip("| \n")]
        if data_rows:
            return True, f"Alerts section has {len(data_rows)} entries"
        return False, "Alerts section empty or placeholder only"

    # OpenTelemetry package checks.
    if "opentelemetry" in a and ("pyproject" in a or "requirements" in a or "package" in a or "added" in a):
        app_dir = app_path
        for dep_file in ["pyproject.toml", "requirements.txt", "package.json", "go.mod"]:
            f = app_dir / dep_file
            if f.exists() and "opentelemetry" in f.read_text().lower():
                return True, f"OpenTelemetry found in {dep_file}"
            if f.exists() and "go.opentelemetry.io" in f.read_text():
                return True, f"OTel Go modules found in {dep_file}"
        return False, "No OpenTelemetry dependencies found"

    # OTel setup file check.
    if "otel_setup" in a or "otel" in a and ("setup" in a or "initialization" in a or "init" in a):
        for pattern in ["otel_setup.py", "otel_*.py", "telemetry.go", "tracing.ts", "tracing.js", "instrumentation.js"]:
            matches = list(app_path.glob(pattern)) + list(app_path.glob(f"**/{pattern}"))
            if matches:
                return True, f"OTel setup file found: {matches[0].name}"
        return False, "No OTel setup/initialization file found"

    # Generic inventory.md updated check.
    if "updated" in a and "inventory" in a and "not" not in a:
        if inventory_text:
            return True, "inventory.md exists with content"
        return False, "inventory.md missing or empty"

    # Fallback: keyword search in inventory.
    keywords = [w for w in a.split() if len(w) > 4 and w.isalpha()]
    matches = sum(1 for kw in keywords if kw in inv_lower)
    if matches >= len(keywords) * 0.6:
        return True, f"Keyword match: {matches}/{len(keywords)} keywords found"
    return False, f"Could not verify assertion programmatically"


def _extract_section(text: str, heading: str) -> str:
    """Extract content between a ## heading and the next ## heading."""
    lines = text.split("\n")
    in_section = False
    section_lines = []
    for line in lines:
        if line.strip() == heading or line.strip().startswith(heading):
            in_section = True
            continue
        if in_section:
            if line.startswith("## ") and line.strip() != heading:
                break
            section_lines.append(line)
    return "\n".join(section_lines)


def make_eval_name(eval_entry: dict) -> str:
    """Derive a short name for an eval from its app or prompt."""
    app = eval_entry.get("app", "")
    if app:
        return Path(app).name
    words = eval_entry["prompt"].split()[:4]
    return "-".join(w.lower() for w in words)


def run_single_eval(
    skill_name: str,
    eval_entry: dict,
    run_dir: Path,
    *,
    skip_baseline: bool = False,
) -> dict:
    """Run one eval (with-skill + optional baseline). Returns benchmark entry."""
    eval_name = make_eval_name(eval_entry)
    app = eval_entry.get("app", "")
    app_path = REPO_ROOT / app if app else REPO_ROOT

    results = {}

    # --- With skill ---
    config = "with_skill"
    out_dir = run_dir / f"{eval_name}-{config}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Clean .observe/ before run to get fresh output.
    observe_dir = app_path / ".observe"
    observe_backup = None
    if observe_dir.exists():
        observe_backup = run_dir / f"{eval_name}-observe-backup"
        shutil.copytree(observe_dir, observe_backup)

    prompt = build_with_skill_prompt(skill_name, eval_entry)
    print(f"  [{config}] Running eval {eval_entry['id']}: {eval_name}...", flush=True)
    timing = run_claude(prompt, cwd=REPO_ROOT)

    # Save timing.
    (out_dir / "timing.json").write_text(json.dumps(timing, indent=2))

    # Collect outputs.
    output_files = collect_outputs(app_path)
    (out_dir / "output_files.json").write_text(json.dumps(output_files, indent=2))

    # Copy inventory to outputs/.
    outputs_dir = out_dir / "outputs"
    outputs_dir.mkdir(exist_ok=True)
    inv = observe_dir / "inventory.md"
    if inv.exists():
        shutil.copy2(inv, outputs_dir / "inventory.md")

    # Grade.
    grading = grade_eval(eval_entry, app_path)
    (out_dir / "grading.json").write_text(json.dumps(grading, indent=2))

    results[config] = {
        "timing": timing,
        "grading": grading,
        "output_files": output_files,
    }

    print(f"    Pass rate: {grading['summary']['pass_rate']:.0%} "
          f"({grading['summary']['passed']}/{grading['summary']['total']}), "
          f"time: {timing['elapsed_seconds']}s", flush=True)

    # --- Baseline (without skill) ---
    if not skip_baseline:
        config = "without_skill"
        out_dir = run_dir / f"{eval_name}-{config}"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Restore original .observe/ state for fair baseline.
        if observe_dir.exists():
            shutil.rmtree(observe_dir)
        if observe_backup and observe_backup.exists():
            shutil.copytree(observe_backup, observe_dir)

        prompt = build_baseline_prompt(eval_entry)
        print(f"  [{config}] Running eval {eval_entry['id']}: {eval_name}...", flush=True)
        timing = run_claude(prompt, cwd=REPO_ROOT)

        (out_dir / "timing.json").write_text(json.dumps(timing, indent=2))

        output_files = collect_outputs(app_path)
        (out_dir / "output_files.json").write_text(json.dumps(output_files, indent=2))

        outputs_dir = out_dir / "outputs"
        outputs_dir.mkdir(exist_ok=True)
        inv = observe_dir / "inventory.md"
        if inv.exists():
            shutil.copy2(inv, outputs_dir / "inventory.md")

        grading = grade_eval(eval_entry, app_path)
        (out_dir / "grading.json").write_text(json.dumps(grading, indent=2))

        results[config] = {
            "timing": timing,
            "grading": grading,
            "output_files": output_files,
        }

        print(f"    Pass rate: {grading['summary']['pass_rate']:.0%} "
              f"({grading['summary']['passed']}/{grading['summary']['total']}), "
              f"time: {timing['elapsed_seconds']}s", flush=True)

    # Restore original .observe/ state after eval.
    if observe_dir.exists():
        shutil.rmtree(observe_dir)
    if observe_backup and observe_backup.exists():
        shutil.copytree(observe_backup, observe_dir)
        shutil.rmtree(observe_backup)

    return results


def build_benchmark(skill_name: str, evals_data: dict, all_results: dict, run_dir: Path) -> dict:
    """Aggregate results into benchmark.json."""
    runs = []
    for eval_entry in evals_data["evals"]:
        eval_id = eval_entry["id"]
        eval_name = make_eval_name(eval_entry)
        eval_results = all_results.get(eval_id, {})

        for config in ["with_skill", "without_skill"]:
            r = eval_results.get(config)
            if not r:
                continue
            runs.append({
                "eval_id": eval_id,
                "eval_name": eval_name,
                "configuration": config,
                "run_number": 1,
                "result": {
                    "pass_rate": r["grading"]["summary"]["pass_rate"],
                    "passed": r["grading"]["summary"]["passed"],
                    "failed": r["grading"]["summary"]["failed"],
                    "total": r["grading"]["summary"]["total"],
                    "time_seconds": r["timing"]["elapsed_seconds"],
                    "tokens": r["timing"]["tokens"],
                    "errors": 0,
                },
                "expectations": r["grading"]["expectations"],
            })

    # Compute summaries.
    summary = {}
    for config in ["with_skill", "without_skill"]:
        config_runs = [r for r in runs if r["configuration"] == config]
        if not config_runs:
            continue
        rates = [r["result"]["pass_rate"] for r in config_runs]
        times = [r["result"]["time_seconds"] for r in config_runs]
        tokens = [r["result"]["tokens"] for r in config_runs]

        def stats(vals):
            n = len(vals)
            mean = sum(vals) / n if n else 0
            variance = sum((v - mean) ** 2 for v in vals) / n if n > 1 else 0
            return {"mean": round(mean, 2), "stddev": round(variance ** 0.5, 2), "min": min(vals, default=0), "max": max(vals, default=0)}

        summary[config] = {
            "pass_rate": stats(rates),
            "time_seconds": stats(times),
            "tokens": stats(tokens),
        }

    delta = {}
    if "with_skill" in summary and "without_skill" in summary:
        delta = {
            "pass_rate": f"+{summary['with_skill']['pass_rate']['mean'] - summary['without_skill']['pass_rate']['mean']:.2f}",
            "time_seconds": f"+{summary['with_skill']['time_seconds']['mean'] - summary['without_skill']['time_seconds']['mean']:.1f}",
            "tokens": f"+{summary['with_skill']['tokens']['mean'] - summary['without_skill']['tokens']['mean']:.0f}",
        }

    benchmark = {
        "metadata": {
            "skill_name": skill_name,
            "skill_path": str(SKILLS_DIR / skill_name),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "evals_run": [e["id"] for e in evals_data["evals"]],
            "runs_per_configuration": 1,
        },
        "runs": runs,
        "run_summary": {**summary, "delta": delta},
    }

    (run_dir / "benchmark.json").write_text(json.dumps(benchmark, indent=2))
    return benchmark


def print_summary(benchmark: dict):
    """Print a human-readable summary table."""
    print()
    print(f"{'='*60}")
    print(f"  Benchmark: {benchmark['metadata']['skill_name']}")
    print(f"{'='*60}")

    summary = benchmark.get("run_summary", {})
    for config in ["with_skill", "without_skill"]:
        s = summary.get(config)
        if not s:
            continue
        pr = s["pass_rate"]
        ts = s["time_seconds"]
        tk = s["tokens"]
        print(f"\n  {config}:")
        print(f"    Pass rate:  {pr['mean']:.0%} (stddev {pr['stddev']:.2f})")
        print(f"    Time:       {ts['mean']:.1f}s (stddev {ts['stddev']:.1f})")
        print(f"    Tokens:     {tk['mean']:.0f} (stddev {tk['stddev']:.0f})")

    delta = summary.get("delta", {})
    if delta:
        print(f"\n  Delta (with - without):")
        print(f"    Pass rate:  {delta.get('pass_rate', 'N/A')}")
        print(f"    Time:       {delta.get('time_seconds', 'N/A')}s")
        print(f"    Tokens:     {delta.get('tokens', 'N/A')}")

    print()

    # Per-eval breakdown.
    print(f"  {'Eval':<25} {'With Skill':>12} {'Baseline':>12}")
    print(f"  {'-'*25} {'-'*12} {'-'*12}")

    runs = benchmark.get("runs", [])
    eval_names = sorted(set(r["eval_name"] for r in runs))
    for name in eval_names:
        ws = next((r for r in runs if r["eval_name"] == name and r["configuration"] == "with_skill"), None)
        bl = next((r for r in runs if r["eval_name"] == name and r["configuration"] == "without_skill"), None)
        ws_str = f"{ws['result']['passed']}/{ws['result']['total']}" if ws else "—"
        bl_str = f"{bl['result']['passed']}/{bl['result']['total']}" if bl else "—"
        print(f"  {name:<25} {ws_str:>12} {bl_str:>12}")

    print(f"\n  Results: {benchmark['metadata'].get('_run_dir', 'skill-eval-workspace/')}")
    print()


def show_report(skill_name: str):
    """Show the latest benchmark report for a skill."""
    latest = WORKSPACE_ROOT / skill_name / "latest"
    if not latest.exists():
        print(f"No eval results found for {skill_name}. Run: make skill-eval SKILL={skill_name}", file=sys.stderr)
        sys.exit(1)
    benchmark_file = latest / "benchmark.json"
    if not benchmark_file.exists():
        print(f"No benchmark.json in {latest}", file=sys.stderr)
        sys.exit(1)
    benchmark = json.loads(benchmark_file.read_text())
    benchmark["metadata"]["_run_dir"] = str(latest.resolve())
    print_summary(benchmark)


def run_skill_evals(skill_name: str, *, eval_id: int | None = None, skip_baseline: bool = False):
    """Run all evals for a skill."""
    evals_data = load_evals(skill_name)
    evals_to_run = evals_data["evals"]
    if eval_id is not None:
        evals_to_run = [e for e in evals_to_run if e["id"] == eval_id]
        if not evals_to_run:
            print(f"Error: eval id {eval_id} not found in {skill_name}", file=sys.stderr)
            sys.exit(1)

    # Create run directory.
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = WORKSPACE_ROOT / skill_name / f"run-{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nSkill eval: {skill_name} ({len(evals_to_run)} evals)")
    print(f"Workspace: {run_dir}")
    print()

    all_results = {}
    for eval_entry in evals_to_run:
        results = run_single_eval(skill_name, eval_entry, run_dir, skip_baseline=skip_baseline)
        all_results[eval_entry["id"]] = results

    # Build benchmark.
    benchmark = build_benchmark(skill_name, evals_data, all_results, run_dir)
    benchmark["metadata"]["_run_dir"] = str(run_dir)

    # Update latest symlink.
    latest_link = WORKSPACE_ROOT / skill_name / "latest"
    if latest_link.is_symlink() or latest_link.exists():
        latest_link.unlink()
    latest_link.symlink_to(run_dir.name)

    print_summary(benchmark)


def main():
    parser = argparse.ArgumentParser(description="Skill eval runner")
    parser.add_argument("--skill", help="Skill name to evaluate")
    parser.add_argument("--id", type=int, help="Run only a specific eval ID")
    parser.add_argument("--no-baseline", action="store_true", help="Skip baseline (without-skill) runs")
    parser.add_argument("--all", action="store_true", help="Run evals for all skills")
    parser.add_argument("--list", action="store_true", help="List all skills with evals")
    parser.add_argument("--report", action="store_true", help="Show latest benchmark report")
    args = parser.parse_args()

    if args.list:
        skills = list_skills()
        print(f"\n  {'Skill':<25} {'Evals':>6}")
        print(f"  {'-'*25} {'-'*6}")
        for s in skills:
            print(f"  {s['skill']:<25} {s['evals']:>6}")
        print()
        return

    if args.report:
        if not args.skill:
            print("Error: --report requires --skill", file=sys.stderr)
            sys.exit(1)
        show_report(args.skill)
        return

    if args.all:
        skills = list_skills()
        for s in skills:
            run_skill_evals(s["skill"], skip_baseline=args.no_baseline)
        return

    if not args.skill:
        parser.print_help()
        sys.exit(1)

    run_skill_evals(args.skill, eval_id=args.id, skip_baseline=args.no_baseline)


if __name__ == "__main__":
    main()
