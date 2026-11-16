# connect-splunk-observability-cloud Rubric Codex Eval Report

Evaluated source: `7db9a57ada23292c0047e9d5cac24fbf0208847b`. Case outcomes: 1 failed, 3 passed. These are the saved run's results; no actor or judge was rerun for this publication.

Rubric grades are available for **4 of 4 prompts**. Case outcomes also include execution and workflow checks; they are not a count of checklist items.

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | connect-splunk-observability-cloud |
| Run ID | 20261116T170554Z-consolidated-report |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 8 |
| Config | evals/codex-evals.logging.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | Case outcomes | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/connect-splunk-observability-cloud | plugins/obstudio | 4 | 1 failed, 3 passed | 98% (43/44), avg score 99 | 121.3K | 3.8m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/connect-splunk-observability-cloud | plugins/obstudio | with_skill | codex | cumulative | measured | 4/4 recognized | 119699 | 63232 | 0 | 1627 | 639 | unknown | 121326 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/connect-splunk-observability-cloud | plugins/obstudio | with_skill | codex | cumulative | measured | 4/4 recognized | 130101 | 61440 | 0 | 4485 | 841 | unknown | 134586 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | plugins/obstudio | with_skill | newly-ready-organization-browser | rubric:rubric-1 FAIL | Assumed endpoints.rest is http://127.0.0.1:17900; no 0.0.0.0-to-127.0.0.1 normalization is modeled. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
