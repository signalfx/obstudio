# connect-splunk-observability-cloud Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | connect-splunk-observability-cloud |
| Run ID | 20260918T171835422424Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/connect-splunk-observability-cloud | plugins/obstudio | 4 | 98% (39/40), avg score 98 | 160.9K | 5.3m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/connect-splunk-observability-cloud | plugins/obstudio | with_skill | codex | cumulative | measured | 4/4 recognized | 157304 | 96256 | 0 | 3558 | 2704 | unknown | 160862 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/connect-splunk-observability-cloud | plugins/obstudio | with_skill | codex | cumulative | measured | 4/4 recognized | 148093 | 86016 | 0 | 9951 | 6450 | unknown | 158044 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | plugins/obstudio | with_skill | confirm-configuration | rubric:rubric-7 FAIL | Final response: `current running standalone process`; no restart persistence warning is present. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
