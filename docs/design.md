Observability Studio is a local OpenTelemetry workspace that helps instrument
application code using OpenTelemetry SDKs, verify the telemetry emitted by that
instrumentation, forward telemetry to Splunk Observability Cloud, and generate
and sync detector and dashboard specs to close monitoring and visualization gaps.

## Architecture

Studio Extension runs inside VS Code. The instrumented Application runs externally
and by using OpenTelemetry SDK sends its telemetry to a locally running Observer
process. The Observer accepts OTLP telemetry and materializes that telemetry
in-memory, assesses the telemetry from the perspective of conformance to OTel
conventions and otherwise verifies the quality of telemetry, augments the
telemetry with assessment metadata, then sends the augmented telemetry to the
Extension using a custom WebSocket protocol. The extension receives an update
every time new telemetry is received from the Application.

The Observer also optionally forwards received metrics and traces to Splunk
Observability Cloud over OTLP/HTTP, making instrumented services visible as
real APM services in the org while the developer is still iterating locally.


```
                                  +-----------------+
                                  |   Application   |
                                  |                 |
                                  | +-------------+ |
                                  | |  Otel SDK   | |
                                  | +-------------+ |
                                  +-----------------+
+-----------------+                        |         
|     VS Code     |                        |         
|                 |                       OTLP       
|                 |                        |         
|                 |                        v         
| +-------------+ |               +-----------------+
| |             | |               |                 |
| |    Studio   | |               |      Local      |
| |  Extension  |<-------WS-------|    Observer     |
| |             | |               |                 |
| |             | |               |                 |
| +-------------+ |               +-----------------+
+-----------------+                                  
```

### Observer-Extension Protocol (OEP)

