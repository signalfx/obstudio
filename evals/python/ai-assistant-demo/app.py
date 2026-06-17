import asyncio
import json
import logging
import random
import time
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("ai_assistant_demo")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="AI Assistant Demo")

CONTEXT_LIMIT_TOKENS = 4096
TOKEN_LIMIT_ERROR_THRESHOLD = 3800
active_streams: dict[str, float] = {}
feedback_queue: list[dict[str, Any]] = []


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1)
    session_id: str = "demo-session"
    tools: list[str] = Field(default_factory=lambda: ["search_docs", "lookup_customer"])
    stream: bool = False


class FeedbackRequest(BaseModel):
    session_id: str
    rating: int = Field(ge=1, le=5)
    comment: str = ""


@dataclass
class ProviderResult:
    text: str
    input_tokens: int
    output_tokens: int
    finish_reason: str
    truncated: bool


def _estimate_tokens(text: str) -> int:
    return max(1, len(text.split()) * 2)


def _context_usage(prompt: str, tool_results: list[dict[str, Any]]) -> tuple[int, float]:
    prompt_tokens = _estimate_tokens(prompt)
    tool_tokens = sum(_estimate_tokens(json.dumps(result)) for result in tool_results)
    used = prompt_tokens + tool_tokens + 256
    return used, min(1.0, used / CONTEXT_LIMIT_TOKENS)


async def run_tool(name: str, prompt: str) -> dict[str, Any]:
    started = time.perf_counter()
    await asyncio.sleep(random.uniform(0.02, 0.08))
    if "tool_error" in prompt and name == "lookup_customer":
        raise RuntimeError("lookup dependency failed")
    if name == "search_docs":
        result = {"tool": name, "matches": 3, "top_score": 0.91}
    elif name == "lookup_customer":
        result = {"tool": name, "tier": "enterprise", "region": "us0"}
    else:
        result = {"tool": name, "status": "unknown_tool"}
    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return result


async def call_provider(prompt: str, tool_results: list[dict[str, Any]]) -> ProviderResult:
    context_tokens, usage = _context_usage(prompt, tool_results)
    await asyncio.sleep(random.uniform(0.05, 0.16))
    if "provider_error" in prompt:
        raise RuntimeError("provider unavailable")
    if context_tokens > TOKEN_LIMIT_ERROR_THRESHOLD or "too_long" in prompt:
        raise HTTPException(status_code=413, detail="context token limit exceeded")
    truncated = usage > 0.75 or "truncate" in prompt
    output = "I found relevant metadata, checked tools, and prepared a short answer."
    if truncated:
        output = output[:48]
    return ProviderResult(
        text=output,
        input_tokens=context_tokens,
        output_tokens=_estimate_tokens(output),
        finish_reason="length" if truncated else "stop",
        truncated=truncated,
    )


async def build_turn(request: ChatRequest) -> dict[str, Any]:
    started = time.perf_counter()
    tool_results = []
    tool_errors = []
    for tool_name in request.tools:
        try:
            tool_results.append(await run_tool(tool_name, request.prompt))
        except Exception as exc:
            logger.warning("tool failed", extra={"tool": tool_name, "error": type(exc).__name__})
            tool_errors.append({"tool": tool_name, "error": type(exc).__name__})

    provider = await call_provider(request.prompt, tool_results)
    context_tokens, context_budget = _context_usage(request.prompt, tool_results)
    return {
        "session_id": request.session_id,
        "message_id": uuid.uuid4().hex,
        "answer": provider.text,
        "provider": "demo-provider",
        "model": "demo-gpt-4o-mini",
        "finish_reason": provider.finish_reason,
        "truncated": provider.truncated,
        "input_tokens": provider.input_tokens,
        "output_tokens": provider.output_tokens,
        "context_tokens": context_tokens,
        "context_budget": round(context_budget, 3),
        "tool_call_count": len(request.tools),
        "tool_error_count": len(tool_errors),
        "tool_results": tool_results,
        "tool_errors": tool_errors,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat")
async def chat(request: ChatRequest) -> dict[str, Any]:
    if request.stream:
        raise HTTPException(status_code=400, detail="use /v1/chat/stream for streaming")
    return await build_turn(request)


@app.post("/v1/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    stream_id = uuid.uuid4().hex
    active_streams[stream_id] = time.time()

    async def events():
        try:
            yield f"event: connected\ndata: {json.dumps({'stream_id': stream_id})}\n\n"
            turn = await build_turn(request)
            words = turn["answer"].split()
            for index, word in enumerate(words):
                await asyncio.sleep(0.03)
                yield f"event: token\ndata: {json.dumps({'index': index, 'text': word})}\n\n"
            yield f"event: done\ndata: {json.dumps(turn)}\n\n"
        except asyncio.CancelledError:
            logger.info("stream detached", extra={"stream_id": stream_id})
            raise
        except Exception as exc:
            logger.exception("stream failed", extra={"stream_id": stream_id, "error": type(exc).__name__})
            yield f"event: error\ndata: {json.dumps({'error': type(exc).__name__})}\n\n"
        finally:
            active_streams.pop(stream_id, None)

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/v1/streams")
async def streams() -> dict[str, Any]:
    now = time.time()
    oldest_age = max((now - started for started in active_streams.values()), default=0.0)
    return {"active": len(active_streams), "oldest_age_seconds": round(oldest_age, 3)}


@app.post("/v1/feedback")
async def feedback(request: FeedbackRequest) -> dict[str, Any]:
    record = request.model_dump()
    record["received_at"] = time.time()
    feedback_queue.append(record)
    return {"queued": len(feedback_queue)}


@app.post("/v1/feedback/export")
async def export_feedback() -> dict[str, Any]:
    started = time.perf_counter()
    await asyncio.sleep(random.uniform(0.03, 0.12))
    if random.random() < 0.08:
        logger.error("feedback export destination failed")
        raise HTTPException(status_code=502, detail="feedback destination failed")
    exported = len(feedback_queue)
    feedback_queue.clear()
    return {
        "records_exported": exported,
        "destination": "demo-warehouse",
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }
