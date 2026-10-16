# Repeated audit accuracy challenge

This opt-in experiment compares two frozen `otel-audit` versions on six new
synthetic Go/Python applications, twice per version and application. It does
not modify either skill. The original ceiling experiment and this challenge
remain separate; neither benchmark establishes performance on arbitrary
production repositories.

The frozen protocol is
[`docs/skill-workflow-accuracy-challenge-protocol.json`](../../../docs/skill-workflow-accuracy-challenge-protocol.json).
It declares the inputs, expected defects and covered predicates, primary
metric, diagnostic exclusion, two grading passes, unresolved-result policy,
application-cluster confidence interval, and acceptance gate before task
outputs. The SDK environment-resource predicate was examined in the earlier
experiment and is excluded from the primary score here.

`probes/` is never copied into the audited service. Those probes execute actual
application functions with real SDK in-memory exporters/readers. They prove
the exercised span relationships, names, status/events, resource fields, and
selected metric attributes. They do not prove OTLP delivery, HTTP transport,
all startup/shutdown interleavings, or cloud ingestion. Missing-provider and
missing-dependency facts also use the frozen source/manifests. The controls
are healthy for the declared predicates, not a claim that no other useful
observability improvements exist.

Each audit receives only `$otel-audit` in a new workspace with its selected
skill bundle. Model, effort, timeout, and runtime are held fixed. The explicit
native provider exporters and the skill recorder exporter are disabled for
this experiment; CLI usage records are not presented as Studio OTel.

Two fresh model grading sessions receive anonymized paired reports, source,
frozen expectations, and SDK capture evidence. Version labels and skill
bundles are withheld. They must classify every declared predicate and every
finding's material factual premises. This is model-assisted grading, not
independent human review. Disagreements remain unresolved and block a
superiority claim for unit predictions; unsupported finding premises count
conservatively in the factual support rate. A true gap can still have an
incorrect explanation. Optional recommendations with accurate premises are
not false findings merely because they are optional.

The local research runner is `evals/audit_accuracy.py`; its frozen execution
version is identified by the protocol hash and Git history. From the repository
root, with the documented eval venv and local Go/Codex runtimes available:

The runner resolves `codex`, `go`, and `node` from `PATH`. Set
`AUDIT_ACCURACY_CODEX_BIN` or `AUDIT_ACCURACY_GO_BIN` to select executable
paths explicitly; `AUDIT_ACCURACY_NODE_BIN` selects the Node binary directory.
The published experiment's exact runtime versions and execution harness hashes
are retained in the results ledger. After execution completed, machine-specific
tool paths were replaced with this discovery; the grading prompt, schema,
scoring functions, frozen source, and acceptance gate were unchanged.
Python truth probes also reject installed SDK versions that differ from the
fixture's pinned requirements; use a matching environment before running them.

```sh
evals/.venv/bin/python3 evals/audit_accuracy.py prepare --workspace /tmp/audit-accuracy-new
evals/.venv/bin/python3 evals/audit_accuracy.py truth --workspace /tmp/audit-accuracy-new
evals/.venv/bin/python3 evals/audit_accuracy.py run --workspace /tmp/audit-accuracy-new --codex-home /path/to/isolated/authenticated/codex-home --workers 4
evals/.venv/bin/python3 evals/audit_accuracy.py grade --workspace /tmp/audit-accuracy-new --codex-home /path/to/isolated/authenticated/codex-home --workers 4
evals/.venv/bin/python3 evals/audit_accuracy.py summarize --workspace /tmp/audit-accuracy-new
```

`prepare` requires an absent output directory and freezes source hashes. The
audits and graders are resumable by completed result files; retain failures
and timeouts. Do not remove failing cases, change skill versions, or tune
scoring after seeing task output. Incomplete execution, changed application
source, missing findings, or unresolved predicate grading cannot establish
superiority.
