# Skill workflow validation

## Revision and preservation

Work started from a fresh clone of remote `main` at
`f56299311afa7c62c9896de1aa76d4ff5a22106f`; the remote head was rechecked and
unchanged before handoff. The original working checkout was left untouched.
All 15 extracted stage reference bodies were compared byte-for-byte with their
original sections. Public skill names, local discovery links, report schemas,
producer rules and original rubric criteria are retained. Plugin skill copies
are generated from the canonical source. Default `git diff --check` reports
blank separators at the ends of extracted references; these preserve original
section bytes. `git -c core.whitespace=-blank-at-eof diff --cached --check` passes;
no other whitespace errors are present.

## Rubric comparison

Each result is one representative Go chi-basic task, not a statistical guarantee
across languages or model versions. The installed Codex CLI was
`0.162.0-alpha.17.2`; baseline and candidate used the same CLI default model,
reasoning setting and isolated authenticated home. The report records model as
`-` because no explicit model was pinned.

| Skill | Clean-main original criteria | Candidate original criteria | New workflow criterion | Raw judge score, baseline → candidate |
|---|---:|---:|---:|---:|
| otel-audit | 10/11 | 11/11 | Pass | 96 → 100 |
| otel-instrument | 7/7 | 7/7 | Pass | 100 → 100 |
| otel-verify | 5/5 | 5/5 | Pass | 100 → 99 |

Audit's baseline failure concerned the existing GenAI No presentation. No
criteria were removed or weakened. Verification's one-point deduction concerned
omitted per-signal zero counts in the final chat response; the report retained
them and all original criteria passed. Consequently, original criterion pass
rates are preserved, but a claim that every numerical score increased or stayed
identical would be false.

Final rubric run IDs are `20261016T061547573822Z` (audit),
`20261016T061548674738Z` (instrument), and `20261016T061549808263Z` (verify).
Superseded runs interrupted after source changes are not the reported results.

The exact run config is committed at its recorded path,
`evals/.workspace/skill-observability-proof/evals.toml`, so source receipts can be
verified in a clean checkout without rewriting their fingerprints. No auth files
or run caches are committed. Its contents are:

```toml
[run]
mode = "with_skill"
[rubric]
enabled = true
[runtime]
enabled = false
[agent]
backend = "codex"
timeout = 1800
extra_args = ["--config", 'model_reasoning_effort="xhigh"', "--config", "sandbox_workspace_write.network_access=true"]
```

Commands below ran from `evals/`, with `UV_NO_CONFIG=1`,
`OBSTUDIO_SKILL_MCP_ENDPOINT=none`, an authenticated isolated `EVAL_CODEX_HOME`,
and the installed CLI on PATH. They deliberately did not publish eval runs into
the native demonstration Studio.

```sh
make eval-rubric SKILL=skills/otel-audit CASE=go/chi-basic PROMPT=direct EVAL_CONFIG=.workspace/skill-observability-proof/evals.toml EVAL_CODEX_HOME=/Users/tithumma/code/splunk/obstudio/.workspace/codex-evals/codex-home
make eval-rubric SKILL=skills/otel-instrument CASE=go/chi-basic PROMPT=direct EVAL_CONFIG=.workspace/skill-observability-proof/evals.toml EVAL_CODEX_HOME=/Users/tithumma/code/splunk/obstudio/.workspace/codex-evals/codex-home
make eval-rubric SKILL=skills/otel-verify CASE=go/chi-basic PROMPT=canonical-proof-packet EVAL_CONFIG=.workspace/skill-observability-proof/evals.toml EVAL_CODEX_HOME=/Users/tithumma/code/splunk/obstudio/.workspace/codex-evals/codex-home
```

## Deterministic and integration proof

The environment used Go 1.27.2, Node 24.19.0 and project-managed Python 3.11.
The Python eval virtual environment was first on PATH; system Python 3.9 is too
old for existing guidance tests. npm used the official registry because the
machine's inherited private registry was unavailable. A dependency reinstall
race between build and client tests was corrected by running those targets
sequentially. A final validation attempt also omitted Node from PATH; its two
Node subprocess checks failed with FileNotFoundError, then both passed after
restoring the configured Node runtime. No skill changes were needed.

| Command from repository root unless stated | Result |
|---|---|
| `cd observer && go test ./internal/mcp ./internal/store` | Pass; protocol, projection, recorder ingestion and telemetry evaluation tests |
| `make test` | Pass, full Go suite |
| `make vet` | Pass |
| `cd observer && go test -race ./internal/mcp ./internal/store` | Pass |
| `make build` | Pass; staged skills, client assets and binary |
| `cd observer/client && npx vitest run src/traces/TraceWaterfall.test.tsx` | 17 passed |
| `cd observer/client && npm run typecheck` | Pass |
| `make test-client` | 406 passed |
| `make test-pytest-plugin` | 217 passed |
| `make test-eval-harness` | 722 passed, 1 skipped; report freshness passed |
| `make test-interactive-otel-scripts` | Pass, including 8 recorder tests and 184 guidance checks |
| `make agent-policy-check` | Pass, 49 policy tests and 8 guideline checks |
| `claude plugin validate ./plugins/obstudio --strict` | Pass |
| `claude plugin validate .` | Pass |
| `make eval-validation SKILL=skills/otel-audit` | 611 passed, 1 skipped |
| `make eval-validation SKILL=skills/otel-instrument` | 631 passed, 1 skipped |
| `make eval-validation SKILL=skills/otel-verify` | 577 passed, 1 skipped |

Protocol proof covers HTTP and stdio using the same catalog, complete manifest
byte/digest checks, materialized remote helpers and validators for all three
skills, legacy tools, invalid-skill isolation, malformed requests, and concurrent
replay without duplicate metrics. Recorder tests exercise offline/redirect
failure, unsafe paths, cancellation, command failure, and concurrent writers.
Evaluation tests check real ingestion through the existing GenAI projection,
custom definitions, invalid rules, partial traces, missing retention, actual
zero versus unknown usage, and idempotent evaluation receipts. Changed-package
coverage was inspected to locate missed branches rather than target a global
percentage.

The final audit trajectory sanity command (from `evals/`) was:

```sh
make eval-sanity SKILL=skills/otel-audit CASE=go/chi-basic PROMPT=stage-path EVAL_CONFIG=.workspace/skill-observability-proof/evals.toml EVAL_CODEX_HOME=/Users/tithumma/code/splunk/obstudio/.workspace/codex-evals/codex-home
```

It passed all 5 checks, including loading guards, declared stage path and
independent report evidence. Instrumentation's existing smoke report was also refreshed with:

```sh
make eval-sanity SKILL=skills/otel-instrument CASE=sanity/skill-smoke EVAL_CONFIG=.workspace/skill-observability-proof/evals.toml EVAL_CODEX_HOME=/Users/tithumma/code/splunk/obstudio/.workspace/codex-evals/codex-home
```

Both existing prompts passed. The reusable harness also tests independent
command witnesses rather than accepting a journal's execution claim alone.

## Ordinary execution demonstration

A separate copy of the demo application ran ordinary CLI prompts containing
only `$otel-audit`, `$otel-instrument`, or `$otel-verify`, outside the eval runner.
The local recorder exported to an isolated Studio at `127.0.0.1:3006`. Its Go
integration driver used the real production MCP/API/store/web/OTLP packages
without registering global runtime state or cloud credentials. Native provider
OTel exporters were disabled only for those individual processes; existing
user configuration was preserved.

Audit recorded a passed workflow. Instrumentation initially recorded Partial
when the app exported to the isolated receiver but the agent inspected a
different Studio. A later ordinary verification used the correct MCP endpoint
and passed 16/16 application telemetry items. The initial errors and recovered
attempts remain visible rather than being relabeled as successful history.
The resulting application code, report, CLI output and workflow journals were
retained locally under the isolated demo and ignored workspace proof directory.

After replaying those journals through the current server, all four retained
runs appeared as GenAI workflow traces. Actual commands became tool spans;
checkpoints remained ordinary instantaneous spans. No model calls or tokens
were synthesized. Custom rules against the stored audit telemetry returned:
Go branch Pass, report command under 1500 ms Pass (490.084 ms measured), and
discovery command latency Unknown because discovery was a checkpoint. Default
evaluations exposed real command failures on instrumentation/verification runs.

UI inspection exercised trace selection, the workflow graph and its evaluation
issue action, which opens named evaluation explanations. Screenshots cover
756×923, a live resize to an actual 716×863 constrained viewport, and
1100×850. A requested 360×740 override was clamped by the embedded host, so
360-pixel support is not claimed. The changed token summary remained legible
without page horizontal overflow at the recorded widths. Temporary viewport
overrides were reset. The standalone app exposes the existing dark theme; no
light-theme or editor-host rendering claim is made.

## Limits and review boundary

The design and telemetry contract are described in
[the implementation plan](skill-workflow-observability.md). Request human review
of the stage contract, optional SEP adapter, and measurement/evaluation boundaries
before merging this architectural change.

Native SEP-2640 loading/activation has not been demonstrated in Codex or Claude;
the adapters were exercised at the server protocol and materialized-bundle
boundaries. Claude manifest validation is not an execution proof. No formal
upstream conformance suite, Windows runtime, editor extension host, Docker
runtime eval, live provider-token correlation, or Galileo/Splunk cloud receipt
was exercised. Representative Go evals do not establish all-language quality.
Checkpoints, root outcomes and digest identity remain recorder reports rather
than independent evidence of everything the host or model did. Missing telemetry
cannot be graded as success. Bounded Studio memory can evict observations; replay
can restore retained local journals, and explicit Clear still clears telemetry.
