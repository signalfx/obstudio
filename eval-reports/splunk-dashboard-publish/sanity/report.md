# splunk-dashboard-publish Sanity Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | sanity |
| Skill | splunk-dashboard-publish |
| Run ID | 20260910T204304896136Z |
| Agent model | gpt-5.5 |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Sanity Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/dashboard-publish | sanity/skill-smoke | 2 | 100% (6/6) | 82.7K | 34.5s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/dashboard-publish | sanity/skill-smoke | with_skill | codex | cumulative | measured | 2/2 recognized | 82507 | 56832 | unknown | 177 | 0 | unknown | 82684 |

## Sanity Failures

No sanity failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
