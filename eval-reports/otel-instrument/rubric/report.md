# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20260928T204046108647Z |
| Agent model | - |
| Judge model | - |
| Rubric enabled | True |
| Workers | 1 |
| Config | - |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/splunk-ao-ownership-demo/qual/instrument | python/splunk-ao-ownership-demo | 1 | 100% (6/6), avg score 94 | 1.6M | 5.8m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/splunk-ao-ownership-demo/qual/instrument | python/splunk-ao-ownership-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1635820 | 1550976 | 0 | 13773 | 4036 | unknown | 1649593 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/splunk-ao-ownership-demo/qual/instrument | python/splunk-ao-ownership-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 143143 | 115200 | 0 | 1685 | 630 | unknown | 144828 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
