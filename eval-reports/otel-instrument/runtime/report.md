# otel-instrument Runtime Codex Eval Report

Evaluated source: `7db9a57ada23292c0047e9d5cac24fbf0208847b`. Case outcomes: 2 failed, 4 passed. These are the saved run's results; no actor or judge was rerun for this publication.

Some skill or eval inputs have changed since this run. These results describe the source above, rather than the latest PR revision.

Separate follow-up checks passed for Flask (fresh generation at `41cf32db753fea721ffbfb090c6e96076dc6f8e3`) and Go kvstore (saved app from `7db9a57ada23292c0047e9d5cac24fbf0208847b`, replayed against the corrected warning-level assertion at `f66baa8c04a0c159d04e4969fbeed54b939bee9c`). Each passed telemetry and log opt-out checks. The original **4 passed / 2 failed** outcomes below are unchanged.

Local usernames in Docker log excerpts are redacted; the original logs remain in the local run artifacts.

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | runtime |
| Skill | otel-instrument |
| Run ID | 20261116T170554Z-consolidated-report |
| Agent model | gpt-6.1-sol |
| Runtime enabled | True |
| Workers | 8 |
| Config | evals/codex-evals.logging.toml |

## Runtime Summary

| Mode | Eval | Service | Prompts | Case outcomes | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/runtime/instrument | go/chi-basic | 1 | 1 passed | 100% (1/1) | 8.4M | 20.7m | - | - | - |
| with_skill | go/chi-partial/runtime/instrument | go/chi-partial | 1 | 1 passed | 100% (1/1) | 7.3M | 21.8m | - | - | - |
| with_skill | go/kvstore/runtime/instrument | go/kvstore | 1 | 1 failed | 50% (1/2) | 12.6M | 25.0m | - | - | - |
| with_skill | node/express-basic/runtime/instrument | node/express-basic | 1 | 1 passed | 100% (2/2) | 7.1M | 16.3m | - | - | - |
| with_skill | python/fastapi-celery/runtime/instrument | python/fastapi-celery | 1 | 1 passed | 100% (1/1) | 7.4M | 18.5m | - | - | - |
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | 1 | 1 failed | 50% (1/2) | 7.4M | 18.3m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/runtime/instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 8384436 | 8232192 | 0 | 50812 | 15949 | unknown | 8435248 |
| with_skill | go/chi-partial/runtime/instrument | go/chi-partial | with_skill | codex | cumulative | measured | 1/1 recognized | 7247464 | 7095680 | 0 | 53467 | 15194 | unknown | 7300931 |
| with_skill | go/kvstore/runtime/instrument | go/kvstore | with_skill | codex | cumulative | measured | 1/1 recognized | 12550463 | 12353024 | 0 | 57460 | 18762 | unknown | 12607923 |
| with_skill | node/express-basic/runtime/instrument | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 7075541 | 6901888 | 0 | 37453 | 11074 | unknown | 7112994 |
| with_skill | python/fastapi-celery/runtime/instrument | python/fastapi-celery | with_skill | codex | cumulative | measured | 1/1 recognized | 7305700 | 7147136 | 0 | 45777 | 13633 | unknown | 7351477 |
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 7362310 | 7206784 | 0 | 45558 | 14169 | unknown | 7407868 |

## Runtime Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/kvstore | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | logs/request-context-logs record 0 expected severityText to contain 'WARN', got <missing>; logs/request-context-logs record 1 expected severityText to contain 'WARN', got <missing>; logs/request-context-logs record 2 expected severityText to contain 'WARN', got <missing>; logs/shutdown-log record 0 expected severity... |
| with_skill | python/flask-basic | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | logs/request-context-log expected 1 matching records, got 0; logs/shutdown-log expected 1 matching records, got 0; preserved-application-sink preserved service log output; compose logs: app-1 \| warning: Ignoring existing virtual environment linked to non-existent Python interpreter: `.venv/bin/python` -> `<user-home... |

## Compose Evidence

Runtime failure evidence includes the relevant Docker Compose log tail in the failure table.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
