# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261008T190813927270Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/content-coverage-instrument | python/ai-assistant-demo | 1 | 83% (5/6), avg score 86 | 14.2M | 18.1m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | 1 | 79% (11/14), avg score 78 | 12.8M | 27.6m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/content-coverage-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 14203456 | 13923328 | 0 | 36870 | 15825 | unknown | 14240326 |
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 12724727 | 12446592 | 0 | 66618 | 21215 | unknown | 12791345 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/content-coverage-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 455589 | 379008 | 0 | 10020 | 6055 | unknown | 465609 |
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1178639 | 1009536 | 0 | 13283 | 6636 | unknown | 1191922 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/ai-assistant-demo | with_skill | selected-model-and-tool-findings | rubric:rubric-6 FAIL | service/tests/test_genai_content.py:102-109 parses gen_ai.output.messages but checks only role and finish_reason, not content or one-candidate length. service/tests/test_genai_content.py:55-56 changes OTEL_SDK_DISABLED to false; service/.observe/otel-verify.md:38-40 documents that override. |
| with_skill | python/ai-assistant-demo | with_skill | direct | rubric:rubric-10 FAIL | service/ao_routing.py resolves Projects/AgentStreams lazily and constructs SplunkAOOTLPExporter per route; pyproject.toml/uv.lock include splunk-ao==0.4.0. Tests use fake project/stream clients and a fake CaptureExporter rather than real SDK endpoint/export config; service/.env.studio.example contains REPLACE_WITH_S... |
| with_skill | python/ai-assistant-demo | with_skill | direct | rubric:rubric-13 FAIL | service/.env.studio.example contains SPLUNK_AO_API_URL/CONSOLE_URL with REPLACE_WITH_STUDIO_GATEWAY_PORT and SPLUNK_AO_API_KEY=local-gateway; no .env.cloud.example is present; tests rely on fake clients/exporter. |
| with_skill | python/ai-assistant-demo | with_skill | direct | rubric:rubric-14 FAIL | service/ao_routing.py AORouteDispatchSpanProcessor constructs SplunkAOOTLPExporter(project_id=..., agent_stream_id=...) per route. tests/test_genai_telemetry.py only invokes the processor with synthetic FinishedSpan objects and fake CaptureExporter, plus mocked resource lookup failure. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
