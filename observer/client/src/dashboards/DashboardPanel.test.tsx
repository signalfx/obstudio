// @vitest-environment happy-dom

import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { DashboardPanel } from "./DashboardPanel";
import { makePanel } from "./testFixtures";

afterEach(cleanup);

describe("DashboardPanel", () => {
  it("renders an SVG chart for a matched time-series panel", () => {
    const { container } = render(<DashboardPanel panel={makePanel()} />);
    // The shared TimeSeriesChart draws a <path> when series have points.
    expect(container.querySelector("svg")).toBeTruthy();
    expect(container.querySelector("path")).toBeTruthy();
    expect(screen.getByText("P99 Latency")).toBeTruthy();
  });

  it("shows an honest empty card naming the metric + filter chips when unmatched", () => {
    const panel = makePanel({
      matched: false,
      metrics: [],
      query: { metricName: "http.server.request.duration", filters: { "service.name": "checkout" } },
    });
    render(<DashboardPanel panel={panel} />);

    expect(screen.getByText(/No local series matches/i)).toBeTruthy();
    expect(screen.getByText("http.server.request.duration")).toBeTruthy();
    expect(screen.getByText("service.name=checkout")).toBeTruthy();
    expect(screen.getByText(/emit it to localhost:4318/i)).toBeTruthy();
  });

  it("shows a distinct parse-error card", () => {
    const panel = makePanel({
      matched: false,
      metrics: [],
      query: { parseError: "no data('<metric>') call found in program_text" },
    });
    render(<DashboardPanel panel={panel} />);

    expect(screen.getByText(/Couldn't parse SignalFlow/i)).toBeTruthy();
    expect(screen.getByText(/no data/i)).toBeTruthy();
  });

  it("passes markdown through for a text panel", () => {
    const panel = makePanel({
      chartType: "text",
      text: "## Runbook notes",
      query: undefined,
      metrics: [],
      matched: false,
    });
    render(<DashboardPanel panel={panel} />);

    expect(screen.getByText("## Runbook notes")).toBeTruthy();
  });

  it("renders the latest value for a single_value panel", () => {
    const panel = makePanel({ chartType: "single_value" });
    const { container } = render(<DashboardPanel panel={panel} />);

    const number = container.querySelector(".dashboard-panel__single-value-number");
    expect(number).toBeTruthy();
    // Latest of the two seeded points (10, 20) is 20.
    expect(number?.textContent).toBe("20");
  });

  it("renders the chart type chip in the panel head", () => {
    const { container } = render(<DashboardPanel panel={makePanel()} />);
    expect(container.querySelector(".dashboard-panel__type")?.textContent).toBe("Time series");
  });
});
