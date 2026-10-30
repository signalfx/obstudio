# otel-audit Sanity Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | sanity |
| Skill | otel-audit |
| Run ID | 20261030T205916938879Z |
| Agent model | gpt-6-luna |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Sanity Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/audit | sanity/skill-smoke | 2 | 83% (5/6) | 128.0K | 17.1s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/audit | sanity/skill-smoke | with_skill | codex | cumulative | measured | 2/2 recognized | 127713 | 62336 | 0 | 303 | 227 | unknown | 128016 |

## Sanity Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | sanity/skill-smoke | with_skill | direct | sanity:skill-instructions-read FAIL | Did not successfully read all of otel-audit/SKILL.md before another action |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
