from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

WORKFLOW_NAME = "assistant_v3_turn"
AGENT_NAME = "deepagents"
MODEL_NAME = "gpt-5.5"
OVERLAPPING_FRAMEWORK_INSTRUMENTORS = ("langchain", "openai")

app = FastAPI(title="Assistant v3 Framework Bridge Demo")


class TurnRequest(BaseModel):
    prompt: str
    model: str = MODEL_NAME


@dataclass
class SpanHandle:
    name: str

    def end(self) -> None:
        return None


def start_workflow_span(name: str) -> SpanHandle:
    # App-owned canonical span: gen_ai.operation.name=invoke_workflow.
    return SpanHandle(f"invoke_workflow {name}")


def start_agent_span(name: str) -> SpanHandle:
    # App-owned canonical span: gen_ai.operation.name=invoke_agent.
    return SpanHandle(f"invoke_agent {name}")


def start_chat_span(model: str) -> SpanHandle:
    # App-owned canonical span: gen_ai.operation.name=chat.
    return SpanHandle(f"chat {model}")


def start_tool_span(tool_name: str) -> SpanHandle:
    # App-owned canonical span: gen_ai.operation.name=execute_tool.
    return SpanHandle(f"execute_tool {tool_name}")


def framework_genai_instrumentation_enabled() -> bool:
    disabled = {
        name.strip().lower()
        for name in os.getenv("OTEL_PYTHON_DISABLED_INSTRUMENTATIONS", "").split(",")
        if name.strip()
    }
    return any(name not in disabled for name in OVERLAPPING_FRAMEWORK_INSTRUMENTORS)


def simulate_framework_shadow_nodes(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Model the duplicate GenAI DAG emitted when framework hooks are not suppressed."""
    shadow_nodes = [{"source": "framework", "kind": "agent", "name": "LangGraph"}]
    for event in events:
        if event["event"] == "on_chat_model_start":
            shadow_nodes.append({"source": "framework", "kind": "llm", "name": f"chat {MODEL_NAME}"})
        if event["event"] == "on_tool_start":
            shadow_nodes.extend(
                [
                    {"source": "framework", "kind": "tool", "name": "step tools"},
                    {"source": "framework", "kind": "tool", "name": event["name"]},
                ]
            )
    return shadow_nodes


async def deepagents_event_stream(prompt: str) -> list[dict[str, Any]]:
    await asyncio.sleep(0.01)
    events = [
        {"event": "on_chat_model_start", "model": MODEL_NAME},
        {"event": "on_chat_model_end", "model": MODEL_NAME, "input_tokens": 32, "output_tokens": 8},
    ]
    if "time" in prompt.lower():
        events.extend(
            [
                {"event": "on_tool_start", "name": "get_current_time"},
                {"event": "on_tool_end", "name": "get_current_time"},
                {"event": "on_chat_model_start", "model": MODEL_NAME},
                {"event": "on_chat_model_end", "model": MODEL_NAME, "input_tokens": 48, "output_tokens": 12},
            ]
        )
    return events


@app.post("/v2/assistant/sessions")
async def assistant_session(request: TurnRequest) -> dict[str, Any]:
    workflow = start_workflow_span(WORKFLOW_NAME)
    agent = start_agent_span(AGENT_NAME)
    llm_calls = 0
    tool_calls = 0
    events = await deepagents_event_stream(request.prompt)
    framework_shadow_nodes = (
        simulate_framework_shadow_nodes(events)
        if framework_genai_instrumentation_enabled()
        else []
    )
    for event in events:
        if event["event"] == "on_chat_model_start":
            llm_calls += 1
            start_chat_span(request.model).end()
        if event["event"] == "on_tool_start":
            tool_calls += 1
            start_tool_span(event["name"]).end()
    agent.end()
    workflow.end()
    return {
        "workflow": WORKFLOW_NAME,
        "agent": AGENT_NAME,
        "llm_calls": llm_calls,
        "tool_calls": tool_calls,
        "framework_shadow_nodes": framework_shadow_nodes,
    }
