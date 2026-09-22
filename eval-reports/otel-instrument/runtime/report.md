# otel-instrument Runtime Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | runtime |
| Skill | otel-instrument |
| Run ID | 20260922T164313195047Z |
| Agent model | gpt-5.5 |
| Runtime enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Runtime Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/runtime/instrument | go/chi-basic | 1 | 0% (0/1) | 2.7M | 10.2m | - | - | - |
| with_skill | go/chi-partial/runtime/instrument | go/chi-partial | 1 | 0% (0/1) | 4.2M | 10.6m | - | - | - |
| with_skill | go/kvstore/runtime/instrument | go/kvstore | 1 | 50% (1/2) | 3.7M | 17.0m | - | - | - |
| with_skill | node/express-basic/runtime/instrument | node/express-basic | 1 | 0% (0/2) | 1.6M | 14.1m | - | - | - |
| with_skill | python/fastapi-celery/runtime/instrument | python/fastapi-celery | 1 | 100% (1/1) | 2.4M | 10.9m | - | - | - |
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | 1 | 50% (1/2) | 1.2M | 12.7m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/runtime/instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2628672 | 2482944 | 0 | 30402 | 13049 | unknown | 2659074 |
| with_skill | go/chi-partial/runtime/instrument | go/chi-partial | with_skill | codex | cumulative | measured | 1/1 recognized | 4135293 | 3906816 | 0 | 31354 | 11282 | unknown | 4166647 |
| with_skill | go/kvstore/runtime/instrument | go/kvstore | with_skill | codex | cumulative | measured | 1/1 recognized | 3628414 | 3443840 | 0 | 33315 | 13427 | unknown | 3661729 |
| with_skill | node/express-basic/runtime/instrument | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1584846 | 1481600 | 0 | 23170 | 12083 | unknown | 1608016 |
| with_skill | python/fastapi-celery/runtime/instrument | python/fastapi-celery | with_skill | codex | cumulative | measured | 1/1 recognized | 2385204 | 2257024 | 0 | 31487 | 15221 | unknown | 2416691 |
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1172985 | 1074176 | 0 | 20737 | 9946 | unknown | 1193722 |

## Runtime Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: docker compose -p codex-eval-87f876ba933e -f /Users/yluther/Documents/born/obstudio/evals/go/chi-basic/eval/runtime/docker-compose.yml up -d --build exited 1: Compose can now delegate builds to bake for better performance. To do so, set COMPOSE_BAKE=true. #0 building with "desktop-linux" instan... |
| with_skill | go/chi-partial | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: docker compose -p codex-eval-6740cbf40470 -f /Users/yluther/Documents/born/obstudio/evals/go/chi-partial/eval/runtime/docker-compose.yml up -d --build exited 1: Compose can now delegate builds to bake for better performance. To do so, set COMPOSE_BAKE=true. #0 building with "desktop-linux" inst... |
| with_skill | go/kvstore | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: command timed out after 300s: docker compose -p codex-eval-25462558db43 -f /Users/yluther/Documents/born/obstudio/evals/go/kvstore/eval/runtime/docker-compose.yml --profile traffic run --rm traffic; compose logs: observer-1 \| observer-1 \| Splunk Observability Studio (collector) observer-1 \| Tel... |
| with_skill | node/express-basic | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: command timed out after 300s: docker compose -p codex-eval-4ebf3b2cfb11 -f /Users/yluther/Documents/born/obstudio/evals/node/express-basic/eval/runtime/docker-compose.yml --profile traffic run --rm traffic; compose logs: app-1 \| app-1 \| > node-express-basic@0.1.0 dev app-1 \| > node --require ./... |
| with_skill | node/express-basic | with_skill | runtime-preserving | runtime:observer-runtime-logs-opt-out FAIL | Runtime check failed: app did not stop gracefully: state=exited, exit_code=1; compose logs: observer-1 \| observer-1 \| Splunk Observability Studio (collector) observer-1 \| Telemetry Explorer: http://127.0.0.1:3000 observer-1 \| OTLP/HTTP receiver: http://0.0.0.0:4318 observer-1 \| OTLP/gRPC receiver: 127.0.0.1:4317 obs... |
| with_skill | python/flask-basic | with_skill | runtime-preserving | runtime:observer-runtime-telemetry FAIL | Runtime check failed: command timed out after 300s: docker compose -p codex-eval-547ffeffb50e -f /Users/yluther/Documents/born/obstudio/evals/python/flask-basic/eval/runtime/docker-compose.yml --profile traffic run --rm traffic; compose logs: observer-1 \| observer-1 \| Splunk Observability Studio (collector) observer... |

## Compose Evidence

Runtime failure evidence includes the relevant Docker Compose log tail in the failure table.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
