"""Grade declared paths using journals plus independent command/artifact evidence."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shlex

from pytest_codex_evals.definitions.sanity import SanityCheck
from pytest_codex_evals.trace import TraceSummary


def inside(root: Path, relative: str) -> Path:
    path = Path(relative)
    if not relative or path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise ValueError("Unsafe workflow evidence path")
    candidate = root / path
    if candidate.is_symlink() or not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError("Workflow evidence escapes the fixture")
    return candidate


def grade_workflow(check: SanityCheck, service_dir: Path, trace: TraceSummary | None) -> tuple[bool, str]:
    failures = []
    try:
        pattern = check.path or ".observe/skill-runs/*.json"
        inside(service_dir, pattern)
        journals = []
        for path in service_dir.glob(pattern):
            inside(service_dir, str(path.relative_to(service_dir)))
            if not path.is_file() or path.stat().st_size > 1024 * 1024:
                raise ValueError("Invalid or oversized workflow journal")
            run = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(run, dict):
                raise ValueError("Invalid workflow object")
            if check.workflow_skill is None or run.get("skill") == check.workflow_skill:
                journals.append((path, run))
        if len(journals) != 1:
            return False, f"Expected one matching invocation journal, found {len(journals)}"
        path, run = journals[0]
        events = run["events"]
        if run.get("schemaVersion") != 1 or not isinstance(events, list) or len(events) > 256:
            raise ValueError("Invalid workflow journal shape")
        status = run.get("status")
        if status not in check.outcomes or (status != "running" and not run.get("finishedAt")):
            failures.append("unexpected or incomplete outcome")
        latest = {event["stage"]: event for event in events}
        order = [event["stage"] for event in events]
        for stage in check.required_stages:
            if stage not in latest or latest[stage]["status"] != "passed":
                failures.append(f"required stage not passed: {stage}")
        for edge in check.before:
            if len(edge) != 2:
                raise ValueError("Stage ordering requires pairs")
            first, second = edge
            if first not in order or second not in order or order.index(first) >= order.index(second):
                failures.append(f"stage ordering: {first} before {second}")
        for event in events:
            if f'{event["stage"]}={event.get("branch", "")}' in check.forbidden_branches:
                failures.append(f'forbidden branch: {event["stage"]}')
        for stage in check.executed_stages:
            event = latest.get(stage, {})
            if (event.get("source") != "executed" or event.get("exitCode") != 0 or not isinstance(event.get("durationMs"), (int, float))
                    or not math.isfinite(event["durationMs"]) or event["durationMs"] < 0):
                failures.append(f"missing measured execution: {stage}")
                continue
            witnessed = False
            for action in trace.actions if trace is not None else []:
                if action.kind != "command" or action.exit_code != event["exitCode"]:
                    continue
                try:
                    words = shlex.split(action.input.get("command", ""))
                    if (len(words)==3 and Path(words[0]).name in {"sh", "bash", "zsh"}
                            and words[1] in {"-c", "-lc"}):
                        words=shlex.split(words[2])
                except ValueError:
                    continue
                # Conservative: shell expansion/aliases do not independently prove an operation.
                if (len(words) < 5 or not Path(words[0]).name.startswith("python")
                        or Path(words[1]).name != "skill_workflow.py" or words[2] != "execute"
                        or any(word in {";", "&&", "||", "|"} for word in words)):
                    continue
                args = words[3:]
                if ("--run" in args and "--stage" in args and "--" in args
                        and args[args.index("--stage") + 1] == stage):
                    journal = Path(args[args.index("--run") + 1])
                    if journal.resolve() == path.resolve() or journal == path.relative_to(service_dir):
                        witnessed = True
            if not witnessed:
                failures.append(f"execution lacks independent command witness: {stage}")
        for relative in check.evidence_paths:
            artifact = inside(service_dir, relative)
            if not artifact.is_file():
                failures.append(f"missing independent artifact: {relative}")
                continue
            digest = hashlib.sha256()
            with artifact.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            expected = "sha256:" + digest.hexdigest()
            matches = [item for event in events for item in event.get("evidence", [])
                       if item.get("path") == relative and item.get("sha256") == expected]
            if not matches:
                failures.append(f"artifact digest not witnessed: {relative}")
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        return False, "Invalid workflow journal, expectation, or evidence"
    return not failures, "; ".join(failures) if failures else "Declared path, command witnesses, and artifact digests agree; checkpoints remain self-reported"
