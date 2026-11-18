# otel-audit Sanity Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | sanity |
| Skill | otel-audit |
| Run ID | collection-node-console-de3-native-403 |
| Agent model | gpt-6.1-sol |
| Workers | 1 |
| Config | evals/codex-evals.logging.toml |

## Sanity Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/audit | sanity/skill-smoke | 1 | 100% (3/3) | 86.2K | 9.4s | - | - | - |
| with_skill | sanity/skill-smoke/sanity/audit | sanity/skill-smoke | 1 | 100% (3/3) | 86.3K | 8.7s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/audit | sanity/skill-smoke | with_skill | codex | cumulative | measured | 1/1 recognized | 86126 | 38400 | 0 | 86 | 29 | unknown | 86212 |
| with_skill | sanity/skill-smoke/sanity/audit | sanity/skill-smoke | with_skill | codex | cumulative | measured | 1/1 recognized | 86184 | 38400 | 0 | 82 | 26 | unknown | 86266 |

## Sanity Failures

No sanity failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
