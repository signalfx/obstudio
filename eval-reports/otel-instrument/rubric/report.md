# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261109T045620782407Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 4 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-instrument-contract | go/chi-basic | 1 | 100% (11/11), avg score 100 | 1.9M | 11.5m | - | - | - |
| with_skill | java/springboot-basic/qual/logging-instrument-contract | java/springboot-basic | 1 | 100% (11/11), avg score 100 | 1.7M | 10.9m | - | - | - |
| with_skill | node/express-basic/qual/logging-instrument-contract | node/express-basic | 1 | 100% (11/11), avg score 100 | 1.7M | 11.0m | - | - | - |
| with_skill | python/flask-basic/qual/logging-instrument-contract | python/flask-basic | 1 | 100% (11/11), avg score 100 | 1.7M | 11.3m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-instrument-contract | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1826142 | 1709312 | 0 | 28480 | 5161 | unknown | 1854622 |
| with_skill | java/springboot-basic/qual/logging-instrument-contract | java/springboot-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1690051 | 1572608 | 0 | 26702 | 4327 | unknown | 1716753 |
| with_skill | node/express-basic/qual/logging-instrument-contract | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1723527 | 1614464 | 0 | 26380 | 2499 | unknown | 1749907 |
| with_skill | python/flask-basic/qual/logging-instrument-contract | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1685206 | 1581952 | 0 | 28567 | 2797 | unknown | 1713773 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-instrument-contract | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 855979 | 757248 | 0 | 2774 | 274 | unknown | 858753 |
| with_skill | java/springboot-basic/qual/logging-instrument-contract | java/springboot-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 885191 | 774656 | 0 | 3661 | 847 | unknown | 888852 |
| with_skill | node/express-basic/qual/logging-instrument-contract | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1046378 | 958336 | 0 | 3313 | 579 | unknown | 1049691 |
| with_skill | python/flask-basic/qual/logging-instrument-contract | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 559444 | 476800 | 0 | 2552 | 351 | unknown | 561996 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
