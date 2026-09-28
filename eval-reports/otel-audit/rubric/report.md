# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20260928T225625779097Z |
| Agent model | gpt-5.5 |
| Judge model | - |
| Rubric enabled | True |
| Workers | 1 |
| Config | - |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/splunk-ao-integration-demo/qual/audit | python/splunk-ao-integration-demo | 1 | 100% (6/6), avg score 92 | 1.4M | 11.1m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/splunk-ao-integration-demo/qual/audit | python/splunk-ao-integration-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1384331 | 1251968 | 0 | 26063 | 11907 | unknown | 1410394 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/splunk-ao-integration-demo/qual/audit | python/splunk-ao-integration-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 442434 | 357760 | 0 | 8034 | 4360 | unknown | 450468 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
