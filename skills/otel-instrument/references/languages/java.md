# Java OpenTelemetry Guide

Language-specific instrumentation guidance for Java services.

---

## Preflight: Trace Wiring Inventory

Before adding any dependency, SDK/provider setup, tracer binding, or custom span
in a Java project, build an existing trace wiring inventory:

- **Runtime/agent:** `-javaagent`, `JAVA_TOOL_OPTIONS`, `OTEL_*`, launcher
  scripts, Docker/Kubernetes startup, sidecars, and collector config.
- **Build files:** Maven/Gradle OTel dependencies, Java agent artifacts,
  framework tracing dependencies, and any existing telemetry modules.
- **SDK/provider setup:** `OpenTelemetrySdk`, `SdkTracerProvider`,
  `GlobalOpenTelemetry`, `OpenTelemetry`, framework `@Bean`/`@Factory`,
  Guice `@Provides`, and external bootstrap modules named in the injector.
- **Tracer usage:** constructor-injected `Tracer`, `getTracer`, `spanBuilder`,
  `Span.current`, span status, `recordException`, MDC/log correlation, and
  propagation inject/extract.

Classify trace wiring as one of:
- `auto-only` — Java agent present, no custom spans
- `custom-with-provider` — custom spans with an in-repo provider/binding
- `custom-provider-external` — custom spans with provider supplied by external bootstrap
- `missing` — no OTel setup found

State the classification and evidence before editing.

### Trace Source of Truth

Record the trace source of truth in the preflight summary:
- Existing provider/binding to reuse
- Existing agent-backed global provider
- External provider likely supplied by bootstrap
- Evidence that the provider/binding is missing

### Application Log Source of Truth

Before changing Java startup configuration, inventory:

- The detected logging facade and implementation, including Logback or Log4j,
  every console/file/platform appender, additivity, levels, formatters, and
  rotation policy.
- Any existing OpenTelemetry appender, SDK `LoggerProvider`, log exporter,
  agent appender instrumentation, or collector/sidecar log pipeline that can
  export the same application record.
- The effective `OTEL_LOGS_EXPORTER`,
  `OTEL_EXPORTER_OTLP_LOGS_PROTOCOL`,
  `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT`, and signal-specific logs headers across
  environment variables, JVM `-D` properties, service managers, containers,
  and deployment manifests.
- Generic `OTEL_EXPORTER_OTLP_ENDPOINT` and
  `OTEL_EXPORTER_OTLP_HEADERS` values. Record whether either points to or
  authenticates to a direct-cloud destination that logs must not inherit.

Classify the application-log path as `local-otlp-default`,
`explicitly-disabled`, `operator-owned`, `correlation-only`, or
`unsupported-stack`. State which component owns the single OTel bridge and
which existing appenders remain active before editing.

---

## Implementation Rules

- Reuse the existing trace source of truth. If custom spans already obtain a
  tracer through DI, framework beans, globals, or an agent-backed global
  provider, add spans through that path instead of creating a second provider or
  a new binding.
- Do not add a new dependency, SDK initializer, tracer provider, meter provider,
  or DI `Tracer` binding unless the inventory proves it is absent and required
  for the requested signal. If dependency manifests already contain the OTel APIs
  you need, do not add duplicate dependencies.
- Before adding dependencies or a `Tracer` provider, inspect existing
  `pom.xml`/Gradle files, Java agent startup, DI modules, framework factories,
  and current constructor-injected `Tracer` usage. Existing OTel dependencies or
  constructor-injected custom spans mean tracing was already partially present.
- Prefer `GlobalOpenTelemetry` only as a bridge to the Java agent's global
  provider. Do not call `OpenTelemetrySdk.builder()` or install another provider
  in an agent-instrumented app unless the repo already uses that pattern and
  there is one provider per process.
- For DI apps (Guice/Micronaut/Spring), search every module/factory plus
  external bootstrap modules named in the injector. If a constructor already
  accepts `Tracer` and the app builds or starts, assume a binding may be provided
  externally. Add a fallback binding only after proving injector startup fails
  without it.
- If a fallback `Tracer` binding is truly needed, place it in an
  observability-owned module/factory such as `OtelModule`, `TelemetryModule`, or
  `ObservabilityConfig`, not in an unrelated persistence/client/business module.
  The fallback should bridge to the existing global/runtime provider
  (`GlobalOpenTelemetry.getTracer(...)` in Java agent setups) and must not
  initialize a second SDK.
- For Guice/Micronaut/Spring DI, do not add `@Provides Tracer`, `@Bean Tracer`,
  or `@Factory Tracer` by default. First verify no existing binding is supplied
  by the app, framework, or external bootstrap module. If one is required, add it
  to an OTel/Telemetry module and mention in the final response why it was
  needed.

### Agent-Owned Application Logs

- For a supported Logback or Log4j stack with the Java agent, rely on the
  agent's logging-appender instrumentation and autoconfigured log provider.
  Do not add an `OpenTelemetryAppender` dependency or appender entry, construct
  another `SdkLoggerProvider`, install a second bridge, or add a separate
  shutdown hook.
- Preserve every existing console, file, and platform appender. Do not replace
  its level, formatter, additivity, or rotation policy. The agent bridge is an
  additional export path, not a replacement for application logging.
- If an OTel appender or bridge already exports the same record, keep exactly
  one owner. Preserve the existing owner as operator-owned or explicitly
  consolidate onto the agent after proving equivalence; never run the manual
  appender and agent appender for the same record.
- Apply this exporter precedence without overwriting operator intent:

  | Existing log configuration | Required action |
  |---|---|
  | exporter unset/empty and endpoint absent or detected-local | Default the exporter to `otlp` for the local Obstudio baseline |
  | exporter `otlp` and endpoint absent or detected-local | Preserve `otlp` and use the detected local Observer endpoint |
  | exporter unset/`otlp` and endpoint non-local | Fail closed before the agent starts its log path; report the operator-owned boundary conflict |
  | `none` | Keep it disabled; do not add another provider, exporter, or bridge |
  | any other explicit value | Preserve it as operator-owned; do not supplement it with a local pipeline |

- When the logs exporter is absent/`otlp`, set the signal-specific OTLP/HTTP
  endpoint to `http://localhost:4318/v1/logs` for a host JVM or the equivalent
  detected Observer service address in Docker. Accept an explicit endpoint on
  that branch only when it matches the detected local receiver and its
  protocol/path tuple. If it is non-local or direct-cloud, do not enable the
  agent-owned log provider/bridge; fail closed and report the boundary conflict
  rather than silently replacing it or adding a second local pipeline. Do not
  validate the endpoint on `none` or another non-OTLP exporter branch.
- Never let logs inherit a generic direct-cloud endpoint or header. Move a
  direct-cloud `OTEL_EXPORTER_OTLP_ENDPOINT` and
  `OTEL_EXPORTER_OTLP_HEADERS` to trace- and metric-specific endpoint/header
  settings, then remove the generic cloud settings from the startup surface.
  Keep the logs endpoint local and do not copy a realm, ingest URL, access
  token, auth header, exporter, or forwarding flag into log configuration.
  Reject a generic header from the local log path even when signal-specific
  logs headers are present, because the SDK may merge both. Obstudio cloud
  forwarding remains traces and metrics only.
- Treat log bodies, arguments, throwable rendering, markers, structured
  messages, and MDC/context data as a privacy surface. Capture only reviewed,
  bounded keys with the detected appender's
  `experimental.capture-mdc-attributes` setting.
  Never use `*` as the MDC allowlist, and never include raw request, user,
  tenant, session, trace, URL, exception, or secret values without an explicit
  policy allowance. Agent-provided trace/span correlation does not require
  wildcard MDC capture.
- Let the Java agent's JVM shutdown hook flush its batch log processor with the
  other agent-owned providers. Do not create an application-owned log SDK only
  to obtain shutdown behavior.

---

## OTel Java Agent (Recommended)

The OpenTelemetry Java agent provides auto-instrumentation with zero code changes.

### Download

```bash
curl -L https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/latest/download/opentelemetry-javaagent.jar \
  -o opentelemetry-javaagent.jar
```

### Host/native run

Prefer the existing JVM startup path. Check in one guarded launcher and use it
from the host, service manager, and container so deployment-time overrides
cannot skip the log ownership checks. Save this as `otel-entrypoint.sh`:

```bash
#!/bin/sh
set -eu
set -f

fail() { printf '%s\n' "$*" >&2; exit 1; }

# Java system properties override environment variables. Scan the standard JVM
# option sources in their effective OpenJDK order; later existing -D values
# retain normal Java precedence.
logs_exporter=${OTEL_LOGS_EXPORTER:-}
logs_protocol=${OTEL_EXPORTER_OTLP_LOGS_PROTOCOL:-}
logs_endpoint=${OTEL_EXPORTER_OTLP_LOGS_ENDPOINT:-}
generic_endpoint=${OTEL_EXPORTER_OTLP_ENDPOINT:-}
generic_headers=${OTEL_EXPORTER_OTLP_HEADERS:-}
logs_exporter_d=0
logs_protocol_d=0
logs_endpoint_d=0

read_otel_property() {
  otel_jvm_arg=${1#\"}; otel_jvm_arg=${otel_jvm_arg%\"}
  otel_jvm_arg=${otel_jvm_arg#\'}; otel_jvm_arg=${otel_jvm_arg%\'}
  case "$otel_jvm_arg" in
    @*|-XX:VMOptionsFile=*)
      fail "expand Java argument files so OTel -D ownership can be checked" ;;
  esac
  otel_property_name=${otel_jvm_arg%%=*}
  case "$otel_jvm_arg" in
    *=*) otel_property_value=${otel_jvm_arg#*=} ;;
    *) otel_property_value= ;;
  esac
  otel_property_value=${otel_property_value#\"}
  otel_property_value=${otel_property_value%\"}
  otel_property_value=${otel_property_value#\'}
  otel_property_value=${otel_property_value%\'}
  case "$otel_property_name" in
    -Dotel.logs.exporter)
      logs_exporter=$otel_property_value; logs_exporter_d=1 ;;
    -Dotel.exporter.otlp.logs.protocol)
      logs_protocol=$otel_property_value; logs_protocol_d=1 ;;
    -Dotel.exporter.otlp.logs.endpoint)
      logs_endpoint=$otel_property_value; logs_endpoint_d=1 ;;
    -Dotel.exporter.otlp.endpoint)
      generic_endpoint=$otel_property_value ;;
    -Dotel.exporter.otlp.headers)
      generic_headers=$otel_property_value ;;
  esac
}

# Relevant option values contain no whitespace. Plain space/tab characters may
# separate environment options; every other control character is rejected
# before this split. Disabling glob expansion above keeps the split from
# expanding operator-provided wildcard characters.
scan_otel_options() {
  for otel_jvm_arg in $1; do
    read_otel_property "$otel_jvm_arg"
  done
}

validate_otel_option_env() {
  otel_option_env_name=$1
  otel_option_env_value=$2
  # OpenJDK may split CR, LF, form feed, vertical tab, and other control
  # whitespace even though this POSIX shell's unquoted expansion does not use
  # all of them as IFS separators. Remove allowed tab separators, then reject
  # every remaining control byte so the guard and JVM cannot parse different
  # effective -D options.
  otel_tab=$(printf '\t_'); otel_tab=${otel_tab%_}
  otel_control_check=$otel_option_env_value
  while case "$otel_control_check" in *"$otel_tab"*) true ;; *) false ;; esac; do
    otel_control_prefix=${otel_control_check%%"$otel_tab"*}
    otel_control_suffix=${otel_control_check#*"$otel_tab"}
    otel_control_check=$otel_control_prefix$otel_control_suffix
  done
  case "$otel_control_check" in
    *[[:cntrl:]]*)
      fail "$otel_option_env_name contains unsupported non-space/tab control whitespace; move reviewed options to explicit launcher arguments" ;;
  esac
  case "$otel_option_env_value" in
    *\"*|*\'*|*\\*)
      fail "$otel_option_env_name contains unsupported quoting, backslashes, or a whitespace-bearing value; move reviewed options to explicit launcher arguments" ;;
  esac
}

scan_otel_launcher_args() {
  otel_skip_option_value=0
  for otel_jvm_arg in "$@"; do
    otel_launcher_arg=${otel_jvm_arg#\"}; otel_launcher_arg=${otel_launcher_arg%\"}
    otel_launcher_arg=${otel_launcher_arg#\'}; otel_launcher_arg=${otel_launcher_arg%\'}
    case "$otel_launcher_arg" in
      @*) fail "expand Java argument files so OTel -D ownership can be checked" ;;
    esac
    if [ "$otel_skip_option_value" -eq 1 ]; then
      otel_skip_option_value=0
      continue
    fi
    case "$otel_launcher_arg" in
      -jar|-m|--module|--module=*) break ;;
      -cp|-classpath|--class-path|-p|--module-path|--upgrade-module-path|\
      --add-modules|--enable-native-access|-d|--describe-module|\
      --add-reads|--add-exports|--add-opens|--limit-modules|--patch-module|\
      --source)
        otel_skip_option_value=1 ;;
      -*) read_otel_property "$otel_launcher_arg" ;;
      *) break ;; # main class or source file; every following value is an app arg
    esac
  done
}
validate_otel_option_env JAVA_TOOL_OPTIONS "${JAVA_TOOL_OPTIONS:-}"
validate_otel_option_env JDK_JAVA_OPTIONS "${JDK_JAVA_OPTIONS:-}"
validate_otel_option_env _JAVA_OPTIONS "${_JAVA_OPTIONS:-}"
scan_otel_options "${JAVA_TOOL_OPTIONS:-}"
# JDK_JAVA_OPTIONS and explicit launcher arguments may contain options whose
# next token is a value. Do not mistake that value, or an application argument
# after the launch target, for an effective JVM property.
scan_otel_launcher_args ${JDK_JAVA_OPTIONS:-}
scan_otel_launcher_args "$@"
scan_otel_options "${_JAVA_OPTIONS:-}"

add_logs_exporter=0
add_logs_protocol=0
add_logs_endpoint=0
if [ -z "$logs_exporter" ]; then
  logs_exporter=otlp
  # Current agents treat an empty system property as their default OTLP
  # exporter. Keep that property in place and do not add a duplicate key.
  [ "$logs_exporter_d" -eq 1 ] || add_logs_exporter=1
fi

# Explicit none and non-OTLP exporters are operator-owned. Add nothing and do
# not interpret their endpoint or generic trace/metric configuration.
if [ "$logs_exporter" != otlp ]; then
  exec java "$@"
fi

if [ -z "$logs_protocol" ]; then
  [ "$logs_protocol_d" -eq 0 ] || fail "remove the empty OTLP logs protocol property"
  logs_protocol=http/protobuf
  add_logs_protocol=1
fi
case "${OBSTUDIO_OBSERVER_TARGET:-host}" in
  host)
    local_http_endpoint=http://localhost:4318
    local_grpc_endpoint=http://localhost:4317 ;;
  docker)
    local_http_endpoint=http://observer:4318
    local_grpc_endpoint=http://observer:4317 ;;
  *) fail "unsupported Observer target" ;;
esac
case "$logs_protocol" in
  http/protobuf)
    local_logs_endpoint=$local_http_endpoint/v1/logs ;;
  grpc)
    local_logs_endpoint=$local_grpc_endpoint ;;
  *) fail "unsupported OTLP logs protocol" ;;
esac
if [ -z "$logs_endpoint" ]; then
  [ "$logs_endpoint_d" -eq 0 ] || fail "remove the empty OTLP logs endpoint property"
  logs_endpoint=$local_logs_endpoint
  add_logs_endpoint=1
elif [ "$logs_endpoint" != "$local_logs_endpoint" ]; then
  fail "OTLP logs endpoint is not the detected local Observer"
fi
if [ -n "$generic_endpoint" ] && \
   [ "$generic_endpoint" != "$local_http_endpoint" ] && \
   [ "$generic_endpoint" != "$local_grpc_endpoint" ]; then
  fail "move a non-local generic OTLP endpoint to trace/metric signal variables"
fi
if [ -n "$generic_headers" ]; then
  fail "move generic OTLP headers to trace/metric signal variables and remove the generic value"
fi

case "${OBSTUDIO_JAVA_LOG_DEFAULTS:-environment}" in
  environment)
    [ "$add_logs_exporter" -eq 0 ] || export OTEL_LOGS_EXPORTER=$logs_exporter
    [ "$add_logs_protocol" -eq 0 ] || export OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=$logs_protocol
    [ "$add_logs_endpoint" -eq 0 ] || export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=$logs_endpoint
    ;;
  system-properties)
    # A key is added only when neither environment nor an existing -D supplied it.
    [ "$add_logs_endpoint" -eq 0 ] || set -- "-Dotel.exporter.otlp.logs.endpoint=$logs_endpoint" "$@"
    [ "$add_logs_protocol" -eq 0 ] || set -- "-Dotel.exporter.otlp.logs.protocol=$logs_protocol" "$@"
    [ "$add_logs_exporter" -eq 0 ] || set -- "-Dotel.logs.exporter=$logs_exporter" "$@"
    ;;
  *) fail "OBSTUDIO_JAVA_LOG_DEFAULTS must be environment or system-properties" ;;
esac

exec java "$@"
```

Invoke the checked-in launcher with the project's existing Java arguments:

```bash
./otel-entrypoint.sh \
  -javaagent:./opentelemetry-javaagent.jar \
  -Dotel.service.name=my-service \
  -Dotel.exporter.otlp.endpoint=http://localhost:4318 \
  -Dotel.exporter.otlp.protocol=http/protobuf \
  -Dotel.resource.attributes=deployment.environment.name=production \
  -jar my-app.jar
```

The launcher resolves each effective setting from the environment and standard
JVM option sources, including `JAVA_TOOL_OPTIONS` and explicit launcher `-D`
arguments. It never adds a property key already present on a JVM property
surface. `none` and every other explicit exporter run unchanged; only the
absent/`otlp` branch receives local defaults and rejects a non-local signal or
generic endpoint and an effective generic header. An empty
`-Dotel.logs.exporter=` keeps its one existing key and follows the current
agent's default OTLP behavior. Launcher scanning stops at the main class,
source file, JAR, or module so application arguments cannot alter ownership.
Keep each relevant JVM option value whitespace-free, as required for the
exporter, protocol, endpoint, and encoded header forms shown here; only plain
space/tab option separators are accepted in the three standard option
environments. The guard rejects argument files, CR/LF/form-feed/vertical-tab
and other control whitespace, and quoted or backslash-escaped JVM option
environment values instead of guessing how OpenJDK will parse them. Move such
reviewed options to explicit launcher arguments, where the calling shell
preserves each value's boundary.

### If the Project Already Runs in Docker

```dockerfile
FROM eclipse-temurin:21-jre

COPY opentelemetry-javaagent.jar /opt/agent.jar
COPY otel-entrypoint.sh /usr/local/bin/otel-entrypoint
COPY my-app.jar /opt/app.jar
RUN chmod 0755 /usr/local/bin/otel-entrypoint

ENV OBSTUDIO_OBSERVER_TARGET=docker
ENV OTEL_SERVICE_NAME=my-service
ENV OTEL_EXPORTER_OTLP_ENDPOINT=http://observer:4318
ENV OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
ENV OTEL_METRIC_EXPORT_INTERVAL=1000
ENV OTEL_METRIC_EXPORT_TIMEOUT=500

ENTRYPOINT ["/usr/local/bin/otel-entrypoint"]
CMD ["-javaagent:/opt/agent.jar", "-jar", "/opt/app.jar"]
```

Docker environment, `JAVA_TOOL_OPTIONS`, and command overrides all pass through
the same guard. `docker run -e OTEL_LOGS_EXPORTER=none ...` disables OTLP logs
without removing existing appenders; a non-OTLP exporter remains operator-owned,
while a non-local OTLP logs endpoint or generic header fails before Java starts.

### JVM system-property equivalent

When the existing launcher owns JVM arguments, ask the same entrypoint to add
missing local defaults as system properties:

```bash
OBSTUDIO_JAVA_LOG_DEFAULTS=system-properties \
./otel-entrypoint.sh \
  -javaagent:./opentelemetry-javaagent.jar \
  -Dotel.service.name=my-service \
  -Dotel.exporter.otlp.endpoint=http://localhost:4318 \
  -Dotel.exporter.otlp.protocol=http/protobuf \
  -jar my-app.jar
```

The entrypoint does not append a log property when the same key already appears
in `JAVA_TOOL_OPTIONS` or the launcher arguments, and it does not synthesize any
log properties when the effective exporter is `none` or non-OTLP. This prevents
the example from overriding an operator's higher-precedence JVM configuration.
For a reviewed MDC allowlist, add only the property matching the detected stack,
for example
`-Dotel.instrumentation.logback-appender.experimental.capture-mdc-attributes=operation,outcome`
or
`-Dotel.instrumentation.log4j-appender.experimental.capture-mdc-attributes=operation,outcome`.
Never set either allowlist to `*`.

---

## Auto-Instrumented Frameworks

The Java agent auto-instruments:
- Spring MVC (REST controllers)
- Spring WebFlux (reactive endpoints)
- Spring Data (JPA, JDBC)
- RestTemplate and WebClient (outbound HTTP)
- Kafka producers/consumers (including clients used internally by Kafka Streams)
- RabbitMQ, gRPC
- Servlet containers (Tomcat, Jetty, Undertow)
- JDBC drivers

No code changes needed for basic coverage.
In final user-facing output, name only the frameworks and clients actually
detected in the project. For Spring MVC or servlet apps, state that HTTP server
spans and request duration metrics will come through the agent. For Kafka or
Kafka Streams apps, state that producer, consumer, and stream client spans will
come through the agent. Also name the service identity and exporter settings,
for example `OTEL_SERVICE_NAME` and `OTEL_EXPORTER_OTLP_ENDPOINT`.

### Kafka Processing Patterns

For Java Kafka services, preserve the current processing pattern instead of
rewriting the application to fit instrumentation. Do not convert one Kafka
processing model into another just to add telemetry:

- Plain producer/consumer services: keep `KafkaProducer.send()` and
  `KafkaConsumer.poll()` startup behavior intact.
- Batch consumers: keep `ConsumerRecords` batch processing, offset commit
  behavior, and batch-level error handling intact.
- Listener-container services, such as Spring Kafka `@KafkaListener` apps: keep
  listener annotations, container factories, topic properties, and framework
  startup intact.
- Kafka Streams: keep the topology, processors, state stores, topic flow, and
  stream lifecycle code intact.

The Java agent covers Kafka producer and consumer clients, including clients
used internally by Kafka Streams and Spring Kafka listener containers. It does
not create spans for Kafka Streams DSL operations or business batch-processing
steps by itself. Treat processed-record counts, failed-parse counters,
batch-size metrics, high-risk alert counts, and topology-level spans as optional
custom business instrumentation unless the user explicitly requests them.

---

## Manual Span Creation

For custom business logic spans, add the OTel API dependency:

```xml
<dependency>
  <groupId>io.opentelemetry</groupId>
  <artifactId>opentelemetry-api</artifactId>
</dependency>
```

```java
import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.api.trace.Tracer;

public class PaymentService {
    private static final Tracer tracer =
        GlobalOpenTelemetry.getTracer("payment-service");

    public void processPayment(String orderId, double amount) {
        Span span = tracer.spanBuilder("process_payment")
            .setAttribute("order.id", orderId)
            .setAttribute("payment.amount", amount)
            .startSpan();

        try (var scope = span.makeCurrent()) {
            gateway.charge(amount);
            span.setStatus(StatusCode.OK);
        } catch (Exception e) {
            span.setStatus(StatusCode.ERROR, e.getMessage());
            span.recordException(e);
            throw e;
        } finally {
            span.end();
        }
    }
}
```

### Using Annotations (with Java agent)

```java
import io.opentelemetry.instrumentation.annotations.WithSpan;
import io.opentelemetry.instrumentation.annotations.SpanAttribute;

@WithSpan("repository.get")
public Item getItem(@SpanAttribute("item.id") String id) {
    Span span = Span.current();
    try {
        Item result = db.get(id);
        return result;
    } catch (Exception e) {
        span.recordException(e);
        span.setStatus(StatusCode.ERROR, e.getMessage());
        throw e;
    }
}
```

---

## Custom Metrics

Before adding a custom counter or histogram for an outcome that happens
inside a request the Java agent already covers, check whether it belongs as
an attribute on `http.server.request.duration` instead — see `../../SKILL.md`
`#### Implementation Rules`. The agent already sets
`http.response.status_code` on that metric for every request, and
`error.type` for a 5xx (or otherwise invalid) status, with no extra code --
a plain 4xx client-error response does not set `error.type` on a server
span. Define a new instrument when the signal does not correlate 1:1 with a
single request (a queue-depth gauge or background job outcome), or cannot be
represented by an attribute on the existing RED metric -- for example a
same-status-different-cause outcome (a 200 that is a logical failure, several
distinct 4xx causes, or several distinct 5xx causes) that `http.response.status_code`
and `error.type` cannot distinguish on their own and that needs its own
dimension. The
Java agent has no per-call metric-attribute hook for adding such a dimension
to `http.server.request.duration` the way Go's `Labeler` can -- a standalone
custom counter/histogram is the correct fallback here, not a workaround to
avoid.

```java
import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.metrics.Meter;
import io.opentelemetry.api.metrics.LongCounter;
import io.opentelemetry.api.common.Attributes;

Meter meter = GlobalOpenTelemetry.getMeter("my-service");

LongCounter ordersProcessed = meter.counterBuilder("orders.processed.count")
    .setDescription("Total orders processed")
    .setUnit("{orders}")
    .build();

// Usage
ordersProcessed.add(1, Attributes.of(stringKey("order.type"), "standard"));
```

---

## Error Handling

APM backends identify errors via `otel.status_code = ERROR`:

```java
span.setStatus(StatusCode.ERROR, "Payment gateway timeout");
span.recordException(exception);
```

Spring MVC auto-instrumentation sets ERROR on unhandled exceptions and 5xx responses automatically.

---

## OTLP Export Configuration

Use Java agent environment variables or their dotted JVM-property equivalents.
Keep an HTTP/protobuf logs endpoint paired with the complete `/v1/logs` path.

| Variable | Default | Purpose |
|----------|---------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | Common OTLP endpoint only when it is local or collector-owned; never leave a direct-cloud value for logs to inherit |
| `OTEL_EXPORTER_OTLP_HEADERS` | unset | Move cloud credentials to trace/metric signal headers and remove this generic value before enabling the agent-owned local log path, even when logs headers are set |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` for Java agent 2.x | Common protocol when using port 4318 |
| `OTEL_LOGS_EXPORTER` | `otlp` only when absent and the logs endpoint is absent or detected-local | `none` disables agent log export; any other explicit value is preserved |
| `OTEL_EXPORTER_OTLP_LOGS_PROTOCOL` | `http/protobuf` for the local baseline | Signal-specific log transport |
| `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | `http://localhost:4318/v1/logs` for a host JVM | Signal-specific local Observer application-log destination |
| `OTEL_EXPORTER_OTLP_LOGS_HEADERS` | unset | Only signal-specific operator-owned log headers; never inherit a generic cloud credential |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` / `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` | unset | Use these instead of a generic endpoint for direct-cloud trace/metric export |
| `OTEL_EXPORTER_OTLP_TRACES_HEADERS` / `OTEL_EXPORTER_OTLP_METRICS_HEADERS` | unset | Keep cloud credentials signal-specific; never copy them to logs |
| `OTEL_SERVICE_NAME` | (must be set) | Service identity in telemetry |
| `OTEL_METRIC_EXPORT_INTERVAL` | `60000` | Metric export interval (ms) |
| `OTEL_METRIC_EXPORT_TIMEOUT` | `30000` | Metric export timeout (ms) |
| `OTEL_BSP_SCHEDULE_DELAY` | `5000` | Span batch export delay (ms) |

For local development with the Observer:

Use this explicit HTTP baseline only when preflight found no operator-owned
logs exporter, protocol, or endpoint. If any of those is configured -- including
`OTEL_LOGS_EXPORTER=none` -- use the precedence-aware host setup above instead.

```bash
OTEL_SERVICE_NAME=my-service \
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf \
OTEL_EXPORTER_OTLP_HEADERS="" \
OTEL_LOGS_EXPORTER=otlp \
OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=http/protobuf \
OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://localhost:4318/v1/logs \
OTEL_METRIC_EXPORT_INTERVAL=1000 \
OTEL_METRIC_EXPORT_TIMEOUT=500 \
OTEL_BSP_SCHEDULE_DELAY=100 \
java -javaagent:./opentelemetry-javaagent.jar -jar my-app.jar
```

If an existing generic endpoint/header targets cloud ingest, first move those
values to the trace- and metric-specific variables in the table and remove the
generic cloud variables from the launch environment. A signal-specific local
logs endpoint alone does not prevent a generic cloud header from being
inherited or merged, even when a signal-specific logs header is also present.
Do not configure a logs cloud header or a cloud log-forwarding pipeline;
Obstudio forwards only traces and metrics. On the absent/`otlp` branch, accept
an explicit logs endpoint only when it matches the detected local Observer;
otherwise fail before the agent starts and report the operator-owned boundary
conflict. Preserve `none` and non-OTLP exporter branches without interpreting
their endpoint.

---

## Application Log Runtime Proof

Agent-installed logging instrumentation requires full-runtime proof; a config
diff or trace IDs printed in stdout is not evidence of OTLP log export.

1. Start the local Observer and the real application startup path with the
   Java agent. Exercise a deterministic Logback/Log4j call with a unique,
   sanitized body/category and known severity inside an active span. Also emit
   one record outside a span to prove the expected absence of correlation.
2. Query the local REST endpoint and inspect the Explorer's **Logs** view at
   `http://localhost:3000`. For example, after setting `proof_body` to the
   unique message:

   ```bash
   curl -fsS http://localhost:3000/api/query/logs | \
     jq --arg body "$proof_body" \
       '[.[] | select(.body == $body)] |
        {count: length,
         body: .[0].body,
         severityText: .[0].severityText,
         severityNumber: .[0].severityNumber,
         scopeName: .[0].scope.name,
         resource: .[0].resource,
         traceId: .[0].traceId,
         spanId: .[0].spanId}'
   ```

3. Require exactly one matching OTLP record for one application log call.
   Assert the body/category, severity text/number, logger or scope, and the same
   `service.name`, environment, and other approved resource identity used by
   traces and metrics. For the in-span record, assert nonempty trace/span IDs
   equal the active span; for the out-of-span record, assert no fabricated
   correlation.
4. Prove the original console/file/platform appender still writes the record
   exactly once. Check both the original sink and Observer count so an existing
   manual appender plus the agent cannot hide a duplicate export.
5. Terminate the JVM normally and confirm a final pre-shutdown record arrives.
   Rely on the Java agent's JVM shutdown hook; do not add an application SDK or
   hook to make this test pass.
6. Rerun the same launch and trigger with `OTEL_LOGS_EXPORTER=none`. Require
   zero matching OTLP records in Observer while the original console/file sink
   still contains the message and configured traces/metrics continue to work.
   Repeat with any other explicit exporter value used by the project and prove
   it was preserved rather than supplemented.
7. When cloud trace/metric export or Obstudio forwarding is enabled, prove the
   application record remains visible only in the local Explorer, generic
   cloud endpoint/header settings are absent from the log path, and no cloud
   log exporter, credential, or forwarding flag was configured.

---

## Gradle Alternative

```groovy
dependencies {
    implementation 'io.opentelemetry:opentelemetry-api'
}
```

Use the `-javaagent` JVM flag in the `bootRun` task or application config.

---

## Gotchas

- **Agent vs SDK**: The javaagent approach requires no code changes for basic coverage. Only add the OTel API dependency when you need custom spans or metrics.
- **`JAVA_TOOL_OPTIONS`**: This env var is the cleanest way to inject the agent in containerized or service-managed environments.
- **Spring Boot and Kafka**: The agent covers Spring MVC, WebFlux, Data,
  RestTemplate, WebClient, Kafka producers/consumers including clients used
  internally by Kafka Streams, and RabbitMQ automatically. Topology-level
  Kafka Streams DSL spans require custom instrumentation. No additional setup
  needed for basic spans and runtime metrics.
- **Metric export interval and timeout**: For local runtime checks, set both
  `OTEL_METRIC_EXPORT_INTERVAL=1000` and `OTEL_METRIC_EXPORT_TIMEOUT=500` so
  HTTP duration metrics flush promptly.
- **Version management**: When using the Java agent, do not also add OTel SDK dependencies -- the agent bundles its own SDK. Only add `opentelemetry-api` for custom instrumentation.
- **Application logs**: Let the agent's detected Logback/Log4j appender export
  to the signal-specific local Observer endpoint. Keep existing appenders,
  avoid a second SDK or bridge, use reviewed MDC allowlists rather than `*`,
  and let the agent flush on JVM shutdown.
