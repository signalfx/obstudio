# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | collection-java-30091609b6ab6e1e9d4e6552ce9a6a4be21deb51-native |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | 1 | 100% (9/9), avg score 100 | 2.2M | 10.8m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/finding-group-instrument | python/ai-assistant-demo | 1 | 100% (7/7), avg score 100 | 1.6M | 5.7m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2208072 | 2105088 | 0 | 24470 | 4575 | unknown | 2232542 |
| with_skill | python/ai-assistant-demo/qual/finding-group-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1609650 | 1480704 | 0 | 9948 | 1351 | unknown | 1619598 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 804148 | 710912 | 0 | 2872 | 164 | unknown | 807020 |
| with_skill | python/ai-assistant-demo/qual/finding-group-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1118223 | 1023232 | 0 | 3336 | 325 | unknown | 1121559 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
