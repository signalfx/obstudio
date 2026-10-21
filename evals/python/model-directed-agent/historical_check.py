"""Focused OTel signal-assertion tests for SmashBot's GenAI instrumentation.

Uses in-memory OTel exporters and a stubbed OpenAI client so no live API key or
credits are needed. Proves the workflow / chat / tool spans and the token and
call-count metrics emit with the expected GenAI semantic-convention attributes.

Run: python3 historical_check.py
"""

from __future__ import annotations

import sys
import types

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)


# ---- Install in-memory providers BEFORE importing chat_core ----
_span_exporter = InMemorySpanExporter()
_tracer_provider = TracerProvider()
_tracer_provider.add_span_processor(SimpleSpanProcessor(_span_exporter))
trace.set_tracer_provider(_tracer_provider)

_metric_reader = InMemoryMetricReader()
metrics.set_meter_provider(MeterProvider(metric_readers=[_metric_reader]))

import chat_core  # noqa: E402


# ---- Stub OpenAI client: one tool call, then a final text reply ----
def _msg(content=None, tool_calls=None):
    return types.SimpleNamespace(content=content, tool_calls=tool_calls)


def _tool_call(call_id, name, arguments):
    return types.SimpleNamespace(
        id=call_id,
        type="function",
        function=types.SimpleNamespace(name=name, arguments=arguments),
    )


def _response(message, model="gpt-4o-mini", usage=(11, 7, 18)):
    prompt, completion, total = usage
    return types.SimpleNamespace(
        model=model,
        usage=types.SimpleNamespace(
            prompt_tokens=prompt, completion_tokens=completion, total_tokens=total
        ),
        choices=[types.SimpleNamespace(message=message)],
    )


class _StubCompletions:
    def __init__(self):
        self._calls = 0

    def create(self, **kwargs):
        self._calls += 1
        if self._calls == 1:
            return _response(
                _msg(
                    tool_calls=[
                        _tool_call("call_1", "recommend_smash_burgers", '{"city": "Austin"}')
                    ]
                )
            )
        return _response(_msg(content="Here are smash burgers in Austin: ..."))


class _StubClient:
    def __init__(self):
        self.chat = types.SimpleNamespace(completions=_StubCompletions())


def _spans_by_name():
    return {s.name: s for s in _span_exporter.get_finished_spans()}


def _metric_points():
    data = _metric_reader.get_metrics_data()
    points = {}
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                total = 0
                dims = []
                for dp in metric.data.data_points:
                    total += dp.value
                    dims.append(dict(dp.attributes))
                points[metric.name] = (total, dims)
    return points


def main() -> int:
    client = _StubClient()
    messages = chat_core.new_conversation()
    messages.append({"role": "user", "content": "smash burgers in Austin"})

    reply = chat_core.run_turn(client, "gpt-4o-mini", messages)
    assert reply.startswith("Here are smash burgers"), reply

    spans = _spans_by_name()
    failures = []

    # Workflow span
    wf = spans.get("invoke_workflow smashbot_turn")
    if wf is None:
        failures.append("missing invoke_workflow span")
    else:
        a = dict(wf.attributes)
        if a.get("gen_ai.operation.name") != "invoke_workflow":
            failures.append("workflow: bad gen_ai.operation.name")
        if a.get("gen_ai.workflow.name") != "smashbot_turn":
            failures.append("workflow: bad gen_ai.workflow.name")
        if a.get("assistant.llm.calls") != 2:
            failures.append(f"workflow: assistant.llm.calls={a.get('assistant.llm.calls')} (want 2)")
        if a.get("assistant.tool.calls") != 1:
            failures.append(f"workflow: assistant.tool.calls={a.get('assistant.tool.calls')} (want 1)")
        if a.get("gen_ai.usage.total_tokens") != 36:
            failures.append(f"workflow: total_tokens={a.get('gen_ai.usage.total_tokens')} (want 36)")

    # Chat inference span
    chat = spans.get("chat gpt-4o-mini")
    if chat is None:
        failures.append("missing chat inference span")
    else:
        a = dict(chat.attributes)
        for k, want in [
            ("gen_ai.operation.name", "chat"),
            ("gen_ai.provider.name", "openai"),
            ("gen_ai.request.model", "gpt-4o-mini"),
            ("gen_ai.response.model", "gpt-4o-mini"),
            ("gen_ai.usage.input_tokens", 11),
            ("gen_ai.usage.output_tokens", 7),
            ("gen_ai.usage.total_tokens", 18),
        ]:
            if a.get(k) != want:
                failures.append(f"chat: {k}={a.get(k)} (want {want})")

    # Tool execution span
    tool = spans.get("execute_tool recommend_smash_burgers")
    if tool is None:
        failures.append("missing execute_tool span")
    else:
        a = dict(tool.attributes)
        if a.get("gen_ai.operation.name") != "execute_tool":
            failures.append("tool: bad gen_ai.operation.name")
        if a.get("gen_ai.tool.name") != "recommend_smash_burgers":
            failures.append("tool: bad gen_ai.tool.name")

    # Parentage: chat and tool spans are children of the workflow span
    if wf is not None and chat is not None:
        if chat.parent is None or chat.parent.span_id != wf.context.span_id:
            failures.append("chat span is not a child of the workflow span")
    if wf is not None and tool is not None:
        if tool.parent is None or tool.parent.span_id != wf.context.span_id:
            failures.append("tool span is not a child of the workflow span")

    # Metrics
    pts = _metric_points()
    if "gen_ai.client.token.usage" not in pts:
        failures.append("missing gen_ai.client.token.usage metric")
    else:
        total, dims = pts["gen_ai.client.token.usage"]
        # 2 chat calls x (11 input + 7 output) = 36
        if total != 36:
            failures.append(f"token usage total={total} (want 36)")
        types_seen = {d.get("gen_ai.token.type") for d in dims}
        if not {"input", "output"}.issubset(types_seen):
            failures.append(f"token types seen={types_seen}")
    if pts.get("assistant.llm.calls", (None,))[0] != 2:
        failures.append(f"assistant.llm.calls metric={pts.get('assistant.llm.calls')}")
    if pts.get("assistant.tool.calls", (None,))[0] != 1:
        failures.append(f"assistant.tool.calls metric={pts.get('assistant.tool.calls')}")

    if failures:
        print("FAIL:")
        for f in failures:
            print("  -", f)
        return 1

    print("PASS: all GenAI spans and metrics emitted with expected attributes")
    print("  spans:", sorted(spans))
    print("  metrics:", sorted(pts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
