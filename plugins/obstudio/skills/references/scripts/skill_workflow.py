#!/usr/bin/env python3
"""Record observable skill stages without capturing prompts or command output."""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

SCHEMA_VERSION = 1
MAX_EVENTS = 256
MAX_STATE_BYTES = 1024 * 1024
STATUSES = {"passed", "failed", "blocked", "skipped"}
RUN_ID = re.compile(r"^[0-9a-f]{32}$")


def definitions():
    return json.loads(Path(__file__).resolve().parents[1].joinpath("workflows.json").read_text())["skills"]


def source_digests(skill):
    shared = Path(__file__).resolve().parents[1]
    candidates = [shared.parent / skill] + [p for p in shared.parents if p.name == skill]
    directory = next((p for p in candidates if (p / "SKILL.md").is_file()), None)
    digest = hashlib.sha256()
    if directory is not None:
        for prefix, root in (("skill", directory), ("shared", shared)):
            for path in sorted(root.rglob("*")):
                relative = path.relative_to(root)
                if (not path.is_file() or path.is_symlink()
                        or {"tests", "__pycache__", "evals"}.intersection(relative.parts)
                        or path.suffix == ".pyc"):
                    continue
                digest.update((prefix + "/" + relative.as_posix()).encode())
                digest.update(b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return {"skillDigest": "sha256:" + digest.hexdigest() if directory else "",
            "contractDigest": "sha256:" + hashlib.sha256((shared / "workflows.json").read_bytes()).hexdigest()}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def read_state(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_STATE_BYTES:
        raise ValueError("Invalid or oversized workflow journal")
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("schemaVersion") != SCHEMA_VERSION or not RUN_ID.fullmatch(state.get("runId", "")):
        raise ValueError("Invalid workflow identity")
    if (state.get("skill") not in definitions() or not isinstance(state.get("events"), list)
            or len(state["events"]) > MAX_EVENTS):
        raise ValueError("Invalid workflow contract")
    for event in state["events"]:
        if (not isinstance(event, dict) or not {"stage", "status", "source"}.issubset(event)
                or event["status"] not in STATUSES or event["source"] not in {"checkpoint", "executed"}):
            raise ValueError("Invalid workflow event")
        stage_definition(state["skill"], event["stage"], event.get("branch", ""))
    return state


@contextlib.contextmanager
def locked(path):
    path = Path(path)
    lock = path.with_suffix(".lock")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("Invalid workflow lock")
        if os.name == "nt":
            import msvcrt
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt":
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def write_state(path, state):
    path = Path(path)
    data = (json.dumps(state, indent=2) + "\n").encode()
    if len(data) > MAX_STATE_BYTES:
        raise ValueError("Workflow journal capacity reached")
    fd, temporary = tempfile.mkstemp(prefix=".workflow-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def start(skill, repo_root):
    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise ValueError("Repository root must exist")
    if skill not in definitions():
        raise ValueError("Unknown skill")
    directory = root / ".observe" / "skill-runs"
    for directory_part in (root / ".observe", directory):
        if directory_part.is_symlink():
            raise ValueError("Workflow directory must not be a symlink")
        directory_part.mkdir(mode=0o700, exist_ok=True)
    identity = secrets.token_hex(16)
    path = directory / (identity + ".json")
    state = {"schemaVersion": 1, "runId": identity, "skill": skill,
             "startedAt": now(), "status": "running", "events": [], **source_digests(skill)}
    write_state(path, state)
    publish(state)
    return path


def stage_definition(skill, stage, branch):
    definition = next((s for s in definitions()[skill]["stages"] if s["id"] == stage), None)
    if definition is None:
        raise ValueError("Unknown workflow stage; read workflows.json")
    if branch and branch not in definition.get("branches", []):
        allowed = ", ".join(definition.get("branches", []))
        raise ValueError("Invalid branch for " + stage + "; " +
                         ("allowed: " + allowed if allowed else "omit --branch"))
    return definition


def evidence_paths(run_path, values):
    if len(values) > 32:
        raise ValueError("Evidence limit exceeded")
    root = Path(run_path).resolve().parents[2]
    results = []
    for value in values:
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts or len(value) > 240:
            raise ValueError("Evidence must use a bounded repository-relative path")
        target = (root / relative).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise ValueError("Evidence file is missing or outside the repository")
        digest = hashlib.sha256()
        with target.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        results.append({"path": relative.as_posix(), "sha256": "sha256:" + digest.hexdigest()})
    return results


def add_event(path, stage, status, source, branch="", reason="", evidence=(),
              started_at=None, duration_ms=None, exit_code=None):
    if status not in STATUSES or source not in {"checkpoint", "executed"}:
        raise ValueError("Invalid stage outcome or source")
    if len(reason) > 160 or (status in {"blocked", "skipped"} and not reason):
        raise ValueError("Blocked/skipped stages require a bounded reason code")
    if reason and not re.fullmatch(r"[a-zA-Z0-9._-]+", reason):
        raise ValueError("Use a reason code, not content or credentials")
    with locked(path):
        state = read_state(path)
        if state["status"] != "running":
            raise ValueError("Workflow is already finished")
        stage_definition(state["skill"], stage, branch)
        if len(state["events"]) >= MAX_EVENTS:
            raise ValueError("Workflow event capacity reached")
        attempt = 1 + sum(e["stage"] == stage for e in state["events"])
        event = {"stage": stage, "attempt": attempt, "status": status, "source": source,
                 "branch": branch, "reason": reason, "startedAt": started_at or now(),
                 "endedAt": now(), "evidence": evidence_paths(path, evidence)}
        if source == "executed":
            event.update(durationMs=duration_ms, exitCode=exit_code)
        state["events"].append(event)
        write_state(path, state)
    publish(state)
    return event


def inspect(state):
    stages = definitions()[state["skill"]]["stages"]
    latest = {e["stage"]: e for e in state["events"]}
    findings = []
    seen = set()
    for event in state["events"]:
        definition = stage_definition(state["skill"], event["stage"], event.get("branch", ""))
        for parent in definition.get("after", []):
            if parent not in seen:
                findings.append({"kind": "stage_order", "stage": event["stage"],
                                 "requiredBefore": parent})
        seen.add(event["stage"])
    for definition in stages:
        stage = definition["id"]
        event = latest.get(stage)
        if event is None:
            findings.append({"kind": "unobserved", "stage": stage})
        elif event["status"] in {"failed", "blocked"}:
            findings.append({"kind": event["status"], "stage": stage,
                             "reason": event.get("reason", "")})
    return {"runId": state["runId"], "skill": state["skill"],
            "status": state["status"], "path": [
                {"stage": e["stage"], "branch": e.get("branch", ""), "attempt": e["attempt"],
                 "status": e["status"], "source": e["source"]} for e in state["events"]],
            "coverage": "recorded_operations_and_checkpoints",
            "tokens": None, "findings": findings,
            "limitations": "Checkpoints are agent-reported; command spans cover only executed operations. "
                           "Missing stages are unobserved. Findings do not establish skill-prose causality."}


def finish(path, requested_status):
    if requested_status not in {"passed", "failed", "partial", "cancelled"}:
        raise ValueError("Invalid workflow outcome")
    with locked(path):
        state = read_state(path)
        if state["status"] != "running":
            raise ValueError("Workflow is already finished")
        diagnostics = inspect(state)
        status = requested_status
        if status == "passed" and diagnostics["findings"]:
            status = "partial"
        state.update(status=status, finishedAt=now())
        write_state(path, state)
    publish(state)
    return state


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def publish(state):
    """Best effort local MCP export; never inherit cloud endpoints or headers."""
    endpoint = os.environ.get("OBSTUDIO_SKILL_MCP_ENDPOINT", "http://127.0.0.1:3000/mcp")
    if endpoint == "none":
        return False
    try:
        parsed = urlsplit(endpoint)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path != "/mcp"):
            return False
        body = json.dumps({"jsonrpc": "2.0", "id": state["runId"], "method": "tools/call",
                           "params": {"name": "observer_skill_workflow_record",
                                      "arguments": {"run": state}}}).encode()
        request = Request(endpoint, body, {"Content-Type": "application/json"}, method="POST")
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=0.25) as response:
            result = json.loads(response.read(MAX_STATE_BYTES))
        if not isinstance(result, dict) or not isinstance(result.get("result"), dict):
            return False
        return "error" not in result and not result.get("result", {}).get("isError", False)
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def execute(args):
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise ValueError("execute requires a command")
    started_at, started = now(), time.monotonic()
    code = 1
    interrupted = False
    try:
        code = subprocess.call(command)
        return code
    except KeyboardInterrupt:
        interrupted = True
        code = 130
        raise
    finally:
        try:
            add_event(args.run, args.stage, "failed" if code else "passed", "executed",
                      branch=args.branch, reason="interrupted" if interrupted else "",
                      evidence=args.evidence, started_at=started_at,
                      duration_ms=(time.monotonic() - started) * 1000, exit_code=code)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            print("Workflow recording unavailable: " + type(exc).__name__, file=sys.stderr)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    start_parser = sub.add_parser("start")
    start_parser.add_argument("--skill", required=True, choices=sorted(definitions()))
    start_parser.add_argument("--repo-root", type=Path, required=True)
    for name in ("checkpoint", "execute"):
        item = sub.add_parser(name)
        item.add_argument("--run", type=Path, required=True)
        item.add_argument("--stage", required=True)
        item.add_argument("--branch", default="")
        item.add_argument("--evidence", action="append", default=[])
        if name == "checkpoint":
            item.add_argument("--status", required=True, choices=sorted(STATUSES))
            item.add_argument("--reason", default="")
        else:
            item.add_argument("command", nargs=argparse.REMAINDER)
    end = sub.add_parser("finish")
    end.add_argument("--run", type=Path, required=True)
    end.add_argument("--status", required=True, choices=["passed", "failed", "partial", "cancelled"])
    for name in ("inspect", "sync"):
        item = sub.add_parser(name)
        item.add_argument("--run", type=Path, required=True)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.action == "start":
            print(json.dumps({"run": str(start(args.skill, args.repo_root))}))
        elif args.action == "checkpoint":
            print(json.dumps(add_event(args.run, args.stage, args.status, "checkpoint",
                                      branch=args.branch, reason=args.reason, evidence=args.evidence)))
        elif args.action == "execute":
            return execute(args)
        elif args.action == "finish":
            print(json.dumps(inspect(finish(args.run, args.status))))
        elif args.action == "inspect":
            print(json.dumps(inspect(read_state(args.run))))
        elif args.action == "sync":
            print(json.dumps({"exported": publish(read_state(args.run))}))
        return 0
    except (OSError, ValueError) as exc:
        print("Workflow operation unavailable: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
