Observability Studio is a VS Code extension that helps instrument application code
using OpenTelemetry SDKs and verify the telemetry emitted by that instrumentation.

## Architecture

Studio Extension runs inside VS Code. The instrumented Application runs externally
and by using OpenTelemetry SDK sends its telemetry to a locally running Observer
process. The Observer accepts OTLP telemetry and materializes that telemetry
in-memory, then sends the view of that telemetry to the Extension using a custom
WebSocket protocol. The view is updated and extension receives an update
every time new telemetry is received from the Application.


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

