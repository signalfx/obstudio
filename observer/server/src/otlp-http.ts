import express from "express";
import http from "node:http";
import { gunzipSync, gzipSync } from "node:zlib";
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

const otlpHost = process.env.OTLP_HOST ?? process.env.HOST ?? "127.0.0.1";
const otlpPort = Number(process.env.OTLP_PORT ?? 4318);
const otlpPayloadLimit = process.env.OTLP_PAYLOAD_LIMIT ?? "10mb";
const supportedContentTypes = new Set(["application/json", "application/x-protobuf"]);
const hexIdPattern = /^[0-9a-fA-F]+$/;

type MessageCodec<TMessage> = {
  create: () => TMessage;
  decode: (input: Uint8Array) => TMessage;
  encode: (message: TMessage) => { finish: () => Uint8Array };
  fromJSON: (input: unknown) => TMessage;
  toJSON: (message: TMessage) => unknown;
};

type OtlpSignalDefinition<TRequest, TResponse> = {
  path: string;
  requestCodec: MessageCodec<TRequest>;
  responseCodec: MessageCodec<TResponse>;
  persist: (message: TRequest) => void;
  signal: "logs" | "metrics" | "traces";
  summarize: (message: TRequest) => string;
};

const traceServiceModule = await import(
  new URL("../../shared/otlp/opentelemetry/proto/collector/trace/v1/trace_service.js", import.meta.url).href,
);
const metricsServiceModule = await import(
  new URL("../../shared/otlp/opentelemetry/proto/collector/metrics/v1/metrics_service.js", import.meta.url).href,
);
const logsServiceModule = await import(
  new URL("../../shared/otlp/opentelemetry/proto/collector/logs/v1/logs_service.js", import.meta.url).href,
);

const logsSignal = createSignal<LogsRequest, LogsResponse>({
  path: "/v1/logs",
  requestCodec: logsServiceModule.ExportLogsServiceRequest as MessageCodec<LogsRequest>,
  responseCodec: logsServiceModule.ExportLogsServiceResponse as MessageCodec<LogsResponse>,
  persist: (message) => otlpInMemoryStore.storeLogs(message),
  signal: "logs",
  summarize: summarizeLogsRequest,
});

const metricsSignal = createSignal<MetricsRequest, MetricsResponse>({
  path: "/v1/metrics",
  requestCodec: metricsServiceModule.ExportMetricsServiceRequest as MessageCodec<MetricsRequest>,
  responseCodec: metricsServiceModule.ExportMetricsServiceResponse as MessageCodec<MetricsResponse>,
  persist: (message) => otlpInMemoryStore.storeMetrics(message),
  signal: "metrics",
  summarize: summarizeMetricsRequest,
});

const tracesSignal = createSignal<TraceRequest, TraceResponse>({
  path: "/v1/traces",
  requestCodec: traceServiceModule.ExportTraceServiceRequest as MessageCodec<TraceRequest>,
  responseCodec: traceServiceModule.ExportTraceServiceResponse as MessageCodec<TraceResponse>,
  persist: (message) => otlpInMemoryStore.storeTraces(message),
  signal: "traces",
  summarize: summarizeTraceRequest,
});

export function createOtlpHttpServer(): http.Server {
  const app = express();

  registerSignalRoute(app, logsSignal);
  registerSignalRoute(app, metricsSignal);
  registerSignalRoute(app, tracesSignal);

  return http.createServer(app);
}

export function listenForOtlpHttp(): http.Server {
  const server = createOtlpHttpServer();

  server.listen(otlpPort, otlpHost, () => {
    console.log(`Observer OTLP receiver listening on http://${otlpHost}:${otlpPort}`);
  });

  return server;
}

function registerSignalRoute<TRequest, TResponse>(
  app: express.Express,
  signal: OtlpSignalDefinition<TRequest, TResponse>,
): void {
  app.post(signal.path, express.raw({ limit: otlpPayloadLimit, type: () => true }), (request, response) => {
    handleOtlpRequest(request, response, signal);
  });
}

function handleOtlpRequest<TRequest, TResponse>(
  request: express.Request,
  response: express.Response,
  signal: OtlpSignalDefinition<TRequest, TResponse>,
): void {
  const contentType = parseContentType(request.header("content-type"));

  if (contentType === null) {
    sendStatusError(response, 415, "Unsupported Content-Type header.", "application/json");
    return;
  }

  const body = request.body;

  if (!Buffer.isBuffer(body)) {
    sendStatusError(response, 400, "Expected a binary request body.", contentType);
    return;
  }

  let payload: Uint8Array;

  try {
    payload = decodeRequestBody(body, request.header("content-encoding"));
  } catch (error) {
    sendStatusError(response, 415, getErrorMessage(error, "Unsupported Content-Encoding header."), contentType);
    return;
  }

  try {
    const message = contentType === "application/json"
      ? signal.requestCodec.fromJSON(normalizeOtlpJson(JSON.parse(Buffer.from(payload).toString("utf8"))))
      : signal.requestCodec.decode(payload);
    const responseMessage = signal.responseCodec.create();

    signal.persist(message);
    console.log(`[otlp] accepted ${signal.signal}: ${signal.summarize(message)}`);
    sendOtlpResponse(response, 200, signal.responseCodec, responseMessage, contentType, request.header("accept-encoding"));
  } catch (error) {
    sendStatusError(response, 400, getErrorMessage(error, `Failed to decode OTLP ${signal.signal} payload.`), contentType);
  }
}

function parseContentType(headerValue: string | undefined): "application/json" | "application/x-protobuf" | null {
  if (headerValue === undefined) {
    return null;
  }

  const mediaType = headerValue.split(";")[0]?.trim().toLowerCase();
  return supportedContentTypes.has(mediaType) ? mediaType as "application/json" | "application/x-protobuf" : null;
}

function decodeRequestBody(body: Buffer, contentEncoding: string | undefined): Uint8Array {
  if (contentEncoding === undefined || contentEncoding.trim() === "") {
    return body;
  }

  const encodings = contentEncoding
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter((value) => value !== "");
  let payload = body;

  for (const encoding of encodings) {
    if (encoding === "identity") {
      continue;
    }

    if (encoding !== "gzip") {
      throw new Error(`Unsupported Content-Encoding: ${encoding}`);
    }

    payload = gunzipSync(payload);
    break;
  }

  return payload;
}

function sendOtlpResponse<TResponse>(
  response: express.Response,
  statusCode: number,
  codec: MessageCodec<TResponse>,
  message: TResponse,
  contentType: "application/json" | "application/x-protobuf",
  acceptEncoding: string | undefined,
): void {
  const payload = contentType === "application/json"
    ? Buffer.from(JSON.stringify(codec.toJSON(message)))
    : Buffer.from(codec.encode(message).finish());
  const shouldGzip = acceptEncoding?.toLowerCase().includes("gzip") ?? false;

  response.status(statusCode);
  response.setHeader("Content-Type", contentType);

  if (shouldGzip) {
    response.setHeader("Content-Encoding", "gzip");
    response.send(gzipSync(payload));
    return;
  }

  response.send(payload);
}

function sendStatusError(
  response: express.Response,
  statusCode: number,
  message: string,
  contentType: "application/json" | "application/x-protobuf",
): void {
  response.status(statusCode);
  response.setHeader("Content-Type", contentType);

  if (contentType === "application/json") {
    response.send(JSON.stringify({ message }));
    return;
  }

  response.send(Buffer.from(encodeRpcStatus(message)));
}

function encodeRpcStatus(message: string): Uint8Array {
  const messageBytes = Buffer.from(message);
  return Buffer.concat([
    Buffer.from([0x12]),
    encodeVarint(messageBytes.length),
    messageBytes,
  ]);
}

function encodeVarint(value: number): Uint8Array {
  const bytes: number[] = [];
  let remaining = value >>> 0;

  while (remaining >= 0x80) {
    bytes.push((remaining & 0x7f) | 0x80);
    remaining >>>= 7;
  }

  bytes.push(remaining);
  return Uint8Array.from(bytes);
}

function normalizeOtlpJson(value: unknown): unknown {
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

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function createSignal<TRequest, TResponse>(
  signal: OtlpSignalDefinition<TRequest, TResponse>,
): OtlpSignalDefinition<TRequest, TResponse> {
  return signal;
}
