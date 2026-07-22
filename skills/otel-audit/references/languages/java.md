# Java Audit Reference

Load only for Java repositories. The OpenTelemetry Java agent automatically
instruments these detected surfaces without application code changes:

- Spring MVC, Spring WebFlux, Spring Data (JPA and JDBC)
- RestTemplate and WebClient
- Kafka producers/consumers, including clients used by Kafka Streams
- RabbitMQ and gRPC
- Servlet containers such as Tomcat, Jetty, and Undertow
- JDBC drivers

For Spring Boot, name the application entry point, controller files, build
wrapper, and Java-agent startup surface. For Kafka services, name producer and
consumer wrappers, batch-poll loops, `@KafkaListener` methods, Streams topology
and lifecycle code, topics, consumer groups, commit behavior, uncaught-exception
handling, and missing processed/failed/lag/latency signals.
