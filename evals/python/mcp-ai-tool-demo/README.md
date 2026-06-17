# MCP AI Tool Demo

Small FastAPI service that mimics an MCP-style AI tool gateway. It exposes
JSON-RPC methods, tool execution, session lifecycle, streaming keepalives,
provider calls, and tool fanout without custom OpenTelemetry instrumentation.

Use it as a before/after demo for the GenAI readiness skills. The baseline app
has the code surfaces the skills should audit and patch: MCP method routing,
tool execution, long-lived streams, provider/model calls, and session state.

## Run

```sh
cd examples/python/mcp-ai-tool-demo
make dev
```

In another terminal:

```sh
make load
```

The service listens on `http://localhost:8020`.

## Demo Workflow

1. Run the baseline app and load generator.
2. Run `/otel-audit` on this directory and review MCP and GenAI pathway gaps.
3. Run `/otel-instrument` on this directory.
4. Run the instrumented app with `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`.
5. Run `make load` again and inspect Explorer for MCP method, session, stream,
   provider, tool, and context-pressure telemetry.

## Eval Workflow

The eval fixture definitions are checked into:

```text
evals/python/mcp-ai-tool-demo/eval/qual/audit.json
evals/python/mcp-ai-tool-demo/eval/qual/instrument.json
```

Validate the eval fixture and render a report:

```sh
make -C evals eval-validation SKILL=skills/otel-audit EVAL_PATTERN='python/mcp-ai-tool-demo/eval/qual/audit.json'
make -C evals eval-validation SKILL=skills/otel-instrument EVAL_PATTERN='python/mcp-ai-tool-demo/eval/qual/instrument.json'
```
