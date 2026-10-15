# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261015T033448000064Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.local-http.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/route-recovery-audit | python/existing-otel-agent-demo | 1 | 100% (5/5), avg score 100 | 1.4M | 7.3m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/route-recovery-audit | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1359681 | 1233664 | 0 | 16874 | 1913 | unknown | 1376555 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/route-recovery-audit | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 396325 | 315776 | 0 | 2146 | 179 | unknown | 398471 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
