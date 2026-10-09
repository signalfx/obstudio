# AI Assistant Demo

Small FastAPI service that mimics the observability surfaces of an AI assistant:
chat turns, streaming responses, provider calls, tool fanout, context pressure,
and offline feedback export.

The interactive `app.py` is intentionally a baseline fixture. It has realistic
code paths but no custom OpenTelemetry instrumentation or Splunk Agent
Observability runtime route. Use it to demonstrate the before/after effect of
the OTel skills.

`eval_runner.py` is a separate offline evaluation process. It resolves an
evaluation project, resolves or creates its dedicated `offline-evaluations`
Agent Stream, publishes a synthetic trace directly through the supported
Splunk AO SDK, and terminates its logger. It never imports `app.py`, and the
FastAPI app never imports it. Evaluation routing therefore does not provide a
project binding, dedicated live stream, or direct export for interactive chat.
No live application target is selected in this baseline; adoption configuration
must be distinguished from already-covered evaluation configuration.

The evaluation runner is optional and requires an authorized account with an
existing project and SDK credentials supplied outside tracked files:

```sh
SPLUNK_AO_EVAL_PROJECT=your-evaluation-project uv run --extra evaluation python eval_runner.py
```

This command may create the dedicated evaluation stream and send synthetic
data. It is not part of ordinary fixture validation, which uses fake SDK
boundaries without credentials or network calls.

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
