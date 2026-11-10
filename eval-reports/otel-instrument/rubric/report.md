# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261110T191507611780Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-instrument-contract | go/chi-basic | 1 | 64% (9/14), avg score 78 | 6.3M | 20.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-instrument-contract | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 6238260 | 6101120 | 0 | 42927 | 10027 | unknown | 6281187 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-instrument-contract | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1988363 | 1828480 | 0 | 8905 | 3166 | unknown | 1997268 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | logging-trial-1 | rubric:rubric-2 FAIL | .observe/otel-instrumentation.md:135-154 leaves multiple numeric/enum branches future-only. Its certificate row says HTTP does not use TLS certificates, but installed loadEnvTLS constructs TLS configuration and newHTTPClient rejects its combination with the selected insecure endpoint, disabling local log export. |
| with_skill | go/chi-basic | with_skill | logging-trial-1 | rubric:rubric-9 FAIL | The report gives count=128 and value length=-1 but leaves depth and combined diagnostic cadence unproven. Installed record.go has a package-wide sync.OnceFunc for count-limit diagnostics; attrnorm.TruncateValue recursively handles supported values without emitting diagnostics or enforcing depth. These distinctions a... |
| with_skill | go/chi-basic | with_skill | logging-trial-1 | rubric:rubric-10 FAIL | TestLogDeliveryControls records N=2 with accepted/rejected counts 2/0, 1/1 and 2/0. verify_runtime.py:156-161 checks final body/count/severity and service filtering, but not its environment/version or absent context. The report lists a 60-second retry elapsed setting without resolving the loop's max(backoff, throttl... |
| with_skill | go/chi-basic | with_skill | logging-trial-1 | rubric:rubric-13 FAIL | TestResourceMerge tests resource-only identity through the helper. Every verify_runtime.py trial explicitly sets OTEL_SERVICE_NAME, and the host run also supplies it. No normal-launch receipt exercises resource-only service.name or the go-chi-basic fallback. |
| with_skill | go/chi-basic | with_skill | logging-trial-1 | rubric:rubric-14 FAIL | LOG-SPEC-CLOSURE primarily binds hashed logging-readiness.md excerpts rather than retained primary clauses. The transport row does not separately dispose the semantics-preserving reduction SHOULD, diagnostic-trimming MAY and cross-surface configurability SHOULD. Configuration equivalence, SDK-disabled propagation, p... |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
