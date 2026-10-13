# splunk-configure Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | splunk-configure |
| Run ID | 20261013T201433786506Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-target-handoff-configure | python/ai-assistant-demo | 1 | 100% (3/3), avg score 98 | 1.6M | 12.3m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-target-handoff-configure | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1598233 | 1424256 | 0 | 17950 | 3581 | unknown | 1616183 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-target-handoff-configure | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1825224 | 1729408 | 0 | 9906 | 3048 | unknown | 1835130 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
