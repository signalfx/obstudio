# Example Prompts

## Audit -- Gap Analysis

| Use Case | Prompt | Skill |
|----------|--------|-------|
| Identify observability gaps without making code changes | `$otel-audit` this service and show me the gaps | `$otel-audit` |
| Assess a legacy service before planning instrumentation work | Run `$otel-audit` on this service -- I need a gap report before the sprint planning | `$otel-audit` |

## Detect -- Generate Alerts

| Use Case | Prompt | Skill |
|----------|--------|-------|
| Generate detectors from an existing audit report | Generate Splunk detectors from my audit report | `$splunk-configure` |
| Target a specific detector category | Create latency detectors for this service | `$splunk-configure` |
| Post-instrument workflow -- set up alerts after adding OTel | I just instrumented the service -- now set up alerts | `$splunk-configure` |
| Override default thresholds via Terraform variables | Generate detectors with a 2s latency threshold and 90% saturation | `$splunk-configure` |
| Full audit-to-detect pipeline | Audit this service, then generate detector Terraform | `$otel-audit` → `$splunk-configure` |
| Explore what would be generated without writing files | What detectors would you create from the audit report? | `$splunk-configure` |

## Instrument -- Add or Adjust OTel Code

| Use Case | Prompt | Skill |
|----------|--------|-------|
| Add OpenTelemetry to an uninstrumented service | Instrument the service with OpenTelemetry | `$otel-instrument` |
| Trace a known bottleneck function with a custom span | Add a custom span around `syncInventory` -- it's a bottleneck with no visibility | `$otel-instrument` |
| Trace an outbound API call and measure its latency | The checkout flow calls a fraud-detection API -- add outbound HTTP spans and a `fraud.check.duration` histogram | `$otel-instrument` |
| Track business events with counters and structured logs | Add a counter for order cancellations by reason and a log event with full cancellation context | `$otel-instrument` |
| Reduce noise from a high-volume histogram | The HTTP latency histogram is too noisy -- only record requests slower than 100ms | `$otel-instrument` |
| Strip sensitive data from telemetry | Remove the `user.email` attribute from all spans -- it's PII and should not be in traces | `$otel-instrument` |
| Switch the OTLP exporter transport protocol | Change the OTLP exporter from HTTP to gRPC for lower overhead | `$otel-instrument` |
| Fix a high-cardinality attribute inflating storage costs | `db.client.operation.duration` has very high cardinality on `db.statement` -- fix it | `$otel-instrument` |
