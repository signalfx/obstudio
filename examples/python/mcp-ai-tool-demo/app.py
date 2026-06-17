import asyncio
import json
import logging
import random
import time
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("mcp_ai_tool_demo")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="MCP AI Tool Demo")

sessions: dict[str, dict[str, Any]] = {}
active_streams: dict[str, float] = {}


class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


@dataclass
class ProviderResult:
    text: str
    input_tokens: int
    output_tokens: int
    finish_reason: str


def _require_auth(authorization: str | None) -> None:
    if authorization != "Bearer demo-token":
        raise HTTPException(status_code=401, detail="invalid demo token")


def _estimate_tokens(payload: Any) -> int:
    return max(1, len(json.dumps(payload).split()) * 2)


def _response(request: JsonRpcRequest, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request.id, "result": result}


def _error(request: JsonRpcRequest, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request.id, "error": {"code": code, "message": message}}


async def _call_provider(tool_name: str, arguments: dict[str, Any]) -> ProviderResult:
    await asyncio.sleep(random.uniform(0.04, 0.12))
    if arguments.get("provider_error"):
        raise RuntimeError("provider unavailable")
    input_tokens = _estimate_tokens(arguments) + 64
    text = f"{tool_name} completed with {random.randint(2, 5)} findings"
    return ProviderResult(
        text=text,
        input_tokens=input_tokens,
        output_tokens=_estimate_tokens(text),
        finish_reason="stop",
    )


async def _execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    await asyncio.sleep(random.uniform(0.02, 0.08))
    if name not in {"summarize_metadata", "search_knowledge"}:
        raise ValueError("unknown tool")
    if arguments.get("tool_error"):
        raise RuntimeError("tool dependency failed")
    provider = await _call_provider(name, arguments)
    return {
        "tool": name,
        "content": provider.text,
        "model": "demo-tool-model",
        "finish_reason": provider.finish_reason,
        "input_tokens": provider.input_tokens,
        "output_tokens": provider.output_tokens,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }


async def _handle_initialize(request: JsonRpcRequest) -> dict[str, Any]:
    session_id = uuid.uuid4().hex
    sessions[session_id] = {
        "created_at": time.time(),
        "authenticated": True,
        "method_count": 1,
        "tool_call_count": 0,
    }
    return _response(
        request,
        {
            "session_id": session_id,
            "server": "mcp-ai-tool-demo",
            "capabilities": {"tools": True, "streaming": True},
        },
    )


async def _handle_tools_list(request: JsonRpcRequest) -> dict[str, Any]:
    return _response(
        request,
        {
            "tools": [
                {"name": "summarize_metadata", "input_schema": {"type": "object"}},
                {"name": "search_knowledge", "input_schema": {"type": "object"}},
            ]
        },
    )


async def _handle_tools_call(request: JsonRpcRequest) -> dict[str, Any]:
    session_id = request.params.get("session_id")
    if session_id not in sessions:
        return _error(request, -32001, "unknown session")
    name = str(request.params.get("name", ""))
    arguments = dict(request.params.get("arguments", {}))
    sessions[session_id]["method_count"] += 1
    sessions[session_id]["tool_call_count"] += 1
    try:
        result = await _execute_tool(name, arguments)
    except ValueError as exc:
        return _error(request, -32602, str(exc))
    except Exception as exc:
        logger.warning("tool call failed", extra={"tool": name, "error": type(exc).__name__})
        return _error(request, -32002, type(exc).__name__)
    return _response(request, result)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/mcp")
async def mcp_rpc(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_auth(authorization)
    payload = JsonRpcRequest.model_validate(await request.json())
    if payload.method == "initialize":
        return await _handle_initialize(payload)
    if payload.method == "tools/list":
        return await _handle_tools_list(payload)
    if payload.method == "tools/call":
        return await _handle_tools_call(payload)
    return _error(payload, -32601, "method not found")


@app.get("/mcp/sessions")
async def list_sessions() -> dict[str, Any]:
    now = time.time()
    oldest_age = max((now - item["created_at"] for item in sessions.values()), default=0.0)
    return {
        "active_sessions": len(sessions),
        "active_streams": len(active_streams),
        "oldest_session_age_seconds": round(oldest_age, 3),
    }


@app.delete("/mcp/sessions/{session_id}")
async def close_session(session_id: str) -> dict[str, Any]:
    existed = sessions.pop(session_id, None) is not None
    return {"session_id": session_id, "closed": existed}


@app.get("/mcp/sessions/{session_id}/stream")
async def session_stream(session_id: str, authorization: str | None = Header(default=None)) -> StreamingResponse:
    _require_auth(authorization)
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="unknown session")
    stream_id = uuid.uuid4().hex
    active_streams[stream_id] = time.time()

    async def events():
        try:
            yield f"event: start\ndata: {json.dumps({'stream_id': stream_id, 'session_id': session_id})}\n\n"
            for index in range(5):
                await asyncio.sleep(0.05)
                if session_id not in sessions:
                    yield "event: close\ndata: {\"reason\":\"session_closed\"}\n\n"
                    return
                yield f"event: keepalive\ndata: {json.dumps({'index': index})}\n\n"
            yield "event: done\ndata: {\"outcome\":\"ok\"}\n\n"
        except asyncio.CancelledError:
            logger.info("mcp stream detached", extra={"session_id": session_id, "stream_id": stream_id})
            raise
        except Exception as exc:
            logger.exception("mcp stream failed", extra={"error": type(exc).__name__})
            yield f"event: error\ndata: {json.dumps({'error': type(exc).__name__})}\n\n"
        finally:
            active_streams.pop(stream_id, None)

    return StreamingResponse(events(), media_type="text/event-stream")
