/**
 * OpenTelemetry SDK setup — creates isolated TracerProviders per service.
 * Uses non-global providers to avoid the single-global-provider limitation.
 *
 * Simulated topology:
 *   api-gateway → user-service, order-service, payment-service
 *   user-service → postgresql
 *   order-service → postgresql, redis
 *   payment-service → api.stripe.com
 *   notification-service → kafka
 */
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-proto";
import { OTLPMetricExporter } from "@opentelemetry/exporter-metrics-otlp-proto";
import { OTLPLogExporter } from "@opentelemetry/exporter-logs-otlp-proto";
import { BasicTracerProvider, BatchSpanProcessor } from "@opentelemetry/sdk-trace-base";
import { MeterProvider, PeriodicExportingMetricReader } from "@opentelemetry/sdk-metrics";
import { LoggerProvider, BatchLogRecordProcessor } from "@opentelemetry/sdk-logs";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { ATTR_SERVICE_NAME, ATTR_SERVICE_VERSION } from "@opentelemetry/semantic-conventions";
import { context } from "@opentelemetry/api";
import { AsyncLocalStorageContextManager } from "@opentelemetry/context-async-hooks";

// Register a context manager so startActiveSpan() propagates context across async calls.
// Without this, BasicTracerProvider uses a no-op context manager and spans don't nest.
const contextManager = new AsyncLocalStorageContextManager();
contextManager.enable();
context.setGlobalContextManager(contextManager);

const OTLP_ENDPOINT = process.env.OTEL_EXPORTER_OTLP_ENDPOINT || "http://localhost:4318";

export const SERVICE_NAMES = [
  "api-gateway",
  "user-service",
  "order-service",
  "payment-service",
  "notification-service",
] as const;

export type ServiceName = (typeof SERVICE_NAMES)[number];

type ServiceSDK = {
  tracerProvider: BasicTracerProvider;
  meterProvider: MeterProvider;
  loggerProvider: LoggerProvider;
  tracer: ReturnType<BasicTracerProvider["getTracer"]>;
  meter: ReturnType<MeterProvider["getMeter"]>;
  logger: ReturnType<LoggerProvider["getLogger"]>;
};

const serviceSDKs = new Map<string, ServiceSDK>();

for (const svcName of SERVICE_NAMES) {
  const resource = resourceFromAttributes({
    [ATTR_SERVICE_NAME]: svcName,
    [ATTR_SERVICE_VERSION]: "1.0.0",
    "deployment.environment.name": "development",
  });

  const tracerProvider = new BasicTracerProvider({
    resource,
    spanProcessors: [
      new BatchSpanProcessor(new OTLPTraceExporter({ url: `${OTLP_ENDPOINT}/v1/traces` })),
    ],
  });

  const meterProvider = new MeterProvider({
    resource,
    readers: [
      new PeriodicExportingMetricReader({
        exporter: new OTLPMetricExporter({ url: `${OTLP_ENDPOINT}/v1/metrics` }),
        exportIntervalMillis: 5000,
      }),
    ],
  });

  const loggerProvider = new LoggerProvider({
    resource,
    processors: [
      new BatchLogRecordProcessor(
        new OTLPLogExporter({ url: `${OTLP_ENDPOINT}/v1/logs` }),
      ),
    ],
  });

  serviceSDKs.set(svcName, {
    tracerProvider,
    meterProvider,
    loggerProvider,
    tracer: tracerProvider.getTracer(svcName, "1.0.0"),
    meter: meterProvider.getMeter(svcName, "1.0.0"),
    logger: loggerProvider.getLogger(svcName, "1.0.0"),
  });
}

export function getTracer(svc: ServiceName) {
  return serviceSDKs.get(svc)!.tracer;
}

export function getMeter(svc: ServiceName) {
  return serviceSDKs.get(svc)!.meter;
}

export function getLogger(svc: ServiceName) {
  return serviceSDKs.get(svc)!.logger;
}

export async function shutdown() {
  const promises: Promise<void>[] = [];
  for (const sdk of serviceSDKs.values()) {
    promises.push(sdk.tracerProvider.shutdown().catch(() => {}));
    promises.push(sdk.meterProvider.shutdown().catch(() => {}));
    promises.push(sdk.loggerProvider.shutdown().catch(() => {}));
  }
  await Promise.all(promises);
}
