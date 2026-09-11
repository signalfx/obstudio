# otel-instrument Runtime Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | runtime |
| Skill | otel-instrument |
| Run ID | 20260910T172151341955Z |
| Agent model | gpt-5.5 |
| Runtime enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.token-benchmark-network.toml |

## Runtime Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/runtime/instrument | go/chi-basic | 1 | 100% (1/1) | 2.7M | 12.0m | - | - | - |
| with_skill | go/chi-partial/runtime/instrument | go/chi-partial | 1 | 100% (1/1) | 3.0M | 15.5m | - | - | - |
| with_skill | go/kvstore/runtime/instrument | go/kvstore | 1 | 100% (2/2) | 3.8M | 14.9m | - | - | - |
| with_skill | node/express-basic/runtime/instrument | node/express-basic | 1 | 100% (2/2) | 8.1M | 16.9m | - | - | - |
| with_skill | python/fastapi-celery/runtime/instrument | python/fastapi-celery | 1 | 100% (1/1) | 2.7M | 15.4m | - | - | - |
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | 1 | 100% (2/2) | 1.6M | 10.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/runtime/instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2689244 | 2588160 | unknown | 27204 | 7432 | unknown | 2716448 |
| with_skill | go/chi-partial/runtime/instrument | go/chi-partial | with_skill | codex | cumulative | measured | 1/1 recognized | 2949042 | 2833536 | unknown | 37859 | 10576 | unknown | 2986901 |
| with_skill | go/kvstore/runtime/instrument | go/kvstore | with_skill | codex | cumulative | measured | 1/1 recognized | 3808109 | 3642240 | unknown | 30987 | 7677 | unknown | 3839096 |
| with_skill | node/express-basic/runtime/instrument | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 8088833 | 7852672 | unknown | 39842 | 10708 | unknown | 8128675 |
| with_skill | python/fastapi-celery/runtime/instrument | python/fastapi-celery | with_skill | codex | cumulative | measured | 1/1 recognized | 2670190 | 2558464 | unknown | 37896 | 11193 | unknown | 2708086 |
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1527201 | 1442176 | unknown | 25028 | 7476 | unknown | 1552229 |

## Runtime Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/flask-basic | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: command timed out after 300s: docker compose -p codex-eval-4426aa005dcf -f /private/tmp/obstudio-pr241-runtime-922d241/evals/python/flask-basic/eval/runtime/docker-compose.yml --profile traffic run --rm traffic; compose logs: app-1 \| Traceback (most recent call last): app-1 \| File "/app/.venv/b... |

## Compose Evidence

Runtime failure evidence includes the relevant Docker Compose log tail in the failure table.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
