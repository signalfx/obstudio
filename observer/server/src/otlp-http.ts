import express from "express";
import http from "node:http";
import { gunzipSync, gzipSync } from "node:zlib";
import {
  type MessageCodec,
  type OtlpIngestContext,
  type OtlpSignalDefinition,
  getErrorMessage,
  ingestOtlpMessage,
  logsSignal,
  metricsSignal,
  normalizeOtlpJson,
  otlpHost,
  otlpHttpPort,
  otlpPayloadLimit,
  tracesSignal,
} from "./otlp-ingest.js";
import { resolveHttpConnectionId } from "./otlp-http-connections.js";

const supportedContentTypes = new Set(["application/json", "application/x-protobuf"]);

/** Create an OTLP/HTTP receiver with one endpoint per supported signal. */
export function createOtlpHttpServer(): http.Server {
  const app = express();

  registerSignalRoute(app, logsSignal);
  registerSignalRoute(app, metricsSignal);
  registerSignalRoute(app, tracesSignal);

  return http.createServer(app);
}

export function listenForOtlpHttp(): http.Server {
  const server = createOtlpHttpServer();

  server.listen(otlpHttpPort, otlpHost, () => {
    console.log(`Observer OTLP/HTTP receiver listening on http://${otlpHost}:${otlpHttpPort}`);
  });

  return server;
}

/** Register a raw-body POST endpoint so OTLP JSON and protobuf share one path. */
function registerSignalRoute<TRequest, TResponse>(
  app: express.Express,
  signal: OtlpSignalDefinition<TRequest, TResponse>,
): void {
  app.post(signal.path, express.raw({ limit: otlpPayloadLimit, type: () => true }), (request, response) => {
    void handleOtlpRequest(request, response, signal);
  });
}

/**
 * Common OTLP request pipeline:
 * validate content type, decode compression, parse OTLP payload, persist it,
 * and reply using the same transport encoding family as the request.
 */
async function handleOtlpRequest<TRequest, TResponse>(
  request: express.Request,
  response: express.Response,
  signal: OtlpSignalDefinition<TRequest, TResponse>,
): Promise<void> {
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
    const context = await getHttpIngestContext(request);
    const message = contentType === "application/json"
      ? signal.requestCodec.fromJSON(normalizeOtlpJson(JSON.parse(Buffer.from(payload).toString("utf8"))))
      : signal.requestCodec.decode(payload);
    const responseMessage = ingestOtlpMessage(signal, message, context);
    sendOtlpResponse(response, 200, signal.responseCodec, responseMessage, contentType, request.header("accept-encoding"));
  } catch (error) {
    sendStatusError(response, 400, getErrorMessage(error, `Failed to decode OTLP ${signal.signal} payload.`), contentType);
  }
}

async function getHttpIngestContext(request: express.Request): Promise<OtlpIngestContext> {
  const connectionId = await resolveHttpConnectionId(request);
  return connectionId === undefined ? {} : { connectionId };
}

/** Extract the media type portion from `Content-Type` and allow only OTLP formats. */
function parseContentType(headerValue: string | undefined): "application/json" | "application/x-protobuf" | null {
  if (headerValue === undefined) {
    return null;
  }

  const mediaType = headerValue.split(";")[0]?.trim().toLowerCase();
  return supportedContentTypes.has(mediaType) ? mediaType as "application/json" | "application/x-protobuf" : null;
}

/**
 * OTLP clients may gzip request bodies. We currently support `identity` and
 * `gzip`; any other encoding is rejected with `415 Unsupported Media Type`.
 */
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

/**
 * Encode the success response in the same OTLP format as the request and gzip
 * the response when the client advertises support for it.
 */
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

/**
 * Errors follow the caller's chosen OTLP transport:
 * JSON callers get a JSON object, protobuf callers get a protobuf-encoded
 * `google.rpc.Status` payload.
 */
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

/** Encode just enough of `google.rpc.Status` for OTLP protobuf error responses. */
function encodeRpcStatus(message: string): Uint8Array {
  const messageBytes = Buffer.from(message);
  return Buffer.concat([
    Buffer.from([0x12]),
    encodeVarint(messageBytes.length),
    messageBytes,
  ]);
}

/** Protobuf status uses base-128 varint framing for string lengths. */
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
