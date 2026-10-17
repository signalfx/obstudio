# otel-audit Sanity Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | sanity |
| Skill | otel-audit |
| Run ID | 20261017T022719447849Z |
| Agent model | - |
| Workers | 1 |
| Config | evals/.workspace/report-mcp-tools/final-evals.toml |

## Sanity Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/sanity/stage-path-audit | go/chi-basic | 1 | 100% (5/5) | 1.8M | 7.4m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/sanity/stage-path-audit | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1811815 | 1664512 | 0 | 19319 | 6489 | unknown | 1831134 |

## Sanity Failures

No sanity failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
