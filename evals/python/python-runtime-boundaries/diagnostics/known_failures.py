from __future__ import annotations

import json
import os

from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import telemetry
from cli import run_batch


def prove_click_trace_collapse() -> None:
    exporter = InMemorySpanExporter()
    telemetry.TRACER_PROVIDER.add_span_processor(SimpleSpanProcessor(exporter))
    run_batch(["import", "reconcile", "publish"])
    task_spans = [
        span for span in exporter.get_finished_spans() if span.name == "task process"
    ]
    trace_ids = {span.context.trace_id for span in task_spans}
    assert len(task_spans) == 3
    assert len(trace_ids) == 1
    print("PASS Click reproduction: 3 independent tasks share 1 trace ID")


def prove_pre_fork_provider_inheritance() -> None:
    if not hasattr(os, "fork"):
        print("SKIP pre-fork reproduction: os.fork is unavailable")
        return

    read_fd, write_fd = os.pipe()
    child_pid = os.fork()
    if child_pid == 0:
        os.close(read_fd)
        payload = json.dumps(
            {"worker_pid": os.getpid(), "provider_pid": telemetry.PROVIDER_PID}
        )
        os.write(write_fd, payload.encode())
        os.close(write_fd)
        os._exit(0)

    os.close(write_fd)
    payload = os.read(read_fd, 4096).decode()
    os.close(read_fd)
    os.waitpid(child_pid, 0)
    ownership = json.loads(payload)
    assert ownership["provider_pid"] != ownership["worker_pid"]
    print("PASS pre-fork reproduction: worker inherited the master provider owner")


if __name__ == "__main__":
    prove_click_trace_collapse()
    prove_pre_fork_provider_inheritance()
