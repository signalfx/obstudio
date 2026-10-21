# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261021T021043977714Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.agent-role.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/agent-connection-demo/qual/instrument | python/agent-connection-demo | 1 | 100% (5/5), avg score 100 | 4.2M | 15.3m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-instrument | python/ai-assistant-demo | 1 | 100% (8/8), avg score 100 | 2.8M | 13.1m | - | - | - |
| with_skill | python/existing-otel-agent-demo/qual/content-redaction-instrument | python/existing-otel-agent-demo | 1 | 100% (6/6), avg score 100 | 2.4M | 15.0m | - | - | - |
| with_skill | python/existing-otel-agent-demo/qual/instrument | python/existing-otel-agent-demo | 4 | 100% (32/32), avg score 100 | 26.7M | 1.9h | - | - | - |
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | 1 | 100% (4/4), avg score 100 | 3.0M | 11.3m | - | - | - |
| with_skill | python/model-directed-agent/qual/resource-table-instrument | python/model-directed-agent | 1 | 100% (6/6), avg score 100 | 9.2M | 23.8m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/agent-connection-demo/qual/instrument | python/agent-connection-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 4192862 | 4034944 | 0 | 35812 | 10628 | unknown | 4228674 |
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 2797249 | 2635392 | 0 | 31652 | 5809 | unknown | 2828901 |
| with_skill | python/existing-otel-agent-demo/qual/content-redaction-instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 2368558 | 2249600 | 0 | 34538 | 11838 | unknown | 2403096 |
| with_skill | python/existing-otel-agent-demo/qual/instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 4/4 recognized | 26403180 | 25590016 | 0 | 276244 | 113571 | unknown | 26679424 |
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 2936151 | 2781824 | 0 | 25691 | 4384 | unknown | 2961842 |
| with_skill | python/model-directed-agent/qual/resource-table-instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 9162830 | 8702208 | 0 | 58988 | 20150 | unknown | 9221818 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/agent-connection-demo/qual/instrument | python/agent-connection-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 785845 | 671744 | 0 | 4557 | 1246 | unknown | 790402 |
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 587151 | 501504 | 0 | 3567 | 616 | unknown | 590718 |
| with_skill | python/existing-otel-agent-demo/qual/content-redaction-instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 381012 | 331520 | 0 | 5267 | 1030 | unknown | 386279 |
| with_skill | python/existing-otel-agent-demo/qual/instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 4/4 recognized | 3740806 | 3372928 | 0 | 29603 | 7897 | unknown | 3770409 |
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 655279 | 567680 | 0 | 3749 | 740 | unknown | 659028 |
| with_skill | python/model-directed-agent/qual/resource-table-instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 887502 | 782080 | 0 | 5605 | 2280 | unknown | 893107 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
