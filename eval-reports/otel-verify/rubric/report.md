# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20261001T191036539613Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | 1 | 80% (4/5), avg score 84 | 3.6M | 11.3m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 3571907 | 3403136 | 0 | 22744 | 8236 | unknown | 3594651 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 853652 | 756352 | 0 | 9696 | 4869 | unknown | 863348 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | canonical-proof-packet | rubric:rubric-5 FAIL | Trace shows `render-instrumentation-html ... -o .observe/otel-instrumentation.html ... --verify-json ...` wrote both `.observe/otel-instrumentation.html` and `.observe/otel.html`; the report also states both HTML files were regenerated at Oct 1 12:16:18 2026. In `service/.observe/otel.html`, `DATA.selection.requeste... |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
