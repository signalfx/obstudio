# otel-instrument Runtime Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | runtime |
| Skill | otel-instrument |
| Run ID | 20260911T043511367063Z |
| Agent model | gpt-5.5 |
| Runtime enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Runtime Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | 1 | 50% (1/2) | 5.3M | 25.4m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 5223511 | 5047936 | unknown | 51883 | 23615 | unknown | 5275394 |

## Runtime Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/flask-basic | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: command timed out after 300s: docker compose -p codex-eval-4426aa005dcf -f /private/tmp/obstudio-pr241-runtime-922d241/evals/python/flask-basic/eval/runtime/docker-compose.yml --profile traffic run --rm traffic; compose logs: app-1 \| Traceback (most recent call last): app-1 \| File "/app/.venv/b... |

## Compose Evidence

Runtime failure evidence includes the relevant Docker Compose log tail in the failure table.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
