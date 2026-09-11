# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20260911T021220597437Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/kvstore/qual/audit | go/kvstore | 2 | 83% (10/12), avg score 86 | 7.0M | 28.3m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/kvstore/qual/audit | go/kvstore | with_skill | codex | cumulative | measured | 2/2 recognized | 6924556 | 6603904 | unknown | 61909 | 24193 | unknown | 6986465 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/kvstore/qual/audit | go/kvstore | with_skill | codex | cumulative | measured | 2/2 recognized | 730684 | 617216 | unknown | 13512 | 7401 | unknown | 744196 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/kvstore | with_skill | direct | rubric:rubric-4 FAIL | OTEL-003 is titled Store persistence, index, and eviction telemetry is missing and covers persistAsync, enqueueIndex/indexLoop, evictOldestLocked, and loadFromDisk, but has priority required and instrument_mode default. |
| with_skill | go/kvstore | with_skill | readiness-review | rubric:rubric-4 FAIL | OTEL-005 'Trace store operations and async persistence/index work' has priority required and instrument_mode default; OTEL-006 covers LRU eviction as recommended/fix all, with only the eviction span event marked optional. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
