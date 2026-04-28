from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .models import DeterministicCheck, GradeCheckResult


def run_observer_docker_runtime(check: DeterministicCheck, service_dir: Path, repo_root: Path | None = None) -> GradeCheckResult:
    try:
        import docker
    except ImportError as exc:
        return runtime_result(check, False, f"Docker SDK is not installed: {exc}")

    config = check.runtime
    if not config:
        return runtime_result(check, False, "Runtime check requires a runtime object")

    containers = []
    network = None
    client = None
    prepared_sources: list[Path] = []
    try:
        prepared_sources = prepare_runtime_sources(config, service_dir, repo_root)
        run_prebuild_commands(config, service_dir, check.timeout_seconds)
        client = docker.from_env()
        client.ping()
        network_name = safe_name(f"codex-eval-{check.id}-{int(time.time() * 1000)}")
        network = client.networks.create(network_name, driver="bridge")

        if not observer_config(config).get("managed"):
            clear_observer(config)
        containers = start_containers(client, network.name, config, service_dir, check.timeout_seconds)
        wait_for_observer(config, check.timeout_seconds)
        if observer_config(config).get("managed"):
            clear_observer(config)
        wait_for_health(config, check.timeout_seconds)
        run_traffic(config, check.timeout_seconds)
        settle_seconds = float(config.get("settle_seconds", 2))
        if settle_seconds > 0:
            time.sleep(settle_seconds)

        passed, evidence = validate_observer_expectations(config)
        if not passed and containers:
            evidence = evidence + "; " + container_log_evidence(containers)
        return runtime_result(check, passed, evidence)
    except Exception as exc:
        evidence = f"Runtime check failed: {exc}"
        if containers:
            evidence = evidence + "; " + container_log_evidence(containers)
        return runtime_result(check, False, evidence)
    finally:
        for container in reversed(containers):
            remove_container(container)
        if network is not None:
            try:
                network.remove()
            except Exception:
                pass
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        cleanup_runtime_sources(prepared_sources)


def start_containers(client: Any, network_name: str, config: dict[str, Any], service_dir: Path, timeout: int) -> list[Any]:
    specs = container_specs(config, service_dir)
    containers = []
    for spec in specs:
        image = resolve_image(client, spec, service_dir)
        container = client.containers.run(
            image,
            command=spec.get("command"),
            detach=True,
            entrypoint=spec.get("entrypoint"),
            environment=environment(spec.get("environment")),
            name=safe_name(f"codex-eval-{spec.get('name', 'service')}-{int(time.time() * 1000)}"),
            network=network_name,
            ports=ports(spec.get("ports")),
            volumes=volumes(spec.get("volumes"), service_dir),
            working_dir=spec.get("working_dir") or spec.get("workdir"),
        )
        containers.append(container)
    if containers:
        time.sleep(min(max(timeout, 1), 5))
    return containers


def prepare_runtime_sources(config: dict[str, Any], service_dir: Path, repo_root: Path | None) -> list[Path]:
    copies = config.get("source_copies") or []
    if not isinstance(copies, list):
        raise ValueError("runtime.source_copies must be a list")
    if copies and repo_root is None:
        raise ValueError("runtime.source_copies requires repo root context")

    prepared = []
    for item in copies:
        if not isinstance(item, dict):
            raise ValueError("runtime.source_copies entries must be objects")
        source_value = item.get("from")
        target_value = item.get("to")
        if not source_value or not target_value:
            raise ValueError("runtime.source_copies entries require from and to")
        source = Path(str(source_value))
        if not source.is_absolute():
            source = (repo_root / source).resolve()  # type: ignore[operator]
        target = service_dir / str(target_value)
        if not is_relative_to(target.resolve(), service_dir.resolve()):
            raise ValueError(f"runtime source copy target must stay under service dir: {target_value}")
        if not source.exists():
            raise ValueError(f"runtime source copy source not found: {source}")
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, ignore=runtime_copy_ignore)
        else:
            shutil.copy2(source, target)
        prepared.append(target)
    return prepared


def runtime_copy_ignore(directory: str, names: list[str]) -> set[str]:
    ignored = {
        ".git",
        ".venv",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
    return {name for name in names if name in ignored or name.endswith(".pyc")}


def cleanup_runtime_sources(paths: list[Path]) -> None:
    for path in reversed(paths):
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        except Exception:
            pass


def run_prebuild_commands(config: dict[str, Any], service_dir: Path, default_timeout: int) -> None:
    commands = config.get("prebuild") or []
    if not isinstance(commands, list):
        raise ValueError("runtime.prebuild must be a list")

    for item in commands:
        if isinstance(item, list):
            command = [str(part) for part in item]
            cwd = service_dir
            env = None
            timeout = default_timeout
        elif isinstance(item, dict):
            command_value = item.get("command")
            if not isinstance(command_value, list) or not command_value:
                raise ValueError("runtime.prebuild command entries require a non-empty command list")
            command = [str(part) for part in command_value]
            cwd = service_dir / str(item.get("cwd", "."))
            if not is_relative_to(cwd.resolve(), service_dir.resolve()):
                raise ValueError(f"runtime.prebuild cwd must stay under service dir: {item.get('cwd')}")
            env = {**os.environ, **{str(key): str(value) for key, value in dict(item.get("env") or {}).items()}}
            timeout = int(item.get("timeout_seconds", default_timeout))
        else:
            raise ValueError("runtime.prebuild entries must be command lists or objects")

        if not cwd.exists():
            raise ValueError(f"runtime.prebuild cwd missing: {cwd}")

        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if completed.returncode != 0:
            output = " ".join((completed.stdout + "\n" + completed.stderr).split())[:1000]
            raise RuntimeError(f"prebuild command failed: {' '.join(command)} exited {completed.returncode}: {output}")


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def container_specs(config: dict[str, Any], service_dir: Path) -> list[dict[str, Any]]:
    if config.get("compose_file"):
        return compose_specs(service_dir / str(config["compose_file"]), config)
    specs = config.get("containers", [])
    if not isinstance(specs, list):
        raise ValueError("runtime.containers must be a list")
    return [dict(spec) for spec in specs]


def compose_specs(path: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        import yaml
    except ImportError as exc:
        raise ValueError(f"PyYAML is required for compose_file runtime checks: {exc}") from exc

    if not path.is_file():
        raise ValueError(f"compose_file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    services = data.get("services")
    if not isinstance(services, dict):
        raise ValueError(f"compose_file has no services table: {path}")

    selected = config.get("services") or list(services)
    specs = []
    for name in selected:
        service = services.get(name)
        if not isinstance(service, dict):
            raise ValueError(f"compose service not found: {name}")
        spec = dict(service)
        spec["name"] = name
        spec["_compose_dir"] = str(path.parent)
        spec["environment"] = merge_environment(config.get("environment"), spec.get("environment"))
        specs.append(spec)
    return specs


def resolve_image(client: Any, spec: dict[str, Any], service_dir: Path) -> str:
    if spec.get("build"):
        build = spec["build"]
        if isinstance(build, str):
            context = compose_relative_path(spec, build, service_dir)
            dockerfile = None
        elif isinstance(build, dict):
            context = compose_relative_path(spec, build.get("context", "."), service_dir)
            dockerfile = build.get("dockerfile")
        else:
            raise ValueError("build must be a string or object")
        tag = safe_name(f"codex-eval-{spec.get('name', 'service')}:latest")
        client.images.build(path=str(context), dockerfile=dockerfile, tag=tag, rm=True)
        return tag

    image = spec.get("image")
    if not image:
        raise ValueError(f"container {spec.get('name', 'service')} needs image or build")
    try:
        client.images.get(image)
    except Exception:
        client.images.pull(image)
    return str(image)


def compose_relative_path(spec: dict[str, Any], value: str, service_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    base = Path(spec.get("_compose_dir") or service_dir)
    return (base / path).resolve()


def environment(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}
    if isinstance(value, list):
        parsed = {}
        for item in value:
            key, _, val = str(item).partition("=")
            parsed[key] = val
        return parsed
    raise ValueError("environment must be an object or list")


def merge_environment(base: Any, override: Any) -> dict[str, str] | None:
    merged = environment(base) or {}
    merged.update(environment(override) or {})
    return merged or None


def ports(value: Any) -> dict[str, Any] | None:
    if not value:
        return None
    if isinstance(value, dict):
        return {normalize_container_port(key): val for key, val in value.items()}
    if not isinstance(value, list):
        raise ValueError("ports must be a list or object")

    parsed: dict[str, Any] = {}
    for item in value:
        if isinstance(item, dict):
            target = item.get("target")
            published = item.get("published")
            host_ip = item.get("host_ip")
            if target is None:
                continue
            parsed[normalize_container_port(target)] = (host_ip, int(published)) if host_ip and published else int(published) if published else None
            continue

        parts = str(item).split(":")
        if len(parts) == 1:
            parsed[normalize_container_port(parts[0])] = None
        elif len(parts) == 2:
            parsed[normalize_container_port(parts[1])] = int(parts[0])
        elif len(parts) == 3:
            parsed[normalize_container_port(parts[2])] = (parts[0], int(parts[1]))
        else:
            raise ValueError(f"unsupported port mapping: {item}")
    return parsed or None


def normalize_container_port(value: Any) -> str:
    text = str(value)
    return text if "/" in text else f"{text}/tcp"


def volumes(value: Any, service_dir: Path) -> dict[str, dict[str, str]] | None:
    if not value:
        return None
    parsed: dict[str, dict[str, str]] = {}
    if isinstance(value, dict):
        for source, target in value.items():
            parsed[str(host_path(source, service_dir))] = {"bind": str(target), "mode": "rw"}
        return parsed
    if not isinstance(value, list):
        raise ValueError("volumes must be a list or object")
    for item in value:
        if isinstance(item, dict):
            source = item.get("source")
            target = item.get("target")
            if not source or not target:
                continue
            mode = "ro" if bool(item.get("read_only")) else str(item.get("mode") or "rw")
            parsed[str(host_path(source, service_dir))] = {"bind": str(target), "mode": mode}
            continue
        parts = str(item).split(":")
        if len(parts) < 2:
            continue
        mode = parts[2] if len(parts) > 2 else "rw"
        parsed[str(host_path(parts[0], service_dir))] = {"bind": parts[1], "mode": mode}
    return parsed or None


def host_path(value: Any, service_dir: Path) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    return (service_dir / path).resolve()


def clear_observer(config: dict[str, Any]) -> None:
    observer = observer_config(config)
    if observer.get("clear", True) is False:
        return
    request_text(observer_url(config, observer.get("clear_path", "/api/data")), method="DELETE", timeout=10, allow_404=True)


def wait_for_health(config: dict[str, Any], timeout: int) -> None:
    health = config.get("health")
    if not health:
        return
    if isinstance(health, str):
        health = {"url": health}
    url = str(health["url"])
    expect_status = int(health.get("expect_status", 200))
    deadline = time.monotonic() + int(health.get("timeout_seconds", timeout))
    last_error = ""
    while time.monotonic() < deadline:
        try:
            status, _ = request_text(url, method=str(health.get("method", "GET")), timeout=5, return_status=True)
            if status == expect_status:
                return
            last_error = f"status {status}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1)
    raise TimeoutError(f"health check did not reach {expect_status}: {url}; last error: {last_error}")


def wait_for_observer(config: dict[str, Any], timeout: int) -> None:
    observer = observer_config(config)
    if not observer.get("managed") and not observer.get("health_path"):
        return
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


def run_traffic(config: dict[str, Any], timeout: int) -> None:
    traffic = config.get("traffic") or []
    if not isinstance(traffic, list):
        raise ValueError("runtime.traffic must be a list")
    for item in traffic:
        if isinstance(item, str):
            item = {"url": item}
        method = str(item.get("method", "GET"))
        body = item.get("body")
        headers = {str(key): str(val) for key, val in dict(item.get("headers") or {}).items()}
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        else:
            data = None if body is None else str(body).encode("utf-8")
        status, _ = request_text(
            str(item["url"]),
            method=method,
            headers=headers,
            data=data,
            timeout=int(item.get("timeout_seconds", timeout)),
            return_status=True,
        )
        expected = item.get("expect_status")
        if expected is not None and status != int(expected):
            raise ValueError(f"traffic request {method} {item['url']} returned {status}, expected {expected}")
        if expected is None and not (200 <= status < 500):
            raise ValueError(f"traffic request {method} {item['url']} returned {status}")


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


def container_log_evidence(containers: list[Any]) -> str:
    snippets = []
    for container in containers[:3]:
        try:
            logs = container.logs(tail=20).decode("utf-8", errors="replace")
        except Exception:
            logs = ""
        if logs:
            snippets.append(f"{container.name} logs: {' '.join(logs.split())[:300]}")
    return "; ".join(snippets)


def remove_container(container: Any) -> None:
    try:
        container.remove(force=True)
    except Exception:
        pass


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
