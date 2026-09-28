# otel-instrument Runtime Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | runtime |
| Skill | otel-instrument |
| Run ID | 20260928T212909279697Z |
| Agent model | gpt-5.5 |
| Runtime enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Runtime Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/runtime/instrument | go/chi-basic | 1 | 0% (0/1) | 2.8M | 9.0m | - | - | - |
| with_skill | go/chi-partial/runtime/instrument | go/chi-partial | 1 | 0% (0/1) | 2.2M | 10.9m | - | - | - |
| with_skill | go/kvstore/runtime/instrument | go/kvstore | 1 | 0% (0/2) | 1.4M | 8.5m | - | - | - |
| with_skill | node/express-basic/runtime/instrument | node/express-basic | 1 | 0% (0/2) | 1.5M | 9.5m | - | - | - |
| with_skill | python/fastapi-celery/runtime/instrument | python/fastapi-celery | 1 | 0% (0/1) | 3.1M | 11.8m | - | - | - |
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | 1 | 0% (0/2) | 2.9M | 12.6m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/runtime/instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2765500 | 2614272 | 0 | 27771 | 14201 | unknown | 2793271 |
| with_skill | go/chi-partial/runtime/instrument | go/chi-partial | with_skill | codex | cumulative | measured | 1/1 recognized | 2163278 | 2014080 | 0 | 25403 | 9598 | unknown | 2188681 |
| with_skill | go/kvstore/runtime/instrument | go/kvstore | with_skill | codex | cumulative | measured | 1/1 recognized | 1400731 | 1292032 | 0 | 26533 | 12608 | unknown | 1427264 |
| with_skill | node/express-basic/runtime/instrument | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1442072 | 1265024 | 0 | 25761 | 13405 | unknown | 1467833 |
| with_skill | python/fastapi-celery/runtime/instrument | python/fastapi-celery | with_skill | codex | cumulative | measured | 1/1 recognized | 3053915 | 2874368 | 0 | 37187 | 19302 | unknown | 3091102 |
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2914009 | 2789632 | 0 | 32689 | 16196 | unknown | 2946698 |

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
