# otel-instrument Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Modes | ab |
| Eval kind | sanity |
| Skill | otel-instrument |
| Run ID | 20260428T234104290071Z |
| Agent model | gpt-5.5 |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Validation

| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| sanity/skill-smoke/sanity/instrument | sanity/skill-smoke | 2 | evals/sanity/skill-smoke/eval/sanity/instrument.json | 0 | 0 | 0 |

## Sanity Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| ab | sanity/skill-smoke/sanity/instrument | sanity/skill-smoke | 2 | 100% (4/4) | 54.6K | 19.2s | 100% (6/6) | 48.6K | 13.4s |

## Sanity Failures

No sanity failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
