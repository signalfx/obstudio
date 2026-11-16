# splunk-dashboard Rubric Codex Eval Report

Evaluated source: `7db9a57ada23292c0047e9d5cac24fbf0208847b`. Case outcomes: 1 passed. These are the saved run's results; no actor or judge was rerun for this publication.

Rubric grades are available for **1 of 1 prompts**. Case outcomes also include execution and workflow checks; they are not a count of checklist items.

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | splunk-dashboard |
| Run ID | 20261116T170554Z-consolidated-report |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 8 |
| Config | evals/codex-evals.logging.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | Case outcomes | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/qual/dashboard | dashboards/checkout-red | 1 | 1 passed | 100% (10/10), avg score 100 | 174.9K | 2.8m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/qual/dashboard | dashboards/checkout-red | with_skill | codex | cumulative | measured | 1/1 recognized | 170113 | 151808 | 0 | 4790 | 646 | unknown | 174903 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/qual/dashboard | dashboards/checkout-red | with_skill | codex | cumulative | measured | 1/1 recognized | 135951 | 114944 | 0 | 1842 | 87 | unknown | 137793 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
