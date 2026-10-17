"""Run outside the audited source: observe actual SDK records, not report flags."""

import asyncio
import importlib.util
import json
import os
import pathlib
import sys

from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode


def verify(case, source, destination):
    os.environ["OTEL_SERVICE_NAME"] = "independent-audit-truth"
    os.environ["OTEL_RESOURCE_ATTRIBUTES"] = "service.version=truth-1"
    spec = importlib.util.spec_from_file_location("audited_app", source / "app.py")
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    sink = InMemorySpanExporter()
    reader = InMemoryMetricReader()
    telemetry = app.Telemetry(exporter=sink, reader=reader)
    try:
        if case == "dispatch-worker":
            assert app.dispatch(telemetry, job_id="job-A", failed=True) is False
            assert app.dispatch(telemetry, job_id="job-B", failed=False) is True
        elif case == "catalog-handler":
            app.read_item(telemetry, item_id="sku-A", customer_email="raw@example.test", failed=True)
            app.read_item(telemetry, item_id="sku-B", customer_email="raw@example.test", failed=False)
        elif case == "billing-worker":
            assert asyncio.run(app.invoice(telemetry, failed=True)) is False
            assert asyncio.run(app.invoice(telemetry, failed=False)) is True
        else:
            raise ValueError(case)
        spans = sink.get_finished_spans()
        assert all(s.resource.attributes["service.name"] == "independent-audit-truth" for s in spans)
        assert all(s.resource.attributes["service.version"] == "truth-1" for s in spans)
        metrics = reader.get_metrics_data()
        points = [p for r in metrics.resource_metrics for s in r.scope_metrics for m in s.metrics for p in m.data.data_points]
        if case == "dispatch-worker":
            roots = [s for s in spans if s.name == "dispatch"]
            children = [s for s in spans if s.name == "deliver"]
            assert len(roots) == len(children) == 2
            assert all(s.parent is None for s in children)
            assert not ({s.context.trace_id for s in roots} & {s.context.trace_id for s in children})
            assert all(s.status.status_code == StatusCode.UNSET and not s.events for s in children)
            assert {p.attributes["job.id"] for p in points} == {"job-A", "job-B"}
        elif case == "catalog-handler":
            assert {s.name for s in spans} == {"GET /items/sku-A", "GET /items/sku-B"}
            assert all(s.attributes["customer.email"] == "raw@example.test" for s in spans)
            assert spans[0].status.status_code == StatusCode.ERROR
            assert any(e.name == "exception" for e in spans[0].events)
            assert {tuple(p.attributes) for p in points} == {("outcome",)}
        else:
            roots = [s for s in spans if s.name == "invoice"]
            children = [s for s in spans if s.name == "charge"]
            assert len(roots) == len(children) == 2
            assert {s.parent.span_id for s in children} == {s.context.span_id for s in roots}
            assert all(s.parent is not None for s in children)
            assert children[0].status.status_code == roots[0].status.status_code == StatusCode.ERROR
            assert any(e.name == "exception" for e in children[0].events)
            assert {tuple(p.attributes) for p in points} == {("outcome",)}
        evidence = {
            "spans": [dict(name=s.name, trace_id=f"{s.context.trace_id:032x}", span_id=f"{s.context.span_id:016x}", parent_id=f"{s.parent.span_id:016x}" if s.parent else None, kind=s.kind.name, status=s.status.status_code.name, attributes=dict(s.attributes), resource=dict(s.resource.attributes), events=[e.name for e in s.events]) for s in spans],
            "metric_points": [dict(attributes=dict(p.attributes), value=p.value) for p in points],
        }
        destination.write_text(json.dumps(evidence, indent=2) + "\n")
    finally:
        telemetry.close()


if __name__ == "__main__":
    verify(sys.argv[1], pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3]))
