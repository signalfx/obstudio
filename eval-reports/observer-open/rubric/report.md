# observer-open Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | observer-open |
| Run ID | 20261019T181052306620Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.model-override.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/observer-open | plugins/obstudio | 2 | 80% (8/10), avg score 82 | 154.4K | 1.5m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/observer-open | plugins/obstudio | with_skill | codex | cumulative | measured | 2/2 recognized | 153754 | 128128 | 0 | 680 | 241 | unknown | 154434 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/observer-open | plugins/obstudio | with_skill | codex | cumulative | measured | 2/2 recognized | 141041 | 115328 | 0 | 1693 | 324 | unknown | 142734 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | plugins/obstudio | with_skill | claude-cli-fallback | rubric:rubric-5 FAIL | Final response says “Reachability is sandbox-unverified” and proposes a health check without explaining its UI-verification limitation. |
| with_skill | plugins/obstudio | with_skill | codex-browser | rubric:rubric-1 FAIL | trace.jsonl records only reading SKILL.md and sending messages; no browser invocation. The final response claims no browser capability was exposed. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
