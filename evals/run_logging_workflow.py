"""Run bare audit/instrument/verify eval tasks on one retained, real service."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.request

from pytest_codex_evals.backends import CodexBackend
from pytest_codex_evals.eval_files import skill_workspace_ignore
from pytest_codex_evals.graders import grade_side
from pytest_codex_evals.graders.rubric import run_rubric_grade
from pytest_codex_evals.plugin import case_from_definition, load_eval_definition
from pytest_codex_evals.runner import prepare_side_workspace

from logging_workflow_check import interrupt_owned_run, source_hashes, stop_owned


SERVICES = {"go": "chi-basic", "java": "springboot-basic", "python": "flask-basic", "node": "express-basic"}


def save(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def bundle_hashes(workspace: Path) -> dict[str, str]:
    root = workspace / ".agents/skills"
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def audit_hash(workspace: Path) -> str | None:
    path = workspace / "service/.observe/otel-audit.json"
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def case_for(repo: Path, language: str, role: str, trial: int):
    path = repo / "evals" / language / SERVICES[language] / "eval/qual" / f"logging-{role}-contract.json"
    definition = load_eval_definition(path)
    prompt = next(prompt for prompt in definition.prompts if prompt.id == f"logging-trial-{trial}")
    assert prompt.task == f"$otel-{role} ./service" and prompt.eval_inputs == []
    return case_from_definition(definition, prompt, path)


def reserve_ports() -> dict[str, int]:
    sockets = [socket.socket() for _ in range(4)]
    try:
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        return dict(zip(("rest", "http", "grpc", "app"), (sock.getsockname()[1] for sock in sockets), strict=True))
    finally:
        for sock in sockets:
            sock.close()


def start_receiver(binary: Path, output: Path, ports: dict[str, int]) -> subprocess.Popen:
    env_file = output / "receiver.env"
    env_file.write_text("# Isolated credential-free eval receiver\n")
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("SPLUNK_", "SIGNALFX_", "SFX_", "OTEL_", "OBSTUDIO_"))}
    environment.update(OBSTUDIO_CONFIG_MANAGER="false", OTLP_HTTP_PORT=str(ports["http"]),
                       OTLP_GRPC_PORT=str(ports["grpc"]), OTLP_GRPC_HOST="127.0.0.1",
                       OBSTUDIO_OWNER="logging-workflow-eval", OBSTUDIO_MODE="standalone")
    command = [str(binary), "--env-file", str(env_file), "--host", "127.0.0.1", "--port", str(ports["rest"])]
    with (output / "receiver.log").open("w") as log:
        process = subprocess.Popen(command, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Owned receiver exited during startup")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{ports['rest']}/api/health", timeout=1) as response:
                    health = json.load(response)
                assert health.get("owner") == "logging-workflow-eval", "Receiver ownership mismatch"
                save(output / "receiver.json", {"pid": process.pid, "command": command, "ports": ports,
                     "health": health, "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest()})
                return process
            except OSError:
                time.sleep(.1)
        raise TimeoutError("Owned receiver startup exceeded15seconds")
    except BaseException:
        stop_owned(process)
        raise


def bind_model_metadata(trace: Path, codex_home: Path, workspace: Path) -> dict:
    ids = [event["thread_id"] for line in trace.read_text().splitlines()
           if (event := json.loads(line)).get("type") == "thread.started"]
    assert len(ids) == 1, "One executed model thread is required"
    sessions = list((codex_home / "sessions").rglob("*" + ids[0] + ".jsonl"))
    assert len(sessions) == 1, "Executed thread must bind one isolated session"
    contexts, meta = [], {}
    # Inspect execution metadata only; do not expose model reasoning contents.
    for line in sessions[0].read_text().splitlines():
        event = json.loads(line)
        payload = event.get("payload", {})
        if event.get("type") == "session_meta":
            meta = {key: payload.get(key) for key in ("id", "cwd", "timestamp")}
        elif event.get("type") == "turn_context":
            contexts.append({key: payload.get(key) for key in ("model", "effort", "cwd")})
    assert meta.get("id") == ids[0] and Path(meta["cwd"]).resolve() == workspace.resolve()
    assert contexts and all(value["model"] == "gpt-6.1-sol" and value["effort"] == "high" for value in contexts)
    return {"thread_id": ids[0], "session": str(sessions[0]), "started": meta["timestamp"],
            "model": "gpt-6.1-sol", "reasoning_effort": "high", "turns": len(contexts)}


def archive_stage(workspace: Path, destination: Path) -> None:
    destination.mkdir()
    for name in ("trace.jsonl", "last_message.md", "stderr.txt", "grade.json", "rubric_grade.json",
                 "rubric_trace.jsonl", "rubric_stderr.txt"):
        path = workspace / name
        if path.exists():
            shutil.copy2(path, destination / name)
    shutil.copytree(workspace / "service", destination / "service", symlinks=True,
                    ignore=shutil.ignore_patterns(".venv", "node_modules", "target", "__pycache__", "*.db"))


GRADER_FEEDBACK_ARTIFACTS = (
    "grade.json", "rubric_grade.json", "rubric_trace.jsonl", "rubric_stderr.txt",
)


def isolate_stage_feedback(workspace: Path, archived_stage: Path) -> None:
    """Remove known grader handoffs only after their external copies are verified."""
    if archived_stage.resolve().is_relative_to(workspace.resolve()):
        raise ValueError("Grader archive must be outside the actor workspace")
    feedback = [workspace / name for name in GRADER_FEEDBACK_ARTIFACTS
                if (workspace / name).exists()]
    for path in feedback:
        archived = archived_stage / path.name
        if not archived.is_file() or path.read_bytes() != archived.read_bytes():
            raise RuntimeError(f"Grader archive is missing or differs: {path.name}")
    for path in feedback:
        path.unlink()


def validate_audit_handoff(repo: Path, workspace: Path) -> None:
    """Use the existing canonical parser, without creating or repairing an audit."""
    script = repo / "skills/references/scripts/observe_report_core.py"
    spec = importlib.util.spec_from_file_location("logging_workflow_report_core", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("Canonical audit parser unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = json.loads((workspace / "service/.observe/otel-audit.json").read_text())
    normalized = module.normalize_audit_report(report)
    if normalized["meta"]["status"] == "Blocked":
        raise RuntimeError("Blocked audit cannot authorize diagnostic continuation")


class CheckedJudgeBackend:
    """Reject failed judge execution even if it left schema-valid output behind."""
    def __init__(self, backend: CodexBackend):
        self.backend = backend

    def run_judge(self, **kwargs):
        result = self.backend.run_judge(**kwargs)
        if result.returncode != 0:
            raise RuntimeError(f"Rubric judge exited with status {result.returncode}")
        return result


def valid_rubric(rubric: dict) -> bool:
    checks = rubric.get("checks")
    return (type(rubric.get("overall_pass")) is bool and isinstance(checks, list)
            and len(checks) == 14
            and all(isinstance(check, dict) and isinstance(check.get("id"), str)
                    and type(check.get("pass")) is bool for check in checks)
            and {check["id"] for check in checks} == {f"rubric-{i}" for i in range(1, 15)})


def prepare_dependencies(language: str, workspace: Path, output: Path) -> None:
    commands = {"python": ["uv", "sync"], "node": ["npm", "install"],
                "go": ["go", "mod", "download", "all"], "java": ["mvn", "-q", "test"]}
    command = commands[language]
    with (output / "baseline-dependencies.log").open("w") as log:
        result = subprocess.run(command, cwd=workspace / "service", stdout=log, stderr=subprocess.STDOUT, timeout=600)
    if result.returncode:
        raise RuntimeError(f"Baseline dependency preparation failed: {command}")


def run(args: argparse.Namespace) -> int:
    repo, output = args.repo.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    config = tomllib.loads((repo / "evals/codex-evals.toml").read_text())
    assert config["models"] == {"agent": "gpt-6.1-sol", "judge": "gpt-6.1-sol"}
    extra_args = config["agent"]["extra_args"]
    assert 'model_reasoning_effort="high"' in extra_args and not any("xhigh" in value for value in extra_args)
    backend = CodexBackend(extra_args=extra_args)
    workspace = Path(tempfile.mkdtemp(prefix=f"logging-workflow-{args.language}-trial-{args.trial}-"))
    case = case_for(repo, args.language, "audit", args.trial)
    prepare_side_workspace(repo, case, "with_skill", workspace)
    for role in ("instrument", "verify"):
        shutil.copytree(repo / "skills" / f"otel-{role}", workspace / ".agents/skills" / f"otel-{role}",
                        ignore=skill_workspace_ignore)
    (workspace / "AGENTS.md").write_text("Run this evaluation headlessly. Do not open or control desktop applications or browsers.\n")
    original_bundle = bundle_hashes(workspace)
    ports = reserve_ports()
    # A dedicated runner process owns its environment. Never change global user config.
    for key in list(os.environ):
        if key.startswith(("SPLUNK_", "SIGNALFX_", "SFX_", "OTEL_", "OBSTUDIO_")) or key.lower().startswith("npm_config_") or key in {"JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS"}:
            os.environ.pop(key)
    endpoint = f"http://127.0.0.1:{ports['http']}"
    npm_global = workspace / ".npm-globalrc"
    npm_global.write_text("# Isolated public-fixture package configuration\n")
    os.environ.update(CODEX_EVAL_HOME=str(args.codex_home.resolve()), UV_NO_CONFIG="1",
                      PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", os.defpath),
                      NPM_CONFIG_USERCONFIG=os.devnull, NPM_CONFIG_GLOBALCONFIG=str(npm_global),
                      NPM_CONFIG_REGISTRY="https://registry.npmjs.org", UV_DEFAULT_INDEX="https://pypi.org/simple",
                      PIP_CONFIG_FILE=os.devnull, PIP_INDEX_URL="https://pypi.org/simple",
                      PORT=str(ports["app"]), HOST="127.0.0.1", OTEL_SERVICE_NAME=f"{args.language}-logging-workflow",
                      OTEL_RESOURCE_ATTRIBUTES="deployment.environment.name=eval", OTEL_EXPORTER_OTLP_ENDPOINT=endpoint,
                      OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf", OTEL_TRACES_EXPORTER="otlp", OTEL_METRICS_EXPORTER="otlp",
                      LOGGING_WORKFLOW_VERIFIER=str(repo / "evals/logging_workflow_check.py"),
                      LOGGING_WORKFLOW_PYTHON=sys.executable, LOGGING_WORKFLOW_STUDIO_URL=f"http://127.0.0.1:{ports['rest']}")
    for signal in ("TRACES", "METRICS", "LOGS"):
        os.environ[f"OTEL_EXPORTER_OTLP_{signal}_ENDPOINT"] = endpoint + "/v1/" + signal.lower()
    summary = {"status": "running", "language": args.language, "trial": args.trial,
               "workspace": str(workspace), "stages": [], "ports": ports,
               "model": "gpt-6.1-sol", "reasoning_effort": "high",
               "collect_semantic_failures": getattr(args, "collect_semantic_failures", False),
               "diagnostic_only": False}
    receiver = None
    try:
        prepare_dependencies(args.language, workspace, output)
        receiver = start_receiver(args.studio_binary.resolve(), output, ports)
        for role in ("audit", "instrument", "verify"):
            case = case_for(repo, args.language, role, args.trial)
            stage = {"role": role, "task": case.task, "status": "running", "source_before": source_hashes(workspace / "service")}
            stage["audit_sha256_before"] = audit_hash(workspace)
            summary["stages"].append(stage)
            save(output / "summary.json", summary)
            started = time.monotonic()
            result = backend.run_agent(prompt=case.task, exec_dir=workspace, model="gpt-6.1-sol", timeout=args.agent_timeout)
            stage["agent_seconds"] = time.monotonic() - started
            stage["agent_exit_code"] = result.returncode
            stage["task_model"] = bind_model_metadata(result.trace_path, args.codex_home.resolve(), workspace)
            stage["source_after"] = source_hashes(workspace / "service")
            stage["audit_sha256_after"] = audit_hash(workspace)
            stage["skill_bundle_unchanged"] = bundle_hashes(workspace) == original_bundle
            trace = backend.parse_trace(result.trace_path)
            grade = grade_side(case=case, run_dir=workspace, final_message=result.final_message_path.read_text(),
                               trace=trace, side="with_skill", repo_root=repo)
            (workspace / "grade.json").write_text(grade.model_dump_json(indent=2))
            stage["guards"] = grade.model_dump(mode="json")
            if role != "audit":
                command = [sys.executable, str(repo / "evals/logging_workflow_check.py"),
                           "--start-command-json", '["make","dev"]', "--operator-identity-profiles"]
                stage["independent_runtime_command"] = command
                stage["independent_runtime_timeout_seconds"] = 720
                with (output / f"{role}-independent-runtime.log").open("w") as log:
                    check = subprocess.Popen(command, cwd=workspace / "service", stdout=log,
                                             stderr=subprocess.STDOUT, start_new_session=True)
                    try:
                        check.wait(timeout=stage["independent_runtime_timeout_seconds"])
                    finally:
                        if check.poll() is None:
                            stop_owned(check, timeout=15)
                stage["independent_runtime_exit_code"] = check.returncode
            judge_before = source_hashes(workspace / "service")
            rubric_path = run_rubric_grade(case=case, side_dir=workspace, model="gpt-6.1-sol", backend=CheckedJudgeBackend(backend), timeout=args.judge_timeout)
            stage["rubric_model"] = bind_model_metadata(workspace / "rubric_trace.jsonl", args.codex_home.resolve(), workspace)
            assert source_hashes(workspace / "service") == judge_before, "Read-only grader changed service inputs"
            rubric = json.loads(rubric_path.read_text())
            stage["rubric"] = rubric
            stage["skill_bundle_unchanged"] = bundle_hashes(workspace) == original_bundle
            rubric_complete = isinstance(rubric, dict) and valid_rubric(rubric)
            required_guards = {"final-message-present", "skills-loaded", "skill-instructions-read"}
            guards_passed = (required_guards <= {check.id for check in grade.checks}
                             and all(check.passed and not check.skipped for check in grade.checks))
            fatal_passed = (result.returncode == 0 and guards_passed and rubric_complete
                            and stage["skill_bundle_unchanged"]
                            and stage["audit_sha256_after"] == audit_hash(workspace)
                            and (role == "audit" or stage["audit_sha256_before"] is not None
                                 and stage["audit_sha256_before"] == stage["audit_sha256_after"] == audit_hash(workspace))
                            and (role == "audit" or stage["independent_runtime_exit_code"] == 0)
                            and (role == "instrument" or stage["source_before"] == stage["source_after"]))
            if fatal_passed and summary["collect_semantic_failures"]:
                try:
                    validate_audit_handoff(repo, workspace)
                except Exception as error:
                    fatal_passed = False
                    stage["audit_handoff_error"] = type(error).__name__ + ": " + str(error)
            semantic_passed = rubric_complete and rubric["overall_pass"] and all(check["pass"] for check in rubric["checks"])
            passed = fatal_passed and semantic_passed
            stage["status"] = "passed" if passed else "failed"
            stage["failure_kind"] = None if passed else "semantic" if fatal_passed else "fatal"
            archive_stage(workspace, output / role)
            isolate_stage_feedback(workspace, output / role)
            save(output / "summary.json", summary)
            print(json.dumps({"language": args.language, "trial": args.trial, "role": role, "status": stage["status"]}), flush=True)
            if not passed:
                if not (fatal_passed and summary["collect_semantic_failures"]):
                    raise RuntimeError(f"{role} stage did not pass all required guards, rubric and applicable runtime checks")
                stage["diagnostic_continuation"] = True
                summary["diagnostic_only"] = True
                save(output / "summary.json", summary)
        if any(stage["status"] != "passed" for stage in summary["stages"]):
            summary.update(status="failed", error="Semantic rubric failure; later stages are diagnostic only")
        else:
            summary["status"] = "passed"
    except Exception as error:
        summary.update(status="failed", error=type(error).__name__ + ": " + str(error))
    finally:
        if receiver is not None:
            summary["receiver_cleanup_graceful"] = stop_owned(receiver)
            if not summary["receiver_cleanup_graceful"]:
                summary.update(status="failed", cleanup_error="Receiver required forced shutdown")
        save(output / "summary.json", summary)
    print(json.dumps({"summary": str(output / "summary.json"), "status": summary["status"], "error": summary.get("error")}), flush=True)
    return 0 if summary["status"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--language", choices=SERVICES, required=True)
    parser.add_argument("--trial", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--studio-binary", type=Path, required=True)
    parser.add_argument("--codex-home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--agent-timeout", type=int, default=3600)
    parser.add_argument("--judge-timeout", type=int, default=1200)
    parser.add_argument("--collect-semantic-failures", action="store_true",
                        help="Collect later bare stages after semantic-only failure; workflow remains failed")
    return run(parser.parse_args())


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupt_owned_run)
    raise SystemExit(main())
