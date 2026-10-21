# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261021T042942403248Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.agent-role.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/agent-connection-demo/qual/instrument | python/agent-connection-demo | 1 | 100% (5/5), avg score 100 | 3.1M | 14.6m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-instrument | python/ai-assistant-demo | 1 | 100% (8/8), avg score 100 | 3.1M | 11.7m | - | - | - |
| with_skill | python/existing-otel-agent-demo/qual/content-redaction-instrument | python/existing-otel-agent-demo | 1 | 100% (6/6), avg score 100 | 3.6M | 14.9m | - | - | - |
| with_skill | python/existing-otel-agent-demo/qual/instrument | python/existing-otel-agent-demo | 4 | 100% (32/32), avg score 100 | 26.6M | 1.6h | - | - | - |
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | 1 | 100% (4/4), avg score 100 | 5.2M | 16.1m | - | - | - |
| with_skill | python/model-directed-agent/qual/resource-table-instrument | python/model-directed-agent | 1 | 100% (6/6), avg score 96 | 9.3M | 23.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/agent-connection-demo/qual/instrument | python/agent-connection-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 3039016 | 2895488 | 0 | 34389 | 10080 | unknown | 3073405 |
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 3044576 | 2880512 | 0 | 26717 | 3082 | unknown | 3071293 |
| with_skill | python/existing-otel-agent-demo/qual/content-redaction-instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 3524296 | 3374592 | 0 | 34954 | 10522 | unknown | 3559250 |
| with_skill | python/existing-otel-agent-demo/qual/instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 4/4 recognized | 26409820 | 25639808 | 0 | 230527 | 71202 | unknown | 26640347 |
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 5139347 | 4946816 | 0 | 37524 | 6543 | unknown | 5176871 |
| with_skill | python/model-directed-agent/qual/resource-table-instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 9259337 | 9033600 | 0 | 55116 | 17775 | unknown | 9314453 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/agent-connection-demo/qual/instrument | python/agent-connection-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1250251 | 1124352 | 0 | 4331 | 913 | unknown | 1254582 |
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 634350 | 550272 | 0 | 4081 | 910 | unknown | 638431 |
| with_skill | python/existing-otel-agent-demo/qual/content-redaction-instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 357322 | 309632 | 0 | 4483 | 1334 | unknown | 361805 |
| with_skill | python/existing-otel-agent-demo/qual/instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 4/4 recognized | 4912909 | 4500992 | 0 | 34141 | 9669 | unknown | 4947050 |
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 720043 | 628736 | 0 | 5015 | 1333 | unknown | 725058 |
| with_skill | python/model-directed-agent/qual/resource-table-instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 1039313 | 932864 | 0 | 6104 | 1748 | unknown | 1045417 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
