# Plain Kafka Producer/Consumer Eval Fixture

This fixture covers direct Java Kafka client usage without Guice, Spring, or
Kafka Streams.

## Runtime

```bash
mvn test

KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \
ORDERS_TOPIC=orders \
SHIPMENTS_TOPIC=shipments \
mvn exec:java
```

`mvn test` is broker-free and verifies the message handling logic. `mvn
exec:java` requires a running Kafka broker.

The service intentionally contains no OpenTelemetry SDK, Java agent startup
configuration, OTLP exporter wiring, or custom `Tracer` usage. Instrumentation
responses should prefer the OpenTelemetry Java agent for producer and consumer
client spans, with custom business metrics such as shipment commands produced
treated as optional unless explicitly requested.
