# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261109T045620782361Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 4 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-audit-contract | go/chi-basic | 1 | 100% (11/11), avg score 100 | 2.1M | 13.6m | - | - | - |
| with_skill | java/springboot-basic/qual/logging-audit-contract | java/springboot-basic | 1 | 100% (11/11), avg score 100 | 1.4M | 10.2m | - | - | - |
| with_skill | node/express-basic/qual/logging-audit-contract | node/express-basic | 1 | 100% (11/11), avg score 100 | 1.4M | 14.3m | - | - | - |
| with_skill | python/flask-basic/qual/logging-audit-contract | python/flask-basic | 1 | 100% (11/11), avg score 100 | 1.9M | 13.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-audit-contract | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2077047 | 1975040 | 0 | 34944 | 5472 | unknown | 2111991 |
| with_skill | java/springboot-basic/qual/logging-audit-contract | java/springboot-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1403404 | 1304320 | 0 | 24735 | 4814 | unknown | 1428139 |
| with_skill | node/express-basic/qual/logging-audit-contract | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1332414 | 1230592 | 0 | 36599 | 8444 | unknown | 1369013 |
| with_skill | python/flask-basic/qual/logging-audit-contract | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1850584 | 1739136 | 0 | 32978 | 6467 | unknown | 1883562 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-audit-contract | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 711583 | 622080 | 0 | 3289 | 453 | unknown | 714872 |
| with_skill | java/springboot-basic/qual/logging-audit-contract | java/springboot-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 796874 | 701952 | 0 | 3545 | 513 | unknown | 800419 |
| with_skill | node/express-basic/qual/logging-audit-contract | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1209289 | 1100544 | 0 | 3742 | 723 | unknown | 1213031 |
| with_skill | python/flask-basic/qual/logging-audit-contract | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 889762 | 791040 | 0 | 3923 | 722 | unknown | 893685 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
