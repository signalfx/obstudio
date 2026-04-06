#!/usr/bin/env bun
// Continuous load generator — sends realistic telemetry to a running observer-ts instance.
// Usage: bun test/load/continuous-load.ts [minutes] [transport]
//   minutes:   how long to run (default: 5)
//   transport:  json | proto | grpc | mixed (default: mixed)

import * as grpc from "@grpc/grpc-js";
import * as protoLoader from "@grpc/proto-loader";
import { join } from "node:path";
import { encodeTracesProtobuf, encodeMetricsProtobuf, encodeLogsProtobuf, warmupProtos } from "../../src/otlp/proto.ts";

const OTLP_HTTP = "http://127.0.0.1:4318";
const OTLP_GRPC_ADDR = "127.0.0.1:4317";

const SERVICES = ["api-gateway", "user-service", "order-service", "payment-service", "notification-service"];
const ROUTES = ["GET /api/users", "POST /api/orders", "GET /api/products", "PUT /api/cart", "DELETE /api/sessions"];
const SEVERITIES = ["DEBUG", "INFO", "INFO", "INFO", "WARN", "ERROR"];

let traceCounter = 0;
let spanCounter = 0;
const pick = <T>(arr: T[]) => arr[Math.floor(Math.random() * arr.length)]!;

type ChildDef = { name: string; kind: number; attrs: Record<string, string> };
const CHILDREN: Record<string, ChildDef[]> = {
  "api-gateway": [
    { name: "GET /users", kind: 3, attrs: { "server.address": "user-service" } },
    { name: "POST /orders", kind: 3, attrs: { "server.address": "order-service" } },
  ],
  "user-service": [{ name: "SELECT users", kind: 3, attrs: { "db.system.name": "postgresql" } }],
  "order-service": [
    { name: "SELECT orders", kind: 3, attrs: { "db.system.name": "postgresql" } },
    { name: "POST /payments", kind: 3, attrs: { "server.address": "payment-service" } },
  ],
  "payment-service": [{ name: "GET cache:payment", kind: 3, attrs: { "db.system.name": "redis" } }],
  "notification-service": [{ name: "send notification", kind: 4, attrs: { "messaging.system": "kafka", "messaging.operation.type": "publish" } }],
};

function mkAttrs(obj: Record<string, string | number>) {
  return Object.entries(obj).map(([key, value]) =>
    typeof value === "string"
      ? { key, value: { stringValue: value } }
      : { key, value: { intValue: value } }
  );
}

function generateTraces(count: number) {
  const byService = new Map<string, any[]>();
  for (let i = 0; i < count; i++) {
    const svc = pick(SERVICES);
    const traceId = (++traceCounter).toString(16).padStart(32, "0");
    const rootId = (++spanCounter).toString(16).padStart(16, "0");
    const route = pick(ROUTES);
    const isError = Math.random() < 0.05;
    const now = Date.now() * 1_000_000;
    const dur = Math.floor(Math.random() * 200 + 10) * 1_000_000;

    if (!byService.has(svc)) byService.set(svc, []);
    byService.get(svc)!.push({
      traceId, spanId: rootId, name: route, kind: 2,
      startTimeUnixNano: now.toString(), endTimeUnixNano: (now + dur).toString(),
      status: { code: isError ? 2 : 1 },
      attributes: mkAttrs({ "http.request.method": route.split(" ")[0]!, "http.response.status_code": isError ? 500 : 200 }),
    });

    const child = pick(CHILDREN[svc] ?? []);
    if (child) {
      const childId = (++spanCounter).toString(16).padStart(16, "0");
      byService.get(svc)!.push({
        traceId, spanId: childId, parentSpanId: rootId,
        name: child.name, kind: child.kind,
        startTimeUnixNano: (now + 2_000_000).toString(), endTimeUnixNano: (now + dur - 2_000_000).toString(),
        status: { code: 1 }, attributes: mkAttrs(child.attrs),
      });
    }
  }
  const resourceSpans = [...byService].map(([svc, spans]) => ({
    resource: { attributes: mkAttrs({ "service.name": svc }) },
    scopeSpans: [{ scope: { name: "otel-auto" }, spans }],
  }));
  return { resourceSpans };
}

function generateMetrics(count: number) {
  const resourceMetrics = Array.from({ length: count }, () => {
    const svc = pick(SERVICES);
    return {
      resource: { attributes: mkAttrs({ "service.name": svc }) },
      scopeMetrics: [{
        scope: { name: "otel" },
        metrics: [
          {
            name: "http.server.request.duration", unit: "s",
            histogram: { dataPoints: [{ timeUnixNano: (Date.now() * 1_000_000).toString(), count: String(Math.floor(Math.random() * 100 + 1)), sum: Math.random() * 50, bucketCounts: ["10", "20", "30", "15", "5"], explicitBounds: [0.005, 0.01, 0.025, 0.05] }], aggregationTemporality: 2 },
          },
          {
            name: "process.cpu.utilization", unit: "1",
            gauge: { dataPoints: [{ timeUnixNano: (Date.now() * 1_000_000).toString(), asDouble: Math.random() }] },
          },
        ],
      }],
    };
  });
  return { resourceMetrics };
}

function generateLogs(count: number) {
  const byService = new Map<string, any[]>();
  for (let i = 0; i < count; i++) {
    const svc = pick(SERVICES);
    const sev = pick(SEVERITIES);
    const sevNum = sev === "DEBUG" ? 5 : sev === "INFO" ? 9 : sev === "WARN" ? 13 : 17;
    if (!byService.has(svc)) byService.set(svc, []);
    byService.get(svc)!.push({
      timeUnixNano: (Date.now() * 1_000_000).toString(), severityNumber: sevNum, severityText: sev,
      body: { stringValue: `[${svc}] ${pick(ROUTES)} - ${sev.toLowerCase()} message ${i}` },
    });
  }
  const resourceLogs = [...byService].map(([svc, logRecords]) => ({
    resource: { attributes: mkAttrs({ "service.name": svc }) },
    scopeLogs: [{ scope: { name: "pino" }, logRecords }],
  }));
  return { resourceLogs };
}

// --- Senders ---

async function sendJson(path: string, body: unknown): Promise<boolean> {
  try {
    const r = await fetch(`${OTLP_HTTP}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    return r.status === 200;
  } catch { return false; }
}

async function sendProto(path: string, body: unknown, signal: "traces" | "metrics" | "logs"): Promise<boolean> {
  try {
    const enc = signal === "traces" ? await encodeTracesProtobuf(body) : signal === "metrics" ? await encodeMetricsProtobuf(body) : await encodeLogsProtobuf(body);
    const r = await fetch(`${OTLP_HTTP}${path}`, { method: "POST", headers: { "Content-Type": "application/x-protobuf" }, body: enc });
    return r.status === 200;
  } catch { return false; }
}

let gTraces: any, gMetrics: any, gLogs: any;
async function initGrpc() {
  const PROTOS_DIR = join(import.meta.dir, "../../src/otlp/protos");
  const pd = await protoLoader.load(
    ["trace", "metrics", "logs"].map(s => join(PROTOS_DIR, `opentelemetry/proto/collector/${s}/v1/${s}_service.proto`)),
    { keepCase: false, longs: String, bytes: String, defaults: false, oneofs: true, includeDirs: [PROTOS_DIR] },
  );
  const p = grpc.loadPackageDefinition(pd) as any;
  const c = grpc.credentials.createInsecure();
  gTraces = new p.opentelemetry.proto.collector.trace.v1.TraceService(OTLP_GRPC_ADDR, c);
  gMetrics = new p.opentelemetry.proto.collector.metrics.v1.MetricsService(OTLP_GRPC_ADDR, c);
  gLogs = new p.opentelemetry.proto.collector.logs.v1.LogsService(OTLP_GRPC_ADDR, c);
}

function sendGrpc(client: any, req: unknown): Promise<boolean> {
  return new Promise(r => client.Export(req, (err: Error | null) => r(!err)));
}

// --- Main ---

const minutes = parseInt(process.argv[2] ?? "5", 10);
const transport = (process.argv[3] ?? "mixed") as "json" | "proto" | "grpc" | "mixed";
const durationMs = minutes * 60 * 1000;

console.log(`\nContinuous load generator`);
console.log(`  Duration:   ${minutes} minutes`);
console.log(`  Transport:  ${transport}`);
console.log(`  Target:     OTLP/HTTP ${OTLP_HTTP}, OTLP/gRPC ${OTLP_GRPC_ADDR}`);
console.log(`  Rate:       ~200 spans/s, ~50 metrics/s, ~30 logs/s (medium load)\n`);

await warmupProtos();
if (transport === "grpc" || transport === "mixed") {
  await initGrpc();
}

const BATCH_INTERVAL = 100; // ms
const TRACES_PER_BATCH = 10;   // ~200 spans/s (2 spans per trace, 10 batches/s)
const METRICS_PER_BATCH = 5;   // ~100 metric points/s
const LOGS_PER_BATCH = 3;      // ~30 logs/s

let totalSpans = 0, totalMetrics = 0, totalLogs = 0, errors = 0, batches = 0;
const startTime = Date.now();

// Cycle through transports in mixed mode
const transportCycle = transport === "mixed" ? ["json", "proto", "grpc"] as const : [transport] as const;
let tIdx = 0;

async function sendBatch() {
  const t = transportCycle[tIdx % transportCycle.length]!;
  tIdx++;

  const traces = generateTraces(TRACES_PER_BATCH);
  const metrics = generateMetrics(METRICS_PER_BATCH);
  const logs = generateLogs(LOGS_PER_BATCH);

  const promises: Promise<boolean>[] = [];

  if (t === "json") {
    promises.push(sendJson("/v1/traces", traces), sendJson("/v1/metrics", metrics), sendJson("/v1/logs", logs));
  } else if (t === "proto") {
    promises.push(sendProto("/v1/traces", traces, "traces"), sendProto("/v1/metrics", metrics, "metrics"), sendProto("/v1/logs", logs, "logs"));
  } else {
    promises.push(sendGrpc(gTraces, traces), sendGrpc(gMetrics, metrics), sendGrpc(gLogs, logs));
  }

  const results = await Promise.all(promises);
  errors += results.filter(r => !r).length;
  totalSpans += TRACES_PER_BATCH * 2;
  totalMetrics += METRICS_PER_BATCH * 2;
  totalLogs += LOGS_PER_BATCH;
  batches++;
}

// Progress reporting every 30s
const progressInterval = setInterval(() => {
  const elapsed = (Date.now() - startTime) / 1000;
  const remaining = Math.max(0, (durationMs - (Date.now() - startTime)) / 1000);
  console.log(
    `  [${new Date().toLocaleTimeString()}] ` +
    `${Math.floor(elapsed)}s elapsed, ${Math.floor(remaining)}s remaining | ` +
    `spans: ${totalSpans.toLocaleString()} (${(totalSpans / elapsed).toFixed(0)}/s), ` +
    `metrics: ${totalMetrics.toLocaleString()}, logs: ${totalLogs.toLocaleString()}, ` +
    `errors: ${errors}`
  );
}, 30_000);

// Main loop
while (Date.now() - startTime < durationMs) {
  const batchStart = Date.now();
  await sendBatch();
  const sleepMs = Math.max(0, BATCH_INTERVAL - (Date.now() - batchStart));
  if (sleepMs > 0) await new Promise(r => setTimeout(r, sleepMs));
}

clearInterval(progressInterval);

const elapsed = (Date.now() - startTime) / 1000;
console.log(`\n  Done! ${elapsed.toFixed(1)}s total`);
console.log(`  Spans:   ${totalSpans.toLocaleString()} (${(totalSpans / elapsed).toFixed(0)}/s)`);
console.log(`  Metrics: ${totalMetrics.toLocaleString()} (${(totalMetrics / elapsed).toFixed(0)}/s)`);
console.log(`  Logs:    ${totalLogs.toLocaleString()} (${(totalLogs / elapsed).toFixed(0)}/s)`);
console.log(`  Errors:  ${errors}`);
console.log(`  Batches: ${batches}\n`);

// Cleanup gRPC
gTraces?.close(); gMetrics?.close(); gLogs?.close();
process.exit(0);
