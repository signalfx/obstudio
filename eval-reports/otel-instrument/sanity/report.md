# otel-instrument Sanity Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | sanity |
| Skill | otel-instrument |
| Run ID | collection-core-2ef0abda3e3791b38a598dc482207ed30279258e-native |
| Agent model | gpt-6.1-sol |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Sanity Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/instrument | sanity/skill-smoke | 1 | 100% (3/3) | 95.5K | 9.6s | - | - | - |
| with_skill | sanity/skill-smoke/sanity/instrument | sanity/skill-smoke | 1 | 100% (3/3) | 95.3K | 8.6s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/instrument | sanity/skill-smoke | with_skill | codex | cumulative | measured | 1/1 recognized | 95390 | 43392 | 0 | 120 | 69 | unknown | 95510 |
| with_skill | sanity/skill-smoke/sanity/instrument | sanity/skill-smoke | with_skill | codex | cumulative | measured | 1/1 recognized | 95219 | 53120 | 0 | 81 | 25 | unknown | 95300 |

## Sanity Failures

No sanity failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
