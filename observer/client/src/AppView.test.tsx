// @vitest-environment happy-dom

import React from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ValidationFinding, ValidationSummary } from "./api/types";
import { AppView } from "./AppView";
import type { TelemetryHandle } from "./telemetry";
import { buildValidationIssues } from "./validation/utils";

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

afterEach(() => {
  cleanup();
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
    expect(screen.getByText("Services")).toBeTruthy();
    expect(screen.queryByText(/occurrences/i)).toBeNull();
    expect(container.querySelector(".metric-summary")).toBeTruthy();
    expect(screen.queryByText("Aggregate Validation")).toBeNull();
    expect(screen.queryByText("Group By")).toBeNull();
    expect(screen.queryByText(/^Validator ready/i)).toBeNull();
    expect(screen.queryByText("Open Side Panel")).toBeNull();
    expect(screen.getAllByText("http.server.duration").length).toBeGreaterThan(0);

    const tablist = screen.getByRole("tablist", { name: "Validation signals" });
    fireEvent.click(within(tablist).getByRole("tab", { name: /^Spans/ }));
    expect(screen.getAllByText("GET /orders").length).toBeGreaterThan(0);
  });

  it("renders summary cards on non-validation tabs", () => {
    const telemetry = makeTelemetryHandle([makeFinding({})]);

    const { container } = render(<AppView telemetry={telemetry} />);

    expect(screen.getByRole("tab", { name: /metrics/i }).getAttribute("aria-selected")).toBe("true");
    expect(container.querySelector(".metric-summary")).toBeTruthy();
    expect(screen.getByText("Services")).toBeTruthy();
  });

  it("renders tab labels with count badges", () => {
    const telemetry = makeTelemetryHandle([makeFinding({})]);

    const { container } = render(<AppView telemetry={telemetry} />);

    const metricsTab = screen.getByRole("tab", { name: /metrics/i });
    const tracesTab = screen.getByRole("tab", { name: /traces/i });
    const logsTab = screen.getByRole("tab", { name: /logs/i });

    expect(metricsTab.querySelector(".tab-button__count")).toBeTruthy();
    expect(tracesTab.querySelector(".tab-button__count")).toBeTruthy();
    expect(logsTab.querySelector(".tab-button__count")).toBeTruthy();
    expect(container.querySelector(".tab-button__glyph")).toBeNull();
  });

  it("does not pause the stream when switching tabs", () => {
    const telemetry = makeTelemetryHandle([makeFinding({})]);

    render(<AppView telemetry={telemetry} />);

    fireEvent.click(screen.getByRole("tab", { name: /traces/i }));
    fireEvent.click(screen.getByRole("tab", { name: /logs/i }));

    expect(telemetry.pause).not.toHaveBeenCalled();
    expect(telemetry.toggle).not.toHaveBeenCalled();
  });
});
