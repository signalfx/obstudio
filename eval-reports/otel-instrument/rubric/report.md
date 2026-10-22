# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261022T004108862497Z |
| Agent model | gpt-6-sol |
| Judge model | gpt-6-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.security.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | 1 | 100% (4/4), avg score 96 | 3.8M | 6.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 3754675 | 3641344 | 0 | 12425 | 1519 | unknown | 3767100 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 842759 | 759168 | 0 | 2330 | 542 | unknown | 845089 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
