# otel-instrument Sanity Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | sanity |
| Skill | otel-instrument |
| Run ID | 20261017T022719447843Z |
| Agent model | - |
| Workers | 1 |
| Config | evals/.workspace/report-mcp-tools/final-evals.toml |

## Sanity Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/instrument | sanity/skill-smoke | 2 | 100% (6/6) | 67.8K | 23.3s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/instrument | sanity/skill-smoke | with_skill | codex | cumulative | measured | 2/2 recognized | 67488 | 51584 | 0 | 334 | 221 | unknown | 67822 |

## Sanity Failures

No sanity failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
