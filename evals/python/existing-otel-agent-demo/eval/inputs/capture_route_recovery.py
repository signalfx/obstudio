"""Record real resource HTTP and native OTLP from separate app startup processes."""

import argparse
import datetime
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVICE))

from app import AgentDemo
from probe import Receiver
from resource_recovery_fixture import RecoveryServer


def clean_environment():
    return {key: value for key, value in os.environ.items()
            if not key.startswith(("OTEL_", "SPLUNK_", "GALILEO_"))
            and key.casefold() not in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}}


def resolve_resources(resolver, origin, project_name, stream_name, calls):
    command = [sys.executable, str(resolver), "--studio-api-origin", origin,
               "--project-name", project_name, "--agent-stream-name", stream_name]
    result = subprocess.run(command, env=clean_environment(), capture_output=True,
                            text=True, timeout=15)
    payload = json.loads(result.stdout)
    calls.append({"command": command, "returncode": result.returncode,
                  "result": payload, "stderr": result.stderr})
    if result.returncode:
        raise RuntimeError("resource_resolution_failed")
    return payload


def worker(args):
    spec = importlib.util.spec_from_file_location("route_adapter", args.adapter)
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    calls = []
    app = AgentDemo("generic", args.endpoint)
    originals = {key: value for key, value in app.owned_objects().items() if value is not None}
    before = json.loads(args.profile.read_text())
    error_type = None
    try:
        adapter.configure_route(args.profile, app.trace_session, lambda project, stream:
            resolve_resources(args.resolver, args.origin, project, stream, calls))
    except Exception as error:
        error_type = type(error).__name__
    preserved = all(app.owned_objects().get(key) is value for key, value in originals.items())
    headers = dict(app.trace_session.headers)
    app.start()
    try:
        result = app.run_agent()
    finally:
        app.shutdown()
    args.output.write_text(json.dumps({
        "process_id": os.getpid(), "configure_error": error_type,
        "owners_preserved": preserved, "endpoint": app.endpoint,
        "trace_headers": headers, "profile_before": before,
        "profile_after": json.loads(args.profile.read_text()),
        "business_result": result, "helper_calls": calls,
    }, indent=2) + "\n")


def capture(resolver, adapter):
    with tempfile.TemporaryDirectory(prefix="route-recovery-profile-") as temporary:
        directory = Path(temporary)
        profile = directory / "runtime-profile.json"
        with RecoveryServer("missing") as resources, Receiver() as receiver:
            thread = threading.Thread(target=resources.serve_forever, daemon=True)
            thread.start()
            try:
                profile.write_text(json.dumps({
                    "project_name": "fixture-project", "agent_stream_name": "fixture-agent",
                    "native_endpoint": receiver.endpoint, "keep_setting": "operator-owned",
                }))

                def startup(stage):
                    first_request, first_resource = len(receiver.requests), len(resources.journal)
                    output = directory / (stage + ".json")
                    command = [sys.executable, str(Path(__file__).resolve()), "worker",
                               "--resolver", str(resolver), "--adapter", str(adapter),
                               "--profile", str(profile), "--origin", resources.origin,
                               "--endpoint", receiver.endpoint, "--output", str(output)]
                    completed = subprocess.run(command, env=clean_environment(),
                                               capture_output=True, text=True, timeout=30)
                    result = json.loads(output.read_text()) if output.exists() else {}
                    return {**result, "stage": stage, "worker_command": command,
                            "worker_returncode": completed.returncode,
                            "stdout": completed.stdout, "stderr": completed.stderr,
                            "resource_requests": resources.journal[first_resource:],
                            "native_requests": receiver.requests[first_request:]}

                stages = [startup("initial_201_create")]
                resources.rotate_identities()
                stages.append(startup("clean_restart_after_external_identity_change"))
                stages.append(startup("repeated_restart"))
                calls = []
                contrast_start = len(resources.journal)
                contrast = resolve_resources(resolver, resources.origin,
                                             "fixture-project", "fixture-agent", calls)
                contrast_requests = resources.journal[contrast_start:]
                resources.scenario = "auth"
                stages.append(startup("clean_restart_with_permission_failure"))
                auth_start = len(resources.journal)
                try:
                    resolve_resources(resolver, resources.origin,
                                      "fixture-project", "fixture-agent", calls)
                except RuntimeError:
                    pass
                return {
                    "kind": "captured-local-existing-otel-route-startups",
                    "captured_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "proof_scope": "Separate real app startup processes, local mock resource HTTP and native OTLP; no Studio/cloud forwarding or model API.",
                    "adapter_path": str(adapter),
                    "adapter_sha256": hashlib.sha256(adapter.read_bytes()).hexdigest(),
                    "resolver_path": str(resolver),
                    "resolver_sha256": hashlib.sha256(resolver.read_bytes()).hexdigest(),
                    "fixture_source_sha256": {
                        str(path.relative_to(SERVICE)): hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in (SERVICE / "app.py", SERVICE / "probe.py", Path(__file__),
                                     Path(__file__).with_name("studio_resources.py"),
                                     Path(__file__).with_name("resource_recovery_fixture.py"))
                    },
                    "installed_versions": {name: importlib.metadata.version(name)
                        for name in ("opentelemetry-sdk", "opentelemetry-exporter-otlp-proto-http")},
                    "stages": stages,
                    "independent_helper_after_rotation": {
                        "result": contrast, "resource_requests": contrast_requests,
                        "proof_scope": "Independent helper result, not adapter repair or app-route closure.",
                    },
                    "independent_helper_permission_failure": {
                        "call": calls[-1], "resource_requests": resources.journal[auth_start:],
                        "proof_scope": "Independent helper failure, not evidence the cached adapter performed lookup.",
                    },
                }
            finally:
                resources.shutdown()
                thread.join()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", choices=("capture", "worker"), default="capture")
    parser.add_argument("--resolver", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, default=Path(__file__).with_name("route_recovery_source.py"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--origin")
    parser.add_argument("--endpoint")
    args = parser.parse_args()
    args.resolver, args.adapter = args.resolver.resolve(), args.adapter.resolve()
    if args.mode == "worker":
        worker(args)
    else:
        result = capture(args.resolver, args.adapter)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({"stages": len(result["stages"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
