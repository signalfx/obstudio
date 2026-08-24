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
| `console.*` | `@opentelemetry/instrumentation-console` 0.3.0 | Application LogRecords while preserving console output; Node `^18.19.0 || >=20.6.0` and `@opentelemetry/api >=1.9.1` only |
| `pino` | `@opentelemetry/instrumentation-pino` | Log sending plus trace/span correlation |
| `winston` | `@opentelemetry/instrumentation-winston` + `@opentelemetry/winston-transport` | Log sending plus trace/span correlation |

**Registration order matters**: `@opentelemetry/instrumentation-http` must be
registered before framework-specific instrumentations (Express, Fastify, etc.)
because the framework instrumentations depend on HTTP spans being created first.

**Note**: `http.server.active_requests` is experimental in the Node.js OTel SDK
and may not be emitted by all versions. Do not treat its presence as a hard
requirement when assessing instrumentation coverage.

---

## Dependencies

```bash
npm install @opentelemetry/sdk-node \
  @opentelemetry/api \
  @opentelemetry/exporter-trace-otlp-http \
  @opentelemetry/exporter-metrics-otlp-http \
  @opentelemetry/exporter-logs-otlp-proto \
  @opentelemetry/sdk-metrics \
  @opentelemetry/sdk-logs \
  @opentelemetry/instrumentation-http \
  @opentelemetry/resources \
  @opentelemetry/semantic-conventions
```

Add detected framework/client packages explicitly. For Express, also install:

```bash
npm install @opentelemetry/instrumentation-express
```

Do not rely on `@opentelemetry/auto-instrumentations-node` alone when the
project uses a known framework such as Express, Fastify, Koa, NestJS, or a
known client library. The manifest should name the matching instrumentation
packages directly.

Install only the detected logging bridge. For detected `console.*` calls, the
current official bridge is version 0.3.0 and requires Node
`^18.19.0 || >=20.6.0` plus `@opentelemetry/api >=1.9.1`; verify the
project-selected runtime and locked API version before adding it:

```bash
npm install @opentelemetry/instrumentation-console@0.3.0
```

If either selected version is older, do not force an application/toolchain
upgrade just to add the bridge. Report `unsupported-stack` and the exact
runtime/API prerequisite instead.

For Pino install `@opentelemetry/instrumentation-pino`. For Winston install
both `@opentelemetry/instrumentation-winston` and
`@opentelemetry/winston-transport` because the instrumentation uses that
transport for log sending.

---

## SDK Initialization

Create a separate file for OTel setup. This file must be loaded before any
application code runs.

**File**: `instrumentation.ts` (or `instrumentation.js`)

```typescript
import { NodeSDK } from '@opentelemetry/sdk-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { OTLPMetricExporter } from '@opentelemetry/exporter-metrics-otlp-http';
import { OTLPLogExporter } from '@opentelemetry/exporter-logs-otlp-proto';
import { BatchLogRecordProcessor } from '@opentelemetry/sdk-logs';
import { PeriodicExportingMetricReader } from '@opentelemetry/sdk-metrics';
import { resourceFromAttributes } from '@opentelemetry/resources';
import { HttpInstrumentation } from '@opentelemetry/instrumentation-http';
import { ExpressInstrumentation } from '@opentelemetry/instrumentation-express';
import { ConsoleInstrumentation } from '@opentelemetry/instrumentation-console';
// ... add other detected framework/client instrumentations here

const LOCAL_OBSERVER_LOGS_ENDPOINT = 'http://localhost:4318/v1/logs';

function defaultLocalLogConfiguration() {
  const configured = process.env.OTEL_LOGS_EXPORTER?.trim().toLowerCase();
  if (configured && configured !== 'otlp') {
    // `none` disables logs. Any other explicit exporter and its bridge belong
    // entirely to a proven operator-owned setup; do not add an Obstudio bridge.
    return {
      logRecordProcessors: undefined,
      addDefaultLocalLogBridge: false,
    };
  }

  const protocol = (
    process.env.OTEL_EXPORTER_OTLP_LOGS_PROTOCOL || 'http/protobuf'
  ).trim().toLowerCase();
  if (protocol !== 'http/protobuf') {
    throw new Error(
      `select the official exporter matching OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=${protocol}`,
    );
  }

  const endpoint = process.env.OTEL_EXPORTER_OTLP_LOGS_ENDPOINT?.trim();
  if (
    endpoint &&
    endpoint !== LOCAL_OBSERVER_LOGS_ENDPOINT
  ) {
    throw new Error(
      'OTEL_EXPORTER_OTLP_LOGS_ENDPOINT is not the detected local Observer; ' +
      'refusing to create an Obstudio log provider or bridge',
    );
  }

  if (process.env.OTEL_EXPORTER_OTLP_HEADERS?.trim()) {
    throw new Error(
      'move generic OTLP headers to trace/metric signal variables and remove ' +
      'OTEL_EXPORTER_OTLP_HEADERS',
    );
  }

  // The exporter may read OTEL_EXPORTER_OTLP_LOGS_HEADERS. The generic header
  // source was rejected above because the SDK merges rather than replaces it.
  const exporter = new OTLPLogExporter({
    url: endpoint || LOCAL_OBSERVER_LOGS_ENDPOINT,
  });
  return {
    logRecordProcessors: [new BatchLogRecordProcessor({ exporter })],
    addDefaultLocalLogBridge: true,
  };
}

const { logRecordProcessors, addDefaultLocalLogBridge } =
  defaultLocalLogConfiguration();

const sdk = new NodeSDK({
  resource: resourceFromAttributes({
    'service.name': process.env.OTEL_SERVICE_NAME || 'my-service',
  }),
  traceExporter: new OTLPTraceExporter(),
  metricReader: new PeriodicExportingMetricReader({
    exporter: new OTLPMetricExporter(),
    exportIntervalMillis: Number(process.env.OTEL_METRIC_EXPORT_INTERVAL || 1000),
    exportTimeoutMillis: Number(process.env.OTEL_METRIC_EXPORT_TIMEOUT || 500),
  }),
  ...(logRecordProcessors ? { logRecordProcessors } : {}),
  instrumentations: [
    new HttpInstrumentation(),
    new ExpressInstrumentation(),
    // Add this only for the Obstudio-owned absent/`otlp` branch, after proving
    // the selected Node runtime is supported and no bridge already owns it.
    ...(addDefaultLocalLogBridge ? [new ConsoleInstrumentation()] : []),
    // ... add other detected instrumentations here
  ],
});

sdk.start();

let shutdownPromise: Promise<void> | undefined;

export function shutdownOnce(): Promise<void> {
  // Integrate this function into an existing graceful shutdown path after the
  // server/worker stops accepting work and emits its final application logs.
  shutdownPromise ??= sdk.shutdown();
  return shutdownPromise;
}

type StopAndDrain = () => void | Promise<void>;
let signalHandlersInstalled = false;

export function installGracefulSignalHandlers(
  stopAndDrain: StopAndDrain,
): void {
  if (signalHandlersInstalled) {
    throw new Error('graceful signal handlers are already installed');
  }
  signalHandlersInstalled = true;
  let signalShutdownStarted = false;
  const handleSignal = (forcedExitCode: number): void => {
    if (signalShutdownStarted) {
      process.exit(forcedExitCode);
    }
    signalShutdownStarted = true;
    const forcedExit = setTimeout(() => process.exit(forcedExitCode), 10_000);
    void (async () => {
      let failed = false;
      try {
        // This must stop intake, drain in-flight work, and emit final logs.
        await stopAndDrain();
      } catch (error: unknown) {
        failed = true;
        console.error('Application drain failed', error);
      }
      try {
        await shutdownOnce();
      } catch (error: unknown) {
        failed = true;
        console.error('OpenTelemetry shutdown failed', error);
      }
      clearTimeout(forcedExit);
      process.exit(failed ? 1 : 0);
    })();
  };

  process.once('SIGTERM', () => handleSignal(143));
  process.once('SIGINT', () => handleSignal(130));
}
```

This complete example assumes the detected application logs use `console.*`,
preflight found no existing bridge, and
that the selected Node runtime satisfies the console instrumentation's
version range. The instrumentation emits one OTel LogRecord and still calls the
original console method, so console output remains. If `console.*` is the only
stack on an older Node runtime, do not change the toolchain or invent a bridge;
report `unsupported-stack` with the required Node version. Integrate
`shutdownOnce()` into the app's existing graceful shutdown sequence after it
stops accepting work and emits final application logs, then let that owner
terminate the process. Do not install another signal owner in that case. When
the application has no graceful owner, call the exported handler installer
with its actual stop-and-drain primitive after creating the server or worker:

```typescript
import { installGracefulSignalHandlers } from './instrumentation';

const server = app.listen(port);
installGracefulSignalHandlers(
  () => new Promise<void>((resolve, reject) => {
    server.close((error?: Error) => error ? reject(error) : resolve());
  }),
);
```

Adapt the callback to drain every detected queue/worker as well as the HTTP
server. The handler always attempts telemetry shutdown after that callback
settles, even when draining reports an error. Its bounded timeout prevents a
stalled drain or exporter from leaving the process alive indefinitely; a
successful drain and flush exits `0`, a drain/export failure exits `1`, and a
timeout or second signal uses the conventional nonzero signal exit code.

Adapt `LOCAL_OBSERVER_LOGS_ENDPOINT` to the detected Observer service address
for Docker/Compose. On the absent/`otlp` branch, any other explicit endpoint
throws before `NodeSDK` or the logging bridge is constructed. Report that
operator-owned boundary conflict instead of converting it to local or cloud
export.

With `OTEL_LOGS_EXPORTER=none`, both the added processor and bridge are omitted.
For another explicit exporter such as `console`, leave provider, exporter, and
bridge ownership entirely to the proven operator-owned setup; this helper adds
none of them. Verify that setup already owns exactly one detected application
bridge. If ownership cannot be proven, report `Not configured`; an environment
value alone is not evidence of a working pipeline. Adding
`ConsoleInstrumentation` here would duplicate console output when NodeSDK owns
the console exporter.

The processor construction above matches current `@opentelemetry/sdk-logs`
0.221.x, whose constructor receives `{ exporter }`. Older project-pinned SDK
versions used `new BatchLogRecordProcessor(exporter)`; inspect the installed
version and retain its documented signature instead of changing versions just
to copy this example.

For Pino or Winston, replace `ConsoleInstrumentation` with exactly one detected
bridge:

```typescript
// Pino v7+ log sending; keep its existing destination/transports.
new PinoInstrumentation({
  disableLogSending: false,
  disableLogCorrelation: false,
})

// Winston v3 log sending; keep its existing Console/File transports.
new WinstonInstrumentation({
  disableLogSending: false,
  disableLogCorrelation: false,
})
```

Import the matching class from `@opentelemetry/instrumentation-pino` or
`@opentelemetry/instrumentation-winston`. Winston's instrumentation-managed
sending already installs the OTel transport. Do not also add
`OpenTelemetryTransportV3`; doing both exports each record twice. Similarly,
do not combine Pino instrumentation sending with
`pino-opentelemetry-transport`, which owns an independent provider. If the app
already uses one of those transports, keep it as the single owner and do not
add instrumentation log sending.

The explicit `exportIntervalMillis` and `exportTimeoutMillis` are required for
local and eval runs. Do not rely on metric reader defaults; they can be too slow
for short-lived runtime checks, causing valid HTTP metrics to never reach the
collector before the process stops. Keep the timeout less than or equal to the
interval; the Node SDK rejects configurations such as interval `1000` ms with
the default timeout `30000` ms.

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

If the repo already uses `npm run start`, `npm run dev`, `tsx`, `ts-node`, or `nodemon`, add the preload there instead of creating a separate observability-only command path.

If the project already runs in Docker:
```dockerfile
ENV OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
ENV OTEL_LOGS_EXPORTER=otlp
ENV OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://otel-collector:4318/v1/logs
CMD ["node", "--require", "./instrumentation.js", "app.js"]
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

Before adding a custom counter or histogram for an outcome that happens
inside a request `@opentelemetry/instrumentation-http` already covers,
check whether it belongs as an attribute on `http.server.request.duration`
instead — see `../../SKILL.md` `#### Implementation Rules` and the
`Node.js:` entry under `#### Language-Specific Musts`. The instrumentation
already sets `http.response.status_code` on that metric from the response
for every request with no extra code, but it does not set `error.type` from
a failing status: that attribute is reserved there for a lower-level
request/response transport error, not an ordinary 4xx/5xx completion.
Define a new instrument when the signal does not correlate 1:1 with a single
request (a queue-depth gauge or background job outcome), or cannot be
represented by `http.response.status_code` alone -- `@opentelemetry/instrumentation-http`
has no per-call metric-attribute hook for adding a finer-grained reason
dimension the way Go's `Labeler` can.

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

## Error Handling

APM backends identify errors by `otel.status_code = ERROR`. Always set error status:

```typescript
import { SpanStatusCode } from '@opentelemetry/api';

span.setStatus({ code: SpanStatusCode.ERROR, message: 'Payment failed' });
span.recordException(error);
```

Express/Fastify auto-instrumentation automatically sets ERROR on 5xx responses.

---

## OTLP Export Configuration

Use environment variables for operator-owned configuration. The only endpoint
literal in the SDK example is the signal-specific local Observer logs fallback,
which prevents a generic direct-cloud endpoint from becoming the implicit log
destination.

| Variable | Default | Purpose |
|----------|---------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | OTLP HTTP endpoint |
| `OTEL_EXPORTER_OTLP_HEADERS` | unset | Move cloud credentials to trace/metric signal headers and remove this generic value before enabling the Obstudio-owned local log path, even when logs headers are set |
| `OTEL_LOGS_EXPORTER` | `otlp` only when the logs endpoint is absent or detected-local | `none` disables the added local log pipeline; another explicit value remains operator-owned |
| `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | `http://localhost:4318/v1/logs` for host/native Obstudio runs | Signal-specific local application-log destination |
| `OTEL_EXPORTER_OTLP_LOGS_PROTOCOL` | `http/protobuf` for the shown local baseline | Select a matching official exporter for another explicit protocol |
| `OTEL_EXPORTER_OTLP_LOGS_HEADERS` | unset | Signal-specific operator log headers; generic cloud headers are rejected from the log path |
| `OTEL_SERVICE_NAME` | (must be set) | Service identity in telemetry |
| `OTEL_METRIC_EXPORT_INTERVAL` | `60000` | Metric export interval (ms) |
| `OTEL_METRIC_EXPORT_TIMEOUT` | `30000` | Metric export timeout (ms) |
| `OTEL_BSP_SCHEDULE_DELAY` | `5000` | Span batch export delay (ms) |

For local development with the Observer, run with:

    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
    OTEL_LOGS_EXPORTER=otlp
    OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://localhost:4318/v1/logs
    OTEL_METRIC_EXPORT_INTERVAL=1000
    OTEL_METRIC_EXPORT_TIMEOUT=500
    OTEL_BSP_SCHEDULE_DELAY=100

When creating `PeriodicExportingMetricReader`, pass
`exportIntervalMillis: Number(process.env.OTEL_METRIC_EXPORT_INTERVAL || 1000)`
and `exportTimeoutMillis: Number(process.env.OTEL_METRIC_EXPORT_TIMEOUT || 500)`.
This makes HTTP metrics from `@opentelemetry/instrumentation-http`, including
`http.server.request.duration` when stable HTTP semantic conventions are
enabled, export promptly to Observer.

### Local Observer application logs and cloud boundary

Local OTLP application logs are the default for a detected supported Node.js
logging stack only when the exporter is absent/`otlp` and the logs endpoint is
absent or matches the detected local Observer receiver. `none` omits the added
processor and bridge while the original console/file destination continues;
another non-OTLP exporter remains operator-owned and its endpoint is not
interpreted. When traces or metrics use direct-cloud signal endpoints, keep
the logs endpoint on local Observer. Never copy a Splunk ingest URL, realm,
access token, generic cloud header, cloud exporter, or forwarding flag into log
configuration. For the absent/`otlp` branch, reject a non-local explicit logs
endpoint before constructing `NodeSDK` or the bridge, preserve it as operator
configuration, report the cloud-boundary conflict, and require the operator to
resolve it. Also reject any generic OTLP header on the local branch even when
signal-specific logs headers exist; move the generic credentials to
trace/metric variables and remove the generic setting. Obstudio cloud
forwarding remains traces and metrics only.

Verify one sanitized record at each required severity both outside and inside
an active span. Assert body/category, severity, shared `service.name`,
trace/span IDs when active, presence in the original console/file sink, one
record in Observer, and zero OTLP records under `OTEL_LOGS_EXPORTER=none`.
That record-count assertion is required for Console, Pino, and Winston because
their transport/instrumentation combinations can otherwise duplicate logs.

---

## Framework Notes

### Express
Auto-instrumented via `@opentelemetry/instrumentation-express` (included in auto-instrumentations-node). All middleware and route handlers produce spans.

### Fastify
Auto-instrumented via `@opentelemetry/instrumentation-fastify`. Hooks and handlers produce spans automatically.

### Database Clients
Auto-instrumented: `pg`, `mysql2`, `mongodb`, `redis`, `ioredis` -- all included in the auto-instrumentations package.

---

## Gotchas

- **ESM vs CJS**: Node.js ESM requires `--import` instead of `--require`.
  If the project has `"type": "module"` in `package.json`, use `--import`.
- **Registration order**: HTTP instrumentation must be registered before
  framework instrumentations. The `NodeSDK` `instrumentations` array is
  order-sensitive.
- **Singleton SDK**: Never call `new NodeSDK()` more than once. If existing
  OTel setup exists, extend its instrumentation array.
- **Graceful shutdown**: Call the idempotent SDK shutdown from the app's
  existing termination sequence after intake stops, then terminate. Only when
  no owner exists, install bounded `SIGTERM`/`SIGINT` handlers that flush and
  explicitly exit; awaiting `sdk.shutdown()` without exiting can leave a
  server process alive after its default signal behavior was intercepted.
- **One logging bridge**: choose Console, Pino, or Winston based on the actual
  logging calls. Do not add multiple bridges to the same record path, and do
  not pair instrumentation-managed sending with a second OTel transport.
- **Metric reader option**: Use the `NodeSDK` option `metricReader` exactly as
  shown above. Do not write `metricReaders` unless the installed SDK version
  documents that option; older versions ignore it and fall back to env-based
  reader setup.
- **Metric export interval and timeout**: Always set `exportIntervalMillis` and
  `exportTimeoutMillis` on `PeriodicExportingMetricReader`. Environment
  variables alone are not enough when constructing the reader manually, and the
  timeout must be less than or equal to the interval.
- **Avoid `@opentelemetry/auto-instrumentations-node`**: This meta-package
  installs every instrumentation. Only install what the project uses to
  minimize dependency surface.
- **TypeScript types**: If using TypeScript, `@opentelemetry/api` provides
  full type definitions. No separate `@types` packages needed.
