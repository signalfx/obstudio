# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20261015T033447999985Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.local-http.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/route-recovery-verify | python/existing-otel-agent-demo | 1 | 100% (5/5), avg score 100 | 1.2M | 8.1m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/route-recovery-verify | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1181145 | 1082240 | 0 | 18535 | 2374 | unknown | 1199680 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/route-recovery-verify | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 371866 | 313600 | 0 | 2888 | 207 | unknown | 374754 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
