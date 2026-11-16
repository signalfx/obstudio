# otel-audit Sanity Codex Eval Report

Evaluated source: `7db9a57ada23292c0047e9d5cac24fbf0208847b`. Case outcomes: 2 passed. These are the saved run's results; no actor or judge was rerun for this publication.

Some skill or eval inputs have changed since this run. These results describe the source above, rather than the latest PR revision.

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | sanity |
| Skill | otel-audit |
| Run ID | 20261116T170554Z-consolidated-report |
| Agent model | gpt-6.1-sol |
| Workers | 8 |
| Config | evals/codex-evals.logging.toml |

## Sanity Summary

| Mode | Eval | Service | Prompts | Case outcomes | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/audit | sanity/skill-smoke | 2 | 2 passed | 100% (6/6) | 172.6K | 30.2s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | sanity/skill-smoke/sanity/audit | sanity/skill-smoke | with_skill | codex | cumulative | measured | 2/2 recognized | 172390 | 76928 | 0 | 173 | 60 | unknown | 172563 |

## Sanity Failures

No sanity failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
