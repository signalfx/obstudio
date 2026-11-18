"""Run bare audit/instrument/verify eval tasks on one retained, real service."""
from __future__ import annotations

import argparse
import codecs
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request

from pytest_codex_evals.backends import CodexBackend
from pytest_codex_evals.config import load_settings
from pytest_codex_evals.eval_files import skill_workspace_ignore, staged_skill_source_files
from pytest_codex_evals.graders import grade_side
from pytest_codex_evals.graders.rubric import run_rubric_dimensions
from pytest_codex_evals.plugin import case_from_definition, load_eval_definition
from pytest_codex_evals.runner import prepare_side_workspace

from logging_workflow_check import interrupt_owned_run, source_hashes, stop_owned


SERVICES = {"go": "chi-basic", "python": "flask-basic"}
DEPENDENCY_TIMEOUT_SECONDS = 600

_CLONEFILE = None
if sys.platform == "darwin":
    import ctypes
    try:
        _CLONEFILE = ctypes.CDLL(None, use_errno=True).clonefile
        _CLONEFILE.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32)
        _CLONEFILE.restype = ctypes.c_int
    except (AttributeError, OSError):
        _CLONEFILE = None


def save(path: Path, value: dict) -> None:
    payload = json.dumps(value, indent=2) + "\n"
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def bundle_hashes(workspace: Path) -> dict[str, str]:
    root = workspace / ".agents/skills"
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in staged_skill_source_files(root)}


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
    owner = "logging-workflow-eval-" + secrets.token_hex(8)
    home = output / "receiver-home"
    home.mkdir(mode=0o700)
    env_file = output / "receiver.env"
    env_file.write_text("# Isolated credential-free eval receiver\n")
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("SPLUNK_", "SIGNALFX_", "SFX_", "OTEL_", "OBSTUDIO_"))}
    environment.update(HOME=str(home), OBSTUDIO_CONFIG_MANAGER="false", OTLP_HTTP_PORT=str(ports["http"]),
                       OTLP_GRPC_PORT=str(ports["grpc"]), OTLP_GRPC_HOST="127.0.0.1",
                       OBSTUDIO_OWNER=owner, OBSTUDIO_MODE="standalone")
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
                assert health.get("owner") == owner, "Receiver ownership mismatch"
                save(output / "receiver.json", {"pid": process.pid, "command": command, "ports": ports,
                     "health": health, "home": str(home), "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest()})
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
    assert (meta.get("id") == ids[0] and isinstance(meta.get("cwd"), str)
            and Path(meta["cwd"]).resolve() == workspace.resolve())
    assert contexts and all(value["model"] == "gpt-6.1-sol" and value["effort"] == "high"
                            and isinstance(value["cwd"], str)
                            and Path(value["cwd"]).resolve() == workspace.resolve() for value in contexts)
    return {"thread_id": ids[0], "session": str(sessions[0]), "started": meta["timestamp"],
            "model": "gpt-6.1-sol", "reasoning_effort": "high", "turns": len(contexts),
            "cwd": str(workspace.resolve())}


ACTOR_ARTIFACTS = ("trace.jsonl", "last_message.md", "stderr.txt")


def read_actor_file(path: Path) -> bytes | None:
    """Read one completed actor artifact without following links or special files."""
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise RuntimeError(f"Cannot safely read actor artifact: {path.name}") from error
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise RuntimeError(f"Actor artifact must be a single-link regular file: {path.name}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        with os.fdopen(os.open(path, flags), "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise RuntimeError(f"Actor artifact must be a single-link regular file: {path.name}")
            value = stream.read()
            after = os.fstat(stream.fileno())
        identities = {(s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size,
                       s.st_mtime_ns, s.st_ctime_ns) for s in (before, opened, after, path.lstat())}
        if len(identities) != 1:
            raise RuntimeError(f"Actor artifact changed while reading: {path.name}")
        return value
    except OSError as error:
        raise RuntimeError(f"Cannot safely read actor artifact: {path.name}") from error


def copy_archive_file(source: str, destination: str) -> str:
    """Clone fresh macOS archive files when possible, otherwise use ordinary copy2."""
    if sys.platform == "darwin" and _CLONEFILE is not None:
        try:
            # Flagged clones can reject copystat; leave those files to copy2.
            # CLONE_NOOWNERCOPY keeps copy2's destination ownership semantics.
            if (not getattr(os.stat(source), "st_flags", 0)
                    and _CLONEFILE(os.fsencode(source), os.fsencode(destination), 0x0002) == 0):
                shutil.copystat(source, destination)
                return destination
        except OSError:
            pass
    return shutil.copy2(source, destination)


def archive_stage(workspace: Path, destination: Path, *, actor_hashes: dict[str, str] | None = None) -> None:
    destination.mkdir()
    refused = []
    for name in (*ACTOR_ARTIFACTS, *GRADER_FEEDBACK_ARTIFACTS):
        try:
            value = read_actor_file(workspace / name)
            if actor_hashes and name in actor_hashes:
                if value is None or hashlib.sha256(value).hexdigest() != actor_hashes[name]:
                    raise RuntimeError(f"Actor artifact changed before archive: {name}")
            if value is not None:
                with (destination / name).open("xb") as stream:
                    stream.write(value)
        except RuntimeError as error:
            refused.append(str(error))
    shutil.copytree(workspace / "service", destination / "service", symlinks=True,
                    copy_function=copy_archive_file,
                    ignore=shutil.ignore_patterns(".venv", "node_modules", "target", "__pycache__", "*.db"))
    if refused:
        raise RuntimeError("; ".join(refused))


GRADER_FEEDBACK_ARTIFACTS = (
    "grade.json", "evidence-receipt-check.json",
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


def load_report_module(repo: Path, filename: str = "observe_report_core.py"):
    """Import the canonical repository helper, never the actor's staged copy."""
    script = repo / "skills/references/scripts" / filename
    spec = importlib.util.spec_from_file_location("logging_workflow_" + script.stem, script)
    if spec is None or spec.loader is None:
        raise RuntimeError("Canonical report parser unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module



def _linux_process_identity(process: Path) -> tuple[str, int]:
    # The comm field may contain spaces and parentheses; starttime is field 22.
    prefix, separator, tail = (process / "stat").read_text().rpartition(")")
    if not separator or prefix.split(" ", 1)[0] != process.name:
        raise ValueError("Unrecognized Linux process identity")
    fields = tail.split()
    return fields[0], int(fields[19])


def capture_process_baseline(*, timeout: float = 5) -> dict[int, int]:
    """Capture host identities before creating the private trial workspace."""
    identities = {}
    if sys.platform != "linux":
        return identities
    deadline = time.monotonic() + timeout
    for process in Path("/proc").iterdir():
        if time.monotonic() >= deadline:
            raise TimeoutError("Host process baseline exceeded its budget")
        if not process.name.isdecimal():
            continue
        try:
            if process.stat().st_uid == os.getuid():
                identities[int(process.name)] = _linux_process_identity(process)[1]
        except (OSError, ValueError, IndexError):
            # Unknown identities cannot qualify for the later baseline exception.
            continue
    return identities


def workspace_processes(workspace: Path, *, timeout: float = 5,
                        preexisting_processes: dict[int, int] | None = None) -> dict[int, dict]:
    """Find same-user work by cwd or writable files in the private trial."""
    root = workspace.resolve()
    deadline = time.monotonic() + timeout
    candidates = {}
    working_directories = {}

    def check_deadline():
        if time.monotonic() >= deadline:
            raise TimeoutError("Trial process inventory exceeded its budget")

    def consider(pid, path, reason):
        check_deadline()
        if pid != os.getpid() and path.is_relative_to(root):
            path = path.resolve()
            if path.is_relative_to(root) and (reason == "cwd" or pid not in candidates):
                candidates[pid] = {"reason": reason, "path": str(path)}

    if sys.platform == "linux":
        for path in Path("/proc").iterdir():
            check_deadline()
            if not path.name.isdecimal() or int(path.name) == os.getpid():
                continue
            pid = int(path.name)
            try:
                if path.stat().st_uid != os.getuid():
                    continue
                try:
                    cwd = (path / "cwd").resolve(strict=True)
                except FileNotFoundError:
                    pass  # A live writer can retain files after its cwd is removed.
                else:
                    working_directories[pid] = str(cwd)
                    consider(pid, cwd, "cwd")
                if pid in candidates:
                    continue
                for descriptor in (path / "fd").iterdir():
                    check_deadline()
                    try:
                        target = Path(os.readlink(descriptor))
                        if not target.is_absolute() or not target.resolve().is_relative_to(root):
                            continue
                        info = (path / "fdinfo" / descriptor.name).read_text()
                        flags = next(line.split()[1] for line in info.splitlines() if line.startswith("flags:"))
                        if int(flags, 8) & os.O_ACCMODE in {os.O_WRONLY, os.O_RDWR}:
                            consider(pid, target.resolve(), "fd")
                            break
                    except (FileNotFoundError, ProcessLookupError):
                        continue
            except (FileNotFoundError, ProcessLookupError):
                continue
            except PermissionError as error:
                try:
                    process_state, identity = _linux_process_identity(path)
                except (FileNotFoundError, ProcessLookupError):
                    continue
                except (OSError, ValueError, IndexError) as identity_error:
                    raise RuntimeError(f"Cannot establish ownership of protected process {pid}") from identity_error
                if process_state == "Z":
                    continue  # A kernel-confirmed zombie cannot retain writable files.
                if preexisting_processes is not None and preexisting_processes.get(pid) == identity:
                    continue
                raise RuntimeError(f"Cannot establish ownership of protected process {pid}") from error
    elif sys.platform == "darwin":
        result = subprocess.run(["/usr/sbin/lsof", "-nP", "-a", "-u", str(os.getuid()), "-F0pfan"],
                                capture_output=True, timeout=max(.001, deadline - time.monotonic()))
        if result.returncode != 0:
            raise RuntimeError("Cannot inspect trial-owned process working directories and files")
        pid, descriptor, access = None, None, None
        for field in result.stdout.split(b"\0"):
            check_deadline()
            field = field.removeprefix(b"\n")
            tag, value = field[:1], field[1:]
            if tag == b"p":
                pid, descriptor, access = int(value), None, None
            elif tag == b"f":
                descriptor, access = value, None
            elif tag == b"a":
                access = value
            elif tag == b"n" and pid is not None and (descriptor == b"cwd" or access in {b"w", b"u"}):
                # Even NUL-delimited lsof names use C escapes for newlines and backslashes.
                target = Path(os.fsdecode(codecs.escape_decode(value)[0]))
                if descriptor == b"cwd":
                    working_directories[pid] = str(target)
                consider(pid, target, "cwd" if descriptor == b"cwd" else "fd")
    else:
        raise RuntimeError("Trial process cleanup requires Linux /proc or macOS lsof")
    owned = {}
    for pid, witness in candidates.items():
        check_deadline()
        try:
            owned[pid] = {"pid": pid, "cwd": working_directories.get(pid),
                          "process_group": os.getpgid(pid), **witness}
        except ProcessLookupError:
            pass
    return owned


def cleanup_workspace_processes(workspace: Path, *, timeout: float = 5,
                                preexisting_processes: dict[int, int] | None = None) -> dict:
    """Reserve half the bounded cleanup window for escalation and confirmation."""
    deadline = time.monotonic() + timeout
    initial = workspace_processes(workspace, timeout=timeout / 2, preexisting_processes=preexisting_processes)
    current = initial
    forced = False
    errors = []
    for sig, phase_deadline in ((signal.SIGTERM, deadline - timeout / 2), (signal.SIGKILL, deadline)):
        if not current:
            break
        if sig == signal.SIGKILL:
            try:
                current = workspace_processes(workspace, timeout=max(.001, deadline - time.monotonic()),
                                              preexisting_processes=preexisting_processes)
            except (TimeoutError, subprocess.TimeoutExpired) as error:
                errors.append(type(error).__name__ + ": " + str(error))
                break
        # Each round uses one fresh ownership snapshot, with no scan or wait
        # between its PID signals. Never signal a PID after a failed recheck.
        for pid in current:
            try:
                os.kill(pid, sig)
                if sig == signal.SIGKILL:
                    forced = True
            except ProcessLookupError:
                pass
        while current and time.monotonic() < phase_deadline:
            remaining = phase_deadline - time.monotonic()
            try:
                current = workspace_processes(workspace, timeout=max(.001, remaining),
                                              preexisting_processes=preexisting_processes)
            except (TimeoutError, subprocess.TimeoutExpired) as error:
                errors.append(type(error).__name__ + ": " + str(error))
                break
            if current:
                time.sleep(min(.05, max(0, phase_deadline - time.monotonic())))
    return {"observed": list(initial.values()), "forced": forced,
            "remaining": list(current.values()), "complete": not current, "inventory_errors": errors}


def require_finished_probes(repo: Path, workspace: Path, stage: dict, *, owner: str = "actor",
                            preexisting_processes: dict[int, int] | None = None) -> None:
    owned = workspace_processes(workspace, preexisting_processes=preexisting_processes)
    if not owned:
        return
    # A healthy canonical finalizer server is intentional until trial teardown.
    module = load_report_module(repo, "observe_report.py")
    directory = (workspace / "service/.observe").resolve()
    canonical = (repo / "skills/references/scripts/observe_report.py").read_bytes()
    for pid in list(owned):
        try:
            if sys.platform == "linux":
                command = (Path("/proc") / str(pid) / "cmdline").read_bytes().decode().rstrip("\0").replace("\0", " ")
            else:
                command = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                                         capture_output=True, text=True, timeout=5).stdout.strip()
            match = re.fullmatch(r".+ -I (.+/observe_report\.py) serve-report --directory (.+) --state-file (.+)", command)
            if not match or os.getsid(pid) != pid:
                continue
            script, report_dir, state_path = (Path(value) for value in match.groups())
            if (not script.resolve().is_relative_to((workspace / ".agents/skills").resolve())
                    or script.read_bytes() != canonical or report_dir.resolve() != directory
                    or state_path.parent.is_symlink()):
                continue
            parent = state_path.parent.stat()
            if (state_path.parent.name != f"obstudio-report-servers-{os.getuid()}"
                    or parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) != 0o700):
                continue
            state = module.load_report_server_state(state_path, directory)
            if state is not None and state["pid"] == pid:
                owned.pop(pid)
        except (FileNotFoundError, ProcessLookupError):
            continue
    if owned:
        stage[f"leaked_{owner}_processes"] = list(owned.values())
        stage["probe_cleanup"] = cleanup_workspace_processes(workspace, preexisting_processes=preexisting_processes)
        raise RuntimeError(f"{owner} left trial-owned probe processes running: " + ", ".join(map(str, owned)))


def validate_audit_handoff(repo: Path, workspace: Path) -> None:
    """Use the existing canonical parser, without creating or repairing an audit."""
    module = load_report_module(repo)
    report = json.loads((workspace / "service/.observe/otel-audit.json").read_text())
    normalized = module.normalize_audit_report(report)
    if normalized["meta"]["status"] == "Blocked":
        raise RuntimeError("Blocked audit cannot authorize workflow continuation")


def check_evidence_receipt(repo: Path, workspace: Path, role: str) -> dict:
    """Record an independent mechanical gate without changing actor-owned proof."""
    service = workspace / "service"
    observed = service / ".observe"
    receipt = observed / "otel-evidence-receipt.json"
    canonical = observed / "otel-verify.json"
    direct_index = observed / "otel-direct-evidence-index.json"
    core = repo / "skills/references/scripts/observe_report_core.py"
    result = {"schema_version": 1, "kind": "logging-workflow-evidence-receipt-check",
              "role": role, "status": "failed", "reason": "Receipt check did not complete",
              "command": [sys.executable, str(repo / "skills/references/scripts/observe_report.py"),
                          "validate-evidence-receipt", "--receipt", str(receipt), "--service-root", str(service)],
              "execution": "in_process_canonical_api", "core": str(core),
              "receipt": str(receipt), "canonical_report": str(canonical)}
    try:
        if role == "audit":
            result.update(status="N_A", reason="Audit stage is plan-only", execution="not_applicable")
        elif not os.path.lexists(canonical):
            module = load_report_module(repo)
            result["core_sha256"] = hashlib.sha256(core.read_bytes()).hexdigest()
            result["direct_index"] = str(direct_index)
            if direct_index.is_symlink() or not direct_index.is_file() or not direct_index.resolve().is_relative_to(service.resolve()):
                raise ValueError("Direct-report index must be an owned regular file: " + str(direct_index))
            index = module.load_json(direct_index)
            scenarios = module.as_list(index.get("scenarios"), "direct_index.scenarios")
            executed = any(module.as_object(row, "direct_index.scenario").get("execution") == "executed" for row in scenarios)
            if executed:
                result["validation"] = module.validate_evidence_receipt(receipt, service)
                value = module.load_json(receipt)
                bound = receipt.parent / value["report"]["path"]
                if bound.resolve() != direct_index.resolve():
                    raise ValueError("Evidence receipt must bind the final direct-report index")
                validation = result["validation"].get("direct_index")
                if validation is None:
                    raise ValueError("Evidence receipt must validate the direct-report index")
            else:
                validation = module.validate_direct_evidence_index(direct_index, service)
            expected = observed / ("otel-instrumentation.md" if role == "instrument" else "otel-verify.md")
            if expected.is_symlink() or not expected.is_file() or not expected.resolve().is_relative_to(service.resolve()):
                raise ValueError("Final direct report must be an owned regular file: " + expected.name)
            if str(expected.resolve()) not in validation["report_paths"]:
                raise ValueError("Direct-report index must bind the final " + expected.name)
            result["direct_result"] = validation["result"]
            if executed:
                result.update(status="valid", reason="Direct index claims, baked controls and final-report hashes validated")
            else:
                result["validation"] = validation
                result.update(status="N_A", reason="Validated direct index records no executed proof", execution="not_applicable")
        else:
            if canonical.is_symlink() or not canonical.is_file() or not canonical.resolve().is_relative_to(service.resolve()):
                raise ValueError("Canonical verification overlay must be an owned regular file")
            module = load_report_module(repo)
            result["core_sha256"] = hashlib.sha256(core.read_bytes()).hexdigest()
            audit_data = module.load_json(observed / "otel-audit.json")
            audit = module.normalize_audit_report(audit_data)
            selection_path = observed / "otel-selection.json"
            selection = module.load_selection(selection_path if selection_path.exists() else None, audit, audit_data)
            instrumentation = module.normalize_instrumentation(
                module.load_json(observed / "otel-instrumentation.json"), audit, selection)
            report = module.normalize_verify(module.load_json(canonical), audit, selection, instrumentation)
            result["canonical_result"] = report["meta"]["result"]
            rows = [row for finding in report["findings"]
                    for row in finding["scenarios"] + finding["item_results"]]
            executed = any(row["proof_mode"] != "not_run"
                           or row["status"] in {"working", "not_working"}
                           or row.get("trace_ids") or row["observed_telemetry"] for row in rows)
            if not executed and report["meta"]["result"] in {"Not run", "Blocked"}:
                result.update(status="N_A", reason="Validated canonical overlay records no executed proof", execution="not_applicable")
            else:
                result["validation"] = module.validate_evidence_receipt(receipt, service)
                # A receipt for a different self-consistent report cannot authorize this canonical overlay.
                value = module.load_json(receipt)
                bound = receipt.parent / value["report"]["path"]
                if bound.resolve() != canonical.resolve():
                    raise ValueError("Evidence receipt must bind the final canonical otel-verify.json")
                result.update(status="valid", reason="Canonical receipt inputs, raw artifacts and final report projection validated")
    except Exception as error:
        result.update(status="failed", reason=type(error).__name__ + ": " + str(error))
    save(workspace / "evidence-receipt-check.json", result)
    return result


class BoundJudgeBackend:
    """Bind successful D judges before their temporary working folders disappear."""
    def __init__(self, backend: CodexBackend, codex_home: Path):
        self.backend, self.codex_home = backend, codex_home
        self.models = {}

    @property
    def name(self):
        return self.backend.name

    def parse_trace(self, path):
        return self.backend.parse_trace(path)

    def run_judge(self, **kwargs):
        result = self.backend.run_judge(**kwargs)
        if result.returncode == 0:
            self.models[kwargs["output_dir"].name] = bind_model_metadata(
                result.trace_path, self.codex_home, kwargs["exec_dir"],
            )
        return result


def runtime_capture_context(log: Path, workspace: Path, checker: Path) -> list[dict]:
    """Only paths returned by this checker invocation can identify its captures."""
    workspace = workspace.resolve()
    root = workspace / "service/.observe/logging-workflow-proof"
    if ((workspace / "service").is_symlink()
            or not root.resolve().is_relative_to(workspace / "service")):
        raise ValueError("Independent checker proof root is outside the current service")
    calls = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    if len(calls) != 4:
        raise ValueError("Independent checker must return the default and three identity profiles")
    records, profiles, paths = [], set(), set()
    for call in calls:
        path = Path(call["proof"])
        if (not path.is_absolute() or path.is_symlink() or not path.is_file()
                or not path.resolve().is_relative_to(root.resolve())
                or any(p.is_symlink() for p in path.parents if p.resolve().is_relative_to(workspace))):
            raise ValueError("Independent checker returned an unowned proof path")
        if path.resolve() in paths:
            raise ValueError("Independent checker repeated a proof path")
        paths.add(path.resolve())
        raw = path.read_bytes()
        value = json.loads(raw)
        profile = value.get("identity_profile", "default")
        if profile in profiles or value["status"] != call["status"] or value["status"] != "passed":
            raise ValueError("Independent checker returned inconsistent captures")
        profiles.add(profile)
        if (Path(value["cwd"]).resolve() != workspace / "service"
                or Path(value["proof_directory"]).resolve() != path.parent.resolve()
                or value["verifier_sha256"] != hashlib.sha256(checker.read_bytes()).hexdigest()
                or value["source_before"] != value["source_after"]
                or value["source_after"] != source_hashes(workspace / "service")):
            raise ValueError("Independent checker capture is not bound to current execution inputs")
        records.append({"proof": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                        "identity_profile": profile, "status": value["status"], "scope": value["scope"],
                        "evidence_bake": value.get("evidence_bake")})
    if profiles != {"default", "resource-only", "explicit-override", "resource-whitespace"}:
        raise ValueError("Independent checker identity profiles are incomplete")
    return records


def grading_case(case, stage: dict, captures: list[dict]):
    context = {"role": stage["role"], "kind": "runner-owned-execution-context",
               "evidence_receipt_guard": stage["evidence_receipt_guard"],
               "independent_runtime_exit_code": stage.get("independent_runtime_exit_code"),
               "independent_runtime_captures": captures}
    encoded = json.dumps(context, sort_keys=True, separators=(",", ":"))
    effective = case.model_copy(update={"judge_inputs": [*case.judge_inputs,
        "Runner-owned facts from the current calls follow. Candidate files with similar names do not "
        "authenticate themselves. Scope is limited to the recorded checks, not complete semantic acceptance.\n" + encoded]})
    contract = json.dumps({"rubric": effective.rubric, "judge_inputs": effective.judge_inputs,
                           "rubric_dimensions": [g.model_dump() for g in effective.rubric_dimensions]},
                          sort_keys=True, separators=(",", ":")).encode()
    stage["grading_context_sha256"] = hashlib.sha256(encoded.encode()).hexdigest()
    stage["effective_rubric_contract_sha256"] = hashlib.sha256(contract).hexdigest()
    return effective


def prepare_dependencies(language: str, workspace: Path, output: Path) -> None:
    if os.name != "posix":
        raise RuntimeError("Logging workflow dependency cleanup requires POSIX process groups")
    commands = {'python': ['uv', 'sync'], 'go': ['go', 'mod', 'download', 'all']}
    command = commands[language]
    with (output / "baseline-dependencies.log").open("w") as log:
        process = subprocess.Popen(command, cwd=workspace / "service", stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            returncode = process.wait(timeout=DEPENDENCY_TIMEOUT_SECONDS)
        finally:
            # Setup must not leave tool children running, even after their parent exits.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            finally:
                process.wait(timeout=5)
    if returncode:
        raise RuntimeError(f"Baseline dependency preparation failed: {command}")


def run(args: argparse.Namespace) -> int:
    repo, output = args.repo.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    config_path = repo / "evals/codex-evals.logging.toml"
    config = load_settings(config_path)
    assert (config.agent_model, config.judge_model) == ("gpt-6.1-sol", "gpt-6.1-sol")
    assert config.agent_backend == "codex" and config.agent_command is None
    extra_args = config.agent_extra_args
    assert 'model_reasoning_effort="high"' in extra_args and not any("xhigh" in value for value in extra_args)
    judge_timeout = config.judge_timeout if args.judge_timeout is None else args.judge_timeout
    judge_timeout_source = "config" if args.judge_timeout is None else "cli"
    backend = CodexBackend(extra_args=extra_args)
    preexisting_processes = capture_process_baseline()
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
               "configuration": {"path": str(config_path), "sha256": hashlib.sha256(config_path.read_bytes()).hexdigest()},
               "model": "gpt-6.1-sol", "reasoning_effort": "high",
               "collect_semantic_failures": getattr(args, "collect_semantic_failures", False),
               "diagnostic_only": False}
    receiver = None
    try:
        prepare_dependencies(args.language, workspace, output)
        receiver = start_receiver(args.studio_binary.resolve(), output, ports)
        for role in ("audit", "instrument", "verify"):
            previous_outputs = []
            for name in ACTOR_ARTIFACTS:
                value = read_actor_file(workspace / name)
                if value is None:
                    continue
                if not summary["stages"]:
                    raise RuntimeError(f"Unexpected actor artifact before the first stage: {name}")
                previous = output / summary["stages"][-1]["role"] / name
                if read_actor_file(previous) != value:
                    raise RuntimeError(f"Previous actor artifact is not safely archived: {name}")
                previous_outputs.append(name)
            for name in previous_outputs:
                (workspace / name).unlink()
            case = case_for(repo, args.language, role, args.trial)
            stage = {"role": role, "task": case.task, "status": "running", "source_before": source_hashes(workspace / "service"),
                     "judge_timeout_seconds": judge_timeout, "judge_timeout_source": judge_timeout_source}
            stage["rubric_contract"] = {
                "criterion_count": len(case.rubric),
                "sha256": hashlib.sha256(json.dumps({"rubric": case.rubric, "judge_inputs": case.judge_inputs},
                                                   sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            }
            stage["audit_sha256_before"] = audit_hash(workspace)
            summary["stages"].append(stage)
            save(output / "summary.json", summary)
            started = time.monotonic()
            result = backend.run_agent(prompt=case.task, exec_dir=workspace, model="gpt-6.1-sol", timeout=args.agent_timeout)
            stage["agent_seconds"] = time.monotonic() - started
            stage["agent_exit_code"] = result.returncode
            stage["source_after"] = source_hashes(workspace / "service")
            stage["audit_sha256_after"] = audit_hash(workspace)
            stage["skill_bundle_unchanged"] = bundle_hashes(workspace) == original_bundle
            actor_files = {name: read_actor_file(workspace / name) for name in ACTOR_ARTIFACTS}
            stage["actor_artifact_sha256"] = {name: hashlib.sha256(value).hexdigest()
                                               for name, value in actor_files.items() if value is not None}
            final_message = (actor_files["last_message.md"] or b"").decode("utf-8")
            if (result.returncode != 0 or not final_message.strip()
                    or any(value is None for value in actor_files.values())):
                stage.update(status="failed", failure_kind="fatal")
                archive_stage(workspace, output / role, actor_hashes=stage["actor_artifact_sha256"])
                raise RuntimeError(f"{role} actor failed or produced no current final response")
            require_finished_probes(repo, workspace, stage, preexisting_processes=preexisting_processes)
            stage["task_model"] = bind_model_metadata(result.trace_path, args.codex_home.resolve(), workspace)
            stage["evidence_receipt_guard"] = check_evidence_receipt(repo, workspace, role)
            trace = backend.parse_trace(result.trace_path)
            grade = grade_side(case=case, run_dir=workspace, final_message=final_message,
                               trace=trace, side="with_skill", repo_root=repo)
            save(workspace / "grade.json", grade.model_dump(mode="json"))
            stage["guards"] = grade.model_dump(mode="json")
            captures = []
            if role != "audit":
                command = [sys.executable, str(repo / "evals/logging_workflow_check.py"),
                           "--start-command-json", '["make","dev"]', "--operator-identity-profiles", "--bake-evidence"]
                stage["independent_runtime_command"] = command
                stage["independent_runtime_timeout_seconds"] = 720
                runtime_log = output / f"{role}-independent-runtime.log"
                runtime_stderr = output / f"{role}-independent-runtime.stderr.log"
                with runtime_log.open("w") as log, runtime_stderr.open("w") as diagnostics:
                    check = subprocess.Popen(command, cwd=workspace / "service", stdout=log,
                                             stderr=diagnostics, start_new_session=True)
                    try:
                        check.wait(timeout=stage["independent_runtime_timeout_seconds"])
                    finally:
                        if check.poll() is None:
                            stop_owned(check, timeout=15)
                stage["independent_runtime_exit_code"] = check.returncode
                if check.returncode == 0:
                    captures = runtime_capture_context(runtime_log, workspace, repo / "evals/logging_workflow_check.py")
            if role != "audit":
                require_finished_probes(repo, workspace, stage, owner="checker",
                                        preexisting_processes=preexisting_processes)
            judge_before = source_hashes(workspace / "service")
            effective_case = grading_case(case, stage, captures)
            archive_stage(workspace, output / role, actor_hashes=stage["actor_artifact_sha256"])
            save(output / role / "grading-contract.json", effective_case.model_dump(mode="json"))
            judge_backend = BoundJudgeBackend(backend, args.codex_home.resolve())
            stage["rubric_models"] = judge_backend.models
            save(output / "summary.json", summary)
            rubric_path = run_rubric_dimensions(
                case=effective_case, workspace_dir=workspace, output_dir=output / f"{role}.rubric",
                model="gpt-6.1-sol", backend=judge_backend, deadline=time.monotonic() + judge_timeout,
            )
            assert source_hashes(workspace / "service") == judge_before, "Read-only grader changed service inputs"
            rubric = json.loads(rubric_path.read_text())
            stage["rubric"] = rubric
            stage["skill_bundle_unchanged"] = bundle_hashes(workspace) == original_bundle
            rubric_complete = rubric["status"] == "complete" and rubric["acceptance"] in {"pass", "fail"}
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
            if fatal_passed:
                try:
                    validate_audit_handoff(repo, workspace)
                except Exception as error:
                    fatal_passed = False
                    stage["audit_handoff_error"] = type(error).__name__ + ": " + str(error)
            semantic_passed = rubric_complete and rubric["acceptance"] == "pass"
            evidence_gate_passed = stage["evidence_receipt_guard"]["status"] in {"valid", "N_A"}
            passed = fatal_passed and semantic_passed and evidence_gate_passed
            stage["semantic_passed"] = semantic_passed
            stage["evidence_gate_passed"] = evidence_gate_passed
            stage["status"] = "passed" if passed else "failed"
            stage["failure_kind"] = (None if passed else "grading" if not rubric_complete else "fatal" if not fatal_passed
                                     else "gate" if not evidence_gate_passed else "semantic")
            isolate_stage_feedback(workspace, output / role)
            save(output / "summary.json", summary)
            print(json.dumps({"language": args.language, "trial": args.trial, "role": role, "status": stage["status"]}), flush=True)
            if not passed:
                if not (fatal_passed and summary["collect_semantic_failures"]):
                    raise RuntimeError(f"{role} stage did not pass all required guards, evidence receipt, rubric and applicable runtime checks")
                stage["diagnostic_continuation"] = True
                summary["diagnostic_only"] = True
                save(output / "summary.json", summary)
        if any(stage["status"] != "passed" for stage in summary["stages"]):
            summary.update(status="failed", error="Semantic rubric or evidence-receipt failure; later stages are diagnostic only")
        else:
            summary["status"] = "passed"
    except (Exception, KeyboardInterrupt) as error:
        if summary["stages"] and summary["stages"][-1]["status"] == "running":
            summary["stages"][-1].update(status="failed", failure_kind="fatal")
        summary.update(status="failed", error=type(error).__name__ + ": " + str(error))
    finally:
        try:
            summary["workspace_cleanup"] = cleanup_workspace_processes(workspace, preexisting_processes=preexisting_processes)
            if not summary["workspace_cleanup"]["complete"]:
                summary.update(status="failed", cleanup_error="Trial-owned processes survived cleanup")
        except Exception as cleanup_error:
            summary.update(status="failed", cleanup_error=type(cleanup_error).__name__ + ": " + str(cleanup_error))
        if summary["stages"] and not (output / summary["stages"][-1]["role"]).exists():
            try:
                archive_stage(workspace, output / summary["stages"][-1]["role"],
                              actor_hashes=summary["stages"][-1].get("actor_artifact_sha256"))
            except Exception as archive_error:
                summary["archive_error"] = type(archive_error).__name__ + ": " + str(archive_error)
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
    parser.add_argument("--judge-timeout", type=int, default=None,
                        help="Override the shared judge budget from codex-evals.logging.toml")
    parser.add_argument("--collect-semantic-failures", action="store_true",
                        help="Collect later bare stages after semantic or evidence-gate failure; workflow remains failed")
    return run(parser.parse_args())


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupt_owned_run)
    raise SystemExit(main())
