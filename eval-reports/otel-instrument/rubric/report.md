# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261007T153815034615Z |
| Agent model | gpt-6.1-sol |
| Judge model | - |
| Rubric enabled | True |
| Workers | 1 |
| Config | - |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/splunk-ao-langchain-demo/qual/instrument | python/splunk-ao-langchain-demo | 1 | 100% (6/6), avg score 100 | 3.1M | 17.3m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/splunk-ao-langchain-demo/qual/instrument | python/splunk-ao-langchain-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 3089736 | 2945024 | 0 | 20422 | 3811 | unknown | 3110158 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/splunk-ao-langchain-demo/qual/instrument | python/splunk-ao-langchain-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 235851 | 199296 | 0 | 1702 | 116 | unknown | 237553 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
