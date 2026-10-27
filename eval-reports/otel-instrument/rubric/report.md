# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261027T150809627145Z |
| Agent model | gpt-5.6-sol |
| Judge model | gpt-5.6-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | .workspace/codex-evals/codex-evals-gpt-5.6-sol.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/benchmark-instrument | go/chi-basic | 1 | 100% (3/3), avg score 99 | 9.9M | 23.9m | - | - | - |
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | 2 | 100% (16/16), avg score 100 | 39.6M | 1.2h | - | - | - |
| with_skill | go/chi-basic/qual/instrument-decision-gated | go/chi-basic | 1 | 100% (4/4), avg score 100 | 8.1M | 17.6m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/benchmark-instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 9896058 | 9653376 | 0 | 48554 | 19844 | unknown | 9944612 |
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 39441951 | 38898944 | 0 | 133399 | 49046 | unknown | 39575350 |
| with_skill | go/chi-basic/qual/instrument-decision-gated | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 8072130 | 7893248 | 0 | 32560 | 14183 | unknown | 8104690 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/benchmark-instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1292966 | 1167616 | 0 | 6511 | 2869 | unknown | 1299477 |
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 1402159 | 1223296 | 0 | 12810 | 6395 | unknown | 1414969 |
| with_skill | go/chi-basic/qual/instrument-decision-gated | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 185046 | 148608 | 0 | 3523 | 1630 | unknown | 188569 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
