# Example Prompts

## End-to-End Observability

| Use Case | Prompt | Skill |
|----------|--------|-------|
| Full observability pipeline on an existing service | `/splunk-observe` | `/splunk-observe` |
| Build a new Go backend and instrument it end-to-end | Create a Go REST API backend in a "go" directory, then `/splunk-observe` | `/splunk-observe` |
| Build a new Python microservice with full observability | Create a Python Flask service with PostgreSQL and Redis caching, then run `/splunk-observe` | `/splunk-observe` |
| A new Kafka consumer was added -- update inventory and instrument | We added a Kafka consumer in `workers/notifications.go` -- update the inventory and instrument it | `/splunk-observe` |

## Audit -- Gap Analysis

| Use Case | Prompt | Skill |
|----------|--------|-------|
| Identify observability gaps without making code changes | `/splunk-audit` this service and show me the gaps | `/splunk-audit` |
| Assess a legacy service before planning instrumentation work | Run `/splunk-audit` on this service -- I need a gap report before the sprint planning | `/splunk-audit` |

## Instrument -- Add or Adjust OTel Code

| Use Case | Prompt | Skill |
|----------|--------|-------|
| Add OpenTelemetry to an uninstrumented service | Instrument the service with OpenTelemetry | `/splunk-instrument` |
| Trace a known bottleneck function with a custom span | Add a custom span around `syncInventory` -- it's a bottleneck with no visibility | `/splunk-instrument` |
| Trace an outbound API call and measure its latency | The checkout flow calls a fraud-detection API -- add outbound HTTP spans and a `fraud.check.duration` histogram | `/splunk-instrument` |
| Track business events with counters and structured logs | Add a counter for order cancellations by reason and a log event with full cancellation context | `/splunk-instrument` |
| Reduce noise from a high-volume histogram | The HTTP latency histogram is too noisy -- only record requests slower than 100ms | `/splunk-instrument` |
| Strip sensitive data from telemetry | Remove the `user.email` attribute from all spans -- it's PII and should not be in traces | `/splunk-instrument` |
| Switch the OTLP exporter transport protocol | Change the OTLP exporter from HTTP to gRPC for lower overhead | `/splunk-instrument` |
| Fix a high-cardinality attribute inflating storage costs | `db.client.operation.duration` has very high cardinality on `db.statement` -- fix it | `/splunk-instrument` |

## Verify -- Validate Telemetry

| Use Case | Prompt | Skill |
|----------|--------|-------|
| Full automated verification of all instrumented KPIs | `/splunk-verify` | `/splunk-verify` |
| Quick spot-check that a single endpoint produces spans | Start the Observer, hit `/orders` a few times, and confirm spans are showing up | `/splunk-verify` |
| Diagnose and fix duplicate spans from double SDK init | I'm seeing duplicate spans for HTTP requests -- find and fix the double initialization | `/splunk-verify` |

## Provision -- Terraform, Detectors, Alerts

| Use Case | Prompt | Skill |
|----------|--------|-------|
| Generate all dashboards, detectors, and alert rules at once | `/splunk-provision` -- generate dashboards, detectors, and alert rules | `/splunk-provision` |
| Create Splunk O11y Cloud Terraform matching the signal tables | Generate Splunk O11y Cloud Terraform for dashboards matching the Metrics table in `.observe/inventory.md` | `/splunk-provision` |
| Create SignalFx detectors for critical production alerts | Create SignalFx detectors for all Critical-severity alerts in the inventory | `/splunk-provision` |
| Generate Prometheus alerting rules for warning-level KPIs | Write Prometheus alerting rules for the Warning-level KPIs | `/splunk-provision` |
| Build a Grafana dashboard from the service health panel | Generate a Grafana dashboard JSON for the service health panel group from the inventory | `/splunk-provision` |
