# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261029T160338863738Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.agent-role.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/agent-connection-demo/qual/instrument | python/agent-connection-demo | 1 | 100% (5/5), avg score 100 | 3.6M | 18.7m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-instrument | python/ai-assistant-demo | 1 | 100% (8/8), avg score 100 | 2.6M | 11.3m | - | - | - |
| with_skill | python/existing-otel-agent-demo/qual/content-redaction-instrument | python/existing-otel-agent-demo | 1 | 100% (6/6), avg score 100 | 2.1M | 15.9m | - | - | - |
| with_skill | python/existing-otel-agent-demo/qual/instrument | python/existing-otel-agent-demo | 4 | 100% (32/32), avg score 100 | 31.8M | 1.8h | - | - | - |
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | 1 | 100% (4/4), avg score 100 | 3.0M | 11.0m | - | - | - |
| with_skill | python/model-directed-agent/qual/resource-table-instrument | python/model-directed-agent | 1 | 100% (6/6), avg score 100 | 10.5M | 25.4m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/agent-connection-demo/qual/instrument | python/agent-connection-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 3589899 | 3450496 | 0 | 37330 | 12336 | unknown | 3627229 |
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 2607785 | 2454400 | 0 | 26095 | 2498 | unknown | 2633880 |
| with_skill | python/existing-otel-agent-demo/qual/content-redaction-instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 2053244 | 1958400 | 0 | 27439 | 8592 | unknown | 2080683 |
| with_skill | python/existing-otel-agent-demo/qual/instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 4/4 recognized | 31572993 | 30465152 | 0 | 217253 | 71228 | unknown | 31790246 |
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 3022832 | 2884224 | 0 | 23023 | 5532 | unknown | 3045855 |
| with_skill | python/model-directed-agent/qual/resource-table-instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 10419693 | 10212736 | 0 | 51572 | 17647 | unknown | 10471265 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/agent-connection-demo/qual/instrument | python/agent-connection-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 555273 | 468864 | 0 | 5033 | 999 | unknown | 560306 |
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 548180 | 463488 | 0 | 3682 | 850 | unknown | 551862 |
| with_skill | python/existing-otel-agent-demo/qual/content-redaction-instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 404776 | 343296 | 0 | 5049 | 1262 | unknown | 409825 |
| with_skill | python/existing-otel-agent-demo/qual/instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 4/4 recognized | 4263991 | 3846784 | 0 | 30617 | 8541 | unknown | 4294608 |
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 456232 | 372992 | 0 | 3246 | 642 | unknown | 459478 |
| with_skill | python/model-directed-agent/qual/resource-table-instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 836934 | 733312 | 0 | 6031 | 2419 | unknown | 842965 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
