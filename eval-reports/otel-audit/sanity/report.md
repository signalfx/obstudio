# otel-audit Sanity Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | sanity |
| Skill | otel-audit |
| Run ID | 20261015T034344520113Z |
| Agent model | gpt-6.1-sol |
| Workers | 1 |
| Config | evals/codex-evals.local-http.toml |

## Sanity Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/audit | sanity/skill-smoke | 2 | 100% (6/6) | 171.2K | 23.8s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/audit | sanity/skill-smoke | with_skill | codex | cumulative | measured | 2/2 recognized | 171018 | 88192 | 0 | 172 | 60 | unknown | 171190 |

## Sanity Failures

No sanity failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
