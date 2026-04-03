## Example Prompts

### Greenfield -- create and instrument from scratch

> Create an example backend service in Go, place in "go" directory. Show
> some examples of handling REST APIs in the service.

> Instrument the service.

> Create a Python Flask microservice that manages user profiles with
> PostgreSQL and Redis caching. Place it in "python" directory.

> Run /observe on the new service.

### Adjust existing instrumentation

> The HTTP latency histogram is too noisy. Switch it from recording every
> request to only recording requests slower than 100ms.

> Add a custom span around the `syncInventory` function -- it's a known
> bottleneck but we have no visibility into it.

> Remove the `user.email` attribute from all spans -- it's PII and should
> not be in traces.

> Change the OTLP exporter from HTTP to gRPC for lower overhead.

### Add instrumentation to an existing service

> We just added a Kafka consumer in `workers/notifications.go`. Run
> /observe to update the inventory and instrument it.

> The checkout flow calls a new fraud-detection API. Add outbound HTTP
> spans and a `fraud.check.duration` histogram.

> Add business metrics for order cancellations -- counter by reason and a
> log event with the full cancellation context.

### Terraform and alerting

> Generate Splunk O11y Cloud terraform for dashboards matching the KPI
> table in `.observe/inventory.md`.

> Create SignalFx detectors for all Critical-severity alerts in the
> inventory.

> Write Prometheus alerting rules for the Warning-level KPIs.

> Generate a Grafana dashboard JSON for the service health panel group
> from the inventory.

### Validation and debugging

> Start the Observer and run the service. Hit the `/orders` endpoint a few
> times and confirm spans are showing up.

> I'm seeing duplicate spans for HTTP requests. Help me find and fix the
> double initialization.

> The `db.client.operation.duration` histogram has very high cardinality
> on the `db.statement` attribute. Fix it.
