# otel-instrument Runtime Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | runtime |
| Skill | otel-instrument |
| Run ID | 20260923T204006546146Z |
| Agent model | gpt-5.5 |
| Runtime enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Runtime Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/runtime/instrument | go/chi-basic | 1 | 100% (1/1) | 5.0M | 12.1m | - | - | - |
| with_skill | go/chi-partial/runtime/instrument | go/chi-partial | 1 | 100% (1/1) | 4.8M | 12.0m | - | - | - |
| with_skill | go/kvstore/runtime/instrument | go/kvstore | 1 | 100% (2/2) | 11.4M | 18.3m | - | - | - |
| with_skill | node/express-basic/runtime/instrument | node/express-basic | 1 | 100% (2/2) | 2.0M | 10.1m | - | - | - |
| with_skill | python/fastapi-celery/runtime/instrument | python/fastapi-celery | 1 | 100% (1/1) | 2.3M | 10.6m | - | - | - |
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | 1 | 100% (2/2) | 3.3M | 9.5m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/runtime/instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 5013497 | 4647168 | 0 | 33305 | 17043 | unknown | 5046802 |
| with_skill | go/chi-partial/runtime/instrument | go/chi-partial | with_skill | codex | cumulative | measured | 1/1 recognized | 4742664 | 4495104 | 0 | 34013 | 16880 | unknown | 4776677 |
| with_skill | go/kvstore/runtime/instrument | go/kvstore | with_skill | codex | cumulative | measured | 1/1 recognized | 11354803 | 11120128 | 0 | 48358 | 17679 | unknown | 11403161 |
| with_skill | node/express-basic/runtime/instrument | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1982224 | 1871232 | 0 | 25288 | 12932 | unknown | 2007512 |
| with_skill | python/fastapi-celery/runtime/instrument | python/fastapi-celery | with_skill | codex | cumulative | measured | 1/1 recognized | 2316056 | 2198272 | 0 | 31652 | 14882 | unknown | 2347708 |
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 3227310 | 3107712 | 0 | 25998 | 14269 | unknown | 3253308 |

## Runtime Failures

No runtime failures.

## Compose Evidence

Runtime failure evidence includes the relevant Docker Compose log tail in the failure table.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
