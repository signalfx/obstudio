# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261007T212452448050Z |
| Agent model | gpt-6-sol |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | node/express-basic/qual/instrument | node/express-basic | 1 | 100% (11/11), avg score 92 | 8.0M | 15.7m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | node/express-basic/qual/instrument | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 7961578 | 7819008 | 0 | 31672 | 15777 | unknown | 7993250 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | node/express-basic/qual/instrument | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 567218 | 455424 | 0 | 11123 | 6179 | unknown | 578341 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
