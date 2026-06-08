# Kafka Batch Consumer Eval Fixture

This fixture covers a plain Java Kafka batch consumer that processes
`ConsumerRecords` from `poll()` as a unit and commits offsets after each batch.

## Runtime

```bash
mvn test

KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \
PAYMENTS_TOPIC=payments \
mvn exec:java
```

`mvn test` is broker-free and verifies the batch processor. `mvn exec:java`
requires a running Kafka broker.

The service intentionally contains no OpenTelemetry SDK, Java agent startup
configuration, OTLP exporter wiring, or custom `Tracer` usage. Instrumentation
responses should prefer the OpenTelemetry Java agent for Kafka consumer spans
and treat batch-size, failed-record, high-value-payment, and batch-duration
metrics as optional custom signals unless explicitly requested.
