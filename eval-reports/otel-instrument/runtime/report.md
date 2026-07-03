# otel-instrument Runtime Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | runtime |
| Skill | otel-instrument |
| Run ID | 20260703T070947771518Z |
| Agent model | gpt-5.5 |
| Runtime enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Runtime Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/runtime/instrument | go/chi-basic | 1 | 0% (0/1) | 1.8M | 5.3m | - | - | - |
| with_skill | go/chi-partial/runtime/instrument | go/chi-partial | 1 | 0% (0/1) | 2.0M | 5.8m | - | - | - |
| with_skill | go/kvstore/runtime/instrument | go/kvstore | 1 | 0% (0/1) | 2.8M | 8.1m | - | - | - |
| with_skill | node/express-basic/runtime/instrument | node/express-basic | 1 | 0% (0/1) | 898.2K | 6.7m | - | - | - |
| with_skill | python/fastapi-celery/runtime/instrument | python/fastapi-celery | 1 | 0% (0/1) | 778.1K | 5.3m | - | - | - |
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | 1 | 0% (0/1) | 909.4K | 4.8m | - | - | - |

## Runtime Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: docker compose -p codex-eval-fa1d834fab90 -f /Users/btiwana/obstudio/evals/go/chi-basic/eval/runtime/docker-compose.yml up -d --build exited 125: unknown shorthand flag: 'p' in -p Usage: docker [OPTIONS] COMMAND [ARG...] Run 'docker --help' for more information; compose logs: unknown shorthand ... |
| with_skill | go/chi-partial | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: docker compose -p codex-eval-fda0f6c07909 -f /Users/btiwana/obstudio/evals/go/chi-partial/eval/runtime/docker-compose.yml up -d --build exited 125: unknown shorthand flag: 'p' in -p Usage: docker [OPTIONS] COMMAND [ARG...] Run 'docker --help' for more information; compose logs: unknown shorthan... |
| with_skill | go/kvstore | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: docker compose -p codex-eval-e301479ca1f3 -f /Users/btiwana/obstudio/evals/go/kvstore/eval/runtime/docker-compose.yml up -d --build exited 125: unknown shorthand flag: 'p' in -p Usage: docker [OPTIONS] COMMAND [ARG...] Run 'docker --help' for more information; compose logs: unknown shorthand fl... |
| with_skill | node/express-basic | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: docker compose -p codex-eval-9cb9bedba866 -f /Users/btiwana/obstudio/evals/node/express-basic/eval/runtime/docker-compose.yml up -d --build exited 125: unknown shorthand flag: 'p' in -p Usage: docker [OPTIONS] COMMAND [ARG...] Run 'docker --help' for more information; compose logs: unknown shor... |
| with_skill | python/fastapi-celery | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: docker compose -p codex-eval-d1f09e4b9234 -f /Users/btiwana/obstudio/evals/python/fastapi-celery/eval/runtime/docker-compose.yml up -d --build exited 125: unknown shorthand flag: 'p' in -p Usage: docker [OPTIONS] COMMAND [ARG...] Run 'docker --help' for more information; compose logs: unknown s... |
| with_skill | python/flask-basic | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: docker compose -p codex-eval-7c54f3f1ad45 -f /Users/btiwana/obstudio/evals/python/flask-basic/eval/runtime/docker-compose.yml up -d --build exited 125: unknown shorthand flag: 'p' in -p Usage: docker [OPTIONS] COMMAND [ARG...] Run 'docker --help' for more information; compose logs: unknown shor... |

## Compose Evidence

Runtime failure evidence includes the relevant Docker Compose log tail in the failure table.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
