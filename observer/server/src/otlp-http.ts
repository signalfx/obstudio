import express from "express";
import http from "node:http";
import { gunzipSync, gzipSync } from "node:zlib";

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

type OtlpSignalDefinition = {
  path: string;
  requestCodec: MessageCodec<unknown>;
  responseCodec: MessageCodec<unknown>;
  signal: "logs" | "metrics" | "traces";
  summarize: (message: unknown) => string;
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

const signals: OtlpSignalDefinition[] = [
  {
    path: "/v1/logs",
    requestCodec: logsServiceModule.ExportLogsServiceRequest as MessageCodec<unknown>,
    responseCodec: logsServiceModule.ExportLogsServiceResponse as MessageCodec<unknown>,
    signal: "logs",
    summarize: summarizeLogsRequest,
  },
  {
    path: "/v1/metrics",
    requestCodec: metricsServiceModule.ExportMetricsServiceRequest as MessageCodec<unknown>,
    responseCodec: metricsServiceModule.ExportMetricsServiceResponse as MessageCodec<unknown>,
    signal: "metrics",
    summarize: summarizeMetricsRequest,
  },
  {
    path: "/v1/traces",
    requestCodec: traceServiceModule.ExportTraceServiceRequest as MessageCodec<unknown>,
    responseCodec: traceServiceModule.ExportTraceServiceResponse as MessageCodec<unknown>,
    signal: "traces",
    summarize: summarizeTraceRequest,
  },
];

export function createOtlpHttpServer(): http.Server {
  const app = express();

  for (const signal of signals) {
    app.post(signal.path, express.raw({ limit: otlpPayloadLimit, type: () => true }), (request, response) => {
      handleOtlpRequest(request, response, signal);
    });
  }

  return http.createServer(app);
}

export function listenForOtlpHttp(): http.Server {
  const server = createOtlpHttpServer();

  server.listen(otlpPort, otlpHost, () => {
    console.log(`Observer OTLP receiver listening on http://${otlpHost}:${otlpPort}`);
  });

  return server;
}

function handleOtlpRequest(
  request: express.Request,
  response: express.Response,
  signal: OtlpSignalDefinition,
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
    break
  }

  return payload;
}

function sendOtlpResponse(
  response: express.Response,
  statusCode: number,
  codec: MessageCodec<unknown>,
  message: unknown,
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

function summarizeTraceRequest(message: unknown): string {
  const resourceSpans = readArrayField(message, "resourceSpans");
  const scopeSpans = resourceSpans.flatMap((resource) => readArrayField(resource, "scopeSpans"));
  const spans = scopeSpans.flatMap((scope) => readArrayField(scope, "spans"));

  return `${resourceSpans.length} resource spans, ${scopeSpans.length} scope spans, ${spans.length} spans`;
}

function summarizeLogsRequest(message: unknown): string {
  const resourceLogs = readArrayField(message, "resourceLogs");
  const scopeLogs = resourceLogs.flatMap((resource) => readArrayField(resource, "scopeLogs"));
  const logRecords = scopeLogs.flatMap((scope) => readArrayField(scope, "logRecords"));

  return `${resourceLogs.length} resource logs, ${scopeLogs.length} scope logs, ${logRecords.length} log records`;
}

function summarizeMetricsRequest(message: unknown): string {
  const resourceMetrics = readArrayField(message, "resourceMetrics");
  const scopeMetrics = resourceMetrics.flatMap((resource) => readArrayField(resource, "scopeMetrics"));
  const metrics = scopeMetrics.flatMap((scope) => readArrayField(scope, "metrics"));
  const dataPoints = metrics.reduce<number>((count, metric) => count + countMetricDataPoints(metric), 0);

  return `${resourceMetrics.length} resource metrics, ${scopeMetrics.length} scope metrics, ${metrics.length} metrics, ${dataPoints} data points`;
}

function countMetricDataPoints(metric: unknown): number {
  const metricRecord = asRecord(metric);

  if (metricRecord === null) {
    return 0;
  }

  return [
    "gauge",
    "sum",
    "histogram",
    "exponentialHistogram",
    "summary",
  ].reduce<number>((count, fieldName) => count + readArrayField(metricRecord[fieldName], "dataPoints").length, 0);
}

function readArrayField(value: unknown, key: string): unknown[] {
  const record = asRecord(value);
  const fieldValue = record?.[key];
  return globalThis.Array.isArray(fieldValue) ? fieldValue : [];
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" ? value as Record<string, unknown> : null;
}

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}
