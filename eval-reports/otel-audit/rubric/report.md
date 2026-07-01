# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20260629T193514000000Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | merged |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/audit | go/chi-basic | 2 | 100% (12/12), avg score 100 | 1.9M | 18.2m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/audit | python/ai-assistant-demo | 2 | 100% (12/12), avg score 98 | 3.7M | 16.8m | - | - | - |
| with_skill | python/assistant-v3-framework-bridge-demo/qual/audit | python/assistant-v3-framework-bridge-demo | 1 | 100% (6/6), avg score 95 | 1.6M | 8.9m | - | - | - |
| with_skill | python/mcp-ai-tool-demo/qual/audit | python/mcp-ai-tool-demo | 2 | 100% (12/12), avg score 100 | 3.6M | 17.0m | - | - | - |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
