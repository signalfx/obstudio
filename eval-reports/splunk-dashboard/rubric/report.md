# splunk-dashboard Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | splunk-dashboard |
| Run ID | 20260918T180620896406Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/qual/dashboard | dashboards/checkout-red | 1 | 88% (7/8), avg score 88 | 368.9K | 5.7m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/qual/dashboard | dashboards/checkout-red | with_skill | codex | cumulative | measured | 1/1 recognized | 357376 | 321024 | 0 | 11511 | 4229 | unknown | 368887 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/qual/dashboard | dashboards/checkout-red | with_skill | codex | cumulative | measured | 1/1 recognized | 167670 | 113536 | 0 | 5058 | 2670 | unknown | 172728 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | dashboards/checkout-red | with_skill | generate | rubric:rubric-8 FAIL | trace.jsonl shows jq empty service/.observe/dashboards.preview.json, jq layout/unresolved-var checks, rg checks for sensitive/api_token/unresolved variables, and cmp for the audit copy; last_message.md says the output was verified locally. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
