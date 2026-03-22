import {
  ExportLogsServiceRequest as ExportLogsServiceRequestCodec,
  ExportLogsServiceResponse as ExportLogsServiceResponseCodec,
} from "../../shared/otlp/opentelemetry/proto/collector/logs/v1/logs_service.js";
import {
  ExportMetricsServiceRequest as ExportMetricsServiceRequestCodec,
  ExportMetricsServiceResponse as ExportMetricsServiceResponseCodec,
} from "../../shared/otlp/opentelemetry/proto/collector/metrics/v1/metrics_service.js";
import {
  ExportTraceServiceRequest as ExportTraceServiceRequestCodec,
  ExportTraceServiceResponse as ExportTraceServiceResponseCodec,
} from "../../shared/otlp/opentelemetry/proto/collector/trace/v1/trace_service.js";
import type {
  ExportLogsServiceRequest as LogsRequest,
  ExportLogsServiceResponse as LogsResponse,
} from "../../shared/otlp/opentelemetry/proto/collector/logs/v1/logs_service.d.mts";
import type {
  ExportMetricsServiceRequest as MetricsRequest,
  ExportMetricsServiceResponse as MetricsResponse,
} from "../../shared/otlp/opentelemetry/proto/collector/metrics/v1/metrics_service.d.mts";
import type {
  ExportTraceServiceRequest as TraceRequest,
  ExportTraceServiceResponse as TraceResponse,
} from "../../shared/otlp/opentelemetry/proto/collector/trace/v1/trace_service.d.mts";
import type { Metric } from "../../shared/otlp/opentelemetry/proto/metrics/v1/metrics.d.mts";
import { otlpInMemoryStore } from "./otlp-store.js";

export const otlpHost = process.env.OTLP_HOST ?? process.env.HOST ?? "127.0.0.1";
export const otlpHttpPort = Number(process.env.OTLP_HTTP_PORT ?? process.env.OTLP_PORT ?? 4318);
export const otlpGrpcPort = Number(process.env.OTLP_GRPC_PORT ?? 4317);
export const otlpPayloadLimit = process.env.OTLP_PAYLOAD_LIMIT ?? "10mb";

/** Minimal surface needed from generated message codecs across transports. */
export type MessageCodec<TMessage> = {
  create: () => TMessage;
  decode: (input: Uint8Array) => TMessage;
  encode: (message: TMessage) => { finish: () => Uint8Array };
  fromJSON: (input: unknown) => TMessage;
  toJSON: (message: TMessage) => unknown;
};

export type OtlpSignal = "logs" | "metrics" | "traces";

export type OtlpSignalDefinition<TRequest, TResponse> = {
  path: string;
  requestCodec: MessageCodec<TRequest>;
  responseCodec: MessageCodec<TResponse>;
  persist: (message: TRequest) => void;
  signal: OtlpSignal;
  summarize: (message: TRequest) => string;
};

export const logsSignal = createSignal<LogsRequest, LogsResponse>({
  path: "/v1/logs",
  requestCodec: ExportLogsServiceRequestCodec as MessageCodec<LogsRequest>,
  responseCodec: ExportLogsServiceResponseCodec as MessageCodec<LogsResponse>,
  persist: (message) => otlpInMemoryStore.storeLogs(message),
  signal: "logs",
  summarize: summarizeLogsRequest,
});

export const metricsSignal = createSignal<MetricsRequest, MetricsResponse>({
  path: "/v1/metrics",
  requestCodec: ExportMetricsServiceRequestCodec as MessageCodec<MetricsRequest>,
  responseCodec: ExportMetricsServiceResponseCodec as MessageCodec<MetricsResponse>,
  persist: (message) => otlpInMemoryStore.storeMetrics(message),
  signal: "metrics",
  summarize: summarizeMetricsRequest,
});

export const tracesSignal = createSignal<TraceRequest, TraceResponse>({
  path: "/v1/traces",
  requestCodec: ExportTraceServiceRequestCodec as MessageCodec<TraceRequest>,
  responseCodec: ExportTraceServiceResponseCodec as MessageCodec<TraceResponse>,
  persist: (message) => otlpInMemoryStore.storeTraces(message),
  signal: "traces",
  summarize: summarizeTraceRequest,
});

export function ingestOtlpMessage<TRequest, TResponse>(
  signal: OtlpSignalDefinition<TRequest, TResponse>,
  message: TRequest,
): TResponse {
  signal.persist(message);
  console.log(`[otlp] accepted ${signal.signal}: ${signal.summarize(message)}`);
  return signal.responseCodec.create();
}

export function normalizeOtlpJson(value: unknown): unknown {
  if (globalThis.Array.isArray(value)) {
    return value.map((entry) => normalizeOtlpJson(entry));
  }

  if (value === null || typeof value !== "object") {
    return value;
  }

  const normalizedEntries = Object.entries(value).map(([key, childValue]) => {
    if ((key === "traceId" || key === "spanId") && typeof childValue === "string" && hexIdPattern.test(childValue)) {
      return [key, Buffer.from(childValue, "hex").toString("base64")];
    }

    return [key, normalizeOtlpJson(childValue)];
  });

  return Object.fromEntries(normalizedEntries);
}

export function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

const hexIdPattern = /^[0-9a-fA-F]+$/;

function summarizeTraceRequest(message: TraceRequest): string {
  const resourceSpans = message.resourceSpans;
  const scopeSpans = resourceSpans.flatMap((resource) => resource.scopeSpans);
  const spans = scopeSpans.flatMap((scope) => scope.spans);

  return `${resourceSpans.length} resource spans, ${scopeSpans.length} scope spans, ${spans.length} spans`;
}

function summarizeLogsRequest(message: LogsRequest): string {
  const resourceLogs = message.resourceLogs;
  const scopeLogs = resourceLogs.flatMap((resource) => resource.scopeLogs);
  const logRecords = scopeLogs.flatMap((scope) => scope.logRecords);

  return `${resourceLogs.length} resource logs, ${scopeLogs.length} scope logs, ${logRecords.length} log records`;
}

function summarizeMetricsRequest(message: MetricsRequest): string {
  const resourceMetrics = message.resourceMetrics;
  const scopeMetrics = resourceMetrics.flatMap((resource) => resource.scopeMetrics);
  const metrics = scopeMetrics.flatMap((scope) => scope.metrics);
  const dataPoints = metrics.reduce<number>((count, metric) => count + countMetricDataPoints(metric), 0);

  return `${resourceMetrics.length} resource metrics, ${scopeMetrics.length} scope metrics, ${metrics.length} metrics, ${dataPoints} data points`;
}

function countMetricDataPoints(metric: Metric): number {
  switch (metric.data?.$case) {
    case "gauge":
      return metric.data.gauge.dataPoints.length;
    case "sum":
      return metric.data.sum.dataPoints.length;
    case "histogram":
      return metric.data.histogram.dataPoints.length;
    case "exponentialHistogram":
      return metric.data.exponentialHistogram.dataPoints.length;
    case "summary":
      return metric.data.summary.dataPoints.length;
    default:
      return 0;
  }
}

function createSignal<TRequest, TResponse>(
  signal: OtlpSignalDefinition<TRequest, TResponse>,
): OtlpSignalDefinition<TRequest, TResponse> {
  return signal;
}
