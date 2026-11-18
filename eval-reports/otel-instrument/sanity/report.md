# otel-instrument Sanity Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | sanity |
| Skill | otel-instrument |
| Run ID | collection-node-console-de3-native-403 |
| Agent model | gpt-6.1-sol |
| Workers | 1 |
| Config | evals/codex-evals.logging.toml |

## Sanity Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/instrument | sanity/skill-smoke | 1 | 100% (3/3) | 94.7K | 8.9s | - | - | - |
| with_skill | sanity/skill-smoke/sanity/instrument | sanity/skill-smoke | 1 | 100% (3/3) | 94.7K | 16.4s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/instrument | sanity/skill-smoke | with_skill | codex | cumulative | measured | 1/1 recognized | 94609 | 52864 | 0 | 103 | 46 | unknown | 94712 |
| with_skill | sanity/skill-smoke/sanity/instrument | sanity/skill-smoke | with_skill | codex | cumulative | measured | 1/1 recognized | 94579 | 43008 | 0 | 77 | 21 | unknown | 94656 |

## Sanity Failures

No sanity failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
