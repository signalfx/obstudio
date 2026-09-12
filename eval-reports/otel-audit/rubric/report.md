# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20260911T185434429109Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/audit | go/chi-basic | 2 | 78% (14/18), avg score 81 | 3.2M | 18.6m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/audit | go/chi-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 3129721 | 2917120 | unknown | 44256 | 17035 | unknown | 3173977 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/audit | go/chi-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 462316 | 321280 | unknown | 10082 | 5080 | unknown | 472398 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | direct | rubric:rubric-7 FAIL | otel.html findingNextStep returns strings such as 'Select this finding, then copy and run the generated $otel-instrument command.' |
| with_skill | go/chi-basic | with_skill | direct | rubric:rubric-9 FAIL | last_message.md contains 'Blocked: sandbox denies loopback bind...' and a local filesystem otel.html link, not 'Review report: [otel.html](http://127.0.0.1:<port>/<token>/otel.html)'. |
| with_skill | go/chi-basic | with_skill | readiness-review | rubric:rubric-7 FAIL | `otel.html` `findingNextStep()` returns strings such as `Select this finding, then copy and run the generated $otel-instrument command.` |
| with_skill | go/chi-basic | with_skill | readiness-review | rubric:rubric-9 FAIL | `last_message.md` contains `Blocked: loopback report server startup is denied by this sandbox...` rather than `Review report: [otel.html](http://127.0.0.1:<port>/<token>/otel.html)`. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
