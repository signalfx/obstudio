# otel-instrument Runtime Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | runtime |
| Skill | otel-instrument |
| Run ID | 20260429T185105710232Z |
| Agent model | gpt-5.5 |
| Runtime enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Runtime Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/runtime/instrument | go/chi-basic | 1 | 100% (1/1) | 2.1M | 4.9m | - | - | - |
| with_skill | go/chi-partial/runtime/instrument | go/chi-partial | 1 | 0% (0/1) | 759.7K | 3.8m | - | - | - |
| with_skill | go/kvstore/runtime/instrument | go/kvstore | 1 | 100% (1/1) | 963.5K | 4.6m | - | - | - |
| with_skill | node/express-basic/runtime/instrument | node/express-basic | 1 | 100% (1/1) | 442.5K | 3.2m | - | - | - |
| with_skill | python/fastapi-celery/runtime/instrument | python/fastapi-celery | 1 | 100% (1/1) | 479.4K | 3.4m | - | - | - |
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | 1 | 100% (1/1) | 203.6K | 2.3m | - | - | - |

## Runtime Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-partial | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: docker compose -p codex-eval-4a2e0520ac72 -f /Users/pavankri/Cisco/obstudio/evals/go/chi-partial/eval/runtime/docker-compose.yml up -d --build exited 1: #1 [internal] load local bake definitions #1 reading from stdin 1.17kB done #1 DONE 0.0s #2 [app internal] load build definition from App.Dock... |

## Compose Evidence

Runtime failure evidence includes the relevant Docker Compose log tail in the failure table.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
