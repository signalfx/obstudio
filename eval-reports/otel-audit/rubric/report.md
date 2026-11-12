# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261112T013449574286Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-audit-contract | python/flask-basic | 1 | 86% (12/14), avg score 92 | 4.1M | 19.9m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-audit-contract | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 4075399 | 3917824 | 0 | 24505 | 4111 | unknown | 4099904 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-audit-contract | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1523152 | 1404032 | 0 | 9163 | 4917 | unknown | 1532315 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-2 FAIL | OTEL-002.expected_telemetry includes canonical context for 'runtime request completed'; logs.records checks its body, severity, counts and Resource, while logs.async.join and logs.context.exact target app.py:38-43. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-5 FAIL | logs.async.join independently observes each workflow log-call context; http.create_task.success asserts the POST span but never joins 'runtime request completed' to it. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
