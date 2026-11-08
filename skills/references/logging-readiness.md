# Application logging readiness

Read this reference when auditing or changing an application logging path.
Use the existing language guide for bridge and provider ownership. These rules
extend the local-log contract; they do not authorize new sinks, sensitive-data
capture, a custom SDK, or changes outside the selected scope.

## Source and applicability

Reconcile rules with the installed SDK/bridge's public APIs and current official
documentation. Record package versions, source URLs/date, applicable stability
and unsupported features. Specification requirements for SDK authors are not
automatically missing application code: a supported SDK default can satisfy a
rule. Do not reimplement SDK behavior merely to make it visible in source.

The [log data model](https://opentelemetry.io/docs/specs/otel/logs/data-model/),
[Logs SDK](https://opentelemetry.io/docs/specs/otel/logs/sdk/),
[SDK configuration](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/),
[exception log conventions](https://opentelemetry.io/docs/specs/semconv/exceptions/exceptions-logs/),
[error handling](https://opentelemetry.io/docs/specs/otel/error-handling/), and
[sensitive-data guidance](https://opentelemetry.io/docs/security/handling-sensitive-data/)
are the primary sources. Check individual development features rather than
describing an entire language or exception convention as stable.

## LOG-RECORD -- Preserve record meaning

Check the real bridge's numeric severity mapping, source severity text, body,
logger/scope and timestamps. Common single-level mappings are DEBUG=5, INFO=9,
WARN=13 and ERROR=17; finer source levels can use their documented range.
Never copy Python level 40 or Go slog level 8 directly into SeverityNumber.
Unknown severity may remain 0/absent; do not invent an ERROR classification.

Preserve the event's occurrence Timestamp when available; ObservedTimestamp
represents collection time. Do not replace an older event time with export
time or assert that the two clocks must be equal. Treat nanoseconds/seconds
conversion explicitly and avoid unsafe JavaScript Number round trips for
64-bit nanoseconds. Optional absent fields alone are not defects. Preserve
structured values rather than turning an entire structured record into an
opaque string. EventName is an event classification when applicable, not a
mandatory field on ordinary application messages.

## LOG-CONTEXT -- Correlate without inventing or leaking context

Use the execution context at the log call, not a remembered last span. Check
top-level TraceId, SpanId and TraceFlags, including a valid unsampled context
and concurrent/asynchronous work. Restore/detach context after a request;
outside-span logs must not inherit the preceding request's IDs. An unsampled
span can still supply valid correlation even when no span is exported.

Do not introduce sampled-only filtering as a log baseline. Inspect explicit
operator filtering first: newer SDKs can offer development `trace_based`
filtering, defaulting to false. Preserve an explicitly selected supported
policy and test its intended drops separately. Do not fabricate or force-sample
a span to make correlation pass. Test both sampled and unsampled contexts and
a no-context call, checking exact IDs and flags rather than nonempty strings.

## LOG-EXCEPTION -- Preserve exception semantics within privacy policy

Where exception details are already collected or explicitly selected, use
the supported bridge/SDK exception mapping and `exception.type`,
`exception.message`, and `exception.stacktrace` as applicable. Do not export
an exception object's arbitrary serialization under invented keys. Minimize
and sanitize message, stack, nested structured values and formatter/MDC fields
before the exporting processor; truncation alone is not redaction.

The exception-log convention explicitly excludes logging bridges from its
instrumentation-specific recording guidance. Do not force every bridged error
to add EventName, change severity, emit a second event, or migrate existing
span exceptions. Preserve bridge semantics and versioned opt-ins. For newly
selected instrumentation exception events, check the applicable conventions
and stability, associate the actual operation context, and choose severity
from impact. No policy permission to collect a message/stack means omit it
and retain permitted type/category evidence, not enable capture for a test.

## LOG-LIMITS -- Bound record cost

Inspect effective log attribute count/value limits and existing operator
values; SDK defaults may already suffice. `OTEL_LOGRECORD_ATTRIBUTE_COUNT_LIMIT`
and `OTEL_LOGRECORD_ATTRIBUTE_VALUE_LENGTH_LIMIT` are signal-specific settings,
subject to installed SDK support and generic fallback. Span limits do not
configure log limits. Attribute length limits do not bound Body, arbitrary
nested payloads or all exception formatting: use a reviewed application or
processor policy for these surfaces when required. Avoid arbitrary new limits
without a source-backed need. Exercise oversized attributes/body, retained
identity/context, dropped-attribute accounting where supported, and privacy
after processing. Do not promise lossless export after truncation/drops.

## LOG-DELIVERY -- Bound buffering and make loss visible

Use the existing provider's batch processor. Check supported log-specific
queue, batch, schedule and timeout settings (`OTEL_BLRP_*` where supported);
`OTEL_BSP_*` configures spans. SDK defaults can be suitable; record the effective
values, keep batch size within queue size, and use public APIs when a language
does not consume those environment variables. A bounded queue may drop logs
when full. Do not promise durable or exactly-once delivery from an in-memory
batch processor; the one-record acceptance check is a healthy-path duplicate
check, not an OTLP network delivery guarantee.

Exercise a failing/unavailable receiver, bounded shutdown after final logs,
and overload when the application has a source-backed overload risk. Confirm
the application and original sink continue, diagnostics identify loss/failure
without secrets, and configured unrelated signals remain usable. An HTTP 200
with OTLP partial-success rejected records is not full acceptance. Report
attempted, received, rejected and dropped evidence separately; never infer
receipt from a successful enqueue or flush call alone.

## LOG-DIAGNOSTICS -- Keep diagnostics outside their own bridge

Trace SDK/exporter diagnostic routing through handlers, appenders, transports
and HTTP-client instrumentation. Avoid returning a log exporter failure to
the same application bridge recursively. Prefer the SDK's suppression and
separate diagnostic mechanism; preserve the ordinary application sink.
Prove bounded diagnostics, no recursive export storm and continued application
work under an exporter fault. Existing safe routing is coverage, not a reason
to add another error handler.

## Audit and instrumentation evidence

Audit each applicable rule as covered, partial, missing, unverified or not
applicable, citing source/config/installed capability or explicitly scoped
fixture evidence. A search miss is not runtime proof. Distinguish missing
source wiring from unavailable execution evidence and SDK-owned defaults.
Promote only concrete app-owned gaps into selectable findings and map their
acceptance scenarios. Instrument only authorized gaps using the existing
bridge and provider; retain supported operator settings and scope exclusions.

For Java, test Logback/Log4j mapping and MDC isolation through the selected
agent/appender without adding a second SDK. For Python, check the selected
logging bridge's level mapping and contextvars across async tasks, detach
tokens, and avoid routing exporter diagnostic loggers into a root OTel handler.
For Go, use the matching bridge and pass the actual context to `InfoContext` /
`ErrorContext` or the detected logger equivalent; slog numeric levels are not
OTel severity numbers. For Node.js, initialize the detected bridge before
logger imports, check async context isolation and preserve timestamp precision.
In every language, test normal operation, explicit opt-out and a fault case;
distinguish focused SDK/bridge proof from full application/receiver proof.

## Acceptance handoff completeness

Make the following obligations explicit in the saved acceptance scenarios for
each selected rule. A general preservation promise or a rule ID alone does
not specify a runnable check. In a plan-only task, label settings as proposed
or retained defaults and runtime evidence as unverified; do not invent an
installed capability. Keep the handoff compact by sharing one outage scenario
across the applicable rules.

| Rule | Required acceptance detail |
|---|---|
| LOG-RECORD | Source occurrence value/precision, observation time separately, source level to numeric severity, and actual body/category. |
| LOG-CONTEXT | Exact sampled/unsampled/outside IDs and flags; concurrent and asynchronous handoff/isolation checks for owned paths, or an explicit source-backed absence of those paths. |
| LOG-EXCEPTION | Allowed exception fields and excluded sensitive fields, with bridge/event convention applicability and optional-field decisions. |
| LOG-LIMITS | Log attribute count/value settings versus the separate Body policy, oversize boundaries and supported drop accounting. |
| LOG-DELIVERY | Effective or concrete proposed queue capacity, batch ceiling, schedule/export/shutdown deadlines via supported settings/public options; explicitly assert batch size <= queue capacity. Record attempted/accepted/rejected/dropped counts independently. |
| LOG-DIAGNOSTICS | One exporter-fault scenario asserting bounded diagnostic volume and export attempts, application progress, original sink output, and continued operation of each other configured signal. Explicitly mark absent signals not configured; preserving configuration alone is not operation proof. |

Before finalizing, compare the saved scenarios against these obligations and
the selected source/policy. An omitted obligation leaves that handoff partial;
unexecuted acceptance never becomes a passing runtime result.
