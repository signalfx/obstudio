# Example Prompts

## Audit -- Gap Analysis

| Use Case | Prompt | Skill |
|----------|--------|-------|
| Identify observability gaps without making code changes | `$otel-audit` this service and show me the gaps | `$otel-audit` |
| Assess a legacy service before planning instrumentation work | Run `$otel-audit` on this service -- I need a gap report before the sprint planning | `$otel-audit` |

## Verify -- Prove Existing Instrumentation

| Use Case | Prompt | Skill |
|----------|--------|-------|
| Verify every signal and path from the audit and instrumentation reports | Run `$otel-verify` and tell me exactly what is working or unproven | `$otel-verify` |
| Prove route-aware HTTP spans, request duration, and duplicate prevention | Verify the HTTP server instrumentation in the real local runtime | `$otel-verify` |
| Capture local OTLP evidence in the Telemetry Explorer | Verify this instrumentation against my local Obstudio collector | `$otel-verify` |
| Recheck instrumentation without changing application code | Rerun the OTel verification report for this service | `$otel-verify` |

## Detect -- Generate Alerts

| Use Case | Prompt | Skill |
|----------|--------|-------|
| Generate detectors from an existing audit report | Generate Splunk detectors from my audit report | `$splunk-configure` |
| Target a specific detector category | Create latency detectors for this service | `$splunk-configure` |
| Post-instrument workflow -- set up alerts after adding OTel | I just instrumented the service -- now set up alerts | `$splunk-configure` |
| Override default thresholds via Terraform variables | Generate detectors with a 2s latency threshold and 90% saturation | `$splunk-configure` |
| Full audit-to-detect pipeline | Audit this service, then generate detector Terraform | `$otel-audit` → `$splunk-configure` |
| Explore what would be generated without writing files | What detectors would you create from the audit report? | `$splunk-configure` |

## Sync -- Push Detector Gaps to Splunk

| Use Case | Prompt | Skill |
|----------|--------|-------|
| See which local detector specs are already live vs. missing | Show me which of my local detectors already exist in Splunk | `$splunk-detector-publish` |
| Create only the missing detectors, skip existing ones | Sync my local detector Terraform to Splunk -- create only the gaps | `$splunk-detector-publish` |
| Dry-run the create before writing anything | Preview what would be created without creating or modifying resources (read-only API calls are still made to check existing state) | `$splunk-detector-publish` |
| Re-run after a partial sync to fill in what failed | Resume the detector sync -- pick up where it left off | `$splunk-detector-publish` |
| Full end-to-end pipeline: audit → configure → sync | Audit this service, generate detectors, then push the gaps to Splunk | `$otel-audit` → `$splunk-configure` → `$splunk-detector-publish` |

## Visualize -- Generate Dashboards

| Use Case | Prompt | Skill |
|----------|--------|-------|
| Generate dashboard Terraform from an existing audit report | Build a dashboard from my audit report | `$splunk-dashboard` |
| Visualize the metrics a service emits | Visualize my metrics / create charts for this service | `$splunk-dashboard` |
| Get a RED-style overview dashboard | Generate a rate/errors/duration dashboard for the service | `$splunk-dashboard` |
| Full audit-to-dashboard pipeline | Audit this service, then generate dashboard Terraform | `$otel-audit` → `$splunk-dashboard` |
| Preview the dashboard layout against live local telemetry | Open the Dashboards tab to preview my dashboard before pushing it | Observer **Dashboards** tab (`localhost:3000`) |

## Sync -- Push Dashboard Gaps to Splunk

| Use Case | Prompt | Skill |
|----------|--------|-------|
| See which local dashboards/charts are already live vs. missing | Show me which of my local dashboards already exist in Splunk | `$splunk-dashboard-publish` |
| Create only the missing dashboards and charts, skip existing ones | Sync my local dashboard Terraform to Splunk -- create only the gaps | `$splunk-dashboard-publish` |
| Understand why each chart is COVERED/GAP/UNCERTAIN | Show the dashboard sync diff with a reason for every chart | `$splunk-dashboard-publish` |
| Dry-run the create before writing anything | Preview the dashboard payloads without creating or modifying resources (read-only API calls are still made to check existing state) | `$splunk-dashboard-publish` |
| Re-run after a partial sync to fill in what failed | Resume the dashboard sync -- pick up where it left off | `$splunk-dashboard-publish` |
| Full end-to-end pipeline: audit → dashboard → sync | Audit this service, generate a dashboard, then push the gaps to Splunk | `$otel-audit` → `$splunk-dashboard` → `$splunk-dashboard-publish` |

## Export -- Forward Telemetry to Splunk

| Use Case | Prompt | Skill / Config |
|----------|--------|----------------|
| Forward metrics to Splunk while developing locally | How do I send my local metrics to Splunk O11y? | `USER.md` — metrics export config |
| Make this service appear in Splunk APM | Forward my spans to Splunk so it shows up in APM | `USER.md` — trace export config |
| Check whether metrics are reaching Splunk | Is the Splunk metrics export working? | MCP: `observer_splunk_metrics_export_status` |
| Apply a new ingest token without restarting obstudio | Update the Splunk ingest token for the running observer | MCP: `observer_splunk_metrics_export_configure` |
| Send a test canary metric to verify connectivity | Send a test metric to confirm Splunk connectivity | MCP: `observer_splunk_metrics_export_test` |

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
