# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261030T205410018659Z |
| Agent model | gpt-6-luna |
| Judge model | gpt-6-luna |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-name-inputs-audit | python/ai-assistant-demo | 1 | 83% (5/6), avg score 97 | 438.5K | 3.6m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/finding-group-audit | python/ai-assistant-demo | 1 | 100% (6/6), avg score 93 | 322.0K | 4.4m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-name-inputs-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 431206 | 373760 | 0 | 7249 | 1044 | unknown | 438455 |
| with_skill | python/ai-assistant-demo/qual/finding-group-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 312695 | 258176 | 0 | 9286 | 2091 | unknown | 321981 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-name-inputs-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 240615 | 193280 | 0 | 2813 | 1547 | unknown | 243428 |
| with_skill | python/ai-assistant-demo/qual/finding-group-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 182826 | 132864 | 0 | 3472 | 1986 | unknown | 186298 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/ai-assistant-demo | with_skill | ao-name-inputs-audit | rubric:rubric-5 FAIL | Case H in ao-name-input-review.md describes compatibility without an example using --ao-project-id project-123 with --ao-agent-stream checkout-stream; case H in .json also omits existing_cli_arguments. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
