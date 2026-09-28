# otel-instrument Runtime Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | runtime |
| Skill | otel-instrument |
| Run ID | 20260928T233429535772Z |
| Agent model | gpt-5.5 |
| Runtime enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Runtime Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/runtime/instrument | go/chi-basic | 1 | 0% (0/1) | 1.3M | 8.2m | - | - | - |
| with_skill | go/chi-partial/runtime/instrument | go/chi-partial | 1 | 0% (0/1) | 4.3M | 10.7m | - | - | - |
| with_skill | go/kvstore/runtime/instrument | go/kvstore | 1 | 0% (0/2) | 1.8M | 8.8m | - | - | - |
| with_skill | node/express-basic/runtime/instrument | node/express-basic | 1 | 0% (0/2) | 2.0M | 8.7m | - | - | - |
| with_skill | python/fastapi-celery/runtime/instrument | python/fastapi-celery | 1 | 0% (0/1) | 2.3M | 9.0m | - | - | - |
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | 1 | 0% (0/2) | 2.3M | 8.4m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/runtime/instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1256061 | 1143808 | 0 | 25556 | 13379 | unknown | 1281617 |
| with_skill | go/chi-partial/runtime/instrument | go/chi-partial | with_skill | codex | cumulative | measured | 1/1 recognized | 4248707 | 3956224 | 0 | 32130 | 13784 | unknown | 4280837 |
| with_skill | go/kvstore/runtime/instrument | go/kvstore | with_skill | codex | cumulative | measured | 1/1 recognized | 1758624 | 1611136 | 0 | 27834 | 11613 | unknown | 1786458 |
| with_skill | node/express-basic/runtime/instrument | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1985997 | 1874944 | 0 | 25018 | 13128 | unknown | 2011015 |
| with_skill | python/fastapi-celery/runtime/instrument | python/fastapi-celery | with_skill | codex | cumulative | measured | 1/1 recognized | 2282914 | 2162304 | 0 | 27660 | 11312 | unknown | 2310574 |
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2313647 | 2198272 | 0 | 24906 | 11027 | unknown | 2338553 |

## Runtime Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: command executable not found: docker |
| with_skill | go/chi-partial | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: command executable not found: docker |
| with_skill | go/kvstore | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: command executable not found: docker |
| with_skill | go/kvstore | with_skill | runtime-preserving | runtime:observer-runtime-logs-opt-out FAIL | Runtime check failed: command executable not found: docker |
| with_skill | node/express-basic | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: command executable not found: docker |
| with_skill | node/express-basic | with_skill | runtime-preserving | runtime:observer-runtime-logs-opt-out FAIL | Runtime check failed: command executable not found: docker |
| with_skill | python/fastapi-celery | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: command executable not found: docker |
| with_skill | python/flask-basic | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: command executable not found: docker |
| with_skill | python/flask-basic | with_skill | runtime-preserving | runtime:observer-runtime-logs-opt-out FAIL | Runtime check failed: command executable not found: docker |

## Compose Evidence

Runtime failure evidence includes the relevant Docker Compose log tail in the failure table.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
