from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from galileo.otel import GalileoSpanProcessor, add_galileo_span_processor
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from pydantic import BaseModel

SERVICE_NAME = "galileo-agent-demo"
WORKFLOW_NAME = "support_turn"
MODEL_NAME = "gpt-4o-mini"
TOOL_NAME = "search_docs"


def configure_telemetry() -> TracerProvider:
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": os.getenv("OTEL_SERVICE_NAME", SERVICE_NAME),
                "service.version": "0.1.0",
            }
        )
    )
    processor = GalileoSpanProcessor(
        project=os.getenv("GALILEO_PROJECT", "galileo-agent-demo")
    )
    add_galileo_span_processor(provider, processor)
    trace.set_tracer_provider(provider)
    return provider


provider = configure_telemetry()
tracer = trace.get_tracer(__name__)
app = FastAPI(title="Galileo Agent Demo")


class ChatRequest(BaseModel):
    prompt: str


async def response_chunks() -> AsyncIterator[str]:
    await asyncio.sleep(0.01)
    yield "answer "
    await asyncio.sleep(0.01)
    yield "complete"


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    workflow = tracer.start_span(
        f"invoke_workflow {WORKFLOW_NAME}",
        attributes={
            "gen_ai.operation.name": "invoke_workflow",
            "gen_ai.workflow.name": WORKFLOW_NAME,
        },
    )

    async def stream() -> AsyncIterator[str]:
        try:
            with trace.use_span(workflow, end_on_exit=False):
                with tracer.start_as_current_span(
                    f"execute_tool {TOOL_NAME}",
                    attributes={
                        "gen_ai.operation.name": "execute_tool",
                        "gen_ai.tool.name": TOOL_NAME,
                    },
                ):
                    await asyncio.sleep(0.01)
                with tracer.start_as_current_span(
                    f"chat {MODEL_NAME}",
                    attributes={
                        "gen_ai.operation.name": "chat",
                        "gen_ai.provider.name": "openai",
                        "gen_ai.request.model": MODEL_NAME,
                        "gen_ai.response.model": MODEL_NAME,
                    },
                ):
                    async for chunk in response_chunks():
                        yield chunk
        finally:
            workflow.end()

    return StreamingResponse(stream(), media_type="text/plain")
