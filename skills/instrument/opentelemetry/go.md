Use https://pkg.go.dev/go.opentelemetry.io/contrib for instrumentation.

Enable runtime instrumentation via https://pkg.go.dev/go.opentelemetry.io/contrib/instrumentation/runtime

Add OTLP http exporter for traces and metrics, sending to http://localhost:4318

Never use go.opentelemetry.io/otel/semconv/* packages since that can result in runtime conflicts in telemetry schemas.
