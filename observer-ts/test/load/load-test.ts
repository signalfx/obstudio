#!/usr/bin/env bun
// Load test simulating realistic local development traffic.
//
// Tests three transport modes:
//   1. OTLP/HTTP with JSON   (Content-Type: application/json)
//   2. OTLP/HTTP with proto  (Content-Type: application/x-protobuf)
//   3. OTLP/gRPC             (port 4317)
//
// A typical local dev setup with 3-5 microservices instrumented with OTel
// generates roughly:
//   - 50-200 spans/sec (HTTP requests, DB queries, cache hits)
//   - 20-50 metric datapoints/sec (histograms, counters, gauges)
//   - 10-30 log records/sec
//   - 5-15 concurrent WebSocket clients (browser tabs, IDE panels)
//
// We'll test at 3 levels per transport:
//   Light:  100 spans/sec, 30 metrics/sec, 20 logs/sec, 2 WS clients
//   Medium: 500 spans/sec, 100 metrics/sec, 50 logs/sec, 5 WS clients
//   Heavy:  2000 spans/sec, 300 metrics/sec, 200 logs/sec, 10 WS clients

import * as grpc from "@grpc/grpc-js";
import * as protoLoader from "@grpc/proto-loader";
import { join } from "node:path";
import { encodeTracesProtobuf, encodeMetricsProtobuf, encodeLogsProtobuf, warmupProtos } from "../../src/otlp/proto.ts";

const OTLP_HTTP_PORT = 4319;
const OTLP_GRPC_PORT = 4320;
const WEB_PORT = 3001;

const OTLP_BASE = `http://127.0.0.1:${OTLP_HTTP_PORT}`;
const WEB_BASE = `http://127.0.0.1:${WEB_PORT}`;

const SERVICES = ["api-gateway", "user-service", "order-service", "payment-service", "notification-service"];
const ROUTES = ["GET /api/users", "POST /api/orders", "GET /api/products", "PUT /api/cart", "DELETE /api/sessions"];
const SEVERITIES = ["DEBUG", "INFO", "INFO", "INFO", "WARN", "ERROR"];

let traceCounter = 0;
let spanCounter = 0;

function randomService() { return SERVICES[Math.floor(Math.random() * SERVICES.length)]!; }
function randomRoute() { return ROUTES[Math.floor(Math.random() * ROUTES.length)]!; }
function randomSeverity() { return SEVERITIES[Math.floor(Math.random() * SEVERITIES.length)]!; }

type ChildSpanDef = {
  name: string;
  kind: number;
  attributes: Array<{ key: string; value: { stringValue: string } }>;
};

const SERVICE_CHILDREN: Record<string, ChildSpanDef[]> = {
  "api-gateway": [
    { name: "GET /users", kind: 3, attributes: [{ key: "server.address", value: { stringValue: "user-service" } }] },
    { name: "POST /orders", kind: 3, attributes: [{ key: "server.address", value: { stringValue: "order-service" } }] },
  ],
  "user-service": [
    { name: "SELECT users", kind: 3, attributes: [{ key: "db.system.name", value: { stringValue: "postgresql" } }] },
  ],
  "order-service": [
    { name: "SELECT orders", kind: 3, attributes: [{ key: "db.system.name", value: { stringValue: "postgresql" } }] },
    { name: "POST /payments", kind: 3, attributes: [{ key: "server.address", value: { stringValue: "payment-service" } }] },
  ],
  "payment-service": [
    { name: "GET cache:payment", kind: 3, attributes: [{ key: "db.system.name", value: { stringValue: "redis" } }] },
  ],
  "notification-service": [
    { name: "send notification", kind: 4, attributes: [{ key: "messaging.system", value: { stringValue: "kafka" } }, { key: "messaging.operation.type", value: { stringValue: "publish" } }] },
  ],
};

function generateTraceBatch(count: number) {
  const resourceSpans: any[] = [];
  const byService = new Map<string, any[]>();

  for (let i = 0; i < count; i++) {
    const svc = randomService();
    const traceId = (++traceCounter).toString(16).padStart(32, "0");
    const rootSpanId = (++spanCounter).toString(16).padStart(16, "0");
    const route = randomRoute();
    const isError = Math.random() < 0.05;
    const now = Date.now() * 1_000_000;
    const duration = Math.floor(Math.random() * 200 + 10) * 1_000_000;

    if (!byService.has(svc)) byService.set(svc, []);

    byService.get(svc)!.push({
      traceId, spanId: rootSpanId, name: route, kind: 2,
      startTimeUnixNano: now.toString(),
      endTimeUnixNano: (now + duration).toString(),
      status: { code: isError ? 2 : 1 },
      attributes: [
        { key: "http.request.method", value: { stringValue: route.split(" ")[0] } },
        { key: "http.response.status_code", value: { intValue: isError ? 500 : 200 } },
      ],
    });

    const children = SERVICE_CHILDREN[svc] ?? [];
    const child = children[Math.floor(Math.random() * children.length)];
    if (child) {
      const childSpanId = (++spanCounter).toString(16).padStart(16, "0");
      byService.get(svc)!.push({
        traceId, spanId: childSpanId, parentSpanId: rootSpanId,
        name: child.name, kind: child.kind,
        startTimeUnixNano: (now + 2_000_000).toString(),
        endTimeUnixNano: (now + duration - 2_000_000).toString(),
        status: { code: 1 },
        attributes: child.attributes,
      });
    }
  }

  for (const [svc, spans] of byService) {
    resourceSpans.push({
      resource: { attributes: [{ key: "service.name", value: { stringValue: svc } }] },
      scopeSpans: [{ scope: { name: "otel-auto" }, spans }],
    });
  }
  return { resourceSpans };
}

function generateMetricBatch(count: number) {
  const resourceMetrics: any[] = [];
  for (let i = 0; i < count; i++) {
    const svc = randomService();
    resourceMetrics.push({
      resource: { attributes: [{ key: "service.name", value: { stringValue: svc } }] },
      scopeMetrics: [{
        scope: { name: "otel" },
        metrics: [
          {
            name: "http.server.request.duration", unit: "s",
            histogram: {
              dataPoints: [{
                timeUnixNano: (Date.now() * 1_000_000).toString(),
                count: String(Math.floor(Math.random() * 100 + 1)),
                sum: Math.random() * 50,
                bucketCounts: ["10", "20", "30", "15", "5"],
                explicitBounds: [0.005, 0.01, 0.025, 0.05],
              }],
              aggregationTemporality: 2,
            },
          },
          {
            name: "process.cpu.utilization", unit: "1",
            gauge: { dataPoints: [{ timeUnixNano: (Date.now() * 1_000_000).toString(), asDouble: Math.random() }] },
          },
        ],
      }],
    });
  }
  return { resourceMetrics };
}

function generateLogBatch(count: number) {
  const resourceLogs: any[] = [];
  const byService = new Map<string, any[]>();

  for (let i = 0; i < count; i++) {
    const svc = randomService();
    const sev = randomSeverity();
    const sevNum = sev === "DEBUG" ? 5 : sev === "INFO" ? 9 : sev === "WARN" ? 13 : 17;
    if (!byService.has(svc)) byService.set(svc, []);
    byService.get(svc)!.push({
      timeUnixNano: (Date.now() * 1_000_000).toString(),
      severityNumber: sevNum,
      severityText: sev,
      body: { stringValue: `[${svc}] ${randomRoute()} - ${sev.toLowerCase()} message ${i}` },
    });
  }

  for (const [svc, logRecords] of byService) {
    resourceLogs.push({
      resource: { attributes: [{ key: "service.name", value: { stringValue: svc } }] },
      scopeLogs: [{ scope: { name: "pino" }, logRecords }],
    });
  }
  return { resourceLogs };
}

// --- Transport senders ---

type Transport = "json" | "proto" | "grpc";

async function sendOtlpJson(path: string, body: unknown): Promise<boolean> {
  try {
    const resp = await fetch(`${OTLP_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return resp.status === 200;
  } catch {
    return false;
  }
}

async function sendOtlpProto(path: string, body: unknown, signal: "traces" | "metrics" | "logs"): Promise<boolean> {
  try {
    let encoded: Uint8Array;
    switch (signal) {
      case "traces": encoded = await encodeTracesProtobuf(body); break;
      case "metrics": encoded = await encodeMetricsProtobuf(body); break;
      case "logs": encoded = await encodeLogsProtobuf(body); break;
    }
    const resp = await fetch(`${OTLP_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/x-protobuf" },
      body: encoded,
    });
    return resp.status === 200;
  } catch {
    return false;
  }
}

// gRPC clients (lazy init)
let grpcTraceClient: any = null;
let grpcMetricsClient: any = null;
let grpcLogsClient: any = null;

async function initGrpcClients() {
  const PROTOS_DIR = join(import.meta.dir, "../../src/otlp/protos");
  const packageDefinition = await protoLoader.load(
    [
      join(PROTOS_DIR, "opentelemetry/proto/collector/trace/v1/trace_service.proto"),
      join(PROTOS_DIR, "opentelemetry/proto/collector/metrics/v1/metrics_service.proto"),
      join(PROTOS_DIR, "opentelemetry/proto/collector/logs/v1/logs_service.proto"),
    ],
    { keepCase: false, longs: String, bytes: String, defaults: false, oneofs: true, includeDirs: [PROTOS_DIR] },
  );
  const proto = grpc.loadPackageDefinition(packageDefinition) as any;
  const creds = grpc.credentials.createInsecure();
  grpcTraceClient = new proto.opentelemetry.proto.collector.trace.v1.TraceService(`127.0.0.1:${OTLP_GRPC_PORT}`, creds);
  grpcMetricsClient = new proto.opentelemetry.proto.collector.metrics.v1.MetricsService(`127.0.0.1:${OTLP_GRPC_PORT}`, creds);
  grpcLogsClient = new proto.opentelemetry.proto.collector.logs.v1.LogsService(`127.0.0.1:${OTLP_GRPC_PORT}`, creds);
}

function closeGrpcClients() {
  grpcTraceClient?.close();
  grpcMetricsClient?.close();
  grpcLogsClient?.close();
}

function sendGrpcExport(client: any, request: unknown): Promise<boolean> {
  return new Promise((resolve) => {
    client.Export(request, (err: Error | null) => {
      resolve(!err);
    });
  });
}

// Generic sender that dispatches to the right transport
async function sendOtlp(transport: Transport, path: string, body: unknown, signal: "traces" | "metrics" | "logs"): Promise<boolean> {
  switch (transport) {
    case "json":
      return sendOtlpJson(path, body);
    case "proto":
      return sendOtlpProto(path, body, signal);
    case "grpc":
      switch (signal) {
        case "traces": return sendGrpcExport(grpcTraceClient, body);
        case "metrics": return sendGrpcExport(grpcMetricsClient, body);
        case "logs": return sendGrpcExport(grpcLogsClient, body);
      }
  }
}

async function queryRest(path: string): Promise<{ ok: boolean; ms: number }> {
  const start = performance.now();
  try {
    const resp = await fetch(`${WEB_BASE}${path}`);
    await resp.text();
    return { ok: resp.status === 200, ms: performance.now() - start };
  } catch {
    return { ok: false, ms: performance.now() - start };
  }
}

function connectWebSocket(): Promise<WebSocket> {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(`ws://127.0.0.1:${WEB_PORT}/api/ws`);
    ws.onopen = () => resolve(ws);
    ws.onerror = (e) => reject(e);
  });
}

interface LoadProfile {
  name: string;
  transport: Transport;
  spansPerSec: number;
  metricsPerSec: number;
  logsPerSec: number;
  wsClients: number;
  durationSec: number;
}

async function runLoadTest(profile: LoadProfile) {
  const transportLabel = profile.transport === "json" ? "HTTP/JSON" : profile.transport === "proto" ? "HTTP/Proto" : "gRPC";
  console.log(`\n${"=".repeat(60)}`);
  console.log(`  ${profile.name}  [${transportLabel}]`);
  console.log(`  ${profile.spansPerSec} spans/s, ${profile.metricsPerSec} metrics/s, ${profile.logsPerSec} logs/s`);
  console.log(`  ${profile.wsClients} WebSocket clients, ${profile.durationSec}s duration`);
  console.log(`${"=".repeat(60)}`);

  // Clear store
  await fetch(`${WEB_BASE}/api/data`, { method: "DELETE" });

  // Reset counters
  traceCounter = 0;
  spanCounter = 0;

  // Connect WebSocket clients
  const wsClients: WebSocket[] = [];
  const wsMessages: number[] = new Array(profile.wsClients).fill(0);
  for (let i = 0; i < profile.wsClients; i++) {
    try {
      const ws = await connectWebSocket();
      ws.onmessage = () => { wsMessages[i]!++; };
      ws.send(JSON.stringify({
        type: "subscribe",
        signals: { traces: { limit: 50 }, metrics: { limit: 50 }, logs: { limit: 100 }, stats: {}, "service-map": {} },
      }));
      wsClients.push(ws);
    } catch {
      console.log(`  Warning: Failed to connect WS client ${i}`);
    }
  }

  const batchesPerSec = 10;
  const spanBatchSize = Math.ceil(profile.spansPerSec / batchesPerSec);
  const metricBatchSize = Math.ceil(profile.metricsPerSec / batchesPerSec);
  const logBatchSize = Math.ceil(profile.logsPerSec / batchesPerSec);

  let totalSpansSent = 0;
  let totalMetricsSent = 0;
  let totalLogsSent = 0;
  let otlpErrors = 0;
  const latencies: number[] = [];

  const startTime = performance.now();
  const endTime = startTime + profile.durationSec * 1000;
  let batchesSent = 0;

  while (performance.now() < endTime) {
    const batchStart = performance.now();

    const promises: Promise<boolean>[] = [];
    if (spanBatchSize > 0) {
      const batch = generateTraceBatch(spanBatchSize);
      promises.push(sendOtlp(profile.transport, "/v1/traces", batch, "traces"));
      totalSpansSent += spanBatchSize * 2;
    }
    if (metricBatchSize > 0) {
      const batch = generateMetricBatch(metricBatchSize);
      promises.push(sendOtlp(profile.transport, "/v1/metrics", batch, "metrics"));
      totalMetricsSent += metricBatchSize * 2;
    }
    if (logBatchSize > 0) {
      const batch = generateLogBatch(logBatchSize);
      promises.push(sendOtlp(profile.transport, "/v1/logs", batch, "logs"));
      totalLogsSent += logBatchSize;
    }

    promises.push(queryRest("/api/query/stats").then((r) => { latencies.push(r.ms); return r.ok; }));

    const results = await Promise.all(promises);
    otlpErrors += results.filter((r) => !r).length;
    batchesSent++;

    const elapsed = performance.now() - batchStart;
    const sleepMs = Math.max(0, 100 - elapsed);
    if (sleepMs > 0) await new Promise((r) => setTimeout(r, sleepMs));
  }

  const totalTime = (performance.now() - startTime) / 1000;

  // Final queries
  const queryTests = [
    { path: "/api/query/stats", label: "stats" },
    { path: "/api/query/traces", label: "traces" },
    { path: "/api/query/metrics", label: "metrics" },
    { path: "/api/query/logs", label: "logs" },
    { path: "/api/query/service-map", label: "service-map" },
  ];
  const queryResults: { label: string; ms: number }[] = [];
  for (const q of queryTests) {
    const r = await queryRest(q.path);
    queryResults.push({ label: q.label, ms: r.ms });
  }

  const statsResp = await fetch(`${WEB_BASE}/api/query/stats`);
  const finalStats = await statsResp.json() as any;

  const totalWsMessages = wsMessages.reduce((a, b) => a + b, 0);
  wsClients.forEach((ws) => ws.close());

  // Report
  console.log(`\n  Results (${totalTime.toFixed(1)}s):`);
  console.log(`  ─────────────────────────────────────────`);
  console.log(`  Ingestion [${transportLabel}]:`);
  console.log(`    Spans sent:    ${totalSpansSent.toLocaleString()} (${(totalSpansSent / totalTime).toFixed(0)}/s)`);
  console.log(`    Metrics sent:  ${totalMetricsSent.toLocaleString()} (${(totalMetricsSent / totalTime).toFixed(0)}/s)`);
  console.log(`    Logs sent:     ${totalLogsSent.toLocaleString()} (${(totalLogsSent / totalTime).toFixed(0)}/s)`);
  console.log(`    OTLP errors:   ${otlpErrors}`);
  console.log(`    Batches:       ${batchesSent}`);
  console.log(`  Store:`);
  console.log(`    Spans:         ${finalStats.spanCount?.toLocaleString()}`);
  console.log(`    Metrics:       ${finalStats.metricCount?.toLocaleString()}`);
  console.log(`    Logs:          ${finalStats.logCount?.toLocaleString()}`);
  console.log(`    Traces:        ${finalStats.traceCount?.toLocaleString()}`);
  console.log(`    Services:      ${finalStats.serviceNames?.join(", ")}`);
  console.log(`  REST latency under load (stats endpoint):`);
  latencies.sort((a, b) => a - b);
  if (latencies.length > 0) {
    console.log(`    p50:  ${latencies[Math.floor(latencies.length * 0.5)]?.toFixed(1)}ms`);
    console.log(`    p95:  ${latencies[Math.floor(latencies.length * 0.95)]?.toFixed(1)}ms`);
    console.log(`    p99:  ${latencies[Math.floor(latencies.length * 0.99)]?.toFixed(1)}ms`);
    console.log(`    max:  ${latencies[latencies.length - 1]?.toFixed(1)}ms`);
  }
  console.log(`  Query response with full store:`);
  for (const q of queryResults) {
    console.log(`    ${q.label.padEnd(14)} ${q.ms.toFixed(1)}ms`);
  }
  console.log(`  WebSocket:`);
  console.log(`    Clients:       ${wsClients.length}`);
  console.log(`    Total msgs:    ${totalWsMessages.toLocaleString()}`);
  console.log(`    Avg msgs/client: ${wsClients.length > 0 ? (totalWsMessages / wsClients.length).toFixed(0) : 0}`);

  return { otlpErrors, latencies, finalStats };
}

// --- Main ---

console.log("╔══════════════════════════════════════════════════════════╗");
console.log("║  Observability Studio — Load Test                       ║");
console.log("║  Testing HTTP/JSON, HTTP/Proto, and gRPC transports     ║");
console.log("╚══════════════════════════════════════════════════════════╝");

// Start servers
import { Store } from "../../src/store/store.ts";
import { startOtlpHttpReceiver } from "../../src/otlp/http-receiver.ts";
import { startOtlpGrpcReceiver } from "../../src/otlp/grpc-receiver.ts";
import { startWebServer } from "../../src/web/server.ts";

const store = new Store({ sessionGap: 0 });

console.log("\nStarting servers...");
await warmupProtos();
const otlpReceiver = startOtlpHttpReceiver(store, "127.0.0.1", OTLP_HTTP_PORT);
const grpcReceiver = await startOtlpGrpcReceiver(store, "127.0.0.1", OTLP_GRPC_PORT);
const webServer = startWebServer(store, "127.0.0.1", WEB_PORT);
await initGrpcClients();
console.log(`  OTLP/HTTP: http://127.0.0.1:${OTLP_HTTP_PORT}`);
console.log(`  OTLP/gRPC: 127.0.0.1:${OTLP_GRPC_PORT}`);
console.log(`  Web:       http://127.0.0.1:${WEB_PORT}`);

// Select which transport to run based on CLI args
const mode = process.argv[2] ?? "all";
type TransportConfig = { transport: Transport; label: string };
let transports: TransportConfig[];

if (mode === "json") {
  transports = [{ transport: "json", label: "HTTP/JSON" }];
} else if (mode === "proto") {
  transports = [{ transport: "proto", label: "HTTP/Proto" }];
} else if (mode === "grpc") {
  transports = [{ transport: "grpc", label: "gRPC" }];
} else {
  transports = [
    { transport: "json", label: "HTTP/JSON" },
    { transport: "proto", label: "HTTP/Proto" },
    { transport: "grpc", label: "gRPC" },
  ];
}

const profiles = [
  { name: "Light  - Single service", spansPerSec: 50, metricsPerSec: 15, logsPerSec: 10, wsClients: 2, durationSec: 10 },
  { name: "Medium - 3-5 microservices", spansPerSec: 250, metricsPerSec: 50, logsPerSec: 30, wsClients: 5, durationSec: 10 },
  { name: "Heavy  - Full stack load test", spansPerSec: 1000, metricsPerSec: 150, logsPerSec: 100, wsClients: 10, durationSec: 10 },
];

for (const t of transports) {
  console.log(`\n\n${"#".repeat(60)}`);
  console.log(`  TRANSPORT: ${t.label}`);
  console.log(`${"#".repeat(60)}`);

  for (const p of profiles) {
    await runLoadTest({ ...p, transport: t.transport });
  }
}

// Cleanup
console.log("\nShutting down...");
closeGrpcClients();
otlpReceiver.stop();
grpcReceiver.stop();
webServer.stop();

console.log("\nLoad test complete.\n");
process.exit(0);
