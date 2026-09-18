# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20260918T173856845760Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/audit | go/chi-basic | 2 | 85% (17/20), avg score 84 | 4.4M | 20.6m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/audit | go/chi-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 4337047 | 4115328 | 0 | 45899 | 17825 | unknown | 4382946 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/audit | go/chi-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 1025624 | 842752 | 0 | 14888 | 6917 | unknown | 1040512 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | direct | rubric:rubric-5 FAIL | A search of `otel-audit.json` and `otel.html` found only generic `chi/net/http` wording, not `otelhttp` or `otelchi`. |
| with_skill | go/chi-basic | with_skill | direct | rubric:rubric-9 FAIL | `last_message.md` says `Rendered report: [otel.html](/var/.../service/.observe/otel.html)` and adds a second paragraph about loopback startup being blocked. It is not the required one-line loopback URL from `finalize-audit`. |
| with_skill | go/chi-basic | with_skill | readiness-review | rubric:rubric-9 FAIL | last_message.md says finalize-audit was blocked, links local otel.html and otel-audit.json paths, and mentions validation counts instead of exactly 'Review report: [otel.html](http://127.0.0.1:<port>/<token>/otel.html)'. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
