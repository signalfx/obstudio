# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261017T022719447823Z |
| Agent model | - |
| Judge model | - |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/.workspace/report-mcp-tools/final-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/mcp-report-audit | go/chi-basic | 1 | 100% (6/6), avg score 100 | 675.3K | 4.6m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/mcp-report-audit | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 668539 | 600960 | 0 | 6767 | 3127 | unknown | 675306 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/mcp-report-audit | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 273464 | 210176 | 0 | 4387 | 1132 | unknown | 277851 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
