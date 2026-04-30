# otel-instrument Runtime Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | runtime |
| Skill | otel-instrument |
| Run ID | 20260430T170207539067Z |
| Agent model | gpt-5.5 |
| Runtime enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Runtime Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/runtime/instrument | go/chi-basic | 1 | 100% (1/1) | 3.2M | 6.1m | - | - | - |
| with_skill | go/chi-partial/runtime/instrument | go/chi-partial | 1 | 100% (1/1) | 1.1M | 4.6m | - | - | - |
| with_skill | go/kvstore/runtime/instrument | go/kvstore | 1 | 100% (1/1) | 1.7M | 5.1m | - | - | - |
| with_skill | node/express-basic/runtime/instrument | node/express-basic | 1 | 100% (1/1) | 415.6K | 4.6m | - | - | - |
| with_skill | python/fastapi-celery/runtime/instrument | python/fastapi-celery | 1 | 100% (1/1) | 616.7K | 3.9m | - | - | - |
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | 1 | 100% (1/1) | 490.4K | 2.9m | - | - | - |

## Runtime Failures

No runtime failures.

## Compose Evidence

Runtime failure evidence includes the relevant Docker Compose log tail in the failure table.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
