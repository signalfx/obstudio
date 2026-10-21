# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261021T005223886170Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.agent-role.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/agent-connection-demo/qual/instrument | python/agent-connection-demo | 1 | 100% (5/5), avg score 100 | 3.1M | 11.9m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-instrument | python/ai-assistant-demo | 1 | 100% (8/8), avg score 100 | 4.0M | 16.5m | - | - | - |
| with_skill | python/existing-otel-agent-demo/qual/content-redaction-instrument | python/existing-otel-agent-demo | 1 | 100% (6/6), avg score 100 | 2.6M | 12.1m | - | - | - |
| with_skill | python/existing-otel-agent-demo/qual/instrument | python/existing-otel-agent-demo | 4 | 100% (32/32), avg score 100 | 27.3M | 1.5h | - | - | - |
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | 1 | 100% (4/4), avg score 100 | 4.8M | 12.7m | - | - | - |
| with_skill | python/model-directed-agent/qual/resource-table-instrument | python/model-directed-agent | 1 | 100% (6/6), avg score 100 | 12.3M | 27.8m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/agent-connection-demo/qual/instrument | python/agent-connection-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 3051547 | 2912256 | 0 | 25868 | 5803 | unknown | 3077415 |
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 3957052 | 3782656 | 0 | 39008 | 11622 | unknown | 3996060 |
| with_skill | python/existing-otel-agent-demo/qual/content-redaction-instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 2574394 | 2459904 | 0 | 28174 | 8824 | unknown | 2602568 |
| with_skill | python/existing-otel-agent-demo/qual/instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 4/4 recognized | 27047704 | 26296448 | 0 | 210370 | 64655 | unknown | 27258074 |
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 4749836 | 4583680 | 0 | 28231 | 5042 | unknown | 4778067 |
| with_skill | python/model-directed-agent/qual/resource-table-instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 12272086 | 12011008 | 0 | 67552 | 25535 | unknown | 12339638 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/agent-connection-demo/qual/instrument | python/agent-connection-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 838700 | 739328 | 0 | 4935 | 1266 | unknown | 843635 |
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1055740 | 964096 | 0 | 5346 | 1679 | unknown | 1061086 |
| with_skill | python/existing-otel-agent-demo/qual/content-redaction-instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 420992 | 364032 | 0 | 3916 | 1138 | unknown | 424908 |
| with_skill | python/existing-otel-agent-demo/qual/instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 4/4 recognized | 2811138 | 2481920 | 0 | 26633 | 8055 | unknown | 2837771 |
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 524911 | 447744 | 0 | 4300 | 741 | unknown | 529211 |
| with_skill | python/model-directed-agent/qual/resource-table-instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 1015159 | 905856 | 0 | 4976 | 1150 | unknown | 1020135 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
