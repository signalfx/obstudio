// OTLP protobuf decoding using a pre-built JSON descriptor from opentelemetry-proto v1.5.0.
//
// The JSON descriptor is generated from vendored .proto files at build time and
// imported as a static module — this means it gets bundled into `bun build --compile`
// binaries without needing filesystem access at runtime.

import protobuf from "protobufjs";
import descriptorJson from "./otlp-descriptors.json";

// Load the proto root synchronously from the embedded JSON descriptor.
const root = protobuf.Root.fromJSON(descriptorJson as protobuf.INamespace);

const TraceRequest = root.lookupType("opentelemetry.proto.collector.trace.v1.ExportTraceServiceRequest");
const MetricsRequest = root.lookupType("opentelemetry.proto.collector.metrics.v1.ExportMetricsServiceRequest");
const LogsRequest = root.lookupType("opentelemetry.proto.collector.logs.v1.ExportLogsServiceRequest");

// toObject options: convert Long → string, bytes → base64 string.
const TO_OBJECT_OPTS: protobuf.IConversionOptions = { longs: String, bytes: String, defaults: false };

export async function decodeTracesProtobuf(buf: Uint8Array): Promise<unknown> {
  const msg = TraceRequest.decode(buf);
  return TraceRequest.toObject(msg, TO_OBJECT_OPTS);
}

export async function decodeMetricsProtobuf(buf: Uint8Array): Promise<unknown> {
  const msg = MetricsRequest.decode(buf);
  return MetricsRequest.toObject(msg, TO_OBJECT_OPTS);
}

export async function decodeLogsProtobuf(buf: Uint8Array): Promise<unknown> {
  const msg = LogsRequest.decode(buf);
  return LogsRequest.toObject(msg, TO_OBJECT_OPTS);
}

/**
 * Eagerly load proto definitions. With the JSON descriptor approach, loading
 * is synchronous at module import time, so this is a no-op retained for
 * backward compatibility.
 */
export async function warmupProtos(): Promise<void> {
  // No-op — types are loaded synchronously at import time.
}

/**
 * Encode helpers — used by gRPC receiver to build response messages and by tests.
 */
export async function encodeTracesProtobuf(obj: unknown): Promise<Uint8Array> {
  const msg = TraceRequest.fromObject(obj as Record<string, unknown>);
  return TraceRequest.encode(msg).finish();
}

export async function encodeMetricsProtobuf(obj: unknown): Promise<Uint8Array> {
  const msg = MetricsRequest.fromObject(obj as Record<string, unknown>);
  return MetricsRequest.encode(msg).finish();
}

export async function encodeLogsProtobuf(obj: unknown): Promise<Uint8Array> {
  const msg = LogsRequest.fromObject(obj as Record<string, unknown>);
  return LogsRequest.encode(msg).finish();
}
