# otel-audit Sanity Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | sanity |
| Skill | otel-audit |
| Run ID | collection-java-30091609b6ab6e1e9d4e6552ce9a6a4be21deb51-native |
| Agent model | gpt-6.1-sol |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Sanity Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/audit | sanity/skill-smoke | 1 | 100% (3/3) | 86.4K | 10.1s | - | - | - |
| with_skill | sanity/skill-smoke/sanity/audit | sanity/skill-smoke | 1 | 100% (3/3) | 93.3K | 10.1s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/audit | sanity/skill-smoke | with_skill | codex | cumulative | measured | 1/1 recognized | 86272 | 48256 | 0 | 86 | 29 | unknown | 86358 |
| with_skill | sanity/skill-smoke/sanity/audit | sanity/skill-smoke | with_skill | codex | cumulative | measured | 1/1 recognized | 93155 | 41984 | 0 | 149 | 93 | unknown | 93304 |

## Sanity Failures

No sanity failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
