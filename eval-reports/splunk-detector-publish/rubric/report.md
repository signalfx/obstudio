# splunk-detector-publish Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | splunk-detector-publish |
| Run ID | 20261028T022139417774Z |
| Agent model | gpt-6-luna |
| Judge model | gpt-6-luna |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-detectors/qual/detector-publish | dashboards/checkout-detectors | 1 | 86% (6/7), avg score 94 | 99.7K | 1.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-detectors/qual/detector-publish | dashboards/checkout-detectors | with_skill | codex | cumulative | measured | 1/1 recognized | 97732 | 71040 | 0 | 1989 | 821 | unknown | 99721 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-detectors/qual/detector-publish | dashboards/checkout-detectors | with_skill | codex | cumulative | measured | 1/1 recognized | 61414 | 39680 | 0 | 1104 | 402 | unknown | 62518 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | dashboards/checkout-detectors | with_skill | offline-plan | rubric:rubric-3 FAIL | Reasons say live inventory was not fetched and cite service.name='checkout', but do not repeat the detector name or metric. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
