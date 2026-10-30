# splunk-configure Sanity Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | sanity |
| Skill | splunk-configure |
| Run ID | 20261030T045334044507Z |
| Agent model | gpt-6-luna |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Sanity Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/configure | sanity/skill-smoke | 2 | 100% (6/6) | 124.5K | 22.6s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/configure | sanity/skill-smoke | with_skill | codex | cumulative | measured | 2/2 recognized | 124035 | 64384 | 0 | 509 | 382 | unknown | 124544 |

## Sanity Failures

No sanity failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
