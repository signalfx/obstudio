# observer-open Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | observer-open |
| Run ID | 20260921T234133309675Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/observer-open | plugins/obstudio | 2 | 90% (9/10), avg score 84 | 207.1K | 4.0m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/observer-open | plugins/obstudio | with_skill | codex | cumulative | measured | 2/2 recognized | 203787 | 148864 | 0 | 3319 | 2516 | unknown | 207106 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/observer-open | plugins/obstudio | with_skill | codex | cumulative | measured | 2/2 recognized | 138347 | 108928 | 0 | 7115 | 4754 | unknown | 145462 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | plugins/obstudio | with_skill | codex-browser | rubric:rubric-1 FAIL | Final: "No callable host browser opener was available... fell back to the skill’s clickable URL behavior." Trace also shows only `http://127.0.0.1:3000/` was targeted. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
