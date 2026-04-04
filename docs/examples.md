# Example Prompts

## End-to-End Observability

| Use Case | Prompt | Skill |
|----------|--------|-------|
| Full observability pipeline on an existing service | `/observe` | `/observe` |
| Build a new Go backend and instrument it end-to-end | Create a Go REST API backend in a "go" directory, then `/observe` | `/observe` |
| Build a new Python microservice with full observability | Create a Python Flask service with PostgreSQL and Redis caching, then run `/observe` | `/observe` |
| A new Kafka consumer was added -- update inventory and instrument | We added a Kafka consumer in `workers/notifications.go` -- update the inventory and instrument it | `/observe` |

## Audit -- Gap Analysis

| Use Case | Prompt | Skill |
|----------|--------|-------|
| Identify observability gaps without making code changes | `/audit` this service and show me the gaps | `/audit` |
| Assess a legacy service before planning instrumentation work | Run `/audit` on this service -- I need a gap report before the sprint planning | `/audit` |

## Instrument -- Add or Adjust OTel Code

| Use Case | Prompt | Skill |
|----------|--------|-------|
| Add OpenTelemetry to an uninstrumented service | Instrument the service with OpenTelemetry | `/instrument` |
| Trace a known bottleneck function with a custom span | Add a custom span around `syncInventory` -- it's a bottleneck with no visibility | `/instrument` |
| Trace an outbound API call and measure its latency | The checkout flow calls a fraud-detection API -- add outbound HTTP spans and a `fraud.check.duration` histogram | `/instrument` |
| Track business events with counters and structured logs | Add a counter for order cancellations by reason and a log event with full cancellation context | `/instrument` |
| Reduce noise from a high-volume histogram | The HTTP latency histogram is too noisy -- only record requests slower than 100ms | `/instrument` |
| Strip sensitive data from telemetry | Remove the `user.email` attribute from all spans -- it's PII and should not be in traces | `/instrument` |
| Switch the OTLP exporter transport protocol | Change the OTLP exporter from HTTP to gRPC for lower overhead | `/instrument` |
| Fix a high-cardinality attribute inflating storage costs | `db.client.operation.duration` has very high cardinality on `db.statement` -- fix it | `/instrument` |

## Verify -- Validate Telemetry

| Use Case | Prompt | Skill |
|----------|--------|-------|
| Full automated verification of all instrumented KPIs | `/verify` | `/verify` |
| Quick spot-check that a single endpoint produces spans | Start the Observer, hit `/orders` a few times, and confirm spans are showing up | `/verify` |
| Diagnose and fix duplicate spans from double SDK init | I'm seeing duplicate spans for HTTP requests -- find and fix the double initialization | `/verify` |

## Provision -- Terraform, Detectors, Alerts

| Use Case | Prompt | Skill |
|----------|--------|-------|
| Generate all dashboards, detectors, and alert rules at once | `/provision` -- generate dashboards, detectors, and alert rules | `/provision` |
| Create Splunk O11y Cloud Terraform matching the KPI table | Generate Splunk O11y Cloud Terraform for dashboards matching the KPI table in `.observe/inventory.md` | `/provision` |
| Create SignalFx detectors for critical production alerts | Create SignalFx detectors for all Critical-severity alerts in the inventory | `/provision` |
| Generate Prometheus alerting rules for warning-level KPIs | Write Prometheus alerting rules for the Warning-level KPIs | `/provision` |
| Build a Grafana dashboard from the service health panel | Generate a Grafana dashboard JSON for the service health panel group from the inventory | `/provision` |
