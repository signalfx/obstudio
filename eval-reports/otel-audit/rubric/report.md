# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261105T162044599867Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-name-inputs-audit | python/ai-assistant-demo | 1 | 100% (6/6), avg score 100 | 1.1M | 7.5m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/finding-group-audit | python/ai-assistant-demo | 1 | 100% (7/7), avg score 100 | 823.1K | 5.4m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-name-inputs-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1131270 | 1015808 | 0 | 13615 | 1282 | unknown | 1144885 |
| with_skill | python/ai-assistant-demo/qual/finding-group-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 811617 | 740480 | 0 | 11487 | 1615 | unknown | 823104 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-name-inputs-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 149029 | 107136 | 0 | 1670 | 207 | unknown | 150699 |
| with_skill | python/ai-assistant-demo/qual/finding-group-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 254214 | 199040 | 0 | 2577 | 291 | unknown | 256791 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
