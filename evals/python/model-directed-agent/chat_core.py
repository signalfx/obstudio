"""Shared chat-agent core used by both the CLI (`agent.py`) and web app (`app.py`).

This module owns the system prompt, tool schema, tool dispatch, and the
`run_turn` loop that resolves tool calls against the OpenAI Chat Completions API.
Keeping it here means the terminal and browser front-ends behave identically.
"""

from __future__ import annotations

import json
import os

from openai import OpenAI
from opentelemetry import metrics, trace
from opentelemetry.trace import SpanKind, StatusCode

from recommendations import recommend_smash_burgers

# GenAI telemetry. Tracer/meter and instruments are created once at import and
# reused; they are cheap no-ops until a provider is configured (see otel_setup).
_tracer = trace.get_tracer("smashbot.chat")
_meter = metrics.get_meter("smashbot.chat")

# gen_ai.client.token.usage: token usage by type (input/output).
_token_usage = _meter.create_counter(
    "gen_ai.client.token.usage",
    unit="{token}",
    description="Number of tokens used, by token type.",
)
# Per-turn LLM and tool call fanout.
_llm_calls = _meter.create_counter(
    "assistant.llm.calls",
    unit="{call}",
    description="Number of LLM (chat) calls per workflow turn.",
)
_tool_calls = _meter.create_counter(
    "assistant.tool.calls",
    unit="{call}",
    description="Number of tool calls per workflow turn.",
)

WORKFLOW_NAME = "smashbot_turn"
PROVIDER_NAME = "openai"


def _error_type(exc: Exception) -> str:
    """Return a low-cardinality error class for span attribution.

    Uses the exception's status_code when the provider exposes one (OpenAI
    errors carry one), otherwise the exception class name. Never the raw
    message.
    """
    status = getattr(exc, "status_code", None)
    if status is not None:
        return f"http_{status}"
    return type(exc).__name__

SYSTEM_PROMPT = (
    "You are SmashBot, a friendly chat assistant whose specialty is recommending "
    "smash burger restaurants. Your mascot is Buttercup, a spirited pony. When a "
    "user mentions a city (or you can figure out which city they mean), call the "
    "recommend_smash_burgers tool to get options, then present them "
    "conversationally with the restaurant names and a short reason for each. If "
    "the user hasn't given a city, ask which city they're in. Keep replies "
    "concise and upbeat. You can also answer general chit-chat, but always steer "
    "toward helping them find a great smash burger."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "recommend_smash_burgers",
            "description": (
                "Get a list of smash burger restaurant recommendations for a "
                "specific city."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "The city to find smash burger restaurants in, e.g. 'Austin'.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "How many recommendations to return (1-3).",
                        "minimum": 1,
                        "maximum": 3,
                    },
                },
                "required": ["city"],
            },
        },
    }
]

# Maps tool names to their Python implementations.
TOOL_IMPLEMENTATIONS = {
    "recommend_smash_burgers": recommend_smash_burgers,
}


def build_client(api_key: str | None = None) -> OpenAI:
    """Create an OpenAI client, reading the key from the environment if needed."""
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    return OpenAI(api_key=key)


def get_model() -> str:
    """Return the configured chat model."""
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def new_conversation() -> list:
    """Return a fresh message list seeded with the system prompt."""
    return [{"role": "system", "content": SYSTEM_PROMPT}]


def _dispatch_tool_call(tool_call) -> str:
    """Execute a tool call and return its JSON-serialized result.

    Emits one execute_tool GenAI span per dispatch with a stable tool name. The
    raw arguments (e.g. the city) are never used as span-name segments or
    attributes to keep cardinality bounded.
    """
    name = tool_call.function.name
    # Span name uses only the stable tool name, never the arguments.
    with _tracer.start_as_current_span(
        f"execute_tool {name}", kind=SpanKind.INTERNAL
    ) as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", name)
        try:
            args = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}

        impl = TOOL_IMPLEMENTATIONS.get(name)
        if impl is None:
            span.set_attribute("error.type", "unknown_tool")
            span.set_status(StatusCode.ERROR, "unknown tool")
            return json.dumps({"error": f"Unknown tool: {name}"})

        try:
            result = impl(**args)
        except TypeError as exc:
            span.record_exception(exc)
            span.set_attribute("error.type", "invalid_arguments")
            span.set_status(StatusCode.ERROR, "invalid arguments")
            result = {"error": f"Invalid arguments for {name}: {exc}"}

        return json.dumps(result)


def _chat_completion(client: OpenAI, model: str, messages: list):
    """Call the provider inside a GenAI chat inference span.

    Emits one `chat {model}` span per provider call with gen_ai.* attributes,
    records token usage as both span attributes and a metric, and sets error
    status with a low-cardinality error.type on failure. Returns the response.
    """
    with _tracer.start_as_current_span(f"chat {model}", kind=SpanKind.CLIENT) as span:
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.provider.name", PROVIDER_NAME)
        span.set_attribute("gen_ai.request.model", model)
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
            )
        except Exception as exc:  # noqa: BLE001 - attribute then re-raise
            span.record_exception(exc)
            span.set_attribute("error.type", _error_type(exc))
            span.set_status(StatusCode.ERROR, type(exc).__name__)
            raise

        # Response model + token usage when the provider returns them.
        response_model = getattr(response, "model", None)
        if response_model:
            span.set_attribute("gen_ai.response.model", response_model)

        usage = getattr(response, "usage", None)
        if usage is not None:
            prompt_tokens = getattr(usage, "prompt_tokens", None)
            completion_tokens = getattr(usage, "completion_tokens", None)
            total_tokens = getattr(usage, "total_tokens", None)
            usage_attrs = {"gen_ai.request.model": model}
            if prompt_tokens is not None:
                span.set_attribute("gen_ai.usage.input_tokens", prompt_tokens)
                _token_usage.add(prompt_tokens, {**usage_attrs, "gen_ai.token.type": "input"})
            if completion_tokens is not None:
                span.set_attribute("gen_ai.usage.output_tokens", completion_tokens)
                _token_usage.add(
                    completion_tokens, {**usage_attrs, "gen_ai.token.type": "output"}
                )
            if total_tokens is not None:
                span.set_attribute("gen_ai.usage.total_tokens", total_tokens)

        return response


def run_turn(client: OpenAI, model: str, messages: list) -> str:
    """Run one assistant turn, resolving any tool calls, and return the reply text.

    Appends all new messages (assistant + tool results) to `messages` in place.
    The whole turn is wrapped in an invoke_workflow span that parents the chat
    and execute_tool spans and carries per-turn token/call aggregates.
    """
    with _tracer.start_as_current_span(
        f"invoke_workflow {WORKFLOW_NAME}", kind=SpanKind.INTERNAL
    ) as workflow_span:
        workflow_span.set_attribute("gen_ai.operation.name", "invoke_workflow")
        workflow_span.set_attribute("gen_ai.workflow.name", WORKFLOW_NAME)

        llm_call_count = 0
        tool_call_count = 0
        total_tokens_agg = 0

        response = _chat_completion(client, model, messages)
        llm_call_count += 1
        total_tokens_agg += _response_total_tokens(response)
        message = response.choices[0].message

        # Resolve tool calls in a loop until the model returns a plain text reply.
        while message.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ],
                }
            )

            for tool_call in message.tool_calls:
                result = _dispatch_tool_call(tool_call)
                tool_call_count += 1
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    }
                )

            response = _chat_completion(client, model, messages)
            llm_call_count += 1
            total_tokens_agg += _response_total_tokens(response)
            message = response.choices[0].message

        reply = message.content or ""
        messages.append({"role": "assistant", "content": reply})

        # Per-turn aggregates on the workflow span (not a generic HTTP span).
        workflow_span.set_attribute("assistant.llm.calls", llm_call_count)
        workflow_span.set_attribute("assistant.tool.calls", tool_call_count)
        if total_tokens_agg:
            workflow_span.set_attribute("gen_ai.usage.total_tokens", total_tokens_agg)

        # Per-turn fanout metrics.
        _llm_calls.add(llm_call_count, {"gen_ai.workflow.name": WORKFLOW_NAME})
        _tool_calls.add(tool_call_count, {"gen_ai.workflow.name": WORKFLOW_NAME})

        return reply


def _response_total_tokens(response) -> int:
    """Return total_tokens from a response usage block, or 0 when absent."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0
    return getattr(usage, "total_tokens", None) or 0
