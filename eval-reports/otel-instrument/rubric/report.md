# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261108T145455476696Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-instrument-contract | go/chi-basic | 3 | 100% (21/21), avg score 99 | 1.9M | 11.3m | - | - | - |
| with_skill | java/springboot-basic/qual/logging-instrument-contract | java/springboot-basic | 3 | 100% (21/21), avg score 97 | 2.3M | 13.0m | - | - | - |
| with_skill | node/express-basic/qual/logging-instrument-contract | node/express-basic | 3 | 100% (21/21), avg score 98 | 1.6M | 10.3m | - | - | - |
| with_skill | python/flask-basic/qual/logging-instrument-contract | python/flask-basic | 3 | 100% (21/21), avg score 100 | 2.0M | 9.8m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-instrument-contract | go/chi-basic | with_skill | codex | cumulative | measured | 3/3 recognized | 1851277 | 1594496 | 0 | 22324 | 6741 | unknown | 1873601 |
| with_skill | java/springboot-basic/qual/logging-instrument-contract | java/springboot-basic | with_skill | codex | cumulative | measured | 3/3 recognized | 2268928 | 2059904 | 0 | 26506 | 9572 | unknown | 2295434 |
| with_skill | node/express-basic/qual/logging-instrument-contract | node/express-basic | with_skill | codex | cumulative | measured | 3/3 recognized | 1617785 | 1429120 | 0 | 19729 | 5180 | unknown | 1637514 |
| with_skill | python/flask-basic/qual/logging-instrument-contract | python/flask-basic | with_skill | codex | cumulative | measured | 3/3 recognized | 1952515 | 1735296 | 0 | 18788 | 4452 | unknown | 1971303 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-instrument-contract | go/chi-basic | with_skill | codex | cumulative | measured | 3/3 recognized | 1147624 | 937984 | 0 | 6576 | 1220 | unknown | 1154200 |
| with_skill | java/springboot-basic/qual/logging-instrument-contract | java/springboot-basic | with_skill | codex | cumulative | measured | 3/3 recognized | 1311914 | 1099264 | 0 | 7482 | 2117 | unknown | 1319396 |
| with_skill | node/express-basic/qual/logging-instrument-contract | node/express-basic | with_skill | codex | cumulative | measured | 3/3 recognized | 1165941 | 964096 | 0 | 6668 | 1453 | unknown | 1172609 |
| with_skill | python/flask-basic/qual/logging-instrument-contract | python/flask-basic | with_skill | codex | cumulative | measured | 3/3 recognized | 834251 | 638336 | 0 | 5795 | 1481 | unknown | 840046 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
