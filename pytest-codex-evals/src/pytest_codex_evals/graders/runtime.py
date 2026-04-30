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
from pytest_codex_evals.definitions.runtime import EndpointExpectation, RuntimeExpectations
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
        results.append(run_runtime_check(check, service_dir, repo_root, eval_dir))
    return GradeResult(checks=results)


def run_runtime_check(
    check: RuntimeCheck,
    service_dir: Path,
    repo_root: Path | None = None,
    eval_dir: Path | None = None,
) -> GradeCheckResult:
    compose_file: Path | None = None
    project = safe_name(f"codex-eval-{uuid.uuid4().hex[:12]}")
    env = runtime_env(repo_root, service_dir, project)
    expect = check.expect
    try:
        compose_file = resolve_compose_file(check, service_dir, eval_dir)
        cwd = compose_file.parent
        run_process(compose_command(compose_file, project) + ["up", "-d", "--build"], cwd, env, check.timeout_seconds)
        base_url = discover_service_base_url(compose_file, project, env, expect.service_name, expect.service_port)
        wait_for_service(base_url, expect.health_path, check.timeout_seconds)
        if expect.clear_path:
            clear_service(base_url, expect.clear_path, expect.clear_method)
        run_process(compose_command(compose_file, project, profile="traffic") + ["run", "--rm", "traffic"], cwd, env, check.timeout_seconds)

        if check.settle_seconds > 0:
            time.sleep(check.settle_seconds)

        passed, evidence = validate_endpoint_expectations(expect.endpoints, base_url)
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


# ---------------------------------------------------------------------------
# Generic endpoint validation
# ---------------------------------------------------------------------------


def validate_endpoint_expectations(
    endpoints: list[EndpointExpectation],
    base_url: str,
) -> tuple[bool, str]:
    if not endpoints:
        return False, "runtime expect must include at least one endpoint expectation"

    evidence: list[str] = []
    failures: list[str] = []

    for ep in endpoints:
        url = service_url(base_url, ep.url)
        text = request_json_text(url)

        check_text_expectations(ep.id, text, ep.contains_all, ep.contains_any, ep.field_checks, evidence, failures)

        if ep.detail_contains_all:
            check_detail_expectations(
                base_url,
                text,
                ep.id,
                ep.detail_path_template or "",
                ep.detail_id_field or "id",
                ep.detail_contains_all,
                evidence,
                failures,
            )

    if failures:
        return False, "; ".join(failures)
    return True, "; ".join(evidence) if evidence else "Endpoint expectations passed"


def check_text_expectations(
    scope: str,
    text: str,
    contains_all: list[str],
    contains_any: list[str],
    field_checks: dict[str, list[str]],
    evidence: list[str],
    failures: list[str],
) -> None:
    if contains_all:
        missing = [v for v in contains_all if v.lower() not in text.lower()]
        if missing:
            failures.append(f"{scope} missing contains_all: {', '.join(missing)}")
        else:
            evidence.append(f"{scope} matched contains_all: {', '.join(contains_all)}")

    if contains_any:
        if not any(v.lower() in text.lower() for v in contains_any):
            failures.append(f"{scope} missing any contains_any: {', '.join(contains_any)}")
        else:
            evidence.append(f"{scope} matched one of contains_any: {', '.join(contains_any)}")

    for key, values in field_checks.items():
        missing = [v for v in values if v.lower() not in text.lower()]
        if missing:
            failures.append(f"{scope} missing {key}: {', '.join(missing)}")
        elif values:
            evidence.append(f"{scope} matched {key}: {', '.join(values)}")


def check_detail_expectations(
    base_url: str,
    list_text: str,
    scope: str,
    detail_path_template: str,
    detail_id_field: str,
    detail_contains_all: list[str],
    evidence: list[str],
    failures: list[str],
) -> None:
    if not detail_contains_all or not detail_path_template:
        return
    try:
        summaries = json.loads(list_text)
    except json.JSONDecodeError:
        failures.append(f"{scope} detail unavailable: list response was not JSON")
        return
    if not isinstance(summaries, list) or not summaries:
        failures.append(f"{scope} detail unavailable: no summaries returned")
        return

    detail_texts: list[str] = []
    for summary in summaries[:20]:
        if not isinstance(summary, dict):
            continue
        item_id = str(summary.get(detail_id_field) or "")
        if not item_id:
            continue
        detail_url = detail_path_template.replace("{id}", item_id)
        detail_texts.append(request_json_text(service_url(base_url, detail_url)))

    combined = "\n".join(detail_texts)
    missing = [v for v in detail_contains_all if v.lower() not in combined.lower()]
    if missing:
        failures.append(f"{scope} missing detail_contains_all: {', '.join(missing)}")
    else:
        evidence.append(f"{scope} matched detail_contains_all: {', '.join(detail_contains_all)}")


# ---------------------------------------------------------------------------
# Compose / service discovery helpers
# ---------------------------------------------------------------------------


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


def discover_service_base_url(
    compose_file: Path,
    project: str,
    env: dict[str, str],
    service_name: str = "observer",
    service_port: int = 3000,
) -> str:
    completed = run_process(
        compose_command(compose_file, project) + ["port", service_name, str(service_port)],
        compose_file.parent,
        env,
        timeout=30,
    )
    return base_url_from_port_output(completed.stdout, service_name)


def base_url_from_port_output(output: str, service_name: str = "observer") -> str:
    line = next((item.strip() for item in output.splitlines() if item.strip()), "")
    if not line:
        raise RuntimeError(f"docker compose port {service_name} returned no output")
    host, separator, port = line.rpartition(":")
    if not separator or not port:
        raise RuntimeError(f"could not parse port output for {service_name}: {line}")
    host = host.strip("[]")
    if host in {"", "0.0.0.0", "::"}:
        host = "127.0.0.1"
    return f"http://{host}:{port}"


def clear_service(base_url: str, path: str, method: str = "DELETE") -> None:
    request_text(service_url(base_url, path), method=method, timeout=10, allow_404=True)


def wait_for_service(base_url: str, health_path: str, timeout: int) -> None:
    url = service_url(base_url, health_path)
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
    raise TimeoutError(f"service did not reach 200: {url}; last error: {last_error}")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def service_url(base_url: str, path: str) -> str:
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
