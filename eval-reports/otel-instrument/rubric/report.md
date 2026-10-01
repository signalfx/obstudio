# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261001T175940987323Z |
| Agent model | - |
| Judge model | - |
| Rubric enabled | True |
| Workers | 1 |
| Config | - |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/splunk-ao-integration-demo/qual/instrument | python/splunk-ao-integration-demo | 1 | 100% (6/6), avg score 91 | 5.1M | 9.4m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/splunk-ao-integration-demo/qual/instrument | python/splunk-ao-integration-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 5079329 | 4962048 | 0 | 19820 | 3793 | unknown | 5099149 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/splunk-ao-integration-demo/qual/instrument | python/splunk-ao-integration-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 153452 | 114944 | 0 | 2186 | 635 | unknown | 155638 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
