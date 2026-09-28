# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20260928T231312470160Z |
| Agent model | gpt-5.5 |
| Judge model | - |
| Rubric enabled | True |
| Workers | 1 |
| Config | - |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/splunk-ao-integration-demo/qual/instrument | python/splunk-ao-integration-demo | 1 | 100% (6/6), avg score 94 | 8.6M | 20.1m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/splunk-ao-integration-demo/qual/instrument | python/splunk-ao-integration-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 8524878 | 8295808 | 0 | 47490 | 12895 | unknown | 8572368 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/splunk-ao-integration-demo/qual/instrument | python/splunk-ao-integration-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1000713 | 902528 | 0 | 10581 | 5163 | unknown | 1011294 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
