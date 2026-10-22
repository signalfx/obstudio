# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20261022T004723285291Z |
| Agent model | gpt-6-sol |
| Judge model | gpt-6-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.security.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/model-directed-agent/qual/verify | python/model-directed-agent | 1 | 100% (4/4), avg score 97 | 1.6M | 4.7m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/model-directed-agent/qual/verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 1559589 | 1472640 | 0 | 10301 | 1368 | unknown | 1569890 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/model-directed-agent/qual/verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 304985 | 248320 | 0 | 1837 | 341 | unknown | 306822 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
