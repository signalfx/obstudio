# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20261030T205410039146Z |
| Agent model | gpt-6-luna |
| Judge model | gpt-6-luna |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-name-inputs-verify | python/ai-assistant-demo | 1 | 83% (5/6), avg score 96 | 1.0M | 5.1m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/finding-group-verify | python/ai-assistant-demo | 1 | 100% (6/6), avg score 97 | 509.6K | 4.1m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-name-inputs-verify | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1002789 | 923008 | 0 | 11470 | 2640 | unknown | 1014259 |
| with_skill | python/ai-assistant-demo/qual/finding-group-verify | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 501702 | 451968 | 0 | 7921 | 1482 | unknown | 509623 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-name-inputs-verify | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 207675 | 179072 | 0 | 2904 | 1684 | unknown | 210579 |
| with_skill | python/ai-assistant-demo/qual/finding-group-verify | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 256965 | 215552 | 0 | 3474 | 1741 | unknown | 260439 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/ai-assistant-demo | with_skill | ao-name-inputs-verify | rubric:rubric-6 FAIL | service/.observe/ao-name-input-review.md: cases H–I; companion JSON case H lacks a compatible_existing_cli_arguments entry. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
