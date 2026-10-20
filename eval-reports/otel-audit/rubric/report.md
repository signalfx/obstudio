# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261020T200853939788Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.agent-role.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/audit | python/existing-otel-agent-demo | 1 | 86% (6/7), avg score 91 | 5.1M | 15.6m | - | - | - |
| with_skill | python/model-directed-agent/qual/audit | python/model-directed-agent | 1 | 100% (5/5), avg score 100 | 4.2M | 13.1m | - | - | - |
| with_skill | python/model-directed-agent/qual/connection-modes-audit | python/model-directed-agent | 1 | 100% (5/5), avg score 100 | 962.1K | 7.9m | - | - | - |
| with_skill | python/model-directed-agent/qual/resource-table-audit | python/model-directed-agent | 1 | 71% (5/7), avg score 93 | 4.4M | 16.3m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/audit | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 5037335 | 4835456 | 0 | 36504 | 9784 | unknown | 5073839 |
| with_skill | python/model-directed-agent/qual/audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 4136032 | 3961344 | 0 | 30869 | 3011 | unknown | 4166901 |
| with_skill | python/model-directed-agent/qual/connection-modes-audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 943813 | 851840 | 0 | 18246 | 2480 | unknown | 962059 |
| with_skill | python/model-directed-agent/qual/resource-table-audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 4385364 | 4179328 | 0 | 37414 | 4010 | unknown | 4422778 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/audit | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 771944 | 681856 | 0 | 4814 | 916 | unknown | 776758 |
| with_skill | python/model-directed-agent/qual/audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 888458 | 800640 | 0 | 3913 | 625 | unknown | 892371 |
| with_skill | python/model-directed-agent/qual/connection-modes-audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 586671 | 507648 | 0 | 3187 | 500 | unknown | 589858 |
| with_skill | python/model-directed-agent/qual/resource-table-audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 1343574 | 1229824 | 0 | 5647 | 1388 | unknown | 1349221 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/existing-otel-agent-demo | with_skill | active-signal-matrix-audit | rubric:rubric-2 FAIL | service/.observe/mode-audit.json modes.metrics and modes.logs: operation_ledger[*].proposed and OTEL-001/OTEL-005.required_fix contain 'exclude those keys from creator registration'. TRACE-001.required_fix specifies integration-owned provider state; service/app.py:117 limits ExistingTraceProducer construction to gen... |
| with_skill | python/model-directed-agent | with_skill | agent-resource-table-audit | rubric:rubric-2 FAIL | service/.observe/agent-resource-cases.json: fresh_native_fallback.producer_decision and routing.exporter_per_request_trace_routing. |
| with_skill | python/model-directed-agent | with_skill | agent-resource-table-audit | rubric:rubric-6 FAIL | Validator passes 16 findings and 27 scenarios; HTML matches normalized canonical JSON; all 13 recorded file hashes match. Supplemental fresh_native_fallback routing and non_agent_control.routing.header_contracts contain the inconsistencies. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
