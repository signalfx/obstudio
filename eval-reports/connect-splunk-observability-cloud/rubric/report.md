# connect-splunk-observability-cloud Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | connect-splunk-observability-cloud |
| Run ID | 20261016T185621158406Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/connect-splunk-observability-cloud | plugins/obstudio | 4 | 0% (0/4), avg score 0 | 139.4K | 2.0m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/connect-splunk-observability-cloud | plugins/obstudio | with_skill | codex | cumulative | measured | 4/4 recognized | 135846 | 92928 | 0 | 3522 | 2523 | unknown | 139368 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/connect-splunk-observability-cloud | plugins/obstudio | with_skill | codex | unknown | absent | 0/4 recognized; 0/4 observed | unknown | unknown | unknown | unknown | unknown | unknown | unknown |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | plugins/obstudio | with_skill | confirm-configuration | rubric:rubric-run FAIL | Reading additional input from stdin... |
| with_skill | plugins/obstudio | with_skill | existing-organization-browser | rubric:rubric-run FAIL | Reading additional input from stdin... |
| with_skill | plugins/obstudio | with_skill | newly-ready-organization-browser | rubric:rubric-run FAIL | Reading additional input from stdin... |
| with_skill | plugins/obstudio | with_skill | terminal-clickable-fallback | rubric:rubric-run FAIL | Reading additional input from stdin... |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
