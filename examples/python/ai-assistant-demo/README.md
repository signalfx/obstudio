# AI Assistant Demo

Small FastAPI service that mimics the observability surfaces of an AI assistant:
chat turns, streaming responses, provider calls, tool fanout, context pressure,
and offline feedback export.

The app is intentionally a baseline fixture. It has realistic code paths but no
custom OpenTelemetry instrumentation. Use it to demonstrate the before/after
effect of the OTel skills.

## Run

```sh
cd examples/python/ai-assistant-demo
make dev
```

In another terminal:

```sh
make load
```

The service listens on `http://localhost:8010`.

## Demo Workflow

1. Run the baseline app and load generator.
2. Run `/otel-audit` on this directory and review the GenAI gaps.
3. Run `/otel-instrument` on this directory.
4. Run the instrumented app with `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`.
5. Run `make load` again and inspect Explorer for turn, provider, tool, stream,
   context, and feedback export telemetry.

## Eval Workflow

The eval fixture definitions are checked into:

```text
evals/python/ai-assistant-demo/eval/qual/audit.json
evals/python/ai-assistant-demo/eval/qual/instrument.json
```

Validate the eval fixture and render a report:

```sh
make -C evals eval-validation SKILL=skills/otel-audit EVAL_PATTERN='python/ai-assistant-demo/eval/qual/audit.json'
make -C evals eval-validation SKILL=skills/otel-instrument EVAL_PATTERN='python/ai-assistant-demo/eval/qual/instrument.json'
```

This lets the example act as a before/after eval fixture: the baseline should
show gaps, and the instrumented version should satisfy the rubric signal
criteria.
