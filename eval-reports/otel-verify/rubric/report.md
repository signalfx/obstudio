# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20260911T202646482252Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.token-benchmark.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | 1 | 100% (4/4), avg score 98 | 890.9K | 6.5m | - | - | - |
| with_skill | go/chi-basic/qual/verify-runtime-blocker | go/chi-basic | 1 | 100% (5/5), avg score 97 | 1.1M | 6.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 879616 | 820480 | unknown | 11285 | 2614 | unknown | 890901 |
| with_skill | go/chi-basic/qual/verify-runtime-blocker | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1052456 | 980224 | unknown | 12090 | 3544 | unknown | 1064546 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 447475 | 374144 | unknown | 5619 | 2428 | unknown | 453094 |
| with_skill | go/chi-basic/qual/verify-runtime-blocker | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 182437 | 139520 | unknown | 4537 | 1690 | unknown | 186974 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
