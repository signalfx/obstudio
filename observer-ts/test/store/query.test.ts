import { test, expect, describe, beforeEach } from "bun:test";
import { Store } from "../../src/store/store.ts";
import { queryTraces, getTrace, queryMetrics, queryLogs, stats, queryServiceMap, inferService, inferRemoteService } from "../../src/store/query.ts";
import type { Span, MetricDataPoint, LogRecord } from "../../src/store/types.ts";

function makeSpan(overrides: Partial<Span> = {}): Span {
  return {
    traceId: "abc123",
    spanId: "span1",
    name: "GET /api",
    kind: "SERVER",
    startTimeUnixNano: "1700000000000000000",
    endTimeUnixNano: "1700000000100000000",
    durationMs: 100,
    status: { code: "OK" },
    attributes: {},
    events: [],
    links: [],
    resource: { serviceName: "test-svc", attributes: {} },
    scope: { name: "test-scope" },
    ...overrides,
  };
}

function makeMetric(overrides: Partial<MetricDataPoint> = {}): MetricDataPoint {
  return {
    name: "http.server.request.duration",
    type: "histogram",
    timeUnixNano: "1700000000000000000",
    attributes: {},
    resource: { serviceName: "test-svc", attributes: {} },
    scope: { name: "test-scope" },
    ...overrides,
  };
}

function makeLog(overrides: Partial<LogRecord> = {}): LogRecord {
  return {
    timeUnixNano: "1700000000000000000",
    body: "Hello world",
    attributes: {},
    resource: { serviceName: "test-svc", attributes: {} },
    scope: { name: "test-scope" },
    ...overrides,
  };
}

describe("queryTraces", () => {
  let store: Store;

  beforeEach(() => {
    store = new Store();
  });

  test("returns empty for empty store", () => {
    expect(queryTraces(store, {})).toEqual([]);
  });

  test("groups spans by traceId", () => {
    store.addSpans([
      makeSpan({ traceId: "t1", spanId: "s1", parentSpanId: undefined }),
      makeSpan({ traceId: "t1", spanId: "s2", parentSpanId: "s1" }),
      makeSpan({ traceId: "t2", spanId: "s3", parentSpanId: undefined }),
    ]);
    const result = queryTraces(store, {});
    expect(result.length).toBe(2);
    const t1 = result.find((t) => t.traceId === "t1");
    expect(t1?.spanCount).toBe(2);
  });

  test("filters by serviceName", () => {
    store.addSpans([
      makeSpan({ traceId: "t1", resource: { serviceName: "svc-a", attributes: {} } }),
      makeSpan({ traceId: "t2", resource: { serviceName: "svc-b", attributes: {} } }),
    ]);
    const result = queryTraces(store, { serviceName: "svc-a" });
    expect(result.length).toBe(1);
    expect(result[0]!.serviceName).toBe("svc-a");
  });

  test("filters by serviceName case-insensitive", () => {
    store.addSpans([
      makeSpan({ traceId: "t1", resource: { serviceName: "MyService", attributes: {} } }),
    ]);
    expect(queryTraces(store, { serviceName: "myservice" }).length).toBe(1);
  });

  test("filters by status", () => {
    store.addSpans([
      makeSpan({ traceId: "t1", status: { code: "OK" } }),
      makeSpan({ traceId: "t2", status: { code: "ERROR" } }),
    ]);
    const result = queryTraces(store, { status: "error" });
    expect(result.length).toBe(1);
    expect(result[0]!.traceId).toBe("t2");
  });

  test("filters by traceIdPrefix", () => {
    store.addSpans([
      makeSpan({ traceId: "abc123" }),
      makeSpan({ traceId: "def456" }),
    ]);
    const result = queryTraces(store, { traceIdPrefix: "abc" });
    expect(result.length).toBe(1);
  });

  test("filters by spanName", () => {
    store.addSpans([
      makeSpan({ traceId: "t1", name: "GET /users" }),
      makeSpan({ traceId: "t2", name: "POST /orders" }),
    ]);
    expect(queryTraces(store, { spanName: "GET /users" }).length).toBe(1);
  });

  test("respects limit", () => {
    for (let i = 0; i < 30; i++) {
      store.addSpans([makeSpan({ traceId: `t${i.toString().padStart(3, "0")}` })]);
    }
    expect(queryTraces(store, { limit: 5 }).length).toBe(5);
  });

  test("includes span previews", () => {
    store.addSpans([makeSpan()]);
    const result = queryTraces(store, { spanPreviewCount: 3 });
    expect(result[0]!.spans!.length).toBe(1);
    expect(result[0]!.spans![0]!.spanId).toBe("span1");
  });

  test("computes trace duration from min start to max end", () => {
    store.addSpans([
      makeSpan({ traceId: "t1", spanId: "s1", startTimeUnixNano: "1000000000", endTimeUnixNano: "2000000000" }),
      makeSpan({ traceId: "t1", spanId: "s2", parentSpanId: "s1", startTimeUnixNano: "500000000", endTimeUnixNano: "3000000000" }),
    ]);
    const result = queryTraces(store, {});
    // Duration: (3000000000 - 500000000) / 1_000_000 = 2500ms... wait
    // Actually (3000000000 - 500000000) / 1_000_000 = 2500
    expect(result[0]!.durationMs).toBe(2500);
  });

  test("computes mixed status", () => {
    store.addSpans([
      makeSpan({ traceId: "t1", spanId: "s1", status: { code: "OK" } }),
      makeSpan({ traceId: "t1", spanId: "s2", parentSpanId: "s1", status: { code: "ERROR" } }),
    ]);
    const result = queryTraces(store, {});
    expect(result[0]!.status).toBe("mixed");
  });
});

describe("getTrace", () => {
  let store: Store;

  beforeEach(() => {
    store = new Store();
  });

  test("returns null for missing trace", () => {
    expect(getTrace(store, "nonexistent")).toBeNull();
  });

  test("returns trace detail with all spans", () => {
    store.addSpans([
      makeSpan({ traceId: "t1", spanId: "s1" }),
      makeSpan({ traceId: "t1", spanId: "s2", parentSpanId: "s1" }),
    ]);
    const detail = getTrace(store, "t1");
    expect(detail).not.toBeNull();
    expect(detail!.spanCount).toBe(2);
    expect(detail!.spans.length).toBe(2);
  });

  test("truncates events per span", () => {
    const events = Array.from({ length: 20 }, (_, i) => ({
      name: `event-${i}`,
      timeUnixNano: "1700000000000000000",
      attributes: {},
    }));
    store.addSpans([makeSpan({ events })]);
    const detail = getTrace(store, "abc123", 5);
    expect(detail!.spans[0]!.events.length).toBe(5);
  });
});

describe("queryMetrics", () => {
  let store: Store;

  beforeEach(() => {
    store = new Store();
  });

  test("returns empty for empty store", () => {
    expect(queryMetrics(store, {})).toEqual([]);
  });

  test("groups by name/service/scope", () => {
    store.addMetrics([
      makeMetric({ name: "m1" }),
      makeMetric({ name: "m1" }),
      makeMetric({ name: "m2" }),
    ]);
    const result = queryMetrics(store, {});
    expect(result.length).toBe(2);
    const m1 = result.find((g) => g.name === "m1");
    expect(m1!.dataPointCount).toBe(2);
  });

  test("filters by metricName case-insensitive", () => {
    store.addMetrics([
      makeMetric({ name: "http.server.request.duration" }),
      makeMetric({ name: "http.client.request.duration" }),
    ]);
    expect(queryMetrics(store, { metricName: "HTTP.SERVER.REQUEST.DURATION" }).length).toBe(1);
  });

  test("filters by serviceName", () => {
    store.addMetrics([
      makeMetric({ resource: { serviceName: "svc-a", attributes: {} } }),
      makeMetric({ resource: { serviceName: "svc-b", attributes: {} } }),
    ]);
    expect(queryMetrics(store, { serviceName: "svc-a" }).length).toBe(1);
  });

  test("filters by type with normalization", () => {
    store.addMetrics([
      makeMetric({ type: "sum" }),
      makeMetric({ type: "gauge" }),
    ]);
    expect(queryMetrics(store, { type: "counter" }).length).toBe(1); // counter → sum
  });

  test("limits datapoints per group", () => {
    store.addMetrics([
      makeMetric({ name: "m1", timeUnixNano: "1" }),
      makeMetric({ name: "m1", timeUnixNano: "2" }),
      makeMetric({ name: "m1", timeUnixNano: "3" }),
      makeMetric({ name: "m1", timeUnixNano: "4" }),
      makeMetric({ name: "m1", timeUnixNano: "5" }),
    ]);
    const result = queryMetrics(store, { dataPointLimit: 2 });
    expect(result[0]!.dataPointCount).toBe(5);
    expect(result[0]!.dataPoints!.length).toBe(2);
  });

  test("respects limit", () => {
    for (let i = 0; i < 30; i++) {
      store.addMetrics([makeMetric({ name: `m${i}` })]);
    }
    expect(queryMetrics(store, { limit: 5 }).length).toBe(5);
  });
});

describe("queryLogs", () => {
  let store: Store;

  beforeEach(() => {
    store = new Store();
  });

  test("returns empty for empty store", () => {
    expect(queryLogs(store, {})).toEqual([]);
  });

  test("returns logs in reverse order (newest first)", () => {
    store.addLogs([
      makeLog({ body: "first", timeUnixNano: "1" }),
      makeLog({ body: "second", timeUnixNano: "2" }),
      makeLog({ body: "third", timeUnixNano: "3" }),
    ]);
    const result = queryLogs(store, {});
    expect(result[0]!.body).toBe("third");
    expect(result[2]!.body).toBe("first");
  });

  test("filters by serviceName", () => {
    store.addLogs([
      makeLog({ resource: { serviceName: "svc-a", attributes: {} } }),
      makeLog({ resource: { serviceName: "svc-b", attributes: {} } }),
    ]);
    expect(queryLogs(store, { serviceName: "svc-a" }).length).toBe(1);
  });

  test("filters by severityText case-insensitive", () => {
    store.addLogs([
      makeLog({ severityText: "ERROR" }),
      makeLog({ severityText: "INFO" }),
    ]);
    expect(queryLogs(store, { severityText: "error" }).length).toBe(1);
  });

  test("filters by body substring", () => {
    store.addLogs([
      makeLog({ body: "User created successfully" }),
      makeLog({ body: "Payment failed" }),
    ]);
    expect(queryLogs(store, { body: "payment" }).length).toBe(1);
  });

  test("filters by traceId", () => {
    store.addLogs([
      makeLog({ traceId: "t1" }),
      makeLog({ traceId: "t2" }),
    ]);
    expect(queryLogs(store, { traceId: "t1" }).length).toBe(1);
  });

  test("respects limit", () => {
    for (let i = 0; i < 100; i++) {
      store.addLogs([makeLog({ body: `log-${i}` })]);
    }
    expect(queryLogs(store, { limit: 10 }).length).toBe(10);
  });
});

describe("stats", () => {
  test("returns zeros for empty store", () => {
    const store = new Store();
    const s = stats(store);
    expect(s.spanCount).toBe(0);
    expect(s.metricCount).toBe(0);
    expect(s.logCount).toBe(0);
    expect(s.traceCount).toBe(0);
    expect(s.metricNameCount).toBe(0);
    expect(s.serviceNames).toEqual([]);
  });

  test("counts correctly", () => {
    const store = new Store();
    store.addSpans([
      makeSpan({ traceId: "t1", spanId: "s1" }),
      makeSpan({ traceId: "t1", spanId: "s2" }),
      makeSpan({ traceId: "t2", spanId: "s3" }),
    ]);
    store.addMetrics([makeMetric({ name: "m1" }), makeMetric({ name: "m1" }), makeMetric({ name: "m2" })]);
    store.addLogs([makeLog()]);

    const s = stats(store);
    expect(s.spanCount).toBe(3);
    expect(s.traceCount).toBe(2);
    expect(s.metricCount).toBe(3);
    expect(s.metricNameCount).toBe(2);
    expect(s.logCount).toBe(1);
  });

  test("collects service names sorted", () => {
    const store = new Store();
    store.addSpans([
      makeSpan({ resource: { serviceName: "zeta", attributes: {} } }),
      makeSpan({ resource: { serviceName: "alpha", attributes: {} } }),
    ]);
    store.addMetrics([makeMetric({ resource: { serviceName: "beta", attributes: {} } })]);
    const s = stats(store);
    expect(s.serviceNames).toEqual(["alpha", "beta", "zeta"]);
  });
});

describe("queryServiceMap", () => {
  test("builds nodes and edges from cross-service spans", () => {
    const store = new Store();
    store.addSpans([
      makeSpan({ traceId: "t1", spanId: "s1", kind: "SERVER", resource: { serviceName: "frontend", attributes: {} } }),
      makeSpan({ traceId: "t1", spanId: "s2", parentSpanId: "s1", kind: "SERVER", resource: { serviceName: "backend", attributes: {} } }),
    ]);
    const map = queryServiceMap(store);
    expect(map.nodes.length).toBe(2);
    expect(map.edges.length).toBe(1);
    expect(map.edges[0]!.source).toBe("frontend");
    expect(map.edges[0]!.target).toBe("backend");
  });

  test("no edge for same service", () => {
    const store = new Store();
    store.addSpans([
      makeSpan({ traceId: "t1", spanId: "s1", resource: { serviceName: "svc", attributes: {} } }),
      makeSpan({ traceId: "t1", spanId: "s2", parentSpanId: "s1", resource: { serviceName: "svc", attributes: {} } }),
    ]);
    const map = queryServiceMap(store);
    expect(map.edges.length).toBe(0);
  });

  test("counts errors on cross-service edges", () => {
    const store = new Store();
    store.addSpans([
      makeSpan({ traceId: "t1", spanId: "s1", status: { code: "OK" }, resource: { serviceName: "fe", attributes: {} } }),
      makeSpan({ traceId: "t1", spanId: "s2", parentSpanId: "s1", status: { code: "ERROR" }, resource: { serviceName: "be", attributes: {} } }),
    ]);
    const map = queryServiceMap(store);
    const be = map.nodes.find((n) => n.id === "be");
    expect(be!.errorCount).toBe(1);
    expect(map.edges[0]!.errorCount).toBe(1);
  });

  test("DB client span creates edge from owning service to database", () => {
    const store = new Store();
    store.addSpans([
      makeSpan({ traceId: "t1", spanId: "s1", kind: "SERVER", name: "GET /api", resource: { serviceName: "api-gateway", attributes: {} } }),
      makeSpan({ traceId: "t1", spanId: "s2", parentSpanId: "s1", kind: "CLIENT", name: "SELECT users",
        attributes: { "db.system.name": "postgresql" },
        resource: { serviceName: "api-gateway", attributes: {} } }),
    ]);
    const map = queryServiceMap(store);
    // Should have api-gateway + postgresql nodes
    expect(map.nodes.length).toBe(2);
    expect(map.nodes.find((n) => n.id === "api-gateway")).toBeTruthy();
    expect(map.nodes.find((n) => n.id === "postgresql")).toBeTruthy();
    // Edge: api-gateway → postgresql (NOT api-gateway as both node AND postgresql as separate tree)
    expect(map.edges.length).toBe(1);
    expect(map.edges[0]!.source).toBe("api-gateway");
    expect(map.edges[0]!.target).toBe("postgresql");
    // Both spans belong to api-gateway's node
    expect(map.nodes.find((n) => n.id === "api-gateway")!.spanCount).toBe(2);
  });

  test("messaging PRODUCER creates edge from owning service to broker", () => {
    const store = new Store();
    store.addSpans([
      makeSpan({ traceId: "t1", spanId: "s1", kind: "PRODUCER", name: "kafka.produce",
        attributes: { "messaging.system": "kafka" },
        resource: { serviceName: "notification-service", attributes: {} } }),
    ]);
    const map = queryServiceMap(store);
    expect(map.nodes.length).toBe(2);
    expect(map.edges.length).toBe(1);
    expect(map.edges[0]!.source).toBe("notification-service");
    expect(map.edges[0]!.target).toBe("kafka");
  });

  test("SERVER span with no remote target creates no extra edge", () => {
    const store = new Store();
    store.addSpans([
      makeSpan({ traceId: "t1", spanId: "s1", kind: "SERVER", name: "GET /api",
        resource: { serviceName: "api-gateway", attributes: {} } }),
    ]);
    const map = queryServiceMap(store);
    expect(map.nodes.length).toBe(1);
    expect(map.edges.length).toBe(0);
  });
});

describe("inferService", () => {
  test("uses db.system.name for database spans", () => {
    const span = makeSpan({ attributes: { "db.system.name": "postgresql" } });
    expect(inferService(span)).toBe("postgresql");
  });

  test("uses server.address for CLIENT spans", () => {
    const span = makeSpan({ kind: "CLIENT", attributes: { "server.address": "api.example.com" } });
    expect(inferService(span)).toBe("api.example.com");
  });

  test("ignores localhost for CLIENT spans", () => {
    const span = makeSpan({ kind: "CLIENT", attributes: { "server.address": "localhost" } });
    expect(inferService(span)).toBe("test-svc");
  });

  test("parses INTERNAL spans with dotted names", () => {
    const span = makeSpan({ kind: "INTERNAL", name: "UserService.getUser" });
    expect(inferService(span)).toBe("user-service");
  });

  test("uses messaging.system for PRODUCER spans", () => {
    const span = makeSpan({ kind: "PRODUCER", attributes: { "messaging.system": "kafka" } });
    expect(inferService(span)).toBe("kafka");
  });

  test("uses messaging.system for CONSUMER spans", () => {
    const span = makeSpan({ kind: "CONSUMER", attributes: { "messaging.system": "rabbitmq" } });
    expect(inferService(span)).toBe("rabbitmq");
  });

  test("PRODUCER falls back to server.address without messaging.system", () => {
    const span = makeSpan({ kind: "PRODUCER", attributes: { "server.address": "kafka-broker.example.com" } });
    expect(inferService(span)).toBe("kafka-broker.example.com");
  });

  // --- RPC / gRPC ---

  test("uses rpc.service for CLIENT gRPC spans", () => {
    const span = makeSpan({ kind: "CLIENT", attributes: { "rpc.system": "grpc", "rpc.service": "UserService", "rpc.method": "GetUser" } });
    expect(inferService(span)).toBe("UserService");
  });

  test("uses rpc.service for AWS SDK calls", () => {
    const span = makeSpan({ kind: "CLIENT", attributes: { "rpc.system": "aws-api", "rpc.service": "DynamoDB" } });
    expect(inferService(span)).toBe("DynamoDB");
  });

  test("rpc.service takes priority over server.address for CLIENT", () => {
    const span = makeSpan({ kind: "CLIENT", attributes: { "rpc.service": "S3", "server.address": "s3.us-east-1.amazonaws.com" } });
    expect(inferService(span)).toBe("S3");
  });

  // --- FaaS ---

  test("uses faas.invoked_name for Lambda invocations", () => {
    const span = makeSpan({ kind: "CLIENT", attributes: { "faas.invoked_name": "my-function" } });
    expect(inferService(span)).toBe("my-function");
  });

  test("parses function name from AWS Lambda ARN", () => {
    const span = makeSpan({ kind: "CLIENT", attributes: { "faas.invoked_name": "arn:aws:lambda:us-east-1:123456789:function:order-processor" } });
    expect(inferService(span)).toBe("order-processor");
  });

  test("parses function name from GCP path", () => {
    const span = makeSpan({ kind: "CLIENT", attributes: { "faas.invoked_name": "projects/my-proj/locations/us-central1/functions/process-order" } });
    expect(inferService(span)).toBe("process-order");
  });

  // --- url.full fallback ---

  test("extracts hostname from url.full when server.address missing", () => {
    const span = makeSpan({ kind: "CLIENT", attributes: { "url.full": "https://api.stripe.com/v1/charges" } });
    expect(inferService(span)).toBe("api.stripe.com");
  });

  test("ignores localhost in url.full", () => {
    const span = makeSpan({ kind: "CLIENT", attributes: { "url.full": "http://localhost:8080/api" } });
    expect(inferService(span)).toBe("test-svc");
  });

  // --- peer.service ---

  test("peer.service takes highest priority", () => {
    const span = makeSpan({ kind: "CLIENT", attributes: { "peer.service": "auth-service", "server.address": "10.0.0.5", "rpc.service": "AuthService" } });
    expect(inferService(span)).toBe("auth-service");
  });

  test("peer.service works on SERVER spans too", () => {
    const span = makeSpan({ kind: "SERVER", attributes: { "peer.service": "downstream-svc" } });
    expect(inferService(span)).toBe("downstream-svc");
  });

  // --- Legacy net.peer.name ---

  test("uses net.peer.name as fallback for CLIENT spans", () => {
    const span = makeSpan({ kind: "CLIENT", attributes: { "net.peer.name": "legacy-db.example.com" } });
    expect(inferService(span)).toBe("legacy-db.example.com");
  });

  test("ignores local net.peer.name", () => {
    const span = makeSpan({ kind: "CLIENT", attributes: { "net.peer.name": "127.0.0.1" } });
    expect(inferService(span)).toBe("test-svc");
  });

  // --- Priority order ---

  test("db.system.name beats rpc.service", () => {
    const span = makeSpan({ kind: "CLIENT", attributes: { "db.system.name": "redis", "rpc.service": "CacheService" } });
    expect(inferService(span)).toBe("redis");
  });

  test("peer.service beats db.system.name", () => {
    const span = makeSpan({ kind: "CLIENT", attributes: { "peer.service": "my-redis", "db.system.name": "redis" } });
    expect(inferService(span)).toBe("my-redis");
  });

  test("falls back to resource service name", () => {
    const span = makeSpan({ kind: "SERVER" });
    expect(inferService(span)).toBe("test-svc");
  });
});
