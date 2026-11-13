# Skill Evals

Skill evals are pytest-collected JSON files. Each fixture keeps its eval
definitions under a service-local `eval/` folder:

```text
evals/<language>/<service>/eval/qual/audit.json
evals/<language>/<service>/eval/qual/instrument.json
evals/<language>/<service>/eval/runtime/instrument.json
evals/<language>/<service>/eval/sanity/audit.json
```

Only create the kind folders a service actually needs. The make targets select
these directories with global-style path patterns such as `*/*/eval/qual`,
`*/*/eval/runtime`, and `*/*/eval/sanity`.

Each eval defines `prompts[]` task variants. The harness separates the eval
kind from the baseline decision:

- `validation` validates JSON and skill source availability without Codex.
- `sanity` runs quick loaded-skill guards such as final output and skill
  visibility.
- `rubric` runs the task and a schema-constrained judge pass.
- `runtime` runs Docker/Splunk Observability Studio telemetry checks.
- `AB=1` adds the no-skill baseline side to any live eval kind.

| Eval Type | What Runs | What It Proves | Output |
|---|---|---|---|
| Validation | Pytest collection only | JSON shape, eval directory, skill source | Validation report |
| Sanity | Codex with `.agents/skills/<skill>` visible | Skill loads and the task completes | Sanity report |
| Rubric | Codex task plus schema-constrained judge | Semantic quality and workflow fit | Rubric report |
| Runtime Checks | Docker Compose plus Splunk Observability Studio API queries | Live spans, metrics, and logs are emitted after traffic | Runtime report |
| A/B | Adds the no-skill baseline side to sanity, rubric, or runtime | Skill lift over baseline | Same report shape with baseline columns populated |

Validation is the fast gate for CI: it proves the eval JSONs are collectable and
the referenced skill source exists. Live evals run the loaded-skill side by
default. Pass `AB=1`, `WITH=ab`, or use the `*-ab` target to add the baseline.

Each eval JSON keeps the human-facing tasks at the top, then only the checks for
that eval kind:

```json
{
  "skill": "otel-audit",
  "prompts": [
    {
      "id": "direct",
      "task": "Scan the service in ./service for observability gaps."
    }
  ],
  "rubric": [
    "Identifies the relevant entrypoint and current telemetry state."
  ]
}
```

Mode-specific JSON files are grouped by role:

```text
eval/sanity/*.json     # quick skill-loading checks
eval/runtime/*.json    # Docker/Splunk Observability Studio runtime checks
eval/qual/*.json       # schema-constrained rubric checks
```

The default sanity pattern picks `evals/sanity/skill-smoke/eval/sanity/`, a
dummy fixture used only to prove that the selected skill loads and the prompt
returns quickly.

Rubric evals may set `judge_inputs` or `judge_prompt` when the judge should
inspect artifacts other than a service directory.

The logging contract evals use bare `$otel-audit ./service`,
`$otel-instrument ./service`, and `$otel-verify ./service` tasks. To exercise
their normal handoff on the same service, run the host workflow runner with
the eval environment active:

```sh
uv run python run_logging_workflow.py --language python --trial 1 \
  --studio-binary /path/to/obstudio \
  --codex-home ../.workspace/codex-evals/codex-home \
  --output ../.workspace/logging-workflow/python-trial-1
```

Repeat for `java`, `go`, and `node` and trials 1 through 3. The runner requires
the normal language toolchains on `PATH` (Java 21 for Spring Boot), creates a
separate local receiver with no cloud credentials, and retains the generated
service workspace plus per-stage source, report, task and rubric evidence.
Grader feedback is archived and checked byte for byte, then removed from the
workspace before the next bare task. Application reports remain available for
the normal skill handoff. By default, any failed stage stops that workflow.
Use `--collect-semantic-failures` to collect later stages after a semantic rubric
failure when execution, required guards, source bindings, canonical audit and
applicable runtime checks remain valid. Original grades stay failed and the
whole workflow exits unsuccessfully; later stages provide diagnostic evidence
only. Execution, malformed evidence, binding and runtime failures still stop it.
The Go live interop fixture explicitly requires Go 1.25, allowing an official
propagator compatible with the driver's emitted trace flags. This test setup
does not authorize a skill to raise another application's runtime requirement.
It independently starts the generated service after instrumentation and
verification and proves concurrent sync/async logs against real SDK span
ancestry and the original sink. Runtime failure, incomplete rubric evidence,
or a task/grader model other than the configured Sol high fails the workflow.
It saves explorer receipts and the matching native-output snapshot while the
producer is alive, before bounded process cleanup. Studio intentionally evicts
a producer's telemetry when it exits. The live joins and cleanup do not prove
post-exit persistence or final-record SDK drain; those need separate owned
receipt tests. A regression models eviction on exit to enforce this ordering.
The checker resolves expected service identity with the SDK environment detector:
resource-only `service.name` is supported, an explicit `OTEL_SERVICE_NAME` takes
its normal precedence, and missing expected identity fails clearly before launch.
The workflow runner and configured fixture test targets additionally enable
`--operator-identity-profiles`: three fresh launches with host-supplied Resource
values check Resource-only identity, an explicit service name overriding a
conflicting Resource name, and whitespace around Resource keys and values
accepted by the selected SDKs.
The checker independently defines expected name, version and an unrelated
attribute, then checks them on received application logs and their owning/server
spans. Each launch retains its inputs, expectations and raw evidence; a later
passing profile cannot erase a failure. The option leaves the original launch
in place and allows 720 seconds for the four-launch check. These cases do not
prove absent/default identity, percent-encoded inputs, metrics Resources or headers.
This host runtime proof supplements the regular per-skill rubric commands;
a standalone verify task on an uninstrumented fixture is only a precondition
check. It is not positive runtime verification.
Regular per-skill rubric runs also send these tasks unchanged; the loading
guard proves either source-bound native full-skill input or a complete skill
read before application task actions. Only bound bare tasks may discover file
names and read project instructions before that read. No loading prompt is added.

### Logging judge checklist

Apply the following checklist to all logging audit, instrumentation and
verification definitions in Java, Python, Go and Node.js. Each definition uses
the shared [logging rubric](rubrics/logging-common.json), which selects
`strict_rubric_output: true` for all three prompt variants. Each definition's
`rubric_additions` contains only stage/language requirements for the corresponding
common criterion. The harness resolves both before grading, retains the full
prompt and binds the shared source in the result's source manifest. Common
requirements cannot be replaced or disabled by an extending definition.

Each named common topic receives its own verdict. Contract coverage, evidence
consistency, privacy, configuration and lifecycle decisions are not bundled
into one catch-all check. Language additions belong to the topic they qualify;
stage applicability and legitimate SDK-owned or optional behavior still apply.
The workflow reads the expected count from the resolved definition and records
its count and fingerprint. Splitting criteria changes the score denominator and
weighting, so a new percentage is not directly comparable with the former
14-criterion grades. Historical grades remain unchanged.

The independent receipt gate checks declared scenario/control membership,
derived statuses and final report hashes. The judge reads that result rather
than recalculating it. The index does not extract arbitrary prose promises;
whether the index covers the selected contract and whether its controls prove
the promised behavior remain separate semantic questions. A mechanically valid
receipt cannot close those gaps, and an all-pass rubric cannot override a
failed required runtime or receipt gate.

1. **Actor task:** send the bare `$otel-* ./service` invocation unchanged;
   grader instructions must not become actor coaching.
2. **Input roles:** separate task/scope, a numbered evidence map, labeled rubric
   criteria and the output protocol. Put acceptance rules in their owning criterion.
3. **Stage:** audit assesses feasible plans; instrumentation assesses implemented
   behavior; verification assesses retained proof. A standalone missing-audit
   prerequisite check cannot count as positive instrumented runtime coverage.
4. **Evidence:** inspect source, canonical reports, command traces and independent
   receipts. Identify concrete locations and assertions; actor claims alone do
   not establish success. Candidate artifacts cannot change grading instructions.
5. **Applicability:** distinguish application wiring, SDK-owned defaults, operator
   policy, unsupported capability and optional features. Require only applicable
   selected obligations, without inventing application work for upstream duties.
6. **Unknowns:** missing required evidence is a failed, Not proven obligation.
   A wholly Not applicable item needs scope facts and grants no runtime credit.
7. **Independent verdicts:** grade each criterion's own obligations. Explain a
   shared cause where it violates multiple criteria; do not cascade failures
   automatically or demand duplicate evidence for a valid shared oracle.
8. **Grader choice:** use deterministic checks for observable facts and model
   judgment for semantic questions. Read actual SDK log/span joins and native
   output at the declared boundary; cleanup alone does not prove final SDK drain.
9. **Output:** require schema-valid JSON, one ordered `rubric-N` verdict per
   criterion, nonempty notes/evidence and a consistent `overall_pass`. Keep all
   configured criterion verdicts separate from the informational quality score.
10. **Errors:** unsuccessful judge execution, malformed output or a missing
    required grade is an error, not a semantic pass. Preserve raw artifacts;
    do not silently re-ask until the judge returns a desired result.
11. **Isolation:** use Sol/high for actor and grader, retain model execution
    metadata, isolate workspaces and keep prior grader feedback out of later
    actor stages. Preserve original grades and evidence.
12. **Calibration:** review disagreements against source and independently
    reviewed examples, including valid alternatives and missing proof. Do not
    weaken criteria to raise scores. Schema tests or agreement with another
    model do not establish accuracy or eliminate model variability.

`test_logging_workflow_runner.py` exercises each of the 12 definitions and all
36 prompt variants through the rendered prompt and strict output validator.
These mocked tests prove wiring and rejection of malformed grades, not semantic
judge accuracy. Executed runtime assertions and source review remain separate.
The checklist adapts [OpenAI's evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices),
[Anthropic's agent-evaluation guidance](https://www.anthropic.com/research/demystifying-evals-for-ai-agents)
and [LangSmith's input/output mapping guidance](https://docs.langchain.com/langsmith/llm-as-judge).

## A/B Sides

| Side | Skill visibility |
|---|---|
| `with_skill` | Copied fixture plus temporary `.agents/skills` entries |
| `with_baseline` | Same copied fixture with no repo skills visible |

Baseline checks stay intentionally simple: final output, `skills-not-loaded`,
and baseline contamination checks.
Detailed sanity artifact checks default to the `with_skill` side, which
also gets a `skills-loaded` guard.

Use command-backed checks when an ecosystem tool can prove behavior more
reliably than text search. Examples in this repo use `go list -mod=readonly -m
all`, `npm pkg get`, `node -e`, and Python `tomllib` against the generated
service workspace.

Runtime checks are top-level `checks[]` entries in `eval/runtime/*.json`.
`eval-runtime` enables them automatically. The eval JSON points at a Compose
file and declares telemetry expectations. The Compose file owns service
topology, Splunk Observability Studio startup, app startup, and a profiled `traffic` service that
generates requests with tools such as `siege`. The harness runs Compose,
discovers Splunk Observability Studio host port with `docker compose port observer 17900`,
invokes `traffic`, queries that isolated Splunk Observability Studio instance, then tears the stack
down. Compose can use `${CODEX_EVAL_SERVICE_DIR}` when it must build the
instrumented temp service workspace rather than the source fixture. Shared
runtime image definitions live in `evals/runtime/`; service-specific runtime
files stay beside each eval under `eval/runtime/`.

For JSON-list endpoints such as `/api/query/logs`, use `record_checks` instead
of response-wide substrings when fields must belong to the same record. A
record check can select records with `match` or `match_contains`, assert
`field_equals`, `field_contains`, and `non_empty` paths, require an
`exact_count`, and reject duplicates with `unique_by`. Dotted paths address
nested fields such as `resource.serviceName`. Set `correlates_with_trace` when
a log must carry nonzero 32/16-hex trace/span IDs that identify the same span in
Splunk Observability Studio trace-detail endpoint. Use a nonempty `service_logs` substring or
occurrence check when the runtime must also prove that the original
stdout/stderr sink is preserved; failure to retrieve Compose logs fails the
check. Per-check `environment` values can drive isolated scenarios such as
`OTEL_LOGS_EXPORTER=none`; harness-owned service paths and Compose project names
remain protected. `stop_services_before_validation` can stop only the app after
traffic while leaving Splunk Observability Studio available, so endpoint assertions include
shutdown-flushed telemetry and preserved container logs.
The Python, Node.js, and Go fixtures emit `runtime shutdown completed` once at
WARN after their graceful server stop. Default checks require that record in
both Splunk Observability Studio and the original service sink; `OTEL_LOGS_EXPORTER=none` checks
require it only in the preserved sink and require zero service records in
Splunk Observability Studio.

The standard Python, Node.js, and Go runtime topologies use an isolated local
Splunk Observability Studio. Shared OTLP receiver integration tests ingest all
three signals and verify remote metrics and traces. Logs remain locally
queryable while independent HEC forwarding is enabled, paused, or failing.
This supplies live receiver-side proof of local and remote delivery without
duplicating a fake cloud service in every language topology.

## Isolated Codex Home for Live Evals

Live evals use a dedicated Codex home at
`.workspace/codex-evals/codex-home`, rather than your normal personal Codex
home. This keeps personal skills, plugins, and configuration from affecting
eval results. The fixture still injects the skill being evaluated through its
workspace-local `.agents/skills` directory.

Authenticate the dedicated home once before your first local live eval:

```bash
make eval-codex-login
```

When prompted, sign in with the same account/email you normally use for Codex.
The login applies only to this ignored, eval-specific home; it does not change
or sign out your normal Codex app, IDE, or CLI sessions. You only need to log
in again if you use a different machine or change `EVAL_CODEX_HOME`. Live eval
targets check this authentication before starting and tell you to run
`make eval-codex-login` if it is missing.

For a direct `uv run pytest` live invocation rather than a Make target, export
the same isolated home first and verify its authentication:

```bash
export CODEX_EVAL_HOME="$PWD/.workspace/codex-evals/codex-home"
make eval-codex-auth
cd evals && uv run pytest go/kvstore/eval/qual --skill ../skills/otel-instrument --codex-eval-kind rubric
```

This direct example uses the default Codex backend. A config using Cursor or
Claude does not use `CODEX_EVAL_HOME`, and `make eval-codex-auth` skips the
Codex login check for those backends.

## Commands

The default `dev` dependency group supplies the model-directed fixture's Flask,
OpenAI client and OTel instrumentors for deterministic regression tests.
`test_agent_review_regressions.py` executes its real startup, stdlib-to-OTLP
logging, header isolation and conversation rollback checks using loopback
receivers and stub model responses.

| Target | Purpose |
|---|---|
| `make test-eval-harness` | Validate every eval JSON and fixture |
| `make eval-report-freshness` | Verify tracked report source manifests still match canonical skill and eval inputs |
| `make skill-eval-list SKILL=skills/otel-audit` | List collected eval items for a skill path |
| `make eval-validation SKILL=skills/otel-audit` | Validate eval JSONs without running Codex |
| `make eval-validation-test SKILL=skills/otel-audit` | Validate evals and write raw JSON only |
| `make eval-validation-report SKILL=skills/otel-audit` | Render the latest validation Markdown and benchmark |
| `make eval-sanity SKILL=skills/otel-audit` | Run quick loaded-skill sanity checks |
| `make eval-sanity-test SKILL=skills/otel-audit` | Run sanity checks and write raw JSON only |
| `make eval-sanity-report SKILL=skills/otel-audit` | Render the latest sanity Markdown and benchmark |
| `make eval-sanity-ab SKILL=skills/otel-audit` | Run sanity checks with baseline |
| `make eval-rubric SKILL=skills/otel-instrument CASE=go/kvstore` | Run rubric judge checks |
| `make eval-rubric-test SKILL=skills/otel-instrument CASE=go/kvstore` | Run rubric checks and write raw JSON only |
| `make eval-rubric-report SKILL=skills/otel-instrument` | Render the latest rubric Markdown and benchmark |
| `make eval-rubric-ab SKILL=skills/otel-instrument CASE=go/kvstore` | Run rubric judge checks with baseline |
| `make eval-runtime SKILL=skills/otel-instrument` | Run Docker/Splunk Observability Studio runtime checks |
| `make eval-runtime-test SKILL=skills/otel-instrument` | Run runtime checks and write raw JSON only |
| `make eval-runtime-report SKILL=skills/otel-instrument` | Render the latest runtime Markdown and benchmark |
| `make eval-runtime-ab SKILL=skills/otel-instrument` | Run Docker/Splunk Observability Studio runtime checks with baseline |
| `make eval-all SKILL=skills/otel-audit` | Run validation, sanity, rubric, and runtime |
| `make eval-all-ab SKILL=skills/otel-audit` | Run validation plus A/B sanity, rubric, and runtime |
| `make eval-with-skill SKILL=skills/otel-instrument CASE=go/kvstore` | Run only the loaded-skill side |
| `make eval-with-baseline SKILL=skills/otel-instrument CASE=go/kvstore` | Run only the no-skill baseline side |
| `make eval-ab SKILL=skills/otel-audit CASE=go/chi-basic PROMPT=direct` | Run both sides in one A/B comparison |
| `make skill-eval` / `make skill-eval-ab` | Compatibility aliases for `eval-with-skill` / `eval-ab` |

Parallelize pytest items with `EVAL_WORKERS`:

```bash
make eval-all SKILL=skills/otel-audit EVAL_WORKERS=4
make eval-all-ab SKILL=skills/otel-audit EVAL_WORKERS=4
make eval-sanity SKILL=skills/otel-instrument WITH=ab
make eval-runtime SKILL=skills/otel-instrument CASE=python/fastapi-celery
make eval-rubric SKILL=skills/otel-audit EVAL_PATTERN='go/*/eval/qual'
```

Each worker writes per-item result JSON under `.workspace/codex-evals/_worker-results/`;
the controller merges those into raw run JSON. Report targets then render
Markdown and benchmark files from the merged JSON.

Progress logging is enabled by default for Make targets and prints item start
and completion lines:

```text
[codex-eval] START rubric:ab go/chi-basic/eval/qual/audit.json::otel-audit::go/chi-basic::direct
[codex-eval] PASSED rubric:ab go/chi-basic/eval/qual/audit.json::otel-audit::go/chi-basic::direct (142.3s)
```

Disable it with `EVAL_PROGRESS=0`.

## Config

| File | Purpose |
|---|---|
| `evals/codex-evals.validation.toml` | Validation-only config |
| `evals/codex-evals.toml` | Default live config and model settings |
| `evals/codex-evals.baseline.toml` | Compatibility with-baseline config |
| `evals/codex-evals.ab.toml` | Compatibility A/B config |

Set the judge model with:

```toml
[models]
agent = "gpt-6.1-sol"
judge = "gpt-6.1-sol"

[runtime]
enabled = false
```

## Reports

Run artifacts are written under `.workspace/codex-evals/<skill>/<run-id>/`.
Pytest writes raw JSON; report targets parse that JSON and create Markdown plus
role-specific benchmarks.

```text
.workspace/codex-evals/<skill>/<run-id>/
  run.json
  runs/
    validation.json
    sanity-with_skill.json
    sanity-ab.json
    rubric-with_skill.json
    runtime-with_skill.json
  results/<language>/<service>/<eval>/
    eval.json
    with_skill.json
    with_baseline.json
  <kind>/
    report.md
    benchmark.json
```

Latest summaries are copied by eval kind:

```text
eval-reports/<skill>/validation/report.md
eval-reports/<skill>/validation/benchmark.json
eval-reports/<skill>/sanity/report.md
eval-reports/<skill>/sanity/benchmark.json
eval-reports/<skill>/rubric/report.md
eval-reports/<skill>/rubric/benchmark.json
eval-reports/<skill>/runtime/report.md
eval-reports/<skill>/runtime/benchmark.json
```

Each `benchmark.json` is kind-specific. Sanity contains sanity checks only,
rubric contains judge/rubric fields only, and runtime contains runtime check
fields only. Baseline columns are `-` when the run mode did not execute a
baseline side.

New reports also record a SHA-256 source manifest for the canonical skill tree,
the shared skill references exposed to with-skill runs, each collected eval
definition, its staged non-generated fixture and prompt-selected eval inputs,
runtime support assets when applicable, and eval configuration. Filtered runs
exclude uncollected definitions and unused prompt inputs; full validation still
detects newly added matching definitions.

Shared evaluator behavior is tracked separately by the integer in
`evals/evaluator-semantics.toml`. Bump it only when a harness, dependency, or
shared eval-environment change can alter a published live-eval result or how it
is interpreted (for example, a grader or agent-execution behavior change). Do
not bump it for comments, tests, docs, or report-only formatting. `make eval-report-freshness` recomputes manifests
without running a model and fails when a tracked input or the evaluator
semantics version no longer matches; after a semantics bump, rerun the affected
live evals and render their reports.

This repository opts into that explicit policy with
`evals/evaluator-semantics.toml`. The reusable harness remains compatible with
repositories that do not have the file: they use the baseline semantics version
`1`, and existing v1/v2 manifests remain verifiable. For a repository adopting
the policy, add the file at `version = 1`, then rerun only reports being
migrated to v3. To roll back a migration before publishing, remove the file and
keep verifying the existing v1/v2 manifests; malformed configured files always
fail verification.

## Fixture Apps

| App | Stack | Run |
|---|---|---|
| `evals/python/flask-basic/` | Flask | `make dev` |
| `evals/python/fastapi-celery/` | FastAPI + Celery | `make dev` |
| `evals/node/express-basic/` | Express | `npm run dev` |
| `evals/go/chi-basic/` | Chi | `go run .` |
| `evals/go/chi-partial/` | Chi with partial OTel | `go run .` |
| `evals/go/kvstore/` | Chi + package tests | `make test` |
| `evals/java/springboot-basic/` | Spring Boot | `mvn spring-boot:run` |
| `evals/java/kafka-producer-consumer/` | Plain Kafka producer + consumer | `mvn test` |
| `evals/java/kafka-batch-consumer/` | Plain Kafka batch consumer | `mvn test` |
| `evals/java/kafka-listener-container/` | Kafka listener container | `mvn test` |
| `evals/java/kafka-streams/` | Kafka Streams with Guice wiring | `mvn test` |

The Java Kafka fixtures use broker-free unit or topology tests as eval commands.
Running the services with `mvn exec:java` or `mvn spring-boot:run` requires a
Kafka broker and is documented in each fixture README. See those fixture READMEs
for eval intent, required environment variables, and the Java-agent versus
manual-SDK boundary.

The Spring Boot fixture currently has no live Java runtime eval because the
repository does not provide a checked-in OpenTelemetry Java agent, a pinned
agent image, or an established Java Compose launch contract. An evaluator that
downloads and injects its own agent could pass independently of the files
produced by the instrumentation task. Until pinned infrastructure is available,
the fixture supplies a request-context log and grades Java's record fields,
single bridge, preserved appenders, opt-out, cloud configuration, and
agent-owned shutdown path as independent semantic rubric requirements; the
shared Splunk Observability Studio integration test supplies the live receiver-side cloud-boundary
proof.

Kafka coverage is organized by processing pattern rather than by every
framework combination: direct producer/consumer, batch consumer, listener
container, and Kafka Streams.
