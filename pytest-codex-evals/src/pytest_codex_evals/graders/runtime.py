from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from pytest_codex_evals.definitions import GradeCheckResult, GradeResult, RuntimeCheck, RuntimeEvalCase
from pytest_codex_evals.definitions.runtime import (
    EndpointExpectation,
    JSONRecordExpectation,
    RuntimeExpectations,
    ServiceLogExpectation,
)
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
    env = runtime_env(repo_root, service_dir, project, check.environment)
    expect = check.expect
    try:
        compose_file = resolve_compose_file(check, service_dir, eval_dir)
        cwd = compose_file.parent
        run_process(
            compose_command(compose_file, project) + ["up", "-d", "--build"],
            cwd,
            env,
            check.timeout_seconds,
        )
        base_url = discover_service_base_url(
            compose_file, project, env, expect.service_name, expect.service_port
        )
        wait_for_service(base_url, expect.health_path, check.timeout_seconds)
        if expect.clear_path:
            clear_service(base_url, expect.clear_path, expect.clear_method)
        run_process(
            compose_command(compose_file, project, profile="traffic")
            + ["run", "--rm", "traffic"],
            cwd,
            env,
            check.timeout_seconds,
        )
        if check.stop_services_before_validation:
            stop_compose_services(
                compose_file,
                project,
                env,
                check.stop_services_before_validation,
                check.timeout_seconds,
            )

        if check.settle_seconds > 0:
            time.sleep(check.settle_seconds)

        if expect.endpoints:
            endpoint_passed, endpoint_evidence = validate_endpoint_expectations(
                expect.endpoints, base_url
            )
        else:
            endpoint_passed, endpoint_evidence = True, ""
        service_logs_passed, service_logs_evidence = validate_service_log_expectations(
            expect.service_logs,
            compose_file,
            project,
            env,
        )
        passed = endpoint_passed and service_logs_passed
        evidence = "; ".join(
            item for item in (endpoint_evidence, service_logs_evidence) if item
        )
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

        check_text_expectations(
            ep.id,
            text,
            ep.contains_all,
            ep.contains_any,
            ep.field_checks,
            evidence,
            failures,
        )

        if ep.record_checks:
            check_json_record_expectations(
                ep.id,
                text,
                ep.record_checks,
                evidence,
                failures,
                base_url=base_url,
            )

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


def check_json_record_expectations(
    scope: str,
    text: str,
    record_checks: list[JSONRecordExpectation],
    evidence: list[str],
    failures: list[str],
    *,
    base_url: str | None = None,
) -> None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        failures.append(f"{scope} record checks unavailable: response was not JSON")
        return
    if not isinstance(payload, list):
        failures.append(f"{scope} record checks require a JSON array response")
        return

    records = [record for record in payload if isinstance(record, dict)]
    trace_details: dict[str, tuple[dict[str, Any] | None, str | None]] = {}
    for expectation in record_checks:
        matched = [record for record in records if record_matches(record, expectation)]
        expected_count = expectation.exact_count
        if expected_count is not None and len(matched) != expected_count:
            failures.append(
                f"{scope}/{expectation.id} expected {expected_count} matching records, "
                f"got {len(matched)}"
            )
            continue
        if expected_count is None and not matched:
            failures.append(f"{scope}/{expectation.id} found no matching records")
            continue

        check_record_fields(
            scope,
            expectation,
            matched,
            evidence,
            failures,
            base_url=base_url,
            trace_details=trace_details,
        )


def record_matches(record: dict[str, Any], expectation: JSONRecordExpectation) -> bool:
    for path, expected in expectation.match.items():
        if json_path(record, path) != expected:
            return False
    for path, expected in expectation.match_contains.items():
        actual = json_path(record, path)
        if actual is _MISSING or expected.lower() not in str(actual).lower():
            return False
    return True


def check_record_fields(
    scope: str,
    expectation: JSONRecordExpectation,
    records: list[dict[str, Any]],
    evidence: list[str],
    failures: list[str],
    *,
    base_url: str | None = None,
    trace_details: dict[str, tuple[dict[str, Any] | None, str | None]] | None = None,
) -> None:
    prefix = f"{scope}/{expectation.id}"
    for index, record in enumerate(records):
        for path, expected in expectation.field_equals.items():
            actual = json_path(record, path)
            if actual != expected:
                failures.append(
                    f"{prefix} record {index} expected {path}={expected!r}, "
                    f"got {display_value(actual)}"
                )
        for path, expected in expectation.field_contains.items():
            actual = json_path(record, path)
            if actual is _MISSING or expected.lower() not in str(actual).lower():
                failures.append(
                    f"{prefix} record {index} expected {path} to contain {expected!r}, "
                    f"got {display_value(actual)}"
                )
        for path in expectation.non_empty:
            actual = json_path(record, path)
            if not value_is_non_empty(actual):
                failures.append(f"{prefix} record {index} expected non-empty {path}")
        if expectation.correlates_with_trace:
            check_otel_trace_correlation(
                prefix,
                index,
                record,
                base_url,
                trace_details if trace_details is not None else {},
                failures,
            )

    if expectation.unique_by and records:
        keys: list[str] = []
        for index, record in enumerate(records):
            values = [json_path(record, path) for path in expectation.unique_by]
            if any(value is _MISSING for value in values):
                failures.append(
                    f"{prefix} record {index} missing uniqueness field(s): "
                    f"{', '.join(expectation.unique_by)}"
                )
                continue
            keys.append(json.dumps(values, sort_keys=True, default=str))
        if len(keys) != len(set(keys)):
            failures.append(
                f"{prefix} expected unique records by {', '.join(expectation.unique_by)}"
            )

    if not any(failure.startswith(prefix) for failure in failures):
        evidence.append(f"{prefix} matched {len(records)} structured record(s)")


_TRACE_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")
_SPAN_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{16}$")


def check_otel_trace_correlation(
    prefix: str,
    index: int,
    record: dict[str, Any],
    base_url: str | None,
    trace_details: dict[str, tuple[dict[str, Any] | None, str | None]],
    failures: list[str],
) -> None:
    trace_id = record.get("traceId")
    span_id = record.get("spanId")
    if not valid_otel_id(trace_id, _TRACE_ID_PATTERN):
        failures.append(
            f"{prefix} record {index} expected traceId to be a nonzero 32-hex OTel ID"
        )
        return
    if not valid_otel_id(span_id, _SPAN_ID_PATTERN):
        failures.append(
            f"{prefix} record {index} expected spanId to be a nonzero 16-hex OTel ID"
        )
        return
    if base_url is None:
        failures.append(f"{prefix} record {index} cannot correlate without a service base URL")
        return

    if trace_id not in trace_details:
        trace_details[trace_id] = load_trace_detail(base_url, trace_id)
    detail, error = trace_details[trace_id]
    if error:
        failures.append(f"{prefix} record {index} could not load trace detail: {error}")
        return
    spans = detail.get("spans") if detail else None
    if not isinstance(spans, list) or not any(
        isinstance(span, dict)
        and span.get("traceId") == trace_id
        and span.get("spanId") == span_id
        for span in spans
    ):
        failures.append(
            f"{prefix} record {index} trace detail did not contain correlated span {span_id}"
        )


def valid_otel_id(value: Any, pattern: re.Pattern[str]) -> bool:
    return (
        isinstance(value, str)
        and pattern.fullmatch(value) is not None
        and any(character != "0" for character in value)
    )


def load_trace_detail(
    base_url: str,
    trace_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    url = service_url(
        base_url,
        f"/api/query/traces/{urllib.parse.quote(trace_id, safe='')}",
    )
    status, text = request_text(url, timeout=15, return_status=True)
    if status != 200:
        return None, f"{url} returned HTTP {status}"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None, f"{url} did not return JSON"
    if not isinstance(payload, dict):
        return None, f"{url} did not return a JSON object"
    if payload.get("traceId") != trace_id:
        return None, f"{url} returned a different traceId"
    return payload, None


_MISSING = object()


def json_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return _MISSING
    return current


def value_is_non_empty(value: Any) -> bool:
    if value is _MISSING or value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def display_value(value: Any) -> str:
    return "<missing>" if value is _MISSING else repr(value)


def validate_service_log_expectations(
    expectations: list[ServiceLogExpectation],
    compose_file: Path,
    project: str,
    env: dict[str, str],
) -> tuple[bool, str]:
    if not expectations:
        return True, ""

    evidence: list[str] = []
    failures: list[str] = []
    logs_by_service: dict[str, str] = {}
    log_errors_by_service: dict[str, str] = {}
    for expectation in expectations:
        service_name = expectation.service_name
        if service_name not in logs_by_service and service_name not in log_errors_by_service:
            try:
                logs_by_service[service_name] = compose_service_logs(
                    compose_file, project, env, service_name
                )
            except Exception as exc:
                log_errors_by_service[service_name] = str(exc)
        if service_name in log_errors_by_service:
            failures.append(
                f"{expectation.id} service logs unavailable for {service_name}: "
                f"{log_errors_by_service[service_name]}"
            )
            continue
        text = logs_by_service[service_name]
        missing = [value for value in expectation.contains_all if value not in text]
        if missing:
            failures.append(
                f"{expectation.id} service logs missing: {', '.join(missing)}"
            )
        for value, expected_count in expectation.occurrences.items():
            actual_count = text.count(value)
            if actual_count != expected_count:
                failures.append(
                    f"{expectation.id} expected {expected_count} occurrences of {value!r} "
                    f"in {expectation.service_name} logs, got {actual_count}"
                )
        if not any(failure.startswith(expectation.id) for failure in failures):
            evidence.append(f"{expectation.id} preserved service log output")

    if failures:
        return False, "; ".join(failures)
    return True, "; ".join(evidence)


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


def runtime_env(
    repo_root: Path | None,
    service_dir: Path,
    project: str,
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    if overrides:
        env.update(overrides)
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


def stop_compose_services(
    compose_file: Path,
    project: str,
    env: dict[str, str],
    service_names: list[str],
    timeout: int,
) -> None:
    run_process(
        compose_command(compose_file, project)
        + ["stop", "--timeout", "30", *service_names],
        compose_file.parent,
        env,
        timeout,
    )
    completed = run_process(
        compose_command(compose_file, project)
        + ["ps", "--all", "--format", "json", *service_names],
        compose_file.parent,
        env,
        timeout,
    )
    records = compose_ps_records(completed.stdout)
    for service_name in service_names:
        record = next(
            (item for item in records if item.get("Service") == service_name),
            None,
        )
        if record is None:
            raise RuntimeError(
                f"docker compose ps did not return stopped service {service_name}"
            )
        state = str(record.get("State", "")).lower()
        try:
            exit_code = int(record.get("ExitCode"))
        except (TypeError, ValueError):
            raise RuntimeError(
                f"docker compose ps returned no exit code for {service_name}"
            ) from None
        if state != "exited" or exit_code != 0:
            raise RuntimeError(
                f"{service_name} did not stop gracefully: state={state or 'unknown'}, "
                f"exit_code={exit_code}"
            )


def compose_ps_records(text: str) -> list[dict[str, Any]]:
    """Parse both array and newline-delimited Docker Compose JSON output."""

    stripped = text.strip()
    if not stripped:
        return []
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        records: list[dict[str, Any]] = []
        for line in stripped.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError("docker compose ps returned invalid JSON") from exc
            if isinstance(item, dict):
                records.append(item)
        return records
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    raise RuntimeError("docker compose ps returned an unexpected JSON value")


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


def compose_service_logs(
    compose_file: Path,
    project: str,
    env: dict[str, str],
    service_name: str,
) -> str:
    completed = run_process(
        compose_command(compose_file, project)
        + ["logs", "--no-color", service_name],
        compose_file.parent,
        env,
        timeout=30,
    )
    return "\n".join(part for part in (completed.stdout, completed.stderr) if part)


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
    status, text = request_text(url, timeout=15, return_status=True)
    if status < 200 or status >= 300:
        raise RuntimeError(f"{url} returned HTTP {status}")
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
