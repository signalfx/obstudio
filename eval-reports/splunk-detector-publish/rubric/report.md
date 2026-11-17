# splunk-detector-publish Rubric Codex Eval Report

Evaluated source: `7db9a57ada23292c0047e9d5cac24fbf0208847b`. Case outcomes: 1 passed. These are the saved run's results; no actor or judge was rerun for this publication.

Rubric grades are available for **1 of 1 prompts**. Case outcomes also include execution and workflow checks; they are not a count of checklist items.

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | splunk-detector-publish |
| Run ID | 20261116T170554Z-consolidated-report |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 8 |
| Config | evals/codex-evals.logging.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | Case outcomes | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-detectors/qual/detector-publish | dashboards/checkout-detectors | 1 | 1 passed | 100% (7/7), avg score 100 | 177.7K | 2.4m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-detectors/qual/detector-publish | dashboards/checkout-detectors | with_skill | codex | cumulative | measured | 1/1 recognized | 173641 | 147072 | 0 | 4061 | 596 | unknown | 177702 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-detectors/qual/detector-publish | dashboards/checkout-detectors | with_skill | codex | cumulative | measured | 1/1 recognized | 152000 | 117248 | 0 | 2018 | 159 | unknown | 154018 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
