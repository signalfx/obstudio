# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261108T145455476696Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-audit-contract | go/chi-basic | 3 | 100% (21/21), avg score 98 | 1.8M | 11.8m | - | - | - |
| with_skill | java/springboot-basic/qual/logging-audit-contract | java/springboot-basic | 3 | 100% (21/21), avg score 98 | 1.7M | 10.8m | - | - | - |
| with_skill | node/express-basic/qual/logging-audit-contract | node/express-basic | 3 | 100% (21/21), avg score 99 | 1.9M | 11.4m | - | - | - |
| with_skill | python/flask-basic/qual/logging-audit-contract | python/flask-basic | 3 | 100% (21/21), avg score 100 | 2.0M | 11.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-audit-contract | go/chi-basic | with_skill | codex | cumulative | measured | 3/3 recognized | 1810164 | 1630848 | 0 | 23714 | 7701 | unknown | 1833878 |
| with_skill | java/springboot-basic/qual/logging-audit-contract | java/springboot-basic | with_skill | codex | cumulative | measured | 3/3 recognized | 1685463 | 1456000 | 0 | 20224 | 5868 | unknown | 1705687 |
| with_skill | node/express-basic/qual/logging-audit-contract | node/express-basic | with_skill | codex | cumulative | measured | 3/3 recognized | 1905052 | 1722880 | 0 | 21178 | 5416 | unknown | 1926230 |
| with_skill | python/flask-basic/qual/logging-audit-contract | python/flask-basic | with_skill | codex | cumulative | measured | 3/3 recognized | 1988974 | 1816960 | 0 | 22105 | 5241 | unknown | 2011079 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-audit-contract | go/chi-basic | with_skill | codex | cumulative | measured | 3/3 recognized | 991363 | 816128 | 0 | 7342 | 1857 | unknown | 998705 |
| with_skill | java/springboot-basic/qual/logging-audit-contract | java/springboot-basic | with_skill | codex | cumulative | measured | 3/3 recognized | 1043980 | 855424 | 0 | 7288 | 1756 | unknown | 1051268 |
| with_skill | node/express-basic/qual/logging-audit-contract | node/express-basic | with_skill | codex | cumulative | measured | 3/3 recognized | 972551 | 776960 | 0 | 6073 | 1401 | unknown | 978624 |
| with_skill | python/flask-basic/qual/logging-audit-contract | python/flask-basic | with_skill | codex | cumulative | measured | 3/3 recognized | 972454 | 804864 | 0 | 6522 | 1365 | unknown | 978976 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
