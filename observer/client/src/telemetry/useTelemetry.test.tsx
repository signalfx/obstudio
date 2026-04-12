// @vitest-environment happy-dom

import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { useTelemetry } from "./useTelemetry";

class MockWebSocket {
  static OPEN = 1;
  static CLOSED = 3;
  static instances: MockWebSocket[] = [];

  readyState = MockWebSocket.OPEN;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(_url: string) {
    MockWebSocket.instances.push(this);
    queueMicrotask(() => {
      this.onopen?.();
    });
  }

  send(): void {}

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
  }
}

function Harness(): React.ReactElement {
  const { state, pause, paused, hasNewUpdates } = useTelemetry();
  return (
    <>
      <button type="button" onClick={pause}>pause</button>
      <output data-testid="snapshot">
        {JSON.stringify({
          traces: state.traces.length,
          metrics: state.metrics.length,
          logs: state.logs.length,
          traceCount: state.stats?.traceCount ?? -1,
          validationFindings: state.validation?.findings.length ?? -1,
          validationIssueServiceName: state.validation?.issues[0]?.serviceName ?? "none",
          validationStatus: state.validation?.summary.status ?? "none",
          paused,
          hasNewUpdates,
        })}
      </output>
    </>
  );
}

describe("useTelemetry", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.endsWith("/api/query/traces")) {
        return new Response(JSON.stringify([{ traceId: "trace-1", rootSpanName: "GET /orders", spanCount: 2, status: "ok" }]), { status: 200 });
      }
      if (url.endsWith("/api/query/metrics")) {
        return new Response(JSON.stringify([{ name: "http.server.duration", type: "histogram", dataPointCount: 1 }]), { status: 200 });
      }
      if (url.endsWith("/api/query/logs")) {
        return new Response(JSON.stringify([{ id: "log-1", timeUnixNano: "1", body: "hello", attributes: {}, resource: { attributes: {} }, scope: { name: "demo" } }]), { status: 200 });
      }
      if (url.endsWith("/api/query/stats")) {
        return new Response(JSON.stringify({ spanCount: 2, dataPointCount: 1, metricNameCount: 1, logCount: 1, traceCount: 1, serviceNames: ["checkout"] }), { status: 200 });
      }
      if (url.endsWith("/api/query/validation/summary")) {
        return new Response(JSON.stringify({
          enabled: true,
          ready: true,
          status: "ready",
          hasResult: true,
          stale: false,
          needsRun: false,
          totalEntities: 1,
          totalAdvisories: 1,
          noAdviceCount: 0,
          severityCounts: { violation: 1, improvement: 0, information: 0 },
          highestSeverityCounts: { violation: 1, improvement: 0, information: 0 },
          signalCounts: { span: 1 },
          updatedAt: "2026-04-10T00:00:00Z",
        }), { status: 200 });
      }
      if (url.endsWith("/api/query/validation/latest")) {
        return new Response(JSON.stringify({
          summary: {
            enabled: true,
            ready: true,
            status: "ready",
            hasResult: true,
            stale: false,
            needsRun: false,
            totalEntities: 1,
            totalAdvisories: 1,
            noAdviceCount: 0,
            severityCounts: { violation: 1, improvement: 0, information: 0 },
            highestSeverityCounts: { violation: 1, improvement: 0, information: 0 },
            signalCounts: { span: 1 },
            updatedAt: "2026-04-10T00:00:00Z",
          },
          findings: [{
            entityKey: "span:trace-1:span-1",
            source: "weaver",
            ruleId: "missing_http_method",
            severity: "violation",
            message: "missing http.method",
            signal: { type: "span", serviceName: "checkout", traceId: "trace-1", spanId: "span-1", spanName: "GET /orders" },
            updatedAt: "2026-04-10T00:00:00Z",
          }],
          issues: [{
            key: "span:checkout:missing_http_method:GET /orders",
            severity: "violation",
            message: "missing http.method",
            signalType: "span",
            targetLabel: "GET /orders",
            count: 1,
            affectedEntityCount: 1,
            firstSeen: "2026-04-10T00:00:00Z",
            lastSeen: "2026-04-10T00:00:00Z",
            findings: [{
              entityKey: "span:trace-1:span-1",
              source: "weaver",
              ruleId: "missing_http_method",
              severity: "violation",
              message: "missing http.method",
              signal: { type: "span", serviceName: "checkout", traceId: "trace-1", spanId: "span-1", spanName: "GET /orders" },
              updatedAt: "2026-04-10T00:00:00Z",
            }],
          }],
        }), { status: 200 });
      }
      throw new Error(`unexpected fetch: ${url}`);
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("hydrates the initial telemetry snapshot from REST before websocket updates arrive", async () => {
    render(<Harness />);

    await waitFor(() => {
      expect(screen.getByTestId("snapshot").textContent).toContain('"traces":1');
      expect(screen.getByTestId("snapshot").textContent).toContain('"metrics":1');
      expect(screen.getByTestId("snapshot").textContent).toContain('"logs":1');
      expect(screen.getByTestId("snapshot").textContent).toContain('"traceCount":1');
      expect(screen.getByTestId("snapshot").textContent).toContain('"validationFindings":1');
      expect(screen.getByTestId("snapshot").textContent).toContain('"validationIssueServiceName":""');
      expect(screen.getByTestId("snapshot").textContent).toContain('"validationStatus":"ready"');
    });
  });

  it("keeps validation live while buffering telemetry updates during pause", async () => {
    render(<Harness />);

    await waitFor(() => {
      expect(screen.getByTestId("snapshot").textContent).toContain('"paused":false');
    });

    screen.getByRole("button", { name: "pause" }).click();

    await waitFor(() => {
      expect(screen.getByTestId("snapshot").textContent).toContain('"paused":true');
    });

    const ws = MockWebSocket.instances.at(-1);
    expect(ws).toBeTruthy();

    ws?.onmessage?.({
      data: JSON.stringify({
        type: "update",
        signal: "validation",
        data: {
          summary: {
            enabled: true,
            ready: false,
            status: "running",
            hasResult: true,
            stale: false,
            needsRun: false,
            totalEntities: 1,
            totalAdvisories: 1,
            noAdviceCount: 0,
            severityCounts: { violation: 1, improvement: 0, information: 0 },
            highestSeverityCounts: { violation: 1, improvement: 0, information: 0 },
            signalCounts: { span: 1 },
            updatedAt: "2026-04-10T00:00:01Z",
          },
          findings: [],
          issues: [],
        },
      }),
    });

    await waitFor(() => {
      expect(screen.getByTestId("snapshot").textContent).toContain('"validationStatus":"running"');
      expect(screen.getByTestId("snapshot").textContent).toContain('"hasNewUpdates":false');
    });

    ws?.onmessage?.({
      data: JSON.stringify({
        type: "update",
        signal: "metrics",
        data: [
          { name: "http.server.duration", type: "histogram", dataPointCount: 1 },
          { name: "http.server.request.count", type: "counter", dataPointCount: 2 },
        ],
      }),
    });

    await waitFor(() => {
      expect(screen.getByTestId("snapshot").textContent).toContain('"metrics":1');
      expect(screen.getByTestId("snapshot").textContent).toContain('"hasNewUpdates":true');
    });
  });
});
