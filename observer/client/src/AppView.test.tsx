// @vitest-environment happy-dom

import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MetricGroup, TraceDetail, TraceSummary, ValidationFinding, ValidationSummary } from "./api/types";
import { AppView } from "./AppView";
import { forwardHostKeyboardEvent, hostKeyboardEventMessageType } from "./hooks/useKeyboardShortcuts";
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

function stubCloudStatusFetch(): void {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => ({
      connected: false,
      enabled: false,
      metrics: { configured: false, enabled: false, exportedBatches: 0, exportedItems: 0, failedBatches: 0 },
      traces: { configured: false, enabled: false, exportedBatches: 0, exportedItems: 0, failedBatches: 0 },
    }),
  }));
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

    const tablist = screen.getByRole("radiogroup", { name: "Validation signals" });
    fireEvent.click(within(tablist).getByRole("radio", { name: /Spans/ }));
    expect(screen.getAllByText("GET /orders").length).toBeGreaterThan(0);
  });

  it("renders the overview tab as the default tab", () => {
    const telemetry = makeTelemetryHandle([makeFinding({})]);

    render(<AppView telemetry={telemetry} />);

    expect(screen.getByRole("tab", { name: /overview/i }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: /metrics/i }).getAttribute("aria-selected")).toBe("false");
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

  it("does not run Studio commands for VS Code modifier shortcuts", () => {
    window.history.replaceState({}, "", "/?tab=services");
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    const vscodeShortcuts = [
      { key: "p", metaKey: true },
      { key: "p", ctrlKey: true },
      { key: "p", metaKey: true, shiftKey: true },
      { key: "1", metaKey: true },
      { key: "c", ctrlKey: true },
      { key: "v", ctrlKey: true },
      { key: "z", metaKey: true },
    ];
    for (const shortcut of vscodeShortcuts) {
      fireEvent.keyDown(window, shortcut);
    }

    expect(telemetry.toggle).not.toHaveBeenCalled();
    expect(screen.getByRole("tab", { name: /services/i }).getAttribute("aria-selected")).toBe("true");
    expect(screen.queryByRole("dialog", { name: "Keyboard Shortcuts" })).toBeNull();
  });

  it("bridges modified keydown and keyup events out of a nested webview", () => {
    const postMessage = vi.fn();
    const parentWindow = { postMessage } as unknown as Window;
    const commands: Array<{
      key: string;
      code: string;
      keyCode: number;
      metaKey?: boolean;
      ctrlKey?: boolean;
      shiftKey?: boolean;
      preventsBrowserDefault: boolean;
    }> = [
      { key: "p", code: "KeyP", keyCode: 80, metaKey: true, preventsBrowserDefault: true },
      { key: "p", code: "KeyP", keyCode: 80, ctrlKey: true, preventsBrowserDefault: true },
      {
        key: "p",
        code: "KeyP",
        keyCode: 80,
        metaKey: true,
        shiftKey: true,
        preventsBrowserDefault: true,
      },
      { key: "1", code: "Digit1", keyCode: 49, metaKey: true, preventsBrowserDefault: false },
      { key: "c", code: "KeyC", keyCode: 67, ctrlKey: true, preventsBrowserDefault: false },
      { key: "v", code: "KeyV", keyCode: 86, ctrlKey: true, preventsBrowserDefault: false },
      { key: "z", code: "KeyZ", keyCode: 90, metaKey: true, preventsBrowserDefault: false },
    ];

    for (const command of commands) {
      const forwardedCodes = new Set<string>();
      const keydown = new KeyboardEvent("keydown", {
        key: command.key,
        code: command.code,
        metaKey: command.metaKey,
        ctrlKey: command.ctrlKey,
        shiftKey: command.shiftKey,
        cancelable: true,
      });
      Object.defineProperty(keydown, "keyCode", { value: command.keyCode });

      expect(forwardHostKeyboardEvent(keydown, forwardedCodes, parentWindow, window)).toBe(true);
      expect(keydown.defaultPrevented).toBe(command.preventsBrowserDefault);
      expect(postMessage).toHaveBeenLastCalledWith({
        type: hostKeyboardEventMessageType,
        event: expect.objectContaining({
          type: "keydown",
          key: command.key,
          code: command.code,
          keyCode: command.keyCode,
          metaKey: Boolean(command.metaKey),
          ctrlKey: Boolean(command.ctrlKey),
          shiftKey: Boolean(command.shiftKey),
        }),
      }, "*");

      const keyup = new KeyboardEvent("keyup", { key: command.key, code: command.code });
      Object.defineProperty(keyup, "keyCode", { value: command.keyCode });
      expect(forwardHostKeyboardEvent(keyup, forwardedCodes, parentWindow, window)).toBe(true);
      expect(postMessage).toHaveBeenLastCalledWith({
        type: hostKeyboardEventMessageType,
        event: expect.objectContaining({ type: "keyup", code: command.code, metaKey: false }),
      }, "*");
      expect(forwardedCodes.size).toBe(0);
    }

    expect(postMessage).toHaveBeenCalledTimes(commands.length * 2);
  });

  it("does not bridge host key events outside an iframe", () => {
    const postMessage = vi.fn();
    const currentWindow = { postMessage } as unknown as Window;
    const forwardedCodes = new Set<string>();
    const keydown = new KeyboardEvent("keydown", { key: "p", code: "KeyP", metaKey: true });

    expect(forwardHostKeyboardEvent(keydown, forwardedCodes, currentWindow, currentWindow)).toBe(false);
    expect(postMessage).not.toHaveBeenCalled();
  });

  it("clears stale shortcut keys when the host modifier is released first", () => {
    const postMessage = vi.fn();
    const parentWindow = { postMessage } as unknown as Window;
    const forwardedCodes = new Set<string>();
    const events = [
      new KeyboardEvent("keydown", { key: "Meta", code: "MetaLeft", metaKey: true }),
      new KeyboardEvent("keydown", { key: "p", code: "KeyP", metaKey: true }),
      new KeyboardEvent("keyup", { key: "Meta", code: "MetaLeft" }),
    ];
    for (const event of events) {
      expect(forwardHostKeyboardEvent(event, forwardedCodes, parentWindow, window)).toBe(true);
    }

    expect(forwardedCodes.size).toBe(0);
    expect(forwardHostKeyboardEvent(
      new KeyboardEvent("keyup", { key: "p", code: "KeyP" }),
      forwardedCodes,
      parentWindow,
      window,
    )).toBe(false);
    expect(postMessage).toHaveBeenCalledTimes(3);
  });

  it("handles the unmodified P shortcut case-insensitively", () => {
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    fireEvent.keyDown(window, { key: "p" });
    fireEvent.keyDown(window, { key: "P" });

    expect(telemetry.toggle).toHaveBeenCalledTimes(2);
  });

  it("keyboard help lists shortcuts that match AppView key bindings", () => {
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    fireEvent.click(screen.getByRole("button", { name: "Keyboard shortcuts" }));
    const dialog = screen.getByRole("dialog", { name: "Keyboard Shortcuts" });

    const keys = Array.from(dialog.querySelectorAll(".keyboard-help__key")).map((el) => el.textContent);
    const descs = Array.from(dialog.querySelectorAll(".keyboard-help__desc")).map((el) => el.textContent);
    const helpMap = Object.fromEntries(keys.map((k, i) => [k, descs[i]]));

    expect(helpMap["1"]).toMatch(/overview/i);
    expect(helpMap["2"]).toMatch(/metrics/i);
    expect(helpMap["3"]).toMatch(/traces/i);
    expect(helpMap["4"]).toMatch(/logs/i);
    expect(helpMap["5"]).toMatch(/services/i);
    expect(helpMap["6"]).toMatch(/validation/i);
    expect(helpMap["7"]).toMatch(/dashboards/i);
    expect(helpMap["8"]).toMatch(/cloud/i);
    expect(helpMap["P"]).toMatch(/pause/i);
  });

  it("switches to the Cloud tab with the 8 shortcut", async () => {
    window.history.replaceState({}, "", "/?tab=metrics");
    stubCloudStatusFetch();
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    fireEvent.keyDown(window, { key: "8" });

    expect(screen.getByRole("tab", { name: /cloud/i }).getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(screen.getByText(/Splunk Observability Cloud/i)).toBeTruthy());
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

    fireEvent.keyDown(window, { key: "Escape", metaKey: true });
    fireEvent.keyDown(window, { key: "Escape", ctrlKey: true });
    fireEvent.keyDown(window, { key: "Escape", altKey: true });

    expect(screen.getByRole("dialog", { name: "Keyboard Shortcuts" })).toBeTruthy();
    expect(container.querySelector(".detail-panel__title")?.textContent).toBe("GET /orders");

    act(() => {
      fireEvent.keyDown(window, { key: "Escape" });
    });

    expect(screen.queryByRole("dialog", { name: "Keyboard Shortcuts" })).toBeNull();
    expect(container.querySelector(".detail-panel__title")?.textContent).toBe("GET /orders");
  });
});

describe("AppView overview tab hand-offs", () => {
  it("switches to the Cloud tab from the Splunk O11y checklist step", async () => {
    stubCloudStatusFetch();
    window.history.replaceState({}, "", "/?tab=overview");
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    fireEvent.click(screen.getByRole("button", { name: /^connect/i }));

    expect(screen.getByRole("tab", { name: /cloud/i }).getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(screen.getByText(/Splunk Observability Cloud/i)).toBeTruthy());
  });
});

describe("AppView cloud connection status chip", () => {
  it("shows Checking connection… immediately when the Cloud tab is active before fetch resolves", () => {
    // Fetch that never resolves — simulates the loading window
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    window.history.replaceState({}, "", "/?tab=cloud");
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    const status = screen.getByRole("status");
    expect(status.textContent).toBe("Checking connection…");
  });

  it("live region is in the DOM before the fetch resolves so announcements are not dropped", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    window.history.replaceState({}, "", "/?tab=cloud");
    const telemetry = makeTelemetryHandle([]);
    const { container } = render(<AppView telemetry={telemetry} />);

    expect(container.querySelector('[aria-live="polite"]')).toBeTruthy();
  });

  it("shows Not connected with muted style when disconnected and unconfigured", async () => {
    stubCloudStatusFetch();
    window.history.replaceState({}, "", "/?tab=cloud");
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Not connected"));
    expect(screen.getByRole("status").className).toContain("stream-toggle--muted");
  });

  it("shows Configured, not connected with paused style when credentials exist but connection is inactive", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({
        connected: false,
        enabled: true,
        metrics: { configured: true, enabled: true, exportedBatches: 0, exportedItems: 0, failedBatches: 0 },
        traces: { configured: false, enabled: false, exportedBatches: 0, exportedItems: 0, failedBatches: 0 },
      }),
    }));
    window.history.replaceState({}, "", "/?tab=cloud");
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Configured, not connected"));
    expect(screen.getByRole("status").className).toContain("stream-toggle--paused");
  });

  it("shows Connected with live style when the connection is active", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({
        connected: true,
        enabled: true,
        metrics: { configured: true, enabled: true, exportedBatches: 5, exportedItems: 100, failedBatches: 0 },
        traces: { configured: true, enabled: true, exportedBatches: 3, exportedItems: 50, failedBatches: 0 },
      }),
    }));
    window.history.replaceState({}, "", "/?tab=cloud");
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Connected"));
    expect(screen.getByRole("status").className).toContain("stream-toggle--live");
  });
});

describe("AppView main tab keyboard navigation", () => {
  it("ArrowRight moves focus and selection to the next tab with roving tabIndex", () => {
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    const tablist = screen.getByRole("tablist", { name: "Observer sections" });
    const overviewTab = screen.getByRole("tab", { name: /overview/i });
    const metricsTab = screen.getByRole("tab", { name: /metrics/i });

    expect(overviewTab.getAttribute("aria-selected")).toBe("true");
    expect(overviewTab.getAttribute("tabindex")).toBe("0");

    fireEvent.keyDown(tablist, { key: "ArrowRight" });

    expect(metricsTab.getAttribute("aria-selected")).toBe("true");
    expect(metricsTab.getAttribute("tabindex")).toBe("0");
    expect(overviewTab.getAttribute("tabindex")).toBe("-1");
    expect(document.activeElement).toBe(metricsTab);
  });

  it("ArrowRight wraps focus from last tab back to first", () => {
    stubCloudStatusFetch();
    window.history.replaceState({}, "", "/?tab=cloud");
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    const tablist = screen.getByRole("tablist", { name: "Observer sections" });
    fireEvent.keyDown(tablist, { key: "ArrowRight" });

    const overviewTab = screen.getByRole("tab", { name: /overview/i });
    expect(overviewTab.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(overviewTab);
  });

  it("ArrowLeft from first tab wraps focus to last", () => {
    stubCloudStatusFetch();
    window.history.replaceState({}, "", "/?tab=overview");
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    const tablist = screen.getByRole("tablist", { name: "Observer sections" });
    fireEvent.keyDown(tablist, { key: "ArrowLeft" });

    const cloudTab = screen.getByRole("tab", { name: /cloud/i });
    expect(cloudTab.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(cloudTab);
  });

  it("End key moves focus to the last tab", () => {
    stubCloudStatusFetch();
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    const tablist = screen.getByRole("tablist", { name: "Observer sections" });
    fireEvent.keyDown(tablist, { key: "End" });

    const cloudTab = screen.getByRole("tab", { name: /cloud/i });
    expect(cloudTab.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(cloudTab);
  });

  it("Home key moves focus to the first tab from any position", () => {
    stubCloudStatusFetch();
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    const tablist = screen.getByRole("tablist", { name: "Observer sections" });
    fireEvent.keyDown(tablist, { key: "End" });
    fireEvent.keyDown(tablist, { key: "Home" });

    const overviewTab = screen.getByRole("tab", { name: /overview/i });
    expect(overviewTab.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(overviewTab);
  });

  it("keyboard navigation mounts the panel content for the newly selected tab", () => {
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    const tablist = screen.getByRole("tablist", { name: "Observer sections" });

    // overview → metrics → traces → logs → services (4 ArrowRights)
    fireEvent.keyDown(tablist, { key: "ArrowRight" });
    fireEvent.keyDown(tablist, { key: "ArrowRight" });
    fireEvent.keyDown(tablist, { key: "ArrowRight" });
    fireEvent.keyDown(tablist, { key: "ArrowRight" });

    const servicesTab = screen.getByRole("tab", { name: /services/i });
    expect(servicesTab.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(servicesTab);
    // ServicesTab column header is rendered synchronously — confirms the panel mounted
    expect(screen.getByRole("button", { name: "Avg Duration" })).toBeTruthy();
  });

  it("active tab aria-controls resolves to a mounted panel; inactive tabs omit aria-controls", () => {
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    const overviewTab = screen.getByRole("tab", { name: /overview/i });
    const controlsId = overviewTab.getAttribute("aria-controls");
    expect(controlsId).toBe("panel-overview");
    // The IDREF must resolve — aria-controls is only set when the panel is mounted
    expect(document.getElementById(controlsId!)).toBeTruthy();

    // Inactive tabs carry no aria-controls to avoid dangling IDREFs
    const tracesTab = screen.getByRole("tab", { name: /traces/i });
    expect(tracesTab.getAttribute("aria-controls")).toBeNull();
    expect(document.getElementById("panel-traces")).toBeNull();
  });
});

describe("AppView KeyboardHelp focus management", () => {
  it("focuses the close button when the dialog opens", () => {
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    const helpButton = screen.getByRole("button", { name: "Keyboard shortcuts" });
    helpButton.focus();
    fireEvent.click(helpButton);

    const dialog = screen.getByRole("dialog", { name: "Keyboard Shortcuts" });
    const closeButton = within(dialog).getByRole("button", { name: "Close" });
    expect(document.activeElement).toBe(closeButton);
  });

  it("returns focus to the help button when the dialog closes via Escape", () => {
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    const helpButton = screen.getByRole("button", { name: "Keyboard shortcuts" });
    helpButton.focus();
    fireEvent.click(helpButton);

    act(() => { fireEvent.keyDown(window, { key: "Escape" }); });

    expect(screen.queryByRole("dialog", { name: "Keyboard Shortcuts" })).toBeNull();
    expect(document.activeElement).toBe(helpButton);
  });

  it("Tab is prevented while the dialog is open — focus stays on the Close button", () => {
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    const helpButton = screen.getByRole("button", { name: "Keyboard shortcuts" });
    helpButton.focus();
    fireEvent.click(helpButton);

    const closeButton = within(screen.getByRole("dialog", { name: "Keyboard Shortcuts" }))
      .getByRole("button", { name: "Close" });
    expect(document.activeElement).toBe(closeButton);

    // fireEvent returns false when the handler called preventDefault()
    expect(fireEvent.keyDown(window, { key: "Tab" })).toBe(false);
    expect(document.activeElement).toBe(closeButton);
  });

  it("Shift+Tab is prevented while the dialog is open — focus stays on the Close button", () => {
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    const helpButton = screen.getByRole("button", { name: "Keyboard shortcuts" });
    helpButton.focus();
    fireEvent.click(helpButton);

    const closeButton = within(screen.getByRole("dialog", { name: "Keyboard Shortcuts" }))
      .getByRole("button", { name: "Close" });
    expect(document.activeElement).toBe(closeButton);

    expect(fireEvent.keyDown(window, { key: "Tab", shiftKey: true })).toBe(false);
    expect(document.activeElement).toBe(closeButton);
  });

  it("full lifecycle: initial focus → Tab containment → close → focus restored to opener", () => {
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    const helpButton = screen.getByRole("button", { name: "Keyboard shortcuts" });
    helpButton.focus();
    fireEvent.click(helpButton);

    const dialog = screen.getByRole("dialog", { name: "Keyboard Shortcuts" });
    const closeButton = within(dialog).getByRole("button", { name: "Close" });
    expect(document.activeElement).toBe(closeButton);

    expect(fireEvent.keyDown(window, { key: "Tab" })).toBe(false);
    expect(document.activeElement).toBe(closeButton);

    expect(fireEvent.keyDown(window, { key: "Tab", shiftKey: true })).toBe(false);
    expect(document.activeElement).toBe(closeButton);

    act(() => { fireEvent.keyDown(window, { key: "Escape" }); });
    expect(screen.queryByRole("dialog", { name: "Keyboard Shortcuts" })).toBeNull();
    expect(document.activeElement).toBe(helpButton);
  });
});

describe("AppView tab-bar responsive layout", () => {
  function makeNarrowTabLayout(): {
    tabsScrollLeft: { value: number };
    patchRects: (tabRightEdge: number, containerWidth: number) => void;
    restore: () => void;
  } {
    // Simulate a clipped tab strip: container is 200px wide, tab extends beyond it
    const tabsScrollLeft = { value: 0 };
    const origGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;
    const origScrollLeftDescriptor = Object.getOwnPropertyDescriptor(Element.prototype, "scrollLeft");

    let tabRightEdge = 0;
    let containerWidth = 200;

    HTMLElement.prototype.getBoundingClientRect = function () {
      if (this.classList?.contains("tab-bar__tabs")) {
        return { left: 0, right: containerWidth, width: containerWidth, top: 0, bottom: 40, height: 40, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
      }
      if ((this as HTMLElement).id?.startsWith("tab-cloud") && tabRightEdge > 0) {
        return { left: tabRightEdge - 60, right: tabRightEdge, width: 60, top: 0, bottom: 40, height: 40, x: tabRightEdge - 60, y: 0, toJSON: () => ({}) } as DOMRect;
      }
      return origGetBoundingClientRect.call(this);
    };

    Object.defineProperty(Element.prototype, "scrollLeft", {
      configurable: true,
      get() { return tabsScrollLeft.value; },
      set(v: number) { tabsScrollLeft.value = v; },
    });

    return {
      tabsScrollLeft,
      patchRects(tabRight: number, contWidth: number) {
        tabRightEdge = tabRight;
        containerWidth = contWidth;
      },
      restore() {
        HTMLElement.prototype.getBoundingClientRect = origGetBoundingClientRect;
        if (origScrollLeftDescriptor) {
          Object.defineProperty(Element.prototype, "scrollLeft", origScrollLeftDescriptor);
        }
      },
    };
  }

  it("scrolls the tabs container right so the active tab is fully visible on mount", () => {
    const { tabsScrollLeft, patchRects, restore } = makeNarrowTabLayout();
    // Cloud tab right edge at 320px, container only 200px wide → needs scrollLeft += 120
    patchRects(320, 200);
    window.history.replaceState({}, "", "/?tab=cloud");
    stubCloudStatusFetch();
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    expect(tabsScrollLeft.value).toBeGreaterThan(0);
    restore();
  });

  it("scrolls the tabs container so the newly selected tab is fully visible after a tab switch", () => {
    const { tabsScrollLeft, patchRects, restore } = makeNarrowTabLayout();
    stubCloudStatusFetch();
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    // Simulate Cloud tab being off to the right after an earlier scroll
    patchRects(320, 200);
    tabsScrollLeft.value = 0;
    fireEvent.click(screen.getByRole("tab", { name: /cloud/i }));

    expect(tabsScrollLeft.value).toBeGreaterThan(0);
    restore();
  });

  it("re-scrolls the active tab into view after a container resize (ResizeObserver path)", () => {
    // Capture the ResizeObserver callback so we can invoke it directly
    let resizeCallback: ResizeObserverCallback | null = null;
    class MockResizeObserver {
      constructor(cb: ResizeObserverCallback) { resizeCallback = cb; }
      observe = vi.fn();
      disconnect = vi.fn();
    }
    vi.stubGlobal("ResizeObserver", MockResizeObserver);
    // Make rAF synchronous so the deferred scroll runs inline in tests
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => { cb(0); return 0; });

    const { tabsScrollLeft, patchRects, restore } = makeNarrowTabLayout();

    // Start with a wide container — Cloud tab is fully visible, no scroll needed
    patchRects(320, 400);
    window.history.replaceState({}, "", "/?tab=cloud");
    stubCloudStatusFetch();
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);
    expect(tabsScrollLeft.value).toBe(0);

    // Simulate container shrink (e.g. viewport resize to 480px)
    patchRects(320, 200);
    tabsScrollLeft.value = 0;

    // Fire the ResizeObserver callback — rAF is synchronous, so adjustment runs immediately
    act(() => {
      resizeCallback?.([{} as ResizeObserverEntry], {} as ResizeObserver);
    });

    expect(tabsScrollLeft.value).toBeGreaterThan(0);

    restore();
    vi.restoreAllMocks();
  });
});

describe("AppView dashboards tab", () => {
  function stubPreviewFetch(): void {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({ available: false, approximate: true, source: "/x", groups: [], message: "Run $splunk-dashboard." }),
    }));
  }

  it("renders a Dashboards tab button and keyboard hint", () => {
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    fireEvent.click(screen.getByRole("button", { name: "Keyboard shortcuts" }));
    const dialog = screen.getByRole("dialog", { name: "Keyboard Shortcuts" });
    const keys = Array.from(dialog.querySelectorAll(".keyboard-help__key")).map((el) => el.textContent);
    const descs = Array.from(dialog.querySelectorAll(".keyboard-help__desc")).map((el) => el.textContent);
    const helpMap = Object.fromEntries(keys.map((k, i) => [k, descs[i]]));
    expect(helpMap["7"]).toMatch(/dashboards/i);
  });

  it("mounts the Dashboards panel when the tab is clicked", async () => {
    stubPreviewFetch();
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    fireEvent.click(screen.getByRole("tab", { name: /dashboards/i }));

    await waitFor(() => expect(screen.getByText(/Approximate · local-data preview/i)).toBeTruthy());
  });

  it("deep-links to the dashboards tab via ?tab=dashboards", async () => {
    window.history.replaceState({}, "", "/?tab=dashboards");
    stubPreviewFetch();
    const telemetry = makeTelemetryHandle([]);
    render(<AppView telemetry={telemetry} />);

    expect(screen.getByRole("tab", { name: /dashboards/i }).getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(screen.getByText(/Approximate · local-data preview/i)).toBeTruthy());
  });
});
