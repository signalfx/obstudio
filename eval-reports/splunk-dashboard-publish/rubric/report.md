# splunk-dashboard-publish Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | splunk-dashboard-publish |
| Run ID | 20260910T192514616166Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-sync/qual/dashboard-publish | dashboards/checkout-sync | 1 | 71% (5/7), avg score 82 | 211.9K | 5.1m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-sync/qual/dashboard-publish | dashboards/checkout-sync | with_skill | codex | cumulative | measured | 1/1 recognized | 205064 | 175744 | unknown | 6831 | 2299 | unknown | 211895 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-sync/qual/dashboard-publish | dashboards/checkout-sync | with_skill | codex | cumulative | measured | 1/1 recognized | 387938 | 316160 | unknown | 7295 | 4470 | unknown | 395233 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | dashboards/checkout-sync | with_skill | offline-plan | rubric:rubric-5 FAIL | last_message.md says no network calls and no Splunk create/update/delete calls, and names Splunk Observability Studio; no literal Confirm? (yes/no) or equivalent explicit yes/no gate appears. |
| with_skill | dashboards/checkout-sync | with_skill | offline-plan | rubric:rubric-7 FAIL | last_message.md describes POST /v2/dashboard with chartId values and placements, but contains no "tags": ["obstudio"] entry. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
