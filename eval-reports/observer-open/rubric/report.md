# observer-open Rubric Codex Eval Report

Evaluated source: `7db9a57ada23292c0047e9d5cac24fbf0208847b`. Case outcomes: 2 passed. These are the saved run's results; no actor or judge was rerun for this publication.

Rubric grades are available for **2 of 2 prompts**. Case outcomes also include execution and workflow checks; they are not a count of checklist items.

The legacy judge marked `claude-cli-fallback` as passing overall while marking `rubric-5` false. Both original answers are preserved; the failed checklist item appears below.

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | observer-open |
| Run ID | 20261116T170554Z-consolidated-report |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 8 |
| Config | evals/codex-evals.logging.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | Case outcomes | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/observer-open | plugins/obstudio | 2 | 2 passed | 90% (9/10), avg score 98 | 53.5K | 1.5m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/observer-open | plugins/obstudio | with_skill | codex | cumulative | measured | 2/2 recognized | 52736 | 45056 | 0 | 729 | 393 | unknown | 53465 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/observer-open | plugins/obstudio | with_skill | codex | cumulative | measured | 2/2 recognized | 90462 | 62208 | 0 | 1519 | 382 | unknown | 91981 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | plugins/obstudio | with_skill | claude-cli-fallback | rubric:rubric-5 FAIL | Status: `sandbox-unverified`; no UI-rendering claim is made. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
