# splunk-configure Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | splunk-configure |
| Run ID | 20261028T005044247606Z |
| Agent model | gpt-6-luna |
| Judge model | gpt-6-luna |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-configure/qual/configure | dashboards/checkout-configure | 1 | 90% (9/10), avg score 85 | 681.0K | 4.1m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/ao-target-handoff-configure | python/ai-assistant-demo | 1 | 100% (3/3), avg score 100 | 619.0K | 5.6m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-configure/qual/configure | dashboards/checkout-configure | with_skill | codex | cumulative | measured | 1/1 recognized | 672186 | 595968 | 0 | 8842 | 3690 | unknown | 681028 |
| with_skill | python/ai-assistant-demo/qual/ao-target-handoff-configure | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 605837 | 546688 | 0 | 13147 | 2518 | unknown | 618984 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-configure/qual/configure | dashboards/checkout-configure | with_skill | codex | cumulative | measured | 1/1 recognized | 121959 | 89088 | 0 | 2487 | 930 | unknown | 124446 |
| with_skill | python/ai-assistant-demo/qual/ao-target-handoff-configure | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 298422 | 246784 | 0 | 3067 | 1607 | unknown | 301489 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | dashboards/checkout-configure | with_skill | generate | rubric:rubric-1 FAIL | detectors.md reports Latency: 1, Throughput: 0, Saturation: 0; detectors.tf contains only latency and error resources. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
