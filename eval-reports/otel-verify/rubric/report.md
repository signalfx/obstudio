# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20261017T022719447868Z |
| Agent model | - |
| Judge model | - |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/.workspace/report-mcp-tools/final-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/mcp-report-verify | go/chi-basic | 1 | 100% (6/6), avg score 100 | 1.0M | 5.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/mcp-report-verify | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1002078 | 942080 | 0 | 8094 | 2934 | unknown | 1010172 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/mcp-report-verify | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 368670 | 303232 | 0 | 4692 | 1436 | unknown | 373362 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
