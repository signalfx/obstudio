# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | retained-four-native |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | 1 | 100% (9/9), avg score 100 | 3.3M | 13.2m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/finding-group-instrument | python/ai-assistant-demo | 1 | 100% (7/7), avg score 100 | 1.3M | 7.0m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 3309961 | 3194880 | 0 | 30330 | 6924 | unknown | 3340291 |
| with_skill | python/ai-assistant-demo/qual/finding-group-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1293472 | 1182720 | 0 | 13001 | 2490 | unknown | 1306473 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 518706 | 438656 | 0 | 2761 | 332 | unknown | 521467 |
| with_skill | python/ai-assistant-demo/qual/finding-group-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1147499 | 1032576 | 0 | 3249 | 311 | unknown | 1150748 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
