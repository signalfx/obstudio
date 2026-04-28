# otel-audit Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Modes | ab |
| Eval kind | sanity |
| Skill | otel-audit |
| Run ID | 20260428T192400828790Z |
| Agent model | gpt-5.5 |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Validation

| Eval | Service | Prompts | Eval File | Deterministic Checks | Qualitative Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| sanity/skill-smoke/audit_sanity | sanity/skill-smoke | 2 | evals/sanity/skill-smoke/audit_sanity_eval.json | 0 | 0 | 0 |

## Deterministic

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| ab | sanity/skill-smoke/audit_sanity | sanity/skill-smoke | 2 | 100% (4/4) | 53.1K | 17.6s | 100% (6/6) | 48.6K | 14.9s |

### Deterministic Failures

No deterministic failures.

## Qualitative

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| ab | sanity/skill-smoke/audit_sanity | sanity/skill-smoke | 2 | - | 53.1K | 17.6s | - | 48.6K | 14.9s |

### Qualitative Failures

No qualitative failures.

## Runtime

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| ab | sanity/skill-smoke/audit_sanity | sanity/skill-smoke | 2 | - | 53.1K | 17.6s | - | 48.6K | 14.9s |

### Runtime Failures

No runtime failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
