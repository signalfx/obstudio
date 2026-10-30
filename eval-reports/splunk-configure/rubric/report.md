# splunk-configure Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | splunk-configure |
| Run ID | 20261029T193104609517Z |
| Agent model | gpt-6-luna |
| Judge model | gpt-6-luna |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-configure/qual/configure | dashboards/checkout-configure | 1 | 91% (10/11), avg score 91 | 809.9K | 4.1m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/ao-target-handoff-configure | python/ai-assistant-demo | 1 | 100% (3/3), avg score 98 | 420.8K | 3.4m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-configure/qual/configure | dashboards/checkout-configure | with_skill | codex | cumulative | measured | 1/1 recognized | 801653 | 739968 | 0 | 8290 | 3177 | unknown | 809943 |
| with_skill | python/ai-assistant-demo/qual/ao-target-handoff-configure | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 413200 | 364032 | 0 | 7612 | 1362 | unknown | 420812 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-configure/qual/configure | dashboards/checkout-configure | with_skill | codex | cumulative | measured | 1/1 recognized | 128291 | 86528 | 0 | 2857 | 1559 | unknown | 131148 |
| with_skill | python/ai-assistant-demo/qual/ao-target-handoff-configure | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 210667 | 166656 | 0 | 1869 | 719 | unknown | 212536 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | dashboards/checkout-configure | with_skill | generate | rubric:rubric-1 FAIL | detectors.md reports Saturation 0 and Throughput 0; it says http.server.active_requests was skipped because its type is auto. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
