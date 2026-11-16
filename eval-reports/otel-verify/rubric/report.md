# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20261116T060932547161Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.logging.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | node/express-basic/qual/report-projection-verify | node/express-basic | 1 | 4/4 criteria passed; strict: 0 fail, 0 not proven, 0 N/A, 0 ungraded; 0/1 strict runs incomplete, 0 all-N/A, avg score 100 | 1.1M | 5.5m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | node/express-basic/qual/report-projection-verify | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1062408 | 982656 | 0 | 9460 | 2037 | unknown | 1071868 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | node/express-basic/qual/report-projection-verify | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 529753 | 456448 | 0 | 3610 | 454 | unknown | 533363 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
