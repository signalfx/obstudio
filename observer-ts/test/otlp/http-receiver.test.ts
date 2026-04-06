import { test, expect, describe, beforeAll, afterAll } from "bun:test";
import { startOtlpHttpReceiver } from "../../src/otlp/http-receiver.ts";
import { Store } from "../../src/store/store.ts";
import { encodeTracesProtobuf, encodeMetricsProtobuf, encodeLogsProtobuf } from "../../src/otlp/proto.ts";

const TEST_PORT = 24318;
const BASE = `http://127.0.0.1:${TEST_PORT}`;

// Use a single server + store instance for all tests to avoid port reuse issues.
const store = new Store({ sessionGap: 0 });
let receiver: { stop: () => void };

describe("OTLP HTTP Receiver", () => {
  beforeAll(() => {
    receiver = startOtlpHttpReceiver(store, "127.0.0.1", TEST_PORT);
  });

  afterAll(() => {
    receiver.stop();
  });

  test("POST /v1/traces ingests spans", async () => {
    store.clear();
    const resp = await fetch(`${BASE}/v1/traces`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resourceSpans: [{
          resource: { attributes: [{ key: "service.name", value: { stringValue: "test-svc" } }] },
          scopeSpans: [{
            scope: { name: "test" },
            spans: [{
              traceId: "0af7651916cd43dd8448eb211c80319c",
              spanId: "b7ad6b7169203331",
              name: "GET /test",
              kind: 2,
              startTimeUnixNano: "1700000000000000000",
              endTimeUnixNano: "1700000000100000000",
              status: { code: 1 },
            }],
          }],
        }],
      }),
    });

    expect(resp.status).toBe(200);
    expect(store.getSpans().length).toBe(1);
    expect(store.getSpans()[0]!.name).toBe("GET /test");
    expect(store.getSpans()[0]!.resource.serviceName).toBe("test-svc");
  });

  test("POST /v1/metrics ingests metrics", async () => {
    store.clear();
    const resp = await fetch(`${BASE}/v1/metrics`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resourceMetrics: [{
          resource: { attributes: [{ key: "service.name", value: { stringValue: "test-svc" } }] },
          scopeMetrics: [{
            scope: { name: "test" },
            metrics: [{
              name: "cpu.usage",
              unit: "1",
              gauge: {
                dataPoints: [{
                  timeUnixNano: "1700000000000000000",
                  asDouble: 0.75,
                }],
              },
            }],
          }],
        }],
      }),
    });

    expect(resp.status).toBe(200);
    expect(store.getMetrics().length).toBe(1);
    expect(store.getMetrics()[0]!.name).toBe("cpu.usage");
  });

  test("POST /v1/logs ingests logs", async () => {
    store.clear();
    const resp = await fetch(`${BASE}/v1/logs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resourceLogs: [{
          resource: { attributes: [{ key: "service.name", value: { stringValue: "test-svc" } }] },
          scopeLogs: [{
            scope: { name: "test" },
            logRecords: [{
              timeUnixNano: "1700000000000000000",
              severityNumber: 9,
              severityText: "INFO",
              body: { stringValue: "Hello world" },
            }],
          }],
        }],
      }),
    });

    expect(resp.status).toBe(200);
    expect(store.getLogs().length).toBe(1);
    expect(store.getLogs()[0]!.body).toBe("Hello world");
  });

  test("POST /v1/traces with empty batch", async () => {
    store.clear();
    const resp = await fetch(`${BASE}/v1/traces`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resourceSpans: [] }),
    });
    expect(resp.status).toBe(200);
    expect(store.getSpans().length).toBe(0);
  });

  test("POST with malformed body returns 400", async () => {
    const resp = await fetch(`${BASE}/v1/traces`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "not json",
    });
    expect(resp.status).toBe(400);
  });

  test("GET returns 405", async () => {
    const resp = await fetch(`${BASE}/v1/traces`);
    expect(resp.status).toBe(405);
  });

  test("unknown path returns 404", async () => {
    const resp = await fetch(`${BASE}/v1/unknown`, { method: "POST" });
    expect(resp.status).toBe(404);
  });

  test("OPTIONS returns CORS headers", async () => {
    const resp = await fetch(`${BASE}/v1/traces`, { method: "OPTIONS" });
    expect(resp.status).toBe(204);
    expect(resp.headers.get("Access-Control-Allow-Origin")).toBe("*");
  });

  test("response has CORS header", async () => {
    const resp = await fetch(`${BASE}/v1/traces`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resourceSpans: [] }),
    });
    expect(resp.headers.get("Access-Control-Allow-Origin")).toBe("*");
  });

  // --- Protobuf tests ---

  test("POST /v1/traces with protobuf ingests spans", async () => {
    store.clear();
    const encoded = await encodeTracesProtobuf({
      resourceSpans: [{
        resource: { attributes: [{ key: "service.name", value: { stringValue: "proto-svc" } }] },
        scopeSpans: [{
          scope: { name: "otel-auto" },
          spans: [{
            traceId: Buffer.from("a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4", "hex"),
            spanId: Buffer.from("1234567890abcdef", "hex"),
            name: "GET /proto-test",
            kind: 2,
            startTimeUnixNano: 1700000000000000000n,
            endTimeUnixNano: 1700000000100000000n,
            status: { code: 1 },
            attributes: [
              { key: "http.request.method", value: { stringValue: "GET" } },
            ],
          }],
        }],
      }],
    });

    const resp = await fetch(`${BASE}/v1/traces`, {
      method: "POST",
      headers: { "Content-Type": "application/x-protobuf" },
      body: encoded,
    });

    expect(resp.status).toBe(200);
    expect(store.getSpans().length).toBe(1);
    expect(store.getSpans()[0]!.name).toBe("GET /proto-test");
    expect(store.getSpans()[0]!.resource.serviceName).toBe("proto-svc");
    expect(store.getSpans()[0]!.kind).toBe("SERVER");
    expect(store.getSpans()[0]!.attributes["http.request.method"]).toBe("GET");
  });

  test("POST /v1/metrics with protobuf ingests metrics", async () => {
    store.clear();
    const encoded = await encodeMetricsProtobuf({
      resourceMetrics: [{
        resource: { attributes: [{ key: "service.name", value: { stringValue: "proto-svc" } }] },
        scopeMetrics: [{
          scope: { name: "otel" },
          metrics: [{
            name: "proto.cpu.usage",
            unit: "1",
            gauge: {
              dataPoints: [{
                timeUnixNano: 1700000000000000000n,
                asDouble: 0.85,
              }],
            },
          }],
        }],
      }],
    });

    const resp = await fetch(`${BASE}/v1/metrics`, {
      method: "POST",
      headers: { "Content-Type": "application/x-protobuf" },
      body: encoded,
    });

    expect(resp.status).toBe(200);
    expect(store.getMetrics().length).toBe(1);
    expect(store.getMetrics()[0]!.name).toBe("proto.cpu.usage");
    expect(store.getMetrics()[0]!.value).toBe(0.85);
  });

  test("POST /v1/logs with protobuf ingests logs", async () => {
    store.clear();
    const encoded = await encodeLogsProtobuf({
      resourceLogs: [{
        resource: { attributes: [{ key: "service.name", value: { stringValue: "proto-svc" } }] },
        scopeLogs: [{
          scope: { name: "pino" },
          logRecords: [{
            timeUnixNano: 1700000000000000000n,
            severityNumber: 9,
            severityText: "INFO",
            body: { stringValue: "Protobuf log message" },
          }],
        }],
      }],
    });

    const resp = await fetch(`${BASE}/v1/logs`, {
      method: "POST",
      headers: { "Content-Type": "application/x-protobuf" },
      body: encoded,
    });

    expect(resp.status).toBe(200);
    expect(store.getLogs().length).toBe(1);
    expect(store.getLogs()[0]!.body).toBe("Protobuf log message");
    expect(store.getLogs()[0]!.severityText).toBe("INFO");
  });
});
