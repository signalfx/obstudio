# OpenTelemetry logging rules and remediation

Nine shared rules guide `otel-audit`, `otel-instrument` and `otel-verify` for
Java, Python, Go and Node.js. They resolve the application's actual logger,
collection owner, installed SDK, configuration and lifecycle instead of imposing
a framework, constructor, timeout, limit value or eval-fixture recipe.

Current instruction identity: `950c7404dd4d7b1b7f3067f6312988e37251b030bb2166616e5a75c65a421516`. Source commit: `e72f203b`.
The three-fresh-workflow gate is **0/3**, with all four languages running in
parallel. The final whole-PR combined Codex and Claude Desktop review has not
started; it follows three consecutive clean passes on unchanged source.

## Rules added and gaps fixed

| Rule | Gap fixed | Required behavior and proof |
|---|---|---|
| `LOG-RECORD` | Incorrect severity, time or structured-value mapping; optional fields treated as mandatory. | Test the actual bridge and resolved dependency. Preserve supported values and occurrence/observation meaning; classify unsupported mapping honestly. |
| `LOG-CONTEXT` | Nonempty IDs mistaken for correlation; valid INTERNAL spans rejected by SERVER-only expectations. | Join canonical IDs to the exact associated real SDK span and verify its request ancestry, flags and Resource. Respect explicit caller-side capture. |
| `LOG-ASYNC-HANDOFF` | Context lost or leaked across workers, callbacks or logging queues. | Capture before dispatch when needed, reuse verified propagation, restore state, and test concurrent request pairing through the owned async path. |
| `LOG-EXCEPTION` | Framework/formatter content escaped selected privacy checks. | Check all captured renderers and sinks at the policy-required boundary. Preserve permitted diagnostics while removing forbidden content; a decision-only filter is not redaction. |
| `LOG-LIMITS` | Span limits substituted for log limits; arbitrary Body caps; expensive disabled-log construction. | Resolve accessible effective log-limit values, precedence and source evidence separately from future runtime boundaries and selected Body policy. Test boundary values and native enablement without suppressing an enabled original sink. |
| `LOG-DELIVERY` | Enqueue/flush, wire receipt or partial success mistaken for acceptance; retry and shutdown budgets confused. | Bound the whole selected operation. Separate emissions, attempts, copies, acknowledgements and persistence; retain legitimate unknowns and record known failure/retry outcomes. Never retry populated partial success. |
| `LOG-DIAGNOSTICS` | Export errors could recurse into the same bridge or leave cross-signal outage claims unproven. | Use an independent diagnostic route; prove bounded failures, application/native-sink progress and applicable configured-signal isolation. |
| `LOG-VERIFY-FRESH` | Stale receipts, skipped tests or zero exits mistaken for current proof. | Bind source, dependencies, commands and actual counts. Retain exact evidence for the current run and verify the generated service independently. |
| `LOG-SPEC-CLOSURE` | A thematic checklist omitted clauses or assigned SDK duties to the application. | Reconcile source, strength, maturity, applicability, owner, disposition and proof boundary in canonical reports. Local workflow/privacy policy stays distinct from OTel requirements. |

## Why guidance was missed and how the change prevents it

Trace correlation and preserving original sinks were already required. The
missing safeguard was complete reconciliation between source guidance, installed
capability, the selected application path and actual evidence. Nonempty or
injected IDs could look correct while tracer startup or span export was broken.
Theme summaries could omit conditional clauses or assign an SDK duty to the
application. Aggregate passing tests could hide an untested control.

A reproduced plan defect supplied a unit-suffixed value to an installed
integer-only environment parser, which would fall back to a different timeout.
The retained source/proposal evidence and reviewed inherited obligations are in
[source evidence](logging-skill-analysis-evidence.json); this is a plan/source
observation, not a claim that the baseline app already ran that configuration.

The skills now bind applicable clauses to primary sources, requirement strength,
feature maturity, owner and disposition. A precisely retained source excerpt or
specific immutable audit evidence row can preserve those clauses without lossy
re-summarization. Installed capability and runtime outcomes are refreshed
separately. A supported SDK default is valid coverage; an optional feature or
upstream limitation is not automatically missing application wiring.

Concrete repair plans must match the detected public API, option units and
effective configuration precedence. Source review now follows applicable normative
imports, including the [common configuration type contract](https://opentelemetry.io/docs/specs/otel/configuration/common/)
referenced by SDK environment settings. It checks accepted value representation,
ranges, fallback, zero-timeout and enum behavior; a unit label alone does not
establish that a proposed serialized value is accepted. Language checks describe context propagation,
record conversion, native capture and lifecycle pitfalls. They do not prescribe
specific framework hooks, SDK constructors, fixture budgets or payload counts.
Existing setup examples remain conditional on the detected stack. Concrete
regression inputs and expectations live in eval fixtures and rubrics. Available
configuration facts are resolved now; an unexecuted boundary test does not justify
deferring installed defaults that can already be inspected.

Correlation proof joins canonical log TraceId/SpanId/flags to exact real SDK
spans, with ancestry and Resource checks. An owned async handoff and its received
worker/callback log must occur in the same scenario. Concurrent, unsampled,
outside-context, reuse and supported failure/cancellation controls retain their
actual scope. A focused SDK test cannot establish normal application startup.

Reports reconcile each required control with its configuration, named assertion,
output and verdict. Grouped or parameterized presentation is allowed when every
member remains addressable. Early planning is recommended; a later complete,
independently contract-derived reconciliation is valid. Tool-call order alone
does not establish a correctness defect. Directly proven item claims can coexist with incomplete related
scenario coverage; a broader lifecycle claim still needs its own drain proof.
Every promised operation maps to an addressable control, and one scalar proof
level covers every assertion in its scenario. Repeated-stop proof retains
same-process delivery while final logging/drain is active and the actual chosen
shutdown policy. The Python fixture explicitly documents its non-interrupting
repeated-stop guarantee as local operator policy, with deliberate forced exit
outside that guarantee; it is not an OTel signal-handler requirement.
Verdicts follow evidence rather than report-helper syntax or aggregate counts.

Delivery reporting derives counts from each decoded request and response before
summing trials. It separates emissions, attempts, received copies, acknowledged
acceptance, rejection, local drops and persistence. Full success acknowledges
N/0; valid partial success acknowledges (N-R)/R; populated partial success,
including warning-only R=0, is not retried. Client terminal results remain
separate from server response intent and lifecycle wait duration. These
[OTLP semantics](https://opentelemetry.io/docs/specs/otlp/) do not promise durable
or exactly-once application delivery.

Privacy and destination choices remain explicit local policy. Supported native
hooks must preserve permitted diagnostics, original sinks and application
behavior at the selected capture boundary. Optional fields, SDK defaults and
Development capabilities are not universal application requirements. Common
attribute-limit diagnostic permissions and ceilings remain distinct from the
Logs SDK's discard recommendation. The [source evidence](logging-skill-analysis-evidence.json)
retains scoped observations and the 183-clause primary-source inventory.

## Replacement evals and current results

The PR replaces its earlier logging evals with twelve definitions and thirty-six
variants. Every actor receives only one bare task:

```text
$otel-audit ./service
$otel-instrument ./service
$otel-verify ./service
```

Both actor and grader use **gpt-6.1-sol / high**. There are no synthetic candidate
overlays or extra repair prompts. Superseded tasks and execution summaries are
excluded from the PR's current results.

Each complete round starts four fresh, uninstrumented service workspaces.
Languages run in parallel; audit → instrument → verify stays sequential within
each language. Native SDK tests, focused checks and plugin parity overlap those
workflows. A failed obligation closes the round early and stops only verified
owned peer processes, preserving partial evidence without pass credit. Required standalone Make rubric runs also run in parallel. Three
complete rounds remain consecutive; a source change or a real failed obligation
resets the streak. Dependency/build caching does not reuse an instrumented app,
telemetry receipt or passing verdict.

A round requires **168 semantic criteria, 89 native cases, 215 focused checks,
plugin parity and eight independent actual-app checks**. The unchanged host
checker captures exact synchronous/asynchronous log/span joins and matching
native output while the producer is alive, then proves bounded owned cleanup.
This live capture does not establish final-record SDK drain, post-exit retention
or production backend persistence; those claims require separate evidence.

| Language | Native cases per round | Three complete final-source passes |
|---|---:|---|
| Java | 25 | Pending |
| Python | 23 | Pending |
| Go, race enabled | 21 | Pending |
| Node.js | 20 | Pending |

Current deterministic checks: **215 focused**, **188 interactive**, **49 policy
unit + 8 contract**, and **228 pytest-plugin tests passed**. Skill validation:
audit **755 passed / 5 skipped**, instrumentation **786 / 5**, verification
**721 / 5**. Validation checks schema/fixtures and does not replace rubric or
runtime proof. The current native run passed all **89 cases**, including **80 sampled SDK
log/span joins**, four unsampled and four outside-context controls, with zero
skips. Rubric outcomes and full harness freshness remain pending. These native
checks alone do not complete a fresh workflow round.

Validation commands, run from the repository root with the managed eval Python:

```bash
make agent-policy-check
make test-interactive-otel-scripts
make test-pytest-plugin
make eval-validation SKILL=skills/otel-audit MODEL=gpt-6.1-sol
make eval-validation SKILL=skills/otel-instrument MODEL=gpt-6.1-sol
make eval-validation SKILL=skills/otel-verify MODEL=gpt-6.1-sol
```

Each role's representative command is the corresponding concrete expansion of:

```bash
make eval-rubric SKILL=skills/otel-<role> CASE=node/express-basic \
  EVAL_PATTERN=node/**/eval/qual/logging-<role>-contract.json \
  PROMPT=logging-trial-1 EVAL_WORKERS=1 EVAL_PROGRESS=0 MODEL=gpt-6.1-sol
```

Runs set `PYTEST_ADDOPTS=--agent-timeout=3600`, use independent owned ports and
public dependency/toolchain configuration. Repository Make commands use their
existing lockfile; fresh service fixtures may create their own lockfile.
[Current results](logging-remediation-results.json) hold source identity,
validation run IDs and the pending gate/review status. Standalone verification
of an uninstrumented fixture earns prerequisite-handling proof only.

## Expected PR behavior and remaining work

All three skills consume the same shared language references. Previous reference
paths remain compatibility forwarders, and isolated-skill tests prove discovery
without requiring another skill to be installed. The generic refactor reviews
all thirteen canonical skill paths changed in this PR.

The expected result is a source-backed audit, minimal supported repairs within
the selected scope, and honest verification that separates Working, Not working,
Not proven and unsupported capability. The controlled fixtures cover basic real
services and native SDK/bridge contracts; they do not certify every framework,
distributed queue, optional feature or production Collector/cloud deployment.

Three consecutive fresh all-language passes, current full-harness report
validation, final combined review, and exact-head PR checks remain required.
Prior Claude Desktop clause verification is historical source evidence, not a
review of this generic rewrite or runtime certification. No merge is authorized.
