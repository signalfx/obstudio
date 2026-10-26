# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261026T220705244293Z |
| Agent model | gpt-5.6-sol |
| Judge model | gpt-5.6-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | .workspace/codex-evals/codex-evals-gpt-5.6-sol.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/audit | go/chi-basic | 2 | 96% (23/24), avg score 96 | 4.4M | 26.3m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/audit | go/chi-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 4341025 | 4104960 | 0 | 48388 | 19372 | unknown | 4389413 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/audit | go/chi-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 1788078 | 1607040 | 0 | 15602 | 8222 | unknown | 1803680 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | direct | rubric:rubric-8 FAIL | otel.html places Findings immediately after Executive Summary and contains an Audit Evidence row "GenAI ownership" = "No". It has no Incident Readiness or GenAI Readiness section, but searching the rendered HTML finds zero occurrences of "GenAI ownership detected:"; ownership is only conveyed indirectly in an audit-... |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
