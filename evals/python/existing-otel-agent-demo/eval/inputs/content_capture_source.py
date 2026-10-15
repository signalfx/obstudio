"""App-owned content capture seed with a deliberate dict-key-only redactor bug.

Copy this file to content_capture.py before the focused repair. The business
app's existing workflow/model spans, ownership and transport remain unchanged.
"""
from __future__ import annotations

import contextlib
import json
from typing import Any

from opentelemetry import trace

PROTECTED_KEYS = {"user_id", "account_id", "email", "api_key", "authorization", "password", "secret", "hidden_reasoning", "chain_of_thought"}


def sanitize(value: Any) -> Any:
    """BUG: protected structured keys are handled, freeform string values are not."""
    if isinstance(value, dict):
        return {key: "[REDACTED]" if str(key).casefold() in PROTECTED_KEYS else sanitize(item)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    return value


def write_content(span: Any, inputs: Any, *, result_available: bool, result: Any = None) -> None:
    """Write actual inputs/result to this same owning span; no telemetry creation."""
    span.set_attribute("demo.capture.mode", "redacted")
    span.set_attribute("gen_ai.input.messages", json.dumps([
        {"role": "user", "parts": [{"type": "text", "content": json.dumps(sanitize(inputs), ensure_ascii=False)}]},
    ], ensure_ascii=False))
    if result_available:
        span.set_attribute("gen_ai.output.messages", json.dumps([
            {"role": "assistant", "parts": [{"type": "text", "content": json.dumps(sanitize(result), ensure_ascii=False)}], "finish_reason": "stop"},
        ], ensure_ascii=False))


def configure(app: Any) -> None:
    if getattr(app, "_content_capture_hook_added", False):
        return
    if app.trace_producer is None:
        raise ValueError("this capture adapter requires the existing GenAI trace producer")

    def begin(span: Any, operation: str, metadata: dict[str, Any]) -> None:
        write_content(span, metadata["inputs"], result_available=False)

    @contextlib.contextmanager
    def complete(operation: str, metadata: dict[str, Any]):
        if operation not in {"workflow", "model"}:
            yield
            return
        span = trace.get_current_span()
        try:
            yield
        finally:
            write_content(span, metadata["inputs"], result_available=metadata["result_available"],
                          result=metadata.get("result"))

    app.trace_producer.span_hooks.append(begin)
    app.operation_hooks.append(complete)
    app._content_capture_hook_added = True
