# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261020T210914152057Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.agent-role.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/agent-connection-demo/qual/instrument | python/agent-connection-demo | 1 | 100% (5/5), avg score 100 | 4.4M | 16.3m | - | - | - |
| with_skill | python/existing-otel-agent-demo/qual/instrument | python/existing-otel-agent-demo | 4 | 97% (31/32), avg score 97 | 22.6M | 1.4h | - | - | - |
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | 1 | 100% (4/4), avg score 100 | 2.9M | 11.1m | - | - | - |
| with_skill | python/model-directed-agent/qual/resource-table-instrument | python/model-directed-agent | 1 | 83% (5/6), avg score 94 | 8.2M | 24.6m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/agent-connection-demo/qual/instrument | python/agent-connection-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 4378505 | 4224640 | 0 | 39628 | 13133 | unknown | 4418133 |
| with_skill | python/existing-otel-agent-demo/qual/instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 4/4 recognized | 22403820 | 21660032 | 0 | 199927 | 67828 | unknown | 22603747 |
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 2868459 | 2716416 | 0 | 25934 | 4643 | unknown | 2894393 |
| with_skill | python/model-directed-agent/qual/resource-table-instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 8154138 | 7938688 | 0 | 56769 | 18893 | unknown | 8210907 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/agent-connection-demo/qual/instrument | python/agent-connection-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 884779 | 787840 | 0 | 3677 | 709 | unknown | 888456 |
| with_skill | python/existing-otel-agent-demo/qual/instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 4/4 recognized | 3652602 | 3302656 | 0 | 29378 | 8687 | unknown | 3681980 |
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 673599 | 569600 | 0 | 2964 | 502 | unknown | 676563 |
| with_skill | python/model-directed-agent/qual/resource-table-instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 1356263 | 1237376 | 0 | 8280 | 3893 | unknown | 1364543 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/existing-otel-agent-demo | with_skill | preserve-logs-instrument | rubric:rubric-3 FAIL | service/content_capture.py:15-51; service/tests/test_instrumentation.py. Evaluator reproduction through configure/app.run_agent and native protobuf encode/decode retained thought-sentinel on workflow, agent, retrieval and model spans, including gen_ai.input.messages and gen_ai.retrieval.query.text. |
| with_skill | python/model-directed-agent | with_skill | native-agent-resource-defaults | rubric:rubric-6 FAIL | receiver-and-api-unavailable asserts business success, zero receipts and any exporter error, without capturing completed spans, metric points or LogRecords. Its recorded output shows only a metrics timeout, so native agent/model/tool emission in that mode remains unproven. Other recovery cases demonstrate stable UUI... |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
