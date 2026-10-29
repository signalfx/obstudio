# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261028T170414701823Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.agent-role.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/audit | python/existing-otel-agent-demo | 1 | 100% (7/7), avg score 100 | 6.5M | 30.8m | - | - | - |
| with_skill | python/model-directed-agent/qual/audit | python/model-directed-agent | 1 | 100% (5/5), avg score 100 | 3.8M | 20.3m | - | - | - |
| with_skill | python/model-directed-agent/qual/connection-modes-audit | python/model-directed-agent | 1 | 100% (5/5), avg score 100 | 875.6K | 12.7m | - | - | - |
| with_skill | python/model-directed-agent/qual/resource-table-audit | python/model-directed-agent | 1 | 100% (7/7), avg score 100 | 5.8M | 29.0m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/audit | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 6488918 | 6312960 | 0 | 46296 | 15108 | unknown | 6535214 |
| with_skill | python/model-directed-agent/qual/audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 3784321 | 3593216 | 0 | 35597 | 4669 | unknown | 3819918 |
| with_skill | python/model-directed-agent/qual/connection-modes-audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 855061 | 797056 | 0 | 20550 | 4409 | unknown | 875611 |
| with_skill | python/model-directed-agent/qual/resource-table-audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 5710597 | 5539072 | 0 | 48116 | 9852 | unknown | 5758713 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/audit | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1319696 | 1201792 | 0 | 4661 | 690 | unknown | 1324357 |
| with_skill | python/model-directed-agent/qual/audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 439720 | 336256 | 0 | 3761 | 339 | unknown | 443481 |
| with_skill | python/model-directed-agent/qual/connection-modes-audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 474069 | 397184 | 0 | 2367 | 343 | unknown | 476436 |
| with_skill | python/model-directed-agent/qual/resource-table-audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 1103915 | 1006080 | 0 | 6549 | 1783 | unknown | 1110464 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
