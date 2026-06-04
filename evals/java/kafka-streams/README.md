# Kafka Streams Eval Fixture

This fixture is a small order stream processor used by the OTel skill evals.
It uses Guice for application wiring and Kafka Streams for stream-processing.

## Runtime

```bash
mvn test

KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \
KAFKA_APPLICATION_ID=order-risk-stream \
ORDERS_TOPIC=orders \
ENRICHED_ORDERS_TOPIC=orders.enriched \
FRAUD_ALERTS_TOPIC=orders.fraud-alerts \
mvn exec:java
```

This fixture does not define a fat-jar or shaded-jar build. Use
`mvn exec:java` for local live runs, with a Kafka broker available at
`KAFKA_BOOTSTRAP_SERVERS`.

The service intentionally contains no OpenTelemetry SDK, Java agent startup
configuration, OTLP exporter wiring, or Guice `Tracer` binding.

## Eval Intent

The audit and instrumentation evals share one boundary: use the OpenTelemetry
Java agent as the primary Kafka Streams instrumentation path, and do not add a
manual SDK, duplicate provider, or Guice `Tracer` binding unless the task
explicitly asks for custom spans or metrics.

`OrderEventParser` intentionally drops malformed and null order records without
logging, metrics, or spans. Audit responses should identify that failed-parse
visibility gap. Instrumentation responses should treat a failed-parse counter or
record-processing latency metric as optional business instrumentation unless the
prompt explicitly requests custom signals.

`OrderEventParser.toJson()` throws on serialization failure and is not a silent
failure gap; the intentional silent failure is limited to `parse()`.

Instrumentation responses that add or recommend Java agent runtime settings
should include fast local metric export settings such as
`OTEL_METRIC_EXPORT_INTERVAL=1000` and `OTEL_METRIC_EXPORT_TIMEOUT=500`.
