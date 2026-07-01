# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20260629T192245327834Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/mcp-ai-tool-demo/qual/instrument | python/mcp-ai-tool-demo | 1 | 86% (6/7), avg score 84 | 3.0M | 18.1m | - | - | - |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/mcp-ai-tool-demo | with_skill | direct | rubric:rubric-7 FAIL | .observe/otel-verify.md reports 24/26 working with OTLP HTTP exporter defaults and FastAPI automatic HTTP server spans/request metrics Not proven; trace.jsonl shows unittest/make test and validate_reader_report, not a live collector or uvicorn acceptance run. grade.json sanity checks passed. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
