# OpenTelemetry logging skill analysis

Analysis date: 2026-11-08. Repository: https://github.com/signalfx/obstudio.
Baseline commit: `4e1e51f300510b26114fdc1b5ef528b3b6f09760`.
Working branch: `codex/otel-logging-rules` in a separate fresh clone.

This document preserves the original six-rule assessment and its test results.
The [current remediation report](logging-rules-and-remediation-report.md)
records the additional async and verification rules, review fixes and latest
three-trial results for all four languages.

## Assessment

The audit and instrumentation skills already cover the core application-log
pipeline: detecting supported bridges, preserving provider ownership and
stdout/file sinks, local OTLP destination and protocol, preventing inherited
cloud credentials, explicit opt-out, duplicate prevention, privacy, resource
identity, in-span correlation, and shutdown/full-runtime verification. It would
be inaccurate to describe logging as wholly missing.

Local-only export is a Splunk Observability Studio product constraint, not a
universal OTel prohibition on sending logs to cloud backends. Privacy capture
decisions likewise follow the application's explicit policy.

Six areas need more explicit, shared rules and acceptance evidence. They are
implemented in [logging-readiness.md](../skills/references/logging-readiness.md)
and routed from both skills. The plugin copies are generated from canonical
sources. Existing language recipes and application runtime behavior are retained.

| Rule | Baseline evidence and actual omission | Required decision/proof |
|---|---|---|
| LOG-RECORD | Audit log inventory and runtime guidance say severity/body, and Java prints `severityNumber`; none distinguishes occurrence time from `ObservedTimestamp` or specifies numeric mapping/precision. | Preserve occurrence and observation semantics; validate bridge level mapping and exact timestamp representation. |
| LOG-CONTEXT | In-span correlation is required; unsampled behavior, trace flags and post-detach/concurrent isolation are not explicit. | Exact sampled/unsampled/no-context identities and flags; preserve supported explicit trace-based filtering. |
| LOG-EXCEPTION | Final-pipeline privacy is covered, but exception log attribute names and applicability to existing bridges versus new instrumentation are absent. | Correct permitted exception fields, no disallowed message/stack capture, no forced event-name or span-event migration for a bridge. |
| LOG-LIMITS | Generic bounded/privacy guidance exists; log-specific attribute settings and their inability to bound Body are absent. | Effective supported log limits, separate Body policy when needed, oversize/drop accounting, respect adequate defaults. |
| LOG-DELIVERY | Batching/shutdown are covered; log-specific BLRP controls, bounded-queue loss and partial-success accounting need explicit acceptance. | Batch within queue capacity, bounded fault/shutdown behavior, distinguish attempted/accepted/rejected/dropped and healthy duplicate checks from delivery guarantees. |
| LOG-DIAGNOSTICS | Go already warns about a specific slog/default-logger recursion path; a cross-language exporter-diagnostics outage rule is absent. | Separate/suppressed diagnostics, bounded attempts and continued application, sink and unrelated-signal operation. |

[Source evidence](logging-skill-analysis-evidence.json) records SHA-256 hashes
for every reviewed baseline Markdown file under the two skills and shared
references, plus matching file/line evidence. The baseline has zero explicit
occurrence-versus-observed-time, log-specific limit, BLRP, unsampled-policy or
exception-field matches; one numeric-severity match is Java's inspection
example, and the meaningful logger-recursion match is the existing Go warning.
Search absence proves the missing explicit guidance, not an SDK defect or a
model's inability to infer a correct answer.

The zero-match portion can be reproduced against the immutable baseline with
the following command (exit 1 means no matches):

```sh
git grep -n -E 'ObservedTimestamp|OTEL_LOGRECORD_ATTRIBUTE|OTEL_BLRP|unsampled|trace_based|exception\.(type|message|stacktrace)' \
  4e1e51f300510b26114fdc1b5ef528b3b6f09760 -- \
  'skills/otel-audit/*.md' 'skills/otel-instrument/*.md' 'skills/references/*.md'
```

The rules distinguish OTel SDK-author requirements from application-owned
work. A correct SDK default is coverage. Optional fields are not automatically
gaps. Exception-event conventions have applicability and development features;
ordinary logging bridges must retain their own supported semantics. Sources:
[data model](https://opentelemetry.io/docs/specs/otel/logs/data-model/),
[Logs SDK](https://opentelemetry.io/docs/specs/otel/logs/sdk/),
[SDK environment variables](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/),
[exception logs](https://opentelemetry.io/docs/specs/semconv/exceptions/exceptions-logs/),
[error handling](https://opentelemetry.io/docs/specs/otel/error-handling/), and
[privacy](https://opentelemetry.io/docs/security/handling-sensitive-data/).

## Test design and proof boundaries

Eight new rubric definitions exercise both skills for Java/Spring Boot,
Python/Flask, Go/chi and Node.js/Express, with three repeated trials each.
The model must inspect actual baseline source separately from an explicitly
synthetic candidate overlay. Six faulty observations cover the rules; four
controls cover adequate SDK defaults, explicit supported filtering, ordinary
messages without EventName, and privacy-preserving bridged exceptions.
The task is deliberately plan-only: these semantic tests establish audit and
repair-plan decisions, not code application or collector/cloud delivery.

Separate real SDK/bridge suites run three times each in fresh processes.
Each has six tests: severity/timestamp, sampled/unsampled/detached context,
concurrent context isolation, attribute limits and type-only exception policy,
bounded exporter failure with original sink retained, and bridge opt-out.
They execute real SDK processors and native Python logging, Go slog, Node
Winston and Java Logback bridges. Historical timestamp precision in Node and
the size-limit accounting subcases additionally exercise the SDK directly.
The fault exporter returns failure without a network receiver. The opt-out
test exercises the bridge-omission branch; it does not prove an application's
environment-variable parser. Privacy tests prove type-only omission and do
not claim comprehensive redaction of arbitrary application payloads.

| Language | Runtime and tested packages | Trial 1 | Trial 2 | Trial 3 |
|---|---|---|---|---|
| Java | Microsoft JDK 17.0.21; SDK 1.68.0; Logback 1.6.6; appender 2.33.1-alpha | 6/6 | 6/6 | 6/6 |
| Python | CPython 3.12.11; SDK 1.45.1; logging bridge 0.66b1 | 6/6 | 6/6 | 6/6 |
| Go | Go 1.25.0; SDK/log 0.20.0; core 1.44.0; otelslog 0.19.0 | 6/6 | 6/6 | 6/6 |
| Node.js | Node 24.22.1; API 1.10.0; SDK 3.1.0; Winston transport 0.35.0; Winston 3.19.0 | 6/6 | 6/6 | 6/6 |

All 72 runtime test executions passed. The native suites are reproducible with
[run_logging_contract.py](../evals/run_logging_contract.py); its JSON output
records every exact command, directory, duration, exit code and log path.

## Semantic trial results

Final frozen revision: **24/24 semantic cases passed; 168/168 rubric criteria passed**. Every trial actually read the logging reference, and its staged reference hash matches the final canonical source. Agent and judge both used the repository default `gpt-6.1-sol` in separate contexts. Scores below are quality scores out of 100, not counts of passing checks.

| Language | Audit trials 1 / 2 / 3 | Instrumentation trials 1 / 2 / 3 | Native SDK checks per trial |
|---|---|---|---|
| Java | PASS (99) / PASS (98) / PASS (98) | PASS (96) / PASS (98) / PASS (98) | 6/6, 6/6, 6/6 |
| Python | PASS (100) / PASS (100) / PASS (100) | PASS (100) / PASS (100) / PASS (100) | 6/6, 6/6, 6/6 |
| Go | PASS (100) / PASS (95) / PASS (100) | PASS (100) / PASS (98) / PASS (98) | 6/6, 6/6, 6/6 |
| Node.js | PASS (100) / PASS (100) / PASS (98) | PASS (98) / PASS (100) / PASS (96) | 6/6, 6/6, 6/6 |

Both final rubric run IDs are `20261108T145455476696Z`, under separate skill directories. [Machine-readable results](logging-skill-test-results.json) retain every final grade, earlier failed grade, source-reference hash, and the native command results. The generated latest [audit report](../eval-reports/otel-audit/rubric/report.md) and [instrumentation report](../eval-reports/otel-instrument/rubric/report.md) contain full run and token provenance. Judge `overall_pass` and individual rubric checks are the semantic result; pytest process completion alone is not a semantic pass.

The generated reports show a `Workers: 1` header; the actual execution logs
record four pytest workers, matching the exact Make commands below. Case
counts and grades were independently checked from every case artifact.

The exploratory unchanged-skill audit run was
`20261108T143553967113Z`: Go 98/pass, Python 100/pass, Java 90/fail and
Node 94/fail. Its SDK-default control had an ambiguous policy scope; the
fixture was corrected before the main repeated trials. That exploratory run
is not a controlled before/after comparison and does not establish skill lift.

The first updated round passed 10/12 audit cases and 9/12 instrumentation cases. Audit Java trial 3 omitted acceptance details for async context, batching and outage isolation; Node trial 2 omitted the unrelated-signal outage assertion. Instrumentation Go trial 1 omitted the batch/queue assertion; trial 3 omitted the unrelated-signal outage assertion; trial 2 declined to classify an ambiguously named exported timestamp. The final fixture now supplies the exact OTLP `time_unix_nano` field, and the rule reference now requires a compact, explicit acceptance handoff. The report allowance increased from 1200 to 1600 words to avoid squeezing out proof obligations. These changes prevent a controlled skill-lift claim. Earlier failures remain recorded rather than being relabeled as successes.

## Validation commands

Run from the clone root. `UV_NO_CONFIG=1` selects public package resolution for
these commands without changing the user's expired private-index settings.
`PYTHON="$PWD/evals/.venv/bin/python"` selects the required modern Python;
the host's system Python 3.9 cannot execute existing `zip(strict=True)` code.

```sh
UV_NO_CONFIG=1 make eval-validation SKILL=skills/otel-audit
UV_NO_CONFIG=1 make eval-validation SKILL=skills/otel-instrument
UV_NO_CONFIG=1 make eval-rubric SKILL=skills/otel-audit EVAL_PATTERN='*/*/eval/qual/logging-audit-contract.json' EVAL_WORKERS=4
UV_NO_CONFIG=1 make eval-rubric SKILL=skills/otel-instrument EVAL_PATTERN='*/*/eval/qual/logging-instrument-contract.json' EVAL_WORKERS=4
UV_NO_CONFIG=1 make eval-sanity SKILL=skills/otel-audit EVAL_WORKERS=2
UV_NO_CONFIG=1 make eval-sanity SKILL=skills/otel-instrument EVAL_WORKERS=2
make agent-policy-check PYTHON="$PWD/evals/.venv/bin/python"
make check-eval-models PYTHON="$PWD/evals/.venv/bin/python"
UV_NO_CONFIG=1 make test-interactive-otel-scripts PYTHON="$PWD/evals/.venv/bin/python"
make check-obstudio-plugin-skills
UV_NO_CONFIG=1 make test-eval-harness
git diff --check
```

| Validation | Result |
|---|---|
| Audit rubric | 12/12 cases, 84/84 criteria passed |
| Instrumentation rubric | 12/12 cases, 84/84 criteria passed |
| Native matrix | 12 fresh processes, 72/72 test executions passed |
| Audit validation | 666 passed, 1 optional module skipped |
| Instrumentation validation | 697 passed, 1 optional module skipped |
| Audit / instrumentation sanity | 2/2 each passed |
| Agent policy | 49 unit tests, 8 guideline contracts and policy check passed |
| Eval model policy | 9 unit tests passed; models/effort match repository defaults |
| Interactive OTel checks | 280 unit tests and 188 guidance tests passed |
| Full eval harness | 26 report source manifests verified; 813 passed, 1 optional module skipped |
| Plugin skill parity | Passed |
| Skill frontmatter validation | Both changed skills passed |
| Go race detector | Passed |
| Diff whitespace | Passed |

The optional skipped module is the unrelated LangChain/Splunk AO fixture; its
optional dependencies are absent. The one warning is expected dropped-log-
attribute accounting exercised by the new limits test, not a failed check.
The additional focused race command was:

```sh
GOTOOLCHAIN=local "$HOME/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.25.0.darwin-arm64/bin/go" \
  -C evals/go/logging-contract test -race -count=1 ./...
UV_NO_CONFIG=1 uv run --directory evals --with pyyaml python \
  "$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py" ../skills/otel-audit
UV_NO_CONFIG=1 uv run --directory evals --with pyyaml python \
  "$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py" ../skills/otel-instrument
```

For runtime suites, use installed Go/Maven/JDK paths, or the task-local paths
recorded in the results:

```sh
UV_NO_CONFIG=1 uv run --directory evals python run_logging_contract.py \
  --go $HOME/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.25.0.darwin-arm64/bin/go \
  --maven "$PWD/.workspace/logging-analysis/toolchains/maven/apache-maven-3.9.11/bin/mvn" \
  --java-home "$PWD/.workspace/logging-analysis/toolchains/jdk/jdk-17.0.21.0.2+1/Contents/Home" \
  --maven-settings "$PWD/.workspace/logging-analysis/public-maven-settings.xml" \
  --output "$PWD/.workspace/logging-analysis/runtime-results"
```

Maven settings for this task point only to public Maven Central, bypassing the
expired private mirror for public dependencies without modifying user settings.
All nine repository skills were installed from the baseline revision, then the two revised entrypoints and shared logging rules were synchronized. At this initial assessment, all 65 installed skill/reference files matched that source snapshot. The current remediation report records the later 70-file installation verification. Prior
installation content is retained under
`~/.codex/skill-backups/obstudio-before-logging-analysis-20261108`.

## Limits and remaining proof

This section describes the initial assessment. The current remediation report
adds local OTLP wire, partial-success, outage, overload and real-span correlation
evidence, with its own explicit limits.

No full Spring Boot/Java-agent, Flask, chi or Express application was launched
for the initial rules. No collector, cloud delivery, OTLP wire partial-success,
real receiver outage, queue-overload durability, framework startup or
end-to-end trace/metric continuity claim follows from the focused suites.
Application-specific full-runtime acceptance remains required where
the rules select such a change. Go/Java/Node/collector product builds and UI
tests are outside the skill-only change; the new native fixtures are compiled
or executed separately. Three repetitions measure this test corpus, not all
future applications or universal best-practice compliance.
