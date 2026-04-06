import { test, expect, describe, beforeEach } from "bun:test";
import { Store } from "../../src/store/store.ts";
import type { Span, MetricDataPoint, LogRecord, Signal } from "../../src/store/types.ts";

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

describe("Store", () => {
  let store: Store;

  beforeEach(() => {
    store = new Store({ sessionGap: 30_000 });
  });

  describe("addSpans", () => {
    test("adds spans to store", () => {
      store.addSpans([makeSpan()]);
      expect(store.getSpans().length).toBe(1);
    });

    test("accumulates spans", () => {
      store.addSpans([makeSpan({ spanId: "s1" })]);
      store.addSpans([makeSpan({ spanId: "s2" })]);
      expect(store.getSpans().length).toBe(2);
    });
  });

  describe("addMetrics", () => {
    test("adds metrics to store", () => {
      store.addMetrics([makeMetric()]);
      expect(store.getMetrics().length).toBe(1);
    });
  });

  describe("addLogs", () => {
    test("adds logs to store", () => {
      store.addLogs([makeLog()]);
      expect(store.getLogs().length).toBe(1);
    });
  });

  describe("clear", () => {
    test("removes all data", () => {
      store.addSpans([makeSpan()]);
      store.addMetrics([makeMetric()]);
      store.addLogs([makeLog()]);
      store.clear();
      expect(store.getSpans().length).toBe(0);
      expect(store.getMetrics().length).toBe(0);
      expect(store.getLogs().length).toBe(0);
    });

    test("notifies all signals on clear", () => {
      const signals: Signal[] = [];
      store.subscribe((sig) => signals.push(sig));
      store.clear();
      expect(signals).toEqual(["traces", "metrics", "logs"]);
    });
  });

  describe("session reset", () => {
    test("clears data after session gap", () => {
      const store = new Store({ sessionGap: 50 }); // 50ms gap
      store.addSpans([makeSpan()]);
      store.addMetrics([makeMetric()]);
      store.addLogs([makeLog()]);
      expect(store.getSpans().length).toBe(1);

      // Wait for gap to pass.
      const start = Date.now();
      while (Date.now() - start < 60) {} // busy wait 60ms

      // Next add triggers reset.
      store.addSpans([makeSpan({ spanId: "new" })]);
      // Old data cleared, new span added.
      expect(store.getSpans().length).toBe(1);
      expect(store.getSpans()[0]!.spanId).toBe("new");
      // Metrics and logs cleared.
      expect(store.getMetrics().length).toBe(0);
      expect(store.getLogs().length).toBe(0);
    });

    test("notifies all signals on session reset", () => {
      const store = new Store({ sessionGap: 50 });
      store.addSpans([makeSpan()]);

      const start = Date.now();
      while (Date.now() - start < 60) {}

      const signals: Signal[] = [];
      store.subscribe((sig) => signals.push(sig));
      store.addSpans([makeSpan({ spanId: "new" })]);

      // Should notify traces, metrics, logs (reset) — not just traces.
      expect(signals).toContain("traces");
      expect(signals).toContain("metrics");
      expect(signals).toContain("logs");
    });

    test("does not reset within session gap", () => {
      store.addSpans([makeSpan()]);
      store.addMetrics([makeMetric()]);
      // Add more immediately — should not reset.
      store.addSpans([makeSpan({ spanId: "s2" })]);
      expect(store.getSpans().length).toBe(2);
      expect(store.getMetrics().length).toBe(1);
    });

    test("does not reset on first ingest", () => {
      store.addSpans([makeSpan()]);
      expect(store.getSpans().length).toBe(1);
    });
  });

  describe("pub/sub", () => {
    test("subscribe receives signals", () => {
      const signals: Signal[] = [];
      store.subscribe((sig) => signals.push(sig));

      store.addSpans([makeSpan()]);
      expect(signals).toEqual(["traces"]);

      store.addMetrics([makeMetric()]);
      expect(signals).toEqual(["traces", "metrics"]);

      store.addLogs([makeLog()]);
      expect(signals).toEqual(["traces", "metrics", "logs"]);
    });

    test("unsubscribe stops notifications", () => {
      const signals: Signal[] = [];
      const id = store.subscribe((sig) => signals.push(sig));
      store.addSpans([makeSpan()]);
      expect(signals.length).toBe(1);

      store.unsubscribe(id);
      store.addSpans([makeSpan()]);
      expect(signals.length).toBe(1); // No new notification.
    });

    test("multiple subscribers", () => {
      const a: Signal[] = [];
      const b: Signal[] = [];
      store.subscribe((sig) => a.push(sig));
      store.subscribe((sig) => b.push(sig));

      store.addSpans([makeSpan()]);
      expect(a).toEqual(["traces"]);
      expect(b).toEqual(["traces"]);
    });

    test("subscriber error does not break others", () => {
      const signals: Signal[] = [];
      store.subscribe(() => {
        throw new Error("boom");
      });
      store.subscribe((sig) => signals.push(sig));

      store.addSpans([makeSpan()]);
      expect(signals).toEqual(["traces"]);
    });
  });
});
