### 5. Validate The Implementation

Read and follow `./references/project-runtime-validation.md`. Local,
deterministic validation is the default completion gate; do not ask for
permission to run a project-configured syntax, compile, typecheck, import, or
focused test command. Do not require full app startup, Docker, credentials,
live providers, or an OTLP collector for this gate.

At minimum:

1. Probe the selected project runtime and record the version actually used.
2. Run static/config checks for changed scripts and manifests, including
   `git diff --check` when Git is available.
3. Compile, typecheck, or import every affected application module with the
   selected project runtime.
4. Run the smallest existing focused tests that exercise changed code. For
   custom spans, metrics, or logs, add or update a focused repo-native test
   when the existing test framework provides a practical in-memory OTel seam.
   For a selected GenAI content attribute, prove its redacted value on a
   completed span. Start the focused test command with ambient
   `OTEL_SDK_DISABLED=true`; inside the test, temporarily set it to `false`
   only for construction of the in-memory SDK provider and import of the
   instrumented app, then restore the inherited value when the test ends.
   A permanent process-wide assignment to `false`, or a test run only without
   the inherited disabled setting, is not this proof. Do not override the
   operator's setting in production application code. Assert exactly one
   completed canonical owning span per selected model or tool operation before
   inspecting its content; choosing the first or latest matching span can
   conceal duplicate capture. Parse `gen_ai.output.messages` and assert
   exactly one candidate whose safe content matches the redacted/truncated
   actual provider return, not merely its role or finish reason. Likewise
   assert the recorded input-message content matches the safe model-bound
   input and that tool arguments/results match their safe call boundaries.
   For each tool, also parse its own input/output message mappings (or the
   supported OpenInference values) and compare them to those same sanitized
   arguments/result; fields on the parent/model are insufficient. Remove each
   mapping in a negative test so arguments/results-only content cannot pass.
   Check current schema, redaction and unchanged trace/span identity with no
   duplicate node; test successful null separately from no result on failure.
   Exercise the selected content policy with source-shaped sensitive fields
   both as structured values and embedded in JSON or labelled freeform text,
   including nested inputs and produced outputs. Dictionary-key filtering does
   not sanitize a string containing identity or protected reasoning fields.
   Check completed owning spans and actual exported content for their absence
   under the redacted policy, while retaining useful approved question/result
   content. A `redacted` label, sanitizer-only assertion, or blanking all content
   is insufficient. If a value cannot be safely transformed before any writer
   captures it, omit that value and report the remaining content gap.
   Build an exact signal closure matrix and execute every changed span name and
   metric call site that should still emit, plus explicit absence proof for
   every removed signal. Do not infer coverage for create, batch, update,
   delete, route, tool, or workflow names solely from a shared helper's test.
   Parameterize tests when those call sites share setup. For
   detector-critical counters, histograms, and observable gauges, drive each
   incident state to a non-default value and assert its emitted datapoint and
   bounded dimensions; metric registration, name presence, or a zero-value
   observation alone is not incident-readiness proof.
   Map these executions back to every in-scope `Audit Gap Closure` row and its
   declared verification scenarios.
5. Confirm filtered tests actually ran by checking test output or generated
   reports; a no-match guard is reactor plumbing, not test evidence.
6. If a validation failure is caused by instrumentation changes, repair it and
   repeat the affected gate until it passes. Do not finalize with a compile,
   type, syntax, or import error on a modified line.

Skip command execution only when the user explicitly forbids verification or
states that an external eval owns all checks. In that case, still perform
source-level review, record `Not run` in the handoff, and do not describe the
instrumentation as verified or complete. If the configured runtime or declared
dependencies are unavailable, record `Blocked` with the exact prerequisite;
do not fall back to an incompatible global runtime.

After the implementation gate, invoke or apply the `$otel-verify` workflow
unless the user explicitly opts out or a concrete prerequisite blocks it. The
instrumentation goal is not done until code viability is known and verification
has run, been explicitly skipped by the user, or is documented as blocked.
When verification observes a semantic failure introduced by this implementation,
repair the selected source mapping/creator and rerun the affected scenarios
before handoff. Apply the shared per-operation public OTel compatibility
exception when checked SDK creators cannot satisfy the contract; do not keep a
known-invalid helper solely to retain its SDK label. Preserve all other valid
producers and regenerate the normal bound reports after repair. If the user
requires verification Pass, unresolved failures or selected cloud/resource
proof remain an incomplete gate: do not drop selected findings, relabel local
receipts as cloud proof, or publish the proposed PR update before that gate.
An exact external permission/runtime blocker remains visible while independent
implementation and credential-free checks continue.
If `$otel-verify` is not exposed as a separate skill invocation in the current
session, read the adjacent `../otel-verify/SKILL.md` and apply that bundled
workflow directly. If an isolated skill environment does not expose that
adjacent file either, apply the local verification contract here: execute the
selected app-code scenarios with the project's runner, inspect completed
spans and metric points, and write the bound `.observe/otel-verify.json` and
reader-first `.observe/otel-verify.md` using the selected audit scenario IDs.
Use `./references/json-approval-handoff.md` and the bundled
`./scripts/observe_report.py` to validate the audit, selection,
instrumentation, and verify overlays and refresh the instrumentation HTML.
Only an individual scenario needing an unavailable listener, credential,
package, or fixture is blocked; a missing skill invocation or adjacent file
is not itself a verification blocker. Do not report verification as `Not run`
when local app-code scenarios executed.

Run local `$otel-verify` for every scenario that can execute without remote
export credentials, even when Agent Observability project creation, Agent
Stream setup, or live delivery is blocked. Keep remote export credentials and
missing local packages as separate prerequisites: if dependency resolution
blocks application import or the project runner, still invoke the read-only
verification workflow to validate the bound handoff, attempt available local
checks, and record exact blocked scenarios. Its `.observe/otel-verify.md`
reader-first result uses `## What Changed`, `## Tested And Working`,
`## Not Working Or Not Proven`, and `## Proof` before diagnostic detail;
the instrumentation Markdown keeps its own report order above.

Record the verification result and `.observe/otel-verify.md` path in
`.observe/otel-instrumentation.md`. If verification cannot run, record the exact
blocking prerequisite and do not describe the instrumentation as verified.

For canonical flow, write and validate `.observe/otel-instrumentation.json`
with `json-approval-handoff.md`, invoke `$otel-verify` with the same bound
selection unless explicitly skipped or concretely blocked, and refresh
`.observe/otel-instrumentation.html` with the available verification overlay.
Do not tell the user to rerun `$otel-verify`; name the concrete remaining repair,
runtime prerequisite, or product-evidence step instead.

When verified metric evidence exists and the user requested detectors,
alerting, monitors, Splunk configuration, or `$splunk-configure`, invoke or
apply that workflow and include the detector/configure verification result in
the instrumentation report.

When any claim depends on auto-instrumentation startup, framework route
resolution, automatic metrics, duplicate automatic-span prevention,
startup/exporter wiring, or runtime-installed OTLP logs, read
`../references/full-runtime-acceptance.md` and require its conditional full
runtime gate in the verification handoff. Attempt the gate without asking when
the repository provides a safe local profile or fixtures. Otherwise record the
exact prerequisite and keep those rows `Partial`, `Blocked`, or `Not proven`.
`Not run` or `no collector was run` alone is not an acceptable blocker. For
each required full-runtime row, record either the executed command and direct
result or the concrete unavailable runtime, listener, dependency, credential,
or fixture that prevented the attempt. Do not finalize while a safe local
profile exists and the required gate has not been attempted.

