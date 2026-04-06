import { test, expect, describe, beforeAll, afterAll, beforeEach } from "bun:test";
import { Store } from "../../src/store/store.ts";
import { startOtlpHttpReceiver } from "../../src/otlp/http-receiver.ts";
import { startWebServer } from "../../src/web/server.ts";
import { encodeTracesProtobuf, encodeMetricsProtobuf, encodeLogsProtobuf } from "../../src/otlp/proto.ts";

const OTLP_PORT = 34319;
const WEB_PORT = 33000;
const OTLP_BASE = `http://127.0.0.1:${OTLP_PORT}`;
const WEB_BASE = `http://127.0.0.1:${WEB_PORT}`;

// Single server instance to avoid Bun.serve port reuse issues.
const store = new Store({ sessionGap: 0 });
let otlpReceiver: { stop: () => void };
let webServer: { stop: () => void };

describe("E2E: OTLP ingest → store → REST query", () => {
  beforeAll(() => {
    otlpReceiver = startOtlpHttpReceiver(store, "127.0.0.1", OTLP_PORT);
    const ws = startWebServer(store, "127.0.0.1", WEB_PORT);
    webServer = ws;
  });

  afterAll(() => {
    otlpReceiver.stop();
    webServer.stop();
  });

  beforeEach(() => {
    store.clear();
  });

  test("full flow: ingest traces via OTLP, query via REST", async () => {
    // 1. Ingest traces via OTLP/HTTP.
    const otlpResp = await fetch(`${OTLP_BASE}/v1/traces`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resourceSpans: [{
          resource: { attributes: [{ key: "service.name", value: { stringValue: "e2e-svc" } }] },
          scopeSpans: [{
            scope: { name: "e2e" },
            spans: [{
              traceId: "e2e0000000000000e2e0000000000001",
              spanId: "e2e000000001",
              name: "GET /health",
              kind: 2,
              startTimeUnixNano: "1700000000000000000",
              endTimeUnixNano: "1700000000050000000",
              status: { code: 1 },
              attributes: [{ key: "http.request.method", value: { stringValue: "GET" } }],
            }],
          }],
        }],
      }),
    });
    expect(otlpResp.status).toBe(200);

    // 2. Query traces via REST.
    const tracesResp = await fetch(`${WEB_BASE}/api/query/traces`);
    expect(tracesResp.status).toBe(200);
    const traces = await tracesResp.json() as any;
    expect(traces.length).toBe(1);
    expect(traces[0].rootSpanName).toBe("GET /health");
    expect(traces[0].serviceName).toBe("e2e-svc");

    // 3. Query stats.
    const statsResp = await fetch(`${WEB_BASE}/api/query/stats`);
    const statsData = await statsResp.json() as any;
    expect(statsData.spanCount).toBe(1);
    expect(statsData.traceCount).toBe(1);
    expect(statsData.serviceNames).toContain("e2e-svc");

    // 4. Query trace detail.
    const detailResp = await fetch(`${WEB_BASE}/api/query/traces/e2e0000000000000e2e0000000000001`);
    expect(detailResp.status).toBe(200);
    const detail = await detailResp.json() as any;
    expect(detail.spans.length).toBe(1);
    expect(detail.spans[0].attributes["http.request.method"]).toBe("GET");
  });

  test("full flow: ingest metrics via OTLP, query via REST", async () => {
    await fetch(`${OTLP_BASE}/v1/metrics`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resourceMetrics: [{
          resource: { attributes: [{ key: "service.name", value: { stringValue: "e2e-svc" } }] },
          scopeMetrics: [{
            scope: { name: "e2e" },
            metrics: [{
              name: "http.server.request.duration",
              unit: "s",
              histogram: {
                dataPoints: [{
                  timeUnixNano: "1700000000000000000",
                  count: "10",
                  sum: 2.5,
                  bucketCounts: ["3", "5", "2"],
                  explicitBounds: [0.01, 0.1],
                }],
                aggregationTemporality: 2,
              },
            }],
          }],
        }],
      }),
    });

    const resp = await fetch(`${WEB_BASE}/api/query/metrics`);
    const metrics = await resp.json() as any;
    expect(metrics.length).toBe(1);
    expect(metrics[0].name).toBe("http.server.request.duration");
    expect(metrics[0].type).toBe("histogram");
  });

  test("full flow: ingest logs via OTLP, query via REST", async () => {
    await fetch(`${OTLP_BASE}/v1/logs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resourceLogs: [{
          resource: { attributes: [{ key: "service.name", value: { stringValue: "e2e-svc" } }] },
          scopeLogs: [{
            scope: { name: "e2e" },
            logRecords: [{
              timeUnixNano: "1700000000000000000",
              severityNumber: 17,
              severityText: "ERROR",
              body: { stringValue: "Something went wrong" },
              attributes: [{ key: "error.type", value: { stringValue: "RuntimeException" } }],
            }],
          }],
        }],
      }),
    });

    const resp = await fetch(`${WEB_BASE}/api/query/logs`);
    const logs = await resp.json() as any;
    expect(logs.length).toBe(1);
    expect(logs[0].body).toBe("Something went wrong");
    expect(logs[0].severityText).toBe("ERROR");
  });

  test("MCP endpoint works end-to-end", async () => {
    // Ingest some data first.
    await fetch(`${OTLP_BASE}/v1/traces`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resourceSpans: [{
          resource: { attributes: [{ key: "service.name", value: { stringValue: "mcp-test" } }] },
          scopeSpans: [{
            spans: [{
              traceId: "mcp0000000000000mcp0000000000001",
              spanId: "mcp000000001",
              name: "mcp-span",
              startTimeUnixNano: "0",
              endTimeUnixNano: "0",
            }],
          }],
        }],
      }),
    });

    // Initialize MCP.
    const initResp = await fetch(`${WEB_BASE}/mcp`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: 1, jsonrpc: "2.0", method: "initialize", params: { protocolVersion: "2024-11-05" } }),
    });
    expect(initResp.status).toBe(200);
    expect(initResp.headers.get("Mcp-Session-Id")).toBeTruthy();

    // List tools.
    const toolsResp = await fetch(`${WEB_BASE}/mcp`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: 2, jsonrpc: "2.0", method: "tools/list" }),
    });
    const toolsBody = await toolsResp.json() as any;
    expect(toolsBody.result.tools.length).toBe(5);

    // Call traces overview.
    const callResp = await fetch(`${WEB_BASE}/mcp`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: 3, jsonrpc: "2.0", method: "tools/call", params: { name: "observer_traces_overview", arguments: {} } }),
    });
    const callBody = await callResp.json() as any;
    const data = JSON.parse(callBody.result.content[0].text);
    expect(data.length).toBe(1);

    // Clear.
    await fetch(`${WEB_BASE}/mcp`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: 4, jsonrpc: "2.0", method: "tools/call", params: { name: "observer_clear", arguments: {} } }),
    });
    expect(store.getSpans().length).toBe(0);
  });

  test("DELETE /api/data clears store via REST", async () => {
    // Ingest data.
    await fetch(`${OTLP_BASE}/v1/traces`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resourceSpans: [{
          resource: { attributes: [] },
          scopeSpans: [{
            spans: [{
              traceId: "del0000000000000del0000000000001",
              spanId: "del000000001",
              name: "to-delete",
              startTimeUnixNano: "0",
              endTimeUnixNano: "0",
            }],
          }],
        }],
      }),
    });
    expect(store.getSpans().length).toBe(1);

    const resp = await fetch(`${WEB_BASE}/api/data`, { method: "DELETE" });
    expect(resp.status).toBe(200);
    expect(store.getSpans().length).toBe(0);
  });

  test("service-map endpoint works", async () => {
    await fetch(`${OTLP_BASE}/v1/traces`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resourceSpans: [{
          resource: { attributes: [{ key: "service.name", value: { stringValue: "frontend" } }] },
          scopeSpans: [{
            spans: [
              {
                traceId: "smap000000000000smap000000000001",
                spanId: "smap00000001",
                name: "GET /page",
                kind: 2,
                startTimeUnixNano: "0",
                endTimeUnixNano: "0",
                status: { code: 1 },
              },
              {
                traceId: "smap000000000000smap000000000001",
                spanId: "smap00000002",
                parentSpanId: "smap00000001",
                name: "db.query",
                kind: 3,
                startTimeUnixNano: "0",
                endTimeUnixNano: "0",
                attributes: [{ key: "db.system.name", value: { stringValue: "postgresql" } }],
              },
            ],
          }],
        }],
      }),
    });

    const resp = await fetch(`${WEB_BASE}/api/query/service-map`);
    const map = await resp.json() as any;
    expect(map.nodes.length).toBeGreaterThan(0);
  });
});

// Helper to encode and send protobuf
type EncodeFn = (obj: unknown) => Promise<Uint8Array>;

async function sendProtobuf(path: string, encodeFn: EncodeFn, obj: unknown): Promise<Response> {
  const body = await encodeFn(obj);
  return fetch(`${OTLP_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/x-protobuf" },
    body,
  });
}

describe("E2E Protobuf: OTLP ingest → store → REST query", () => {
  beforeEach(() => {
    store.clear();
  });

  test("full flow: ingest traces via protobuf, query via REST", async () => {
    const resp = await sendProtobuf("/v1/traces", encodeTracesProtobuf, {
      resourceSpans: [{
        resource: { attributes: [{ key: "service.name", value: { stringValue: "proto-e2e-svc" } }] },
        scopeSpans: [{
          scope: { name: "io.opentelemetry.spring-boot" },
          spans: [{
            traceId: Buffer.from("aabb000000000000aabb000000000001", "hex"),
            spanId: Buffer.from("aabb000000000001", "hex"),
            name: "GET /proto-health",
            kind: 2,
            startTimeUnixNano: 1700000000000000000n,
            endTimeUnixNano: 1700000000050000000n,
            status: { code: 1 },
            attributes: [
              { key: "http.request.method", value: { stringValue: "GET" } },
              { key: "http.response.status_code", value: { intValue: 200 } },
            ],
          }],
        }],
      }],
    });
    expect(resp.status).toBe(200);

    // Query traces via REST.
    const traces = await (await fetch(`${WEB_BASE}/api/query/traces`)).json() as any[];
    expect(traces.length).toBe(1);
    expect(traces[0].rootSpanName).toBe("GET /proto-health");
    expect(traces[0].serviceName).toBe("proto-e2e-svc");
    expect(traces[0].status).toBe("ok");

    // Query stats.
    const stats = await (await fetch(`${WEB_BASE}/api/query/stats`)).json() as any;
    expect(stats.spanCount).toBe(1);
    expect(stats.traceCount).toBe(1);
    expect(stats.serviceNames).toContain("proto-e2e-svc");

    // Query trace detail.
    const detail = await (await fetch(`${WEB_BASE}/api/query/traces/aabb000000000000aabb000000000001`)).json() as any;
    expect(detail.spans.length).toBe(1);
    expect(detail.spans[0].kind).toBe("SERVER");
    expect(detail.spans[0].attributes["http.request.method"]).toBe("GET");
    expect(detail.spans[0].attributes["http.response.status_code"]).toBe(200);
  });

  test("full flow: ingest metrics via protobuf, query via REST", async () => {
    const resp = await sendProtobuf("/v1/metrics", encodeMetricsProtobuf, {
      resourceMetrics: [{
        resource: { attributes: [{ key: "service.name", value: { stringValue: "proto-e2e-svc" } }] },
        scopeMetrics: [{
          scope: { name: "otel" },
          metrics: [{
            name: "http.server.request.duration",
            unit: "s",
            histogram: {
              dataPoints: [{
                timeUnixNano: 1700000000000000000n,
                count: 42,
                sum: 12.5,
                bucketCounts: [10, 15, 12, 5],
                explicitBounds: [0.005, 0.01, 0.025, 0.05],
              }],
              aggregationTemporality: 2,
            },
          }],
        }],
      }],
    });
    expect(resp.status).toBe(200);

    const metrics = await (await fetch(`${WEB_BASE}/api/query/metrics`)).json() as any[];
    expect(metrics.length).toBe(1);
    expect(metrics[0].name).toBe("http.server.request.duration");
    expect(metrics[0].type).toBe("histogram");
    expect(metrics[0].serviceName).toBe("proto-e2e-svc");
  });

  test("full flow: ingest logs via protobuf, query via REST", async () => {
    const resp = await sendProtobuf("/v1/logs", encodeLogsProtobuf, {
      resourceLogs: [{
        resource: { attributes: [{ key: "service.name", value: { stringValue: "proto-e2e-svc" } }] },
        scopeLogs: [{
          scope: { name: "logback" },
          logRecords: [{
            timeUnixNano: 1700000000000000000n,
            severityNumber: 17,
            severityText: "ERROR",
            body: { stringValue: "Protobuf error event" },
            traceId: Buffer.from("aabb000000000000aabb000000000001", "hex"),
            spanId: Buffer.from("aabb000000000001", "hex"),
            attributes: [{ key: "error.type", value: { stringValue: "NullPointerException" } }],
          }],
        }],
      }],
    });
    expect(resp.status).toBe(200);

    const logs = await (await fetch(`${WEB_BASE}/api/query/logs`)).json() as any[];
    expect(logs.length).toBe(1);
    expect(logs[0].body).toBe("Protobuf error event");
    expect(logs[0].severityText).toBe("ERROR");
    expect(logs[0].resource.serviceName).toBe("proto-e2e-svc");
    expect(logs[0].attributes["error.type"]).toBe("NullPointerException");
  });

  test("protobuf service-map works", async () => {
    // Send parent SERVER span and child CLIENT DB span via protobuf.
    await sendProtobuf("/v1/traces", encodeTracesProtobuf, {
      resourceSpans: [{
        resource: { attributes: [{ key: "service.name", value: { stringValue: "proto-frontend" } }] },
        scopeSpans: [{
          scope: { name: "otel" },
          spans: [
            {
              traceId: Buffer.from("ccdd000000000000ccdd000000000001", "hex"),
              spanId: Buffer.from("ccdd000000000001", "hex"),
              name: "GET /page",
              kind: 2,
              startTimeUnixNano: 1700000000000000000n,
              endTimeUnixNano: 1700000000100000000n,
              status: { code: 1 },
            },
            {
              traceId: Buffer.from("ccdd000000000000ccdd000000000001", "hex"),
              spanId: Buffer.from("ccdd000000000002", "hex"),
              parentSpanId: Buffer.from("ccdd000000000001", "hex"),
              name: "SELECT users",
              kind: 3,
              startTimeUnixNano: 1700000000010000000n,
              endTimeUnixNano: 1700000000090000000n,
              status: { code: 1 },
              attributes: [{ key: "db.system.name", value: { stringValue: "mysql" } }],
            },
          ],
        }],
      }],
    });

    const map = await (await fetch(`${WEB_BASE}/api/query/service-map`)).json() as any;
    expect(map.nodes.length).toBe(2);
    const frontend = map.nodes.find((n: any) => n.id === "proto-frontend");
    const mysql = map.nodes.find((n: any) => n.id === "mysql");
    expect(frontend).toBeTruthy();
    expect(mysql).toBeTruthy();
    expect(frontend.spanCount).toBe(2);
    expect(map.edges.length).toBe(1);
    expect(map.edges[0].source).toBe("proto-frontend");
    expect(map.edges[0].target).toBe("mysql");
  });

  test("mixed: JSON traces + protobuf metrics in same session", async () => {
    // Ingest traces via JSON.
    await fetch(`${OTLP_BASE}/v1/traces`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resourceSpans: [{
          resource: { attributes: [{ key: "service.name", value: { stringValue: "mixed-svc" } }] },
          scopeSpans: [{
            scope: { name: "otel" },
            spans: [{
              traceId: "eeff000000000000eeff000000000001",
              spanId: "eeff000000000001",
              name: "GET /mixed",
              kind: 2,
              startTimeUnixNano: "1700000000000000000",
              endTimeUnixNano: "1700000000050000000",
              status: { code: 1 },
            }],
          }],
        }],
      }),
    });

    // Ingest metrics via protobuf.
    await sendProtobuf("/v1/metrics", encodeMetricsProtobuf, {
      resourceMetrics: [{
        resource: { attributes: [{ key: "service.name", value: { stringValue: "mixed-svc" } }] },
        scopeMetrics: [{
          scope: { name: "otel" },
          metrics: [{
            name: "mixed.gauge",
            unit: "1",
            gauge: { dataPoints: [{ timeUnixNano: 1700000000000000000n, asDouble: 0.5 }] },
          }],
        }],
      }],
    });

    const stats = await (await fetch(`${WEB_BASE}/api/query/stats`)).json() as any;
    expect(stats.spanCount).toBe(1);
    expect(stats.metricCount).toBe(1);
    expect(stats.serviceNames).toEqual(["mixed-svc"]);
  });
});
