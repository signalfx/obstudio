import { test, expect, describe, beforeEach } from "bun:test";
import { handleRest } from "../../src/api/rest.ts";
import { Store } from "../../src/store/store.ts";
import type { Span, MetricDataPoint, LogRecord } from "../../src/store/types.ts";

function makeSpan(overrides: Partial<Span> = {}): Span {
  return {
    traceId: "abc123",
    spanId: "def456",
    name: "GET /api",
    kind: "SERVER",
    startTimeUnixNano: "1700000000000000000",
    endTimeUnixNano: "1700000000100000000",
    durationMs: 100,
    status: { code: "OK" },
    attributes: {},
    events: [],
    links: [],
    resource: { serviceName: "my-svc", attributes: {} },
    scope: { name: "my-scope" },
    ...overrides,
  };
}

function makeMetric(overrides: Partial<MetricDataPoint> = {}): MetricDataPoint {
  return {
    name: "cpu.usage",
    type: "gauge",
    timeUnixNano: "1700000000000000000",
    attributes: {},
    resource: { serviceName: "my-svc", attributes: {} },
    scope: { name: "my-scope" },
    value: 0.75,
    ...overrides,
  };
}

function makeLog(overrides: Partial<LogRecord> = {}): LogRecord {
  return {
    timeUnixNano: "1700000000000000000",
    severityText: "INFO",
    severityNumber: 9,
    body: "hello world",
    attributes: {},
    resource: { serviceName: "my-svc", attributes: {} },
    scope: { name: "logback" },
    ...overrides,
  };
}

function req(method: string, path: string): Request {
  return new Request(`http://localhost:3000${path}`, { method });
}

describe("REST API", () => {
  let store: Store;

  beforeEach(() => {
    store = new Store({ sessionGap: 0 });
  });

  test("GET /api/query/traces returns traces", () => {
    store.addSpans([makeSpan()]);
    const resp = handleRest(req("GET", "/api/query/traces"), store);
    expect(resp).not.toBeNull();
    expect(resp!.status).toBe(200);
    expect(resp!.headers.get("Content-Type")).toBe("application/json");
    expect(resp!.headers.get("Access-Control-Allow-Origin")).toBe("*");
  });

  test("GET /api/query/traces returns JSON array", async () => {
    store.addSpans([makeSpan()]);
    const resp = handleRest(req("GET", "/api/query/traces"), store)!;
    const body = await resp.json() as any;
    expect(Array.isArray(body)).toBe(true);
    expect(body.length).toBe(1);
    expect(body[0].traceId).toBe("abc123");
  });

  test("GET /api/query/traces with filters", async () => {
    store.addSpans([
      makeSpan({ traceId: "t1", resource: { serviceName: "svc-a", attributes: {} } }),
      makeSpan({ traceId: "t2", resource: { serviceName: "svc-b", attributes: {} } }),
    ]);
    const resp = handleRest(req("GET", "/api/query/traces?serviceName=svc-a"), store)!;
    const body = await resp.json() as any;
    expect(body.length).toBe(1);
    expect(body[0].serviceName).toBe("svc-a");
  });

  test("GET /api/query/traces/:traceId returns trace detail", async () => {
    store.addSpans([makeSpan({ traceId: "abc123" })]);
    const resp = handleRest(req("GET", "/api/query/traces/abc123"), store)!;
    expect(resp.status).toBe(200);
    const body = await resp.json() as any;
    expect(body.traceId).toBe("abc123");
    expect(body.spans).toBeDefined();
  });

  test("GET /api/query/traces/:traceId returns 404 for missing trace", async () => {
    const resp = handleRest(req("GET", "/api/query/traces/nonexistent"), store)!;
    expect(resp.status).toBe(404);
  });

  test("GET /api/query/metrics returns metrics", async () => {
    store.addMetrics([makeMetric()]);
    const resp = handleRest(req("GET", "/api/query/metrics"), store)!;
    const body = await resp.json() as any;
    expect(Array.isArray(body)).toBe(true);
    expect(body.length).toBe(1);
    expect(body[0].name).toBe("cpu.usage");
  });

  test("GET /api/query/metrics with filters", async () => {
    store.addMetrics([
      makeMetric({ name: "cpu.usage" }),
      makeMetric({ name: "mem.usage" }),
    ]);
    const resp = handleRest(req("GET", "/api/query/metrics?metricName=cpu.usage"), store)!;
    const body = await resp.json() as any;
    expect(body.length).toBe(1);
    expect(body[0].name).toBe("cpu.usage");
  });

  test("GET /api/query/logs returns logs", async () => {
    store.addLogs([makeLog()]);
    const resp = handleRest(req("GET", "/api/query/logs"), store)!;
    const body = await resp.json() as any;
    expect(Array.isArray(body)).toBe(true);
    expect(body.length).toBe(1);
    expect(body[0].body).toBe("hello world");
  });

  test("GET /api/query/logs with filters", async () => {
    store.addLogs([
      makeLog({ severityText: "INFO", body: "info msg" }),
      makeLog({ severityText: "ERROR", body: "error msg" }),
    ]);
    const resp = handleRest(req("GET", "/api/query/logs?severityText=ERROR"), store)!;
    const body = await resp.json() as any;
    expect(body.length).toBe(1);
    expect(body[0].severityText).toBe("ERROR");
  });

  test("GET /api/query/stats returns stats", async () => {
    store.addSpans([makeSpan()]);
    store.addMetrics([makeMetric()]);
    store.addLogs([makeLog()]);
    const resp = handleRest(req("GET", "/api/query/stats"), store)!;
    const body = await resp.json() as any;
    expect(body.spanCount).toBe(1);
    expect(body.metricCount).toBe(1);
    expect(body.logCount).toBe(1);
    expect(body.traceCount).toBe(1);
  });

  test("GET /api/query/service-map returns service map", async () => {
    store.addSpans([makeSpan()]);
    const resp = handleRest(req("GET", "/api/query/service-map"), store)!;
    const body = await resp.json() as any;
    expect(body.nodes).toBeDefined();
    expect(body.edges).toBeDefined();
  });

  test("DELETE /api/data clears store", async () => {
    store.addSpans([makeSpan()]);
    const resp = handleRest(req("DELETE", "/api/data"), store)!;
    expect(resp.status).toBe(200);
    const body = await resp.json() as any;
    expect(body.status).toBe("cleared");
    // Verify store is empty.
    expect(store.getSpans().length).toBe(0);
  });

  test("OPTIONS returns CORS preflight", () => {
    const resp = handleRest(req("OPTIONS", "/api/query/traces"), store)!;
    expect(resp.status).toBe(204);
    expect(resp.headers.get("Access-Control-Allow-Origin")).toBe("*");
    expect(resp.headers.get("Access-Control-Allow-Methods")).toContain("GET");
  });

  test("POST returns null (not handled)", () => {
    const resp = handleRest(req("POST", "/api/query/traces"), store);
    expect(resp).toBeNull();
  });

  test("unknown path returns null", () => {
    const resp = handleRest(req("GET", "/api/unknown"), store);
    expect(resp).toBeNull();
  });

  test("Cache-Control is no-store", () => {
    store.addSpans([makeSpan()]);
    const resp = handleRest(req("GET", "/api/query/stats"), store)!;
    expect(resp.headers.get("Cache-Control")).toBe("no-store");
  });
});
