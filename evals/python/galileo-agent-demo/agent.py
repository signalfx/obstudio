"""Offline replay entrypoint for a model-directed agent on the Galileo pipeline."""

from __future__ import annotations

import json

from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

AGENT_NAME = "support-agent"
tracer = trace.get_tracer("galileo-agent-demo.agent")


def search_docs(query: str) -> str:
    return f"Documentation for {query}"


def run_agent(client, messages: list[dict]) -> str:
    tools = {"search_docs": search_docs}
    with tracer.start_as_current_span(
        f"invoke_agent {AGENT_NAME}",
        attributes={"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": AGENT_NAME},
    ) as agent:
        try:
            while True:
                with tracer.start_as_current_span(
                    "chat replay-model",
                    kind=SpanKind.CLIENT,
                    attributes={"gen_ai.operation.name": "chat", "gen_ai.request.model": "replay-model"},
                ):
                    response = client.complete(messages=messages, tools=list(tools))
                messages.append(response)
                if not response.get("tool_calls"):
                    return response["content"]
                for call in response["tool_calls"]:
                    with tracer.start_as_current_span(
                        f"execute_tool {call['name']}",
                        attributes={"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": call["name"]},
                    ):
                        result = tools[call["name"]](**call["arguments"])
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
        except Exception as error:
            agent.set_status(Status(StatusCode.ERROR))
            agent.set_attribute("error.type", type(error).__name__)
            raise


class ReplayModel:
    def complete(self, *, messages, tools):
        if messages[-1]["role"] == "tool":
            return {"role": "assistant", "content": messages[-1]["content"]}
        return {
            "role": "assistant",
            "tool_calls": [{"id": "replay-call", "name": tools[0], "arguments": {"query": "returns"}}],
        }


if __name__ == "__main__":
    # Reuse the actual web startup's Galileo-owned provider and export path.
    from app import provider

    try:
        print(json.dumps({"answer": run_agent(ReplayModel(), [{"role": "user", "content": "Find returns docs"}])}))
    finally:
        provider.force_flush()
        provider.shutdown()
