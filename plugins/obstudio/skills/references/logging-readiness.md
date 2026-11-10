# Application logging readiness

Read this reference when auditing or changing an application logging path.
These rules extend the local-log contract; they do not authorize new sinks,
sensitive-data capture, a custom SDK, or changes outside the selected scope.

For audit, instrumentation and verification, read only the detected stack's
**Logging Readiness Checks** section in the existing language guide, following
its bridge/provider ownership references as needed. Those guides own the SDK
options, numeric conversions, async mechanisms and diagnostic-routing recipes;
the common rules and acceptance obligations below still apply. A guide's setup
examples do not authorize application changes in an audit or verification task.
The logging checks are self-contained for each declared consumer; audit and
verification do not require a sibling instrumentation skill to be installed.

| Detected stack | Existing language reference |
|---|---|
| Java | [Java logging checks](languages/java.md#logging-readiness-checks) |
| Python | [Python logging checks](languages/python.md#logging-readiness-checks) |
| Go | [Go logging checks](languages/go.md#logging-readiness-checks) |
| Node.js | [Node.js logging checks](languages/node.md#logging-readiness-checks) |

## Source and applicability

Reconcile rules with the installed SDK/bridge's public APIs and current official
documentation. Record package versions, source URLs/date, applicable stability
of the language's Logs signal and individual features, and unsupported features.
Development or release-candidate status calls for capability verification, not
an automatic upgrade or a reason to skip that language. SDK-author,
instrumentation-library release and semantic-convention-author duties are not
automatically missing application code. A supported SDK default can satisfy a
rule. If the repository owns the selected instrumentation library, assess its
own obligations there; do not reimplement an upstream SDK merely for visibility.

The [log data model](https://opentelemetry.io/docs/specs/otel/logs/data-model/),
[Logs API](https://opentelemetry.io/docs/specs/otel/logs/api/),
[Logs SDK](https://opentelemetry.io/docs/specs/otel/logs/sdk/),
[SDK configuration](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/),
[resource merging](https://opentelemetry.io/docs/specs/otel/resource/sdk/),
[event/attribute naming](https://opentelemetry.io/docs/specs/semconv/general/naming/),
[log registry](https://opentelemetry.io/docs/specs/semconv/registry/attributes/log/),
[common attribute limits](https://opentelemetry.io/docs/specs/otel/common/#attribute-limits),
[exception log conventions](https://opentelemetry.io/docs/specs/semconv/exceptions/exceptions-logs/),
[trace context in non-OTLP formats](https://opentelemetry.io/docs/specs/otel/compatibility/logging_trace_context/),
[logging context guidance](https://opentelemetry.io/docs/specs/otel/logs/supplementary-guidelines/),
[OTLP delivery](https://opentelemetry.io/docs/specs/otlp/),
[OTLP exporter retries](https://opentelemetry.io/docs/specs/otel/protocol/exporter/#retry),
[error handling](https://opentelemetry.io/docs/specs/otel/error-handling/), and
[sensitive-data guidance](https://opentelemetry.io/docs/security/handling-sensitive-data/)
are primary sources; the security page is non-normative guidance. Check
individual development features rather than
describing an entire language or exception convention as stable.

Resolve the effective configuration owner before applying environment-based
recipes. A supported, active `OTEL_CONFIG_FILE` loader (or its deprecated
`OTEL_EXPERIMENTAL_CONFIG_FILE` alias) ignores flat SDK environment settings
except variables referenced for substitution; inspect application overlays too.
Do not infer loader support from a variable's presence. Otherwise follow the
installed distribution's environment, programmatic and agent precedence; empty
environment values are unset. Check effective `OTEL_SDK_DISABLED`, native/SDK
filters and resource merge results before diagnosing a missing pipeline.
For supported environment Boolean settings, only case-insensitive `true` means
true; `1` and `yes` do not disable the SDK. Other values resolve false, with a
warning recommended for invalid nonempty values. Let the actual config owner
parse settings; do not apply flat-environment rules to an active file loader.
`OTEL_LOG_LEVEL` controls SDK diagnostics, not application log severity.
User-provided resources take precedence over `OTEL_RESOURCE_ATTRIBUTES` in the
standard SDK merge; preserve operator identity when adding defaults by avoiding
conflicting code values, not by assuming the environment wins. Check decoding
errors and actual merge order rather than replacing the existing provider.
An existing `service.name` in the effective resource configuration is valid
operator identity even when `OTEL_SERVICE_NAME` is absent. Do not add a higher-
precedence Make, shell, CLI, `.env`, launch profile, image or JVM fallback that
replaces it. Resolve resource values with the installed SDK's supported detector/merge, apply new
application defaults underneath supplied values, and inspect the actual merge
order. Verify the normal launcher as well as the helper with resource-only
identity, explicit service-name override and absent-identity controls.
Resource-only and absent-identity controls must also account for values reloaded
by an active `.env` or launch profile; clearing the parent environment alone can
leave a hidden service-name override. Use an isolated configuration/project copy
for those controls rather than deleting operator-owned settings.
These preservation checks are local workflow; SDK configuration defines each
setting's precedence, and an active file loader retains its own contract. Include resource
encodings accepted by that installed configuration owner, such as whitespace
around resource entries where supported. A shell substring match is not SDK
parsing: appending a default after a supplied key the substring test missed can
overwrite operator identity when later duplicate keys win. Preserve the supplied resource
configuration intact when no supported lower-priority defaults mechanism exists.

Let the installed exporter parse OTLP header environment values using its
supported `key=value,key2=value2` encoding. W3C Baggage-style semicolon metadata
is not supported here. Do not introduce a custom parser, print header values
or silently rewrite operator credentials to make a local recipe work.

Follow an existing file/stdout forwarding route through its parser, Collector
processors and destination before adding an SDK bridge. It can be operator-owned
coverage; context strings alone cannot prove that route exports canonical OTLP
records. Preserve one collection owner per record. A Collector redaction/filter/
transform processor can satisfy an approved downstream processing boundary,
but cannot close a policy requiring sanitization before SDK or writer capture.
Name the boundary and prove the values at it; local storage before a later
redactor still counts as capture.

For a selected privacy policy, include framework/access/error renderers captured
by that path, not only application logger calls. Preserving sinks, levels,
permitted diagnostic categories and safe formatting does not require retaining
policy-forbidden content. If a selected probe exposes it, inspect a supported
native hook at the boundary the policy requires and rerun the probe; dependency
ownership alone does not make that captured path unselected. Preserve application
behavior and permitted diagnostics instead of disabling all framework logging
or replacing the provider. If no supported hook exists at that boundary, record
the exact limitation and leave coverage unresolved. These are selected privacy
workflow rules supported by the non-normative sensitive-data guidance, not a
universal OTel payload prohibition. Preserve the permitted diagnostic category
at each selected output boundary; retaining it only in native output does not
justify replacing the exported category with a generic redaction label.
An input or attribute that source evidence shows cannot reach the selected
logging path may be not applicable; do not add a capture path just to test it.
A control already required by the bound scenario must still be executed or
retained as not proven, not silently removed from the contract.

## LOG-SPEC-CLOSURE -- Reconcile sources, implementation and proof

Begin with the applicable official source sections, not only this guide's rule
names or a keyword search. Record source URL, version/date or supplied snapshot,
requirement level, applicability and owner (SDK, bridge, instrumentation library,
semantic-convention author, application, collector or operator). Attribute
requirement levels bind the instrumentation library; inspect its ownership
before assigning an application fix. Supplementary guidance adds no normative
SDK requirements.
Separate upstream requirements, optional/development capabilities and the
repository's local destination/privacy policy. If current sources are unavailable,
name the snapshot and leave unsupported conclusions unverified.

Keep a compact source-to-evidence matrix in the existing report/evidence fields;
follow the canonical report schemas and do not invent JSON keys or new artifact
types. Cover record/time/severity/structured values, trace context and propagation,
resource/scope identity, bridge/provider initialization and duplicate prevention,
filtering/opt-out, exception/privacy, limits, batching/delivery, diagnostics and
flush/shutdown. Reconcile other applicable clauses found in the sources even
when they have no LOG-* name here. For each row, record source/config/default
evidence, covered/partial/missing/unverified/not-applicable, finding/scenario
IDs where needed, and the actual proof boundary. An SDK-owned default can be
covered without an application override; absence of an installed capability is
not proof that an application has implemented it.

Decompose a source paragraph into its separate conditions, actions and requirement
levels before condensing it into a matrix row. One row may retain several clauses,
but give each its own strength and disposition; a later failure fallback does not
cover an earlier recommendation or permission. For example, a receiver response
row retains all of: MUST bound before compression; SHOULD reduce oversized partial
responses without changing semantics when possible and practical; MAY trim optional
diagnostics; MUST fail with HTTP 500 if the response still cannot fit, with acceptance
unspecified. "May reduce diagnostics" alone loses the separate SHOULD. Compare the
saved row with each source clause, not only its topic or citation. This is a local
report-completeness check, not an additional OTel implementation requirement.

For audit, emit concrete application-owned gaps through the normal findings and
acceptance flow. For instrumentation, implement the authorized ones and retain
unselected gaps. For verification, independently reconcile the matrix with real
call sites and the selected contract; report omitted obligations and unproven
wiring without editing the app or rebinding prior evidence. Source review,
SDK/bridge probes, application startup, receiver receipt and backend joins are
different proof boundaries. Passing one cannot close the others. A rule mention,
schema check, total test count or supplied ID strings cannot establish full
guideline coverage. Any omitted applicable row leaves that claim incomplete.

Before finalizing, perform a per-scenario check of every required assertion and
control named by its trigger and acceptance criteria, including negative controls.
Keep missing checks not proven rather than completing a row from related passes.
Choose each executed row's supported `proof_mode` at its own boundary: a focused
SDK/bridge probe with a loopback receiver supplies focused proof (for example
`unit+otlp`), even when a separate test starts the app. Preserve `app_test` for
actual application-test proof. Use `full_runtime` only when the claimed event
traverses the normal application entrypoint and call site to the observed boundary.
Audit uses a different field: choose `proof_level` `focused call-site` for a
focused capability test, or `either` when its contract allows both focused and
application proof; do not label an isolated SDK/bridge fixture `full runtime`.
Reserve that audit level for normal application execution, including agent or
preload startup, framework-resolved routes, automatic metrics or installed log export.
Audit plans these checks; instrumentation and verification reconcile actual
results. These are local report-contract checks, not new normative SDK requirements.
Audit separates scenarios when their owners or required proof boundaries differ.
For example, a parser failure reached through the normal application entrypoint
can use `full runtime`; a constructed shutdown Error emitted through an isolated
bridge belongs in a separate `focused call-site` scenario. Do not append a focused
control to a full-runtime scenario and expect later stages to reinterpret its level.
`either` permits either adequate proof for the same contract, not a mixture of
different controls with incompatible boundaries. A server-close test seam or an
isolated structured-value probe likewise keeps its actual boundary. SDK/exporter
and receiver-owned capability checks retain their owners; do not bundle them into
an executable application finding merely because both concern delivery. Unverified
upstream capability can keep conditional future checks in the matrix evidence.
Later stages retain bound IDs and distinguish observations in existing evidence
fields. Retain each required control's expected input/outcome, actual command,
concrete evidence and verdict; one invocation can supply several controls.
Derive working status from those individual results, not a total test count or
an automated finalizer that marks every selected scenario working together.

For a claim combining properties, bind its evidence to the same owned path and
operation. Separate passing unit tests for context copying and synchronous
real-span receipt do not prove an asynchronous log-to-span join. Mark that
combined claim partial until one scenario traverses the owned handoff and
joins that worker/callback log to its actual SDK span at the claimed receiver.
Apply the same reasoning to other combined claims: do not assemble end-to-end
coverage from unrelated paths or independent probes.

## LOG-RECORD -- Preserve record meaning

Check the real bridge's numeric severity mapping, source severity text, body,
logger/scope and timestamps. Common single-level mappings are DEBUG=5, INFO=9,
WARN=13 and ERROR=17; finer source levels can use their documented range.
These range labels do not prescribe `SeverityText` or its casing. Preserve the
selected bridge's actual source-text mapping; do not uppercase it to match a
numeric band name. The [data model](https://opentelemetry.io/docs/specs/otel/logs/data-model/#field-severitytext)
allows a short-name substitution when SeverityText is absent, not replacement
of a present source value.
Never copy a source logger's numeric level directly into SeverityNumber.
Unknown severity in a source with a level concept may remain 0/absent; do not
invent an ERROR classification. If an event is known erroneous and its source
has no severity concept, the data model recommends ERROR=17 during mapping.
Keep that recommendation and its preconditions distinct from a universal MUST.

Preserve the event's occurrence Timestamp when available; ObservedTimestamp
represents collection time. Do not replace an older event time with export
time or assert that the two clocks must be equal. Treat nanoseconds/seconds
conversion explicitly and preserve 64-bit nanosecond precision. Optional
absent fields alone are not defects. Preserve
structured values rather than turning an entire structured record into an
opaque string. EventName is an event classification when applicable, not a
mandatory field on ordinary application messages.
The language's supported empty value (null/None/nil), zero, false, empty strings
and empty arrays are meaningful AnyValues. Assert presence and type separately
from truthiness/nonemptiness. Preserve accepted null array entries and their
positions; an exporter unable to export null may substitute zero, false or an
empty string. Check that capability before accepting a substitution; dropping
an entry is different from retaining its position. Check the selected
bridge's supported conversion before claiming preservation; a direct SDK test
does not prove the bridge handles every value, or authorize replacing it.
For selected semantic events, keep EventName free of per-occurrence IDs; put
permitted varying values in attributes. Reuse applicable semantic attributes;
new application keys should use a nonconflicting application/company namespace,
and new `otel.*` keys require specification approval. Where call-site fields are
selected, check the installed bridge's convention version and current `code.*`
keys before changing deprecated mappings; do not upgrade or rewrite its SDK.
Keep scope identity consistent rather than attaching conflicting scope attributes
to the same Logger identity. Optional development `log.iostream`,
`log.record.original` and `log.record.uid` are not mandatory on every record.
If present, bound and sanitize original content before constructing it; two
distinguishable records must not share a UID. A trace ID is not a per-record UID.

For a newly selected event definition, document when it occurs, its name,
occurrence timestamp, default severity and permitted attributes, including
sensitive, expensive or large fields. Reuse relevant attributes without copying
every span attribute; failure outcomes use applicable `error.type` conventions.
A named event represents a timestamped occurrence, a span a duration, and span
attributes properties of the whole operation. Ordinary diagnostic messages
remain ordinary logs; events can occur outside a trace without inventing a span.
On a supported new event path, use the canonical EventName field rather than
the deprecated `event.name` attribute. Resolve existing bridge/version migration
policy before changing an older mapping; do not upgrade solely for this example.

## LOG-CONTEXT -- Correlate without inventing or leaking context

Use the execution context at the log call, not a remembered last span. Check
top-level TraceId, SpanId and TraceFlags, including a valid unsampled context
and concurrent/asynchronous work. Restore/detach context after a request;
outside-span logs must not inherit the preceding request's IDs. An unsampled
span can still supply valid correlation even when no span is exported.

For a cross-process join, also check the installed propagator against the actual
peer carrier. A locally correct logger cannot repair a rejected incoming
`traceparent`. Record the peer's emitted flags and extracted context through
supported APIs; distinguish a propagator capability limit from missing logger
wiring. Resolve compatible official dependencies within the existing runtime
constraints, or leave the affected join explicitly unsupported/unproven. Do not
strip peer flags, copy IDs manually, replace the provider or silently raise the
runtime floor to make the test pass. This is a compatibility verification
workflow grounded in the [Propagators API](https://opentelemetry.io/docs/specs/otel/context/api-propagators/).
Its W3C parsing/validation requirements bind the propagator implementation.
Rejecting a valid peer carrier is a dependency conformance gap to resolve or
report, not optional covered behavior or a repair to application logger wiring.

Do not introduce sampled-only filtering as a log baseline. Inspect explicit
operator filtering first: newer SDKs can offer development `trace_based`
filtering, defaulting to false. Preserve an explicitly selected supported
policy and test its intended drops separately. Do not fabricate or force-sample
a span to make correlation pass. Test both sampled and unsampled contexts and
a no-context call, checking exact IDs and flags rather than nonempty strings.
Where supported, development `LoggerConfig.enabled` should default true and
`minimum_severity` defaults to 0; severity-0 records bypass that threshold.
A disabled SDK/logger is a no-op for that path, not proof of a missing bridge
or permission to suppress other native sinks. Test selected filters separately
from missing wiring, including severity-0 and no-context bypasses. Configuration
changes may become visible eventually; do not demand instantaneous SDK updates.

Trace the actual tracer/context manager, provider initialization, log bridge and
record call site. When tracing is configured, prove correlation with SDK-created
spans: emit through the application's logger inside a real parent and child
span, including owned asynchronous handoff. At the claimed receiver/backend
boundary, join each sampled log's canonical top-level TraceId and SpanId to the
exact received span and check parentage plus source-backed resource identity.
Compare TraceFlags with the actual SDK context, preserving its defined bits;
do not assume a sampled SDK context has only a single flag bit. Injected
non-recording contexts remain useful unit controls, but cannot prove tracer
startup, span export or an end-to-end join. Do not manufacture IDs, add a second
provider or invent spans for unowned operations merely to satisfy a test.

For each call, derive the expected SpanId from the bridge/API's selected context,
including explicit caller-side capture when used. That span may be an INTERNAL
framework/handler child. Verify its ancestry to the correct request separately;
do not require the log to use a SERVER ancestor's SpanId or replace valid context
merely to satisfy a test. A SERVER-only target needs evidence that this is the
associated span on that path.

Where the application owns an async boundary, require at least one combined
scenario: capture a real SDK parent/child context, traverse that boundary,
emit through the worker/callback's application logger and join that record to
the exact received SDK span, checking flags, parentage and resource. A child
may start before dispatch or inside the worker according to the actual path.
Reuse existing spans/propagation; controlled test spans stay within the existing
provider and do not justify new production instrumentation or unowned work.
Label the joint scenario explicitly in the handoff. A known-ID async test plus
a separate synchronous real-span test cannot replace it.

Keep the valid unsampled case separate: logs can retain SDK-generated context
even when sampling intentionally prevents the span from being exported. Missing
that span is then expected, not proof of broken correlation. Outside-span logs
may legitimately have no context. Ordinary attributes or strings named
`trace_id`/`span_id` are not the OTLP record's canonical context fields. If the
selected collection path is a non-OTLP JSON/text sink, check its supported
context injection and customary top-level `trace_id`, `span_id`, `trace_flags`
representation separately; OTLP receipt alone cannot prove formatted stdout
correlation. Preserve existing sinks and explicit format policy.

## LOG-ASYNC-HANDOFF -- Capture before scheduling and restore after work

For each owned asynchronous boundary, identify where the log record and its
OTel context are captured relative to executor, callback and logging queues.
Capture the caller's context per work item before scheduling. Reuse verified
framework/agent propagation; do not add a second wrapper merely by language.
Use the detected language guide's supported handoff and cleanup mechanism,
including separate handling for approved application context fields.

A standalone bridge after a logging queue can observe the queue worker's
context instead of the caller's. Preserve a supported context-capturing queue
path, or keep the existing bridge on the caller side beside the original
asynchronous sink and use the SDK batch processor. Never duplicate bridges.
Test caller-created sampled/unsampled context, exact record-to-request pairing
under concurrency, caller detach and worker reuse. Exercise error/cancellation
cleanup where the owned path supports those outcomes; otherwise classify that
application path not applicable and keep any supported SDK-scope control focused.
Do not add business cancellation behavior solely for a logging check. Ending a span
or detaching context is not cancellation of scheduled work.
Include a missing-propagation control where feasible; its expected context loss
is evidence of an unsafe path, not an acceptable production configuration.
Link the combined real-span async scenario required by LOG-CONTEXT; independent
handoff and join scenarios alone leave that combined obligation unproven.

## LOG-EXCEPTION -- Preserve exception semantics within privacy policy

Where exception details are already collected or explicitly selected, use
the supported bridge/SDK exception mapping and `exception.type`,
`exception.message`, and `exception.stacktrace` as applicable. Do not export
an exception object's arbitrary serialization under invented keys. Minimize
and sanitize message, stack, nested structured values and formatter/MDC fields
before the exporting processor; truncation alone is not redaction.
Hashing a small, predictable input does not establish anonymization either.
Follow the selected privacy policy and capture boundary rather than declaring
a hashed identifier safe by algorithm name.

The exception-log convention explicitly excludes logging bridges from its
instrumentation-specific recording guidance. Do not force every bridged error
to add EventName, change severity, emit a second event, or migrate existing
span exceptions. Preserve bridge semantics and versioned opt-ins. For newly
selected instrumentation exception events, check the applicable conventions
and stability, associate the actual operation context, and choose severity
from impact. No policy permission to collect a message/stack means omit it
and retain permitted type/category evidence, not enable capture for a test.
For a selected instrumentation exception event, the convention requires type
or message when the other is unavailable; if policy permits neither, report the
semantic limitation without capturing forbidden content. Do not apply this floor
to ordinary bridged messages. Instrumentation should avoid artificial exceptions
used only to represent an unsuccessful status; this development recommendation
does not forbid an application's intentional error log. Where an installed Emit
API derives exception attributes, explicit user attributes take precedence.
Prefer a supported exception-instance Emit API for selected instrumentation
only when policy permits that capture; otherwise retain just permitted fields.
For a selected exception event, check the versioned recommendation for an
operation-specific `.exception` name or generic `exception` handler name.
Check deprecation/version policy for `exception.escaped`; do not migrate span
exception behavior or delete approved compatibility fields merely by keyword.

Apply a selected exception-field allowlist exactly. Compatibility is not
permission to retain an excluded alias such as `error.kind` or `error.dump`.
When only `exception.type` is allowed, omit those aliases as well as message
and stack, and assert their absence. Do not pass the raw exception to a bridge
and rely on truncation to hide its contents. Preserve an alias only when the
applicable policy explicitly permits it; do not remove unrelated application
metadata merely because it is not an exception attribute.

## LOG-LIMITS -- Bound record cost

Inspect effective log attribute count/value limits and existing operator
values; SDK defaults may already suffice. `OTEL_LOGRECORD_ATTRIBUTE_COUNT_LIMIT`
and `OTEL_LOGRECORD_ATTRIBUTE_VALUE_LENGTH_LIMIT` are signal-specific settings,
subject to installed SDK support and generic fallback. Span limits do not
configure log limits. Attribute length limits do not bound Body, nested
payloads carried in Body or all exception formatting: use a reviewed application
or processor policy for these surfaces when required. Avoid arbitrary new limits
without a source-backed need. When current messages are bounded and no Body
policy or size problem is established, preserve them and record that a new Body
cap is not applicable; do not import GenAI capture thresholds into ordinary logs.
Exercise selected oversized attributes/body, retained
identity/context, dropped-attribute accounting where supported, and privacy
after processing. Do not promise lossless export after truncation/drops.
Resource attributes SHOULD be exempt from common attribute limits; log-record
limits do not configure Resource limits. Preserve source-backed identity rather
than applying a record attribute-count budget to its Resource.

When constructing Body or attributes is expensive, use the detected native
logger's supported enablement query before that work. Check at the actual log
call, including inside an owned worker/callback, rather than caching a decision
across configuration changes. The OTel `Logger.Enabled` API is an optional
optimization for direct OTel emits; a cheap emit does not require a guard.
An OTel-only disabled result must not suppress an enabled original native sink.
Keep filtering independent of this optimization: callers may emit directly,
and processor `OnEmit` must still apply its configured filter. Do not add
unsupported queries, new filtering policy or a provider to copy an example.

Name the setting or public option that implements the selected count/value
policy; a promise such as "supported log limits" followed by numbers is not a
repair mechanism. Resolve the installed/project-compatible API first and apply
it to the existing provider owner. Use the public count/value options in the
detected language guide as capability leads, not new-provider or
dependency-upgrade requirements. Do not copy another language's configuration
shape into this provider. Preserve its resource, scope and existing processors.

Keep the Body/privacy policy separate from these options. For each selected
limit, specify below-limit, exactly-at-limit and above-limit inputs with units
and expected preservation/truncation/drop behavior. Include non-ASCII input
when the policy measures UTF-8 bytes. Preserve an adequate verified default;
do not force the observation's stricter policy onto an independent control.

State boundary outcomes, not only test sizes: below/at the selected limit
preserves permitted input; above a count limit retains at most that count and
accounts for discarded attributes; above a string-value limit truncates to at
most that length. Use explicit ASCII-character inputs for an unambiguous
string-length boundary, then check the installed SDK's Unicode behavior before
claiming broader character handling. Body overflow follows the separately
selected application policy, such as valid UTF-8 truncation or dropping, with
its own expected outcome and loss accounting. Common attribute rules also
cover byte-array units and recursive array/map value/depth handling where
implemented; inspect that capability instead of assuming every SDK/version
enforces the same arbitrary nested payload policy. These limits still do not
cap Body. Do not reimplement SDK internals to satisfy an unsupported feature.
If already selected, the development external-content `_ref` convention needs
a registry-defined base attribute and a string reference (preferably an absolute
URI); it does not authorize new storage or moving forbidden content elsewhere.

## LOG-DELIVERY -- Bound buffering and make loss visible

Identify the existing processor first. For an OTLP batch path, use the existing
provider's batch processor and check supported log-specific
queue, batch, schedule and timeout settings (`OTEL_BLRP_*` where supported);
`OTEL_BSP_*` configures spans. SDK defaults can be suitable; record the effective
values, keep batch size within queue size, and use public APIs when a language
does not consume those environment variables. A bounded queue may drop logs
when full. Do not promise durable or exactly-once delivery from an in-memory
batch processor; the one-record acceptance check is a healthy-path duplicate
check, not an OTLP network delivery guarantee.
An SDK stdout/console exporter may legitimately use a simple processor; batch
and queue settings then do not apply. Assess synchronous cost instead, preserve
the operator-owned branch, and do not confuse that exporter with a native
console sink. Its [unspecified format](https://opentelemetry.io/docs/specs/otel/logs/sdk_exporters/stdout/)
is not a production format contract.

Exercise a failing/unavailable receiver, bounded shutdown after final logs,
and overload when the application has a source-backed overload risk. Confirm
the application and original sink continue, diagnostics identify loss/failure
without secrets, and configured unrelated signals remain usable. An HTTP 200
with OTLP partial-success rejected records is not full acceptance. Report
attempted, received, rejected and dropped evidence separately; never infer
receipt from a successful enqueue or flush call alone.
Where implemented, [development SDK log metrics](https://opentelemetry.io/docs/specs/semconv/otel/sdk-metrics/) can supply
creation, queue-pressure, processed and exported counts. Record each instrument's
stage and retry/rejection semantics; created/processed is not receiver acceptance.
Do not add duplicate application metrics or assume unavailable instruments exist.
For a custom asynchronous processor, do not retain and mutate an unsafe shared
ReadWriteLogRecord after `OnEmit`; use a supported snapshot/clone, keep `OnEmit`
nonblocking and nonthrowing, and verify concurrent isolation. Built-in SDK
processors are not a reason to write a replacement. An optional event-to-span
bridge must still forward the log record when that feature is selected.

Compose the complete export/retry deadline rather than assuming a per-request
timeout bounds the entire operation. Test a receiver that stalls as well as one
that fails immediately. Use the existing SDK processor/caller deadline or a
supported public option to satisfy the selected overall budget; preserve a
verified adequate default. A client timeout does not prove zero receiver
acceptance: a receiver can accept after the caller stops waiting. Keep delivery
unknown until receipt evidence resolves it. When an OTLP response has populated
`partial_success`, the client MUST NOT retry that request, including an inferred
rejected subset; this also covers warning-only responses with zero rejections.
Keep request-attempt counts, received/accepted/rejected record counts and local
drops distinct; receiver rejection is not evidence of a local queue drop.

A completed negative OTLP response is a known protocol failure, not a request
still awaiting a response from a stalled server. Record the response and any
observed retry exhaustion. Keep acceptance uncertainty where the protocol leaves
it unspecified or evidence does not resolve it: after an oversized partial-success
response fails, OTLP explicitly leaves acceptance unspecified. Backend persistence
is a separate boundary. For a valid partial-success response with known request
count N and rejected count R (0 <= R <= N), report acknowledged accepted N-R and
rejected R separately from SDK emissions, attempts and received copies. Controlled
receiver rejection policy or observed late acceptance can resolve more counts;
neither a client failure result nor received bytes alone proves persisted loss
or success. Unknown accepted counts can be valid after a completed negative
response: the protocol does not always return per-record counts. They do not
make a known failure response pending. Record the observed response and terminal
retry decision separately, such as non-retryable HTTP 400 or a completed HTTP 503
whose server wait cannot fit the remaining export budget. Assess that evidence
across the report and raw observations; do not invent zero acceptance or rejection
counts merely to fill a field.

For the local evidence report, reconcile per-batch request and response counts
before summing a multi-batch trial. Save per-outcome attempted, received,
acknowledged accepted, rejected and unresolved counts with durable raw-receipt links in
the canonical runtime report's existing `evidence`/`observed_telemetry` fields,
or its Markdown evidence section. A compact shared fault test may cover multiple
outcomes; do not mark the mixed fault scenario `otlp_accepted` because one
healthy or partial-success subtrial was acknowledged. Split the observations or
explain each outcome using an existing visibility state; do not invent a mixed
visibility enum or new JSON keys. The [shared report contract](scripts/observe_report_core.py)
defines `proof_mode`, `visibility` and the existing evidence fields. Receipt alone,
completed failure, a stall and protocol acknowledgement retain distinct meanings.

The standard OTLP exporter timeout covers a whole batch export, including all
attempts and retry waits; it must not restart for each attempt, and an earlier
caller deadline takes precedence. Keep that specification contract separate
from an arbitrary SDK option named timeout. If the installed path only bounds
one request, report its SDK/capability limitation and verify a supported whole
deadline through the existing owner rather than claiming the standard contract
is satisfied or reimplementing the SDK.
For the selected transport, distinguish server throttling (`Retry-After` or
gRPC `RetryInfo`) from client backoff, within the same whole-export deadline.
HTTP `Retry-After` uses integer delay-seconds or an HTTP-date, never a value
such as `100ms`; gRPC retry durations use their own protocol representation.
If the server wait exceeds the remaining export/caller budget, end within the
earlier deadline instead of retrying early or requiring another attempt. For
example, `Retry-After: 1` requires a one-second wait; it cannot fit after a
response arriving 100ms into an 800ms export budget. State the valid header,
measured wait, remaining budget and expected request count in the handoff.
OTLP/HTTP retries use 429, 502, 503 and 504; other 4xx/5xx must not be retried.
Check installed exporter behavior with a controlled receiver before claiming
conformance; do not add an application retry loop around an SDK exporter.
Record supported request/response byte bounds separately from Body/attribute
limits. The [OTLP transport clauses](https://opentelemetry.io/docs/specs/otlp/)
require a separate source-matrix disposition for these HTTP boundaries:

- Receiver request parsing MUST be bounded, including after decompression;
  64 MiB is the recommended default. An exceeded bound requires HTTP 413.
- Exporter request bodies SHOULD be bounded, including before compression; 64 MiB is the
  recommended default. Above an active bound, the client MUST NOT send and
  SHOULD record the discard.
- Exporter response parsing MUST be bounded, including after decompression;
  4 MiB is the recommended default. An exceeded bound is a non-retryable error;
  the client SHOULD record the discard.
- Receiver response bodies MUST be bounded, including before compression;
  4 MiB is the recommended default. For an oversized partial response, the server
  SHOULD reduce response size without changing semantics when possible and practical.
  It MAY trim optional diagnostic fields. If the response still cannot fit,
  HTTP 500 is required and acceptance is unspecified.

Implementations SHOULD allow these limits to be configured; recommended numbers
are not mandatory application settings. For gRPC, assess its corresponding
message limits and non-retryable size-limit `RESOURCE_EXHAUSTED` outcomes rather than
copying HTTP status codes. A common client response-receive default of 4 MiB is
acceptable; the recommended request default is 64 MiB. Acceptance after an
unrepresentable partial response fails remains unspecified for gRPC too.

These are exporter/receiver duties. Resolve the selected transport, installed
capability and effective bounds in bytes, or mark capability unverified. Missing
public configuration alone does not prove a missing built-in bound. Do not add
an application parser, retry loop or forced dependency upgrade to imitate an
SDK-owned limit. Audit records ownership/disposition and plans below/at/above-
bound checks, including decompression where supported, oversized-response failure
and unresolved acceptance. Runtime reporting retains observed unsupported
capability or missing proof. If several destinations are configured, assess
each queue/ack/retry boundary independently; one success does not prove another.

A maximum attempt count is a ceiling, not a requirement to reach that many
attempts during every failure. An earlier deadline can end retries first.
Receiver request counts prove received requests, not every client connection
or interrupted attempt. Resolve whether the SDK option covers one attempt or
the whole export, including retry waits and jitter; do not infer its scope
from its name or add a separate full timeout for each retry without evidence.

Record the observed per-attempt timeout, retry/backoff duration and enclosing
caller/processor deadline with units and source evidence, including an absent
deadline. Then state the proposed or retained mechanism and composed budget
separately. A generic instruction to "bound retries" or a new timeout number
does not explain the current failure or establish which wait it bounds.

### Concrete deadline mechanisms

A concrete plan must name a public mechanism, not defer it as an unspecified
"overall deadline option". Resolve the installed/project-compatible SDK first;
the detected language guide supplies concrete proposals to verify, not upgrade
or override mandates. Keep
unsupported/installed capability unverified. Record checked library versions in
the task's evidence artifacts rather than pinning a release recipe in this guide.
Leave time for encoding/draining within the selected whole-operation budget
and verify it against a stalled receiver rather than assuming a timeout knob
proves the bound. Keep exporter attempts, processor waits and caller lifecycle
deadlines distinct; a caller that stops waiting may not cancel delivery.

## LOG-DIAGNOSTICS -- Keep diagnostics outside their own bridge

Trace SDK/exporter diagnostic routing through handlers, appenders, transports
and HTTP-client instrumentation. Avoid returning a log exporter failure to
the same application bridge recursively. Prefer the SDK's suppression and
separate diagnostic mechanism; preserve the ordinary application sink.
Prove bounded diagnostics, no recursive export storm and continued application
work under an exporter fault. Existing safe routing is coverage, not a reason
to add another error handler.
Name the actual routing/suppression mechanism in the repair and handoff, not
only a desired zero-recursion outcome.
When testing SDK attribute-discard diagnostics, count at most one diagnostic
per discarded-attribute record, not one per dropped attribute; inspect installed
support without replacing SDK diagnostic internals.

## LOG-VERIFY-FRESH -- Bind each verdict to its own execution evidence

This is a repository verification rule, not an upstream SDK requirement.
Give each repetition fresh report storage and bind it to the tested fixture or
application revision, dependency versions and command. Count actual successful,
failed, errored and skipped cases; a zero exit status or an old XML `tests`
total is insufficient. Missing reports, skipped cases, unexpected counts,
source changes during a run and missing runtime dependencies cannot pass.
Prepare dependencies using the project's supported manifests and lockfiles.

Persist per-trial results as they finish. On timeout, preserve available output,
mark the trial failed, clean up owned processes and retain the partial matrix;
continue independent trials where safe. Mark interruption separately. Keep
negative-control assertions distinct from safe configurations. Do not upgrade
SDK/in-memory results to application, agent, receiver or cloud proof. For
plan-only tasks, save acceptance requirements and leave execution Not run.

## Audit and instrumentation evidence

Audit each applicable rule as covered, partial, missing, unverified or not
applicable, citing source/config/installed capability or explicitly scoped
fixture evidence. A search miss is not runtime proof. Distinguish missing
source wiring from unavailable execution evidence and SDK-owned defaults.
Promote only concrete app-owned gaps into selectable findings and map their
acceptance scenarios. Instrument only authorized gaps using the existing
bridge and provider; retain supported operator settings and scope exclusions.

Use the detected language guide for bridge mapping, propagation, log limits,
deadline APIs and diagnostic routing. Test normal operation, explicit opt-out and a fault case;
distinguish focused SDK/bridge proof from full application/receiver proof.

## Acceptance handoff completeness

Make the following obligations explicit in the saved acceptance scenarios for
each selected rule. A general preservation promise or a rule ID alone does
not specify a runnable check. In a plan-only task, label settings as proposed
or retained defaults and runtime evidence as unverified; do not invent an
installed capability. Keep the handoff compact by sharing one outage scenario
across applicable rules that use the same owned path and proof boundary.

| Rule | Required acceptance detail |
|---|---|
| LOG-SPEC-CLOSURE | Applicable source clauses with requirement level, owner, source/config/default evidence, classification, selected finding/scenario mapping and explicit proof boundary. Reconcile every bound scenario assertion and negative control, using the audit proof_level and runtime proof_mode appropriate to that row. Combined claims need evidence from the same owned path; unrelated passing probes cannot be combined into end-to-end coverage. Unmapped clauses or missing evidence keep the relevant completeness claim partial. |
| LOG-RECORD | Name the detected/proposed bridge and verified version or unverified capability; specify source occurrence value/precision, observation time separately, source level to numeric severity, actual SeverityText/casing independently of the numeric band name, and actual body/category. |
| LOG-CONTEXT | Exact sampled/unsampled/outside IDs and SDK flags; real SDK-created sampled parent/child spans joined to their logs at the claimed boundary, with parentage/resource checks. Explicitly name one joint scenario traversing an owned async handoff and joining that worker/callback log to its received real span; separate known-ID async and synchronous join tests are insufficient. Separate unsampled non-export and outside-span controls, canonical OTLP fields from ordinary attributes, and non-OTLP formatter proof where selected. |
| LOG-ASYNC-HANDOFF | Caller capture before scheduling; exact request pairing, permitted MDC handling where applicable, worker cleanup and bridge placement relative to queues. Link the joint real-span async scenario, supported propagation and expected-loss controls. |
| LOG-EXCEPTION | Allowed exception fields and excluded sensitive fields, with bridge/event convention applicability and optional-field decisions. |
| LOG-LIMITS | Name the effective/proposed log attribute count/value settings or public API fields, separately from Body policy. Specify below/at/above-limit inputs, units, expected outcomes and supported drop accounting; generic limits plus numbers are insufficient. For an expensive construction path, name the supported native/direct-OTel enablement query, check current policy inside the owned worker, and prove construction/output counts across disabled/enabled/disabled states. Preserve cheap direct emits and original sinks when the OTel path is disabled. |
| LOG-DELIVERY | Record observed attempt/retry/caller deadlines and missing bounds with units/source separately from proposed queue/batch/schedule/export/shutdown settings and the composed budget. Assert batch <= queue on a batch path; a selected simple processor needs synchronous-cost evidence instead. Include a stalled receiver/caller deadline and a final log immediately before shutdown, with healthy receipt and bounded fault behavior checked independently. For each valid partial response of N records with R rejected, require N-R acknowledged accepted and R rejected; warning-only R=0 acknowledges all N without retry. Reconcile per-batch accounting before multi-batch totals and preserve per-outcome attempted/received/acknowledged accepted/rejected/dropped/unresolved counts with durable raw-receipt links. Include the selected transport's request/response byte limits, parsing after decompression where applicable, and oversized-response failure acceptance uncertainty with the correct SDK/receiver owner. Do not give a mixed fault scenario an unqualified accepted visibility from another successful subtrial; use existing report fields/states and explain each outcome. Retain unknown acceptance after a client timeout until a receipt resolves it. Name observed completed failure responses and terminal retry decisions separately from unresolved acceptance/persistence counts; a null count alone is not a failed response-classification check. |
| LOG-DIAGNOSTICS | Name the supported separate routing or suppression mechanism. One exporter-fault scenario asserts bounded diagnostic volume and export attempts, application progress, original sink output, and continued operation of each other configured signal. Explicitly mark absent signals not configured; preserving configuration alone is not operation proof. |
| LOG-VERIFY-FRESH | Unique report storage for each trial; planned manifest/lockfile dependency preparation; binding to source, command and dependency versions; actual success/failure/error/skip counts; preserved timeout console output, failed timeout verdict, owned-process cleanup and incremental structured partial results; explicit evidence scope. |

Before finalizing, compare the saved scenarios against these obligations and
the selected source/policy. An omitted obligation leaves that handoff partial;
unexecuted acceptance never becomes a passing runtime result.
Preserve the concrete obligations when shortening a report. Share scenarios by
ID and let the authoritative structured report own their detail, with a compact
Markdown summary where that artifact is permitted; do not duplicate the full
plan in both formats or delete settings, expected outcomes, dependency setup,
evidence bindings or fault assertions to meet a prose budget. Read back the
saved handoff and reconcile every applicable acceptance row before claiming
completeness. For unknown/optional SDK capabilities, give a concrete future
source/API-resolution step and conditional test, preserving the unverified
state; do not force an unselected development feature into application code.
Readback must check the conjunction: the owned async log itself joins its
received real SDK span in one scenario. Finding "async" and "real span" in
different scenarios is not that proof.
Plan-only restrictions prohibit executing setup, not specifying it: retain the
future dependency-preparation and unique-storage steps explicitly in the saved
handoff. Do not replace a named setting/public option or bridge with outcome
assertions alone.
