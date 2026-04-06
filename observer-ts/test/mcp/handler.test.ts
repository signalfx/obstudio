import { test, expect, describe, beforeEach } from "bun:test";
import { McpDispatcher, type JsonRpcRequest } from "../../src/mcp/handler.ts";
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

function rpc(method: string, params?: unknown): JsonRpcRequest {
  return { id: 1, jsonrpc: "2.0", method, params };
}

describe("MCP Dispatcher", () => {
  let store: Store;
  let dispatcher: McpDispatcher;

  beforeEach(() => {
    store = new Store({ sessionGap: 0 });
    dispatcher = new McpDispatcher(store);
  });

  // --- Initialize ---

  test("initialize returns server info and protocol version", () => {
    const resp = dispatcher.dispatch(rpc("initialize", { protocolVersion: "2024-11-05" }));
    expect(resp).not.toBeNull();
    expect(resp!.jsonrpc).toBe("2.0");
    expect(resp!.id).toBe(1);
    const result = resp!.result as Record<string, unknown>;
    expect(result.protocolVersion).toBe("2024-11-05");
    expect((result.serverInfo as Record<string, unknown>).name).toBe("obstudio");
  });

  test("initialize negotiates latest version when client sends unknown", () => {
    const resp = dispatcher.dispatch(rpc("initialize", { protocolVersion: "1999-01-01" }));
    const result = resp!.result as Record<string, unknown>;
    expect(result.protocolVersion).toBe("2025-06-18");
  });

  test("initialize negotiates latest version when no version sent", () => {
    const resp = dispatcher.dispatch(rpc("initialize", {}));
    const result = resp!.result as Record<string, unknown>;
    expect(result.protocolVersion).toBe("2025-06-18");
  });

  // --- Notifications ---

  test("notifications/initialized returns null (no response)", () => {
    const resp = dispatcher.dispatch(rpc("notifications/initialized"));
    expect(resp).toBeNull();
  });

  // --- tools/list ---

  test("tools/list returns all 5 tools", () => {
    const resp = dispatcher.dispatch(rpc("tools/list"));
    const result = resp!.result as { tools: unknown[] };
    expect(result.tools.length).toBe(5);
    const names = result.tools.map((t: any) => t.name);
    expect(names).toContain("observer_traces_overview");
    expect(names).toContain("observer_trace_detail");
    expect(names).toContain("observer_metrics_overview");
    expect(names).toContain("observer_metric_detail");
    expect(names).toContain("observer_clear");
  });

  test("tools have proper structure", () => {
    const resp = dispatcher.dispatch(rpc("tools/list"));
    const result = resp!.result as { tools: any[] };
    for (const tool of result.tools) {
      expect(tool.name).toBeDefined();
      expect(tool.description).toBeDefined();
      expect(tool.inputSchema).toBeDefined();
      expect(tool.annotations).toBeDefined();
    }
  });

  // --- Method not found ---

  test("unknown method returns error", () => {
    const resp = dispatcher.dispatch(rpc("unknown/method"));
    expect(resp!.error).toBeDefined();
    expect(resp!.error!.code).toBe(-32601);
    expect(resp!.error!.message).toContain("Method not found");
  });

  // --- observer_traces_overview ---

  test("observer_traces_overview returns traces", () => {
    store.addSpans([makeSpan()]);
    const resp = dispatcher.dispatch(rpc("tools/call", { name: "observer_traces_overview", arguments: {} }));
    const result = resp!.result as { content: { text: string }[] };
    const data = JSON.parse(result.content[0]!.text);
    expect(Array.isArray(data)).toBe(true);
    expect(data.length).toBe(1);
    expect(data[0].traceId).toBe("abc123");
  });

  test("observer_traces_overview with filters", () => {
    store.addSpans([
      makeSpan({ traceId: "t1", resource: { serviceName: "svc-a", attributes: {} } }),
      makeSpan({ traceId: "t2", resource: { serviceName: "svc-b", attributes: {} } }),
    ]);
    const resp = dispatcher.dispatch(rpc("tools/call", {
      name: "observer_traces_overview",
      arguments: { serviceName: "svc-a" },
    }));
    const result = resp!.result as { content: { text: string }[] };
    const data = JSON.parse(result.content[0]!.text);
    expect(data.length).toBe(1);
  });

  test("observer_traces_overview with empty store", () => {
    const resp = dispatcher.dispatch(rpc("tools/call", { name: "observer_traces_overview", arguments: {} }));
    const result = resp!.result as { content: { text: string }[] };
    const data = JSON.parse(result.content[0]!.text);
    expect(data).toEqual([]);
  });

  // --- observer_trace_detail ---

  test("observer_trace_detail returns trace", () => {
    store.addSpans([makeSpan({ traceId: "abc123" })]);
    const resp = dispatcher.dispatch(rpc("tools/call", { name: "observer_trace_detail", arguments: { traceId: "abc123" } }));
    const result = resp!.result as { content: { text: string }[] };
    const data = JSON.parse(result.content[0]!.text);
    expect(data.traceId).toBe("abc123");
    expect(data.spans).toBeDefined();
  });

  test("observer_trace_detail returns error for missing trace", () => {
    const resp = dispatcher.dispatch(rpc("tools/call", { name: "observer_trace_detail", arguments: { traceId: "nonexistent" } }));
    const result = resp!.result as { content: { text: string }[]; isError: boolean };
    expect(result.isError).toBe(true);
    expect(result.content[0]!.text).toContain("No trace found");
  });

  test("observer_trace_detail returns error when traceId missing", () => {
    const resp = dispatcher.dispatch(rpc("tools/call", { name: "observer_trace_detail", arguments: {} }));
    const result = resp!.result as { content: { text: string }[]; isError: boolean };
    expect(result.isError).toBe(true);
    expect(result.content[0]!.text).toContain("traceId is required");
  });

  // --- observer_metrics_overview ---

  test("observer_metrics_overview returns metrics", () => {
    store.addMetrics([makeMetric()]);
    const resp = dispatcher.dispatch(rpc("tools/call", { name: "observer_metrics_overview", arguments: {} }));
    const result = resp!.result as { content: { text: string }[] };
    const data = JSON.parse(result.content[0]!.text);
    expect(data.length).toBe(1);
    expect(data[0].name).toBe("cpu.usage");
  });

  // --- observer_metric_detail ---

  test("observer_metric_detail returns single metric", () => {
    store.addMetrics([makeMetric({ name: "cpu.usage" })]);
    const resp = dispatcher.dispatch(rpc("tools/call", { name: "observer_metric_detail", arguments: { metricName: "cpu.usage" } }));
    const result = resp!.result as { content: { text: string }[] };
    const data = JSON.parse(result.content[0]!.text);
    expect(data.name).toBe("cpu.usage");
  });

  test("observer_metric_detail returns error for missing metric", () => {
    const resp = dispatcher.dispatch(rpc("tools/call", { name: "observer_metric_detail", arguments: { metricName: "nonexistent" } }));
    const result = resp!.result as { content: { text: string }[]; isError: boolean };
    expect(result.isError).toBe(true);
    expect(result.content[0]!.text).toContain("No metric found");
  });

  test("observer_metric_detail returns error when metricName missing", () => {
    const resp = dispatcher.dispatch(rpc("tools/call", { name: "observer_metric_detail", arguments: {} }));
    const result = resp!.result as { content: { text: string }[]; isError: boolean };
    expect(result.isError).toBe(true);
    expect(result.content[0]!.text).toContain("metricName is required");
  });

  // --- observer_clear ---

  test("observer_clear clears the store", () => {
    store.addSpans([makeSpan()]);
    store.addMetrics([makeMetric()]);
    expect(store.getSpans().length).toBe(1);
    expect(store.getMetrics().length).toBe(1);

    const resp = dispatcher.dispatch(rpc("tools/call", { name: "observer_clear", arguments: {} }));
    const result = resp!.result as { content: { text: string }[] };
    expect(result.content[0]!.text).toBe("All telemetry data cleared.");
    expect(store.getSpans().length).toBe(0);
    expect(store.getMetrics().length).toBe(0);
  });

  // --- Unknown tool ---

  test("unknown tool returns error", () => {
    const resp = dispatcher.dispatch(rpc("tools/call", { name: "unknown_tool", arguments: {} }));
    expect(resp!.error).toBeDefined();
    expect(resp!.error!.code).toBe(-32602);
  });
});
