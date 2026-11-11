# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261111T220643259322Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-audit-contract | python/flask-basic | 1 | 79% (11/14), avg score 88 | 4.9M | 15.3m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-audit-contract | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 4833115 | 4686208 | 0 | 27846 | 5618 | unknown | 4860961 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-audit-contract | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2012384 | 1862528 | 0 | 10800 | 4898 | unknown | 2023184 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-2 FAIL | trace.jsonl entry 88 edits evidence and logs.fault.live, prints three other scenarios, and redirects required-controls output to contract-readback.json. Subsequent checks inspect report metadata and summaries. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-9 FAIL | otel-audit.json evidence[14] versus SDK LogRecordLimits.__init__:164-178 and _from_env_if_absent:197-211. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-14 FAIL | LOG-SPEC-CLOSURE limits/default ownership claims empty limits become unlimited; LogRecordLimits.__init__ restores the global count default to 128. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
