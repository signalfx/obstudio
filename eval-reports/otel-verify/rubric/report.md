# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20261109T045620782348Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 4 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-verify-contract | go/chi-basic | 1 | 100% (11/11), avg score 100 | 2.0M | 10.9m | - | - | - |
| with_skill | java/springboot-basic/qual/logging-verify-contract | java/springboot-basic | 1 | 100% (11/11), avg score 100 | 1.4M | 10.9m | - | - | - |
| with_skill | node/express-basic/qual/logging-verify-contract | node/express-basic | 1 | 100% (11/11), avg score 100 | 1.1M | 10.0m | - | - | - |
| with_skill | python/flask-basic/qual/logging-verify-contract | python/flask-basic | 1 | 100% (11/11), avg score 100 | 1.5M | 11.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-verify-contract | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1992086 | 1892224 | 0 | 26528 | 5167 | unknown | 2018614 |
| with_skill | java/springboot-basic/qual/logging-verify-contract | java/springboot-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1417704 | 1315200 | 0 | 26638 | 3955 | unknown | 1444342 |
| with_skill | node/express-basic/qual/logging-verify-contract | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1114605 | 1025536 | 0 | 24200 | 3360 | unknown | 1138805 |
| with_skill | python/flask-basic/qual/logging-verify-contract | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1499483 | 1398784 | 0 | 27461 | 4082 | unknown | 1526944 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-verify-contract | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 742990 | 665344 | 0 | 3212 | 528 | unknown | 746202 |
| with_skill | java/springboot-basic/qual/logging-verify-contract | java/springboot-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 864177 | 775808 | 0 | 3603 | 669 | unknown | 867780 |
| with_skill | node/express-basic/qual/logging-verify-contract | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 836195 | 752384 | 0 | 3350 | 452 | unknown | 839545 |
| with_skill | python/flask-basic/qual/logging-verify-contract | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 712065 | 634496 | 0 | 3271 | 419 | unknown | 715336 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
