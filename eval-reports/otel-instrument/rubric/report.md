# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261017T022719447865Z |
| Agent model | - |
| Judge model | - |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/.workspace/report-mcp-tools/final-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/mcp-report-instrument | go/chi-basic | 1 | 100% (6/6), avg score 98 | 724.4K | 5.0m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/mcp-report-instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 716604 | 662784 | 0 | 7841 | 3271 | unknown | 724445 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/mcp-report-instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 365074 | 289920 | 0 | 5011 | 1454 | unknown | 370085 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
