# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20261001T175940988475Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | 1 | 80% (4/5), avg score 88 | 2.9M | 12.1m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2838414 | 2643072 | 0 | 23930 | 7303 | unknown | 2862344 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 566027 | 498560 | 0 | 11366 | 7349 | unknown | 577393 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | canonical-proof-packet | rubric:rubric-5 FAIL | `otel-verify.md` lists `render-html .observe/otel-audit.json -o .observe/otel.html` as a Pass command, and `.observe/otel.html` has a fresh timestamp. The refreshed instrumentation HTML is present and the canonical proof JSON is preserved. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
