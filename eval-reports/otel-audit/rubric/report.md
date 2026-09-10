# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20260910T194630806051Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/kvstore/qual/audit | go/kvstore | 2 | 75% (9/12), avg score 86 | 3.5M | 19.0m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/kvstore/qual/audit | go/kvstore | with_skill | codex | cumulative | measured | 2/2 recognized | 3448397 | 3203200 | unknown | 44126 | 9252 | unknown | 3492523 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/kvstore/qual/audit | go/kvstore | with_skill | codex | cumulative | measured | 2/2 recognized | 303614 | 213760 | unknown | 7596 | 3320 | unknown | 311210 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/kvstore | with_skill | direct | rubric:rubric-4 FAIL | OTEL-003 for Store workflow and async durability has priority "required" and instrument_mode "default"; OTEL-004 covers eviction with priority "recommended" and instrument_mode "fix all". |
| with_skill | go/kvstore | with_skill | readiness-review | rubric:rubric-2 FAIL | routes contains PUT/GET/DELETE /kv/{key} and GET /search; verification scenarios include GET /search?word=bar, PUT /kv/test, and GET /kv/missing. |
| with_skill | go/kvstore | with_skill | readiness-review | rubric:rubric-4 FAIL | OTEL-004 is required/default for async persistence and index health; OTEL-006 is recommended/fix all for runtime and LRU eviction metrics. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
