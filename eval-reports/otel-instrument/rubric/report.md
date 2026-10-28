# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261027T175239134893Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.agent-role.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/benchmark-instrument | go/chi-basic | 1 | 100% (3/3), avg score 100 | 2.8M | 16.5m | - | - | - |
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | 2 | 100% (16/16), avg score 100 | 5.8M | 31.8m | - | - | - |
| with_skill | go/chi-basic/qual/instrument-decision-gated | go/chi-basic | 1 | 100% (4/4), avg score 100 | 2.8M | 11.9m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/benchmark-instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2809334 | 2731392 | 0 | 26821 | 5332 | unknown | 2836155 |
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 5713748 | 5496704 | 0 | 59171 | 13300 | unknown | 5772919 |
| with_skill | go/chi-basic/qual/instrument-decision-gated | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2760502 | 2660224 | 0 | 21365 | 3539 | unknown | 2781867 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/benchmark-instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 598094 | 513152 | 0 | 3195 | 678 | unknown | 601289 |
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 932031 | 775680 | 0 | 5306 | 627 | unknown | 937337 |
| with_skill | go/chi-basic/qual/instrument-decision-gated | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 351229 | 319232 | 0 | 2671 | 188 | unknown | 353900 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
