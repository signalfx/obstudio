# otel-instrument Runtime Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | runtime |
| Skill | otel-instrument |
| Run ID | 20260929T012415104637Z-node-retry-merged |
| Agent model | gpt-5.5 |
| Runtime enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Runtime Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/runtime/instrument | go/chi-basic | 1 | 100% (1/1) | 9.7M | 19.5m | - | - | - |
| with_skill | go/chi-partial/runtime/instrument | go/chi-partial | 1 | 100% (1/1) | 3.0M | 11.5m | - | - | - |
| with_skill | go/kvstore/runtime/instrument | go/kvstore | 1 | 100% (2/2) | 8.2M | 18.4m | - | - | - |
| with_skill | python/fastapi-celery/runtime/instrument | python/fastapi-celery | 1 | 100% (1/1) | 2.7M | 9.9m | - | - | - |
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | 1 | 100% (2/2) | 2.3M | 9.4m | - | - | - |
| with_skill | node/express-basic/runtime/instrument | node/express-basic | 1 | 100% (2/2) | 2.4M | 10.3m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/runtime/instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 9635653 | 9393920 | 0 | 50791 | 19673 | unknown | 9686444 |
| with_skill | go/chi-partial/runtime/instrument | go/chi-partial | with_skill | codex | cumulative | measured | 1/1 recognized | 2982246 | 2830592 | 0 | 30763 | 11615 | unknown | 3013009 |
| with_skill | go/kvstore/runtime/instrument | go/kvstore | with_skill | codex | cumulative | measured | 1/1 recognized | 8179614 | 7958272 | 0 | 48340 | 17017 | unknown | 8227954 |
| with_skill | python/fastapi-celery/runtime/instrument | python/fastapi-celery | with_skill | codex | cumulative | measured | 1/1 recognized | 2679956 | 2541696 | 0 | 27817 | 11746 | unknown | 2707773 |
| with_skill | python/flask-basic/runtime/instrument | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2265851 | 2149888 | 0 | 25711 | 11196 | unknown | 2291562 |
| with_skill | node/express-basic/runtime/instrument | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2338870 | 2175744 | 0 | 25274 | 13589 | unknown | 2364144 |

## Runtime Failures

No runtime failures.

## Compose Evidence

Runtime failure evidence includes the relevant Docker Compose log tail in the failure table.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
