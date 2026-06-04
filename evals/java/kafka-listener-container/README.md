# Kafka Listener Container Eval Fixture

This fixture covers container-managed Kafka consumers implemented with Spring
Kafka `@KafkaListener`. It is intentionally separate from the plain Kafka
`Consumer.poll()` fixtures because listener containers change the startup and
configuration surfaces an instrumentation agent should preserve.

## Runtime

```bash
mvn test

SPRING_KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \
ALERTS_TOPIC=alerts \
mvn spring-boot:run
```

`mvn test` is broker-free and calls the listener directly. `mvn spring-boot:run`
requires a running Kafka broker.

The service intentionally contains no OpenTelemetry SDK, Java agent startup
configuration, OTLP exporter wiring, or custom `Tracer` usage. Instrumentation
responses should prefer the OpenTelemetry Java agent for Kafka listener client
spans and avoid replacing Spring Kafka listener container behavior.
