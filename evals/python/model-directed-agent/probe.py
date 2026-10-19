"""Independent native telemetry probe; emits nothing except through app code."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace as NS

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def run(expect_agent: bool) -> None:
    exporter = InMemorySpanExporter()
    traces = TracerProvider()
    traces.add_span_processor(SimpleSpanProcessor(exporter))
    reader = InMemoryMetricReader()
    meters = MeterProvider(metric_readers=[reader])
    trace.set_tracer_provider(traces)
    metrics.set_meter_provider(meters)

    import chat_core

    captured = []
    errors = []
    for case in ("no_tool", "tool_feedback", "provider_failure"):
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            if case == "provider_failure":
                raise RuntimeError("synthetic provider unavailable")
            tool_calls = None
            content = "Synthetic final reply"
            if case == "tool_feedback" and len(calls) == 1:
                content = None
                tool_calls = [NS(id="call_synthetic", type="function", function=NS(
                    name="recommend_smash_burgers", arguments='{"city":"Austin"}'
                ))]
            return NS(id="response_synthetic", model="gpt-4o-mini",
                      usage=NS(prompt_tokens=11, completion_tokens=7, total_tokens=18),
                      choices=[NS(index=0, finish_reason="tool_calls" if tool_calls else "stop",
                                  message=NS(content=content, tool_calls=tool_calls))])

        client = NS(chat=NS(completions=NS(create=create)))
        messages = chat_core.new_conversation()
        messages.append({"role": "user", "content": "Synthetic Austin request"})
        start = len(exporter.get_finished_spans())
        try:
            reply = chat_core.run_turn(client, "gpt-4o-mini", messages)
            assert case != "provider_failure", "provider failure was swallowed"
            assert reply == "Synthetic final reply"
        except RuntimeError as exc:
            assert case == "provider_failure", str(exc)
            assert str(exc) == "synthetic provider unavailable"

        spans = exporter.get_finished_spans()[start:]
        records = [{"name": s.name, "span_id": format(s.context.span_id, "016x"),
                    "parent_id": format(s.parent.span_id, "016x") if s.parent else None,
                    "attributes": dict(s.attributes), "status": s.status.status_code.name}
                   for s in spans]
        captured.append({"case": case, "actual_model_calls": len(calls), "spans": records})
        if not expect_agent:
            continue
        agents = [s for s in spans if s.attributes.get("gen_ai.operation.name") == "invoke_agent"]
        if len(agents) != 1:
            errors.append(f"{case}: expected one agent, got {len(agents)}")
            continue
        agent = agents[0]
        if agent.attributes.get("gen_ai.agent.name") != "SmashBot":
            errors.append(f"{case}: missing source agent identity")
        if any(s.attributes.get("gen_ai.operation.name") == "invoke_workflow" for s in spans):
            errors.append(f"{case}: duplicate workflow at the same agent boundary")
        models = [s for s in spans if s.attributes.get("gen_ai.operation.name") == "chat"]
        tools = [s for s in spans if s.attributes.get("gen_ai.operation.name") == "execute_tool"]
        if len(models) != len(calls) or len(tools) != (1 if case == "tool_feedback" else 0):
            errors.append(f"{case}: duplicate/missing model or tool nodes")
        if any(s.parent is None or s.parent.span_id != agent.context.span_id for s in models + tools):
            errors.append(f"{case}: wrong model/tool parent")
        if agent.attributes.get("assistant.llm.calls") != len(calls):
            errors.append(f"{case}: incorrect attempted model-call count")
        if agent.attributes.get("assistant.tool.calls") != len(tools):
            errors.append(f"{case}: incorrect tool-call count")
        if (agent.status.status_code.name == "ERROR") != (case == "provider_failure"):
            errors.append(f"{case}: wrong agent status")
        if case == "provider_failure" and not agent.attributes.get("error.type"):
            errors.append(f"{case}: missing agent error.type")

    measurements = []
    for resource in reader.get_metrics_data().resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                measurements.append({"name": metric.name, "unit": metric.unit,
                                     "kind": type(metric.data).__name__,
                                     "points": [{"attributes": dict(p.attributes),
                                                 "value": getattr(p, "value", None),
                                                 "count": getattr(p, "count", None),
                                                 "sum": getattr(p, "sum", None)}
                                                for p in metric.data.data_points]})
    duration = [m for m in measurements if m["name"] == "gen_ai.invoke_agent.duration"]
    if expect_agent and (len(duration) != 1 or duration[0]["kind"] != "Histogram"
                         or duration[0]["unit"] != "s"
                         or sum(p["count"] for p in duration[0]["points"]) != 3):
        errors.append("agent duration: expected Histogram s with three observations")
    if expect_agent and duration:
        if any(p["attributes"].get("gen_ai.agent.name") != "SmashBot" for p in duration[0]["points"]):
            errors.append("agent duration: missing source-applicable agent name")
        if not any(p["attributes"].get("error.type") for p in duration[0]["points"]):
            errors.append("agent duration: missing bounded failure dimension")
    output = Path(".observe/probe-native.json")
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps({"cases": captured, "metrics": measurements, "errors": errors}, indent=2) + "\n")
    meters.shutdown()
    traces.shutdown()
    if errors:
        raise AssertionError("; ".join(errors))
    print("PASS: original app executed three cases; native telemetry saved to", output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-agent", action="store_true")
    run(parser.parse_args().expect_agent)
