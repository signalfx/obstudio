# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261008T194926518826Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/content-coverage-instrument | python/ai-assistant-demo | 1 | 100% (6/6), avg score 94 | 9.6M | 18.1m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | 1 | 79% (11/14), avg score 74 | 14.2M | 30.4m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/content-coverage-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 9508708 | 9282432 | 0 | 41688 | 12477 | unknown | 9550396 |
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 14152470 | 13849600 | 0 | 62514 | 20631 | unknown | 14214984 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/content-coverage-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 558431 | 469504 | 0 | 9341 | 5408 | unknown | 567772 |
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 2200708 | 1944576 | 0 | 19595 | 10668 | unknown | 2220303 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/ai-assistant-demo | with_skill | direct | rubric:rubric-10 FAIL | service/ao_routing.py has separate resolver and processor classes, but normalize_route_key() returns DEFAULT_ROUTE_KEY for unknown requested routes; .observe/otel-verify.md reports no real project/stream/exporter/cloud proof. |
| with_skill | python/ai-assistant-demo | with_skill | direct | rubric:rubric-13 FAIL | service/.env.studio.example contains http://127.0.0.1:<studio-api-port> and <studio-console-port>; tests use FakeProjects/FakeStreams/FakeExporter rather than real splunk-ao config acceptance. |
| with_skill | python/ai-assistant-demo | with_skill | direct | rubric:rubric-14 FAIL | service/ao_routing.py exporter_factory receives project_id and agent_stream_id after resolve(); tests/test_telemetry.py uses FakeExporter and fake resource lookups; no real SplunkAOOTLPExporter import/config/export proof was run. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
