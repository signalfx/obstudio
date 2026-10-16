# observer-open Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | observer-open |
| Run ID | 20261016T190416338524Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/observer-open | plugins/obstudio | 2 | 0% (0/2), avg score 0 | 157.6K | 1.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/observer-open | plugins/obstudio | with_skill | codex | cumulative | measured | 2/2 recognized | 155505 | 123776 | 0 | 2070 | 1531 | unknown | 157575 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/observer-open | plugins/obstudio | with_skill | codex | unknown | absent | 0/2 recognized; 0/2 observed | unknown | unknown | unknown | unknown | unknown | unknown | unknown |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | plugins/obstudio | with_skill | claude-cli-fallback | rubric:rubric-run FAIL | Reading additional input from stdin... |
| with_skill | plugins/obstudio | with_skill | codex-browser | rubric:rubric-run FAIL | Reading additional input from stdin... |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
