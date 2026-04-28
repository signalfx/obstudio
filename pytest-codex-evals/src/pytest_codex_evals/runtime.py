from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .models import DeterministicCheck, GradeCheckResult


def run_observer_docker_runtime(
    check: DeterministicCheck,
    service_dir: Path,
    repo_root: Path | None = None,
    eval_dir: Path | None = None,
) -> GradeCheckResult:
    config = check.runtime
    if not config:
        return runtime_result(check, False, "Runtime check requires a runtime object")

    compose_file: Path | None = None
    project = safe_name(f"codex-eval-{check.id}-{int(time.time() * 1000)}")
    env = runtime_env(repo_root, service_dir, project)
    try:
        compose_file = resolve_compose_file(config, service_dir, eval_dir)
        cwd = compose_file.parent

        run_process(compose_command(compose_file, project) + ["up", "-d", "--build"], cwd, env, check.timeout_seconds)
        wait_for_observer(config, check.timeout_seconds)
        clear_observer(config)
        run_process(compose_command(compose_file, project, profile="traffic") + ["run", "--rm", "traffic"], cwd, env, check.timeout_seconds)

        settle_seconds = float(config.get("settle_seconds", 5))
        if settle_seconds > 0:
            time.sleep(settle_seconds)

        passed, evidence = validate_observer_expectations(config)
        if not passed:
            evidence = evidence_with_compose_logs(evidence, compose_file, project, env)
        return runtime_result(check, passed, evidence)
    except Exception as exc:
        evidence = f"Runtime check failed: {exc}"
        if compose_file is not None:
            evidence = evidence_with_compose_logs(evidence, compose_file, project, env)
        return runtime_result(check, False, evidence)
    finally:
        if compose_file is not None:
            try:
                run_process(
                    compose_command(compose_file, project) + ["down", "-v", "--remove-orphans"],
                    compose_file.parent,
                    env,
                    timeout=60,
                    check=False,
                )
            except Exception:
                pass


def resolve_compose_file(config: dict[str, Any], service_dir: Path, eval_dir: Path | None = None) -> Path:
    value = config.get("compose_file")
    if not value:
        raise ValueError("runtime.compose_file is required")
    path = Path(str(value))
    if path.is_absolute():
        resolved = path
    else:
        base = eval_dir or service_dir
        resolved = (base / path).resolve()
    if not resolved.is_file():
        raise ValueError(f"compose_file not found: {resolved}")
    return resolved


def runtime_env(repo_root: Path | None, service_dir: Path, project: str) -> dict[str, str]:
    env = os.environ.copy()
    env["CODEX_EVAL_SERVICE_DIR"] = str(service_dir.resolve())
    env["COMPOSE_PROJECT_NAME"] = project
    if repo_root is not None:
        env["CODEX_EVAL_REPO_ROOT"] = str(repo_root.resolve())
    return env


def compose_command(compose_file: Path, project: str, profile: str | None = None) -> list[str]:
    command = ["docker", "compose", "-p", project, "-f", str(compose_file)]
    if profile:
        command.extend(["--profile", profile])
    return command


def run_process(
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"command executable not found: {exc.filename}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"command timed out after {exc.timeout}s: {' '.join(command)}") from exc

    if check and completed.returncode != 0:
        output = command_output(completed)
        raise RuntimeError(f"{' '.join(command)} exited {completed.returncode}: {output}")
    return completed


def command_output(completed: subprocess.CompletedProcess[str], limit: int = 2000) -> str:
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    return " ".join(output.split())[:limit]


def evidence_with_compose_logs(evidence: str, compose_file: Path, project: str, env: dict[str, str]) -> str:
    logs = compose_logs(compose_file, project, env)
    return f"{evidence}; {logs}" if logs else evidence


def compose_logs(compose_file: Path, project: str, env: dict[str, str]) -> str:
    try:
        completed = run_process(
            compose_command(compose_file, project) + ["logs", "--tail=80"],
            compose_file.parent,
            env,
            timeout=30,
            check=False,
        )
    except Exception:
        return ""
    output = command_output(completed, limit=5000)
    return f"compose logs: {output}" if output else ""


def clear_observer(config: dict[str, Any]) -> None:
    observer = observer_config(config)
    if observer.get("clear", True) is False:
        return
    request_text(observer_url(config, observer.get("clear_path", "/api/data")), method="DELETE", timeout=10, allow_404=True)


def wait_for_observer(config: dict[str, Any], timeout: int) -> None:
    observer = observer_config(config)
    health_path = str(observer.get("health_path", "/api/health"))
    url = observer_url(config, health_path)
    expect_status = int(observer.get("expect_status", 200))
    deadline = time.monotonic() + int(observer.get("timeout_seconds", timeout))
    last_error = ""
    while time.monotonic() < deadline:
        try:
            status, _ = request_text(url, timeout=5, return_status=True)
            if status == expect_status:
                return
            last_error = f"status {status}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1)
    raise TimeoutError(f"observer did not reach {expect_status}: {url}; last error: {last_error}")


def validate_observer_expectations(config: dict[str, Any]) -> tuple[bool, str]:
    expect = config.get("expect") or {}
    if not expect:
        return False, "runtime.expect is required"

    evidence = []
    failures = []
    traces = expect.get("traces") or {}
    if traces:
        text = request_json_text(observer_url(config, traces.get("path", "/api/query/traces")))
        check_expected_text("traces", text, traces, evidence, failures)

    metrics = expect.get("metrics") or {}
    if metrics:
        text = request_json_text(observer_url(config, metrics.get("path", "/api/query/metrics")))
        check_expected_text("metrics", text, metrics, evidence, failures)

    if not traces and not metrics:
        return False, "runtime.expect must include traces or metrics expectations"
    if failures:
        return False, "; ".join(failures)
    return True, "; ".join(evidence) if evidence else "Observer expectations passed"


def check_expected_text(scope: str, text: str, expect: dict[str, Any], evidence: list[str], failures: list[str]) -> None:
    for key in ("contains_all", "service_names", "span_names", "metric_names"):
        values = [str(value) for value in expect.get(key, [])]
        missing = [value for value in values if value.lower() not in text.lower()]
        if missing:
            failures.append(f"{scope} missing {key}: {', '.join(missing)}")
        elif values:
            evidence.append(f"{scope} matched {key}: {', '.join(values)}")

    for key in ("contains_any", "span_name_contains_any", "metric_name_contains_any"):
        values = [str(value) for value in expect.get(key, [])]
        if values and not any(value.lower() in text.lower() for value in values):
            failures.append(f"{scope} missing any {key}: {', '.join(values)}")
        elif values:
            evidence.append(f"{scope} matched one of {key}: {', '.join(values)}")


def observer_config(config: dict[str, Any]) -> dict[str, Any]:
    observer = config.get("observer") or {}
    if not isinstance(observer, dict):
        raise ValueError("runtime.observer must be an object")
    return observer


def observer_url(config: dict[str, Any], path: str) -> str:
    base_url = str(observer_config(config).get("base_url", "http://127.0.0.1:3000")).rstrip("/")
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return base_url + "/" + path.lstrip("/")


def request_json_text(url: str) -> str:
    _, text = request_text(url, timeout=15, return_status=True)
    try:
        return json.dumps(json.loads(text), sort_keys=True)
    except json.JSONDecodeError:
        return text


def request_text(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: int = 15,
    allow_404: bool = False,
    return_status: bool = False,
) -> str | tuple[int, str]:
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            return (response.status, text) if return_status else text
    except urllib.error.HTTPError as exc:
        if allow_404 and exc.code == 404:
            return (exc.code, "") if return_status else ""
        text = exc.read().decode("utf-8", errors="replace")
        if return_status:
            return exc.code, text
        raise


def runtime_result(check: DeterministicCheck, passed: bool, evidence: str) -> GradeCheckResult:
    return GradeCheckResult(
        id=check.id,
        description=check.description,
        passed=passed,
        evidence=evidence,
        category="runtime",
    )


def safe_name(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")[:63] or "codex-eval"
