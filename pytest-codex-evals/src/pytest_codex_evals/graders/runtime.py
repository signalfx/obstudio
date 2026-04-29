from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from pytest_codex_evals.definitions import GradeCheckResult, GradeResult, RuntimeCheck, RuntimeEvalCase
from pytest_codex_evals.trace import TraceSummary

from .shared import guard_checks


def grade_runtime(
    case: RuntimeEvalCase,
    run_dir: Path,
    final_message: str,
    trace: TraceSummary,
    side: str,
    *,
    runtime_enabled: bool = False,
    repo_root: Path | None = None,
) -> GradeResult:
    service_dir = run_dir / "service"
    eval_dir = case.definition_path.parent if case.definition_path else None
    results = guard_checks(run_dir, final_message, trace, side, case.skill)
    for check in case.checks:
        if check.applies_to not in ("both", side):
            continue
        if not runtime_enabled:
            results.append(
                runtime_result(
                    check,
                    True,
                    "Runtime check skipped; enable [runtime].enabled = true or pass --codex-runtime.",
                    skipped=True,
                )
            )
            continue
        results.append(run_observer_runtime(check, service_dir, repo_root, eval_dir))
    return GradeResult(checks=results)


def run_observer_runtime(
    check: RuntimeCheck,
    service_dir: Path,
    repo_root: Path | None = None,
    eval_dir: Path | None = None,
) -> GradeCheckResult:
    compose_file: Path | None = None
    project = safe_name(f"codex-eval-{uuid.uuid4().hex[:12]}")
    env = runtime_env(repo_root, service_dir, project)
    try:
        compose_file = resolve_compose_file(check, service_dir, eval_dir)
        cwd = compose_file.parent
        run_process(compose_command(compose_file, project) + ["up", "-d", "--build"], cwd, env, check.timeout_seconds)
        observer_base_url = discover_observer_base_url(compose_file, project, env)
        wait_for_observer(observer_base_url, check.timeout_seconds)
        clear_observer(observer_base_url)
        run_process(compose_command(compose_file, project, profile="traffic") + ["run", "--rm", "traffic"], cwd, env, check.timeout_seconds)

        if check.settle_seconds > 0:
            time.sleep(check.settle_seconds)

        passed, evidence = validate_observer_expectations(check.expect.model_dump(exclude_none=True), observer_base_url)
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


def resolve_compose_file(check: RuntimeCheck, service_dir: Path, eval_dir: Path | None = None) -> Path:
    path = Path(check.compose_file)
    resolved = path if path.is_absolute() else ((eval_dir or service_dir) / path).resolve()
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
        completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise RuntimeError(f"command executable not found: {exc.filename}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"command timed out after {exc.timeout}s: {' '.join(command)}") from exc
    if check and completed.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} exited {completed.returncode}: {command_output(completed)}")
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


def discover_observer_base_url(compose_file: Path, project: str, env: dict[str, str]) -> str:
    completed = run_process(
        compose_command(compose_file, project) + ["port", "observer", "3000"],
        compose_file.parent,
        env,
        timeout=30,
    )
    return observer_base_url_from_port_output(completed.stdout)


def observer_base_url_from_port_output(output: str) -> str:
    line = next((item.strip() for item in output.splitlines() if item.strip()), "")
    if not line:
        raise RuntimeError("docker compose port observer 3000 returned no output")
    host, separator, port = line.rpartition(":")
    if not separator or not port:
        raise RuntimeError(f"could not parse observer port output: {line}")
    host = host.strip("[]")
    if host in {"", "0.0.0.0", "::"}:
        host = "127.0.0.1"
    return f"http://{host}:{port}"


def clear_observer(base_url: str) -> None:
    request_text(observer_url(base_url, "/api/data"), method="DELETE", timeout=10, allow_404=True)


def wait_for_observer(base_url: str, timeout: int) -> None:
    url = observer_url(base_url, "/api/health")
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            status, _ = request_text(url, timeout=5, return_status=True)
            if status == 200:
                return
            last_error = f"status {status}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1)
    raise TimeoutError(f"observer did not reach 200: {url}; last error: {last_error}")


def validate_observer_expectations(expect: dict[str, Any], base_url: str) -> tuple[bool, str]:
    if not expect:
        return False, "runtime expect is required"

    evidence = []
    failures = []
    traces = expect.get("traces") or {}
    if traces:
        text = request_json_text(observer_url(base_url, traces.get("path", "/api/query/traces")))
        check_expected_text("traces", text, traces, evidence, failures)
        check_trace_detail_expectations(base_url, text, traces, evidence, failures)

    metrics = expect.get("metrics") or {}
    if metrics:
        text = request_json_text(observer_url(base_url, metrics.get("path", "/api/query/metrics")))
        check_expected_text("metrics", text, metrics, evidence, failures)

    if not traces and not metrics:
        return False, "runtime expect must include traces or metrics expectations"
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


def check_trace_detail_expectations(base_url: str, traces_text: str, expect: dict[str, Any], evidence: list[str], failures: list[str]) -> None:
    values = [str(value) for value in expect.get("trace_detail_contains_all", [])]
    if not values:
        return
    try:
        summaries = json.loads(traces_text)
    except json.JSONDecodeError:
        failures.append("traces detail unavailable: trace summary response was not JSON")
        return
    if not isinstance(summaries, list) or not summaries:
        failures.append("traces detail unavailable: no trace summaries returned")
        return

    detail_texts: list[str] = []
    for summary in summaries[:20]:
        if not isinstance(summary, dict):
            continue
        trace_id = str(summary.get("traceId") or "")
        if not trace_id:
            continue
        detail_texts.append(request_json_text(observer_url(base_url, f"/api/query/traces/{trace_id}")))

    combined = "\n".join(detail_texts)
    missing = [value for value in values if value.lower() not in combined.lower()]
    if missing:
        failures.append(f"traces missing trace_detail_contains_all: {', '.join(missing)}")
    else:
        evidence.append(f"traces matched trace_detail_contains_all: {', '.join(values)}")


def observer_url(base_url: str, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return base_url.rstrip("/") + "/" + path.lstrip("/")


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


def runtime_result(check: RuntimeCheck, passed: bool, evidence: str, skipped: bool = False) -> GradeCheckResult:
    return GradeCheckResult(
        id=check.id,
        description=check.description,
        passed=passed,
        evidence=evidence,
        category="runtime",
        skipped=skipped,
    )


def safe_name(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")[:63] or "codex-eval"
