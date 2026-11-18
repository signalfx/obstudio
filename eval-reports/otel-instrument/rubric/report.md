# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | collection-go-a49853bcd918a968f4ea9494c2b6b08d7c85a815-native |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | 1 | 100% (9/9), avg score 100 | 2.8M | 12.0m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/finding-group-instrument | python/ai-assistant-demo | 1 | 100% (7/7), avg score 100 | 1.6M | 6.1m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2737052 | 2632192 | 0 | 26542 | 5608 | unknown | 2763594 |
| with_skill | python/ai-assistant-demo/qual/finding-group-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1587767 | 1476608 | 0 | 11981 | 1387 | unknown | 1599748 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 623857 | 542080 | 0 | 3773 | 601 | unknown | 627630 |
| with_skill | python/ai-assistant-demo/qual/finding-group-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1142884 | 1051392 | 0 | 2950 | 377 | unknown | 1145834 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
