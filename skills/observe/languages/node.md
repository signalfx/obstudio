# Node.js OpenTelemetry Guide

Language-specific instrumentation guidance for Node.js and TypeScript services.

---

## Auto-Instrumentation Library Map

Install auto-instrumentation packages matching the frameworks and clients
detected in the codebase. Only install what the project actually uses.

| Dependency in package.json | Auto-instrumentation Package | What It Covers |
|----------------------------|------------------------------|----------------|
| `express` | `@opentelemetry/instrumentation-express` | HTTP server spans with route, method, status code |
| `fastify` | `@opentelemetry/instrumentation-fastify` | HTTP server spans with route, method, status code |
| `koa` | `@opentelemetry/instrumentation-koa` | HTTP server spans with route, method, status code |
| `@nestjs/core` | `@opentelemetry/instrumentation-nestjs-core` | NestJS handler and interceptor spans |
| `http` / `https` (stdlib) | `@opentelemetry/instrumentation-http` | Inbound and outbound HTTP spans |
| `pg` | `@opentelemetry/instrumentation-pg` | SQL query spans with `db.statement` |
| `mysql2` | `@opentelemetry/instrumentation-mysql2` | SQL query spans |
| `mongodb` | `@opentelemetry/instrumentation-mongodb` | MongoDB command spans |
| `ioredis` | `@opentelemetry/instrumentation-ioredis` | Redis command spans |
| `redis` (node-redis v4+) | `@opentelemetry/instrumentation-redis-4` | Redis command spans |
| `@grpc/grpc-js` | `@opentelemetry/instrumentation-grpc` | gRPC client/server spans |
| `kafkajs` | `@opentelemetry/instrumentation-kafkajs` | Producer/consumer spans with topic |
| `graphql` | `@opentelemetry/instrumentation-graphql` | GraphQL resolve spans |
| `aws-sdk` / `@aws-sdk/*` | `@opentelemetry/instrumentation-aws-sdk` | AWS service call spans |

**Registration order matters**: `@opentelemetry/instrumentation-http` must be
registered before framework-specific instrumentations (Express, Fastify, etc.)
because the framework instrumentations depend on HTTP spans being created first.

---

## SDK Initialization

Create a separate file for OTel setup. This file must be loaded before any
application code runs.

**File**: `instrumentation.ts` (or `instrumentation.js`)

```typescript
import { NodeSDK } from '@opentelemetry/sdk-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { OTLPMetricExporter } from '@opentelemetry/exporter-metrics-otlp-http';
import { PeriodicExportingMetricReader } from '@opentelemetry/sdk-metrics';
import { resourceFromAttributes } from '@opentelemetry/resources';
import { HttpInstrumentation } from '@opentelemetry/instrumentation-http';
// ... add detected framework/client instrumentations here

const sdk = new NodeSDK({
  resource: resourceFromAttributes({
    'service.name': process.env.OTEL_SERVICE_NAME || 'my-service',
  }),
  traceExporter: new OTLPTraceExporter(),
  metricReader: new PeriodicExportingMetricReader({
    exporter: new OTLPMetricExporter(),
  }),
  instrumentations: [
    new HttpInstrumentation(),
    // ... add detected instrumentations here
  ],
});

sdk.start();

process.on('SIGTERM', () => sdk.shutdown());
```

### Loading the SDK

**CommonJS** (`require`):
```
node --require ./instrumentation.js app.js
```

**ESM** (`import`):
```
node --import ./instrumentation.js app.js
```

If the project uses `ts-node` or `tsx`, load via:
```
node --require ./instrumentation.ts -r ts-node/register app.ts
```

Alternatively, import the instrumentation file as the first line of the
application entry point:
```typescript
import './instrumentation';
// ... rest of app
```

---

## Custom Spans

Use `tracer.startActiveSpan()` for operations that represent a diagnostic
boundary. Always end the span in a `finally` block.

```typescript
import { trace, SpanStatusCode } from '@opentelemetry/api';

const tracer = trace.getTracer('my-service/orders');

async function processOrder(orderId: string): Promise<Order> {
  return tracer.startActiveSpan('orders.process', async (span) => {
    span.setAttribute('order.id', orderId);
    try {
      const order = await db.getOrder(orderId);
      span.setAttribute('order.total', order.total);
      await chargePayment(order);
      return order;
    } catch (err) {
      span.recordException(err as Error);
      span.setStatus({ code: SpanStatusCode.ERROR, message: String(err) });
      throw err;
    } finally {
      span.end();
    }
  });
}
```

---

## Custom Metrics

```typescript
import { metrics } from '@opentelemetry/api';

const meter = metrics.getMeter('my-service');

// Counter -- monotonically increasing count
const ordersProcessed = meter.createCounter('orders.processed.count', {
  description: 'Total orders processed',
  unit: '{orders}',
});

// Histogram -- duration or size distribution
const orderDuration = meter.createHistogram('orders.process.duration', {
  description: 'Order processing duration',
  unit: 's',
});

// Gauge -- point-in-time value via observable callback
meter.createObservableGauge('orders.queue.depth', {
  description: 'Current order queue depth',
  unit: '{orders}',
}).addCallback((result) => {
  result.observe(getQueueDepth());
});

// Usage in application code
ordersProcessed.add(1, { 'order.type': 'standard' });

const start = performance.now();
await processOrder(orderId);
orderDuration.record((performance.now() - start) / 1000, { 'order.type': 'standard' });
```

---

## OTLP Export Configuration

All configuration is via environment variables. Do not hardcode endpoints.

| Variable | Default | Purpose |
|----------|---------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | OTLP HTTP endpoint |
| `OTEL_SERVICE_NAME` | (must be set) | Service identity in telemetry |
| `OTEL_METRIC_EXPORT_INTERVAL` | `60000` | Metric export interval (ms) |
| `OTEL_BSP_SCHEDULE_DELAY` | `5000` | Span batch export delay (ms) |

For local development with the Observer, run with:

    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
    OTEL_METRIC_EXPORT_INTERVAL=1000
    OTEL_BSP_SCHEDULE_DELAY=100

---

## Gotchas

- **ESM vs CJS**: Node.js ESM requires `--import` instead of `--require`.
  If the project has `"type": "module"` in `package.json`, use `--import`.
- **Registration order**: HTTP instrumentation must be registered before
  framework instrumentations. The `NodeSDK` `instrumentations` array is
  order-sensitive.
- **Singleton SDK**: Never call `new NodeSDK()` more than once. If existing
  OTel setup exists, extend its instrumentation array.
- **Graceful shutdown**: Always hook `SIGTERM` to `sdk.shutdown()` to flush
  pending telemetry.
- **Avoid `@opentelemetry/auto-instrumentations-node`**: This meta-package
  installs every instrumentation. Only install what the project uses to
  minimize dependency surface.
- **TypeScript types**: If using TypeScript, `@opentelemetry/api` provides
  full type definitions. No separate `@types` packages needed.
