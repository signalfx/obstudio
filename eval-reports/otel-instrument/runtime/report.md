# otel-instrument Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Modes | ab |
| Eval kind | runtime |
| Skill | otel-instrument |
| Run ID | 20260428T195137546739Z |
| Agent model | gpt-5.5 |
| Runtime enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Validation

| Eval | Service | Prompts | Eval File | Deterministic Checks | Qualitative Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| python/fastapi-celery/instrument_runtime | python/fastapi-celery | 1 | evals/python/fastapi-celery/instrument_runtime_eval.json | 0 | 0 | 1 |

## Deterministic

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| ab | python/fastapi-celery/instrument_runtime | python/fastapi-celery | 1 | 100% (2/2) | 635.0K | 4.5m | 100% (3/3) | 377.5K | 1.8m |

### Deterministic Failures

No deterministic failures.

## Qualitative

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| ab | python/fastapi-celery/instrument_runtime | python/fastapi-celery | 1 | - | 635.0K | 4.5m | - | 377.5K | 1.8m |

### Qualitative Failures

No qualitative failures.

## Runtime

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| ab | python/fastapi-celery/instrument_runtime | python/fastapi-celery | 1 | 0% (0/1) | 635.0K | 4.5m | - | 377.5K | 1.8m |

### Runtime Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| ab | python/fastapi-celery | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: traffic request POST http://127.0.0.1:8000/orders returned 500, expected 201; codex-eval-observer-1777406124332 logs: Observability Studio (collector) Telemetry Explorer: http://0.0.0.0:3000 OTLP/HTTP receiver: http://0.0.0.0:4318 OTLP/gRPC receiver: 0.0.0.0:4317 MCP endpoint: http://0.0.0.0:30... |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
