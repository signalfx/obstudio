// @vitest-environment happy-dom

import React from "react";
import { readFileSync } from "fs";
import { resolve } from "path";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MetricGroup, SplunkExportStatus, TraceDetail, TraceSummary, ValidationFinding, ValidationSummary } from "./api/types";
import { AppView } from "./AppView";
import type { TelemetryHandle } from "./telemetry";
import { buildValidationIssues } from "./validation/utils";

vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 36,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index,
        key: index,
        start: index * 36,
        end: (index + 1) * 36,
        size: 36,
      })),
    measureElement: () => undefined,
  }),
}));

function makeFinding(overrides: Partial<ValidationFinding>): ValidationFinding {
  return {
    entityKey: "span:trace-1:span-1",
    source: "weaver",
    ruleId: "missing_http_method",
    severity: "violation",
    message: "missing http.method",
    signal: {
      type: "span",
      serviceName: "checkout",
      traceId: "trace-1",
      spanId: "span-1",
      spanName: "GET /orders",
    },
    updatedAt: "2026-04-09T00:00:00Z",
    ...overrides,
  };
}

function makeSummary(): ValidationSummary {
  return {
    enabled: true,
    ready: true,
    status: "ready",
    message: "Weaver validator connected",
    hasResult: true,
    stale: false,
    needsRun: false,
    totalEntities: 3,
    totalAdvisories: 3,
    noAdviceCount: 0,
    severityCounts: { violation: 3, improvement: 0, information: 0 },
    highestSeverityCounts: { violation: 3, improvement: 0, information: 0 },
    signalCounts: { span: 3 },
    updatedAt: "2026-04-09T00:01:00Z",
  };
}

function makeTelemetryHandle(findings: ValidationFinding[]): TelemetryHandle {
  return {
    state: {
      error: null,
      traces: [],
      metrics: [],
      logs: [],
      stats: {
        spanCount: 12,
        dataPointCount: 8,
        metricNameCount: 3,
        logCount: 5,
        traceCount: 2,
        serviceNames: ["checkout"],
      },
      validation: {
        summary: makeSummary(),
        findings,
        issues: buildValidationIssues(findings),
      },
    },
    paused: false,
    hasNewUpdates: false,
    pause: vi.fn(),
    resume: vi.fn(),
    toggle: vi.fn(),
    flush: vi.fn(),
  };
}

function makeMetric(name: string): MetricGroup {
  return {
    name,
    description: `${name} description`,
    unit: "ms",
    type: "gauge",
    serviceName: "checkout",
    scopeName: "otel",
    dataPointCount: 1,
    dataPoints: [],
  };
}

function makeTraceSummary(): TraceSummary {
  return {
    traceId: "trace-1",
    rootSpanName: "GET /orders",
    serviceName: "checkout",
    spanCount: 1,
    durationMs: 12.3,
    status: "ok",
  };
}

function makeTraceDetail(): TraceDetail {
  return {
    traceId: "trace-1",
    rootSpanName: "GET /orders",
    serviceName: "checkout",
    spanCount: 1,
    durationMs: 12.3,
    status: "ok",
    spans: [
      {
        traceId: "trace-1",
        spanId: "span-1",
        name: "GET /orders",
        kind: "SERVER",
        startTimeUnixNano: "2026-04-09T00:00:00Z",
        endTimeUnixNano: "2026-04-09T00:00:00.012Z",
        durationMs: 12.3,
        status: { code: "OK", message: "" },
        attributes: {},
        events: [],
        links: [],
        resource: { serviceName: "checkout", attributes: {} },
        scope: { name: "otel", version: "1.0.0" },
      },
    ],
  };
}

function makeCloudStatus(options: { connected?: boolean; enabled?: boolean } = {}): SplunkExportStatus {
  const connected = options.connected ?? true;
  const enabled = connected && (options.enabled ?? false);
  return {
    metrics: {
      accessTokenConfigured: connected,
      configured: enabled,
      enabled,
      endpoints: enabled ? ["https://ingest.lab0.signalfx.com/v2/datapoint/otlp"] : undefined,
      realm: connected ? "lab0" : undefined,
    },
    traces: {
      accessTokenConfigured: connected,
      configured: enabled,
      enabled,
      endpoints: enabled ? ["https://ingest.lab0.signalfx.com/v2/trace/otlp"] : undefined,
      realm: connected ? "lab0" : undefined,
    },
  };
}

function jsonResponse(body: unknown, options: { ok?: boolean; status?: number; statusText?: string } = {}) {
  return {
    ok: options.ok ?? true,
    status: options.status ?? 200,
    statusText: options.statusText ?? "OK",
    json: async () => body,
  };
}

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, "clientHeight", {
    configurable: true,
    value: 400,
  });
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    value: 1200,
  });
  HTMLElement.prototype.getBoundingClientRect = () =>
    ({
      width: 1200,
      height: 400,
      top: 0,
      left: 0,
      right: 1200,
      bottom: 400,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    }) as DOMRect;
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.history.replaceState({}, "", "/");
});

describe("AppView validation tab", () => {
  it("supports opening directly to the validation tab from the location query", () => {
    window.history.replaceState({}, "", "/?tab=validation");
    const telemetry = makeTelemetryHandle([makeFinding({})]);

    const { container } = render(<AppView telemetry={telemetry} />);

    expect(screen.getByRole("tab", { name: /validation/i }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getAllByText("Validation").length).toBeGreaterThan(0);
  });

  it("supports opening directly to the cloud tab from the location query", async () => {
    window.history.replaceState({}, "", "/?tab=cloud");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        metrics: {
          accessTokenConfigured: true,
          configured: true,
          enabled: true,
          endpoints: ["https://ingest.lab0.signalfx.com/v2/datapoint/otlp"],
          realm: "lab0",
        },
        traces: {
          accessTokenConfigured: true,
          configured: true,
          enabled: true,
          endpoints: ["https://ingest.lab0.signalfx.com/v2/trace/otlp"],
          realm: "lab0",
        },
      }),
    }));
    const telemetry = makeTelemetryHandle([]);

    render(<AppView telemetry={telemetry} />);

    expect(screen.getByRole("tab", { name: /cloud/i }).getAttribute("aria-selected")).toBe("true");
    await waitFor(() => {
      expect(screen.getByText("Splunk Observability Cloud")).toBeTruthy();
    });
    expect(screen.getByText("lab0 realm / token in secure storage")).toBeTruthy();
    expect(screen.getByText("https://ingest.lab0.signalfx.com/v2/datapoint/otlp")).toBeTruthy();
    expect(screen.getByText("https://ingest.lab0.signalfx.com/v2/trace/otlp")).toBeTruthy();
  });

  it("keeps the cloud export switch enabled when a token is stored and export is off", async () => {
    window.history.replaceState({}, "", "/?tab=cloud");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        metrics: {
          accessTokenConfigured: true,
          configured: false,
          enabled: false,
          realm: "lab0",
        },
        traces: {
          accessTokenConfigured: true,
          configured: false,
          enabled: false,
          realm: "lab0",
        },
      }),
    }));
    const telemetry = makeTelemetryHandle([]);

    render(<AppView telemetry={telemetry} />);

    await waitFor(() => {
      expect(screen.getByText("Splunk Observability Cloud")).toBeTruthy();
    });
    const switchButton = screen.getByRole("switch", { name: "Cloud export" });
    expect(switchButton.getAttribute("disabled")).toBeNull();
    expect(switchButton.getAttribute("aria-checked")).toBe("false");
    expect(screen.getByText("lab0 realm / token in secure storage")).toBeTruthy();
  });

  it("keeps the cloud export switch disabled for partially configured exporters", async () => {
    window.history.replaceState({}, "", "/?tab=cloud");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        metrics: {
          accessTokenConfigured: true,
          configured: true,
          enabled: false,
          realm: "lab0",
        },
        traces: {
          accessTokenConfigured: false,
          configured: false,
          enabled: false,
          realm: "lab0",
        },
      }),
    }));
    const telemetry = makeTelemetryHandle([]);

    render(<AppView telemetry={telemetry} />);

    await waitFor(() => {
      expect(screen.getByText("Local telemetry")).toBeTruthy();
    });
    const switchButton = screen.getByRole("switch", { name: "Cloud export" });
    expect(switchButton.getAttribute("disabled")).toBe("");
    expect(screen.getByText("Setup incomplete")).toBeTruthy();
  });

  it("enables and disables remote export while preserving local storage", async () => {
    window.history.replaceState({}, "", "/?tab=cloud");
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(makeCloudStatus()))
      .mockResolvedValueOnce(jsonResponse(makeCloudStatus({ enabled: true })))
      .mockResolvedValueOnce(jsonResponse(makeCloudStatus()));
    vi.stubGlobal("fetch", fetchMock);

    render(<AppView telemetry={makeTelemetryHandle([])} />);

    const exportSwitch = await screen.findByRole("switch", { name: "Cloud export" });
    expect(exportSwitch.getAttribute("aria-checked")).toBe("false");
    fireEvent.click(exportSwitch);
    await waitFor(() => expect(exportSwitch.getAttribute("aria-checked")).toBe("true"));
    expect(screen.getByText("Telemetry is retained locally and forwarded to lab0.")).toBeTruthy();
    expect(screen.getByText("Local collection always on")).toBeTruthy();

    fireEvent.click(exportSwitch);
    await waitFor(() => expect(exportSwitch.getAttribute("aria-checked")).toBe("false"));
    expect(screen.getByText("Remote export is off")).toBeTruthy();

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/splunk/export/enabled");
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      body: JSON.stringify({ enabled: true }),
      method: "POST",
    });
    expect(fetchMock.mock.calls[2][1]).toMatchObject({
      body: JSON.stringify({ enabled: false }),
      method: "POST",
    });
  });

  it("opens an accessible forget confirmation and cancels without calling the API", async () => {
    window.history.replaceState({}, "", "/?tab=cloud");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(makeCloudStatus()));
    vi.stubGlobal("fetch", fetchMock);

    render(<AppView telemetry={makeTelemetryHandle([])} />);

    const trigger = await screen.findByRole("button", { name: "Forget key" });
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Forget cloud key?" });
    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    expect(document.activeElement).toBe(cancel);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    fireEvent.click(cancel);
    expect(screen.queryByRole("dialog", { name: "Forget cloud key?" })).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("supports Escape and traps keyboard focus in the forget confirmation", async () => {
    window.history.replaceState({}, "", "/?tab=cloud");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(makeCloudStatus())));

    render(<AppView telemetry={makeTelemetryHandle([])} />);

    const trigger = await screen.findByRole("button", { name: "Forget key" });
    fireEvent.click(trigger);
    let dialog = screen.getByRole("dialog", { name: "Forget cloud key?" });
    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    const confirm = within(dialog).getByRole("button", { name: "Forget key" });

    confirm.focus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(document.activeElement).toBe(cancel);
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Forget cloud key?" })).toBeNull();

    fireEvent.click(trigger);
    dialog = screen.getByRole("dialog", { name: "Forget cloud key?" });
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Forget cloud key?" })).toBeNull();
  });

  it("forgets the cloud key only after explicit confirmation", async () => {
    window.history.replaceState({}, "", "/?tab=cloud");
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(makeCloudStatus()))
      .mockResolvedValueOnce(jsonResponse(makeCloudStatus({ connected: false })));
    vi.stubGlobal("fetch", fetchMock);

    render(<AppView telemetry={makeTelemetryHandle([])} />);

    fireEvent.click(await screen.findByRole("button", { name: "Forget key" }));
    const dialog = screen.getByRole("dialog", { name: "Forget cloud key?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Forget key" }));

    await waitFor(() => expect(screen.getByText("Local telemetry")).toBeTruthy());
    expect(screen.getByText("Destination key forgotten.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Forget key" })).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/splunk/export/forget");
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      headers: { "X-Obstudio-Browser-Action": "forget" },
      method: "POST",
    });
  });

  it("keeps the forget confirmation retryable when the API fails", async () => {
    window.history.replaceState({}, "", "/?tab=cloud");
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(makeCloudStatus()))
      .mockResolvedValueOnce(jsonResponse({}, {
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
      }));
    vi.stubGlobal("fetch", fetchMock);

    render(<AppView telemetry={makeTelemetryHandle([])} />);

    fireEvent.click(await screen.findByRole("button", { name: "Forget key" }));
    let dialog = screen.getByRole("dialog", { name: "Forget cloud key?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Forget key" }));

    await waitFor(() => {
      dialog = screen.getByRole("dialog", { name: "Forget cloud key?" });
      expect(within(dialog).getByRole("alert").textContent).toContain("500 Internal Server Error");
    });
    expect(within(dialog).getByRole("button", { name: "Forget key" }).getAttribute("disabled")).toBeNull();
  });

  it("renders a dedicated Validation tab with compact explorer chrome and issue-based validation counts", () => {
    const telemetry = makeTelemetryHandle([
      makeFinding({}),
      makeFinding({
        entityKey: "span:trace-2:span-2",
        signal: {
          type: "span",
          serviceName: "checkout",
          traceId: "trace-2",
          spanId: "span-2",
          spanName: "GET /orders",
        },
        updatedAt: "2026-04-09T00:01:00Z",
      }),
      makeFinding({
        entityKey: "metric:checkout:http.server.duration",
        ruleId: "missing_metric_unit",
        signal: {
          type: "metric",
          serviceName: "checkout",
          scopeName: "otel",
          metricName: "http.server.duration",
        },
      }),
    ]);

    const { container } = render(<AppView telemetry={telemetry} />);

    const validationTab = screen.getByRole("tab", { name: /validation/i });
    expect(validationTab.querySelector(".validation-badge")).toBeNull();

    fireEvent.click(validationTab);

    expect(screen.getAllByText("Validation").length).toBeGreaterThan(0);
    expect(screen.getByText("1 issue")).toBeTruthy();
    expect(screen.queryByText(/occurrences/i)).toBeNull();
    expect(container.querySelector(".metric-summary")).toBeNull();
    expect(screen.queryByText("Aggregate Validation")).toBeNull();
    expect(screen.queryByText("Group By")).toBeNull();
    expect(screen.queryByText(/^Validator ready/i)).toBeNull();
    expect(screen.queryByText("Open Side Panel")).toBeNull();
    expect(screen.getAllByText("http.server.duration").length).toBeGreaterThan(0);

    const tablist = screen.getByRole("tablist", { name: "Validation signals" });
    fireEvent.click(within(tablist).getByRole("tab", { name: /Spans/ }));
    expect(screen.getAllByText("GET /orders").length).toBeGreaterThan(0);
  });

  it("renders the metrics tab as the default tab", () => {
    const telemetry = makeTelemetryHandle([makeFinding({})]);

    render(<AppView telemetry={telemetry} />);

    expect(screen.getByRole("tab", { name: /metrics/i }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: /services/i }).getAttribute("aria-selected")).toBe("false");
  });

  it("renders tab labels with count badges", () => {
    const telemetry = makeTelemetryHandle([makeFinding({})]);

    const { container } = render(<AppView telemetry={telemetry} />);

    const servicesTab = screen.getByRole("tab", { name: /services/i });
    const metricsTab = screen.getByRole("tab", { name: /metrics/i });
    const tracesTab = screen.getByRole("tab", { name: /traces/i });
    const logsTab = screen.getByRole("tab", { name: /logs/i });
    const validationTab = screen.getByRole("tab", { name: /validation/i });
    const cloudTab = screen.getByRole("tab", { name: /cloud/i });

    expect(servicesTab.textContent).toContain("Services");
    expect(servicesTab.querySelector(".tab-button__count")?.textContent).toBe("1");
    expect(servicesTab.getAttribute("aria-label")).toBe("Services, 1 service");
    expect(metricsTab.textContent).toContain("Metrics");
    expect(metricsTab.querySelector(".tab-button__count")?.textContent).toBe("3");
    expect(metricsTab.getAttribute("aria-label")).toBe("Metrics, 3 metric names");
    expect(tracesTab.textContent).toContain("Traces");
    expect(tracesTab.querySelector(".tab-button__count")?.textContent).toBe("2");
    expect(tracesTab.getAttribute("aria-label")).toBe("Traces, 2 traces");
    expect(logsTab.textContent).toContain("Logs");
    expect(logsTab.querySelector(".tab-button__count")?.textContent).toBe("5");
    expect(logsTab.getAttribute("aria-label")).toBe("Logs, 5 logs");
    expect(validationTab.textContent).toContain("Validation");
    expect(validationTab.querySelector(".tab-button__count")?.textContent).toBe("1");
    expect(validationTab.getAttribute("aria-label")).toBe("Validation, 1 issue");
    expect(cloudTab.textContent).toContain("Cloud");
    expect(cloudTab.querySelector(".tab-button__count")).toBeNull();
    expect(container.querySelector(".tab-button__glyph")).toBeNull();
  });

  it("does not auto-pause when interacting with the signal tabs", () => {
    const telemetry = makeTelemetryHandle([makeFinding({})]);
    telemetry.state.metrics = [makeMetric("alpha.metric")];

    render(<AppView telemetry={telemetry} />);

    fireEvent.click(screen.getByRole("tab", { name: /metrics/i }));
    fireEvent.click(screen.getByRole("button", { name: /alpha\.metric/i }));

    expect(telemetry.pause).not.toHaveBeenCalled();
  });

  it("renders tab-bar actions (live toggle and help) in the tab bar row", () => {
    const telemetry = makeTelemetryHandle([]);
    const { container } = render(<AppView telemetry={telemetry} />);
    expect(container.querySelector(".tab-bar__actions")).toBeTruthy();
    expect(container.querySelector(".tab-bar__tabs")).toBeTruthy();
  });

  it("keyboard help lists shortcuts that match AppView key bindings", () => {
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    fireEvent.click(screen.getByRole("button", { name: "Keyboard shortcuts" }));
    const dialog = screen.getByRole("dialog", { name: "Keyboard Shortcuts" });

    const keys = Array.from(dialog.querySelectorAll(".keyboard-help__key")).map((el) => el.textContent);
    const descs = Array.from(dialog.querySelectorAll(".keyboard-help__desc")).map((el) => el.textContent);
    const helpMap = Object.fromEntries(keys.map((k, i) => [k, descs[i]]));

    expect(helpMap["4"]).toMatch(/services/i);
    expect(helpMap["5"]).toMatch(/validation/i);
    expect(helpMap["6"]).toMatch(/cloud/i);
    expect(helpMap["1"]).toMatch(/metrics/i);
    expect(helpMap["2"]).toMatch(/traces/i);
    expect(helpMap["3"]).toMatch(/logs/i);
  });

  it("closes keyboard help without clearing the selected trace", async () => {
    window.history.replaceState({}, "", "/?tab=traces");
    const telemetry = makeTelemetryHandle([]);
    telemetry.state.traces = [makeTraceSummary()];

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => makeTraceDetail(),
    }));

    const { container } = render(<AppView telemetry={telemetry} />);

    fireEvent.click(screen.getByRole("button", { name: /get \/orders/i }));

    await waitFor(() => {
      expect(container.querySelector(".detail-panel__title")?.textContent).toBe("GET /orders");
    });

    fireEvent.click(screen.getByRole("button", { name: "Keyboard shortcuts" }));
    expect(screen.getByRole("dialog", { name: "Keyboard Shortcuts" })).toBeTruthy();

    act(() => {
      fireEvent.keyDown(window, { key: "Escape" });
    });

    expect(screen.queryByRole("dialog", { name: "Keyboard Shortcuts" })).toBeNull();
    expect(container.querySelector(".detail-panel__title")?.textContent).toBe("GET /orders");
  });
});
