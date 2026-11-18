# otel-instrument Sanity Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | sanity |
| Skill | otel-instrument |
| Run ID | retained-four-native |
| Agent model | gpt-6.1-sol |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Sanity Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/instrument | sanity/skill-smoke | 1 | 100% (3/3) | 100.3K | 9.2s | - | - | - |
| with_skill | sanity/skill-smoke/sanity/instrument | sanity/skill-smoke | 1 | 100% (3/3) | 100.4K | 8.4s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/instrument | sanity/skill-smoke | with_skill | codex | cumulative | measured | 1/1 recognized | 100224 | 45824 | 0 | 72 | 15 | unknown | 100296 |
| with_skill | sanity/skill-smoke/sanity/instrument | sanity/skill-smoke | with_skill | codex | cumulative | measured | 1/1 recognized | 100282 | 45952 | 0 | 76 | 20 | unknown | 100358 |

## Sanity Failures

No sanity failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
