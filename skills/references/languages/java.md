# Java OpenTelemetry Guide

Language-specific instrumentation guidance for Java services.

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
- Kafka, RabbitMQ, gRPC
- Servlet containers (Tomcat, Jetty, Undertow)
- JDBC drivers

No code changes needed for basic coverage.
In final user-facing output, state that Spring MVC and the servlet container
will emit HTTP server spans and request duration metrics through the agent.
Also name the service identity and exporter settings, for example
`OTEL_SERVICE_NAME` and `OTEL_EXPORTER_OTLP_ENDPOINT`.

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
- **Spring Boot**: The agent covers Spring MVC, WebFlux, Data, RestTemplate, WebClient, Kafka, and RabbitMQ automatically. No additional setup needed.
- **Metric export interval and timeout**: For local runtime checks, set both
  `OTEL_METRIC_EXPORT_INTERVAL=1000` and `OTEL_METRIC_EXPORT_TIMEOUT=500` so
  HTTP duration metrics flush promptly.
- **Version management**: When using the Java agent, do not also add OTel SDK dependencies -- the agent bundles its own SDK. Only add `opentelemetry-api` for custom instrumentation.
