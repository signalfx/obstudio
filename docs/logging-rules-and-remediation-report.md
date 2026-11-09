# OpenTelemetry logging rules and remediation

Nine shared rules now guide `otel-audit`, `otel-instrument` and `otel-verify`
for Java, Python, Go and Node.js. They distinguish missing application wiring
from SDK defaults, unsupported capabilities, optional features and local policy.

The current instruction identity is
`60bb2505414661eebf5a45fc8846fe94a73229972b8c70ec72d9bb01d59c1565`.
Claude Desktop verified the exact thirteen-file snapshot against primary
sources: no verified defect in the inspected clauses and all six negative
source checks passed. This is source verification, not runtime certification.
The complete three-run execution gate is running with **0/3** clean passes;
the final whole-PR combined review follows that gate.

## Gaps and corrections

The [source evidence](logging-skill-analysis-evidence.json) binds the initial
instruction gaps to baseline `4e1e51f3` and preserves the 183-clause primary-source
inventory, ownership decisions and current clause verification. The branch also
includes upstream `e2c31a57`.

Trace correlation and preserving original sinks were already required. The
weakness was incomplete reconciliation of source clauses, installed capability,
selected code path and actual proof. Injected IDs could pass while a real tracer
or span exporter was broken; a broad checklist could also miss configuration
precedence or impose an unsupported requirement. The fixes make those decisions
and their evidence explicit.

| Rule | Gap fixed | Required behavior and proof |
|---|---|---|
| `LOG-RECORD` | Incorrect severity, time or structured-value mapping; optional fields treated as mandatory. | Test the actual bridge and resolved dependency. Preserve supported values and occurrence/observation meaning; classify unsupported mapping honestly. |
| `LOG-CONTEXT` | Nonempty IDs mistaken for correlation; valid INTERNAL spans rejected by SERVER-only expectations. | Join canonical IDs to the exact associated real SDK span and verify its request ancestry, flags and Resource. Respect explicit caller-side capture. |
| `LOG-ASYNC-HANDOFF` | Context lost or leaked across workers, callbacks or logging queues. | Capture before dispatch when needed, reuse verified propagation, restore state, and test concurrent request pairing through the owned async path. |
| `LOG-EXCEPTION` | Framework/formatter content escaped selected privacy checks. | Check all captured renderers and sinks at the policy-required boundary. Preserve permitted diagnostics while removing forbidden content; a decision-only filter is not redaction. |
| `LOG-LIMITS` | Span limits substituted for log limits; arbitrary Body caps; expensive disabled-log construction. | Check actual supported log limits and selected Body policy separately. Test boundary values and native enablement without suppressing an enabled original sink. |
| `LOG-DELIVERY` | Enqueue/flush, wire receipt or partial success mistaken for acceptance; retry and shutdown budgets confused. | Bound the whole selected operation. Separate emissions, attempts, copies, acknowledgements and persistence; retain legitimate unknowns and record known failure/retry outcomes. Never retry populated partial success. |
| `LOG-DIAGNOSTICS` | Export errors could recurse into the same bridge or leave cross-signal outage claims unproven. | Use an independent diagnostic route; prove bounded failures, application/native-sink progress and applicable configured-signal isolation. |
| `LOG-VERIFY-FRESH` | Stale receipts, skipped tests or zero exits mistaken for current proof. | Bind source, dependencies, commands and actual counts. Retain exact evidence for the current run and verify the generated service independently. |
| `LOG-SPEC-CLOSURE` | A thematic checklist omitted clauses or assigned SDK duties to the application. | Reconcile source, strength, maturity, applicability, owner, disposition and proof boundary in canonical reports. Local workflow/privacy policy stays distinct from OTel requirements. |

The existing four language guides are shared by all three skills; prior
instrumentation-reference paths remain compatibility forwarders. Isolated-skill
checks prove the references are reachable without another skill installed.
Java capability guidance uses the resolved dependency's documentation/source and
actual appender tests. A different release or upstream main cannot prove support;
fixed dependency versions in fixtures are reproducibility evidence only.

Resource preservation also covers normal launchers. Python CLI defaults no
longer replace service/resource settings; programmatic defaults sit underneath
SDK-decoded operator values. Java's image example no longer bakes in a service-name
fallback. All four guides recognize resource-only `service.name` as valid without
requiring `OTEL_SERVICE_NAME`. The actual Node SDK path already preserved that
identity, so its code recipe was retained.

## Replacement evals and current results

The PR contains twelve current logging eval definitions and thirty-six variants.
Every actor task is exactly one of:

```text
$otel-audit ./service
$otel-instrument ./service
$otel-verify ./service
```

Superseded coached/plan-only evals, synthetic overlays and old execution summaries
are excluded from this PR. Current maintained native tests remain active proof
for the new rules. Fixtures and rubrics hold the expectations; the actor receives
no extra repair prompt.

Each complete pass uses fresh service workspaces and the normal audit → instrument
→ verify handoff. It requires **168 semantic criteria, 88 native cases, 214 focused
checks, plugin parity and eight independent actual-app checks**. Two concurrent
requests share a trace but have distinct ancestry; every sync/async log must join
its own real SDK span, with native counts and source identity preserved.
Passes run sequentially. A failed obligation or changed frozen input resets the
streak. A standalone verify on an uninstrumented fixture proves prerequisite
handling only and earns no positive logging-runtime coverage.

| Language | Native cases per pass | Three complete final-source passes |
|---|---:|---|
| Java | 25 | Pending |
| Python | 23 | Pending |
| Go, race enabled | 20 | Pending |
| Node.js | 20 | Pending |

The [current results](logging-remediation-results.json) contain only the current
replacement eval contract and its source-bound outcomes. No superseded scores or
old clean streaks are counted. Both actor and grader use **gpt-6.1-sol / high**;
GitHub live-model evals remain disabled, so local PR-branch execution is reported
as local execution.

| Command | Result |
|---|---|
| From `evals/`: `UV_NO_CONFIG=1 uv run pytest -q test_default_local_log_export_guidance.py test_incident_readiness_skill_guidance.py test_logging_contract_runner.py test_logging_receiver.py test_logging_workflow_check.py` | 214 passed |
| `UV_NO_CONFIG=1 make eval-validation SKILL=skills/otel-audit` | 754 passed, 5 scoped skips |
| `UV_NO_CONFIG=1 make eval-validation SKILL=skills/otel-instrument` | 785 passed, 5 scoped skips |
| `UV_NO_CONFIG=1 make eval-validation SKILL=skills/otel-verify` | 720 passed, 5 scoped skips |
| `PATH="$PWD/evals/.venv/bin:$PATH" make agent-policy-check` | 49 unit + 8 contracts and policy passed |
| `PATH="$PWD/evals/.venv/bin:$PATH" make test-interactive-otel-scripts` | 188 passed |
| `UV_NO_CONFIG=1 make test-pytest-plugin` | 228 passed |

The five validation skips are scoped optional/receiver-dependent checks. Formal
native trials supply the receiver and require zero skips. The full eval-harness
freshness gate must pass after the current representative reports are generated.

Current representative commands use the project virtual environment/toolchain
on `PATH` and the supported outer model timeout:

```sh
PYTEST_ADDOPTS=--agent-timeout=3600 UV_NO_CONFIG=1 make eval-rubric SKILL=skills/otel-audit CASE=go/chi-basic EVAL_PATTERN=go/chi-basic/eval/qual/logging-audit-contract.json PROMPT=logging-trial-1 MODEL=gpt-6.1-sol
PYTEST_ADDOPTS=--agent-timeout=3600 UV_NO_CONFIG=1 make eval-rubric SKILL=skills/otel-instrument CASE=go/chi-basic EVAL_PATTERN=go/chi-basic/eval/qual/logging-instrument-contract.json PROMPT=logging-trial-1 MODEL=gpt-6.1-sol
PYTEST_ADDOPTS=--agent-timeout=3600 UV_NO_CONFIG=1 make eval-rubric SKILL=skills/otel-verify CASE=go/chi-basic EVAL_PATTERN=go/chi-basic/eval/qual/logging-verify-contract.json PROMPT=logging-trial-1 MODEL=gpt-6.1-sol
```

A positive language/trial workflow uses:

```sh
cd evals
UV_NO_CONFIG=1 uv run python run_logging_workflow.py --language python --trial 1 --studio-binary /path/to/obstudio --codex-home ../.workspace/codex-evals/codex-home --output ../.workspace/logging-workflow/python-trial-1
```

The gate repeats it for all four languages and trials 1–3. Actual session metadata,
rubric decisions and runtime receipts determine success; pytest exit status alone
does not establish semantic quality. The outer model timeout does not alter app,
export or probe deadlines.

## Review and limits

The final combined Codex protocol/Toolkit/baseline and independent Claude Desktop
standard/Toolkit review is pending three complete current-source clean passes.
[PR 352](https://github.com/signalfx/obstudio/pull/352) remains a draft; final-head
Copilot and Required CI outcomes will be recorded after publication.

These tests cover controlled native SDK/bridge behavior and basic Spring, Flask,
chi and Express startup. REST does not expose every TraceFlags bit; native wire
tests cover flags separately. They do not certify production Collector/cloud
delivery, arbitrary payload sanitization, distributed queues or every optional
Development feature. OTel does not prescribe every business event an application
should log; that selection remains tied to incident needs and privacy policy.
