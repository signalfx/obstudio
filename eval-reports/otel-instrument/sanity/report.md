# otel-instrument Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Modes | ab |
| Eval kind | sanity |
| Skill | otel-instrument |
| Run ID | 20260428T192400828790Z |
| Agent model | gpt-5.5 |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Validation

| Eval | Service | Prompts | Eval File | Deterministic Checks | Qualitative Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| sanity/skill-smoke/instrument_sanity | sanity/skill-smoke | 2 | evals/sanity/skill-smoke/instrument_sanity_eval.json | 0 | 0 | 0 |

## Deterministic

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| ab | sanity/skill-smoke/instrument_sanity | sanity/skill-smoke | 2 | 100% (4/4) | 54.5K | 22.0s | 100% (6/6) | 48.6K | 15.3s |

### Deterministic Failures

No deterministic failures.

## Qualitative

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| ab | sanity/skill-smoke/instrument_sanity | sanity/skill-smoke | 2 | - | 54.5K | 22.0s | - | 48.6K | 15.3s |

### Qualitative Failures

No qualitative failures.

## Runtime

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| ab | sanity/skill-smoke/instrument_sanity | sanity/skill-smoke | 2 | - | 54.5K | 22.0s | - | 48.6K | 15.3s |

### Runtime Failures

No runtime failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
