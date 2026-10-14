# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261014T060709621901Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-audit | python/ai-assistant-demo | 1 | 70% (7/10), avg score 80 | 4.7M | 25.9m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 4628582 | 4319616 | 0 | 36471 | 4499 | unknown | 4665053 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1404353 | 1263744 | 0 | 13756 | 4600 | unknown | 1418109 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/ai-assistant-demo | with_skill | genai-sdk-default-audit | rubric:rubric-8 FAIL | OTEL-003 required_fix and expected_telemetry create both invoke_workflow and invoke_agent around build_turn; app.py only has build_turn/run_tool/call_provider. OTEL-006 constraints prohibit gen_ai.usage.total_tokens and use assistant.usage.total_tokens as custom. |
| with_skill | python/ai-assistant-demo | with_skill | genai-sdk-default-audit | rubric:rubric-9 FAIL | genai-default-scenarios.md known_context row mentions qwen3:8b, conv_demo_approved_72fbd8, fixed-agent request.model and tool description/type, but lacks the configured agent description value and a per-field/value/level mapping. |
| with_skill | python/ai-assistant-demo | with_skill | genai-sdk-default-audit | rubric:rubric-10 FAIL | genai-default-scenarios.md says helper sets many attributes on exit and sampler/on_start proof is not established; OTEL-003/OTEL-009 mention creation-time sampling partial. No report artifact cites start_as_current_span(splunk_ao_span.name) or the finally-time build_span_attributes path explicitly. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
