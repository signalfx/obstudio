import json
import logging
import os
import sys

from opentelemetry import metrics, trace

from telemetry import configure


class ReplayModel:
    def complete(self, messages, tools):
        if messages[-1]["role"] == "tool":
            return {"content": messages[-1]["content"]}
        return {"tool_calls": [{"id": "call-1", "name": tools[0], "arguments": {"query": "returns"}}]}


def run_turn():
    tracer = trace.get_tracer("connection-agent")
    counter = metrics.get_meter("connection-agent").create_counter("agent.turns")
    messages = [{"role": "user", "content": "Find returns docs"}]
    tools = {"search_docs": lambda query: f"Documentation for {query}"}
    with tracer.start_as_current_span(
        "invoke_agent mode-agent",
        attributes={"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "mode-agent"},
    ):
        counter.add(1)
        while True:
            with tracer.start_as_current_span("chat replay-model", attributes={"gen_ai.operation.name": "chat"}):
                reply = ReplayModel().complete(messages, list(tools))
            if not reply.get("tool_calls"):
                logging.getLogger("connection-agent").info("agent completed")
                print(json.dumps({"answer": reply["content"]}), flush=True)
                return
            messages.append(reply)
            for call in reply["tool_calls"]:
                with tracer.start_as_current_span(
                    "execute_tool search_docs", attributes={"gen_ai.operation.name": "execute_tool"}
                ):
                    value = tools[call["name"]](**call["arguments"])
                messages.append({"role": "tool", "content": value, "tool_call_id": call["id"]})


def main():
    finish = configure()
    try:
        if os.getenv("AGENT_INTERACTIVE") == "1":
            for line in sys.stdin:
                if line.strip() == "quit":
                    break
                run_turn()
        else:
            run_turn()
    finally:
        finish()
