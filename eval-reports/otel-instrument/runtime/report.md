# otel-instrument Runtime Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | runtime |
| Skill | otel-instrument |
| Run ID | 20260922T162220074029Z |
| Agent model | gpt-5.5 |
| Runtime enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Runtime Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | 1 | 0% (0/2) | 2.0M | 18.5m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1958339 | 1842176 | 0 | 24404 | 13353 | unknown | 1982743 |

## Runtime Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/flask-basic | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: command timed out after 300s: docker compose -p codex-eval-c3b73f748c5d -f /Users/bdrake/code/obstudio/evals/python/flask-basic/eval/runtime/docker-compose.yml up -d --build |
| with_skill | python/flask-basic | with_skill | runtime-preserving | runtime:observer-runtime-logs-opt-out FAIL | Runtime check failed: command timed out after 300s: docker compose -p codex-eval-38f09e55e81e -f /Users/bdrake/code/obstudio/evals/python/flask-basic/eval/runtime/docker-compose.yml up -d --build |

## Compose Evidence

Runtime failure evidence includes the relevant Docker Compose log tail in the failure table.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
