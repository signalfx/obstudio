# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20260928T204046108675Z |
| Agent model | - |
| Judge model | - |
| Rubric enabled | True |
| Workers | 1 |
| Config | - |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/splunk-ao-ownership-demo/qual/audit | python/splunk-ao-ownership-demo | 1 | 100% (6/6), avg score 93 | 1.4M | 4.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/splunk-ao-ownership-demo/qual/audit | python/splunk-ao-ownership-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1414981 | 1348224 | 0 | 8378 | 1559 | unknown | 1423359 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/splunk-ao-ownership-demo/qual/audit | python/splunk-ao-ownership-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 111983 | 77696 | 0 | 1746 | 521 | unknown | 113729 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
