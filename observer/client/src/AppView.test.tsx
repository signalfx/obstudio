// @vitest-environment happy-dom

import React from "react";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppView } from "./AppView";
import type { TelemetryHandle } from "./telemetry";

function makeTelemetryHandle(): TelemetryHandle {
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
});

describe("AppView", () => {
  it("renders summary cards and the telemetry stream pill", () => {
    const { container } = render(<AppView telemetry={makeTelemetryHandle()} />);
    const summary = container.querySelector(".metric-summary");

    expect(summary).toBeTruthy();
    expect(within(summary as HTMLElement).getByText("Traces")).toBeTruthy();
    expect(within(summary as HTMLElement).getByText("Metrics")).toBeTruthy();
    expect(within(summary as HTMLElement).getByText("Logs")).toBeTruthy();
    expect(within(summary as HTMLElement).getByText("Services")).toBeTruthy();
    expect(screen.getByText("Telemetry stream")).toBeTruthy();
  });

  it("renders plain tab labels without letter badges", () => {
    const { container } = render(<AppView telemetry={makeTelemetryHandle()} />);

    expect(screen.getByRole("tab", { name: "Metrics" }).textContent).toBe("Metrics");
    expect(screen.getByRole("tab", { name: "Traces" }).textContent).toBe("Traces");
    expect(screen.getByRole("tab", { name: "Logs" }).textContent).toBe("Logs");
    expect(container.querySelector(".tab-button__glyph")).toBeNull();
  });
});
