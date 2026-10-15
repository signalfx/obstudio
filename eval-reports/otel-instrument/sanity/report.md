# otel-instrument Sanity Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | sanity |
| Skill | otel-instrument |
| Run ID | 20261015T050015219146Z |
| Agent model | gpt-6.1-sol |
| Workers | 1 |
| Config | evals/codex-evals.local-http.toml |

## Sanity Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/instrument | sanity/skill-smoke | 2 | 100% (6/6) | 189.8K | 20.7s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/instrument | sanity/skill-smoke | with_skill | codex | cumulative | measured | 2/2 recognized | 189621 | 98304 | 0 | 130 | 26 | unknown | 189751 |

## Sanity Failures

No sanity failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
