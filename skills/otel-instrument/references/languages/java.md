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

---

## OTel Java Agent (Recommended)

The OpenTelemetry Java agent provides auto-instrumentation with zero code changes.

### Download

```bash
curl -L https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/latest/download/opentelemetry-javaagent.jar \
  -o opentelemetry-javaagent.jar
```

### Run

Prefer the existing JVM startup path. For host-based services, `JAVA_TOOL_OPTIONS` or the current service-manager JVM args are usually the cleanest place to inject the agent.

```bash
java -javaagent:./opentelemetry-javaagent.jar \
  -Dotel.service.name=my-service \
  -Dotel.exporter.otlp.endpoint=http://localhost:4318 \
  -Dotel.resource.attributes=deployment.environment=production \
  -jar my-app.jar
```

### If the Project Already Runs in Docker

```dockerfile
FROM eclipse-temurin:21-jre

COPY opentelemetry-javaagent.jar /opt/agent.jar
COPY my-app.jar /opt/app.jar

ENV JAVA_TOOL_OPTIONS="-javaagent:/opt/agent.jar"
ENV OTEL_SERVICE_NAME=my-service
ENV OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
ENV OTEL_METRIC_EXPORT_INTERVAL=1000
ENV OTEL_METRIC_EXPORT_TIMEOUT=500

CMD ["java", "-jar", "/opt/app.jar"]
```

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

| Variable | Default | Purpose |
|----------|---------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | OTLP HTTP endpoint |
| `OTEL_SERVICE_NAME` | (must be set) | Service identity in telemetry |
| `OTEL_METRIC_EXPORT_INTERVAL` | `60000` | Metric export interval (ms) |
| `OTEL_METRIC_EXPORT_TIMEOUT` | `30000` | Metric export timeout (ms) |
| `OTEL_BSP_SCHEDULE_DELAY` | `5000` | Span batch export delay (ms) |

For local development with the Observer:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
OTEL_METRIC_EXPORT_INTERVAL=1000 \
OTEL_METRIC_EXPORT_TIMEOUT=500 \
OTEL_BSP_SCHEDULE_DELAY=100 \
java -javaagent:./opentelemetry-javaagent.jar -jar my-app.jar
```

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
