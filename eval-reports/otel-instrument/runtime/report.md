# otel-instrument Runtime Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | runtime |
| Skill | otel-instrument |
| Run ID | 20260910T204659732550Z |
| Agent model | gpt-5.5 |
| Runtime enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Runtime Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | 1 | 0% (0/2) | 6.4M | 17.3m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 6353762 | 6189696 | unknown | 37838 | 12556 | unknown | 6391600 |

## Runtime Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/flask-basic | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: HTTP Error 403: Forbidden; compose logs: observer-1 \| 2026/09/10 21:03:46 failed to write shared service state: create parent directory for "/home/obstudio/.obstudio/shared-observer.json": mkdir /home/obstudio/.obstudio: no space left on device observer-1 \| observer-1 \| Observability Studio (co... |
| with_skill | python/flask-basic | with_skill | runtime-preserving | runtime:observer-runtime-logs-opt-out FAIL | Runtime check failed: HTTP Error 403: Forbidden; compose logs: app-1 \| warning: Ignoring existing virtual environment linked to non-existent Python interpreter: .venv/bin/python3 -> python app-1 \| Using CPython 3.12.14 interpreter at: /usr/local/bin/python3 observer-1 \| 2026/09/10 21:04:01 failed to write shared ser... |

## Compose Evidence

Runtime failure evidence includes the relevant Docker Compose log tail in the failure table.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
