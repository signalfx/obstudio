# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261007T182853866125Z |
| Agent model | gpt-6-sol |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | node/express-basic/qual/instrument | node/express-basic | 1 | 80% (8/10), avg score 82 | 4.3M | 20.6m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | node/express-basic/qual/instrument | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 4290806 | 4165760 | 0 | 42215 | 25307 | unknown | 4333021 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | node/express-basic/qual/instrument | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 323773 | 278912 | 0 | 11132 | 8274 | unknown | 334905 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | node/express-basic | with_skill | direct | rubric:rubric-5 FAIL | service/instrumentation.js returns empty processors/instrumentations for any non-otlp `OTEL_LOGS_EXPORTER`, then always passes `logRecordProcessors: logs.processors` to NodeSDK. |
| with_skill | node/express-basic | with_skill | direct | rubric:rubric-9 FAIL | service/app.js calls `server.close()`, emits `runtime shutdown completed`, then calls memoized `shutdownTelemetry()`, but there is no timeout guard or `process.exit` fallback for stalled drain/export work. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
