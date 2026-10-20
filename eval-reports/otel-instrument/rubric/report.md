# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261020T200855159694Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.agent-role.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/agent-connection-demo/qual/instrument | python/agent-connection-demo | 1 | 100% (5/5), avg score 100 | 3.1M | 12.0m | - | - | - |
| with_skill | python/existing-otel-agent-demo/qual/instrument | python/existing-otel-agent-demo | 4 | 91% (29/32), avg score 95 | 24.5M | 1.6h | - | - | - |
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | 1 | 100% (4/4), avg score 100 | 4.0M | 16.4m | - | - | - |
| with_skill | python/model-directed-agent/qual/resource-table-instrument | python/model-directed-agent | 1 | 100% (6/6), avg score 96 | 8.2M | 30.4m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/agent-connection-demo/qual/instrument | python/agent-connection-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 3039375 | 2900608 | 0 | 27257 | 7530 | unknown | 3066632 |
| with_skill | python/existing-otel-agent-demo/qual/instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 4/4 recognized | 24261232 | 23521024 | 0 | 227684 | 85373 | unknown | 24488916 |
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 3989997 | 3822592 | 0 | 40476 | 11241 | unknown | 4030473 |
| with_skill | python/model-directed-agent/qual/resource-table-instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 8148909 | 7916928 | 0 | 71726 | 28673 | unknown | 8220635 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/agent-connection-demo/qual/instrument | python/agent-connection-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 744331 | 640640 | 0 | 3646 | 444 | unknown | 747977 |
| with_skill | python/existing-otel-agent-demo/qual/instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 4/4 recognized | 3459507 | 3111168 | 0 | 29749 | 9313 | unknown | 3489256 |
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 612344 | 529024 | 0 | 3374 | 674 | unknown | 615718 |
| with_skill | python/model-directed-agent/qual/resource-table-instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 1327002 | 1197952 | 0 | 7889 | 3265 | unknown | 1334891 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/existing-otel-agent-demo | with_skill | preserve-genai-instrument | rubric:rubric-3 FAIL | service/instrumentation.py:31, :55 and :169. Read-only reproduction retained HIDDEN_SENTINEL in captured messages for 'hidden_reasoning=HIDDEN_SENTINEL; question=shipment'. Sanitizing JSON with sixteen 2000-character fields produced 16614 UTF-8 bytes; retrieval.query.text receives this directly despite declared 1024... |
| with_skill | python/existing-otel-agent-demo | with_skill | preserve-logs-instrument | rubric:rubric-3 FAIL | service/instrumentation.py:62-72 returns parsed scalar strings without applying the redaction rules. Evaluating _enrich with inputs.prompt=json.dumps("private-prompt-sentinel"), then encoding and decoding native OTLP, retained the sentinel; equivalent quoted identity and secret/reasoning strings also leaked. See ser... |
| with_skill | python/existing-otel-agent-demo | with_skill | preserve-logs-instrument | rubric:rubric-8 FAIL | service/.observe/otel-verify.json:376 and :402 list resources-existing trace IDs instead of those in service/.observe/evidence/public-app.json and rejected-app.json. Source hashes and complete schema copies were independently checked; the saved comparisons themselves remain valid. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
